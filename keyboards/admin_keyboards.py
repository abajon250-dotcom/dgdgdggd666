from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def admin_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Непроверенные QR", callback_data="admin_pending")],
        [InlineKeyboardButton(text="💰 Изменить цены", callback_data="admin_prices")],
        [InlineKeyboardButton(text="🔄 Переключить режим сдачи", callback_data="admin_toggle_mode")],
        [InlineKeyboardButton(text="🎫 Управление слотами брони", callback_data="admin_slots")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users_stats")],
        [InlineKeyboardButton(text="💸 Выплаты", callback_data="admin_payouts")],
        [InlineKeyboardButton(text="💰 Заявки на вывод", callback_data="admin_withdraw_requests")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🧹 Очистить все непроверенные", callback_data="admin_clear_pending")]
    ])

def pending_actions(submission_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍💻 Взять в работу", callback_data=f"take_sub:{submission_id}")]
    ])

def work_actions(submission_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Засчитать выплату", callback_data=f"pay_sub:{submission_id}"),
         InlineKeyboardButton(text="🔄 Слетел", callback_data=f"fail_sub:{submission_id}")],
        [InlineKeyboardButton(text="🚫 Блок", callback_data=f"block_sub:{submission_id}")]
    ])

def operators_price_edit(operators):
    kb = []
    for op in operators:
        kb.append([InlineKeyboardButton(text=f"{op['name']} (ХОЛД: {op['price_hold']}$, БХ: {op['price_bh']}$)", callback_data=f"edit_price:{op['name']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def operators_slot_edit(operators):
    kb = []
    for op in operators:
        limit = op['slot_limit']
        limit_str = "∞" if limit == -1 else str(limit)
        kb.append([InlineKeyboardButton(text=f"{op['name']} (лимит: {limit_str})", callback_data=f"edit_slot:{op['name']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def mode_buttons(current_mode):
    text = "ХОЛД (30 мин)" if current_mode == "hold" else "БХ (сразу)"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Сейчас: {text}", callback_data="noop")],
        [InlineKeyboardButton(text="Переключить", callback_data="toggle_mode_confirm")]
    ])

def confirm_clear():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, очистить", callback_data="confirm_clear_pending")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="admin_back")]
    ])

def payout_list(users):
    kb = []
    for u in users:
        kb.append([InlineKeyboardButton(text=f"@{u['username']} - {u['earned_today']:.2f}$", callback_data=f"mark_paid:{u['user_id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)