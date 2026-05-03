# admin_reports.py
from db import get_pool
from datetime import datetime, timedelta

async def send_weekly_report(bot):
    """Отправляет админу сводку за последние 7 дней."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        week_ago = datetime.now() - timedelta(days=7)
        # Общее количество заявок за неделю
        submissions = await conn.fetchval("SELECT COUNT(*) FROM qr_submissions WHERE submitted_at >= $1", week_ago)
        # Выплаченная сумма (accepted)
        paid = await conn.fetchval("SELECT COALESCE(SUM(earned_amount),0) FROM qr_submissions WHERE status='accepted' AND submitted_at >= $1", week_ago)
        # Новые пользователи
        new_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE registered_at >= $1", week_ago)
        # Топ-5 работников по количеству обработанных заявок
        workers_top = await conn.fetch("""
            SELECT u.username, COUNT(*) as cnt
            FROM qr_submissions q
            JOIN users u ON q.admin_id = u.user_id
            WHERE q.reviewed_at >= $1 AND q.status IN ('accepted','rejected')
            GROUP BY u.user_id, u.username
            ORDER BY cnt DESC LIMIT 5
        """, week_ago)
        text = f"📊 **Еженедельный отчёт**\n\n📅 За период: {(week_ago).strftime('%d.%m.%Y')} – {datetime.now().strftime('%d.%m.%Y')}\n\n"
        text += f"📋 Всего заявок: {submissions}\n💰 Выплачено: {paid:.2f}$\n👥 Новых пользователей: {new_users}\n\n🏆 **Топ работников:**\n"
        for w in workers_top:
            text += f"• @{w['username']}: {w['cnt']} заявок\n"
        from config import ADMIN_IDS
        for admin in ADMIN_IDS:
            await bot.send_message(admin, text, parse_mode="Markdown")