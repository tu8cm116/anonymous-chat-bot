import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import os
from dotenv import load_dotenv
from database import *

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
MODERATOR_ID = 684261784  # Твой ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

# --- Клавиатуры ---
def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Найти собеседника", callback_data="search")],
        [InlineKeyboardButton(text="Правила", callback_data="rules")],
        [InlineKeyboardButton(text="Мой ID", callback_data="my_id")]
    ])

def get_searching_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="cancel_search")]
    ])

def get_chat_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Стоп", callback_data="stop")],
        [InlineKeyboardButton(text="Следующий", callback_data="next")],
        [InlineKeyboardButton(text="Пожаловаться", callback_data="report")]
    ])

# --- Проверка бана ---
async def check_ban(user_id):
    if await is_banned(user_id):
        await bot.send_message(user_id, "Ты забанен. Обжалуй у модератора.")
        return True
    return false

# --- Хендлеры ---
@dp.message(Command("start"))
async def start(message: types.Message):
    user_id = message.from_user.id
    if await check_ban(user_id):
        return
    await update_user(user_id, state='menu')
    await message.answer(
        "Привет! Анонимный чат на двоих\n\n"
        "• Полная анонимность\n"
        "• Реальные собеседники\n"
        "• Бан за нарушения\n\n"
        "Готов? Нажми кнопку.",
        reply_markup=get_main_menu()
    )

@dp.callback_query(lambda c: c.data == "my_id")
async def my_id(callback: types.CallbackQuery):
    await callback.answer(f"Твой ID: {callback.from_user.id}", show_alert=True)

@dp.callback_query(lambda c: c.data == "rules")
async def rules(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Правила:\n1. Нет мата\n2. Нет спама\n3. Нет рекламы\n4. Уважение\n\nНарушение = бан",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="back_to_menu")]
        ])
    )

@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    await update_user(callback.from_user.id, state='menu')
    await callback.message.edit_text("Главное меню:", reply_markup=get_main_menu())

@dp.callback_query(lambda c: c.data == "search")
async def search(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if await check_ban(user_id):
        return
    await update_user(user_id, state='searching')
    await callback.message.edit_text(
        "Ищем собеседника...\n\nОжидаем ещё одного человека.",
        reply_markup=get_searching_menu()
    )
    asyncio.create_task(search_partner(user_id))

async def search_partner(user_id):
    await asyncio.sleep(2)
    partner_id = await find_partner(user_id)
    if partner_id:
        await update_user(user_id, partner_id=partner_id, state='chat')
        await update_user(partner_id, partner_id=user_id, state='chat')
        # КНОПКИ ВНИЗУ, НОВЫМ СООБЩЕНИЕМ
        await bot.send_message(user_id, "Собеседник найден! Пиши.", reply_markup=get_chat_menu())
        await bot.send_message(partner_id, "Собеседник найден! Пиши.", reply_markup=get_chat_menu())
    else:
        await update_user(user_id, state='menu')
        await bot.send_message(user_id, "Никого нет. Попробуй позже.", reply_markup=get_main_menu())

@dp.callback_query(lambda c: c.data == "cancel_search")
async def cancel_search(callback: types.CallbackQuery):
    await update_user(callback.from_user.id, state='menu')
    await callback.message.edit_text("Поиск отменён.", reply_markup=get_main_menu())

@dp.callback_query(lambda c: c.data == "stop")
async def stop(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if user and user['partner_id']:
        await update_user(user['partner_id'], partner_id=None, state='menu')
        await bot.send_message(user['partner_id'], "Собеседник завершил чат.")
    await update_user(user_id, partner_id=None, state='menu')
    await callback.message.edit_text("Чат завершён.", reply_markup=get_main_menu())

@dp.callback_query(lambda c: c.data == "next")
async def next_chat(callback: types.CallbackQuery):
    await stop(callback)
    await search(callback)

@dp.callback_query(lambda c: c.data == "report")
async def report(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if user and user['partner_id']:
        await add_report(user_id, user['partner_id'])
        count = await get_reports_count(user['partner_id'])
        if count >= 3:
            await ban_user(user['partner_id'])
            await bot.send_message(user['partner_id'], "Ты забанен за жалобы.")
        await bot.send_message(MODERATOR_ID, f"Жалоба: {user_id} → {user['partner_id']} (всего: {count})")
    await callback.answer("Жалоба отправлена.", show_alert=True)

@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    if user and user['state'] == 'chat' and user['partner_id']:
        await bot.send_message(user['partner_id'], message.text)

# --- МОДЕРАЦИЯ (ИСПРАВЛЕНО) ---
@dp.message(Command("mod"))
async def mod_panel(message: types.Message):
    if message.from_user.id != MODERATOR_ID:
        return
    stats = await get_stats()
    await message.answer(
        f"Панель модератора:\n\n"
        f"Пользователей: {stats[0]}\n"
        f"Чатов: {stats[1]}\n"
        f"Жалоб: {stats[2]}\n\n"
        f"/ban ID — бан\n"
        f"/unban ID — разбан\n"
        f"/user ID — профиль"
    )

@dp.message(Command("ban"))
async def ban_cmd(message: types.Message):
    if message.from_user.id != MODERATOR_ID:
        return
    try:
        tg_id = int(message.text.split()[1])
        await ban_user(tg_id)
        await message.answer(f"{tg_id} забанен на 24ч.")
    except:
        await message.answer("Использование: /ban ID")

@dp.message(Command("unban"))
async def unban_cmd(message: types.Message):
    if message.from_user.id != MODERATOR_ID:
        return
    try:
        tg_id = int(message.text.split()[1])
        await unban_user(tg_id)
        await message.answer(f"{tg_id} разбанен.")
    except:
        await message.answer("Использование: /unban ID")

@dp.message(Command("user"))
async def user_info(message: types.Message):
    if message.from_user.id != MODERATOR_ID:
        return
    try:
        tg_id = int(message.text.split()[1])
        user = await get_user(tg_id)
        reports = await get_reports_count(tg_id)
        banned = "Да" if await is_banned(tg_id) else "Нет"
        state = user['state'] if user else "Неизвестен"
        await message.answer(
            f"Пользователь {tg_id}:\n"
            f"Статус: {state}\n"
            f"Жалоб: {reports}\n"
            f"Забанен: {banned}"
        )
    except:
        await message.answer("Использование: /user ID")

# --- Запуск ---
async def on_startup(app):
    await init_db()
    webhook_url = f"https://anonymous-chat-bot-7f1b.onrender.com/webhook"
    await bot.set_webhook(webhook_url)
    print("Бот запущен! Кнопки внизу, /mod работает!")

def main():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    app.on_startup.append(on_startup)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

if __name__ == "__main__":
    main()
