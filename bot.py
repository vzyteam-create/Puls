import asyncio
import logging
import sqlite3
import random
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8557190026:AAGnqxtrAyZz-huihyGctKWNHgjt7w9lQTo"
ADMIN_IDS = [6708209142]
BOT_USERNAME = "@PulsOfficialManager_bot"

# Настройки
COOLDOWN_PM = 3  # КД в личных сообщениях (3 секунды)
COOLDOWN_GROUP = 5  # КД в группах (5 секунд)
BONUS_AMOUNT = 50
BONUS_COOLDOWN = 24 * 3600
WORK_COOLDOWN = 30 * 60
WORK_LIMIT = 5
WORK_LIMIT_COOLDOWN = 10 * 3600
GAME_LIMIT = 5
GAME_LIMIT_COOLDOWN = 3 * 3600
MIN_BET = 25
VIP_MULTIPLIER = 1.5

VIP_PACKAGES = {
    30: 1000,
    90: 2940,
    150: 4850,
    365: 11400
}

ADMIN_PASSWORD = "vanezypulsbot13579"
MAX_ACCOUNTS_PER_USER = 3
ACCOUNT_CREATION_COOLDOWN = 3 * 24 * 3600  # 3 дня в секундах
REGISTRATION_TIMEOUT = 300
LOGIN_TIMEOUT = 400

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ========== КЛАССЫ И ФУНКЦИИ ==========
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('pulse_bot.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
    
    def create_tables(self):
        # Аккаунты пользователей (логин/пароль)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                account_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                recovery_code TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_blocked BOOLEAN DEFAULT FALSE,
                block_reason TEXT,
                blocked_until TIMESTAMP,
                owner_user_id INTEGER,
                last_account_creation TIMESTAMP
            )
        ''')
        
        # Блокировки пользователей от создания аккаунтов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_blocks (
                user_id INTEGER PRIMARY KEY,
                is_blocked BOOLEAN DEFAULT FALSE,
                block_reason TEXT,
                blocked_until TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Сессии пользователей (кто в каком аккаунте)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                telegram_username TEXT,
                login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                logout_time TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id)
            )
        ''')
        
        # Настройки доступа для аккаунтов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS account_settings (
                account_id INTEGER PRIMARY KEY,
                can_play_games BOOLEAN DEFAULT TRUE,
                can_work BOOLEAN DEFAULT TRUE,
                can_use_shop BOOLEAN DEFAULT TRUE,
                can_claim_bonus BOOLEAN DEFAULT TRUE,
                can_use_vip BOOLEAN DEFAULT TRUE,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id)
            )
        ''')
        
        # Данные игрового аккаунта
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS game_data (
                account_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                is_vip BOOLEAN DEFAULT FALSE,
                vip_until TIMESTAMP,
                last_action TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                games_played INTEGER DEFAULT 0,
                work_count INTEGER DEFAULT 0,
                total_spent INTEGER DEFAULT 0,
                last_bonus TIMESTAMP,
                last_work TIMESTAMP,
                game1_count INTEGER DEFAULT 0,
                game2_count INTEGER DEFAULT 0,
                game3_count INTEGER DEFAULT 0,
                game1_cooldown TIMESTAMP,
                game2_cooldown TIMESTAMP,
                game3_cooldown TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id)
            )
        ''')
        
        # Админские сессии
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_sessions (
                user_id INTEGER PRIMARY KEY,
                expires_at TIMESTAMP
            )
        ''')
        
        # Транзакции (для казны)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                amount INTEGER,
                type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таймеры регистрации и входа
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_timers (
                user_id INTEGER PRIMARY KEY,
                timer_type TEXT,
                start_time TIMESTAMP,
                expires_at TIMESTAMP
            )
        ''')
        
        # Права на удаление сообщений в группах
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS delete_permissions (
                chat_id INTEGER,
                user_id INTEGER,
                granted_by INTEGER,
                granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, user_id)
            )
        ''')
        
        # Таблица для кулдаунов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_cooldowns (
                user_id INTEGER,
                chat_id INTEGER,
                last_action TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, chat_id)
            )
        ''')
        
        # Таблица для статистики активности пользователей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                chat_type TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
    
    # === Управление кулдаунами ===
    def update_user_cooldown(self, user_id: int, chat_id: int):
        """Обновляет время последнего действия пользователя"""
        self.cursor.execute(
            "INSERT OR REPLACE INTO user_cooldowns (user_id, chat_id, last_action) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id, chat_id)
        )
        self.conn.commit()
    
    def get_user_cooldown(self, user_id: int, chat_id: int) -> Optional[datetime]:
        """Получает время последнего действия пользователя"""
        self.cursor.execute(
            "SELECT last_action FROM user_cooldowns WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id)
        )
        result = self.cursor.fetchone()
        return datetime.fromisoformat(result[0]) if result else None
    
    # === Статистика активности ===
    def log_activity(self, user_id: int, action: str, chat_type: str = "private"):
        """Логирует активность пользователя"""
        self.cursor.execute(
            "INSERT INTO user_activity (user_id, action, chat_type) VALUES (?, ?, ?)",
            (user_id, action, chat_type)
        )
        self.conn.commit()
    
    def get_activity_stats(self, period: str = "all") -> Dict:
        """Получает статистику активности"""
        query = "SELECT COUNT(DISTINCT user_id) as unique_users, COUNT(*) as total_actions FROM user_activity"
        
        if period == "today":
            query += " WHERE DATE(timestamp) = DATE('now')"
        elif period == "month":
            query += " WHERE timestamp >= datetime('now', '-30 days')"
        
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return {
            "unique_users": result[0] if result else 0,
            "total_actions": result[1] if result else 0
        }
    
    # === Управление таймерами ===
    def start_timer(self, user_id: int, timer_type: str, duration: int):
        """Запускает таймер для пользователя"""
        start_time = datetime.now()
        expires_at = start_time + timedelta(seconds=duration)
        
        self.cursor.execute(
            "INSERT OR REPLACE INTO user_timers (user_id, timer_type, start_time, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, timer_type, start_time.isoformat(), expires_at.isoformat())
        )
        self.conn.commit()
    
    def check_timer(self, user_id: int, timer_type: str) -> Tuple[bool, Optional[str]]:
        """Проверяет таймер пользователя"""
        self.cursor.execute(
            "SELECT expires_at FROM user_timers WHERE user_id = ? AND timer_type = ?",
            (user_id, timer_type)
        )
        result = self.cursor.fetchone()
        
        if not result:
            return False, None  # Таймер не найден - значит можно выполнять действие
        
        expires_at = datetime.fromisoformat(result[0])
        if datetime.now() > expires_at:
            self.cursor.execute(
                "DELETE FROM user_timers WHERE user_id = ? AND timer_type = ?",
                (user_id, timer_type)
            )
            self.conn.commit()
            return False, None  # Таймер истек - можно выполнять действие
        
        remaining = (expires_at - datetime.now()).total_seconds()
        return True, f"Осталось времени: {int(remaining)} секунд"  # Таймер активен
    
    def clear_timer(self, user_id: int, timer_type: str):
        """Очищает таймер пользователя"""
        self.cursor.execute(
            "DELETE FROM user_timers WHERE user_id = ? AND timer_type = ?",
            (user_id, timer_type)
        )
        self.conn.commit()
    
    # === Управление правами на удаление ===
    def has_delete_permission(self, chat_id: int, user_id: int) -> bool:
        """Проверяет, имеет ли пользователь право удалять сообщения"""
        self.cursor.execute(
            "SELECT 1 FROM delete_permissions WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        )
        return self.cursor.fetchone() is not None
    
    def grant_delete_permission(self, chat_id: int, user_id: int, granted_by: int):
        """Выдает право на удаление сообщений"""
        self.cursor.execute(
            "INSERT OR REPLACE INTO delete_permissions (chat_id, user_id, granted_by) VALUES (?, ?, ?)",
            (chat_id, user_id, granted_by)
        )
        self.conn.commit()
    
    def revoke_delete_permission(self, chat_id: int, user_id: int) -> bool:
        """Отзывает право на удаление сообщений"""
        self.cursor.execute(
            "DELETE FROM delete_permissions WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        )
        self.conn.commit()
        return self.cursor.rowcount > 0
    
    def get_all_with_delete_permissions(self, chat_id: int) -> List[Dict]:
        """Получает всех, кто имеет права на удаление в чате"""
        self.cursor.execute(
            "SELECT user_id, granted_by, granted_at FROM delete_permissions WHERE chat_id = ?",
            (chat_id,)
        )
        columns = [desc[0] for desc in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
    
    # === Управление аккаунтами ===
    def create_account(self, username: str, password: str, recovery_code: str = None, owner_user_id: int = None) -> int:
        """Создает новый аккаунт"""
        try:
            self.cursor.execute(
                "INSERT INTO accounts (username, password, recovery_code, owner_user_id, last_account_creation) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (username, password, recovery_code, owner_user_id)
            )
            account_id = self.cursor.lastrowid
            
            self.cursor.execute("INSERT INTO game_data (account_id) VALUES (?)", (account_id,))
            self.cursor.execute("INSERT INTO account_settings (account_id) VALUES (?)", (account_id,))
            
            self.conn.commit()
            return account_id
        except sqlite3.IntegrityError:
            return None
    
    def get_account_by_credentials(self, username: str, password: str) -> Dict:
        """Получает аккаунт по логину и паролю"""
        self.cursor.execute(
            "SELECT * FROM accounts WHERE username = ? AND password = ?",
            (username, password)
        )
        columns = [desc[0] for desc in self.cursor.description]
        row = self.cursor.fetchone()
        return dict(zip(columns, row)) if row else None
    
    def get_account_by_id(self, account_id: int) -> Dict:
        """Получает аккаунт по ID"""
        self.cursor.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,))
        columns = [desc[0] for desc in self.cursor.description]
        row = self.cursor.fetchone()
        return dict(zip(columns, row)) if row else None
    
    def get_account_by_username(self, username: str) -> Dict:
        """Получает аккаунт по username"""
        self.cursor.execute("SELECT * FROM accounts WHERE username = ?", (username,))
        columns = [desc[0] for desc in self.cursor.description]
        row = self.cursor.fetchone()
        return dict(zip(columns, row)) if row else None
    
    def search_accounts_by_owner(self, owner_user_id: int) -> List[Dict]:
        """Ищет все аккаунты по ID владельца"""
        self.cursor.execute(
            "SELECT * FROM accounts WHERE owner_user_id = ? ORDER BY created_at DESC",
            (owner_user_id,)
        )
        columns = [desc[0] for desc in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
    
    def get_all_accounts(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Получает все аккаунты"""
        self.cursor.execute(
            "SELECT * FROM accounts ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        )
        columns = [desc[0] for desc in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
    
    def get_total_accounts_count(self) -> int:
        """Получает общее количество аккаунтов"""
        self.cursor.execute("SELECT COUNT(*) FROM accounts")
        return self.cursor.fetchone()[0]
    
    def get_account_settings(self, account_id: int) -> Dict:
        """Получает настройки аккаунта"""
        self.cursor.execute("SELECT * FROM account_settings WHERE account_id = ?", (account_id,))
        columns = [desc[0] for desc in self.cursor.description]
        row = self.cursor.fetchone()
        if row:
            return dict(zip(columns, row))
        else:
            self.cursor.execute("INSERT INTO account_settings (account_id) VALUES (?)", (account_id,))
            self.conn.commit()
            return {"account_id": account_id, "can_play_games": True, "can_work": True, 
                    "can_use_shop": True, "can_claim_bonus": True, "can_use_vip": True}
    
    def username_exists(self, username: str) -> bool:
        """Проверяет, существует ли username"""
        self.cursor.execute("SELECT 1 FROM accounts WHERE username = ?", (username,))
        return self.cursor.fetchone() is not None
    
    def get_user_accounts_count(self, user_id: int) -> int:
        """Сколько аккаунтов создал пользователь"""
        self.cursor.execute("SELECT COUNT(*) FROM accounts WHERE owner_user_id = ?", (user_id,))
        return self.cursor.fetchone()[0]
    
    def get_last_account_creation(self, user_id: int) -> Optional[datetime]:
        """Получает время последнего создания аккаунта пользователем"""
        self.cursor.execute(
            "SELECT last_account_creation FROM accounts WHERE owner_user_id = ? ORDER BY last_account_creation DESC LIMIT 1",
            (user_id,)
        )
        result = self.cursor.fetchone()
        if result and result[0]:
            return datetime.fromisoformat(result[0])
        return None
    
    def can_create_account(self, user_id: int) -> Tuple[bool, Optional[str]]:
        """Проверяет, может ли пользователь создать новый аккаунт"""
        # Проверяем количество аккаунтов
        accounts_count = self.get_user_accounts_count(user_id)
        if accounts_count >= MAX_ACCOUNTS_PER_USER:
            return False, f"Вы уже создали максимальное количество аккаунтов ({MAX_ACCOUNTS_PER_USER})."
        
        # Проверяем кулдаун после последнего создания
        last_creation = self.get_last_account_creation(user_id)
        if last_creation:
            time_since_last = (datetime.now() - last_creation).total_seconds()
            if time_since_last < ACCOUNT_CREATION_COOLDOWN:
                remaining = ACCOUNT_CREATION_COOLDOWN - time_since_last
                days = int(remaining // (24 * 3600))
                hours = int((remaining % (24 * 3600)) // 3600)
                minutes = int((remaining % 3600) // 60)
                return False, f"Вы сможете создать новый аккаунт через: {days}д {hours}ч {minutes}м"
        
        return True, None
    
    # === Управление сессиями ===
    def create_session(self, user_id: int, account_id: int, telegram_username: str = None) -> int:
        """Создает новую сессию"""
        self.cursor.execute(
            "INSERT INTO sessions (user_id, account_id, telegram_username) VALUES (?, ?, ?)",
            (user_id, account_id, telegram_username)
        )
        session_id = self.cursor.lastrowid
        self.conn.commit()
        return session_id
    
    def get_active_session(self, user_id: int) -> Optional[Dict]:
        """Получает активную сессию пользователя"""
        self.cursor.execute(
            "SELECT s.*, a.username, a.recovery_code FROM sessions s "
            "JOIN accounts a ON s.account_id = a.account_id "
            "WHERE s.user_id = ? AND s.logout_time IS NULL "
            "ORDER BY s.login_time DESC LIMIT 1",
            (user_id,)
        )
        columns = [desc[0] for desc in self.cursor.description]
        row = self.cursor.fetchone()
        if row:
            return dict(zip(columns, row))
        return None
    
    def get_all_sessions(self, limit: int = 50) -> List[Dict]:
        """Получает все сессии"""
        self.cursor.execute(
            "SELECT s.*, a.username FROM sessions s "
            "JOIN accounts a ON s.account_id = a.account_id "
            "ORDER BY s.login_time DESC LIMIT ?",
            (limit,)
        )
        columns = [desc[0] for desc in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
    
    def logout_session(self, session_id: int):
        """Завершает сессию"""
        self.cursor.execute(
            "UPDATE sessions SET logout_time = CURRENT_TIMESTAMP WHERE session_id = ?",
            (session_id,)
        )
        self.conn.commit()
    
    # === Игровые данные ===
    def get_game_data(self, account_id: int) -> Optional[Dict]:
        """Получает игровые данные аккаунта"""
        self.cursor.execute("SELECT * FROM game_data WHERE account_id = ?", (account_id,))
        columns = [desc[0] for desc in self.cursor.description]
        row = self.cursor.fetchone()
        return dict(zip(columns, row)) if row else None
    
    def update_balance(self, account_id: int, amount: int, transaction_type: str = "other"):
        """Обновляет баланс"""
        self.cursor.execute(
            "UPDATE game_data SET balance = balance + ? WHERE account_id = ?",
            (amount, account_id)
        )
        if amount < 0:
            self.cursor.execute(
                "UPDATE game_data SET total_spent = total_spent + ? WHERE account_id = ?",
                (abs(amount), account_id)
            )
            self.cursor.execute(
                "INSERT INTO transactions (account_id, amount, type) VALUES (?, ?, ?)",
                (account_id, abs(amount), transaction_type)
            )
        self.conn.commit()
    
    def set_balance(self, account_id: int, new_balance: int):
        """Устанавливает баланс аккаунта"""
        self.cursor.execute(
            "UPDATE game_data SET balance = ? WHERE account_id = ?",
            (new_balance, account_id)
        )
        self.conn.commit()
    
    def get_treasury(self) -> int:
        """Получает сумму казны (все отрицательные транзакции)"""
        self.cursor.execute("SELECT SUM(amount) FROM transactions WHERE amount > 0")
        result = self.cursor.fetchone()
        return result[0] if result and result[0] else 0
    
    def update_last_action(self, account_id: int):
        """Обновляет время последнего действия"""
        self.cursor.execute(
            "UPDATE game_data SET last_action = CURRENT_TIMESTAMP WHERE account_id = ?",
            (account_id,)
        )
        self.conn.commit()
    
    def check_vip(self, account_id: int) -> bool:
        """Проверяет VIP статус"""
        game_data = self.get_game_data(account_id)
        if not game_data or not game_data.get('is_vip'):
            return False
        
        if game_data.get('vip_until'):
            vip_until = datetime.fromisoformat(game_data['vip_until'])
            if vip_until < datetime.now():
                self.cursor.execute(
                    "UPDATE game_data SET is_vip = FALSE WHERE account_id = ?",
                    (account_id,)
                )
                self.conn.commit()
                return False
        return True
    
    # === Админ сессии ===
    def create_admin_session(self, user_id: int):
        """Создает админскую сессию"""
        expires_at = datetime.now() + timedelta(minutes=30)
        self.cursor.execute(
            "INSERT OR REPLACE INTO admin_sessions (user_id, expires_at) VALUES (?, ?)",
            (user_id, expires_at.isoformat())
        )
        self.conn.commit()
    
    def check_admin_session(self, user_id: int) -> bool:
        """Проверяет админскую сессию"""
        self.cursor.execute("SELECT expires_at FROM admin_sessions WHERE user_id = ?", (user_id,))
        result = self.cursor.fetchone()
        
        if not result:
            return False
        
        expires_at = datetime.fromisoformat(result[0])
        if expires_at < datetime.now():
            self.cursor.execute("DELETE FROM admin_sessions WHERE user_id = ?", (user_id,))
            self.conn.commit()
            return False
        
        return True

db = Database()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def validate_password(password: str) -> Tuple[bool, str]:
    """Проверяет пароль на соответствие требованиям"""
    if len(password) < 5:
        return False, "Пароль должен содержать минимум 5 символов"
    if not re.search(r'[A-Za-z]', password):
        return False, "Пароль должен содержать минимум 1 букву"
    if not re.search(r'\d', password):
        return False, "Пароль должен содержать минимум 1 цифру"
    if len(password) > 15:
        return False, "Пароль не должен превышать 15 символов"
    return True, "OK"

def validate_recovery_code(code: str) -> Tuple[bool, str]:
    """Проверяет кодовое слово для восстановления"""
    if len(code) < 5:
        return False, "Кодовое слово должно содержать минимум 5 символов"
    if len(code) > 20:
        return False, "Кодовое слово не должно превышать 20 символов"
    if not re.match(r'^[A-Za-z]+$', code):
        return False, "Кодовое слово должно содержать только английские буквы"
    return True, "OK"

def get_user_session(user_id: int) -> Optional[Dict]:
    """Получает активную сессию пользователя"""
    return db.get_active_session(user_id)

def is_logged_in(user_id: int) -> bool:
    """Проверяет, авторизован ли пользователь"""
    session = get_user_session(user_id)
    return session is not None

def format_time(seconds: float) -> str:
    """Форматирует время в ЧЧ:ММ:СС"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)
    return f"{hours}ч {minutes}м {seconds}с"

def format_days_time(seconds: float) -> str:
    """Форматирует время в дни, часы, минуты"""
    days = int(seconds // (24 * 3600))
    hours = int((seconds % (24 * 3600)) // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{days}д {hours}ч {minutes}м"

# ========== СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЕЙ ==========
class UserState:
    def __init__(self):
        self.states = {}
    
    def set_state(self, user_id: int, state: str, data: dict = None):
        """Устанавливает состояние пользователя"""
        self.states[user_id] = {
            "state": state,
            "data": data or {},
            "timestamp": datetime.now()
        }
    
    def get_state(self, user_id: int) -> Optional[Dict]:
        """Получает состояние пользователя"""
        if user_id not in self.states:
            return None
        
        state_data = self.states[user_id]
        if state_data["state"] == "waiting_for_username":
            timeout = REGISTRATION_TIMEOUT
        elif state_data["state"] == "waiting_for_login_username":
            timeout = LOGIN_TIMEOUT
        elif state_data["state"] in ["admin_password", "admin_search", "admin_search_by_owner", 
                                    "admin_balance", "admin_broadcast", "admin_treasury"]:
            timeout = 300
        else:
            timeout = 300
        
        elapsed = (datetime.now() - state_data["timestamp"]).total_seconds()
        if elapsed > timeout:
            self.clear_state(user_id)
            return None
        
        return state_data
    
    def clear_state(self, user_id: int):
        """Очищает состояние пользователя"""
        if user_id in self.states:
            state_data = self.states[user_id]
            if state_data["state"] in ["waiting_for_username", "waiting_for_password", "waiting_for_recovery"]:
                db.clear_timer(user_id, "registration")
            elif state_data["state"] in ["waiting_for_login_username", "waiting_for_login_password"]:
                db.clear_timer(user_id, "login")
            del self.states[user_id]
    
    def update_data(self, user_id: int, key: str, value: Any):
        """Обновляет данные состояния"""
        if user_id in self.states:
            self.states[user_id]["data"][key] = value

user_state = UserState()

# ========== МЕНЕДЖЕР КУЛДАУНОВ ==========
class CooldownManager:
    @staticmethod
    async def check_cooldown(message: Message, user_id: int, is_admin_in_group: bool = False) -> Tuple[bool, Optional[str]]:
        """Проверяет кулдаун перед выполнением действия"""
        chat_type = message.chat.type
        
        # Админы Telegram в группах без КД
        if chat_type in ["group", "supergroup"] and is_admin_in_group:
            return True, None
        
        # Проверяем кулдаун из базы данных
        chat_id = message.chat.id
        last_action = db.get_user_cooldown(user_id, chat_id)
        
        if not last_action:
            return True, None
        
        # Определяем КД в зависимости от типа чата
        cooldown_seconds = COOLDOWN_GROUP if chat_type in ["group", "supergroup"] else COOLDOWN_PM
        
        # Проверяем VIP статус если пользователь авторизован
        if is_logged_in(user_id):
            session = get_user_session(user_id)
            if session and db.check_vip(session['account_id']):
                cooldown_seconds = int(cooldown_seconds / VIP_MULTIPLIER)
        
        now = datetime.now()
        elapsed = (now - last_action).total_seconds()
        
        if elapsed < cooldown_seconds:
            remaining = cooldown_seconds - elapsed
            return False, f"Подожди перед следующим действием\nОсталось: {format_time(remaining)}"
        
        return True, None
    
    @staticmethod
    async def update_cooldown(message: Message, user_id: int):
        """Обновляет кулдаун после выполнения действия"""
        chat_id = message.chat.id
        db.update_user_cooldown(user_id, chat_id)
        # Логируем активность
        db.log_activity(user_id, "command", message.chat.type)

# ========== ЗАЩИТА КНОПОК ==========
class ButtonSecurity:
    """Защита кнопок от чужих пользователей"""
    
    @staticmethod
    def create_callback_data(prefix: str, user_id: int, **kwargs) -> str:
        """Создает callback data с user_id"""
        data = f"{prefix}:{user_id}"
        for key, value in kwargs.items():
            data += f":{key}={value}"
        return data
    
    @staticmethod
    def parse_callback_data(callback_data: str) -> Tuple[str, int, Dict]:
        """Парсит callback data"""
        parts = callback_data.split(":")
        prefix = parts[0]
        user_id = int(parts[1])
        params = {}
        
        for part in parts[2:]:
            if "=" in part:
                key, value = part.split("=")
                params[key] = value
        
        return prefix, user_id, params
    
    @staticmethod
    async def check_owner(callback: CallbackQuery, check_session: bool = True) -> bool:
        """Проверяет, принадлежит ли кнопка пользователю"""
        try:
            _, owner_id, _ = ButtonSecurity.parse_callback_data(callback.data)
            
            # Проверяем владельца кнопки
            if callback.from_user.id != owner_id:
                return False
            
            # Если нужно проверять сессию
            if check_session:
                # Проверяем, есть ли у пользователя активная сессия
                # Для некоторых действий (профиль, главное меню) не требуется сессия
                prefix, owner_id, params = ButtonSecurity.parse_callback_data(callback.data)
                action = params.get("action") if params else None
                
                # Для этих действий не требуется сессия
                if prefix == "menu" and action in ["main", "profile", "admin"]:
                    return True
                
                # Для остальных действий проверяем сессию
                if not is_logged_in(callback.from_user.id):
                    return False
            
            return True
        except Exception as e:
            logger.error(f"Ошибка в check_owner: {e}")
            return False

# ========== КЛАВИАТУРЫ ==========
class Keyboards:
    """Класс для создания клавиатур"""
    
    @staticmethod
    def main_menu(user_id: int = None, in_group: bool = False) -> InlineKeyboardMarkup:
        """Главное меню"""
        builder = InlineKeyboardBuilder()
        
        is_logged = is_logged_in(user_id) if user_id else False
        is_admin = user_id in ADMIN_IDS if user_id else False
        
        if not is_logged:
            builder.row(
                InlineKeyboardButton(
                    text="🔐 Войти в аккаунт", 
                    callback_data=ButtonSecurity.create_callback_data("auth", user_id, action="login")
                ),
                InlineKeyboardButton(
                    text="📝 Регистрация", 
                    callback_data=ButtonSecurity.create_callback_data("auth", user_id, action="register")
                )
            )
        else:
            session = get_user_session(user_id)
            if session:
                account_settings = db.get_account_settings(session['account_id'])
                
                if account_settings['can_play_games']:
                    builder.row(
                        InlineKeyboardButton(
                            text="🎮 Игры", 
                            callback_data=ButtonSecurity.create_callback_data("menu", user_id, action="games")
                        ),
                    )
                if account_settings['can_work']:
                    builder.row(
                        InlineKeyboardButton(
                            text="💼 Работа", 
                            callback_data=ButtonSecurity.create_callback_data("menu", user_id, action="work")
                        ),
                    )
                if account_settings['can_use_shop']:
                    builder.row(
                        InlineKeyboardButton(
                            text="🏪 Магазин", 
                            callback_data=ButtonSecurity.create_callback_data("menu", user_id, action="shop")
                        ),
                    )
            
            builder.row(
                InlineKeyboardButton(
                    text="👤 Профиль", 
                    callback_data=ButtonSecurity.create_callback_data("menu", user_id, action="profile")
                ),
                InlineKeyboardButton(
                    text="🎁 Бонус", 
                    callback_data=ButtonSecurity.create_callback_data("menu", user_id, action="bonus")
                )
            )
            
            builder.row(
                InlineKeyboardButton(
                    text="🚪 Выйти", 
                    callback_data=ButtonSecurity.create_callback_data("auth", user_id, action="logout")
                )
            )
        
        # Кнопка админ-панели только для админа и ТОЛЬКО в ЛС (не в группах)
        if is_admin and not in_group:
            builder.row(
                InlineKeyboardButton(
                    text="🛠 Админ панель", 
                    callback_data=ButtonSecurity.create_callback_data("menu", user_id, action="admin")
                )
            )
        
        return builder.as_markup()
    
    @staticmethod
    def games_menu(user_id: int) -> InlineKeyboardMarkup:
        """Меню игр"""
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text="⚡ Импульс", 
                callback_data=ButtonSecurity.create_callback_data("game", user_id, type="impulse")
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="📶 Три сигнала", 
                callback_data=ButtonSecurity.create_callback_data("game", user_id, type="three_signals")
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="🎯 Тактическое решение", 
                callback_data=ButtonSecurity.create_callback_data("game", user_id, type="tactical")
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="🔙 Назад", 
                callback_data=ButtonSecurity.create_callback_data("menu", user_id, action="main")
            )
        )
        return builder.as_markup()
    
    @staticmethod
    def shop_menu(user_id: int) -> InlineKeyboardMarkup:
        """Меню магазина"""
        builder = InlineKeyboardBuilder()
        for days, price in VIP_PACKAGES.items():
            months = days // 30
            builder.row(
                InlineKeyboardButton(
                    text=f"VIP на {months} мес. - {price} Pulse", 
                    callback_data=ButtonSecurity.create_callback_data("buy_vip", user_id, days=days)
                )
            )
        builder.row(
            InlineKeyboardButton(
                text="🔙 Назад", 
                callback_data=ButtonSecurity.create_callback_data("menu", user_id, action="main")
            )
        )
        return builder.as_markup()
    
    @staticmethod
    def admin_menu(user_id: int) -> InlineKeyboardMarkup:
        """Меню админ-панели"""
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text="📊 Статистика", 
                callback_data=ButtonSecurity.create_callback_data("admin", user_id, action="stats")
            ),
            InlineKeyboardButton(
                text="👥 Все аккаунты", 
                callback_data=ButtonSecurity.create_callback_data("admin", user_id, action="accounts")
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="📋 Все сессии", 
                callback_data=ButtonSecurity.create_callback_data("admin", user_id, action="sessions")
            ),
            InlineKeyboardButton(
                text="🔍 Найти аккаунт", 
                callback_data=ButtonSecurity.create_callback_data("admin", user_id, action="search")
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="👤 Поиск по владельцу", 
                callback_data=ButtonSecurity.create_callback_data("admin", user_id, action="search_owner")
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="💰 Управление балансами", 
                callback_data=ButtonSecurity.create_callback_data("admin", user_id, action="balance")
            ),
            InlineKeyboardButton(
                text="📢 Рассылка", 
                callback_data=ButtonSecurity.create_callback_data("admin", user_id, action="broadcast")
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="🏦 Казна", 
                callback_data=ButtonSecurity.create_callback_data("admin", user_id, action="treasury")
            ),
            InlineKeyboardButton(
                text="⚙️ Управление", 
                callback_data=ButtonSecurity.create_callback_data("admin", user_id, action="manage")
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="🔙 В главное меню", 
                callback_data=ButtonSecurity.create_callback_data("menu", user_id, action="main")
            )
        )
        return builder.as_markup()
    
    @staticmethod
    def cancel_keyboard(user_id: int, action: str = "cancel") -> InlineKeyboardMarkup:
        """Клавиатура с отменой"""
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text="❌ Отменить действие", 
                callback_data=ButtonSecurity.create_callback_data(action, user_id)
            )
        )
        return builder.as_markup()
    
    @staticmethod
    def skip_recovery_keyboard(user_id: int) -> InlineKeyboardMarkup:
        """Клавиатура для пропуска кодового слова"""
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text="⏭ Пропустить", 
                callback_data=ButtonSecurity.create_callback_data("skip_recovery", user_id)
            ),
            InlineKeyboardButton(
                text="❌ Отмена", 
                callback_data=ButtonSecurity.create_callback_data("cancel", user_id)
            )
        )
        return builder.as_markup()
    
    @staticmethod
    def admin_back_keyboard(user_id: int) -> InlineKeyboardMarkup:
        """Клавиатура для возврата в админ-меню"""
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text="🔙 Назад в админ-панель", 
                callback_data=ButtonSecurity.create_callback_data("admin", user_id, action="back")
            )
        )
        return builder.as_markup()

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@dp.message(Command("start", "startpuls"))
async def cmd_start(message: Message):
    """Обработчик команд /start и /startpuls"""
    user_id = message.from_user.id
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(message, user_id)
    if not allowed:
        await message.answer(error)
        return
    
    # Обновляем кулдаун и логируем активность
    await CooldownManager.update_cooldown(message, user_id)
    
    in_group = message.chat.type in ["group", "supergroup"]
    
    welcome_text = (
        "🎮 <b>Добро пожаловать в Pulse Bot!</b>\n\n"
        "Это игровой бот с системой аккаунтов.\n"
        "Для начала работы необходимо зарегистрироваться или войти в существующий аккаунт.\n\n"
        "<b>⚠️ ВАЖНО:</b>\n"
        "• Регистрация доступна только в личных сообщениях\n"
        "• Никому не передавайте свои данные для входа\n"
        "• Администрация никогда не просит пароли или коды\n\n"
        "Выбери действие:"
    )
    
    await message.answer(welcome_text, reply_markup=Keyboards.main_menu(user_id, in_group))

@dp.message(Command("registerpuls"))
async def cmd_register(message: Message):
    """Команда регистрации"""
    user_id = message.from_user.id
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(message, user_id)
    if not allowed:
        await message.answer(error)
        return
    
    if message.chat.type != "private":
        await message.answer(
            "Регистрация доступна только в личных сообщениях. "
            "Я отправил тебе инструкцию в ЛС.",
            reply_to_message_id=message.message_id
        )
        
        try:
            await bot.send_message(
                user_id,
                "Для регистрации аккаунта нажмите кнопку '📝 Регистрация' в главном меню."
            )
        except:
            pass
        
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    if is_logged_in(user_id):
        await message.answer("Вы уже авторизованы в аккаунте. Сначала выйдите.")
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    # Проверяем, может ли пользователь создать аккаунт
    can_create, error_msg = db.can_create_account(user_id)
    if not can_create:
        await message.answer(f"❌ {error_msg}")
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    # Начинаем процесс регистрации
    user_state.set_state(user_id, "waiting_for_username")
    db.start_timer(user_id, "registration", REGISTRATION_TIMEOUT)
    
    # Показываем информацию о лимитах
    accounts_count = db.get_user_accounts_count(user_id)
    
    await message.answer(
        f"📝 <b>Регистрация нового аккаунта</b>\n\n"
        f"📊 <b>Ваши лимиты:</b>\n"
        f"• Создано аккаунтов: {accounts_count}/{MAX_ACCOUNTS_PER_USER}\n"
        f"• Новый аккаунт можно создать раз в 3 дня\n\n"
        f"Придумайте логин (имя пользователя):\n"
        f"• Минимум 3 символа\n"
        f"• Только буквы, цифры и _\n"
        f"• Уникальный для системы\n\n"
        f"⏰ У вас есть {REGISTRATION_TIMEOUT // 60} минут чтобы завершить регистрацию",
        reply_markup=Keyboards.cancel_keyboard(user_id)
    )
    
    await CooldownManager.update_cooldown(message, user_id)

@dp.message(Command("login"))
async def cmd_login(message: Message):
    """Команда входа в аккаунт"""
    user_id = message.from_user.id
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(message, user_id)
    if not allowed:
        await message.answer(error)
        return
    
    if message.chat.type != "private":
        await message.answer(
            "Вход в аккаунт доступен только в личных сообщениях.",
            reply_to_message_id=message.message_id
        )
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    if is_logged_in(user_id):
        await message.answer("Вы уже авторизованы в аккаунте.")
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    user_state.set_state(user_id, "waiting_for_login_username")
    db.start_timer(user_id, "login", LOGIN_TIMEOUT)
    
    await message.answer(
        "🔐 <b>Вход в аккаунт</b>\n\n"
        "Введите ваш логин:\n\n"
        f"⏰ У вас есть {LOGIN_TIMEOUT // 60} минут чтобы завершить вход",
        reply_markup=Keyboards.cancel_keyboard(user_id)
    )
    
    await CooldownManager.update_cooldown(message, user_id)

@dp.message(Command("logout"))
async def cmd_logout(message: Message):
    """Команда выхода из аккаунта"""
    user_id = message.from_user.id
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(message, user_id)
    if not allowed:
        await message.answer(error)
        return
    
    if not is_logged_in(user_id):
        await message.answer("Вы не авторизованы в аккаунте.")
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    session = get_user_session(user_id)
    if session:
        db.logout_session(session['session_id'])
    
    await message.answer(
        "✅ <b>Вы успешно вышли из аккаунта!</b>\n\n"
        "Теперь вы можете войти в другой аккаунт или зарегистрировать новый.",
        reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"])
    )
    
    await CooldownManager.update_cooldown(message, user_id)

# ========== КОМАНДЫ УДАЛЕНИЯ СООБЩЕНИЙ В ГРУППАХ ==========
@dp.message(F.text.startswith("-соо"))
async def delete_message_command(message: Message):
    """Команда -соо для удаления сообщений (только в ответ)"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Проверяем, что команда используется в группе
    if message.chat.type not in ["group", "supergroup"]:
        return
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(message, user_id)
    if not allowed:
        await message.answer(error, reply_to_message_id=message.message_id)
        return
    
    # Проверяем, что это ответ на сообщение
    if not message.reply_to_message:
        await message.answer("❌ Команда -соо работает только в ответ на сообщение!", reply_to_message_id=message.message_id)
        try:
            await message.delete()
        except:
            pass
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    # Проверяем, зарегистрирован ли пользователь
    if not is_logged_in(user_id):
        await message.answer("❌ Вы должны быть зарегистрированы в боте и войти в аккаунт для использования этой команды!", reply_to_message_id=message.message_id)
        try:
            await message.delete()
        except:
            pass
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    # Проверяем права пользователя
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        is_creator = chat_member.status == "creator"
        has_delete_permission = db.has_delete_permission(chat_id, user_id)
        
        # Только создатель или пользователи с правами могут удалять
        if not is_creator and not has_delete_permission:
            await message.answer("❌ У вас нет прав на удаление сообщений!", reply_to_message_id=message.message_id)
            try:
                await message.delete()
            except:
                pass
            await CooldownManager.update_cooldown(message, user_id)
            return
    except:
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    # Пытаемся удалить сообщение, на которое ответили
    try:
        await message.reply_to_message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
        await message.answer("❌ Не удалось удалить сообщение. У бота нет прав администратора!", reply_to_message_id=message.message_id)
    
    # Удаляем команду -соо
    try:
        await message.delete()
    except:
        pass
    
    await CooldownManager.update_cooldown(message, user_id)

@dp.message(F.text.startswith("+удал соо"))
async def grant_delete_permission_command(message: Message):
    """Команда +удал соо для выдачи прав на удаление"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Проверяем, что команда используется в группе
    if message.chat.type not in ["group", "supergroup"]:
        return
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(message, user_id)
    if not allowed:
        await message.answer(error, reply_to_message_id=message.message_id)
        return
    
    # Проверяем, что отправитель - создатель чата
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        if chat_member.status != "creator":
            await message.answer("❌ Только создатель чата может выдавать права на удаление!", reply_to_message_id=message.message_id)
            try:
                await message.delete()
            except:
                pass
            await CooldownManager.update_cooldown(message, user_id)
            return
    except:
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    # Получаем целевого пользователя
    target_user_id = None
    
    # Проверяем, если это ответ на сообщение
    if message.reply_to_message:
        target_user_id = message.reply_to_message.from_user.id
    # Или если указан user_id
    elif len(message.text.split()) > 2:
        try:
            target_user_id = int(message.text.split()[2])
        except ValueError:
            pass
    
    if not target_user_id:
        await message.answer(
            "❌ Не указан пользователь!\n\n"
            "Используйте команду одним из способов:\n"
            "1. Ответьте на сообщение пользователя командой +удал соо\n"
            "2. Укажите ID пользователя: +удал соо 123456789",
            reply_to_message_id=message.message_id
        )
        try:
            await message.delete()
        except:
            pass
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    # Проверяем, существует ли пользователь
    try:
        target_user = await bot.get_chat_member(chat_id, target_user_id)
    except:
        await message.answer("❌ Пользователь не найден в этом чате!", reply_to_message_id=message.message_id)
        try:
            await message.delete()
        except:
            pass
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    # Проверяем, зарегистрирован ли целевой пользователь
    if not is_logged_in(target_user_id):
        await message.answer(
            f"❌ Пользователь @{target_user.user.username or 'ID:' + str(target_user_id)} не зарегистрирован в боте!\n"
            "Пользователь должен быть зарегистрирован в боте и войти в аккаунт для получения прав.",
            reply_to_message_id=message.message_id
        )
        try:
            await message.delete()
        except:
            pass
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    # Выдаем права
    db.grant_delete_permission(chat_id, target_user_id, user_id)
    
    username = target_user.user.username or f"ID: {target_user_id}"
    await message.answer(
        f"✅ Пользователю @{username} выданы права на удаление сообщений командой -соо!",
        reply_to_message_id=message.message_id
    )
    
    try:
        await message.delete()
    except:
        pass
    
    await CooldownManager.update_cooldown(message, user_id)

@dp.message(F.text.startswith("-удал соо"))
async def revoke_delete_permission_command(message: Message):
    """Команда -удал соо для отзыва прав на удаление"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Проверяем, что команда используется в группе
    if message.chat.type not in ["group", "supergroup"]:
        return
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(message, user_id)
    if not allowed:
        await message.answer(error, reply_to_message_id=message.message_id)
        return
    
    # Проверяем, что отправитель - создатель чата
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        if chat_member.status != "creator":
            await message.answer("❌ Только создатель чата может отзывать права на удаление!", reply_to_message_id=message.message_id)
            try:
                await message.delete()
            except:
                pass
            await CooldownManager.update_cooldown(message, user_id)
            return
    except:
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    # Получаем целевого пользователя
    target_user_id = None
    
    # Проверяем, если это ответ на сообщение
    if message.reply_to_message:
        target_user_id = message.reply_to_message.from_user.id
    # Или если указан user_id
    elif len(message.text.split()) > 2:
        try:
            target_user_id = int(message.text.split()[2])
        except ValueError:
            pass
    
    if not target_user_id:
        await message.answer(
            "❌ Не указан пользователь!\n\n"
            "Используйте команду одним из способов:\n"
            "1. Ответьте на сообщение пользователя командой -удал соо\n"
            "2. Укажите ID пользователя: -удал соо 123456789",
            reply_to_message_id=message.message_id
        )
        try:
            await message.delete()
        except:
            pass
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    # Отзываем права
    success = db.revoke_delete_permission(chat_id, target_user_id)
    
    if success:
        try:
            target_user = await bot.get_chat_member(chat_id, target_user_id)
            username = target_user.user.username or f"ID: {target_user_id}"
        except:
            username = f"ID: {target_user_id}"
        
        await message.answer(
            f"✅ Права на удаление сообщений отозваны у пользователя @{username}!",
            reply_to_message_id=message.message_id
        )
    else:
        await message.answer(
            "❌ У этого пользователя нет прав на удаление сообций!\n\n"
            "Чтобы выдать права, используйте команду:\n"
            "+удал соо (ответом на сообщение пользователя или указав его ID)",
            reply_to_message_id=message.message_id
        )
    
    try:
        await message.delete()
    except:
        pass
    
    await CooldownManager.update_cooldown(message, user_id)

@dp.message(Command("удалсписок"))
async def list_delete_permissions_command(message: Message):
    """Команда для просмотра списка пользователей с правами на удаление"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Проверяем, что команда используется в группе
    if message.chat.type not in ["group", "supergroup"]:
        return
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(message, user_id)
    if not allowed:
        await message.answer(error, reply_to_message_id=message.message_id)
        return
    
    # Проверяем, что отправитель - создатель чата
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        if chat_member.status != "creator":
            await message.answer("❌ Только создатель чата может просматривать список прав!", reply_to_message_id=message.message_id)
            await CooldownManager.update_cooldown(message, user_id)
            return
    except:
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    # Получаем список пользователей с правами
    permissions = db.get_all_with_delete_permissions(chat_id)
    
    if not permissions:
        await message.answer(
            "📋 <b>Список прав на удаление сообщений</b>\n\n"
            "В этом чате никто не имеет прав на удаление сообщений командой -соо.\n\n"
            "Чтобы выдать права:\n"
            "+удал соо (ответом на сообщение пользователя)",
            reply_to_message_id=message.message_id
        )
    else:
        # Формируем список
        permissions_text = "📋 <b>Список прав на удаление сообщений</b>\n\n"
        
        for perm in permissions:
            try:
                user = await bot.get_chat_member(chat_id, perm['user_id'])
                username = f"@{user.user.username}" if user.user.username else f"ID: {perm['user_id']}"
            except:
                username = f"ID: {perm['user_id']}"
            
            try:
                granted_by_user = await bot.get_chat_member(chat_id, perm['granted_by'])
                granted_by_name = f"@{granted_by_user.user.username}" if granted_by_user.user.username else f"ID: {perm['granted_by']}"
            except:
                granted_by_name = f"ID: {perm['granted_by']}"
            
            granted_date = datetime.fromisoformat(perm['granted_at']).strftime('%d.%m.%Y %H:%M')
            
            permissions_text += (
                f"👤 <b>{username}</b>\n"
                f"   🎖️ Выдал: {granted_by_name}\n"
                f"   📅 Дата: {granted_date}\n"
                f"   🔧 Отозвать: -удал соо {perm['user_id']}\n\n"
            )
        
        permissions_text += "\n<i>Для отзыва прав используйте команду: -удал соо (ответом на сообщение или указав ID)</i>"
        
        await message.answer(permissions_text, reply_to_message_id=message.message_id)
    
    await CooldownManager.update_cooldown(message, user_id)

# ========== ОБРАБОТКА ВВОДА ДАННЫХ ==========
@dp.message(F.text)
async def handle_text_input(message: Message):
    """Обработчик текстового ввода"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Пропускаем команды удаления сообщений
    if text.startswith(("-соо", "+удал соо", "-удал соо")):
        return
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(message, user_id)
    if not allowed:
        await message.answer(error)
        return
    
    # Получаем текущее состояние
    state_data = user_state.get_state(user_id)
    
    # Если нет состояния, проверяем не админ ли это
    if not state_data:
        return
    
    state = state_data["state"]
    data = state_data["data"]
    
    # Проверяем таймер
    if state in ["waiting_for_username", "waiting_for_password", "waiting_for_recovery"]:
        is_active, timer_msg = db.check_timer(user_id, "registration")
        if is_active and timer_msg:
            await message.answer(f"⏰ {timer_msg}\n\nПроцесс регистрации продолжается.")
        elif not is_active:
            await message.answer("⏰ Время регистрации вышло! Процесс отменен.")
            user_state.clear_state(user_id)
            await message.answer("Главное меню:", reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"]))
            await CooldownManager.update_cooldown(message, user_id)
            return
    elif state in ["waiting_for_login_username", "waiting_for_login_password"]:
        is_active, timer_msg = db.check_timer(user_id, "login")
        if is_active and timer_msg:
            await message.answer(f"⏰ {timer_msg}\n\nПроцесс входа продолжается.")
        elif not is_active:
            await message.answer("⏰ Время на вход вышло! Процесс отменен.")
            user_state.clear_state(user_id)
            await message.answer("Главное меню:", reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"]))
            await CooldownManager.update_cooldown(message, user_id)
            return
    
    # Обработка админских состояний
    if state == "admin_password":
        # Обработка админского пароля
        if text == ADMIN_PASSWORD:
            db.create_admin_session(user_id)
            user_state.clear_state(user_id)
            await message.answer(
                "✅ <b>Пароль правильный!</b>\n\n"
                "Доступ к админ-панели разрешен.\n"
                "Сессия активна 30 минут.\n\n"
                "Выберите действие:",
                reply_markup=Keyboards.admin_menu(user_id)
            )
        else:
            await message.answer(
                "❌ <b>Пароль не правильный!</b>\n\n"
                "Попробуйте еще раз или нажмите 'Отмена'.",
                reply_markup=Keyboards.cancel_keyboard(user_id)
            )
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    elif state == "admin_search":
        # Поиск аккаунта по логину или ID
        try:
            # Пробуем найти по ID
            if text.isdigit():
                account_id = int(text)
                account = db.get_account_by_id(account_id)
                if not account:
                    await message.answer(f"❌ Аккаунт с ID {account_id} не найден.\n\nПопробуйте еще раз или нажмите 'Отмена'.", 
                                       reply_markup=Keyboards.cancel_keyboard(user_id))
                    await CooldownManager.update_cooldown(message, user_id)
                    return
            else:
                # Ищем по логину
                account = db.get_account_by_username(text)
                if not account:
                    await message.answer(f"❌ Аккаунт с логином '{text}' не найден.\n\nПопробуйте еще раз или нажмите 'Отмена'.", 
                                       reply_markup=Keyboards.cancel_keyboard(user_id))
                    await CooldownManager.update_cooldown(message, user_id)
                    return
                account_id = account['account_id']
            
            # Получаем игровые данные
            game_data = db.get_game_data(account_id)
            
            # Формируем информацию об аккаунте
            account_info = (
                f"🔍 <b>Найден аккаунт:</b>\n\n"
                f"🆔 ID: {account['account_id']}\n"
                f"👤 Логин: <code>{account['username']}</code>\n"
                f"🔐 Пароль: <code>{account['password']}</code>\n"
                f"🗝️ Кодовое слово: <code>{account['recovery_code'] or 'Не установлено'}</code>\n"
                f"👑 Владелец: {account['owner_user_id']}\n"
                f"📅 Создан: {datetime.fromisoformat(account['created_at']).strftime('%d.%m.%Y %H:%M')}\n"
                f"🚫 Заблокирован: {'✅ Да' if account['is_blocked'] else '❌ Нет'}\n\n"
                f"💰 <b>Игровые данные:</b>\n"
                f"💵 Баланс: {game_data['balance'] if game_data else 0} Pulse\n"
                f"⭐ VIP: {'✅ Да' if game_data and db.check_vip(account_id) else '❌ Нет'}\n"
                f"🎮 Игр сыграно: {game_data['games_played'] if game_data else 0}\n"
                f"💼 Работ выполнено: {game_data['work_count'] if game_data else 0}"
            )
            
            user_state.clear_state(user_id)
            await message.answer(account_info, reply_markup=Keyboards.admin_menu(user_id))
            
        except Exception as e:
            logger.error(f"Ошибка при поиске аккаунта: {e}")
            await message.answer("❌ Произошла ошибка при поиске аккаунта.\n\nПопробуйте еще раз или нажмите 'Отмена'.", 
                               reply_markup=Keyboards.cancel_keyboard(user_id))
        
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    elif state == "admin_search_by_owner":
        # Поиск аккаунтов по ID владельца
        if not text.isdigit():
            await message.answer("❌ Введите числовой ID пользователя.\n\nПопробуйте еще раз или нажмите 'Отмена'.", 
                               reply_markup=Keyboards.cancel_keyboard(user_id))
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        owner_id = int(text)
        accounts = db.search_accounts_by_owner(owner_id)
        
        if not accounts:
            await message.answer(f"❌ У пользователя с ID {owner_id} нет аккаунтов.\n\nПопробуйте другой ID или нажмите 'Отмена'.", 
                               reply_markup=Keyboards.cancel_keyboard(user_id))
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        accounts_text = f"👤 <b>Аккаунты пользователя {owner_id}:</b>\n\n"
        accounts_text += f"📊 Всего аккаунтов: {len(accounts)}\n\n"
        
        for i, account in enumerate(accounts, 1):
            game_data = db.get_game_data(account['account_id'])
            accounts_text += (
                f"{i}. <b>{account['username']}</b>\n"
                f"   🆔 ID: {account['account_id']}\n"
                f"   🔐 Пароль: <code>{account['password']}</code>\n"
                f"   🗝️ Кодовое слово: <code>{account['recovery_code'] or 'Нет'}</code>\n"
                f"   💰 Баланс: {game_data['balance'] if game_data else 0} Pulse\n"
                f"   📅 Создан: {datetime.fromisoformat(account['created_at']).strftime('%d.%m.%Y')}\n\n"
            )
        
        user_state.clear_state(user_id)
        await message.answer(accounts_text, reply_markup=Keyboards.admin_menu(user_id))
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    elif state == "admin_balance":
        # Управление балансом аккаунта
        parts = text.split()
        if len(parts) != 2:
            await message.answer("❌ Неверный формат. Используйте: <логин или ID> <сумма>\n\nПример: myaccount 1000\n\nПопробуйте еще раз или нажмите 'Отмена'.", 
                               reply_markup=Keyboards.cancel_keyboard(user_id))
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        target, amount_str = parts
        try:
            amount = int(amount_str)
        except ValueError:
            await message.answer("❌ Сумма должна быть числом.\n\nПопробуйте еще раз или нажмите 'Отмена'.", 
                               reply_markup=Keyboards.cancel_keyboard(user_id))
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        # Ищем аккаунт
        if target.isdigit():
            account = db.get_account_by_id(int(target))
        else:
            account = db.get_account_by_username(target)
        
        if not account:
            await message.answer(f"❌ Аккаунт '{target}' не найден.\n\nПопробуйте еще раз или нажмите 'Отмена'.", 
                               reply_markup=Keyboards.cancel_keyboard(user_id))
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        # Устанавливаем баланс
        db.set_balance(account['account_id'], amount)
        
        user_state.clear_state(user_id)
        await message.answer(
            f"✅ <b>Баланс обновлен!</b>\n\n"
            f"👤 Аккаунт: {account['username']}\n"
            f"💰 Новый баланс: {amount} Pulse\n"
            f"🆔 ID: {account['account_id']}",
            reply_markup=Keyboards.admin_menu(user_id)
        )
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    elif state == "admin_broadcast":
        # Рассылка сообщения
        if len(text) < 5:
            await message.answer("❌ Сообщение слишком короткое (минимум 5 символов).\n\nПопробуйте еще раз или нажмите 'Отмена'.", 
                               reply_markup=Keyboards.cancel_keyboard(user_id))
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        user_state.clear_state(user_id)
        
        # Получаем все уникальные пользователи из активности
        db.cursor.execute("SELECT DISTINCT user_id FROM user_activity")
        users = db.cursor.fetchall()
        
        if not users:
            await message.answer("❌ Нет пользователей для рассылки.", reply_markup=Keyboards.admin_menu(user_id))
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        sent = 0
        failed = 0
        
        await message.answer(f"📢 <b>Начинаю рассылку...</b>\n\nПолучателей: {len(users)}\n\nСообщение:\n{text[:100]}...")
        
        for user_row in users:
            try:
                await bot.send_message(user_row[0], f"📢 <b>Рассылка от администратора:</b>\n\n{text}")
                sent += 1
                await asyncio.sleep(0.1)  # Задержка чтобы не превысить лимиты
            except:
                failed += 1
        
        await message.answer(
            f"✅ <b>Рассылка завершена!</b>\n\n"
            f"📊 Статистика:\n"
            f"✅ Отправлено: {sent}\n"
            f"❌ Не отправлено: {failed}\n"
            f"📨 Всего получателей: {len(users)}",
            reply_markup=Keyboards.admin_menu(user_id)
        )
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    elif state == "admin_treasury":
        # Изменение казны
        if not text.isdigit():
            await message.answer("❌ Введите число для установки суммы казны.\n\nПопробуйте еще раз или нажмите 'Отмена'.", 
                               reply_markup=Keyboards.cancel_keyboard(user_id))
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        # Здесь должна быть логика изменения казны
        # В реальном боте нужно добавить таблицу для казны
        
        user_state.clear_state(user_id)
        await message.answer(
            f"✅ <b>Казна обновлена!</b>\n\n"
            f"🏦 Новая сумма казны: {text} Pulse",
            reply_markup=Keyboards.admin_menu(user_id)
        )
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    # Обработка состояний регистрации
    if state == "waiting_for_username":
        # Проверяем логин
        if len(text) < 3:
            await message.answer("Логин должен содержать минимум 3 символа. Попробуйте еще раз:")
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        if not re.match(r'^[A-Za-z0-9_]+$', text):
            await message.answer("Логин может содержать только буквы, цифры и символ _. Попробуйте еще раз:")
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        if db.username_exists(text):
            await message.answer("Этот логин уже занят. Придумайте другой:")
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        # Сохраняем логин и запрашиваем пароль
        data["username"] = text
        user_state.update_data(user_id, "username", text)
        user_state.set_state(user_id, "waiting_for_password", data)
        
        await message.answer(
            "✅ Отлично! Теперь придумайте пароль:\n\n"
            "<b>Требования к паролю:</b>\n"
            "• Минимум 5 символов\n"
            "• Хотя бы 1 буква\n"
            "• Хотя бы 1 цифра\n"
            "• Максимум 15 символов",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
        await CooldownManager.update_cooldown(message, user_id)
    
    elif state == "waiting_for_password":
        # Проверяем пароль
        is_valid, error_msg = validate_password(text)
        if not is_valid:
            await message.answer(f"{error_msg}\n\nПопробуйте еще раз:")
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        # Сохраняем пароль и запрашиваем кодовое слово
        data["password"] = text
        user_state.update_data(user_id, "password", text)
        user_state.set_state(user_id, "waiting_for_recovery", data)
        
        await message.answer(
            "✅ <b>Отличный пароль!</b>\n\n"
            "<b>Теперь придумайте кодовое слово для восстановления аккаунта:</b>\n"
            "• Только английские буквы\n"
            "• Минимум 5 символов\n"
            "• Максимум 20 символов\n\n"
            "<i>Это слово нужно будет сказать администрации для восстановления доступа к аккаунту, "
            "если вы забудете пароль.</i>\n\n"
            "Можно пропустить этот шаг, но это не рекомендуется.",
            reply_markup=Keyboards.skip_recovery_keyboard(user_id)
        )
        await CooldownManager.update_cooldown(message, user_id)
    
    elif state == "waiting_for_recovery":
        # Проверяем кодовое слово
        is_valid, error_msg = validate_recovery_code(text)
        if not is_valid:
            await message.answer(f"{error_msg}\n\nПопробуйте еще раз:")
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        # Завершаем регистрацию
        username = data.get("username")
        password = data.get("password")
        
        if not username or not password:
            await message.answer("Ошибка: данные регистрации потеряны. Начните заново.")
            user_state.clear_state(user_id)
            await message.answer("Главное меню:", reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"]))
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        # Проверяем лимиты перед созданием аккаунта
        can_create, error_msg = db.can_create_account(user_id)
        if not can_create:
            await message.answer(f"❌ {error_msg}")
            user_state.clear_state(user_id)
            await message.answer("Главное меню:", reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"]))
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        account_id = db.create_account(username, password, text, user_id)
        if not account_id:
            await message.answer("Произошла ошибка при создании аккаунта. Попробуйте еще раз.")
            user_state.clear_state(user_id)
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        # Создаем сессию
        db.create_session(user_id, account_id, message.from_user.username)
        
        # Очищаем таймер
        db.clear_timer(user_id, "registration")
        user_state.clear_state(user_id)
        
        await message.answer(
            "🎉 <b>Поздравляем с успешной регистрацией!</b>\n\n"
            f"📝 <b>Ваши данные:</b>\n"
            f"👤 Логин: <code>{username}</code>\n"
            f"🔐 Пароль: <code>{password}</code>\n"
            f"🗝️ Кодовое слово: <code>{text}</code>\n\n"
            "<b>⚠️ СОХРАНИТЕ ЭТИ ДАННЫЕ!</b>\n"
            "• Никому не передавайте свои данные\n"
            "• Кодовое слово нужно для восстановления аккаунта\n"
            "• Администрация никогда не просит пароли\n\n"
            "Теперь вы можете пользоваться всеми функциями бота!",
            reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"])
        )
        await CooldownManager.update_cooldown(message, user_id)
    
    # Обработка состояний входа
    elif state == "waiting_for_login_username":
        # Сохраняем логин для входа
        data["login_username"] = text
        user_state.update_data(user_id, "login_username", text)
        user_state.set_state(user_id, "waiting_for_login_password", data)
        
        await message.answer("Введите пароль:", reply_markup=Keyboards.cancel_keyboard(user_id))
        await CooldownManager.update_cooldown(message, user_id)
    
    elif state == "waiting_for_login_password":
        # Пытаемся войти
        username = data.get("login_username")
        password = text
        
        if not username:
            await message.answer("Ошибка: логин не найден. Начните заново.")
            user_state.clear_state(user_id)
            await message.answer("Главное меню:", reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"]))
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        account = db.get_account_by_credentials(username, password)
        if not account:
            await message.answer("Неверный логин или пароль. Попробуйте еще раз или зарегистрируйтесь.")
            user_state.clear_state(user_id)
            await message.answer("Главное меню:", reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"]))
            await CooldownManager.update_cooldown(message, user_id)
            return
        
        # Создаем сессию
        db.create_session(user_id, account['account_id'], message.from_user.username)
        
        # Очищаем таймер
        db.clear_timer(user_id, "login")
        user_state.clear_state(user_id)
        
        game_data = db.get_game_data(account['account_id'])
        
        await message.answer(
            f"✅ <b>Успешный вход!</b>\n\n"
            f"👤 Аккаунт: <code>{username}</code>\n"
            f"💰 Баланс: {game_data['balance'] if game_data else 0} Pulse Coins\n"
            f"⭐ Статус: {'✅ VIP' if db.check_vip(account['account_id']) else '❌ Обычный'}\n\n"
            "Добро пожаловать обратно!",
            reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"])
        )
        await CooldownManager.update_cooldown(message, user_id)

# ========== ОБРАБОТЧИКИ КНОПОК ==========
@dp.callback_query(F.data.startswith("auth:"))
async def auth_handler(callback: CallbackQuery):
    """Обработчик кнопок авторизации"""
    user_id = callback.from_user.id
    
    # Проверяем владельца кнопки
    if not await ButtonSecurity.check_owner(callback, check_session=False):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(callback.message, user_id)
    if not allowed:
        await callback.answer(error, show_alert=True)
        return
    
    prefix, owner_id, params = ButtonSecurity.parse_callback_data(callback.data)
    action = params.get("action")
    
    if action == "register":
        if callback.message.chat.type != "private":
            await callback.answer("Регистрация только в ЛС! Я написал вам.", show_alert=True)
            try:
                await bot.send_message(
                    user_id,
                    "Для регистрации аккаунта нажмите кнопку '📝 Регистрация' в главном меню."
                )
            except:
                pass
            await CooldownManager.update_cooldown(callback.message, user_id)
            return
        
        if is_logged_in(user_id):
            await callback.answer("Вы уже авторизованы!", show_alert=True)
            await CooldownManager.update_cooldown(callback.message, user_id)
            return
        
        # Проверяем, может ли пользователь создать аккаунт
        can_create, error_msg = db.can_create_account(user_id)
        if not can_create:
            await callback.answer(f"❌ {error_msg}", show_alert=True)
            await CooldownManager.update_cooldown(callback.message, user_id)
            return
        
        user_state.set_state(user_id, "waiting_for_username")
        db.start_timer(user_id, "registration", REGISTRATION_TIMEOUT)
        
        # Показываем информацию о лимитах
        accounts_count = db.get_user_accounts_count(user_id)
        
        await callback.message.edit_text(
            f"📝 <b>Регистрация нового аккаунта</b>\n\n"
            f"📊 <b>Ваши лимиты:</b>\n"
            f"• Создано аккаунтов: {accounts_count}/{MAX_ACCOUNTS_PER_USER}\n"
            f"• Новый аккаунт можно создать раз в 3 дня\n\n"
            f"Придумайте логин (имя пользователя):\n"
            f"• Минимум 3 символа\n"
            f"• Только буквы, цифры и _\n"
            f"• Уникальный для системы\n\n"
            f"⏰ У вас есть {REGISTRATION_TIMEOUT // 60} минут чтобы завершить регистрацию",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "login":
        if callback.message.chat.type != "private":
            await callback.answer("Вход только в ЛС!", show_alert=True)
            await CooldownManager.update_cooldown(callback.message, user_id)
            return
        
        if is_logged_in(user_id):
            await callback.answer("Вы уже авторизованы!", show_alert=True)
            await CooldownManager.update_cooldown(callback.message, user_id)
            return
        
        user_state.set_state(user_id, "waiting_for_login_username")
        db.start_timer(user_id, "login", LOGIN_TIMEOUT)
        
        await callback.message.edit_text(
            "🔐 <b>Вход в аккаунт</b>\n\n"
            "Введите ваш логин:\n\n"
            f"⏰ У вас есть {LOGIN_TIMEOUT // 60} минут чтобы завершить вход",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "logout":
        if not is_logged_in(user_id):
            await callback.answer("Вы не авторизованы!", show_alert=True)
            await CooldownManager.update_cooldown(callback.message, user_id)
            return
        
        session = get_user_session(user_id)
        if session:
            db.logout_session(session['session_id'])
        
        in_group = callback.message.chat.type in ["group", "supergroup"]
        await callback.message.edit_text(
            "✅ <b>Вы успешно вышли из аккаунта!</b>\n\n"
            "Теперь вы можете войти в другой аккаунт или зарегистрировать новый.",
            reply_markup=Keyboards.main_menu(user_id, in_group)
        )
    
    await CooldownManager.update_cooldown(callback.message, user_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("skip_recovery:"))
async def skip_recovery_handler(callback: CallbackQuery):
    """Пропуск кодового слова"""
    if not await ButtonSecurity.check_owner(callback, check_session=False):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(callback.message, user_id)
    if not allowed:
        await callback.answer(error, show_alert=True)
        return
    
    state_data = user_state.get_state(user_id)
    if not state_data or state_data["state"] != "waiting_for_recovery":
        await callback.answer("Неверное состояние", show_alert=True)
        await CooldownManager.update_cooldown(callback.message, user_id)
        return
    
    data = state_data["data"]
    
    # Завершаем регистрацию без кодового слова
    username = data.get("username")
    password = data.get("password")
    
    if not username or not password:
        await callback.answer("Ошибка: данные регистрации потеряны", show_alert=True)
        user_state.clear_state(user_id)
        await CooldownManager.update_cooldown(callback.message, user_id)
        return
    
    # Проверяем лимиты перед созданием аккаунта
    can_create, error_msg = db.can_create_account(user_id)
    if not can_create:
        await callback.answer(f"❌ {error_msg}", show_alert=True)
        user_state.clear_state(user_id)
        await CooldownManager.update_cooldown(callback.message, user_id)
        return
    
    account_id = db.create_account(username, password, None, user_id)
    if not account_id:
        await callback.answer("Ошибка создания аккаунта", show_alert=True)
        user_state.clear_state(user_id)
        await CooldownManager.update_cooldown(callback.message, user_id)
        return
    
    # Создаем сессию
    db.create_session(user_id, account_id, callback.from_user.username)
    
    # Очищаем таймер
    db.clear_timer(user_id, "registration")
    user_state.clear_state(user_id)
    
    in_group = callback.message.chat.type in ["group", "supergroup"]
    await callback.message.edit_text(
        "🎉 <b>Поздравляем с успешной регистрацией!</b>\n\n"
        f"📝 <b>Ваши данные:</b>\n"
        f"👤 Логин: <code>{username}</code>\n"
        f"🔐 Пароль: <code>{password}</code>\n\n"
        "<b>⚠️ ВНИМАНИЕ:</b>\n"
        "• Вы не указали кодовое слово для восстановления\n"
        "• При потере пароля восстановить аккаунт будет сложнее\n"
        "• Никому не передавайте свои данные!\n\n"
        "Теперь вы можете пользоваться всеми функциями бота!",
        reply_markup=Keyboards.main_menu(user_id, in_group)
    )
    
    await CooldownManager.update_cooldown(callback.message, user_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("cancel:"))
async def cancel_handler(callback: CallbackQuery):
    """Обработчик отмены действия"""
    if not await ButtonSecurity.check_owner(callback, check_session=False):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(callback.message, user_id)
    if not allowed:
        await callback.answer(error, show_alert=True)
        return
    
    # Очищаем состояние и таймеры
    state_data = user_state.get_state(user_id)
    if state_data:
        if state_data["state"] in ["waiting_for_username", "waiting_for_password", "waiting_for_recovery"]:
            db.clear_timer(user_id, "registration")
        elif state_data["state"] in ["waiting_for_login_username", "waiting_for_login_password"]:
            db.clear_timer(user_id, "login")
    
    user_state.clear_state(user_id)
    
    in_group = callback.message.chat.type in ["group", "supergroup"]
    await callback.message.edit_text(
        "❌ Действие отменено.\n\nГлавное меню:",
        reply_markup=Keyboards.main_menu(user_id, in_group)
    )
    
    await CooldownManager.update_cooldown(callback.message, user_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("menu:"))
async def menu_handler(callback: CallbackQuery):
    """Обработчик главного меню"""
    user_id = callback.from_user.id
    
    # Проверяем владельца кнопки
    if not await ButtonSecurity.check_owner(callback, check_session=False):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(callback.message, user_id)
    if not allowed:
        await callback.answer(error, show_alert=True)
        return
    
    prefix, owner_id, params = ButtonSecurity.parse_callback_data(callback.data)
    action = params.get("action")
    
    # Очищаем любые активные состояния при переходе в меню
    if user_state.get_state(user_id):
        user_state.clear_state(user_id)
    
    if action == "admin":
        if user_id not in ADMIN_IDS:
            await callback.answer("Доступ запрещен", show_alert=True)
            await CooldownManager.update_cooldown(callback.message, user_id)
            return
        
        # Проверяем админскую сессию
        if not db.check_admin_session(user_id):
            # Запрашиваем пароль
            await callback.message.edit_text(
                "🔐 <b>Админ-панель</b>\n\n"
                "Введите пароль для доступа:",
                reply_markup=Keyboards.cancel_keyboard(user_id)
            )
            user_state.set_state(user_id, "admin_password")
        else:
            # Показываем админ-панель
            await callback.message.edit_text(
                "🛠 <b>Админ-панель</b>\n\nВыберите действие:",
                reply_markup=Keyboards.admin_menu(user_id)
            )
        
        await CooldownManager.update_cooldown(callback.message, user_id)
        await callback.answer()
        return
    
    # Для остальных действий проверяем авторизацию (кроме главного меню и профиля)
    if action not in ["main", "profile"] and not is_logged_in(user_id):
        await callback.answer("Сначала войдите в аккаунт!", show_alert=True)
        await CooldownManager.update_cooldown(callback.message, user_id)
        return
    
    in_group = callback.message.chat.type in ["group", "supergroup"]
    
    if action == "main":
        await callback.message.edit_text(
            "🎮 <b>Главное меню</b>\n\nВыбери действие:",
            reply_markup=Keyboards.main_menu(user_id, in_group)
        )
    
    elif action == "games":
        await callback.message.edit_text(
            "🎮 <b>Игры</b>\n\nВыбери игру:\n"
            "⚡ <b>Импульс</b> - проверь свою реакцию\n"
            "📶 <b>Три сигнала</b> - найди настоящий сигнал\n"
            "🎯 <b>Тактическое решение</b> - переиграй противника\n\n"
            f"Минимальная ставка: {MIN_BET} Pulse Coins",
            reply_markup=Keyboards.games_menu(user_id)
        )
    
    elif action == "work":
        await work_command(callback.message)
        await callback.answer()
        return
    
    elif action == "shop":
        await callback.message.edit_text(
            "🏪 <b>Магазин</b>\n\nДоступные товары:\n"
            "💎 <b>VIP статус</b> - уменьшает все кулдауны в 1.5 раза\n\n"
            "Выбери пакет:",
            reply_markup=Keyboards.shop_menu(user_id)
        )
    
    elif action == "profile":
        # Профиль могут смотреть даже чужие пользователи
        await show_profile(callback.message, user_id)
        await callback.answer()
        return
    
    elif action == "bonus":
        await bonus_command(callback.message)
        await callback.answer()
        return
    
    await CooldownManager.update_cooldown(callback.message, user_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("admin:"))
async def admin_handler(callback: CallbackQuery):
    """Обработчик админ-меню"""
    user_id = callback.from_user.id
    
    if not await ButtonSecurity.check_owner(callback, check_session=False):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    if user_id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        await CooldownManager.update_cooldown(callback.message, user_id)
        return
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(callback.message, user_id)
    if not allowed:
        await callback.answer(error, show_alert=True)
        return
    
    # Проверяем админскую сессию
    if not db.check_admin_session(user_id):
        await callback.answer("Сессия истекла. Введите пароль заново.", show_alert=True)
        await CooldownManager.update_cooldown(callback.message, user_id)
        return
    
    prefix, owner_id, params = ButtonSecurity.parse_callback_data(callback.data)
    action = params.get("action")
    
    if action == "back":
        await callback.message.edit_text(
            "🛠 <b>Админ-панель</b>\n\nВыберите действие:",
            reply_markup=Keyboards.admin_menu(user_id)
        )
        await CooldownManager.update_cooldown(callback.message, user_id)
        await callback.answer()
        return
    
    elif action == "stats":
        # Статистика бота
        total_accounts = db.get_total_accounts_count()
        
        # Статистика активности
        today_stats = db.get_activity_stats("today")
        month_stats = db.get_activity_stats("month")
        all_stats = db.get_activity_stats("all")
        
        # Казна
        treasury = db.get_treasury()
        
        stats_text = (
            f"📊 <b>Статистика бота</b>\n\n"
            f"👥 Всего аккаунтов: {total_accounts}\n"
            f"🏦 Казна: {treasury} Pulse\n\n"
            f"📈 <b>Активность за сегодня:</b>\n"
            f"👤 Уникальных пользователей: {today_stats['unique_users']}\n"
            f"📨 Действий: {today_stats['total_actions']}\n\n"
            f"📅 <b>Активность за месяц:</b>\n"
            f"👤 Уникальных пользователей: {month_stats['unique_users']}\n"
            f"📨 Действий: {month_stats['total_actions']}\n\n"
            f"📊 <b>Вся статистика:</b>\n"
            f"👤 Уникальных пользователей: {all_stats['unique_users']}\n"
            f"📨 Действий: {all_stats['total_actions']}"
        )
        
        await callback.message.edit_text(stats_text, reply_markup=Keyboards.admin_menu(user_id))
    
    elif action == "accounts":
        # Все аккаунты
        accounts = db.get_all_accounts(limit=20)
        
        if not accounts:
            accounts_text = "📭 <b>Нет зарегистрированных аккаунтов</b>"
        else:
            accounts_text = f"👥 <b>Последние 20 аккаунтов:</b>\n\n"
            
            for i, account in enumerate(accounts, 1):
                game_data = db.get_game_data(account['account_id'])
                accounts_text += (
                    f"{i}. <b>{account['username']}</b>\n"
                    f"   🆔 ID: {account['account_id']}\n"
                    f"   👑 Владелец: {account['owner_user_id']}\n"
                    f"   💰 Баланс: {game_data['balance'] if game_data else 0} Pulse\n"
                    f"   📅 Создан: {datetime.fromisoformat(account['created_at']).strftime('%d.%m.%Y')}\n\n"
                )
            
            accounts_text += f"📊 Всего аккаунтов: {db.get_total_accounts_count()}"
        
        await callback.message.edit_text(accounts_text, reply_markup=Keyboards.admin_menu(user_id))
    
    elif action == "sessions":
        # Все сессии
        sessions = db.get_all_sessions(limit=20)
        
        if not sessions:
            sessions_text = "📭 <b>Нет активных сессий</b>"
        else:
            sessions_text = f"📋 <b>Последние 20 сессий:</b>\n\n"
            
            for i, session in enumerate(sessions, 1):
                login_time = datetime.fromisoformat(session['login_time']).strftime('%d.%m.%Y %H:%M')
                logout_time = datetime.fromisoformat(session['logout_time']).strftime('%d.%m.%Y %H:%M') if session['logout_time'] else "Активна"
                status = "✅ Активна" if not session['logout_time'] else "❌ Завершена"
                
                sessions_text += (
                    f"{i}. <b>{session['username']}</b>\n"
                    f"   👤 Пользователь: {session['user_id']}\n"
                    f"   🆔 Сессия: #{session['session_id']}\n"
                    f"   📅 Вход: {login_time}\n"
                    f"   📅 Выход: {logout_time}\n"
                    f"   📊 Статус: {status}\n\n"
                )
        
        await callback.message.edit_text(sessions_text, reply_markup=Keyboards.admin_menu(user_id))
    
    elif action == "search":
        # Поиск аккаунта
        user_state.set_state(user_id, "admin_search")
        await callback.message.edit_text(
            "🔍 <b>Поиск аккаунта</b>\n\n"
            "Введите логин или ID аккаунта для поиска:\n\n"
            "<i>Примеры:</i>\n"
            "<code>myusername</code> - поиск по логину\n"
            "<code>123</code> - поиск по ID аккаунта",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "search_owner":
        # Поиск по владельцу
        user_state.set_state(user_id, "admin_search_by_owner")
        await callback.message.edit_text(
            "👤 <b>Поиск аккаунтов по владельцу</b>\n\n"
            "Введите ID пользователя Telegram для поиска его аккаунтов:\n\n"
            "<i>Пример:</i>\n"
            "<code>123456789</code> - поиск всех аккаунтов пользователя с этим ID",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "balance":
        # Управление балансами
        user_state.set_state(user_id, "admin_balance")
        await callback.message.edit_text(
            "💰 <b>Управление балансами</b>\n\n"
            "Введите логин или ID аккаунта и новую сумму:\n\n"
            "<i>Формат:</i>\n"
            "<code>логин сумма</code>\n"
            "<code>ID сумма</code>\n\n"
            "<i>Примеры:</i>\n"
            "<code>myusername 1000</code>\n"
            "<code>123 500</code>",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "broadcast":
        # Рассылка
        user_state.set_state(user_id, "admin_broadcast")
        await callback.message.edit_text(
            "📢 <b>Рассылка сообщения</b>\n\n"
            "Введите сообщение для рассылки всем пользователям:\n\n"
            "<i>Сообщение будет отправлено всем, кто использовал бота</i>",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "treasury":
        # Казна
        treasury = db.get_treasury()
        user_state.set_state(user_id, "admin_treasury")
        await callback.message.edit_text(
            f"🏦 <b>Управление казной</b>\n\n"
            f"Текущая казна: {treasury} Pulse\n\n"
            "Введите новую сумму казны:",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "manage":
        # Управление (пока просто заглушка)
        await callback.message.edit_text(
            "⚙️ <b>Управление ботом</b>\n\n"
            "Этот раздел в разработке.\n"
            "Здесь будут настройки бота и дополнительные функции.",
            reply_markup=Keyboards.admin_menu(user_id)
        )
    
    await CooldownManager.update_cooldown(callback.message, user_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("game:"))
async def game_handler(callback: CallbackQuery):
    """Обработчик выбора игры"""
    if not await ButtonSecurity.check_owner(callback):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(callback.message, user_id)
    if not allowed:
        await callback.answer(error, show_alert=True)
        return
    
    if not is_logged_in(user_id):
        await callback.answer("Сначала войдите в аккаунт!", show_alert=True)
        await CooldownManager.update_cooldown(callback.message, user_id)
        return
    
    prefix, owner_id, params = ButtonSecurity.parse_callback_data(callback.data)
    game_type = params.get("type")
    
    # Проверяем баланс
    session = get_user_session(user_id)
    game_data = db.get_game_data(session['account_id'])
    
    if game_data['balance'] < MIN_BET:
        await callback.answer(
            f"Недостаточно Pulse Coins. Нужно {MIN_BET}, а у тебя {game_data['balance']}.", 
            show_alert=True
        )
        await CooldownManager.update_cooldown(callback.message, user_id)
        return
    
    # Показываем сообщение об игре
    game_names = {"impulse": "Импульс", "three_signals": "Три сигнала", "tactical": "Тактическое решение"}
    
    await callback.message.edit_text(
        f"🎮 <b>{game_names[game_type]}</b>\n\n"
        f"💰 Ставка: {MIN_BET} Pulse Coins\n"
        "⏳ Игра начинается...",
        reply_markup=None
    )
    
    await CooldownManager.update_cooldown(callback.message, user_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_vip:"))
async def buy_vip_handler(callback: CallbackQuery):
    """Обработчик покупки VIP"""
    if not await ButtonSecurity.check_owner(callback):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(callback.message, user_id)
    if not allowed:
        await callback.answer(error, show_alert=True)
        return
    
    if not is_logged_in(user_id):
        await callback.answer("Сначала войдите в аккаунт!", show_alert=True)
        await CooldownManager.update_cooldown(callback.message, user_id)
        return
    
    prefix, owner_id, params = ButtonSecurity.parse_callback_data(callback.data)
    days = int(params.get("days"))
    
    price = VIP_PACKAGES[days]
    session = get_user_session(user_id)
    game_data = db.get_game_data(session['account_id'])
    
    # Проверяем баланс
    if game_data['balance'] < price:
        await callback.answer(
            f"Недостаточно Pulse Coins. Нужно {price}, а у тебя {game_data['balance']}.", 
            show_alert=True
        )
        await CooldownManager.update_cooldown(callback.message, user_id)
        return
    
    # Покупаем VIP (здесь должна быть логика покупки)
    months = days // 30
    
    await callback.message.edit_text(
        f"🎉 <b>Поздравляем с покупкой VIP!</b>\n\n"
        f"⭐ Теперь у тебя VIP статус на {months} месяцев\n"
        f"💎 Все кулдауны уменьшены в 1.5 раза\n"
        f"💰 Списано: {price} Pulse Coins\n"
        f"💳 Баланс: {game_data['balance'] - price} Pulse",
        reply_markup=Keyboards.main_menu(user_id, callback.message.chat.type in ["group", "supergroup"])
    )
    
    await CooldownManager.update_cooldown(callback.message, user_id)
    await callback.answer()

# ========== ФУНКЦИИ БОТА ==========
async def work_command(message: Message):
    """Обработчик работы"""
    user_id = message.from_user.id
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(message, user_id)
    if not allowed:
        await message.answer(error)
        return
    
    if not is_logged_in(user_id):
        await message.answer("Сначала войдите в аккаунт!")
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    session = get_user_session(user_id)
    game_data = db.get_game_data(session['account_id'])
    
    # Выполняем работу
    reward = random.randint(20, 100)
    db.update_balance(session['account_id'], reward, "work")
    
    await message.answer(
        f"💼 <b>Работа выполнена!</b>\n\n"
        f"Ты заработал: {reward} Pulse Coins\n"
        f"Баланс: {game_data['balance'] + reward} Pulse",
        reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"])
    )
    
    await CooldownManager.update_cooldown(message, user_id)

async def bonus_command(message: Message):
    """Обработчик бонуса"""
    user_id = message.from_user.id
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(message, user_id)
    if not allowed:
        await message.answer(error)
        return
    
    if not is_logged_in(user_id):
        await message.answer("Сначала войдите в аккаунт!")
        await CooldownManager.update_cooldown(message, user_id)
        return
    
    session = get_user_session(user_id)
    game_data = db.get_game_data(session['account_id'])
    
    # Выдаем бонус
    db.update_balance(session['account_id'], BONUS_AMOUNT, "bonus")
    
    await message.answer(
        f"🎁 <b>Ежедневный бонус!</b>\n\n"
        f"Ты получил: {BONUS_AMOUNT} Pulse Coins\n"
        f"Баланс: {game_data['balance'] + BONUS_AMOUNT} Pulse",
        reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"])
    )
    
    await CooldownManager.update_cooldown(message, user_id)

async def show_profile(message: Message, user_id: int = None):
    """Показывает профиль пользователя"""
    if not user_id:
        user_id = message.from_user.id
    
    # Проверяем кулдаун
    allowed, error = await CooldownManager.check_cooldown(message, user_id)
    if not allowed:
        await message.answer(error)
        return
    
    if not is_logged_in(user_id):
        profile_text = "👤 <b>Профиль</b>\n\nВы не авторизованы в аккаунте.\nИспользуйте команду /login чтобы войти."
    else:
        session = get_user_session(user_id)
        account_id = session['account_id']
        game_data = db.get_game_data(account_id)
        account = db.get_account_by_id(account_id)
        
        # Статус VIP
        is_vip = db.check_vip(account_id)
        vip_status = "✅ VIP" if is_vip else "❌ Обычный"
        
        # Формируем текст профиля
        profile_text = (
            f"👤 <b>Профиль аккаунта</b>\n\n"
            f"📛 Логин: {account['username']}\n"
            f"🔗 Сессия: #{session['session_id']}\n"
            f"⭐ Статус: {vip_status}\n"
            f"💰 Баланс: {game_data['balance']} Pulse Coins\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"🎮 Игр сыграно: {game_data['games_played']}\n"
            f"💼 Работ выполнено: {game_data['work_count']}\n"
            f"💸 Потрачено: {game_data['total_spent']} Pulse"
        )
    
    await message.answer(profile_text, reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"]))
    await CooldownManager.update_cooldown(message, user_id)

# ========== ГРУППОВЫЕ КОМАНДЫ ==========
@dp.message(F.chat.type.in_(["group", "supergroup"]))
async def group_handler(message: Message):
    """Обработчик сообщений в группах"""
    if message.text and message.text.startswith("/"):
        command = message.text.split()[0].lower()
        
        if command in ["/start", "/startpuls", "/registerpuls", "/login", "/logout", "/удалсписок"]:
            user_id = message.from_user.id
            
            # Проверяем кулдаун
            allowed, error = await CooldownManager.check_cooldown(message, user_id)
            if not allowed:
                await message.answer(error, reply_to_message_id=message.message_id)
                return
            
            # Для всех команд в группах проверяем регистрацию (кроме /start и /удалсписок)
            if command not in ["/start", "/startpuls", "/удалсписок"] and not is_logged_in(user_id):
                await message.answer(
                    "❌ Вы должны быть зарегистрированы в боте и войти в аккаунт для использования команд!\n\n"
                    "Перейдите в личные сообщения с ботом @PulsOfficialManager_bot чтобы зарегистрироваться.",
                    reply_to_message_id=message.message_id
                )
                await CooldownManager.update_cooldown(message, user_id)
                return
            
            if command in ["/registerpuls", "/login"]:
                await message.answer(
                    "Эта функция доступна только в личных сообщениях. "
                    "Я отправил тебе инструкцию в ЛС.",
                    reply_to_message_id=message.message_id
                )
                
                try:
                    if command == "/registerpuls":
                        await bot.send_message(
                            user_id,
                            "Для регистрации аккаунта нажмите кнопку '📝 Регистрация' в главном меню."
                        )
                    else:
                        await bot.send_message(
                            user_id,
                            "Для входа в аккаунт нажмите кнопку '🔐 Войти в аккаунт' в главном меню."
                        )
                except:
                    pass
            
            elif command in ["/start", "/startpuls"]:
                in_group = message.chat.type in ["group", "supergroup"]
                await message.answer(
                    "🎮 <b>Pulse Bot - Игровой бот</b>\n\n"
                    "<b>Основные команды:</b>\n"
                    "🚀 /start или /startpuls - Начать работу с ботом\n"
                    "📝 /registerpuls - Регистрация (только в ЛС)\n"
                    "🔐 /login - Вход в аккаунт (только в ЛС)\n"
                    "🚪 /logout - Выход из аккаунта\n\n"
                    "<b>Команды удаления сообщений:</b>\n"
                    "🗑️ -соо - Удалить сообщение (в ответ, требуется регистрация)\n"
                    "➕ +удал соо - Выдать права на удаление (только создателю)\n"
                    "➖ -удал соо - Отозвать права на удаление (только создателю)\n"
                    "📋 /удалсписок - Список прав на удаление (только создателю)\n\n"
                    "Для полного функционала перейдите в личные сообщения с ботом.",
                    reply_to_message_id=message.message_id,
                    reply_markup=Keyboards.main_menu(user_id, in_group)
                )
            
            elif command == "/logout":
                if not is_logged_in(user_id):
                    await message.answer("Вы не авторизованы в аккаунте.")
                else:
                    session = get_user_session(user_id)
                    if session:
                        db.logout_session(session['session_id'])
                    
                    await message.answer("✅ Вы успешно вышли из аккаунта!", reply_to_message_id=message.message_id)
            
            await CooldownManager.update_cooldown(message, user_id)

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция"""
    logger.info("Запуск бота Pulse Bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
