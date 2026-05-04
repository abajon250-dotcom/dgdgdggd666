from fastapi import FastAPI, Request, Depends, HTTPException, Form, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer
import uvicorn
import aiofiles
from datetime import datetime
from typing import List, Dict, Optional

from db import (
    get_pool, get_user, get_user_by_username, get_total_users_count, get_new_users_count,
    get_active_tickets_count, get_dashboard_stats, get_recent_submissions, get_submissions_ratio,
    get_submission, get_operators, get_blacklist, get_open_tickets, answer_ticket,
    add_to_blacklist, remove_from_blacklist, update_operator_prices, update_operator_slot_limit,
    get_custom_texts, set_custom_text, get_workers, add_worker, remove_worker,
    get_api_keys, create_api_key, revoke_api_key, get_subscriptions, update_subscription,
    get_achievements_list, get_ranks_list, grant_achievement, get_audit_log,
    fetch, execute
)
from ws_manager import manager
from config import ADMIN_IDS

app = FastAPI(title="eSIM Bot Admin Panel")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ========== АВТОРИЗАЦИЯ (по Telegram ID) ==========
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

# ========== DASHBOARD ==========
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: dict = Depends(get_current_user)):
    stats = await get_dashboard_stats()
    recent = await get_recent_submissions(10)
    ratio = await get_submissions_ratio()
    notifications = [
        {"text": "Новая заявка зарегистрирована", "time": "только что"},
        {"text": "Добро пожаловать в админ-панель", "time": datetime.now().strftime("%H:%M")},
    ]
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
        "recent_submissions": recent,
        "ratio": ratio,
        "notifications": notifications,
        "admin_name": user.get("username", f"Admin {user['user_id']}"),
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
    tickets = await get_open_tickets()
    return templates.TemplateResponse("tickets.html", {"request": request, "tickets": tickets})

@app.post("/tickets/answer")
async def answer_ticket_web(ticket_id: int = Form(...), response_text: str = Form(...), admin: dict = Depends(get_current_admin)):
    user_id = await answer_ticket(ticket_id, response_text, admin['user_id'])
    if user_id:
        # Здесь можно отправить сообщение пользователю через бота
        pass
    return RedirectResponse(url="/tickets", status_code=302)

# ========== ОПЕРАТОРЫ ==========
@app.get("/operators", response_class=HTMLResponse)
async def operators_page(request: Request, user: dict = Depends(get_current_user)):
    ops = await get_operators()
    return templates.TemplateResponse("operators.html", {"request": request, "operators": ops})

@app.post("/operators/price")
async def update_operator_price(operator: str = Form(...), price_hold: float = Form(...), price_bh: float = Form(...), admin: dict = Depends(get_current_admin)):
    await update_operator_prices(operator, price_hold, price_bh)
    return RedirectResponse(url="/operators", status_code=302)

@app.post("/operators/slot")
async def update_operator_slot(operator: str = Form(...), slot_limit: int = Form(...), admin: dict = Depends(get_current_admin)):
    await update_operator_slot_limit(operator, slot_limit)
    return RedirectResponse(url="/operators", status_code=302)

@app.post("/operators/reorder")
async def reorder_operators(order: List[str] = Form(...), admin: dict = Depends(get_current_admin)):
    from db import reorder_operators
    await reorder_operators(order)
    return JSONResponse({"status": "ok"})

# ========== ЧЁРНЫЙ СПИСОК ==========
@app.get("/blacklist", response_class=HTMLResponse)
async def blacklist_page(request: Request, admin: dict = Depends(get_current_admin)):
    items = await get_blacklist()
    return templates.TemplateResponse("blacklist.html", {"request": request, "blacklist": items})

@app.post("/blacklist/add")
async def add_blacklist(phone: str = Form(...), admin: dict = Depends(get_current_admin)):
    await add_to_blacklist(phone, admin['user_id'])
    return RedirectResponse(url="/blacklist", status_code=302)

@app.post("/blacklist/remove")
async def remove_blacklist(phone: str = Form(...), admin: dict = Depends(get_current_admin)):
    await remove_from_blacklist(phone)
    return RedirectResponse(url="/blacklist", status_code=302)

# ========== РАССЫЛКА ==========
@app.get("/broadcast", response_class=HTMLResponse)
async def broadcast_page(request: Request, admin: dict = Depends(get_current_admin)):
    return templates.TemplateResponse("broadcast.html", {"request": request})

@app.post("/broadcast/send")
async def send_broadcast(message: str = Form(...), target: str = Form("all"), admin: dict = Depends(get_current_admin)):
    users = await fetch("SELECT user_id FROM users WHERE $1 = 'all' OR role = $1", target)
    for u in users:
        # Здесь вызвать bot.send_message (нужен экземпляр бота)
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
    total_users = await get_total_users_count()
    revenue_today = await fetch("SELECT COALESCE(SUM(earned_amount),0) as sum FROM qr_submissions WHERE status='accepted' AND DATE(submitted_at)=CURRENT_DATE")
    submissions_by_hour = await fetch("""
        SELECT EXTRACT(HOUR FROM submitted_at) as hour, COUNT(*) as cnt
        FROM qr_submissions WHERE DATE(submitted_at)=CURRENT_DATE
        GROUP BY hour ORDER BY hour
    """)
    return {
        "total_users": total_users,
        "revenue_today": float(revenue_today[0]['sum']) if revenue_today else 0,
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
    # Генерация CSV – можно добавить позже
    return JSONResponse({"status": "generated"})

# ========== АЧИВКИ ==========
@app.get("/achievements", response_class=HTMLResponse)
async def achievements_page(request: Request, user: dict = Depends(get_current_user)):
    achievements = await get_achievements_list()
    ranks = await get_ranks_list()
    return templates.TemplateResponse("achievements.html", {"request": request, "achievements": achievements, "ranks": ranks})

@app.post("/achievements/grant")
async def grant_achievement_web(user_id: int = Form(...), achievement: str = Form(...), admin: dict = Depends(get_current_admin)):
    await grant_achievement(user_id, achievement)
    return RedirectResponse(url="/achievements", status_code=302)

# ========== НАСТРОЙКИ ==========
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user: dict = Depends(get_current_user)):
    texts = await get_custom_texts()
    return templates.TemplateResponse("settings.html", {"request": request, "texts": texts})

@app.post("/settings/text")
async def update_text_web(key: str = Form(...), value: str = Form(...), admin: dict = Depends(get_current_admin)):
    await set_custom_text(key, value)
    return RedirectResponse(url="/settings", status_code=302)

# ========== РАБОТНИКИ ==========
@app.get("/workers", response_class=HTMLResponse)
async def workers_page(request: Request, admin: dict = Depends(get_current_admin)):
    workers = await get_workers()
    return templates.TemplateResponse("workers.html", {"request": request, "workers": workers})

@app.post("/workers/add")
async def add_worker_web(user_id: int = Form(...), permissions: str = Form(""), admin: dict = Depends(get_current_admin)):
    await add_worker(user_id, permissions)
    return RedirectResponse(url="/workers", status_code=302)

@app.post("/workers/remove")
async def remove_worker_web(user_id: int = Form(...), admin: dict = Depends(get_current_admin)):
    await remove_worker(user_id)
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
    logs = await get_audit_log(200)
    return templates.TemplateResponse("audit_log.html", {"request": request, "logs": logs})

# ========== API-КЛЮЧИ ==========
@app.get("/api-keys", response_class=HTMLResponse)
async def api_keys_page(request: Request, user: dict = Depends(get_current_user)):
    keys = await get_api_keys()
    return templates.TemplateResponse("api_keys.html", {"request": request, "api_keys": keys})

@app.post("/api-keys/create")
async def api_key_create_web(user_id: int = Form(...), permissions: str = Form(...), admin: dict = Depends(get_current_admin)):
    await create_api_key(user_id, permissions)
    return RedirectResponse(url="/api-keys", status_code=302)

@app.post("/api-keys/revoke")
async def api_key_revoke_web(key_id: int = Form(...), admin: dict = Depends(get_current_admin)):
    await revoke_api_key(key_id)
    return RedirectResponse(url="/api-keys", status_code=302)

# ========== ПОДПИСКИ ==========
@app.get("/subscriptions", response_class=HTMLResponse)
async def subscriptions_page(request: Request, user: dict = Depends(get_current_user)):
    subs = await get_subscriptions()
    return templates.TemplateResponse("subscriptions.html", {"request": request, "subscriptions": subs})

@app.post("/subscriptions/update")
async def subscription_update_web(user_id: int = Form(...), plan: str = Form(...), status: str = Form(...), end_date: str = Form(...), auto_renew: bool = Form(False), admin: dict = Depends(get_current_admin)):
    await update_subscription(user_id, plan, status, end_date, auto_renew)
    return RedirectResponse(url="/subscriptions", status_code=302)

# ========== WEBSOCKET ==========
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)