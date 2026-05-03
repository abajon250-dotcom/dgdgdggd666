# cron.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import auto_create_withdraw_requests_for_all
from daily_summary import send_daily_summary

async def reset_daily_earnings():
    from db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET earned_today = 0")

def setup_scheduler(bot):
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(send_daily_summary, "cron", hour=18, minute=0, args=[bot])
    scheduler.add_job(reset_daily_earnings, "cron", hour=0, minute=0)
    scheduler.add_job(auto_create_withdraw_requests_for_all, "cron", hour=23, minute=55)
    scheduler.start()
    return scheduler