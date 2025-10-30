import asyncio
import logging
import asyncpg
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
MODERATOR_ID = 684261784

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
    return False

# --- ОЧЕРЕДЬ (одна на всех) ---
searching_queue = []

# --- ЦЕНТРАЛЬНЫЙ ПОИСК ---
async def start_search_loop():
    while True:
        if len(searching_queue) >= 2:
            user1 = searching_queue.pop(0)
            user2 = searching_queue.pop(0)
            
            await update_user(user1, partner_id=user2, state='chat')
            await update_user(user2, partner_id=user1, state='chat')
            
            await bot.send_message(user1, "Собеседник найден! Пиши.", reply_markup=get_chat_menu())
            await bot.send_message(user2, "Собеседник найден! Пиши.", reply_markup=get_chat_menu())
        else:
            await asyncio.sleep(1)

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
    await callback.message.edit_text(
        "Привет! Анонимный чат на двоих\n\n"
        "• Полная анонимность\n"
        "• Реальные собеседники\n"
        "• Бан за нарушения\n\n"
        "Готов? Нажми кнопку.",
        reply_markup=get_main_menu()
    )

# --- ПОИСК ---
@dp.callback_query(lambda c: c.data == "search")
async def search(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if await check_ban(user_id):
        return
    
    if user_id in searching_queue:
        await callback.answer("Ты уже в очереди!")
        return
    
    await update_user(user_id, state='searching')
    searching_queue.append(user_id)
    
    await callback.message.edit_text(
        "Ищем собеседника...\n\nОжидаем ещё одного человека.",
        reply_markup=get_searching_menu()
    )

@dp.callback_query(lambda c: c.data == "cancel_search")
async def cancel_search(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in searching_queue:
        searching_queue.remove(user_id)
    await update_user(user_id, state='menu')
    await callback.message.edit_text("Поиск отменён.", reply_markup=get_main_menu())

# --- ЖАЛОБА ---
@dp.callback_query(lambda c: c.data == "report")
async def report(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if not user or not user['partner_id']:
        await callback.answer("Чат завершён.", show_alert=True)
        return
    
    await callback.message.edit_text(
        "Напиши причину жалобы (1–100 символов):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="cancel_report")]
        ])
    )
    await update_user(user_id, state='reporting')

@dp.callback_query(lambda c: c.data == "cancel_report")
async def cancel_report(callback: types.CallbackQuery):
    await update_user(callback.from_user.id, state='chat')
    await callback.message.edit_text("Жалоба отменена.", reply_markup=get_chat_menu())

# --- 1. ЖАЛОБА ---
@dp.message(lambda m: m.text and (user := await get_user(m.from_user.id)) and user['state'] == 'reporting')
async def handle_report_reason(message: types.Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    reason = message.text.strip()
    
    if len(reason) > 100:
        await message.answer("Причина слишком длинная (макс. 100 символов).")
        return
    
    partner_id = user['partner_id']
    await add_report(user_id, partner_id)
    await message.answer("Жалоба отправлена. Спасибо!", reply_markup=get_chat_menu())
    await update_user(user_id, state='chat')
    
    count = await get_reports_count(partner_id)
    if count >= 3:
        await ban_user(partner_id)
        await bot.send_message(partner_id, "Ты забанен за жалобы.")
    
    await bot.send_message(MODERATOR_ID, f"Жалоба:\nОт: {user_id}\nНа: {partner_id}\nПричина: {reason}\nВсего: {count}")

# --- 2. ЧАТ ---
@dp.message(lambda m: m.text and (user := await get_user(m.from_user.id)) and user['state'] == 'chat' and user['partner_id'])
async def handle_chat_message(message: types.Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    await bot.send_message(user['partner_id'], message.text)

# --- СТОП ---
@dp.callback_query(lambda c: c.data == "stop")
async def stop(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if user and user['partner_id']:
        partner_id = user['partner_id']
        await update_user(partner_id, partner_id=None, state='menu')
        await bot.send_message(partner_id, "Собеседник завершил чат.", reply_markup=None)
    if user_id in searching_queue:
        searching_queue.remove(user_id)
    await update_user(user_id, partner_id=None, state='menu')
    await callback.message.edit_text("Чат завершён.", reply_markup=get_main_menu())

@dp.callback_query(lambda c: c.data == "next")
async def next_chat(callback: types.CallbackQuery):
    await stop(callback)
    await search(callback)

# --- Запуск ---
async def on_startup(app):
    await init_db()
    webhook_url = f"https://anonymous-chat-bot-7f1b.onrender.com/webhook"
    await bot.set_webhook(webhook_url)
    # Запускаем центральный поиск
    asyncio.create_task(start_search_loop())
    print("БОТ ЗАПУЩЕН! ОЧЕРЕДЬ — ОДНА, СООБЩЕНИЯ — 100%")

def main():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    app.on_startup.append(on_startup)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

if __name__ == "__main__":
    main()
