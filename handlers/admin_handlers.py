import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS
from db import (
    get_pool, get_pending_submissions, get_operators,
    update_operator_prices, update_operator_slot_limit, get_setting, set_setting,
    get_today_stats, get_top_users, get_user, add_crypto_balance,
    reject_submission, get_submission, accept_submission_now,
    get_user_qr_last_30_days, accept_submission_from_hold, hold_submission,
    get_total_users_count, get_new_users_count,
    get_pending_withdraw_requests, update_withdraw_request,
    get_pending_submissions_by_mode
)
from states import AdminSetPrice, AdminSetSlot, BroadcastState
from utils import calculate_rank
from keyboards.admin_keyboards import (
    admin_main_menu, pending_actions, operators_price_edit,
    operators_slot_edit, mode_buttons, confirm_clear, payout_list,
    work_actions
)
from keyboards.user_keyboards import main_menu

router = Router()
hold_tasks = {}

async def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ------------------------------------------------------------
# Главное меню и общие callback
# ------------------------------------------------------------
@router.message(F.text == "👑 Админ панель")
async def admin_panel_button(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Нет прав")
        return
    await message.answer("👑 Панель администратора", reply_markup=admin_main_menu())

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    await callback.message.edit_text("👑 Панель администратора", reply_markup=admin_main_menu())
    await callback.answer()

# ------------------------------------------------------------
# Непроверенные заявки (только для текущего режима)
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_pending")
async def list_pending(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    current_mode = await get_setting("sale_mode", "hold")
    pending = await get_pending_submissions_by_mode(current_mode, 20)
    if not pending:
        await callback.message.edit_text(f"Нет непроверенных заявок в режиме {current_mode.upper()}.", reply_markup=admin_main_menu())
        return
    for sub in pending:
        text = f"ID: {sub['id']}\nОператор: {sub['operator']}\nЦена: {sub['price']}$\nНомер: {sub['phone']}\nВремя: {sub['submitted_at']}"
        await callback.message.answer_photo(sub['photo_file_id'], caption=text, reply_markup=pending_actions(sub['id']))
    await callback.message.delete()
    await callback.answer()

# ------------------------------------------------------------
# Изменение цен (две цены: холд и БХ)
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_prices")
async def edit_prices_menu(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    operators = await get_operators()
    kb = []
    for op in operators:
        kb.append([InlineKeyboardButton(
            text=f"{op['name']} (ХОЛД: {op['price_hold']}$, БХ: {op['price_bh']}$)",
            callback_data=f"edit_price:{op['name']}"
        )])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    await callback.message.edit_text("Выберите оператора для изменения цен:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@router.callback_query(F.data.startswith("edit_price:"))
async def start_edit_price(callback: CallbackQuery, state: FSMContext):
    operator = callback.data.split(":")[1]
    await state.update_data(edit_operator=operator)
    await state.set_state(AdminSetPrice.waiting_for_price)
    await callback.message.edit_text(f"Введите новые цены для {operator} в формате: цена_холд цена_бх\nПример: 15 12")
    await callback.answer()

@router.message(AdminSetPrice.waiting_for_price)
async def set_new_prices(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    try:
        parts = message.text.split()
        if len(parts) != 2:
            raise ValueError
        price_hold = float(parts[0].replace(',', '.'))
        price_bh = float(parts[1].replace(',', '.'))
    except:
        await message.answer("❌ Неверный формат. Введите две цены через пробел, например: 15 12")
        return
    data = await state.get_data()
    operator = data['edit_operator']
    await update_operator_prices(operator, price_hold, price_bh)
    await message.answer(f"✅ Цены для {operator} обновлены:\nХОЛД: {price_hold}$, БХ: {price_bh}$")
    await state.clear()

# ------------------------------------------------------------
# Переключение режима ХОЛД/БХ
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_toggle_mode")
async def toggle_mode_menu(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    current = await get_setting("sale_mode", "hold")
    await callback.message.edit_text(f"Текущий режим: {'ХОЛД' if current == 'hold' else 'БХ'}", reply_markup=mode_buttons(current))
    await callback.answer()

@router.callback_query(F.data == "toggle_mode_confirm")
async def toggle_mode(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    current = await get_setting("sale_mode", "hold")
    new_mode = "bh" if current == "hold" else "hold"
    await set_setting("sale_mode", new_mode)
    await callback.message.edit_text(f"Режим изменён на: {'БХ' if new_mode == 'bh' else 'ХОЛД'}", reply_markup=admin_main_menu())
    await callback.answer()

# ------------------------------------------------------------
# Управление слотами брони
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_slots")
async def slots_menu(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    operators = await get_operators()
    await callback.message.edit_text("Выберите оператора для установки лимита слотов:", reply_markup=operators_slot_edit(operators))
    await callback.answer()

@router.callback_query(F.data.startswith("edit_slot:"))
async def start_edit_slot(callback: CallbackQuery, state: FSMContext):
    operator = callback.data.split(":")[1]
    await state.update_data(slot_operator=operator)
    await state.set_state(AdminSetSlot.waiting_for_slot_limit)
    await callback.message.edit_text(f"Введите лимит слотов для {operator} (число, -1 безлимит, 0 недоступно):")
    await callback.answer()

@router.message(AdminSetSlot.waiting_for_slot_limit)
async def set_slot_limit(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    try:
        limit = int(message.text)
    except:
        await message.answer("Введите целое число.")
        return
    data = await state.get_data()
    operator = data['slot_operator']
    await update_operator_slot_limit(operator, limit)
    await message.answer(f"Лимит слотов для {operator} установлен: {limit if limit != -1 else 'безлимит'}")
    await state.clear()

# ------------------------------------------------------------
# Статистика (общая + пользователи)
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    today_stats = await get_today_stats()
    top_users = await get_top_users(5)
    total_users = await get_total_users_count()
    new_today = await get_new_users_count(1)
    new_week = await get_new_users_count(7)
    text = (
        f"📊 **Статистика за сегодня:**\n"
        f"✅ Зачтено QR: {today_stats['total_qr']}\n"
        f"💰 Сумма: {today_stats['total_earned']:.2f}$\n\n"
        f"👥 **Пользователи:**\n"
        f"Всего: {total_users} | за сегодня: +{new_today} | за 7 дней: +{new_week}\n\n"
        f"🏆 **Топ-5 по общему заработку:**\n"
    )
    for i, u in enumerate(top_users, 1):
        user = await get_user(u['user_id'])
        name = f"@{user['username']}" if user and user['username'] else f"ID {u['user_id']}"
        text += f"{i}. {name} — {u['total_earned']:.2f}$\n"
    await callback.message.edit_text(text, reply_markup=admin_main_menu())
    await callback.answer()

# ------------------------------------------------------------
# Отдельная кнопка пользователей (опционально)
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_users_stats")
async def admin_users_stats(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    total = await get_total_users_count()
    today = await get_new_users_count(1)
    week = await get_new_users_count(7)
    text = (
        f"👥 **Статистика пользователей**\n\n"
        f"📊 Всего зарегистрировано: {total}\n"
        f"✅ За сегодня: {today}\n"
        f"📆 За 7 дней: {week}"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=admin_main_menu())
    await callback.answer()

# ------------------------------------------------------------
# Выплаты (список earned_today)
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_payouts")
async def payouts_list(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, username, earned_today FROM users WHERE earned_today > 0")
        users = [{"user_id": r['user_id'], "username": r['username'], "earned_today": r['earned_today']} for r in rows]
    if not users:
        await callback.message.edit_text("Нет пользователей для выплаты сегодня.", reply_markup=admin_main_menu())
        return
    await callback.message.edit_text("💸 Пользователи к выплате:", reply_markup=payout_list(users))
    await callback.answer()

@router.callback_query(F.data.startswith("mark_paid:"))
async def mark_paid(callback: CallbackQuery):
    uid = int(callback.data.split(":")[1])
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET earned_today = 0 WHERE user_id = $1", uid)
    await callback.answer("Пользователь отмечен как выплаченный")
    await callback.message.delete()
    await callback.message.answer("Главное меню админа", reply_markup=admin_main_menu())

# ------------------------------------------------------------
# Очистка непроверенных заявок
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_clear_pending")
async def confirm_clear(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    await callback.message.edit_text("Вы уверены, что хотите удалить все непроверенные заявки?", reply_markup=confirm_clear())
    await callback.answer()

@router.callback_query(F.data == "confirm_clear_pending")
async def clear_pending(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM qr_submissions WHERE status = 'pending'")
    await callback.message.edit_text("Все непроверенные заявки удалены.", reply_markup=admin_main_menu())
    await callback.answer()

# ------------------------------------------------------------
# Крипто-баланс (пополнение)
# ------------------------------------------------------------
@router.message(Command("add_crypto"))
async def add_crypto(message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Использование: /add_crypto <user_id> <сумма>")
        return
    try:
        uid = int(args[1])
        amount = float(args[2])
    except:
        await message.answer("Неверный формат")
        return
    await add_crypto_balance(uid, amount)
    await message.answer(f"Крипто-баланс пользователя {uid} пополнен на {amount}$")

# ------------------------------------------------------------
# Рассылка
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(BroadcastState.waiting_for_message)
    await callback.message.edit_text("📢 Введите текст сообщения для рассылки (можно с фото, видео, документом).\nДля отмены /cancel")
    await callback.answer()

@router.message(BroadcastState.waiting_for_message)
async def broadcast_send(message: Message, state: FSMContext, bot: Bot):
    if not await is_admin(message.from_user.id):
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        user_ids = [r['user_id'] for r in rows]
    if not user_ids:
        await message.answer("Нет пользователей.")
        await state.clear()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отправить", callback_data="confirm_broadcast")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")]
    ])
    await state.update_data(broadcast_message=message)
    await message.answer(f"Будет отправлено {len(user_ids)} пользователям. Начать?", reply_markup=kb)

@router.callback_query(F.data == "confirm_broadcast")
async def broadcast_confirm(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not await is_admin(callback.from_user.id):
        return
    data = await state.get_data()
    orig: Message = data.get('broadcast_message')
    if not orig:
        await callback.answer("Сообщение не найдено")
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        user_ids = [r['user_id'] for r in rows]
    success = 0
    fail = 0
    for uid in user_ids:
        try:
            if orig.text:
                await bot.send_message(uid, orig.text, parse_mode="HTML")
            elif orig.photo:
                await bot.send_photo(uid, orig.photo[-1].file_id, caption=orig.caption)
            elif orig.video:
                await bot.send_video(uid, orig.video.file_id, caption=orig.caption)
            elif orig.document:
                await bot.send_document(uid, orig.document.file_id, caption=orig.caption)
            else:
                await bot.send_message(uid, "Сообщение от администратора")
            success += 1
        except:
            fail += 1
    await callback.message.edit_text(f"✅ Рассылка завершена. Успешно: {success}, Ошибок: {fail}")
    await state.clear()
    await callback.answer()

# ------------------------------------------------------------
# Заявки на вывод
# ------------------------------------------------------------
@router.callback_query(F.data == "admin_withdraw_requests")
async def list_withdraw_requests(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    requests = await get_pending_withdraw_requests()
    if not requests:
        await callback.message.edit_text("Нет активных заявок на вывод.", reply_markup=admin_main_menu())
        return
    for req in requests:
        user = await get_user(req['user_id'])
        text = f"Заявка #{req['id']}\n👤 @{user['username']} (ID {user['user_id']})\n💰 {req['amount']}$\n🕒 {req['requested_at']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Выплачено", callback_data=f"withdraw_paid:{req['id']}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"withdraw_reject:{req['id']}")]
        ])
        await callback.message.answer(text, reply_markup=kb)
    await callback.message.delete()
    await callback.answer()

from states import CryptoCheckState

# ... остальной код

@router.callback_query(F.data.startswith("withdraw_paid:"))
async def ask_crypto_check(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    req_id = int(callback.data.split(":")[1])
    await state.update_data(withdraw_request_id=req_id)
    await state.set_state(CryptoCheckState.waiting_for_check)
    await callback.message.answer("🔗 Введите крипто-чек (ссылку на транзакцию или платёж):")
    await callback.answer()

@router.message(CryptoCheckState.waiting_for_check)
async def process_crypto_check(message: Message, state: FSMContext, bot: Bot):
    if not await is_admin(message.from_user.id):
        return
    check_link = message.text.strip()
    data = await state.get_data()
    req_id = data['withdraw_request_id']
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id, amount FROM withdraw_requests WHERE id = $1 AND status = 'pending'", req_id)
        if not row:
            await message.answer("❌ Заявка уже обработана.")
            await state.clear()
            return
        user_id = row['user_id']
        amount = row['amount']
        # Списываем с earned_today
        await conn.execute("UPDATE users SET earned_today = earned_today - $1 WHERE user_id = $2", amount, user_id)
        await update_withdraw_request(req_id, 'paid', message.from_user.id)
    # Отправляем пользователю крипто-чек
    user = await get_user(user_id)
    if user:
        try:
            await bot.send_message(user_id, f"✅ Вам выплачено {amount}$.\n🔗 Чек: {check_link}")
        except:
            pass
    await message.answer(f"✅ Выплата по заявке #{req_id} подтверждена. Чек отправлен пользователю.")
    await state.clear()

@router.callback_query(F.data.startswith("withdraw_reject:"))
async def withdraw_reject(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    req_id = int(callback.data.split(":")[1])
    await update_withdraw_request(req_id, 'rejected', callback.from_user.id)
    await callback.answer("Заявка отклонена")
    await callback.message.delete()

# ---------- ЧЁРНЫЙ СПИСОК ----------
@router.message(Command("blacklist_add"))
async def blacklist_add(message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /blacklist_add <номер>")
        return
    phone = args[1]
    await add_to_blacklist(phone, message.from_user.id)
    await message.answer(f"✅ Номер {phone} добавлен в чёрный список.")

@router.message(Command("blacklist_remove"))
async def blacklist_remove(message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /blacklist_remove <номер>")
        return
    phone = args[1]
    await remove_from_blacklist(phone)
    await message.answer(f"✅ Номер {phone} удалён из чёрного списка.")

@router.message(Command("blacklist_list"))
async def blacklist_list(message: Message):
    if not await is_admin(message.from_user.id):
        return
    numbers = await get_blacklist()
    if not numbers:
        await message.answer("Чёрный список пуст.")
        return
    text = "🚫 **Чёрный список номеров:**\n" + "\n".join(numbers)
    await message.answer(text, parse_mode="Markdown")

# ---------- ТИКЕТЫ ПОДДЕРЖКИ (админская часть) ----------
@router.callback_query(F.data == "admin_tickets")
async def admin_tickets_menu(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    tickets = await get_open_tickets()
    if not tickets:
        await callback.message.edit_text("Нет открытых тикетов.", reply_markup=admin_main_menu())
        return
    for ticket in tickets:
        user = await get_user(ticket['user_id'])
        text = f"Тикет #{ticket['id']}\n👤 @{user['username']} (ID {user['user_id']})\n📂 Категория: {ticket['category']}\n💬 {ticket['message']}\n🕒 {ticket['created_at']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Ответить", callback_data=f"answer_ticket:{ticket['id']}")]
        ])
        await callback.message.answer(text, reply_markup=kb)
    await callback.message.delete()
    await callback.answer()

@router.callback_query(F.data.startswith("answer_ticket:"))
async def answer_ticket_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    ticket_id = int(callback.data.split(":")[1])
    await state.update_data(answer_ticket_id=ticket_id)
    await state.set_state(TicketAnswer.waiting_for_response)
    await callback.message.answer("Введите ответ на тикет (можно с фото):")
    await callback.answer()

@router.message(TicketAnswer.waiting_for_response)
async def answer_ticket_response(message: Message, state: FSMContext, bot: Bot):
    if not await is_admin(message.from_user.id):
        return
    data = await state.get_data()
    ticket_id = data['answer_ticket_id']
    response_text = message.text or message.caption
    if not response_text:
        await message.answer("Ответ не может быть пустым.")
        return
    # Получаем информацию о тикете
    pool = await get_pool()
    async with pool.acquire() as conn:
        ticket = await conn.fetchrow("SELECT user_id FROM tickets WHERE id = $1", ticket_id)
        if not ticket:
            await message.answer("Тикет не найден")
            await state.clear()
            return
        user_id = ticket['user_id']
        await answer_ticket(ticket_id, response_text, message.from_user.id)
    # Отправляем ответ пользователю
    await bot.send_message(user_id, f"✅ Администратор ответил на ваш тикет:\n{response_text}")
    await message.answer(f"✅ Ответ на тикет #{ticket_id} отправлен.")
    await state.clear()

# ---------- КАСТОМНЫЕ ТЕКСТЫ (приветствие, прайс, FAQ) ----------
@router.message(Command("set_text"))
async def set_text(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /set_text <ключ> <новый текст>\nДоступные ключи: welcome, faq, price_list")
        return
    key, value = args[0].split(maxsplit=1)[1], args[1]
    await set_custom_text(key, value)
    await message.answer(f"✅ Текст для ключа '{key}' обновлён.")

@router.message(Command("get_text"))
async def get_text(message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /get_text <ключ>")
        return
    key = args[1]
    text = await get_custom_text(key)
    await message.answer(f"Текущий текст для '{key}':\n{text}")

# ---------- РАСШИРЕННАЯ СТАТИСТИКА ДЛЯ АДМИНА ----------
@router.message(Command("stats_advanced"))
async def stats_advanced(message: Message):
    if not await is_admin(message.from_user.id):
        return
    hourly = await get_hourly_stats()
    avg_time = await get_avg_processing_time()
    top_ops = await get_top_operators(5)
    text = "📊 **Расширенная статистика**\n\n"
    text += f"⏱️ Среднее время обработки заявки: {avg_time:.1f} мин.\n\n"
    text += "🏆 **Топ операторов (за 7 дней):**\n"
    for op in top_ops:
        text += f"• {op['operator']}: {op['count']} шт.\n"
    text += "\n📈 **Заявки по часам (за 24 часа):**\n"
    for h in hourly:
        text += f"{int(h['hour'])}:00 – всего {h['total']}, принято {h['accepted']}\n"
    await message.answer(text, parse_mode="Markdown")

@router.message(Command("export_stats"))
async def export_stats(message: Message):
    if not await is_admin(message.from_user.id):
        return
    # Экспорт в CSV (можно расширить)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, username, total_earned, earned_today, total_qr, crypto_balance FROM users")
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "username", "total_earned", "earned_today", "total_qr", "crypto_balance"])
    for row in rows:
        writer.writerow([row['user_id'], row['username'], row['total_earned'], row['earned_today'], row['total_qr'], row['crypto_balance']])
    await message.answer_document(io.BytesIO(output.getvalue().encode()), filename="users_stats.csv")

# ---------- УПРАВЛЕНИЕ АЧИВКАМИ ----------
@router.message(Command("grant_achievement"))
async def grant_achievement_cmd(message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Использование: /grant_achievement <user_id> <achievement>")
        return
    user_id = int(args[1])
    ach = args[2]
    await grant_achievement(user_id, ach)
    await message.answer(f"✅ Ачивка '{ach}' выдана пользователю {user_id}")

# ---------- ОТМЕНА ВСЕХ ЗАЯВОК ПОЛЬЗОВАТЕЛЯ (админ) ----------
@router.message(Command("cancel_user_submissions"))
async def cancel_user_submissions(message: Message):
    if not await is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /cancel_user_submissions <user_id>")
        return
    user_id = int(args[1])
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE qr_submissions SET status = 'rejected', reject_reason = 'cancelled_by_admin' WHERE user_id = $1 AND status IN ('pending', 'taken')", user_id)
    await message.answer(f"✅ Все активные заявки пользователя {user_id} отменены.")