import aiohttp
import asyncio
import logging
import sqlite3
import re
import json
import requests
import random
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from collections import defaultdict

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command, ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile, ChatMemberUpdated
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
USER_ID_COUNTER = 1

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
            bot_token TEXT DEFAULT 'main',
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
            bot_token TEXT DEFAULT 'main'
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
            bot_token TEXT DEFAULT 'main',
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
            bot_token TEXT DEFAULT 'main',
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
            bot_token TEXT DEFAULT 'main',
            PRIMARY KEY (group_id, message_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_consent (
            user_id INTEGER PRIMARY KEY,
            consented_at TEXT NOT NULL,
            bot_token TEXT DEFAULT 'main'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blacklist (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            blocked_at TEXT NOT NULL,
            blocked_by INTEGER,
            bot_token TEXT DEFAULT 'main'
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
            updated_at TEXT NOT NULL
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
            UNIQUE(chat_id, trigger_word)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trigger_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_id INTEGER NOT NULL,
            used_at TEXT NOT NULL,
            used_by INTEGER,
            FOREIGN KEY (trigger_id) REFERENCES triggers (id) ON DELETE CASCADE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            data TEXT,
            expires_at TEXT NOT NULL
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
        
        try:
            cursor.execute("SELECT title FROM tickets LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE tickets ADD COLUMN title TEXT")
        
        try:
            cursor.execute("SELECT initial_messages_count FROM tickets LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE tickets ADD COLUMN initial_messages_count INTEGER DEFAULT 0")
        
        try:
            cursor.execute("SELECT last_name FROM users LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE users ADD COLUMN last_name TEXT")
            cursor.execute("ALTER TABLE users ADD COLUMN last_activity TEXT")
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ Ошибка миграции: {e}")

init_db()

active_bots = {}
bot_sessions = {}
pending_timeouts = {}

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

async def start_timeout_timer(user_id: int, action_type: str, timeout_seconds: int, state: FSMContext):
    """Запуск таймера для отмены действия при бездействии"""
    await asyncio.sleep(timeout_seconds)
    
    current_state = await state.get_state()
    if current_state:
        data = await state.get_data()
        if data.get('action_type') == action_type:
            await state.clear()
            
            try:
                conn = sqlite3.connect(DB_FILE, timeout=30)
                cursor = conn.cursor()
                now = datetime.utcnow().isoformat()
                cursor.execute("INSERT INTO pending_actions (user_id, action_type, data, expires_at) VALUES (?, ?, ?, ?)",
                              (user_id, f"timeout_{action_type}", json.dumps({"timeout": True}), now))
                conn.commit()
                conn.close()
            except:
                pass
            
            try:
                await bot.send_message(
                    user_id,
                    f"⏰ Время на выполнение действия истекло. Операция отменена по причине бездействия."
                )
            except:
                pass

def get_or_create_custom_id(user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> int:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        
        cursor.execute("SELECT custom_id FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        
        if row:
            custom_id = row[0]
            cursor.execute("""
                UPDATE users 
                SET username = ?, first_name = ?, last_name = ?, last_activity = ? 
                WHERE user_id = ?
            """, (username, first_name, last_name, datetime.utcnow().isoformat(), user_id))
        else:
            cursor.execute("SELECT MAX(custom_id) FROM users")
            max_id = cursor.fetchone()[0]
            custom_id = (max_id + 1) if max_id and max_id >= USER_ID_COUNTER else USER_ID_COUNTER
            
            now = datetime.utcnow().isoformat()
            cursor.execute("""
                INSERT INTO users (user_id, custom_id, username, first_name, last_name, registered_at, last_activity)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, custom_id, username, first_name, last_name, now, now))
        
        conn.commit()
        conn.close()
        return custom_id
    except Exception as e:
        logging.error(f"❌ Ошибка get_or_create_custom_id: {e}")
        return 0

def check_ticket_cooldown(user_id: int, bot_token: str = 'main') -> tuple[bool, Optional[int]]:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT created_at FROM tickets 
            WHERE user_id = ? AND bot_token = ? 
            ORDER BY created_at DESC LIMIT 1
        """, (user_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0]:
            last_time = datetime.fromisoformat(row[0])
            diff = datetime.utcnow() - last_time
            if diff.total_seconds() < TICKET_COOLDOWN:
                remaining = int(TICKET_COOLDOWN - diff.total_seconds())
                return True, remaining
        return False, None
    except Exception as e:
        logging.error(f"❌ Ошибка check_ticket_cooldown: {e}")
        return False, None

def has_open_ticket(user_id: int, bot_token: str = 'main') -> bool:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tickets WHERE user_id = ? AND bot_token = ? AND status = 'open'", 
                      (user_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        return row is not None
    except Exception as e:
        logging.error(f"❌ Ошибка has_open_ticket: {e}")
        return False

def get_open_ticket_info(user_id: int, bot_token: str = 'main') -> Optional[tuple]:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, custom_user_id, title, category, created_at, has_responded, initial_messages_count
            FROM tickets 
            WHERE user_id = ? AND bot_token = ? AND status = 'open'
        """, (user_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        return row if row else None
    except Exception as e:
        logging.error(f"❌ Ошибка get_open_ticket_info: {e}")
        return None

def can_user_send_message(user_id: int, bot_token: str = 'main') -> tuple[bool, Optional[str]]:
    """Проверяет, может ли пользователь отправить сообщение"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, has_responded, initial_messages_count FROM tickets 
            WHERE user_id = ? AND bot_token = ? AND status = 'open'
        """, (user_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return False, "❌ У вас нет открытого обращения"
        
        ticket_id, has_responded, initial_count = row
        
        if has_responded:
            return True, None
        
        if initial_count >= INITIAL_MESSAGE_LIMIT:
            return False, "⏳ Дождитесь ответа поддержки прежде чем отправить новое сообщение"
        
        return True, None
    except:
        return False, "❌ Ошибка проверки"

def increment_initial_count(user_id: int, bot_token: str = 'main'):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tickets SET initial_messages_count = initial_messages_count + 1 
            WHERE user_id = ? AND bot_token = ? AND status = 'open'
        """, (user_id, bot_token))
        conn.commit()
        conn.close()
    except:
        pass

def has_consent(user_id: int, bot_token: str = 'main') -> bool:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT consented_at FROM user_consent WHERE user_id = ? AND bot_token = ?", 
                      (user_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        return row is not None
    except:
        return False

def save_consent(user_id: int, bot_token: str = 'main'):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            INSERT OR REPLACE INTO user_consent (user_id, consented_at, bot_token)
            VALUES (?, ?, ?)
        """, (user_id, now, bot_token))
        conn.commit()
        conn.close()
    except:
        pass

def is_admin(user_id: int, bot_token: str = 'main') -> bool:
    if bot_token == 'main':
        return user_id in ADMIN_IDS
    else:
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT admins FROM clone_bots WHERE token = ?", (bot_token,))
            row = cursor.fetchone()
            conn.close()
            if row:
                admins = json.loads(row[0])
                return user_id in admins
        except:
            pass
    return False

def is_chat_creator(user_id: int, chat_id: int) -> bool:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT creator_id FROM group_settings WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        conn.close()
        return row and row[0] == user_id
    except:
        return False

def get_admin_name(user_id: int, bot_token: str = 'main') -> Optional[str]:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT display_name FROM support_admins WHERE user_id = ? AND bot_token = ?", 
                      (user_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except:
        return None

def save_admin_name(user_id: int, display_name: str, bot_token: str = 'main'):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            INSERT OR REPLACE INTO support_admins (user_id, display_name, registered_at, last_active, bot_token)
            VALUES (?, ?, COALESCE((SELECT registered_at FROM support_admins WHERE user_id = ? AND bot_token = ?), ?), ?, ?)
        """, (user_id, display_name, user_id, bot_token, now, now, bot_token))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Ошибка save_admin_name: {e}")

def update_admin_activity(user_id: int, bot_token: str = 'main'):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            UPDATE support_admins 
            SET last_active = ?, total_replies = total_replies + 1 
            WHERE user_id = ? AND bot_token = ?
        """, (now, user_id, bot_token))
        conn.commit()
        conn.close()
    except:
        pass

def add_admin_review(admin_id: int, admin_name: str, ticket_id: int, user_id: int, 
                     user_custom_id: int, rating: int, feedback: str = None, bot_token: str = 'main'):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        
        cursor.execute("""
            INSERT INTO admin_reviews (admin_id, admin_name, ticket_id, user_id, user_custom_id, rating, feedback, created_at, bot_token)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (admin_id, admin_name, ticket_id, user_id, user_custom_id, rating, feedback, now, bot_token))
        
        cursor.execute("""
            SELECT total_ratings, avg_rating FROM support_admins 
            WHERE user_id = ? AND bot_token = ?
        """, (admin_id, bot_token))
        row = cursor.fetchone()
        
        if row:
            total_ratings, avg_rating = row
            new_total = total_ratings + 1
            new_avg = (avg_rating * total_ratings + rating) / new_total
            cursor.execute("""
                UPDATE support_admins 
                SET total_ratings = ?, avg_rating = ? 
                WHERE user_id = ? AND bot_token = ?
            """, (new_total, new_avg, admin_id, bot_token))
        
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Ошибка add_admin_review: {e}")

def get_admin_reviews(admin_id: int, bot_token: str = 'main', limit: int = 20) -> List:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT rating, feedback, created_at, user_custom_id, ticket_id
            FROM admin_reviews 
            WHERE admin_id = ? AND bot_token = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (admin_id, bot_token, limit))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except:
        return []

def create_new_ticket(user: types.User, title: str, category: str = 'question', bot_token: str = 'main') -> int:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        custom_id = get_or_create_custom_id(user.id, user.username, user.first_name, user.last_name)
        
        cursor.execute("""
            INSERT INTO tickets (
                user_id, custom_user_id, username, first_name, last_name, 
                title, category, created_at, last_message_at, status, bot_token
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
        """, (user.id, custom_id, user.username, user.first_name, user.last_name, 
              title, category, now, now, bot_token))
        ticket_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        asyncio.create_task(notify_admins_new_ticket(user, ticket_id, custom_id, title, category, bot_token))
        return ticket_id
    except Exception as e:
        logging.error(f"❌ Ошибка create_new_ticket: {e}")
        return 0

async def notify_admins_new_ticket(user: types.User, ticket_id: int, custom_id: int, title: str, category: str, bot_token: str = 'main'):
    category_names = {
        'question': '❓ Вопрос',
        'problem': '⚠️ Проблема',
        'suggestion': '💡 Предложение',
        'other': '📌 Другое'
    }
    
    category_text = category_names.get(category, category)
    
    text = (
        f"🆕 <b>НОВОЕ ОБРАЩЕНИЕ #{custom_id}</b>\n\n"
        f"📝 <b>Тема:</b> {title}\n"
        f"👤 Пользователь: <a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
        f"🆔 ID: <code>{custom_id}</code>\n"
        f"📱 @{user.username or 'нет'}\n"
        f"📂 {category_text}\n"
        f"⏰ {datetime.utcnow().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Действия:"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять", callback_data=f"admin:accept_ticket:{ticket_id}:{user.id}:{custom_id}")
    builder.button(text="⛔ Отклонить", callback_data=f"admin:reject_ticket:{ticket_id}:{user.id}:{custom_id}")
    builder.button(text="🚫 В ЧС", callback_data=f"admin:blacklist_ticket:{user.id}:{custom_id}")
    builder.adjust(2, 1)
    
    if bot_token == 'main':
        admin_ids = ADMIN_IDS
    else:
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT admins FROM clone_bots WHERE token = ?", (bot_token,))
            row = cursor.fetchone()
            admin_ids = json.loads(row[0]) if row else []
            conn.close()
        except:
            admin_ids = []
    
    for admin_id in admin_ids:
        try:
            if bot_token == 'main':
                await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
            else:
                clone_bot, _, _ = active_bots.get(bot_token, (None, None, None))
                if clone_bot:
                    await clone_bot.send_message(admin_id, text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        except Exception as e:
            logging.error(f"❌ Ошибка уведомления админа {admin_id}: {e}")

def check_spam_block(user_id: int, bot_token: str = 'main') -> tuple[bool, Optional[str]]:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT blocked_until FROM tickets WHERE user_id = ? AND bot_token = ? AND status = 'open'", 
                      (user_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0]:
            blocked_until = datetime.fromisoformat(row[0])
            if datetime.utcnow() < blocked_until:
                remaining = (blocked_until - datetime.utcnow()).seconds // 60
                return True, f"⛔ Вы заблокированы на {remaining} мин. за спам."
        return False, None
    except:
        return False, None

def update_message_time(user_id: int, bot_token: str = 'main'):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            UPDATE tickets SET last_message_at = ? 
            WHERE user_id = ? AND bot_token = ? AND status = 'open'
        """, (now, user_id, bot_token))
        conn.commit()
        conn.close()
    except:
        pass

def get_ticket_by_custom_id(custom_id: int, bot_token: str = 'main') -> Optional[tuple]:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, user_id, status, title, category, created_at 
            FROM tickets 
            WHERE custom_user_id = ? AND bot_token = ? AND status = 'open'
        """, (custom_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        return row if row else None
    except:
        return None

def get_user_by_custom_id(custom_id: int) -> Optional[tuple]:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, first_name FROM users WHERE custom_id = ?", (custom_id,))
        row = cursor.fetchone()
        conn.close()
        return row if row else None
    except:
        return None

def update_has_responded(user_id: int, bot_token: str = 'main'):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tickets SET has_responded = 1 
            WHERE user_id = ? AND bot_token = ? AND status = 'open'
        """, (user_id, bot_token))
        conn.commit()
        conn.close()
    except:
        pass

def reset_has_responded(user_id: int, bot_token: str = 'main'):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tickets SET has_responded = 0 
            WHERE user_id = ? AND bot_token = ? AND status = 'open'
        """, (user_id, bot_token))
        conn.commit()
        conn.close()
    except:
        pass

def save_message(ticket_id: int, sender_type: str, sender_id: int, content: str, 
                 sender_name: str = None, media_group_id: str = None, 
                 file_id: str = None, media_type: str = None, caption: str = None,
                 bot_token: str = 'main'):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute('''
            INSERT INTO messages (
                ticket_id, sender_type, sender_id, sender_name, content, 
                media_group_id, file_id, media_type, caption, timestamp, bot_token
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ticket_id, sender_type, sender_id, sender_name, content, 
              media_group_id, file_id, media_type, caption, now, bot_token))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Ошибка save_message: {e}")

def save_media_group(group_id: str, ticket_id: int, message_id: int, file_id: str, 
                     media_type: str, caption: str = None, bot_token: str = 'main'):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute('''
            INSERT OR REPLACE INTO media_groups (group_id, ticket_id, message_id, file_id, media_type, caption, timestamp, bot_token)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (group_id, ticket_id, message_id, file_id, media_type, caption, now, bot_token))
        conn.commit()
        conn.close()
    except:
        pass

def get_media_group(group_id: str, bot_token: str = 'main') -> List[tuple]:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT file_id, media_type, caption FROM media_groups 
            WHERE group_id = ? AND bot_token = ? ORDER BY message_id ASC
        ''', (group_id, bot_token))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except:
        return []

def close_ticket(ticket_id: int, closed_by: int, closed_by_name: str = None, bot_token: str = 'main') -> bool:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            UPDATE tickets 
            SET status = 'closed', closed_at = ?, closed_by = ?, closed_by_name = ? 
            WHERE id = ? AND status = 'open' AND bot_token = ?
        """, (now, closed_by, closed_by_name, ticket_id, bot_token))
        success = cursor.rowcount > 0
        
        if success and closed_by != 0:
            cursor.execute("""
                UPDATE support_admins 
                SET total_closed = total_closed + 1 
                WHERE user_id = ? AND bot_token = ?
            """, (closed_by, bot_token))
        
        conn.commit()
        conn.close()
        return success
    except Exception as e:
        logging.error(f"❌ Ошибка close_ticket: {e}")
        return False

def save_rating_and_feedback(ticket_id: int, rating: int, feedback: str = None, 
                            admin_id: int = None, admin_name: str = None, 
                            user_id: int = None, user_custom_id: int = None,
                            bot_token: str = 'main'):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE tickets SET rating = ?, feedback_text = ? 
            WHERE id = ? AND bot_token = ?
        """, (rating, feedback, ticket_id, bot_token))
        
        if admin_id and user_id:
            add_admin_review(admin_id, admin_name, ticket_id, user_id, user_custom_id, rating, feedback, bot_token)
        
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Ошибка save_rating_and_feedback: {e}")

def get_ticket_messages(ticket_id: int, bot_token: str = 'main') -> List:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT sender_type, sender_name, content, timestamp, media_group_id, file_id, media_type, caption
            FROM messages 
            WHERE ticket_id = ? AND bot_token = ?
            ORDER BY timestamp ASC
        ''', (ticket_id, bot_token))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except:
        return []

def get_all_open_tickets(bot_token: str = 'main') -> List:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, custom_user_id, username, first_name, title, category, created_at, last_message_at, has_responded
            FROM tickets
            WHERE status = 'open' AND bot_token = ?
            ORDER BY created_at ASC
        ''', (bot_token,))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except:
        return []

def get_admin_tickets(admin_id: int, bot_token: str = 'main') -> List:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT DISTINCT t.id, t.custom_user_id, t.username, t.first_name, t.title, t.status, t.created_at, t.last_message_at
            FROM tickets t
            JOIN messages m ON t.id = m.ticket_id
            WHERE m.sender_type = 'admin' AND m.sender_id = ? AND t.bot_token = ?
            ORDER BY t.last_message_at DESC
            LIMIT 50
        ''', (admin_id, bot_token))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except:
        return []

def search_tickets(query: str, bot_token: str = 'main') -> List:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, custom_user_id, username, first_name, title, created_at
            FROM tickets
            WHERE title LIKE ? AND bot_token = ?
            ORDER BY created_at DESC
            LIMIT 20
        """, (f"%{query}%", bot_token))
        by_title = cursor.fetchall()
        
        cursor.execute("""
            SELECT DISTINCT t.id, t.custom_user_id, t.username, t.first_name, t.title, m.timestamp
            FROM messages m
            JOIN tickets t ON m.ticket_id = t.id
            WHERE m.content LIKE ? AND m.sender_type = 'user' AND t.bot_token = ?
            ORDER BY m.timestamp DESC
            LIMIT 20
        """, (f"%{query}%", bot_token))
        by_message = cursor.fetchall()
        
        conn.close()
        
        seen = set()
        results = []
        for r in by_title + by_message:
            if r[0] not in seen:
                seen.add(r[0])
                results.append(r)
        
        return results[:20]
    except:
        return []

def get_admin_profile(admin_id: int, bot_token: str = 'main') -> Dict[str, Any]:
    name = get_admin_name(admin_id, bot_token)
    
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT registered_at, last_active, total_replies, total_closed, total_ratings, avg_rating
            FROM support_admins 
            WHERE user_id = ? AND bot_token = ?
        """, (admin_id, bot_token))
        row = cursor.fetchone()
        
        profile = {
            'name': name,
            'admin_id': admin_id,
            'registered': 'неизвестно',
            'last_active': 'никогда',
            'total_replies': 0,
            'total_closed': 0,
            'total_ratings': 0,
            'avg_rating': 0,
            'reviews': []
        }
        
        if row:
            profile['registered'] = datetime.fromisoformat(row[0]).strftime('%d.%m.%Y %H:%M') if row[0] else 'неизвестно'
            profile['last_active'] = datetime.fromisoformat(row[1]).strftime('%d.%m.%Y %H:%M') if row[1] else 'никогда'
            profile['total_replies'] = row[2]
            profile['total_closed'] = row[3]
            profile['total_ratings'] = row[4]
            profile['avg_rating'] = round(row[5], 1) if row[5] else 0
        
        conn.close()
        
        reviews = get_admin_reviews(admin_id, bot_token, 20)
        for r in reviews:
            rating, feedback, created_at, user_custom_id, ticket_id = r
            profile['reviews'].append({
                'rating': rating,
                'feedback': feedback,
                'date': datetime.fromisoformat(created_at).strftime('%d.%m.%Y %H:%M'),
                'user_id': user_custom_id,
                'ticket_id': ticket_id
            })
        
        return profile
    except:
        return {'name': name, 'admin_id': admin_id, 'reviews': []}

def get_statistics(bot_token: str = 'main') -> Dict[str, Any]:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        stats = {}
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE bot_token = ?", (bot_token,))
        stats['total_tickets'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'open' AND bot_token = ?", (bot_token,))
        stats['open_tickets'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'closed' AND bot_token = ?", (bot_token,))
        stats['closed_tickets'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT AVG(rating) FROM tickets WHERE rating IS NOT NULL AND bot_token = ?", (bot_token,))
        avg_rating = cursor.fetchone()[0]
        stats['avg_rating'] = round(avg_rating, 1) if avg_rating else 0
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE rating = 5 AND bot_token = ?", (bot_token,))
        stats['rating_5'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE rating = 4 AND bot_token = ?", (bot_token,))
        stats['rating_4'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE rating = 3 AND bot_token = ?", (bot_token,))
        stats['rating_3'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE rating = 2 AND bot_token = ?", (bot_token,))
        stats['rating_2'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE rating = 1 AND bot_token = ?", (bot_token,))
        stats['rating_1'] = cursor.fetchone()[0]
        
        stats['daily'] = []
        for i in range(29, -1, -1):
            day = (datetime.utcnow() - timedelta(days=i)).strftime('%d.%m')
            cursor.execute("""
                SELECT COUNT(*) FROM tickets 
                WHERE date(created_at) = date('now', ?) AND bot_token = ?
            """, (f'-{i} days', bot_token))
            count = cursor.fetchone()[0]
            stats['daily'].append((day, count))
        
        cursor.execute("""
            SELECT category, COUNT(*) FROM tickets 
            WHERE bot_token = ? 
            GROUP BY category
        """, (bot_token,))
        stats['categories'] = cursor.fetchall()
        
        cursor.execute("""
            SELECT display_name, total_replies, avg_rating, total_ratings
            FROM support_admins 
            WHERE bot_token = ? AND total_ratings > 0
            ORDER BY avg_rating DESC, total_ratings DESC
            LIMIT 10
        """, (bot_token,))
        stats['top_admins'] = cursor.fetchall()
        
        cursor.execute("""
            SELECT AVG(
                strftime('%s', m.timestamp) - strftime('%s', t.created_at)
            ) FROM tickets t
            JOIN messages m ON t.id = m.ticket_id
            WHERE m.sender_type = 'admin' AND m.bot_token = ? AND m.id = (
                SELECT MIN(id) FROM messages 
                WHERE ticket_id = t.id AND sender_type = 'admin' AND bot_token = ?
            )
        """, (bot_token, bot_token))
        avg_response = cursor.fetchone()[0]
        stats['avg_response_seconds'] = int(avg_response) if avg_response else 0
        
        conn.close()
        return stats
    except Exception as e:
        logging.error(f"❌ Ошибка get_statistics: {e}")
        return {}

def add_to_blacklist(user_id: int, reason: str, blocked_by: int, bot_token: str = 'main'):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            INSERT OR REPLACE INTO blacklist (user_id, reason, blocked_at, blocked_by, bot_token)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, reason, now, blocked_by, bot_token))
        
        cursor.execute("""
            UPDATE tickets SET status = 'closed', closed_at = ? 
            WHERE user_id = ? AND bot_token = ? AND status = 'open'
        """, (now, user_id, bot_token))
        
        conn.commit()
        conn.close()
    except:
        pass

def check_blacklist(user_id: int, bot_token: str = 'main') -> bool:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT reason FROM blacklist WHERE user_id = ? AND bot_token = ?", (user_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        return row is not None
    except:
        return False

async def verify_bot_token(token: str) -> tuple[bool, Optional[str], Optional[str]]:
    print(f"🔍 ПРОВЕРКА ТОКЕНА: {token[:10]}...")
    try:
        async with aiohttp.ClientSession() as session:
            print("📡 Отправляю запрос к Telegram...")
            async with session.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10) as response:
                print(f"📥 Статус ответа: {response.status}")
                if response.status == 200:
                    data = await response.json()
                    print(f"📦 Данные: {data}")
                    if data.get('ok'):
                        return True, data['result']['username'], data['result']['first_name']
        return False, None, None
    except Exception as e:
        print(f"❌ ИСКЛЮЧЕНИЕ: {e}")
        return False, None, None
async def start_clone_bot(token: str):
    try:
        session = AiohttpSession()
        bot = Bot(token=token, session=session)
        dp = Dispatcher(storage=MemoryStorage())
        bot_info = await bot.get_me()
        
        asyncio.create_task(dp.start_polling(bot))
        
        active_bots[token] = (bot, dp, bot_info)
        bot_sessions[token] = session
        
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

def save_clone_bot(token: str, owner_id: int, bot_username: str, bot_name: str, admins: List[int]):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            INSERT OR REPLACE INTO clone_bots (token, owner_id, bot_username, bot_name, created_at, last_active, status, admins)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
        """, (token, owner_id, bot_username, bot_name, now, now, json.dumps(admins)))
        conn.commit()
        conn.close()
    except:
        pass

def get_clone_bots(owner_id: int) -> List:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT token, bot_username, bot_name, created_at, status FROM clone_bots WHERE owner_id = ?", 
                      (owner_id,))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except:
        return []

def delete_clone_bot(token: str):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM clone_bots WHERE token = ?", (token,))
        conn.commit()
        conn.close()
    except:
        pass

def update_clone_bot_admins(token: str, admins: List[int]):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("UPDATE clone_bots SET admins = ? WHERE token = ?", 
                      (json.dumps(admins), token))
        conn.commit()
        conn.close()
    except:
        pass

def get_bot_display_info(bot_token: str = 'main') -> Dict[str, str]:
    if bot_token == 'main':
        return {'name': 'Основной бот поддержки', 'username': BOT_USERNAME, 'type': 'main'}
    
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT bot_username, bot_name FROM clone_bots WHERE token = ?", (bot_token,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {'name': row[1] or 'Бот поддержки', 'username': f'@{row[0]}' if row[0] else 'неизвестно', 'type': 'clone'}
    except:
        pass
    return {'name': 'Бот поддержки', 'username': 'неизвестно', 'type': 'clone'}

def format_bot_header(bot_token: str = 'main') -> str:
    info = get_bot_display_info(bot_token)
    if info['type'] == 'main':
        return f"🤖 <b>Основной бот поддержки</b>\n└ {info['username']}\n\n"
    else:
        return f"🤖 <b>Бот поддержки</b>\n└ {info['username']}\n\n"

def get_group_settings(chat_id: int) -> Optional[Dict[str, Any]]:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM group_settings WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'chat_id': row[0], 'chat_title': row[1], 'creator_id': row[2],
                'welcome_enabled': bool(row[3]), 'goodbye_enabled': bool(row[4]),
                'welcome_text': row[5], 'goodbye_text': row[6],
                'welcome_media': row[7], 'welcome_media_type': row[8],
                'goodbye_media': row[9], 'goodbye_media_type': row[10],
                'created_at': row[11], 'updated_at': row[12]
            }
    except:
        pass
    return None

def create_group_settings(chat_id: int, chat_title: str, creator_id: int, bot_token: str = 'main'):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        
        cursor.execute("SELECT chat_id FROM group_settings WHERE chat_id = ?", (chat_id,))
        if cursor.fetchone():
            conn.close()
            return
        
        bot_info = get_bot_display_info(bot_token)
        welcome_text = (
            f"👋 Добро пожаловать в чат, {{name}}!\n\n"
            f"Я - {bot_info['name']}\n"
            f"Этот бот создан для вопросов и предложений.\n"
            f"Если у вас есть вопрос - напишите мне в личные сообщения."
        )
        
        goodbye_text = f"👋 {{name}} покинул чат"
        
        cursor.execute("""
            INSERT INTO group_settings 
            (chat_id, chat_title, creator_id, welcome_enabled, goodbye_enabled, 
             welcome_text, goodbye_text, created_at, updated_at)
            VALUES (?, ?, ?, 1, 1, ?, ?, ?, ?)
        """, (chat_id, chat_title, creator_id, welcome_text, goodbye_text, now, now))
        
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Ошибка create_group_settings: {e}")

def update_group_settings(chat_id: int, **kwargs):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        
        updates = []
        values = []
        for key, value in kwargs.items():
            updates.append(f"{key} = ?")
            values.append(value)
        
        values.append(now)
        values.append(chat_id)
        
        query = f"UPDATE group_settings SET {', '.join(updates)}, updated_at = ? WHERE chat_id = ?"
        cursor.execute(query, values)
        
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Ошибка update_group_settings: {e}")

def reset_welcome_to_default(chat_id: int, bot_token: str = 'main'):
    bot_info = get_bot_display_info(bot_token)
    default_text = (
        f"👋 Добро пожаловать в чат, {{name}}!\n\n"
        f"Я - {bot_info['name']}\n"
        f"Этот бот создан для вопросов и предложений.\n"
        f"Если у вас есть вопрос - напишите мне в личные сообщения."
    )
    update_group_settings(chat_id, welcome_text=default_text, welcome_media=None, welcome_media_type=None)

def reset_goodbye_to_default(chat_id: int):
    default_text = f"👋 {{name}} покинул чат"
    update_group_settings(chat_id, goodbye_text=default_text, goodbye_media=None, goodbye_media_type=None)

def add_trigger(chat_id: int, trigger_word: str, response_type: str, 
                response_content: str, created_by: int, caption: str = None) -> int:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        
        cursor.execute("SELECT id FROM triggers WHERE chat_id = ? AND trigger_word = ?", 
                      (chat_id, trigger_word.lower()))
        existing = cursor.fetchone()
        
        if existing:
            cursor.execute("""
                UPDATE triggers SET response_type = ?, response_content = ?, caption = ?, 
                created_by = ?, created_at = ?, use_count = 0
                WHERE id = ?
            """, (response_type, response_content, caption, created_by, now, existing[0]))
            trigger_id = existing[0]
        else:
            cursor.execute("""
                INSERT INTO triggers (chat_id, trigger_word, response_type, response_content, caption, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (chat_id, trigger_word.lower(), response_type, response_content, caption, created_by, now))
            trigger_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        return trigger_id
    except Exception as e:
        logging.error(f"❌ Ошибка add_trigger: {e}")
        return 0

def delete_trigger(chat_id: int, identifier: str) -> bool:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        
        if identifier.isdigit():
            cursor.execute("DELETE FROM triggers WHERE id = ? AND chat_id = ?", (int(identifier), chat_id))
        else:
            cursor.execute("DELETE FROM triggers WHERE trigger_word = ? AND chat_id = ?", 
                          (identifier.lower(), chat_id))
        
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted
    except:
        return False

def get_triggers(chat_id: int) -> List:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, trigger_word, response_type, use_count, created_at 
            FROM triggers 
            WHERE chat_id = ?
            ORDER BY trigger_word
        """, (chat_id,))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except:
        return []

def get_trigger_stats(trigger_id: int) -> tuple:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), MAX(used_at) FROM trigger_stats WHERE trigger_id = ?", (trigger_id,))
        row = cursor.fetchone()
        conn.close()
        return (row[0], row[1]) if row else (0, None)
    except:
        return (0, None)

def check_trigger(chat_id: int, text: str) -> Optional[Dict]:
    if not text:
        return None
    
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, response_type, response_content, caption 
            FROM triggers 
            WHERE chat_id = ? AND LOWER(trigger_word) = LOWER(?)
        """, (chat_id, text.strip()))
        
        row = cursor.fetchone()
        
        if row:
            trigger_id, response_type, response_content, caption = row
            
            cursor.execute("UPDATE triggers SET use_count = use_count + 1 WHERE id = ?", (trigger_id,))
            cursor.execute("INSERT INTO trigger_stats (trigger_id, used_at) VALUES (?, ?)", 
                          (trigger_id, datetime.utcnow().isoformat()))
            
            conn.commit()
            conn.close()
            
            return {
                'id': trigger_id,
                'type': response_type,
                'content': response_content,
                'caption': caption
            }
        
        conn.close()
        return None
    except:
        return None

async def check_video_duration(message: Message) -> tuple[bool, Optional[int]]:
    if message.video:
        duration = message.video.duration
        if duration > MAX_VIDEO_DURATION:
            return False, duration
    return True, None

def get_admin_main_menu(bot_token: str = 'main') -> InlineKeyboardMarkup:
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

def get_user_main_menu(bot_token: str = 'main') -> InlineKeyboardMarkup:
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

def get_group_main_menu(bot_token: str = 'main') -> InlineKeyboardMarkup:
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
        builder.button(
            text=f"{status_emoji} #{custom_id} - {short_title} ({date})", 
            callback_data=f"user:view_ticket_{ticket_id}"
        )
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

media_groups_buffer: Dict[str, List[Message]] = defaultdict(list)

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if message.chat.type != 'private':
        settings = get_group_settings(message.chat.id)
        bot_token = 'main'
        for token in active_bots.keys():
            if active_bots[token][2].id == bot.id:
                bot_token = token
                break
        
        if not settings and message.from_user:
            create_group_settings(message.chat.id, message.chat.title or "Группа", message.from_user.id, bot_token)
        settings = get_group_settings(message.chat.id)
        
        bot_info = get_bot_display_info(bot_token)
        
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
    bot_token = 'main'
    
    if check_blacklist(user.id):
        await message.answer(
            f"⛔ Вы находитесь в черном списке и не можете использовать поддержку.\n"
            f"Для вопросов обратитесь к {ADMIN_USERNAME}"
        )
        return
    
    custom_id = get_or_create_custom_id(user.id, user.username, user.first_name, user.last_name)
    
    if is_admin(user.id, bot_token):
        if not get_admin_name(user.id, bot_token):
            await message.answer(
                f"👋 Добро пожаловать в панель поддержки {BOT_USERNAME}!\n"
                f"Ваш персональный ID: <code>{custom_id}</code>\n\n"
                f"Введите своё имя в формате:\n"
                f"Имя Ф.\n\n"
                f"Пример: Иван З.",
                parse_mode=ParseMode.HTML
            )
            await state.set_state(AdminRegistration.waiting_for_name)
            asyncio.create_task(start_timeout_timer(user.id, "admin_registration", ACTION_TIMEOUT, state))
        else:
            admin_name = get_admin_name(user.id, bot_token)
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
        open_ticket = get_open_ticket_info(user.id, bot_token)
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

@dp.message(Command("triggers"))
async def cmd_triggers(message: Message, state: FSMContext):
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    
    bot_token = 'main'
    for token in active_bots.keys():
        if active_bots[token][2].id == bot.id:
            bot_token = token
            break
    
    settings = get_group_settings(message.chat.id)
    if not settings:
        if message.from_user:
            create_group_settings(message.chat.id, message.chat.title or "Группа", message.from_user.id, bot_token)
        settings = get_group_settings(message.chat.id)
    
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может просматривать триггеры")
        return
    
    triggers = get_triggers(message.chat.id)
    
    if not triggers:
        await message.answer(
            "📝 В этой группе пока нет триггеров.\n\n"
            "Чтобы добавить триггер, отправьте команду:\n"
            "/addtrigger слово - например: /addtrigger привет"
        )
        return
    
    text = "🔤 <b>Список триггеров:</b>\n\n"
    for t in triggers[:15]:
        trigger_id, word, rtype, use_count, created_at = t
        emoji = "📝" if rtype == 'text' else "📷" if rtype == 'photo' else "🎥" if rtype == 'video' else "🎞️"
        date = datetime.fromisoformat(created_at).strftime("%d.%m.%Y")
        text += f"{emoji} <b>#{trigger_id}</b> - '{word}'\n"
        text += f"└ Использован: {use_count} раз | Создан: {date}\n\n"
    
    text += "\nЧтобы добавить новый триггер: /addtrigger слово\n"
    text += "Чтобы удалить: /deletetrigger слово или /deletetrigger ID"
    
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(Command("addtrigger"))
async def cmd_addtrigger(message: Message, state: FSMContext):
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    
    bot_token = 'main'
    for token in active_bots.keys():
        if active_bots[token][2].id == bot.id:
            bot_token = token
            break
    
    settings = get_group_settings(message.chat.id)
    if not settings:
        if message.from_user:
            create_group_settings(message.chat.id, message.chat.title or "Группа", message.from_user.id, bot_token)
        settings = get_group_settings(message.chat.id)
    
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может добавлять триггеры")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "❌ Использование: /addtrigger слово\n"
            "Пример: /addtrigger привет"
        )
        return
    
    trigger_word = args[1].strip().lower()
    
    if len(trigger_word) < 2 or len(trigger_word) > 50:
        await message.answer(
            "❌ Слово-триггер должно содержать от 2 до 50 символов"
        )
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
    asyncio.create_task(start_timeout_timer(message.from_user.id, "add_trigger", ACTION_TIMEOUT, state))

@dp.message(Command("deletetrigger"))
async def cmd_deletetrigger(message: Message, state: FSMContext):
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    
    settings = get_group_settings(message.chat.id)
    if not settings:
        await message.answer("❌ Сначала настройте группу через /start")
        return
    
    if settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может удалять триггеры")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "❌ Использование: /deletetrigger слово или /deletetrigger ID\n"
            "Пример: /deletetrigger привет\n"
            "Или: /deletetrigger 5"
        )
        return
    
    identifier = args[1].strip()
    
    if delete_trigger(message.chat.id, identifier):
        await message.answer(f"✅ Триггер '{identifier}' успешно удален")
    else:
        await message.answer(f"❌ Триггер '{identifier}' не найден")

@dp.message(Command("hello"))
async def cmd_hello(message: Message, state: FSMContext):
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    
    bot_token = 'main'
    for token in active_bots.keys():
        if active_bots[token][2].id == bot.id:
            bot_token = token
            break
    
    settings = get_group_settings(message.chat.id)
    if not settings:
        if message.from_user:
            create_group_settings(message.chat.id, message.chat.title or "Группа", message.from_user.id, bot_token)
        settings = get_group_settings(message.chat.id)
    
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может изменять приветствие")
        return
    
    if not settings['welcome_enabled']:
        await message.answer(
            "⚠️ Сейчас приветствие отключено. Хотите включить и установить новый текст?",
            reply_markup=get_enable_confirmation_keyboard("welcome_enable")
        )
        await state.update_data(chat_id=message.chat.id, bot_token=bot_token)
        return
    
    has_text = message.text and len(message.text.split()) > 1
    has_media = message.photo or message.video or message.animation
    has_reply = message.reply_to_message is not None
    
    if not (has_text or has_media or has_reply):
        current = f"Текущее приветствие: {settings['welcome_text']}"
        if settings['welcome_media']:
            current += "\n(с медиа)"
        await message.answer(
            f"{current}\n\n"
            f"Чтобы изменить, отправьте команду с контентом:\n"
            f"/hello ваш текст\n"
            f"Или отправьте фото/видео с командой в подписи"
        )
        return
    
    media_type = None
    media_id = None
    caption = None
    
    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.text:
            caption = replied.text
        elif replied.photo:
            if len(replied.photo) > MAX_PHOTOS_PER_MESSAGE:
                await message.answer(f"❌ Максимум {MAX_PHOTOS_PER_MESSAGE} фото в одном сообщении")
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
            if len(message.photo) > MAX_PHOTOS_PER_MESSAGE:
                await message.answer(f"❌ Максимум {MAX_PHOTOS_PER_MESSAGE} фото в одном сообщении")
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
    
    bot_info = get_bot_display_info(bot_token)
    footer = f"\n\nℹ️ Этот бот создан для вопросов и предложений. Напишите мне в ЛС: {bot_info['username']}"
    
    full_caption = (caption or "") + footer
    
    update_data = {
        'welcome_text': full_caption,
        'welcome_media': media_id,
        'welcome_media_type': media_type,
        'welcome_enabled': 1
    }
    update_group_settings(message.chat.id, **update_data)
    
    await message.answer("✅ Приветствие успешно обновлено!")

@dp.message(Command("bye"))
async def cmd_bye(message: Message, state: FSMContext):
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    
    settings = get_group_settings(message.chat.id)
    if not settings:
        if message.from_user:
            create_group_settings(message.chat.id, message.chat.title or "Группа", message.from_user.id)
        settings = get_group_settings(message.chat.id)
    
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может изменять прощание")
        return
    
    if not settings['goodbye_enabled']:
        await message.answer(
            "⚠️ Сейчас прощание отключено. Хотите включить и установить новый текст?",
            reply_markup=get_enable_confirmation_keyboard("goodbye_enable")
        )
        await state.update_data(chat_id=message.chat.id)
        return
    
    has_text = message.text and len(message.text.split()) > 1
    has_media = message.photo or message.video or message.animation
    has_reply = message.reply_to_message is not None
    
    if not (has_text or has_media or has_reply):
        current = f"Текущее прощание: {settings['goodbye_text']}"
        if settings['goodbye_media']:
            current += "\n(с медиа)"
        await message.answer(
            f"{current}\n\n"
            f"Чтобы изменить, отправьте команду с контентом:\n"
            f"/bye ваш текст\n"
            f"Или отправьте фото/видео с командой в подписи"
        )
        return
    
    media_type = None
    media_id = None
    caption = None
    
    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.text:
            caption = replied.text
        elif replied.photo:
            if len(replied.photo) > MAX_PHOTOS_PER_MESSAGE:
                await message.answer(f"❌ Максимум {MAX_PHOTOS_PER_MESSAGE} фото в одном сообщении")
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
            if len(message.photo) > MAX_PHOTOS_PER_MESSAGE:
                await message.answer(f"❌ Максимум {MAX_PHOTOS_PER_MESSAGE} фото в одном сообщении")
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
    
    update_data = {
        'goodbye_text': caption or "👋 {name} покинул чат",
        'goodbye_media': media_id,
        'goodbye_media_type': media_type,
        'goodbye_enabled': 1
    }
    update_group_settings(message.chat.id, **update_data)
    
    await message.answer("✅ Прощание успешно обновлено!")

@dp.message(Command("delhello"))
async def cmd_delhello(message: Message, state: FSMContext):
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    
    bot_token = 'main'
    for token in active_bots.keys():
        if active_bots[token][2].id == bot.id:
            bot_token = token
            break
    
    settings = get_group_settings(message.chat.id)
    if not settings:
        await message.answer("❌ Сначала настройте группу через /start")
        return
    
    if settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может удалять приветствие")
        return
    
    await message.answer(
        "❓ Вы хотите удалить приветствие. Выберите действие:",
        reply_markup=get_welcome_delete_keyboard()
    )
    await state.set_state(WelcomeStates.waiting_for_delete_choice)
    await state.update_data(chat_id=message.chat.id, bot_token=bot_token)

@dp.message(Command("delbye"))
async def cmd_delbye(message: Message, state: FSMContext):
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    
    settings = get_group_settings(message.chat.id)
    if not settings:
        await message.answer("❌ Сначала настройте группу через /start")
        return
    
    if settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может удалять прощание")
        return
    
    await message.answer(
        "❓ Вы хотите удалить прощание. Выберите действие:",
        reply_markup=get_goodbye_delete_keyboard()
    )
    await state.set_state(GoodbyeStates.waiting_for_delete_choice)
    await state.update_data(chat_id=message.chat.id)

@dp.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_user_join(event: ChatMemberUpdated):
    settings = get_group_settings(event.chat.id)
    if not settings or not settings['welcome_enabled']:
        return
    
    user = event.new_chat_member.user
    name = user.full_name
    
    welcome_text = settings['welcome_text'].replace('{name}', name)
    
    try:
        if settings['welcome_media'] and settings['welcome_media_type']:
            if settings['welcome_media_type'] == 'photo':
                await bot.send_photo(
                    event.chat.id,
                    settings['welcome_media'],
                    caption=welcome_text
                )
            elif settings['welcome_media_type'] == 'video':
                await bot.send_video(
                    event.chat.id,
                    settings['welcome_media'],
                    caption=welcome_text
                )
            elif settings['welcome_media_type'] == 'animation':
                await bot.send_animation(
                    event.chat.id,
                    settings['welcome_media'],
                    caption=welcome_text
                )
        else:
            await bot.send_message(event.chat.id, welcome_text)
    except Exception as e:
        logging.error(f"❌ Ошибка отправки приветствия: {e}")

@dp.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_user_leave(event: ChatMemberUpdated):
    settings = get_group_settings(event.chat.id)
    if not settings or not settings['goodbye_enabled']:
        return
    
    user = event.old_chat_member.user
    name = user.full_name
    
    goodbye_text = settings['goodbye_text'].replace('{name}', name)
    
    try:
        if settings['goodbye_media'] and settings['goodbye_media_type']:
            if settings['goodbye_media_type'] == 'photo':
                await bot.send_photo(
                    event.chat.id,
                    settings['goodbye_media'],
                    caption=goodbye_text
                )
            elif settings['goodbye_media_type'] == 'video':
                await bot.send_video(
                    event.chat.id,
                    settings['goodbye_media'],
                    caption=goodbye_text
                )
            elif settings['goodbye_media_type'] == 'animation':
                await bot.send_animation(
                    event.chat.id,
                    settings['goodbye_media'],
                    caption=goodbye_text
                )
        else:
            await bot.send_message(event.chat.id, goodbye_text)
    except Exception as e:
        logging.error(f"❌ Ошибка отправки прощания: {e}")

@dp.message(F.chat.type.in_({'group', 'supergroup'}))
async def handle_group_message(message: Message):
    if not message.text or message.text.startswith('/'):
        return
    
    trigger = check_trigger(message.chat.id, message.text)
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

@dp.message(TriggerStates.waiting_for_trigger_response)
async def process_trigger_response(message: Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data['chat_id']
    trigger_word = data['trigger_word']
    
    if message.video:
        is_valid, duration = await check_video_duration(message)
        if not is_valid:
            await message.answer(
                f"❌ Видео слишком длинное! Максимальная длительность: {MAX_VIDEO_DURATION} секунд.\n"
                f"Ваше видео: {duration} сек. Попробуйте ещё раз."
            )
            return
    
    if message.photo and len(message.photo) > MAX_PHOTOS_PER_MESSAGE:
        await message.answer(f"❌ Максимум {MAX_PHOTOS_PER_MESSAGE} фото в одном сообщении")
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
        await message.answer(
            "❌ Неподдерживаемый тип сообщения.\n"
            "Отправьте текст, фото, видео, GIF или стикер."
        )
        return
    
    trigger_id = add_trigger(chat_id, trigger_word, response_type, response_content, message.from_user.id, caption)
    
    total_uses, last_used = get_trigger_stats(trigger_id)
    
    await message.answer(
        f"✅ Триггер '#{trigger_id} - {trigger_word}' успешно создан!",
        reply_markup=InlineKeyboardBuilder()
            .button(text="📋 Список триггеров", callback_data="trigger:list")
            .button(text="➕ Ещё триггер", callback_data="trigger:add")
            .as_markup()
    )
    await state.clear()

@dp.message(AdminRegistration.waiting_for_name)
async def register_admin(message: Message, state: FSMContext):
    name = message.text.strip()
    
    if not re.match(r'^[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z]\.$', name):
        await message.answer(
            "❌ Неверный формат. Пример: Иван З.\n"
            "Попробуйте ещё раз:"
        )
        return
    
    save_admin_name(message.from_user.id, name)
    await state.clear()
    
    custom_id = get_or_create_custom_id(message.from_user.id)
    
    await message.answer(
        f"✅ Вы зарегистрированы как <b>{name}</b> в {BOT_USERNAME}\n"
        f"Ваш ID: <code>{custom_id}</code>\n\n"
        f"🔧 Панель поддержки готова к работе!",
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_main_menu()
    )

@dp.message(Command("change_name"))
async def change_name_command(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        return
    
    await message.answer(
        "Введите новое имя в формате 'Имя Ф.' (пример: Иван З.):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminEditName.waiting_for_new_name)
    asyncio.create_task(start_timeout_timer(message.from_user.id, "change_name", ACTION_TIMEOUT, state))

@dp.message(AdminEditName.waiting_for_new_name)
async def change_name(message: Message, state: FSMContext):
    name = message.text.strip()
    
    if not re.match(r'^[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z]\.$', name):
        await message.answer(
            "❌ Неверный формат. Пример: Иван З.\n"
            "Попробуйте ещё раз:"
        )
        return
    
    save_admin_name(message.from_user.id, name)
    await state.clear()
    
    await message.answer(
        f"✅ Имя изменено на <b>{name}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_main_menu()
    )

@dp.message(Command("reply"))
async def reply_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Использование: /reply <ID_пользователя> <текст>\n"
            "Пример: /reply 105 Здравствуйте, чем могу помочь?"
        )
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
    
    ticket_info = get_ticket_by_custom_id(custom_id)
    
    if not ticket_info:
        await message.answer(f"❌ Обращение с ID {custom_id} не найдено или уже закрыто")
        return
    
    ticket_id, user_id, status, title, category, created_at = ticket_info
    admin_name = get_admin_name(message.from_user.id)
    
    if not admin_name:
        await message.answer("❌ Вы не зарегистрированы. Используйте /start для регистрации.")
        return
    
    user_info = get_user_by_custom_id(custom_id)
    if user_info:
        user_id, username, first_name = user_info
    
    try:
        await bot.send_message(
            user_id, 
            f"✉️ <b>Ответ от {admin_name}:</b>\n\n{reply_text}",
            parse_mode=ParseMode.HTML
        )
        
        update_has_responded(user_id)
        save_message(ticket_id, 'admin', message.from_user.id, reply_text, admin_name)
        update_admin_activity(message.from_user.id)
        
        await message.answer(
            f"✅ Ответ на обращение #{custom_id} отправлен",
            reply_markup=get_ticket_actions_keyboard(ticket_id, user_id, custom_id)
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("search"))
async def search_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    
    query = message.text.replace("/search", "").strip()
    if not query:
        await message.answer("Введите текст для поиска\nПример: /search проблема с оплатой")
        return
    
    results = search_tickets(query)
    
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

@dp.message(TicketStates.waiting_title)
async def handle_ticket_title(message: Message, state: FSMContext):
    title = message.text.strip()
    
    if len(title) < TITLE_MIN_LENGTH or len(title) > TITLE_MAX_LENGTH:
        await message.answer(
            f"❌ Заголовок должен содержать от {TITLE_MIN_LENGTH} до {TITLE_MAX_LENGTH} символов.\n"
            f"Попробуйте ещё раз:"
        )
        return
    
    data = await state.get_data()
    category = data.get('category', 'question')
    
    await message.answer(
        f"✅ Заголовок '{title}' принят!\n\n"
        f"📝 Теперь напишите ваше обращение (от {MESSAGE_MIN_LENGTH} до {MESSAGE_MAX_LENGTH} символов).\n"
        f"Можно отправить текст, фото (до {MAX_PHOTOS_PER_MESSAGE} шт.), видео (до {MAX_VIDEO_DURATION} сек).\n\n"
        f"⏰ У вас есть {ACTION_TIMEOUT // 60} минут на отправку сообщения, иначе обращение будет автоматически закрыто."
    )
    
    await state.update_data(title=title, category=category)
    await state.set_state(TicketStates.waiting_initial_message)
    asyncio.create_task(start_timeout_timer(message.from_user.id, "initial_message", ACTION_TIMEOUT, state))

@dp.message(TicketStates.waiting_initial_message)
async def handle_initial_message(message: Message, state: FSMContext):
    user = message.from_user
    
    if message.photo and len(message.photo) > MAX_PHOTOS_PER_MESSAGE:
        await message.answer(f"❌ Максимум {MAX_PHOTOS_PER_MESSAGE} фото в одном сообщении")
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
        await message.answer(
            f"❌ Текст должен содержать от {MESSAGE_MIN_LENGTH} до {MESSAGE_MAX_LENGTH} символов.\n"
            f"Сейчас: {content_length} символов"
        )
        return
    
    data = await state.get_data()
    title = data.get('title')
    category = data.get('category', 'question')
    
    ticket_id = create_new_ticket(user, title, category)
    custom_id = get_or_create_custom_id(user.id, user.username, user.first_name, user.last_name)
    
    await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)
    
    if message.text:
        save_message(ticket_id, 'user', user.id, message.text, user.first_name)
        content_for_admin = message.text
    elif message.photo:
        file_id = message.photo[-1].file_id
        save_message(ticket_id, 'user', user.id, f"[Фото] {message.caption or ''}", user.first_name,
                    file_id=file_id, media_type='photo', caption=message.caption)
        content_for_admin = f"[Фото] {message.caption or ''}"
    elif message.video:
        file_id = message.video.file_id
        save_message(ticket_id, 'user', user.id, f"[Видео] {message.caption or ''}", user.first_name,
                    file_id=file_id, media_type='video', caption=message.caption)
        content_for_admin = f"[Видео] {message.caption or ''}"
    else:
        await message.answer("❌ Неподдерживаемый тип сообщения")
        return
    
    increment_initial_count(user.id)
    
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
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, user_info, parse_mode=ParseMode.HTML)
            await message.forward(admin_id)
        except Exception as e:
            logging.error(f"❌ Ошибка отправки админу {admin_id}: {e}")
    
    await message.answer(
        f"✅ Обращение #{custom_id} создано и отправлено!\n\n"
        f"Тема: {title}\n"
        f"Категория: {category}\n\n"
        f"⏳ Ожидайте ответа поддержки. Вы можете отправить ещё {INITIAL_MESSAGE_LIMIT - 1} сообщение до ответа.",
        reply_markup=get_after_message_menu(ticket_id, custom_id)
    )
    
    await state.set_state(TicketStates.in_dialog)

@dp.message(TicketStates.waiting_feedback)
async def handle_feedback(message: Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data.get('ticket_id')
    rating = data.get('rating')
    admin_id = data.get('admin_id')
    admin_name = data.get('admin_name')
    user_id = data.get('user_id')
    user_custom_id = data.get('user_custom_id')
    
    feedback = message.text if message.text else None
    
    save_rating_and_feedback(
        ticket_id, rating, feedback, 
        admin_id, admin_name, 
        user_id or message.from_user.id, 
        user_custom_id
    )
    
    if feedback:
        await message.answer(
            f"✅ Спасибо за ваш развёрнутый отзыв!\n"
            f"Он поможет нам стать лучше.\n\n"
            f"Главное меню {BOT_USERNAME}:",
            reply_markup=get_user_main_menu()
        )
    else:
        await message.answer(
            "✅ Спасибо за оценку!\n\n"
            f"Главное меню {BOT_USERNAME}:",
            reply_markup=get_user_main_menu()
        )
    
    await state.clear()

@dp.message(F.chat.type == 'private')
async def handle_user_message(message: Message, state: FSMContext):
    if message.text and message.text.startswith('/'):
        return
    
    user = message.from_user
    
    if check_blacklist(user.id):
        await message.answer(
            f"⛔ Вы находитесь в черном списке и не можете использовать поддержку."
        )
        return
    
    current_state = await state.get_state()
    
    if current_state != TicketStates.in_dialog.state:
        if has_open_ticket(user.id):
            open_ticket = get_open_ticket_info(user.id)
            if open_ticket:
                ticket_id, custom_id, title, _, _, has_responded, initial_count = open_ticket
                if not has_responded and initial_count >= INITIAL_MESSAGE_LIMIT:
                    await message.answer(
                        f"⏳ Вы уже отправили максимальное количество сообщений ({INITIAL_MESSAGE_LIMIT}). Дождитесь ответа поддержки."
                    )
                    return
                await state.set_state(TicketStates.in_dialog)
                await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)
            else:
                await message.answer(
                    "❌ У вас нет активного обращения.\n"
                    "Начните новое через /start",
                    reply_markup=InlineKeyboardBuilder()
                        .button(text="📝 Начать", callback_data="support:start")
                        .as_markup()
                )
                return
        else:
            return
    
    data = await state.get_data()
    ticket_id = data.get('ticket_id')
    custom_id = data.get('custom_id')
    title = data.get('title')
    
    if not ticket_id:
        open_ticket = get_open_ticket_info(user.id)
        if open_ticket:
            ticket_id, custom_id, title, _, _, has_responded, initial_count = open_ticket
            if not has_responded and initial_count >= INITIAL_MESSAGE_LIMIT:
                await message.answer(
                    f"⏳ Вы уже отправили максимальное количество сообщений ({INITIAL_MESSAGE_LIMIT}). Дождитесь ответа поддержки."
                )
                return
            await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)
        else:
            await message.answer(
                "❌ Ошибка: обращение не найдено.\n"
                "Начните новое через /start"
            )
            await state.clear()
            return
    
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT status, has_responded, initial_messages_count FROM tickets WHERE id = ?", (ticket_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row or row[0] != 'open':
            await message.answer(
                "❌ Ваше обращение уже закрыто.\n"
                "Создайте новое, если нужно.",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="📝 Создать", callback_data="support:start")
                    .as_markup()
            )
            await state.clear()
            return
        
        status, has_responded, initial_count = row
        
        if not has_responded and initial_count >= INITIAL_MESSAGE_LIMIT:
            await message.answer(
                f"⏳ Вы уже отправили максимальное количество сообщений ({INITIAL_MESSAGE_LIMIT}). Дождитесь ответа поддержки."
            )
            return
    except:
        pass
    
    can_send, error_msg = can_user_send_message(user.id)
    if not can_send:
        await message.answer(error_msg)
        return
    
    blocked, block_msg = check_spam_block(user.id)
    if blocked:
        await message.answer(block_msg)
        return
    
    if message.sticker or message.animation or message.dice:
        await message.answer("❌ Пожалуйста, отправляйте текстовые сообщения или фото/видео по теме.")
        return
    
    if message.photo and len(message.photo) > MAX_PHOTOS_PER_MESSAGE:
        await message.answer(f"❌ Максимум {MAX_PHOTOS_PER_MESSAGE} фото в одном сообщении")
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
        await message.answer(
            f"❌ Текст должен содержать от {MESSAGE_MIN_LENGTH} до {MESSAGE_MAX_LENGTH} символов.\n"
            f"Сейчас: {content_length} символов"
        )
        return
    
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT category FROM tickets WHERE id = ?", (ticket_id,))
        row = cursor.fetchone()
        category = row[0] if row else 'question'
        conn.close()
    except:
        category = 'question'
    
    if message.media_group_id:
        if message.media_group_id not in media_groups_buffer:
            media_groups_buffer[message.media_group_id] = []
        media_groups_buffer[message.media_group_id].append(message)
        
        await asyncio.sleep(1)
        
        if message.media_group_id in media_groups_buffer:
            messages = media_groups_buffer.pop(message.media_group_id)
            
            for msg in messages:
                file_id = None
                media_type = None
                
                if msg.photo:
                    file_id = msg.photo[-1].file_id
                    media_type = 'photo'
                elif msg.video:
                    file_id = msg.video.file_id
                    media_type = 'video'
                
                if file_id:
                    save_media_group(
                        message.media_group_id,
                        ticket_id,
                        msg.message_id,
                        file_id,
                        media_type,
                        msg.caption
                    )
            
            save_message(
                ticket_id, 'user', user.id, 
                f"[Альбом] {messages[0].caption or ''}", 
                user.first_name,
                message.media_group_id
            )
            
            increment_initial_count(user.id)
            
            user_info = (
                f"<b>Обращение #{custom_id}</b>\n"
                f"📝 Тема: {title}\n"
                f"<a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
                f"ID: <code>{custom_id}</code>\n"
                f"📱 @{user.username or 'нет'}\n"
                f"📂 {category}\n"
                f"─" * 30 + "\n"
                f"<b>Альбом ({len(messages)} шт.)</b>\n"
            )
            
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, user_info, parse_mode=ParseMode.HTML)
                    
                    media_group = []
                    for msg in messages:
                        if msg.photo:
                            media_group.append(types.InputMediaPhoto(
                                media=msg.photo[-1].file_id,
                                caption=msg.caption if msg == messages[0] else None
                            ))
                        elif msg.video:
                            media_group.append(types.InputMediaVideo(
                                media=msg.video.file_id,
                                caption=msg.caption if msg == messages[0] else None
                            ))
                    
                    await bot.send_media_group(admin_id, media_group)
                except Exception as e:
                    logging.error(f"❌ Ошибка отправки админу {admin_id}: {e}")
            
            await message.answer(
                f"✅ Альбом отправлен в обращение #{custom_id}.",
                reply_markup=get_after_message_menu(ticket_id, custom_id)
            )
            
            update_message_time(user.id)
            return
    
    content_for_admin = ""
    
    if message.text:
        save_message(ticket_id, 'user', user.id, message.text, user.first_name)
        content_for_admin = message.text
        increment_initial_count(user.id)
        await message.answer(
            f"✅ Сообщение отправлено в обращение #{custom_id}.", 
            reply_markup=get_after_message_menu(ticket_id, custom_id)
        )
    elif message.photo:
        file_id = message.photo[-1].file_id
        save_message(ticket_id, 'user', user.id, f"[Фото] {message.caption or ''}", user.first_name,
                    file_id=file_id, media_type='photo', caption=message.caption)
        content_for_admin = f"[Фото] {message.caption or ''}"
        increment_initial_count(user.id)
        await message.answer(
            f"✅ Фото отправлено в обращение #{custom_id}.", 
            reply_markup=get_after_message_menu(ticket_id, custom_id)
        )
    elif message.video:
        file_id = message.video.file_id
        save_message(ticket_id, 'user', user.id, f"[Видео] {message.caption or ''}", user.first_name,
                    file_id=file_id, media_type='video', caption=message.caption)
        content_for_admin = f"[Видео] {message.caption or ''}"
        increment_initial_count(user.id)
        await message.answer(
            f"✅ Видео отправлено в обращение #{custom_id}.", 
            reply_markup=get_after_message_menu(ticket_id, custom_id)
        )
    else:
        return
    
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
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, user_info, parse_mode=ParseMode.HTML)
            await message.forward(admin_id)
        except Exception as e:
            logging.error(f"❌ Ошибка отправки админу {admin_id}: {e}")
    
    update_message_time(user.id)

@dp.message(lambda m: is_admin(m.from_user.id) and m.reply_to_message is not None)
async def handle_admin_reply(message: Message):
    replied = message.reply_to_message
    
    user_id = None
    custom_id = None
    
    if replied.forward_from:
        user_id = replied.forward_from.id
    elif replied.text and "ID: <code>" in replied.text:
        match = re.search(r'ID: <code>(\d+)</code>', replied.text)
        if match:
            custom_id = int(match.group(1))
            user_info = get_user_by_custom_id(custom_id)
            if user_info:
                user_id = user_info[0]
    
    if not user_id:
        await message.reply("❌ Не удалось определить пользователя. Ответьте на пересланное сообщение.")
        return
    
    admin_name = get_admin_name(message.from_user.id)
    
    if not admin_name:
        await message.reply("❌ Вы не зарегистрированы. Используйте /start.")
        return
    
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT id, custom_user_id, title FROM tickets WHERE user_id = ? AND status = 'open'", (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            await message.reply("❌ Активное обращение не найдено")
            return
        
        ticket_id, custom_id, title = row
    except:
        await message.reply("❌ Ошибка базы данных")
        return
    
    try:
        if message.text:
            await bot.send_message(
                user_id, 
                f"✉️ <b>Ответ от {admin_name}:</b>\n\n{message.text}",
                parse_mode=ParseMode.HTML
            )
            save_message(ticket_id, 'admin', message.from_user.id, message.text, admin_name)
        elif message.photo:
            if len(message.photo) > MAX_PHOTOS_PER_MESSAGE:
                await message.reply(f"❌ Максимум {MAX_PHOTOS_PER_MESSAGE} фото в одном сообщении")
                return
            await bot.send_photo(
                user_id, 
                message.photo[-1].file_id,
                caption=f"✉️ <b>Ответ от {admin_name}:</b>\n\n{message.caption or ''}",
                parse_mode=ParseMode.HTML
            )
            save_message(ticket_id, 'admin', message.from_user.id, f"[Фото] {message.caption or ''}", admin_name)
        elif message.video:
            if message.video.duration > MAX_VIDEO_DURATION:
                await message.reply(f"❌ Видео слишком длинное! Максимум {MAX_VIDEO_DURATION} сек")
                return
            await bot.send_video(
                user_id, 
                message.video.file_id,
                caption=f"✉️ <b>Ответ от {admin_name}:</b>\n\n{message.caption or ''}",
                parse_mode=ParseMode.HTML
            )
            save_message(ticket_id, 'admin', message.from_user.id, f"[Видео] {message.caption or ''}", admin_name)
        else:
            await message.reply("❌ Неподдерживаемый тип сообщения")
            return
        
        update_has_responded(user_id)
        update_admin_activity(message.from_user.id)
        
        await message.reply(
            f"✅ Ответ на обращение #{custom_id} отправлен от имени {admin_name}",
            reply_markup=get_ticket_actions_keyboard(ticket_id, user_id, custom_id)
        )
        
    except Exception as e:
        await message.reply(f"❌ Ошибка при отправке: {e}")
        logging.error(f"❌ Ошибка ответа админа: {e}")

@dp.callback_query()
async def process_callback(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.answer()
    except:
        pass
    
    data = callback.data
    user = callback.from_user
    bot_token = 'main'
    
    if data == "menu:main":
        await state.clear()
        custom_id = get_or_create_custom_id(user.id)
        
        if is_admin(user.id):
            await callback.message.edit_text(
                f"🔧 Панель поддержки {BOT_USERNAME}:\nВаш ID: <code>{custom_id}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_admin_main_menu(bot_token)
            )
        else:
            await callback.message.edit_text(
                f"Главное меню {BOT_USERNAME}:\nВаш ID: <code>{custom_id}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_user_main_menu(bot_token)
            )
        return
    
    if data == "admin:change_name":
        if not is_admin(user.id):
            return
        await callback.message.answer(
            "Введите новое имя в формате 'Имя Ф.' (пример: Иван З.):",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(AdminEditName.waiting_for_new_name)
        asyncio.create_task(start_timeout_timer(user.id, "change_name", ACTION_TIMEOUT, state))
        return

    if data == "clone:create":
        await callback.message.edit_text(
        "🤖 <b>Создание своего бота поддержки</b>\n\n"
        "1. Откройте @BotFather в Telegram\n"
        "2. Создайте нового бота командой /newbot\n"
        "3. Скопируйте токен, который даст BotFather\n"
        "4. Отправьте его сюда\n\n"
        "⚠️ Токен выглядит так: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz\n\n"
        f"⏰ У вас есть {CLONE_CREATION_TIMEOUT // 60} минут на создание бота",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(CloneBotStates.waiting_for_token)
    asyncio.create_task(start_timeout_timer(user.id, "clone_token", CLONE_CREATION_TIMEOUT, state))
    return
    
    if data == "admin:blacklist":
        if not is_admin(user.id):
            return
        await callback.message.answer(
            "⛔ <b>Управление черным списком</b>\n\n"
            "Выберите действие:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_blacklist_keyboard()
        )
        return
    
    if data == "blacklist:add":
        if not is_admin(user.id):
            return
        await callback.message.answer(
            "Введите ID пользователя для добавления в черный список:",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(BlacklistStates.waiting_for_user_id)
        asyncio.create_task(start_timeout_timer(user.id, "blacklist_add", ACTION_TIMEOUT, state))
        return
    
    if data == "info:rules":
        rules_text = (
            f"📜 <b>Правила работы с поддержкой {BOT_USERNAME}</b>\n\n"
            "1️⃣ <b>Вежливость</b> - будьте уважительны к операторам\n"
            "2️⃣ <b>Подробности</b> - описывайте проблему максимально подробно\n"
            "3️⃣ <b>Заголовок</b> - указывайте краткую суть обращения\n"
            "4️⃣ <b>Без спама</b> - не отправляйте одинаковые сообщения (блокировка 10 мин)\n"
            "5️⃣ <b>Одна тема</b> - одно обращение = одна проблема\n"
            "6️⃣ <b>Ожидание</b> - ответ может занять до 24 часов\n"
            "7️⃣ <b>Без стикеров</b> - только текст и фото/видео по теме\n"
            "8️⃣ <b>Закрытие</b> - после закрытия нельзя открыть снова\n"
            "9️⃣ <b>Перерыв</b> - между обращениями 5 минут\n\n"
            f"👤 Создатель бота: {ADMIN_USERNAME}"
        )
        await callback.message.answer(
            rules_text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="menu:main")
                .as_markup()
        )
        return
    
    if data == "user:my_tickets":
        if is_admin(user.id):
            await callback.answer("Эта функция только для пользователей")
            return
        
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, custom_user_id, title, status, created_at 
                FROM tickets 
                WHERE user_id = ? AND bot_token = ?
                ORDER BY created_at DESC
                LIMIT 10
            """, (user.id, bot_token))
            tickets = cursor.fetchall()
            conn.close()
        except:
            tickets = []
        
        if not tickets:
            await callback.message.edit_text(
                "📭 У вас пока нет обращений в поддержку.",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data="menu:main")
                    .as_markup()
            )
            return
        
        await callback.message.edit_text(
            "📋 <b>Ваши последние обращения:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_user_tickets_keyboard(tickets)
        )
        return
    
    if data.startswith("user:view_ticket_"):
        ticket_id = int(data.split("_")[-1])
        messages = get_ticket_messages(ticket_id)
        
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT custom_user_id, title, category, status, created_at, closed_at, rating
                FROM tickets WHERE id = ?
            """, (ticket_id,))
            ticket_info = cursor.fetchone()
            conn.close()
        except:
            ticket_info = None
        
        if not ticket_info:
            await callback.message.answer("❌ Обращение не найдено")
            return
        
        custom_id, title, category, status, created_at, closed_at, rating = ticket_info
        status_emoji = "🟢" if status == 'open' else "🔴"
        created = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")
        
        text = (f"<b>Обращение #{custom_id}</b> {status_emoji}\n"
                f"📝 Тема: {title}\n"
                f"📂 Категория: {category}\n"
                f"📅 Создано: {created}\n")
        
        if status == 'closed' and closed_at:
            closed = datetime.fromisoformat(closed_at).strftime("%d.%m.%Y %H:%M")
            text += f"🔒 Закрыто: {closed}\n"
        
        if rating:
            text += f"⭐️ Оценка: {'⭐️' * rating}\n"
        
        text += "\n" + "─" * 30 + "\n\n"
        
        if not messages:
            text += "📭 Нет сообщений"
        else:
            for msg in messages[:20]:
                sender_type, sender_name, content, timestamp, media_group_id, file_id, media_type, caption = msg
                time_str = datetime.fromisoformat(timestamp).strftime("%d.%m %H:%M")
                
                if sender_type == 'user':
                    sender_disp = "👤 Вы"
                else:
                    sender_disp = f"👨‍💼 {sender_name or 'Поддержка'}"
                
                if media_group_id:
                    media_mark = "📎 [Альбом] "
                elif media_type == 'photo':
                    media_mark = "📷 [Фото] "
                elif media_type == 'video':
                    media_mark = "🎥 [Видео] "
                elif media_type == 'voice':
                    media_mark = "🎤 [Голосовое] "
                elif media_type == 'document':
                    media_mark = "📄 [Документ] "
                else:
                    media_mark = ""
                
                text += f"[{time_str}] {sender_disp}: {media_mark}{content or caption or ''}\n\n"
        
        if len(text) > 4000:
            text = text[:4000] + "...\n\n(сообщение обрезано)"
        
        await callback.message.answer(
            text, 
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="user:my_tickets")
                .as_markup()
        )
        return
    
    if data == "support:start":
        if is_admin(user.id):
            await callback.answer("Админы не могут создавать обращения")
            return
        
        if check_blacklist(user.id):
            await callback.message.edit_text(
                "⛔ Вы находитесь в черном списке и не можете создавать обращения.",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data="menu:main")
                    .as_markup()
            )
            return
        
        if has_open_ticket(user.id):
            ticket_info = get_open_ticket_info(user.id)
            if ticket_info:
                ticket_id, custom_id, title, category, created_at, has_responded, initial_count = ticket_info
                await callback.message.edit_text(
                    f"❌ У вас уже есть открытое обращение #{custom_id}.\n"
                    f"Тема: {title}\n\n"
                    f"Сначала закройте его, чтобы создать новое.",
                    reply_markup=InlineKeyboardBuilder()
                        .button(text="📝 Перейти к диалогу", callback_data="support:continue")
                        .button(text="◀️ Назад", callback_data="menu:main")
                        .as_markup()
                )
            else:
                await callback.message.edit_text(
                    "❌ У вас уже есть открытое обращение.\n"
                    "Сначала закройте его, чтобы создать новое.",
                    reply_markup=InlineKeyboardBuilder()
                        .button(text="◀️ Назад", callback_data="menu:main")
                        .as_markup()
                )
            return
        
        on_cooldown, remaining = check_ticket_cooldown(user.id)
        if on_cooldown:
            minutes = remaining // 60
            seconds = remaining % 60
            await callback.message.edit_text(
                f"⏳ Подождите {minutes} мин {seconds} сек перед созданием нового обращения.\n"
                f"Это нужно для предотвращения спама.",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data="menu:main")
                    .as_markup()
            )
            return
        
        await callback.message.edit_text(
            f"📜 <b>Правила обращения в поддержку {BOT_USERNAME}</b>\n\n"
            "1. Будьте вежливы и уважительны\n"
            "2. Описывайте проблему подробно\n"
            "3. Укажите краткий заголовок обращения\n"
            "4. Не спамьте (блокировка на 10 минут)\n"
            "5. Ожидайте ответа (до 24 часов)\n"
            "6. Одно обращение = одна тема\n\n"
            "Подтвердите своё согласие с правилами:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_consent_keyboard()
        )
        return
    
    if data == "consent:accept":
        save_consent(user.id)
        await callback.message.edit_text(
            "✅ Спасибо! Теперь выберите категорию обращения:",
            reply_markup=get_category_menu()
        )
        return
    
    if data.startswith("category:"):
        category = data.split(":")[1]
        await state.update_data(category=category)
        await callback.message.edit_text(
            f"📝 Введите краткий заголовок обращения ({TITLE_MIN_LENGTH}-{TITLE_MAX_LENGTH} символов):\n\n"
            "Пример: Проблема с оплатой\n"
            "Или: Вопрос по функционалу",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(TicketStates.waiting_title)
        asyncio.create_task(start_timeout_timer(user.id, "ticket_title", ACTION_TIMEOUT, state))
        return
    
    if data == "support:cancel":
        await state.clear()
        custom_id = get_or_create_custom_id(user.id)
        
        if is_admin(user.id):
            await callback.message.edit_text(
                f"❌ Действие отменено.\n\nПанель поддержки {BOT_USERNAME}:\nВаш ID: <code>{custom_id}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_admin_main_menu(bot_token)
            )
        else:
            await callback.message.edit_text(
                f"❌ Действие отменено.\n\nГлавное меню {BOT_USERNAME}:\nВаш ID: <code>{custom_id}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_user_main_menu(bot_token)
            )
        return
    
    if data == "group:cancel":
        await state.clear()
        await callback.message.edit_text(
            "❌ Действие отменено",
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="group:menu")
                .as_markup()
        )
        return
    
    if data == "support:continue":
        data_state = await state.get_data()
        ticket_id = data_state.get('ticket_id')
        custom_id = data_state.get('custom_id')
        title = data_state.get('title')
        
        if not ticket_id or not has_open_ticket(user.id):
            open_ticket = get_open_ticket_info(user.id)
            if open_ticket:
                ticket_id, custom_id, title, _, _, _, _ = open_ticket
                await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)
            else:
                await callback.message.edit_text(
                    "❌ Ошибка: обращение не найдено.\n"
                    "Начните новое обращение.",
                    reply_markup=get_user_main_menu(bot_token)
                )
                await state.clear()
                return
        
        await callback.message.edit_text(
            f"📝 Продолжайте диалог по обращению #{custom_id}\n"
            f"Тема: {title}\n\n"
            f"Отправьте сообщение (текст, фото, видео):",
            parse_mode=ParseMode.HTML
        )
        return
    
    if data.startswith("support:close:"):
        parts = data.split(":")
        if len(parts) >= 3:
            ticket_id = int(parts[1])
            custom_id = int(parts[2])
            
            try:
                conn = sqlite3.connect(DB_FILE, timeout=30)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT sender_id, sender_name FROM messages 
                    WHERE ticket_id = ? AND sender_type = 'admin' 
                    ORDER BY timestamp DESC LIMIT 1
                """, (ticket_id,))
                last_admin = cursor.fetchone()
                conn.close()
            except:
                last_admin = None
            
            admin_id = last_admin[0] if last_admin else None
            admin_name = last_admin[1] if last_admin else None
            
            if close_ticket(ticket_id, user.id, "Пользователь"):
                await callback.message.edit_text(
                    f"✅ Обращение #{custom_id} закрыто.\n\n"
                    f"Оцените качество поддержки:",
                    reply_markup=get_rating_keyboard(ticket_id, admin_id)
                )
            else:
                await callback.message.edit_text(
                    "❌ Не удалось закрыть обращение. Возможно, оно уже закрыто.",
                    reply_markup=get_user_main_menu(bot_token)
                )
                await state.clear()
        
        return
    
    if data.startswith("rate:"):
        parts = data.split(":")
        if len(parts) >= 4:
            _, rating, ticket_id, admin_id = parts[:4]
            rating = int(rating)
            ticket_id = int(ticket_id)
            admin_id = int(admin_id) if admin_id != '0' else None
            
            try:
                conn = sqlite3.connect(DB_FILE, timeout=30)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT user_id, custom_user_id, closed_by, closed_by_name 
                    FROM tickets WHERE id = ?
                """, (ticket_id,))
                ticket_info = cursor.fetchone()
                conn.close()
            except:
                ticket_info = None
            
            if ticket_info:
                user_id, user_custom_id, closed_by, closed_by_name = ticket_info
                
                if not admin_id and closed_by:
                    admin_id = closed_by
                    admin_name = closed_by_name
                else:
                    admin_name = get_admin_name(admin_id) if admin_id else None
                
                await callback.message.edit_text(
                    f"✅ Спасибо за вашу оценку: {'⭐️' * rating}!\n\n"
                    f"Если хотите оставить развёрнутый отзыв, напишите его сейчас в течение 1 минуты.\n"
                    f"Или отправьте /start для возврата в меню."
                )
                
                await state.set_state(TicketStates.waiting_feedback)
                await state.update_data(
                    ticket_id=ticket_id, 
                    rating=rating,
                    admin_id=admin_id,
                    admin_name=admin_name,
                    user_id=user_id,
                    user_custom_id=user_custom_id
                )
                asyncio.create_task(start_timeout_timer(user.id, "feedback", 60, state))
            else:
                await callback.message.edit_text(
                    f"✅ Спасибо за вашу оценку: {'⭐️' * rating}!\n\n"
                    f"Отправьте /start для возврата в меню."
                )
        
        return
    
    if data.startswith("admin:accept_ticket:"):
        parts = data.split(":")
        if len(parts) == 5:
            _, _, ticket_id, user_id, custom_id = parts
            ticket_id = int(ticket_id)
            user_id = int(user_id)
            custom_id = int(custom_id)
            
            await callback.message.edit_text(
                f"✅ Обращение #{custom_id} принято в работу"
            )
            
            try:
                await bot.send_message(
                    user_id,
                    f"✅ Ваше обращение #{custom_id} принято в работу. Ожидайте ответа."
                )
            except:
                pass
        return
    
    if data.startswith("admin:reject_ticket:"):
        parts = data.split(":")
        if len(parts) == 5:
            _, _, ticket_id, user_id, custom_id = parts
            ticket_id = int(ticket_id)
            user_id = int(user_id)
            custom_id = int(custom_id)
            
            if close_ticket(ticket_id, 0, "Администратор отклонил"):
                await callback.message.edit_text(
                    f"❌ Обращение #{custom_id} отклонено"
                )
                
                try:
                    await bot.send_message(
                        user_id,
                        f"❌ Ваше обращение #{custom_id} отклонено администратором."
                    )
                except:
                    pass
        return
    
    if data.startswith("admin:blacklist_ticket:"):
        parts = data.split(":")
        if len(parts) == 4:
            _, _, user_id, custom_id = parts
            user_id = int(user_id)
            custom_id = int(custom_id)
            
            await state.update_data(blacklist_user_id=user_id, blacklist_custom_id=custom_id)
            await callback.message.answer(
                f"⛔ Введите причину блокировки для пользователя #{custom_id}:",
                reply_markup=get_cancel_keyboard()
            )
            await state.set_state(BlacklistStates.waiting_for_reason)
            asyncio.create_task(start_timeout_timer(user.id, "blacklist_reason", ACTION_TIMEOUT, state))
        return
    
    if data == "admin:open_tickets":
        if not is_admin(user.id):
            return
        
        tickets = get_all_open_tickets()
        if not tickets:
            await callback.message.answer(
                f"📭 Нет открытых обращений",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data="menu:main")
                    .as_markup()
            )
            return
        
        text = "📂 <b>Открытые обращения:</b>\n\n"
        builder = InlineKeyboardBuilder()
        
        for t in tickets[:10]:
            ticket_id, custom_id, username, first_name, title, category, created_at, last_msg, has_responded = t
            created = datetime.fromisoformat(created_at).strftime("%d.%m %H:%M")
            status_emoji = "🟢" if not has_responded else "🟡"
            short_title = title[:20] + "..." if len(title) > 20 else title
            text += f"{status_emoji} <b>#{custom_id}</b> - {short_title}\n└ {first_name} (@{username}) [{created}]\n\n"
            builder.button(text=f"#{custom_id}", callback_data=f"admin:view_ticket_{ticket_id}")
        
        builder.button(text="◀️ Назад", callback_data="menu:main")
        builder.adjust(4)
        
        await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        return
    
    if data == "admin:my_history":
        if not is_admin(user.id):
            return
        
        tickets = get_admin_tickets(user.id)
        if not tickets:
            await callback.message.answer(
                f"📭 У вас пока нет истории ответов",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data="menu:main")
                    .as_markup()
            )
            return
        
        text = "📜 <b>Ваши последние ответы:</b>\n\n"
        builder = InlineKeyboardBuilder()
        
        for t in tickets[:10]:
            ticket_id, custom_id, username, first_name, title, status, created_at, last_msg = t
            date = datetime.fromisoformat(created_at).strftime("%d.%m %H:%M")
            status_emoji = "🟢" if status == 'open' else "🔴"
            short_title = title[:20] + "..." if len(title) > 20 else title
            text += f"{status_emoji} <b>#{custom_id}</b> - {short_title}\n└ {first_name} (@{username}) [{date}]\n\n"
            builder.button(text=f"#{custom_id}", callback_data=f"admin:view_ticket_{ticket_id}")
        
        builder.button(text="◀️ Назад", callback_data="menu:main")
        builder.adjust(4)
        
        await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        return
    
    if data.startswith("admin:view_ticket_"):
        if not is_admin(user.id):
            return
        
        ticket_id = int(data.split("_")[-1])
        messages = get_ticket_messages(ticket_id)
        
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT custom_user_id, username, first_name, last_name, title, category, status, created_at, closed_at, rating
                FROM tickets WHERE id = ?
            """, (ticket_id,))
            ticket_info = cursor.fetchone()
            conn.close()
        except:
            ticket_info = None
        
        if not ticket_info:
            await callback.message.answer("❌ Обращение не найдено")
            return
        
        custom_id, username, first_name, last_name, title, category, status, created_at, closed_at, rating = ticket_info
        status_emoji = "🟢" if status == 'open' else "🔴"
        created = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")
        
        full_name = f"{first_name} {last_name}" if last_name else first_name
        
        text = (f"<b>Обращение #{custom_id}</b> {status_emoji}\n"
                f"📝 Тема: {title}\n"
                f"👤 {full_name} (@{username or 'нет'})\n"
                f"📂 Категория: {category}\n"
                f"📅 Создано: {created}\n")
        
        if status == 'closed' and closed_at:
            closed = datetime.fromisoformat(closed_at).strftime("%d.%m.%Y %H:%M")
            text += f"🔒 Закрыто: {closed}\n"
        
        if rating:
            text += f"⭐️ Оценка: {'⭐️' * rating}\n"
        
        text += "─" * 40 + "\n\n"
        
        if not messages:
            text += "📭 Нет сообщений"
        else:
            for msg in messages:
                sender_type, sender_name, content, timestamp, media_group_id, file_id, media_type, caption = msg
                time_str = datetime.fromisoformat(timestamp).strftime("%d.%m %H:%M")
                
                if sender_type == 'user':
                    sender_disp = "👤 Пользователь"
                else:
                    sender_disp = f"👨‍💼 {sender_name or 'Админ'}"
                
                if media_group_id:
                    media_mark = "📎 [Альбом] "
                elif media_type == 'photo':
                    media_mark = "📷 [Фото] "
                elif media_type == 'video':
                    media_mark = "🎥 [Видео] "
                elif media_type == 'voice':
                    media_mark = "🎤 [Голосовое] "
                elif media_type == 'document':
                    media_mark = "📄 [Документ] "
                else:
                    media_mark = ""
                
                text += f"[{time_str}] {sender_disp}: {media_mark}{content or caption or ''}\n\n"
        
        if len(text) > 4000:
            text = text[:4000] + "...\n\n(сообщение обрезано)"
        
        await callback.message.answer(
            text, 
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardBuilder()
                .button(text="✅ Закрыть", callback_data=f"close:{ticket_id}:{custom_id}:{user.id}")
                .button(text="◀️ Назад", callback_data="admin:open_tickets")
                .adjust(2)
                .as_markup()
        )
        return
    
    if data == "admin:profile":
        if not is_admin(user.id):
            return
        
        profile = get_admin_profile(user.id)
        
        text = (f"👤 <b>Профиль поддержки</b>\n\n"
                f"📋 Имя: {profile['name']}\n"
                f"🆔 Telegram ID: <code>{profile['admin_id']}</code>\n"
                f"📅 Зарегистрирован: {profile['registered']}\n"
                f"⏰ Последняя активность: {profile['last_active']}\n"
                f"💬 Всего ответов: {profile['total_replies']}\n"
                f"🔒 Закрыто тикетов: {profile['total_closed']}\n"
                f"⭐️ Получено оценок: {profile['total_ratings']}\n"
                f"📊 Средний рейтинг: {profile['avg_rating']}/5")
        
        await callback.message.answer(
            text, 
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardBuilder()
                .button(text="⭐️ Мои отзывы", callback_data="admin:my_reviews")
                .button(text="◀️ Назад", callback_data="menu:main")
                .adjust(2)
                .as_markup()
        )
        return
    
    if data == "admin:my_reviews":
        if not is_admin(user.id):
            return
        
        reviews = get_admin_reviews(user.id)
        
        if not reviews:
            await callback.message.answer(
                "📭 У вас пока нет отзывов от пользователей.",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data="admin:profile")
                    .as_markup()
            )
            return
        
        text = "⭐️ <b>Ваши отзывы:</b>\n\n"
        for r in reviews[:10]:
            rating, feedback, created_at, user_custom_id, ticket_id = r
            date = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")
            stars = "⭐️" * rating
            text += f"{stars} от пользователя #{user_custom_id}\n"
            text += f"📅 {date}\n"
            if feedback:
                text += f"💬 {feedback}\n"
            text += "\n"
        
        await callback.message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="admin:profile")
                .as_markup()
        )
        return
    
    if data == "admin:stats":
        if not is_admin(user.id):
            return
        
        stats = get_statistics()
        
        if stats['avg_response_seconds'] > 0:
            if stats['avg_response_seconds'] < 60:
                response_time = f"{stats['avg_response_seconds']} сек"
            elif stats['avg_response_seconds'] < 3600:
                response_time = f"{stats['avg_response_seconds'] // 60} мин"
            else:
                hours = stats['avg_response_seconds'] // 3600
                minutes = (stats['avg_response_seconds'] % 3600) // 60
                response_time = f"{hours} ч {minutes} мин"
        else:
            response_time = "нет данных"
        
        daily_text = ""
        for day, count in stats['daily'][-7:]:
            daily_text += f"{day}: {'🔵' * min(count, 5)} {count}\n"
        
        text = (
            f"📊 <b>Статистика {BOT_USERNAME}</b>\n\n"
            f"📋 <b>Всего обращений:</b> {stats['total_tickets']}\n"
            f"├ 🟢 Открыто: {stats['open_tickets']}\n"
            f"└ 🔴 Закрыто: {stats['closed_tickets']}\n\n"
            f"⭐️ <b>Средняя оценка:</b> {stats['avg_rating']}/5\n"
            f"⏱ <b>Среднее время ответа:</b> {response_time}\n\n"
            f"📅 <b>Последние 7 дней:</b>\n{daily_text}"
        )
        
        await callback.message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="menu:main")
                .as_markup()
        )
        return
    
    if data.startswith("close:"):
        if not is_admin(user.id):
            return
        
        parts = data.split(":")
        if len(parts) == 4:
            _, ticket_id, custom_id, admin_id = parts
            ticket_id = int(ticket_id)
            custom_id = int(custom_id)
            
            admin_name = get_admin_name(user.id)
            
            try:
                conn = sqlite3.connect(DB_FILE, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT user_id FROM tickets WHERE id = ?", (ticket_id,))
                row = cursor.fetchone()
                user_id = row[0] if row else None
                conn.close()
            except:
                user_id = None
            
            if user_id and close_ticket(ticket_id, user.id, admin_name):
                await callback.message.edit_text(f"✅ Обращение #{custom_id} закрыто")
                
                try:
                    await bot.send_message(
                        user_id,
                        f"🔒 Ваше обращение #{custom_id} было закрыто администратором {admin_name}.\n\n"
                        f"Оцените качество поддержки:",
                        reply_markup=get_rating_keyboard(ticket_id, user.id)
                    )
                except:
                    pass
            else:
                await callback.message.edit_text(f"❌ Обращение уже закрыто или не найдено")
        
        return
    
    if data == "group:rules":
        await callback.message.answer(
            f"📜 <b>Правила чата</b>\n\n"
            f"1. Уважайте других участников\n"
            f"2. Не спамьте\n"
            f"3. По вопросам к боту - пишите в ЛС: {BOT_USERNAME}",
            parse_mode=ParseMode.HTML
        )
        return
    
    if data == "group:menu":
        await callback.message.edit_text(
            f"👋 Меню управления группой\n\n"
            f"Команды для создателя:\n"
            f"/triggers - просмотр триггеров\n"
            f"/addtrigger слово - добавить триггер\n"
            f"/deletetrigger слово/ID - удалить триггер\n"
            f"/hello текст/фото/видео - установить приветствие\n"
            f"/bye текст/фото/видео - установить прощание\n"
            f"/delhello - удалить приветствие\n"
            f"/delbye - удалить прощание",
            reply_markup=get_group_main_menu()
        )
        return
    
    if data == "trigger:add":
        if not is_chat_creator(user.id, callback.message.chat.id):
            await callback.answer("❌ Только создатель")
            return
        await callback.message.edit_text(
            "🔤 Введите слово-триггер (например: привет, помощь, вопрос):",
            reply_markup=get_cancel_keyboard(for_group=True)
        )
        await state.set_state(TriggerStates.waiting_for_trigger_word)
        await state.update_data(chat_id=callback.message.chat.id, action_type="add_trigger_word")
        asyncio.create_task(start_timeout_timer(user.id, "add_trigger_word", ACTION_TIMEOUT, state))
        return
    
    if data == "trigger:list":
        triggers = get_triggers(callback.message.chat.id)
        if triggers:
            await callback.message.edit_text(
                "🔤 <b>Список триггеров:</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_triggers_list_keyboard(callback.message.chat.id, triggers)
            )
        else:
            await callback.message.edit_text(
                "📭 В этой группе пока нет триггеров",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="➕ Добавить", callback_data="trigger:add")
                    .button(text="◀️ Назад", callback_data="group:menu")
                    .as_markup()
            )
        return
    
    if data.startswith("trigger:info:"):
        trigger_id = int(data.split(":")[2])
        
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT trigger_word, response_type, use_count, created_at, caption
                FROM triggers WHERE id = ?
            """, (trigger_id,))
            row = cursor.fetchone()
            
            cursor.execute("""
                SELECT COUNT(*), MAX(used_at) FROM trigger_stats WHERE trigger_id = ?
            """, (trigger_id,))
            stats = cursor.fetchone()
            conn.close()
        except:
            row = None
            stats = None
        
        if row:
            word, rtype, use_count, created_at, caption = row
            total_uses, last_used = stats if stats else (0, None)
            created = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")
            last_used_str = datetime.fromisoformat(last_used).strftime("%d.%m.%Y %H:%M") if last_used else "никогда"
            
            type_emoji = {
                'text': '📝 Текст',
                'photo': '📷 Фото',
                'video': '🎥 Видео',
                'animation': '🎞️ GIF',
                'sticker': '🏷️ Стикер'
            }.get(rtype, rtype)
            
            info_text = (
                f"🔤 <b>Информация о триггере #{trigger_id}</b>\n\n"
                f"Слово: '{word}'\n"
                f"Тип ответа: {type_emoji}\n"
                f"Использован: {use_count} раз\n"
                f"Всего срабатываний: {total_uses}\n"
                f"Создан: {created}\n"
                f"Последнее использование: {last_used_str}\n"
            )
            if caption:
                info_text += f"\nПодпись: {caption}\n"
            
            await callback.message.answer(
                info_text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardBuilder()
                    .button(text="❌ Удалить", callback_data=f"trigger:delete:{trigger_id}")
                    .button(text="◀️ Назад", callback_data="trigger:list")
                    .adjust(2)
                    .as_markup()
            )
        return
    
    if data.startswith("trigger:delete:"):
        trigger_id = int(data.split(":")[2])
        
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM triggers WHERE id = ?", (trigger_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            conn.close()
        except:
            deleted = False
        
        if deleted:
            await callback.message.edit_text(
                "✅ Триггер успешно удален",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data="trigger:list")
                    .as_markup()
            )
        else:
            await callback.message.edit_text(
                "❌ Триггер не найден",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data="trigger:list")
                    .as_markup()
            )
        return
    
    if data == "welcome:default":
        data_state = await state.get_data()
        chat_id = data_state['chat_id']
        bot_token = data_state.get('bot_token', 'main')
        reset_welcome_to_default(chat_id, bot_token)
        await callback.message.edit_text(
            "✅ Приветствие сброшено к значению по умолчанию",
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="group:menu")
                .as_markup()
        )
        await state.clear()
        return
    
    if data == "welcome:disable":
        chat_id = (await state.get_data())['chat_id']
        update_group_settings(chat_id, welcome_enabled=0)
        await callback.message.edit_text(
            "🔴 Приветствие отключено",
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="group:menu")
                .as_markup()
        )
        await state.clear()
        return
    
    if data == "welcome:cancel":
        await state.clear()
        await callback.message.edit_text(
            "❌ Действие отменено",
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="group:menu")
                .as_markup()
        )
        return
    
    if data == "goodbye:default":
        chat_id = (await state.get_data())['chat_id']
        reset_goodbye_to_default(chat_id)
        await callback.message.edit_text(
            "✅ Прощание сброшено к значению по умолчанию",
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="group:menu")
                .as_markup()
        )
        await state.clear()
        return
    
    if data == "goodbye:disable":
        chat_id = (await state.get_data())['chat_id']
        update_group_settings(chat_id, goodbye_enabled=0)
        await callback.message.edit_text(
            "🔴 Прощание отключено",
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="group:menu")
                .as_markup()
        )
        await state.clear()
        return
    
    if data == "goodbye:cancel":
        await state.clear()
        await callback.message.edit_text(
            "❌ Действие отменено",
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="group:menu")
                .as_markup()
        )
        return
    
    if data == "welcome_enable:confirm":
        data_state = await state.get_data()
        chat_id = data_state['chat_id']
        bot_token = data_state.get('bot_token', 'main')
        update_group_settings(chat_id, welcome_enabled=1)
        await callback.message.edit_text(
            "✅ Приветствие включено. Теперь отправьте новый текст/медиа с командой /hello:",
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="group:menu")
                .as_markup()
        )
        await state.clear()
        return
    
    if data == "welcome_enable:cancel":
        await state.clear()
        await callback.message.edit_text(
            "❌ Действие отменено",
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="group:menu")
                .as_markup()
        )
        return
    
    if data == "goodbye_enable:confirm":
        chat_id = (await state.get_data())['chat_id']
        update_group_settings(chat_id, goodbye_enabled=1)
        await callback.message.edit_text(
            "✅ Прощание включено. Теперь отправьте новый текст/медиа с командой /bye:",
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="group:menu")
                .as_markup()
        )
        await state.clear()
        return
    
    if data == "goodbye_enable:cancel":
        await state.clear()
        await callback.message.edit_text(
            "❌ Действие отменено",
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="group:menu")
                .as_markup()
        )
        return
    
    if data == "clone:create":
        await callback.message.edit_text(
            "🤖 <b>Создание своего бота поддержки</b>\n\n"
            "1. Откройте @BotFather в Telegram\n"
            "2. Создайте нового бота командой /newbot\n"
            "3. Скопируйте токен, который даст BotFather\n"
            "4. Отправьте его сюда\n\n"
            "⚠️ Токен выглядит так: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz\n\n"
            f"⏰ У вас есть {CLONE_CREATION_TIMEOUT // 60} минут на создание бота",
            parse_mode=ParseMode.HTML
        )
        await state.set_state(CloneBotStates.waiting_for_token)
        asyncio.create_task(start_timeout_timer(user.id, "clone_token", CLONE_CREATION_TIMEOUT, state))
        return
    
    if data == "clone:list":
        bots = get_clone_bots(user.id)
        
        if not bots:
            await callback.message.edit_text(
                "📋 У вас пока нет созданных ботов.\n\n"
                "Нажмите 'Создать своего бота', чтобы начать.",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data="menu:main")
                    .as_markup()
            )
            return
        
        text = "📋 <b>Ваши боты</b>\n\n"
        builder = InlineKeyboardBuilder()
        
        for token, bot_username, bot_name, created_at, status in bots:
            created_date = datetime.fromisoformat(created_at).strftime('%d.%m.%Y')
            status_emoji = "🟢" if status == 'active' else "🔴"
            
            text += f"{status_emoji} <b>{bot_name}</b> (@{bot_username})\n"
            text += f"├ Создан: {created_date}\n"
            text += f"└ Статус: {'Активен' if status == 'active' else 'Неактивен'}\n\n"
            
            builder.button(text=f"⚙️ {bot_name}", callback_data=f"clone:manage:{token}")
        
        builder.button(text="◀️ Назад", callback_data="menu:main")
        builder.adjust(1)
        
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        return
    
    if data.startswith("clone:manage:"):
        token = data.split(":")[2]
        
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT bot_username, bot_name, created_at, status, admins FROM clone_bots WHERE token = ?", 
                          (token,))
            row = cursor.fetchone()
            conn.close()
        except:
            row = None
        
        if not row:
            await callback.message.edit_text("❌ Бот не найден")
            return
        
        bot_username, bot_name, created_at, status, admins_json = row
        admins = json.loads(admins_json)
        created_date = datetime.fromisoformat(created_at).strftime('%d.%m.%Y %H:%M')
        status_emoji = "🟢" if status == 'active' else "🔴"
        
        text = (
            f"⚙️ <b>Управление ботом</b>\n\n"
            f"🤖 Имя: {bot_name}\n"
            f"📱 Юзернейм: @{bot_username}\n"
            f"{status_emoji} Статус: {'Активен' if status == 'active' else 'Неактивен'}\n"
            f"📅 Создан: {created_date}\n"
            f"👥 Админы: {', '.join(map(str, admins))}\n\n"
            f"Выберите действие:"
        )
        
        await callback.message.edit_text(
            text, 
            parse_mode=ParseMode.HTML,
            reply_markup=get_clone_management_keyboard(token)
        )
        return
    
    if data.startswith("clone:stats:"):
        token = data.split(":")[2]
        
        stats = get_statistics(token)
        bot_info = get_bot_display_info(token)
        
        if stats['avg_response_seconds'] > 0:
            if stats['avg_response_seconds'] < 60:
                response_time = f"{stats['avg_response_seconds']} сек"
            elif stats['avg_response_seconds'] < 3600:
                response_time = f"{stats['avg_response_seconds'] // 60} мин"
            else:
                response_time = f"{stats['avg_response_seconds'] // 3600} ч"
        else:
            response_time = "нет данных"
        
        text = (
            f"📊 <b>Статистика бота</b>\n"
            f"🤖 {bot_info['name']} ({bot_info['username']})\n\n"
            f"📋 <b>Тикеты:</b>\n"
            f"├ Всего: {stats['total_tickets']}\n"
            f"├ Открыто: {stats['open_tickets']}\n"
            f"└ Закрыто: {stats['closed_tickets']}\n\n"
            f"⭐️ <b>Средняя оценка:</b> {stats['avg_rating']}/5\n"
            f"├ 5 ⭐️: {stats['rating_5']}\n"
            f"├ 4 ⭐️: {stats['rating_4']}\n"
            f"├ 3 ⭐️: {stats['rating_3']}\n"
            f"├ 2 ⭐️: {stats['rating_2']}\n"
            f"└ 1 ⭐️: {stats['rating_1']}\n\n"
            f"⏱ <b>Среднее время ответа:</b> {response_time}"
        )
        
        await callback.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data=f"clone:manage:{token}")
                .as_markup()
        )
        return
    
    if data.startswith("clone:restart:"):
        token = data.split(":")[2]
        
        await callback.message.edit_text("🔄 Перезапуск бота...")
        
        await stop_clone_bot(token)
        await asyncio.sleep(2)
        
        success = await start_clone_bot(token)
        
        if success:
            await callback.message.edit_text(
                "✅ Бот успешно перезапущен!",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data=f"clone:manage:{token}")
                    .as_markup()
            )
        else:
            await callback.message.edit_text(
                "❌ Не удалось перезапустить бота",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data=f"clone:manage:{token}")
                    .as_markup()
            )
        
        return
    
    if data.startswith("clone:delete:"):
        token = data.split(":")[2]
        
        await stop_clone_bot(token)
        
        delete_clone_bot(token)
        
        await callback.message.edit_text(
            "✅ Бот успешно удален",
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="clone:list")
                .as_markup()
        )
        return

@dp.message(BlacklistStates.waiting_for_user_id)
async def blacklist_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except:
        await message.answer("❌ Введите корректный ID пользователя (только цифры)")
        return
    
    await state.update_data(blacklist_user_id=user_id)
    await message.answer(
        "Введите причину блокировки:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(BlacklistStates.waiting_for_reason)
    asyncio.create_task(start_timeout_timer(message.from_user.id, "blacklist_reason", ACTION_TIMEOUT, state))

@dp.message(BlacklistStates.waiting_for_reason)
async def blacklist_reason(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get('blacklist_user_id')
    custom_id = data.get('blacklist_custom_id')
    reason = message.text.strip()
    
    if not reason:
        await message.answer("Введите причину блокировки:")
        return
    
    add_to_blacklist(user_id, reason, message.from_user.id)
    
    try:
        await bot.send_message(
            user_id,
            f"⛔ Вы были добавлены в черный список поддержки.\n"
            f"Причина: {reason}\n\n"
            f"Для вопросов обратитесь к {ADMIN_USERNAME}"
        )
    except:
        pass
    
    await message.answer(
        f"✅ Пользователь #{custom_id or user_id} добавлен в черный список.\n"
        f"Причина: {reason}",
        reply_markup=get_admin_main_menu()
    )
    await state.clear()

@dp.message(CloneBotStates.waiting_for_token)
async def clone_token_received(message: Message, state: FSMContext):
    token = message.text.strip()
    await message.answer("🔄 Проверяю токен...")
    
    is_valid, username, bot_name = await verify_bot_token(token)
    
    await message.answer(f"📊 Результат: {is_valid}, {username}")
    
    if not is_valid:
        await message.answer("❌ Неверный токен. Убедитесь, что вы скопировали его правильно.\nПопробуйте ещё раз или отправьте /cancel")
        return
    
    await state.update_data(token=token, username=username, bot_name=bot_name)
    
    await message.answer(
        f"✅ Бот @{username} успешно проверен!\n\n"
        f"Теперь укажите ID администраторов (через запятую), которые будут иметь доступ к этому боту.\n"
        f"Пример: 123456789, 987654321\n\n"
        f"Вы (ID: {message.from_user.id}) будете добавлены автоматически.\n\n"
        f"⏰ У вас есть {ACTION_TIMEOUT // 60} минут на ввод админов"
    )
    await state.set_state(CloneBotStates.waiting_for_admins)
    asyncio.create_task(start_timeout_timer(message.from_user.id, "clone_admins", ACTION_TIMEOUT, state))

@dp.message(CloneBotStates.waiting_for_admins)
async def clone_admins_received(message: Message, state: FSMContext):
    data = await state.get_data()
    token = data['token']
    username = data['username']
    bot_name = data['bot_name']
    
    admin_ids = [message.from_user.id]
    
    if message.text.strip():
        try:
            parts = message.text.strip().split(',')
            for part in parts:
                admin_id = int(part.strip())
                if admin_id not in admin_ids:
                    admin_ids.append(admin_id)
        except:
            await message.answer(
                "❌ Неверный формат. Введите ID через запятую.\n"
                "Пример: 123456789, 987654321"
            )
            return
    
    save_clone_bot(token, message.from_user.id, username, bot_name, admin_ids)
    
    success = await start_clone_bot(token)
    
    if success:
        await message.answer(
            f"✅ <b>Бот @{username} успешно создан и запущен!</b>\n\n"
            f"📋 Информация:\n"
            f"├ Имя: {bot_name}\n"
            f"├ Юзернейм: @{username}\n"
            f"├ Админы: {', '.join(map(str, admin_ids))}\n"
            f"└ Статус: 🟢 Активен",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(
            f"❌ Бот @{username} сохранен, но не удалось запустить.\n"
            f"Попробуйте перезапустить позже."
        )
    
    await state.clear()

@dp.message(TriggerStates.waiting_for_trigger_word)
async def process_trigger_word(message: Message, state: FSMContext):
    trigger_word = message.text.strip().lower()
    
    if len(trigger_word) < 2 or len(trigger_word) > 50:
        await message.answer(
            "❌ Слово-триггер должно содержать от 2 до 50 символов.\n"
            "Попробуйте ещё раз:"
        )
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
    asyncio.create_task(start_timeout_timer(message.from_user.id, "trigger_response", ACTION_TIMEOUT, state))

async def check_pending_actions():
    """Проверка истекших действий"""
    while True:
        await asyncio.sleep(60)
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            now = datetime.utcnow().isoformat()
            
            cursor.execute("SELECT user_id, action_type, data FROM pending_actions WHERE expires_at < ?", (now,))
            expired = cursor.fetchall()
            
            for user_id, action_type, data_json in expired:
                try:
                    data = json.loads(data_json)
                    if data.get('timeout'):
                        await bot.send_message(
                            user_id,
                            f"⏰ Время на выполнение действия истекло. Операция отменена по причине бездействия."
                        )
                except:
                    pass
                
                cursor.execute("DELETE FROM pending_actions WHERE user_id = ? AND action_type = ?", 
                              (user_id, action_type))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logging.error(f"❌ Ошибка в check_pending_actions: {e}")

async def auto_close_old_tickets():
    """Автоматическое закрытие старых тикетов"""
    while True:
        await asyncio.sleep(3600)
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            
            cutoff = (datetime.utcnow() - timedelta(hours=TICKET_AUTO_CLOSE_HOURS)).isoformat()
            
            cursor.execute("""
                SELECT id, user_id, custom_user_id, title FROM tickets 
                WHERE status = 'open' AND last_message_at < ? AND bot_token = 'main'
            """, (cutoff,))
            
            old_tickets = cursor.fetchall()
            
            for ticket_id, user_id, custom_id, title in old_tickets:
                cursor.execute("UPDATE tickets SET status = 'closed', closed_at = ?, closed_by_name = 'Автоматически' WHERE id = ?", 
                              (datetime.utcnow().isoformat(), ticket_id))
                
                try:
                    await bot.send_message(
                        user_id,
                        f"⏰ Ваше обращение #{custom_id} автоматически закрыто из-за отсутствия активности в течение {TICKET_AUTO_CLOSE_HOURS} часов.\n\n"
                        f"Тема: {title}\n\n"
                        f"Если вопрос остался актуален, создайте новое обращение через /start"
                    )
                except:
                    pass
            
            cursor.execute("SELECT token FROM clone_bots WHERE status = 'active'")
            clone_rows = cursor.fetchall()
            
            for clone_row in clone_rows:
                token = clone_row[0]
                cursor.execute("""
                    SELECT id, user_id, custom_user_id, title FROM tickets 
                    WHERE status = 'open' AND last_message_at < ? AND bot_token = ?
                """, (cutoff, token))
                
                clone_tickets = cursor.fetchall()
                
                for ticket_id, user_id, custom_id, title in clone_tickets:
                    cursor.execute("UPDATE tickets SET status = 'closed', closed_at = ?, closed_by_name = 'Автоматически' WHERE id = ?", 
                                  (datetime.utcnow().isoformat(), ticket_id))
                    
                    if token in active_bots:
                        clone_bot, _, _ = active_bots[token]
                        try:
                            await clone_bot.send_message(
                                user_id,
                                f"⏰ Ваше обращение #{custom_id} автоматически закрыто из-за отсутствия активности в течение {TICKET_AUTO_CLOSE_HOURS} часов.\n\n"
                                f"Тема: {title}\n\n"
                                f"Если вопрос остался актуален, создайте новое обращение через /start"
                            )
                        except:
                            pass
            
            conn.commit()
            conn.close()
            
            total_closed = len(old_tickets) + sum(1 for _ in clone_rows)
            if total_closed > 0:
                logging.info(f"✅ Автоматически закрыто {total_closed} старых обращений")
                
        except Exception as e:
            logging.error(f"❌ Ошибка в auto_close_old_tickets: {e}")

def register_clone_handlers(dp: Dispatcher, bot_token: str):
    pass

@dp.message(CloneBotStates.waiting_for_token)
async def clone_token_received(message: Message, state: FSMContext):
    token = message.text.strip()
    await message.answer("🔄 Проверяю токен...")
    
    is_valid, username, bot_name = await verify_bot_token(token)
    
    if not is_valid:
        await message.answer("❌ Неверный токен. Убедитесь, что вы скопировали его правильно.")
        return
    
    await state.update_data(token=token, username=username, bot_name=bot_name)
    
    await message.answer(
        f"✅ Бот @{username} успешно проверен!\n\n"
        f"Теперь укажите ID администраторов (через запятую):\n"
        f"Пример: 123456789, 987654321\n\n"
        f"Вы (ID: {message.from_user.id}) будете добавлены автоматически."
    )
    await state.set_state(CloneBotStates.waiting_for_admins)
    asyncio.create_task(start_timeout_timer(message.from_user.id, "clone_admins", ACTION_TIMEOUT, state))

@dp.message(CloneBotStates.waiting_for_admins)
async def clone_admins_received(message: Message, state: FSMContext):
    data = await state.get_data()
    token = data['token']
    username = data['username']
    bot_name = data['bot_name']
    
    admin_ids = [message.from_user.id]
    
    if message.text.strip():
        try:
            parts = message.text.strip().split(',')
            for part in parts:
                admin_id = int(part.strip())
                if admin_id not in admin_ids:
                    admin_ids.append(admin_id)
        except:
            await message.answer("❌ Неверный формат. Введите ID через запятую.")
            return
    
    save_clone_bot(token, message.from_user.id, username, bot_name, admin_ids)
    success = await start_clone_bot(token)
    
    if success:
        await message.answer(f"✅ Бот @{username} успешно создан и запущен!")
    else:
        await message.answer(f"❌ Не удалось запустить бота.")
    
    await state.clear()

async def main():
    logging.info(f"🚀 Бот {BOT_USERNAME} запускается...")
    
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT token FROM clone_bots WHERE status = 'active'")
        clones = cursor.fetchall()
        conn.close()
        
        for clone in clones:
            token = clone[0]
            logging.info(f"🔄 Запуск клона бота {token}...")
            await start_clone_bot(token)
            await asyncio.sleep(1)
    except:
        pass
    
    asyncio.create_task(auto_close_old_tickets())
    asyncio.create_task(check_pending_actions())
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("🛑 Бот остановлен")
        
        for token in list(active_bots.keys()):
            asyncio.run(stop_clone_bot(token))
    except Exception as e:
        logging.error(f"❌ Критическая ошибка: {e}")












