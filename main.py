import asyncio
import logging
import hashlib
import random
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.enums import ContentType
from aiohttp import web
import os
from dotenv import load_dotenv
from database import *

load_dotenv()

# Безопасное получение конфигурации
BOT_TOKEN = os.getenv("BOT_TOKEN")
MODERATOR_ID = int(os.getenv("MODERATOR_ID", "0"))
MOD_SECRET = os.getenv("MOD_SECRET", "")
HASH_SALT = os.getenv("HASH_SALT", "default_salt_change_me")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in environment variables")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

# --- Безопасное хеширование ID ---
def hash_id(user_id):
    return hashlib.sha256(f"{user_id}{HASH_SALT}".encode()).hexdigest()[:16]

# --- ОЧЕРЕДЬ СО СЛУЧАЙНЫМ СОЕДИНЕНИЕМ ---
class RandomMatchQueue:
    def __init__(self):
        self._users = set()
        self._lock = asyncio.Lock()
    
    async def add(self, user_id):
        async with self._lock:
            if user_id not in self._users:
                self._users.add(user_id)
                logging.info(f"User {user_id} added to queue. Queue size: {len(self._users)}")
                return True
        return False
    
    async def remove(self, user_id):
        async with self._lock:
            if user_id in self._users:
                self._users.remove(user_id)
                logging.info(f"User {user_id} removed from queue. Queue size: {len(self._users)}")
                return True
        return False
    
    async def get_random_pair(self):
        async with self._lock:
            if len(self._users) < 2:
                return None, None
            
            users_list = list(self._users)
            user1, user2 = random.sample(users_list, 2)
            
            self._users.remove(user1)
            self._users.remove(user2)
            
            logging.info(f"Random pair created: {user1} and {user2}. Queue size: {len(self._users)}")
            return user1, user2
    
    def __len__(self):
        return len(self._users)
    
    async def get_queue_info(self):
        async with self._lock:
            return list(self._users)

searching_queue = RandomMatchQueue()

# --- Клавиатуры ---
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
        [InlineKeyboardButton(text="Бан по ID", callback_data="mod_ban")],
        [InlineKeyboardButton(text="Очередь поиска", callback_data="mod_queue")]
    ])

# --- Проверка бана ---
async def check_ban(user_id):
    # МОДЕРАТОР НИКОГДА НЕ МОЖЕТ БЫТЬ ЗАБАНЕН
    if user_id == MODERATOR_ID:
        return False
        
    if await is_banned(user_id):
        await bot.send_message(user_id, "❌ Ты забанен. Обратись к модератору для разблокировки.")
        return True
    return False

# --- Безопасная отправка сообщений ---
async def safe_send_message(chat_id, text, reply_markup=None):
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
        return True
    except Exception as e:
        logging.error(f"Failed to send message to {chat_id}: {e}")
        return False

# --- Безопасная пересылка медиа ---
async def safe_forward_media(chat_id, message):
    try:
        # Текст
        if message.text:
            await bot.send_message(chat_id, message.text)
        
        # Фото
        elif message.photo:
            await bot.send_photo(chat_id, message.photo[-1].file_id, caption=message.caption)
        
        # Видео
        elif message.video:
            await bot.send_video(chat_id, message.video.file_id, caption=message.caption)
        
        # Голосовые сообщения
        elif message.voice:
            await bot.send_voice(chat_id, message.voice.file_id)
        
        # Аудио (музыка)
        elif message.audio:
            await bot.send_audio(chat_id, message.audio.file_id, caption=message.caption)
        
        # Документы
        elif message.document:
            await bot.send_document(chat_id, message.document.file_id, caption=message.caption)
        
        # Стикеры
        elif message.sticker:
            await bot.send_sticker(chat_id, message.sticker.file_id)
        
        # Видео-сообщения (кружочки)
        elif message.video_note:
            await bot.send_video_note(chat_id, message.video_note.file_id)
        
        # Анимации (GIF)
        elif message.animation:
            await bot.send_animation(chat_id, message.animation.file_id, caption=message.caption)
        
        # Локация
        elif message.location:
            await bot.send_location(chat_id, message.location.latitude, message.location.longitude)
        
        # Контакты
        elif message.contact:
            await bot.send_contact(chat_id, message.contact.phone_number, message.contact.first_name)
        
        return True
    except Exception as e:
        logging.error(f"Failed to forward media to {chat_id}: {e}")
        return False

# --- Цикл поиска собеседников ---
async def start_search_loop():
    logging.info("Random search loop started")
    try:
        while True:
            user1, user2 = await searching_queue.get_random_pair()
            if user1 and user2:
                try:
                    u1_data = await get_user(user1)
                    u2_data = await get_user(user2)
                    
                    if not u1_data or not u2_data:
                        continue
                    
                    if u1_data['state'] == 'searching' and u2_data['state'] == 'searching':
                        await update_user(user1, partner_id=user2, state='chat')
                        await update_user(user2, partner_id=user1, state='chat')
                        
                        await safe_send_message(user1, 
                            "🎉 Случайный собеседник найден! Начинайте общение.\n\n"
                            "💬 Теперь можно отправлять:\n"
                            "• Текст\n• Фото\n• Видео\n• Голосовые\n• Музыку\n• Стикеры\n• Файлы\n• И многое другое!",
                            reply_markup=get_chat_menu()
                        )
                        await safe_send_message(user2, 
                            "🎉 Случайный собеседник найден! Начинайте общение.\n\n"
                            "💬 Теперь можно отправлять:\n"
                            "• Текст\n• Фото\n• Видео\n• Голосовые\n• Музыку\n• Стикеры\n• Файлы\n• И многое другое!",
                            reply_markup=get_chat_menu()
                        )
                        
                    else:
                        if u1_data['state'] == 'searching':
                            await searching_queue.add(user1)
                        if u2_data['state'] == 'searching':
                            await searching_queue.add(user2)
                            
                except Exception as e:
                    logging.error(f"Error pairing users: {e}")
                    await searching_queue.add(user1)
                    await searching_queue.add(user2)
            
            await asyncio.sleep(0.5)
            
    except asyncio.CancelledError:
        logging.info("Search loop stopped")
    except Exception as e:
        logging.error(f"Search loop crashed: {e}")

# ================================
#           КОМАНДЫ
# ================================

@dp.message(Command("start"))
async def start(message: types.Message):
    user_id = message.from_user.id
    
    # ОСОБАЯ ПРОВЕРКА ДЛЯ МОДЕРАТОРА
    if user_id == MODERATOR_ID:
        await update_user(user_id, state='menu')
        await message.answer(
            "👑 ПАНЕЛЬ МОДЕРАТОРА\n\n"
            "Используй /mod для доступа к панели модератора.",
            reply_markup=get_main_menu()
        )
        return
        
    if await check_ban(user_id):
        return
    
    await update_user(user_id, state='menu')
    await message.answer(
        "👋 Привет! Добро пожаловать в анонимный чат!\n\n"
        "💬 Теперь можно отправлять:\n"
        "• Текст\n• Фото\n• Видео\n• Голосовые\n• Музыку\n• Стикеры\n• Файлы\n• И многое другое!",
        reply_markup=get_main_menu()
    )

@dp.message(Command("mod"))
async def mod_panel(message: types.Message):
    user_id = message.from_user.id
    
    if user_id != MODERATOR_ID:
        return
    
    args = message.text.split()
    if len(args) < 2 or args[1] != MOD_SECRET:
        await message.answer("❌ Неверный ключ доступа.")
        return
    
    await update_user(user_id, state='mod_menu')
    await message.answer(
        f"🛠 МОДЕРАТОРСКАЯ ПАНЕЛЬ\n"
        f"👑 Ваш ID: {MODERATOR_ID}",
        reply_markup=get_mod_menu()
    )

# --- КОМАНДА ДЛЯ ПОЛУЧЕНИЯ РЕАЛЬНОГО ID ---
@dp.message(Command("myrealid"))
async def my_real_id(message: types.Message):
    user_id = message.from_user.id
    await message.answer(f"🆔 Ваш реальный ID: `{user_id}`", parse_mode="Markdown")

@dp.message(lambda m: m.text == "Мой ID")
async def my_id(message: types.Message):
    user_id = message.from_user.id
    
    # МОДЕРАТОР ВИДИТ РЕАЛЬНЫЙ ID
    if user_id == MODERATOR_ID:
        hashed_id = hash_id(user_id)
        await message.answer(
            f"👑 Ваш реальный ID: `{user_id}`\n"
            f"🔐 Хешированный ID: `{hashed_id}`", 
            parse_mode="Markdown"
        )
    else:
        # ОБЫЧНЫЕ ПОЛЬЗОВАТЕЛИ ВИДЯТ ТОЛЬКО ХЕШИРОВАННЫЙ
        hashed_id = hash_id(user_id)
        await message.answer(f"🔐 Твой анонимный ID: `{hashed_id}`", parse_mode="Markdown")

@dp.message(lambda m: m.text == "Правила")
async def rules(message: types.Message):
    await message.answer(
        "📜 Правила чата:\n\n"
        "1. 🚫 Запрещён нецензурный язык\n"
        "2. 🚫 Запрещён спам и флуд\n"
        "3. 🚫 Запрещена реклама\n"
        "4. 🚫 Запрещены оскорбления\n"
        "5. ✅ Уважайте собеседника\n\n"
        "💬 Можно отправлять: текст, фото, видео, голосовые, музыку, стикеры, файлы",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Назад")]], resize_keyboard=True)
    )

@dp.message(lambda m: m.text == "Назад")
async def back_to_menu(message: types.Message):
    user_id = message.from_user.id
    await update_user(user_id, state='menu')
    await message.answer("Главное меню:", reply_markup=get_main_menu())

@dp.message(lambda m: m.text == "Найти собеседника")
async def search(message: types.Message):
    user_id = message.from_user.id
    
    if await check_ban(user_id):
        return
    
    user_data = await get_user(user_id)
    if user_data and user_data['state'] == 'chat':
        await message.answer("❌ Ты уже в чате! Заверши текущий разговор сначала.")
        return
    
    await update_user(user_id, state='searching')
    added = await searching_queue.add(user_id)
    
    if added:
        # УБРАНО: количество людей в очереди
        await message.answer(
            "🔍 Ищем случайного собеседника...",
            reply_markup=get_searching_menu()
        )
    else:
        await message.answer("⏳ Ты уже в очереди поиска!")

@dp.message(lambda m: m.text == "Отмена")
async def cancel_anything(message: types.Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    
    if not user:
        return
    
    if user['state'] == 'reporting':
        await update_user(user_id, state='chat')
        await message.answer("❌ Жалоба отменена.", reply_markup=get_chat_menu())
        return
        
    if user['state'] == 'searching':
        await searching_queue.remove(user_id)
        await update_user(user_id, state='menu')
        await message.answer("❌ Поиск отменён.", reply_markup=get_main_menu())
        return
    
    await message.answer("❌ Нечего отменять.", reply_markup=get_main_menu())

# ================================
#        УПРАВЛЕНИЕ ЧАТОМ
# ================================

@dp.message(lambda m: m.text in ["Стоп", "Следующий", "Пожаловаться"])
async def handle_chat_buttons(message: types.Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    
    if not user or user['state'] != 'chat':
        await message.answer("❌ Сначала найди собеседника.")
        return

    if message.text == "Стоп":
        partner_id = user['partner_id']
        
        await update_user(user_id, partner_id=None, state='menu')
        if partner_id:
            await update_user(partner_id, partner_id=None, state='menu')
            await safe_send_message(partner_id, "❌ Собеседник завершил чат.", reply_markup=get_main_menu())
        
        await searching_queue.remove(user_id)
        await message.answer("✅ Чат завершён.", reply_markup=get_main_menu())
        return

    if message.text == "Следующий":
        partner_id = user['partner_id']
        
        if partner_id:
            await update_user(partner_id, partner_id=None, state='menu')
            await safe_send_message(partner_id, "🔍 Собеседник ищет нового партнёра.", reply_markup=get_main_menu())
        
        await update_user(user_id, partner_id=None, state='searching')
        await searching_queue.add(user_id)
        
        # УБРАНО: количество людей в очереди
        await message.answer("🔄 Ищем нового собеседника...", reply_markup=get_searching_menu())
        return

    if message.text == "Пожаловаться":
        if not user['partner_id']:
            await message.answer("❌ Нет активного чата для жалобы.")
            return
            
        await message.answer(
            "📝 Опиши причину жалобы:",
            reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True)
        )
        await update_user(user_id, state='reporting')
        return

# ================================
#        СИСТЕМА ЖАЛОБ
# ================================

@dp.message()
async def handle_messages(message: types.Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    
    if not user:
        await update_user(user_id, state='menu')
        return

    # Обработка жалобы
    if user['state'] == 'reporting':
        reason = message.text.strip()
        
        partner_id = user['partner_id']
        if not partner_id:
            await message.answer("❌ Чат уже завершён.")
            await update_user(user_id, state='menu')
            return
        
        # Сохраняем жалобу
        await add_report(user_id, partner_id, reason)
        
        # Завершаем чат для обоих
        await update_user(user_id, state='menu', partner_id=None)
        await update_user(partner_id, state='menu', partner_id=None)
        
        await message.answer("✅ Жалоба отправлена. Чат завершён.", reply_markup=get_main_menu())
        await safe_send_message(partner_id, "❌ Чат завершён по техническим причинам.", reply_markup=get_main_menu())
        
        # НЕ БАНИМ АВТОМАТИЧЕСКИ - ТОЛЬКО УВЕДОМЛЯЕМ МОДЕРАТОРА
        reports_count = await get_reports_count(partner_id)
        
        if MODERATOR_ID:
            await safe_send_message(
                MODERATOR_ID,
                f"🚨 НОВАЯ ЖАЛОБА\n\n"
                f"От: {hash_id(user_id)}\n"
                f"На: {hash_id(partner_id)}\n"
                f"Причина: {reason}\n"
                f"Всего жалоб на пользователя: {reports_count}"
            )
        return

    # Пересылка сообщений в чате (ВСЕ ТИПЫ МЕДИА)
    if user['state'] == 'chat' and user['partner_id']:
        try:
            await safe_forward_media(user['partner_id'], message)
        except Exception as e:
            logging.error(f"Error forwarding message: {e}")
            await message.answer("❌ Ошибка отправки сообщения.")

# ================================
#        МОДЕРАТОРСКАЯ ПАНЕЛЬ
# ================================

@dp.callback_query(lambda c: c.data.startswith("mod_"))
async def mod_callbacks(callback: types.CallbackQuery):
    if callback.from_user.id != MODERATOR_ID:
        await callback.answer("Доступ запрещён.")
        return

    data = callback.data

    if data == "mod_chats":
        users = await get_all_users()
        chats = []
        seen = set()
        
        for user in users:
            if (user['partner_id'] and user['partner_id'] not in seen 
                and user['state'] == 'chat'):
                p1, p2 = user['tg_id'], user['partner_id']
                seen.add(p1)
                seen.add(p2)
                chats.append((p1, p2))
        
        if not chats:
            await callback.message.edit_text("📊 Активных чатов нет.", reply_markup=get_mod_menu())
            return
        
        text = "📊 АКТИВНЫЕ ЧАТЫ:\n\n"
        kb = []
        for i, (u1, u2) in enumerate(chats, 1):
            h1, h2 = hash_id(u1), hash_id(u2)
            text += f"Чат #{i}: {h1} ↔ {h2}\n"
            kb.append([InlineKeyboardButton(text=f"Чат #{i}", callback_data=f"view_chat_{u1}_{u2}")])
        
        kb.append([InlineKeyboardButton(text="Назад", callback_data="mod_back")])
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    elif data.startswith("view_chat_"):
        _, _, u1, u2 = data.split("_")
        u1, u2 = int(u1), int(u2)
        await callback.message.edit_text(
            f"💬 Переписка {hash_id(u1)} ↔ {hash_id(u2)}\n\n"
            f"Просмотр переписки в реальном времени будет добавлен в будущих обновлениях.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Назад", callback_data="mod_chats")]
            ])
        )

    elif data == "mod_reports":
        reports = await get_all_reports()
        if not reports:
            await callback.message.edit_text("📝 Жалоб нет.", reply_markup=get_mod_menu())
            return
        
        text = "📝 ПОСЛЕДНИЕ ЖАЛОБЫ:\n\n"
        for r in reports[:10]:
            # Используем правильные ключи
            reporter_id = r.get('reporter_id') or r.get('from_id')
            reported_id = r.get('reported_id') or r.get('to_id')
            text += f"👤 {hash_id(reporter_id)} → {hash_id(reported_id)}\n"
            text += f"📋 Причина: {r['reason']}\n"
            text += f"🕒 {r['timestamp'].strftime('%d.%m %H:%M')}\n\n"
        
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="mod_back")]
        ]))

    elif data == "mod_stats":
        total_users, active_chats, total_reports = await get_stats()
        in_queue = len(searching_queue)
        reports_today = await get_reports_today()
        
        text = (
            f"📈 СТАТИСТИКА СИСТЕМЫ\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"💬 Активных чатов: {active_chats}\n"
            f"🔍 В поиске: {in_queue}\n"
            f"📝 Всего жалоб: {total_reports}\n"
            f"📅 Жалоб сегодня: {reports_today}\n"
        )
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="mod_back")]
        ]))

    elif data == "mod_ban":
        await callback.message.edit_text(
            "🚫 Введите ID пользователя для бана:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data="mod_back")]
            ])
        )
        await update_user(callback.from_user.id, state='mod_banning')

    elif data == "mod_queue":
        queue_users = await searching_queue.get_queue_info()
        if not queue_users:
            await callback.message.edit_text("👥 Очередь поиска пуста.", reply_markup=get_mod_menu())
            return
        
        text = f"👥 ОЧЕРЕДЬ ПОИСКА ({len(queue_users)}):\n\n"
        for i, user_id in enumerate(queue_users, 1):
            text += f"{i}. {hash_id(user_id)}\n"
        
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="mod_back")]
        ]))

    elif data == "mod_back":
        await callback.message.edit_text("🛠 МОДЕРАТОРСКАЯ ПАНЕЛЬ", reply_markup=get_mod_menu())

    await callback.answer()

# --- Обработка бана от модератора ---
@dp.message(lambda m: m.from_user.id == MODERATOR_ID)
async def mod_ban_execute(message: types.Message):
    user = await get_user(message.from_user.id)
    if not user or user['state'] != 'mod_banning':
        return
        
    try:
        target_id = int(message.text.strip())
        
        # НЕЛЬЗЯ ЗАБАНИТЬ САМОГО СЕБЯ
        if target_id == MODERATOR_ID:
            await message.answer("❌ Нельзя забанить себя!", reply_markup=get_mod_menu())
            await update_user(message.from_user.id, state='mod_menu')
            return
            
        await ban_user(target_id)
        await message.answer(
            f"✅ Пользователь {hash_id(target_id)} забанен на 24 часа.", 
            reply_markup=get_mod_menu()
        )
        await update_user(message.from_user.id, state='mod_menu')
        
        await safe_send_message(target_id, "🚫 Вы были заблокированы модератором на 24 часа.")
        
    except ValueError:
        await message.answer("❌ Неверный формат ID.", reply_markup=get_mod_menu())
    except Exception as e:
        logging.error(f"Ban error: {e}")
        await message.answer("❌ Ошибка при бане пользователя.", reply_markup=get_mod_menu())

# ================================
#           ЗАПУСК
# ================================

async def on_startup(app):
    logging.info("Starting bot...")
    
    # Инициализация БД
    await init_db()
    
    # Автоматический разбан модератора при запуске
    await unban_user(MODERATOR_ID)
    
    # Установка вебхука
    webhook_url = f"https://{os.getenv('RENDER_SERVICE_NAME')}.onrender.com/webhook"
    await bot.set_webhook(webhook_url)
    logging.info(f"Webhook set to: {webhook_url}")
    
    # Запуск фоновых задач
    asyncio.create_task(start_search_loop())
    
    logging.info("Bot started successfully!")

async def on_shutdown(app):
    logging.info("Shutting down bot...")
    await bot.session.close()

def main():
    app = web.Application()
    
    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_handler.register(app, path="/webhook")
    
    setup_application(app, dp, bot=bot)
    
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    
    port = int(os.getenv("PORT", 10000))
    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
