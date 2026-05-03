from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def main_menu(is_admin: bool = False, is_worker: bool = False):
    buttons = [
        [KeyboardButton(text="📱 Сдать ESIM")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📅 Бронирование")],
        [KeyboardButton(text="🎁 Бонусы"), KeyboardButton(text="👥 Рефералы")],
        [KeyboardButton(text="🆘 Поддержка")]   # новая кнопка
    ]
    if is_worker or is_admin:
        buttons.append([KeyboardButton(text="📋 Мои заявки")])
    if is_admin:
        buttons.append([KeyboardButton(text="👑 Админ панель")])
    buttons.append([KeyboardButton(text="❌ Стоп")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_accept_terms_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ПРИНЯТЬ УСЛОВИЯ", callback_data="accept_terms")]
    ])

def subscription_check_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]
    ])

def profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Полезное", callback_data="useful")],
        [InlineKeyboardButton(text="📞 Мои номера", callback_data="my_numbers"),
         InlineKeyboardButton(text="👥 Рефералы", callback_data="ref_system")],
        [InlineKeyboardButton(text="💸 Вывести баланс", callback_data="withdraw_balance"),
         InlineKeyboardButton(text="📜 История сдач", callback_data="history")],
        [InlineKeyboardButton(text="🌐 Язык", callback_data="change_language")]   # новая кнопка
    ])

def language_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
         InlineKeyboardButton(text="🇺🇸 English", callback_data="lang_en")],
        [InlineKeyboardButton(text="🇺🇦 Українська", callback_data="lang_ua")]
    ])

def ticket_categories():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Проблема с выплатой", callback_data="ticket:payment")],
        [InlineKeyboardButton(text="⚙️ Техническая ошибка", callback_data="ticket:tech")],
        [InlineKeyboardButton(text="📖 Вопрос по мануалу", callback_data="ticket:manual")],
        [InlineKeyboardButton(text="❓ Другое", callback_data="ticket:other")]
    ])

def cancel_submissions_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить все свои заявки", callback_data="cancel_my_submissions")]
    ])

def retry_submission_button(submission_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data=f"retry_sub:{submission_id}")]
    ])

def booking_menu(has_booking: bool):
    if has_booking:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Забронировать", callback_data="book_operator")],
            [InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_booking"),
             InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_booking")]
        ])
    else:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Забронировать", callback_data="book_operator")]
        ])

def operators_for_booking(operators):
    kb = []
    for op in operators:
        kb.append([InlineKeyboardButton(text=f"{op['name']} (свободно {op['free_slots']})", callback_data=f"book:{op['name']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def back_button():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]])