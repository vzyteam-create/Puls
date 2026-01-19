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
MIN_PUNISHMENT_TIME = timedelta(seconds=30)  # 30 секунд
MAX_PUNISHMENT_TIME = timedelta(days=3650)   # 10 лет

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

class ShopStates(StatesGroup):
    waiting_game_attempts = State()
    waiting_work_attempts = State()

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
        game_vip_attempts INTEGER DEFAULT 0,
        work_vip_attempts INTEGER DEFAULT 0,
        vip_until TIMESTAMP,
        is_admin BOOLEAN DEFAULT 0,
        last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        status TEXT DEFAULT 'active'
    )
    ''')
    
    # Таблица прав модераторов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS moderator_rights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        chat_id INTEGER,
        can_mute BOOLEAN DEFAULT 0,
        can_ban BOOLEAN DEFAULT 0,
        can_kick BOOLEAN DEFAULT 0,
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
        set_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица правил
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        rule_number INTEGER,
        punishment_type TEXT,
        min_time TEXT,
        max_time TEXT,
        short_explanation TEXT,
        full_explanation TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Индексы
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_rules_chat ON rules(chat_id, rule_number)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_log_chats_user ON log_chats(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_active ON users(last_active)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_restrictions_active ON restrictions(status, until)')
    
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
    def create_user(user_id: int, username: str, full_name: str, is_admin: bool = False):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, full_name, coins, dollars, is_admin, last_active)
            VALUES (?, ?, ?, 0, 0, ?, CURRENT_TIMESTAMP)
        ''', (user_id, username, full_name, 1 if is_admin else 0))
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
        cursor.execute('SELECT chat_id, log_chat_id, chat_title FROM log_chats WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result
    
    @staticmethod
    def set_log_chat(user_id: int, chat_id: int, log_chat_id: int, chat_title: str):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM log_chats WHERE user_id = ?', (user_id,))
        cursor.execute('''
            INSERT INTO log_chats (user_id, chat_id, log_chat_id, chat_title)
            VALUES (?, ?, ?, ?)
        ''', (user_id, chat_id, log_chat_id, chat_title))
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
                       moderator_id: int, moderator_name: str, message_id: int = None):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO restrictions (user_id, chat_id, restriction_type, until, reason, 
                                     rule_number, moderator_id, moderator_name, message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, chat_id, restriction_type, until, reason, rule_number, 
              moderator_id, moderator_name, message_id))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_moderator_rights(user_id: int, chat_id: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT can_mute, can_ban, can_kick FROM moderator_rights 
            WHERE user_id = ? AND chat_id = ?
        ''', (user_id, chat_id))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'mute': bool(result[0]),
                'ban': bool(result[1]),
                'kick': bool(result[2])
            }
        return {'mute': False, 'ban': False, 'kick': False}
    
    @staticmethod
    def check_moderator_right(user_id: int, chat_id: int, right_type: str) -> bool:
        rights = Database.get_moderator_rights(user_id, chat_id)
        return rights.get(right_type, False)
    
    @staticmethod
    def add_moderator_right(user_id: int, chat_id: int, rights: dict, granted_by: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM moderator_rights WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
        
        cursor.execute('''
            INSERT INTO moderator_rights (user_id, chat_id, can_mute, can_ban, can_kick, granted_by)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, chat_id, 
              rights.get('mute', 0), 
              rights.get('ban', 0), 
              rights.get('kick', 0), 
              granted_by))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_top_players(limit: int = 10):
        conn = Database.get_connection()
        cursor = conn.cursor()
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
    
    GREETINGS = [
        "🌟 Добро пожаловать в наш уютный чат, {name}! Рады тебя видеть! 🌟",
        "🎉 Ого, к нам присоединился {name}! Давайте поприветствуем нового участника! 🎉",
        "✨ Привет-привет, {name}! Заходи, располагайся, чувствуй себя как дома! ✨",
        "👋 {name} переступил порог нашего чата! Рады новому собеседнику! 👋",
        "💫 И у нас пополнение! Встречайте {name} — самого крутого новичка дня! 💫",
        "🎈 {name} присоединился к веселью! Давайте сделаем ему тёплый приём! 🎈",
        "⭐ Приветствуем тебя, {name}! Надеемся, тебе у нас понравится! ⭐",
        "😊 О, новый друг! {name}, мы очень рады тебя видеть в нашем чате! 😊",
        "🤗 {name} зашёл к нам на огонёк! Присоединяйся к беседе! 🤗",
        "💖 Ура! У нас новый участник — {name}! Добро пожаловать в нашу дружную компанию! 💖"
    ]
    
    FAREWELLS = [
        "😢 Нас покидает {name}... Надеемся, это ненадолго!",
        "👋 {name} вышел из чата. Будем скучать! Возвращайся скорее!",
        "💔 {name} покинул нас... Надеемся, ты ещё вернёшься!",
        "🌟 {name} ушёл, но светит яркой звездой в наших сердцах! Возвращайся!",
        "🎈 Пока-пока, {name}! Не забывай нас, мы будем ждать тебя!",
        "✨ {name} отправился в новое путешествие! Удачи и до новых встреч!",
        "💫 {name} покинул чат... Надеемся, это всего лишь пауза!",
        "😔 Нас покинул {name}. Пусть новые дороги приведут тебя обратно к нам!",
        "👑 {name} вышел из чата. Спасибо за время, проведённое с нами!",
        "💖 До свидания, {name}! Надеемся, ты ещё вернётся в нашу дружную семью!"
    ]
    
    @staticmethod
    def get_emoji(category: str = 'random'):
        if category in Utils.EMOJIS:
            return random.choice(Utils.EMOJIS[category])
        return random.choice(Utils.EMOJIS['random'])
    
    @staticmethod
    def get_random_greeting():
        return random.choice(Utils.GREETINGS)
    
    @staticmethod
    def get_random_farewell():
        return random.choice(Utils.FAREWELLS)
    
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
        keyboard.button(text="📜 Правила бота", callback_data="rules")
        keyboard.button(text="🎮 Магазин", callback_data="shop")
        
        if user_id in ADMIN_IDS:
            keyboard.button(text="⚙️ Админ-панель", callback_data="admin_panel")
        
        keyboard.button(text="🎮 Играть", callback_data="play_game")
        keyboard.button(text="💰 Баланс", callback_data="balance")
        keyboard.button(text="🏆 Топ игроков", callback_data="top_players")
        keyboard.button(text="📊 Лог-чат", callback_data="log_chat_menu")
        keyboard.button(text="➕ Добавить в группу", url=f"https://t.me/{BOT_USERNAME}?startgroup=true")
        
        if user_id in ADMIN_IDS:
            keyboard.adjust(2, 2, 2, 1, 1)
        else:
            keyboard.adjust(1, 1, 2, 1, 1)
        
        return keyboard.as_markup()
    
    @staticmethod
    def get_admin_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="📊 Статистика", callback_data="admin_stats")
        keyboard.button(text="📣 Рассылка", callback_data="admin_broadcast")
        keyboard.button(text="💰 Выдать валюту", callback_data="admin_give_currency")
        keyboard.button(text="🔙 Выйти из админ-панели", callback_data="admin_exit")
        keyboard.adjust(2, 1, 1)
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
        keyboard.button(text="❌ Отмена", callback_data="admin_cancel")
        return keyboard.as_markup()
    
    @staticmethod
    def get_shop_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🎮 Доп. попытки (Играть)", callback_data="shop_game_attempts")
        keyboard.button(text="💼 Доп. попытки (Работать)", callback_data="shop_work_attempts")
        keyboard.button(text="👑 VIP-статус", callback_data="shop_vip")
        keyboard.button(text="🔙 Назад", callback_data="main_menu")
        keyboard.adjust(2, 1, 1)
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
        keyboard.button(text="✏️ Изменить группу", callback_data="log_chat_change")
        keyboard.button(text="🔙 Назад", callback_data="log_chat_menu")
        keyboard.adjust(2, 1)
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

# ============ ОБРАБОТЧИКИ КОМАНД ============

@router.message(CommandStart())
@router.message(F.text.lower().in_(["/startpuls", "startpuls", "старт", "/старт"]))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Нет username"
    full_name = message.from_user.full_name
    
    is_admin = user_id in ADMIN_IDS
    Database.create_user(user_id, username, full_name, is_admin)
    
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

# ============ БАЛАНС ============
@router.message(F.text.lower().in_(["баланс", "/баланс", "balance", "/balance", "профиль", "/профиль", "стата", "/стата"]))
@router.callback_query(F.data == "balance")
async def cmd_balance(message_or_callback):
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
        response = f"{Utils.get_emoji('error')} Начните с /start"
        if isinstance(message_or_callback, Message):
            await message.reply(response)
        else:
            await message.edit_text(response, reply_markup=Keyboards.get_back_to_main_keyboard())
        return
    
    coins = user_data[3] or 0
    dollars = user_data[4] or 0
    
    # Проверяем VIP статус
    vip_info = ""
    if user_data[13]:  # vip_until
        vip_until = datetime.fromisoformat(user_data[13])
        if vip_until > datetime.now():
            days_left = (vip_until - datetime.now()).days
            vip_info = f"\n👑 VIP статус активен: {days_left} дней"
    
    response = (
        f"{Utils.get_emoji('game')} <b>Ваш баланс</b>\n\n"
        f"🎮 <b>Puls Coins:</b> {coins}\n"
        f"💵 <b>Доллары:</b> ${dollars}"
        f"{vip_info}"
    )
    
    if isinstance(message_or_callback, Message):
        await message.reply(response)
    else:
        await message.edit_text(response, reply_markup=Keyboards.get_back_to_main_keyboard())

# ============ ИГРАТЬ ============
@router.message(F.text.lower().in_(["играть", "/играть", "game", "/game", "gamepuls", "/gamepuls"]))
@router.callback_query(F.data == "play_game")
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
    
    # Админы имеют 10 попыток
    max_attempts = 10 if user_id in ADMIN_IDS else 3
    
    # Проверяем VIP статус для уменьшения времени
    vip_bonus = False
    reset_hours = 5
    if user_data[13]:  # vip_until
        vip_until = datetime.fromisoformat(user_data[13])
        if vip_until > datetime.now():
            vip_bonus = True
            reset_hours = 3  # VIP уменьшает КД на 2 часа
    
    # Проверяем ограничения
    now = datetime.now()
    game_count = user_data[7] or 0
    game_vip_attempts = user_data[11] or 0
    reset_time = datetime.fromisoformat(user_data[9]) if user_data[9] else None
    
    if reset_time and now >= reset_time:
        game_count = 0
        Database.update_user(user_id, game_count=0, game_reset_time=None)
    
    # Общее количество доступных попыток
    total_attempts = game_count + game_vip_attempts
    
    if total_attempts >= max_attempts:
        if not reset_time:
            reset_time = now + timedelta(hours=reset_hours)
            Database.update_user(user_id, game_reset_time=reset_time)
        
        time_left = reset_time - now
        hours = time_left.seconds // 3600
        minutes = (time_left.seconds % 3600) // 60
        
        response = (
            f"{Utils.get_emoji('error')} <b>Лимит игр исчерпан!</b>\n\n"
            f"Вы уже сыграли {total_attempts}/{max_attempts} раз.\n"
            f"⏳ Следующая игра возможна через: {hours}ч {minutes}м\n\n"
            f"💡 Купите дополнительные попытки в магазине!"
        )
        if isinstance(message_or_callback, CallbackQuery):
            await message.edit_text(response, reply_markup=Keyboards.get_back_to_main_keyboard())
        else:
            await message.reply(response)
        return
    
    # Игра
    coins_won = random.randint(5, 50)
    new_coins = (user_data[3] or 0) + coins_won
    
    # Используем обычные попытки, потом VIP попытки
    if game_count < 3:
        game_count += 1
        Database.update_user(
            user_id,
            coins=new_coins,
            last_game=now,
            game_count=game_count,
            game_reset_time=now + timedelta(hours=reset_hours) if game_count >= 3 else None
        )
    else:
        game_vip_attempts += 1
        Database.update_user(
            user_id,
            coins=new_coins,
            last_game=now,
            game_vip_attempts=game_vip_attempts
        )
    
    response = (
        f"{Utils.get_emoji('game')} <b>Вы выиграли {coins_won} Puls Coins!</b>\n\n"
        f"💰 <b>Баланс:</b> {new_coins} монет\n"
        f"🎮 <b>Игр сыграно:</b> {total_attempts + 1}/{max_attempts}\n\n"
        f"{Utils.get_emoji('success')} Продолжайте в том же духе!"
    )
    
    if isinstance(message_or_callback, CallbackQuery):
        await message.edit_text(response, reply_markup=Keyboards.get_back_to_main_keyboard())
    else:
        await message.reply(response)

# ============ РАБОТАТЬ ============
@router.message(F.text.lower().in_(["работать", "/работать", "work", "/work"]))
async def cmd_work(message: Message):
    user_id = message.from_user.id
    
    Database.update_user(user_id, last_active=datetime.now().isoformat())
    user_data = Database.get_user(user_id)
    
    if not user_data:
        await message.reply(f"{Utils.get_emoji('error')} Начните с /start")
        return
    
    # Админы имеют больше попыток
    max_attempts = 10 if user_id in ADMIN_IDS else 5
    
    # Проверяем VIP статус для уменьшения времени
    vip_bonus = False
    reset_hours = 24
    if user_data[13]:  # vip_until
        vip_until = datetime.fromisoformat(user_data[13])
        if vip_until > datetime.now():
            vip_bonus = True
            reset_hours = 19  # VIP уменьшает КД на 5 часов
    
    # Проверяем ограничения
    now = datetime.now()
    work_count = user_data[8] or 0
    work_vip_attempts = user_data[12] or 0
    reset_time = datetime.fromisoformat(user_data[10]) if user_data[10] else None
    
    if reset_time and now >= reset_time:
        work_count = 0
        Database.update_user(user_id, work_count=0, work_reset_time=None)
    
    # Общее количество доступных попыток
    total_attempts = work_count + work_vip_attempts
    
    if total_attempts >= max_attempts:
        if not reset_time:
            reset_time = now + timedelta(hours=reset_hours)
            Database.update_user(user_id, work_reset_time=reset_time)
        
        time_left = reset_time - now
        hours = time_left.seconds // 3600
        minutes = (time_left.seconds % 3600) // 60
        
        response = (
            f"{Utils.get_emoji('error')} <b>Лимит работы исчерпан!</b>\n\n"
            f"Вы уже поработали {total_attempts}/{max_attempts} раз.\n"
            f"⏳ Следующая работа возможна через: {hours}ч {minutes}м\n\n"
            f"💡 Купите дополнительные попытки в магазине!"
        )
        await message.reply(response)
        return
    
    # Работа
    dollars_earned = random.randint(1, 20)
    new_dollars = (user_data[4] or 0) + dollars_earned
    
    # Используем обычные попытки, потом VIP попытки
    if work_count < 5:
        work_count += 1
        Database.update_user(
            user_id,
            dollars=new_dollars,
            last_work=now,
            work_count=work_count,
            work_reset_time=now + timedelta(hours=reset_hours) if work_count >= 5 else None
        )
    else:
        work_vip_attempts += 1
        Database.update_user(
            user_id,
            dollars=new_dollars,
            last_work=now,
            work_vip_attempts=work_vip_attempts
        )
    
    response = (
        f"{Utils.get_emoji('success')} <b>Работа выполнена!</b>\n\n"
        f"💰 <b>Заработано:</b> ${dollars_earned}\n\n"
        f"💵 <b>Баланс:</b> ${new_dollars}\n"
        f"📊 <b>Работ выполнено:</b> {total_attempts + 1}/{max_attempts}\n\n"
        f"💪 Отличная работа!"
    )
    
    await message.reply(response)

# ============ МОДЕРАЦИЯ ============
async def get_target_user(message: Message, target: str):
    """Получает пользователя по ID, username или reply с проверками"""
    try:
        if message.reply_to_message:
            return message.reply_to_message.from_user
        
        if target.startswith('@'):
            return type('User', (), {
                'id': 0,
                'full_name': target,
                'username': target.lstrip('@'),
                'is_bot': False
            })()
        elif target.isdigit():
            target_id = int(target)
            user_data = Database.get_user(target_id)
            if user_data:
                return type('User', (), {
                    'id': target_id,
                    'full_name': user_data[2],
                    'username': user_data[1] or 'Нет',
                    'is_bot': False
                })()
    except:
        pass
    return None

async def check_permissions(user_id: int, chat_id: int, action: str, target_user) -> Tuple[bool, str]:
    """Проверяет права на выполнение действия"""
    # Проверка на себя
    if target_user.id == user_id:
        return False, f"{Utils.get_emoji('error')} Нельзя наказывать самого себя!"
    
    # Проверка на бота
    if target_user.is_bot:
        return False, f"{Utils.get_emoji('error')} Нельзя наказывать ботов!"
    
    # Проверка прав администратора чата
    try:
        chat_member = await bot.get_chat_member(chat_id, target_user.id)
        if chat_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            return False, f"{Utils.get_emoji('error')} Нельзя наказывать администраторов чата!"
    except:
        pass
    
    # Проверка прав модератора
    is_admin = user_id in ADMIN_IDS
    has_right = False
    
    if is_admin:
        has_right = True
    elif action == 'mute':
        has_right = Database.check_moderator_right(user_id, chat_id, 'mute')
    elif action == 'ban':
        has_right = Database.check_moderator_right(user_id, chat_id, 'ban')
    elif action == 'kick':
        has_right = Database.check_moderator_right(user_id, chat_id, 'kick')
    
    if not has_right:
        return False, f"{Utils.get_emoji('error')} ⛔ Недостаточно прав!"
    
    return True, ""

# ============ ОБРАБОТКА КОМАНД МОДЕРАЦИИ ============
@router.message(F.chat.type.in_(["group", "supergroup"]))
async def handle_moderation_commands(message: Message):
    if not message.text:
        return
    
    text = message.text.strip()
    words = text.split()
    
    if len(words) < 1:
        return
    
    command = words[0].lstrip('/').lower()
    
    # Команды модерации (одна буква, русская/английская)
    command_map = {
        'm': 'mute', 'м': 'mute',  # Мут
        'b': 'ban', 'б': 'ban',    # Бан
        'k': 'kick', 'к': 'kick',  # Кик
    }
    
    # Команды выдачи прав
    if command in ['+м', '+m', '+мут', '+mute']:
        await handle_add_mod_rights_command(message, words, 'mute')
        return
    elif command in ['+б', '+b', '+бан', '+ban']:
        await handle_add_mod_rights_command(message, words, 'ban')
        return
    elif command in ['+к', '+k', '+кик', '+kick']:
        await handle_add_mod_rights_command(message, words, 'kick')
        return
    
    if command not in command_map:
        return
    
    action = command_map[command]
    await handle_punishment_command(message, words, action)

async def handle_add_mod_rights_command(message: Message, words: List[str], right_type: str):
    if len(words) < 2:
        await message.reply(f"{Utils.get_emoji('error')} Использование: {words[0]} [ID/@username/reply]")
        return
    
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Только админы могут выдавать права
    if user_id not in ADMIN_IDS:
        await message.reply(f"{Utils.get_emoji('error')} Только администраторы могут выдавать права!")
        return
    
    target_user = await get_target_user(message, words[1])
    
    if not target_user:
        await message.reply(f"{Utils.get_emoji('error')} Не удалось найти пользователя.")
        return
    
    # Проверка на себя
    if target_user.id == user_id:
        await message.reply(f"{Utils.get_emoji('error')} Нельзя выдавать права самому себе!")
        return
    
    # Проверка на бота
    if target_user.is_bot:
        await message.reply(f"{Utils.get_emoji('error')} Нельзя выдавать права ботам!")
        return
    
    # Даём права
    rights = {'mute': False, 'ban': False, 'kick': False}
    rights[right_type] = True
    
    Database.add_moderator_right(target_user.id, chat_id, rights, user_id)
    
    response = (
        f"{Utils.get_emoji('success')} <b>Права модератора выданы!</b>\n\n"
        f"👤 Пользователь: {target_user.full_name}\n"
        f"🆔 ID: <code>{target_user.id}</code>\n"
        f"🔧 Права: {right_type}\n"
        f"👮 Выдал: {message.from_user.full_name}"
    )
    
    await message.reply(response)

async def handle_punishment_command(message: Message, words: List[str], action: str):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Определяем цель
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
        time_index = 1
        reason_index = 2
    else:
        if len(words) < 3 and action in ['mute', 'ban']:
            usage = f"{words[0]} [время] [причина] или reply + {words[0]} [время] [причина]"
            await message.reply(f"{Utils.get_emoji('error')} Использование: {usage}")
            return
        elif len(words) < 2 and action == 'kick':
            usage = f"{words[0]} [причина] или reply + {words[0]} [причина]"
            await message.reply(f"{Utils.get_emoji('error')} Использование: {usage}")
            return
        
        target = words[1]
        target_user = await get_target_user(message, target)
        
        if not target_user:
            await message.reply(f"{Utils.get_emoji('error')} Не удалось найти пользователя.")
            return
        
        time_index = 2
        reason_index = 3 if action in ['mute', 'ban'] else 2
    
    # Проверяем права и безопасность
    has_permission, error_msg = await check_permissions(user_id, chat_id, action, target_user)
    if not has_permission:
        await message.reply(error_msg)
        return
    
    # Парсим время
    duration = None
    if action in ['mute', 'ban']:
        if len(words) > time_index:
            time_str = words[time_index]
            duration = Utils.parse_time(time_str)
        
        if not duration:
            duration = timedelta(hours=1)
    
    # Проверяем ограничения по времени
    if duration:
        is_valid, error_msg = Utils.validate_punishment_time(duration)
        if not is_valid:
            await message.reply(f"{Utils.get_emoji('error')} {error_msg}")
            return
    
    # Получаем причину
    reason = "Не указана"
    if len(words) > reason_index:
        reason = ' '.join(words[reason_index:])
    
    # Применяем наказание через Telegram API
    until_date = datetime.now() + duration if duration else datetime.now() + timedelta(minutes=1)
    moderator = message.from_user
    
    try:
        if action == 'mute':
            # Мут в Telegram
            until_timestamp = int(until_date.timestamp())
            permissions = ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False
            )
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_user.id,
                permissions=permissions,
                until_date=until_timestamp
            )
            
        elif action == 'ban':
            # Бан в Telegram
            until_timestamp = int(until_date.timestamp())
            await bot.ban_chat_member(
                chat_id=chat_id,
                user_id=target_user.id,
                until_date=until_timestamp
            )
            
        elif action == 'kick':
            # Кик в Telegram (бан и разбан)
            await bot.ban_chat_member(chat_id=chat_id, user_id=target_user.id)
            await asyncio.sleep(1)
            await bot.unban_chat_member(chat_id=chat_id, user_id=target_user.id)
        
        # Сохраняем в БД
        Database.add_restriction(
            target_user.id, chat_id, action,
            until_date, reason, 0, moderator.id, moderator.full_name
        )
        
        # Отправляем сообщение о наказании
        if action == 'mute':
            response = (
                f"{Utils.get_emoji('moderation')} <b>Пользователь получил мут!</b>\n\n"
                f"👤 Пользователь: {target_user.full_name}\n"
                f"🆔 ID: <code>{target_user.id}</code>\n"
                f"⏰ Длительность: {Utils.format_time(duration) if duration else 'навсегда'}\n"
                f"📝 Причина: {reason}\n"
                f"👮 Модератор: {moderator.full_name}"
            )
        elif action == 'ban':
            response = (
                f"{Utils.get_emoji('moderation')} <b>Пользователь забанен!</b>\n\n"
                f"👤 Пользователь: {target_user.full_name}\n"
                f"🆔 ID: <code>{target_user.id}</code>\n"
                f"⏰ Длительность: {Utils.format_time(duration) if duration else 'навсегда'}\n"
                f"📝 Причина: {reason}\n"
                f"👮 Модератор: {moderator.full_name}"
            )
        else:  # kick
            response = (
                f"{Utils.get_emoji('moderation')} <b>Пользователь кикнут!</b>\n\n"
                f"👤 Пользователь: {target_user.full_name}\n"
                f"🆔 ID: <code>{target_user.id}</code>\n"
                f"📝 Причина: {reason}\n"
                f"👮 Модератор: {moderator.full_name}"
            )
        
        await message.reply(response)
        
    except TelegramForbiddenError:
        await message.reply(f"{Utils.get_emoji('error')} У бота недостаточно прав для выполнения этого действия!")
    except Exception as e:
        logger.error(f"Ошибка при наказании: {e}")
        await message.reply(f"{Utils.get_emoji('error')} Произошла ошибка при выполнении действия!")

# ============ АДМИН-ПАНЕЛЬ ============
@router.callback_query(F.data == "admin_panel")
async def callback_admin_panel(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
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
    
    if user_id not in ADMIN_IDS:
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
            reply_markup=Keyboards.get_admin_keyboard()
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
    
    if user_id not in ADMIN_IDS:
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
        # Статистика
        total_users = len(Database.get_all_users())
        total_coins = Database.get_total_coins()
        total_dollars = Database.get_total_dollars()
        active_users_today = Database.get_active_users_today()
        
        stats_text = (
            f"{Utils.get_emoji('info')} <b>📊 Статистика бота</b>\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"🎮 Всего Puls Coins: {total_coins}\n"
            f"💵 Всего долларов: ${total_dollars}\n"
            f"📈 Активных сегодня: {active_users_today}\n"
            f"👑 Админов: {len(ADMIN_IDS)}"
        )
        
        try:
            msg = await callback.message.edit_text(
                stats_text,
                reply_markup=Keyboards.get_admin_keyboard()
            )
            add_admin_message(user_id, msg.message_id)
        except:
            msg = await callback.message.answer(
                stats_text,
                reply_markup=Keyboards.get_admin_keyboard()
            )
            add_admin_message(user_id, msg.message_id)
    
    elif data == "admin_broadcast":
        # Рассылка
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
        # Выдача валюты
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
    
    elif data == "admin_back_to_panel":
        try:
            msg = await callback.message.edit_text(
                f"{Utils.get_emoji('info')} <b>Админ-панель</b>\n\n"
                "Выберите действие:",
                reply_markup=Keyboards.get_admin_keyboard()
            )
            add_admin_message(user_id, msg.message_id)
        except:
            msg = await callback.message.answer(
                f"{Utils.get_emoji('info')} <b>Админ-панель</b>\n\n"
                "Выберите действие:",
                reply_markup=Keyboards.get_admin_keyboard()
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

# ============ ОБРАБОТЧИК РАССЫЛКИ ============
@router.message(AdminStates.waiting_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text
    
    if not text:
        await message.answer("Пожалуйста, введите текст для рассылки.")
        return
    
    # Получаем всех пользователей
    all_users = Database.get_all_users()
    
    # Отправляем статус
    status_msg = await message.answer(
        f"{Utils.get_emoji('info')} <b>📣 Начинаю рассылку...</b>\n\n"
        f"Получателей: {len(all_users)}\n"
        f"Сообщение отправляется..."
    )
    
    success_count = 0
    fail_count = 0
    
    # Отправляем сообщения
    for user in all_users:
        try:
            await bot.send_message(user, text)
            success_count += 1
        except Exception as e:
            fail_count += 1
        
        # Небольшая задержка, чтобы не превысить лимиты Telegram
        await asyncio.sleep(0.1)
    
    # Обновляем статус
    await status_msg.edit_text(
        f"{Utils.get_emoji('success')} <b>✅ Рассылка завершена!</b>\n\n"
        f"📊 Статистика:\n"
        f"✅ Успешно: {success_count}\n"
        f"❌ Не доставлено: {fail_count}\n"
        f"👥 Всего получателей: {len(all_users)}"
    )
    
    await state.clear()
    
    # Возвращаем в админ-панель
    msg = await message.answer(
        f"{Utils.get_emoji('info')} <b>Админ-панель</b>\n\n"
        "Выберите действие:",
        reply_markup=Keyboards.get_admin_keyboard()
    )
    add_admin_message(user_id, msg.message_id)
    
    try:
        await message.delete()
    except:
        pass

# ============ ВЫДАЧА ВАЛЮТЫ ============
@router.callback_query(F.data.in_(["give_coins", "give_dollars"]))
async def callback_give_currency(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
        await callback.answer(f"{Utils.get_emoji('error')} Нет доступа!", show_alert=True)
        return
    
    is_active, error_msg = check_admin_session(user_id)
    if not is_active:
        await callback.answer(error_msg, show_alert=True)
        return
    
    currency_type = "коинов" if callback.data == "give_coins" else "долларов"
    await state.update_data(currency_type=callback.data)
    await state.set_state(AdminStates.waiting_target_user)
    
    try:
        msg = await callback.message.edit_text(
            f"{Utils.get_emoji('info')} <b>💰 Выдача {currency_type}</b>\n\n"
            "Введите ID пользователя или его @username:",
            reply_markup=Keyboards.get_cancel_keyboard()
        )
        add_admin_message(user_id, msg.message_id)
    except:
        msg = await callback.message.answer(
            f"{Utils.get_emoji('info')} <b>💰 Выдача {currency_type}</b>\n\n"
            "Введите ID пользователя или его @username:",
            reply_markup=Keyboards.get_cancel_keyboard()
        )
        add_admin_message(user_id, msg.message_id)
    
    await callback.answer()

@router.message(AdminStates.waiting_target_user)
async def process_target_user(message: Message, state: FSMContext):
    user_id = message.from_user.id
    target = message.text.strip()
    
    # Получаем user_id из ввода
    target_user_id = None
    
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
    
    if not target_user_id:
        await message.answer(
            f"{Utils.get_emoji('error')} Пользователь не найден!\n"
            "Введите ID пользователя или его @username еще раз:"
        )
        return
    
    # Проверяем существование пользователя
    user_data = Database.get_user(target_user_id)
    if not user_data:
        await message.answer(
            f"{Utils.get_emoji('error')} Пользователь не найден в базе данных!\n"
            "Введите ID пользователя или его @username еще раз:"
        )
        return
    
    await state.update_data(target_user_id=target_user_id)
    
    data = await state.get_data()
    currency_type = data['currency_type']
    
    if currency_type == "give_coins":
        await state.set_state(AdminStates.waiting_coins_amount)
        await message.answer(
            f"{Utils.get_emoji('info')} <b>💰 Выдача Puls Coins</b>\n\n"
            f"Пользователь: {user_data[2]}\n"
            f"ID: {target_user_id}\n\n"
            "Введите количество коинов для выдачи:"
        )
    else:
        await state.set_state(AdminStates.waiting_dollars_amount)
        await message.answer(
            f"{Utils.get_emoji('info')} <b>💰 Выдача Долларов</b>\n\n"
            f"Пользователь: {user_data[2]}\n"
            f"ID: {target_user_id}\n\n"
            "Введите количество долларов для выдачи:"
        )
    
    try:
        await message.delete()
    except:
        pass

@router.message(AdminStates.waiting_coins_amount)
async def process_coins_amount(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if not message.text.isdigit():
        await message.answer(
            f"{Utils.get_emoji('error')} Пожалуйста, введите число:"
        )
        return
    
    amount = int(message.text)
    data = await state.get_data()
    target_user_id = data['target_user_id']
    
    # Выдаём коины
    Database.add_coins_to_user(target_user_id, amount)
    
    user_data = Database.get_user(target_user_id)
    
    await message.answer(
        f"{Utils.get_emoji('success')} <b>✅ Коины успешно выданы!</b>\n\n"
        f"👤 Пользователь: {user_data[2]}\n"
        f"🆔 ID: {target_user_id}\n"
        f"💰 Выдано: {amount} Puls Coins\n"
        f"💰 Новый баланс: {user_data[3] + amount} Puls Coins"
    )
    
    await state.clear()
    
    # Обновляем админ-панель
    msg = await message.answer(
        f"{Utils.get_emoji('info')} <b>Админ-панель</b>\n\n"
        "Выберите действие:",
        reply_markup=Keyboards.get_admin_keyboard()
    )
    add_admin_message(user_id, msg.message_id)
    
    try:
        await message.delete()
    except:
        pass

@router.message(AdminStates.waiting_dollars_amount)
async def process_dollars_amount(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if not message.text.isdigit():
        await message.answer(
            f"{Utils.get_emoji('error')} Пожалуйста, введите число:"
        )
        return
    
    amount = int(message.text)
    data = await state.get_data()
    target_user_id = data['target_user_id']
    
    # Выдаём доллары
    Database.add_dollars_to_user(target_user_id, amount)
    
    user_data = Database.get_user(target_user_id)
    
    await message.answer(
        f"{Utils.get_emoji('success')} <b>✅ Доллары успешно выданы!</b>\n\n"
        f"👤 Пользователь: {user_data[2]}\n"
        f"🆔 ID: {target_user_id}\n"
        f"💰 Выдано: ${amount}\n"
        f"💰 Новый баланс: ${user_data[4] + amount}"
    )
    
    await state.clear()
    
    # Обновляем админ-панель
    msg = await message.answer(
        f"{Utils.get_emoji('info')} <b>Админ-панель</b>\n\n"
        "Выберите действие:",
        reply_markup=Keyboards.get_admin_keyboard()
    )
    add_admin_message(user_id, msg.message_id)
    
    try:
        await message.delete()
    except:
        pass

# ============ МАГАЗИН ============
@router.callback_query(F.data == "shop")
async def callback_shop(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if callback.message.chat.type != "private":
        await callback.answer(f"{Utils.get_emoji('error')} Магазин доступен только в ЛС!", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"{Utils.get_emoji('shop')} <b>🎮 Магазин Puls Bot</b>\n\n"
        "Выберите категорию:",
        reply_markup=Keyboards.get_shop_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "shop_game_attempts")
async def callback_shop_game_attempts(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = Database.get_user(user_id)
    
    if not user_data:
        await callback.answer(f"{Utils.get_emoji('error')} Начните с /start", show_alert=True)
        return
    
    coins = user_data[3] or 0
    
    # Проверяем, исчерпаны ли обычные попытки
    game_count = user_data[7] or 0
    if game_count < 3:
        await callback.answer(f"{Utils.get_emoji('error')} У вас еще есть обычные попытки!", show_alert=True)
        return
    
    # Проверяем лимит VIP попыток
    game_vip_attempts = user_data[11] or 0
    if game_vip_attempts >= 2:
        await callback.answer(f"{Utils.get_emoji('error')} Лимит VIP попыток исчерпан!", show_alert=True)
        return
    
    await state.set_state(ShopStates.waiting_game_attempts)
    
    await callback.message.edit_text(
        f"{Utils.get_emoji('shop')} <b>🎮 Дополнительные попытки 'Играть'</b>\n\n"
        f"💰 Ваш баланс: {coins} Puls Coins\n"
        f"💎 Стоимость: 30 Puls Coins за 1 попытку\n"
        f"🎮 Доступно к покупке: {2 - game_vip_attempts} попыток\n\n"
        "Введите количество попыток для покупки:",
        reply_markup=Keyboards.get_cancel_keyboard()
    )
    await callback.answer()

@router.message(ShopStates.waiting_game_attempts)
async def process_game_attempts_purchase(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = Database.get_user(user_id)
    
    if not message.text.isdigit():
        await message.answer(f"{Utils.get_emoji('error')} Пожалуйста, введите число:")
        return
    
    quantity = int(message.text)
    
    if quantity <= 0:
        await message.answer(f"{Utils.get_emoji('error')} Количество должно быть больше 0:")
        return
    
    # Проверяем лимит
    game_vip_attempts = user_data[11] or 0
    if game_vip_attempts + quantity > 2:
        await message.answer(
            f"{Utils.get_emoji('error')} Вы можете купить максимум {2 - game_vip_attempts} попыток!"
        )
        return
    
    # Проверяем баланс
    coins = user_data[3] or 0
    cost = quantity * 30
    
    if coins < cost:
        await message.answer(
            f"{Utils.get_emoji('error')} Недостаточно Puls Coins!\n"
            f"💰 Нужно: {cost} коинов\n"
            f"💰 У вас: {coins} коинов"
        )
        return
    
    # Покупка
    Database.update_user(
        user_id,
        coins=coins - cost,
        game_vip_attempts=game_vip_attempts + quantity
    )
    
    await message.answer(
        f"{Utils.get_emoji('success')} <b>✅ Покупка успешна!</b>\n\n"
        f"🎮 Куплено попыток: {quantity}\n"
        f"💰 Потрачено: {cost} Puls Coins\n"
        f"🎮 Всего VIP попыток: {game_vip_attempts + quantity}/2\n\n"
        f"💡 Используйте команду 'играть'!"
    )
    
    await state.clear()
    
    # Возвращаем в магазин
    await message.answer(
        f"{Utils.get_emoji('shop')} <b>🎮 Магазин Puls Bot</b>\n\n"
        "Выберите категорию:",
        reply_markup=Keyboards.get_shop_keyboard()
    )
    
    try:
        await message.delete()
    except:
        pass

@router.callback_query(F.data == "shop_vip")
async def callback_shop_vip(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if callback.message.chat.type != "private":
        await callback.answer(f"{Utils.get_emoji('error')} Магазин доступен только в ЛС!", show_alert=True)
        return
    
    user_data = Database.get_user(user_id)
    if not user_data:
        await callback.answer(f"{Utils.get_emoji('error')} Начните с /start", show_alert=True)
        return
    
    coins = user_data[3] or 0
    dollars = user_data[4] or 0
    
    vip_info = ""
    if user_data[13]:  # vip_until
        vip_until = datetime.fromisoformat(user_data[13])
        if vip_until > datetime.now():
            days_left = (vip_until - datetime.now()).days
            vip_info = f"\n👑 Текущий VIP активен: {days_left} дней\n"
    
    await callback.message.edit_text(
        f"{Utils.get_emoji('shop')} <b>👑 VIP-статус</b>\n\n"
        f"💰 Баланс: {coins} Puls Coins + ${dollars}"
        f"{vip_info}"
        f"\n🎮 Бонусы VIP-статуса:\n"
        f"• -2 часа к КД 'Играть'\n"
        f"• -5 часов к КД 'Работать'\n"
        f"• Возможность купить VIP-попытки\n"
        f"• Приоритетная поддержка\n\n"
        f"Выберите срок VIP-статуса:",
        reply_markup=Keyboards.get_vip_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("vip_"))
async def callback_vip_purchase(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_data = Database.get_user(user_id)
    
    if not user_data:
        await callback.answer(f"{Utils.get_emoji('error')} Начните с /start", show_alert=True)
        return
    
    vip_type = callback.data
    coins = user_data[3] or 0
    dollars = user_data[4] or 0
    
    # Определяем цены в зависимости от типа VIP
    prices = {
        'vip_1': {'coins': 1000, 'dollars': 500, 'months': 1},
        'vip_2': {'coins': 2000, 'dollars': 1000, 'months': 2},
        'vip_5': {'coins': 5000, 'dollars': 2500, 'months': 5},
        'vip_12': {'coins': 12000, 'dollars': 6000, 'months': 12}
    }
    
    price = prices.get(vip_type)
    if not price:
        await callback.answer(f"{Utils.get_emoji('error')} Неверный тип VIP", show_alert=True)
        return
    
    # Проверяем баланс
    if coins < price['coins']:
        await callback.answer(
            f"{Utils.get_emoji('error')} Недостаточно Puls Coins!\n"
            f"Нужно: {price['coins']} коинов\n"
            f"У вас: {coins} коинов",
            show_alert=True
        )
        return
    
    if dollars < price['dollars']:
        await callback.answer(
            f"{Utils.get_emoji('error')} Недостаточно долларов!\n"
            f"Нужно: {price['dollars']}$\n"
            f"У вас: {dollars}$",
            show_alert=True
        )
        return
    
    # Рассчитываем новую дату окончания VIP
    current_vip = user_data[13]  # vip_until
    vip_until = datetime.now()
    
    if current_vip:
        current_vip_date = datetime.fromisoformat(current_vip)
        if current_vip_date > datetime.now():
            vip_until = current_vip_date
    
    vip_until = vip_until + timedelta(days=30 * price['months'])
    
    # Применяем покупку
    Database.update_user(
        user_id,
        coins=coins - price['coins'],
        dollars=dollars - price['dollars'],
        vip_until=vip_until.isoformat()
    )
    
    await callback.message.edit_text(
        f"{Utils.get_emoji('success')} <b>✅ VIP-статус куплен!</b>\n\n"
        f"👑 Срок: {price['months']} месяцев\n"
        f"💰 Потрачено: {price['coins']} Puls Coins + {price['dollars']}$\n"
        f"📅 VIP действует до: {vip_until.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"🎮 Бонусы:\n"
        f"• -2 часа к КД 'Играть'\n"
        f"• -5 часов к КД 'Работать'\n"
        f"• Дополнительные VIP-попытки",
        reply_markup=Keyboards.get_back_to_main_keyboard()
    )
    await callback.answer()

# ============ ЛОГ-ЧАТ ============
@router.callback_query(F.data == "log_chat_menu")
async def callback_log_chat_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    log_chat = Database.get_log_chat(user_id)
    
    has_log_chat = bool(log_chat)
    chat_title = log_chat[3] if log_chat else None
    
    await callback.message.edit_text(
        f"{Utils.get_emoji('info')} <b>📊 Управление лог-чатом</b>\n\n"
        "Здесь вы можете настроить чат для логов наказаний.",
        reply_markup=Keyboards.get_log_chat_keyboard(has_log_chat, chat_title)
    )
    await callback.answer()

@router.callback_query(F.data == "log_chat_add")
async def callback_log_chat_add(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_log_chat)
    
    await callback.message.edit_text(
        f"{Utils.get_emoji('info')} <b>➕ Добавление лог-чата</b>\n\n"
        "Чтобы добавить группу для логов:\n\n"
        "1. Добавьте бота в группу\n"
        "2. Сделайте бота администратором\n"
        "3. Отправьте ID группы сюда\n\n"
        "Введите ID группы для логов:",
        reply_markup=Keyboards.get_cancel_keyboard()
    )
    await callback.answer()

@router.message(AdminStates.waiting_log_chat)
async def process_log_chat_id(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if message.text and message.text.strip().lstrip('-').isdigit():
        chat_id = int(message.text.strip())
        
        # Проверяем, что бот в этом чате
        try:
            chat = await bot.get_chat(chat_id)
            chat_title = chat.title
            
            # Проверяем права бота в чате
            bot_member = await bot.get_chat_member(chat_id, bot.id)
            if bot_member.status != ChatMemberStatus.ADMINISTRATOR:
                await message.answer(
                    f"{Utils.get_emoji('error')} ❌ <b>Ошибка!</b>\n\n"
                    f"Бот не является администратором в чате '{chat_title}'.\n"
                    f"Пожалуйста, выдайте боту права администратора и попробуйте снова."
                )
                return
            
            # Сохраняем лог-чат
            Database.set_log_chat(user_id, message.chat.id, chat_id, chat_title)
            
            await message.answer(
                f"{Utils.get_emoji('success')} ✅ <b>Лог-чат настроен!</b>\n\n"
                f"📊 Чат: {chat_title}\n"
                f"🆔 ID: <code>{chat_id}</code>\n"
                f"Все действия модерации теперь будут логироваться.",
                reply_markup=Keyboards.get_back_to_main_keyboard()
            )
            
        except TelegramBadRequest:
            await message.answer(
                f"{Utils.get_emoji('error')} ❌ <b>Ошибка!</b>\n\n"
                f"Бот не добавлен в указанный чат или чат не существует.\n"
                f"Убедитесь, что:\n"
                f"1. Бот добавлен в чат\n"
                f"2. Бот является администратором\n"
                f"3. ID чата указан правильно"
            )
        except Exception as e:
            logger.error(f"Ошибка при настройке лог-чата: {e}")
            await message.answer(
                f"{Utils.get_emoji('error')} ❌ <b>Ошибка!</b>\n\n"
                f"Произошла ошибка: {str(e)[:100]}"
            )
    
    await state.clear()

# ============ ДОПОЛНИТЕЛЬНЫЕ ОБРАБОТЧИКИ ============
@router.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def new_chat_member(event: ChatMemberUpdated):
    new_member = event.new_chat_member.user
    chat = event.chat
    
    if new_member.id == bot.id:
        return
    
    Database.create_user(new_member.id, new_member.username or "Нет", new_member.full_name)
    
    greeting = Utils.get_random_greeting().format(name=new_member.full_name)
    
    member_info = (
        f"\n\n📋 Информация об участнике:\n"
        f"• Имя: {new_member.full_name}\n"
        f"• ID: {new_member.id}\n"
        f"• Username: @{new_member.username or 'Нет'}\n"
        f"• Бот: {'🤖 Да' if new_member.is_bot else '👤 Нет'}\n\n"
        f"✨ Рады приветствовать в чате!"
    )
    
    await bot.send_message(chat_id=chat.id, text=greeting + member_info)

@router.chat_member(ChatMemberUpdatedFilter(LEAVE_TRANSITION))
async def left_chat_member(event: ChatMemberUpdated):
    left_member = event.old_chat_member.user
    chat = event.chat
    
    if left_member.id == bot.id:
        return
    
    farewell = Utils.get_random_farewell().format(name=left_member.full_name)
    
    member_info = (
        f"\n\n📋 Информация:\n"
        f"• Имя: {left_member.full_name}\n"
        f"• ID: {left_member.id}\n"
        f"• Username: @{left_member.username or 'Нет'}\n\n"
        f"💔 Надеемся, вы ещё вернётесь!"
    )
    
    await bot.send_message(chat_id=chat.id, text=farewell + member_info)

@router.callback_query(F.data == "rules")
async def callback_rules(callback: CallbackQuery):
    rules_text = (
        f"📜 Правила использования Puls Bot\n\n"
        f"1. 🤖 Уважение к боту\n"
        f"2. 👥 Взаимодействие с участниками\n"
        f"3. 🎮 Честная игра\n"
        f"4. 🔧 Справедливая модерация\n\n"
        f"Спасибо за понимание! 😊"
    )
    
    try:
        await callback.message.edit_text(rules_text, reply_markup=Keyboards.get_back_to_main_keyboard())
    except:
        await callback.message.answer(rules_text, reply_markup=Keyboards.get_back_to_main_keyboard())
    
    await callback.answer()

@router.callback_query(F.data == "top_players")
async def callback_top_players(callback: CallbackQuery):
    top_players = Database.get_top_players(10)
    
    if not top_players:
        top_text = "🏆 Топ игроков пуст!\nПока никто не заработал Puls Coins."
    else:
        top_text = "🏆 ТОП-10 игроков по Puls Coins 🏆\n\n"
        
        for i, player in enumerate(top_players, 1):
            user_id, username, full_name, coins = player
            medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
            name_display = f"@{username}" if username and username != "Нет" else full_name
            top_text += f"{medal} {name_display} - {coins} Puls Coins\n"
    
    try:
        await callback.message.edit_text(top_text, reply_markup=Keyboards.get_back_to_main_keyboard())
    except:
        await callback.message.answer(top_text, reply_markup=Keyboards.get_back_to_main_keyboard())
    
    await callback.answer()

@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    # При выходе в главное меню закрываем админ-сессию
    remove_admin_session(user_id)
    
    try:
        await callback.message.edit_text(
            "Главное меню:",
            reply_markup=Keyboards.get_main_keyboard(user_id)
        )
    except:
        await callback.message.answer(
            "Главное меню:",
            reply_markup=Keyboards.get_main_keyboard(user_id)
        )
    
    await callback.answer()

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

# ============ ЗАПУСК БОТА ============
async def main():
    # Запускаем фоновые задачи
    asyncio.create_task(check_admin_sessions())
    
    logger.info("Бот запускается...")
    logger.info(f"Админ ID: {ADMIN_IDS}")
    logger.info(f"Бот username: @{BOT_USERNAME}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())хх
