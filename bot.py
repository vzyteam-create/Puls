import aiohttp
import asyncio
import logging
import sqlite3
import re
import json
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from collections import defaultdict

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode, ContentType
from aiogram.exceptions import TelegramBadRequest
from aiogram.client.session.aiohttp import AiohttpSession

# --------------------- НАСТРОЙКИ ---------------------
BOT_TOKEN = "8533732699:AAH_iSLnJnHI0-ROJE8fwqAxKQPeRbo_Lck"  # ← @PulsSupportBot
BOT_USERNAME = "@PulsSupportBot"  # Юзернейм основного бота
ADMIN_IDS = [6708209142, 8475965198]  # ← твои ID
MAIN_BOT_USERNAME = "@PulsOfficialManager_bot"
DB_FILE = "tickets.db"

# Настройки анти-спама
TICKET_COOLDOWN = 300  # 5 минут между новыми обращениями (в секундах)
SPAM_LIMIT = 5  # сообщений без ответа
SPAM_BLOCK_TIME = 600  # 10 минут в секундах
TICKET_AUTO_CLOSE_HOURS = 48  # часов без активности

# Счетчик для ID пользователей (начинаем со 100)
USER_ID_COUNTER = 100

# --------------------- БАЗА ДАННЫХ ---------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Таблица пользователей с ID
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
    
    # Таблица для отзывов о поддержке
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
    
    # Таблица админов поддержки
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
    
    # Таблица для альбомов (медиа групп)
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
    
    # Таблица для согласия с правилами
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_consent (
            user_id INTEGER PRIMARY KEY,
            consented_at TEXT NOT NULL,
            bot_token TEXT DEFAULT 'main'
        )
    ''')
    
    # Таблица для черного списка
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blacklist (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            blocked_at TEXT NOT NULL,
            blocked_by INTEGER,
            bot_token TEXT DEFAULT 'main'
        )
    ''')
    
    # Таблица для клонов ботов
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
    
    # Индексы
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_custom_id ON tickets(custom_user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_title ON tickets(title)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_ticket_id ON messages(ticket_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_media_groups_group_id ON media_groups(group_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_admin_reviews_admin ON admin_reviews(admin_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_clone_bots_owner ON clone_bots(owner_id)')
    
    conn.commit()
    conn.close()

init_db()

# --------------------- ХРАНИЛИЩЕ АКТИВНЫХ БОТОВ ---------------------
active_bots = {}  # token: (bot, dp, bot_info)
bot_sessions = {}  # token: session

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

# --------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---------------------
def get_or_create_custom_id(user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> int:
    """Получение или создание пользовательского ID (начиная со 100)"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT custom_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row:
        custom_id = row[0]
        # Обновляем информацию
        cursor.execute("""
            UPDATE users SET username = ?, first_name = ?, last_name = ?, last_activity = ? 
            WHERE user_id = ?
        """, (username, first_name, last_name, datetime.utcnow().isoformat(), user_id))
    else:
        # Получаем максимальный custom_id
        cursor.execute("SELECT MAX(custom_id) FROM users")
        max_id = cursor.fetchone()[0]
        if max_id and max_id >= USER_ID_COUNTER:
            custom_id = max_id + 1
        else:
            custom_id = USER_ID_COUNTER
        
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            INSERT INTO users (user_id, custom_id, username, first_name, last_name, registered_at, last_activity)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, custom_id, username, first_name, last_name, now, now))
    
    conn.commit()
    conn.close()
    return custom_id

def check_ticket_cooldown(user_id: int, bot_token: str = 'main') -> tuple[bool, Optional[int]]:
    """Проверка кулдауна на создание нового обращения"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT created_at FROM tickets 
        WHERE user_id = ? AND bot_token = ? 
        ORDER BY created_at DESC LIMIT 1
    """, (user_id, bot_token))
    
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0]:
        last_ticket_time = datetime.fromisoformat(row[0])
        diff = datetime.utcnow() - last_ticket_time
        if diff.total_seconds() < TICKET_COOLDOWN:
            remaining = int(TICKET_COOLDOWN - diff.total_seconds())
            return True, remaining
    
    return False, None

def has_open_ticket(user_id: int, bot_token: str = 'main') -> bool:
    """Проверка наличия открытого тикета"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM tickets WHERE user_id = ? AND bot_token = ? AND status = 'open'", 
                  (user_id, bot_token))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def get_open_ticket_id(user_id: int, bot_token: str = 'main') -> Optional[int]:
    """Получение ID открытого тикета"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM tickets WHERE user_id = ? AND bot_token = ? AND status = 'open'", 
                  (user_id, bot_token))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def get_open_ticket_info(user_id: int, bot_token: str = 'main') -> Optional[tuple]:
    """Получение информации об открытом тикете"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, custom_user_id, title, category, created_at, has_responded 
        FROM tickets 
        WHERE user_id = ? AND bot_token = ? AND status = 'open'
    """, (user_id, bot_token))
    row = cursor.fetchone()
    conn.close()
    return row if row else None

def has_consent(user_id: int, bot_token: str = 'main') -> bool:
    """Проверка согласия с правилами"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT consented_at FROM user_consent WHERE user_id = ? AND bot_token = ?", 
                  (user_id, bot_token))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def save_consent(user_id: int, bot_token: str = 'main'):
    """Сохранение согласия с правилами"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO user_consent (user_id, consented_at, bot_token)
        VALUES (?, ?, ?)
    """, (user_id, now, bot_token))
    conn.commit()
    conn.close()

def is_admin(user_id: int, bot_token: str = 'main') -> bool:
    """Проверка, является ли пользователь админом"""
    if bot_token == 'main':
        return user_id in ADMIN_IDS
    else:
        # Для клонов проверяем по списку админов
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT admins FROM clone_bots WHERE token = ?", (bot_token,))
        row = cursor.fetchone()
        conn.close()
        if row:
            admins = json.loads(row[0])
            return user_id in admins
    return False

def get_admin_name(user_id: int, bot_token: str = 'main') -> Optional[str]:
    """Получение имени админа по ID"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT display_name FROM support_admins WHERE user_id = ? AND bot_token = ?", 
                  (user_id, bot_token))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def save_admin_name(user_id: int, display_name: str, bot_token: str = 'main'):
    """Сохранение имени админа"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO support_admins (user_id, display_name, registered_at, last_active, bot_token)
        VALUES (?, ?, COALESCE((SELECT registered_at FROM support_admins WHERE user_id = ? AND bot_token = ?), ?), ?, ?)
    """, (user_id, display_name, user_id, bot_token, now, now, bot_token))
    conn.commit()
    conn.close()

def update_admin_activity(user_id: int, bot_token: str = 'main'):
    """Обновление времени последней активности админа"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        UPDATE support_admins 
        SET last_active = ?, total_replies = total_replies + 1 
        WHERE user_id = ? AND bot_token = ?
    """, (now, user_id, bot_token))
    conn.commit()
    conn.close()

def add_admin_review(admin_id: int, admin_name: str, ticket_id: int, user_id: int, 
                     user_custom_id: int, rating: int, feedback: str = None, bot_token: str = 'main'):
    """Добавление отзыва о работе админа"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        INSERT INTO admin_reviews (admin_id, admin_name, ticket_id, user_id, user_custom_id, rating, feedback, created_at, bot_token)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (admin_id, admin_name, ticket_id, user_id, user_custom_id, rating, feedback, now, bot_token))
    
    # Обновляем статистику админа
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

def get_admin_reviews(admin_id: int, bot_token: str = 'main', limit: int = 10) -> List:
    """Получение отзывов о работе админа"""
    conn = sqlite3.connect(DB_FILE)
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

def create_new_ticket(user: types.User, title: str, category: str = 'question', bot_token: str = 'main') -> int:
    """Создание нового тикета с заголовком"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    custom_id = get_or_create_custom_id(user.id, user.username, user.first_name, user.last_name)
    
    # Закрываем старые открытые тикеты (на всякий случай)
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
    
    # Уведомление админов о новом тикете
    asyncio.create_task(notify_admins_new_ticket(user, ticket_id, custom_id, title, category, bot_token))
    
    return ticket_id

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
    
    # Получаем список админов для этого бота
    if bot_token == 'main':
        admin_ids = ADMIN_IDS
    else:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT admins FROM clone_bots WHERE token = ?", (bot_token,))
        row = cursor.fetchone()
        admin_ids = json.loads(row[0]) if row else []
        conn.close()
    
    for admin_id in admin_ids:
        try:
            if bot_token == 'main':
                await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
            else:
                clone_bot, _, _ = active_bots.get(bot_token, (None, None, None))
                if clone_bot:
                    await clone_bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.error(f"Ошибка уведомления админа {admin_id} для бота {bot_token}: {e}")

def check_spam_block(user_id: int, bot_token: str = 'main') -> tuple[bool, Optional[str]]:
    """Проверка на спам-блок"""
    conn = sqlite3.connect(DB_FILE)
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

def check_message_limit(user_id: int, bot_token: str = 'main') -> tuple[bool, Optional[str]]:
    """Проверка лимита сообщений без ответа"""
    conn = sqlite3.connect(DB_FILE)
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
        # Блокируем пользователя
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

def update_message_time(user_id: int, bot_token: str = 'main'):
    """Обновление времени последнего сообщения"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        UPDATE tickets SET last_message_at = ? 
        WHERE user_id = ? AND bot_token = ? AND status = 'open'
    """, (now, user_id, bot_token))
    conn.commit()
    conn.close()

def get_ticket_by_custom_id(custom_id: int, bot_token: str = 'main') -> Optional[tuple]:
    """Получение тикета по пользовательскому ID"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, user_id, status, title, category, created_at 
        FROM tickets 
        WHERE custom_user_id = ? AND bot_token = ? AND status = 'open'
    """, (custom_id, bot_token))
    row = cursor.fetchone()
    conn.close()
    return row if row else None

def get_user_by_custom_id(custom_id: int, bot_token: str = 'main') -> Optional[tuple]:
    """Получение пользователя по пользовательскому ID"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name FROM users WHERE custom_id = ?", (custom_id,))
    row = cursor.fetchone()
    conn.close()
    return row if row else None

def update_has_responded(user_id: int, bot_token: str = 'main'):
    """Обновление флага ответа админа"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE tickets SET has_responded = 1 
        WHERE user_id = ? AND bot_token = ? AND status = 'open'
    """, (user_id, bot_token))
    conn.commit()
    conn.close()

def reset_has_responded(user_id: int, bot_token: str = 'main'):
    """Сброс флага ответа админа"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE tickets SET has_responded = 0 
        WHERE user_id = ? AND bot_token = ? AND status = 'open'
    """, (user_id, bot_token))
    conn.commit()
    conn.close()

def save_message(ticket_id: int, sender_type: str, sender_id: int, content: str, 
                 sender_name: str = None, media_group_id: str = None, 
                 file_id: str = None, media_type: str = None, caption: str = None,
                 bot_token: str = 'main'):
    """Сохранение сообщения в БД"""
    conn = sqlite3.connect(DB_FILE)
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

def save_media_group(group_id: str, ticket_id: int, message_id: int, file_id: str, 
                     media_type: str, caption: str = None, bot_token: str = 'main'):
    """Сохранение медиа группы в БД"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute('''
        INSERT OR REPLACE INTO media_groups (group_id, ticket_id, message_id, file_id, media_type, caption, timestamp, bot_token)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (group_id, ticket_id, message_id, file_id, media_type, caption, now, bot_token))
    conn.commit()
    conn.close()

def get_media_group(group_id: str, bot_token: str = 'main') -> List[tuple]:
    """Получение всех медиа из группы"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT file_id, media_type, caption FROM media_groups 
        WHERE group_id = ? AND bot_token = ? ORDER BY message_id ASC
    ''', (group_id, bot_token))
    rows = cursor.fetchall()
    conn.close()
    return rows

def close_ticket(ticket_id: int, closed_by: int, closed_by_name: str = None, bot_token: str = 'main') -> bool:
    """Закрытие тикета"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        UPDATE tickets 
        SET status = 'closed', closed_at = ?, closed_by = ?, closed_by_name = ? 
        WHERE id = ? AND status = 'open' AND bot_token = ?
    """, (now, closed_by, closed_by_name, ticket_id, bot_token))
    success = cursor.rowcount > 0
    
    if success:
        # Обновляем счетчик закрытых тикетов у админа
        cursor.execute("""
            UPDATE support_admins 
            SET total_closed = total_closed + 1 
            WHERE user_id = ? AND bot_token = ?
        """, (closed_by, bot_token))
    
    conn.commit()
    conn.close()
    return success

def save_rating_and_feedback(ticket_id: int, rating: int, feedback: str = None, 
                            admin_id: int = None, admin_name: str = None, 
                            user_id: int = None, user_custom_id: int = None,
                            bot_token: str = 'main'):
    """Сохранение оценки и отзыва, включая информацию об админе"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Обновляем тикет
    cursor.execute("""
        UPDATE tickets SET rating = ?, feedback_text = ? 
        WHERE id = ? AND bot_token = ?
    """, (rating, feedback, ticket_id, bot_token))
    
    # Если есть информация об админе, добавляем отзыв
    if admin_id and user_id:
        add_admin_review(admin_id, admin_name, ticket_id, user_id, user_custom_id, rating, feedback, bot_token)
    
    conn.commit()
    conn.close()

def get_ticket_messages(ticket_id: int, bot_token: str = 'main') -> List:
    """Получение всех сообщений тикета"""
    conn = sqlite3.connect(DB_FILE)
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

def get_all_open_tickets(bot_token: str = 'main') -> List:
    """Получение всех открытых тикетов"""
    conn = sqlite3.connect(DB_FILE)
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

def get_admin_tickets(admin_id: int, bot_token: str = 'main') -> List:
    """Получение тикетов, в которых участвовал админ"""
    conn = sqlite3.connect(DB_FILE)
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

def search_tickets(query: str, bot_token: str = 'main') -> List:
    """Поиск по тикетам (по заголовку и сообщениям)"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Ищем по заголовку
    cursor.execute("""
        SELECT id, custom_user_id, username, first_name, title, created_at
        FROM tickets
        WHERE title LIKE ? AND bot_token = ?
        ORDER BY created_at DESC
        LIMIT 20
    """, (f"%{query}%", bot_token))
    by_title = cursor.fetchall()
    
    # Ищем по сообщениям
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
    
    # Объединяем и убираем дубликаты
    seen = set()
    results = []
    for r in by_title + by_message:
        if r[0] not in seen:
            seen.add(r[0])
            results.append(r)
    
    return results[:20]

def get_admin_profile(admin_id: int, bot_token: str = 'main') -> Dict[str, Any]:
    """Получение полного профиля админа со статистикой и отзывами"""
    name = get_admin_name(admin_id, bot_token)
    
    conn = sqlite3.connect(DB_FILE)
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
    
    # Получаем отзывы
    reviews = get_admin_reviews(admin_id, bot_token)
    for r in reviews:
        rating, feedback, created_at, user_custom_id, ticket_id = r
        profile['reviews'].append({
            'rating': rating,
            'feedback': feedback,
            'date': datetime.fromisoformat(created_at).strftime('%d.%m.%Y %H:%M'),
            'user_id': user_custom_id,
            'ticket_id': ticket_id
        })
    
    conn.close()
    return profile

def get_statistics(bot_token: str = 'main') -> Dict[str, Any]:
    """Получение статистики поддержки"""
    conn = sqlite3.connect(DB_FILE)
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
    
    # Статистика по дням (последние 7 дней)
    stats['daily'] = []
    for i in range(6, -1, -1):
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
    
    # Топ администраторов по рейтингу
    cursor.execute("""
        SELECT display_name, total_replies, avg_rating, total_ratings
        FROM support_admins 
        WHERE bot_token = ? AND total_ratings > 0
        ORDER BY avg_rating DESC, total_ratings DESC
        LIMIT 5
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

def add_to_blacklist(user_id: int, reason: str, blocked_by: int, bot_token: str = 'main'):
    """Добавление пользователя в черный список"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO blacklist (user_id, reason, blocked_at, blocked_by, bot_token)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, reason, now, blocked_by, bot_token))
    
    # Закрываем все открытые тикеты
    cursor.execute("""
        UPDATE tickets SET status = 'closed', closed_at = ? 
        WHERE user_id = ? AND bot_token = ? AND status = 'open'
    """, (now, user_id, bot_token))
    
    conn.commit()
    conn.close()

def check_blacklist(user_id: int, bot_token: str = 'main') -> bool:
    """Проверка, находится ли пользователь в черном списке"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT reason FROM blacklist WHERE user_id = ? AND bot_token = ?", (user_id, bot_token))
    row = cursor.fetchone()
    conn.close()
    return row is not None

# --------------------- ФУНКЦИИ ДЛЯ КЛОНОВ БОТОВ ---------------------
def verify_bot_token(token: str) -> tuple[bool, Optional[str], Optional[str]]:
    """Проверка валидности токена бота через Telegram API"""
    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/getMe")
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
        # Создаем сессию и бота
        session = AiohttpSession()
        bot = Bot(token=token, session=session)
        dp = Dispatcher(storage=MemoryStorage())
        
        # Получаем информацию о боте
        bot_info = await bot.get_me()
        
        # Регистрируем обработчики для клона
        register_clone_handlers(dp, token)
        
        # Запускаем polling
        asyncio.create_task(dp.start_polling(bot))
        
        # Сохраняем в активные боты
        active_bots[token] = (bot, dp, bot_info)
        bot_sessions[token] = session
        
        logging.info(f"Клон бота @{bot_info.username} успешно запущен")
        return True
    except Exception as e:
        logging.error(f"Ошибка запуска клона бота {token}: {e}")
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
    """Сохранение информации о клоне бота"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO clone_bots (token, owner_id, bot_username, bot_name, created_at, last_active, status, admins)
        VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
    """, (token, owner_id, bot_username, bot_name, now, now, json.dumps(admins)))
    conn.commit()
    conn.close()

def get_clone_bots(owner_id: int) -> List:
    """Получение всех клонов ботов пользователя"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT token, bot_username, bot_name, created_at, status FROM clone_bots WHERE owner_id = ?", 
                  (owner_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def delete_clone_bot(token: str):
    """Удаление клона бота"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM clone_bots WHERE token = ?", (token,))
    conn.commit()
    conn.close()

def update_clone_bot_admins(token: str, admins: List[int]):
    """Обновление списка админов для клона бота"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE clone_bots SET admins = ? WHERE token = ?", 
                  (json.dumps(admins), token))
    conn.commit()
    conn.close()

def get_bot_display_info(bot_token: str = 'main') -> Dict[str, str]:
    """Получение информации о боте для отображения"""
    if bot_token == 'main':
        return {
            'name': 'Основной бот',
            'username': BOT_USERNAME,
            'type': 'main'
        }
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT bot_username, bot_name FROM clone_bots WHERE token = ?", (bot_token,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        username, name = row
        return {
            'name': name or 'Клон бота',
            'username': f'@{username}' if username else 'неизвестно',
            'type': 'clone'
        }
    
    return {
        'name': 'Неизвестный бот',
        'username': 'неизвестно',
        'type': 'unknown'
    }

def format_bot_header(bot_token: str = 'main') -> str:
    """Форматирование заголовка с информацией о боте"""
    info = get_bot_display_info(bot_token)
    
    if info['type'] == 'main':
        return f"🤖 <b>Основной бот поддержки</b>\n└ {info['username']}\n\n"
    else:
        created_info = ""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT created_at FROM clone_bots WHERE token = ?", (bot_token,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            created_date = datetime.fromisoformat(row[0]).strftime('%d.%m.%Y')
            created_info = f"📅 Создан: {created_date}\n"
        
        return (f"🤖 <b>Бот поддержки</b>\n"
                f"└ {info['username']}\n"
                f"{created_info}")

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

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены"""
    builder = InlineKeyboardBuilder()
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

def get_user_tickets_keyboard(tickets: List, page: int = 0) -> InlineKeyboardMarkup:
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

# --------------------- ИНИЦИАЛИЗАЦИЯ ---------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Словарь для временного хранения альбомов
media_groups_buffer: Dict[str, List[Message]] = defaultdict(list)

# --------------------- КОМАНДЫ ---------------------
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработка команды /start"""
    if message.chat.type != 'private':
        await message.answer(
            f"👋 Привет! Для обращений пиши мне в личные сообщения: {BOT_USERNAME}"
        )
        return

    user = message.from_user
    bot_token = 'main'
    
    # Проверяем черный список
    if check_blacklist(user.id):
        await message.answer(
            "⛔ Вы находитесь в черном списке и не можете использовать поддержку.\n"
            "Для вопросов обратитесь к @PulsOfficialManager_bot"
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
                f"Ваш персональный ID: <code>{custom_id}</code>\n\n"
                f"Выберите действие:",
                parse_mode=ParseMode.HTML,
                reply_markup=get_user_main_menu(bot_token)
            )
        await state.clear()

@dp.message(Command("reply"))
async def reply_command(message: Message):
    """Быстрый ответ на обращение по ID"""
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
    
    # Получаем информацию по пользовательскому ID
    ticket_info = get_ticket_by_custom_id(custom_id)
    
    if not ticket_info:
        await message.answer(f"❌ Обращение с ID {custom_id} не найдено или уже закрыто")
        return
    
    ticket_id, user_id, status, title, category, created_at = ticket_info
    admin_name = get_admin_name(message.from_user.id)
    
    if not admin_name:
        await message.answer("❌ Вы не зарегистрированы. Используйте /start для регистрации.")
        return
    
    # Получаем информацию о пользователе
    user_info = get_user_by_custom_id(custom_id)
    if user_info:
        user_id, username, first_name = user_info
    
    try:
        # Отправляем ответ
        await bot.send_message(
            user_id, 
            f"✉️ <b>Ответ от {admin_name}:</b>\n\n{reply_text}",
            parse_mode=ParseMode.HTML
        )
        
        # Сохраняем в БД
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
    """Поиск по обращениям"""
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
        if len(r) == 6:  # По заголовку
            ticket_id, custom_id, username, first_name, title, timestamp = r
            time_str = datetime.fromisoformat(timestamp).strftime("%d.%m %H:%M")
            text += f"#{custom_id} - {first_name} (@{username or 'нет'}) [{time_str}]\n📝 {title}\n\n"
        else:  # По сообщению
            ticket_id, custom_id, username, first_name, title, timestamp = r
            time_str = datetime.fromisoformat(timestamp).strftime("%d.%m %H:%M")
            text += f"#{custom_id} - {first_name} (@{username or 'нет'}) [{time_str}]\n📝 {title}\n\n"
        
        builder.button(text=f"#{custom_id}", callback_data=f"admin:view_ticket_{ticket_id}")
    
    builder.button(text="◀️ Назад", callback_data="menu:main")
    builder.adjust(4)
    
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())

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

# --------------------- ИЗМЕНЕНИЕ ИМЕНИ АДМИНА ---------------------
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

# --------------------- ОБРАБОТКА CALLBACK ---------------------
@dp.callback_query()
async def process_callback(callback: CallbackQuery, state: FSMContext):
    """Обработка callback-запросов"""
    data = callback.data
    user = callback.from_user
    bot_token = 'main'
    
    # Главное меню
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
        await callback.answer()
        return
    
    # Правила
    if data == "info:rules":
        rules_text = (
            f"📜 <b>Правила работы с поддержкой {BOT_USERNAME}</b>\n\n"
            "1️⃣ <b>Вежливость</b> - будьте уважительны к операторам\n"
            "2️⃣ <b>Подробности</b> - описывайте проблему максимально подробно\n"
            "3️⃣ <b>Заголовок</b> - указывайте краткую суть обращения\n"
            "4️⃣ <b>Без спама</b> - не отправляйте одинаковые сообщения (блокировка 10 мин)\n"
            "5️⃣ <b>Одна тема</b> - одно обращение = одна проблема\n"
            "6️⃣ <b>Ожидание</b> - ответ может занять до 24 часов в рабочие дни\n"
            "7️⃣ <b>Без стикеров</b> - только текст и фото/видео по теме\n"
            "8️⃣ <b>Закрытие</b> - после закрытия нельзя открыть снова\n"
            "9️⃣ <b>Перерыв</b> - между обращениями 5 минут\n\n"
            "❌ Нарушение правил ведёт к блокировке!"
        )
        await callback.message.answer(
            rules_text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="menu:main")
                .as_markup()
        )
        await callback.answer()
        return
    
    # Мои обращения (для пользователя)
    if data == "user:my_tickets":
        if is_admin(user.id):
            await callback.answer("Эта функция только для пользователей")
            return
        
        conn = sqlite3.connect(DB_FILE)
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
        
        if not tickets:
            await callback.message.edit_text(
                "📭 У вас пока нет обращений в поддержку.",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data="menu:main")
                    .as_markup()
            )
            await callback.answer()
            return
        
        await callback.message.edit_text(
            "📋 <b>Ваши последние обращения:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_user_tickets_keyboard(tickets)
        )
        await callback.answer()
        return
    
    # Просмотр конкретного обращения пользователем
    if data.startswith("user:view_ticket_"):
        ticket_id = int(data.split("_")[-1])
        messages = get_ticket_messages(ticket_id)
        
        # Получаем информацию о тикете
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT custom_user_id, title, category, status, created_at, closed_at, rating
            FROM tickets WHERE id = ?
        """, (ticket_id,))
        ticket_info = cursor.fetchone()
        conn.close()
        
        if not ticket_info:
            await callback.message.answer("❌ Обращение не найдено")
            await callback.answer()
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
            for msg in messages[:20]:  # Показываем последние 20 сообщений
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
        await callback.answer()
        return
    
    # Начало обращения
    if data == "support:start":
        if is_admin(user.id):
            await callback.answer("Админы не могут создавать обращения")
            return
        
        # Проверяем черный список
        if check_blacklist(user.id):
            await callback.message.edit_text(
                "⛔ Вы находитесь в черном списке и не можете создавать обращения.",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data="menu:main")
                    .as_markup()
            )
            await callback.answer()
            return
        
        # Проверяем, есть ли уже открытое обращение
        if has_open_ticket(user.id):
            ticket_info = get_open_ticket_info(user.id)
            if ticket_info:
                ticket_id, custom_id, title, category, created_at, _ = ticket_info
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
            await callback.answer()
            return
        
        # Проверяем кулдаун на создание нового обращения
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
            await callback.answer()
            return
        
        # Показываем правила для согласия
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
        await callback.answer()
        return
    
    # Согласие с правилами
    if data == "consent:accept":
        save_consent(user.id)
        await callback.message.edit_text(
            "✅ Спасибо! Теперь выберите категорию обращения:",
            reply_markup=get_category_menu()
        )
        await callback.answer()
        return
    
    # Категории
    if data.startswith("category:"):
        category = data.split(":")[1]
        await state.update_data(category=category)
        await callback.message.edit_text(
            "📝 Введите краткий заголовок обращения (2-5 слов):\n\n"
            "Пример: Проблема с оплатой\n"
            "Или: Вопрос по функционалу",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(TicketStates.waiting_title)
        await callback.answer()
        return
    
    # Отмена
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
        await callback.answer()
        return
    
    # Продолжить диалог
    if data == "support:continue":
        data_state = await state.get_data()
        ticket_id = data_state.get('ticket_id')
        custom_id = data_state.get('custom_id')
        title = data_state.get('title')
        
        if not ticket_id or not has_open_ticket(user.id):
            # Пробуем найти открытый тикет
            open_ticket = get_open_ticket_info(user.id)
            if open_ticket:
                ticket_id, custom_id, title, _, _, _ = open_ticket
                await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)
            else:
                await callback.message.edit_text(
                    "❌ Ошибка: обращение не найдено.\n"
                    "Начните новое обращение.",
                    reply_markup=get_user_main_menu(bot_token)
                )
                await state.clear()
                await callback.answer()
                return
        
        await callback.message.edit_text(
            f"📝 Продолжайте диалог по обращению #{custom_id}\n"
            f"Тема: {title}\n\n"
            f"Отправьте сообщение (текст, фото, видео):",
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return
    
    # Закрыть обращение (по желанию пользователя)
    if data == "support:close":
        data_state = await state.get_data()
        ticket_id = data_state.get('ticket_id')
        custom_id = data_state.get('custom_id')
        
        # Получаем информацию об админе, который последним отвечал
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sender_id, sender_name FROM messages 
            WHERE ticket_id = ? AND sender_type = 'admin' 
            ORDER BY timestamp DESC LIMIT 1
        """, (ticket_id,))
        last_admin = cursor.fetchone()
        conn.close()
        
        admin_id = last_admin[0] if last_admin else None
        admin_name = last_admin[1] if last_admin else None
        
        if ticket_id and close_ticket(ticket_id, user.id, "Пользователь"):
            await callback.message.edit_text(
                f"✅ Обращение #{custom_id} закрыто.\n\n"
                f"Оцените качество поддержки (это поможет нам стать лучше):",
                reply_markup=get_rating_keyboard(ticket_id, admin_id)
            )
        else:
            await callback.message.edit_text(
                "❌ Не удалось закрыть обращение. Возможно, оно уже закрыто.",
                reply_markup=get_user_main_menu(bot_token)
            )
            await state.clear()
        
        await callback.answer()
        return
    
    # Оценка
    if data.startswith("rate:"):
        parts = data.split(":")
        if len(parts) >= 4:
            _, rating, ticket_id, admin_id = parts[:4]
            rating = int(rating)
            ticket_id = int(ticket_id)
            admin_id = int(admin_id) if admin_id != '0' else None
            
            # Получаем информацию о пользователе и тикете
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT user_id, custom_user_id, closed_by, closed_by_name 
                FROM tickets WHERE id = ?
            """, (ticket_id,))
            ticket_info = cursor.fetchone()
            conn.close()
            
            if ticket_info:
                user_id, user_custom_id, closed_by, closed_by_name = ticket_info
                
                # Если admin_id не передан, используем closed_by
                if not admin_id and closed_by:
                    admin_id = closed_by
                    admin_name = closed_by_name
                else:
                    admin_name = get_admin_name(admin_id) if admin_id else None
                
                # Сохраняем оценку и отзыв
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
            else:
                await callback.message.edit_text(
                    f"✅ Спасибо за вашу оценку: {'⭐️' * rating}!\n\n"
                    f"Отправьте /start для возврата в меню."
                )
        
        await callback.answer()
        return
    
    # Админ: открытые обращения
    if data == "admin:open_tickets":
        if not is_admin(user.id):
            await callback.answer("Нет доступа")
            return
        
        tickets = get_all_open_tickets()
        if not tickets:
            await callback.message.answer(
                f"📭 Нет открытых обращений",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data="menu:main")
                    .as_markup()
            )
            await callback.answer()
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
        await callback.answer()
        return
    
    # Админ: моя история
    if data == "admin:my_history":
        if not is_admin(user.id):
            await callback.answer("Нет доступа")
            return
        
        tickets = get_admin_tickets(user.id)
        if not tickets:
            await callback.message.answer(
                f"📭 У вас пока нет истории ответов",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data="menu:main")
                    .as_markup()
            )
            await callback.answer()
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
        await callback.answer()
        return
    
    # Админ: просмотр тикета
    if data.startswith("admin:view_ticket_"):
        if not is_admin(user.id):
            await callback.answer("Нет доступа")
            return
        
        ticket_id = int(data.split("_")[-1])
        messages = get_ticket_messages(ticket_id)
        
        # Получаем информацию о пользователе
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT custom_user_id, username, first_name, last_name, title, category, status, created_at, closed_at, rating
            FROM tickets WHERE id = ?
        """, (ticket_id,))
        ticket_info = cursor.fetchone()
        conn.close()
        
        if not ticket_info:
            await callback.message.answer("❌ Обращение не найдено")
            await callback.answer()
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
        await callback.answer()
        return
    
    # Админ: профиль
    if data == "admin:profile":
        if not is_admin(user.id):
            await callback.answer("Нет доступа")
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
        await callback.answer()
        return
    
    # Админ: мои отзывы
    if data == "admin:my_reviews":
        if not is_admin(user.id):
            await callback.answer("Нет доступа")
            return
        
        reviews = get_admin_reviews(user.id)
        
        if not reviews:
            await callback.message.answer(
                "📭 У вас пока нет отзывов от пользователей.",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Назад", callback_data="admin:profile")
                    .as_markup()
            )
            await callback.answer()
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
        await callback.answer()
        return
    
    # Админ: изменить имя
    if data == "admin:change_name":
        if not is_admin(user.id):
            await callback.answer("Нет доступа")
            return
        
        await callback.message.answer(
            "Введите новое имя в формате 'Имя Ф.' (пример: Иван З.):",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(AdminEditName.waiting_for_new_name)
        await callback.answer()
        return
    
    # Админ: поиск
    if data == "admin:search":
        if not is_admin(user.id):
            await callback.answer("Нет доступа")
            return
        
        await callback.message.answer(
            "🔍 Введите текст для поиска по обращениям\n"
            "Формат: /search <текст>\n"
            "Пример: /search проблема с оплатой"
        )
        await callback.answer()
        return
    
    # Админ: статистика
    if data == "admin:stats":
        if not is_admin(user.id):
            await callback.answer("Нет доступа")
            return
        
        stats = get_statistics()
        
        # Форматируем время ответа
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
        
        # Статистика по дням
        daily_text = ""
        for day, count in stats['daily']:
            daily_text += f"{day}: {'🔵' * min(count, 5)} {count}\n"
        
        # Статистика по категориям
        categories_text = ""
        category_names = {
            'question': '❓ Вопросы',
            'problem': '⚠️ Проблемы',
            'suggestion': '💡 Предложения',
            'other': '📌 Другое'
        }
        for cat, count in stats['categories']:
            cat_name = category_names.get(cat, cat)
            categories_text += f"{cat_name}: {count}\n"
        
        # Топ администраторов
        top_admins_text = ""
        for admin in stats['top_admins']:
            name, replies, avg_rating, total_ratings = admin
            top_admins_text += f"👨‍💼 {name}: {avg_rating}/5 ({total_ratings} оценок, {replies} ответов)\n"
        
        text = (
            f"📊 <b>Статистика {BOT_USERNAME}</b>\n\n"
            f"📋 <b>Всего обращений:</b> {stats['total_tickets']}\n"
            f"├ 🟢 Открыто: {stats['open_tickets']}\n"
            f"└ 🔴 Закрыто: {stats['closed_tickets']}\n\n"
            f"⭐️ <b>Средняя оценка:</b> {stats['avg_rating']}/5\n"
            f"├ 5 ⭐️: {stats['rating_5']}\n"
            f"├ 4 ⭐️: {stats['rating_4']}\n"
            f"├ 3 ⭐️: {stats['rating_3']}\n"
            f"├ 2 ⭐️: {stats['rating_2']}\n"
            f"└ 1 ⭐️: {stats['rating_1']}\n\n"
            f"⏱ <b>Среднее время ответа:</b> {response_time}\n\n"
            f"📅 <b>Последние 7 дней:</b>\n{daily_text}\n"
            f"📂 <b>По категориям:</b>\n{categories_text}\n"
            f"🏆 <b>Топ администраторов:</b>\n{top_admins_text}"
        )
        
        await callback.message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="menu:main")
                .as_markup()
        )
        await callback.answer()
        return
    
    # Админ: черный список
    if data == "admin:blacklist":
        if not is_admin(user.id):
            await callback.answer("Нет доступа")
            return
        
        await callback.message.answer(
            "⛔ <b>Управление черным списком</b>\n\n"
            "Выберите действие:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_blacklist_keyboard()
        )
        await callback.answer()
        return
    
    # Добавить в черный список
    if data.startswith("blacklist:") and len(data.split(":")) == 3:
        if not is_admin(user.id):
            await callback.answer("Нет доступа")
            return
        
        _, user_id, custom_id = data.split(":")
        user_id = int(user_id)
        custom_id = int(custom_id)
        
        await state.update_data(blacklist_user_id=user_id, blacklist_custom_id=custom_id)
        await callback.message.answer(
            f"⛔ Введите причину блокировки для пользователя #{custom_id}:",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(BlacklistStates.waiting_for_reason)
        await callback.answer()
        return
    
    # Закрытие тикета админом
    if data.startswith("close:"):
        if not is_admin(user.id):
            await callback.answer("Нет доступа")
            return
        
        parts = data.split(":")
        if len(parts) == 4:
            _, ticket_id, custom_id, admin_id = parts
            ticket_id = int(ticket_id)
            custom_id = int(custom_id)
            admin_id = int(admin_id)
            
            admin_name = get_admin_name(user.id)
            
            # Получаем user_id
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM tickets WHERE id = ?", (ticket_id,))
            row = cursor.fetchone()
            user_id = row[0] if row else None
            conn.close()
            
            if user_id and close_ticket(ticket_id, user.id, admin_name):
                await callback.message.edit_text(f"✅ Обращение #{custom_id} закрыто")
                
                # Уведомляем пользователя
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
        
        await callback.answer()
        return
    
    # --------------------- КЛОНЫ БОТОВ ---------------------
    if data == "clone:create":
        await callback.message.edit_text(
            "🤖 <b>Создание своего бота поддержки</b>\n\n"
            "1. Откройте @BotFather в Telegram\n"
            "2. Создайте нового бота командой /newbot\n"
            "3. Скопируйте токен, который даст BotFather\n"
            "4. Отправьте его сюда\n\n"
            "⚠️ Токен выглядит так: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
            parse_mode=ParseMode.HTML
        )
        await state.set_state(CloneBotStates.waiting_for_token)
        await callback.answer()
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
            await callback.answer()
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
        await callback.answer()
        return
    
    if data.startswith("clone:manage:"):
        token = data.split(":")[2]
        
        # Получаем информацию о боте
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT bot_username, bot_name, created_at, status, admins FROM clone_bots WHERE token = ?", 
                      (token,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            await callback.message.edit_text("❌ Бот не найден")
            await callback.answer()
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
        await callback.answer()
        return
    
    if data.startswith("clone:stats:"):
        token = data.split(":")[2]
        
        stats = get_statistics(token)
        bot_info = get_bot_display_info(token)
        
        # Форматируем время ответа
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
        await callback.answer()
        return
    
    if data.startswith("clone:restart:"):
        token = data.split(":")[2]
        
        await callback.message.edit_text("🔄 Перезапуск бота...")
        
        # Останавливаем
        await stop_clone_bot(token)
        await asyncio.sleep(2)
        
        # Запускаем снова
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
        
        await callback.answer()
        return
    
    if data.startswith("clone:delete:"):
        token = data.split(":")[2]
        
        # Останавливаем бота
        await stop_clone_bot(token)
        
        # Удаляем из БД
        delete_clone_bot(token)
        
        await callback.message.edit_text(
            "✅ Бот успешно удален",
            reply_markup=InlineKeyboardBuilder()
                .button(text="◀️ Назад", callback_data="clone:list")
                .as_markup()
        )
        await callback.answer()
        return

# --------------------- ОБРАБОТКА ЗАГОЛОВКА ОБРАЩЕНИЯ ---------------------
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
    
    # Создаем новый тикет
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

# --------------------- ОБРАБОТКА ЧЕРНОГО СПИСКА ---------------------
@dp.message(BlacklistStates.waiting_for_reason)
async def blacklist_reason(message: Message, state: FSMContext):
    """Добавление причины в черный список"""
    data = await state.get_data()
    user_id = data.get('blacklist_user_id')
    custom_id = data.get('blacklist_custom_id')
    reason = message.text.strip()
    
    if not reason:
        await message.answer("Введите причину блокировки:")
        return
    
    add_to_blacklist(user_id, reason, message.from_user.id)
    
    # Уведомляем пользователя
    try:
        await bot.send_message(
            user_id,
            f"⛔ Вы были добавлены в черный список поддержки.\n"
            f"Причина: {reason}\n\n"
            f"Для вопросов обратитесь к @PulsOfficialManager_bot"
        )
    except:
        pass
    
    await message.answer(
        f"✅ Пользователь #{custom_id} добавлен в черный список.\n"
        f"Причина: {reason}",
        reply_markup=get_admin_main_menu()
    )
    await state.clear()

# --------------------- ОБРАБОТКА ОТЗЫВА ---------------------
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
@dp.message(TicketStates.in_dialog, F.chat.type == 'private')
async def handle_user_message(message: Message, state: FSMContext):
    """Обработка сообщений от пользователя в диалоге"""
    user = message.from_user
    bot_token = 'main'
    
    # Проверяем черный список
    if check_blacklist(user.id):
        await message.answer(
            "⛔ Вы находитесь в черном списке и не можете использовать поддержку."
        )
        await state.clear()
        return
    
    data = await state.get_data()
    ticket_id = data.get('ticket_id')
    custom_id = data.get('custom_id')
    title = data.get('title')
    
    # Проверяем, что тикет существует и открыт
    if not ticket_id or not has_open_ticket(user.id):
        # Пробуем найти открытый тикет
        open_ticket = get_open_ticket_info(user.id)
        if open_ticket:
            ticket_id, custom_id, title, _, _, _ = open_ticket
            await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)
        else:
            await message.answer(
                "❌ Ошибка: активное обращение не найдено.\n"
                "Начните новое обращение через /start",
                reply_markup=get_user_main_menu(bot_token)
            )
            await state.clear()
            return
    
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
    
    # Получаем информацию о тикете для категории
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT category FROM tickets WHERE id = ?", (ticket_id,))
    row = cursor.fetchone()
    category = row[0] if row else 'question'
    conn.close()
    
    # Обработка альбомов
    if message.media_group_id:
        if message.media_group_id not in media_groups_buffer:
            media_groups_buffer[message.media_group_id] = []
        media_groups_buffer[message.media_group_id].append(message)
        
        # Ждем немного, чтобы собрать все сообщения альбома
        await asyncio.sleep(1)
        
        # Проверяем, собрали ли все сообщения
        if message.media_group_id in media_groups_buffer:
            messages = media_groups_buffer.pop(message.media_group_id)
            
            # Сохраняем альбом в БД
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
            
            # Сохраняем запись о сообщении
            save_message(
                ticket_id, 'user', user.id, 
                f"[Альбом] {messages[0].caption or ''}", 
                user.first_name,
                message.media_group_id
            )
            
            # Пересылаем админам
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
                    
                    # Отправляем альбом
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
    content = message.text or "[Медиа]"
    file_id = None
    media_type = None
    caption = None
    
    # Определяем тип сообщения
    if message.text:
        save_message(ticket_id, 'user', user.id, message.text, user.first_name)
        content_for_admin = message.text
    elif message.photo:
        file_id = message.photo[-1].file_id
        media_type = 'photo'
        caption = message.caption
        save_message(ticket_id, 'user', user.id, f"[Фото] {caption or ''}", user.first_name, 
                    file_id=file_id, media_type=media_type, caption=caption)
        content_for_admin = f"[Фото] {caption or ''}"
    elif message.video:
        file_id = message.video.file_id
        media_type = 'video'
        caption = message.caption
        save_message(ticket_id, 'user', user.id, f"[Видео] {caption or ''}", user.first_name,
                    file_id=file_id, media_type=media_type, caption=caption)
        content_for_admin = f"[Видео] {caption or ''}"
    elif message.voice:
        file_id = message.voice.file_id
        media_type = 'voice'
        save_message(ticket_id, 'user', user.id, "[Голосовое сообщение]", user.first_name,
                    file_id=file_id, media_type=media_type)
        content_for_admin = "[Голосовое сообщение]"
    elif message.document:
        file_id = message.document.file_id
        media_type = 'document'
        caption = message.caption
        save_message(ticket_id, 'user', user.id, f"[Документ] {message.document.file_name}", user.first_name,
                    file_id=file_id, media_type=media_type, caption=caption)
        content_for_admin = f"[Документ] {message.document.file_name}"
    else:
        await message.answer("❌ Неподдерживаемый тип сообщения")
        return
    
    # Информация для админов
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
    
    # Отправка админам
    for admin_id in ADMIN_IDS:
        try:
            # Сначала отправляем информацию
            await bot.send_message(admin_id, user_info, parse_mode=ParseMode.HTML)
            
            # Затем пересылаем само сообщение для возможности ответа
            await message.forward(admin_id)
            
        except Exception as e:
            logging.error(f"Ошибка отправки админу {admin_id}: {e}")
    
    await message.answer(
        f"✅ Сообщение отправлено в обращение #{custom_id}.",
        reply_markup=get_after_message_menu()
    )
    
    update_message_time(user.id)
    reset_has_responded(user.id)

# --------------------- ОТВЕТ АДМИНА ---------------------
@dp.message(lambda m: is_admin(m.from_user.id) and m.reply_to_message is not None)
async def handle_admin_reply(message: Message):
    """Обработка ответа админа (reply на пересланное сообщение)"""
    replied = message.reply_to_message
    bot_token = 'main'
    
    # Определяем ID пользователя из пересланного сообщения
    user_id = None
    custom_id = None
    title = None
    
    if replied.forward_from:
        user_id = replied.forward_from.id
    elif replied.text and "ID: <code>" in replied.text:
        # Парсим ID из информационного сообщения
        match = re.search(r'ID: <code>(\d+)</code>', replied.text)
        if match:
            custom_id = int(match.group(1))
            # Получаем user_id по custom_id
            user_info = get_user_by_custom_id(custom_id)
            if user_info:
                user_id = user_info[0]
        
        # Парсим тему
        title_match = re.search(r'Тема: (.+)\n', replied.text)
        if title_match:
            title = title_match.group(1)
    
    if not user_id:
        await message.reply("❌ Не удалось определить пользователя. Ответьте на пересланное сообщение.")
        return
    
    admin_name = get_admin_name(message.from_user.id, bot_token)
    
    if not admin_name:
        await message.reply(
            "❌ Вы не зарегистрированы в системе поддержки.\n"
            "Используйте /start для регистрации."
        )
        return
    
    # Получаем номер обращения
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, custom_user_id, title FROM tickets WHERE user_id = ? AND status = 'open'", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        await message.reply("❌ Активное обращение не найдено")
        conn.close()
        return
    
    ticket_id, custom_id, title = row
    conn.close()
    
    try:
        file_id = None
        media_type = None
        caption = None
        content = ""
        
        # Отправляем ответ пользователю с пересылкой
        if message.text:
            await bot.send_message(
                user_id, 
                f"✉️ <b>Ответ от {admin_name}:</b>\n\n{message.text}",
                parse_mode=ParseMode.HTML
            )
            content = message.text
            save_message(ticket_id, 'admin', message.from_user.id, content, admin_name, bot_token=bot_token)
            
        elif message.photo:
            file_id = message.photo[-1].file_id
            media_type = 'photo'
            caption = message.caption
            await bot.send_photo(
                user_id, 
                file_id,
                caption=f"✉️ <b>Ответ от {admin_name}:</b>\n\n{caption or ''}",
                parse_mode=ParseMode.HTML
            )
            content = f"[Фото] {caption or ''}"
            save_message(ticket_id, 'admin', message.from_user.id, content, admin_name,
                        file_id=file_id, media_type=media_type, caption=caption, bot_token=bot_token)
            
        elif message.video:
            file_id = message.video.file_id
            media_type = 'video'
            caption = message.caption
            await bot.send_video(
                user_id, 
                file_id,
                caption=f"✉️ <b>Ответ от {admin_name}:</b>\n\n{caption or ''}",
                parse_mode=ParseMode.HTML
            )
            content = f"[Видео] {caption or ''}"
            save_message(ticket_id, 'admin', message.from_user.id, content, admin_name,
                        file_id=file_id, media_type=media_type, caption=caption, bot_token=bot_token)
            
        elif message.voice:
            file_id = message.voice.file_id
            media_type = 'voice'
            await bot.send_voice(user_id, file_id)
            await bot.send_message(
                user_id,
                f"✉️ <b>Ответ от {admin_name}:</b> (голосовое)",
                parse_mode=ParseMode.HTML
            )
            content = "[Голосовое сообщение]"
            save_message(ticket_id, 'admin', message.from_user.id, content, admin_name,
                        file_id=file_id, media_type=media_type, bot_token=bot_token)
            
        elif message.document:
            file_id = message.document.file_id
            media_type = 'document'
            caption = message.caption
            await bot.send_document(
                user_id, 
                file_id,
                caption=f"✉️ <b>Ответ от {admin_name}:</b>\n\n{caption or ''}",
                parse_mode=ParseMode.HTML
            )
            content = f"[Документ] {message.document.file_name}"
            save_message(ticket_id, 'admin', message.from_user.id, content, admin_name,
                        file_id=file_id, media_type=media_type, caption=caption, bot_token=bot_token)
            
        elif message.media_group_id:
            # Обработка альбома от админа
            await message.copy_to(user_id)
            await bot.send_message(
                user_id,
                f"✉️ <b>Ответ от {admin_name}:</b> (альбом)",
                parse_mode=ParseMode.HTML
            )
            content = "[Альбом]"
            save_message(ticket_id, 'admin', message.from_user.id, content, admin_name,
                        media_group_id=message.media_group_id, bot_token=bot_token)
        else:
            await message.reply("❌ Неподдерживаемый тип сообщения")
            return
        
        update_has_responded(user_id, bot_token)
        update_admin_activity(message.from_user.id, bot_token)
        
        await message.reply(
            f"✅ Ответ на обращение #{custom_id} отправлен от имени {admin_name}",
            reply_markup=get_ticket_actions_keyboard(ticket_id, user_id, custom_id)
        )
        
    except Exception as e:
        await message.reply(f"❌ Ошибка при отправке: {e}")
        logging.error(f"Ошибка ответа админа: {e}")

# --------------------- ОБРАБОТКА КЛОНОВ БОТОВ ---------------------
@dp.message(CloneBotStates.waiting_for_token)
async def clone_token_received(message: Message, state: FSMContext):
    """Получение токена для клона бота"""
    token = message.text.strip()
    
    # Проверяем валидность токена
    is_valid, username, bot_name = verify_bot_token(token)
    
    if not is_valid:
        await message.answer(
            "❌ Неверный токен. Убедитесь, что вы скопировали его правильно.\n"
            "Попробуйте ещё раз или отправьте /cancel"
        )
        return
    
    # Сохраняем токен в состояние
    await state.update_data(token=token, username=username, bot_name=bot_name)
    
    await message.answer(
        f"✅ Бот @{username} успешно проверен!\n\n"
        f"Теперь укажите ID администраторов (через запятую), которые будут иметь доступ к этому боту.\n"
        f"Пример: 123456789, 987654321\n\n"
        f"Вы (ID: {message.from_user.id}) будете добавлены автоматически."
    )
    await state.set_state(CloneBotStates.waiting_for_admins)

@dp.message(CloneBotStates.waiting_for_admins)
async def clone_admins_received(message: Message, state: FSMContext):
    """Получение списка админов для клона бота"""
    data = await state.get_data()
    token = data['token']
    username = data['username']
    bot_name = data['bot_name']
    
    # Парсим ID админов
    admin_ids = [message.from_user.id]  # Владелец всегда админ
    
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
    
    # Сохраняем в БД
    save_clone_bot(token, message.from_user.id, username, bot_name, admin_ids)
    
    # Запускаем клона бота
    success = await start_clone_bot(token)
    
    if success:
        await message.answer(
            f"✅ <b>Бот @{username} успешно создан и запущен!</b>\n\n"
            f"📋 Информация:\n"
            f"├ Имя: {bot_name}\n"
            f"├ Юзернейм: @{username}\n"
            f"├ Админы: {', '.join(map(str, admin_ids))}\n"
            f"└ Статус: 🟢 Активен\n\n"
            f"Теперь вы можете управлять ботом через меню 'Мои боты'.",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(
            f"❌ Бот @{username} сохранен, но не удалось запустить.\n"
            f"Попробуйте перезапустить позже."
        )
    
    await state.clear()

# --------------------- РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ ДЛЯ КЛОНОВ ---------------------
def register_clone_handlers(dp: Dispatcher, bot_token: str):
    """Регистрация обработчиков для клона бота"""
    
    @dp.message(CommandStart())
    async def clone_start(message: Message, state: FSMContext):
        if message.chat.type != 'private':
            await message.answer(
                f"👋 Привет! Для обращений пиши мне в личные сообщения."
            )
            return

        user = message.from_user
        
        # Проверяем черный список
        if check_blacklist(user.id, bot_token):
            await message.answer(
                "⛔ Вы находитесь в черном списке и не можете использовать поддержку."
            )
            return
        
        # Получаем или создаем пользовательский ID
        custom_id = get_or_create_custom_id(user.id, user.username, user.first_name, user.last_name)
        
        bot_info = get_bot_display_info(bot_token)
        
        # Проверяем, админ ли пользователь
        if is_admin(user.id, bot_token):
            # Админ - показываем админское меню
            if not get_admin_name(user.id, bot_token):
                await message.answer(
                    f"👋 Добро пожаловать в панель поддержки {bot_info['name']}!\n"
                    f"Ваш ID: <code>{custom_id}</code>\n\n"
                    f"Введите своё имя в формате:\n"
                    f"Имя Ф.\n\n"
                    f"Пример: Иван З.",
                    parse_mode=ParseMode.HTML
                )
                await state.set_state(AdminRegistration.waiting_for_name)
            else:
                admin_name = get_admin_name(user.id, bot_token)
                await message.answer(
                    f"👋 С возвращением, {admin_name}!\n"
                    f"Бот: {bot_info['name']}\n"
                    f"Ваш ID: <code>{custom_id}</code>\n\n"
                    f"🔧 Панель поддержки:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_main_menu(bot_token)
                )
        else:
            # Обычный пользователь
            open_ticket = get_open_ticket_info(user.id, bot_token)
            if open_ticket:
                ticket_id, custom_id, title, category, created_at, has_responded = open_ticket
                created = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")
                await message.answer(
                    f"👋 С возвращением в {bot_info['name']}!\n"
                    f"Ваш ID: <code>{custom_id}</code>\n\n"
                    f"📌 У вас есть открытое обращение #{custom_id}\n"
                    f"📝 Тема: {title}\n"
                    f"📅 Создано: {created}\n\n"
                    f"Продолжите диалог:",
                    parse_mode=ParseMode.HTML
                )
                await state.set_state(TicketStates.in_dialog)
                await state.update_data(ticket_id=ticket_id, custom_id=custom_id, title=title)
            else:
                await message.answer(
                    f"👋 Добро пожаловать в {bot_info['name']}!\n"
                    f"Ваш персональный ID: <code>{custom_id}</code>\n\n"
                    f"Выберите действие:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_user_main_menu(bot_token)
                )
            await state.clear()
    
    # Здесь можно добавить остальные обработчики для клона,
    # они аналогичны основным, но используют bot_token

# --------------------- ПЛАНИРОВЩИК ЗАДАЧ ---------------------
async def scheduler():
    """Планировщик для автоматического закрытия старых тикетов"""
    while True:
        await asyncio.sleep(3600)  # Каждый час
        try:
            # Для основного бота
            conn = sqlite3.connect(DB_FILE)
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
                
                # Уведомление пользователя
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
            clones = cursor.fetchall()
            
            for clone in clones:
                token = clone[0]
                cursor.execute("""
                    SELECT id, user_id, custom_user_id, title FROM tickets 
                    WHERE status = 'open' AND last_message_at < ? AND bot_token = ?
                """, (cutoff, token))
                
                clone_tickets = cursor.fetchall()
                
                for ticket_id, user_id, custom_id, title in clone_tickets:
                    cursor.execute("UPDATE tickets SET status = 'closed', closed_at = ?, closed_by_name = 'Автоматически' WHERE id = ?", 
                                  (datetime.utcnow().isoformat(), ticket_id))
                    
                    # Уведомление пользователя через клона
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
            
            total_closed = len(old_tickets) + sum(len(c[1]) for c in clones)
            if total_closed > 0:
                logging.info(f"Автоматически закрыто {total_closed} старых обращений")
                
        except Exception as e:
            logging.error(f"Ошибка в планировщике: {e}")

# --------------------- ЗАПУСК ---------------------
async def main():
    """Основная функция запуска бота"""
    logging.info(f"Бот {BOT_USERNAME} запускается...")
    
    # Запускаем все сохраненные клоны ботов
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT token FROM clone_bots WHERE status = 'active'")
    clones = cursor.fetchall()
    conn.close()
    
    for clone in clones:
        token = clone[0]
        logging.info(f"Запуск клона бота {token}...")
        await start_clone_bot(token)
        await asyncio.sleep(1)
    
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

