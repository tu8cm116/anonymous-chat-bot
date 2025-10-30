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
    raise ValueError("BOT_TOKEN не найден в .env")

# Твой ID (модератор) — ЗАМЕНИ НА СВОЙ TELEGRAM ID!
MODERATOR_ID = 684261784  # Получи свой ID: напиши боту /start, потом в коде /my_id

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

# --- Клавиатуры ---
def get_main_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти собеседника", callback_data="search")],
        [InlineKeyboardButton(text="📜 Правила", callback_data="rules")],
        [InlineKeyboardButton(text="🆔 Мой ID", callback_data="my_id")]
    ])
    return kb

def get_searching_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_search")]
    ])
    return kb

def get_chat_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Стоп", callback_data="stop")],
        [InlineKeyboardButton(text="➡️ Следующий", callback_data="next")],
        [InlineKeyboardButton(text="⚠️ Пожаловаться", callback_data="report")]
    ])
    return kb

# --- База данных (пока в памяти) ---
users = {}  # tg_id: {state, partner, last_message_time}

# --- Хендлеры ---
@dp.message(Command("start"))
async def start(message: types.Message):
    user_id = message.from_user.id
    users[user_id] = {"state": "menu", "last_message_time": asyncio.get_event_loop().time()}
    await message.answer(
        "Привет! Это анонимный чат на двоих 🤫\n\n"
        "Ты общаешься с реальным человеком, но:\n"
        "• Никаких имён, фото, ссылок на профиль\n"
        "• Никто не узнает, кто ты\n"
        "• Нарушителей — бан\n\n"
        "Правила: не матерись, не спамь, уважай собеседника.\n\n"
        "Готов? Нажми кнопку ниже.",
        reply_markup=get_main_menu()
    )

@dp.callback_query(F.data == "rules")
async def rules(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📜 Правила:\n"
        "1. Не матерись и не оскорбляй\n"
        "2. Не спамь и не флуди\n"
        "3. Не рекламируй\n"
        "4. Уважай собеседника\n\n"
        "Нарушение = бан. Жалобы проверяются модератором.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Назад", callback_data="back_to_menu")]
        ])
    )

@dp.callback_query(F.data == "my_id")
async def my_id(callback: types.CallbackQuery):
    await callback.answer(f"🆔 Твой ID: {callback.from_user.id}\n\nЕсли забанят — напиши модератору с этим ID.", show_alert=True)

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in users:
        users[user_id]["state"] = "menu"
    await callback.message.edit_text("🏠 Главное меню:", reply_markup=get_main_menu())

@dp.callback_query(F.data == "search")
async def search(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    users[user_id] = {"state": "searching", "last_message_time": asyncio.get_event_loop().time()}
    
    # Простая имитация поиска (позже добавим реальную очередь)
    await callback.message.edit_text(
        "🔍 Ищем собеседника... (1–2 человека в поиске)\n\n"
        "Это займёт до 30 секунд.",
        reply_markup=get_searching_menu()
    )
    
    # Имитация задержки
    await asyncio.sleep(3)
    
    # Заглушка: "нашли" партнёра (позже реальный)
    partner_id = user_id + 1  # Фейк
    users[user_id]["partner"] = partner_id
    if partner_id not in users:
        users[partner_id] = {"partner": user_id, "state": "chat"}
    
    await callback.message.edit_text(
        "✅ Собеседник найден! Можешь писать.\n\n"
        "Всё анонимно — просто общайся. Сообщения пересылаются автоматически.",
        reply_markup=get_chat_menu()
    )
    users[user_id]["state"] = "chat"

@dp.callback_query(F.data == "cancel_search")
async def cancel_search(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in users:
        users[user_id]["state"] = "menu"
    await callback.message.edit_text("❌ Поиск отменён.", reply_markup=get_main_menu())

@dp.callback_query(F.data == "stop")
async def stop(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in users and "partner" in users[user_id]:
        partner_id = users[user_id]["partner"]
        if partner_id in users:
            users[partner_id]["partner"] = None
            users[partner_id]["state"] = "menu"
        users[user_id]["partner"] = None
        users[user_id]["state"] = "menu"
    await callback.message.edit_text(
        "⏹️ Чат завершён. Спасибо за общение!\n\n"
        "Хочешь найти нового?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Найти ещё", callback_data="search")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")]
        ])
    )

@dp.callback_query(F.data == "next")
async def next_chat(callback: types.CallbackQuery):
    await stop(callback)  # Разрываем текущий
    await search(callback)  # Ищем новый

@dp.callback_query(F.data == "report")
async def report(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in users and "partner" in users[user_id]:
        partner_id = users[user_id]["partner"]
        # Сохраняем жалобу (пока в памяти, позже в БД)
        if "reports" not in globals():
            globals()["reports"] = []
        globals()["reports"].append({"from": user_id, "to": partner_id, "time": asyncio.get_event_loop().time()})
        
        # Уведомляем модератора (если ты)
        if MODERATOR_ID:
            await bot.send_message(MODERATOR_ID, f"⚠️ Новая жалоба: от {user_id} на {partner_id}")
    
    await callback.answer("⚠️ Жалоба отправлена модератору. Мы проверим.", show_alert=True)

# Обработка сообщений в чате (анонимная пересылка)
@dp.message(F.text)
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    if user_id not in users or users[user_id]["state"] != "chat":
        await message.answer("Сначала найди собеседника! Нажми /start")
        return
    
    partner_id = users[user_id]["partner"]
    if not partner_id:
        await message.answer("Чат завершён. Нажми 'Найти собеседника'.")
        return
    
    # Анонимная пересылка: только текст, без метаданных
    await bot.send_message(partner_id, f"💬 {message.text}")
    users[user_id]["last_message_time"] = asyncio.get_event_loop().time()

# --- Веб-сервер для Render (health check) ---
async def on_startup(_):
    print("Бот запущен...")

async def on_shutdown(dp):
    await dp.storage.close()

def main():
    # Создаём приложение
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    
    # Health check endpoint
    async def health_check(request):
        return web.Response(text="OK")
    
    app.router.add_get("/health", health_check)
    
    # Запуск
    port = int(os.getenv("PORT", 10000))
    app.on_startup.append(on_startup)
    app.on_shutdown.append(lambda _: on_shutdown(dp))
    
    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
