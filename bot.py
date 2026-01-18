import asyncio
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Any
import random

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, ChatMemberUpdated, InlineKeyboardMarkup,
    InlineKeyboardButton, CallbackQuery, ChatPermissions
)
from aiogram.filters import Command, CommandStart, ChatMemberUpdatedFilter, JOIN_TRANSITION, LEAVE_TRANSITION
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ============ НАСТРОЙКИ БОТА ============
BOT_TOKEN = "8557190026:AAHAhHOxPQ4HlFHbGokpyTFoQ2R_a634rE4"
ADMIN_PASSWORD = "vanezypuls13579cod"
ADMIN_IDS = [6708209142]
DATABASE_NAME = "bot.db"
BOT_USERNAME = "PulsOfficialManager_bot"

# Время жизни админ-сессии (25 минут)
ADMIN_SESSION_TIMEOUT = 25 * 60

# Минимальное и максимальное время наказаний
MIN_PUNISHMENT_TIME = timedelta(seconds=30)
MAX_PUNISHMENT_TIME = timedelta(days=3650)

# ============ ИНИЦИАЛИЗАЦИЯ БОТА ============
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ============ СОСТОЯНИЯ FSM ============
class AdminStates(StatesGroup):
    waiting_password = State()
    waiting_target_user = State()
    waiting_coins_amount = State()
    waiting_dollars_amount = State()
    waiting_broadcast = State()
    waiting_currency_type = State()
    waiting_log_chat = State()
    waiting_admin_target = State()
    waiting_admin_functions = State()

class ShopStates(StatesGroup):
    buying_temp_attempts = State()
    buying_luck = State()

class BalanceStates(StatesGroup):
    checking_other_user = State()

class RuleStates(StatesGroup):
    waiting_rule_text = State()

# Словари для хранения админ-сессий и сообщений
admin_sessions: Dict[int, datetime] = {}
admin_messages: Dict[int, List[int]] = {}

# ============ ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ============
def init_database():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        coins INTEGER DEFAULT 0,
        dollars INTEGER DEFAULT 0,
        last_game TIMESTAMP,
        last_work TIMESTAMP,
        game_count INTEGER DEFAULT 0,
        work_count INTEGER DEFAULT 0,
        game_reset_time TIMESTAMP,
        work_reset_time TIMESTAMP,
        game_perm_attempts INTEGER DEFAULT 0,
        work_perm_attempts INTEGER DEFAULT 0,
        game_temp_attempts INTEGER DEFAULT 0,
        work_temp_attempts INTEGER DEFAULT 0,
        luck_active_until TIMESTAMP,
        is_bot_admin BOOLEAN DEFAULT 0,
        last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        coins_weekly INTEGER DEFAULT 0,
        dollars_weekly INTEGER DEFAULT 0,
        coins_daily INTEGER DEFAULT 0,
        dollars_daily INTEGER DEFAULT 0
    )
    ''')
    
    # Таблица ограничений
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS restrictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        chat_id INTEGER,
        restriction_type TEXT,
        until TIMESTAMP,
        reason TEXT,
        rule_number INTEGER,
        moderator_id INTEGER,
        moderator_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        message_id INTEGER,
        log_message_id INTEGER,
        status TEXT DEFAULT 'active'
    )
    ''')
    
    # Таблица прав модераторов в группах
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS group_moderator_rights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        chat_id INTEGER,
        can_mute BOOLEAN DEFAULT 0,
        can_ban BOOLEAN DEFAULT 0,
        can_kick BOOLEAN DEFAULT 0,
        can_delete BOOLEAN DEFAULT 0,
        can_add_rules BOOLEAN DEFAULT 0,
        can_edit_rules BOOLEAN DEFAULT 0,
        can_delete_rules BOOLEAN DEFAULT 0,
        granted_by INTEGER,
        granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица для блокировки админ-панели
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admin_lock (
        user_id INTEGER PRIMARY KEY,
        failed_attempts INTEGER DEFAULT 0,
        lock_until TIMESTAMP,
        last_attempt TIMESTAMP
    )
    ''')
    
    # Таблица для лог-чатов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS log_chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        chat_id INTEGER,
        log_chat_id INTEGER,
        chat_title TEXT,
        chat_username TEXT,
        set_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица правил групп
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS group_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        rule_number INTEGER,
        punishment_type TEXT,
        min_time TEXT,
        max_time TEXT,
        short_explanation TEXT,
        full_explanation TEXT,
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица админов бота
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS bot_admins (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        can_access_panel BOOLEAN DEFAULT 0,
        can_broadcast BOOLEAN DEFAULT 0,
        can_give_currency BOOLEAN DEFAULT 0,
        can_manage_admins BOOLEAN DEFAULT 0,
        can_moderate_anywhere BOOLEAN DEFAULT 0,
        added_by INTEGER,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица репортов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        reporter_id INTEGER,
        reporter_name TEXT,
        target_id INTEGER,
        target_name TEXT,
        reason TEXT,
        message_id INTEGER,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Индексы
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_rules_chat ON group_rules(chat_id, rule_number)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_log_chats_user ON log_chats(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_active ON users(last_active)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_restrictions_active ON restrictions(status, until)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_coins ON users(coins)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_dollars ON users(dollars)')
    
    conn.commit()
    conn.close()

init_database()

# ============ УТИЛИТЫ РАБОТЫ С БД ============
class Database:
    @staticmethod
    def get_connection():
        return sqlite3.connect(DATABASE_NAME)
    
    @staticmethod
    def get_user(user_id: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        conn.close()
        return user
    
    @staticmethod
    def create_user(user_id: int, username: str, full_name: str, is_bot_admin: bool = False):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, full_name, is_bot_admin, last_active)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, username, full_name, 1 if is_bot_admin else 0))
        conn.commit()
        conn.close()
    
    @staticmethod
    def update_user(user_id: int, **kwargs):
        if not kwargs:
            return
        conn = Database.get_connection()
        cursor = conn.cursor()
        set_clause = ", ".join([f"{key} = ?" for key in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]
        cursor.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_all_users():
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        users = [row[0] for row in cursor.fetchall()]
        conn.close()
        return users
    
    @staticmethod
    def get_active_users_today():
        conn = Database.get_connection()
        cursor = conn.cursor()
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute('''
            SELECT COUNT(DISTINCT user_id) FROM users 
            WHERE DATE(last_active) = ?
        ''', (today,))
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    @staticmethod
    def get_total_coins():
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT SUM(coins) FROM users')
        total = cursor.fetchone()[0] or 0
        conn.close()
        return total
    
    @staticmethod
    def get_total_dollars():
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT SUM(dollars) FROM users')
        total = cursor.fetchone()[0] or 0
        conn.close()
        return total
    
    @staticmethod
    def add_coins_to_user(user_id: int, amount: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET coins = coins + ? WHERE user_id = ?', (amount, user_id))
        conn.commit()
        conn.close()
    
    @staticmethod
    def add_dollars_to_user(user_id: int, amount: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET dollars = dollars + ? WHERE user_id = ?', (amount, user_id))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_log_chat(user_id: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT chat_id, log_chat_id, chat_title, chat_username FROM log_chats WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result
    
    @staticmethod
    def set_log_chat(user_id: int, chat_id: int, log_chat_id: int, chat_title: str, chat_username: str = None):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM log_chats WHERE user_id = ?', (user_id,))
        cursor.execute('''
            INSERT INTO log_chats (user_id, chat_id, log_chat_id, chat_title, chat_username)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, chat_id, log_chat_id, chat_title, chat_username))
        conn.commit()
        conn.close()
    
    @staticmethod
    def remove_log_chat(user_id: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM log_chats WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
    
    @staticmethod
    def add_restriction(user_id: int, chat_id: int, restriction_type: str,
                       until: datetime, reason: str, rule_number: int, 
                       moderator_id: int, moderator_name: str, message_id: int = None, log_message_id: int = None):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO restrictions (user_id, chat_id, restriction_type, until, reason, 
                                     rule_number, moderator_id, moderator_name, message_id, log_message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, chat_id, restriction_type, until, reason, rule_number, 
              moderator_id, moderator_name, message_id, log_message_id))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_group_moderator_rights(user_id: int, chat_id: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT can_mute, can_ban, can_kick, can_delete, can_add_rules, can_edit_rules, can_delete_rules 
            FROM group_moderator_rights 
            WHERE user_id = ? AND chat_id = ?
        ''', (user_id, chat_id))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'mute': bool(result[0]),
                'ban': bool(result[1]),
                'kick': bool(result[2]),
                'delete': bool(result[3]),
                'add_rules': bool(result[4]),
                'edit_rules': bool(result[5]),
                'delete_rules': bool(result[6])
            }
        return {'mute': False, 'ban': False, 'kick': False, 'delete': False, 
                'add_rules': False, 'edit_rules': False, 'delete_rules': False}
    
    @staticmethod
    def check_group_moderator_right(user_id: int, chat_id: int, right_type: str) -> bool:
        rights = Database.get_group_moderator_rights(user_id, chat_id)
        return rights.get(right_type, False)
    
    @staticmethod
    def add_group_moderator_right(user_id: int, chat_id: int, rights: dict, granted_by: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM group_moderator_rights WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
        
        cursor.execute('''
            INSERT INTO group_moderator_rights (user_id, chat_id, can_mute, can_ban, can_kick, 
                                               can_delete, can_add_rules, can_edit_rules, can_delete_rules, granted_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, chat_id, 
              rights.get('mute', 0), 
              rights.get('ban', 0), 
              rights.get('kick', 0),
              rights.get('delete', 0),
              rights.get('add_rules', 0),
              rights.get('edit_rules', 0),
              rights.get('delete_rules', 0),
              granted_by))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_top_players_by_coins(limit: int = 10, period: str = 'all'):
        conn = Database.get_connection()
        cursor = conn.cursor()
        
        if period == 'daily':
            cursor.execute('''
                SELECT user_id, username, full_name, coins_daily 
                FROM users 
                WHERE coins_daily > 0 
                ORDER BY coins_daily DESC 
                LIMIT ?
            ''', (limit,))
        elif period == 'weekly':
            cursor.execute('''
                SELECT user_id, username, full_name, coins_weekly 
                FROM users 
                WHERE coins_weekly > 0 
                ORDER BY coins_weekly DESC 
                LIMIT ?
            ''', (limit,))
        else:  # all
            cursor.execute('''
                SELECT user_id, username, full_name, coins 
                FROM users 
                WHERE coins > 0 
                ORDER BY coins DESC 
                LIMIT ?
            ''', (limit,))
        
        players = cursor.fetchall()
        conn.close()
        return players
    
    @staticmethod
    def get_top_players_by_dollars(limit: int = 10, period: str = 'all'):
        conn = Database.get_connection()
        cursor = conn.cursor()
        
        if period == 'daily':
            cursor.execute('''
                SELECT user_id, username, full_name, dollars_daily 
                FROM users 
                WHERE dollars_daily > 0 
                ORDER BY dollars_daily DESC 
                LIMIT ?
            ''', (limit,))
        elif period == 'weekly':
            cursor.execute('''
                SELECT user_id, username, full_name, dollars_weekly 
                FROM users 
                WHERE dollars_weekly > 0 
                ORDER BY dollars_weekly DESC 
                LIMIT ?
            ''', (limit,))
        else:  # all
            cursor.execute('''
                SELECT user_id, username, full_name, dollars 
                FROM users 
                WHERE dollars > 0 
                ORDER BY dollars DESC 
                LIMIT ?
            ''', (limit,))
        
        players = cursor.fetchall()
        conn.close()
        return players
    
    @staticmethod
    def get_bot_admin(user_id: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM bot_admins WHERE user_id = ?', (user_id,))
        admin = cursor.fetchone()
        conn.close()
        return admin
    
    @staticmethod
    def get_all_bot_admins():
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, full_name FROM bot_admins')
        admins = cursor.fetchall()
        conn.close()
        return admins
    
    @staticmethod
    def add_bot_admin(user_id: int, username: str, full_name: str, added_by: int, **kwargs):
        conn = Database.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM bot_admins WHERE user_id = ?', (user_id,))
        
        cursor.execute('''
            INSERT INTO bot_admins (user_id, username, full_name, 
                                  can_access_panel, can_broadcast, can_give_currency, 
                                  can_manage_admins, can_moderate_anywhere, added_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, username, full_name,
              kwargs.get('can_access_panel', 0),
              kwargs.get('can_broadcast', 0),
              kwargs.get('can_give_currency', 0),
              kwargs.get('can_manage_admins', 0),
              kwargs.get('can_moderate_anywhere', 0),
              added_by))
        
        cursor.execute('UPDATE users SET is_bot_admin = 1 WHERE user_id = ?', (user_id,))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def update_bot_admin(user_id: int, **kwargs):
        if not kwargs:
            return
        conn = Database.get_connection()
        cursor = conn.cursor()
        set_clause = ", ".join([f"{key} = ?" for key in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]
        cursor.execute(f"UPDATE bot_admins SET {set_clause} WHERE user_id = ?", values)
        conn.commit()
        conn.close()
    
    @staticmethod
    def remove_bot_admin(user_id: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM bot_admins WHERE user_id = ?', (user_id,))
        cursor.execute('UPDATE users SET is_bot_admin = 0 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
    
    @staticmethod
    def can_moderate_anywhere(user_id: int) -> bool:
        admin = Database.get_bot_admin(user_id)
        if admin and admin[8] == 1:
            return True
        return False
    
    @staticmethod
    def get_group_rules(chat_id: int, page: int = 0, limit: int = 5):
        conn = Database.get_connection()
        cursor = conn.cursor()
        offset = page * limit
        cursor.execute('''
            SELECT * FROM group_rules WHERE chat_id = ? 
            ORDER BY rule_number 
            LIMIT ? OFFSET ?
        ''', (chat_id, limit, offset))
        rules = cursor.fetchall()
        conn.close()
        return rules
    
    @staticmethod
    def get_group_rule(chat_id: int, rule_number: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM group_rules WHERE chat_id = ? AND rule_number = ?', (chat_id, rule_number))
        rule = cursor.fetchone()
        conn.close()
        return rule
    
    @staticmethod
    def add_group_rule(chat_id: int, rule_number: int, punishment_type: str, min_time: str, 
                      max_time: str, short_explanation: str, full_explanation: str, created_by: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM group_rules WHERE chat_id = ? AND rule_number = ?', (chat_id, rule_number))
        
        cursor.execute('''
            INSERT INTO group_rules (chat_id, rule_number, punishment_type, min_time, max_time, 
                                   short_explanation, full_explanation, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (chat_id, rule_number, punishment_type, min_time, max_time, 
              short_explanation, full_explanation, created_by))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def delete_group_rule(chat_id: int, rule_number: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM group_rules WHERE chat_id = ? AND rule_number = ?', (chat_id, rule_number))
        
        cursor.execute('''
            UPDATE group_rules SET rule_number = rule_number - 1 
            WHERE chat_id = ? AND rule_number > ?
        ''', (chat_id, rule_number))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def count_group_rules(chat_id: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM group_rules WHERE chat_id = ?', (chat_id,))
        count = cursor.fetchone()[0]
        conn.close()
        return count

# ============ УТИЛИТЫ ============
class Utils:
    EMOJIS = {
        'success': ["✅", "✨", "🌟", "🎉", "🔥", "💫", "⚡", "🎊", "🏆", "💖"],
        'error': ["❌", "🚫", "⛔", "⚠️", "💥", "💔", "😢", "🙅", "🚨", "🛑"],
        'info': ["ℹ️", "📋", "📝", "📊", "🔍", "💡", "📌", "📍", "🗒️", "📄"],
        'moderation': ["🔇", "🔨", "👢", "👮", "⚖️", "🚔", "🔒", "🗝️", "🛡️", "⚔️"],
        'greeting': ["👋", "🤗", "😊", "🎈", "🎁", "🎀", "💝", "💌", "💐", "🌸"],
        'game': ["🎮", "🎲", "🕹️", "👾", "🎯", "🏅", "🥇", "🥈", "🥉", "💰"],
        'shop': ["🛒", "🏪", "💳", "💰", "💎", "👑", "⭐", "💫", "✨", "🎁"],
        'random': ["🎉", "✨", "🌟", "🎊", "🎈", "💫", "🔥", "💥", "⭐", "😊"]
    }
    
    @staticmethod
    def get_emoji(category: str = 'random'):
        if category in Utils.EMOJIS:
            return random.choice(Utils.EMOJIS[category])
        return random.choice(Utils.EMOJIS['random'])
    
    @staticmethod
    def parse_time(time_str: str) -> Optional[timedelta]:
        if not time_str:
            return None
            
        time_str = time_str.lower().strip()
        
        if time_str.isdigit():
            return timedelta(minutes=int(time_str))
        
        multipliers = {
            's': 1, 'сек': 1, 'с': 1, 'секунд': 1, 'секунды': 1,
            'm': 60, 'мин': 60, 'м': 60, 'минут': 60, 'минуты': 60,
            'h': 3600, 'час': 3600, 'ч': 3600, 'часов': 3600,
            'd': 86400, 'дней': 86400, 'д': 86400, 'день': 86400, 'дня': 86400
        }
        
        try:
            for suffix, multiplier in multipliers.items():
                if time_str.endswith(suffix):
                    num_str = time_str[:-len(suffix)].strip()
                    if num_str.isdigit():
                        num = int(num_str)
                        return timedelta(seconds=num * multiplier)
            
            return timedelta(seconds=int(time_str))
        except:
            return None
    
    @staticmethod
    def format_time(delta: timedelta) -> str:
        total_seconds = int(delta.total_seconds())
        
        if total_seconds < 60:
            return f"{total_seconds} секунд"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes} минут {seconds} секунд"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours} часов {minutes} минут"
        else:
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            return f"{days} дней {hours} часов"
    
    @staticmethod
    def validate_punishment_time(duration: timedelta) -> Tuple[bool, str]:
        if duration < MIN_PUNISHMENT_TIME:
            return False, f"Минимальное время наказания: {Utils.format_time(MIN_PUNISHMENT_TIME)}"
        if duration > MAX_PUNISHMENT_TIME:
            return False, f"Максимальное время наказания: {Utils.format_time(MAX_PUNISHMENT_TIME)}"
        return True, ""

# ============ КЛАВИАТУРЫ ============
class Keyboards:
    @staticmethod
    def get_main_keyboard(user_id: int):
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🎮 Развлечения", callback_data="entertainment")
        keyboard.button(text="📜 Правила бота", callback_data="rules")
        keyboard.button(text="🛒 Магазин", callback_data="shop")
        
        is_bot_admin = Database.get_bot_admin(user_id)
        if is_bot_admin and is_bot_admin[3] == 1:
            keyboard.button(text="⚙️ Админ-панель", callback_data="admin_panel")
        
        keyboard.button(text="💰 Баланс", callback_data="balance")
        keyboard.button(text="🏆 Топ игроков", callback_data="top_players_menu")
        keyboard.button(text="📊 Лог-чат", callback_data="log_chat_menu")
        keyboard.button(text="➕ Добавить в группу", url=f"https://t.me/{BOT_USERNAME}?startgroup=true")
        
        if is_bot_admin and is_bot_admin[3] == 1:
            keyboard.adjust(2, 2, 2, 1, 1)
        else:
            keyboard.adjust(1, 1, 1, 2, 1)
        
        return keyboard.as_markup()
    
    @staticmethod
    def get_entertainment_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🎮 Играть", callback_data="play_game")
        keyboard.button(text="💼 Работать", callback_data="work_game")
        keyboard.button(text="🍀 Купить удачу", callback_data="buy_luck")
        keyboard.button(text="🔙 Назад", callback_data="main_menu")
        keyboard.adjust(2, 1, 1)
        return keyboard.as_markup()
    
    @staticmethod
    def get_admin_keyboard(user_id: int):
        keyboard = InlineKeyboardBuilder()
        
        admin_data = Database.get_bot_admin(user_id)
        if not admin_data:
            return None
        
        if admin_data[3] == 1:
            keyboard.button(text="📊 Статистика", callback_data="admin_stats")
        
        if admin_data[4] == 1:
            keyboard.button(text="📣 Рассылка", callback_data="admin_broadcast")
        
        if admin_data[5] == 1:
            keyboard.button(text="💰 Выдать валюту", callback_data="admin_give_currency")
        
        if admin_data[6] == 1:
            keyboard.button(text="👑 Управление админами", callback_data="admin_manage_admins")
        
        keyboard.button(text="🔙 Выйти из админ-панели", callback_data="admin_exit")
        
        return keyboard.as_markup()
    
    @staticmethod
    def get_back_to_admin_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🔙 Назад в админ-панель", callback_data="admin_back_to_panel")
        return keyboard.as_markup()
    
    @staticmethod
    def get_back_to_main_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🔙 Назад в меню", callback_data="main_menu")
        return keyboard.as_markup()
    
    @staticmethod
    def get_cancel_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="❌ Отмена", callback_data="cancel")
        return keyboard.as_markup()
    
    @staticmethod
    def get_shop_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🎮 Попытки (Играть)", callback_data="shop_game_attempts")
        keyboard.button(text="💼 Попытки (Работать)", callback_data="shop_work_attempts")
        keyboard.button(text="👑 VIP-статус", callback_data="shop_vip")
        keyboard.button(text="🔙 Назад", callback_data="main_menu")
        keyboard.adjust(2, 1, 1)
        return keyboard.as_markup()
    
    @staticmethod
    def get_game_attempts_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🔄 Обычные попытки", callback_data="buy_temp_game")
        keyboard.button(text="⭐ Перманентные попытки", callback_data="buy_perm_game")
        keyboard.button(text="🔙 Назад", callback_data="shop")
        keyboard.adjust(1, 1, 1)
        return keyboard.as_markup()
    
    @staticmethod
    def get_temp_attempts_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="1 попытка (30 коинов)", callback_data="temp_1")
        keyboard.button(text="3 попытки (80 коинов)", callback_data="temp_3")
        keyboard.button(text="5 попыток (120 коинов)", callback_data="temp_5")
        keyboard.button(text="10 попыток (200 коинов)", callback_data="temp_10")
        keyboard.button(text="🔙 Назад", callback_data="shop_game_attempts")
        keyboard.adjust(2, 2, 1)
        return keyboard.as_markup()
    
    @staticmethod
    def get_vip_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="👑 1 месяц (1000 коинов + 500$)", callback_data="vip_1")
        keyboard.button(text="👑 2 месяца (2000 коинов + 1000$)", callback_data="vip_2")
        keyboard.button(text="👑 5 месяцев (5000 коинов + 2500$)", callback_data="vip_5")
        keyboard.button(text="👑 1 год (12000 коинов + 6000$)", callback_data="vip_12")
        keyboard.button(text="🔙 Назад", callback_data="shop")
        keyboard.adjust(2, 2, 1)
        return keyboard.as_markup()
    
    @staticmethod
    def get_log_chat_keyboard(has_log_chat: bool = False, chat_title: str = None):
        keyboard = InlineKeyboardBuilder()
        
        if has_log_chat and chat_title:
            keyboard.button(text=f"📊 {chat_title}", callback_data="log_chat_manage")
        else:
            keyboard.button(text="➕ Добавить группу для логов", callback_data="log_chat_add")
        
        keyboard.button(text="🔙 Назад", callback_data="main_menu")
        keyboard.adjust(1, 1)
        return keyboard.as_markup()
    
    @staticmethod
    def get_log_chat_manage_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🗑️ Удалить группу", callback_data="log_chat_remove")
        keyboard.button(text="🔙 Назад", callback_data="log_chat_menu")
        keyboard.adjust(1, 1)
        return keyboard.as_markup()
    
    @staticmethod
    def get_yes_no_keyboard(action: str):
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="✅ Да", callback_data=f"confirm_{action}")
        keyboard.button(text="❌ Нет", callback_data=f"cancel_{action}")
        return keyboard.as_markup()
    
    @staticmethod
    def get_currency_type_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🎮 Puls Coins", callback_data="give_coins")
        keyboard.button(text="💵 Доллары", callback_data="give_dollars")
        keyboard.button(text="🔙 Назад", callback_data="admin_back_to_panel")
        keyboard.adjust(2, 1)
        return keyboard.as_markup()
    
    @staticmethod
    def get_top_players_menu_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🎮 Топ по Puls Coins", callback_data="top_coins")
        keyboard.button(text="💵 Топ по Долларам", callback_data="top_dollars")
        keyboard.button(text="🔙 Назад", callback_data="main_menu")
        keyboard.adjust(1, 1, 1)
        return keyboard.as_markup()
    
    @staticmethod
    def get_top_period_keyboard(top_type: str):
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="📅 За день", callback_data=f"top_{top_type}_daily")
        keyboard.button(text="📆 За неделю", callback_data=f"top_{top_type}_weekly")
        keyboard.button(text="🏆 За всё время", callback_data=f"top_{top_type}_all")
        keyboard.button(text="🔙 Назад", callback_data="top_players_menu")
        keyboard.adjust(1, 1, 1)
        return keyboard.as_markup()
    
    @staticmethod
    def get_remove_restriction_keyboard(restriction_id: int):
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="✅ Снять ограничение", callback_data=f"remove_{restriction_id}")
        return keyboard.as_markup()

# ============ ФУНКЦИИ ПРОВЕРКИ СЕССИЙ ============
def check_admin_session(user_id: int) -> Tuple[bool, Optional[str]]:
    if user_id not in admin_sessions:
        return False, "🔐 Сессия не активна. Войдите заново."
    
    session_time = admin_sessions[user_id]
    if (datetime.now() - session_time).total_seconds() > ADMIN_SESSION_TIMEOUT:
        remove_admin_session(user_id)
        return False, "⏰ Сессия истекла (таймаут 25 минут). Войдите заново."
    
    admin_sessions[user_id] = datetime.now()
    return True, None

def add_admin_session(user_id: int):
    admin_sessions[user_id] = datetime.now()
    admin_messages[user_id] = []

def remove_admin_session(user_id: int):
    if user_id in admin_sessions:
        del admin_sessions[user_id]
    
    if user_id in admin_messages:
        for msg_id in admin_messages[user_id]:
            try:
                asyncio.create_task(bot.delete_message(user_id, msg_id))
            except:
                pass
        del admin_messages[user_id]

def add_admin_message(user_id: int, message_id: int):
    if user_id not in admin_messages:
        admin_messages[user_id] = []
    admin_messages[user_id].append(message_id)

# ============ ФУНКЦИИ ЛОГОВ ============
async def send_moderation_log(chat_id: int, action: str, target_user: dict, moderator: dict, 
                            duration: timedelta = None, reason: str = None, rule_number: int = None,
                            message_id: int = None, is_removed: bool = False, restriction_id: int = None):
    """Отправляет лог модерации в указанный чат"""
    try:
        log_chat = Database.get_log_chat(moderator['id'])
        if not log_chat:
            return None
        
        log_chat_id = log_chat[1]
        
        action_emojis = {
            'mute': '🔇',
            'ban': '🔨',
            'kick': '👢',
            'delete': '🗑️',
            'report': '🚨',
            'unmute': '🔊',
            'unban': '🔓'
        }
        
        action_names = {
            'mute': 'МУТ',
            'ban': 'БАН',
            'kick': 'КИК',
            'delete': 'УДАЛЕНИЕ',
            'report': 'РЕПОРТ',
            'unmute': 'СНЯТИЕ МУТА',
            'unban': 'СНЯТИЕ БАНА'
        }
        
        emoji = action_emojis.get(action, '📝')
        action_name = action_names.get(action, action.upper())
        
        log_message = f"{emoji} <b>{action_name}</b>\n\n"
        
        if is_removed:
            log_message += f"<b>Действие:</b> Снято ограничение\n"
        else:
            log_message += f"<b>Действие:</b> {action_name}\n"
        
        log_message += f"<b>Пользователь:</b> {target_user['full_name']}\n"
        log_message += f"<b>ID пользователя:</b> <code>{target_user['id']}</code>\n"
        
        if target_user.get('username'):
            log_message += f"<b>Username:</b> @{target_user['username']}\n"
        
        log_message += f"<b>Модератор:</b> {moderator['full_name']}\n"
        log_message += f"<b>ID модератора:</b> <code>{moderator['id']}</code>\n"
        
        if moderator.get('username'):
            log_message += f"<b>Username модератора:</b> @{moderator['username']}\n"
        
        if duration and not is_removed:
            log_message += f"<b>Длительность:</b> {Utils.format_time(duration)}\n"
        
        if rule_number:
            log_message += f"<b>Правило:</b> #{rule_number}\n"
        
        if reason:
            log_message += f"<b>Причина:</b> {reason}\n"
        
        log_message += f"<b>Чат ID:</b> <code>{chat_id}</code>\n"
        log_message += f"<b>Время:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        if message_id:
            try:
                chat = await bot.get_chat(chat_id)
                log_message += f"\n<b>Ссылка:</b> https://t.me/{chat.username}/{message_id}"
            except:
                pass
        
        keyboard = None
        if restriction_id and not is_removed:
            keyboard = Keyboards.get_remove_restriction_keyboard(restriction_id)
        
        msg = await bot.send_message(log_chat_id, log_message, parse_mode=ParseMode.HTML, 
                                    reply_markup=keyboard)
        
        return msg.message_id
        
    except Exception as e:
        logger.error(f"Ошибка при отправке лога: {e}")
        return None

# ============ ОБРАБОТЧИКИ КОМАНД ============

@router.message(CommandStart())
@router.message(F.text.lower().in_(["/startpuls", "startpuls", "старт", "/старт"]))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Нет username"
    full_name = message.from_user.full_name
    
    is_bot_admin = user_id in ADMIN_IDS
    Database.create_user(user_id, username, full_name, is_bot_admin)
    
    welcome_text = (
        f"🎉 Привет! Я — Puls Bot! ✨\n\n"
        f"Я универсальный бот для модерации, игр и мини-экономики!\n"
        f"Спасибо, что добавили меня!\n\n"
        f"{Utils.get_emoji('greeting')} Ваши данные:\n"
        f"• ID: {user_id}\n"
        f"• Username: @{username if username else 'Нет'}\n"
        f"• Имя: {full_name}"
    )
    
    await message.answer(welcome_text, reply_markup=Keyboards.get_main_keyboard(user_id))

# ============ РАЗВЛЕЧЕНИЯ ============
@router.callback_query(F.data == "entertainment")
async def callback_entertainment(callback: CallbackQuery):
    await callback.message.edit_text(
        f"{Utils.get_emoji('game')} <b>🎮 Развлечения</b>\n\n"
        "Выберите действие:",
        reply_markup=Keyboards.get_entertainment_keyboard()
    )
    await callback.answer()

# ============ ИГРАТЬ С ШАНСАМИ ============
@router.callback_query(F.data == "play_game")
@router.message(F.text.lower().in_(["играть", "/играть", "game", "/game", "gamepuls", "/gamepuls"]))
async def cmd_play_game(message_or_callback):
    if isinstance(message_or_callback, CallbackQuery):
        message = message_or_callback.message
        user_id = message_or_callback.from_user.id
        await message_or_callback.answer()
    else:
        message = message_or_callback
        user_id = message.from_user.id
    
    Database.update_user(user_id, last_active=datetime.now().isoformat())
    user_data = Database.get_user(user_id)
    
    if not user_data:
        await message.reply(f"{Utils.get_emoji('error')} Начните с /start")
        return
    
    # Проверяем, активна ли удача
    luck_active = False
    if user_data[15]:  # luck_active_until
        luck_until = datetime.fromisoformat(user_data[15])
        if luck_until > datetime.now():
            luck_active = True
    
    # Админы имеют 10 попыток, остальные 3 + перманентные + временные
    base_attempts = 10 if Database.get_bot_admin(user_id) else 3
    perm_attempts = user_data[11] or 0
    temp_attempts = user_data[13] or 0
    
    max_attempts = base_attempts + perm_attempts + temp_attempts
    
    # Проверяем ограничения
    now = datetime.now()
    game_count = user_data[7] or 0
    reset_time = datetime.fromisoformat(user_data[9]) if user_data[9] else None
    
    if reset_time and now >= reset_time:
        game_count = 0
        Database.update_user(user_id, game_count=0, game_reset_time=None)
    
    # Используем попытки в порядке: обычные -> временные -> перманентные
    total_used = game_count
    
    if total_used >= max_attempts:
        if not reset_time:
            reset_time = now + timedelta(hours=5)
            Database.update_user(user_id, game_reset_time=reset_time)
        
        time_left = reset_time - now
        hours = time_left.seconds // 3600
        minutes = (time_left.seconds % 3600) // 60
        
        response = (
            f"{Utils.get_emoji('error')} <b>Лимит игр исчерпан!</b>\n\n"
            f"Вы уже сыграли {total_used}/{max_attempts} раз.\n"
            f"⏳ Следующая игра возможна через: {hours}ч {minutes}м\n\n"
            f"💡 Купите дополнительные попытки в магазине!"
        )
        if isinstance(message_or_callback, CallbackQuery):
            await message.edit_text(response, reply_markup=Keyboards.get_back_to_main_keyboard())
        else:
            await message.reply(response)
        return
    
    # Генерация выигрыша с учетом удачи
    roll = random.randint(1, 100)
    
    # Базовые шансы (1-9: 85%, 10-19: 80%, ..., 90-100: 1%)
    chance_ranges = [
        (1, 9, 85),
        (10, 19, 80),
        (20, 29, 70),
        (30, 39, 60),
        (40, 49, 50),
        (50, 59, 40),
        (60, 69, 30),
        (70, 79, 20),
        (80, 89, 10),
        (90, 100, 1)
    ]
    
    base_chance = 1
    range_text = ""
    for min_val, max_val, chance in chance_ranges:
        if min_val <= roll <= max_val:
            base_chance = chance
            range_text = f"{min_val}-{max_val}"
            break
    
    # Корректировка шанса при активной удаче
    final_chance = base_chance
    if luck_active:
        if base_chance >= 50:
            final_chance = min(base_chance + 5, 90)
        else:
            final_chance = max(base_chance - 5, 1)
    
    # Определяем выигрыш
    win_threshold = random.randint(1, 100)
    coins_won = 0
    
    if win_threshold <= final_chance:
        # Выигрыш - от 5 до 50 коинов, пропорционально удаче
        base_win = random.randint(5, 50)
        if luck_active:
            coins_won = min(base_win * 2, 100)
        else:
            coins_won = base_win
    
    # Обновляем баланс
    new_coins = (user_data[3] or 0) + coins_won
    
    # Определяем тип использованной попытки
    if game_count < base_attempts:
        game_count += 1
        Database.update_user(
            user_id,
            coins=new_coins,
            last_game=now,
            game_count=game_count,
            game_reset_time=now + timedelta(hours=5) if game_count >= base_attempts else None
        )
    elif temp_attempts > 0:
        temp_attempts -= 1
        Database.update_user(
            user_id,
            coins=new_coins,
            last_game=now,
            game_temp_attempts=temp_attempts
        )
    else:
        # Используем перманентную попытку (но она не тратится)
        Database.update_user(
            user_id,
            coins=new_coins,
            last_game=now
        )
    
    # Формируем ответ
    response = (
        f"{Utils.get_emoji('game')} <b>🎮 Игра завершена!</b>\n\n"
        f"🎲 Выпало число: <b>{roll}</b>\n"
        f"📊 Диапазон: {range_text}\n"
        f"📈 Шанс выигрыша: {final_chance}%"
    )
    
    if luck_active:
        response += f"\n🍀 Удача активна: +5% к шансу"
    
    if coins_won > 0:
        response += f"\n\n💰 <b>Вы выиграли {coins_won} Puls Coins!</b>"
    else:
        response += f"\n\n😢 <b>Повезёт в следующий раз!</b>"
    
    response += f"\n\n🎮 Использовано попыток: {total_used + 1}/{max_attempts}"
    response += f"\n💰 Баланс: {new_coins} Puls Coins"
    
    if isinstance(message_or_callback, CallbackQuery):
        await message.edit_text(response, reply_markup=Keyboards.get_back_to_main_keyboard())
    else:
        await message.reply(response)

# ============ РАБОТАТЬ С ШАНСАМИ ============
@router.callback_query(F.data == "work_game")
@router.message(F.text.lower().in_(["работать", "/работать", "work", "/work"]))
async def cmd_work_game(message_or_callback):
    if isinstance(message_or_callback, CallbackQuery):
        message = message_or_callback.message
        user_id = message_or_callback.from_user.id
        await message_or_callback.answer()
    else:
        message = message_or_callback
        user_id = message.from_user.id
    
    Database.update_user(user_id, last_active=datetime.now().isoformat())
    user_data = Database.get_user(user_id)
    
    if not user_data:
        await message.reply(f"{Utils.get_emoji('error')} Начните с /start")
        return
    
    # Проверяем, активна ли удача
    luck_active = False
    if user_data[15]:  # luck_active_until
        luck_until = datetime.fromisoformat(user_data[15])
        if luck_until > datetime.now():
            luck_active = True
    
    # Админы имеют 10 попыток, остальные 5 + перманентные + временные
    base_attempts = 10 if Database.get_bot_admin(user_id) else 5
    perm_attempts = user_data[12] or 0
    temp_attempts = user_data[14] or 0
    
    max_attempts = base_attempts + perm_attempts + temp_attempts
    
    # Проверяем ограничения
    now = datetime.now()
    work_count = user_data[8] or 0
    reset_time = datetime.fromisoformat(user_data[10]) if user_data[10] else None
    
    if reset_time and now >= reset_time:
        work_count = 0
        Database.update_user(user_id, work_count=0, work_reset_time=None)
    
    # Используем попытки в порядке: обычные -> временные -> перманентные
    total_used = work_count
    
    if total_used >= max_attempts:
        if not reset_time:
            reset_time = now + timedelta(hours=24)
            Database.update_user(user_id, work_reset_time=reset_time)
        
        time_left = reset_time - now
        hours = time_left.seconds // 3600
        minutes = (time_left.seconds % 3600) // 60
        
        response = (
            f"{Utils.get_emoji('error')} <b>Лимит работы исчерпан!</b>\n\n"
            f"Вы уже поработали {total_used}/{max_attempts} раз.\n"
            f"⏳ Следующая работа возможна через: {hours}ч {minutes}м\n\n"
            f"💡 Купите дополнительные попытки в магазине!"
        )
        if isinstance(message_or_callback, CallbackQuery):
            await message.edit_text(response, reply_markup=Keyboards.get_back_to_main_keyboard())
        else:
            await message.reply(response)
        return
    
    # Генерация заработка с учетом удачи (для работы шансы ниже)
    roll = random.randint(1, 100)
    
    # Шансы для работы (менее выгодные)
    chance_ranges = [
        (1, 9, 70),
        (10, 19, 65),
        (20, 29, 55),
        (30, 39, 45),
        (40, 49, 35),
        (50, 59, 25),
        (60, 69, 15),
        (70, 79, 10),
        (80, 89, 5),
        (90, 100, 1)
    ]
    
    base_chance = 1
    range_text = ""
    for min_val, max_val, chance in chance_ranges:
        if min_val <= roll <= max_val:
            base_chance = chance
            range_text = f"{min_val}-{max_val}"
            break
    
    # Корректировка шанса при активной удаче
    final_chance = base_chance
    if luck_active:
        if base_chance >= 30:
            final_chance = min(base_chance + 3, 75)
        else:
            final_chance = max(base_chance - 3, 1)
    
    # Определяем заработок
    win_threshold = random.randint(1, 100)
    dollars_earned = 0
    
    if win_threshold <= final_chance:
        # Заработок - от 1 до 20 долларов
        base_earn = random.randint(1, 20)
        if luck_active:
            dollars_earned = min(base_earn * 2, 40)
        else:
            dollars_earned = base_earn
    
    # Обновляем баланс
    new_dollars = (user_data[4] or 0) + dollars_earned
    
    # Определяем тип использованной попытки
    if work_count < base_attempts:
        work_count += 1
        Database.update_user(
            user_id,
            dollars=new_dollars,
            last_work=now,
            work_count=work_count,
            work_reset_time=now + timedelta(hours=24) if work_count >= base_attempts else None
        )
    elif temp_attempts > 0:
        temp_attempts -= 1
        Database.update_user(
            user_id,
            dollars=new_dollars,
            last_work=now,
            work_temp_attempts=temp_attempts
        )
    else:
        # Используем перманентную попытку (но она не тратится)
        Database.update_user(
            user_id,
            dollars=new_dollars,
            last_work=now
        )
    
    # Формируем ответ
    response = (
        f"{Utils.get_emoji('success')} <b>💼 Работа завершена!</b>\n\n"
        f"🎲 Выпало число: <b>{roll}</b>\n"
        f"📊 Диапазон: {range_text}\n"
        f"📈 Шанс заработка: {final_chance}%"
    )
    
    if luck_active:
        response += f"\n🍀 Удача активна: +3% к шансу"
    
    if dollars_earned > 0:
        response += f"\n\n💰 <b>Вы заработали ${dollars_earned}!</b>"
    else:
        response += f"\n\n😢 <b>В следующий раз получится!</b>"
    
    response += f"\n\n💼 Использовано попыток: {total_used + 1}/{max_attempts}"
    response += f"\n💵 Баланс: ${new_dollars}"
    
    if isinstance(message_or_callback, CallbackQuery):
        await message.edit_text(response, reply_markup=Keyboards.get_back_to_main_keyboard())
    else:
        await message.reply(response)

# ============ БАЛАНС С ВОЗМОЖНОСТЬЮ ПРОСМОТРА ДРУГОГО ПОЛЬЗОВАТЕЛЯ ============
@router.callback_query(F.data == "balance")
async def callback_balance(callback: CallbackQuery):
    await callback.message.edit_text(
        f"{Utils.get_emoji('info')} <b>💰 Просмотр баланса</b>\n\n"
        "Введите:\n"
        "• 'мой баланс' или 'баланс' - чтобы посмотреть свой баланс\n"
        "• 'баланс @username' или 'баланс ID' - чтобы посмотреть баланс другого пользователя\n"
        "• Или ответьте на сообщение пользователя с текстом 'баланс'",
        reply_markup=Keyboards.get_back_to_main_keyboard()
    )
    await callback.answer()

@router.message(F.text.lower().in_(["баланс", "/баланс", "balance", "/balance", "профиль", "/профиль", "стата", "/стата", "мой баланс", "my balance"]))
async def cmd_balance(message: Message):
    user_id = message.from_user.id
    text = message.text.lower().strip()
    
    Database.update_user(user_id, last_active=datetime.now().isoformat())
    
    # Проверяем, хочет ли пользователь посмотреть баланс другого пользователя
    target_user_id = None
    
    if message.reply_to_message:
        # Если ответ на сообщение
        target_user_id = message.reply_to_message.from_user.id
    elif "баланс" in text or "balance" in text:
        words = text.split()
        if len(words) > 1:
            # Пытаемся найти пользователя по username или ID
            target = words[1]
            if target.startswith('@'):
                # По username (упрощённо)
                conn = Database.get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT user_id FROM users WHERE username LIKE ?', (target[1:],))
                result = cursor.fetchone()
                conn.close()
                if result:
                    target_user_id = result[0]
            elif target.isdigit():
                target_user_id = int(target)
    
    # Если не указан другой пользователь или указано "мой баланс"
    if not target_user_id or "мой" in text or "my" in text:
        # Показываем свой баланс
        user_data = Database.get_user(user_id)
        
        if not user_data:
            await message.reply(f"{Utils.get_emoji('error')} Начните с /start")
            return
        
        coins = user_data[3] or 0
        dollars = user_data[4] or 0
        
        # Проверяем VIP статус
        vip_info = ""
        if user_data[15]:  # luck_active_until
            vip_until = datetime.fromisoformat(user_data[15])
            if vip_until > datetime.now():
                days_left = (vip_until - datetime.now()).days
                vip_info = f"\n👑 Удача активна: {days_left} дней"
        
        response = (
            f"{Utils.get_emoji('game')} <b>💰 Ваш баланс</b>\n\n"
            f"🎮 <b>Puls Coins:</b> {coins}\n"
            f"💵 <b>Доллары:</b> ${dollars}"
            f"{vip_info}"
        )
        
        await message.reply(response)
    else:
        # Показываем баланс другого пользователя
        target_data = Database.get_user(target_user_id)
        
        if not target_data:
            await message.reply(f"{Utils.get_emoji('error')} Пользователь не найден!")
            return
        
        coins = target_data[3] or 0
        dollars = target_data[4] or 0
        
        response = (
            f"{Utils.get_emoji('info')} <b>💰 Баланс пользователя</b>\n\n"
            f"👤 <b>Пользователь:</b> {target_data[2]}\n"
            f"🆔 <b>ID:</b> <code>{target_user_id}</code>\n"
            f"🎮 <b>Puls Coins:</b> {coins}\n"
            f"💵 <b>Доллары:</b> ${dollars}"
        )
        
        await message.reply(response)

# ============ ТОП ИГРОКОВ ============
@router.callback_query(F.data == "top_players_menu")
async def callback_top_players_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        f"{Utils.get_emoji('info')} <b>🏆 Топ игроков</b>\n\n"
        "Выберите категорию:",
        reply_markup=Keyboards.get_top_players_menu_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("top_"))
async def callback_top_players(callback: CallbackQuery):
    data = callback.data
    
    if data == "top_coins":
        await callback.message.edit_text(
            f"{Utils.get_emoji('info')} <b>🎮 Топ по Puls Coins</b>\n\n"
            "Выберите период:",
            reply_markup=Keyboards.get_top_period_keyboard("coins")
        )
    elif data == "top_dollars":
        await callback.message.edit_text(
            f"{Utils.get_emoji('info')} <b>💵 Топ по Долларам</b>\n\n"
            "Выберите период:",
            reply_markup=Keyboards.get_top_period_keyboard("dollars")
        )
    elif data.startswith("top_coins_"):
        period = data.split("_")[2]
        await show_top_coins(callback, period)
    elif data.startswith("top_dollars_"):
        period = data.split("_")[2]
        await show_top_dollars(callback, period)
    
    await callback.answer()

async def show_top_coins(callback: CallbackQuery, period: str):
    period_names = {
        'daily': 'за день',
        'weekly': 'за неделю',
        'all': 'за всё время'
    }
    
    period_name = period_names.get(period, 'за всё время')
    top_players = Database.get_top_players_by_coins(10, period)
    
    if not top_players:
        top_text = f"🏆 Топ игроков по Puls Coins {period_name} пуст!"
    else:
        top_text = f"🏆 ТОП-10 игроков по Puls Coins {period_name} 🏆\n\n"
        
        for i, player in enumerate(top_players, 1):
            user_id, username, full_name, coins = player
            medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
            name_display = f"@{username}" if username and username != "Нет" else full_name
            top_text += f"{medal} {name_display} - {coins} Puls Coins\n"
    
    await callback.message.edit_text(
        top_text,
        reply_markup=Keyboards.get_top_period_keyboard("coins")
    )

async def show_top_dollars(callback: CallbackQuery, period: str):
    period_names = {
        'daily': 'за день',
        'weekly': 'за неделю',
        'all': 'за всё время'
    }
    
    period_name = period_names.get(period, 'за всё время')
    top_players = Database.get_top_players_by_dollars(10, period)
    
    if not top_players:
        top_text = f"🏆 Топ игроков по Долларам {period_name} пуст!"
    else:
        top_text = f"🏆 ТОП-10 игроков по Долларам {period_name} 🏆\n\n"
        
        for i, player in enumerate(top_players, 1):
            user_id, username, full_name, dollars = player
            medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
            name_display = f"@{username}" if username and username != "Нет" else full_name
            top_text += f"{medal} {name_display} - ${dollars}\n"
    
    await callback.message.edit_text(
        top_text,
        reply_markup=Keyboards.get_top_period_keyboard("dollars")
    )

# ============ МАГАЗИН ============
@router.callback_query(F.data == "shop")
async def callback_shop(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if callback.message.chat.type != "private":
        await callback.answer(f"{Utils.get_emoji('error')} Магазин доступен только в ЛС!", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"{Utils.get_emoji('shop')} <b>🛒 Магазин Puls Bot</b>\n\n"
        "Выберите категорию:",
        reply_markup=Keyboards.get_shop_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "shop_game_attempts")
async def callback_shop_game_attempts(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_data = Database.get_user(user_id)
    
    if not user_data:
        await callback.answer(f"{Utils.get_emoji('error')} Начните с /start", show_alert=True)
        return
    
    coins = user_data[3] or 0
    perm_attempts = user_data[11] or 0
    temp_attempts = user_data[13] or 0
    
    await callback.message.edit_text(
        f"{Utils.get_emoji('shop')} <b>🎮 Дополнительные попытки для игры</b>\n\n"
        f"💰 Ваш баланс: {coins} Puls Coins\n"
        f"🎮 Перманентные попытки: {perm_attempts}/∞\n"
        f"🎮 Временные попытки: {temp_attempts}\n\n"
        "Выберите тип попыток:",
        reply_markup=Keyboards.get_game_attempts_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "buy_temp_game")
async def callback_buy_temp_game(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_data = Database.get_user(user_id)
    
    if not user_data:
        await callback.answer(f"{Utils.get_emoji('error')} Начните с /start", show_alert=True)
        return
    
    coins = user_data[3] or 0
    
    await callback.message.edit_text(
        f"{Utils.get_emoji('shop')} <b>🎮 Покупка временных попыток</b>\n\n"
        f"💰 Ваш баланс: {coins} Puls Coins\n\n"
        "Временные попытки действуют до использования.\n"
        "Вы можете купить несколько пакетов.\n\n"
        "Выберите пакет:",
        reply_markup=Keyboards.get_temp_attempts_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("temp_"))
async def callback_buy_temp_attempts(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_data = Database.get_user(user_id)
    
    if not user_data:
        await callback.answer(f"{Utils.get_emoji('error')} Начните с /start", show_alert=True)
        return
    
    temp_type = callback.data
    prices = {
        'temp_1': {'coins': 30, 'attempts': 1},
        'temp_3': {'coins': 80, 'attempts': 3},
        'temp_5': {'coins': 120, 'attempts': 5},
        'temp_10': {'coins': 200, 'attempts': 10}
    }
    
    price = prices.get(temp_type)
    if not price:
        await callback.answer(f"{Utils.get_emoji('error')} Неверный тип пакета", show_alert=True)
        return
    
    coins = user_data[3] or 0
    current_temp = user_data[13] or 0
    
    if coins < price['coins']:
        await callback.answer(
            f"{Utils.get_emoji('error')} Недостаточно Puls Coins!\n"
            f"Нужно: {price['coins']} коинов\n"
            f"У вас: {coins} коинов",
            show_alert=True
        )
        return
    
    # Покупка
    Database.update_user(
        user_id,
        coins=coins - price['coins'],
        game_temp_attempts=current_temp + price['attempts']
    )
    
    new_temp = current_temp + price['attempts']
    
    await callback.message.edit_text(
        f"{Utils.get_emoji('success')} <b>✅ Покупка успешна!</b>\n\n"
        f"🎮 Куплено попыток: {price['attempts']}\n"
        f"💰 Потрачено: {price['coins']} Puls Coins\n"
        f"🎮 Всего временных попыток: {new_temp}\n\n"
        f"💡 Используйте команду 'играть'!"
    )
    
    await asyncio.sleep(2)
    
    # Возвращаем в магазин
    await callback.message.edit_text(
        f"{Utils.get_emoji('shop')} <b>🛒 Магазин Puls Bot</b>\n\n"
        "Выберите категорию:",
        reply_markup=Keyboards.get_shop_keyboard()
    )
    
    await callback.answer()

@router.callback_query(F.data == "buy_perm_game")
async def callback_buy_perm_game(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_data = Database.get_user(user_id)
    
    if not user_data:
        await callback.answer(f"{Utils.get_emoji('error')} Начните с /start", show_alert=True)
        return
    
    coins = user_data[3] or 0
    perm_attempts = user_data[11] or 0
    
    # Максимум 2 перманентные попытки можно купить
    if perm_attempts >= 2:
        await callback.answer(
            f"{Utils.get_emoji('error')} Вы уже купили максимальное количество перманентных попыток!",
            show_alert=True
        )
        return
    
    price = 500  # 500 коинов за 1 перманентную попытку
    
    if coins < price:
        await callback.answer(
            f"{Utils.get_emoji('error')} Недостаточно Puls Coins!\n"
            f"Нужно: {price} коинов\n"
            f"У вас: {coins} коинов",
            show_alert=True
        )
        return
    
    # Покупка
    Database.update_user(
        user_id,
        coins=coins - price,
        game_perm_attempts=perm_attempts + 1
    )
    
    await callback.message.edit_text(
        f"{Utils.get_emoji('success')} <b>✅ Покупка успешна!</b>\n\n"
        f"⭐ Куплено: 1 перманентная попытка\n"
        f"💰 Потрачено: {price} Puls Coins\n"
        f"🎮 Всего перманентных попыток: {perm_attempts + 1}/2\n\n"
        f"💡 Перманентные попытки действуют всегда!"
    )
    
    await asyncio.sleep(2)
    
    # Возвращаем в магазин
    await callback.message.edit_text(
        f"{Utils.get_emoji('shop')} <b>🛒 Магазин Puls Bot</b>\n\n"
        "Выберите категорию:",
        reply_markup=Keyboards.get_shop_keyboard()
    )
    
    await callback.answer()

@router.callback_query(F.data == "buy_luck")
async def callback_buy_luck(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_data = Database.get_user(user_id)
    
    if not user_data:
        await callback.answer(f"{Utils.get_emoji('error')} Начните с /start", show_alert=True)
        return
    
    coins = user_data[3] or 0
    dollars = user_data[4] or 0
    
    # Проверяем, активна ли уже удача
    luck_active = False
    if user_data[15]:
        luck_until = datetime.fromisoformat(user_data[15])
        if luck_until > datetime.now():
            luck_active = True
    
    if luck_active:
        time_left = luck_until - datetime.now()
        hours = time_left.seconds // 3600
        minutes = (time_left.seconds % 3600) // 60
        
        await callback.answer(
            f"🍀 Удача уже активна! Осталось: {hours}ч {minutes}м",
            show_alert=True
        )
        return
    
    # Цены: 50 коинов или 30$ за 10 минут удачи
    price_coins = 50
    price_dollars = 30
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text=f"🎮 50 Puls Coins (10 мин)", callback_data="luck_coins")
    keyboard.button(text=f"💵 30$ (10 мин)", callback_data="luck_dollars")
    keyboard.button(text="🔙 Назад", callback_data="entertainment")
    keyboard.adjust(1, 1, 1)
    
    await callback.message.edit_text(
        f"{Utils.get_emoji('shop')} <b>🍀 Покупка удачи</b>\n\n"
        f"💰 Ваш баланс: {coins} Puls Coins + ${dollars}\n\n"
        "Удача увеличивает шансы на выигрыш:\n"
        "• В игре: +5% к высоким шансам\n"
        "• В работе: +3% к высоким шансам\n\n"
        "Действует 10 минут.\n\n"
        "Выберите способ оплаты:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.in_(["luck_coins", "luck_dollars"]))
async def callback_purchase_luck(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_data = Database.get_user(user_id)
    
    if not user_data:
        await callback.answer(f"{Utils.get_emoji('error')} Начните с /start", show_alert=True)
        return
    
    coins = user_data[3] or 0
    dollars = user_data[4] or 0
    
    if callback.data == "luck_coins":
        price = 50
        if coins < price:
            await callback.answer(
                f"{Utils.get_emoji('error')} Недостаточно Puls Coins!\n"
                f"Нужно: {price} коинов\n"
                f"У вас: {coins} коинов",
                show_alert=True
            )
            return
        
        # Покупка за коины
        Database.update_user(
            user_id,
            coins=coins - price,
            luck_active_until=(datetime.now() + timedelta(minutes=10)).isoformat()
        )
        currency_used = "Puls Coins"
        
    else:  # luck_dollars
        price = 30
        if dollars < price:
            await callback.answer(
                f"{Utils.get_emoji('error')} Недостаточно долларов!\n"
                f"Нужно: ${price}\n"
                f"У вас: ${dollars}",
                show_alert=True
            )
            return
        
        # Покупка за доллары
        Database.update_user(
            user_id,
            dollars=dollars - price,
            luck_active_until=(datetime.now() + timedelta(minutes=10)).isoformat()
        )
        currency_used = "доллары"
    
    await callback.message.edit_text(
        f"{Utils.get_emoji('success')} <b>✅ Удача куплена!</b>\n\n"
        f"🍀 Удача активна: 10 минут\n"
        f"💰 Потрачено: {price} {currency_used}\n\n"
        f"💡 Бонусы:\n"
        f"• В игре: +5% к шансам ≥50%\n"
        f"• В работе: +3% к шансам ≥30%"
    )
    
    await asyncio.sleep(2)
    
    # Возвращаем в развлечения
    await callback.message.edit_text(
        f"{Utils.get_emoji('game')} <b>🎮 Развлечения</b>\n\n"
        "Выберите действие:",
        reply_markup=Keyboards.get_entertainment_keyboard()
    )
    
    await callback.answer()

# ============ АДМИН-ПАНЕЛЬ ============
@router.callback_query(F.data == "admin_panel")
async def callback_admin_panel(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    # Проверяем, является ли пользователь админом бота
    admin_data = Database.get_bot_admin(user_id)
    if not admin_data or admin_data[3] != 1:
        await callback.answer(f"{Utils.get_emoji('error')} Нет доступа!", show_alert=True)
        return
    
    if callback.message.chat.type != "private":
        await callback.answer(f"{Utils.get_emoji('error')} Только в ЛС!", show_alert=True)
        await callback.message.answer(f"🔒 Админ-панель доступна только в ЛС: @{BOT_USERNAME}")
        return
    
    # Проверяем блокировку
    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT failed_attempts, lock_until FROM admin_lock WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result and result[0] >= 2 and result[1]:
        lock_until = datetime.fromisoformat(result[1])
        if datetime.now() < lock_until:
            time_left = lock_until - datetime.now()
            minutes = time_left.seconds // 60
            await callback.answer(f"⛔ Заблокировано! Попробуйте через {minutes} минут.", show_alert=True)
            return
    
    # Запрашиваем пароль
    await state.set_state(AdminStates.waiting_password)
    
    try:
        await callback.message.edit_text(
            f"{Utils.get_emoji('info')} <b>Админ-панель</b>\n\n"
            "Для доступа введите пароль:\n"
            "<i>У вас есть 2 попытки, после чего блокировка на 5 минут.</i>",
            reply_markup=Keyboards.get_cancel_keyboard()
        )
    except:
        await callback.message.answer(
            f"{Utils.get_emoji('info')} <b>Админ-панель</b>\n\n"
            "Для доступа введите пароль:\n"
            "<i>У вас есть 2 попытки, после чего блокировка на 5 минут.</i>",
            reply_markup=Keyboards.get_cancel_keyboard()
        )
    
    await callback.answer()

@router.message(AdminStates.waiting_password)
async def process_admin_password(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Проверяем, является ли пользователь админом бота
    admin_data = Database.get_bot_admin(user_id)
    if not admin_data or admin_data[3] != 1:
        await state.clear()
        return
    
    password = message.text.strip()
    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT failed_attempts, lock_until FROM admin_lock WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    failed_attempts = result[0] if result else 0
    lock_until = datetime.fromisoformat(result[1]) if result and result[1] else None
    
    # Проверяем блокировку
    if failed_attempts >= 2 and lock_until and datetime.now() < lock_until:
        time_left = lock_until - datetime.now()
        minutes = time_left.seconds // 60
        await message.answer(f"{Utils.get_emoji('error')} Доступ заблокирован! Попробуйте через {minutes} минут.")
        await state.clear()
        conn.close()
        return
    
    if password == ADMIN_PASSWORD:
        # Успешный вход
        cursor.execute('DELETE FROM admin_lock WHERE user_id = ?', (user_id,))
        add_admin_session(user_id)
        
        try:
            await message.delete()
        except:
            pass
        
        msg = await message.answer(
            f"{Utils.get_emoji('success')} <b>✅ Пароль верный!</b>\n\n"
            "Добро пожаловать в админ-панель!",
            reply_markup=Keyboards.get_admin_keyboard(user_id)
        )
        add_admin_message(user_id, msg.message_id)
        
    else:
        # Неверный пароль
        failed_attempts += 1
        
        if failed_attempts >= 2:
            lock_until = datetime.now() + timedelta(minutes=5)
            cursor.execute('''
                INSERT OR REPLACE INTO admin_lock (user_id, failed_attempts, lock_until)
                VALUES (?, ?, ?)
            ''', (user_id, failed_attempts, lock_until.isoformat()))
            
            time_left = lock_until - datetime.now()
            minutes = time_left.seconds // 60
            
            await message.answer(
                f"{Utils.get_emoji('error')} <b>⛔ Слишком много неверных попыток!</b>\n\n"
                f"Доступ заблокирован на {minutes} минут.\n\n"
                f"Возвращаемся в главное меню...",
                reply_markup=Keyboards.get_main_keyboard(user_id)
            )
        else:
            cursor.execute('''
                INSERT OR REPLACE INTO admin_lock (user_id, failed_attempts, lock_until)
                VALUES (?, ?, NULL)
            ''', (user_id, failed_attempts))
            attempts_left = 2 - failed_attempts
            
            await message.answer(
                f"{Utils.get_emoji('error')} <b>❌ Неверный пароль!</b>\n\n"
                f"Осталось попыток: {attempts_left}\n"
                f"Введите пароль еще раз:"
            )
    
    conn.commit()
    conn.close()
    await state.clear()

# ============ АДМИНСКИЕ ДЕЙСТВИЯ ============
@router.callback_query(F.data.startswith("admin_"))
async def callback_admin_actions(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    # Проверяем, является ли пользователь админом бота
    admin_data = Database.get_bot_admin(user_id)
    if not admin_data or admin_data[3] != 1:
        await callback.answer(f"{Utils.get_emoji('error')} Нет доступа!", show_alert=True)
        return
    
    # Проверяем сессию
    is_active, error_msg = check_admin_session(user_id)
    if not is_active:
        await callback.answer(error_msg, show_alert=True)
        
        try:
            await callback.message.edit_text(
                f"{Utils.get_emoji('error')} {error_msg}",
                reply_markup=Keyboards.get_main_keyboard(user_id)
            )
        except:
            await callback.message.answer(
                f"{Utils.get_emoji('error')} {error_msg}",
                reply_markup=Keyboards.get_main_keyboard(user_id)
            )
        return
    
    data = callback.data
    
    # Добавляем сообщение в список для удаления
    add_admin_message(user_id, callback.message.message_id)
    
    if data == "admin_stats":
        # Статистика (ТОЛЬКО данные бота, без групп)
        total_users = len(Database.get_all_users())
        total_coins = Database.get_total_coins()
        total_dollars = Database.get_total_dollars()
        active_users_today = Database.get_active_users_today()
        
        # Количество админов бота
        bot_admins = Database.get_all_bot_admins()
        admin_count = len(bot_admins)
        
        stats_text = (
            f"{Utils.get_emoji('info')} <b>📊 Статистика бота</b>\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"🎮 Всего Puls Coins: {total_coins}\n"
            f"💵 Всего долларов: ${total_dollars}\n"
            f"📈 Активных сегодня: {active_users_today}\n"
            f"👑 Администраторов бота: {admin_count}"
        )
        
        try:
            msg = await callback.message.edit_text(
                stats_text,
                reply_markup=Keyboards.get_admin_keyboard(user_id)
            )
            add_admin_message(user_id, msg.message_id)
        except:
            msg = await callback.message.answer(
                stats_text,
                reply_markup=Keyboards.get_admin_keyboard(user_id)
            )
            add_admin_message(user_id, msg.message_id)
    
    elif data == "admin_broadcast":
        # Проверяем право на рассылку
        if admin_data[4] != 1:
            await callback.answer(f"{Utils.get_emoji('error')} Нет прав на рассылку!", show_alert=True)
            return
        
        await state.set_state(AdminStates.waiting_broadcast)
        
        try:
            msg = await callback.message.edit_text(
                f"{Utils.get_emoji('info')} <b>📣 Рассылка</b>\n\n"
                "Введите текст для рассылки всем пользователям:",
                reply_markup=Keyboards.get_cancel_keyboard()
            )
            add_admin_message(user_id, msg.message_id)
        except:
            msg = await callback.message.answer(
                f"{Utils.get_emoji('info')} <b>📣 Рассылка</b>\n\n"
                "Введите текст для рассылки всем пользователей:",
                reply_markup=Keyboards.get_cancel_keyboard()
            )
            add_admin_message(user_id, msg.message_id)
    
    elif data == "admin_give_currency":
        # Проверяем право на выдачу валюты
        if admin_data[5] != 1:
            await callback.answer(f"{Utils.get_emoji('error')} Нет прав на выдачу валюты!", show_alert=True)
            return
        
        try:
            msg = await callback.message.edit_text(
                f"{Utils.get_emoji('info')} <b>💰 Выдача валюты</b>\n\n"
                "Выберите тип валюты для выдачи:",
                reply_markup=Keyboards.get_currency_type_keyboard()
            )
            add_admin_message(user_id, msg.message_id)
        except:
            msg = await callback.message.answer(
                f"{Utils.get_emoji('info')} <b>💰 Выдача валюты</b>\n\n"
                "Выберите тип валюты для выдачи:",
                reply_markup=Keyboards.get_currency_type_keyboard()
            )
            add_admin_message(user_id, msg.message_id)
    
    elif data == "admin_manage_admins":
        # Проверяем право на управление админами
        if admin_data[6] != 1:
            await callback.answer(f"{Utils.get_emoji('error')} Нет прав на управление админами!", show_alert=True)
            return
        
        await show_admin_management(callback, user_id)
    
    elif data == "admin_back_to_panel":
        try:
            msg = await callback.message.edit_text(
                f"{Utils.get_emoji('info')} <b>Админ-панель</b>\n\n"
                "Выберите действие:",
                reply_markup=Keyboards.get_admin_keyboard(user_id)
            )
            add_admin_message(user_id, msg.message_id)
        except:
            msg = await callback.message.answer(
                f"{Utils.get_emoji('info')} <b>Админ-панель</b>\n\n"
                "Выберите действие:",
                reply_markup=Keyboards.get_admin_keyboard(user_id)
            )
            add_admin_message(user_id, msg.message_id)
    
    elif data == "admin_exit":
        # Выход из админ-панели
        remove_admin_session(user_id)
        await state.clear()
        
        try:
            await callback.message.edit_text(
                f"{Utils.get_emoji('success')} ✅ Вы вышли из админ-панели.",
                reply_markup=Keyboards.get_main_keyboard(user_id)
            )
        except:
            await callback.message.answer(
                f"{Utils.get_emoji('success')} ✅ Вы вышли из админ-панели.",
                reply_markup=Keyboards.get_main_keyboard(user_id)
            )
    
    elif data == "admin_cancel":
        await state.clear()
        
        try:
            await callback.message.edit_text(
                f"{Utils.get_emoji('info')} ❌ Действие отменено.",
                reply_markup=Keyboards.get_main_keyboard(user_id)
            )
        except:
            await callback.message.answer(
                f"{Utils.get_emoji('info')} ❌ Действие отменено.",
                reply_markup=Keyboards.get_main_keyboard(user_id)
            )
    
    await callback.answer()

async def show_admin_management(callback: CallbackQuery, user_id: int):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="➕ Добавить админа", callback_data="add_admin")
    keyboard.button(text="📋 Список админов", callback_data="list_admins")
    keyboard.button(text="⚙️ Настройки админа", callback_data="edit_admin")
    keyboard.button(text="🔙 Назад", callback_data="admin_back_to_panel")
    keyboard.adjust(1, 1, 1, 1)
    
    await callback.message.edit_text(
        f"{Utils.get_emoji('info')} <b>👑 Управление админами</b>\n\n"
        "Выберите действие:",
        reply_markup=keyboard.as_markup()
    )

# ============ ФОНОВЫЕ ЗАДАЧИ ============
async def check_admin_sessions():
    """Проверка истечения админ-сессий"""
    while True:
        try:
            current_time = datetime.now()
            users_to_remove = []
            
            for user_id, session_time in admin_sessions.items():
                if (current_time - session_time).total_seconds() > ADMIN_SESSION_TIMEOUT:
                    users_to_remove.append(user_id)
            
            for user_id in users_to_remove:
                remove_admin_session(user_id)
                
                try:
                    await bot.send_message(
                        user_id,
                        f"{Utils.get_emoji('info')} ⏰ <b>Админ-сессия истекла</b>\n\n"
                        f"Ваша сессия админ-панели автоматически закрыта (таймаут 25 минут).\n"
                        f"Для доступа войдите заново."
                    )
                except:
                    pass
            
            await asyncio.sleep(30)
        
        except Exception as e:
            logger.error(f"Ошибка при проверке сессий: {e}")
            await asyncio.sleep(60)

async def reset_daily_stats_task():
    """Ежедневный сброс статистики"""
    while True:
        try:
            now = datetime.now()
            # Сброс в 00:00
            next_reset = datetime(now.year, now.month, now.day) + timedelta(days=1)
            wait_seconds = (next_reset - now).total_seconds()
            
            await asyncio.sleep(wait_seconds)
            
            Database.reset_daily_stats()
            logger.info("Ежедневная статистика сброшена")
            
        except Exception as e:
            logger.error(f"Ошибка при сбросе статистики: {e}")
            await asyncio.sleep(3600)

# ============ ЗАПУСК БОТА ============
async def main():
    # Запускаем фоновые задачи
    asyncio.create_task(check_admin_sessions())
    asyncio.create_task(reset_daily_stats_task())
    
    logger.info("Бот запускается...")
    logger.info(f"Админ ID: {ADMIN_IDS}")
    logger.info(f"Бот username: @{BOT_USERNAME}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
