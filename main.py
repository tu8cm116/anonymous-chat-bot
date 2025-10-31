import asyncio
import logging
import hashlib
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
MOD_SECRET = "supersecret123"  # ← ТВОЙ СЕКРЕТНЫЙ КЛЮЧ

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

# --- ХЕШИРОВАНИЕ ID (БЕЗОПАСНОСТЬ) ---
def hash_id(user_id):
    return hashlib.sha256(str(user_id).encode()).hexdigest()[:16]

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
        resize_keyboard=True
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

def get_mod_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Активные чаты", callback_data="mod_chats")],
        [InlineKeyboardButton(text="Жалобы", callback_data="mod_reports")],
        [InlineKeyboardButton(text="Статистика", callback_data="mod_stats")],
        [InlineKeyboardButton(text="Бан по ID", callback_data="mod_ban")]
    ])

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

# ================================
#        /mod — ПЕРВЫМ ДЕЛОМ!
# ================================

@dp.message(Command("mod"))
async def mod_panel(message: types.Message):
    user_id = message.from_user.id
    
    # Логируем попытку
    await bot.send_message(
        MODERATOR_ID,
        f"Попытка /mod от {user_id}"
    )
    
    if user_id != MODERATOR_ID:
        return
    
    args = message.text.split()
    if len(args) < 2 or args[1] != MOD_SECRET:
        await message.answer("Неверный ключ.")
        return
    
    await update_user(user_id, state='mod_menu')
    await message.answer("МОДЕРАТОРСКАЯ ПАНЕЛЬ", reply_markup=get_mod_menu())

# --- МОДЕРАТОРСКИЕ КОЛБЭКИ ---
@dp.callback_query(lambda c: c.data.startswith("mod_"))
async def mod_callbacks(callback: types.CallbackQuery):
    if callback.from_user.id != MODERATOR_ID:
        return

    data = callback.data

    # --- АКТИВНЫЕ ЧАТЫ ---
    if data == "mod_chats":
        users = await get_all_users()
        chats = []
        seen = set()
        for user in users:
            if user['partner_id'] and user['partner_id'] not in seen and user['state'] == 'chat':
                p1, p2 = user['id'], user['partner_id']
                seen.add(p1)
                seen.add(p2)
                chats.append((p1, p2))
        
        if not chats:
            await callback.message.edit_text("Активных чатов нет.", reply_markup=get_mod_menu())
            return
        
        text = "АКТИВНЫЕ ЧАТЫ:\n\n"
        kb = []
        for i, (u1, u2) in enumerate(chats, 1):
            h1, h2 = hash_id(u1), hash_id(u2)
            text += f"Чат #{i}: {h1} ↔ {h2}\n"
            kb.append([InlineKeyboardButton(text=f"Чат #{i}", callback_data=f"view_chat_{u1}_{u2}")])
        kb.append([InlineKeyboardButton(text="Назад", callback_data="mod_back")])
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    # --- ПРОСМОТР ЧАТА ---
    elif data.startswith("view_chat_"):
        _, u1, u2 = data.split("_")
        u1, u2 = int(u1), int(u2)
        await callback.message.edit_text(
            f"Переписка {hash_id(u1)} ↔ {hash_id(u2)}\n\n"
            f"[Логирование сообщений — в разработке]\n"
            f"Скоро добавим!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Назад", callback_data="mod_chats")]
            ])
        )

    # --- ЖАЛОБЫ ---
    elif data == "mod_reports":
        reports = await get_all_reports()
        if not reports:
            await callback.message.edit_text("Жалоб нет.", reply_markup=get_mod_menu())
            return
        
        text = "ПОСЛЕДНИЕ ЖАЛОБЫ:\n\n"
        for r in reports[-10:]:
            text += f"От {hash_id(r['reporter_id'])} → {hash_id(r['reported_id'])}\n"
            text += f"Причина: {r['reason']}\n\n"
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="mod_back")]
        ]))

    # --- СТАТИСТИКА ---
    elif data == "mod_stats":
        users = await get_all_users()
        online = len([u for u in users if u['state'] in ['menu', 'searching', 'chat']])
        in_chat = len([u for u in users if u['state'] == 'chat'])
        in_queue = len(searching_queue)
        reports_today = await get_reports_today()
        
        text = (
            f"СТАТИСТИКА\n\n"
            f"Онлайн: {online}\n"
            f"В чате: {in_chat}\n"
            f"В поиске: {in_queue}\n"
            f"Жалоб сегодня: {reports_today}\n"
        )
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="mod_back")]
        ]))

    # --- БАН ПО ID ---
    elif data == "mod_ban":
        await callback.message.edit_text(
            "Введите ID пользователя для бана:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data="mod_back")]
            ])
        )
        await update_user(callback.from_user.id, state='mod_banning')

    # --- НАЗАД ---
    elif data == "mod_back":
        await callback.message.edit_text("МОДЕРАТОРСКАЯ ПАНЕЛЬ", reply_markup=get_mod_menu())

# --- БАН ПО ID (ввод) ---
@dp.message(lambda m: m.from_user.id == MODERATOR_ID)
async def mod_ban_execute(message: types.Message):
    user = await get_user(message.from_user.id)
    if not user or user['state'] != 'mod_banning':
        return
    try:
        target_id = int(message.text.strip())
        await ban_user(target_id)
        await message.answer(f"Пользователь {hash_id(target_id)} забанен.", reply_markup=get_mod_menu())
        await update_user(message.from_user.id, state='mod_menu')
    except:
        await message.answer("Неверный ID. Попробуй ещё раз.", reply_markup=get_mod_menu())

# ================================
#         ПОЛЬЗОВАТЕЛЬСКИЙ ЧАТ
# ================================

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
    await message.answer(f"Твой ID: {hash_id(message.from_user.id)}")

@dp.message(lambda m: m.text == "Правила")
async def rules(message: types.Message):
    await message.answer(
        "Правила:\n1. Нет мата\n2. Нет спама\n3. Нет рекламы\n4. Уважение\n\nНарушение = бан",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Назад")]], resize_keyboard=True)
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
    await message.answer("Ищем собеседника...", reply_markup=get_searching_menu())

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
        await message.answer("Ищем нового...", reply_markup=get_searching_menu())
        return

    if message.text == "Пожаловаться":
        if not user or not user['partner_id']:
            await message.answer("Чат завершён.")
            return
        await message.answer(
            "Напиши причину жалобы (1–100 символов):",
            reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True)
        )
        await update_user(user_id, state='reporting')
        return

# --- ОТМЕНА ---
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

# --- СООБЩЕНИЯ + ЖАЛОБА (завершает чат) ---
@dp.message()
async def handle_messages(message: types.Message):
    user = await get_user(message.from_user.id)
    if not user:
        return

    # ЖАЛОБА → ЗАВЕРШАЕТ ЧАТ
    if user['state'] == 'reporting':
        reason = message.text.strip()
        if len(reason) > 100:
            await message.answer("Причина слишком длинная.")
            return
        
        partner_id = user['partner_id']
        await add_report(message.from_user.id, partner_id)
        
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
            f"От: {hash_id(message.from_user.id)}\n"
            f"На: {hash_id(partner_id)}\n"
            f"Причина: {reason}\n"
            f"Всего: {count}"
        )
        return

    # ОБЫЧНЫЕ СООБЩЕНИЯ
    if user['state'] == 'chat' and user['partner_id']:
        await bot.send_message(user['partner_id'], message.text)

# --- Запуск ---
async def on_startup(app):
    await init_db()
    webhook_url = f"https://anonymous-chat-bot-7f1b.onrender.com/webhook"
    await bot.set_webhook(webhook_url)
    asyncio.create_task(start_search_loop())
    print("БОТ ЗАПУЩЕН! /mod С СЕКРЕТОМ! ID ХЕШИРУЮТСЯ!")

def main():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    app.on_startup.append(on_startup)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

if __name__ == "__main__":
    main()
