from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from db import get_user, register_user
from keyboards.user_keyboards import back_button

router = Router()

@router.message(Command("start"))
async def cmd_start_with_ref(message: Message):
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].split("_")[1])
        except:
            pass
    user = message.from_user
    await register_user(user.id, user.username, user.full_name, referrer_id)
    # Далее обычный старт с условиями
    # (скопируйте код из cmd_start, но без повторной регистрации)

@router.message(Command("referral"))
async def show_referral_info(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала выполните /start")
        return
    ref_link = f"https://t.me/YourBotUsername?start=ref_{user['user_id']}"
    text = f"🌟 Ваша реферальная ссылка:\n{ref_link}\n\nВы заработали с рефералов: {user['referral_earnings']:.2f}$\nПриглашайте друзей — получайте бонус $1 за каждого!"
    await message.answer(text, reply_markup=back_button())