import asyncio
import logging
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

import database as db

# --- Настройки ---
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- Клавиатуры ---
menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("🔎 Поиск собеседника")],
        [KeyboardButton("🚫 Жалоба"), KeyboardButton("⛔ Завершить чат")]
    ],
    resize_keyboard=True
)

# --- /start ---
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    await db.update_user(message.from_user.id, state="menu", partner_id=None, last_active=datetime.now())
    await message.answer("Привет 👋\nНажми «🔎 Поиск собеседника», чтобы начать чат.", reply_markup=menu_kb)

# --- Поиск собеседника ---
@dp.message(F.text == "🔎 Поиск собеседника")
async def search_partner(message: types.Message):
    tg_id = message.from_user.id

    if await db.is_banned(tg_id):
        await message.answer("🚫 Ты временно заблокирован. Попробуй позже.")
        return

    await db.update_user(tg_id, state="searching", last_active=datetime.now())
    partner_id = await db.find_partner(tg_id)

    if partner_id:
        # Соединяем пользователей
        await db.update_user(tg_id, state="chat", partner_id=partner_id)
        await db.update_user(partner_id, state="chat", partner_id=tg_id)
        await bot.send_message(partner_id, "💬 Найден собеседник! Можешь писать.", reply_markup=menu_kb)
        await message.answer("💬 Собеседник найден! Можешь писать.", reply_markup=menu_kb)
    else:
        await message.answer("⌛ Ищем тебе собеседника... Подожди немного.")

# --- Отправка сообщений между собеседниками ---
@dp.message(F.text & ~F.text.in_({"🔎 Поиск собеседника", "🚫 Жалоба", "⛔ Завершить чат"}))
async def relay_message(message: types.Message):
    user = await db.get_user(message.from_user.id)

    if not user or user["state"] != "chat" or not user["partner_id"]:
        await message.answer("Ты сейчас не в чате. Нажми «🔎 Поиск собеседника».")
        return

    partner_id = user["partner_id"]
    if partner_id:
        await bot.send_message(partner_id, message.text)
        await db.update_user(message.from_user.id, last_active=datetime.now())
        await db.update_user(partner_id, last_active=datetime.now())

# --- Завершить чат ---
@dp.message(F.text == "⛔ Завершить чат")
async def end_chat(message: types.Message):
    user = await db.get_user(message.from_user.id)
    if user and user["partner_id"]:
        partner_id = user["partner_id"]
        await db.update_user(partner_id, state="menu", partner_id=None)
        await bot.send_message(partner_id, "❌ Собеседник покинул чат.", reply_markup=menu_kb)

    await db.update_user(message.from_user.id, state="menu", partner_id=None)
    await message.answer("✅ Чат завершён.", reply_markup=menu_kb)

# --- Жалоба ---
@dp.message(F.text == "🚫 Жалоба")
async def report_partner(message: types.Message):
    user = await db.get_user(message.from_user.id)
    if not user or not user["partner_id"]:
        await message.answer("Ты не в чате, жаловаться не на кого 😅")
        return

    partner_id = user["partner_id"]
    await db.add_report(message.from_user.id, partner_id)
    count = await db.get_reports_count(partner_id)

    if count >= 3:  # бан после 3 жалоб
        await db.ban_user(partner_id, hours=24)
        await db.update_user(partner_id, state="menu", partner_id=None)
        await bot.send_message(partner_id, "🚫 Ты получил слишком много жалоб и был временно заблокирован на 24 часа.")
        await bot.send_message(message.from_user.id, "✅ Жалоба отправлена. Пользователь заблокирован.")
    else:
        await bot.send_message(message.from_user.id, "✅ Жалоба отправлена. Спасибо за отзывчивость.")
        await bot.send_message(partner_id, "⚠️ На тебя поступила жалоба. Соблюдай правила общения.")

    # Завершаем чат после жалобы
    await db.update_user(message.from_user.id, state="menu", partner_id=None)
    await db.update_user(partner_id, state="menu", partner_id=None)

# --- /stats ---
@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    total_users, active_chats, total_reports = await db.get_stats()
    await message.answer(
        f"📊 Статистика:\n"
        f"👤 Пользователей: {total_users}\n"
        f"💬 Активных чатов: {active_chats}\n"
        f"🚨 Жалоб: {total_reports}"
    )

# --- Запуск ---
async def main():
    await db.init_db()
    print("Бот запущен ✅")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
