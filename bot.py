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
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# --------------------- НАСТРОЙКИ ---------------------
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"  # ← Основной бот
ADMIN_IDS = [123456789, 987654321]  # ← твои ID
MAIN_BOT_USERNAME = "@PulsOfficialManager_bot"
DB_FILE = "tickets.db"
CLONE_BOTS_FILE = "clone_bots.json"

# Настройки анти-спама
MESSAGE_COOLDOWN = 60  # секунд
SPAM_LIMIT = 5  # сообщений без ответа
SPAM_BLOCK_TIME = 600  # 10 минут в секундах
TICKET_AUTO_CLOSE_HOURS = 48  # часов без активности

# --------------------- БАЗА ДАННЫХ ---------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Таблица тикетов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            username TEXT,
            first_name TEXT,
            category TEXT DEFAULT 'question',
            created_at TEXT NOT NULL,
            last_message_at TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            has_responded INTEGER DEFAULT 0,
            closed_at TEXT,
            closed_by INTEGER,
            blocked_until TEXT,
            rating INTEGER,
            feedback_text TEXT,
            bot_token TEXT DEFAULT 'main'
        )
    ''')
    
    # Таблица админов поддержки
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS support_admins (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            last_active TEXT,
            bot_token TEXT DEFAULT 'main'
        )
    ''')
    
    # Таблица сообщений
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            sender_type TEXT NOT NULL,
            sender_id INTEGER NOT NULL,
            content TEXT,
            media_group_id TEXT,
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
    
    # Индексы для быстрого поиска
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_ticket_id ON messages(ticket_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_media_groups_group_id ON media_groups(group_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_clone_bots_owner ON clone_bots(owner_id)')
    
    conn.commit()
    conn.close()

init_db()

# --------------------- СОСТОЯНИЯ FSM ---------------------
class AdminRegistration(StatesGroup):
    waiting_for_name = State()

class AdminEditName(StatesGroup):
    waiting_for_new_name = State()

class TicketStates(StatesGroup):
    in_dialog = State()
    waiting_category = State()
    waiting_feedback = State()

class TicketClose(StatesGroup):
    waiting_confirmation = State()

class CloneBotStates(StatesGroup):
    waiting_for_token = State()
    waiting_for_admins = State()
    waiting_for_settings = State()

# --------------------- ХРАНИЛИЩЕ АКТИВНЫХ БОТОВ ---------------------
active_bots = {}  # token: (bot, dp, bot_info)
bot_sessions = {}  # token: session

# --------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---------------------
def get_bot_display_info(bot_token: str = 'main') -> Dict[str, str]:
    """Получение информации о боте для отображения"""
    if bot_token == 'main':
        return {
            'name': 'Основной бот',
            'username': '@PulsSupport_bot',
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
        return f"🤖 <b>Основной бот поддержки</b>\n└ @PulsSupport_bot\n\n"
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
                f"{created_info}"
                f"\n")

def is_admin(user_id: int, bot_token: str = 'main') -> bool:
    """Проверка, является ли пользователь админом"""
    if bot_token == 'main':
        return user_id in ADMIN_IDS
    
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
    cursor.execute("UPDATE support_admins SET last_active = ? WHERE user_id = ? AND bot_token = ?", 
                  (now, user_id, bot_token))
    conn.commit()
    conn.close()

def get_or_create_ticket(user: types.User, category: str = 'question', bot_token: str = 'main') -> int:
    """Получение или создание тикета для пользователя"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, status FROM tickets WHERE user_id = ? AND bot_token = ?", 
                  (user.id, bot_token))
    row = cursor.fetchone()
    
    now = datetime.utcnow().isoformat()
    
    if row:
        ticket_id = row[0]
        status = row[1]
        
        # Если тикет закрыт, создаем новый
        if status == 'closed':
            cursor.execute("""
                INSERT INTO tickets (user_id, username, first_name, category, created_at, last_message_at, status, bot_token)
                VALUES (?, ?, ?, ?, ?, ?, 'open', ?)
            """, (user.id, user.username, user.first_name, category, now, now, bot_token))
            ticket_id = cursor.lastrowid
        else:
            cursor.execute("UPDATE tickets SET last_message_at = ?, username = ?, first_name = ? WHERE id = ?",
                           (now, user.username, user.first_name, ticket_id))
    else:
        cursor.execute("""
            INSERT INTO tickets (user_id, username, first_name, category, created_at, last_message_at, status, bot_token)
            VALUES (?, ?, ?, ?, ?, ?, 'open', ?)
        """, (user.id, user.username, user.first_name, category, now, now, bot_token))
        ticket_id = cursor.lastrowid
        
        # Уведомление админов о новом тикете
        asyncio.create_task(notify_admins_new_ticket(user, ticket_id, category, bot_token))
    
    conn.commit()
    conn.close()
    return ticket_id

async def notify_admins_new_ticket(user: types.User, ticket_id: int, category: str, bot_token: str = 'main'):
    """Уведомление админов о новом тикете"""
    category_names = {
        'question': '❓ Вопрос',
        'problem': '⚠️ Проблема',
        'suggestion': '💡 Предложение',
        'other': '📌 Другое'
    }
    
    category_text = category_names.get(category, category)
    bot_info = get_bot_display_info(bot_token)
    
    # Получаем список админов для этого бота
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    if bot_token == 'main':
        admin_ids = ADMIN_IDS
    else:
        cursor.execute("SELECT admins FROM clone_bots WHERE token = ?", (bot_token,))
        row = cursor.fetchone()
        admin_ids = json.loads(row[0]) if row else []
    
    conn.close()
    
    text = (
        f"🆕 <b>НОВЫЙ ТИКЕТ #{ticket_id}</b>\n"
        f"🤖 {bot_info['name']} ({bot_info['username']})\n\n"
        f"👤 Пользователь: <a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"📱 Username: @{user.username or 'нет'}\n"
        f"📂 Категория: {category_text}\n"
        f"⏰ Время: {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')} UTC\n\n"
        f"Для ответа используйте /reply {ticket_id}"
    )
    
    # Отправляем уведомления через соответствующих ботов
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
    
    cursor.execute("SELECT blocked_until FROM tickets WHERE user_id = ? AND bot_token = ?", 
                  (user_id, bot_token))
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0]:
        blocked_until = datetime.fromisoformat(row[0])
        if datetime.utcnow() < blocked_until:
            remaining = (blocked_until - datetime.utcnow()).seconds // 60
            return True, f"⛔ Вы заблокированы на {remaining} мин. за спам."
    
    return False, None

def check_message_cooldown(user_id: int, bot_token: str = 'main') -> tuple[bool, Optional[str]]:
    """Проверка кулдауна между сообщениями"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT last_message_at FROM tickets WHERE user_id = ? AND bot_token = ?", 
                  (user_id, bot_token))
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0]:
        last_time = datetime.fromisoformat(row[0])
        diff = datetime.utcnow() - last_time
        if diff.total_seconds() < MESSAGE_COOLDOWN:
            remaining = int(MESSAGE_COOLDOWN - diff.total_seconds())
            return True, f"⏳ Подождите {remaining} сек. перед следующим сообщением."
    
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
        cursor.execute("UPDATE tickets SET blocked_until = ? WHERE user_id = ? AND bot_token = ?", 
                      (block_until.isoformat(), user_id, bot_token))
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
    cursor.execute("UPDATE tickets SET last_message_at = ? WHERE user_id = ? AND bot_token = ?", 
                  (now, user_id, bot_token))
    conn.commit()
    conn.close()

def get_ticket_status(user_id: int, bot_token: str = 'main') -> Optional[tuple]:
    """Получение статуса тикета"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT status, has_responded FROM tickets WHERE user_id = ? AND bot_token = ?", 
                  (user_id, bot_token))
    row = cursor.fetchone()
    conn.close()
    return row if row else None

def update_has_responded(user_id: int, bot_token: str = 'main'):
    """Обновление флага ответа админа"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET has_responded = 1 WHERE user_id = ? AND bot_token = ?", 
                  (user_id, bot_token))
    conn.commit()
    conn.close()

def reset_has_responded(user_id: int, bot_token: str = 'main'):
    """Сброс флага ответа админа (для нового сообщения пользователя)"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET has_responded = 0 WHERE user_id = ? AND bot_token = ?", 
                  (user_id, bot_token))
    conn.commit()
    conn.close()

def save_message(ticket_id: int, sender_type: str, sender_id: int, content: str, 
                 media_group_id: str = None, bot_token: str = 'main'):
    """Сохранение сообщения в БД"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute('''
        INSERT INTO messages (ticket_id, sender_type, sender_id, content, media_group_id, timestamp, bot_token)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (ticket_id, sender_type, sender_id, content, media_group_id, now, bot_token))
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

def get_ticket_messages(ticket_id: int, bot_token: str = 'main') -> List:
    """Получение всех сообщений тикета"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT sender_type, content, timestamp, media_group_id 
        FROM messages 
        WHERE ticket_id = ? AND bot_token = ?
        ORDER BY timestamp ASC
    ''', (ticket_id, bot_token))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_admin_tickets(admin_id: int, bot_token: str = 'main') -> List:
    """Получение тикетов, в которых участвовал админ"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT t.id, t.user_id, t.username, t.status, t.created_at, t.last_message_at
        FROM tickets t
        JOIN messages m ON t.id = m.ticket_id
        WHERE m.sender_type = 'admin' AND m.sender_id = ? AND t.bot_token = ?
        ORDER BY t.last_message_at DESC
    ''', (admin_id, bot_token))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_all_open_tickets(bot_token: str = 'main') -> List:
    """Получение всех открытых тикетов"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, user_id, username, first_name, category, created_at, last_message_at
        FROM tickets
        WHERE status = 'open' AND bot_token = ?
        ORDER BY created_at ASC
    ''', (bot_token,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_admin_profile(admin_id: int, bot_token: str = 'main') -> str:
    """Получение профиля админа"""
    name = get_admin_name(admin_id, bot_token)
    bot_info = get_bot_display_info(bot_token)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT registered_at, last_active,
               (SELECT COUNT(*) FROM messages WHERE sender_id = ? AND sender_type = 'admin' AND bot_token = ?) as total_replies
        FROM support_admins WHERE user_id = ? AND bot_token = ?
    """, (admin_id, bot_token, admin_id, bot_token))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        registered = datetime.fromisoformat(row[0]).strftime('%d.%m.%Y %H:%M')
        last_active = datetime.fromisoformat(row[1]).strftime('%d.%m.%Y %H:%M') if row[1] else 'никогда'
        total_replies = row[2]
        
        return (
            f"👤 <b>Профиль поддержки</b>\n"
            f"🤖 {bot_info['name']} ({bot_info['username']})\n\n"
            f"📋 Имя: {name}\n"
            f"🆔 ID: <code>{admin_id}</code>\n"
            f"📅 Зарегистрирован: {registered}\n"
            f"⏰ Последняя активность: {last_active}\n"
            f"💬 Всего ответов: {total_replies}"
        )
    
    return f"Профиль поддержки\n\nИмя: {name}\nID: {admin_id}"

def delete_admin_account(admin_id: int, bot_token: str = 'main'):
    """Удаление аккаунта админа"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM support_admins WHERE user_id = ? AND bot_token = ?", 
                  (admin_id, bot_token))
    conn.commit()
    conn.close()

def close_ticket(ticket_id: int, closed_by: int, bot_token: str = 'main') -> bool:
    """Закрытие тикета"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        UPDATE tickets 
        SET status = 'closed', closed_at = ?, closed_by = ? 
        WHERE id = ? AND status != 'closed' AND bot_token = ?
    """, (now, closed_by, ticket_id, bot_token))
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success

def auto_close_old_tickets(bot_token: str = 'main') -> int:
    """Автоматическое закрытие старых тикетов"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cutoff = (datetime.utcnow() - timedelta(hours=TICKET_AUTO_CLOSE_HOURS)).isoformat()
    
    cursor.execute("""
        SELECT id, user_id FROM tickets 
        WHERE status = 'open' AND last_message_at < ? AND bot_token = ?
    """, (cutoff, bot_token))
    
    old_tickets = cursor.fetchall()
    
    bot_info = get_bot_display_info(bot_token)
    
    for ticket_id, user_id in old_tickets:
        cursor.execute("""
            UPDATE tickets 
            SET status = 'closed', closed_at = ?, closed_by = ? 
            WHERE id = ?
        """, (datetime.utcnow().isoformat(), 0, ticket_id))
        
        # Уведомление пользователя
        try:
            if bot_token == 'main':
                asyncio.create_task(bot.send_message(
                    user_id,
                    f"⏰ Ваше обращение #{ticket_id} в {bot_info['name']} автоматически закрыто из-за отсутствия активности в течение {TICKET_AUTO_CLOSE_HOURS} часов.\n\n"
                    f"Если вопрос остался актуален, напишите новое сообщение."
                ))
            else:
                clone_bot, _, _ = active_bots.get(bot_token, (None, None, None))
                if clone_bot:
                    asyncio.create_task(clone_bot.send_message(
                        user_id,
                        f"⏰ Ваше обращение #{ticket_id} в {bot_info['name']} автоматически закрыто из-за отсутствия активности в течение {TICKET_AUTO_CLOSE_HOURS} часов.\n\n"
                        f"Если вопрос остался актуален, напишите новое сообщение."
                    ))
        except:
            pass
    
    conn.commit()
    conn.close()
    return len(old_tickets)

def save_rating(ticket_id: int, rating: int, feedback: str = None, bot_token: str = 'main'):
    """Сохранение оценки тикета"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET rating = ?, feedback_text = ? WHERE id = ? AND bot_token = ?", 
                  (rating, feedback, ticket_id, bot_token))
    conn.commit()
    conn.close()

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
    avg_response_time = cursor.fetchone()[0]
    stats['avg_response_seconds'] = int(avg_response_time) if avg_response_time else 0
    
    conn.close()
    return stats

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

# --------------------- КЛАВИАТУРЫ ---------------------
def get_main_menu(bot_token: str = 'main') -> InlineKeyboardMarkup:
    """Главное меню для пользователя"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Написать в поддержку", callback_data="support:start")
    builder.button(text="ℹ️ Информация", callback_data="info:about")
    
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

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены диалога"""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить", callback_data="support:cancel")
    return builder.as_markup()

def get_after_message_menu(bot_token: str = 'main') -> InlineKeyboardMarkup:
    """Меню после отправки сообщения"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Новое сообщение", callback_data="support:continue")
    builder.button(text="🏠 Главное меню", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_rating_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для оценки"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐️ 5 - Отлично", callback_data=f"rate:5:{ticket_id}")
    builder.button(text="⭐️ 4 - Хорошо", callback_data=f"rate:4:{ticket_id}")
    builder.button(text="⭐️ 3 - Нормально", callback_data=f"rate:3:{ticket_id}")
    builder.button(text="⭐️ 2 - Плохо", callback_data=f"rate:2:{ticket_id}")
    builder.button(text="⭐️ 1 - Ужасно", callback_data=f"rate:1:{ticket_id}")
    builder.adjust(1)
    return builder.as_markup()

def get_admin_menu(bot_token: str = 'main') -> InlineKeyboardMarkup:
    """Главное меню админа"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📂 Открытые тикеты", callback_data="admin:open_tickets")
    builder.button(text="📜 Моя история", callback_data="admin:history")
    builder.button(text="👤 Профиль", callback_data="admin:profile")
    builder.button(text="✏️ Изменить имя", callback_data="admin:change_name")
    builder.button(text="🔍 Поиск", callback_data="admin:search")
    builder.button(text="📊 Статистика", callback_data="admin:stats")
    builder.button(text="🗑️ Удалить аккаунт", callback_data="admin:delete_account")
    
    if bot_token != 'main':
        builder.button(text="⚙️ Управление ботом", callback_data="clone:manage")
    
    builder.adjust(1)
    return builder.as_markup()

def get_group_menu() -> InlineKeyboardMarkup:
    """Меню для групповых чатов"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Написать в поддержку", url="https://t.me/PulsSupport_bot")
    return builder.as_markup()

def get_ticket_actions_keyboard(ticket_id: int, user_id: int) -> InlineKeyboardMarkup:
    """Кнопки действий над тикетом для админа"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Закрыть тикет", callback_data=f"close:{ticket_id}:{user_id}")
    builder.button(text="📜 История", callback_data=f"admin:view_ticket_{ticket_id}")
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

# --------------------- ОСНОВНОЙ БОТ ---------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Словарь для временного хранения альбомов
media_groups_buffer: Dict[str, List[Message]] = defaultdict(list)

# --------------------- ОБРАБОТЧИКИ ДЛЯ ОСНОВНОГО БОТА ---------------------
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработка команды /start для основного бота"""
    if message.chat.type != 'private':
        await message.answer(
            "👋 Привет! Для вопросов и предложений пиши мне в личные сообщения.",
            reply_markup=get_group_menu()
        )
        return

    user = message.from_user
    bot_token = 'main'
    
    # Проверяем, нужно ли авто-закрыть старые тикеты
    closed_count = auto_close_old_tickets(bot_token)
    if closed_count > 0:
        logging.info(f"Автоматически закрыто {closed_count} старых тикетов")

    # Если админ и не зарегистрирован
    if is_admin(user.id, bot_token) and not get_admin_name(user.id, bot_token):
        await message.answer(
            "👋 Добро пожаловать в панель поддержки!\n\n"
            "Введите своё имя в формате:\n"
            "Имя Ф.\n\n"
            "Пример: Иван З."
        )
        await state.set_state(AdminRegistration.waiting_for_name)
        return

    # Для обычных пользователей - главное меню с информацией о боте
    bot_info = get_bot_display_info(bot_token)
    await message.answer(
        f"{format_bot_header(bot_token)}"
        f"👋 Добро пожаловать в поддержку Puls!\n\n"
        f"Выберите действие:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_menu(bot_token)
    )

@dp.message(Command("admin_menu"))
async def admin_menu_command(message: Message):
    """Команда /admin_menu для основного бота"""
    bot_token = 'main'
    
    if not is_admin(message.from_user.id, bot_token):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    update_admin_activity(message.from_user.id, bot_token)
    
    bot_info = get_bot_display_info(bot_token)
    await message.answer(
        f"{format_bot_header(bot_token)}"
        f"🔧 <b>Меню поддержки</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_menu(bot_token)
    )

@dp.message(Command("change_name"))
async def change_name_command(message: Message, state: FSMContext):
    """Команда /change_name для основного бота"""
    bot_token = 'main'
    
    if not is_admin(message.from_user.id, bot_token):
        await message.answer("❌ У вас нет доступа.")
        return
    
    await message.answer(
        "Введите новое имя в формате 'Имя Ф.' (пример: Иван З.):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminEditName.waiting_for_new_name)

@dp.message(Command("reply"))
async def reply_command(message: Message):
    """Быстрый ответ на тикет по номеру для основного бота"""
    bot_token = 'main'
    
    if not is_admin(message.from_user.id, bot_token):
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /reply <номер_тикета> <текст>")
        return
    
    try:
        ticket_id = int(args[1].split()[0])
        reply_text = ' '.join(args[1].split()[1:])
    except:
        await message.answer("Неверный формат. Пример: /reply 123 Ваш ответ")
        return
    
    if not reply_text:
        await message.answer("Введите текст ответа")
        return
    
    # Получаем user_id по ticket_id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM tickets WHERE id = ? AND bot_token = ?", 
                  (ticket_id, bot_token))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        await message.answer(f"Тикет #{ticket_id} не найден")
        return
    
    user_id = row[0]
    admin_name = get_admin_name(message.from_user.id, bot_token)
    bot_info = get_bot_display_info(bot_token)
    
    if not admin_name:
        await message.answer("Вы не зарегистрированы. Используйте /start")
        return
    
    try:
        prefix = f"✉️ <b>Ответ от {admin_name}</b>\n({bot_info['name']})\n\n"
        await bot.send_message(user_id, prefix + reply_text, parse_mode=ParseMode.HTML)
        
        # Сохраняем в БД
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tickets WHERE user_id = ? AND bot_token = ?", 
                      (user_id, bot_token))
        ticket_id_db = cursor.fetchone()[0]
        
        update_has_responded(user_id, bot_token)
        save_message(ticket_id_db, 'admin', message.from_user.id, reply_text, bot_token=bot_token)
        conn.close()
        
        await message.answer(f"✅ Ответ на тикет #{ticket_id} отправлен", 
                           reply_markup=get_ticket_actions_keyboard(ticket_id, user_id))
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("close"))
async def close_command(message: Message, state: FSMContext):
    """Команда /close для закрытия тикета в основном боте"""
    bot_token = 'main'
    
    if not is_admin(message.from_user.id, bot_token):
        await message.answer("❌ У вас нет доступа.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /close <номер_тикета>")
        return
    
    try:
        ticket_id = int(args[1])
    except:
        await message.answer("Неверный номер тикета")
        return
    
    # Получаем информацию о тикете
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, status FROM tickets WHERE id = ? AND bot_token = ?", 
                  (ticket_id, bot_token))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        await message.answer(f"Тикет #{ticket_id} не найден")
        return
    
    user_id, status = row
    
    if status == 'closed':
        await message.answer(f"Тикет #{ticket_id} уже закрыт")
        return
    
    bot_info = get_bot_display_info(bot_token)
    
    if close_ticket(ticket_id, message.from_user.id, bot_token):
        await message.answer(f"✅ Тикет #{ticket_id} закрыт")
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                user_id,
                f"🔒 Ваше обращение #{ticket_id} в {bot_info['name']} было закрыто администратором.\n\n"
                f"Оцените качество поддержки:",
                reply_markup=get_rating_keyboard(ticket_id)
            )
        except:
            pass
    else:
        await message.answer(f"❌ Не удалось закрыть тикет #{ticket_id}")

@dp.message(Command("stats"))
async def stats_command(message: Message):
    """Команда /stats для просмотра статистики в основном боте"""
    bot_token = 'main'
    
    if not is_admin(message.from_user.id, bot_token):
        await message.answer("❌ У вас нет доступа.")
        return
    
    stats = get_statistics(bot_token)
    bot_info = get_bot_display_info(bot_token)
    
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
        f"📊 <b>СТАТИСТИКА ПОДДЕРЖКИ</b>\n"
        f"🤖 {bot_info['name']} ({bot_info['username']})\n\n"
        f"📋 <b>Тикеты:</b>\n"
        f"├ Всего: {stats['total_tickets']}\n"
        f"├ Открыто: {stats['open_tickets']}\n"
        f"└ Закрыто: {stats['closed_tickets']}\n\n"
        f"⭐️ <b>Оценки:</b>\n"
        f"├ Средняя: {stats['avg_rating']}/5\n"
        f"├ 5 ⭐️: {stats['rating_5']}\n"
        f"├ 4 ⭐️: {stats['rating_4']}\n"
        f"├ 3 ⭐️: {stats['rating_3']}\n"
        f"├ 2 ⭐️: {stats['rating_2']}\n"
        f"└ 1 ⭐️: {stats['rating_1']}\n\n"
        f"⏱ <b>Среднее время ответа:</b> {response_time}"
    )
    
    await message.answer(text, parse_mode=ParseMode.HTML)

# --------------------- РЕГИСТРАЦИЯ АДМИНА ---------------------
@dp.message(AdminRegistration.waiting_for_name)
async def register_admin(message: Message, state: FSMContext):
    """Регистрация нового админа"""
    bot_token = 'main'
    name = message.text.strip()
    
    if not re.match(r'^[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z]\.$', name):
        await message.answer(
            "❌ Неверный формат. Пример: Иван З.\n"
            "Попробуйте ещё раз или отправьте /cancel"
        )
        return
    
    save_admin_name(message.from_user.id, name, bot_token)
    await state.clear()
    
    bot_info = get_bot_display_info(bot_token)
    
    await message.answer(
        f"✅ Вы зарегистрированы как <b>{name}</b> в {bot_info['name']}\n\n"
        f"Теперь вы можете:\n"
        f"• Отвечать пользователям (reply на их сообщения)\n"
        f"• Использовать /admin_menu для управления\n"
        f"• Просматривать историю чатов",
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_menu(bot_token)
    )

# --------------------- ИЗМЕНЕНИЕ ИМЕНИ АДМИНА ---------------------
@dp.message(AdminEditName.waiting_for_new_name)
async def change_name(message: Message, state: FSMContext):
    """Изменение имени админа"""
    bot_token = 'main'
    name = message.text.strip()
    
    if not re.match(r'^[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z]\.$', name):
        await message.answer(
            "❌ Неверный формат. Пример: Иван З.\n"
            "Попробуйте ещё раз:"
        )
        return
    
    save_admin_name(message.from_user.id, name, bot_token)
    await state.clear()
    
    await message.answer(
        f"✅ Имя изменено на <b>{name}</b>",
        parse_mode=ParseMode.HTML
    )

# --------------------- СОЗДАНИЕ КЛОНА БОТА ---------------------
@dp.callback_query(F.data == "clone:create")
async def clone_create(callback: CallbackQuery, state: FSMContext):
    """Начало создания клона бота"""
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

@dp.callback_query(F.data == "clone:list")
async def clone_list(callback: CallbackQuery):
    """Список клонов ботов пользователя"""
    bots = get_clone_bots(callback.from_user.id)
    
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

@dp.callback_query(F.data.startswith("clone:manage:"))
async def clone_manage(callback: CallbackQuery):
    """Управление конкретным клоном бота"""
    token = callback.data.split(":")[2]
    
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

@dp.callback_query(F.data.startswith("clone:admins:"))
async def clone_admins(callback: CallbackQuery, state: FSMContext):
    """Управление админами клона бота"""
    token = callback.data.split(":")[2]
    
    await state.update_data(clone_token=token)
    
    await callback.message.edit_text(
        "👥 <b>Управление администраторами</b>\n\n"
        "Введите ID администраторов через запятую.\n"
        "Пример: 123456789, 987654321\n\n"
        "Текущие админы будут заменены новым списком.",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(CloneBotStates.waiting_for_admins)
    await callback.answer()

@dp.callback_query(F.data.startswith("clone:stats:"))
async def clone_stats(callback: CallbackQuery):
    """Статистика для клона бота"""
    token = callback.data.split(":")[2]
    
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
        f"📊 <b>СТАТИСТИКА БОТА</b>\n"
        f"🤖 {bot_info['name']} ({bot_info['username']})\n\n"
        f"📋 <b>Тикеты:</b>\n"
        f"├ Всего: {stats['total_tickets']}\n"
        f"├ Открыто: {stats['open_tickets']}\n"
        f"└ Закрыто: {stats['closed_tickets']}\n\n"
        f"⭐️ <b>Оценки:</b>\n"
        f"├ Средняя: {stats['avg_rating']}/5\n"
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

@dp.callback_query(F.data.startswith("clone:restart:"))
async def clone_restart(callback: CallbackQuery):
    """Перезапуск клона бота"""
    token = callback.data.split(":")[2]
    
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

@dp.callback_query(F.data.startswith("clone:delete:"))
async def clone_delete(callback: CallbackQuery):
    """Удаление клона бота"""
    token = callback.data.split(":")[2]
    
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

# --------------------- ОБРАБОТКА CALLBACK ДЛЯ ОСНОВНОГО БОТА ---------------------
@dp.callback_query()
async def process_callback(callback: CallbackQuery, state: FSMContext):
    """Обработка всех callback-запросов для основного бота"""
    data = callback.data
    bot_token = 'main'
    
    # Категории
    if data.startswith("category:"):
        category = data.split(":")[1]
        user = callback.from_user
        
        ticket_id = get_or_create_ticket(user, category, bot_token)
        
        category_names = {
            'question': '❓ Вопрос',
            'problem': '⚠️ Проблема',
            'suggestion': '💡 Предложение',
            'other': '📌 Другое'
        }
        
        await callback.message.edit_text(
            f"{format_bot_header(bot_token)}"
            f"<b>Категория:</b> {category_names.get(category, category)}\n"
            f"<b>Номер обращения:</b> #{ticket_id}\n\n"
            f"📝 Опишите вашу проблему или вопрос.\n"
            f"Можно отправлять текст, фото, видео, альбомы.",
            parse_mode=ParseMode.HTML
        )
        
        await state.set_state(TicketStates.in_dialog)
        await callback.answer()
        return
    
    # Оценка
    if data.startswith("rate:"):
        _, rating, ticket_id = data.split(":")
        rating = int(rating)
        ticket_id = int(ticket_id)
        
        save_rating(ticket_id, rating, bot_token=bot_token)
        
        await callback.message.edit_text(
            f"✅ Спасибо за вашу оценку: {'⭐️' * rating}!\n"
            f"Если хотите оставить отзыв, напишите его сейчас.\n"
            f"Или отправьте /start для возврата в меню."
        )
        
        await state.set_state(TicketStates.waiting_feedback)
        await state.update_data(ticket_id=ticket_id, rating=rating)
        await callback.answer()
        return
    
    # Закрытие тикета
    if data.startswith("close:"):
        _, ticket_id, user_id = data.split(":")
        ticket_id = int(ticket_id)
        user_id = int(user_id)
        
        bot_info = get_bot_display_info(bot_token)
        
        if close_ticket(ticket_id, callback.from_user.id, bot_token):
            await callback.message.edit_text(f"✅ Тикет #{ticket_id} закрыт")
            
            # Уведомляем пользователя
            try:
                await bot.send_message(
                    user_id,
                    f"🔒 Ваше обращение #{ticket_id} в {bot_info['name']} было закрыто администратором.\n\n"
                    f"Оцените качество поддержки:",
                    reply_markup=get_rating_keyboard(ticket_id)
                )
            except:
                pass
        else:
            await callback.message.edit_text(f"❌ Тикет уже закрыт или не найден")
        
        await callback.answer()
        return
    
    # Поддержка
    if data == "support:start":
        await callback.message.edit_text(
            f"{format_bot_header(bot_token)}"
            f"Выберите категорию обращения:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_category_menu()
        )
    
    elif data == "support:cancel":
        await state.clear()
        await callback.message.edit_text(
            f"{format_bot_header(bot_token)}"
            f"❌ Обращение отменено.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu(bot_token)
        )
    
    elif data == "support:continue":
        await state.set_state(TicketStates.in_dialog)
        await callback.message.edit_text(
            f"{format_bot_header(bot_token)}"
            f"📝 Продолжаем диалог. Напишите сообщение.",
            parse_mode=ParseMode.HTML
        )
    
    elif data == "menu:main":
        await state.clear()
        await callback.message.edit_text(
            f"{format_bot_header(bot_token)}"
            f"Главное меню:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu(bot_token)
        )
    
    elif data == "info:about":
        await callback.message.answer(
            f"{format_bot_header(bot_token)}"
            f"ℹ️ <b>Информация о поддержке</b>\n\n"
            f"📌 <b>Правила:</b>\n"
            f"• Не отправляйте пустые сообщения и стикеры\n"
            f"• Описывайте проблему подробно\n"
            f"• Будьте вежливы\n"
            f"• Ожидайте ответа в рабочее время\n"
            f"• Не спамьте (блокировка)\n\n"
            f"⏱ <b>Время ответа:</b>\n"
            f"Обычно в течение нескольких часов\n\n"
            f"📞 <b>Связь:</b>\n"
            f"Основной бот: @PulsOfficialManager_bot",
            parse_mode=ParseMode.HTML
        )
    
    # Админ-меню
    elif data == "admin:open_tickets":
        tickets = get_all_open_tickets(bot_token)
        if not tickets:
            await callback.message.answer(f"{format_bot_header(bot_token)}📭 Нет открытых тикетов")
            await callback.answer()
            return
        
        builder = InlineKeyboardBuilder()
        for t in tickets[:10]:  # Показываем первые 10
            short_name = t[3][:15] + "..." if len(t[3]) > 15 else t[3]
            builder.button(
                text=f"#{t[0]} - {short_name} ({t[4]})", 
                callback_data=f"admin:view_ticket_{t[0]}"
            )
        
        if len(tickets) > 10:
            builder.button(text="📋 Все тикеты", callback_data="admin:all_tickets")
        
        builder.button(text="◀️ Назад", callback_data="admin:back")
        builder.adjust(1)
        
        await callback.message.answer(
            f"{format_bot_header(bot_token)}"
            f"📂 <b>Открытые тикеты ({len(tickets)})</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
    
    elif data == "admin:history":
        tickets = get_admin_tickets(callback.from_user.id, bot_token)
        if not tickets:
            await callback.message.answer(f"{format_bot_header(bot_token)}📭 У вас нет истории чатов.")
            await callback.answer()
            return
        
        builder = InlineKeyboardBuilder()
        for t in tickets[:10]:
            status_emoji = "🟢" if t[3] == 'open' else "🔴"
            builder.button(
                text=f"{status_emoji} #{t[0]} - @{t[2] or 'без username'}", 
                callback_data=f"admin:view_ticket_{t[0]}"
            )
        
        if len(tickets) > 10:
            builder.button(text="📋 Вся история", callback_data="admin:all_history")
        
        builder.button(text="◀️ Назад", callback_data="admin:back")
        builder.adjust(1)
        
        await callback.message.answer(
            f"{format_bot_header(bot_token)}"
            f"📜 <b>Ваша история чатов</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
    
    elif data.startswith("admin:view_ticket_"):
        ticket_id = int(data.split("_")[-1])
        messages = get_ticket_messages(ticket_id, bot_token)
        
        # Получаем информацию о пользователе
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, first_name, status FROM tickets WHERE id = ? AND bot_token = ?", 
                      (ticket_id, bot_token))
        ticket_info = cursor.fetchone()
        conn.close()
        
        if not ticket_info:
            await callback.message.answer("❌ Тикет не найден")
            await callback.answer()
            return
        
        user_id, username, first_name, status = ticket_info
        status_emoji = "🟢" if status == 'open' else "🔴"
        
        text = f"{format_bot_header(bot_token)}<b>Тикет #{ticket_id}</b> {status_emoji}\n"
        text += f"👤 {first_name} (@{username or 'нет'})\n"
        text += f"🆔 <code>{user_id}</code>\n"
        text += "─" * 20 + "\n\n"
        
        if not messages:
            text += "📭 Нет сообщений"
        else:
            for msg in messages:
                sender_type, content, timestamp, media_group_id = msg
                time_str = datetime.fromisoformat(timestamp).strftime("%d.%m %H:%M")
                sender = "👤 Пользователь" if sender_type == 'user' else "👨‍💼 Админ"
                media_mark = "📎 " if media_group_id else ""
                text += f"[{time_str}] {sender}: {media_mark}{content or '[медиа]'}\n\n"
        
        # Разбиваем длинное сообщение
        if len(text) > 4000:
            text = text[:4000] + "...\n\n(сообщение обрезано)"
        
        await callback.message.answer(text, parse_mode=ParseMode.HTML)
    
    elif data == "admin:profile":
        profile = get_admin_profile(callback.from_user.id, bot_token)
        await callback.message.answer(profile, parse_mode=ParseMode.HTML)
    
    elif data == "admin:change_name":
        await callback.message.answer(
            "Введите новое имя в формате 'Имя Ф.' (пример: Иван З.):",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(AdminEditName.waiting_for_new_name)
    
    elif data == "admin:search":
        await callback.message.answer(
            "🔍 Введите текст для поиска по сообщениям\n"
            "Формат: /search <текст>"
        )
    
    elif data == "admin:stats":
        stats = get_statistics(bot_token)
        bot_info = get_bot_display_info(bot_token)
        
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
            f"{format_bot_header(bot_token)}"
            f"📊 <b>СТАТИСТИКА</b>\n\n"
            f"📋 Всего тикетов: {stats['total_tickets']}\n"
            f"├ Открыто: {stats['open_tickets']}\n"
            f"└ Закрыто: {stats['closed_tickets']}\n\n"
            f"⭐️ Средняя оценка: {stats['avg_rating']}/5\n"
            f"⏱ Среднее время ответа: {response_time}"
        )
        
        await callback.message.answer(text, parse_mode=ParseMode.HTML)
    
    elif data == "admin:delete_account":
        delete_admin_account(callback.from_user.id, bot_token)
        await callback.message.answer(
            f"{format_bot_header(bot_token)}"
            f"🗑 Ваш аккаунт поддержки удалён.\n"
            f"Для восстановления используйте /start"
        )
    
    elif data == "admin:back":
        await callback.message.edit_text(
            f"{format_bot_header(bot_token)}"
            f"🔧 <b>Меню поддержки</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_admin_menu(bot_token)
        )
    
    await callback.answer()

# --------------------- ПОИСК ---------------------
@dp.message(Command("search"))
async def search_command(message: Message):
    """Поиск по сообщениям"""
    bot_token = 'main'
    
    if not is_admin(message.from_user.id, bot_token):
        return
    
    query = message.text.replace("/search", "").strip()
    if not query:
        await message.answer("Введите текст для поиска")
        return
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.user_id, t.username, m.content, m.timestamp
        FROM messages m
        JOIN tickets t ON m.ticket_id = t.id
        WHERE m.content LIKE ? AND m.sender_type = 'user' AND t.bot_token = ?
        ORDER BY m.timestamp DESC
        LIMIT 20
    """, (f"%{query}%", bot_token))
    
    results = cursor.fetchall()
    conn.close()
    
    if not results:
        await message.answer("❌ Ничего не найдено")
        return
    
    builder = InlineKeyboardBuilder()
    for r in results:
        ticket_id, user_id, username, content, timestamp = r
        short_content = content[:30] + "..." if len(content) > 30 else content
        time_str = datetime.fromisoformat(timestamp).strftime("%d.%m")
        builder.button(
            text=f"#{ticket_id} @{username or 'no'} ({time_str}): {short_content}",
            callback_data=f"admin:view_ticket_{ticket_id}"
        )
    
    builder.adjust(1)
    await message.answer(f"🔍 Результаты поиска по '{query}':", reply_markup=builder.as_markup())

# --------------------- ОБРАБОТКА СООБЩЕНИЙ ПОЛЬЗОВАТЕЛЯ ---------------------
@dp.message(TicketStates.in_dialog, F.chat.type == 'private')
async def handle_user_message(message: Message, state: FSMContext):
    """Обработка сообщений от пользователя в диалоге"""
    user = message.from_user
    bot_token = 'main'
    
    # Проверка на спам-блок
    blocked, block_msg = check_spam_block(user.id, bot_token)
    if blocked:
        await message.answer(block_msg)
        return
    
    # Проверка кулдауна
    cooldown, cooldown_msg = check_message_cooldown(user.id, bot_token)
    if cooldown:
        await message.answer(cooldown_msg)
        return
    
    # Проверка лимита сообщений без ответа
    limit_exceeded, limit_msg = check_message_limit(user.id, bot_token)
    if limit_exceeded:
        await message.answer(limit_msg)
        return
    
    ticket_status = get_ticket_status(user.id, bot_token)
    if ticket_status:
        status, has_responded = ticket_status
        if status == 'open' and has_responded == 0:
            # Первое сообщение уже отправлено и ждёт ответа
            await message.answer(
                "⏳ Дождитесь ответа поддержки прежде чем отправить новое сообщение.\n"
                "Спам может привести к блокировке."
            )
            return
    
    # Фильтр спама (эмодзи, стикеры и т.д.)
    if message.sticker or message.animation or message.dice:
        await message.answer("❌ Пожалуйста, отправляйте текстовые сообщения или фото/видео по теме.")
        return
    
    if message.text and len(message.text.strip()) < 3 and not any(c.isalpha() for c in message.text):
        await message.answer("❌ Слишком короткое сообщение. Опишите проблему подробнее.")
        return
    
    # Получаем или создаем тикет
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, category FROM tickets WHERE user_id = ? AND bot_token = ?", 
                  (user.id, bot_token))
    row = cursor.fetchone()
    
    if row:
        ticket_id, category = row
    else:
        # Если нет тикета, просим выбрать категорию
        await state.clear()
        await message.answer(
            f"{format_bot_header(bot_token)}"
            f"Пожалуйста, сначала выберите категорию обращения:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_category_menu()
        )
        conn.close()
        return
    
    conn.close()
    
    # Обработка альбомов
    if message.media_group_id:
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
                        msg.caption,
                        bot_token
                    )
            
            # Сохраняем запись о сообщении
            save_message(ticket_id, 'user', user.id, f"[Альбом] {messages[0].caption or ''}", 
                        message.media_group_id, bot_token)
            
            # Пересылаем админам
            bot_info = get_bot_display_info(bot_token)
            
            user_info = (
                f"<b>Тикет #{ticket_id}</b> (категория: {category})\n"
                f"🤖 {bot_info['name']} ({bot_info['username']})\n"
                f"<a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
                f"ID: <code>{user.id}</code>\n"
                f"@{user.username or 'нет'}\n"
                f"──────────────────────\n"
                f"<b>Альбом ({len(messages)} шт.)</b>\n"
            )
            
            # Получаем список админов
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT admins FROM clone_bots WHERE token = ?", (bot_token,))
            row = cursor.fetchone()
            admin_ids = json.loads(row[0]) if row else ADMIN_IDS
            conn.close()
            
            for admin_id in admin_ids:
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
                f"{format_bot_header(bot_token)}"
                f"✅ Альбом отправлен в тикет #{ticket_id}.",
                parse_mode=ParseMode.HTML,
                reply_markup=get_after_message_menu(bot_token)
            )
            
            update_message_time(user.id, bot_token)
            return
    
    # Обычное сообщение
    content = message.text or "[Медиа]"
    
    if message.text:
        save_message(ticket_id, 'user', user.id, message.text, bot_token=bot_token)
    elif message.photo:
        file_id = message.photo[-1].file_id
        save_message(ticket_id, 'user', user.id, f"[Фото] {message.caption or ''}", bot_token=bot_token)
        save_media_group(f"single_{message.message_id}", ticket_id, message.message_id, 
                        file_id, 'photo', message.caption, bot_token)
    elif message.video:
        file_id = message.video.file_id
        save_message(ticket_id, 'user', user.id, f"[Видео] {message.caption or ''}", bot_token=bot_token)
        save_media_group(f"single_{message.message_id}", ticket_id, message.message_id, 
                        file_id, 'video', message.caption, bot_token)
    elif message.voice:
        save_message(ticket_id, 'user', user.id, "[Голосовое сообщение]", bot_token=bot_token)
    elif message.document:
        save_message(ticket_id, 'user', user.id, f"[Документ] {message.document.file_name}", bot_token=bot_token)
    
    # Отправка админам
    bot_info = get_bot_display_info(bot_token)
    
    user_info = (
        f"<b>Тикет #{ticket_id}</b> (категория: {category})\n"
        f"🤖 {bot_info['name']} ({bot_info['username']})\n"
        f"<a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
        f"ID: <code>{user.id}</code>\n"
        f"@{user.username or 'нет'}\n"
        f"──────────────────────\n"
    )
    
    # Получаем список админов
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT admins FROM clone_bots WHERE token = ?", (bot_token,))
    row = cursor.fetchone()
    admin_ids = json.loads(row[0]) if row else ADMIN_IDS
    conn.close()
    
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, user_info, parse_mode=ParseMode.HTML)
            
            if message.text:
                await bot.send_message(admin_id, message.text)
            elif message.photo:
                await bot.send_photo(admin_id, message.photo[-1].file_id, caption=message.caption)
            elif message.video:
                await bot.send_video(admin_id, message.video.file_id, caption=message.caption)
            elif message.voice:
                await bot.send_voice(admin_id, message.voice.file_id)
            elif message.document:
                await bot.send_document(admin_id, message.document.file_id, caption=message.caption)
        except Exception as e:
            logging.error(f"Ошибка отправки админу {admin_id}: {e}")
    
    await message.answer(
        f"{format_bot_header(bot_token)}"
        f"✅ Сообщение отправлено в тикет #{ticket_id}.",
        parse_mode=ParseMode.HTML,
        reply_markup=get_after_message_menu(bot_token)
    )
    
    update_message_time(user.id, bot_token)
    
    # Если это первое сообщение, обновляем статус
    if ticket_status and ticket_status[1] == 1:
        reset_has_responded(user.id, bot_token)

# --------------------- ОБРАБОТКА ОТЗЫВА ---------------------
@dp.message(TicketStates.waiting_feedback)
async def handle_feedback(message: Message, state: FSMContext):
    """Обработка текстового отзыва после оценки"""
    bot_token = 'main'
    data = await state.get_data()
    ticket_id = data.get('ticket_id')
    rating = data.get('rating')
    
    if message.text:
        save_rating(ticket_id, rating, message.text, bot_token)
        await message.answer(
            f"{format_bot_header(bot_token)}"
            f"✅ Спасибо за ваш отзыв!\n"
            f"Он поможет нам стать лучше."
        )
    else:
        await message.answer("Отзыв сохранен без комментария.")
    
    await state.clear()
    await message.answer(
        f"{format_bot_header(bot_token)}"
        f"Главное меню:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_menu(bot_token)
    )

# --------------------- ОТВЕТ АДМИНА ---------------------
@dp.message(lambda m: is_admin(m.from_user.id, 'main') and m.reply_to_message is not None)
async def handle_admin_reply(message: Message):
    """Обработка ответа админа (reply на сообщение пользователя)"""
    bot_token = 'main'
    replied = message.reply_to_message
    
    # Определяем ID пользователя
    user_id = None
    
    if replied.from_user.id == bot.id and replied.forward_from:
        user_id = replied.forward_from.id
    elif replied.forward_from:
        user_id = replied.forward_from.id
    elif replied.text and "ID: <code>" in replied.text:
        # Парсим ID из сообщения админу
        match = re.search(r'ID: <code>(\d+)</code>', replied.text)
        if match:
            user_id = int(match.group(1))
    
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
    
    update_admin_activity(message.from_user.id, bot_token)
    
    # Получаем номер тикета
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM tickets WHERE user_id = ? AND bot_token = ?", 
                  (user_id, bot_token))
    row = cursor.fetchone()
    
    if not row:
        await message.reply("❌ Тикет не найден")
        conn.close()
        return
    
    ticket_id = row[0]
    conn.close()
    
    bot_info = get_bot_display_info(bot_token)
    
    try:
        prefix = f"✉️ <b>Ответ от {admin_name}</b>\n({bot_info['name']})\n\n"
        
        if message.text:
            await bot.send_message(user_id, prefix + message.text, parse_mode=ParseMode.HTML)
            save_message(ticket_id, 'admin', message.from_user.id, message.text, bot_token=bot_token)
        elif message.photo:
            caption = f"{prefix}{message.caption or ''}"
            await bot.send_photo(user_id, message.photo[-1].file_id, caption=caption, parse_mode=ParseMode.HTML)
            save_message(ticket_id, 'admin', message.from_user.id, f"[Фото] {message.caption or ''}", 
                        bot_token=bot_token)
        elif message.video:
            caption = f"{prefix}{message.caption or ''}"
            await bot.send_video(user_id, message.video.file_id, caption=caption, parse_mode=ParseMode.HTML)
            save_message(ticket_id, 'admin', message.from_user.id, f"[Видео] {message.caption or ''}", 
                        bot_token=bot_token)
        elif message.voice:
            await bot.send_voice(user_id, message.voice.file_id)
            await bot.send_message(user_id, prefix + "↑", parse_mode=ParseMode.HTML)
            save_message(ticket_id, 'admin', message.from_user.id, "[Голосовое сообщение]", bot_token=bot_token)
        elif message.document:
            caption = f"{prefix}{message.caption or ''}"
            await bot.send_document(user_id, message.document.file_id, caption=caption, parse_mode=ParseMode.HTML)
            save_message(ticket_id, 'admin', message.from_user.id, f"[Документ] {message.document.file_name}", 
                        bot_token=bot_token)
        else:
            await message.reply("❌ Неподдерживаемый тип сообщения")
            return
        
        update_has_responded(user_id, bot_token)
        
        await message.reply(
            f"✅ Ответ отправлен от имени {admin_name}",
            reply_markup=get_ticket_actions_keyboard(ticket_id, user_id)
        )
        
    except Exception as e:
        await message.reply(f"❌ Ошибка при отправке: {e}")
        logging.error(f"Ошибка ответа админа: {e}")

# --------------------- РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ ДЛЯ КЛОНОВ ---------------------
def register_clone_handlers(dp: Dispatcher, bot_token: str):
    """Регистрация обработчиков для клона бота"""
    
    @dp.message(CommandStart())
    async def clone_start(message: Message, state: FSMContext):
        if message.chat.type != 'private':
            await message.answer(
                "👋 Привет! Для вопросов и предложений пиши мне в личные сообщения.",
                reply_markup=get_group_menu()
            )
            return

        user = message.from_user
        
        # Проверяем, нужно ли авто-закрыть старые тикеты
        closed_count = auto_close_old_tickets(bot_token)
        if closed_count > 0:
            logging.info(f"Автоматически закрыто {closed_count} старых тикетов в клоне {bot_token}")

        # Если админ и не зарегистрирован
        if is_admin(user.id, bot_token) and not get_admin_name(user.id, bot_token):
            await message.answer(
                "👋 Добро пожаловать в панель поддержки!\n\n"
                "Введите своё имя в формате:\n"
                "Имя Ф.\n\n"
                "Пример: Иван З."
            )
            await state.set_state(AdminRegistration.waiting_for_name)
            return

        # Для обычных пользователей - главное меню с информацией о боте
        await message.answer(
            f"{format_bot_header(bot_token)}"
            f"👋 Добро пожаловать в поддержку!\n\n"
            f"Выберите действие:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu(bot_token)
        )
    
    @dp.message(Command("admin_menu"))
    async def clone_admin_menu(message: Message):
        if not is_admin(message.from_user.id, bot_token):
            await message.answer("❌ У вас нет доступа к этой команде.")
            return
        
        update_admin_activity(message.from_user.id, bot_token)
        
        await message.answer(
            f"{format_bot_header(bot_token)}"
            f"🔧 <b>Меню поддержки</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_admin_menu(bot_token)
        )
    
    @dp.message(Command("change_name"))
    async def clone_change_name(message: Message, state: FSMContext):
        if not is_admin(message.from_user.id, bot_token):
            await message.answer("❌ У вас нет доступа.")
            return
        
        await message.answer(
            "Введите новое имя в формате 'Имя Ф.' (пример: Иван З.):",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(AdminEditName.waiting_for_new_name)
    
    @dp.message(Command("reply"))
    async def clone_reply(message: Message):
        if not is_admin(message.from_user.id, bot_token):
            return
        
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Использование: /reply <номер_тикета> <текст>")
            return
        
        try:
            ticket_id = int(args[1].split()[0])
            reply_text = ' '.join(args[1].split()[1:])
        except:
            await message.answer("Неверный формат. Пример: /reply 123 Ваш ответ")
            return
        
        if not reply_text:
            await message.answer("Введите текст ответа")
            return
        
        # Получаем user_id по ticket_id
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM tickets WHERE id = ? AND bot_token = ?", 
                      (ticket_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            await message.answer(f"Тикет #{ticket_id} не найден")
            return
        
        user_id = row[0]
        admin_name = get_admin_name(message.from_user.id, bot_token)
        bot_info = get_bot_display_info(bot_token)
        
        if not admin_name:
            await message.answer("Вы не зарегистрированы. Используйте /start")
            return
        
        # Получаем бота-клона
        clone_bot, _, _ = active_bots.get(bot_token, (None, None, None))
        if not clone_bot:
            await message.answer("❌ Бот не активен")
            return
        
        try:
            prefix = f"✉️ <b>Ответ от {admin_name}</b>\n({bot_info['name']})\n\n"
            await clone_bot.send_message(user_id, prefix + reply_text, parse_mode=ParseMode.HTML)
            
            # Сохраняем в БД
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM tickets WHERE user_id = ? AND bot_token = ?", 
                          (user_id, bot_token))
            ticket_id_db = cursor.fetchone()[0]
            
            update_has_responded(user_id, bot_token)
            save_message(ticket_id_db, 'admin', message.from_user.id, reply_text, bot_token=bot_token)
            conn.close()
            
            await message.answer(f"✅ Ответ на тикет #{ticket_id} отправлен", 
                               reply_markup=get_ticket_actions_keyboard(ticket_id, user_id))
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
    
    @dp.message(Command("close"))
    async def clone_close(message: Message):
        if not is_admin(message.from_user.id, bot_token):
            await message.answer("❌ У вас нет доступа.")
            return
        
        args = message.text.split()
        if len(args) < 2:
            await message.answer("Использование: /close <номер_тикета>")
            return
        
        try:
            ticket_id = int(args[1])
        except:
            await message.answer("Неверный номер тикета")
            return
        
        # Получаем информацию о тикете
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, status FROM tickets WHERE id = ? AND bot_token = ?", 
                      (ticket_id, bot_token))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            await message.answer(f"Тикет #{ticket_id} не найден")
            return
        
        user_id, status = row
        
        if status == 'closed':
            await message.answer(f"Тикет #{ticket_id} уже закрыт")
            return
        
        bot_info = get_bot_display_info(bot_token)
        clone_bot, _, _ = active_bots.get(bot_token, (None, None, None))
        
        if close_ticket(ticket_id, message.from_user.id, bot_token):
            await message.answer(f"✅ Тикет #{ticket_id} закрыт")
            
            # Уведомляем пользователя
            if clone_bot:
                try:
                    await clone_bot.send_message(
                        user_id,
                        f"🔒 Ваше обращение #{ticket_id} в {bot_info['name']} было закрыто администратором.\n\n"
                        f"Оцените качество поддержки:",
                        reply_markup=get_rating_keyboard(ticket_id)
                    )
                except:
                    pass
        else:
            await message.answer(f"❌ Не удалось закрыть тикет #{ticket_id}")
    
    @dp.message(AdminRegistration.waiting_for_name)
    async def clone_register_admin(message: Message, state: FSMContext):
        name = message.text.strip()
        
        if not re.match(r'^[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z]\.$', name):
            await message.answer(
                "❌ Неверный формат. Пример: Иван З.\n"
                "Попробуйте ещё раз или отправьте /cancel"
            )
            return
        
        save_admin_name(message.from_user.id, name, bot_token)
        await state.clear()
        
        bot_info = get_bot_display_info(bot_token)
        
        await message.answer(
            f"✅ Вы зарегистрированы как <b>{name}</b> в {bot_info['name']}\n\n"
            f"Теперь вы можете:\n"
            f"• Отвечать пользователям (reply на их сообщения)\n"
            f"• Использовать /admin_menu для управления\n"
            f"• Просматривать историю чатов",
            parse_mode=ParseMode.HTML,
            reply_markup=get_admin_menu(bot_token)
        )
    
    @dp.message(AdminEditName.waiting_for_new_name)
    async def clone_change_name(message: Message, state: FSMContext):
        name = message.text.strip()
        
        if not re.match(r'^[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z]\.$', name):
            await message.answer(
                "❌ Неверный формат. Пример: Иван З.\n"
                "Попробуйте ещё раз:"
            )
            return
        
        save_admin_name(message.from_user.id, name, bot_token)
        await state.clear()
        
        await message.answer(
            f"✅ Имя изменено на <b>{name}</b>",
            parse_mode=ParseMode.HTML
        )
    
    @dp.callback_query()
    async def clone_callback(callback: CallbackQuery, state: FSMContext):
        data = callback.data
        
        # Категории
        if data.startswith("category:"):
            category = data.split(":")[1]
            user = callback.from_user
            
            ticket_id = get_or_create_ticket(user, category, bot_token)
            
            category_names = {
                'question': '❓ Вопрос',
                'problem': '⚠️ Проблема',
                'suggestion': '💡 Предложение',
                'other': '📌 Другое'
            }
            
            await callback.message.edit_text(
                f"{format_bot_header(bot_token)}"
                f"<b>Категория:</b> {category_names.get(category, category)}\n"
                f"<b>Номер обращения:</b> #{ticket_id}\n\n"
                f"📝 Опишите вашу проблему или вопрос.\n"
                f"Можно отправлять текст, фото, видео, альбомы.",
                parse_mode=ParseMode.HTML
            )
            
            await state.set_state(TicketStates.in_dialog)
            await callback.answer()
            return
        
        # Оценка
        if data.startswith("rate:"):
            _, rating, ticket_id = data.split(":")
            rating = int(rating)
            ticket_id = int(ticket_id)
            
            save_rating(ticket_id, rating, bot_token=bot_token)
            
            await callback.message.edit_text(
                f"✅ Спасибо за вашу оценку: {'⭐️' * rating}!\n"
                f"Если хотите оставить отзыв, напишите его сейчас.\n"
                f"Или отправьте /start для возврата в меню."
            )
            
            await state.set_state(TicketStates.waiting_feedback)
            await state.update_data(ticket_id=ticket_id, rating=rating)
            await callback.answer()
            return
        
        # Закрытие тикета
        if data.startswith("close:"):
            _, ticket_id, user_id = data.split(":")
            ticket_id = int(ticket_id)
            user_id = int(user_id)
            
            bot_info = get_bot_display_info(bot_token)
            clone_bot, _, _ = active_bots.get(bot_token, (None, None, None))
            
            if close_ticket(ticket_id, callback.from_user.id, bot_token):
                await callback.message.edit_text(f"✅ Тикет #{ticket_id} закрыт")
                
                # Уведомляем пользователя
                if clone_bot:
                    try:
                        await clone_bot.send_message(
                            user_id,
                            f"🔒 Ваше обращение #{ticket_id} в {bot_info['name']} было закрыто администратором.\n\n"
                            f"Оцените качество поддержки:",
                            reply_markup=get_rating_keyboard(ticket_id)
                        )
                    except:
                        pass
            else:
                await callback.message.edit_text(f"❌ Тикет уже закрыт или не найден")
            
            await callback.answer()
            return
        
        # Поддержка
        if data == "support:start":
            await callback.message.edit_text(
                f"{format_bot_header(bot_token)}"
                f"Выберите категорию обращения:",
                parse_mode=ParseMode.HTML,
                reply_markup=get_category_menu()
            )
        
        elif data == "support:cancel":
            await state.clear()
            await callback.message.edit_text(
                f"{format_bot_header(bot_token)}"
                f"❌ Обращение отменено.",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_menu(bot_token)
            )
        
        elif data == "support:continue":
            await state.set_state(TicketStates.in_dialog)
            await callback.message.edit_text(
                f"{format_bot_header(bot_token)}"
                f"📝 Продолжаем диалог. Напишите сообщение.",
                parse_mode=ParseMode.HTML
            )
        
        elif data == "menu:main":
            await state.clear()
            await callback.message.edit_text(
                f"{format_bot_header(bot_token)}"
                f"Главное меню:",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_menu(bot_token)
            )
        
        elif data == "info:about":
            await callback.message.answer(
                f"{format_bot_header(bot_token)}"
                f"ℹ️ <b>Информация о поддержке</b>\n\n"
                f"📌 <b>Правила:</b>\n"
                f"• Не отправляйте пустые сообщения и стикеры\n"
                f"• Описывайте проблему подробно\n"
                f"• Будьте вежливы\n"
                f"• Ожидайте ответа в рабочее время\n"
                f"• Не спамьте (блокировка)",
                parse_mode=ParseMode.HTML
            )
        
        # Админ-меню
        elif data == "admin:open_tickets":
            tickets = get_all_open_tickets(bot_token)
            if not tickets:
                await callback.message.answer(f"{format_bot_header(bot_token)}📭 Нет открытых тикетов")
                await callback.answer()
                return
            
            builder = InlineKeyboardBuilder()
            for t in tickets[:10]:
                short_name = t[3][:15] + "..." if len(t[3]) > 15 else t[3]
                builder.button(
                    text=f"#{t[0]} - {short_name} ({t[4]})", 
                    callback_data=f"admin:view_ticket_{t[0]}"
                )
            
            builder.button(text="◀️ Назад", callback_data="admin:back")
            builder.adjust(1)
            
            await callback.message.answer(
                f"{format_bot_header(bot_token)}"
                f"📂 <b>Открытые тикеты ({len(tickets)})</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup()
            )
        
        elif data == "admin:history":
            tickets = get_admin_tickets(callback.from_user.id, bot_token)
            if not tickets:
                await callback.message.answer(f"{format_bot_header(bot_token)}📭 У вас нет истории чатов.")
                await callback.answer()
                return
            
            builder = InlineKeyboardBuilder()
            for t in tickets[:10]:
                status_emoji = "🟢" if t[3] == 'open' else "🔴"
                builder.button(
                    text=f"{status_emoji} #{t[0]} - @{t[2] or 'без username'}", 
                    callback_data=f"admin:view_ticket_{t[0]}"
                )
            
            builder.button(text="◀️ Назад", callback_data="admin:back")
            builder.adjust(1)
            
            await callback.message.answer(
                f"{format_bot_header(bot_token)}"
                f"📜 <b>Ваша история чатов</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup()
            )
        
        elif data.startswith("admin:view_ticket_"):
            ticket_id = int(data.split("_")[-1])
            messages = get_ticket_messages(ticket_id, bot_token)
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, username, first_name, status FROM tickets WHERE id = ? AND bot_token = ?", 
                          (ticket_id, bot_token))
            ticket_info = cursor.fetchone()
            conn.close()
            
            if not ticket_info:
                await callback.message.answer("❌ Тикет не найден")
                await callback.answer()
                return
            
            user_id, username, first_name, status = ticket_info
            status_emoji = "🟢" if status == 'open' else "🔴"
            
            text = f"{format_bot_header(bot_token)}<b>Тикет #{ticket_id}</b> {status_emoji}\n"
            text += f"👤 {first_name} (@{username or 'нет'})\n"
            text += f"🆔 <code>{user_id}</code>\n"
            text += "─" * 20 + "\n\n"
            
            if not messages:
                text += "📭 Нет сообщений"
            else:
                for msg in messages:
                    sender_type, content, timestamp, media_group_id = msg
                    time_str = datetime.fromisoformat(timestamp).strftime("%d.%m %H:%M")
                    sender = "👤 Пользователь" if sender_type == 'user' else "👨‍💼 Админ"
                    media_mark = "📎 " if media_group_id else ""
                    text += f"[{time_str}] {sender}: {media_mark}{content or '[медиа]'}\n\n"
            
            if len(text) > 4000:
                text = text[:4000] + "...\n\n(сообщение обрезано)"
            
            await callback.message.answer(text, parse_mode=ParseMode.HTML)
        
        elif data == "admin:profile":
            profile = get_admin_profile(callback.from_user.id, bot_token)
            await callback.message.answer(profile, parse_mode=ParseMode.HTML)
        
        elif data == "admin:change_name":
            await callback.message.answer(
                "Введите новое имя в формате 'Имя Ф.' (пример: Иван З.):",
                reply_markup=get_cancel_keyboard()
            )
            await state.set_state(AdminEditName.waiting_for_new_name)
        
        elif data == "admin:search":
            await callback.message.answer(
                "🔍 Введите текст для поиска по сообщениям\n"
                "Формат: /search <текст>"
            )
        
        elif data == "admin:stats":
            stats = get_statistics(bot_token)
            bot_info = get_bot_display_info(bot_token)
            
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
                f"{format_bot_header(bot_token)}"
                f"📊 <b>СТАТИСТИКА</b>\n\n"
                f"📋 Всего тикетов: {stats['total_tickets']}\n"
                f"├ Открыто: {stats['open_tickets']}\n"
                f"└ Закрыто: {stats['closed_tickets']}\n\n"
                f"⭐️ Средняя оценка: {stats['avg_rating']}/5\n"
                f"⏱ Среднее время ответа: {response_time}"
            )
            
            await callback.message.answer(text, parse_mode=ParseMode.HTML)
        
        elif data == "admin:delete_account":
            delete_admin_account(callback.from_user.id, bot_token)
            await callback.message.answer(
                f"{format_bot_header(bot_token)}"
                f"🗑 Ваш аккаунт поддержки удалён.\n"
                f"Для восстановления используйте /start"
            )
        
        elif data == "admin:back":
            await callback.message.edit_text(
                f"{format_bot_header(bot_token)}"
                f"🔧 <b>Меню поддержки</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_admin_menu(bot_token)
            )
        
        await callback.answer()
    
    @dp.message(TicketStates.in_dialog, F.chat.type == 'private')
    async def clone_user_message(message: Message, state: FSMContext):
        user = message.from_user
        
        # Проверка на спам-блок
        blocked, block_msg = check_spam_block(user.id, bot_token)
        if blocked:
            await message.answer(block_msg)
            return
        
        # Проверка кулдауна
        cooldown, cooldown_msg = check_message_cooldown(user.id, bot_token)
        if cooldown:
            await message.answer(cooldown_msg)
            return
        
        # Проверка лимита сообщений без ответа
        limit_exceeded, limit_msg = check_message_limit(user.id, bot_token)
        if limit_exceeded:
            await message.answer(limit_msg)
            return
        
        ticket_status = get_ticket_status(user.id, bot_token)
        if ticket_status:
            status, has_responded = ticket_status
            if status == 'open' and has_responded == 0:
                await message.answer(
                    "⏳ Дождитесь ответа поддержки прежде чем отправить новое сообщение.\n"
                    "Спам может привести к блокировке."
                )
                return
        
        # Фильтр спама
        if message.sticker or message.animation or message.dice:
            await message.answer("❌ Пожалуйста, отправляйте текстовые сообщения или фото/видео по теме.")
            return
        
        if message.text and len(message.text.strip()) < 3 and not any(c.isalpha() for c in message.text):
            await message.answer("❌ Слишком короткое сообщение. Опишите проблему подробнее.")
            return
        
        # Получаем тикет
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, category FROM tickets WHERE user_id = ? AND bot_token = ?", 
                      (user.id, bot_token))
        row = cursor.fetchone()
        
        if row:
            ticket_id, category = row
        else:
            await state.clear()
            await message.answer(
                f"{format_bot_header(bot_token)}"
                f"Пожалуйста, сначала выберите категорию обращения:",
                parse_mode=ParseMode.HTML,
                reply_markup=get_category_menu()
            )
            conn.close()
            return
        
        conn.close()
        
        # Получаем бота-клона для отправки
        clone_bot, _, _ = active_bots.get(bot_token, (None, None, None))
        if not clone_bot:
            await message.answer("❌ Ошибка: бот не активен")
            return
        
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
                            msg.caption,
                            bot_token
                        )
                
                save_message(ticket_id, 'user', user.id, f"[Альбом] {messages[0].caption or ''}", 
                            message.media_group_id, bot_token)
                
                bot_info = get_bot_display_info(bot_token)
                
                user_info = (
                    f"<b>Тикет #{ticket_id}</b> (категория: {category})\n"
                    f"🤖 {bot_info['name']} ({bot_info['username']})\n"
                    f"<a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
                    f"ID: <code>{user.id}</code>\n"
                    f"@{user.username or 'нет'}\n"
                    f"──────────────────────\n"
                    f"<b>Альбом ({len(messages)} шт.)</b>\n"
                )
                
                # Получаем список админов
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute("SELECT admins FROM clone_bots WHERE token = ?", (bot_token,))
                row = cursor.fetchone()
                admin_ids = json.loads(row[0]) if row else []
                conn.close()
                
                for admin_id in admin_ids:
                    try:
                        await clone_bot.send_message(admin_id, user_info, parse_mode=ParseMode.HTML)
                        
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
                        
                        await clone_bot.send_media_group(admin_id, media_group)
                    except Exception as e:
                        logging.error(f"Ошибка отправки админу {admin_id}: {e}")
                
                await message.answer(
                    f"{format_bot_header(bot_token)}"
                    f"✅ Альбом отправлен в тикет #{ticket_id}.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_after_message_menu(bot_token)
                )
                
                update_message_time(user.id, bot_token)
                return
        
        # Обычное сообщение
        content = message.text or "[Медиа]"
        
        if message.text:
            save_message(ticket_id, 'user', user.id, message.text, bot_token=bot_token)
        elif message.photo:
            file_id = message.photo[-1].file_id
            save_message(ticket_id, 'user', user.id, f"[Фото] {message.caption or ''}", bot_token=bot_token)
            save_media_group(f"single_{message.message_id}", ticket_id, message.message_id, 
                            file_id, 'photo', message.caption, bot_token)
        elif message.video:
            file_id = message.video.file_id
            save_message(ticket_id, 'user', user.id, f"[Видео] {message.caption or ''}", bot_token=bot_token)
            save_media_group(f"single_{message.message_id}", ticket_id, message.message_id, 
                            file_id, 'video', message.caption, bot_token)
        elif message.voice:
            save_message(ticket_id, 'user', user.id, "[Голосовое сообщение]", bot_token=bot_token)
        elif message.document:
            save_message(ticket_id, 'user', user.id, f"[Документ] {message.document.file_name}", bot_token=bot_token)
        
        bot_info = get_bot_display_info(bot_token)
        
        user_info = (
            f"<b>Тикет #{ticket_id}</b> (категория: {category})\n"
            f"🤖 {bot_info['name']} ({bot_info['username']})\n"
            f"<a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
            f"ID: <code>{user.id}</code>\n"
            f"@{user.username or 'нет'}\n"
            f"──────────────────────\n"
        )
        
        # Получаем список админов
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT admins FROM clone_bots WHERE token = ?", (bot_token,))
        row = cursor.fetchone()
        admin_ids = json.loads(row[0]) if row else []
        conn.close()
        
        for admin_id in admin_ids:
            try:
                await clone_bot.send_message(admin_id, user_info, parse_mode=ParseMode.HTML)
                
                if message.text:
                    await clone_bot.send_message(admin_id, message.text)
                elif message.photo:
                    await clone_bot.send_photo(admin_id, message.photo[-1].file_id, caption=message.caption)
                elif message.video:
                    await clone_bot.send_video(admin_id, message.video.file_id, caption=message.caption)
                elif message.voice:
                    await clone_bot.send_voice(admin_id, message.voice.file_id)
                elif message.document:
                    await clone_bot.send_document(admin_id, message.document.file_id, caption=message.caption)
            except Exception as e:
                logging.error(f"Ошибка отправки админу {admin_id}: {e}")
        
        await message.answer(
            f"{format_bot_header(bot_token)}"
            f"✅ Сообщение отправлено в тикет #{ticket_id}.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_after_message_menu(bot_token)
        )
        
        update_message_time(user.id, bot_token)
        
        if ticket_status and ticket_status[1] == 1:
            reset_has_responded(user.id, bot_token)
    
    @dp.message(TicketStates.waiting_feedback)
    async def clone_feedback(message: Message, state: FSMContext):
        data = await state.get_data()
        ticket_id = data.get('ticket_id')
        rating = data.get('rating')
        
        if message.text:
            save_rating(ticket_id, rating, message.text, bot_token)
            await message.answer(
                f"{format_bot_header(bot_token)}"
                f"✅ Спасибо за ваш отзыв!\n"
                f"Он поможет нам стать лучше."
            )
        else:
            await message.answer("Отзыв сохранен без комментария.")
        
        await state.clear()
        await message.answer(
            f"{format_bot_header(bot_token)}"
            f"Главное меню:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu(bot_token)
        )
    
    @dp.message(lambda m: is_admin(m.from_user.id, bot_token) and m.reply_to_message is not None)
    async def clone_admin_reply(message: Message):
        replied = message.reply_to_message
        
        # Определяем ID пользователя
        user_id = None
        
        clone_bot, _, _ = active_bots.get(bot_token, (None, None, None))
        if not clone_bot:
            await message.reply("❌ Бот не активен")
            return
        
        if replied.from_user.id == clone_bot.id and replied.forward_from:
            user_id = replied.forward_from.id
        elif replied.forward_from:
            user_id = replied.forward_from.id
        elif replied.text and "ID: <code>" in replied.text:
            match = re.search(r'ID: <code>(\d+)</code>', replied.text)
            if match:
                user_id = int(match.group(1))
        
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
        
        update_admin_activity(message.from_user.id, bot_token)
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tickets WHERE user_id = ? AND bot_token = ?", 
                      (user_id, bot_token))
        row = cursor.fetchone()
        
        if not row:
            await message.reply("❌ Тикет не найден")
            conn.close()
            return
        
        ticket_id = row[0]
        conn.close()
        
        bot_info = get_bot_display_info(bot_token)
        
        try:
            prefix = f"✉️ <b>Ответ от {admin_name}</b>\n({bot_info['name']})\n\n"
            
            if message.text:
                await clone_bot.send_message(user_id, prefix + message.text, parse_mode=ParseMode.HTML)
                save_message(ticket_id, 'admin', message.from_user.id, message.text, bot_token=bot_token)
            elif message.photo:
                caption = f"{prefix}{message.caption or ''}"
                await clone_bot.send_photo(user_id, message.photo[-1].file_id, caption=caption, parse_mode=ParseMode.HTML)
                save_message(ticket_id, 'admin', message.from_user.id, f"[Фото] {message.caption or ''}", 
                            bot_token=bot_token)
            elif message.video:
                caption = f"{prefix}{message.caption or ''}"
                await clone_bot.send_video(user_id, message.video.file_id, caption=caption, parse_mode=ParseMode.HTML)
                save_message(ticket_id, 'admin', message.from_user.id, f"[Видео] {message.caption or ''}", 
                            bot_token=bot_token)
            elif message.voice:
                await clone_bot.send_voice(user_id, message.voice.file_id)
                await clone_bot.send_message(user_id, prefix + "↑", parse_mode=ParseMode.HTML)
                save_message(ticket_id, 'admin', message.from_user.id, "[Голосовое сообщение]", bot_token=bot_token)
            elif message.document:
                caption = f"{prefix}{message.caption or ''}"
                await clone_bot.send_document(user_id, message.document.file_id, caption=caption, parse_mode=ParseMode.HTML)
                save_message(ticket_id, 'admin', message.from_user.id, f"[Документ] {message.document.file_name}", 
                            bot_token=bot_token)
            else:
                await message.reply("❌ Неподдерживаемый тип сообщения")
                return
            
            update_has_responded(user_id, bot_token)
            
            await message.reply(
                f"✅ Ответ отправлен от имени {admin_name}",
                reply_markup=get_ticket_actions_keyboard(ticket_id, user_id)
            )
            
        except Exception as e:
            await message.reply(f"❌ Ошибка при отправке: {e}")
            logging.error(f"Ошибка ответа админа: {e}")

# --------------------- ПЛАНИРОВЩИК ЗАДАЧ ---------------------
async def scheduler():
    """Планировщик для периодических задач"""
    while True:
        await asyncio.sleep(3600)  # Каждый час
        try:
            # Авто-закрытие для основного бота
            closed_main = auto_close_old_tickets('main')
            if closed_main > 0:
                logging.info(f"Авто-закрыто {closed_main} тикетов в основном боте")
            
            # Авто-закрытие для клонов
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT token FROM clone_bots WHERE status = 'active'")
            clones = cursor.fetchall()
            conn.close()
            
            for clone in clones:
                token = clone[0]
                closed = auto_close_old_tickets(token)
                if closed > 0:
                    logging.info(f"Авто-закрыто {closed} тикетов в клоне {token}")
        except Exception as e:
            logging.error(f"Ошибка в планировщике: {e}")

# --------------------- ЗАПУСК ---------------------
async def main():
    """Основная функция запуска бота"""
    logging.info("Бот поддержки запускается...")
    
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
        await asyncio.sleep(1)  # Небольшая задержка между запусками
    
    # Запускаем планировщик
    asyncio.create_task(scheduler())
    
    # Запускаем polling для основного бота
    logging.info("Основной бот запущен")
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
