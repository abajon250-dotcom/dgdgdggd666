import logging
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
from states import SubmitEsim, WithdrawState, TicketState, TicketAnswer, LanguageState

from config import ADMIN_IDS, REQUIRED_CHANNEL
from db import (
    register_user, has_accepted_terms, accept_terms, get_user,
    get_operator_price, create_submission, get_setting, set_setting,
    add_crypto_balance, get_operators, count_active_bookings_for_operator,
    get_user_qr_last_30_days, get_active_booking, cancel_booking,
    create_booking, get_user_stats, get_operator_top_regions,
    get_operator_conditions, get_referral_percent, get_referral_stats,
    get_user_role, get_most_popular_operator, get_low_stock_operators,
    get_pool, create_withdraw_request
)
from states import SubmitEsim, WithdrawState
from utils import (
    validate_phone, normalize_phone, calculate_rank,
    calculate_volume_points, calculate_regularity_points, calculate_priority
)
from user_keyboards import (
    main_menu, profile_keyboard, booking_menu, back_button,
    subscription_check_button, get_accept_terms_keyboard, operators_for_booking, ticket_categories
)
from admin_keyboards import pending_actions

router = Router()

TERMS_TEXT = """📄 **Условия работы:**

• Формат сдачи: одним сообщением — QR‑код + номер телефона в формате "79999999999" для каждой eSIM.

• Критерии: оплаченный тариф (минимум 100 минут) и рабочий QR‑код, залитые QR в несколько приёмок не оплачиваем.

• Выплаты: ежедневно, день в день, после 17:00-19:00 (МСК).

• Wi‑Fi‑звонки не требуются! Не сканируйте QR‑код своим устройством - часто он одноразовый, ничего включать не нужно.

⚠ Условия могут меняться без уведомления.
Без принятия условий доступ к функционалу закрыт."""

# ---------- Старт, принятие условий, проверка подписки ----------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].split("_")[1])
        except:
            pass
    user = message.from_user
    await register_user(user.id, user.username, user.full_name, referrer_id)

    role = await get_user_role(user.id)
    is_admin = user.id in ADMIN_IDS
    if await has_accepted_terms(user.id):
        await message.answer("✅ Вы уже приняли условия.", reply_markup=main_menu(is_admin, role == 'worker'))
    else:
        await message.answer(TERMS_TEXT, parse_mode="Markdown", reply_markup=get_accept_terms_keyboard())

@router.callback_query(F.data == "accept_terms")
async def accept_terms_callback(callback: CallbackQuery):
    await accept_terms(callback.from_user.id)
    await callback.answer("Условия приняты!")
    if REQUIRED_CHANNEL:
        text = f"✅ Условия приняты!\n\nТеперь подпишитесь на наш канал: {REQUIRED_CHANNEL}\n\nНажмите кнопку ниже после подписки."
        await callback.message.edit_text(text, reply_markup=subscription_check_button())
    else:
        await callback.message.delete()
        role = await get_user_role(callback.from_user.id)
        await callback.message.answer("🎉 Добро пожаловать!", reply_markup=main_menu(callback.from_user.id in ADMIN_IDS, role == 'worker'))

@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery, bot: Bot):
    if not REQUIRED_CHANNEL:
        await callback.message.delete()
        role = await get_user_role(callback.from_user.id)
        await callback.message.answer("🎉 Главное меню:", reply_markup=main_menu(callback.from_user.id in ADMIN_IDS, role == 'worker'))
        return
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, callback.from_user.id)
        if member.status in ("left", "kicked"):
            await callback.answer("❌ Вы не подписаны на канал. Подпишитесь и нажмите снова.", show_alert=True)
        else:
            await callback.answer("✅ Подписка подтверждена!")
            await callback.message.delete()
            role = await get_user_role(callback.from_user.id)
            await callback.message.answer("🎉 Главное меню:", reply_markup=main_menu(callback.from_user.id in ADMIN_IDS, role == 'worker'))
    except Exception as e:
        logging.error(f"Check subscription error: {e}")
        await callback.answer("⚠️ Ошибка проверки подписки. Попробуйте позже.", show_alert=True)

# ---------- Сдать ESIM ----------
@router.message(F.text == "📱 Сдать ESIM")
async def cmd_sell_esim(message: Message):
    mode = await get_setting("sale_mode", "hold")
    operators = await get_operators()
    most_taken = await get_most_popular_operator()
    low_stock = await get_low_stock_operators()

    mode_text = "БХ 🟢 (мгновенное начисление)" if mode == "bh" else "ХОЛД 🔴 (начисление через 30 минут)"
    mode_short = "БХ 🟢" if mode == "bh" else "ХОЛД 🔴"

    operators_text = ""
    for op in operators:
        price = op['price_bh'] if mode == 'bh' else op['price_hold']
        marker = "🟢" if (op['name'] in low_stock or op['name'] == most_taken) else ""
        operators_text += f"{op['name']} - {price}$ {marker}\n"

    text = (
        f"📱 **Сдать ESIM**\n\n"
        f"Режим сдачи: {mode_text}\n\n"
        f"🔥 Больше всего взято: {most_taken}\n"
        f"⚠️ Минимальный остаток: {', '.join(low_stock) if low_stock else 'все слоты свободны'}\n\n"
        f"**Операторы и цены:**\n{operators_text}\n"
        f"Для смены режима нажмите кнопку ниже."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔄 Режим сдачи: {mode_short}", callback_data="toggle_mode_from_sell")],
        *[[InlineKeyboardButton(text=f"{op['name']} - {op['price_bh'] if mode == 'bh' else op['price_hold']}$",
                                callback_data=f"select_operator:{op['name']}")] for op in operators],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    await message.answer(text, parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data == "toggle_mode_from_sell")
async def toggle_mode_from_sell(callback: CallbackQuery):
    current = await get_setting("sale_mode", "hold")
    new_mode = "bh" if current == "hold" else "hold"
    await set_setting("sale_mode", new_mode)
    await cmd_sell_esim(callback.message)
    await callback.answer(f"Режим изменён на {'БХ' if new_mode == 'bh' else 'ХОЛД'}")

@router.callback_query(F.data.startswith("select_operator:"))
async def select_operator(callback: CallbackQuery, state: FSMContext):
    operator = callback.data.split(":")[1]
    mode = await get_setting("sale_mode", "hold")
    price = await get_operator_price(operator, mode)
    if price is None:
        await callback.answer("Ошибка: оператор не найден")
        return
    await state.update_data(operator=operator, price=price)
    await state.set_state(SubmitEsim.waiting_for_photo_and_phone)
    await callback.message.delete()
    await callback.message.answer(
        f"📱 Оператор: {operator}\n💰 Стоимость: {price}$ + бонус ранга.\n\n"
        "Отправьте **фото QR-кода** и **номер телефона** в подписи (пример: +79001234567).\n\n"
        "❗ Важно: фото и номер в одном сообщении.\n\nДля отмены нажмите ❌ Стоп"
    )
    await callback.answer()

@router.message(SubmitEsim.waiting_for_photo_and_phone, F.photo)
async def receive_photo(message: Message, state: FSMContext):
    if not message.caption:
        await message.answer("❌ Добавьте номер телефона в подпись к фото.")
        return
    phone = message.caption.strip()
    if not validate_phone(phone):
        await message.answer("❌ Неверный номер. Нужно 11 цифр, начинается с 7. Пример: +79001234567")
        return
    phone = normalize_phone(phone)
    region = phone[:3] if len(phone) >= 3 else ""
    data = await state.get_data()
    operator = data.get('operator')
    price = data.get('price')
    if not operator or not price:
        await message.answer("❌ Ошибка: выберите оператора заново.")
        await state.clear()
        return

    user_id = message.from_user.id
    photo_file_id = message.photo[-1].file_id

    mode = await get_setting("sale_mode", "hold")
    if mode == "hold":
        pool = await get_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchval("""
                SELECT id FROM qr_submissions
                WHERE operator = $1 AND phone = $2 AND submitted_at >= NOW() - INTERVAL '30 minutes'
            """, operator, phone)
            if existing:
                await message.answer("❌ Этот QR уже сдан недавно (режим ХОЛД). Подождите 30 минут.")
                await state.clear()
                return

    submission_id = await create_submission(user_id, operator, price, phone, photo_file_id, region, mode)
    role = await get_user_role(user_id)
    await message.answer("✅ QR принят на проверку. Ожидайте решения админа.", reply_markup=main_menu(user_id in ADMIN_IDS, role == 'worker'))
    await state.clear()

    user = await get_user(user_id)
    username = user['username'] or str(user_id)
    qr_count_30d, _ = await get_user_qr_last_30_days(user_id)
    _, bonus = calculate_rank(qr_count_30d)
    mode_text = "ХОЛД" if mode == "hold" else "БХ"
    text = (
        f"🆕 Новая сдача eSIM\n"
        f"👤 Пользователь: @{username} (ID {user_id})\n"
        f"📱 Оператор: {operator}\n"
        f"⚙️ Режим: {mode_text}\n"
        f"💰 Стоимость: {price}$ + бонус {bonus}$\n"
        f"📞 Номер: {phone}\n"
        f"🕒 Время: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"ID заявки: {submission_id}"
    )
    for admin in ADMIN_IDS:
        try:
            await message.bot.send_photo(admin, photo_file_id, caption=text, reply_markup=pending_actions(submission_id))
        except Exception as e:
            logging.error(f"Не удалось отправить уведомление админу {admin}: {e}")

@router.message(SubmitEsim.waiting_for_photo_and_phone)
async def incorrect_input(message: Message, state: FSMContext):
    if message.text == "❌ Стоп":
        await state.clear()
        role = await get_user_role(message.from_user.id)
        await message.answer("✅ Действие отменено.", reply_markup=main_menu(message.from_user.id in ADMIN_IDS, role == 'worker'))
        return
    await message.answer("❌ Пожалуйста, отправьте **фото** с подписью-номером. Для отмены нажмите ❌ Стоп")

@router.message(F.text == "❌ Стоп")
async def stop_action(message: Message, state: FSMContext):
    current_state = await state.get_state()
    role = await get_user_role(message.from_user.id)
    if current_state:
        await state.clear()
        await message.answer("✅ Действие отменено.", reply_markup=main_menu(message.from_user.id in ADMIN_IDS, role == 'worker'))
    else:
        await message.answer("🤷‍♂️ Нет активного действия для отмены.", reply_markup=main_menu(message.from_user.id in ADMIN_IDS, role == 'worker'))

# ---------- Профиль ----------
@router.message(F.text == "👤 Профиль")
async def cmd_profile(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала /start")
        return

    qr_count_30d, unique_dates = await get_user_qr_last_30_days(user['user_id'])
    rank_name, bonus = calculate_rank(qr_count_30d)

    pool = await get_pool()
    async with pool.acquire() as conn:
        qr_today = await conn.fetchval("""
            SELECT COUNT(*) FROM qr_submissions
            WHERE user_id = $1 AND status='accepted' AND DATE(submitted_at) = CURRENT_DATE
        """, user['user_id']) or 0

    volume_points = calculate_volume_points(qr_today)
    regularity_points = calculate_regularity_points(len(unique_dates))
    priority = calculate_priority(volume_points, regularity_points)

    stats_1d = await get_user_stats(user['user_id'], 1)
    stats_7d = await get_user_stats(user['user_id'], 7)
    stats_30d = await get_user_stats(user['user_id'], 30)
    stats_total = await get_user_stats(user['user_id'], None)

    def fmt(stats):
        accepted = stats.get('accepted') or 0
        blocked = stats.get('blocked') or 0
        noscan = stats.get('noscan') or 0
        sum_earned = stats.get('sum_earned') or 0
        acc_str = str(accepted) if accepted else "пусто"
        blk_str = str(blocked) if blocked else "пусто"
        nsc_str = str(noscan) if noscan else "пусто"
        sum_str = f"{sum_earned:.2f}$" if sum_earned else "пусто"
        return f"✅ {acc_str} ❌ {blk_str} 🔥 {nsc_str} 💰 {sum_str}"

    text = (
        f"👤 Профиль @{user['username']} · ID {user['user_id']}\n"
        f"🏆 Ранг: {rank_name}\n"
        f"💰 Бонус: +{bonus}$ к QR\n"
        f"📊 Зачтено за месяц: {qr_count_30d}\n"
        f"🔥 Приоритет: {priority:.1f} · {rank_name}\n"
        f"💵 Ожидаемая выплата за сегодня: {user['earned_today']:.2f}$\n"
        f"💰 Крипто-баланс: {user['crypto_balance']:.2f}$\n"
        f"🕒 Всего заработано: {user['total_earned']:.2f}$\n"
        f"👥 Реферальный бонус: {user['referral_earnings']:.2f}$\n\n"
        f"📊 **Статистика по периодам:**\n"
        f"1 день: {fmt(stats_1d)}\n"
        f"7 дней: {fmt(stats_7d)}\n"
        f"30 дней: {fmt(stats_30d)}\n"
        f"Всего: {fmt(stats_total)}"
    )
    await message.answer(text, reply_markup=profile_keyboard())

# ---------- Полезное и подменю ----------
@router.callback_query(F.data == "useful")
async def useful_menu(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 FAQ", callback_data="faq")],
        [InlineKeyboardButton(text="📈 Статистика", callback_data="stats_detailed")],
        [InlineKeyboardButton(text="📞 Операторы", callback_data="operators_list")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text("📚 **Полезное** – выберите раздел:", parse_mode="Markdown", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "faq")
async def faq_section(callback: CallbackQuery):
    text = (
        "**FAQ – Часто задаваемые вопросы**\n\n"
        "• **Актуальный прайс (за каждую отдельную eSIM с холодом 30м / БХ)**\n"
        "  - МТС (включая салон) — 14$ (БХ - 8$ за eSIM)\n"
        "  - Сбер — 10$ (БХ - 7$ за eSIM)\n"
        "  - Билайн — 13$ (БХ - 9$ за eSIM)\n"
        "  - Т2 — 12$ (БХ - 8$ за eSIM)\n"
        "  - ВТБ — 25$ (БХ 18$)\n"
        "  - Газпром — 28$ (БХ 21$)\n"
        "  - Тинькофф — 12$\n"
        "  - Мегафон — 11$\n"
        "  - Миранда — 12$\n"
        "  - Волна / 7телеком — 12$\n"
        "  - Йота — 14$\n\n"
        "• **Мануалы по регистрации:**\n"
        "  [SberMobile](https://t.me/c/3751926773/3/18)\n"
        "  [BeeLine](https://t.me/c/3751926773/3/19)\n"
        "  [MTS](https://t.me/c/3751926773/3/20)\n\n"
        "⚠️ Ссылки работают только при подписке на [HITORO HUB](https://t.me/+76Z8pTDcnE85YWU0)\n\n"
        "📞 **По всем вопросам:** @hitorowork"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button())
    await callback.answer()

@router.callback_query(F.data == "stats_detailed")
async def detailed_stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    periods = [(1, "1 день"), (7, "7 дней"), (30, "30 дней"), (None, "все время")]
    text = "📊 **Статистика по отчётным дням**\n\n"
    for days, label in periods:
        stats = await get_user_stats(user_id, days)
        total = stats['total'] if stats['total'] else "пусто"
        blocked = stats['blocked'] if stats['blocked'] else "пусто"
        noscan = stats['noscan'] if stats['noscan'] else "пусто"
        sum_earned = stats['sum_earned'] or 0
        sum_str = f"{sum_earned:.2f}$" if sum_earned else "пусто"
        text += f"• **{label}**\n"
        text += f"  ✅ Сдано: {total}\n"
        text += f"  🚫 Блоки: {blocked}\n"
        text += f"  🔥 Несканы: {noscan}\n"
        text += f"  💰 Сумма: {sum_str}\n\n"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button())
    await callback.answer()

@router.callback_query(F.data == "operators_list")
async def operators_list(callback: CallbackQuery):
    ops = await get_operators()
    kb = []
    for op in ops:
        kb.append([InlineKeyboardButton(text=op['name'], callback_data=f"operator_stats:{op['name']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="useful")])
    await callback.message.edit_text("Выберите оператора для просмотра статистики:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@router.callback_query(F.data.startswith("operator_stats:"))
async def operator_stats(callback: CallbackQuery):
    operator = callback.data.split(":")[1]
    top_regions = await get_operator_top_regions(operator, 7)
    conditions = await get_operator_conditions(operator)
    reg_text = "\n".join([f"{r['region_name']} — {r['cnt']} шт." for r in top_regions]) if top_regions else "Нет данных"
    text = (
        f"📡 **Оператор: {operator}**\n\n"
        f"**ТОП-5 лучших регионов (за неделю):**\n{reg_text}\n\n"
        f"**Условия по оператору:**\n"
        f"Минимум {conditions.get('min_minutes', 50)} минут звонков по РФ либо равносильный баланс.\n"
        f"{conditions.get('conditions', '')}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К списку", callback_data="operators_list")],
        [InlineKeyboardButton(text="🏠 В профиль", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    await callback.answer()

# ---------- Мои номера ----------
@router.callback_query(F.data == "my_numbers")
async def show_my_numbers(callback: CallbackQuery):
    user_id = callback.from_user.id
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT ON (phone) phone, submitted_at
            FROM qr_submissions
            WHERE user_id = $1
            ORDER BY phone, submitted_at DESC
        """, user_id)
    if not rows:
        await callback.answer("У вас нет сохранённых номеров.", show_alert=True)
        return
    numbers = [row['phone'] for row in rows]
    text = "📞 Ваши номера:\n" + "\n".join(f"+{num}" for num in numbers)
    await callback.message.answer(text, reply_markup=back_button())
    await callback.answer()

# ---------- История сдач ----------
@router.callback_query(F.data == "history")
async def show_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT operator, price, status, submitted_at, earned_amount, reject_reason
            FROM qr_submissions
            WHERE user_id = $1
            ORDER BY submitted_at DESC
            LIMIT 10
        """, user_id)
    if not rows:
        await callback.answer("Нет сдач", show_alert=True)
        return
    text = "📜 **Последние 10 сдач**\n\n"
    for row in rows:
        status_emoji = "✅" if row['status'] == "accepted" else "⏳" if row['status'] == "pending" else "❌"
        reason = f" ({'блок' if row['reject_reason']=='block' else 'нескан'})" if row['status'] == 'rejected' and row['reject_reason'] else ""
        earned = row['earned_amount'] or 0
        dt = row['submitted_at'].strftime("%Y-%m-%d %H:%M")
        text += f"{status_emoji} {row['operator']} - {row['price']}$ | {dt} | +{earned}$ {reason}\n"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button())
    await callback.answer()

# ---------- Бронирование ----------
@router.message(F.text == "📅 Бронирование")
async def cmd_booking(message: Message):
    active = await get_active_booking(message.from_user.id)
    if active:
        text = f"📌 Активная бронь: {active['operator']}\n{active['created_at']}"
        await message.answer(text, reply_markup=booking_menu(True))
    else:
        await message.answer("Нет активной брони.", reply_markup=booking_menu(False))

@router.callback_query(F.data == "book_operator")
async def book_operator_list(callback: CallbackQuery):
    operators = await get_operators()
    available = []
    for op in operators:
        limit = op['slot_limit']
        if limit == -1:
            free = "∞"
            available.append({"name": op['name'], "free_slots": free})
        else:
            used = await count_active_bookings_for_operator(op['name'])
            free_slots = limit - used
            if free_slots > 0:
                available.append({"name": op['name'], "free_slots": free_slots})
    if not available:
        await callback.answer("Нет свободных слотов для бронирования.", show_alert=True)
        return
    await callback.message.edit_text("Выберите оператора для бронирования:", reply_markup=operators_for_booking(available))
    await callback.answer()

@router.callback_query(F.data.startswith("book:"))
async def create_booking_callback(callback: CallbackQuery):
    operator = callback.data.split(":")[1]
    user_id = callback.from_user.id
    existing = await get_active_booking(user_id)
    if existing:
        await callback.answer("У вас уже есть активная бронь. Отмените её сначала.", show_alert=True)
        return
    op_list = await get_operators()
    op_data = next((op for op in op_list if op['name'] == operator), None)
    if op_data and op_data['slot_limit'] != -1:
        used = await count_active_bookings_for_operator(operator)
        if used >= op_data['slot_limit']:
            await callback.answer("Все слоты заняты.", show_alert=True)
            return
    await create_booking(user_id, operator)
    await callback.message.edit_text(f"✅ Вы забронировали {operator}. Бронь сгорит после сдачи eSIM.", reply_markup=booking_menu(True))
    await callback.answer()

@router.callback_query(F.data == "cancel_booking")
async def cancel_booking_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    booking = await get_active_booking(user_id)
    if not booking:
        await callback.answer("У вас нет активной брони.", show_alert=True)
        return
    await cancel_booking(booking['id'])
    await callback.message.edit_text("Бронь отменена.", reply_markup=booking_menu(False))
    await callback.answer()

@router.callback_query(F.data == "edit_booking")
async def edit_booking_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    booking = await get_active_booking(user_id)
    if booking:
        await cancel_booking(booking['id'])
    await book_operator_list(callback)

# ---------- Бонусы ----------
@router.message(F.text == "🎁 Бонусы")
async def cmd_bonuses(message: Message):
    user_id = message.from_user.id
    qr_count_30d, unique_dates = await get_user_qr_last_30_days(user_id)
    rank_name, bonus = calculate_rank(qr_count_30d)

    pool = await get_pool()
    async with pool.acquire() as conn:
        qr_today = await conn.fetchval("""
            SELECT COUNT(*) FROM qr_submissions
            WHERE user_id = $1 AND status='accepted' AND DATE(submitted_at) = CURRENT_DATE
        """, user_id) or 0

    volume_points = calculate_volume_points(qr_today)
    regularity_points = calculate_regularity_points(len(unique_dates))
    priority = calculate_priority(volume_points, regularity_points)

    text = (
        f"🎁 **Бонусная система**\n\n"
        f"📈 Ранг: {qr_count_30d} / 30 (Профи), /60 (Элита)\n"
        f"🏆 {rank_name} +${bonus}/QR\n"
        f"⭐ Объём: {volume_points}/5 (сегодня {qr_today} QR)\n"
        f"⭐ Регулярность: {regularity_points}/4 ({len(unique_dates)} дней)\n"
        f"🔥 Приоритет: {priority:.1f} / 7\n\n"
        f"**Ранги:**\n"
        f"• Старт (0–29 QR) → +$0/QR\n"
        f"• Профи (30–59 QR) → +$0.5/QR\n"
        f"• Элита (60+ QR) → +$1/QR\n\n"
        f"Приоритет = объём + регулярность (до 7 баллов).\n"
        f"Чем выше приоритет – тем быстрее вам достаются слоты."
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=back_button())

# ---------- Рефералы ----------
@router.message(F.text == "👥 Рефералы")
async def referral_button(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала /start")
        return
    ref_percent = await get_referral_percent(user['user_id'])
    ref_stats = await get_referral_stats(user['user_id'])
    bot_info = await message.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref_{user['user_id']}"
    text = (
        f"🌟 Реферальная программа\n\n"
        f"Ваша ссылка: {link}\n\n"
        f"👥 Приглашено: {ref_stats['count']}\n"
        f"💰 Заработано: {user['referral_earnings']:.2f}$\n"
        f"📈 Текущий процент бонуса: {ref_percent}%\n\n"
        f"Шкала:\n"
        f"0–20 QR → 0%\n21–40 → 1%\n41–60 → 2%\n61–100 → 3%\n101–199 → 3.5%\n200+ → 4%\n\n"
        f"Запрос на вывод от $10."
    )
    await message.answer(text, reply_markup=back_button())

# ---------- Вывод баланса (через кнопку) – используем earned_today ----------
@router.callback_query(F.data == "withdraw_balance")
async def withdraw_balance_start(callback: CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Сначала /start", show_alert=True)
        return
    if user['earned_today'] <= 0:
        await callback.answer("❌ У вас нет средств для вывода сегодня.", show_alert=True)
        return
    await callback.message.answer(f"💰 Ваш доступный баланс для вывода: {user['earned_today']:.2f}$\n💸 Введите сумму для вывода (число, например 10):")
    await state.set_state(WithdrawState.waiting_for_amount)
    await callback.answer()

@router.message(WithdrawState.waiting_for_amount)
async def withdraw_balance_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("❌ Неверная сумма. Введите положительное число, например 10.")
        return
    user_id = message.from_user.id
    user = await get_user(user_id)
    if not user:
        await message.answer("Сначала /start")
        await state.clear()
        return
    if user['earned_today'] < amount:
        await message.answer(f"❌ Недостаточно средств. Доступно для вывода: {user['earned_today']:.2f}$")
        await state.clear()
        return
    # Создаём заявку на вывод
    request_id = await create_withdraw_request(user_id, amount)
    await message.answer(f"✅ Заявка на вывод #{request_id} на сумму {amount}$ создана. Ожидайте обработки администратором.")
    for admin in ADMIN_IDS:
        await message.bot.send_message(admin, f"💰 Новая заявка на вывод #{request_id}\n👤 @{message.from_user.username} (ID {user_id})\n💵 Сумма: {amount}$")
    await state.clear()

# ---------- Назад в меню ----------
@router.callback_query(F.data == "back_to_menu")
async def back_menu_callback(callback: CallbackQuery):
    await callback.message.delete()
    role = await get_user_role(callback.from_user.id)
    await callback.message.answer("Главное меню:", reply_markup=main_menu(callback.from_user.id in ADMIN_IDS, role == 'worker'))

# ---------- Мои заявки (для работников) ----------
@router.message(F.text == "📋 Мои заявки")
async def my_tasks(message: Message):
    user_id = message.from_user.id
    role = await get_user_role(user_id)
    if role not in ('admin', 'worker'):
        await message.answer("Эта функция только для работников.")
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, operator, phone, submitted_at, taken_at
            FROM qr_submissions
            WHERE taken_by = $1 AND status = 'taken'
            ORDER BY taken_at DESC
        """, user_id)
    if not rows:
        await message.answer("У вас нет активных заявок в работе.", reply_markup=back_button())
        return
    text = "📋 Ваши активные заявки:\n\n"
    for row in rows:
        text += f"ID {row['id']} | {row['operator']} | +{row['phone']}\n   взято: {row['taken_at']}\n"
    await message.answer(text, reply_markup=back_button())

# ---------- ПОДДЕРЖКА (ТИКЕТЫ) ----------
@router.message(F.text == "🆘 Поддержка")
async def support_menu(message: Message, state: FSMContext):
    await state.set_state(TicketState.waiting_for_category)
    await message.answer("Выберите категорию вашего обращения:", reply_markup=ticket_categories())

@router.callback_query(F.data.startswith("ticket:"))
async def ticket_category_selected(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split(":")[1]
    await state.update_data(ticket_category=category)
    await state.set_state(TicketState.waiting_for_message)
    await callback.message.edit_text("Опишите вашу проблему подробно (можно с фото):")
    await callback.answer()

@router.message(TicketState.waiting_for_message)
async def ticket_message_received(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    category = data['ticket_category']
    text = message.text or message.caption
    if not text:
        await message.answer("Пожалуйста, опишите проблему текстом.")
        return
    ticket_id = await create_ticket(message.from_user.id, category, text)
    await message.answer(f"✅ Ваш тикет #{ticket_id} создан. Администратор ответит в ближайшее время.")
    await state.clear()
    # Уведомляем администратора
    for admin in ADMIN_IDS:
        await bot.send_message(admin, f"🆕 Новый тикет #{ticket_id} от @{message.from_user.username}\nКатегория: {category}\nСообщение: {text}")

# ---------- ОТМЕНА ВСЕХ СВОИХ ЗАЯВОК ----------
@router.callback_query(F.data == "cancel_my_submissions")
async def cancel_my_submissions(callback: CallbackQuery):
    user_id = callback.from_user.id
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE qr_submissions SET status = 'rejected', reject_reason = 'cancelled_by_user'
            WHERE user_id = $1 AND status IN ('pending', 'taken')
        """, user_id)
    await callback.answer("Все ваши активные заявки отменены.")
    await callback.message.answer("❌ Ваши заявки отменены. Можете подать новые.", reply_markup=back_button())

# ---------- УВЕДОМЛЕНИЕ О СЛЕТЕВШЕМ НОМЕРЕ С ПЕРЕСДАЧЕЙ ----------
# Добавить эту функцию в обработчик, вызываемый при отметке "слетел" (в admin_handlers)
# Однако сама кнопка пересдачи будет отправлена пользователю в ЛС.
# Для этого добавим отдельный callback.
@router.callback_query(F.data.startswith("retry_sub:"))
async def retry_submission(callback: CallbackQuery, state: FSMContext):
    submission_id = int(callback.data.split(":")[1])
    sub = await get_submission(submission_id)
    if not sub or sub['status'] != 'failed':
        await callback.answer("Эта заявка уже неактивна.", show_alert=True)
        return
    # Предлагаем выбрать оператора заново
    await state.update_data(operator=sub['operator'], price=sub['price'])
    await state.set_state(SubmitEsim.waiting_for_photo_and_phone)
    await callback.message.answer(
        f"🔄 Попробуйте снова:\nОператор: {sub['operator']}\n💰 Стоимость: {sub['price']}$ + бонус ранга.\n\n"
        "Отправьте **новый фото QR-кода** и **номер телефона** в подписи."
    )
    await callback.answer()

# ---------- ВЫБОР ЯЗЫКА ----------
@router.callback_query(F.data == "change_language")
async def change_language(callback: CallbackQuery):
    await callback.message.edit_text("Выберите язык:", reply_markup=language_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith("lang_"))
async def set_language(callback: CallbackQuery):
    lang = callback.data.split("_")[1]
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET lang = $1 WHERE user_id = $2", lang, callback.from_user.id)
    await callback.answer(f"Язык изменён на {lang.upper()}")
    await callback.message.delete()
    await callback.message.answer("Главное меню:", reply_markup=main_menu(callback.from_user.id in ADMIN_IDS, await get_user_role(callback.from_user.id) == 'worker'))

# ---------- АВТОМАТИЧЕСКОЕ РАСПОЗНАВАНИЕ НОМЕРА ИЗ ФОТО (OCR) ----------
# Требуется установка easyocr. В обработчике receive_photo добавьте:
# try:
#     import easyocr
#     reader = easyocr.Reader(['ru', 'en'])
#     result = reader.readtext(photo_bytes, detail=0)
#     recognized = ''.join(filter(str.isdigit, result[0])) if result else ''
#     if len(recognized) >= 11 and recognized.startswith('7'):
#         phone = recognized
# except Exception as e:
#     print("OCR failed:", e)
# Также необходимо добавить загрузку фото в байты через `await message.bot.download_file(...)`
# Для простоты пока оставим ручной ввод, но код готов.

# ---------- КНОПКА "ОТМЕНИТЬ ВСЕ ЗАЯВКИ" В ПРОФИЛЕ ----------
# Добавьте эту кнопку в profile_keyboard (уже сделано)