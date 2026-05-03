import asyncio
from db import init_db_pool, get_pool

async def create_tables_and_data():
    print("Создаю/обновляю базу данных PostgreSQL...")
    await init_db_pool()
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Таблица пользователей
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
                permissions TEXT DEFAULT ''
            )
        """)

        # Таблица заявок
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

        # Таблица операторов
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

        # Таблица бронирований
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                operator TEXT,
                created_at TIMESTAMP,
                used BOOLEAN DEFAULT FALSE
            )
        """)

        # Таблица настроек
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Таблица ежедневной статистики
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                date DATE PRIMARY KEY,
                total_qr INTEGER DEFAULT 0,
                total_earned REAL DEFAULT 0
            )
        """)

        # Таблица регионов
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS regions (
                code TEXT PRIMARY KEY,
                name TEXT
            )
        """)

        # Таблица заявок на вывод
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

        # Индексы
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_user ON qr_submissions(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_status ON qr_submissions(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_region ON qr_submissions(region)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_taken_by ON qr_submissions(taken_by)")

        # Заполнение начальными данными
        count = await conn.fetchval("SELECT COUNT(*) FROM operators")
        if count == 0:
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

        await conn.execute("INSERT INTO settings (key, value) VALUES ('sale_mode', 'hold') ON CONFLICT (key) DO NOTHING")

        count = await conn.fetchval("SELECT COUNT(*) FROM regions")
        if count == 0:
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

    print("✅ База данных PostgreSQL успешно создана и заполнена начальными данными.")

if __name__ == "__main__":
    asyncio.run(create_tables_and_data())