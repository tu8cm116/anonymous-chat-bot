import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
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
def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Найти собеседника")],
            [KeyboardButton(text="Правила"), KeyboardButton(text="Мой ID")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие..."
    )

def get_searching_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отмена")]],
        resize_keyboard=True,
        input_field_placeholder="Ищем собеседника..."
    )

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

# --- КНОПКИ МЕНЮ ---
@dp.message(lambda m: m.text == "Мой ID")
async def my_id(message: types.Message):
    await message.answer(f"Твой ID: {message.from_user.id}")

@dp.message(lambda m: m.text == "Правила")
async def rules(message: types.Message):
    await message.answer(
        "Правила:\n1. Нет мата\n2. Нет спама\n3. Нет рекламы\n4. Уважение\n\nНарушение = бан",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Назад")]],
            resize_keyboard=True
        )
    )

@dp.message(lambda m: m.text == "Назад")
async def back_to_menu(message: types.Message):
    await update_user(message.from_user.id, state='menu')
    await message.answer("Готов? Нажми кнопку.", reply_markup=get_main_menu())

# --- ПОИСК ---
@dp.message(lambda m: m.text == "Найти собеседника")
async def search(message: types.Message):
    user_id = message.from_user.id
    if await check_ban(user_id):
        return
    
    if user_id in searching_queue:
        await message.answer("Ты уже в очереди!")
        return
    
    await update_user(user_id, state='searching')
    searching_queue.append(user_id)
    
    await message.answer(
        "Ищем собеседника...\n\nОжидаем ещё одного человека.",
        reply_markup=get_searching_menu()
    )

# --- КНОПКИ ЧАТА ---
@dp.message(lambda m: m.text in ["Стоп", "Следующий", "Пожаловаться"])
async def handle_chat_buttons(message: types.Message):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if message.text == "Стоп":
        if user and user['partner_id']:
            partner_id = user['partner_id']
            await update_user(partner_id, partner_id=None, state='menu')
            await bot.send_message(partner_id, "Собеседник завершил чат.", reply_markup=get_main_menu())
        if user_id in searching_queue:
            searching_queue.remove(user_id)
        await update_user(user_id, partner_id=None, state='menu')
        await message.answer("Чат завершён.", reply_markup=get_main_menu())
        return

    if message.text == "Следующий":
        if user and user['partner_id']:
            partner_id = user['partner_id']
            await update_user(partner_id, partner_id=None, state='menu')
            await bot.send_message(partner_id, "Собеседник ищет нового.", reply_markup=get_main_menu())
        if user_id in searching_queue:
            searching_queue.remove(user_id)
        await update_user(user_id, partner_id=None, state='searching')
        searching_queue.append(user_id)
        await message.answer("Ищем нового собеседника...", reply_markup=get_searching_menu())
        return

    if message.text == "Пожаловаться":
        if not user or not user['partner_id']:
            await message.answer("Чат завершён.")
            return
        await message.answer(
            "Напиши причину жалобы (1–100 символов):",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="Отмена")]],
                resize_keyboard=True,
                input_field_placeholder="Причина..."
            )
        )
        await update_user(user_id, state='reporting')
        return

# --- ОТМЕНА (умная) ---
@dp.message(lambda m: m.text == "Отмена")
async def cancel_anything(message: types.Message):
    user = await get_user(message.from_user.id)
    
    if user and user['state'] == 'reporting':
        await update_user(message.from_user.id, state='chat')
        await message.answer("Жалоба отменена.", reply_markup=get_chat_menu())
        return
    
    if user and user['state'] == 'searching':
        if message.from_user.id in searching_queue:
            searching_queue.remove(message.from_user.id)
        await update_user(message.from_user.id, state='menu')
        await message.answer("Поиск отменён.", reply_markup=get_main_menu())
        return

# --- ЕДИНЫЙ ХЕНДЛЕР: ЖАЛОБА + ЧАТ ---
@dp.message()
async def handle_messages(message: types.Message):
    user = await get_user(message.from_user.id)
    if not user:
        return

    # --- ЖАЛОБА ---
    if user['state'] == 'reporting':
        reason = message.text.strip()
        if len(reason) > 100:
            await message.answer("Причина слишком длинная (макс. 100 символов).")
            return
        
        partner_id = user['partner_id']
        await add_report(message.from_user.id, partner_id)
        
        # ЗАВЕРШАЕМ ЧАТ У ОБОИХ
        await update_user(message.from_user.id, state='menu', partner_id=None)
        await update_user(partner_id, state='menu', partner_id=None)
        
        await message.answer("Жалоба отправлена. Чат завершён.", reply_markup=get_main_menu())
        await bot.send_message(partner_id, "Чат завершён из-за жалобы.", reply_markup=get_main_menu())
        
        count = await get_reports_count(partner_id)
        if count >= 3:
            await ban_user(partner_id)
            await bot.send_message(partner_id, "Ты забанен за жалобы.", reply_markup=get_main_menu())
        
        await bot.send_message(
            MODERATOR_ID,
            f"ЖАЛОБА + ЧАТ ЗАВЕРШЁН\n"
            f"От: {message.from_user.id}\n"
            f"На: {partner_id}\n"
            f"Причина: {reason}\n"
            f"Всего жалоб: {count}"
        )
        return

    # --- ОБЫЧНЫЕ СООБЩЕНИЯ ---
    if user['state'] == 'chat' and user['partner_id']:
        await bot.send_message(user['partner_id'], message.text)

# --- МОДЕРАТОРСКИЙ РЕЖИМ ---

def get_moderator_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Жалобы"), KeyboardButton(text="🚫 Бан"), KeyboardButton(text="♻️ Разбан")],
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="⬅️ Выйти из режима модератора")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие..."
    )

@dp.message(Command("moderator"))
async def enter_moderator_mode(message: types.Message):
    if message.from_user.id != MODERATOR_ID:
        await message.answer("⛔ У тебя нет прав модератора.")
        return
    await update_user(message.from_user.id, state="moderator")
    await message.answer("🔐 Режим модератора активирован.", reply_markup=get_moderator_menu())

# --- Выход из режима ---
@dp.message(lambda m: m.text == "⬅️ Выйти из режима модератора")
async def exit_moderator_mode(message: types.Message):
    await update_user(message.from_user.id, state="menu")
    await message.answer("✅ Режим модератора выключен.", reply_markup=get_main_menu())

# --- Просмотр жалоб ---
@dp.message(lambda m: m.text == "📋 Жалобы")
async def show_reports(message: types.Message):
    if message.from_user.id != MODERATOR_ID:
        return
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch('SELECT * FROM reports ORDER BY id DESC LIMIT 10')
    await conn.close()
    if not rows:
        await message.answer("Жалоб пока нет.")
        return
    text = "\n\n".join([f"#{r['id']} | От: {r['from_id']} → На: {r['to_id']} | {r['timestamp']:%d.%m %H:%M}" for r in rows])
    await message.answer(f"📋 Последние жалобы:\n\n{text}")

# --- Бан пользователя ---
@dp.message(lambda m: m.text == "🚫 Бан")
async def ask_ban_id(message: types.Message):
    if message.from_user.id != MODERATOR_ID:
        return
    await update_user(message.from_user.id, state="ban_input")
    await message.answer("Введи ID пользователя, которого нужно забанить:", reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Выйти из режима модератора")]],
        resize_keyboard=True
    ))

# --- Разбан ---
@dp.message(lambda m: m.text == "♻️ Разбан")
async def ask_unban_id(message: types.Message):
    if message.from_user.id != MODERATOR_ID:
        return
    await update_user(message.from_user.id, state="unban_input")
    await message.answer("Введи ID пользователя, которого нужно разбанить:", reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Выйти из режима модератора")]],
        resize_keyboard=True
    ))

# --- Ввод ID для бана/разбана ---
@dp.message()
async def handle_moderator_actions(message: types.Message):
    user = await get_user(message.from_user.id)
    if not user or user["state"] not in ["ban_input", "unban_input"]:
        return

    target_id = message.text.strip()
    if not target_id.isdigit():
        await message.answer("Некорректный ID.")
        return
    target_id = int(target_id)

    if user["state"] == "ban_input":
        await ban_user(target_id)
        await message.answer(f"🚫 Пользователь {target_id} забанен.", reply_markup=get_moderator_menu())
        await bot.send_message(target_id, "Ты был забанен модератором.", reply_markup=get_main_menu())

    elif user["state"] == "unban_input":
        await unban_user(target_id)
        await message.answer(f"♻️ Пользователь {target_id} разбанен.", reply_markup=get_moderator_menu())
        await bot.send_message(target_id, "Твой бан снят. Повтори /start.", reply_markup=get_main_menu())

    await update_user(message.from_user.id, state="moderator")

# --- Статистика ---
@dp.message(lambda m: m.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if message.from_user.id != MODERATOR_ID:
        return
    total, active, reports = await get_stats()
    await message.answer(
        f"📊 Статистика:\n\n"
        f"👥 Всего пользователей: {total}\n"
        f"💬 Активных чатов: {active}\n"
        f"⚠️ Жалоб: {reports}"
    )


# --- Запуск ---
async def on_startup(app):
    await init_db()
    webhook_url = f"https://anonymous-chat-bot-7f1b.onrender.com/webhook"
    await bot.set_webhook(webhook_url)
    asyncio.create_task(start_search_loop())
    print("БОТ ЗАПУЩЕН! СООБЩЕНИЯ РАБОТАЮТ! КНОПКИ РАБОТАЮТ!")

def main():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    app.on_startup.append(on_startup)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

if __name__ == "__main__":
    main()
