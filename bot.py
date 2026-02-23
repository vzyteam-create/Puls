import aiohttp
import asyncio
import logging
import sqlite3
import aiosqlite
import re
import json
import random
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from collections import defaultdict

from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import CommandStart, Command, ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile, ChatMemberUpdated, InputMediaPhoto, InputMediaVideo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode, ContentType
from aiogram.exceptions import TelegramBadRequest
from aiogram.client.session.aiohttp import AiohttpSession

BOT_TOKEN = "8533732699:AAH_iSLnJnHI0-ROJE8fwqAxKQPeRbo_Lck"
BOT_USERNAME = "@PulsSupportBot"
ADMIN_IDS = [6708209142, 8475965198]
ADMIN_USERNAME = "@vanezyyy"
MAIN_BOT_USERNAME = "@PulsOfficialManager_bot"
DB_FILE = "tickets.db"

TICKET_COOLDOWN = 300
INITIAL_MESSAGE_LIMIT = 3
SPAM_BLOCK_TIME = 600
TICKET_AUTO_CLOSE_HOURS = 48
TITLE_MIN_LENGTH = 5
TITLE_MAX_LENGTH = 20
MESSAGE_MIN_LENGTH = 10
MESSAGE_MAX_LENGTH = 250
MAX_PHOTOS_PER_MESSAGE = 2
CLONE_CREATION_TIMEOUT = 600
ACTION_TIMEOUT = 300
MAX_VIDEO_DURATION = 20
ADMIN_RESPONSE_TIMEOUT = 300  # 5 минут

# Premium эмодзи и стикеры
PREMIUM_EMOJIS = {
    "thumbs_up": "5368324170671202286",
    "fire": "5368324170671202287",
    "party": "5368324170671202291",
    "rocket": "5368324170671202293",
    "sparkles": "5368324170671202292",
    "hourglass": "5368324170671202290",
    "check": "5368324170671202285",
    "bell": "5368324170671202284",
    "heart": "5368324170671202288",
    "star": "5368324170671202294",
    "thinking": "5368324170671202289",
    "coffee": "5368324170671202283",
}

PREMIUM_STICKERS = {
    "success": "CAACAgIAAxkBAAIBsme_p1hBc0wO70cAARkVu7M9zAahZAACJk4AAn_LuEhHhEluAvqM7zYE",
    "thinking": "CAACAgIAAxkBAAIBs2e_p1jCk3GmI-MC9YHhwLhbMgB0AAIqTgACf8u4SEzXH-EUevv7NgQ",
    "coffee": "CAACAgIAAxkBAAIBtGe_p1i24xL1dNkUfZotfYotV8uYAAKJTgACf8u4SFttA6FqnBoGNgQ",
    "waiting": "CAACAgIAAxkBAAIBtWe_p1iIqfev4DTyCkS6cR8GscnfAAKNTgACf8u4SJ_kvOj6QpfcNgQ",
    "alert": "CAACAgIAAxkBAAIBtme_p1hEgtR8AAGDcpvP8eFhO8G3ewACkE4AAn_LuEhQ_-qVlJX8-DYE",
}

# Роутеры
user_router = Router(name="user")
admin_router = Router(name="admin")
group_router = Router(name="group")
clone_router = Router(name="clone")

# Временный хендлер для получения file_id стикеров
@user_router.message(F.sticker)
async def get_sticker_id(message: Message):
    s = message.sticker
    await message.answer(
        f"file_id: <code>{s.file_id}</code>\n"
        f"premium: {s.is_premium}",
        parse_mode=ParseMode.HTML
    )

def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            custom_id INTEGER UNIQUE,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            registered_at TEXT NOT NULL,
            last_activity TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            custom_user_id INTEGER,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            title TEXT,
            category TEXT DEFAULT 'question',
            created_at TEXT NOT NULL,
            last_message_at TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            has_responded INTEGER DEFAULT 0,
            initial_messages_count INTEGER DEFAULT 0,
            closed_at TEXT,
            closed_by INTEGER,
            closed_by_name TEXT,
            blocked_until TEXT,
            rating INTEGER,
            feedback_text TEXT,
            bot_token TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            admin_name TEXT,
            ticket_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            user_custom_id INTEGER,
            rating INTEGER NOT NULL,
            feedback TEXT,
            created_at TEXT NOT NULL,
            bot_token TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS support_admins (
            user_id INTEGER NOT NULL,
            display_name TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            last_active TEXT,
            total_replies INTEGER DEFAULT 0,
            total_closed INTEGER DEFAULT 0,
            total_ratings INTEGER DEFAULT 0,
            avg_rating REAL DEFAULT 0,
            bot_token TEXT NOT NULL,
            PRIMARY KEY (user_id, bot_token)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            sender_type TEXT NOT NULL,
            sender_id INTEGER NOT NULL,
            sender_name TEXT,
            content TEXT,
            media_group_id TEXT,
            file_id TEXT,
            media_type TEXT,
            caption TEXT,
            timestamp TEXT NOT NULL,
            bot_token TEXT NOT NULL,
            FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS media_groups (
            group_id TEXT NOT NULL,
            ticket_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            media_type TEXT NOT NULL,
            caption TEXT,
            timestamp TEXT NOT NULL,
            bot_token TEXT NOT NULL,
            PRIMARY KEY (group_id, message_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_consent (
            user_id INTEGER PRIMARY KEY,
            consented_at TEXT NOT NULL,
            bot_token TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blacklist (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            blocked_at TEXT NOT NULL,
            blocked_by INTEGER,
            bot_token TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS clone_bots (
            token TEXT PRIMARY KEY,
            owner_id INTEGER NOT NULL,
            bot_username TEXT,
            bot_name TEXT,
            created_at TEXT NOT NULL,
            last_active TEXT,
            status TEXT DEFAULT 'active',
            admins TEXT DEFAULT '[]',
            settings TEXT DEFAULT '{}'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS group_settings (
            chat_id INTEGER PRIMARY KEY,
            chat_title TEXT,
            creator_id INTEGER NOT NULL,
            welcome_enabled INTEGER DEFAULT 1,
            goodbye_enabled INTEGER DEFAULT 1,
            welcome_text TEXT DEFAULT '👋 Добро пожаловать в чат, {name}!',
            goodbye_text TEXT DEFAULT '👋 {name} покинул чат',
            welcome_media TEXT,
            welcome_media_type TEXT,
            goodbye_media TEXT,
            goodbye_media_type TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            bot_token TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            trigger_word TEXT NOT NULL,
            response_type TEXT NOT NULL,
            response_content TEXT,
            caption TEXT,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            use_count INTEGER DEFAULT 0,
            bot_token TEXT NOT NULL,
            UNIQUE(chat_id, trigger_word, bot_token)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trigger_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_id INTEGER NOT NULL,
            used_at TEXT NOT NULL,
            used_by INTEGER,
            bot_token TEXT NOT NULL,
            FOREIGN KEY (trigger_id) REFERENCES triggers (id) ON DELETE CASCADE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            data TEXT,
            expires_at TEXT NOT NULL,
            bot_token TEXT NOT NULL
        )
    ''')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_custom_id ON tickets(custom_user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_title ON tickets(title)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_ticket_id ON messages(ticket_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_media_groups_group_id ON media_groups(group_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_admin_reviews_admin ON admin_reviews(admin_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_clone_bots_owner ON clone_bots(owner_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_triggers_chat ON triggers(chat_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_trigger_stats_trigger ON trigger_stats(trigger_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pending_actions_user ON pending_actions(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pending_actions_expires ON pending_actions(expires_at)')
    
    conn.commit()
    conn.close()
    
    migrate_old_database()

def migrate_old_database():
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT total_ratings FROM support_admins LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE support_admins ADD COLUMN total_ratings INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE support_admins ADD COLUMN avg_rating REAL DEFAULT 0")
            print("✅ Добавлены колонки рейтинга в support_admins")
        
        try:
            cursor.execute("SELECT title FROM tickets LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE tickets ADD COLUMN title TEXT")
            print("✅ Добавлена колонка title в tickets")
        
        try:
            cursor.execute("SELECT initial_messages_count FROM tickets LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE tickets ADD COLUMN initial_messages_count INTEGER DEFAULT 0")
            print("✅ Добавлена колонка initial_messages_count в tickets")
        
        try:
            cursor.execute("SELECT last_name FROM users LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE users ADD COLUMN last_name TEXT")
            cursor.execute("ALTER TABLE users ADD COLUMN last_activity TEXT")
            print("✅ Добавлены колонки в users")
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ Ошибка миграции: {e}")

init_db()

active_bots = {}
bot_sessions = {}
pending_timeouts = {}
media_groups_buffer: Dict[str, List[Message]] = defaultdict(list)
waiting_for_admin: Dict[int, asyncio.Task] = {}  # user_id -> task

class AdminRegistration(StatesGroup):
    waiting_for_name = State()

class AdminEditName(StatesGroup):
    waiting_for_new_name = State()

class TicketStates(StatesGroup):
    waiting_category = State()
    waiting_title = State()
    waiting_initial_message = State()
    in_dialog = State()
    waiting_feedback = State()

class BlacklistStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_reason = State()

class CloneBotStates(StatesGroup):
    waiting_for_token = State()
    waiting_for_admins = State()
    waiting_for_settings = State()

class TriggerStates(StatesGroup):
    waiting_for_trigger_word = State()
    waiting_for_trigger_response = State()

class WelcomeStates(StatesGroup):
    waiting_for_welcome = State()
    waiting_for_delete_choice = State()

class GoodbyeStates(StatesGroup):
    waiting_for_goodbye = State()
    waiting_for_delete_choice = State()

async def start_timeout_timer(user_id: int, action_type: str, timeout_seconds: int, state: FSMContext, bot_token: str):
    await asyncio.sleep(timeout_seconds)
    current_state = await state.get_state()
    if current_state:
        data = await state.get_data()
        if data.get('action_type') == action_type:
            await state.clear()
            try:
                async with aiosqlite.connect(DB_FILE) as conn:
                    cursor = await conn.cursor()
                    now = datetime.utcnow().isoformat()
                    await cursor.execute("INSERT INTO pending_actions (user_id, action_type, data, expires_at, bot_token) VALUES (?, ?, ?, ?, ?)",
                                  (user_id, f"timeout_{action_type}", json.dumps({"timeout": True}), now, bot_token))
                    await conn.commit()
            except:
                pass
            
            # Отправляем уведомление
            current_bot = bot if bot_token == 'main' else active_bots.get(bot_token, (None, None, None))[0]
            if current_bot:
                await current_bot.send_message(
                    user_id,
                    f'⏰ <tg-emoji emoji-id="{PREMIUM_EMOJIS["bell"]}">🔔</tg-emoji> Время на выполнение действия истекло. Операция отменена по причине бездействия.',
                    parse_mode=ParseMode.HTML
                )
                await current_bot.send_sticker(user_id, PREMIUM_STICKERS["alert"])

async def get_current_bot(bot_token: str):
    """Получить экземпляр бота по токену"""
    if bot_token == 'main':
        return bot
    clone_data = active_bots.get(bot_token)
    return clone_data[0] if clone_data else None

async def get_or_create_custom_id(user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> int:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT custom_id FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if row:
            custom_id = row[0]
            await cursor.execute("""
                UPDATE users SET username = ?, first_name = ?, last_name = ?, last_activity = ? WHERE user_id = ?
            """, (username, first_name, last_name, datetime.utcnow().isoformat(), user_id))
        else:
            while True:
                custom_id = random.randint(100000000, 999999999)
                await cursor.execute("SELECT custom_id FROM users WHERE custom_id = ?", (custom_id,))
                if not await cursor.fetchone():
                    break
            now = datetime.utcnow().isoformat()
            await cursor.execute("""
                INSERT INTO users (user_id, custom_id, username, first_name, last_name, registered_at, last_activity)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, custom_id, username, first_name, last_name, now, now))
        await conn.commit()
        return custom_id

async def check_ticket_cooldown(user_id: int, bot_token: str) -> tuple[bool, Optional[int]]:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT created_at FROM tickets WHERE user_id = ? AND bot_token = ? ORDER BY created_at DESC LIMIT 1", (user_id, bot_token))
        row = await cursor.fetchone()
        if row and row[0]:
            last_time = datetime.fromisoformat(row[0])
            diff = datetime.utcnow() - last_time
            if diff.total_seconds() < TICKET_COOLDOWN:
                remaining = int(TICKET_COOLDOWN - diff.total_seconds())
                return True, remaining
        return False, None

async def has_open_ticket(user_id: int, bot_token: str) -> bool:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT id FROM tickets WHERE user_id = ? AND bot_token = ? AND status = 'open'", (user_id, bot_token))
        row = await cursor.fetchone()
        return row is not None

async def get_open_ticket_info(user_id: int, bot_token: str) -> Optional[tuple]:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT id, custom_user_id, title, category, created_at, has_responded, initial_messages_count FROM tickets WHERE user_id = ? AND bot_token = ? AND status = 'open'", (user_id, bot_token))
        return await cursor.fetchone()

async def can_user_send_message(user_id: int, bot_token: str) -> tuple[bool, Optional[str]]:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT id, has_responded, initial_messages_count FROM tickets WHERE user_id = ? AND bot_token = ? AND status = 'open'", (user_id, bot_token))
        row = await cursor.fetchone()
        if not row:
            return False, "❌ У вас нет открытого обращения"
        ticket_id, has_responded, initial_count = row
        if has_responded:
            return True, None
        if initial_count >= INITIAL_MESSAGE_LIMIT:
            return False, "⏳ Дождитесь ответа поддержки прежде чем отправить новое сообщение"
        return True, None

async def increment_initial_count(user_id: int, bot_token: str):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("UPDATE tickets SET initial_messages_count = initial_messages_count + 1 WHERE user_id = ? AND bot_token = ? AND status = 'open'", (user_id, bot_token))
        await conn.commit()

async def has_consent(user_id: int, bot_token: str) -> bool:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT consented_at FROM user_consent WHERE user_id = ? AND bot_token = ?", (user_id, bot_token))
        row = await cursor.fetchone()
        return row is not None

async def save_consent(user_id: int, bot_token: str):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        now = datetime.utcnow().isoformat()
        await cursor.execute("INSERT OR REPLACE INTO user_consent (user_id, consented_at, bot_token) VALUES (?, ?, ?)", (user_id, now, bot_token))
        await conn.commit()

async def is_admin(user_id: int, bot_token: str) -> bool:
    if bot_token == 'main':
        return user_id in ADMIN_IDS
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT admins FROM clone_bots WHERE token = ?", (bot_token,))
        row = await cursor.fetchone()
        if row:
            admins = json.loads(row[0])
            return user_id in admins
    return False

async def is_chat_creator(user_id: int, chat_id: int, bot_token: str) -> bool:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT creator_id FROM group_settings WHERE chat_id = ? AND bot_token = ?", (chat_id, bot_token))
        row = await cursor.fetchone()
        return row and row[0] == user_id

async def get_admin_name(user_id: int, bot_token: str) -> Optional[str]:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT display_name FROM support_admins WHERE user_id = ? AND bot_token = ?", (user_id, bot_token))
        row = await cursor.fetchone()
        return row[0] if row else None

async def save_admin_name(user_id: int, display_name: str, bot_token: str):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        now = datetime.utcnow().isoformat()
        await cursor.execute("INSERT OR REPLACE INTO support_admins (user_id, display_name, registered_at, last_active, bot_token) VALUES (?, ?, ?, ?, ?)", (user_id, display_name, now, now, bot_token))
        await conn.commit()

async def update_admin_activity(user_id: int, bot_token: str):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        now = datetime.utcnow().isoformat()
        await cursor.execute("UPDATE support_admins SET last_active = ?, total_replies = total_replies + 1 WHERE user_id = ? AND bot_token = ?", (now, user_id, bot_token))
        await conn.commit()

async def add_admin_review(admin_id: int, admin_name: str, ticket_id: int, user_id: int, user_custom_id: int, rating: int, feedback: str = None, bot_token: str = 'main'):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        now = datetime.utcnow().isoformat()
        await cursor.execute("INSERT INTO admin_reviews (admin_id, admin_name, ticket_id, user_id, user_custom_id, rating, feedback, created_at, bot_token) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (admin_id, admin_name, ticket_id, user_id, user_custom_id, rating, feedback, now, bot_token))
        await cursor.execute("SELECT total_ratings, avg_rating FROM support_admins WHERE user_id = ? AND bot_token = ?", (admin_id, bot_token))
        row = await cursor.fetchone()
        if row:
            total_ratings, avg_rating = row
            new_total = total_ratings + 1
            new_avg = (avg_rating * total_ratings + rating) / new_total
            await cursor.execute("UPDATE support_admins SET total_ratings = ?, avg_rating = ? WHERE user_id = ? AND bot_token = ?", (new_total, new_avg, admin_id, bot_token))
        await conn.commit()

async def get_admin_reviews(admin_id: int, bot_token: str, limit: int = 20) -> List:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT rating, feedback, created_at, user_custom_id, ticket_id FROM admin_reviews WHERE admin_id = ? AND bot_token = ? ORDER BY created_at DESC LIMIT ?", (admin_id, bot_token, limit))
        return await cursor.fetchall()

async def create_new_ticket(user: types.User, title: str, category: str, bot_token: str) -> int:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        now = datetime.utcnow().isoformat()
        custom_id = await get_or_create_custom_id(user.id, user.username, user.first_name, user.last_name)
        await cursor.execute("INSERT INTO tickets (user_id, custom_user_id, username, first_name, last_name, title, category, created_at, last_message_at, status, bot_token) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)", (user.id, custom_id, user.username, user.first_name, user.last_name, title, category, now, now, bot_token))
        ticket_id = cursor.lastrowid
        await conn.commit()
        asyncio.create_task(notify_admins_new_ticket(user, ticket_id, custom_id, title, category, bot_token))
        return ticket_id

async def notify_admins_new_ticket(user: types.User, ticket_id: int, custom_id: int, title: str, category: str, bot_token: str):
    category_names = {'question': '❓ Вопрос', 'problem': '⚠️ Проблема', 'suggestion': '💡 Предложение', 'other': '📌 Другое'}
    category_text = category_names.get(category, category)
    text = f"🆕 <b>НОВОЕ ОБРАЩЕНИЕ #{custom_id}</b>\n\n📝 <b>Тема:</b> {title}\n👤 Пользователь: <a href='tg://user?id={user.id}'>{user.first_name}</a>\n🆔 ID: <code>{custom_id}</code>\n📱 @{user.username or 'нет'}\n📂 {category_text}\n⏰ {datetime.utcnow().strftime('%d.%m.%Y %H:%M')}\n\nДействия:"
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять", callback_data=f"admin:accept_ticket:{ticket_id}:{user.id}:{custom_id}")
    builder.button(text="⛔ Отклонить", callback_data=f"admin:reject_ticket:{ticket_id}:{user.id}:{custom_id}")
    builder.button(text="🚫 В ЧС", callback_data=f"admin:blacklist_ticket:{user.id}:{custom_id}")
    builder.adjust(2, 1)
    
    if bot_token == 'main':
        admin_ids = ADMIN_IDS
        current_bot = bot
    else:
        async with aiosqlite.connect(DB_FILE) as conn:
            cursor = await conn.cursor()
            await cursor.execute("SELECT admins FROM clone_bots WHERE token = ?", (bot_token,))
            row = await cursor.fetchone()
            admin_ids = json.loads(row[0]) if row else []
        clone_data = active_bots.get(bot_token)
        current_bot = clone_data[0] if clone_data else None
    
    if not current_bot:
        logging.error(f"Бот для токена {bot_token} не найден")
        return
    
    for admin_id in admin_ids:
        try:
            await current_bot.send_message(admin_id, text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        except Exception as e:
            logging.error(f"❌ Ошибка уведомления админа {admin_id}: {e}")

async def check_spam_block(user_id: int, bot_token: str) -> tuple[bool, Optional[str]]:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT blocked_until FROM tickets WHERE user_id = ? AND bot_token = ? AND status = 'open'", (user_id, bot_token))
        row = await cursor.fetchone()
        if row and row[0]:
            blocked_until = datetime.fromisoformat(row[0])
            if datetime.utcnow() < blocked_until:
                remaining = (blocked_until - datetime.utcnow()).seconds // 60
                return True, f"⛔ Вы заблокированы на {remaining} мин. за спам."
        return False, None

async def update_message_time(user_id: int, bot_token: str):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        now = datetime.utcnow().isoformat()
        await cursor.execute("UPDATE tickets SET last_message_at = ? WHERE user_id = ? AND bot_token = ? AND status = 'open'", (now, user_id, bot_token))
        await conn.commit()

async def get_ticket_by_custom_id(custom_id: int, bot_token: str) -> Optional[tuple]:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT id, user_id, status, title, category, created_at FROM tickets WHERE custom_user_id = ? AND bot_token = ? AND status = 'open'", (custom_id, bot_token))
        return await cursor.fetchone()

async def get_user_by_custom_id(custom_id: int) -> Optional[tuple]:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT user_id, username, first_name FROM users WHERE custom_id = ?", (custom_id,))
        return await cursor.fetchone()

async def update_has_responded(user_id: int, bot_token: str):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("UPDATE tickets SET has_responded = 1 WHERE user_id = ? AND bot_token = ? AND status = 'open'", (user_id, bot_token))
        await conn.commit()

async def reset_has_responded(user_id: int, bot_token: str):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("UPDATE tickets SET has_responded = 0 WHERE user_id = ? AND bot_token = ? AND status = 'open'", (user_id, bot_token))
        await conn.commit()

async def save_message(ticket_id: int, sender_type: str, sender_id: int, content: str, sender_name: str = None, media_group_id: str = None, file_id: str = None, media_type: str = None, caption: str = None, bot_token: str = 'main'):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        now = datetime.utcnow().isoformat()
        await cursor.execute("INSERT INTO messages (ticket_id, sender_type, sender_id, sender_name, content, media_group_id, file_id, media_type, caption, timestamp, bot_token) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (ticket_id, sender_type, sender_id, sender_name, content, media_group_id, file_id, media_type, caption, now, bot_token))
        await conn.commit()

async def save_media_group(group_id: str, ticket_id: int, message_id: int, file_id: str, media_type: str, caption: str = None, bot_token: str = 'main'):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        now = datetime.utcnow().isoformat()
        await cursor.execute("INSERT OR REPLACE INTO media_groups (group_id, ticket_id, message_id, file_id, media_type, caption, timestamp, bot_token) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (group_id, ticket_id, message_id, file_id, media_type, caption, now, bot_token))
        await conn.commit()

async def get_media_group(group_id: str, bot_token: str) -> List[tuple]:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT file_id, media_type, caption FROM media_groups WHERE group_id = ? AND bot_token = ? ORDER BY message_id ASC", (group_id, bot_token))
        return await cursor.fetchall()

async def close_ticket(ticket_id: int, closed_by: int, closed_by_name: str = None, bot_token: str = 'main') -> bool:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        now = datetime.utcnow().isoformat()
        await cursor.execute("UPDATE tickets SET status = 'closed', closed_at = ?, closed_by = ?, closed_by_name = ? WHERE id = ? AND status = 'open' AND bot_token = ?", (now, closed_by, closed_by_name, ticket_id, bot_token))
        success = cursor.rowcount > 0
        if success and closed_by != 0:
            await cursor.execute("UPDATE support_admins SET total_closed = total_closed + 1 WHERE user_id = ? AND bot_token = ?", (closed_by, bot_token))
        await conn.commit()
        return success

async def save_rating_and_feedback(ticket_id: int, rating: int, feedback: str = None, admin_id: int = None, admin_name: str = None, user_id: int = None, user_custom_id: int = None, bot_token: str = 'main'):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("UPDATE tickets SET rating = ?, feedback_text = ? WHERE id = ? AND bot_token = ?", (rating, feedback, ticket_id, bot_token))
        if admin_id and user_id:
            await add_admin_review(admin_id, admin_name, ticket_id, user_id, user_custom_id, rating, feedback, bot_token)
        await conn.commit()

async def get_ticket_messages(ticket_id: int, bot_token: str) -> List:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT sender_type, sender_name, content, timestamp, media_group_id, file_id, media_type, caption FROM messages WHERE ticket_id = ? AND bot_token = ? ORDER BY timestamp ASC", (ticket_id, bot_token))
        return await cursor.fetchall()

async def get_all_open_tickets(bot_token: str) -> List:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT id, custom_user_id, username, first_name, title, category, created_at, last_message_at, has_responded FROM tickets WHERE status = 'open' AND bot_token = ? ORDER BY created_at ASC", (bot_token,))
        return await cursor.fetchall()

async def get_admin_tickets(admin_id: int, bot_token: str) -> List:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT DISTINCT t.id, t.custom_user_id, t.username, t.first_name, t.title, t.status, t.created_at, t.last_message_at FROM tickets t JOIN messages m ON t.id = m.ticket_id WHERE m.sender_type = 'admin' AND m.sender_id = ? AND t.bot_token = ? ORDER BY t.last_message_at DESC LIMIT 50", (admin_id, bot_token))
        return await cursor.fetchall()

async def search_tickets(query: str, bot_token: str) -> List:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT id, custom_user_id, username, first_name, title, created_at FROM tickets WHERE title LIKE ? AND bot_token = ? ORDER BY created_at DESC LIMIT 20", (f"%{query}%", bot_token))
        by_title = await cursor.fetchall()
        await cursor.execute("SELECT DISTINCT t.id, t.custom_user_id, t.username, t.first_name, t.title, m.timestamp FROM messages m JOIN tickets t ON m.ticket_id = t.id WHERE m.content LIKE ? AND m.sender_type = 'user' AND t.bot_token = ? ORDER BY m.timestamp DESC LIMIT 20", (f"%{query}%", bot_token))
        by_message = await cursor.fetchall()
        seen = set()
        results = []
        for r in by_title + by_message:
            if r[0] not in seen:
                seen.add(r[0])
                results.append(r)
        return results[:20]

async def get_admin_profile(admin_id: int, bot_token: str) -> Dict[str, Any]:
    name = await get_admin_name(admin_id, bot_token)
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT registered_at, last_active, total_replies, total_closed, total_ratings, avg_rating FROM support_admins WHERE user_id = ? AND bot_token = ?", (admin_id, bot_token))
        row = await cursor.fetchone()
        profile = {'name': name, 'admin_id': admin_id, 'registered': 'неизвестно', 'last_active': 'никогда', 'total_replies': 0, 'total_closed': 0, 'total_ratings': 0, 'avg_rating': 0, 'reviews': []}
        if row:
            profile['registered'] = datetime.fromisoformat(row[0]).strftime('%d.%m.%Y %H:%M') if row[0] else 'неизвестно'
            profile['last_active'] = datetime.fromisoformat(row[1]).strftime('%d.%m.%Y %H:%M') if row[1] else 'никогда'
            profile['total_replies'] = row[2]
            profile['total_closed'] = row[3]
            profile['total_ratings'] = row[4]
            profile['avg_rating'] = round(row[5], 1) if row[5] else 0
        reviews = await get_admin_reviews(admin_id, bot_token, 20)
        for r in reviews:
            rating, feedback, created_at, user_custom_id, ticket_id = r
            profile['reviews'].append({'rating': rating, 'feedback': feedback, 'date': datetime.fromisoformat(created_at).strftime('%d.%m.%Y %H:%M'), 'user_id': user_custom_id, 'ticket_id': ticket_id})
        return profile

async def get_statistics(bot_token: str) -> Dict[str, Any]:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        stats = {}
        await cursor.execute("SELECT COUNT(*) FROM tickets WHERE bot_token = ?", (bot_token,))
        stats['total_tickets'] = (await cursor.fetchone())[0]
        await cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'open' AND bot_token = ?", (bot_token,))
        stats['open_tickets'] = (await cursor.fetchone())[0]
        await cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'closed' AND bot_token = ?", (bot_token,))
        stats['closed_tickets'] = (await cursor.fetchone())[0]
        await cursor.execute("SELECT AVG(rating) FROM tickets WHERE rating IS NOT NULL AND bot_token = ?", (bot_token,))
        avg_rating = (await cursor.fetchone())[0]
        stats['avg_rating'] = round(avg_rating, 1) if avg_rating else 0
        await cursor.execute("SELECT COUNT(*) FROM tickets WHERE rating = 5 AND bot_token = ?", (bot_token,))
        stats['rating_5'] = (await cursor.fetchone())[0]
        await cursor.execute("SELECT COUNT(*) FROM tickets WHERE rating = 4 AND bot_token = ?", (bot_token,))
        stats['rating_4'] = (await cursor.fetchone())[0]
        await cursor.execute("SELECT COUNT(*) FROM tickets WHERE rating = 3 AND bot_token = ?", (bot_token,))
        stats['rating_3'] = (await cursor.fetchone())[0]
        await cursor.execute("SELECT COUNT(*) FROM tickets WHERE rating = 2 AND bot_token = ?", (bot_token,))
        stats['rating_2'] = (await cursor.fetchone())[0]
        await cursor.execute("SELECT COUNT(*) FROM tickets WHERE rating = 1 AND bot_token = ?", (bot_token,))
        stats['rating_1'] = (await cursor.fetchone())[0]
        stats['daily'] = []
        for i in range(29, -1, -1):
            day = (datetime.utcnow() - timedelta(days=i)).strftime('%d.%m')
            await cursor.execute("SELECT COUNT(*) FROM tickets WHERE date(created_at) = date('now', ?) AND bot_token = ?", (f'-{i} days', bot_token))
            count = (await cursor.fetchone())[0]
            stats['daily'].append((day, count))
        await cursor.execute("SELECT category, COUNT(*) FROM tickets WHERE bot_token = ? GROUP BY category", (bot_token,))
        stats['categories'] = await cursor.fetchall()
        await cursor.execute("SELECT display_name, total_replies, avg_rating, total_ratings FROM support_admins WHERE bot_token = ? AND total_ratings > 0 ORDER BY avg_rating DESC, total_ratings DESC LIMIT 10", (bot_token,))
        stats['top_admins'] = await cursor.fetchall()
        await cursor.execute("SELECT AVG(strftime('%s', m.timestamp) - strftime('%s', t.created_at)) FROM tickets t JOIN messages m ON t.id = m.ticket_id WHERE m.sender_type = 'admin' AND m.bot_token = ? AND m.id = (SELECT MIN(id) FROM messages WHERE ticket_id = t.id AND sender_type = 'admin' AND bot_token = ?)", (bot_token, bot_token))
        avg_response = (await cursor.fetchone())[0]
        stats['avg_response_seconds'] = int(avg_response) if avg_response else 0
        return stats

async def add_to_blacklist(user_id: int, reason: str, blocked_by: int, bot_token: str):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        now = datetime.utcnow().isoformat()
        await cursor.execute("INSERT OR REPLACE INTO blacklist (user_id, reason, blocked_at, blocked_by, bot_token) VALUES (?, ?, ?, ?, ?)", (user_id, reason, now, blocked_by, bot_token))
        await cursor.execute("UPDATE tickets SET status = 'closed', closed_at = ? WHERE user_id = ? AND bot_token = ? AND status = 'open'", (now, user_id, bot_token))
        await conn.commit()

async def check_blacklist(user_id: int, bot_token: str) -> bool:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT reason FROM blacklist WHERE user_id = ? AND bot_token = ?", (user_id, bot_token))
        row = await cursor.fetchone()
        return row is not None

async def verify_bot_token(token: str) -> tuple[bool, Optional[str], Optional[str]]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('ok'):
                        return True, data['result']['username'], data['result']['first_name']
        return False, None, None
    except:
        return False, None, None

async def start_clone_bot(token: str):
    try:
        session = AiohttpSession()
        bot = Bot(token=token, session=session)
        dp_clone = Dispatcher(storage=MemoryStorage())
        
        dp_clone.include_routers(user_router, admin_router, group_router)
        
        @dp_clone.update.outer_middleware()
        async def bot_token_middleware(handler, event, data):
            data['bot_token'] = token
            return await handler(event, data)
        
        bot_info = await bot.get_me()
        active_bots[token] = (bot, dp_clone, bot_info)
        bot_sessions[token] = session
        
        asyncio.create_task(dp_clone.start_polling(bot))
        logging.info(f"✅ Клон бота @{bot_info.username} запущен")
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка запуска клона: {e}")
        return False

async def stop_clone_bot(token: str):
    if token in active_bots:
        bot, dp, _ = active_bots[token]
        await bot.session.close()
        await dp.storage.close()
        del active_bots[token]
        if token in bot_sessions:
            await bot_sessions[token].close()
            del bot_sessions[token]
        logging.info(f"⏹️ Клон бота {token} остановлен")
        return True
    return False

async def save_clone_bot(token: str, owner_id: int, bot_username: str, bot_name: str, admins: List[int]):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        now = datetime.utcnow().isoformat()
        await cursor.execute("INSERT OR REPLACE INTO clone_bots (token, owner_id, bot_username, bot_name, created_at, last_active, status, admins) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)", (token, owner_id, bot_username, bot_name, now, now, json.dumps(admins)))
        await conn.commit()

async def get_clone_bots(owner_id: int) -> List:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT token, bot_username, bot_name, created_at, status, admins FROM clone_bots WHERE owner_id = ?", (owner_id,))
        return await cursor.fetchall()

async def delete_clone_bot(token: str):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("DELETE FROM clone_bots WHERE token = ?", (token,))
        await conn.commit()

async def update_clone_bot_admins(token: str, admins: List[int]):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("UPDATE clone_bots SET admins = ? WHERE token = ?", (json.dumps(admins), token))
        await conn.commit()

async def get_bot_display_info(bot_token: str) -> Dict[str, str]:
    if bot_token == 'main':
        return {'name': 'Основной бот поддержки', 'username': BOT_USERNAME, 'type': 'main'}
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT bot_username, bot_name FROM clone_bots WHERE token = ?", (bot_token,))
        row = await cursor.fetchone()
        if row:
            return {'name': row[1] or 'Бот поддержки', 'username': f'@{row[0]}' if row[0] else 'неизвестно', 'type': 'clone'}
    return {'name': 'Бот поддержки', 'username': 'неизвестно', 'type': 'clone'}

def format_bot_header(bot_token: str) -> str:
    info = get_bot_display_info(bot_token)
    if info['type'] == 'main':
        return f"🤖 <b>Основной бот поддержки</b>\n└ {info['username']}\n\n"
    else:
        return f"🤖 <b>Бот поддержки</b>\n└ {info['username']}\n\n"

async def get_group_settings(chat_id: int, bot_token: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT * FROM group_settings WHERE chat_id = ? AND bot_token = ?", (chat_id, bot_token))
        row = await cursor.fetchone()
        if row:
            return {'chat_id': row[0], 'chat_title': row[1], 'creator_id': row[2], 'welcome_enabled': bool(row[3]), 'goodbye_enabled': bool(row[4]), 'welcome_text': row[5], 'goodbye_text': row[6], 'welcome_media': row[7], 'welcome_media_type': row[8], 'goodbye_media': row[9], 'goodbye_media_type': row[10], 'created_at': row[11], 'updated_at': row[12]}
        return None

async def create_group_settings(chat_id: int, chat_title: str, creator_id: int, bot_token: str):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        now = datetime.utcnow().isoformat()
        await cursor.execute("SELECT chat_id FROM group_settings WHERE chat_id = ? AND bot_token = ?", (chat_id, bot_token))
        if await cursor.fetchone():
            return
        bot_info = await get_bot_display_info(bot_token)
        welcome_text = f"👋 Добро пожаловать в чат, {{name}}!\n\nЯ - {bot_info['name']}\nЭтот бот создан для вопросов и предложений.\nЕсли у вас есть вопрос - напишите мне в личные сообщения."
        goodbye_text = f"👋 {{name}} покинул чат"
        await cursor.execute("INSERT INTO group_settings (chat_id, chat_title, creator_id, welcome_enabled, goodbye_enabled, welcome_text, goodbye_text, created_at, updated_at, bot_token) VALUES (?, ?, ?, 1, 1, ?, ?, ?, ?, ?)", (chat_id, chat_title, creator_id, welcome_text, goodbye_text, now, now, bot_token))
        await conn.commit()

async def update_group_settings(chat_id: int, bot_token: str, **kwargs):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        now = datetime.utcnow().isoformat()
        updates = []
        values = []
        for key, value in kwargs.items():
            updates.append(f"{key} = ?")
            values.append(value)
        values.append(now)
        values.append(chat_id)
        values.append(bot_token)
        await cursor.execute(f"UPDATE group_settings SET {', '.join(updates)}, updated_at = ? WHERE chat_id = ? AND bot_token = ?", values)
        await conn.commit()

async def reset_welcome_to_default(chat_id: int, bot_token: str):
    bot_info = await get_bot_display_info(bot_token)
    default_text = f"👋 Добро пожаловать в чат, {{name}}!\n\nЯ - {bot_info['name']}\nЭтот бот создан для вопросов и предложений.\nЕсли у вас есть вопрос - напишите мне в личные сообщения."
    await update_group_settings(chat_id, bot_token, welcome_text=default_text, welcome_media=None, welcome_media_type=None)

async def reset_goodbye_to_default(chat_id: int, bot_token: str):
    default_text = f"👋 {{name}} покинул чат"
    await update_group_settings(chat_id, bot_token, goodbye_text=default_text, goodbye_media=None, goodbye_media_type=None)

async def add_trigger(chat_id: int, trigger_word: str, response_type: str, response_content: str, created_by: int, bot_token: str, caption: str = None) -> int:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        now = datetime.utcnow().isoformat()
        await cursor.execute("SELECT id FROM triggers WHERE chat_id = ? AND trigger_word = ? AND bot_token = ?", (chat_id, trigger_word.lower(), bot_token))
        existing = await cursor.fetchone()
        if existing:
            await cursor.execute("UPDATE triggers SET response_type = ?, response_content = ?, caption = ?, created_by = ?, created_at = ?, use_count = 0 WHERE id = ?", (response_type, response_content, caption, created_by, now, existing[0]))
            trigger_id = existing[0]
        else:
            await cursor.execute("INSERT INTO triggers (chat_id, trigger_word, response_type, response_content, caption, created_by, created_at, bot_token) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (chat_id, trigger_word.lower(), response_type, response_content, caption, created_by, now, bot_token))
            trigger_id = cursor.lastrowid
        await conn.commit()
        return trigger_id

async def delete_trigger(chat_id: int, identifier: str, bot_token: str) -> bool:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        if identifier.isdigit():
            await cursor.execute("DELETE FROM triggers WHERE id = ? AND chat_id = ? AND bot_token = ?", (int(identifier), chat_id, bot_token))
        else:
            await cursor.execute("DELETE FROM triggers WHERE trigger_word = ? AND chat_id = ? AND bot_token = ?", (identifier.lower(), chat_id, bot_token))
        deleted = cursor.rowcount > 0
        await conn.commit()
        return deleted

async def get_triggers(chat_id: int, bot_token: str) -> List:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT id, trigger_word, response_type, use_count, created_at FROM triggers WHERE chat_id = ? AND bot_token = ? ORDER BY trigger_word", (chat_id, bot_token))
        return await cursor.fetchall()

async def get_trigger_stats(trigger_id: int, bot_token: str) -> tuple:
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT COUNT(*), MAX(used_at) FROM trigger_stats WHERE trigger_id = ? AND bot_token = ?", (trigger_id, bot_token))
        row = await cursor.fetchone()
        return (row[0], row[1]) if row else (0, None)

async def check_trigger(chat_id: int, text: str, bot_token: str) -> Optional[Dict]:
    if not text:
        return None
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT id, response_type, response_content, caption FROM triggers WHERE chat_id = ? AND bot_token = ? AND LOWER(trigger_word) = LOWER(?)", (chat_id, bot_token, text.strip()))
        row = await cursor.fetchone()
        if row:
            trigger_id, response_type, response_content, caption = row
            await cursor.execute("UPDATE triggers SET use_count = use_count + 1 WHERE id = ?", (trigger_id,))
            await cursor.execute("INSERT INTO trigger_stats (trigger_id, used_at, bot_token) VALUES (?, ?, ?)", (trigger_id, datetime.utcnow().isoformat(), bot_token))
            await conn.commit()
            return {'id': trigger_id, 'type': response_type, 'content': response_content, 'caption': caption}
        return None

async def check_video_duration(message: Message) -> tuple[bool, Optional[int]]:
    if message.video:
        duration = message.video.duration
        if duration > MAX_VIDEO_DURATION:
            return False, duration
    return True, None

def get_admin_main_menu(bot_token: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📂 Открытые обращения", callback_data="admin:open_tickets")
    builder.button(text="📜 Моя история", callback_data="admin:my_history")
    builder.button(text="👤 Мой профиль", callback_data="admin:profile")
    builder.button(text="⭐️ Мои отзывы", callback_data="admin:my_reviews")
    builder.button(text="✏️ Изменить имя", callback_data="admin:change_name")
    builder.button(text="🔍 Поиск", callback_data="admin:search")
    builder.button(text="📊 Статистика", callback_data="admin:stats")
    builder.button(text="⛔ Черный список", callback_data="admin:blacklist")
    if bot_token != 'main':
        builder.button(text="⚙️ Управление ботом", callback_data="clone:manage")
    builder.adjust(1)
    return builder.as_markup()

def get_user_main_menu(bot_token: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Обратиться в поддержку", callback_data="support:start")
    builder.button(text="ℹ️ Правила", callback_data="info:rules")
    builder.button(text="📋 Мои обращения", callback_data="user:my_tickets")
    if bot_token == 'main':
        builder.button(text="🤖 Создать своего бота", callback_data="clone:create")
        builder.button(text="📋 Мои боты", callback_data="clone:list")
        builder.button(text="🤖 Главный бот", url="https://t.me/PulsOfficialManager_bot")
    builder.adjust(1)
    return builder.as_markup()

def get_group_main_menu(bot_token: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    bot_info = get_bot_display_info(bot_token)
    builder.button(text="📝 Задать вопрос", url=f"https://t.me/{bot_info['username'][1:]}")
    builder.button(text="ℹ️ Правила чата", callback_data="group:rules")
    builder.adjust(1)
    return builder.as_markup()

def get_category_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❓ Вопрос", callback_data="category:question")
    builder.button(text="⚠️ Проблема", callback_data="category:problem")
    builder.button(text="💡 Предложение", callback_data="category:suggestion")
    builder.button(text="📌 Другое", callback_data="category:other")
    builder.button(text="◀️ Назад", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_consent_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Я согласен с правилами", callback_data="consent:accept")
    builder.button(text="◀️ Назад", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_cancel_keyboard(for_group: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if for_group:
        builder.button(text="❌ Отменить", callback_data="group:cancel")
    else:
        builder.button(text="❌ Отменить", callback_data="support:cancel")
    return builder.as_markup()

def get_after_message_menu(ticket_id: int = None, custom_id: int = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Продолжить диалог", callback_data="support:continue")
    if ticket_id and custom_id:
        builder.button(text="🔒 Закрыть обращение", callback_data=f"support:close:{ticket_id}:{custom_id}")
    builder.button(text="🏠 Главное меню", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_rating_keyboard(ticket_id: int, admin_id: int = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐️ 5 - Отлично", callback_data=f"rate:5:{ticket_id}:{admin_id or 0}")
    builder.button(text="⭐️ 4 - Хорошо", callback_data=f"rate:4:{ticket_id}:{admin_id or 0}")
    builder.button(text="⭐️ 3 - Нормально", callback_data=f"rate:3:{ticket_id}:{admin_id or 0}")
    builder.button(text="⭐️ 2 - Плохо", callback_data=f"rate:2:{ticket_id}:{admin_id or 0}")
    builder.button(text="⭐️ 1 - Ужасно", callback_data=f"rate:1:{ticket_id}:{admin_id or 0}")
    builder.adjust(1)
    return builder.as_markup()

def get_ticket_actions_keyboard(ticket_id: int, user_id: int, custom_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Закрыть обращение", callback_data=f"close:{ticket_id}:{user_id}:{custom_id}")
    builder.button(text="📜 История", callback_data=f"admin:view_ticket_{ticket_id}")
    builder.button(text="⛔ В черный список", callback_data=f"blacklist:{user_id}:{custom_id}")
    builder.adjust(1)
    return builder.as_markup()

def get_user_tickets_keyboard(tickets: List) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ticket in tickets:
        ticket_id, custom_id, title, status, created_at = ticket
        status_emoji = "🟢" if status == 'open' else "🔴"
        date = datetime.fromisoformat(created_at).strftime("%d.%m")
        short_title = title[:20] + "..." if len(title) > 20 else title
        builder.button(text=f"{status_emoji} #{custom_id} - {short_title} ({date})", callback_data=f"user:view_ticket_{ticket_id}")
    builder.button(text="◀️ Назад", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_blacklist_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить в ЧС", callback_data="blacklist:add")
    builder.button(text="📋 Список ЧС", callback_data="blacklist:list")
    builder.button(text="❌ Удалить из ЧС", callback_data="blacklist:remove")
    builder.button(text="◀️ Назад", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_clone_management_keyboard(token: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Управление админами", callback_data=f"clone:admins:{token}")
    builder.button(text="📊 Статистика бота", callback_data=f"clone:stats:{token}")
    builder.button(text="🔄 Перезапустить", callback_data=f"clone:restart:{token}")
    builder.button(text="❌ Удалить бота", callback_data=f"clone:delete:{token}")
    builder.button(text="◀️ Назад", callback_data="clone:list")
    builder.adjust(1)
    return builder.as_markup()

def get_welcome_delete_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 По умолчанию", callback_data="welcome:default")
    builder.button(text="🔴 Выключить", callback_data="welcome:disable")
    builder.button(text="❌ Отмена", callback_data="welcome:cancel")
    builder.adjust(2)
    return builder.as_markup()

def get_goodbye_delete_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 По умолчанию", callback_data="goodbye:default")
    builder.button(text="🔴 Выключить", callback_data="goodbye:disable")
    builder.button(text="❌ Отмена", callback_data="goodbye:cancel")
    builder.adjust(2)
    return builder.as_markup()

def get_enable_confirmation_keyboard(action: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"{action}:confirm")
    builder.button(text="❌ Отменить", callback_data=f"{action}:cancel")
    builder.adjust(2)
    return builder.as_markup()

def get_triggers_list_keyboard(chat_id: int, triggers: List) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for t in triggers[:10]:
        trigger_id, word, rtype, use_count, created_at = t
        emoji = "📝" if rtype == 'text' else "📷" if rtype == 'photo' else "🎥" if rtype == 'video' else "🎞️"
        builder.button(text=f"{emoji} {word} (исп. {use_count})", callback_data=f"trigger:info:{trigger_id}")
    builder.button(text="➕ Добавить триггер", callback_data="trigger:add")
    builder.button(text="❌ Удалить триггер", callback_data="trigger:delete")
    builder.button(text="◀️ Назад", callback_data="group:menu")
    builder.adjust(1)
    return builder.as_markup()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

dp.include_routers(user_router, admin_router, group_router, clone_router)

@dp.update.outer_middleware()
async def main_bot_token_middleware(handler, event, data):
    data['bot_token'] = 'main'
    return await handler(event, data)

async def start_waiting_timer(user_id: int, bot_token: str, ticket_id: int):
    await asyncio.sleep(ADMIN_RESPONSE_TIMEOUT)
    
    # Проверяем, не ответил ли уже админ
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT has_responded FROM tickets WHERE id = ?", (ticket_id,))
        row = await cursor.fetchone()
        if not row or row[0] == 1:
            return
    
    current_bot = await get_current_bot(bot_token)
    if current_bot:
        await current_bot.send_message(
            user_id,
            f'💭 <tg-emoji emoji-id="{PREMIUM_EMOJIS["thinking"]}">🤔</tg-emoji> Админ ещё думает...\n'
            f'Мы уже отправили ему напоминание! <tg-emoji emoji-id="{PREMIUM_EMOJIS["hourglass"]}">⌛</tg-emoji>',
            parse_mode=ParseMode.HTML
        )
        await current_bot.send_sticker(user_id, PREMIUM_STICKERS["thinking"])

@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, **data):
    bot_token = data.get("bot_token", "main")
    if message.chat.type != 'private':
        settings = await get_group_settings(message.chat.id, bot_token)
        if not settings and message.from_user:
            await create_group_settings(message.chat.id, message.chat.title or "Группа", message.from_user.id, bot_token)
        settings = await get_group_settings(message.chat.id, bot_token)
        bot_info = await get_bot_display_info(bot_token)
        await message.answer(
            f"👋 Привет! Я {bot_info['name']}\n\n"
            f"Этот чат предназначен для общения участников.\n"
            f"Если у вас есть вопрос или предложение - напишите мне в личные сообщения.\n\n"
            f"Команды для создателя группы:\n"
            f"/triggers - просмотр триггеров\n"
            f"/addtrigger слово - добавить триггер\n"
            f"/deletetrigger слово/ID - удалить триггер\n"
            f"/hello текст/фото/видео - установить приветствие\n"
            f"/bye текст/фото/видео - установить прощание\n"
            f"/delhello - удалить приветствие\n"
            f"/delbye - удалить прощание",
            reply_markup=get_group_main_menu(bot_token)
        )
        return
    user = message.from_user
    if await check_blacklist(user.id, bot_token):
        await message.answer(f"⛔ Вы находитесь в черном списке и не можете использовать поддержку.\nДля вопросов обратитесь к {ADMIN_USERNAME}")
        return
    custom_id = await get_or_create_custom_id(user.id, user.username, user.first_name, user.last_name)
    if await is_admin(user.id, bot_token):
        if not await get_admin_name(user.id, bot_token):
            await message.answer(
                f"👋 Добро пожаловать в панель поддержки {BOT_USERNAME}!\n"
                f"Ваш персональный ID: <code>{custom_id}</code>\n\n"
                f"Введите своё имя в формате:\n"
                f"Имя Ф.\n\n"
                f"Пример: Иван З.",
                parse_mode=ParseMode.HTML
            )
            await state.set_state(AdminRegistration.waiting_for_name)
            asyncio.create_task(start_timeout_timer(user.id, "admin_registration", ACTION_TIMEOUT, state, bot_token))
        else:
            admin_name = await get_admin_name(user.id, bot_token)
            await message.answer(
                f"👋 С возвращением, {admin_name}!\n"
                f"Бот: {BOT_USERNAME}\n"
                f"Создатель: {ADMIN_USERNAME}\n"
                f"Ваш ID: <code>{custom_id}</code>\n\n"
                f"🔧 Панель поддержки:",
                parse_mode=ParseMode.HTML,
                reply_markup=get_admin_main_menu(bot_token)
            )
    else:
        open_ticket = await get_open_ticket_info(user.id, bot_token)
        if open_ticket:
            ticket_id, custom_id, title, category, created_at, has_responded, initial_count = open_ticket
            created = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")
            if has_responded:
                status_text = "✅ Поддержка ответила"
            else:
                status_text = f"⏳ Ожидание ответа (отправлено {initial_count}/{INITIAL_MESSAGE_LIMIT} сообщений)"
            await message.answer(
                f"👋 С возвращением!\n"
                f"Ваш ID: <code>{custom_id}</code>\n\n"
                f"📌 <b>Обращение #{custom_id}</b>\n"
                f"📝 Тема: {title}\n"
                f"📅 Создано: {created}\n"
                f"📂 Категория: {category}\n"
                f"{status_text}\n\n"
                f"Продолжите диалог:",
                parse_mode=ParseMode.HTML
            )
            await state.set_state(TicketStates.in_dialog)
            await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)
        else:
            await message.answer(
                f"👋 Добро пожаловать!\n"
                f"Создатель бота: {ADMIN_USERNAME}\n"
                f"Ваш персональный ID: <code>{custom_id}</code>\n\n"
                f"Выберите действие:",
                parse_mode=ParseMode.HTML,
                reply_markup=get_user_main_menu(bot_token)
            )
        await state.clear()

@group_router.message(Command("triggers"))
async def cmd_triggers(message: Message, state: FSMContext, **data):
    bot_token = data.get("bot_token", "main")
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    settings = await get_group_settings(message.chat.id, bot_token)
    if not settings:
        if message.from_user:
            await create_group_settings(message.chat.id, message.chat.title or "Группа", message.from_user.id, bot_token)
        settings = await get_group_settings(message.chat.id, bot_token)
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может просматривать триггеры")
        return
    triggers = await get_triggers(message.chat.id, bot_token)
    if not triggers:
        await message.answer("📝 В этой группе пока нет триггеров.\n\nЧтобы добавить триггер, отправьте команду:\n/addtrigger слово - например: /addtrigger привет")
        return
    text = "🔤 <b>Список триггеров:</b>\n\n"
    for t in triggers[:15]:
        trigger_id, word, rtype, use_count, created_at = t
        emoji = "📝" if rtype == 'text' else "📷" if rtype == 'photo' else "🎥" if rtype == 'video' else "🎞️"
        date = datetime.fromisoformat(created_at).strftime("%d.%m.%Y")
        text += f"{emoji} <b>#{trigger_id}</b> - '{word}'\n└ Использован: {use_count} раз | Создан: {date}\n\n"
    text += "\nЧтобы добавить новый триггер: /addtrigger слово\nЧтобы удалить: /deletetrigger слово или /deletetrigger ID"
    await message.answer(text, parse_mode=ParseMode.HTML)

@group_router.message(Command("addtrigger"))
async def cmd_addtrigger(message: Message, state: FSMContext, **data):
    bot_token = data.get("bot_token", "main")
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    settings = await get_group_settings(message.chat.id, bot_token)
    if not settings:
        if message.from_user:
            await create_group_settings(message.chat.id, message.chat.title or "Группа", message.from_user.id, bot_token)
        settings = await get_group_settings(message.chat.id, bot_token)
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может добавлять триггеры")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /addtrigger слово\nПример: /addtrigger привет")
        return
    trigger_word = args[1].strip().lower()
    if len(trigger_word) < 2 or len(trigger_word) > 50:
        await message.answer("❌ Слово-триггер должно содержать от 2 до 50 символов")
        return
    await state.update_data(trigger_word=trigger_word, chat_id=message.chat.id, action_type="add_trigger")
    await message.answer(
        f"✅ Слово '{trigger_word}' сохранено.\n\n"
        f"Теперь отправьте ответ, который бот будет отправлять на этот триггер.\n"
        f"Можно отправить: текст, фото, видео, GIF, стикер.\n\n"
        f"❗️ Фото/видео/GIF должны быть без текста (текст станет подписью)\n\n"
        f"⏰ У вас есть {ACTION_TIMEOUT // 60} минут на отправку ответа",
        reply_markup=get_cancel_keyboard(for_group=True)
    )
    await state.set_state(TriggerStates.waiting_for_trigger_response)
    asyncio.create_task(start_timeout_timer(message.from_user.id, "add_trigger", ACTION_TIMEOUT, state, bot_token))

@group_router.message(Command("deletetrigger"))
async def cmd_deletetrigger(message: Message, state: FSMContext, **data):
    bot_token = data.get("bot_token", "main")
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    settings = await get_group_settings(message.chat.id, bot_token)
    if not settings:
        await message.answer("❌ Сначала настройте группу через /start")
        return
    if settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может удалять триггеры")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /deletetrigger слово или /deletetrigger ID\nПример: /deletetrigger привет\nИли: /deletetrigger 5")
        return
    identifier = args[1].strip()
    if await delete_trigger(message.chat.id, identifier, bot_token):
        await message.answer(f"✅ Триггер '{identifier}' успешно удален")
    else:
        await message.answer(f"❌ Триггер '{identifier}' не найден")

@group_router.message(Command("hello"))
async def cmd_hello(message: Message, state: FSMContext, **data):
    bot_token = data.get("bot_token", "main")
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    settings = await get_group_settings(message.chat.id, bot_token)
    if not settings:
        if message.from_user:
            await create_group_settings(message.chat.id, message.chat.title or "Группа", message.from_user.id, bot_token)
        settings = await get_group_settings(message.chat.id, bot_token)
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может изменять приветствие")
        return
    if not settings['welcome_enabled']:
        await message.answer("⚠️ Сейчас приветствие отключено. Хотите включить и установить новый текст?", reply_markup=get_enable_confirmation_keyboard("welcome_enable"))
        await state.update_data(chat_id=message.chat.id, bot_token=bot_token)
        return
    has_text = message.text and len(message.text.split()) > 1
    has_media = message.photo or message.video or message.animation
    has_reply = message.reply_to_message is not None
    if not (has_text or has_media or has_reply):
        current = f"Текущее приветствие: {settings['welcome_text']}"
        if settings['welcome_media']:
            current += "\n(с медиа)"
        await message.answer(f"{current}\n\nЧтобы изменить, отправьте команду с контентом:\n/hello ваш текст\nИли отправьте фото/видео с командой в подписи")
        return
    media_type = None
    media_id = None
    caption = None
    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.text:
            caption = replied.text
        elif replied.photo:
            if replied.media_group_id:
                await message.answer("❌ Альбомы не поддерживаются. Отправьте 1 фото.")
                return
            media_type = 'photo'
            media_id = replied.photo[-1].file_id
            caption = replied.caption
        elif replied.video:
            if replied.video.duration > MAX_VIDEO_DURATION:
                await message.answer(f"❌ Видео слишком длинное! Максимум {MAX_VIDEO_DURATION} сек")
                return
            media_type = 'video'
            media_id = replied.video.file_id
            caption = replied.caption
        elif replied.animation:
            media_type = 'animation'
            media_id = replied.animation.file_id
            caption = replied.caption
    else:
        if message.photo:
            if message.media_group_id:
                await message.answer("❌ Альбомы не поддерживаются. Отправьте 1 фото.")
                return
            media_type = 'photo'
            media_id = message.photo[-1].file_id
            caption = message.caption
        elif message.video:
            if message.video.duration > MAX_VIDEO_DURATION:
                await message.answer(f"❌ Видео слишком длинное! Максимум {MAX_VIDEO_DURATION} сек")
                return
            media_type = 'video'
            media_id = message.video.file_id
            caption = message.caption
        elif message.animation:
            media_type = 'animation'
            media_id = message.animation.file_id
            caption = message.caption
        elif message.text:
            parts = message.text.split(maxsplit=1)
            if len(parts) > 1:
                caption = parts[1]
    if not caption and not media_type:
        await message.answer("❌ Не отправлено никакого контента")
        return
    bot_info = await get_bot_display_info(bot_token)
    footer = f"\n\nℹ️ Этот бот создан для вопросов и предложений. Напишите мне в ЛС: {bot_info['username']}"
    full_caption = (caption or "") + footer
    update_data = {'welcome_text': full_caption, 'welcome_media': media_id, 'welcome_media_type': media_type, 'welcome_enabled': 1}
    await update_group_settings(message.chat.id, bot_token, **update_data)
    await message.answer("✅ Приветствие успешно обновлено!")

@group_router.message(Command("bye"))
async def cmd_bye(message: Message, state: FSMContext, **data):
    bot_token = data.get("bot_token", "main")
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    settings = await get_group_settings(message.chat.id, bot_token)
    if not settings:
        if message.from_user:
            await create_group_settings(message.chat.id, message.chat.title or "Группа", message.from_user.id, bot_token)
        settings = await get_group_settings(message.chat.id, bot_token)
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может изменять прощание")
        return
    if not settings['goodbye_enabled']:
        await message.answer("⚠️ Сейчас прощание отключено. Хотите включить и установить новый текст?", reply_markup=get_enable_confirmation_keyboard("goodbye_enable"))
        await state.update_data(chat_id=message.chat.id)
        return
    has_text = message.text and len(message.text.split()) > 1
    has_media = message.photo or message.video or message.animation
    has_reply = message.reply_to_message is not None
    if not (has_text or has_media or has_reply):
        current = f"Текущее прощание: {settings['goodbye_text']}"
        if settings['goodbye_media']:
            current += "\n(с медиа)"
        await message.answer(f"{current}\n\nЧтобы изменить, отправьте команду с контентом:\n/bye ваш текст\nИли отправьте фото/видео с командой в подписи")
        return
    media_type = None
    media_id = None
    caption = None
    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.text:
            caption = replied.text
        elif replied.photo:
            if replied.media_group_id:
                await message.answer("❌ Альбомы не поддерживаются. Отправьте 1 фото.")
                return
            media_type = 'photo'
            media_id = replied.photo[-1].file_id
            caption = replied.caption
        elif replied.video:
            if replied.video.duration > MAX_VIDEO_DURATION:
                await message.answer(f"❌ Видео слишком длинное! Максимум {MAX_VIDEO_DURATION} сек")
                return
            media_type = 'video'
            media_id = replied.video.file_id
            caption = replied.caption
        elif replied.animation:
            media_type = 'animation'
            media_id = replied.animation.file_id
            caption = replied.caption
    else:
        if message.photo:
            if message.media_group_id:
                await message.answer("❌ Альбомы не поддерживаются. Отправьте 1 фото.")
                return
            media_type = 'photo'
            media_id = message.photo[-1].file_id
            caption = message.caption
        elif message.video:
            if message.video.duration > MAX_VIDEO_DURATION:
                await message.answer(f"❌ Видео слишком длинное! Максимум {MAX_VIDEO_DURATION} сек")
                return
            media_type = 'video'
            media_id = message.video.file_id
            caption = message.caption
        elif message.animation:
            media_type = 'animation'
            media_id = message.animation.file_id
            caption = message.caption
        elif message.text:
            parts = message.text.split(maxsplit=1)
            if len(parts) > 1:
                caption = parts[1]
    if not caption and not media_type:
        await message.answer("❌ Не отправлено никакого контента")
        return
    update_data = {'goodbye_text': caption or "👋 {name} покинул чат", 'goodbye_media': media_id, 'goodbye_media_type': media_type, 'goodbye_enabled': 1}
    await update_group_settings(message.chat.id, bot_token, **update_data)
    await message.answer("✅ Прощание успешно обновлено!")

@group_router.message(Command("delhello"))
async def cmd_delhello(message: Message, state: FSMContext, **data):
    bot_token = data.get("bot_token", "main")
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    settings = await get_group_settings(message.chat.id, bot_token)
    if not settings:
        await message.answer("❌ Сначала настройте группу через /start")
        return
    if settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может удалять приветствие")
        return
    await message.answer("❓ Вы хотите удалить приветствие. Выберите действие:", reply_markup=get_welcome_delete_keyboard())
    await state.set_state(WelcomeStates.waiting_for_delete_choice)
    await state.update_data(chat_id=message.chat.id, bot_token=bot_token)

@group_router.message(Command("delbye"))
async def cmd_delbye(message: Message, state: FSMContext, **data):
    bot_token = data.get("bot_token", "main")
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    settings = await get_group_settings(message.chat.id, bot_token)
    if not settings:
        await message.answer("❌ Сначала настройте группу через /start")
        return
    if settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может удалять прощание")
        return
    await message.answer("❓ Вы хотите удалить прощание. Выберите действие:", reply_markup=get_goodbye_delete_keyboard())
    await state.set_state(GoodbyeStates.waiting_for_delete_choice)
    await state.update_data(chat_id=message.chat.id)

@group_router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_user_join(event: ChatMemberUpdated, **data):
    bot_token = data.get("bot_token", "main")
    settings = await get_group_settings(event.chat.id, bot_token)
    if not settings or not settings['welcome_enabled']:
        return
    user = event.new_chat_member.user
    name = user.full_name
    welcome_text = settings['welcome_text'].replace('{name}', name)
    
    current_bot = await get_current_bot(bot_token)
    if not current_bot:
        return
    
    try:
        if settings['welcome_media'] and settings['welcome_media_type']:
            if settings['welcome_media_type'] == 'photo':
                await current_bot.send_photo(event.chat.id, settings['welcome_media'], caption=welcome_text)
            elif settings['welcome_media_type'] == 'video':
                await current_bot.send_video(event.chat.id, settings['welcome_media'], caption=welcome_text)
            elif settings['welcome_media_type'] == 'animation':
                await current_bot.send_animation(event.chat.id, settings['welcome_media'], caption=welcome_text)
        else:
            await current_bot.send_message(event.chat.id, welcome_text)
    except Exception as e:
        logging.error(f"❌ Ошибка отправки приветствия: {e}")

@group_router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_user_leave(event: ChatMemberUpdated, **data):
    bot_token = data.get("bot_token", "main")
    settings = await get_group_settings(event.chat.id, bot_token)
    if not settings or not settings['goodbye_enabled']:
        return
    user = event.old_chat_member.user
    name = user.full_name
    goodbye_text = settings['goodbye_text'].replace('{name}', name)
    
    current_bot = await get_current_bot(bot_token)
    if not current_bot:
        return
    
    try:
        if settings['goodbye_media'] and settings['goodbye_media_type']:
            if settings['goodbye_media_type'] == 'photo':
                await current_bot.send_photo(event.chat.id, settings['goodbye_media'], caption=goodbye_text)
            elif settings['goodbye_media_type'] == 'video':
                await current_bot.send_video(event.chat.id, settings['goodbye_media'], caption=goodbye_text)
            elif settings['goodbye_media_type'] == 'animation':
                await current_bot.send_animation(event.chat.id, settings['goodbye_media'], caption=goodbye_text)
        else:
            await current_bot.send_message(event.chat.id, goodbye_text)
    except Exception as e:
        logging.error(f"❌ Ошибка отправки прощания: {e}")

@group_router.message(F.chat.type.in_({'group', 'supergroup'}))
async def handle_group_message(message: Message, **data):
    bot_token = data.get("bot_token", "main")
    if not message.text or message.text.startswith('/'):
        return
    trigger = await check_trigger(message.chat.id, message.text, bot_token)
    if trigger:
        try:
            if trigger['type'] == 'text':
                await message.reply(trigger['content'])
            elif trigger['type'] == 'photo':
                await message.reply_photo(trigger['content'], caption=trigger['caption'])
            elif trigger['type'] == 'video':
                await message.reply_video(trigger['content'], caption=trigger['caption'])
            elif trigger['type'] == 'animation':
                await message.reply_animation(trigger['content'], caption=trigger['caption'])
            elif trigger['type'] == 'sticker':
                await message.reply_sticker(trigger['content'])
        except Exception as e:
            logging.error(f"❌ Ошибка отправки триггера: {e}")

@group_router.message(TriggerStates.waiting_for_trigger_response)
async def process_trigger_response(message: Message, state: FSMContext, **data):
    bot_token = data.get("bot_token", "main")
    data_state = await state.get_data()
    chat_id = data_state['chat_id']
    trigger_word = data_state['trigger_word']
    if message.video:
        is_valid, duration = await check_video_duration(message)
        if not is_valid:
            await message.answer(f"❌ Видео слишком длинное! Максимальная длительность: {MAX_VIDEO_DURATION} секунд.\nВаше видео: {duration} сек. Попробуйте ещё раз.")
            return
    if message.photo:
        if message.media_group_id:
            await message.answer("❌ Альбомы не поддерживаются. Отправьте 1 фото.")
            return
    response_type = None
    response_content = None
    caption = message.caption or message.text
    if message.text:
        response_type = 'text'
        response_content = message.text
    elif message.photo:
        response_type = 'photo'
        response_content = message.photo[-1].file_id
    elif message.video:
        response_type = 'video'
        response_content = message.video.file_id
    elif message.animation:
        response_type = 'animation'
        response_content = message.animation.file_id
    elif message.sticker:
        response_type = 'sticker'
        response_content = message.sticker.file_id
        caption = None
    else:
        await message.answer("❌ Неподдерживаемый тип сообщения.\nОтправьте текст, фото, видео, GIF или стикер.")
        return
    trigger_id = await add_trigger(chat_id, trigger_word, response_type, response_content, message.from_user.id, bot_token, caption)
    await message.answer(
        f"✅ Триггер '#{trigger_id} - {trigger_word}' успешно создан!",
        reply_markup=InlineKeyboardBuilder()
            .button(text="📋 Список триггеров", callback_data="trigger:list")
            .button(text="➕ Ещё триггер", callback_data="trigger:add")
            .as_markup()
    )
    await state.clear()

@admin_router.message(Command("change_name"))
async def change_name_command(message: Message, state: FSMContext, **data):
    bot_token = data.get("bot_token", "main")
    if not await is_admin(message.from_user.id, bot_token):
        await message.answer("❌ У вас нет доступа.")
        return
    await message.answer("Введите новое имя в формате 'Имя Ф.' (пример: Иван З.):", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminEditName.waiting_for_new_name)
    asyncio.create_task(start_timeout_timer(message.from_user.id, "change_name", ACTION_TIMEOUT, state, bot_token))

@admin_router.message(AdminEditName.waiting_for_new_name)
async def change_name(message: Message, state: FSMContext, **data):
    bot_token = data.get("bot_token", "main")
    name = message.text.strip()
    if not re.match(r'^[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z]\.$', name):
        await message.answer("❌ Неверный формат. Пример: Иван З.\nПопробуйте ещё раз:")
        return
    await save_admin_name(message.from_user.id, name, bot_token)
    await state.clear()
    await message.answer(f"✅ Имя изменено на <b>{name}</b>", parse_mode=ParseMode.HTML, reply_markup=get_admin_main_menu(bot_token))

@admin_router.message(Command("reply"))
async def reply_command(message: Message, **data):
    bot_token = data.get("bot_token", "main")
    if not await is_admin(message.from_user.id, bot_token):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /reply <ID_пользователя> <текст>\nПример: /reply 105 Здравствуйте, чем могу помочь?")
        return
    try:
        parts = args[1].split(maxsplit=1)
        custom_id = int(parts[0])
        reply_text = parts[1] if len(parts) > 1 else ""
    except:
        await message.answer("Неверный формат. Пример: /reply 105 Ваш ответ")
        return
    if not reply_text:
        await message.answer("Введите текст ответа")
        return
    ticket_info = await get_ticket_by_custom_id(custom_id, bot_token)
    if not ticket_info:
        await message.answer(f"❌ Обращение с ID {custom_id} не найдено или уже закрыто")
        return
    ticket_id, user_id, status, title, category, created_at = ticket_info
    admin_name = await get_admin_name(message.from_user.id, bot_token)
    if not admin_name:
        await message.answer("❌ Вы не зарегистрированы. Используйте /start для регистрации.")
        return
    user_info = await get_user_by_custom_id(custom_id)
    if user_info:
        user_id, username, first_name = user_info
    
    current_bot = await get_current_bot(bot_token)
    if not current_bot:
        await message.answer("❌ Ошибка: бот не найден")
        return
    
    try:
        await current_bot.send_message(user_id, f"✉️ <b>Ответ от {admin_name}:</b>\n\n{reply_text}", parse_mode=ParseMode.HTML)
        await update_has_responded(user_id, bot_token)
        await save_message(ticket_id, 'admin', message.from_user.id, reply_text, admin_name, bot_token=bot_token)
        await update_admin_activity(message.from_user.id, bot_token)
        await message.answer(f"✅ Ответ на обращение #{custom_id} отправлен", reply_markup=get_ticket_actions_keyboard(ticket_id, user_id, custom_id))
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@admin_router.message(Command("search"))
async def search_command(message: Message, **data):
    bot_token = data.get("bot_token", "main")
    if not await is_admin(message.from_user.id, bot_token):
        return
    query = message.text.replace("/search", "").strip()
    if not query:
        await message.answer("Введите текст для поиска\nПример: /search проблема с оплатой")
        return
    results = await search_tickets(query, bot_token)
    if not results:
        await message.answer("❌ Ничего не найдено")
        return
    text = f"🔍 Результаты поиска по '{query}':\n\n"
    builder = InlineKeyboardBuilder()
    for r in results[:10]:
        if len(r) == 6:
            ticket_id, custom_id, username, first_name, title, timestamp = r
            time_str = datetime.fromisoformat(timestamp).strftime("%d.%m %H:%M")
            text += f"#{custom_id} - {first_name} (@{username or 'нет'}) [{time_str}]\n📝 {title}\n\n"
        else:
            ticket_id, custom_id, username, first_name, title, timestamp = r
            time_str = datetime.fromisoformat(timestamp).strftime("%d.%m %H:%M")
            text += f"#{custom_id} - {first_name} (@{username or 'нет'}) [{time_str}]\n📝 {title}\n\n"
        builder.button(text=f"#{custom_id}", callback_data=f"admin:view_ticket_{ticket_id}")
    builder.button(text="◀️ Назад", callback_data="menu:main")
    builder.adjust(4)
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())

@user_router.message(TicketStates.waiting_title)
async def handle_ticket_title(message: Message, state: FSMContext, **data):
    bot_token = data.get("bot_token", "main")
    title = message.text.strip()
    if len(title) < TITLE_MIN_LENGTH or len(title) > TITLE_MAX_LENGTH:
        await message.answer(f"❌ Заголовок должен содержать от {TITLE_MIN_LENGTH} до {TITLE_MAX_LENGTH} символов.\nПопробуйте ещё раз:")
        return
    data_state = await state.get_data()
    category = data_state.get('category', 'question')
    await message.answer(
        f"✅ Заголовок '{title}' принят!\n\n"
        f"📝 Теперь напишите ваше обращение (от {MESSAGE_MIN_LENGTH} до {MESSAGE_MAX_LENGTH} символов).\n"
        f"Можно отправить текст, фото (до {MAX_PHOTOS_PER_MESSAGE} шт.), видео (до {MAX_VIDEO_DURATION} сек).\n\n"
        f"⏰ У вас есть {ACTION_TIMEOUT // 60} минут на отправку сообщения, иначе обращение будет автоматически закрыто."
    )
    await state.update_data(title=title, category=category)
    await state.set_state(TicketStates.waiting_initial_message)
    asyncio.create_task(start_timeout_timer(message.from_user.id, "initial_message", ACTION_TIMEOUT, state, bot_token))

@user_router.message(TicketStates.waiting_initial_message)
async def handle_initial_message(message: Message, state: FSMContext, **data):
    bot_token = data.get("bot_token", "main")
    user = message.from_user
    if message.photo:
        if message.media_group_id:
            await message.answer(f"❌ Альбомы не поддерживаются. Отправьте до {MAX_PHOTOS_PER_MESSAGE} фото в одном сообщении.")
            return
    if message.video:
        is_valid, duration = await check_video_duration(message)
        if not is_valid:
            await message.answer(f"❌ Видео слишком длинное! Максимум {MAX_VIDEO_DURATION} сек")
            return
    content_length = 0
    if message.text:
        content_length = len(message.text.strip())
    elif message.caption:
        content_length = len(message.caption.strip())
    if content_length > 0 and (content_length < MESSAGE_MIN_LENGTH or content_length > MESSAGE_MAX_LENGTH):
        await message.answer(f"❌ Текст должен содержать от {MESSAGE_MIN_LENGTH} до {MESSAGE_MAX_LENGTH} символов.\nСейчас: {content_length} символов")
        return
    data_state = await state.get_data()
    title = data_state.get('title')
    category = data_state.get('category', 'question')
    ticket_id = await create_new_ticket(user, title, category, bot_token)
    custom_id = await get_or_create_custom_id(user.id, user.username, user.first_name, user.last_name)
    await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)
    if message.text:
        await save_message(ticket_id, 'user', user.id, message.text, user.first_name, bot_token=bot_token)
        content_for_admin = message.text
    elif message.photo:
        file_id = message.photo[-1].file_id
        await save_message(ticket_id, 'user', user.id, f"[Фото] {message.caption or ''}", user.first_name,
                    file_id=file_id, media_type='photo', caption=message.caption, bot_token=bot_token)
        content_for_admin = f"[Фото] {message.caption or ''}"
    elif message.video:
        file_id = message.video.file_id
        await save_message(ticket_id, 'user', user.id, f"[Видео] {message.caption or ''}", user.first_name,
                    file_id=file_id, media_type='video', caption=message.caption, bot_token=bot_token)
        content_for_admin = f"[Видео] {message.caption or ''}"
    else:
        await message.answer("❌ Неподдерживаемый тип сообщения")
        return
    await increment_initial_count(user.id, bot_token)
    user_info = (
        f"<b>Обращение #{custom_id}</b>\n"
        f"📝 Тема: {title}\n"
        f"<a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
        f"ID: <code>{custom_id}</code>\n"
        f"📱 @{user.username or 'нет'}\n"
        f"📂 {category}\n"
        f"─" * 30 + "\n"
        f"{content_for_admin}"
    )
    
    current_bot = await get_current_bot(bot_token)
    if not current_bot:
        await message.answer("❌ Ошибка: бот не найден")
        return
    
    for admin_id in ADMIN_IDS:
        try:
            await current_bot.send_message(admin_id, user_info, parse_mode=ParseMode.HTML)
            await message.forward(admin_id)
        except Exception as e:
            logging.error(f"❌ Ошибка отправки админу {admin_id}: {e}")
    
    await message.answer(
        f'✅ Обращение #{custom_id} создано и отправлено! <tg-emoji emoji-id="{PREMIUM_EMOJIS["party"]}">🎉</tg-emoji>\n\n'
        f'📝 Тема: {title}\n'
        f'📂 Категория: {category}\n\n'
        f'⏳ Ожидайте ответа поддержки. Вы можете отправить ещё {INITIAL_MESSAGE_LIMIT - 1} сообщение до ответа.',
        parse_mode=ParseMode.HTML,
        reply_markup=get_after_message_menu(ticket_id, custom_id)
    )
    await current_bot.send_sticker(message.chat.id, PREMIUM_STICKERS["success"])
    
    asyncio.create_task(start_waiting_timer(user.id, bot_token, ticket_id))
    
    await state.set_state(TicketStates.in_dialog)

@user_router.message(TicketStates.waiting_feedback)
async def handle_feedback(message: Message, state: FSMContext, **data):
    bot_token = data.get("bot_token", "main")
    data_state = await state.get_data()
    ticket_id = data_state.get('ticket_id')
    rating = data_state.get('rating')
    admin_id = data_state.get('admin_id')
    admin_name = data_state.get('admin_name')
    user_id = data_state.get('user_id')
    user_custom_id = data_state.get('user_custom_id')
    feedback = message.text if message.text else None
    await save_rating_and_feedback(ticket_id, rating, feedback, admin_id, admin_name, user_id or message.from_user.id, user_custom_id, bot_token)
    if feedback:
        await message.answer(
            f'✅ Спасибо за ваш развёрнутый отзыв! <tg-emoji emoji-id="{PREMIUM_EMOJIS["heart"]}">❤️</tg-emoji>\n'
            f'Он поможет нам стать лучше.\n\n'
            f'Главное меню {BOT_USERNAME}:',
            parse_mode=ParseMode.HTML,
            reply_markup=get_user_main_menu(bot_token)
        )
    else:
        await message.answer(
            f'✅ Спасибо за оценку! <tg-emoji emoji-id="{PREMIUM_EMOJIS["star"]}">⭐</tg-emoji>\n\n'
            f'Главное меню {BOT_USERNAME}:',
            parse_mode=ParseMode.HTML,
            reply_markup=get_user_main_menu(bot_token)
        )
    await state.clear()

@clone_router.message(CloneBotStates.waiting_for_token)
async def clone_token_received(message: Message, state: FSMContext, **data):
    token = message.text.strip()
    await message.answer("🔄 Проверяю токен...")
    
    is_valid, username, bot_name = await verify_bot_token(token)
    if not is_valid:
        await message.answer("❌ Неверный токен. Убедитесь, что вы скопировали его правильно.\nПопробуйте ещё раз или отправьте /cancel")
        return
    
    await state.update_data(token=token, username=username, bot_name=bot_name)
    await message.answer(
        f'✅ Бот @{username} успешно проверен! <tg-emoji emoji-id="{PREMIUM_EMOJIS["check"]}">✅</tg-emoji>\n\n'
        f"Теперь укажите ID администраторов (через запятую), которые будут иметь доступ к этому боту.\n"
        f"Пример: 123456789, 987654321\n\n"
        f"Вы (ID: {message.from_user.id}) будете добавлены автоматически.\n\n"
        f"⏰ У вас есть {ACTION_TIMEOUT // 60} минут на ввод админов",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(CloneBotStates.waiting_for_admins)
    asyncio.create_task(start_timeout_timer(message.from_user.id, "clone_admins", ACTION_TIMEOUT, state, data.get("bot_token", "main")))

@clone_router.message(CloneBotStates.waiting_for_admins)
async def clone_admins_received(message: Message, state: FSMContext, **data):
    data_state = await state.get_data()
    token = data_state['token']
    username = data_state['username']
    bot_name = data_state['bot_name']
    
    admin_ids = [message.from_user.id]
    if message.text.strip():
        try:
            parts = message.text.strip().split(',')
            for part in parts:
                admin_id = int(part.strip())
                if admin_id not in admin_ids:
                    admin_ids.append(admin_id)
        except:
            await message.answer("❌ Неверный формат. Введите ID через запятую.\nПример: 123456789, 987654321")
            return
    
    await save_clone_bot(token, message.from_user.id, username, bot_name, admin_ids)
    success = await start_clone_bot(token)
    
    current_bot = await get_current_bot(data.get("bot_token", "main"))
    if success:
        await message.answer(
            f'✅ <b>Бот @{username} успешно создан и запущен!</b> <tg-emoji emoji-id="{PREMIUM_EMOJIS["rocket"]}">🚀</tg-emoji>\n\n'
            f"📋 Информация:\n"
            f"├ Имя: {bot_name}\n"
            f"├ Юзернейм: @{username}\n"
            f"├ Админы: {', '.join(map(str, admin_ids))}\n"
            f"└ Статус: 🟢 Активен",
            parse_mode=ParseMode.HTML
        )
        if current_bot:
            await current_bot.send_sticker(message.chat.id, PREMIUM_STICKERS["success"])
    else:
        await message.answer(f"❌ Бот @{username} сохранен, но не удалось запустить.\nПопробуйте перезапустить позже.")
    
    await state.clear()

@group_router.message(TriggerStates.waiting_for_trigger_word)
async def process_trigger_word(message: Message, state: FSMContext, **data):
    bot_token = data.get("bot_token", "main")
    trigger_word = message.text.strip().lower()
    if len(trigger_word) < 2 or len(trigger_word) > 50:
        await message.answer("❌ Слово-триггер должно содержать от 2 до 50 символов.\nПопробуйте ещё раз:")
        return
    await state.update_data(trigger_word=trigger_word)
    await message.answer(
        f"✅ Слово '{trigger_word}' сохранено.\n\n"
        f"Теперь отправьте ответ, который бот будет отправлять на этот триггер.\n"
        f"Можно отправить: текст, фото, видео, GIF, стикер.\n\n"
        f"❗️ Фото/видео/GIF должны быть без текста (текст станет подписью)\n\n"
        f"⏰ У вас есть {ACTION_TIMEOUT // 60} минут на отправку ответа",
        reply_markup=get_cancel_keyboard(for_group=True)
    )
    await state.set_state(TriggerStates.waiting_for_trigger_response)
    asyncio.create_task(start_timeout_timer(message.from_user.id, "trigger_response", ACTION_TIMEOUT, state, bot_token))

@user_router.message(F.chat.type == 'private')
async def handle_user_message(message: Message, state: FSMContext, **data):
    if message.text and message.text.startswith('/'):
        return
    bot_token = data.get("bot_token", "main")
    user = message.from_user
    if await check_blacklist(user.id, bot_token):
        await message.answer(f"⛔ Вы находитесь в черном списке и не можете использовать поддержку.")
        return
    current_state = await state.get_state()
    if current_state != TicketStates.in_dialog.state:
        if await has_open_ticket(user.id, bot_token):
            open_ticket = await get_open_ticket_info(user.id, bot_token)
            if open_ticket:
                ticket_id, custom_id, title, _, _, has_responded, initial_count = open_ticket
                if not has_responded and initial_count >= INITIAL_MESSAGE_LIMIT:
                    await message.answer_sticker(PREMIUM_STICKERS["waiting"])
                    await message.answer(f"⏳ Вы уже отправили максимальное количество сообщений ({INITIAL_MESSAGE_LIMIT}). Дождитесь ответа поддержки.")
                    return
                await state.set_state(TicketStates.in_dialog)
                await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)
            else:
                await message.answer("❌ У вас нет активного обращения.\nНачните новое через /start", reply_markup=InlineKeyboardBuilder().button(text="📝 Начать", callback_data="support:start").as_markup())
                return
        else:
            return
    data_state = await state.get_data()
    ticket_id = data_state.get('ticket_id')
    custom_id = data_state.get('custom_id')
    title = data_state.get('title')
    if not ticket_id:
        open_ticket = await get_open_ticket_info(user.id, bot_token)
        if open_ticket:
            ticket_id, custom_id, title, _, _, has_responded, initial_count = open_ticket
            if not has_responded and initial_count >= INITIAL_MESSAGE_LIMIT:
                await message.answer_sticker(PREMIUM_STICKERS["waiting"])
                await message.answer(f"⏳ Вы уже отправили максимальное количество сообщений ({INITIAL_MESSAGE_LIMIT}). Дождитесь ответа поддержки.")
                return
            await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)
        else:
            await message.answer("❌ Ошибка: обращение не найдено.\nНачните новое через /start")
            await state.clear()
            return
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT status, has_responded, initial_messages_count FROM tickets WHERE id = ?", (ticket_id,))
        row = await cursor.fetchone()
        if not row or row[0] != 'open':
            await message.answer("❌ Ваше обращение уже закрыто.\nСоздайте новое, если нужно.", reply_markup=InlineKeyboardBuilder().button(text="📝 Создать", callback_data="support:start").as_markup())
            await state.clear()
            return
        status, has_responded, initial_count = row
        if not has_responded and initial_count >= INITIAL_MESSAGE_LIMIT:
            await message.answer_sticker(PREMIUM_STICKERS["waiting"])
            await message.answer(f"⏳ Вы уже отправили максимальное количество сообщений ({INITIAL_MESSAGE_LIMIT}). Дождитесь ответа поддержки.")
            return
    can_send, error_msg = await can_user_send_message(user.id, bot_token)
    if not can_send:
        await message.answer(error_msg)
        return
    blocked, block_msg = await check_spam_block(user.id, bot_token)
    if blocked:
        await message.answer(block_msg)
        return
    if message.sticker or message.animation or message.dice:
        await message.answer("❌ Пожалуйста, отправляйте текстовые сообщения или фото/видео по теме.")
        return
    if message.photo:
        if message.media_group_id:
            if message.media_group_id not in media_groups_buffer:
                media_groups_buffer[message.media_group_id] = []
