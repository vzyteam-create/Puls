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
# ⚠️ ВАЖНО: ЗАМЕНИТЕ НА СВОИ ДАННЫЕ ⚠️
BOT_TOKEN = "8533732699:AAH_iSLnJnHI0-ROJE8fwqAxKQPeRbo_Lck"  # Токен основного бота
BOT_USERNAME = "@PulsSupportBot"  # Юзернейм основного бота
ADMIN_IDS = [6708209142, 8475965198]  # ID администраторов
ADMIN_USERNAME = "@vanezyyy"  # Твой юзернейм
MAIN_BOT_USERNAME = "@PulsOfficialManager_bot"
DB_FILE = "tickets.db"

# Настройки анти-спама
TICKET_COOLDOWN = 300  # 5 минут между новыми обращениями
SPAM_LIMIT = 5  # сообщений без ответа
SPAM_BLOCK_TIME = 600  # 10 минут
TICKET_AUTO_CLOSE_HOURS = 48  # часов без активности
MAX_VIDEO_DURATION = 20  # максимум секунд для видео в приветствиях
USER_ID_COUNTER = 100  # ID пользователей начинаются со 100

# --------------------- БАЗА ДАННЫХ ---------------------
def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DB_FILE, timeout=10)
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
    
    # Таблица согласия с правилами
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
    
    # Индексы
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_custom_id ON tickets(custom_user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_triggers_chat ON triggers(chat_id)')
    
    conn.commit()
    conn.close()
    
    # Миграция старых данных
    migrate_old_database()

def migrate_old_database():
    """Обновление старой базы данных"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        
        # Добавляем недостающие колонки
        try:
            cursor.execute("SELECT total_ratings FROM support_admins LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE support_admins ADD COLUMN total_ratings INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE support_admins ADD COLUMN avg_rating REAL DEFAULT 0")
            print("✅ Добавлены колонки total_ratings и avg_rating")
        
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
    waiting_for_trigger_response = State()

class WelcomeStates(StatesGroup):
    waiting_for_delete_choice = State()

class GoodbyeStates(StatesGroup):
    waiting_for_delete_choice = State()

# --------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---------------------
def get_or_create_custom_id(user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> int:
    """Получение или создание пользовательского ID"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
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
        conn = sqlite3.connect(DB_FILE, timeout=10)
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
        conn = sqlite3.connect(DB_FILE, timeout=10)
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
        conn = sqlite3.connect(DB_FILE, timeout=10)
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

def is_admin(user_id: int, bot_token: str = 'main') -> bool:
    """Проверка, является ли пользователь админом"""
    if bot_token == 'main':
        return user_id in ADMIN_IDS
    else:
        try:
            conn = sqlite3.connect(DB_FILE, timeout=10)
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
        conn = sqlite3.connect(DB_FILE, timeout=10)
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
        conn = sqlite3.connect(DB_FILE, timeout=10)
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
        conn = sqlite3.connect(DB_FILE, timeout=10)
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

def create_new_ticket(user: types.User, title: str, category: str = 'question', bot_token: str = 'main') -> int:
    """Создание нового тикета"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
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
        logging.error(f"Ошибка create_new_ticket: {e}")
        return 0

async def notify_admins_new_ticket(user: types.User, ticket_id: int, custom_id: int, title: str, category: str, bot_token: str = 'main'):
    """Уведомление админов о новом тикете"""
    category_names = {'question': '❓ Вопрос', 'problem': '⚠️ Проблема', 'suggestion': '💡 Предложение', 'other': '📌 Другое'}
    category_text = category_names.get(category, category)
    
    text = (
        f"🆕 <b>НОВОЕ ОБРАЩЕНИЕ #{custom_id}</b>\n\n"
        f"📝 <b>Тема:</b> {title}\n"
        f"👤 Пользователь: <a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
        f"🆔 ID: <code>{custom_id}</code>\n"
        f"📱 @{user.username or 'нет'}\n"
        f"📂 Категория: {category_text}\n"
        f"⏰ {datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC\n\n"
        f"Для ответа: /reply {custom_id}"
    )
    
    if bot_token == 'main':
        admin_ids = ADMIN_IDS
    else:
        try:
            conn = sqlite3.connect(DB_FILE, timeout=10)
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

def save_message(ticket_id: int, sender_type: str, sender_id: int, content: str, 
                 sender_name: str = None, media_group_id: str = None, 
                 file_id: str = None, media_type: str = None, caption: str = None,
                 bot_token: str = 'main'):
    """Сохранение сообщения"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
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

def close_ticket(ticket_id: int, closed_by: int, closed_by_name: str = None, bot_token: str = 'main') -> bool:
    """Закрытие тикета"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
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
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE tickets SET rating = ?, feedback_text = ? 
            WHERE id = ? AND bot_token = ?
        """, (rating, feedback, ticket_id, bot_token))
        
        if admin_id and user_id:
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
                total, avg = row
                new_total = total + 1
                new_avg = (avg * total + rating) / new_total
                cursor.execute("""
                    UPDATE support_admins SET total_ratings = ?, avg_rating = ? 
                    WHERE user_id = ? AND bot_token = ?
                """, (new_total, new_avg, admin_id, bot_token))
        
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка save_rating_and_feedback: {e}")

def get_ticket_by_custom_id(custom_id: int, bot_token: str = 'main') -> Optional[tuple]:
    """Получение тикета по пользовательскому ID"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, user_id, status, title, category, created_at 
            FROM tickets 
            WHERE custom_user_id = ? AND bot_token = ? AND status = 'open'
        """, (custom_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        return row
    except:
        return None

def get_user_by_custom_id(custom_id: int) -> Optional[tuple]:
    """Получение пользователя по custom_id"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, first_name FROM users WHERE custom_id = ?", (custom_id,))
        row = cursor.fetchone()
        conn.close()
        return row
    except:
        return None

def update_has_responded(user_id: int, bot_token: str = 'main'):
    """Обновление флага ответа админа"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
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
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tickets SET has_responded = 0 
            WHERE user_id = ? AND bot_token = ? AND status = 'open'
        """, (user_id, bot_token))
        conn.commit()
        conn.close()
    except:
        pass

def update_message_time(user_id: int, bot_token: str = 'main'):
    """Обновление времени последнего сообщения"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
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

def check_spam_block(user_id: int, bot_token: str = 'main') -> tuple[bool, Optional[str]]:
    """Проверка на спам-блок"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
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
    except:
        pass
    return False, None

def get_ticket_messages(ticket_id: int, bot_token: str = 'main') -> List:
    """Получение всех сообщений тикета"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
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
        conn = sqlite3.connect(DB_FILE, timeout=10)
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
# --------------------- ФУНКЦИИ ДЛЯ ГРУПП ---------------------
def get_group_settings(chat_id: int) -> Optional[Dict[str, Any]]:
    """Получение настроек группы"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
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
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        welcome_text = f"👋 Добро пожаловать в чат, {{name}}!\n\nЯ - бот поддержки {BOT_USERNAME}\nСоздатель: {ADMIN_USERNAME}"
        cursor.execute("""
            INSERT INTO group_settings 
            (chat_id, chat_title, creator_id, welcome_text, goodbye_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (chat_id, chat_title, creator_id, welcome_text, "👋 {name} покинул чат", now, now))
        conn.commit()
        conn.close()
    except:
        pass

def update_group_settings(chat_id: int, **kwargs):
    """Обновление настроек группы"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        updates = [f"{k} = ?" for k in kwargs.keys()]
        values = list(kwargs.values()) + [now, chat_id]
        cursor.execute(f"UPDATE group_settings SET {', '.join(updates)}, updated_at = ? WHERE chat_id = ?", values)
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка update_group_settings: {e}")

def add_trigger(chat_id: int, trigger_word: str, response_type: str, 
                response_content: str, created_by: int, caption: str = None) -> int:
    """Добавление триггера"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("SELECT id FROM triggers WHERE chat_id = ? AND trigger_word = ?", 
                      (chat_id, trigger_word.lower()))
        existing = cursor.fetchone()
        if existing:
            cursor.execute("""
                UPDATE triggers SET response_type = ?, response_content = ?, caption = ?, 
                created_by = ?, created_at = ?, use_count = 0 WHERE id = ?
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
    except:
        return 0

def delete_trigger(chat_id: int, identifier: str) -> bool:
    """Удаление триггера"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
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
    """Получение всех триггеров"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT id, trigger_word, response_type, use_count, created_at FROM triggers WHERE chat_id = ? ORDER BY trigger_word", (chat_id,))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except:
        return []

def check_trigger(chat_id: int, text: str) -> Optional[Dict]:
    """Проверка триггера"""
    if not text:
        return None
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT id, response_type, response_content, caption FROM triggers WHERE chat_id = ? AND LOWER(trigger_word) = LOWER(?)", 
                      (chat_id, text.strip()))
        row = cursor.fetchone()
        if row:
            trigger_id, rtype, content, caption = row
            cursor.execute("UPDATE triggers SET use_count = use_count + 1 WHERE id = ?", (trigger_id,))
            cursor.execute("INSERT INTO trigger_stats (trigger_id, used_at) VALUES (?, ?)", 
                          (trigger_id, datetime.utcnow().isoformat()))
            conn.commit()
            conn.close()
            return {'id': trigger_id, 'type': rtype, 'content': content, 'caption': caption}
        conn.close()
    except:
        pass
    return None

# --------------------- КЛАВИАТУРЫ ---------------------
def get_admin_main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📂 Открытые обращения", callback_data="admin:open_tickets")
    builder.button(text="📜 Моя история", callback_data="admin:my_history")
    builder.button(text="👤 Мой профиль", callback_data="admin:profile")
    builder.button(text="⭐️ Мои отзывы", callback_data="admin:my_reviews")
    builder.button(text="✏️ Изменить имя", callback_data="admin:change_name")
    builder.button(text="🔍 Поиск", callback_data="admin:search")
    builder.button(text="📊 Статистика", callback_data="admin:stats")
    builder.button(text="⛔ Черный список", callback_data="admin:blacklist")
    builder.adjust(1)
    return builder.as_markup()

def get_user_main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Обратиться в поддержку", callback_data="support:start")
    builder.button(text="ℹ️ Правила", callback_data="info:rules")
    builder.button(text="📋 Мои обращения", callback_data="user:my_tickets")
    builder.button(text="🤖 Создать своего бота", callback_data="clone:create")
    builder.button(text="📋 Мои боты", callback_data="clone:list")
    builder.button(text="🤖 Главный бот", url="https://t.me/PulsOfficialManager_bot")
    builder.adjust(1)
    return builder.as_markup()

def get_group_main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Задать вопрос", url=f"https://t.me/{BOT_USERNAME[1:]}")
    builder.button(text="ℹ️ Правила чата", callback_data="group:rules")
    builder.button(text="👤 Создатель", url=f"https://t.me/{ADMIN_USERNAME[1:]}")
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
    builder.button(text="✅ Я согласен", callback_data="consent:accept")
    builder.button(text="◀️ Назад", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_cancel_keyboard(for_group: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить", callback_data="group:cancel" if for_group else "support:cancel")
    return builder.as_markup()

def get_after_message_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Продолжить", callback_data="support:continue")
    builder.button(text="🔒 Закрыть", callback_data="support:close")
    builder.button(text="🏠 Меню", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_rating_keyboard(ticket_id: int, admin_id: int = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i in range(5, 0, -1):
        builder.button(text=f"{'⭐️' * i} {i}", callback_data=f"rate:{i}:{ticket_id}:{admin_id or 0}")
    builder.adjust(1)
    return builder.as_markup()

def get_ticket_actions_keyboard(ticket_id: int, user_id: int, custom_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Закрыть", callback_data=f"close:{ticket_id}:{user_id}:{custom_id}")
    builder.button(text="📜 История", callback_data=f"admin:view_ticket_{ticket_id}")
    builder.button(text="⛔ В ЧС", callback_data=f"blacklist:{user_id}:{custom_id}")
    builder.adjust(1)
    return builder.as_markup()

def get_user_tickets_keyboard(tickets: List) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for t in tickets:
        builder.button(text=f"#{t[1]} {t[2][:20]}", callback_data=f"user:view_ticket_{t[0]}")
    builder.button(text="◀️ Назад", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_triggers_list_keyboard(chat_id: int, triggers: List) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for t in triggers[:10]:
        emoji = "📝" if t[2] == 'text' else "📷"
        builder.button(text=f"{emoji} {t[1]}", callback_data=f"trigger:info:{t[0]}")
    builder.button(text="➕ Добавить", callback_data="trigger:add")
    builder.button(text="◀️ Назад", callback_data="group:menu")
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

# --------------------- ИНИЦИАЛИЗАЦИЯ ---------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
media_groups_buffer: Dict[str, List[Message]] = defaultdict(list)

# --------------------- КОМАНДЫ ---------------------
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if message.chat.type != 'private':
        settings = get_group_settings(message.chat.id)
        if not settings and message.from_user:
            create_group_settings(message.chat.id, message.chat.title or "Группа", message.from_user.id)
        await message.answer(
            f"👋 Я бот поддержки {BOT_USERNAME}\n\nКоманды для создателя:\n"
            f"/triggers - список триггеров\n/addtrigger слово - добавить\n/deletetrigger слово/ID - удалить\n"
            f"/hello текст/фото - приветствие\n/bye текст/фото - прощание\n/delhello - удалить приветствие\n/delbye - удалить прощание",
            reply_markup=get_group_main_menu())
        return

    user = message.from_user
    custom_id = get_or_create_custom_id(user.id, user.username, user.first_name, user.last_name)
    
    if is_admin(user.id):
        if not get_admin_name(user.id):
            await message.answer(f"👋 Введите имя в формате 'Имя Ф.':", parse_mode=ParseMode.HTML)
            await state.set_state(AdminRegistration.waiting_for_name)
        else:
            await message.answer(f"👋 С возвращением, {get_admin_name(user.id)}!\nВаш ID: <code>{custom_id}</code>",
                               parse_mode=ParseMode.HTML, reply_markup=get_admin_main_menu())
    else:
        open_ticket = get_open_ticket_info(user.id)
        if open_ticket:
            await state.set_state(TicketStates.in_dialog)
            await state.update_data(ticket_id=open_ticket[0], custom_id=open_ticket[1], title=open_ticket[2])
            await message.answer(f"👋 Продолжите обращение #{open_ticket[1]}: {open_ticket[2]}")
        else:
            await message.answer(f"👋 Добро пожаловать!\nВаш ID: <code>{custom_id}</code>",
                               parse_mode=ParseMode.HTML, reply_markup=get_user_main_menu())

@dp.message(Command("reply"))
async def reply_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /reply <ID> <текст>")
        return
    try:
        parts = args[1].split(maxsplit=1)
        custom_id, reply_text = int(parts[0]), parts[1] if len(parts) > 1 else ""
    except:
        await message.answer("Неверный формат")
        return
    
    ticket = get_ticket_by_custom_id(custom_id)
    if not ticket:
        await message.answer(f"❌ Тикет #{custom_id} не найден")
        return
    
    ticket_id, user_id, _, title, _, _ = ticket
    admin_name = get_admin_name(message.from_user.id)
    if not admin_name:
        await message.answer("❌ Зарегистрируйтесь через /start")
        return
    
    try:
        await bot.send_message(user_id, f"✉️ <b>Ответ от {admin_name}:</b>\n\n{reply_text}", parse_mode=ParseMode.HTML)
        update_has_responded(user_id)
        save_message(ticket_id, 'admin', message.from_user.id, reply_text, admin_name)
        await message.answer(f"✅ Ответ на #{custom_id} отправлен")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("addtrigger"))
async def cmd_addtrigger(message: Message, state: FSMContext):
    if message.chat.type == 'private':
        await message.answer("❌ Только в группах")
        return
    settings = get_group_settings(message.chat.id)
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /addtrigger слово")
        return
    word = args[1].strip().lower()
    if len(word) < 2 or len(word) > 50:
        await message.answer("❌ От 2 до 50 символов")
        return
    await state.update_data(trigger_word=word, chat_id=message.chat.id)
    await message.answer(f"✅ Слово '{word}'. Теперь отправьте ответ:", reply_markup=get_cancel_keyboard(for_group=True))
    await state.set_state(TriggerStates.waiting_for_trigger_response)

@dp.message(Command("deletetrigger"))
async def cmd_deletetrigger(message: Message):
    if message.chat.type == 'private':
        return
    settings = get_group_settings(message.chat.id)
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /deletetrigger слово или ID")
        return
    if delete_trigger(message.chat.id, args[1].strip()):
        await message.answer(f"✅ Триггер удален")
    else:
        await message.answer(f"❌ Не найден")

@dp.message(Command("triggers"))
async def cmd_triggers(message: Message):
    if message.chat.type == 'private':
        return
    triggers = get_triggers(message.chat.id)
    if not triggers:
        await message.answer("📭 Нет триггеров. /addtrigger слово")
        return
    text = "🔤 <b>Триггеры:</b>\n"
    for t in triggers:
        text += f"#{t[0]} - '{t[1]}' (исп. {t[3]})\n"
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(Command("hello"))
async def cmd_hello(message: Message, state: FSMContext):
    if message.chat.type == 'private':
        return
    settings = get_group_settings(message.chat.id)
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель")
        return
    has_content = (message.reply_to_message or message.photo or message.video or 
                  (message.text and len(message.text.split()) > 1))
    if not has_content:
        await message.answer(f"Текущее: {settings['welcome_text']}\nОтправьте с контентом: /hello текст")
        return
    media_type, media_id, caption = None, None, None
    if message.reply_to_message:
        r = message.reply_to_message
        if r.text:
            caption = r.text
        elif r.photo:
            media_type, media_id, caption = 'photo', r.photo[-1].file_id, r.caption
        elif r.video:
            if r.video.duration > MAX_VIDEO_DURATION:
                await message.answer(f"❌ Видео >{MAX_VIDEO_DURATION} сек")
                return
            media_type, media_id, caption = 'video', r.video.file_id, r.caption
    else:
        if message.photo:
            media_type, media_id, caption = 'photo', message.photo[-1].file_id, message.caption
        elif message.video:
            if message.video.duration > MAX_VIDEO_DURATION:
                await message.answer(f"❌ Видео >{MAX_VIDEO_DURATION} сек")
                return
            media_type, media_id, caption = 'video', message.video.file_id, message.caption
        elif message.text:
            caption = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else None
    if not caption and not media_type:
        await message.answer("❌ Нет контента")
        return
    update_group_settings(message.chat.id, welcome_text=caption or "👋 Добро пожаловать, {name}!", 
                         welcome_media=media_id, welcome_media_type=media_type, welcome_enabled=1)
    await message.answer("✅ Приветствие обновлено!")

@dp.message(Command("bye"))
async def cmd_bye(message: Message, state: FSMContext):
    if message.chat.type == 'private':
        return
    settings = get_group_settings(message.chat.id)
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель")
        return
    has_content = (message.reply_to_message or message.photo or message.video or 
                  (message.text and len(message.text.split()) > 1))
    if not has_content:
        await message.answer(f"Текущее: {settings['goodbye_text']}\nОтправьте с контентом: /bye текст")
        return
    media_type, media_id, caption = None, None, None
    if message.reply_to_message:
        r = message.reply_to_message
        if r.text:
            caption = r.text
        elif r.photo:
            media_type, media_id, caption = 'photo', r.photo[-1].file_id, r.caption
        elif r.video:
            if r.video.duration > MAX_VIDEO_DURATION:
                await message.answer(f"❌ Видео >{MAX_VIDEO_DURATION} сек")
                return
            media_type, media_id, caption = 'video', r.video.file_id, r.caption
    else:
        if message.photo:
            media_type, media_id, caption = 'photo', message.photo[-1].file_id, message.caption
        elif message.video:
            if message.video.duration > MAX_VIDEO_DURATION:
                await message.answer(f"❌ Видео >{MAX_VIDEO_DURATION} сек")
                return
            media_type, media_id, caption = 'video', message.video.file_id, message.caption
        elif message.text:
            caption = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else None
    if not caption and not media_type:
        await message.answer("❌ Нет контента")
        return
    update_group_settings(message.chat.id, goodbye_text=caption or "👋 {name} покинул чат", 
                         goodbye_media=media_id, goodbye_media_type=media_type, goodbye_enabled=1)
    await message.answer("✅ Прощание обновлено!")

@dp.message(Command("delhello"))
async def cmd_delhello(message: Message, state: FSMContext):
    if message.chat.type == 'private':
        return
    settings = get_group_settings(message.chat.id)
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель")
        return
    await message.answer("❓ Удалить приветствие?", reply_markup=get_welcome_delete_keyboard())
    await state.set_state(WelcomeStates.waiting_for_delete_choice)
    await state.update_data(chat_id=message.chat.id)

@dp.message(Command("delbye"))
async def cmd_delbye(message: Message, state: FSMContext):
    if message.chat.type == 'private':
        return
    settings = get_group_settings(message.chat.id)
    if not settings or settings['creator_id'] != message.from_user.id:
        await message.answer("❌ Только создатель")
        return
    await message.answer("❓ Удалить прощание?", reply_markup=get_goodbye_delete_keyboard())
    await state.set_state(GoodbyeStates.waiting_for_delete_choice)
    await state.update_data(chat_id=message.chat.id)

# --------------------- ОБРАБОТЧИКИ СОБЫТИЙ ---------------------
@dp.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_user_join(event: ChatMemberUpdated):
    settings = get_group_settings(event.chat.id)
    if not settings or not settings['welcome_enabled']:
        return
    text = settings['welcome_text'].replace('{name}', event.new_chat_member.user.full_name)
    text += f"\n\nℹ️ Вопросы в ЛС: {BOT_USERNAME}"
    try:
        if settings['welcome_media'] and settings['welcome_media_type'] == 'photo':
            await bot.send_photo(event.chat.id, settings['welcome_media'], caption=text)
        elif settings['welcome_media'] and settings['welcome_media_type'] == 'video':
            await bot.send_video(event.chat.id, settings['welcome_media'], caption=text)
        else:
            await bot.send_message(event.chat.id, text)
    except:
        pass

@dp.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_user_leave(event: ChatMemberUpdated):
    settings = get_group_settings(event.chat.id)
    if not settings or not settings['goodbye_enabled']:
        return
    text = settings['goodbye_text'].replace('{name}', event.old_chat_member.user.full_name)
    try:
        if settings['goodbye_media'] and settings['goodbye_media_type'] == 'photo':
            await bot.send_photo(event.chat.id, settings['goodbye_media'], caption=text)
        elif settings['goodbye_media'] and settings['goodbye_media_type'] == 'video':
            await bot.send_video(event.chat.id, settings['goodbye_media'], caption=text)
        else:
            await bot.send_message(event.chat.id, text)
    except:
        pass

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
        except:
            pass

# --------------------- РЕГИСТРАЦИЯ АДМИНА ---------------------
@dp.message(AdminRegistration.waiting_for_name)
async def register_admin(message: Message, state: FSMContext):
    name = message.text.strip()
    if not re.match(r'^[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z]\.$', name):
        await message.answer("❌ Формат: Иван З.")
        return
    save_admin_name(message.from_user.id, name)
    await state.clear()
    await message.answer(f"✅ Вы зарегистрированы как {name}", reply_markup=get_admin_main_menu())

@dp.message(Command("change_name"))
async def change_name_command(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Введите новое имя (Иван З.):", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminEditName.waiting_for_new_name)

@dp.message(AdminEditName.waiting_for_new_name)
async def change_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not re.match(r'^[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z]\.$', name):
        await message.answer("❌ Формат: Иван З.")
        return
    save_admin_name(message.from_user.id, name)
    await state.clear()
    await message.answer(f"✅ Имя изменено на {name}", reply_markup=get_admin_main_menu())

# --------------------- ОБРАБОТЧИКИ СОСТОЯНИЙ ---------------------
@dp.message(TicketStates.waiting_title)
async def handle_ticket_title(message: Message, state: FSMContext):
    title = message.text.strip()
    if len(title) < 5 or len(title) > 100:
        await message.answer("❌ От 5 до 100 символов")
        return
    data = await state.get_data()
    ticket_id = create_new_ticket(message.from_user, title, data.get('category', 'question'))
    custom_id = get_or_create_custom_id(message.from_user.id)
    await message.answer(f"✅ Обращение #{custom_id} создано!\nТема: {title}\nОпишите проблему:")
    await state.set_state(TicketStates.in_dialog)
    await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)

@dp.message(TriggerStates.waiting_for_trigger_response)
async def process_trigger_response(message: Message, state: FSMContext):
    data = await state.get_data()
    chat_id, word = data['chat_id'], data['trigger_word']
    if message.video and message.video.duration > MAX_VIDEO_DURATION:
        await message.answer(f"❌ Видео >{MAX_VIDEO_DURATION} сек")
        return
    rtype, content, caption = None, None, message.caption or message.text
    if message.text:
        rtype, content = 'text', message.text
    elif message.photo:
        rtype, content = 'photo', message.photo[-1].file_id
    elif message.video:
        rtype, content = 'video', message.video.file_id
    elif message.animation:
        rtype, content = 'animation', message.animation.file_id
    elif message.sticker:
        rtype, content, caption = 'sticker', message.sticker.file_id, None
    else:
        await message.answer("❌ Неподдерживаемый тип")
        return
    tid = add_trigger(chat_id, word, rtype, content, message.from_user.id, caption)
    await message.answer(f"✅ Триггер #{tid} создан!")
    await state.clear()

@dp.message(TicketStates.waiting_feedback)
async def handle_feedback(message: Message, state: FSMContext):
    data = await state.get_data()
    save_rating_and_feedback(data['ticket_id'], data['rating'], message.text, 
                           data.get('admin_id'), data.get('admin_name'),
                           data.get('user_id') or message.from_user.id, data.get('user_custom_id'))
    await message.answer("✅ Спасибо за отзыв!", reply_markup=get_user_main_menu())
    await state.clear()

# --------------------- ОБРАБОТКА СООБЩЕНИЙ ПОЛЬЗОВАТЕЛЯ ---------------------
@dp.message(F.chat.type == 'private')
async def handle_user_message(message: Message, state: FSMContext):
    if message.text and message.text.startswith('/'):
        return
    
    user = message.from_user
    current = await state.get_state()
    
    if current != TicketStates.in_dialog.state:
        if has_open_ticket(user.id):
            ot = get_open_ticket_info(user.id)
            if ot:
                await state.set_state(TicketStates.in_dialog)
                await state.update_data(ticket_id=ot[0], custom_id=ot[1], title=ot[2])
            else:
                await message.answer("❌ Начните через /start")
                return
        else:
            await message.answer("❌ Нет обращения. /start")
            return
    
    data = await state.get_data()
    ticket_id, custom_id, title = data.get('ticket_id'), data.get('custom_id'), data.get('title')
    
    if not ticket_id:
        ot = get_open_ticket_info(user.id)
        if ot:
            ticket_id, custom_id, title = ot[0], ot[1], ot[2]
            await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)
        else:
            await message.answer("❌ Ошибка", reply_markup=get_user_main_menu())
            await state.clear()
            return
    
    blocked, msg = check_spam_block(user.id)
    if blocked:
        await message.answer(msg)
        return
    
    if message.sticker or message.animation:
        await message.answer("❌ Только текст/фото/видео")
        return
    
    if message.media_group_id:
        media_groups_buffer[message.media_group_id].append(message)
        await asyncio.sleep(1)
        if message.media_group_id in media_groups_buffer:
            msgs = media_groups_buffer.pop(message.media_group_id)
            save_message(ticket_id, 'user', user.id, f"[Альбом]", user.first_name, message.media_group_id)
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, f"<b>#{custom_id}</b> {title}\nАльбом ({len(msgs)})", parse_mode=ParseMode.HTML)
                    media = []
                    for m in msgs:
                        if m.photo:
                            media.append(types.InputMediaPhoto(media=m.photo[-1].file_id))
                        elif m.video:
                            media.append(types.InputMediaVideo(media=m.video.file_id))
                    await bot.send_media_group(admin_id, media)
                except:
                    pass
            await message.answer(f"✅ Альбом отправлен в #{custom_id}", reply_markup=get_after_message_menu())
            update_message_time(user.id)
        return
    
    content, file_id, mtype, caption = None, None, None, None
    if message.text:
        content = message.text
        save_message(ticket_id, 'user', user.id, content, user.first_name)
    elif message.photo:
        file_id = message.photo[-1].file_id
        mtype, caption = 'photo', message.caption
        save_message(ticket_id, 'user', user.id, f"[Фото]", user.first_name, file_id=file_id, media_type=mtype, caption=caption)
        content = f"[Фото]"
    elif message.video:
        file_id = message.video.file_id
        mtype, caption = 'video', message.caption
        save_message(ticket_id, 'user', user.id, f"[Видео]", user.first_name, file_id=file_id, media_type=mtype, caption=caption)
        content = f"[Видео]"
    else:
        await message.answer("❌ Неподдерживаемый тип")
        return
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"<b>#{custom_id}</b> {title}\n{content}", parse_mode=ParseMode.HTML)
            await message.forward(admin_id)
        except:
            pass
    
    await message.answer(f"✅ Отправлено в #{custom_id}", reply_markup=get_after_message_menu())
    update_message_time(user.id)
    reset_has_responded(user.id)

# --------------------- ОТВЕТ АДМИНА ---------------------
@dp.message(lambda m: is_admin(m.from_user.id) and m.reply_to_message)
async def handle_admin_reply(message: Message):
    replied = message.reply_to_message
    user_id = None
    if replied.forward_from:
        user_id = replied.forward_from.id
    elif replied.text and "ID: <code>" in replied.text:
        import re
        m = re.search(r'ID: <code>(\d+)</code>', replied.text)
        if m:
            ui = get_user_by_custom_id(int(m.group(1)))
            user_id = ui[0] if ui else None
    if not user_id:
        await message.reply("❌ Не определен")
        return
    
    admin_name = get_admin_name(message.from_user.id)
    if not admin_name:
        await message.reply("❌ Зарегистрируйтесь")
        return
    
    conn = sqlite3.connect(DB_FILE, timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT id, custom_user_id FROM tickets WHERE user_id = ? AND status = 'open'", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        await message.reply("❌ Нет активного обращения")
        return
    
    ticket_id, custom_id = row
    try:
        if message.text:
            await bot.send_message(user_id, f"✉️ <b>Ответ от {admin_name}:</b>\n\n{message.text}", parse_mode=ParseMode.HTML)
            save_message(ticket_id, 'admin', message.from_user.id, message.text, admin_name)
        elif message.photo:
            await bot.send_photo(user_id, message.photo[-1].file_id, caption=f"✉️ <b>{admin_name}:</b>\n\n{message.caption or ''}", parse_mode=ParseMode.HTML)
            save_message(ticket_id, 'admin', message.from_user.id, f"[Фото]", admin_name)
        elif message.video:
            await bot.send_video(user_id, message.video.file_id, caption=f"✉️ <b>{admin_name}:</b>\n\n{message.caption or ''}", parse_mode=ParseMode.HTML)
            save_message(ticket_id, 'admin', message.from_user.id, f"[Видео]", admin_name)
        else:
            await message.reply("❌ Неподдерживаемый тип")
            return
        update_has_responded(user_id)
        await message.reply(f"✅ Ответ на #{custom_id} отправлен")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")

# --------------------- CALLBACK ---------------------
@dp.callback_query()
async def process_callback(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.answer()
    except:
        pass
    
    data, user = callback.data, callback.from_user
    
    if data == "menu:main":
        await state.clear()
        cid = get_or_create_custom_id(user.id)
        if is_admin(user.id):
            await callback.message.edit_text(f"🔧 Панель:\nID: <code>{cid}</code>", parse_mode=ParseMode.HTML, reply_markup=get_admin_main_menu())
        else:
            await callback.message.edit_text(f"🏠 Меню:\nID: <code>{cid}</code>", parse_mode=ParseMode.HTML, reply_markup=get_user_main_menu())
        return
    
    if data == "info:rules":
        await callback.message.answer(f"📜 Правила\n1. Вежливость\n2. Не спам\nСоздатель: {ADMIN_USERNAME}")
        return
    
    if data == "user:my_tickets":
        if is_admin(user.id):
            return
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT id, custom_user_id, title, status, created_at FROM tickets WHERE user_id = ? ORDER BY created_at DESC LIMIT 10", (user.id,))
        tickets = cursor.fetchall()
        conn.close()
        if not tickets:
            await callback.message.edit_text("📭 Нет обращений", reply_markup=InlineKeyboardBuilder().button(text="◀️", callback_data="menu:main").as_markup())
            return
        await callback.message.edit_text("📋 Ваши обращения:", reply_markup=get_user_tickets_keyboard(tickets))
        return
    
    if data.startswith("user:view_ticket_"):
        tid = int(data.split("_")[-1])
        msgs = get_ticket_messages(tid)
        text = f"<b>Обращение</b>\n"
        for m in msgs[:10]:
            text += f"{m[3][:16]} {m[0]}: {m[2][:50]}\n"
        await callback.message.answer(text, parse_mode=ParseMode.HTML)
        return
    
    if data == "support:start":
        if is_admin(user.id):
            return
        if check_blacklist(user.id):
            await callback.message.edit_text("⛔ Вы в ЧС")
            return
        if has_open_ticket(user.id):
            await callback.message.edit_text("❌ Уже есть открытое")
            return
        cd, rem = check_ticket_cooldown(user.id)
        if cd:
            await callback.message.edit_text(f"⏳ Подождите {rem//60} мин")
            return
        await callback.message.edit_text("📜 Правила...\nСогласны?", reply_markup=get_consent_keyboard())
        return
    
    if data == "consent:accept":
        save_consent(user.id)
        await callback.message.edit_text("Выберите категорию:", reply_markup=get_category_menu())
        return
    
    if data.startswith("category:"):
        cat = data.split(":")[1]
        await state.update_data(category=cat)
        await callback.message.edit_text("📝 Введите заголовок (2-5 слов):", reply_markup=get_cancel_keyboard())
        await state.set_state(TicketStates.waiting_title)
        return
    
    if data == "support:cancel":
        await state.clear()
        cid = get_or_create_custom_id(user.id)
        await callback.message.edit_text(f"❌ Отменено.\nID: <code>{cid}</code>", parse_mode=ParseMode.HTML, 
                                        reply_markup=get_user_main_menu() if not is_admin(user.id) else get_admin_main_menu())
        return
    
    if data == "group:cancel":
        await state.clear()
        await callback.message.edit_text("❌ Отменено", reply_markup=InlineKeyboardBuilder().button(text="◀️", callback_data="group:menu").as_markup())
        return
    
    if data == "support:continue":
        d = await state.get_data()
        if not d.get('ticket_id') or not has_open_ticket(user.id):
            ot = get_open_ticket_info(user.id)
            if ot:
                await state.update_data(ticket_id=ot[0], custom_id=ot[1], title=ot[2])
            else:
                await callback.message.edit_text("❌ Нет обращения")
                await state.clear()
                return
        await callback.message.edit_text(f"📝 Продолжайте...")
        return
    
    if data == "support:close":
        d = await state.get_data()
        if close_ticket(d['ticket_id'], user.id, "Пользователь"):
            await callback.message.edit_text(f"✅ Обращение #{d['custom_id']} закрыто.\nОцените:", reply_markup=get_rating_keyboard(d['ticket_id']))
        else:
            await callback.message.edit_text("❌ Ошибка")
        return
    
    if data.startswith("rate:"):
        parts = data.split(":")
        if len(parts) >= 4:
            rating, tid, aid = int(parts[1]), int(parts[2]), int(parts[3]) if parts[3] != '0' else None
            conn = sqlite3.connect(DB_FILE, timeout=10)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, custom_user_id, closed_by, closed_by_name FROM tickets WHERE id = ?", (tid,))
            ti = cursor.fetchone()
            conn.close()
            if ti:
                await state.update_data(ticket_id=tid, rating=rating, admin_id=aid or ti[2], 
                                       admin_name=get_admin_name(aid) if aid else ti[3],
                                       user_id=ti[0], user_custom_id=ti[1])
                await callback.message.edit_text("✅ Спасибо! Напишите отзыв или /start")
                await state.set_state(TicketStates.waiting_feedback)
            else:
                await callback.message.edit_text("✅ Спасибо!")
        return
    
    if data == "admin:open_tickets":
        if not is_admin(user.id):
            return
        tickets = get_all_open_tickets()
        if not tickets:
            await callback.message.answer("📭 Нет открытых")
            return
        text = "📂 Открытые:\n"
        b = InlineKeyboardBuilder()
        for t in tickets[:10]:
            text += f"#{t[1]} {t[3][:10]}...\n"
            b.button(text=f"#{t[1]}", callback_data=f"admin:view_ticket_{t[0]}")
        b.button(text="◀️", callback_data="menu:main")
        b.adjust(4)
        await callback.message.answer(text, reply_markup=b.as_markup())
        return
    
    if data.startswith("admin:view_ticket_"):
        tid = int(data.split("_")[-1])
        msgs = get_ticket_messages(tid)
        text = f"<b>Тикет</b>\n"
        for m in msgs[-10:]:
            text += f"{m[3][:16]} {m[0]}: {m[2][:50]}\n"
        await callback.message.answer(text, parse_mode=ParseMode.HTML)
        return
    
    if data == "admin:profile":
        if not is_admin(user.id):
            return
        p = get_admin_profile(user.id)
        await callback.message.answer(f"👤 {p['name']}\n⭐️ {p['avg_rating']}/5\n💬 {p['total_replies']}", 
                                     reply_markup=InlineKeyboardBuilder().button(text="⭐️ Отзывы", callback_data="admin:my_reviews").button(text="◀️", callback_data="menu:main").as_markup())
        return
    
    if data == "admin:my_reviews":
        if not is_admin(user.id):
            return
        revs = get_admin_reviews(user.id)
        if not revs:
            await callback.message.answer("📭 Нет отзывов")
            return
        text = "⭐️ Отзывы:\n"
        for r in revs[:5]:
            text += f"{'⭐️'*r[0]} от #{r[3]}: {r[1] or 'без текста'}\n"
        await callback.message.answer(text)
        return
    
    if data == "group:rules":
        await callback.message.answer(f"📜 Правила чата\nСоздатель: {ADMIN_USERNAME}")
        return
    
    if data == "group:menu":
        await callback.message.edit_text("👋 Меню группы", reply_markup=get_group_main_menu())
        return
    
    if data == "trigger:add":
        if not is_chat_creator(user.id, callback.message.chat.id):
            return
        await callback.message.edit_text("🔤 Введите слово-триггер:", reply_markup=get_cancel_keyboard(for_group=True))
        await state.set_state(TriggerStates.waiting_for_trigger_word)
        await state.update_data(chat_id=callback.message.chat.id)
        return
    
    if data.startswith("trigger:info:"):
        tid = int(data.split(":")[2])
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT trigger_word, response_type, use_count FROM triggers WHERE id = ?", (tid,))
        r = cursor.fetchone()
        conn.close()
        if r:
            await callback.message.answer(f"🔤 {r[0]}\nТип: {r[1]}\nИспользован: {r[2]}")
        return
    
    if data == "welcome:default":
        reset_welcome_to_default((await state.get_data())['chat_id'])
        await callback.message.edit_text("✅ По умолчанию")
        await state.clear()
        return
    
    if data == "welcome:disable":
        update_group_settings((await state.get_data())['chat_id'], welcome_enabled=0)
        await callback.message.edit_text("🔴 Отключено")
        await state.clear()
        return
    
    if data == "welcome:cancel" or data == "goodbye:cancel":
        await state.clear()
        await callback.message.edit_text("❌ Отменено")
        return
    
    if data == "goodbye:default":
        reset_goodbye_to_default((await state.get_data())['chat_id'])
        await callback.message.edit_text("✅ По умолчанию")
        await state.clear()
        return
    
    if data == "goodbye:disable":
        update_group_settings((await state.get_data())['chat_id'], goodbye_enabled=0)
        await callback.message.edit_text("🔴 Отключено")
        await state.clear()
        return
    
    if data.startswith("close:"):
        parts = data.split(":")
        if len(parts) == 4 and is_admin(user.id):
            _, tid, uid, cid = parts
            if close_ticket(int(tid), user.id, get_admin_name(user.id)):
                await callback.message.edit_text(f"✅ #{cid} закрыто")
                try:
                    await bot.send_message(int(uid), f"🔒 #{cid} закрыто админом.\nОцените:", reply_markup=get_rating_keyboard(int(tid), user.id))
                except:
                    pass
            else:
                await callback.message.edit_text("❌ Ошибка")
        return

# --------------------- ЗАПУСК ---------------------
async def main():
    logging.info(f"Бот {BOT_USERNAME} запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен")
