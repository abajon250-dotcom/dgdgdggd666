import hashlib
import hmac
from urllib.parse import parse_qs
import json
from datetime import datetime, timedelta
from typing import List, Dict
from fastapi import FastAPI, Request, Depends, HTTPException, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import uvicorn
import aiofiles

from db import get_pool
from config import ADMIN_IDS, BOT_TOKEN

app = FastAPI(title="eSIM Bot Admin Panel")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------- Вспомогательные функции БД ----------
async def fetch(query: str, *args) -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]

async def execute(query: str, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(query, *args)

# ---------- Статистика для дашборда ----------
async def get_dashboard_stats():
    res = await fetch("""
        SELECT
            (SELECT COUNT(*) FROM users) AS total_users,
            (SELECT COUNT(*) FROM qr_submissions WHERE DATE(submitted_at) = CURRENT_DATE) AS submissions_today,
            (SELECT COALESCE(SUM(earned_amount),0) FROM qr_submissions WHERE status='accepted' AND DATE(submitted_at) = CURRENT_DATE) AS earned_today,
            (SELECT COUNT(*) FROM withdraw_requests WHERE status='pending') AS pending_withdrawals
    """)
    return res[0] if res else {}

async def get_recent_submissions(limit=10):
    return await fetch("SELECT id, user_id, operator, price, phone, status, submitted_at FROM qr_submissions ORDER BY submitted_at DESC LIMIT $1", limit)

async def get_submissions_ratio():
    r = await fetch("""
        SELECT 
            COUNT(CASE WHEN status='accepted' THEN 1 END) as accepted,
            COUNT(CASE WHEN status='rejected' THEN 1 END) as rejected,
            COUNT(CASE WHEN status NOT IN ('accepted','rejected') THEN 1 END) as pending
        FROM qr_submissions
    """)
    if r:
        total = r[0]['accepted'] + r[0]['rejected'] + r[0]['pending']
        if total:
            r[0]['accepted_pct'] = round(r[0]['accepted']/total*100)
            r[0]['rejected_pct'] = round(r[0]['rejected']/total*100)
            r[0]['pending_pct'] = 100 - r[0]['accepted_pct'] - r[0]['rejected_pct']
        else:
            r[0]['accepted_pct'] = r[0]['rejected_pct'] = r[0]['pending_pct'] = 0
        return r[0]
    return {"accepted":0,"rejected":0,"pending":0}

async def get_recent_notifications():
    # Замените на реальные уведомления, если нужно
    return [
        {"text": "Новая заявка от @user123: 2 мин назад", "type": "info"},
        {"text": "Новый тикет от @user456: 5 мин назад", "type": "warning"},
    ]

# ---------- Тикеты ----------
async def get_open_tickets():
    return await fetch("SELECT id, user_id, category, message, created_at FROM tickets WHERE status = 'open' ORDER BY created_at ASC")

async def answer_ticket(ticket_id: int, response: str, admin_id: int):
    ticket = await fetch("SELECT user_id FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return None
    user_id = ticket[0]['user_id']
    await execute("UPDATE tickets SET admin_response = $1, status = 'closed', updated_at = NOW(), closed_at = NOW() WHERE id = $2", response, ticket_id)
    return user_id

# ---------- Чёрный список ----------
async def get_blacklist():
    return await fetch("SELECT phone, created_at FROM blacklist ORDER BY created_at DESC")

async def add_to_blacklist(phone: str, admin_id: int):
    await execute("INSERT INTO blacklist (phone, created_at, admin_id) VALUES ($1, NOW(), $2) ON CONFLICT (phone) DO NOTHING", phone, admin_id)

async def remove_from_blacklist(phone: str):
    await execute("DELETE FROM blacklist WHERE phone = $1", phone)

# ---------- Операторы ----------
async def get_operators():
    return await fetch("SELECT * FROM operators ORDER BY name")

async def update_operator_price(operator: str, price_hold: float, price_bh: float):
    await execute("UPDATE operators SET price_hold = $1, price_bh = $2 WHERE name = $3", price_hold, price_bh, operator)

async def update_operator_slot(operator: str, slot_limit: int):
    await execute("UPDATE operators SET slot_limit = $1 WHERE name = $2", slot_limit, operator)

# ---------- Кастомные тексты ----------
async def get_custom_texts():
    return await fetch("SELECT key, value, updated_at FROM custom_texts")

async def set_custom_text(key: str, value: str):
    await execute("INSERT INTO custom_texts (key, value, updated_at) VALUES ($1, $2, NOW()) ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()", key, value)

# ---------- Работники ----------
async def get_workers():
    return await fetch("SELECT user_id, username, permissions FROM users WHERE role = 'worker'")

async def add_worker(user_id: int, permissions: str = ""):
    from db import add_worker as db_add_worker
    await db_add_worker(user_id, permissions)

async def remove_worker(user_id: int):
    from db import remove_worker as db_remove_worker
    await db_remove_worker(user_id)

# ---------- API-ключи ----------
async def get_api_keys():
    return await fetch("SELECT id, user_id, api_key, permissions, created_at, last_used FROM api_keys ORDER BY created_at DESC")

async def create_api_key(user_id: int, permissions: str):
    import uuid
    api_key = str(uuid.uuid4())
    await execute("INSERT INTO api_keys (user_id, api_key, permissions, created_at) VALUES ($1, $2, $3, NOW())", user_id, api_key, permissions)
    return api_key

async def revoke_api_key(key_id: int):
    await execute("DELETE FROM api_keys WHERE id = $1", key_id)

# ---------- Подписки ----------
async def get_subscriptions():
    return await fetch("SELECT u.user_id, u.username, s.plan, s.status, s.end_date, s.auto_renew FROM users u LEFT JOIN subscriptions s ON u.user_id = s.user_id ORDER BY u.user_id")

async def update_subscription(user_id: int, plan: str, status: str, end_date: str, auto_renew: bool):
    await execute("""
        INSERT INTO subscriptions (user_id, plan, status, end_date, auto_renew)
        VALUES ($1, $2, $3, $4::TIMESTAMP, $5)
        ON CONFLICT (user_id) DO UPDATE SET plan=$2, status=$3, end_date=$4::TIMESTAMP, auto_renew=$5
    """, user_id, plan, status, end_date, auto_renew)

# ---------- Ачивки ----------
async def grant_achievement(user_id: int, achievement: str):
    from db import grant_achievement as db_grant
    await db_grant(user_id, achievement)

async def get_achievements():
    return await fetch("SELECT u.username, a.achievement, a.earned_at FROM achievements a JOIN users u ON a.user_id = u.user_id ORDER BY a.earned_at DESC LIMIT 50")

async def get_ranks():
    return await fetch("SELECT u.username, r.level, r.xp FROM ranks r JOIN users u ON r.user_id = u.user_id ORDER BY r.level DESC LIMIT 20")

# ---------- Аудиториум ----------
async def get_audit_log(limit=200):
    return await fetch("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT $1", limit)

# ---------- Авторизация через Telegram ----------
def verify_telegram_auth(init_data: str) -> bool:
    try:
        params = parse_qs(init_data)
        hash_str = params.get('hash', [''])[0]
        if not hash_str:
            return False
        del params['hash']
        sorted_params = [f"{k}={v[0]}" for k, v in sorted(params.items())]
        data_check_string = "\n".join(sorted_params)
        secret_key = hmac.new(key=b"WebAppData", msg=BOT_TOKEN.encode(), digestmod=hashlib.sha256).digest()
        computed_hash = hmac.new(key=secret_key, msg=data_check_string.encode(), digestmod=hashlib.sha256).hexdigest()
        return computed_hash == hash_str
    except:
        return False

async def get_current_admin(request: Request):
    tid = request.cookies.get("telegram_id")
    if tid is None or int(tid) not in ADMIN_IDS:
        raise HTTPException(status_code=303, detail="Unauthorized", headers={"Location": "/"})
    return int(tid)

# ---------- Маршруты ----------
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "bot_username": "Tetribot7827bot"})

@app.post("/auth")
async def auth(request: Request):
    form = await request.form()
    init_data = form.get("init_data")
    if not init_data or not verify_telegram_auth(init_data):
        raise HTTPException(status_code=403, detail="Invalid auth")
    data = parse_qs(init_data)
    user = json.loads(data['user'][0]) if 'user' in data else {}
    user_id = user.get('id', 0)
    if user_id not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Not admin")
    resp = RedirectResponse(url="/dashboard", status_code=302)
    resp.set_cookie(key="telegram_id", value=str(user_id), httponly=True)
    return resp

@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/")
    resp.delete_cookie("telegram_id")
    return resp

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, admin_id: int = Depends(get_current_admin)):
    stats = await get_dashboard_stats()
    recent = await get_recent_submissions(10)
    ratio = await get_submissions_ratio()
    notif = await get_recent_notifications()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
        "recent_submissions": recent,
        "ratio": ratio,
        "notifications": notif,
        "admin_name": f"Admin {admin_id}"
    })

@app.get("/submissions", response_class=HTMLResponse)
async def submissions_page(request: Request, admin_id: int = Depends(get_current_admin)):
    subs = await fetch("SELECT * FROM qr_submissions ORDER BY submitted_at DESC LIMIT 100")
    return templates.TemplateResponse("submissions.html", {"request": request, "submissions": subs})

@app.post("/submissions/accept")
async def accept_submission(sub_id: int = Form(...), admin_id: int = Depends(get_current_admin)):
    from db import accept_submission_now, get_submission, get_user_qr_last_30_days, calculate_rank
    sub = await get_submission(sub_id)
    if sub and sub['status'] == 'pending':
        qr, _ = await get_user_qr_last_30_days(sub['user_id'])
        _, bonus = calculate_rank(qr)
        earned = sub['price'] + bonus
        await accept_submission_now(sub_id, admin_id, earned)
    return RedirectResponse(url="/submissions", status_code=302)

@app.post("/submissions/reject")
async def reject_submission(sub_id: int = Form(...), admin_id: int = Depends(get_current_admin)):
    from db import reject_submission
    await reject_submission(sub_id, admin_id, 'block')
    return RedirectResponse(url="/submissions", status_code=302)

@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, admin_id: int = Depends(get_current_admin)):
    users = await fetch("SELECT user_id, username, total_earned, earned_today, role FROM users ORDER BY user_id LIMIT 200")
    return templates.TemplateResponse("users.html", {"request": request, "users": users})

@app.post("/users/role")
async def change_user_role(user_id: int = Form(...), role: str = Form(...), admin_id: int = Depends(get_current_admin)):
    from db import set_user_role
    await set_user_role(user_id, role)
    return RedirectResponse(url="/users", status_code=302)

@app.get("/tickets", response_class=HTMLResponse)
async def tickets_page(request: Request, admin_id: int = Depends(get_current_admin)):
    tickets = await get_open_tickets()
    return templates.TemplateResponse("tickets.html", {"request": request, "tickets": tickets})

@app.post("/tickets/answer")
async def answer_ticket_web(ticket_id: int = Form(...), response_text: str = Form(...), admin_id: int = Depends(get_current_admin)):
    user_id = await answer_ticket(ticket_id, response_text, admin_id)
    if user_id:
        # Отправить ответ пользователю через бота (можно через глобальный bot instance)
        pass
    return RedirectResponse(url="/tickets", status_code=302)

@app.get("/operators", response_class=HTMLResponse)
async def operators_page(request: Request, admin_id: int = Depends(get_current_admin)):
    ops = await get_operators()
    return templates.TemplateResponse("operators.html", {"request": request, "operators": ops})

@app.post("/operators/price")
async def update_operator_price_web(operator: str = Form(...), price_hold: float = Form(...), price_bh: float = Form(...), admin_id: int = Depends(get_current_admin)):
    await update_operator_price(operator, price_hold, price_bh)
    return RedirectResponse(url="/operators", status_code=302)

@app.post("/operators/slot")
async def update_operator_slot_web(operator: str = Form(...), slot_limit: int = Form(...), admin_id: int = Depends(get_current_admin)):
    await update_operator_slot(operator, slot_limit)
    return RedirectResponse(url="/operators", status_code=302)

@app.get("/blacklist", response_class=HTMLResponse)
async def blacklist_page(request: Request, admin_id: int = Depends(get_current_admin)):
    items = await get_blacklist()
    return templates.TemplateResponse("blacklist.html", {"request": request, "blacklist": items})

@app.post("/blacklist/add")
async def add_blacklist(phone: str = Form(...), admin_id: int = Depends(get_current_admin)):
    await add_to_blacklist(phone, admin_id)
    return RedirectResponse(url="/blacklist", status_code=302)

@app.post("/blacklist/remove")
async def remove_blacklist(phone: str = Form(...), admin_id: int = Depends(get_current_admin)):
    await remove_from_blacklist(phone)
    return RedirectResponse(url="/blacklist", status_code=302)

@app.get("/broadcast", response_class=HTMLResponse)
async def broadcast_page(request: Request, admin_id: int = Depends(get_current_admin)):
    return templates.TemplateResponse("broadcast.html", {"request": request})

@app.post("/broadcast/send")
async def send_broadcast(message: str = Form(...), target: str = Form("all"), admin_id: int = Depends(get_current_admin)):
    users = await fetch("SELECT user_id FROM users WHERE $1 = 'all' OR role = $1", target)
    # Здесь нужно отправить сообщения – можно вызвать бота
    return RedirectResponse(url="/broadcast", status_code=302)

@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, admin_id: int = Depends(get_current_admin)):
    return templates.TemplateResponse("analytics.html", {"request": request})

@app.get("/api/analytics/daily")
async def analytics_daily(period: str = Query("7d")):
    days = int(period[:-1])
    data = await fetch("""
        SELECT DATE(submitted_at) as date, COUNT(*) as submissions, COALESCE(SUM(earned_amount),0) as revenue
        FROM qr_submissions
        WHERE submitted_at >= NOW() - $1::INTERVAL
        GROUP BY date ORDER BY date
    """, f"{days} days")
    return JSONResponse({"dates": [row['date'].isoformat() for row in data], "submissions": [row['submissions'] for row in data], "revenue": [float(row['revenue']) for row in data]})

@app.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request, admin_id: int = Depends(get_current_admin)):
    return templates.TemplateResponse("stats.html", {"request": request})

@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, admin_id: int = Depends(get_current_admin)):
    return templates.TemplateResponse("reports.html", {"request": request})

@app.get("/reports/generate")
async def generate_report(report_type: str = Query("weekly")):
    # Генерация CSV
    return JSONResponse({"status": "generated"})

@app.get("/achievements", response_class=HTMLResponse)
async def achievements_page(request: Request, admin_id: int = Depends(get_current_admin)):
    achievements = await get_achievements()
    ranks = await get_ranks()
    return templates.TemplateResponse("achievements.html", {"request": request, "achievements": achievements, "ranks": ranks})

@app.post("/achievements/grant")
async def grant_achievement_web(user_id: int = Form(...), achievement: str = Form(...), admin_id: int = Depends(get_current_admin)):
    await grant_achievement(user_id, achievement)
    return RedirectResponse(url="/achievements", status_code=302)

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, admin_id: int = Depends(get_current_admin)):
    texts = await get_custom_texts()
    return templates.TemplateResponse("settings.html", {"request": request, "texts": texts})

@app.post("/settings/text")
async def update_text_web(key: str = Form(...), value: str = Form(...), admin_id: int = Depends(get_current_admin)):
    await set_custom_text(key, value)
    return RedirectResponse(url="/settings", status_code=302)

@app.get("/workers", response_class=HTMLResponse)
async def workers_page(request: Request, admin_id: int = Depends(get_current_admin)):
    workers = await get_workers()
    return templates.TemplateResponse("workers.html", {"request": request, "workers": workers})

@app.post("/workers/add")
async def add_worker_web(user_id: int = Form(...), permissions: str = Form(""), admin_id: int = Depends(get_current_admin)):
    await add_worker(user_id, permissions)
    return RedirectResponse(url="/workers", status_code=302)

@app.post("/workers/remove")
async def remove_worker_web(user_id: int = Form(...), admin_id: int = Depends(get_current_admin)):
    await remove_worker(user_id)
    return RedirectResponse(url="/workers", status_code=302)

@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, admin_id: int = Depends(get_current_admin)):
    content = ""
    try:
        async with aiofiles.open("bot.log", "r") as f:
            content = (await f.read())[-5000:]
    except:
        content = "Лог-файл не найден"
    return templates.TemplateResponse("logs.html", {"request": request, "logs": content})

@app.get("/audit-log", response_class=HTMLResponse)
async def audit_log_page(request: Request, admin_id: int = Depends(get_current_admin)):
    logs = await get_audit_log(200)
    return templates.TemplateResponse("audit_log.html", {"request": request, "logs": logs})

@app.get("/api-keys", response_class=HTMLResponse)
async def api_keys_page(request: Request, admin_id: int = Depends(get_current_admin)):
    keys = await get_api_keys()
    return templates.TemplateResponse("api_keys.html", {"request": request, "api_keys": keys})

@app.post("/api-keys/create")
async def api_key_create_web(user_id: int = Form(...), permissions: str = Form(...), admin_id: int = Depends(get_current_admin)):
    await create_api_key(user_id, permissions)
    return RedirectResponse(url="/api-keys", status_code=302)

@app.post("/api-keys/revoke")
async def api_key_revoke_web(key_id: int = Form(...), admin_id: int = Depends(get_current_admin)):
    await revoke_api_key(key_id)
    return RedirectResponse(url="/api-keys", status_code=302)

@app.get("/subscriptions", response_class=HTMLResponse)
async def subscriptions_page(request: Request, admin_id: int = Depends(get_current_admin)):
    subs = await get_subscriptions()
    return templates.TemplateResponse("subscriptions.html", {"request": request, "subscriptions": subs})

@app.post("/subscriptions/update")
async def subscription_update_web(user_id: int = Form(...), plan: str = Form(...), status: str = Form(...), end_date: str = Form(...), auto_renew: bool = Form(False), admin_id: int = Depends(get_current_admin)):
    await update_subscription(user_id, plan, status, end_date, auto_renew)
    return RedirectResponse(url="/subscriptions", status_code=302)

async def get_active_tickets_count():
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE status = 'open'") or 0

async def get_recent_notifications(limit=5):
    # Здесь можно сделать выборку из audit_log или отдельной таблицы notifications
    # Для примера вернём статические данные, как на скриншоте
    return [
        {"text": "Новая заявка от @user123", "time": "2 мин назад"},
        {"text": "Новый тикет от @user456", "time": "5 мин назад"},
        {"text": "Заявка #1234 принята", "time": "10 мин назад"},
        {"text": "Пользователь @user789 зарегистрирован", "time": "15 мин назад"},
        {"text": "Выплата #5678 завершена", "time": "20 мин назад"},
    ]

# Внутри маршрута /dashboard добавьте:
    active_tickets = await get_active_tickets_count()
    notifications = await get_recent_notifications()
    # Для расчёта роста можно добавить логику сравнения с предыдущим днём
    # Для простоты используем заглушки
    new_users_today = 12
    submissions_growth = 8
    earnings_growth = 15

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)