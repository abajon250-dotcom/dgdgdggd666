import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery

from config import ADMIN_IDS
from db import (
    get_submission, get_user_qr_last_30_days,
    accept_submission_from_hold, get_user, get_operators,
    count_active_bookings_for_operator, create_booking,
    get_active_booking, cancel_booking, get_setting, hold_submission,
    accept_submission_now, mark_submission_failed, mark_submission_blocked,
    take_submission, get_user_role
)
from utils import calculate_rank   # <-- правильный импорт
from keyboards.user_keyboards import main_menu, booking_menu, operators_for_booking
from keyboards.admin_keyboards import work_actions

router = Router()
hold_tasks = {}

# ---------- Таймер для холда ----------
async def start_hold_timer(bot: Bot, submission_id: int, base_price: float, user_id: int, delay_seconds: float):
    await asyncio.sleep(delay_seconds)
    sub = await get_submission(submission_id)
    if sub and sub['status'] == 'hold':
        qr_count_30d, _ = await get_user_qr_last_30_days(user_id)
        _, bonus = calculate_rank(qr_count_30d)   # здесь был calc_rank
        earned = base_price + bonus
        await accept_submission_from_hold(submission_id, earned)
        try:
            await bot.send_message(user_id, f"✅ Ваш QR прошёл холд! Начислено {earned:.2f}$ (цена {base_price}$ + бонус {bonus}$).", reply_markup=main_menu(user_id in ADMIN_IDS))
        except:
            pass
    if submission_id in hold_tasks:
        del hold_tasks[submission_id]

# ---------- Взятие заявки в работу ----------
@router.callback_query(F.data.startswith("take_sub:"))
async def take_submission_callback(callback: CallbackQuery, bot: Bot):
    worker_id = callback.from_user.id
    submission_id = int(callback.data.split(":")[1])
    sub = await get_submission(submission_id)
    if not sub or sub['status'] != 'pending':
        await callback.answer("Заявка уже обработана или недоступна", show_alert=True)
        return
    role = await get_user_role(worker_id)
    if role not in ('admin', 'worker'):
        await callback.answer("У вас нет прав брать заявки в работу", show_alert=True)
        return
    await take_submission(submission_id, worker_id)
    try:
        await bot.send_message(sub['user_id'], "👨‍💻 Ваш номер взят в работу! Ожидайте решения.")
    except:
        pass
    # Показываем кнопки работы над заявкой
    await callback.message.edit_caption(
        caption=f"🔄 Заявка #{submission_id} в работе у @{callback.from_user.username}\nОператор: {sub['operator']}\nНомер: {sub['phone']}",
        reply_markup=work_actions(submission_id)
    )
    await callback.answer()

# ---------- Засчитать выплату ----------
@router.callback_query(F.data.startswith("pay_sub:"))
async def pay_submission_callback(callback: CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    submission_id = int(callback.data.split(":")[1])
    sub = await get_submission(submission_id)
    if not sub or sub['status'] != 'taken':
        await callback.answer("Заявка не в работе или уже обработана", show_alert=True)
        return
    mode = await get_setting("sale_mode", "hold")
    if mode == "bh":
        qr_count_30d, _ = await get_user_qr_last_30_days(sub['user_id'])
        _, bonus = calculate_rank(qr_count_30d)   # здесь тоже был calc_rank
        earned = sub['price'] + bonus
        await accept_submission_now(submission_id, admin_id, earned)
        await bot.send_message(sub['user_id'], f"✅ Ваш номер принят! Начислено {earned:.2f}$ (цена {sub['price']}$ + бонус {bonus}$).")
        await callback.message.edit_caption(caption=f"✅ Заявка #{submission_id} засчитана (админ @{callback.from_user.username})", reply_markup=None)
    else:
        hold_until = datetime.now() + timedelta(minutes=30)
        await hold_submission(submission_id, admin_id, hold_until)
        delay = 30 * 60
        task = asyncio.create_task(start_hold_timer(bot, submission_id, sub['price'], sub['user_id'], delay))
        hold_tasks[submission_id] = task
        await bot.send_message(sub['user_id'], f"✅ Номер принят и переведён в холд на 30 минут. Начисление будет автоматически.")
        await callback.message.edit_caption(caption=f"⏳ Заявка #{submission_id} в холде до {hold_until.strftime('%H:%M')} (админ @{callback.from_user.username})", reply_markup=None)
    await callback.answer()

# ---------- Слетел ----------
@router.callback_query(F.data.startswith("fail_sub:"))
async def fail_submission_callback(callback: CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    submission_id = int(callback.data.split(":")[1])
    sub = await get_submission(submission_id)
    if not sub or sub['status'] != 'taken':
        await callback.answer("Заявка не в работе", show_alert=True)
        return
    await mark_submission_failed(submission_id, admin_id)
    await bot.send_message(sub['user_id'], "🔄 Ваш номер слетел (не засчитан).")
    await callback.message.edit_caption(caption=f"❌ Заявка #{submission_id} помечена как слетевшая (админ @{callback.from_user.username})", reply_markup=None)
    await callback.answer()

# ---------- Блок ----------
@router.callback_query(F.data.startswith("block_sub:"))
async def block_submission_callback(callback: CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    submission_id = int(callback.data.split(":")[1])
    sub = await get_submission(submission_id)
    if not sub or sub['status'] != 'taken':
        await callback.answer("Заявка не в работе", show_alert=True)
        return
    await mark_submission_blocked(submission_id, admin_id)
    await bot.send_message(sub['user_id'], "🚫 Ваш номер заблокирован (не засчитан).")
    await callback.message.edit_caption(caption=f"🚫 Заявка #{submission_id} заблокирована (админ @{callback.from_user.username})", reply_markup=None)
    await callback.answer()

# ---------- Бронирование (callback'и, если они здесь) ----------
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
        await callback.answer("У вас уже есть активная бронь.", show_alert=True)
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