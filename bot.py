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
COOLDOWN_PM = 3
COOLDOWN_GROUP = 5
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
MAX_ACCOUNTS_PER_USER = 3  # Максимум аккаунтов на одного пользователя
ACCOUNT_CREATION_COOLDOWN = 3 * 24 * 3600  # 3 дня кулдаун на создание нового аккаунта
REGISTRATION_TIMEOUT = 300  # 5 минут на регистрацию
LOGIN_TIMEOUT = 400  # 6 минут 40 секунд на вход

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ========== БАЗА ДАННЫХ ==========
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
        
        self.conn.commit()
    
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
            return True, "Таймер не активен"
        
        expires_at = datetime.fromisoformat(result[0])
        if datetime.now() > expires_at:
            # Таймер истек
            self.cursor.execute(
                "DELETE FROM user_timers WHERE user_id = ? AND timer_type = ?",
                (user_id, timer_type)
            )
            self.conn.commit()
            return False, "Время вышло! Процесс отменен."
        
        # Возвращаем оставшееся время
        remaining = (expires_at - datetime.now()).total_seconds()
        return True, f"Осталось времени: {int(remaining)} секунд"
    
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
    
    def get_delete_permission_granted_by(self, chat_id: int, user_id: int) -> Optional[int]:
        """Получает, кто выдал права"""
        self.cursor.execute(
            "SELECT granted_by FROM delete_permissions WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        )
        result = self.cursor.fetchone()
        return result[0] if result else None
    
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
            
            # Создаем игровые данные для аккаунта
            self.cursor.execute(
                "INSERT INTO game_data (account_id) VALUES (?)",
                (account_id,)
            )
            
            # Создаем настройки по умолчанию
            self.cursor.execute(
                "INSERT INTO account_settings (account_id) VALUES (?)",
                (account_id,)
            )
            
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
    
    def get_account_settings(self, account_id: int) -> Dict:
        """Получает настройки аккаунта"""
        self.cursor.execute("SELECT * FROM account_settings WHERE account_id = ?", (account_id,))
        columns = [desc[0] for desc in self.cursor.description]
        row = self.cursor.fetchone()
        if row:
            return dict(zip(columns, row))
        else:
            # Создаем настройки по умолчанию
            self.cursor.execute(
                "INSERT INTO account_settings (account_id) VALUES (?)",
                (account_id,)
            )
            self.conn.commit()
            return {"account_id": account_id, "can_play_games": True, "can_work": True, 
                    "can_use_shop": True, "can_claim_bonus": True, "can_use_vip": True}
    
    def update_account_setting(self, account_id: int, setting_name: str, value: bool):
        """Обновляет настройку аккаунта"""
        self.cursor.execute(
            f"UPDATE account_settings SET {setting_name} = ? WHERE account_id = ?",
            (value, account_id)
        )
        self.conn.commit()
    
    def username_exists(self, username: str) -> bool:
        """Проверяет, существует ли username"""
        self.cursor.execute("SELECT 1 FROM accounts WHERE username = ?", (username,))
        return self.cursor.fetchone() is not None
    
    def get_user_accounts_count(self, user_id: int) -> int:
        """Сколько аккаунтов создал пользователь"""
        self.cursor.execute(
            "SELECT COUNT(*) FROM accounts WHERE owner_user_id = ?",
            (user_id,)
        )
        return self.cursor.fetchone()[0]
    
    def get_user_last_account_creation(self, user_id: int) -> Optional[datetime]:
        """Когда пользователь последний раз создавал аккаунт"""
        self.cursor.execute(
            "SELECT MAX(last_account_creation) FROM accounts WHERE owner_user_id = ?",
            (user_id,)
        )
        result = self.cursor.fetchone()[0]
        return datetime.fromisoformat(result) if result else None
    
    def can_user_create_account(self, user_id: int) -> Tuple[bool, str]:
        """Может ли пользователь создать новый аккаунт"""
        # Проверяем блокировку
        self.cursor.execute(
            "SELECT is_blocked, blocked_until FROM user_blocks WHERE user_id = ?",
            (user_id,)
        )
        block_data = self.cursor.fetchone()
        if block_data and block_data[0]:
            blocked_until = datetime.fromisoformat(block_data[1]) if block_data[1] else None
            if blocked_until and blocked_until > datetime.now():
                return False, f"Вы заблокированы от создания аккаунтов до {blocked_until.strftime('%d.%m.%Y %H:%M')}"
            elif blocked_until is None:  # Перманентная блокировка
                return False, "Вы заблокированы от создания аккаунтов навсегда"
        
        # Проверяем лимит аккаунтов
        accounts_count = self.get_user_accounts_count(user_id)
        if accounts_count >= MAX_ACCOUNTS_PER_USER:
            return False, f"Вы можете создать максимум {MAX_ACCOUNTS_PER_USER} аккаунта"
        
        # Проверяем кулдаун
        last_creation = self.get_user_last_account_creation(user_id)
        if last_creation:
            next_creation = last_creation + timedelta(seconds=ACCOUNT_CREATION_COOLDOWN)
            if next_creation > datetime.now():
                remaining = (next_creation - datetime.now()).total_seconds()
                hours = int(remaining // 3600)
                minutes = int((remaining % 3600) // 60)
                return False, f"Вы можете создать следующий аккаунт через {hours}ч {minutes}м"
        
        return True, "OK"
    
    # === Управление блокировками ===
    def block_user_accounts(self, user_id: int, reason: str = None, until: datetime = None):
        """Блокирует пользователю создание аккаунтов"""
        self.cursor.execute(
            "INSERT OR REPLACE INTO user_blocks (user_id, is_blocked, block_reason, blocked_until) VALUES (?, ?, ?, ?)",
            (user_id, True, reason, until.isoformat() if until else None)
        )
        self.conn.commit()
    
    def unblock_user_accounts(self, user_id: int):
        """Разблокирует пользователю создание аккаунтов"""
        self.cursor.execute(
            "UPDATE user_blocks SET is_blocked = FALSE WHERE user_id = ?",
            (user_id,)
        )
        self.conn.commit()
    
    def block_account(self, account_id: int, reason: str = None, until: datetime = None):
        """Блокирует аккаунт"""
        self.cursor.execute(
            "UPDATE accounts SET is_blocked = TRUE, block_reason = ?, blocked_until = ? WHERE account_id = ?",
            (reason, until.isoformat() if until else None, account_id)
        )
        self.conn.commit()
    
    def unblock_account(self, account_id: int):
        """Разблокирует аккаунт"""
        self.cursor.execute(
            "UPDATE accounts SET is_blocked = FALSE, block_reason = NULL, blocked_until = NULL WHERE account_id = ?",
            (account_id,)
        )
        self.conn.commit()
    
    def is_account_blocked(self, account_id: int) -> bool:
        """Проверяет, заблокирован ли аккаунт"""
        account = self.get_account_by_id(account_id)
        if not account or not account['is_blocked']:
            return False
        
        if account['blocked_until']:
            blocked_until = datetime.fromisoformat(account['blocked_until'])
            if blocked_until < datetime.now():
                # Срок блокировки истек
                self.unblock_account(account_id)
                return False
        return True
    
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
    
    def get_active_session(self, user_id: int) -> Dict:
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
        return dict(zip(columns, row)) if row else None
    
    def get_account_sessions(self, account_id: int, active_only: bool = False) -> List[Dict]:
        """Получает все сессии аккаунта"""
        query = """
            SELECT s.*, a.username FROM sessions s 
            JOIN accounts a ON s.account_id = a.account_id 
            WHERE s.account_id = ?
        """
        if active_only:
            query += " AND s.logout_time IS NULL"
        query += " ORDER BY s.login_time DESC"
        
        self.cursor.execute(query, (account_id,))
        columns = [desc[0] for desc in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
    
    def logout_session(self, session_id: int):
        """Завершает сессию"""
        self.cursor.execute(
            "UPDATE sessions SET logout_time = CURRENT_TIMESTAMP WHERE session_id = ?",
            (session_id,)
        )
        self.conn.commit()
    
    def logout_user_from_account(self, user_id: int, account_id: int):
        """Выходит пользователя из аккаунта"""
        self.cursor.execute(
            "UPDATE sessions SET logout_time = CURRENT_TIMESTAMP WHERE user_id = ? AND account_id = ? AND logout_time IS NULL",
            (user_id, account_id)
        )
        self.conn.commit()
    
    def logout_all_from_account(self, account_id: int):
        """Выходит всех пользователей из аккаунта"""
        self.cursor.execute(
            "UPDATE sessions SET logout_time = CURRENT_TIMESTAMP WHERE account_id = ? AND logout_time IS NULL",
            (account_id,)
        )
        self.conn.commit()
    
    def get_all_sessions(self) -> List[Dict]:
        """Получает все сессии для админ-панели"""
        self.cursor.execute(
            "SELECT s.*, a.username, a.recovery_code FROM sessions s "
            "JOIN accounts a ON s.account_id = a.account_id "
            "ORDER BY s.login_time DESC"
        )
        columns = [desc[0] for desc in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
    
    # === Игровые данные ===
    def get_game_data(self, account_id: int) -> Dict:
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
    
    def update_last_action(self, account_id: int):
        """Обновляет время последнего действия"""
        self.cursor.execute(
            "UPDATE game_data SET last_action = CURRENT_TIMESTAMP WHERE account_id = ?",
            (account_id,)
        )
        self.conn.commit()
    
    def set_vip(self, account_id: int, days: int):
        """Устанавливает VIP"""
        game_data = self.get_game_data(account_id)
        current_time = datetime.now()
        
        if game_data['vip_until'] and datetime.fromisoformat(game_data['vip_until']) > current_time:
            vip_until = datetime.fromisoformat(game_data['vip_until']) + timedelta(days=days)
        else:
            vip_until = current_time + timedelta(days=days)
        
        self.cursor.execute(
            "UPDATE game_data SET is_vip = TRUE, vip_until = ? WHERE account_id = ?",
            (vip_until.isoformat(), account_id)
        )
        self.conn.commit()
    
    def check_vip(self, account_id: int) -> bool:
        """Проверяет VIP статус"""
        game_data = db.get_game_data(account_id)
        if not game_data['is_vip']:
            return False
        
        if game_data['vip_until']:
            vip_until = datetime.fromisoformat(game_data['vip_until'])
            if vip_until < datetime.now():
                self.cursor.execute(
                    "UPDATE game_data SET is_vip = FALSE WHERE account_id = ?",
                    (account_id,)
                )
                self.conn.commit()
                return False
        return True
    
    # === Админ-функции ===
    def get_all_accounts(self) -> List[Dict]:
        """Получает все аккаунты для админ-панели"""
        self.cursor.execute(
            "SELECT a.*, g.balance, g.is_vip, g.vip_until FROM accounts a "
            "LEFT JOIN game_data g ON a.account_id = g.account_id "
            "ORDER BY a.created_at DESC"
        )
        columns = [desc[0] for desc in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
    
    def get_treasury(self) -> int:
        """Получает сумму казны"""
        self.cursor.execute("SELECT SUM(amount) FROM transactions")
        result = self.cursor.fetchone()[0]
        return result if result else 0
    
    def reset_treasury(self):
        """Сбрасывает казну"""
        self.cursor.execute("DELETE FROM transactions")
        self.conn.commit()
    
    def get_all_account_ids(self) -> List[int]:
        """Получает все ID аккаунтов"""
        self.cursor.execute("SELECT account_id FROM accounts")
        return [row[0] for row in self.cursor.fetchall()]
    
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
    
    def delete_admin_session(self, user_id: int):
        """Удаляет админскую сессию"""
        self.cursor.execute("DELETE FROM admin_sessions WHERE user_id = ?", (user_id,))
        self.conn.commit()

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
    if not session:
        return False
    
    # Проверяем, не заблокирован ли аккаунт
    if db.is_account_blocked(session['account_id']):
        # Выходим из заблокированного аккаунта
        db.logout_session(session['session_id'])
        return False
    
    return True

def format_time(seconds: float) -> str:
    """Форматирует время в ЧЧ:ММ:СС"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)
    return f"{hours}ч {minutes}м {seconds}с"

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
        # Проверяем таймаут состояния
        if state_data["state"] == "waiting_for_username":
            timeout = REGISTRATION_TIMEOUT
        elif state_data["state"] == "waiting_for_login_username":
            timeout = LOGIN_TIMEOUT
        else:
            timeout = 300  # 5 минут по умолчанию
        
        elapsed = (datetime.now() - state_data["timestamp"]).total_seconds()
        if elapsed > timeout:
            self.clear_state(user_id)
            return None
        
        return state_data
    
    def clear_state(self, user_id: int):
        """Очищает состояние пользователя"""
        if user_id in self.states:
            # Очищаем таймер, если есть
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

class CooldownManager:
    @staticmethod
    async def check_cooldown(message: Message, user_id: int, is_admin_in_group: bool = False) -> Tuple[bool, Optional[str]]:
        """Проверяет кулдаун перед выполнением действия"""
        chat_type = message.chat.type
        
        # Админы Telegram в группах без КД
        if chat_type in ["group", "supergroup"] and is_admin_in_group:
            return True, None
        
        session = get_user_session(user_id)
        if not session:
            return True, None
        
        game_data = db.get_game_data(session['account_id'])
        if not game_data:
            return True, None
        
        last_action = datetime.fromisoformat(game_data['last_action'])
        now = datetime.now()
        
        # Определяем КД в зависимости от типа чата
        cooldown_seconds = COOLDOWN_GROUP if chat_type in ["group", "supergroup"] else COOLDOWN_PM
        if db.check_vip(session['account_id']):
            cooldown_seconds = int(cooldown_seconds / VIP_MULTIPLIER)
        
        elapsed = (now - last_action).total_seconds()
        
        if elapsed < cooldown_seconds:
            remaining = cooldown_seconds - elapsed
            return False, f"Подожди перед следующим действием\nОсталось: {format_time(remaining)}"
        
        return True, None

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
    async def check_owner(callback: CallbackQuery) -> bool:
        """Проверяет, принадлежит ли кнопка пользователю"""
        _, owner_id, _ = ButtonSecurity.parse_callback_data(callback.data)
        return callback.from_user.id == owner_id

# ========== ИГРЫ ==========
class Games:
    """Класс для управления играми"""
    
    @staticmethod
    async def check_game_cooldown(account_id: int, game_number: int) -> Tuple[bool, Optional[str]]:
        """Проверяет кулдаун игры"""
        game_data = db.get_game_data(account_id)
        game_count_field = f"game{game_number}_count"
        cooldown_field = f"game{game_number}_cooldown"
        
        # Проверяем лимит игр
        if game_data[game_count_field] >= GAME_LIMIT:
            cooldown_time = datetime.fromisoformat(game_data[cooldown_field]) if game_data[cooldown_field] else datetime.now()
            now = datetime.now()
            
            if cooldown_time > now:
                remaining = (cooldown_time - now).total_seconds()
                if db.check_vip(account_id):
                    remaining = int(remaining / VIP_MULTIPLIER)
                return False, f"Лимит игр исчерпан. Подожди: {format_time(remaining)}"
            else:
                # Сбрасываем счетчик
                db.cursor.execute(f"UPDATE game_data SET {game_count_field} = 0 WHERE account_id = ?", (account_id,))
                db.conn.commit()
        
        return True, None
    
    @staticmethod
    async def impulse_game(account_id: int, bet: int) -> Dict[str, Any]:
        """Игра 'Импульс'"""
        await asyncio.sleep(random.uniform(2, 4))
        
        win_chance = 0.6
        is_win = random.random() < win_chance
        
        if is_win:
            win_amount = int(bet * 1.6)
            db.update_balance(account_id, win_amount, "game_win")
            result = {
                "win": True,
                "amount": win_amount,
                "message": "🎮 <b>Импульс</b>\nТы успешно поймал момент стабильности! Отличная реакция!"
            }
        else:
            result = {
                "win": False,
                "amount": -bet,
                "message": "🎮 <b>Импульс</b>\nУвы, импульс был нестабилен. Попробуй ещё раз!"
            }
        
        db.cursor.execute("UPDATE game_data SET game1_count = game1_count + 1 WHERE account_id = ?", (account_id,))
        game_data = db.get_game_data(account_id)
        if game_data['game1_count'] >= GAME_LIMIT:
            cooldown_time = datetime.now() + timedelta(seconds=GAME_LIMIT_COOLDOWN)
            db.cursor.execute(
                "UPDATE game_data SET game1_cooldown = ? WHERE account_id = ?",
                (cooldown_time.isoformat(), account_id)
            )
        db.conn.commit()
        
        return result
    
    @staticmethod
    async def three_signals_game(account_id: int, bet: int) -> Dict[str, Any]:
        """Игра 'Три сигнала'"""
        await asyncio.sleep(random.uniform(1, 3))
        
        win_chance = 0.6
        is_win = random.random() < win_chance
        
        if is_win:
            win_amount = int(bet * 1.5)
            db.update_balance(account_id, win_amount, "game_win")
            result = {
                "win": True,
                "amount": win_amount,
                "message": "🎮 <b>Три сигнала</b>\nТы верно определил настоящий сигнал! Отличный анализ!"
            }
        else:
            result = {
                "win": False,
                "amount": -bet,
                "message": "🎮 <b>Три сигнала</b>\nЭто был ложный сигнал. Будь внимательнее в следующий раз!"
            }
        
        db.cursor.execute("UPDATE game_data SET game2_count = game2_count + 1 WHERE account_id = ?", (account_id,))
        game_data = db.get_game_data(account_id)
        if game_data['game2_count'] >= GAME_LIMIT:
            cooldown_time = datetime.now() + timedelta(seconds=GAME_LIMIT_COOLDOWN)
            db.cursor.execute(
                "UPDATE game_data SET game2_cooldown = ? WHERE account_id = ?",
                (cooldown_time.isoformat(), account_id)
            )
        db.conn.commit()
        
        return result
    
    @staticmethod
    async def tactical_decision_game(account_id: int, bet: int) -> Dict[str, Any]:
        """Игра 'Тактическое решение'"""
        await asyncio.sleep(random.uniform(1, 3))
        
        win_chance = 0.6
        is_win = random.random() < win_chance
        
        if is_win:
            win_amount = int(bet * 1.7)
            db.update_balance(account_id, win_amount, "game_win")
            result = {
                "win": True,
                "amount": win_amount,
                "message": "🎮 <b>Тактическое решение</b>\nТвой ход оказался верным! Противник повержен!"
            }
        else:
            result = {
                "win": False,
                "amount": -bet,
                "message": "🎮 <b>Тактическое решение</b>\nПротивник переиграл тебя. Подумай над тактикой!"
            }
        
        db.cursor.execute("UPDATE game_data SET game3_count = game3_count + 1 WHERE account_id = ?", (account_id,))
        game_data = db.get_game_data(account_id)
        if game_data['game3_count'] >= GAME_LIMIT:
            cooldown_time = datetime.now() + timedelta(seconds=GAME_LIMIT_COOLDOWN)
            db.cursor.execute(
                "UPDATE game_data SET game3_cooldown = ? WHERE account_id = ?",
                (cooldown_time.isoformat(), account_id)
            )
        db.conn.commit()
        
        return result

# ========== КЛАВИАТУРЫ ==========
class Keyboards:
    """Класс для создания клавиатур"""
    
    @staticmethod
    def main_menu(user_id: int = None) -> InlineKeyboardMarkup:
        """Главное меню"""
        builder = InlineKeyboardBuilder()
        
        if not is_logged_in(user_id):
            builder.row(
                InlineKeyboardButton(text="🔐 Войти в аккаунт", callback_data="auth:login"),
                InlineKeyboardButton(text="📝 Регистрация", callback_data="auth:register")
            )
        else:
            session = get_user_session(user_id)
            account_settings = db.get_account_settings(session['account_id'])
            
            if account_settings['can_play_games']:
                builder.row(
                    InlineKeyboardButton(text="🎮 Игры", callback_data="menu:games"),
                )
            if account_settings['can_work']:
                builder.row(
                    InlineKeyboardButton(text="💼 Работа", callback_data="menu:work"),
                )
            if account_settings['can_use_shop']:
                builder.row(
                    InlineKeyboardButton(text="🏪 Магазин", callback_data="menu:shop"),
                )
            
            builder.row(
                InlineKeyboardButton(text="👤 Профиль", callback_data="menu:profile"),
                InlineKeyboardButton(text="🎁 Бонус", callback_data="menu:bonus")
            )
            
            builder.row(
                InlineKeyboardButton(text="🚪 Выйти", callback_data="auth:logout")
            )
        
        # Кнопка админ-панели только для админа
        if user_id in ADMIN_IDS:
            builder.row(
                InlineKeyboardButton(text="🛠 Админ панель", callback_data="menu:admin")
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
            InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main")
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
            InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main")
        )
        return builder.as_markup()
    
    @staticmethod
    def admin_menu() -> InlineKeyboardMarkup:
        """Меню админ-панели"""
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats"),
            InlineKeyboardButton(text="👥 Все аккаунты", callback_data="admin:accounts")
        )
        builder.row(
            InlineKeyboardButton(text="📋 Все сессии", callback_data="admin:sessions"),
            InlineKeyboardButton(text="🔍 Найти аккаунт", callback_data="admin:search")
        )
        builder.row(
            InlineKeyboardButton(text="💰 Управление балансами", callback_data="admin:balance"),
            InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")
        )
        builder.row(
            InlineKeyboardButton(text="🏦 Казна", callback_data="admin:treasury"),
            InlineKeyboardButton(text="⚙️ Управление", callback_data="admin:manage")
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

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@dp.message(Command("start", "startpuls"))
async def cmd_start(message: Message):
    """Обработчик команд /start и /startpuls"""
    user_id = message.from_user.id
    
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
    
    await message.answer(welcome_text, reply_markup=Keyboards.main_menu(user_id))

@dp.message(Command("registerpuls"))
async def cmd_register(message: Message):
    """Команда регистрации"""
    user_id = message.from_user.id
    
    if message.chat.type != "private":
        await message.answer(
            "Регистрация доступна только в личных сообщениях. "
            "Я отправил тебе инструкцию в ЛС.",
            reply_to_message_id=message.message_id
        )
        
        # Отправляем сообщение в ЛС
        try:
            await bot.send_message(
                user_id,
                "Для регистрации аккаунта нажмите кнопку '📝 Регистрация' в главном меню."
            )
        except:
            pass
        return
    
    if is_logged_in(user_id):
        await message.answer("Вы уже авторизованы в аккаунте. Сначала выйдите.")
        return
    
    # Проверяем, может ли пользователь создать аккаунт
    can_create, reason = db.can_user_create_account(user_id)
    if not can_create:
        await message.answer(f"❌ {reason}")
        return
    
    # Начинаем процесс регистрации
    user_state.set_state(user_id, "waiting_for_username")
    db.start_timer(user_id, "registration", REGISTRATION_TIMEOUT)
    
    await message.answer(
        "📝 <b>Регистрация нового аккаунта</b>\n\n"
        "Придумайте логин (имя пользователя):\n"
        "• Минимум 3 символа\n"
        "• Только буквы, цифры и _\n"
        "• Уникальный для системы\n\n"
        f"⏰ У вас есть {REGISTRATION_TIMEOUT // 60} минут чтобы завершить регистрацию",
        reply_markup=Keyboards.cancel_keyboard(user_id)
    )

@dp.message(Command("login"))
async def cmd_login(message: Message):
    """Команда входа в аккаунт"""
    user_id = message.from_user.id
    
    if message.chat.type != "private":
        await message.answer(
            "Вход в аккаунт доступен только в личных сообщениях.",
            reply_to_message_id=message.message_id
        )
        return
    
    if is_logged_in(user_id):
        await message.answer("Вы уже авторизованы в аккаунте.")
        return
    
    user_state.set_state(user_id, "waiting_for_login_username")
    db.start_timer(user_id, "login", LOGIN_TIMEOUT)
    
    await message.answer(
        "🔐 <b>Вход в аккаунт</b>\n\n"
        "Введите ваш логин:\n\n"
        f"⏰ У вас есть {LOGIN_TIMEOUT // 60} минут чтобы завершить вход",
        reply_markup=Keyboards.cancel_keyboard(user_id)
    )

@dp.message(Command("logout"))
async def cmd_logout(message: Message):
    """Команда выхода из аккаунта"""
    user_id = message.from_user.id
    
    if not is_logged_in(user_id):
        await message.answer("Вы не авторизованы в аккаунте.")
        return
    
    session = get_user_session(user_id)
    if session:
        db.logout_session(session['session_id'])
    
    await message.answer(
        "✅ <b>Вы успешно вышли из аккаунта!</b>\n\n"
        "Теперь вы можете войти в другой аккаунт или зарегистрировать новый.",
        reply_markup=Keyboards.main_menu(user_id)
    )

# ========== КОМАНДЫ УДАЛЕНИЯ СООБЩЕНИЙ В ГРУППАХ ==========
@dp.message(F.text.startswith("-соо"))
async def delete_message_command(message: Message):
    """Команда -соо для удаления сообщений (только в ответ)"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Проверяем, что команда используется в группе
    if message.chat.type not in ["group", "supergroup"]:
        return
    
    # Проверяем, что это ответ на сообщение
    if not message.reply_to_message:
        await message.answer("❌ Команда -соо работает только в ответ на сообщение!", reply_to_message_id=message.message_id)
        try:
            await message.delete()
        except:
            pass
        return
    
    # Проверяем, зарегистрирован ли пользователь
    if not is_logged_in(user_id):
        await message.answer("❌ Вы должны быть зарегистрированы в боте и войти в аккаунт для использования этой команды!", reply_to_message_id=message.message_id)
        try:
            await message.delete()
        except:
            pass
        return
    
    # Проверяем права пользователя
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

@dp.message(F.text.startswith("+удал соо"))
async def grant_delete_permission_command(message: Message):
    """Команда +удал соо для выдачи прав на удаление"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Проверяем, что команда используется в группе
    if message.chat.type not in ["group", "supergroup"]:
        return
    
    # Проверяем, что отправитель - создатель чата
    chat_member = await bot.get_chat_member(chat_id, user_id)
    if chat_member.status != "creator":
        await message.answer("❌ Только создатель чата может выдавать права на удаление!", reply_to_message_id=message.message_id)
        try:
            await message.delete()
        except:
            pass
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

@dp.message(F.text.startswith("-удал соо"))
async def revoke_delete_permission_command(message: Message):
    """Команда -удал соо для отзыва прав на удаление"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Проверяем, что команда используется в группе
    if message.chat.type not in ["group", "supergroup"]:
        return
    
    # Проверяем, что отправитель - создатель чата
    chat_member = await bot.get_chat_member(chat_id, user_id)
    if chat_member.status != "creator":
        await message.answer("❌ Только создатель чата может отзывать права на удаление!", reply_to_message_id=message.message_id)
        try:
            await message.delete()
        except:
            pass
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
            "❌ У этого пользователя нет прав на удаление сообщений!\n\n"
            "Чтобы выдать права, используйте команду:\n"
            "+удал соо (ответом на сообщение пользователя или указав его ID)",
            reply_to_message_id=message.message_id
        )
    
    try:
        await message.delete()
    except:
        pass

@dp.message(Command("удалсписок"))
async def list_delete_permissions_command(message: Message):
    """Команда для просмотра списка пользователей с правами на удаление"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Проверяем, что команда используется в группе
    if message.chat.type not in ["group", "supergroup"]:
        return
    
    # Проверяем, что отправитель - создатель чата
    chat_member = await bot.get_chat_member(chat_id, user_id)
    if chat_member.status != "creator":
        await message.answer("❌ Только создатель чата может просматривать список прав!", reply_to_message_id=message.message_id)
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
        return
    
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

# ========== ОБРАБОТКА ВВОДА ДАННЫХ ==========
@dp.message(F.text)
async def handle_text_input(message: Message):
    """Обработчик текстового ввода"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Пропускаем команды удаления сообщений
    if text.startswith(("-соо", "+удал соо", "-удал соо")):
        return
    
    # Получаем текущее состояние
    state_data = user_state.get_state(user_id)
    
    # Если нет состояния, проверяем не админ ли это
    if not state_data:
        if user_id in ADMIN_IDS:
            # Проверяем админские команды
            if text.startswith("/"):
                return
            
            # Проверяем, не находится ли админ в состоянии поиска
            admin_state = user_state.get_state(user_id)
            if admin_state and admin_state["state"] == "admin_search":
                await handle_admin_search(message)
                return
        return
    
    state = state_data["state"]
    data = state_data["data"]
    
    # Проверяем таймер
    if state in ["waiting_for_username", "waiting_for_password", "waiting_for_recovery"]:
        is_valid, timer_msg = db.check_timer(user_id, "registration")
        if not is_valid:
            await message.answer("⏰ Время регистрации вышло! Процесс отменен.")
            user_state.clear_state(user_id)
            await message.answer("Главное меню:", reply_markup=Keyboards.main_menu(user_id))
            return
    elif state in ["waiting_for_login_username", "waiting_for_login_password"]:
        is_valid, timer_msg = db.check_timer(user_id, "login")
        if not is_valid:
            await message.answer("⏰ Время на вход вышло! Процесс отменен.")
            user_state.clear_state(user_id)
            await message.answer("Главное меню:", reply_markup=Keyboards.main_menu(user_id))
            return
    
    # Обработка состояний регистрации
    if state == "waiting_for_username":
        # Проверяем логин
        if len(text) < 3:
            await message.answer("Логин должен содержать минимум 3 символа. Попробуйте еще раз:")
            return
        
        if not re.match(r'^[A-Za-z0-9_]+$', text):
            await message.answer("Логин может содержать только буквы, цифры и символ _. Попробуйте еще раз:")
            return
        
        if db.username_exists(text):
            await message.answer("Этот логин уже занят. Придумайте другой:")
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
    
    elif state == "waiting_for_password":
        # Проверяем пароль
        is_valid, error_msg = validate_password(text)
        if not is_valid:
            await message.answer(f"{error_msg}\n\nПопробуйте еще раз:")
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
    
    elif state == "waiting_for_recovery":
        # Проверяем кодовое слово
        is_valid, error_msg = validate_recovery_code(text)
        if not is_valid:
            await message.answer(f"{error_msg}\n\nПопробуйте еще раз:")
            return
        
        # Завершаем регистрацию
        username = data.get("username")
        password = data.get("password")
        
        if not username or not password:
            await message.answer("Ошибка: данные регистрации потеряны. Начните заново.")
            user_state.clear_state(user_id)
            await message.answer("Главное меню:", reply_markup=Keyboards.main_menu(user_id))
            return
        
        account_id = db.create_account(username, password, text, user_id)
        if not account_id:
            await message.answer("Произошла ошибка при создании аккаунта. Попробуйте еще раз.")
            user_state.clear_state(user_id)
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
            reply_markup=Keyboards.main_menu(user_id)
        )
    
    # Обработка состояний входа
    elif state == "waiting_for_login_username":
        # Сохраняем логин для входа
        data["login_username"] = text
        user_state.update_data(user_id, "login_username", text)
        user_state.set_state(user_id, "waiting_for_login_password", data)
        
        await message.answer("Введите пароль:", reply_markup=Keyboards.cancel_keyboard(user_id))
    
    elif state == "waiting_for_login_password":
        # Пытаемся войти
        username = data.get("login_username")
        password = text
        
        if not username:
            await message.answer("Ошибка: логин не найден. Начните заново.")
            user_state.clear_state(user_id)
            await message.answer("Главное меню:", reply_markup=Keyboards.main_menu(user_id))
            return
        
        account = db.get_account_by_credentials(username, password)
        if not account:
            await message.answer("Неверный логин или пароль. Попробуйте еще раз или зарегистрируйтесь.")
            user_state.clear_state(user_id)
            await message.answer("Главное меню:", reply_markup=Keyboards.main_menu(user_id))
            return
        
        # Проверяем, не заблокирован ли аккаунт
        if db.is_account_blocked(account['account_id']):
            await message.answer("❌ Этот аккаунт заблокирован.")
            user_state.clear_state(user_id)
            await message.answer("Главное меню:", reply_markup=Keyboards.main_menu(user_id))
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
            f"💰 Баланс: {game_data['balance']} Pulse Coins\n"
            f"⭐ Статус: {'✅ VIP' if db.check_vip(account['account_id']) else '❌ Обычный'}\n\n"
            "Добро пожаловать обратно!",
            reply_markup=Keyboards.main_menu(user_id)
        )

async def handle_admin_search(message: Message):
    """Обработка поиска аккаунта админом"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    accounts = db.get_all_accounts()
    found_accounts = []
    
    for account in accounts:
        if text.lower() in account['username'].lower() or str(text) == str(account['account_id']):
            found_accounts.append(account)
    
    if found_accounts:
        result_text = "🔍 <b>Найденные аккаунты:</b>\n\n"
        for acc in found_accounts[:5]:
            is_blocked = db.is_account_blocked(acc['account_id'])
            result_text += (
                f"<b>ID: {acc['account_id']}</b>\n"
                f"👤 Логин: {acc['username']}\n"
                f"💰 Баланс: {acc['balance']} Pulse\n"
                f"🚫 Статус: {'Заблокирован' if is_blocked else 'Активен'}\n\n"
            )
        
        await message.answer(result_text, reply_markup=Keyboards.admin_menu())
    else:
        await message.answer("❌ Аккаунты не найдены.", reply_markup=Keyboards.admin_menu())
    
    user_state.clear_state(user_id)

# ========== ОБРАБОТЧИКИ КНОПОК ==========
@dp.callback_query(F.data.startswith("auth:"))
async def auth_handler(callback: CallbackQuery):
    """Обработчик кнопок авторизации"""
    user_id = callback.from_user.id
    action = callback.data.split(":")[1]
    
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
            return
        
        if is_logged_in(user_id):
            await callback.answer("Вы уже авторизованы!", show_alert=True)
            return
        
        # Проверяем, может ли пользователь создать аккаунт
        can_create, reason = db.can_user_create_account(user_id)
        if not can_create:
            await callback.answer(f"❌ {reason}", show_alert=True)
            return
        
        user_state.set_state(user_id, "waiting_for_username")
        db.start_timer(user_id, "registration", REGISTRATION_TIMEOUT)
        
        await callback.message.edit_text(
            "📝 <b>Регистрация нового аккаунта</b>\n\n"
            "Придумайте логин (имя пользователя):\n"
            "• Минимум 3 символа\n"
            "• Только буквы, цифры и _\n"
            "• Уникальный для системы\n\n"
            f"⏰ У вас есть {REGISTRATION_TIMEOUT // 60} минут чтобы завершить регистрацию",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "login":
        if callback.message.chat.type != "private":
            await callback.answer("Вход только в ЛС!", show_alert=True)
            return
        
        if is_logged_in(user_id):
            await callback.answer("Вы уже авторизованы!", show_alert=True)
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
            return
        
        session = get_user_session(user_id)
        if session:
            db.logout_session(session['session_id'])
        
        await callback.message.edit_text(
            "✅ <b>Вы успешно вышли из аккаунта!</b>\n\n"
            "Теперь вы можете войти в другой аккаунт или зарегистрировать новый.",
            reply_markup=Keyboards.main_menu(user_id)
        )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("skip_recovery:"))
async def skip_recovery_handler(callback: CallbackQuery):
    """Пропуск кодового слова"""
    user_id = callback.from_user.id
    
    if not await ButtonSecurity.check_owner(callback):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    state_data = user_state.get_state(user_id)
    if not state_data or state_data["state"] != "waiting_for_recovery":
        await callback.answer("Неверное состояние", show_alert=True)
        return
    
    data = state_data["data"]
    
    # Завершаем регистрацию без кодового слова
    username = data.get("username")
    password = data.get("password")
    
    if not username or not password:
        await callback.answer("Ошибка: данные регистрации потеряны", show_alert=True)
        user_state.clear_state(user_id)
        return
    
    account_id = db.create_account(username, password, None, user_id)
    if not account_id:
        await callback.answer("Ошибка создания аккаунта", show_alert=True)
        user_state.clear_state(user_id)
        return
    
    # Создаем сессию
    db.create_session(user_id, account_id, callback.from_user.username)
    
    # Очищаем таймер
    db.clear_timer(user_id, "registration")
    user_state.clear_state(user_id)
    
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
        reply_markup=Keyboards.main_menu(user_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("cancel:"))
async def cancel_handler(callback: CallbackQuery):
    """Обработчик отмены действия"""
    if not await ButtonSecurity.check_owner(callback):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Очищаем состояние и таймеры
    state_data = user_state.get_state(user_id)
    if state_data:
        if state_data["state"] in ["waiting_for_username", "waiting_for_password", "waiting_for_recovery"]:
            db.clear_timer(user_id, "registration")
        elif state_data["state"] in ["waiting_for_login_username", "waiting_for_login_password"]:
            db.clear_timer(user_id, "login")
    
    user_state.clear_state(user_id)
    
    await callback.message.edit_text(
        "❌ Действие отменено.\n\nГлавное меню:",
        reply_markup=Keyboards.main_menu(user_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("menu:"))
async def menu_handler(callback: CallbackQuery):
    """Обработчик главного меню"""
    user_id = callback.from_user.id
    action = callback.data.split(":")[1]
    
    # Проверяем владельца кнопки
    if not await ButtonSecurity.check_owner(callback):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    # Очищаем любые активные состояния при переходе в меню
    if user_state.get_state(user_id):
        user_state.clear_state(user_id)
    
    if action == "admin":
        if user_id not in ADMIN_IDS:
            await callback.answer("Доступ запрещен", show_alert=True)
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
                reply_markup=Keyboards.admin_menu()
            )
        
        await callback.answer()
        return
    
    # Для остальных действий проверяем авторизацию
    if action not in ["main"] and not is_logged_in(user_id):
        await callback.answer("Сначала войдите в аккаунт!", show_alert=True)
        return
    
    if action == "main":
        await callback.message.edit_text(
            "🎮 <b>Главное меню</b>\n\nВыбери действие:",
            reply_markup=Keyboards.main_menu(user_id)
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
    
    elif action == "shop":
        await callback.message.edit_text(
            "🏪 <b>Магазин</b>\n\nДоступные товары:\n"
            "💎 <b>VIP статус</b> - уменьшает все кулдауны в 1.5 раза\n\n"
            "Выбери пакет:",
            reply_markup=Keyboards.shop_menu(user_id)
        )
    
    elif action == "profile":
        if not is_logged_in(user_id):
            await callback.answer("Сначала войдите в аккаунт!", show_alert=True)
            return
        
        await show_profile(callback.message)
        await callback.answer()
    
    elif action == "bonus":
        await bonus_command(callback.message)
        await callback.answer()
    
    await callback.answer()

@dp.callback_query(F.data.startswith("game:"))
async def game_handler(callback: CallbackQuery):
    """Обработчик выбора игры"""
    if not await ButtonSecurity.check_owner(callback):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    if not is_logged_in(user_id):
        await callback.answer("Сначала войдите в аккаунт!", show_alert=True)
        return
    
    session = get_user_session(user_id)
    account_id = session['account_id']
    
    # Проверяем доступность игр
    account_settings = db.get_account_settings(account_id)
    if not account_settings['can_play_games']:
        await callback.answer("❌ Игры отключены для этого аккаунта!", show_alert=True)
        return
    
    prefix, owner_id, params = ButtonSecurity.parse_callback_data(callback.data)
    game_type = params.get("type")
    
    # Проверка КД
    allowed, error = await CooldownManager.check_cooldown(callback.message, user_id)
    if not allowed:
        await callback.answer(error, show_alert=True)
        return
    
    # Проверяем баланс
    game_data = db.get_game_data(account_id)
    if game_data['balance'] < MIN_BET:
        await callback.answer(
            f"Недостаточно Pulse Coins. Нужно {MIN_BET}, а у тебя {game_data['balance']}.", 
            show_alert=True
        )
        return
    
    # Определяем номер игры для проверки КД
    game_number = {"impulse": 1, "three_signals": 2, "tactical": 3}[game_type]
    
    # Проверяем кулдаун игры
    allowed_game, error_game = await Games.check_game_cooldown(account_id, game_number)
    if not allowed_game:
        await callback.answer(error_game, show_alert=True)
        return
    
    # Списываем минимальную ставку
    db.update_balance(account_id, -MIN_BET, "game_bet")
    db.update_last_action(account_id)
    
    # Обновляем общий счетчик игр
    db.cursor.execute(
        "UPDATE game_data SET games_played = games_played + 1 WHERE account_id = ?",
        (account_id,)
    )
    db.conn.commit()
    
    # Запускаем игру
    game_names = {
        "impulse": "Импульс",
        "three_signals": "Три сигнала",
        "tactical": "Тактическое решение"
    }
    
    await callback.message.edit_text(
        f"🎮 <b>{game_names[game_type]}</b>\n\n"
        f"💰 Ставка: {MIN_BET} Pulse Coins\n"
        "⏳ Игра начинается...",
        reply_markup=None
    )
    
    # Играем
    if game_type == "impulse":
        result = await Games.impulse_game(account_id, MIN_BET)
    elif game_type == "three_signals":
        result = await Games.three_signals_game(account_id, MIN_BET)
    else:  # tactical
        result = await Games.tactical_decision_game(account_id, MIN_BET)
    
    # Получаем актуальный баланс
    game_data = db.get_game_data(account_id)
    
    # Отправляем результат
    result_text = (
        f"{result['message']}\n\n"
        f"💰 Ставка: {MIN_BET} Pulse Coins\n"
        f"📈 Результат: {'Выигрыш' if result['win'] else 'Проигрыш'} "
        f"({'+' if result['win'] else ''}{result['amount']})\n"
        f"💳 Баланс сейчас: {game_data['balance']}"
    )
    
    await callback.message.edit_text(
        result_text,
        reply_markup=Keyboards.games_menu(user_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_vip:"))
async def buy_vip_handler(callback: CallbackQuery):
    """Обработчик покупки VIP"""
    if not await ButtonSecurity.check_owner(callback):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    if not is_logged_in(user_id):
        await callback.answer("Сначала войдите в аккаунт!", show_alert=True)
        return
    
    session = get_user_session(user_id)
    account_id = session['account_id']
    
    # Проверяем доступность VIP
    account_settings = db.get_account_settings(account_id)
    if not account_settings['can_use_vip']:
        await callback.answer("❌ Покупка VIP отключена для этого аккаунта!", show_alert=True)
        return
    
    prefix, owner_id, params = ButtonSecurity.parse_callback_data(callback.data)
    days = int(params.get("days"))
    
    # Проверка КД
    allowed, error = await CooldownManager.check_cooldown(callback.message, user_id)
    if not allowed:
        await callback.answer(error, show_alert=True)
        return
    
    price = VIP_PACKAGES[days]
    game_data = db.get_game_data(account_id)
    
    # Проверяем баланс
    if game_data['balance'] < price:
        await callback.answer(
            f"Недостаточно Pulse Coins. Нужно {price}, а у тебя {game_data['balance']}.", 
            show_alert=True
        )
        return
    
    # Покупаем VIP
    db.update_balance(account_id, -price, "vip_purchase")
    db.set_vip(account_id, days)
    db.update_last_action(account_id)
    
    months = days // 30
    
    await callback.message.edit_text(
        f"🎉 <b>Поздравляем с покупкой VIP!</b>\n\n"
        f"⭐ Теперь у тебя VIP статус на {months} месяцев\n"
        f"💎 Все кулдауны уменьшены в 1.5 раза\n"
        f"💰 Списано: {price} Pulse Coins\n"
        f"💳 Баланс: {game_data['balance'] - price} Pulse",
        reply_markup=Keyboards.main_menu(user_id)
    )
    await callback.answer()

# ========== АДМИН-ПАНЕЛЬ ==========
@dp.callback_query(F.data.startswith("admin:"))
async def admin_handler(callback: CallbackQuery):
    """Обработчик админ-меню"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Проверяем админскую сессию
    if not db.check_admin_session(user_id):
        await callback.answer("Сессия истекла. Введите пароль заново.", show_alert=True)
        return
    
    action = callback.data.split(":")[1]
    
    if action == "stats":
        accounts = db.get_all_accounts()
        total_accounts = len(accounts)
        total_sessions = len(db.get_all_sessions())
        treasury = db.get_treasury()
        
        active_sessions = len([s for s in db.get_all_sessions() if s['logout_time'] is None])
        blocked_accounts = len([a for a in accounts if db.is_account_blocked(a['account_id'])])
        
        stats_text = (
            f"📊 <b>Статистика бота</b>\n\n"
            f"👥 Всего аккаунтов: {total_accounts}\n"
            f"🚫 Заблокировано: {blocked_accounts}\n"
            f"📋 Всего сессий: {total_sessions}\n"
            f"🟢 Активных сессий: {active_sessions}\n"
            f"🏦 Казна: {treasury} Pulse\n\n"
            f"<b>Последние 5 аккаунтов:</b>\n"
        )
        
        for i, acc in enumerate(accounts[:5]):
            status = "🚫" if db.is_account_blocked(acc['account_id']) else "🟢"
            stats_text += f"{i+1}. {status} {acc['username']} - {acc['balance']} Pulse\n"
        
        await callback.message.edit_text(stats_text, reply_markup=Keyboards.admin_menu())
    
    elif action == "search":
        user_state.set_state(user_id, "admin_search")
        await callback.message.edit_text(
            "🔍 <b>Поиск аккаунта</b>\n\n"
            "Введите логин или ID аккаунта для поиска:",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "balance":
        user_state.set_state(user_id, "admin_balance")
        await callback.message.edit_text(
            "💰 <b>Управление балансами</b>\n\n"
            "Отправьте в формате:\n"
            "<code>ID_аккаунта СУММА</code>\n\n"
            "Пример: <code>123 100</code>\n"
            "Для снятия: <code>123 -50</code>\n\n"
            "<i>ID аккаунта можно посмотреть в списке всех аккаунтов</i>",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "broadcast":
        user_state.set_state(user_id, "admin_broadcast")
        await callback.message.edit_text(
            "📢 <b>Рассылка</b>\n\n"
            "Отправьте сообщение для рассылки.\n"
            "Поддерживается текст, фото и видео.\n\n"
            "<i>Ответьте на это сообщение тем, что хотите разослать</i>",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "treasury":
        treasury = db.get_treasury()
        
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text="💳 Вывести казну", 
                callback_data=ButtonSecurity.create_callback_data("withdraw_treasury", user_id)
            )
        )
        builder.row(
            InlineKeyboardButton(text="🔙 Назад", callback_data="admin:stats")
        )
        
        await callback.message.edit_text(
            f"🏦 <b>Казна бота</b>\n\n"
            f"Общая сумма потраченных коинов: {treasury} Pulse\n\n"
            "Казна — это статистика, а не кошелёк.\n"
            "При выводе сумма записывается на баланс бота.",
            reply_markup=builder.as_markup()
        )
    
    elif action == "manage":
        await callback.message.edit_text(
            "⚙️ <b>Управление ботом</b>\n\n"
            "Выберите действие из списка выше.",
            reply_markup=Keyboards.admin_menu()
        )
    
    await callback.answer()

# Обработка админского пароля
@dp.message(F.text)
async def admin_text_handler(message: Message):
    """Обработчик текстовых сообщений для админа"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    text = message.text.strip()
    
    # Пропускаем команды удаления
    if text.startswith(("-соо", "+удал соо", "-удал соо")):
        return
    
    # Проверяем состояние
    state_data = user_state.get_state(user_id)
    if not state_data:
        return
    
    state = state_data["state"]
    
    if state == "admin_password":
        if text == ADMIN_PASSWORD:
            db.create_admin_session(user_id)
            user_state.clear_state(user_id)
            await message.answer(
                "✅ <b>Пароль правильный!</b>\n\n"
                "Доступ к админ-панели разрешен.\n"
                "Сессия активна 30 минут.\n\n"
                "Выберите действие:",
                reply_markup=Keyboards.admin_menu()
            )
        else:
            await message.answer(
                "❌ <b>Пароль не правильный!</b>\n\n"
                "Попробуйте еще раз или нажмите 'Отмена'."
            )
    
    elif state == "admin_balance":
        try:
            if not text.replace('-', '').replace(' ', '').isdigit():
                await message.answer("❌ Неверный формат. Используйте: ID СУММА")
                return
            
            parts = text.split()
            if len(parts) != 2:
                await message.answer("❌ Неверный формат. Используйте: ID СУММА")
                return
            
            account_id = int(parts[0])
            amount = int(parts[1])
            
            account = db.get_account_by_id(account_id)
            if not account:
                await message.answer("❌ Аккаунт не найден")
                return
            
            db.update_balance(account_id, amount, "admin_change")
            game_data = db.get_game_data(account_id)
            
            await message.answer(
                f"✅ Баланс изменен\n\n"
                f"Аккаунт: {account['username']}\n"
                f"ID: {account_id}\n"
                f"Изменение: {'+' if amount > 0 else ''}{amount} Pulse\n"
                f"Новый баланс: {game_data['balance']} Pulse",
                reply_markup=Keyboards.admin_menu()
            )
            user_state.clear_state(user_id)
            
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")
    
    elif state == "admin_broadcast":
        # Для рассылки нужно обрабатывать отдельно
        pass

# ========== ГРУППОВЫЕ КОМАНДЫ ==========
@dp.message(F.chat.type.in_(["group", "supergroup"]))
async def group_handler(message: Message):
    """Обработчик сообщений в группах"""
    if message.text and message.text.startswith("/"):
        command = message.text.split()[0].lower()
        
        if command in ["/start", "/startpuls", "/registerpuls", "/login", "/logout", "/удалсписок"]:
            is_admin = False
            try:
                chat_member = await bot.get_chat_member(message.chat.id, message.from_user.id)
                is_admin = chat_member.status in ["administrator", "creator"]
            except:
                pass
            
            user_id = message.from_user.id
            
            # Проверяем, зарегистрирован ли пользователь
            if not is_logged_in(user_id):
                await message.answer(
                    "❌ Вы должны быть зарегистрированы в боте и войти в аккаунт для использования команд!\n\n"
                    "Перейдите в личные сообщения с ботом @PulsOfficialManager_bot чтобы зарегистрироваться.",
                    reply_to_message_id=message.message_id
                )
                return
            
            allowed, error = await CooldownManager.check_cooldown(message, user_id, is_admin)
            if not allowed:
                await message.answer(error)
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
                    reply_to_message_id=message.message_id
                )
            
            elif command == "/logout":
                if not is_logged_in(user_id):
                    await message.answer("Вы не авторизованы в аккаунте.")
                    return
                
                session = get_user_session(user_id)
                if session:
                    db.logout_session(session['session_id'])
                
                await message.answer("✅ Вы успешно вышли из аккаунта!", reply_to_message_id=message.message_id)
            
            elif command == "/удалсписок":
                # Эта команда обрабатывается отдельно выше
                pass

# ========== ОСТАЛЬНЫЕ ФУНКЦИИ ==========
async def work_command(message: Message):
    """Обработчик работы"""
    user_id = message.from_user.id
    
    if not is_logged_in(user_id):
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    session = get_user_session(user_id)
    account_id = session['account_id']
    
    # Проверяем доступность работы
    account_settings = db.get_account_settings(account_id)
    if not account_settings['can_work']:
        await message.answer("❌ Работа отключена для этого аккаунта!")
        return
    
    game_data = db.get_game_data(account_id)
    
    # Проверяем лимит работ
    if game_data['work_count'] >= WORK_LIMIT:
        await message.answer(
            f"Достигнут лимит работ ({WORK_LIMIT}).\n"
            f"Следующая работа через: {format_time(WORK_LIMIT_COOLDOWN)}"
        )
        return
    
    # Проверяем кулдаун
    if game_data['last_work']:
        last_work = datetime.fromisoformat(game_data['last_work'])
        cooldown = WORK_COOLDOWN
        if db.check_vip(account_id):
            cooldown = int(cooldown / VIP_MULTIPLIER)
        
        next_work = last_work + timedelta(seconds=cooldown)
        if next_work > datetime.now():
            remaining = (next_work - datetime.now()).total_seconds()
            await message.answer(
                f"Работа пока недоступна.\n"
                f"Осталось: {format_time(remaining)}"
            )
            return
    
    # Выполняем работу
    reward = random.randint(20, 100)
    db.update_balance(account_id, reward, "work")
    
    # Обновляем статистику
    db.cursor.execute(
        "UPDATE game_data SET work_count = work_count + 1, last_work = CURRENT_TIMESTAMP WHERE account_id = ?",
        (account_id,)
    )
    db.conn.commit()
    
    await message.answer(
        f"💼 <b>Работа выполнена!</b>\n\n"
        f"Ты заработал: {reward} Pulse Coins\n"
        f"Баланс: {game_data['balance'] + reward} Pulse\n\n"
        f"Осталось работ сегодня: {WORK_LIMIT - game_data['work_count'] - 1}",
        reply_markup=Keyboards.main_menu(user_id)
    )

async def bonus_command(message: Message):
    """Обработчик бонуса"""
    user_id = message.from_user.id
    
    if not is_logged_in(user_id):
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    session = get_user_session(user_id)
    account_id = session['account_id']
    
    # Проверяем доступность бонуса
    account_settings = db.get_account_settings(account_id)
    if not account_settings['can_claim_bonus']:
        await message.answer("❌ Бонус отключен для этого аккаунта!")
        return
    
    game_data = db.get_game_data(account_id)
    
    # Проверяем кулдаун
    if game_data['last_bonus']:
        last_bonus = datetime.fromisoformat(game_data['last_bonus'])
        next_bonus = last_bonus + timedelta(seconds=BONUS_COOLDOWN)
        
        if next_bonus > datetime.now():
            remaining = (next_bonus - datetime.now()).total_seconds()
            await message.answer(
                f"Бонус пока недоступен.\n"
                f"Осталось: {format_time(remaining)}"
            )
            return
    
    # Выдаем бонус
    db.update_balance(account_id, BONUS_AMOUNT, "bonus")
    db.cursor.execute(
        "UPDATE game_data SET last_bonus = CURRENT_TIMESTAMP WHERE account_id = ?",
        (account_id,)
    )
    db.conn.commit()
    
    await message.answer(
        f"🎁 <b>Ежедневный бонус!</b>\n\n"
        f"Ты получил: {BONUS_AMOUNT} Pulse Coins\n"
        f"Баланс: {game_data['balance'] + BONUS_AMOUNT} Pulse",
        reply_markup=Keyboards.main_menu(user_id)
    )

async def show_profile(message: Message):
    """Показывает профиль пользователя"""
    user_id = message.from_user.id
    
    if not is_logged_in(user_id):
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    session = get_user_session(user_id)
    account_id = session['account_id']
    game_data = db.get_game_data(account_id)
    account = db.get_account_by_id(account_id)
    
    # Статус VIP
    is_vip = db.check_vip(account_id)
    vip_status = "✅ VIP" if is_vip else "❌ Обычный"
    vip_until = ""
    
    if is_vip and game_data['vip_until']:
        vip_date = datetime.fromisoformat(game_data['vip_until'])
        vip_until = f"\nVIP до: {vip_date.strftime('%d.%m.%Y %H:%M')}"
    
    # Время до бонуса
    bonus_time = "Доступен сейчас"
    if game_data['last_bonus']:
        last_bonus = datetime.fromisoformat(game_data['last_bonus'])
        next_bonus = last_bonus + timedelta(seconds=BONUS_COOLDOWN)
        if next_bonus > datetime.now():
            remaining = (next_bonus - datetime.now()).total_seconds()
            bonus_time = f"Через {format_time(remaining)}"
    
    # Время до работы
    work_time = "Доступна сейчас"
    if game_data['last_work']:
        last_work = datetime.fromisoformat(game_data['last_work'])
        next_work = last_work + timedelta(seconds=WORK_COOLDOWN)
        if next_work > datetime.now():
            remaining = (next_work - datetime.now()).total_seconds()
            work_time = f"Через {format_time(remaining)}"
    
    # Формируем текст профиля
    profile_text = (
        f"👤 <b>Профиль аккаунта</b>\n\n"
        f"📛 Логин: {account['username']}\n"
        f"🔗 Сессия: #{session['session_id']}\n"
        f"⭐ Статус: {vip_status}{vip_until}\n"
        f"💰 Баланс: {game_data['balance']} Pulse Coins\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"🎮 Игр сыграно: {game_data['games_played']}\n"
        f"💼 Работ выполнено: {game_data['work_count']}\n"
        f"💸 Потрачено: {game_data['total_spent']} Pulse\n\n"
        f"⏰ <b>Таймеры:</b>\n"
        f"🎁 Бонус: {bonus_time}\n"
        f"💼 Работа: {work_time}"
    )
    
    await message.answer(profile_text, reply_markup=Keyboards.main_menu(user_id))

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция"""
    logger.info("Запуск бота Pulse Bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

