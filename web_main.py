import hashlib
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from fastapi import FastAPI, Request, Depends, HTTPException, Form, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import uvicorn
import aiofiles

# ========== ПРОВЕРКА НАЛИЧИЯ ОПЦИОНАЛЬНЫХ МОДУЛЕЙ ==========
try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    jwt = None
    JWT_AVAILABLE = False

try:
    import stripe
    from payments import create_payment_intent
    STRIPE_AVAILABLE = True
except ImportError:
    stripe = None
    STRIPE_AVAILABLE = False

from db import get_pool, get_user_by_id, get_user_by_username, get_total_users_count, get_new_users_count
from auth import create_jwt_token, decode_jwt_token, hash_password, verify_password
from roles import require_role
from ws_manager import manager

# ========== ИНИЦИАЛИЗАЦИЯ ==========
app = FastAPI(title="eSIM Bot Admin Panel", version="5.0")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

SECRET_KEY = "your-super-secret-change-this"  # обязательно замените в продакшене (из config.py)
security = HTTPBearer()

# ========== БАЗОВЫЕ ФУНКЦИИ БД ==========
async def fetch(query: str, *args) -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]

async def execute(query: str, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(query, *args)

# ========== АВТОРИЗАЦИЯ (JWT) ==========
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not JWT_AVAILABLE:
        raise HTTPException(status_code=500, detail="JWT authentication not configured")
    token = credentials.credentials
    payload = decode_jwt_token(token)
    user = await get_user_by_id(payload["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

async def get_current_admin(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin rights required")
    return user

# ========== СТРАНИЦА ВХОДА ==========
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@app.post("/auth")
async def auth(request: Request, user_id: int = Form(...)):
    if user_id in ADMIN_IDS:
        resp = RedirectResponse(url="/dashboard", status_code=302)
        resp.set_cookie(key="admin_id", value=str(user_id), httponly=True)
        return resp
    return templates.TemplateResponse("login.html", {"request": request, "error": "Неверный ID"})

@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/")
    resp.delete_cookie("admin_id")
    return resp

async def get_current_user(request: Request):
    admin_id = request.cookies.get("admin_id")
    if not admin_id or int(admin_id) not in ADMIN_IDS:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = await get_user(int(admin_id))
    if not user:
        user = {"user_id": int(admin_id), "role": "admin", "username": "admin"}
    return user

async def get_current_admin(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin rights required")
    return user

# ========== DASHBOARD ==========
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: dict = Depends(get_current_user)):
    stats = await fetch("""
        SELECT
            (SELECT COUNT(*) FROM users) AS total_users,
            (SELECT COUNT(*) FROM qr_submissions WHERE DATE(submitted_at) = CURRENT_DATE) AS submissions_today,
            (SELECT COALESCE(SUM(earned_amount),0) FROM qr_submissions WHERE status='accepted' AND DATE(submitted_at) = CURRENT_DATE) AS earned_today,
            (SELECT COUNT(*) FROM withdraw_requests WHERE status='pending') AS pending_withdrawals,
            (SELECT COUNT(*) FROM tickets WHERE status = 'open') AS active_tickets
    """)
    recent = await fetch("SELECT id, user_id, operator, price, status, submitted_at FROM qr_submissions ORDER BY submitted_at DESC LIMIT 10")
    ratio = await fetch("""
        SELECT 
            COUNT(CASE WHEN status='accepted' THEN 1 END) as accepted,
            COUNT(CASE WHEN status='rejected' THEN 1 END) as rejected,
            COUNT(CASE WHEN status NOT IN ('accepted','rejected') THEN 1 END) as pending
        FROM qr_submissions
    """)
    if ratio:
        total = ratio[0]['accepted'] + ratio[0]['rejected'] + ratio[0]['pending']
        if total:
            ratio[0]['accepted_pct'] = round(ratio[0]['accepted']/total*100)
            ratio[0]['rejected_pct'] = round(ratio[0]['rejected']/total*100)
            ratio[0]['pending_pct'] = 100 - ratio[0]['accepted_pct'] - ratio[0]['rejected_pct']
    notifications = [
        {"text": "Новая заявка зарегистрирована", "time": "только что"},
    ]
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats[0] if stats else {},
        "recent_submissions": recent,
        "ratio": ratio[0] if ratio else {},
        "notifications": notifications,
        "admin_name": user["username"],
        "admin_id": user["user_id"]
    })

# ========== ЗАЯВКИ ==========
@app.get("/submissions", response_class=HTMLResponse)
async def submissions_page(request: Request, user: dict = Depends(get_current_user)):
    subs = await fetch("SELECT * FROM qr_submissions ORDER BY submitted_at DESC LIMIT 100")
    return templates.TemplateResponse("submissions.html", {"request": request, "submissions": subs})

@app.post("/submissions/accept")
async def accept_submission(sub_id: int = Form(...), admin: dict = Depends(get_current_admin)):
    from db import accept_submission_now, get_submission, get_user_qr_last_30_days, calculate_rank
    sub = await get_submission(sub_id)
    if sub and sub['status'] == 'pending':
        qr, _ = await get_user_qr_last_30_days(sub['user_id'])
        _, bonus = calculate_rank(qr)
        earned = sub['price'] + bonus
        await accept_submission_now(sub_id, admin['user_id'], earned)
        await manager.broadcast({"type": "submission_accepted", "submission_id": sub_id})
    return RedirectResponse(url="/submissions", status_code=302)

@app.post("/submissions/reject")
async def reject_submission(sub_id: int = Form(...), admin: dict = Depends(get_current_admin)):
    from db import reject_submission
    await reject_submission(sub_id, admin['user_id'], 'block')
    await manager.broadcast({"type": "submission_rejected", "submission_id": sub_id})
    return RedirectResponse(url="/submissions", status_code=302)

# ========== ПОЛЬЗОВАТЕЛИ ==========
@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, admin: dict = Depends(get_current_admin)):
    users = await fetch("SELECT user_id, username, total_earned, earned_today, role FROM users ORDER BY user_id LIMIT 200")
    return templates.TemplateResponse("users.html", {"request": request, "users": users})

@app.post("/users/role")
async def change_user_role(user_id: int = Form(...), role: str = Form(...), admin: dict = Depends(get_current_admin)):
    from db import set_user_role
    await set_user_role(user_id, role)
    return RedirectResponse(url="/users", status_code=302)

# ========== ТИКЕТЫ ==========
@app.get("/tickets", response_class=HTMLResponse)
async def tickets_page(request: Request, user: dict = Depends(get_current_user)):
    tickets = await fetch("SELECT * FROM tickets WHERE status = 'open' ORDER BY created_at ASC")
    return templates.TemplateResponse("tickets.html", {"request": request, "tickets": tickets})

@app.post("/tickets/answer")
async def answer_ticket(ticket_id: int = Form(...), response_text: str = Form(...), admin: dict = Depends(get_current_admin)):
    ticket = await fetch("SELECT user_id FROM tickets WHERE id = $1", ticket_id)
    if ticket:
        await execute("UPDATE tickets SET admin_response = $1, status = 'closed', updated_at = NOW(), closed_at = NOW() WHERE id = $2", response_text, ticket_id)
        await manager.broadcast({"type": "ticket_closed", "ticket_id": ticket_id})
    return RedirectResponse(url="/tickets", status_code=302)

# ========== ОПЕРАТОРЫ ==========
@app.get("/operators", response_class=HTMLResponse)
async def operators_page(request: Request, user: dict = Depends(get_current_user)):
    ops = await fetch("SELECT * FROM operators ORDER BY sort_order ASC, name ASC")
    return templates.TemplateResponse("operators.html", {"request": request, "operators": ops})

@app.post("/operators/price")
async def update_operator_price(operator: str = Form(...), price_hold: float = Form(...), price_bh: float = Form(...), admin: dict = Depends(get_current_admin)):
    await execute("UPDATE operators SET price_hold = $1, price_bh = $2 WHERE name = $3", price_hold, price_bh, operator)
    return RedirectResponse(url="/operators", status_code=302)

@app.post("/operators/slot")
async def update_operator_slot(operator: str = Form(...), slot_limit: int = Form(...), admin: dict = Depends(get_current_admin)):
    await execute("UPDATE operators SET slot_limit = $1 WHERE name = $2", slot_limit, operator)
    return RedirectResponse(url="/operators", status_code=302)

@app.post("/operators/reorder")
async def reorder_operators(order: List[str] = Form(...), admin: dict = Depends(get_current_admin)):
    for idx, name in enumerate(order):
        await execute("UPDATE operators SET sort_order = $1 WHERE name = $2", idx, name)
    return JSONResponse({"status": "ok"})

# ========== ЧЁРНЫЙ СПИСОК ==========
@app.get("/blacklist", response_class=HTMLResponse)
async def blacklist_page(request: Request, admin: dict = Depends(get_current_admin)):
    items = await fetch("SELECT phone, created_at FROM blacklist ORDER BY created_at DESC")
    return templates.TemplateResponse("blacklist.html", {"request": request, "blacklist": items})

@app.post("/blacklist/add")
async def add_blacklist(phone: str = Form(...), admin: dict = Depends(get_current_admin)):
    await execute("INSERT INTO blacklist (phone, created_at, admin_id) VALUES ($1, NOW(), $2) ON CONFLICT (phone) DO NOTHING", phone, admin['user_id'])
    return RedirectResponse(url="/blacklist", status_code=302)

@app.post("/blacklist/remove")
async def remove_blacklist(phone: str = Form(...), admin: dict = Depends(get_current_admin)):
    await execute("DELETE FROM blacklist WHERE phone = $1", phone)
    return RedirectResponse(url="/blacklist", status_code=302)

# ========== РАССЫЛКА ==========
@app.get("/broadcast", response_class=HTMLResponse)
async def broadcast_page(request: Request, admin: dict = Depends(get_current_admin)):
    return templates.TemplateResponse("broadcast.html", {"request": request})

@app.post("/broadcast/send")
async def send_broadcast(message: str = Form(...), target: str = Form("all"), admin: dict = Depends(get_current_admin)):
    users = await fetch("SELECT user_id FROM users WHERE $1 = 'all' OR role = $1", target)
    for u in users:
        # Здесь вызвать bot.send_message(u['user_id'], message) – подключите вашего бота
        pass
    return RedirectResponse(url="/broadcast", status_code=302)

# ========== АНАЛИТИКА ==========
@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse("analytics.html", {"request": request})

@app.get("/api/analytics/daily")
async def analytics_daily(period: str = Query("7d")):
    if period == "today":
        rows = await fetch("""
            SELECT EXTRACT(HOUR FROM submitted_at) as hour, COUNT(*) as cnt
            FROM qr_submissions WHERE DATE(submitted_at) = CURRENT_DATE
            GROUP BY hour ORDER BY hour
        """)
        labels = [f"{int(r['hour'])}:00" for r in rows]
        data = [r['cnt'] for r in rows]
    else:
        days = int(period[:-1])
        rows = await fetch("""
            SELECT DATE(submitted_at) as date, COUNT(*) as cnt
            FROM qr_submissions WHERE submitted_at >= NOW() - $1::INTERVAL
            GROUP BY date ORDER BY date
        """, f"{days} days")
        labels = [r['date'].isoformat() for r in rows]
        data = [r['cnt'] for r in rows]
    return JSONResponse({"labels": labels, "submissions": data})

@app.get("/api/advanced-stats")
async def advanced_stats(user: dict = Depends(get_current_user)):
    total_users = await fetch("SELECT COUNT(*) as cnt FROM users")
    revenue_today = await fetch("SELECT COALESCE(SUM(earned_amount),0) as sum FROM qr_submissions WHERE status='accepted' AND DATE(submitted_at)=CURRENT_DATE")
    submissions_by_hour = await fetch("""
        SELECT EXTRACT(HOUR FROM submitted_at) as hour, COUNT(*) as cnt
        FROM qr_submissions WHERE DATE(submitted_at)=CURRENT_DATE
        GROUP BY hour ORDER BY hour
    """)
    return {
        "total_users": total_users[0]['cnt'],
        "revenue_today": float(revenue_today[0]['sum']),
        "submissions_by_hour": [{"hour": int(r['hour']), "count": r['cnt']} for r in submissions_by_hour]
    }

# ========== СТАТИСТИКА ==========
@app.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse("stats.html", {"request": request})

# ========== ОТЧЁТЫ ==========
@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse("reports.html", {"request": request})

@app.get("/reports/generate")
async def generate_report(report_type: str = Query("weekly"), user: dict = Depends(get_current_user)):
    # Генерация CSV (заглушка)
    return JSONResponse({"status": "generated"})

# ========== АЧИВКИ ==========
@app.get("/achievements", response_class=HTMLResponse)
async def achievements_page(request: Request, user: dict = Depends(get_current_user)):
    achievements = await fetch("SELECT u.username, a.achievement, a.earned_at FROM achievements a JOIN users u ON a.user_id = u.user_id ORDER BY a.earned_at DESC LIMIT 50")
    ranks = await fetch("SELECT u.username, r.level, r.xp FROM ranks r JOIN users u ON r.user_id = u.user_id ORDER BY r.level DESC LIMIT 20")
    return templates.TemplateResponse("achievements.html", {"request": request, "achievements": achievements, "ranks": ranks})

@app.post("/achievements/grant")
async def grant_achievement(user_id: int = Form(...), achievement: str = Form(...), admin: dict = Depends(get_current_admin)):
    from db import grant_achievement as db_grant
    await db_grant(user_id, achievement)
    return RedirectResponse(url="/achievements", status_code=302)

# ========== НАСТРОЙКИ ==========
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user: dict = Depends(get_current_user)):
    texts = await fetch("SELECT key, value, updated_at FROM custom_texts")
    return templates.TemplateResponse("settings.html", {"request": request, "texts": texts})

@app.post("/settings/text")
async def update_text(key: str = Form(...), value: str = Form(...), admin: dict = Depends(get_current_admin)):
    await execute("INSERT INTO custom_texts (key, value, updated_at) VALUES ($1, $2, NOW()) ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()", key, value)
    return RedirectResponse(url="/settings", status_code=302)

# ========== РАБОТНИКИ ==========
@app.get("/workers", response_class=HTMLResponse)
async def workers_page(request: Request, admin: dict = Depends(get_current_admin)):
    workers = await fetch("SELECT user_id, username, permissions FROM users WHERE role = 'worker'")
    return templates.TemplateResponse("workers.html", {"request": request, "workers": workers})

@app.post("/workers/add")
async def add_worker(user_id: int = Form(...), permissions: str = Form(""), admin: dict = Depends(get_current_admin)):
    from db import add_worker as db_add_worker
    await db_add_worker(user_id, permissions)
    return RedirectResponse(url="/workers", status_code=302)

@app.post("/workers/remove")
async def remove_worker(user_id: int = Form(...), admin: dict = Depends(get_current_admin)):
    from db import remove_worker as db_remove_worker
    await db_remove_worker(user_id)
    return RedirectResponse(url="/workers", status_code=302)

# ========== ЛОГИ ==========
@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, user: dict = Depends(get_current_user)):
    try:
        async with aiofiles.open("bot.log", "r") as f:
            content = (await f.read())[-5000:]
    except:
        content = "Лог-файл не найден"
    return templates.TemplateResponse("logs.html", {"request": request, "logs": content})

@app.get("/audit-log", response_class=HTMLResponse)
async def audit_log_page(request: Request, user: dict = Depends(get_current_user)):
    logs = await fetch("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 200")
    return templates.TemplateResponse("audit_log.html", {"request": request, "logs": logs})

# ========== API-КЛЮЧИ ==========
@app.get("/api-keys", response_class=HTMLResponse)
async def api_keys_page(request: Request, user: dict = Depends(get_current_user)):
    keys = await fetch("SELECT id, user_id, api_key, permissions, created_at, last_used FROM api_keys ORDER BY created_at DESC")
    return templates.TemplateResponse("api_keys.html", {"request": request, "api_keys": keys})

@app.post("/api-keys/create")
async def create_api_key(user_id: int = Form(...), permissions: str = Form(...), admin: dict = Depends(get_current_admin)):
    from db import create_api_key as db_create_key
    api_key = await db_create_key(user_id, permissions)
    return RedirectResponse(url="/api-keys", status_code=302)

@app.post("/api-keys/revoke")
async def revoke_api_key(key_id: int = Form(...), admin: dict = Depends(get_current_admin)):
    from db import revoke_api_key as db_revoke
    await db_revoke(key_id)
    return RedirectResponse(url="/api-keys", status_code=302)

# ========== ПОДПИСКИ ==========
@app.get("/subscriptions", response_class=HTMLResponse)
async def subscriptions_page(request: Request, user: dict = Depends(get_current_user)):
    subs = await fetch("SELECT u.user_id, u.username, s.plan, s.status, s.end_date, s.auto_renew FROM users u LEFT JOIN subscriptions s ON u.user_id = s.user_id ORDER BY u.user_id")
    return templates.TemplateResponse("subscriptions.html", {"request": request, "subscriptions": subs})

@app.post("/subscriptions/update")
async def update_subscription(user_id: int = Form(...), plan: str = Form(...), status: str = Form(...), end_date: str = Form(...), auto_renew: bool = Form(False), admin: dict = Depends(get_current_admin)):
    from db import update_subscription as db_update_sub
    await db_update_sub(user_id, plan, status, end_date, auto_renew)
    return RedirectResponse(url="/subscriptions", status_code=302)

# ========== ПЛАТЕЖИ (STRIPE) ==========
@app.post("/create-payment")
async def create_payment(amount: float = Form(...), user: dict = Depends(get_current_user)):
    if not STRIPE_AVAILABLE:
        raise HTTPException(status_code=501, detail="Stripe not configured")
    intent = create_payment_intent(amount)
    return JSONResponse({"client_secret": intent.client_secret})

# ========== WEBSOCKET ==========
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
    user_id = None
    if token and JWT_AVAILABLE:
        try:
            payload = decode_jwt_token(token)
            user_id = payload["user_id"]
        except:
            user_id = None
    await manager.connect(websocket, user_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)