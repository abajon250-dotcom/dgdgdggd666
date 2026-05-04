import asyncio
import os
from db import init_db_pool, get_pool

async def create_all_tables():
    print("Подключение к PostgreSQL...")
    await init_db_pool()
    pool = await get_pool()
    async with pool.acquire() as conn:
        # ---------- Таблица пользователей (расширенная) ----------
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
                wallet TEXT DEFAULT '',
                password_hash TEXT
            )
        """)

        # ---------- Заявки на eSIM ----------
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

        # ---------- Операторы (с сортировкой для Drag & Drop) ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS operators (
                name TEXT PRIMARY KEY,
                price_hold REAL,
                price_bh REAL,
                slot_limit INTEGER DEFAULT -1,
                min_minutes INTEGER DEFAULT 50,
                conditions TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 0
            )
        """)

        # ---------- Бронирования ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                operator TEXT,
                created_at TIMESTAMP,
                used BOOLEAN DEFAULT FALSE
            )
        """)

        # ---------- Настройки ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # ---------- Ежедневная статистика ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                date DATE PRIMARY KEY,
                total_qr INTEGER DEFAULT 0,
                total_earned REAL DEFAULT 0
            )
        """)

        # ---------- Регионы ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS regions (
                code TEXT PRIMARY KEY,
                name TEXT
            )
        """)

        # ---------- Заявки на вывод средств ----------
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

        # ---------- Кастомные тексты (приветствие, FAQ, прайс) ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_texts (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP
            )
        """)

        # ---------- Тикеты поддержки (как Zendesk) ----------
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

        # ---------- Чёрный список номеров ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                phone TEXT PRIMARY KEY,
                created_at TIMESTAMP,
                admin_id BIGINT
            )
        """)

        # ---------- Ачивки ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                user_id BIGINT,
                achievement TEXT,
                earned_at TIMESTAMP,
                PRIMARY KEY (user_id, achievement)
            )
        """)

        # ---------- Ранги / уровни ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ranks (
                user_id BIGINT PRIMARY KEY,
                level INTEGER DEFAULT 1,
                xp INTEGER DEFAULT 0,
                updated_at TIMESTAMP
            )
        """)

        # ---------- API-ключи ----------
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

        # ---------- Подписки ----------
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

        # ---------- Аудит-лог ----------
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

        # ---------- Уведомления (для WebSocket) ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                title TEXT,
                message TEXT,
                type TEXT DEFAULT 'info',
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # ---------- Сессии для веб-панели ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_id TEXT PRIMARY KEY,
                user_id BIGINT,
                created_at TIMESTAMP,
                expires_at TIMESTAMP
            )
        """)

        # ---------- Индексы для скорости ----------
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_user ON qr_submissions(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_status ON qr_submissions(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_region ON qr_submissions(region)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_taken_by ON qr_submissions(taken_by)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_blacklist_phone ON blacklist(phone)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id)")

        # ---------- Заполнение начальными данными ----------
        # Операторы
        count_ops = await conn.fetchval("SELECT COUNT(*) FROM operators")
        if count_ops == 0:
            operators = [
                ("Билайн", 15.0, 12.0, -1, 50, "", 0),
                ("Газпром", 28.0, 22.0, -1, 50, "", 1),
                ("МТС", 18.0, 14.0, -1, 50, "", 2),
                ("Сбер", 12.0, 9.0, -1, 50, "", 3),
                ("ВТБ", 25.0, 20.0, -1, 50, "", 4),
                ("Добросвязь", 13.0, 10.0, -1, 50, "", 5),
                ("Мегафон", 14.0, 11.0, -1, 50, "", 6),
                ("Т2", 14.0, 11.0, -1, 50, "", 7),
                ("Тинькофф", 14.0, 11.0, -1, 50, "", 8),
                ("Миранда", 11.0, 9.0, -1, 50, "", 9),
                ("Волна", 12.0, 10.0, -1, 50, "", 10),
                ("Йота", 14.0, 11.0, -1, 50, "", 11),
            ]
            for op in operators:
                await conn.execute("""
                    INSERT INTO operators (name, price_hold, price_bh, slot_limit, min_minutes, conditions, sort_order)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
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
                # ... добавьте остальные регионы (можно скопировать из предыдущих ответов)
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

        # Кастомные тексты
        default_texts = {
            'welcome': '📄 Условия работы: ...',
            'faq': '**FAQ – Часто задаваемые вопросы** ...',
            'price_list': '**Актуальный прайс** ...',
        }
        for key, val in default_texts.items():
            await conn.execute("""
                INSERT INTO custom_texts (key, value, updated_at) VALUES ($1, $2, NOW())
                ON CONFLICT (key) DO NOTHING
            """, key, val)

        # Пароль для админа (по умолчанию 'admin123'). Хэш для 'admin123' = '240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9'
        # В реальности поменяйте на хэш своего пароля.
        default_admin_password_hash = "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9"
        await conn.execute("""
            UPDATE users SET password_hash = $1 WHERE user_id IN (SELECT unnest($2::bigint[]))
        """, default_admin_password_hash, ADMIN_IDS)

    print("✅ База данных PostgreSQL инициализирована со всеми таблицами и начальными данными.")

if __name__ == "__main__":
    # При запуске init_db.py нужно предварительно загрузить переменные окружения
    from dotenv import load_dotenv
    load_dotenv()
    from config import ADMIN_IDS  # импорт после загрузки .env
    asyncio.run(create_all_tables())