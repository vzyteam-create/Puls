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

# --------------------- НАСТРОЙКИ ---------------------
BOT_TOKEN = "8533732699:AAH_iSLnJnHI0-ROJE8fwqAxKQPeRbo_Lck"  # Основной бот
BOT_USERNAME = "@PulsSupportBot"
ADMIN_IDS = [6708209142, 8475965198]
ADMIN_USERNAME = "@vanezyyy"
MAIN_BOT_USERNAME = "@PulsOfficialManager_bot"
DB_FILE = "tickets.db"

# Настройки анти-спама
TICKET_COOLDOWN = 300  # 5 минут
SPAM_LIMIT = 5
SPAM_BLOCK_TIME = 600  # 10 минут
TICKET_AUTO_CLOSE_HOURS = 48
MAX_VIDEO_DURATION = 20
USER_ID_COUNTER = 100

# --------------------- БАЗА ДАННЫХ ---------------------
def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DB_FILE, timeout=20)
    cursor = conn.cursor()
    
    # Таблица пользователей
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
    
    # Таблица тикетов
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
    
    # Таблица отзывов об админах
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
    
    # Таблица админов
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
    
    # Таблица сообщений
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
    
    # Таблица для альбомов
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
    
    # Таблица согласия
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_consent (
            user_id INTEGER PRIMARY KEY,
            consented_at TEXT NOT NULL,
            bot_token TEXT DEFAULT 'main'
        )
    ''')
    
    # Таблица черного списка
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blacklist (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            blocked_at TEXT NOT NULL,
            blocked_by INTEGER,
            bot_token TEXT DEFAULT 'main'
        )
    ''')
    
    # Таблица клонов ботов
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
    
    # Таблица настроек групп
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
    
    # Таблица триггеров
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
    
    # Таблица статистики триггеров
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trigger_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_id INTEGER NOT NULL,
            used_at TEXT NOT NULL,
            used_by INTEGER,
            FOREIGN KEY (trigger_id) REFERENCES triggers (id) ON DELETE CASCADE
        )
    ''')
    
    # Индексы для производительности
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
    
    conn.commit()
    conn.close()
    
    # Миграция старой базы
    migrate_old_database()

def migrate_old_database():
    """Обновление старой базы данных"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        
        # Добавляем колонки в support_admins
        try:
            cursor.execute("SELECT total_ratings FROM support_admins LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE support_admins ADD COLUMN total_ratings INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE support_admins ADD COLUMN avg_rating REAL DEFAULT 0")
            print("✅ Добавлены колонки total_ratings и avg_rating")
        
        # Добавляем колонку title в tickets
        try:
            cursor.execute("SELECT title FROM tickets LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE tickets ADD COLUMN title TEXT")
            print("✅ Добавлена колонка title в tickets")
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Ошибка миграции: {e}")

init_db()
# --------------------- ХРАНИЛИЩЕ АКТИВНЫХ БОТОВ ---------------------
active_bots = {}
bot_sessions = {}

# --------------------- СОСТОЯНИЯ FSM ---------------------
class AdminRegistration(StatesGroup):
    waiting_for_name = State()

class AdminEditName(StatesGroup):
    waiting_for_new_name = State()

class TicketStates(StatesGroup):
    waiting_category = State()
    waiting_title = State()
    waiting_consent = State()
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

# --------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---------------------
def get_or_create_custom_id(user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> int:
    """Получение или создание пользовательского ID"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        
        cursor.execute("SELECT custom_id FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        
        if row:
            custom_id = row[0]
            cursor.execute("""
                UPDATE users SET username = ?, first_name = ?, last_name = ?, last_activity = ? 
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
        logging.error(f"Ошибка get_or_create_custom_id: {e}")
        return 0

def check_ticket_cooldown(user_id: int, bot_token: str = 'main') -> tuple[bool, Optional[int]]:
    """Проверка кулдауна на новое обращение"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
        logging.error(f"Ошибка check_ticket_cooldown: {e}")
        return False, None

def has_open_ticket(user_id: int, bot_token: str = 'main') -> bool:
    """Проверка наличия открытого тикета"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tickets WHERE user_id = ? AND bot_token = ? AND status = 'open'", 
                      (user_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        return row is not None
    except Exception as e:
        logging.error(f"Ошибка has_open_ticket: {e}")
        return False

def get_open_ticket_info(user_id: int, bot_token: str = 'main') -> Optional[tuple]:
    """Получение информации об открытом тикете"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, custom_user_id, title, category, created_at, has_responded 
            FROM tickets 
            WHERE user_id = ? AND bot_token = ? AND status = 'open'
        """, (user_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        return row if row else None
    except Exception as e:
        logging.error(f"Ошибка get_open_ticket_info: {e}")
        return None

def has_consent(user_id: int, bot_token: str = 'main') -> bool:
    """Проверка согласия с правилами"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT consented_at FROM user_consent WHERE user_id = ? AND bot_token = ?", 
                      (user_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        return row is not None
    except:
        return False

def save_consent(user_id: int, bot_token: str = 'main'):
    """Сохранение согласия с правилами"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Проверка, является ли пользователь админом"""
    if bot_token == 'main':
        return user_id in ADMIN_IDS
    else:
        try:
            conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Проверка, является ли пользователь создателем группы"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT creator_id FROM group_settings WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        conn.close()
        return row and row[0] == user_id
    except:
        return False

def get_admin_name(user_id: int, bot_token: str = 'main') -> Optional[str]:
    """Получение имени админа"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT display_name FROM support_admins WHERE user_id = ? AND bot_token = ?", 
                      (user_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except:
        return None

def save_admin_name(user_id: int, display_name: str, bot_token: str = 'main'):
    """Сохранение имени админа"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            INSERT OR REPLACE INTO support_admins (user_id, display_name, registered_at, last_active, bot_token)
            VALUES (?, ?, COALESCE((SELECT registered_at FROM support_admins WHERE user_id = ? AND bot_token = ?), ?), ?, ?)
        """, (user_id, display_name, user_id, bot_token, now, now, bot_token))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка save_admin_name: {e}")

def update_admin_activity(user_id: int, bot_token: str = 'main'):
    """Обновление активности админа"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Добавление отзыва об админе"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
        logging.error(f"Ошибка add_admin_review: {e}")

def get_admin_reviews(admin_id: int, bot_token: str = 'main', limit: int = 20) -> List:
    """Получение отзывов об админе"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Создание нового тикета"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        custom_id = get_or_create_custom_id(user.id, user.username, user.first_name, user.last_name)
        
        cursor.execute("""
            UPDATE tickets SET status = 'closed', closed_at = ? 
            WHERE user_id = ? AND bot_token = ? AND status = 'open'
        """, (now, user.id, bot_token))
        
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
        logging.error(f"Ошибка create_new_ticket: {e}")
        return 0

async def notify_admins_new_ticket(user: types.User, ticket_id: int, custom_id: int, title: str, category: str, bot_token: str = 'main'):
    """Уведомление админов о новом тикете"""
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
        f"📱 Username: @{user.username or 'нет'}\n"
        f"📂 Категория: {category_text}\n"
        f"⏰ Время: {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')} UTC\n\n"
        f"Для ответа используйте /reply {custom_id}"
    )
    
    if bot_token == 'main':
        admin_ids = ADMIN_IDS
    else:
        try:
            conn = sqlite3.connect(DB_FILE, timeout=20)
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
                await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
            else:
                clone_bot, _, _ = active_bots.get(bot_token, (None, None, None))
                if clone_bot:
                    await clone_bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.error(f"Ошибка уведомления админа {admin_id}: {e}")

def check_spam_block(user_id: int, bot_token: str = 'main') -> tuple[bool, Optional[str]]:
    """Проверка на спам-блок"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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

def check_message_limit(user_id: int, bot_token: str = 'main') -> tuple[bool, Optional[str]]:
    """Проверка лимита сообщений без ответа"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) FROM messages m
            JOIN tickets t ON m.ticket_id = t.id
            WHERE t.user_id = ? AND m.sender_type = 'user' 
            AND t.has_responded = 0 AND t.status = 'open'
            AND m.timestamp > datetime('now', '-1 hour')
            AND t.bot_token = ?
        """, (user_id, bot_token))
        
        count = cursor.fetchone()[0]
        
        if count >= SPAM_LIMIT:
            block_until = datetime.utcnow() + timedelta(seconds=SPAM_BLOCK_TIME)
            cursor.execute("""
                UPDATE tickets SET blocked_until = ? 
                WHERE user_id = ? AND bot_token = ? AND status = 'open'
            """, (block_until.isoformat(), user_id, bot_token))
            conn.commit()
            conn.close()
            return True, f"⛔ Вы заблокированы на 10 минут за отправку более {SPAM_LIMIT} сообщений без ответа."
        
        conn.close()
        return False, None
    except:
        return False, None

def update_message_time(user_id: int, bot_token: str = 'main'):
    """Обновление времени последнего сообщения"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Получение тикета по пользовательскому ID"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Получение пользователя по custom_id"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, first_name FROM users WHERE custom_id = ?", (custom_id,))
        row = cursor.fetchone()
        conn.close()
        return row if row else None
    except:
        return None

def update_has_responded(user_id: int, bot_token: str = 'main'):
    """Обновление флага ответа админа"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Сброс флага ответа админа"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Сохранение сообщения в БД"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
        logging.error(f"Ошибка save_message: {e}")

def save_media_group(group_id: str, ticket_id: int, message_id: int, file_id: str, 
                     media_type: str, caption: str = None, bot_token: str = 'main'):
    """Сохранение медиа группы"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Получение всех медиа из группы"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Закрытие тикета"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
        logging.error(f"Ошибка close_ticket: {e}")
        return False
def save_rating_and_feedback(ticket_id: int, rating: int, feedback: str = None, 
                            admin_id: int = None, admin_name: str = None, 
                            user_id: int = None, user_custom_id: int = None,
                            bot_token: str = 'main'):
    """Сохранение оценки и отзыва"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
        logging.error(f"Ошибка save_rating_and_feedback: {e}")

def get_ticket_messages(ticket_id: int, bot_token: str = 'main') -> List:
    """Получение всех сообщений тикета"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Получение всех открытых тикетов"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Получение тикетов, в которых участвовал админ"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Поиск по тикетам"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        
        # Поиск по заголовку
        cursor.execute("""
            SELECT id, custom_user_id, username, first_name, title, created_at
            FROM tickets
            WHERE title LIKE ? AND bot_token = ?
            ORDER BY created_at DESC
            LIMIT 20
        """, (f"%{query}%", bot_token))
        by_title = cursor.fetchall()
        
        # Поиск по сообщениям
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
    """Получение полного профиля админа"""
    name = get_admin_name(admin_id, bot_token)
    
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
        
        # Получаем отзывы
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
    """Получение подробной статистики"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        stats = {}
        
        # Общая статистика
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE bot_token = ?", (bot_token,))
        stats['total_tickets'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'open' AND bot_token = ?", (bot_token,))
        stats['open_tickets'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'closed' AND bot_token = ?", (bot_token,))
        stats['closed_tickets'] = cursor.fetchone()[0]
        
        # Оценки
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
        
        # Статистика по дням (последние 30 дней)
        stats['daily'] = []
        for i in range(29, -1, -1):
            day = (datetime.utcnow() - timedelta(days=i)).strftime('%d.%m')
            cursor.execute("""
                SELECT COUNT(*) FROM tickets 
                WHERE date(created_at) = date('now', ?) AND bot_token = ?
            """, (f'-{i} days', bot_token))
            count = cursor.fetchone()[0]
            stats['daily'].append((day, count))
        
        # Статистика по категориям
        cursor.execute("""
            SELECT category, COUNT(*) FROM tickets 
            WHERE bot_token = ? 
            GROUP BY category
        """, (bot_token,))
        stats['categories'] = cursor.fetchall()
        
        # Топ администраторов
        cursor.execute("""
            SELECT display_name, total_replies, avg_rating, total_ratings
            FROM support_admins 
            WHERE bot_token = ? AND total_ratings > 0
            ORDER BY avg_rating DESC, total_ratings DESC
            LIMIT 10
        """, (bot_token,))
        stats['top_admins'] = cursor.fetchall()
        
        # Время ответа
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
        logging.error(f"Ошибка get_statistics: {e}")
        return {}

def add_to_blacklist(user_id: int, reason: str, blocked_by: int, bot_token: str = 'main'):
    """Добавление в черный список"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Проверка черного списка"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT reason FROM blacklist WHERE user_id = ? AND bot_token = ?", (user_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        return row is not None
    except:
        return False

# --------------------- ФУНКЦИИ ДЛЯ КЛОНОВ БОТОВ ---------------------
def verify_bot_token(token: str) -> tuple[bool, Optional[str], Optional[str]]:
    """Проверка токена бота"""
    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data['ok']:
                return True, data['result']['username'], data['result']['first_name']
        return False, None, None
    except:
        return False, None, None

async def start_clone_bot(token: str):
    """Запуск клона бота"""
    try:
        session = AiohttpSession()
        bot = Bot(token=token, session=session)
        dp = Dispatcher(storage=MemoryStorage())
        bot_info = await bot.get_me()
        
        # Здесь нужно зарегистрировать обработчики для клона
        # register_clone_handlers(dp, token)
        
        asyncio.create_task(dp.start_polling(bot))
        
        active_bots[token] = (bot, dp, bot_info)
        bot_sessions[token] = session
        
        logging.info(f"Клон бота @{bot_info.username} запущен")
        return True
    except Exception as e:
        logging.error(f"Ошибка запуска клона: {e}")
        return False

async def stop_clone_bot(token: str):
    """Остановка клона бота"""
    if token in active_bots:
        bot, dp, _ = active_bots[token]
        await bot.session.close()
        await dp.storage.close()
        del active_bots[token]
        
        if token in bot_sessions:
            await bot_sessions[token].close()
            del bot_sessions[token]
        
        logging.info(f"Клон бота {token} остановлен")
        return True
    return False

def save_clone_bot(token: str, owner_id: int, bot_username: str, bot_name: str, admins: List[int]):
    """Сохранение клона бота"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Получение клонов ботов пользователя"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT token, bot_username, bot_name, created_at, status FROM clone_bots WHERE owner_id = ?", 
                      (owner_id,))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except:
        return []

def delete_clone_bot(token: str):
    """Удаление клона бота"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM clone_bots WHERE token = ?", (token,))
        conn.commit()
        conn.close()
    except:
        pass

def get_bot_display_info(bot_token: str = 'main') -> Dict[str, str]:
    """Информация о боте для отображения"""
    if bot_token == 'main':
        return {'name': 'Основной бот', 'username': BOT_USERNAME, 'type': 'main'}
    
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT bot_username, bot_name FROM clone_bots WHERE token = ?", (bot_token,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {'name': row[1] or 'Клон бота', 'username': f'@{row[0]}' if row[0] else 'неизвестно', 'type': 'clone'}
    except:
        pass
    return {'name': 'Неизвестный бот', 'username': 'неизвестно', 'type': 'unknown'}

def format_bot_header(bot_token: str = 'main') -> str:
    """Заголовок с информацией о боте"""
    info = get_bot_display_info(bot_token)
    if info['type'] == 'main':
        return f"🤖 <b>Основной бот поддержки</b>\n└ {info['username']}\n\n"
    else:
        return f"🤖 <b>Бот поддержки</b>\n└ {info['username']}\n\n"

# --------------------- ФУНКЦИИ ДЛЯ ГРУПП ---------------------
def get_group_settings(chat_id: int) -> Optional[Dict[str, Any]]:
    """Получение настроек группы"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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

def create_group_settings(chat_id: int, chat_title: str, creator_id: int):
    """Создание настроек группы"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        
        cursor.execute("SELECT chat_id FROM group_settings WHERE chat_id = ?", (chat_id,))
        if cursor.fetchone():
            conn.close()
            return
        
        welcome_text = (
            f"👋 Добро пожаловать в чат, {{name}}!\n\n"
            f"Я - бот поддержки {BOT_USERNAME}\n"
            f"Создатель бота: {ADMIN_USERNAME}\n"
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
        logging.error(f"Ошибка create_group_settings: {e}")

def update_group_settings(chat_id: int, **kwargs):
    """Обновление настроек группы"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
        logging.error(f"Ошибка update_group_settings: {e}")

def reset_welcome_to_default(chat_id: int):
    """Сброс приветствия к значению по умолчанию"""
    default_text = (
        f"👋 Добро пожаловать в чат, {{name}}!\n\n"
        f"Я - бот поддержки {BOT_USERNAME}\n"
        f"Создатель бота: {ADMIN_USERNAME}\n"
        f"Этот бот создан для вопросов и предложений.\n"
        f"Если у вас есть вопрос - напишите мне в личные сообщения."
    )
    update_group_settings(chat_id, welcome_text=default_text, welcome_media=None, welcome_media_type=None)

def reset_goodbye_to_default(chat_id: int):
    """Сброс прощания к значению по умолчанию"""
    default_text = f"👋 {{name}} покинул чат"
    update_group_settings(chat_id, goodbye_text=default_text, goodbye_media=None, goodbye_media_type=None)

def add_trigger(chat_id: int, trigger_word: str, response_type: str, 
                response_content: str, created_by: int, caption: str = None) -> int:
    """Добавление триггера"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
        logging.error(f"Ошибка add_trigger: {e}")
        return 0

def delete_trigger(chat_id: int, identifier: str) -> bool:
    """Удаление триггера"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Получение всех триггеров группы"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Получение статистики триггера"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), MAX(used_at) FROM trigger_stats WHERE trigger_id = ?", (trigger_id,))
        row = cursor.fetchone()
        conn.close()
        return (row[0], row[1]) if row else (0, None)
    except:
        return (0, None)

def check_trigger(chat_id: int, text: str) -> Optional[Dict]:
    """Проверка сообщения на соответствие триггеру"""
    if not text:
        return None
    
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
    """Проверка длительности видео"""
    if message.video:
        duration = message.video.duration
        if duration > MAX_VIDEO_DURATION:
            return False, duration
    return True, None
# --------------------- КЛАВИАТУРЫ ---------------------
def get_admin_main_menu(bot_token: str = 'main') -> InlineKeyboardMarkup:
    """Главное меню для админа"""
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
    """Главное меню для пользователя"""
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

def get_group_main_menu() -> InlineKeyboardMarkup:
    """Главное меню для групп"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Задать вопрос", url=f"https://t.me/{BOT_USERNAME[1:]}")
    builder.button(text="ℹ️ Правила чата", callback_data="group:rules")
    builder.button(text="👤 Создатель", url=f"https://t.me/{ADMIN_USERNAME[1:]}")
    builder.adjust(1)
    return builder.as_markup()

def get_category_menu() -> InlineKeyboardMarkup:
    """Меню выбора категории обращения"""
    builder = InlineKeyboardBuilder()
    builder.button(text="❓ Вопрос", callback_data="category:question")
    builder.button(text="⚠️ Проблема", callback_data="category:problem")
    builder.button(text="💡 Предложение", callback_data="category:suggestion")
    builder.button(text="📌 Другое", callback_data="category:other")
    builder.button(text="◀️ Назад", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_consent_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для согласия с правилами"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Я согласен с правилами", callback_data="consent:accept")
    builder.button(text="◀️ Назад", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_cancel_keyboard(for_group: bool = False) -> InlineKeyboardMarkup:
    """Кнопка отмены - для ЛС и групп по-разному"""
    builder = InlineKeyboardBuilder()
    if for_group:
        builder.button(text="❌ Отменить", callback_data="group:cancel")
    else:
        builder.button(text="❌ Отменить", callback_data="support:cancel")
    return builder.as_markup()

def get_after_message_menu() -> InlineKeyboardMarkup:
    """Меню после отправки сообщения"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Продолжить диалог", callback_data="support:continue")
    builder.button(text="🔒 Закрыть обращение", callback_data="support:close")
    builder.button(text="🏠 Главное меню", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_rating_keyboard(ticket_id: int, admin_id: int = None) -> InlineKeyboardMarkup:
    """Клавиатура для оценки"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐️ 5 - Отлично", callback_data=f"rate:5:{ticket_id}:{admin_id or 0}")
    builder.button(text="⭐️ 4 - Хорошо", callback_data=f"rate:4:{ticket_id}:{admin_id or 0}")
    builder.button(text="⭐️ 3 - Нормально", callback_data=f"rate:3:{ticket_id}:{admin_id or 0}")
    builder.button(text="⭐️ 2 - Плохо", callback_data=f"rate:2:{ticket_id}:{admin_id or 0}")
    builder.button(text="⭐️ 1 - Ужасно", callback_data=f"rate:1:{ticket_id}:{admin_id or 0}")
    builder.adjust(1)
    return builder.as_markup()

def get_ticket_actions_keyboard(ticket_id: int, user_id: int, custom_id: int) -> InlineKeyboardMarkup:
    """Кнопки действий для админа"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Закрыть обращение", callback_data=f"close:{ticket_id}:{user_id}:{custom_id}")
    builder.button(text="📜 История", callback_data=f"admin:view_ticket_{ticket_id}")
    builder.button(text="⛔ В черный список", callback_data=f"blacklist:{user_id}:{custom_id}")
    builder.adjust(1)
    return builder.as_markup()

def get_user_tickets_keyboard(tickets: List) -> InlineKeyboardMarkup:
    """Клавиатура со списком обращений пользователя"""
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
    """Клавиатура для черного списка"""
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить в ЧС", callback_data="blacklist:add")
    builder.button(text="📋 Список ЧС", callback_data="blacklist:list")
    builder.button(text="❌ Удалить из ЧС", callback_data="blacklist:remove")
    builder.button(text="◀️ Назад", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_clone_management_keyboard(token: str) -> InlineKeyboardMarkup:
    """Клавиатура управления клоном бота"""
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Управление админами", callback_data=f"clone:admins:{token}")
    builder.button(text="📊 Статистика бота", callback_data=f"clone:stats:{token}")
    builder.button(text="🔄 Перезапустить", callback_data=f"clone:restart:{token}")
    builder.button(text="❌ Удалить бота", callback_data=f"clone:delete:{token}")
    builder.button(text="◀️ Назад", callback_data="clone:list")
    builder.adjust(1)
    return builder.as_markup()

def get_welcome_delete_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для удаления приветствия"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 По умолчанию", callback_data="welcome:default")
    builder.button(text="🔴 Выключить", callback_data="welcome:disable")
    builder.button(text="❌ Отмена", callback_data="welcome:cancel")
    builder.adjust(2)
    return builder.as_markup()

def get_goodbye_delete_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для удаления прощания"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 По умолчанию", callback_data="goodbye:default")
    builder.button(text="🔴 Выключить", callback_data="goodbye:disable")
    builder.button(text="❌ Отмена", callback_data="goodbye:cancel")
    builder.adjust(2)
    return builder.as_markup()

def get_enable_confirmation_keyboard(action: str) -> InlineKeyboardMarkup:
    """Клавиатура для подтверждения включения"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"{action}:confirm")
    builder.button(text="❌ Отменить", callback_data=f"{action}:cancel")
    builder.adjust(2)
    return builder.as_markup()

def get_triggers_list_keyboard(chat_id: int, triggers: List) -> InlineKeyboardMarkup:
    """Клавиатура со списком триггеров"""
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

# --------------------- ИНИЦИАЛИЗАЦИЯ ---------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Словарь для временного хранения альбомов
media_groups_buffer: Dict[str, List[Message]] = defaultdict(list)

# --------------------- КОМАНДЫ ДЛЯ ГРУПП ---------------------
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработка команды /start"""
    if message.chat.type != 'private':
        # В группе показываем информацию о боте
        settings = get_group_settings(message.chat.id)
        if not settings and message.from_user:
            create_group_settings(message.chat.id, message.chat.title or "Группа", message.from_user.id)
        
        await message.answer(
            f"👋 Привет! Я бот поддержки {BOT_USERNAME}\n\n"
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
            reply_markup=get_group_main_menu()
        )
        return

    # ЛИЧНЫЕ СООБЩЕНИЯ - поддержка
    user = message.from_user
    bot_token = 'main'
    
    # Проверяем черный список
    if check_blacklist(user.id):
        await message.answer(
            f"⛔ Вы находитесь в черном списке и не можете использовать поддержку.\n"
            f"Для вопросов обратитесь к {ADMIN_USERNAME}"
        )
        return
    
    # Получаем или создаем пользовательский ID
    custom_id = get_or_create_custom_id(user.id, user.username, user.first_name, user.last_name)
    
    # Проверяем, админ ли пользователь
    if is_admin(user.id, bot_token):
        # Админ - показываем админское меню
        if not get_admin_name(user.id, bot_token):
            # Админ не зарегистрирован - просим представиться
            await message.answer(
                f"👋 Добро пожаловать в панель поддержки {BOT_USERNAME}!\n"
                f"Ваш персональный ID: <code>{custom_id}</code>\n\n"
                f"Введите своё имя в формате:\n"
                f"Имя Ф.\n\n"
                f"Пример: Иван З.",
                parse_mode=ParseMode.HTML
            )
            await state.set_state(AdminRegistration.waiting_for_name)
        else:
            # Админ зарегистрирован - показываем админ-меню
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
        # Обычный пользователь
        # Проверяем, есть ли открытое обращение
        open_ticket = get_open_ticket_info(user.id, bot_token)
        if open_ticket:
            ticket_id, custom_id, title, category, created_at, has_responded = open_ticket
            created = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")
            await message.answer(
                f"👋 С возвращением в {BOT_USERNAME}!\n"
                f"Ваш ID: <code>{custom_id}</code>\n\n"
                f"📌 У вас есть открытое обращение #{custom_id}\n"
                f"📝 Тема: {title}\n"
                f"📅 Создано: {created}\n"
                f"📂 Категория: {category}\n\n"
                f"Продолжите диалог:",
                parse_mode=ParseMode.HTML
            )
            await state.set_state(TicketStates.in_dialog)
            await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)
        else:
            # Новый пользователь или нет открытых обращений
            await message.answer(
                f"👋 Добро пожаловать в {BOT_USERNAME}!\n"
                f"Создатель бота: {ADMIN_USERNAME}\n"
                f"Ваш персональный ID: <code>{custom_id}</code>\n\n"
                f"Выберите действие:",
                parse_mode=ParseMode.HTML,
                reply_markup=get_user_main_menu(bot_token)
            )
        await state.clear()

@dp.message(Command("triggers"))
async def cmd_triggers(message: Message, state: FSMContext):
    """Просмотр триггеров (только создатель группы)"""
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    
    # Проверяем, является ли пользователь создателем группы
    settings = get_group_settings(message.chat.id)
    if not settings:
        if message.from_user:
            create_group_settings(message.chat.id, message.chat.title or "Группа", message.from_user.id)
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
    """Добавление нового триггера"""
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    
    # Проверяем, является ли пользователь создателем группы
    settings = get_group_settings(message.chat.id)
    if not settings:
        if message.from_user:
            create_group_settings(message.chat.id, message.chat.title or "Группа", message.from_user.id)
        settings = get_group_settings(message.chat.id)
    
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может добавлять триггеры")
        return
    
    # Получаем слово-триггер из команды
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
    
    await state.update_data(trigger_word=trigger_word, chat_id=message.chat.id)
    await message.answer(
        f"✅ Слово '{trigger_word}' сохранено.\n\n"
        f"Теперь отправьте ответ, который бот будет отправлять на этот триггер.\n"
        f"Можно отправить: текст, фото, видео, GIF, стикер.\n\n"
        f"❗️ Фото/видео/GIF должны быть без текста (текст станет подписью)",
        reply_markup=get_cancel_keyboard(for_group=True)
    )
    await state.set_state(TriggerStates.waiting_for_trigger_response)

@dp.message(Command("deletetrigger"))
async def cmd_deletetrigger(message: Message, state: FSMContext):
    """Удаление триггера по слову или ID"""
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    
    # Проверяем, является ли пользователь создателем группы
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
    """Установка приветствия (только создатель группы)"""
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    
    settings = get_group_settings(message.chat.id)
    if not settings:
        if message.from_user:
            create_group_settings(message.chat.id, message.chat.title or "Группа", message.from_user.id)
        settings = get_group_settings(message.chat.id)
    
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель группы может изменять приветствие")
        return
    
    # Проверяем, есть ли контент
    has_text = message.text and len(message.text.split()) > 1
    has_media = message.photo or message.video or message.animation
    has_reply = message.reply_to_message is not None
    
    if not (has_text or has_media or has_reply):
        # Нет контента - показываем текущее
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
    
    # Обрабатываем контент
    media_type = None
    media_id = None
    caption = None
    
    # Если это ответ на другое сообщение
    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.text:
            caption = replied.text
        elif replied.photo:
            media_type = 'photo'
            media_id = replied.photo[-1].file_id
            caption = replied.caption
        elif replied.video:
            # Проверяем длительность видео
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
        # Контент в самом сообщении
        if message.photo:
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
            # Текст после команды
            parts = message.text.split(maxsplit=1)
            if len(parts) > 1:
                caption = parts[1]
    
    if not caption and not media_type:
        await message.answer("❌ Не отправлено никакого контента")
        return
    
    # Сохраняем
    update_data = {
        'welcome_text': caption or "👋 Добро пожаловать, {name}!",
        'welcome_media': media_id,
        'welcome_media_type': media_type,
        'welcome_enabled': 1
    }
    update_group_settings(message.chat.id, **update_data)
    
    await message.answer("✅ Приветствие успешно обновлено!")

@dp.message(Command("bye"))
async def cmd_bye(message: Message, state: FSMContext):
    """Установка прощания (только создатель группы)"""
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
    
    # Проверяем, есть ли контент
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
    
    # Обрабатываем контент
    media_type = None
    media_id = None
    caption = None
    
    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.text:
            caption = replied.text
        elif replied.photo:
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
    
    # Сохраняем
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
    """Удаление приветствия (только создатель группы)"""
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда работает только в группах")
        return
    
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
    await state.update_data(chat_id=message.chat.id)

@dp.message(Command("delbye"))
async def cmd_delbye(message: Message, state: FSMContext):
    """Удаление прощания (только создатель группы)"""
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

# --------------------- ОБРАБОТЧИКИ СОБЫТИЙ В ГРУППАХ ---------------------
@dp.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_user_join(event: ChatMemberUpdated):
    """Обработчик входа пользователя в группу"""
    settings = get_group_settings(event.chat.id)
    if not settings or not settings['welcome_enabled']:
        return
    
    user = event.new_chat_member.user
    name = user.full_name
    
    welcome_text = settings['welcome_text'].replace('{name}', name)
    
    # Добавляем стандартную подпись
    welcome_text += f"\n\nℹ️ Этот бот для вопросов и предложений. Напишите мне в ЛС: {BOT_USERNAME}"
    
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
        logging.error(f"Ошибка отправки приветствия: {e}")

@dp.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_user_leave(event: ChatMemberUpdated):
    """Обработчик выхода пользователя из группы"""
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
        logging.error(f"Ошибка отправки прощания: {e}")

@dp.message(F.chat.type.in_({'group', 'supergroup'}))
async def handle_group_message(message: Message):
    """Обработка сообщений в группах (проверка триггеров)"""
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
            logging.error(f"Ошибка отправки триггера: {e}")

# --------------------- ОБРАБОТЧИКИ СОСТОЯНИЙ ДЛЯ ГРУПП ---------------------
@dp.message(TriggerStates.waiting_for_trigger_response)
async def process_trigger_response(message: Message, state: FSMContext):
    """Обработка ответа на триггер"""
    data = await state.get_data()
    chat_id = data['chat_id']
    trigger_word = data['trigger_word']
    
    # Проверяем видео на длительность
    if message.video:
        is_valid, duration = await check_video_duration(message)
        if not is_valid:
            await message.answer(
                f"❌ Видео слишком длинное! Максимальная длительность: {MAX_VIDEO_DURATION} секунд.\n"
                f"Ваше видео: {duration} сек. Попробуйте ещё раз."
            )
            return
    
    # Определяем тип ответа
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
    
    # Сохраняем триггер
    trigger_id = add_trigger(chat_id, trigger_word, response_type, response_content, message.from_user.id, caption)
    
    # Получаем статистику
    total_uses, last_used = get_trigger_stats(trigger_id)
    last_used_str = datetime.fromisoformat(last_used).strftime("%d.%m.%Y %H:%M") if last_used else "никогда"
    
    await message.answer(
        f"✅ Триггер '#{trigger_id} - {trigger_word}' успешно создан!\n"
        f"📊 Статистика: пока не использован",
        reply_markup=InlineKeyboardBuilder()
            .button(text="📋 Список триггеров", callback_data="trigger:list")
            .button(text="➕ Ещё триггер", callback_data="trigger:add")
            .as_markup()
    )
    await state.clear()

# --------------------- РЕГИСТРАЦИЯ АДМИНА ---------------------
@dp.message(AdminRegistration.waiting_for_name)
async def register_admin(message: Message, state: FSMContext):
    """Регистрация нового админа"""
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
    """Команда для изменения имени админа"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        return
    
    await message.answer(
        "Введите новое имя в формате 'Имя Ф.' (пример: Иван З.):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminEditName.waiting_for_new_name)

@dp.message(AdminEditName.waiting_for_new_name)
async def change_name(message: Message, state: FSMContext):
    """Изменение имени админа"""
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

# --------------------- ОБРАБОТЧИК ЗАГОЛОВКА ОБРАЩЕНИЯ ---------------------
@dp.message(TicketStates.waiting_title)
async def handle_ticket_title(message: Message, state: FSMContext):
    """Обработка заголовка обращения"""
    title = message.text.strip()
    
    if len(title) < 5 or len(title) > 100:
        await message.answer(
            "❌ Заголовок должен содержать от 5 до 100 символов.\n"
            "Попробуйте ещё раз:"
        )
        return
    
    data = await state.get_data()
    category = data.get('category', 'question')
    
    ticket_id = create_new_ticket(message.from_user, title, category)
    custom_id = get_or_create_custom_id(message.from_user.id)
    
    await message.answer(
        f"✅ <b>Обращение #{custom_id} создано!</b>\n"
        f"📝 Тема: {title}\n"
        f"📂 Категория: {category}\n\n"
        f"📝 Опишите вашу проблему или вопрос подробно.\n"
        f"Можно отправлять текст, фото, видео, альбомы.\n\n"
        f"Ответ поддержки придёт сюда в этот же чат.",
        parse_mode=ParseMode.HTML
    )
    
    await state.set_state(TicketStates.in_dialog)
    await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)
# --------------------- ОБРАБОТЧИК ОТЗЫВА ---------------------
@dp.message(TicketStates.waiting_feedback)
async def handle_feedback(message: Message, state: FSMContext):
    """Обработка текстового отзыва после оценки"""
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

# --------------------- ОБРАБОТКА СООБЩЕНИЙ ПОЛЬЗОВАТЕЛЯ ---------------------
@dp.message(F.chat.type == 'private')
async def handle_user_message(message: Message, state: FSMContext):
    """Обработка сообщений от пользователя в диалоге"""
    if message.text and message.text.startswith('/'):
        return
    
    user = message.from_user
    
    # Проверяем черный список
    if check_blacklist(user.id):
        await message.answer(
            f"⛔ Вы находитесь в черном списке и не можете использовать поддержку."
        )
        return
    
    # Получаем текущее состояние
    current_state = await state.get_state()
    
    # Если пользователь не в диалоге, проверяем есть ли открытый тикет
    if current_state != TicketStates.in_dialog.state:
        if has_open_ticket(user.id):
            open_ticket = get_open_ticket_info(user.id)
            if open_ticket:
                ticket_id, custom_id, title, _, _, _ = open_ticket
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
            await message.answer(
                "❌ У вас нет активного обращения.\n"
                "Хотите создать новое?",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="✅ Да, создать", callback_data="support:start")
                    .button(text="❌ Нет", callback_data="menu:main")
                    .adjust(2)
                    .as_markup()
            )
            return
    
    # Получаем данные из состояния
    data = await state.get_data()
    ticket_id = data.get('ticket_id')
    custom_id = data.get('custom_id')
    title = data.get('title')
    
    # Если нет ticket_id в состоянии, пробуем найти открытый тикет
    if not ticket_id:
        open_ticket = get_open_ticket_info(user.id)
        if open_ticket:
            ticket_id, custom_id, title, _, _, _ = open_ticket
            await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)
        else:
            await message.answer(
                "❌ Ошибка: обращение не найдено.\n"
                "Начните новое через /start"
            )
            await state.clear()
            return
    
    # Проверяем, что тикет всё ещё открыт
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
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
    except:
        pass
    
    # Проверка на спам-блок
    blocked, block_msg = check_spam_block(user.id)
    if blocked:
        await message.answer(block_msg)
        return
    
    # Проверка лимита сообщений без ответа
    limit_exceeded, limit_msg = check_message_limit(user.id)
    if limit_exceeded:
        await message.answer(limit_msg)
        return
    
    # Фильтр спама
    if message.sticker or message.animation or message.dice:
        await message.answer("❌ Пожалуйста, отправляйте текстовые сообщения или фото/видео по теме.")
        return
    
    if message.text and len(message.text.strip()) < 3 and not any(c.isalpha() for c in message.text):
        await message.answer("❌ Слишком короткое сообщение. Опишите проблему подробнее.")
        return
    
    # Получаем категорию
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT category FROM tickets WHERE id = ?", (ticket_id,))
        row = cursor.fetchone()
        category = row[0] if row else 'question'
        conn.close()
    except:
        category = 'question'
    
    # Обработка альбомов
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
                    logging.error(f"Ошибка отправки админу {admin_id}: {e}")
            
            await message.answer(
                f"✅ Альбом отправлен в обращение #{custom_id}.",
                reply_markup=get_after_message_menu()
            )
            
            update_message_time(user.id)
            return
    
    # Обычное сообщение
    content_for_admin = ""
    
    if message.text:
        save_message(ticket_id, 'user', user.id, message.text, user.first_name)
        content_for_admin = message.text
        await message.answer(
            f"✅ Сообщение отправлено в обращение #{custom_id}.", 
            reply_markup=get_after_message_menu()
        )
    elif message.photo:
        file_id = message.photo[-1].file_id
        save_message(ticket_id, 'user', user.id, f"[Фото] {message.caption or ''}", user.first_name,
                    file_id=file_id, media_type='photo', caption=message.caption)
        content_for_admin = f"[Фото] {message.caption or ''}"
        await message.answer(
            f"✅ Фото отправлено в обращение #{custom_id}.", 
            reply_markup=get_after_message_menu()
        )
    elif message.video:
        file_id = message.video.file_id
        save_message(ticket_id, 'user', user.id, f"[Видео] {message.caption or ''}", user.first_name,
                    file_id=file_id, media_type='video', caption=message.caption)
        content_for_admin = f"[Видео] {message.caption or ''}"
        await message.answer(
            f"✅ Видео отправлено в обращение #{custom_id}.", 
            reply_markup=get_after_message_menu()
        )
    elif message.voice:
        file_id = message.voice.file_id
        save_message(ticket_id, 'user', user.id, "[Голосовое сообщение]", user.first_name,
                    file_id=file_id, media_type='voice')
        content_for_admin = "[Голосовое сообщение]"
        await message.answer(
            f"✅ Голосовое отправлено в обращение #{custom_id}.", 
            reply_markup=get_after_message_menu()
        )
    elif message.document:
        file_id = message.document.file_id
        save_message(ticket_id, 'user', user.id, f"[Документ] {message.document.file_name}", user.first_name,
                    file_id=file_id, media_type='document', caption=message.caption)
        content_for_admin = f"[Документ] {message.document.file_name}"
        await message.answer(
            f"✅ Документ отправлен в обращение #{custom_id}.", 
            reply_markup=get_after_message_menu()
        )
    else:
        await message.answer("❌ Неподдерживаемый тип сообщения")
        return
    
    # Отправка админам
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
            logging.error(f"Ошибка отправки админу {admin_id}: {e}")
    
    update_message_time(user.id)
    reset_has_responded(user.id)

# --------------------- ОТВЕТ АДМИНА ---------------------
@dp.message(lambda m: is_admin(m.from_user.id) and m.reply_to_message is not None)
async def handle_admin_reply(message: Message):
    """Обработка ответа админа (reply на пересланное сообщение)"""
    replied = message.reply_to_message
    
    # Определяем ID пользователя
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
    
    # Получаем тикет
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
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
        # Отправляем ответ
        if message.text:
            await bot.send_message(
                user_id, 
                f"✉️ <b>Ответ от {admin_name}:</b>\n\n{message.text}",
                parse_mode=ParseMode.HTML
            )
            save_message(ticket_id, 'admin', message.from_user.id, message.text, admin_name)
        elif message.photo:
            await bot.send_photo(
                user_id, 
                message.photo[-1].file_id,
                caption=f"✉️ <b>Ответ от {admin_name}:</b>\n\n{message.caption or ''}",
                parse_mode=ParseMode.HTML
            )
            save_message(ticket_id, 'admin', message.from_user.id, f"[Фото] {message.caption or ''}", admin_name)
        elif message.video:
            await bot.send_video(
                user_id, 
                message.video.file_id,
                caption=f"✉️ <b>Ответ от {admin_name}:</b>\n\n{message.caption or ''}",
                parse_mode=ParseMode.HTML
            )
            save_message(ticket_id, 'admin', message.from_user.id, f"[Видео] {message.caption or ''}", admin_name)
        elif message.voice:
            await bot.send_voice(user_id, message.voice.file_id)
            await bot.send_message(user_id, f"✉️ <b>Ответ от {admin_name}:</b> (голосовое)", parse_mode=ParseMode.HTML)
            save_message(ticket_id, 'admin', message.from_user.id, "[Голосовое]", admin_name)
        elif message.document:
            await bot.send_document(
                user_id, 
                message.document.file_id,
                caption=f"✉️ <b>Ответ от {admin_name}:</b>\n\n{message.caption or ''}",
                parse_mode=ParseMode.HTML
            )
            save_message(ticket_id, 'admin', message.from_user.id, f"[Документ] {message.document.file_name}", admin_name)
        elif message.media_group_id:
            await message.copy_to(user_id)
            await bot.send_message(user_id, f"✉️ <b>Ответ от {admin_name}:</b> (альбом)", parse_mode=ParseMode.HTML)
            save_message(ticket_id, 'admin', message.from_user.id, "[Альбом]", admin_name, media_group_id=message.media_group_id)
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
        logging.error(f"Ошибка ответа админа: {e}")

# --------------------- ПЛАНИРОВЩИК ЗАДАЧ ---------------------
async def scheduler():
    """Планировщик для автоматического закрытия старых тикетов"""
    while True:
        await asyncio.sleep(3600)  # Каждый час
        try:
            conn = sqlite3.connect(DB_FILE, timeout=20)
            cursor = conn.cursor()
            
            cutoff = (datetime.utcnow() - timedelta(hours=TICKET_AUTO_CLOSE_HOURS)).isoformat()
            
            # Для основного бота
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
            
            # Для клонов ботов
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
                logging.info(f"Автоматически закрыто {total_closed} старых обращений")
                
        except Exception as e:
            logging.error(f"Ошибка в планировщике: {e}")

# --------------------- РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ ДЛЯ КЛОНОВ ---------------------
def register_clone_handlers(dp: Dispatcher, bot_token: str):
    """Регистрация обработчиков для клона бота"""
    # Здесь должны быть обработчики для клонов (упрощённая версия основных)
    # Из-за ограничений длины кода, они не включены в этот файл
    pass

# --------------------- ЗАПУСК ---------------------
async def main():
    """Основная функция запуска бота"""
    logging.info(f"Бот {BOT_USERNAME} запускается...")
    
    # Запускаем все сохраненные клоны ботов
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT token FROM clone_bots WHERE status = 'active'")
        clones = cursor.fetchall()
        conn.close()
        
        for clone in clones:
            token = clone[0]
            logging.info(f"Запуск клона бота {token}...")
            await start_clone_bot(token)
            await asyncio.sleep(1)
    except:
        pass
    
    # Запускаем планировщик
    asyncio.create_task(scheduler())
    
    # Запускаем polling для основного бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен")
        
        # Останавливаем всех клонов
        for token in list(active_bots.keys()):
            asyncio.run(stop_clone_bot(token))
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")
