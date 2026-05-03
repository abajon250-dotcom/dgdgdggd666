import asyncpg
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from config import DATABASE_URL, ADMIN_IDS

_pool: Optional[asyncpg.Pool] = None

async def init_db_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    return _pool

async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        await init_db_pool()
    return _pool

async def init_db():
    """Создаёт или обновляет таблицы, добавляет новые колонки, индексы."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # ---------- Таблицы ----------
        # Пользователи
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                registered_at TIMESTAMP,
                total_earned REAL DEFAULT 0,
                earned_today REAL DEFAULT 0,
                total_qr INTEGER DEFAULT 0,
                crypto_balance REAL DEFAULT 0,
                referrer_id BIGINT,
                referral_earnings REAL DEFAULT 0,
                terms_accepted BOOLEAN DEFAULT FALSE,
                role TEXT DEFAULT 'user',
                permissions TEXT DEFAULT '',
                lang TEXT DEFAULT 'ru',
                wallet TEXT DEFAULT ''
            )
        """)
        # Заявки
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS qr_submissions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                operator TEXT,
                price REAL,
                phone TEXT,
                photo_file_id TEXT,
                status TEXT DEFAULT 'pending',
                submitted_at TIMESTAMP,
                reviewed_at TIMESTAMP,
                admin_id BIGINT,
                earned_amount REAL DEFAULT 0,
                hold_until TIMESTAMP,
                region TEXT,
                reject_reason TEXT,
                taken_by BIGINT,
                taken_at TIMESTAMP,
                mode TEXT DEFAULT 'hold'
            )
        """)
        # Операторы
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS operators (
                name TEXT PRIMARY KEY,
                price_hold REAL,
                price_bh REAL,
                slot_limit INTEGER DEFAULT -1,
                min_minutes INTEGER DEFAULT 50,
                conditions TEXT DEFAULT ''
            )
        """)
        # Брони
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                operator TEXT,
                created_at TIMESTAMP,
                used BOOLEAN DEFAULT FALSE
            )
        """)
        # Настройки
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Статистика
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                date DATE PRIMARY KEY,
                total_qr INTEGER DEFAULT 0,
                total_earned REAL DEFAULT 0
            )
        """)
        # Регионы
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS regions (
                code TEXT PRIMARY KEY,
                name TEXT
            )
        """)
        # Заявки на вывод
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS withdraw_requests (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount REAL,
                status TEXT DEFAULT 'pending',
                requested_at TIMESTAMP,
                processed_at TIMESTAMP,
                admin_id BIGINT
            )
        """)
        # Кастомные тексты
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_texts (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP
            )
        """)
        # Тикеты поддержки
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                category TEXT,
                message TEXT,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                admin_response TEXT,
                closed_at TIMESTAMP
            )
        """)
        # Чёрный список
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                phone TEXT PRIMARY KEY,
                created_at TIMESTAMP,
                admin_id BIGINT
            )
        """)
        # Ачивки
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                user_id BIGINT,
                achievement TEXT,
                earned_at TIMESTAMP,
                PRIMARY KEY (user_id, achievement)
            )
        """)
        # Ранги / уровни
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ranks (
                user_id BIGINT PRIMARY KEY,
                level INTEGER DEFAULT 1,
                xp INTEGER DEFAULT 0,
                updated_at TIMESTAMP
            )
        """)
        # API-ключи
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                api_key TEXT UNIQUE,
                permissions TEXT,
                created_at TIMESTAMP,
                last_used TIMESTAMP
            )
        """)
        # Подписки
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id BIGINT PRIMARY KEY,
                plan TEXT DEFAULT 'free',
                status TEXT DEFAULT 'active',
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                auto_renew BOOLEAN DEFAULT FALSE
            )
        """)
        # Аудит-лог
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                action TEXT,
                details TEXT,
                ip TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # Сессии (для веб-панели)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_id TEXT PRIMARY KEY,
                user_id BIGINT,
                created_at TIMESTAMP,
                expires_at TIMESTAMP
            )
        """)

        # Индексы
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_user ON qr_submissions(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_status ON qr_submissions(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_region ON qr_submissions(region)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_taken_by ON qr_submissions(taken_by)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_blacklist_phone ON blacklist(phone)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_time ON audit_log(created_at)")

        # Заполнение начальными данными
        # Операторы
        count_ops = await conn.fetchval("SELECT COUNT(*) FROM operators")
        if count_ops == 0:
            operators = [
                ("Билайн", 15.0, 12.0, -1, 50, ""),
                ("Газпром", 28.0, 22.0, -1, 50, ""),
                ("МТС", 18.0, 14.0, -1, 50, ""),
                ("Сбер", 12.0, 9.0, -1, 50, ""),
                ("ВТБ", 25.0, 20.0, -1, 50, ""),
                ("Добросвязь", 13.0, 10.0, -1, 50, ""),
                ("Мегафон", 14.0, 11.0, -1, 50, ""),
                ("Т2", 14.0, 11.0, -1, 50, ""),
                ("Тинькофф", 14.0, 11.0, -1, 50, ""),
                ("Миранда", 11.0, 9.0, -1, 50, ""),
                ("Волна", 12.0, 10.0, -1, 50, ""),
                ("Йота", 14.0, 11.0, -1, 50, ""),
            ]
            for op in operators:
                await conn.execute("""
                    INSERT INTO operators (name, price_hold, price_bh, slot_limit, min_minutes, conditions)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (name) DO NOTHING
                """, *op)

        # Настройка по умолчанию
        await conn.execute("INSERT INTO settings (key, value) VALUES ('sale_mode', 'hold') ON CONFLICT (key) DO NOTHING")

        # Регионы
        count_reg = await conn.fetchval("SELECT COUNT(*) FROM regions")
        if count_reg == 0:
            regions = [
                ("901", "г. Санкт-Петербург и Ленинградская область"),
                ("902", "г. Санкт-Петербург и Ленинградская область"),
                ("903", "г. Санкт-Петербург и Ленинградская область"),
                ("904", "г. Санкт-Петербург и Ленинградская область"),
                ("905", "г. Санкт-Петербург и Ленинградская область"),
                ("906", "г. Санкт-Петербург и Ленинградская область"),
                ("909", "г. Санкт-Петербург и Ленинградская область"),
                ("910", "Москва и Московская область"),
                ("915", "Москва и Московская область"),
                ("916", "Москва и Московская область"),
                ("917", "Москва и Московская область"),
                ("925", "Москва и Московская область"),
                ("926", "Москва и Московская область"),
                ("929", "Москва и Московская область"),
                ("930", "Москва и Московская область"),
                ("937", "Москва и Московская область"),
                ("938", "Москва и Московская область"),
                ("939", "Москва и Московская область"),
                ("958", "Москва и Московская область"),
                ("977", "Москва и Московская область"),
                ("985", "Москва и Московская область"),
                ("986", "Москва и Московская область"),
                ("987", "Москва и Московская область"),
                ("988", "Москва и Московская область"),
                ("989", "Москва и Московская область"),
                ("995", "Москва и Московская область"),
                ("981", "Иркутская обл."),
                ("982", "Иркутская обл."),
                ("983", "Иркутская обл."),
                ("984", "Иркутская обл."),
            ]
            for code, name in regions:
                await conn.execute("INSERT INTO regions (code, name) VALUES ($1, $2) ON CONFLICT (code) DO NOTHING", code, name)

        # Кастомные тексты по умолчанию
        default_texts = {
            'welcome': '📄 **Условия работы:** ... (ваш текст)',
            'faq': '**FAQ – Часто задаваемые вопросы** ...',
            'price_list': '**Актуальный прайс** ...',
        }
        for key, val in default_texts.items():
            await conn.execute("""
                INSERT INTO custom_texts (key, value, updated_at) VALUES ($1, $2, NOW())
                ON CONFLICT (key) DO NOTHING
            """, key, val)

# ------------------------------------------------------------
# Функции для пользователей и ролей (были, дополним)
# ------------------------------------------------------------
async def register_user(user_id: int, username: str, full_name: str, referrer_id: int = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        role = 'admin' if user_id in ADMIN_IDS else 'user'
        await conn.execute("""
            INSERT INTO users (user_id, username, full_name, registered_at, referrer_id, terms_accepted, role)
            VALUES ($1, $2, $3, $4, $5, FALSE, $6)
            ON CONFLICT (user_id) DO NOTHING
        """, user_id, username, full_name, datetime.now(), referrer_id, role)
        if referrer_id and referrer_id != user_id:
            await update_user_earnings(referrer_id, 1.0, is_referral_bonus=True)

async def accept_terms(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET terms_accepted = TRUE WHERE user_id = $1", user_id)

async def has_accepted_terms(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT terms_accepted FROM users WHERE user_id = $1", user_id) or False

async def get_user(user_id: int) -> Optional[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        return dict(row) if row else None

async def update_user_earnings(user_id: int, amount: float, is_referral_bonus=False):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if is_referral_bonus:
            await conn.execute("UPDATE users SET referral_earnings = referral_earnings + $1, crypto_balance = crypto_balance + $1 WHERE user_id = $2", amount, user_id)
        else:
            await conn.execute("UPDATE users SET total_earned = total_earned + $1, earned_today = earned_today + $1 WHERE user_id = $2", amount, user_id)

async def add_crypto_balance(user_id: int, amount: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET crypto_balance = crypto_balance + $1 WHERE user_id = $2", amount, user_id)

async def increment_total_qr(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET total_qr = total_qr + 1 WHERE user_id = $1", user_id)

async def set_user_role(user_id: int, role: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET role = $1 WHERE user_id = $2", role, user_id)

async def get_user_role(user_id: int) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT role FROM users WHERE user_id = $1", user_id) or "user"

async def add_worker(user_id: int, permissions: str = ""):
    await set_user_role(user_id, "worker")
    if permissions:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET permissions = $1 WHERE user_id = $2", permissions, user_id)

async def remove_worker(user_id: int):
    await set_user_role(user_id, "user")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET permissions = '' WHERE user_id = $1", user_id)

# ------------------------------------------------------------
# Заявки
# ------------------------------------------------------------
async def create_submission(user_id: int, operator: str, price: float, phone: str, photo_file_id: str, region: str = None, mode: str = 'hold') -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO qr_submissions (user_id, operator, price, phone, photo_file_id, submitted_at, status, region, mode)
            VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7, $8)
            RETURNING id
        """, user_id, operator, price, phone, photo_file_id, datetime.now(), region, mode)
        return row['id']

async def get_pending_submissions(limit: int = 20) -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM qr_submissions WHERE status = 'pending' ORDER BY submitted_at DESC LIMIT $1", limit)
        return [dict(row) for row in rows]

async def get_pending_submissions_by_mode(mode: str, limit: int = 20) -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM qr_submissions WHERE status = 'pending' AND mode = $1 ORDER BY submitted_at DESC LIMIT $2",
            mode, limit
        )
        return [dict(row) for row in rows]

async def get_submission(submission_id: int) -> Optional[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM qr_submissions WHERE id = $1", submission_id)
        return dict(row) if row else None

async def take_submission(submission_id: int, worker_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE qr_submissions SET status = 'taken', taken_by = $1, taken_at = $2 WHERE id = $3", worker_id, datetime.now(), submission_id)

async def hold_submission(submission_id: int, admin_id: int, hold_until: datetime):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE qr_submissions SET status = 'hold', reviewed_at = $1, admin_id = $2, hold_until = $3 WHERE id = $4", datetime.now(), admin_id, hold_until, submission_id)

async def accept_submission_now(submission_id: int, admin_id: int, earned_amount: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE qr_submissions SET status = 'accepted', reviewed_at = $1, admin_id = $2, earned_amount = $3 WHERE id = $4", datetime.now(), admin_id, earned_amount, submission_id)
        sub = await get_submission(submission_id)
        if sub:
            await update_user_earnings(sub['user_id'], earned_amount)
            await increment_total_qr(sub['user_id'])

async def accept_submission_from_hold(submission_id: int, earned_amount: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE qr_submissions SET status = 'accepted', earned_amount = $1 WHERE id = $2", earned_amount, submission_id)
        sub = await get_submission(submission_id)
        if sub:
            await update_user_earnings(sub['user_id'], earned_amount)
            await increment_total_qr(sub['user_id'])

async def mark_submission_failed(submission_id: int, admin_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE qr_submissions SET status = 'failed', reviewed_at = $1, admin_id = $2 WHERE id = $3", datetime.now(), admin_id, submission_id)

async def mark_submission_blocked(submission_id: int, admin_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE qr_submissions SET status = 'blocked', reviewed_at = $1, admin_id = $2 WHERE id = $3", datetime.now(), admin_id, submission_id)

async def reject_submission(submission_id: int, admin_id: int, reason: str = 'block'):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE qr_submissions SET status = 'rejected', reviewed_at = $1, admin_id = $2, reject_reason = $3 WHERE id = $4", datetime.now(), admin_id, reason, submission_id)

async def get_hold_submissions() -> List[Dict]:
    pool = await get_pool()
    now = datetime.now()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM qr_submissions WHERE status = 'hold' AND hold_until > $1", now)
        return [dict(row) for row in rows]

async def get_taken_submissions(worker_id: int = None) -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if worker_id:
            rows = await conn.fetch("SELECT * FROM qr_submissions WHERE status = 'taken' AND taken_by = $1", worker_id)
        else:
            rows = await conn.fetch("SELECT * FROM qr_submissions WHERE status = 'taken'")
        return [dict(row) for row in rows]

# ------------------------------------------------------------
# Операторы
# ------------------------------------------------------------
async def get_operators() -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM operators ORDER BY name")
        return [dict(row) for row in rows]

async def get_operator_price(operator: str, mode: str) -> Optional[float]:
    column = "price_hold" if mode == "hold" else "price_bh"
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(f"SELECT {column} FROM operators WHERE name = $1", operator)

async def update_operator_prices(operator: str, price_hold: float, price_bh: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE operators SET price_hold = $1, price_bh = $2 WHERE name = $3", price_hold, price_bh, operator)

async def update_operator_slot_limit(operator: str, limit: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE operators SET slot_limit = $1 WHERE name = $2", limit, operator)

async def update_operator_conditions(operator: str, min_minutes: int, conditions: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE operators SET min_minutes = $1, conditions = $2 WHERE name = $3", min_minutes, conditions, operator)

async def get_operator_conditions(operator: str) -> Dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT min_minutes, conditions FROM operators WHERE name = $1", operator)
        return dict(row) if row else {"min_minutes": 50, "conditions": ""}

# ------------------------------------------------------------
# Бронирования
# ------------------------------------------------------------
async def create_booking(user_id: int, operator: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("INSERT INTO bookings (user_id, operator, created_at) VALUES ($1, $2, $3) RETURNING id", user_id, operator, datetime.now())
        return row['id']

async def get_active_booking(user_id: int) -> Optional[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM bookings WHERE user_id = $1 AND used = FALSE ORDER BY created_at DESC LIMIT 1", user_id)
        return dict(row) if row else None

async def use_booking(booking_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE bookings SET used = TRUE WHERE id = $1", booking_id)

async def cancel_booking(booking_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM bookings WHERE id = $1", booking_id)

async def count_active_bookings_for_operator(operator: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM bookings WHERE operator = $1 AND used = FALSE", operator) or 0

# ------------------------------------------------------------
# Настройки
# ------------------------------------------------------------
async def get_setting(key: str, default: str = None) -> Optional[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        value = await conn.fetchval("SELECT value FROM settings WHERE key = $1", key)
        return value if value is not None else default

async def set_setting(key: str, value: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2", key, value)

# ------------------------------------------------------------
# Статистика
# ------------------------------------------------------------
async def get_user_stats(user_id: int, days: int = None) -> Dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if days is None:
            row = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) as accepted,
                    SUM(CASE WHEN status = 'rejected' AND reject_reason = 'block' THEN 1 ELSE 0 END) as blocked,
                    SUM(CASE WHEN status = 'rejected' AND reject_reason = 'noscan' THEN 1 ELSE 0 END) as noscan,
                    COALESCE(SUM(earned_amount), 0) as sum_earned
                FROM qr_submissions
                WHERE user_id = $1
            """, user_id)
        else:
            row = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) as accepted,
                    SUM(CASE WHEN status = 'rejected' AND reject_reason = 'block' THEN 1 ELSE 0 END) as blocked,
                    SUM(CASE WHEN status = 'rejected' AND reject_reason = 'noscan' THEN 1 ELSE 0 END) as noscan,
                    COALESCE(SUM(earned_amount), 0) as sum_earned
                FROM qr_submissions
                WHERE user_id = $1 AND submitted_at >= NOW() - make_interval(days => $2)
            """, user_id, days)
        return dict(row) if row else {"total":0, "accepted":0, "blocked":0, "noscan":0, "sum_earned":0.0}

async def get_user_qr_last_30_days(user_id: int) -> Tuple[int, List[str]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT submitted_at FROM qr_submissions WHERE user_id = $1 AND status = 'accepted' AND submitted_at >= NOW() - INTERVAL '30 days'", user_id)
        dates = [row['submitted_at'].strftime("%Y-%m-%d") for row in rows]
        return len(rows), list(set(dates))

async def get_today_stats() -> Dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*), COALESCE(SUM(earned_amount), 0) FROM qr_submissions WHERE status = 'accepted' AND DATE(submitted_at) = CURRENT_DATE")
        return {"total_qr": row[0] or 0, "total_earned": row[1] or 0.0}

async def get_top_users(limit: int = 10) -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, total_earned FROM users ORDER BY total_earned DESC LIMIT $1", limit)
        return [{"user_id": r['user_id'], "total_earned": r['total_earned']} for r in rows]

async def get_most_popular_operator() -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("""
            SELECT operator FROM qr_submissions
            WHERE status = 'accepted' AND submitted_at >= NOW() - INTERVAL '30 days'
            GROUP BY operator ORDER BY COUNT(*) DESC LIMIT 1
        """) or "нет данных"

async def get_low_stock_operators() -> List[str]:
    operators = await get_operators()
    low_stock = []
    for op in operators:
        if op['slot_limit'] != -1:
            used = await count_active_bookings_for_operator(op['name'])
            free = op['slot_limit'] - used
            if free <= 2:
                low_stock.append(op['name'])
    return low_stock

async def get_operator_top_regions(operator: str, period_days: int = 7) -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT r.name as region_name, COUNT(*) as cnt
            FROM qr_submissions q
            JOIN regions r ON q.region = r.code
            WHERE q.operator = $1 AND q.status = 'accepted' AND q.submitted_at >= NOW() - make_interval(days => $2)
            GROUP BY q.region, r.name
            ORDER BY cnt DESC
            LIMIT 5
        """, operator, period_days)
        return [dict(row) for row in rows]

# ------------------------------------------------------------
# Реферальная система
# ------------------------------------------------------------
async def get_referral_percent(referrer_id: int) -> float:
    pool = await get_pool()
    async with pool.acquire() as conn:
        qr_count = await conn.fetchval("""
            SELECT COUNT(q.id)
            FROM qr_submissions q
            JOIN users u ON q.user_id = u.user_id
            WHERE u.referrer_id = $1 AND q.status = 'accepted' AND q.submitted_at >= NOW() - INTERVAL '30 days'
        """, referrer_id) or 0
        if qr_count >= 200: return 4.0
        elif qr_count >= 101: return 3.5
        elif qr_count >= 61: return 3.0
        elif qr_count >= 41: return 2.0
        elif qr_count >= 21: return 1.0
        else: return 0.0

async def get_referral_stats(user_id: int) -> Dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE referrer_id = $1", user_id) or 0
        user = await get_user(user_id)
        earnings = user['referral_earnings'] if user else 0
        return {"count": count, "earnings": earnings}

# ------------------------------------------------------------
# Аудит-лог
# ------------------------------------------------------------
async def add_audit_log(user_id: int, action: str, details: str = "", ip: str = ""):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO audit_log (user_id, action, details, ip, created_at) VALUES ($1, $2, $3, $4, NOW())", user_id, action, details, ip)

# ------------------------------------------------------------
# Заявки на вывод
# ------------------------------------------------------------
async def create_withdraw_request(user_id: int, amount: float) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO withdraw_requests (user_id, amount, requested_at, status)
            VALUES ($1, $2, NOW(), 'pending') RETURNING id
        """, user_id, amount)
        return row['id']

async def get_pending_withdraw_requests() -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM withdraw_requests WHERE status = 'pending' ORDER BY requested_at ASC")
        return [dict(row) for row in rows]

async def update_withdraw_request(request_id: int, status: str, admin_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE withdraw_requests SET status = $1, processed_at = NOW(), admin_id = $2 WHERE id = $3
        """, status, admin_id, request_id)

# ------------------------------------------------------------
# Ачивки
# ------------------------------------------------------------
async def grant_achievement(user_id: int, achievement: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO achievements (user_id, achievement, earned_at) VALUES ($1, $2, NOW()) ON CONFLICT DO NOTHING", user_id, achievement)

async def get_user_achievements(user_id: int) -> List[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT achievement FROM achievements WHERE user_id = $1", user_id)
        return [r['achievement'] for r in rows]

# ------------------------------------------------------------
# Подписки
# ------------------------------------------------------------
async def get_user_subscription(user_id: int) -> Dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM subscriptions WHERE user_id = $1", user_id)
        return dict(row) if row else {"plan": "free", "status": "active"}

# ------------------------------------------------------------
# Кастомные тексты
# ------------------------------------------------------------
async def get_custom_text(key: str, default: str = "") -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT value FROM custom_texts WHERE key = $1", key)
        return val if val else default

async def set_custom_text(key: str, value: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO custom_texts (key, value, updated_at) VALUES ($1, $2, NOW()) ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()", key, value)

# ------------------------------------------------------------
# Чёрный список
# ------------------------------------------------------------
async def add_to_blacklist(phone: str, admin_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO blacklist (phone, created_at, admin_id) VALUES ($1, NOW(), $2) ON CONFLICT (phone) DO NOTHING", phone, admin_id)

async def remove_from_blacklist(phone: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM blacklist WHERE phone = $1", phone)

async def is_blacklisted(phone: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT 1 FROM blacklist WHERE phone = $1", phone) is not None

async def get_blacklist() -> List[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT phone FROM blacklist ORDER BY created_at DESC")
        return [r['phone'] for r in rows]

# ------------------------------------------------------------
# Тикеты
# ------------------------------------------------------------
async def create_ticket(user_id: int, category: str, message: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO tickets (user_id, category, message, created_at, updated_at, status)
            VALUES ($1, $2, $3, NOW(), NOW(), 'open') RETURNING id
        """, user_id, category, message)
        return row['id']

async def get_open_tickets() -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM tickets WHERE status = 'open' ORDER BY created_at ASC")
        return [dict(row) for row in rows]

async def answer_ticket(ticket_id: int, response: str, admin_id: int) -> Optional[int]:
    """Возвращает user_id владельца тикета"""
    ticket = await get_ticket(ticket_id)
    if not ticket or ticket['status'] != 'open':
        return None
    user_id = ticket['user_id']
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE tickets SET admin_response = $1, status = 'closed', updated_at = NOW(), closed_at = NOW()
            WHERE id = $2
        """, response, ticket_id)
        await add_audit_log(admin_id, "answer_ticket", f"Ticket #{ticket_id}: {response[:50]}...")
    return user_id

async def get_ticket(ticket_id: int) -> Optional[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
        return dict(row) if row else None

# ------------------------------------------------------------
# API-ключи
# ------------------------------------------------------------
async def create_api_key(user_id: int, permissions: str) -> str:
    import uuid
    api_key = str(uuid.uuid4())
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO api_keys (user_id, api_key, permissions, created_at) VALUES ($1, $2, $3, NOW())", user_id, api_key, permissions)
    return api_key

async def revoke_api_key(key_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM api_keys WHERE id = $1", key_id)

async def get_api_keys() -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM api_keys ORDER BY created_at DESC")
        return [dict(row) for row in rows]

# ------------------------------------------------------------
# Общие вспомогательные функции
# ------------------------------------------------------------
async def get_total_users_count() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users") or 0

async def get_new_users_count(days: int = 1) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users WHERE registered_at >= NOW() - make_interval(days => $1)", days) or 0

async def auto_create_withdraw_requests_for_all():
    """Автоматически создаёт заявки на вывод для всех пользователей, у которых earned_today > 0"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, earned_today FROM users WHERE earned_today > 0")
        for row in rows:
            user_id = row['user_id']
            amount = row['earned_today']
            if amount <= 0:
                continue
            # Вставляем заявку на вывод
            await conn.execute("""
                INSERT INTO withdraw_requests (user_id, amount, requested_at, status)
                VALUES ($1, $2, NOW(), 'pending')
            """, user_id, amount)
            # Обнуляем earned_today
            await conn.execute("UPDATE users SET earned_today = 0 WHERE user_id = $1", user_id)