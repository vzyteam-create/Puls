import asyncio
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
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

# Время автоудаления служебных сообщений (секунды)
AUTO_DELETE_TIME = 30

# ============ ИНИЦИАЛИЗАЦИЯ БОТА ============
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ============ СОСТОЯНИЯ FSM ============
class AdminStates(StatesGroup):
    waiting_password = State()

# Словари для хранения админ-сессий и сообщений
admin_sessions: Dict[int, datetime] = {}
admin_messages: Dict[int, List[int]] = {}
messages_to_delete: Dict[int, List[Tuple[int, datetime]]] = {}  # chat_id -> [(message_id, delete_time)]

# Словарь для лог-чатов
log_chats: Dict[int, int] = {}  # chat_id -> log_chat_id

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
        is_admin BOOLEAN DEFAULT 0
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
        chat_id INTEGER PRIMARY KEY,
        log_chat_id INTEGER,
        set_by INTEGER,
        set_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Индексы
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_restrictions_user ON restrictions(user_id, chat_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_restrictions_time ON restrictions(until)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_moderator_rights ON moderator_rights(user_id, chat_id)')
    
    conn.commit()
    conn.close()

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
            INSERT OR IGNORE INTO users (user_id, username, full_name, coins, dollars, is_admin)
            VALUES (?, ?, ?, 0, 0, ?)
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
    def add_restriction(user_id: int, chat_id: int, restriction_type: str,
                       until: datetime, reason: str, moderator_id: int, moderator_name: str, message_id: int = None):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO restrictions (user_id, chat_id, restriction_type, until, reason, moderator_id, moderator_name, message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, chat_id, restriction_type, until, reason, moderator_id, moderator_name, message_id))
        conn.commit()
        conn.close()
    
    @staticmethod
    def update_restriction_status(restriction_id: int, status: str = 'removed'):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE restrictions SET status = ? WHERE id = ?', (status, restriction_id))
        conn.commit()
        conn.close()
    
    @staticmethod
    def remove_restriction(user_id: int, chat_id: int, restriction_type: str = None):
        conn = Database.get_connection()
        cursor = conn.cursor()
        if restriction_type:
            cursor.execute('''
                UPDATE restrictions SET status = 'removed'
                WHERE user_id = ? AND chat_id = ? AND restriction_type = ? AND status = 'active'
            ''', (user_id, chat_id, restriction_type))
        else:
            cursor.execute('''
                UPDATE restrictions SET status = 'removed'
                WHERE user_id = ? AND chat_id = ? AND status = 'active'
            ''', (user_id, chat_id))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_restriction(user_id: int, chat_id: int, restriction_type: str = None):
        conn = Database.get_connection()
        cursor = conn.cursor()
        if restriction_type:
            cursor.execute('''
                SELECT * FROM restrictions 
                WHERE user_id = ? AND chat_id = ? AND restriction_type = ? AND status = 'active'
            ''', (user_id, chat_id, restriction_type))
        else:
            cursor.execute('''
                SELECT * FROM restrictions 
                WHERE user_id = ? AND chat_id = ? AND status = 'active'
            ''', (user_id, chat_id))
        restriction = cursor.fetchone()
        conn.close()
        return restriction
    
    @staticmethod
    def get_restriction_by_message(chat_id: int, message_id: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM restrictions WHERE chat_id = ? AND message_id = ? AND status = "active"', 
                      (chat_id, message_id))
        restriction = cursor.fetchone()
        conn.close()
        return restriction
    
    @staticmethod
    def get_active_restrictions():
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM restrictions WHERE until > ? AND status = "active"', 
                      (datetime.now().isoformat(),))
        restrictions = cursor.fetchall()
        conn.close()
        return restrictions
    
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
    
    @staticmethod
    def check_admin_lock(user_id: int) -> tuple:
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT failed_attempts, lock_until, last_attempt FROM admin_lock WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            failed_attempts, lock_until_str, last_attempt_str = result
            lock_until = datetime.fromisoformat(lock_until_str) if lock_until_str else None
            last_attempt = datetime.fromisoformat(last_attempt_str) if last_attempt_str else None
            return failed_attempts, lock_until, last_attempt
        return 0, None, None
    
    @staticmethod
    def update_admin_lock(user_id: int, failed_attempts: int = None, lock_until: datetime = None):
        conn = Database.get_connection()
        cursor = conn.cursor()
        
        if failed_attempts is not None:
            cursor.execute('''
                INSERT OR REPLACE INTO admin_lock (user_id, failed_attempts, lock_until, last_attempt)
                VALUES (?, ?, ?, ?)
            ''', (user_id, failed_attempts, lock_until.isoformat() if lock_until else None, datetime.now().isoformat()))
        else:
            cursor.execute('DELETE FROM admin_lock WHERE user_id = ?', (user_id,))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def set_log_chat(chat_id: int, log_chat_id: int, set_by: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO log_chats (chat_id, log_chat_id, set_by)
            VALUES (?, ?, ?)
        ''', (chat_id, log_chat_id, set_by))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_log_chat(chat_id: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT log_chat_id FROM log_chats WHERE chat_id = ?', (chat_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None

init_database()

# ============ УТИЛИТЫ ============
class Utils:
    # Эмодзи для разных типов сообщений
    EMOJIS = {
        'success': ["✅", "✨", "🌟", "🎉", "🔥", "💫", "⚡", "🎊", "🏆", "💖"],
        'error': ["❌", "🚫", "⛔", "⚠️", "💥", "💔", "😢", "🙅", "🚨", "🛑"],
        'info': ["ℹ️", "📋", "📝", "📊", "🔍", "💡", "📌", "📍", "🗒️", "📄"],
        'moderation': ["🔇", "🔨", "👢", "👮", "⚖️", "🚔", "🔒", "🗝️", "🛡️", "⚔️"],
        'greeting': ["👋", "🤗", "😊", "🎈", "🎁", "🎀", "💝", "💌", "💐", "🌸"],
        'game': ["🎮", "🎲", "🕹️", "👾", "🎯", "🏅", "🥇", "🥈", "🥉", "💰"],
        'random': ["🎉", "✨", "🌟", "🎊", "🎈", "💫", "🔥", "💥", "⭐", "😊", "🤗", "👋", "💖", "🎁", "🏆"]
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
        """Получает случайный эмодзи из категории"""
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

# ============ ФУНКЦИИ АВТООЧИСТКИ ============
def add_message_to_delete(chat_id: int, message_id: int, delete_after: int = AUTO_DELETE_TIME):
    """Добавляет сообщение в список на удаление"""
    if chat_id not in messages_to_delete:
        messages_to_delete[chat_id] = []
    
    delete_time = datetime.now() + timedelta(seconds=delete_after)
    messages_to_delete[chat_id].append((message_id, delete_time))

async def cleanup_messages():
    """Фоновая задача для очистки сообщений"""
    while True:
        try:
            current_time = datetime.now()
            chats_to_clean = list(messages_to_delete.keys())
            
            for chat_id in chats_to_clean:
                messages = messages_to_delete[chat_id]
                messages_to_keep = []
                
                for message_id, delete_time in messages:
                    if current_time >= delete_time:
                        try:
                            await bot.delete_message(chat_id, message_id)
                        except (TelegramBadRequest, TelegramForbiddenError):
                            pass  # Сообщение уже удалено или нет прав
                    else:
                        messages_to_keep.append((message_id, delete_time))
                
                if messages_to_keep:
                    messages_to_delete[chat_id] = messages_to_keep
                else:
                    del messages_to_delete[chat_id]
        
        except Exception as e:
            logger.error(f"Ошибка при очистке сообщений: {e}")
        
        await asyncio.sleep(5)  # Проверяем каждые 5 секунд

# ============ ФУНКЦИИ ЛОГ-ЧАТА ============
async def send_moderation_log(chat_id: int, action: str, target_user: dict, moderator: dict, 
                            duration: timedelta = None, reason: str = None, is_removed: bool = False):
    """Отправляет лог модерации в указанный чат"""
    try:
        log_chat_id = Database.get_log_chat(chat_id)
        if not log_chat_id:
            return
        
        action_emojis = {
            'mute': '🔇',
            'ban': '🔨',
            'kick': '👢',
            'unmute': '🔊',
            'unban': '🔓'
        }
        
        action_names = {
            'mute': 'МУТ',
            'ban': 'БАН',
            'kick': 'КИК',
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
        
        if reason:
            log_message += f"<b>Причина:</b> {reason}\n"
        
        log_message += f"<b>Чат:</b> {chat_id}\n"
        log_message += f"<b>Время:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await bot.send_message(log_chat_id, log_message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка при отправке лога: {e}")

# ============ ФУНКЦИИ ПРОВЕРКИ СЕССИЙ ============
def check_admin_session(user_id: int) -> Tuple[bool, Optional[str]]:
    """Проверяет активность админ-сессии"""
    if user_id not in admin_sessions:
        return False, "🔐 Сессия не активна. Войдите заново."
    
    session_time = admin_sessions[user_id]
    if (datetime.now() - session_time).total_seconds() > ADMIN_SESSION_TIMEOUT:
        remove_admin_session(user_id)
        return False, "⏰ Сессия истекла (таймаут 25 минут). Войдите заново."
    
    admin_sessions[user_id] = datetime.now()
    return True, None

def add_admin_session(user_id: int):
    """Добавляет админ-сессию"""
    admin_sessions[user_id] = datetime.now()
    admin_messages[user_id] = []

def remove_admin_session(user_id: int):
    """Удаляет админ-сессию и все сообщения"""
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
    """Добавляет сообщение админ-панели в список для удаления"""
    if user_id not in admin_messages:
        admin_messages[user_id] = []
    admin_messages[user_id].append(message_id)

# ============ КЛАВИАТУРЫ ============
class Keyboards:
    @staticmethod
    def get_main_keyboard(user_id: int):
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="📜 Правила бота", callback_data="rules")
        
        if user_id in ADMIN_IDS:
            keyboard.button(text="⚙️ Админ-панель", callback_data="admin_panel")
        
        keyboard.button(text="🎮 Играть", callback_data="play_game")
        keyboard.button(text="💰 Баланс", callback_data="balance")
        keyboard.button(text="🏆 Топ игроков", callback_data="top_players")
        keyboard.button(text="➕ Добавить в группу", url=f"https://t.me/{BOT_USERNAME}?startgroup=true")
        
        if user_id in ADMIN_IDS:
            keyboard.adjust(2, 2, 1, 1)
        else:
            keyboard.adjust(1, 2, 1, 1)
        
        return keyboard.as_markup()
    
    @staticmethod
    def get_admin_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="📊 Статистика", callback_data="admin_stats")
        keyboard.button(text="🔧 Модерация", callback_data="admin_moderation")
        keyboard.button(text="📣 Рассылка", callback_data="admin_broadcast")
        keyboard.button(text="👮 Управление модераторами", callback_data="admin_moderators")
        keyboard.button(text="📝 Настроить лог-чат", callback_data="admin_set_log_chat")
        keyboard.button(text="🔄 Сбросить ограничения", callback_data="admin_reset_restrictions")
        keyboard.button(text="🔙 Выйти из админ-панели", callback_data="admin_exit")
        keyboard.adjust(2, 2, 1, 1)
        return keyboard.as_markup()
    
    @staticmethod
    def get_moderation_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🔇 Выдать мут", callback_data="admin_mute")
        keyboard.button(text="🔨 Выдать бан", callback_data="admin_ban")
        keyboard.button(text="👢 Кикнуть", callback_data="admin_kick")
        keyboard.button(text="➕ Дать права модератора", callback_data="admin_add_mod")
        keyboard.button(text="📋 Активные ограничения", callback_data="admin_active_restrictions")
        keyboard.button(text="🔙 Назад в админ-панель", callback_data="admin_back_to_panel")
        keyboard.adjust(2, 2, 1, 1)
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
    def get_remove_restriction_keyboard(user_id: int, chat_id: int, restriction_type: str, restriction_id: int):
        keyboard = InlineKeyboardBuilder()
        keyboard.button(
            text=f"✅ Снять {restriction_type}", 
            callback_data=f"remove_{restriction_id}"
        )
        return keyboard.as_markup()

# ============ ОБРАБОТЧИКИ КОМАНД ============

# ============ КОМАНДЫ START И СИНОНИМЫ ============
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
        f"Спасибо, что добавили меня! Для начала прочитайте правила бота, "
        f"нажав кнопку «Правила бота».\n\n"
        f"{Utils.get_emoji('greeting')} Ваши данные:\n"
        f"• ID: {user_id}\n"
        f"• Username: @{username if username else 'Нет'}\n"
        f"• Имя: {full_name}"
    )
    
    await message.answer(welcome_text, reply_markup=Keyboards.get_main_keyboard(user_id))

# ============ КОМАНДЫ БАЛАНСА И СИНОНИМЫ ============
@router.message(F.text.lower().in_(["баланс", "/баланс", "balance", "/balance", "профиль", "/профиль", "стата", "/стата"]))
@router.callback_query(F.data == "balance")
async def cmd_balance(message_or_callback):
    """Команда баланса и её синонимы"""
    if isinstance(message_or_callback, CallbackQuery):
        message = message_or_callback.message
        user_id = message_or_callback.from_user.id
        await message_or_callback.answer()
    else:
        message = message_or_callback
        user_id = message.from_user.id
    
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
    
    response = (
        f"{Utils.get_emoji('game')} <b>Ваш баланс</b>\n\n"
        f"🎮 <b>Puls Coins:</b> {coins}\n"
        f"💵 <b>Доллары:</b> ${dollars}\n\n"
        f"💡 Используйте команды <code>играть</code> и <code>работать</code>"
    )
    
    if isinstance(message_or_callback, Message):
        msg = await message.reply(response)
        add_message_to_delete(message.chat.id, msg.message_id)
    else:
        await message.edit_text(response, reply_markup=Keyboards.get_back_to_main_keyboard())

# ============ КОМАНДА ИГРАТЬ ============
@router.message(F.text.lower().in_(["играть", "/играть", "game", "/game", "gamepuls", "/gamepuls"]))
async def cmd_play_game(message: Message):
    user_id = message.from_user.id
    user_data = Database.get_user(user_id)
    
    if not user_data:
        await message.reply(f"{Utils.get_emoji('error')} Начните с /start")
        return
    
    # Проверяем ограничения
    now = datetime.now()
    game_count = user_data[7] or 0
    reset_time = datetime.fromisoformat(user_data[9]) if user_data[9] else None
    
    if reset_time and now >= reset_time:
        game_count = 0
        Database.update_user(user_id, game_count=0, game_reset_time=None)
    
    if game_count >= 3:
        if not reset_time:
            reset_time = now + timedelta(hours=5)
            Database.update_user(user_id, game_reset_time=reset_time)
        
        time_left = reset_time - now
        hours = time_left.seconds // 3600
        minutes = (time_left.seconds % 3600) // 60
        
        response = (
            f"{Utils.get_emoji('error')} <b>Лимит игр исчерпан!</b>\n\n"
            f"Вы уже сыграли 3 раза за последние 5 часов.\n"
            f"⏳ Следующая игра возможна через: {hours}ч {minutes}м"
        )
        msg = await message.reply(response)
        add_message_to_delete(message.chat.id, msg.message_id)
        return
    
    # Игра
    coins_won = random.randint(5, 50)
    new_coins = (user_data[3] or 0) + coins_won
    
    Database.update_user(
        user_id,
        coins=new_coins,
        last_game=now,
        game_count=game_count + 1,
        game_reset_time=now + timedelta(hours=5) if game_count + 1 >= 3 else None
    )
    
    response = (
        f"{Utils.get_emoji('game')} <b>Вы выиграли {coins_won} Puls Coins!</b>\n\n"
        f"💰 <b>Баланс:</b> {new_coins} монет\n"
        f"🎮 <b>Игр сыграно:</b> {game_count + 1}/3 (сброс через 5ч)\n\n"
        f"{Utils.get_emoji('success')} Продолжайте в том же духе!"
    )
    
    msg = await message.reply(response)
    add_message_to_delete(message.chat.id, msg.message_id)

# ============ КОМАНДА РАБОТАТЬ ============
@router.message(F.text.lower().in_(["работать", "/работать", "work", "/work"]))
async def cmd_work(message: Message):
    user_id = message.from_user.id
    user_data = Database.get_user(user_id)
    
    if not user_data:
        await message.reply(f"{Utils.get_emoji('error')} Начните с /start")
        return
    
    # Проверяем ограничения
    now = datetime.now()
    work_count = user_data[8] or 0
    reset_time = datetime.fromisoformat(user_data[10]) if user_data[10] else None
    
    if reset_time and now >= reset_time:
        work_count = 0
        Database.update_user(user_id, work_count=0, work_reset_time=None)
    
    if work_count >= 5:
        if not reset_time:
            reset_time = now + timedelta(hours=24)
            Database.update_user(user_id, work_reset_time=reset_time)
        
        time_left = reset_time - now
        hours = time_left.seconds // 3600
        minutes = (time_left.seconds % 3600) // 60
        
        response = (
            f"{Utils.get_emoji('error')} <b>Лимит работы исчерпан!</b>\n\n"
            f"Вы уже поработали 5 раз за последние 24 часа.\n"
            f"⏳ Следующая работа возможна через: {hours}ч {minutes}м"
        )
        msg = await message.reply(response)
        add_message_to_delete(message.chat.id, msg.message_id)
        return
    
    # Работа
    dollars_earned = random.randint(1, 20)
    new_dollars = (user_data[4] or 0) + dollars_earned
    
    Database.update_user(
        user_id,
        dollars=new_dollars,
        last_work=now,
        work_count=work_count + 1,
        work_reset_time=now + timedelta(hours=24) if work_count + 1 >= 5 else None
    )
    
    response = (
        f"{Utils.get_emoji('success')} <b>Работа выполнена!</b>\n\n"
        f"💰 <b>Заработано:</b> ${dollars_earned}\n\n"
        f"💵 <b>Баланс:</b> ${new_dollars}\n"
        f"📊 <b>Работ выполнено:</b> {work_count + 1}/5 (сброс через 24ч)\n\n"
        f"💪 Отличная работа!"
    )
    
    msg = await message.reply(response)
    add_message_to_delete(message.chat.id, msg.message_id)

# ============ ОБРАБОТЧИК КОМАНД МОДЕРАЦИИ С ПРОВЕРКАМИ ============
async def get_target_user(message: Message, target: str):
    """Получает пользователя по ID, username или reply с проверками"""
    try:
        if message.reply_to_message:
            return message.reply_to_message.from_user
        
        if target.startswith('@'):
            # По username (упрощённая реализация)
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
        msg = await message.reply(f"{Utils.get_emoji('error')} Использование: {words[0]} [ID/@username/reply]")
        add_message_to_delete(message.chat.id, msg.message_id)
        return
    
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Только админы могут выдавать права
    if user_id not in ADMIN_IDS:
        msg = await message.reply(f"{Utils.get_emoji('error')} Только администраторы могут выдавать права!")
        add_message_to_delete(message.chat.id, msg.message_id)
        return
    
    target_user = await get_target_user(message, words[1])
    
    if not target_user:
        msg = await message.reply(f"{Utils.get_emoji('error')} Не удалось найти пользователя.")
        add_message_to_delete(message.chat.id, msg.message_id)
        return
    
    # Проверка на себя
    if target_user.id == user_id:
        msg = await message.reply(f"{Utils.get_emoji('error')} Нельзя выдавать права самому себе!")
        add_message_to_delete(message.chat.id, msg.message_id)
        return
    
    # Проверка на бота
    if target_user.is_bot:
        msg = await message.reply(f"{Utils.get_emoji('error')} Нельзя выдавать права ботам!")
        add_message_to_delete(message.chat.id, msg.message_id)
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
    
    msg = await message.reply(response)
    add_message_to_delete(message.chat.id, msg.message_id)

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
            msg = await message.reply(f"{Utils.get_emoji('error')} Использование: {usage}")
            add_message_to_delete(message.chat.id, msg.message_id)
            return
        elif len(words) < 2 and action == 'kick':
            usage = f"{words[0]} [причина] или reply + {words[0]} [причина]"
            msg = await message.reply(f"{Utils.get_emoji('error')} Использование: {usage}")
            add_message_to_delete(message.chat.id, msg.message_id)
            return
        
        target = words[1]
        target_user = await get_target_user(message, target)
        
        if not target_user:
            msg = await message.reply(f"{Utils.get_emoji('error')} Не удалось найти пользователя.")
            add_message_to_delete(message.chat.id, msg.message_id)
            return
        
        time_index = 2
        reason_index = 3 if action in ['mute', 'ban'] else 2
    
    # Проверяем права и безопасность
    has_permission, error_msg = await check_permissions(user_id, chat_id, action, target_user)
    if not has_permission:
        msg = await message.reply(error_msg)
        add_message_to_delete(message.chat.id, msg.message_id)
        return
    
    # Парсим время
    duration = None
    if action in ['mute', 'ban']:
        if len(words) > time_index:
            time_str = words[time_index]
            duration = Utils.parse_time(time_str)
        
        if not duration:
            duration = timedelta(hours=1)
    
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
            until_date, reason, moderator.id, moderator.full_name
        )
        
        # Отправляем сообщение о наказании
        if action == 'mute':
            response = (
                f"{Utils.get_emoji('moderation')} <b>Пользователь получил мут!</b>\n\n"
                f"👤 Пользователь: {target_user.full_name}\n"
                f"🆔 ID: <code>{target_user.id}</code>\n"
                f"⏰ Длительность: {Utils.format_time(duration)}\n"
                f"📝 Причина: {reason}\n"
                f"👮 Модератор: {moderator.full_name}"
            )
        elif action == 'ban':
            response = (
                f"{Utils.get_emoji('moderation')} <b>Пользователь забанен!</b>\n\n"
                f"👤 Пользователь: {target_user.full_name}\n"
                f"🆔 ID: <code>{target_user.id}</code>\n"
                f"⏰ Длительность: {Utils.format_time(duration)}\n"
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
        
        msg = await message.reply(response)
        
        # Отправляем лог
        await send_moderation_log(
            chat_id=chat_id,
            action=action,
            target_user={
                'id': target_user.id,
                'full_name': target_user.full_name,
                'username': target_user.username
            },
            moderator={
                'id': moderator.id,
                'full_name': moderator.full_name,
                'username': moderator.username
            },
            duration=duration,
            reason=reason
        )
        
        add_message_to_delete(message.chat.id, msg.message_id)
        
    except TelegramForbiddenError:
        msg = await message.reply(f"{Utils.get_emoji('error')} У бота недостаточно прав для выполнения этого действия!")
        add_message_to_delete(message.chat.id, msg.message_id)
    except Exception as e:
        logger.error(f"Ошибка при наказании: {e}")
        msg = await message.reply(f"{Utils.get_emoji('error')} Произошла ошибка при выполнении действия!")
        add_message_to_delete(message.chat.id, msg.message_id)

# ============ ОБРАБОТЧИК КОЛЛБЭКОВ ДЛЯ СНЯТИЯ ОГРАНИЧЕНИЙ ============
@router.callback_query(F.data.startswith("remove_"))
async def callback_remove_restriction(callback: CallbackQuery):
    """Снятие ограничения по кнопке"""
    data = callback.data.split("_")
    
    if len(data) != 2 or not data[1].isdigit():
        await callback.answer(f"{Utils.get_emoji('error')} Ошибка формата!")
        return
    
    restriction_id = int(data[1])
    
    # Получаем информацию об ограничении
    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM restrictions WHERE id = ?', (restriction_id,))
    restriction = cursor.fetchone()
    conn.close()
    
    if not restriction:
        await callback.answer(f"{Utils.get_emoji('error')} Ограничение не найдено!")
        return
    
    user_id = restriction[1]
    chat_id = restriction[2]
    restriction_type = restriction[3]
    
    try:
        # Снимаем ограничение в Telegram
        if restriction_type == 'mute':
            # Восстанавливаем все права
            permissions = ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=True,
                can_invite_users=True,
                can_pin_messages=True
            )
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=permissions
            )
        elif restriction_type == 'ban':
            await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
        
        # Обновляем статус в БД
        Database.update_restriction_status(restriction_id, 'removed')
        
        # Отправляем подтверждение
        await callback.message.edit_text(
            f"{Utils.get_emoji('success')} <b>✅ Ограничение снято!</b>\n\n"
            f"Тип: {restriction_type}\n"
            f"Пользователь ID: <code>{user_id}</code>\n"
            f"Чат ID: <code>{chat_id}</code>"
        )
        
        # Отправляем лог о снятии
        await send_moderation_log(
            chat_id=chat_id,
            action=f'un{restriction_type}',
            target_user={'id': user_id, 'full_name': f'ID: {user_id}'},
            moderator={'id': callback.from_user.id, 'full_name': callback.from_user.full_name},
            is_removed=True
        )
        
    except TelegramForbiddenError:
        await callback.message.edit_text(
            f"{Utils.get_emoji('error')} <b>❌ Не удалось снять ограничение!</b>\n\n"
            f"У бота недостаточно прав в чате."
        )
    except Exception as e:
        logger.error(f"Ошибка при снятии ограничения: {e}")
        await callback.message.edit_text(
            f"{Utils.get_emoji('error')} <b>❌ Ошибка при снятии ограничения!</b>\n\n"
            f"Ошибка: {str(e)[:100]}"
        )
    
    await callback.answer()

# ============ ОБРАБОТЧИКИ АДМИН-ПАНЕЛИ ============

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
    failed_attempts, lock_until, last_attempt = Database.check_admin_lock(user_id)
    if failed_attempts >= 2 and lock_until and datetime.now() < lock_until:
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
    failed_attempts, lock_until, last_attempt = Database.check_admin_lock(user_id)
    
    # Проверяем блокировку
    if failed_attempts >= 2 and lock_until and datetime.now() < lock_until:
        time_left = lock_until - datetime.now()
        minutes = time_left.seconds // 60
        await message.answer(f"{Utils.get_emoji('error')} Доступ заблокирован! Попробуйте через {minutes} минут.")
        await state.clear()
        return
    
    if password == ADMIN_PASSWORD:
        # Успешный вход
        Database.update_admin_lock(user_id, 0, None)
        add_admin_session(user_id)
        
        # Удаляем сообщение с паролем
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
            Database.update_admin_lock(user_id, failed_attempts, lock_until)
            
            time_left = lock_until - datetime.now()
            minutes = time_left.seconds // 60
            
            await message.answer(
                f"{Utils.get_emoji('error')} <b>⛔ Слишком много неверных попыток!</b>\n\n"
                f"Доступ заблокирован на {minutes} минут.\n\n"
                f"Возвращаемся в главное меню...",
                reply_markup=Keyboards.get_main_keyboard(user_id)
            )
        else:
            Database.update_admin_lock(user_id, failed_attempts, None)
            attempts_left = 2 - failed_attempts
            
            await message.answer(
                f"{Utils.get_emoji('error')} <b>❌ Неверный пароль!</b>\n\n"
                f"Осталось попыток: {attempts_left}\n"
                f"Введите пароль еще раз:"
            )
    
    await state.clear()

# ============ ОБРАБОТЧИКИ АДМИНСКИХ ДЕЙСТВИЙ ============

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
        conn = Database.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(coins) FROM users')
        total_coins = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT SUM(dollars) FROM users')
        total_dollars = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COUNT(*) FROM restrictions WHERE status = "active" AND until > ?', 
                      (datetime.now().isoformat(),))
        active_restrictions = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM moderator_rights')
        total_moderators = cursor.fetchone()[0]
        
        conn.close()
        
        stats_text = (
            f"{Utils.get_emoji('info')} <b>📊 Статистика бота</b>\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"🎮 Всего Puls Coins: {total_coins}\n"
            f"💵 Всего долларов: ${total_dollars}\n"
            f"🔇 Активных ограничений: {active_restrictions}\n"
            f"👮 Всего модераторов: {total_moderators}\n"
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
    
    elif data == "admin_moderation":
        try:
            msg = await callback.message.edit_text(
                f"{Utils.get_emoji('moderation')} <b>Панель модерации</b>\n\n"
                "Выберите действие:",
                reply_markup=Keyboards.get_moderation_keyboard()
            )
            add_admin_message(user_id, msg.message_id)
        except:
            msg = await callback.message.answer(
                f"{Utils.get_emoji('moderation')} <b>Панель модерации</b>\n\n"
                "Выберите действие:",
                reply_markup=Keyboards.get_moderation_keyboard()
            )
            add_admin_message(user_id, msg.message_id)
    
    elif data == "admin_set_log_chat":
        # Настройка лог-чата
        await state.set_state(AdminStates.waiting_password)  # Используем для ввода ID
        
        try:
            msg = await callback.message.edit_text(
                f"{Utils.get_emoji('info')} <b>Настройка лог-чата</b>\n\n"
                "Для настройки лог-чата:\n"
                "1. Добавьте бота в чат для логов\n"
                "2. Сделайте бота администратором\n"
                "3. Пришлите ID чата (можно получить командой /id в том чате)\n\n"
                "Введите ID чата для логов:",
                reply_markup=Keyboards.get_cancel_keyboard()
            )
            add_admin_message(user_id, msg.message_id)
        except:
            msg = await callback.message.answer(
                f"{Utils.get_emoji('info')} <b>Настройка лог-чата</b>\n\n"
                "Для настройки лог-чата:\n"
                "1. Добавьте бота в чат для логов\n"
                "2. Сделайте бота администратором\n"
                "3. Пришлите ID чата (можно получить командой /id в том чате)\n\n"
                "Введите ID чата для логов:",
                reply_markup=Keyboards.get_cancel_keyboard()
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

# ============ ОБРАБОТКА НАСТРОЙКИ ЛОГ-ЧАТА ============
@router.message(AdminStates.waiting_password)  # Используем то же состояние
async def process_log_chat_id(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await state.clear()
        return
    
    if message.text and message.text.strip().lstrip('-').isdigit():
        log_chat_id = int(message.text.strip())
        
        # Проверяем, что бот в этом чате
        try:
            await bot.get_chat(log_chat_id)
            Database.set_log_chat(message.chat.id, log_chat_id, user_id)
            
            await message.answer(
                f"{Utils.get_emoji('success')} ✅ <b>Лог-чат настроен!</b>\n\n"
                f"ID лог-чата: <code>{log_chat_id}</code>\n"
                f"Все действия модерации теперь будут логироваться.",
                reply_markup=Keyboards.get_admin_keyboard()
            )
            
            # Обновляем сессию
            add_admin_session(user_id)
            
        except TelegramBadRequest:
            await message.answer(
                f"{Utils.get_emoji('error')} ❌ <b>Ошибка!</b>\n\n"
                f"Бот не добавлен в указанный чат или чат не существует.\n"
                f"Убедитесь, что:\n"
                f"1. Бот добавлен в чат\n"
                f"2. Бот является администратором\n"
                f"3. ID чата указан правильно",
                reply_markup=Keyboards.get_admin_keyboard()
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

@router.callback_query(F.data == "play_game")
async def callback_play_game(callback: CallbackQuery):
    await cmd_play_game(callback.message)
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
            top_text += f"{meddi} {name_display} - {coins} Puls Coins\n"
    
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

async def check_restrictions():
    """Проверка просроченных ограничений"""
    while True:
        try:
            conn = Database.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM restrictions WHERE until < ? AND status = "active"', 
                          (datetime.now().isoformat(),))
            expired = cursor.fetchall()
            
            for restriction in expired:
                user_id, chat_id, restriction_type = restriction[1], restriction[2], restriction[3]
                
                # Снимаем ограничение в Telegram
                try:
                    if restriction_type == 'mute':
                        permissions = ChatPermissions(
                            can_send_messages=True,
                            can_send_media_messages=True,
                            can_send_polls=True,
                            can_send_other_messages=True,
                            can_add_web_page_previews=True,
                            can_change_info=True,
                            can_invite_users=True,
                            can_pin_messages=True
                        )
                        await bot.restrict_chat_member(
                            chat_id=chat_id,
                            user_id=user_id,
                            permissions=permissions
                        )
                    elif restriction_type == 'ban':
                        await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
                except:
                    pass
                
                # Обновляем статус в БД
                cursor.execute('UPDATE restrictions SET status = "expired" WHERE id = ?', (restriction[0],))
            
            conn.commit()
            conn.close()
            
            if expired:
                logger.info(f"Снято {len(expired)} просроченных ограничений")
        
        except Exception as e:
            logger.error(f"Ошибка при проверке ограничений: {e}")
        
        await asyncio.sleep(60)

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
            
            await asyncio.sleep(30)  # Проверяем каждые 30 секунд
        
        except Exception as e:
            logger.error(f"Ошибка при проверке сессий: {e}")
            await asyncio.sleep(60)

# ============ ЗАПУСК БОТА ============

async def main():
    # Запускаем фоновые задачи
    asyncio.create_task(check_restrictions())
    asyncio.create_task(check_admin_sessions())
    asyncio.create_task(cleanup_messages())
    
    logger.info("Бот запускается...")
    logger.info(f"Админ ID: {ADMIN_IDS}")
    logger.info(f"Бот username: @{BOT_USERNAME}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
