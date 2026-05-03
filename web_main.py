from fastapi import FastAPI, Request, Depends, HTTPException, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from urllib.parse import parse_qs
import json
import uuid
from datetime import datetime

# Импорты из наших модулей
from web_database import *
from web_auth import verify_telegram_auth
from config import ADMIN_IDS

# Создаём приложение
app = FastAPI(title="eSIM Bot Admin Panel", version="3.0")

# Шаблоны и статика
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Зависимость для проверки авторизации
async def get_current_admin(request: Request):
    tid = request.cookies.get("telegram_id")
    if tid is None or int(tid) not in ADMIN_IDS:
        raise HTTPException(status_code=303, detail="Unauthorized", headers={"Location": "/"})
    return int(tid)

# ---------- Страницы авторизации ----------
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "bot_username": "ваш_бот_username"  # замените на реальное имя бота
    })

@app.post("/auth")
async def auth(request: Request):
    form = await request.form()
    init_data = form.get("init_data")
    if not init_data or not verify_telegram_auth(init_data):
        raise HTTPException(status_code=403, detail="Invalid auth")
    data = parse_qs(init_data)
    user_data = data.get('user', [''])[0]
    user = json.loads(user_data) if user_data else {}
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

# ---------- Дашборд ----------
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, admin_id: int = Depends(get_current_admin)):
    stats = await get_dashboard_stats()
    recent = await get_recent_submissions(10)
    ratio = await get_submissions_ratio()
    notif = await get_recent_notifications()  # временные уведомления
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
        "recent_submissions": recent,
        "ratio": ratio,
        "notifications": notif,
        "admin_name": f"Admin {admin_id}"
    })

# ---------- Заявки ----------
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

# ---------- Пользователи ----------
@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, admin_id: int = Depends(get_current_admin)):
    users = await get_all_users()
    return templates.TemplateResponse("users.html", {"request": request, "users": users})

@app.post("/users/role")
async def change_user_role(user_id: int = Form(...), role: str = Form(...), admin_id: int = Depends(get_current_admin)):
    from db import set_user_role
    await set_user_role(user_id, role)
    return RedirectResponse(url="/users", status_code=302)

# ---------- Тикеты ----------
@app.get("/tickets", response_class=HTMLResponse)
async def tickets_page(request: Request, admin_id: int = Depends(get_current_admin)):
    tickets = await get_open_tickets()
    return templates.TemplateResponse("tickets.html", {"request": request, "tickets": tickets})

@app.post("/tickets/answer")
async def answer_ticket(ticket_id: int = Form(...), response_text: str = Form(...), admin_id: int = Depends(get_current_admin)):
    user_id = await answer_ticket(ticket_id, response_text, admin_id)
    if user_id:
        # Отправить ответ через бота — если нужно, доработайте
        pass
    return RedirectResponse(url="/tickets", status_code=302)

# ---------- Операторы ----------
@app.get("/operators", response_class=HTMLResponse)
async def operators_page(request: Request, admin_id: int = Depends(get_current_admin)):
    ops = await get_operators()
    return templates.TemplateResponse("operators.html", {"request": request, "operators": ops})

@app.post("/operators/price")
async def update_price(operator: str = Form(...), price_hold: float = Form(...), price_bh: float = Form(...), admin_id: int = Depends(get_current_admin)):
    await update_operator_price(operator, price_hold, price_bh)
    return RedirectResponse(url="/operators", status_code=302)

@app.post("/operators/slot")
async def update_slot(operator: str = Form(...), slot_limit: int = Form(...), admin_id: int = Depends(get_current_admin)):
    await update_operator_slot(operator, slot_limit)
    return RedirectResponse(url="/operators", status_code=302)

# ---------- Чёрный список ----------
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

# ---------- Рассылка ----------
@app.get("/broadcast", response_class=HTMLResponse)
async def broadcast_page(request: Request, admin_id: int = Depends(get_current_admin)):
    return templates.TemplateResponse("broadcast.html", {"request": request})

@app.post("/broadcast/send")
async def send_broadcast(message: str = Form(...), target: str = Form("all"), admin_id: int = Depends(get_current_admin)):
    # Здесь нужно отправить сообщения через бота (можно добавить позже)
    return RedirectResponse(url="/broadcast", status_code=302)

# ---------- Аналитика (API) ----------
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
    return {
        "dates": [row['date'].isoformat() for row in data],
        "submissions": [row['submissions'] for row in data],
        "revenue": [float(row['revenue']) for row in data]
    }

# ---------- Статистика ----------
@app.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request, admin_id: int = Depends(get_current_admin)):
    return templates.TemplateResponse("stats.html", {"request": request})

# ---------- Отчёты ----------
@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, admin_id: int = Depends(get_current_admin)):
    return templates.TemplateResponse("reports.html", {"request": request})

@app.get("/reports/generate")
async def generate_report(report_type: str = Query("weekly")):
    # Здесь можно сгенерировать CSV-отчёт
    return JSONResponse({"status": "generated"})

# ---------- Ачивки и уровни ----------
@app.get("/achievements", response_class=HTMLResponse)
async def achievements_page(request: Request, admin_id: int = Depends(get_current_admin)):
    achievements = await get_achievements()
    ranks = await get_ranks()
    return templates.TemplateResponse("achievements.html", {"request": request, "achievements": achievements, "ranks": ranks})

@app.post("/achievements/grant")
async def grant_achievement(user_id: int = Form(...), achievement: str = Form(...), admin_id: int = Depends(get_current_admin)):
    from db import grant_achievement as db_grant
    await db_grant(user_id, achievement)
    return RedirectResponse(url="/achievements", status_code=302)

# ---------- Настройки (кастомные тексты) ----------
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, admin_id: int = Depends(get_current_admin)):
    texts = await get_custom_texts()
    return templates.TemplateResponse("settings.html", {"request": request, "texts": texts})

@app.post("/settings/text")
async def update_text(key: str = Form(...), value: str = Form(...), admin_id: int = Depends(get_current_admin)):
    await set_custom_text(key, value)
    return RedirectResponse(url="/settings", status_code=302)

# ---------- Работники ----------
@app.get("/workers", response_class=HTMLResponse)
async def workers_page(request: Request, admin_id: int = Depends(get_current_admin)):
    workers = await get_workers()
    return templates.TemplateResponse("workers.html", {"request": request, "workers": workers})

@app.post("/workers/add")
async def add_worker(user_id: int = Form(...), permissions: str = Form(""), admin_id: int = Depends(get_current_admin)):
    from db import add_worker as db_add_worker
    await db_add_worker(user_id, permissions)
    return RedirectResponse(url="/workers", status_code=302)

@app.post("/workers/remove")
async def remove_worker(user_id: int = Form(...), admin_id: int = Depends(get_current_admin)):
    from db import remove_worker as db_remove_worker
    await db_remove_worker(user_id)
    return RedirectResponse(url="/workers", status_code=302)

# ---------- Логи ----------
@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, admin_id: int = Depends(get_current_admin)):
    import aiofiles
    content = ""
    try:
        async with aiofiles.open("bot.log", "r") as f:
            content = (await f.read())[-5000:]
    except:
        content = "Лог-файл не найден"
    return templates.TemplateResponse("logs.html", {"request": request, "logs": content})

@app.get("/audit-log", response_class=HTMLResponse)
async def audit_log_page(request: Request, admin_id: int = Depends(get_current_admin)):
    logs = await fetch("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 200")
    return templates.TemplateResponse("audit_log.html", {"request": request, "logs": logs})

# ---------- API-ключи ----------
@app.get("/api-keys", response_class=HTMLResponse)
async def api_keys_page(request: Request, admin_id: int = Depends(get_current_admin)):
    keys = await get_api_keys()
    return templates.TemplateResponse("api_keys.html", {"request": request, "api_keys": keys})

@app.post("/api-keys/create")
async def api_key_create(user_id: int = Form(...), permissions: str = Form(...), admin_id: int = Depends(get_current_admin)):
    from db import create_api_key as db_create
    await db_create(user_id, permissions)
    return RedirectResponse(url="/api-keys", status_code=302)

@app.post("/api-keys/revoke")
async def api_key_revoke(key_id: int = Form(...), admin_id: int = Depends(get_current_admin)):
    from db import revoke_api_key as db_revoke
    await db_revoke(key_id)
    return RedirectResponse(url="/api-keys", status_code=302)

# ---------- Подписки ----------
@app.get("/subscriptions", response_class=HTMLResponse)
async def subscriptions_page(request: Request, admin_id: int = Depends(get_current_admin)):
    subs = await get_subscriptions()
    return templates.TemplateResponse("subscriptions.html", {"request": request, "subscriptions": subs})

@app.post("/subscriptions/update")
async def subscription_update(user_id: int = Form(...), plan: str = Form(...), status: str = Form(...), end_date: str = Form(...), auto_renew: bool = Form(False), admin_id: int = Depends(get_current_admin)):
    await update_subscription(user_id, plan, status, end_date, auto_renew)
    return RedirectResponse(url="/subscriptions", status_code=302)

# ---------- Уведомления (API для фронта) ----------
@app.get("/api/unread-count")
async def unread_count(request: Request, admin_id: int = Depends(get_current_admin)):
    count = await get_unread_count(admin_id)
    return JSONResponse({"unread": count})

# ---------- Запуск (при локальном тестировании) ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_main:app", host="0.0.0.0", port=8000, reload=True)