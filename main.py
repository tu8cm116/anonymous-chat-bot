import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import os
from dotenv import load_dotenv

# Загружаем .env
load_dotenv()

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден")

# Твой ID (модератор) — ЗАМЕНИ НА СВОЙ!
MODERATOR_ID = 123456789  # ← ВСТАВЬ СВОЙ ID ИЗ "Мой ID"

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

# --- Клавиатуры ---
def get_main_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Найти собеседника", callback_data="search")],
        [InlineKeyboardButton(text="Правила", callback_data="rules")],
        [InlineKeyboardButton(text="Мой ID", callback_data="my_id")]
    ])
    return kb

def get_searching_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="cancel_search")]
    ])
    return kb

def get_chat_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Стоп", callback_data="stop")],
        [InlineKeyboardButton(text="Следующий", callback_data="next")],
        [InlineKeyboardButton(text="Пожаловаться", callback_data="report")]
    ])
    return kb

# --- База данных (в памяти) ---
users = {}

# --- Хендлеры ---
@dp.message(Command("start"))
async def start(message: types.Message):
    user_id = message.from_user.id
    users[user_id] = {"state": "menu"}
    await message.answer(
        "Привет! Это анонимный чат на двоих\n\n"
        "Ты общаешься с реальным человеком, но:\n"
        "• Никаких имён, фото, ссылок\n"
        "• Никто не узнает, кто ты\n"
        "• Нарушителей — бан\n\n"
        "Правила: не матерись, не спамь, уважай собеседника.",
        reply_markup=get_main_menu()
    )

@dp.callback_query(F.data == "rules")
async def rules(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Правила:\n"
        "1. Не матерись\n"
        "2. Не спамь\n"
        "3. Не рекламируй\n"
        "4. Уважай собеседника\n\n"
        "Нарушение = бан",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="back_to_menu")]
        ])
    )

@dp.callback_query(F.data == "my_id")
async def my_id(callback: types.CallbackQuery):
    await callback.answer(f"Твой ID: {callback.from_user.id}", show_alert=True)

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    users[callback.from_user.id]["state"] = "menu"
    await callback.message.edit_text("Главное меню:", reply_markup=get_main_menu())

@dp.callback_query(F.data == "search")
async def search(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    users[user_id] = {"state": "searching"}
    await callback.message.edit_text(
        "Ищем собеседника... (1 человек в поиске)\n"
        "Это займёт до 30 секунд.",
        reply_markup=get_searching_menu()
    )
    await asyncio.sleep(3)
    partner_id = 999999999
    users[user_id]["partner"] = partner_id
    users[partner_id] = {"partner": user_id, "state": "chat"}
    await callback.message.edit_text(
        "Собеседник найден! Можешь писать.",
        reply_markup=get_chat_menu()
    )

@dp.callback_query(F.data == "cancel_search")
async def cancel_search(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    users[user_id]["state"] = "menu"
    await callback.message.edit_text("Поиск отменён.", reply_markup=get_main_menu())

@dp.message()
async def echo(message: types.Message):
    user_id = message.from_user.id
    if user_id not in users or users[user_id]["state"] != "chat":
        return
    partner_id = users[user_id]["partner"]
    await bot.send_message(partner_id, message.text)

# --- Веб-сервер для Render ---
async def on_startup(app):
    webhook_url = f"https://anonymous-chat-bot-7f1b.onrender.com/webhook"
    await bot.set_webhook(webhook_url)
    print(f"Webhook установлен: {webhook_url}")

async def on_shutdown(app):
    await bot.delete_webhook()
    print("Webhook удалён")

def main():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    
    # Health check
    async def health(request):
        return web.Response(text="OK")
    app.router.add_get("/health", health)
    
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    
    port = int(os.getenv("PORT", 10000))
    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
