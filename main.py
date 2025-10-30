import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
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

# --- КЛАВИАТУРЫ ---
# 1. МЕНЮ — ВВЕРХУ (Inline)
def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Найти собеседника", callback_data="search")],
        [InlineKeyboardButton(text="Правила", callback_data="rules"),
         InlineKeyboardButton(text="Мой ID", callback_data="my_id")]
    ])

# 2. ПОИСК — ВВЕРХУ (Inline)
def get_searching_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="cancel_search")]
    ])

# 3. ЧАТ — ВНИЗУ (Reply)
def get_chat_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Стоп"), KeyboardButton(text="Следующий")],
            [KeyboardButton(text="Пожаловаться")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Напиши сообщение..."
    )

# --- Проверка бана ---
async def check_ban(user_id):
    if await is_banned(user_id):
        await bot.send_message(user_id, "Ты забанен. Обжалуй у модератора.")
        return True
    return False

# --- ОЧЕРЕДЬ ---
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

# --- СТАРТ ---
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

# --- INLINE КНОПКИ (вверху) ---
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

# --- ПОИСК (Inline) ---
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

# --- ОТМЕНА ПОИСКА ---
@dp.callback_query(lambda c: c.data == "cancel_search")
async def cancel_search(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in searching_queue:
        searching_queue.remove(user_id)
    await update_user(user_id, state='menu')
    await callback.message.edit_text("Поиск отменён.", reply_markup=get_main_menu())

# --- КНОПКИ ЧАТА: СТОП, СЛЕДУЮЩИЙ, ПОЖАЛОВАТЬСЯ (Reply) ---
@dp.message(lambda m: m.text in ["Стоп", "Следующий", "Пожаловаться"])
async def handle_chat_buttons(message: types.Message):
    text = message.text
    user_id = message.from_user.id
    user = await get_user(user_id)

    # --- СТОП ---
    if text == "Стоп":
        if user and user['partner_id']:
            partner_id = user['partner_id']
            await update_user(partner_id, partner_id=None, state='menu')
            await bot.send_message(partner_id, "Собеседник завершил чат.")
        if user_id in searching_queue:
            searching_queue.remove(user_id)
        await update_user(user_id, partner_id=None, state='menu')
        await message.answer("Чат завершён.", reply_markup=get_main_menu())
        return

    # --- СЛЕДУЮЩИЙ ---
    if text == "Следующий":
        if user and user['partner_id']:
            partner_id = user['partner_id']
            await update_user(partner_id, partner_id=None, state='menu')
            await bot.send_message(partner_id, "Собеседник ищет нового.")
        if user_id in searching_queue:
            searching_queue.remove(user_id)
        await update_user(user_id, partner_id=None, state='searching')
        searching_queue.append(user_id)
        await message.answer("Ищем нового собеседника...", reply_markup=get_searching_menu())
        return

    # --- ПОЖАЛОВАТЬСЯ ---
    if text == "Пожаловаться":
        if not user or not user['partner_id']:
            await message.answer("Чат завершён.")
            return
        await message.answer(
            "Напиши причину жалобы (1–100 символов):",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="Отмена")]],
                resize_keyboard=True
            )
        )
        await update_user(user_id, state='reporting')
        return

# --- ОТМЕНА ЖАЛОБЫ ---
@dp.message(lambda m: m.text == "Отмена")
async def cancel_report(message: types.Message):
    user = await get_user(message.from_user.id)
    if user and user['state'] == 'reporting':
        await update_user(message.from_user.id, state='chat')
        await message.answer("Жалоба отменена.", reply_markup=get_chat_menu())

# --- ПРИЧИНА ЖАЛОБЫ ---
@dp.message(lambda m: m.text and (user := await get_user(m.from_user.id)) and user['state'] == 'reporting')
async def handle_report_reason(message: types.Message):
    reason = message.text.strip()
    if len(reason) > 100:
        await message.answer("Причина слишком длинная (макс. 100 символов).")
        return
    
    user_id = message.from_user.id
    partner_id = (await get_user(user_id))['partner_id']
    await add_report(user_id, partner_id)
    await message.answer("Жалоба отправлена. Спасибо!", reply_markup=get_chat_menu())
    await update_user(user_id, state='chat')
    
    count = await get_reports_count(partner_id)
    if count >= 3:
        await ban_user(partner_id)
        await bot.send_message(partner_id, "Ты забанен за жалобы.")
    
    await bot.send_message(MODERATOR_ID, f"Жалоба:\nОт: {user_id}\nНа: {partner_id}\nПричина: {reason}\nВсего: {count}")

# --- ОБЫЧНЫЕ СООБЩЕНИЯ В ЧАТЕ ---
@dp.message(lambda m: m.text)
async def handle_chat(message: types.Message):
    user = await get_user(message.from_user.id)
    if not user or user['state'] != 'chat' or not user['partner_id']:
        return
    await bot.send_message(user['partner_id'], message.text)

# --- Запуск ---
async def on_startup(app):
    await init_db()
    webhook_url = f"https://anonymous-chat-bot-7f1b.onrender.com/webhook"
    await bot.set_webhook(webhook_url)
    asyncio.create_task(start_search_loop())
    print("БОТ ЗАПУЩЕН! КНОПКИ ВНИЗУ — ТОЛЬКО В ЧАТЕ! СТОП И СЛЕДУЮЩИЙ — РАБОТАЮТ!")

def main():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    app.on_startup.append(on_startup)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

if __name__ == "__main__":
    main()
