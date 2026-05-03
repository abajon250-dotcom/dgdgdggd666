import io
import asyncio
import aiosqlite
from aiogram import Router, F
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import Command
from config import ADMIN_IDS
from db import DATABASE

router = Router()

@router.message(Command("backup"))
async def backup_db(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Нет прав")
        return
    # Читаем файл базы данных
    with open(DATABASE, "rb") as f:
        data = f.read()
    await message.answer_document(BufferedInputFile(data, filename="esim_bot_backup.db"))
    await message.answer("Бэкап создан и отправлен.")

@router.message(Command("restore"))
async def restore_db(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Нет прав")
        return
    if not message.document:
        await message.answer("Пришлите файл дампа .db с командой /restore")
        return
    file = await message.bot.get_file(message.document.file_id)
    # Скачиваем файл
    downloaded = await message.bot.download_file(file.file_path)
    # Сохраняем поверх текущей БД (сначала закрываем соединения)
    # В реальном проекте надо остановить все обращения к БД, здесь просто перезаписываем
    with open(DATABASE, "wb") as f:
        f.write(downloaded.getvalue())
    await message.answer("База данных восстановлена. Перезапустите бота командой /restart_bot (если реализовано).")