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
        
        self.conn.commit()
    
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
        game_data = self.get_game_data(account_id)
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
    def cancel_keyboard(user_id: int) -> InlineKeyboardMarkup:
        """Клавиатура с отменой"""
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text="❌ Отмена", 
                callback_data=ButtonSecurity.create_callback_data("cancel", user_id)
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
    def account_management_keyboard(account_id: int, user_id: int) -> InlineKeyboardMarkup:
        """Клавиатура управления аккаунтом"""
        builder = InlineKeyboardBuilder()
        
        account = db.get_account_by_id(account_id)
        is_blocked = db.is_account_blocked(account_id)
        account_settings = db.get_account_settings(account_id)
        
        # Информация
        builder.row(
            InlineKeyboardButton(
                text=f"👤 Логин: {account['username']}", 
                callback_data=f"view_login:{account_id}"
            )
        )
        builder.row(
            InlineKeyboardButton(
                text=f"🔐 Пароль", 
                callback_data=f"view_password:{account_id}"
            )
        )
        if account['recovery_code']:
            builder.row(
                InlineKeyboardButton(
                    text=f"🗝️ Кодовое слово", 
                    callback_data=f"view_recovery:{account_id}"
                )
            )
        
        # Блокировки
        if is_blocked:
            builder.row(
                InlineKeyboardButton(
                    text="✅ Разблокировать аккаунт", 
                    callback_data=f"unblock_account:{account_id}"
                )
            )
        else:
            builder.row(
                InlineKeyboardButton(
                    text="❌ Заблокировать временно", 
                    callback_data=f"block_temp:{account_id}"
                ),
                InlineKeyboardButton(
                    text="🚫 Заблокировать навсегда", 
                    callback_data=f"block_perm:{account_id}"
                )
            )
        
        # Сессии
        builder.row(
            InlineKeyboardButton(
                text="👥 Активные сессии", 
                callback_data=f"view_sessions:{account_id}"
            ),
            InlineKeyboardButton(
                text="👢 Выйти всем", 
                callback_data=f"logout_all:{account_id}"
            )
        )
        
        # Настройки доступа
        builder.row(
            InlineKeyboardButton(
                text=f"🎮 Игры: {'✅' if account_settings['can_play_games'] else '❌'}", 
                callback_data=f"toggle_games:{account_id}"
            )
        )
        builder.row(
            InlineKeyboardButton(
                text=f"💼 Работа: {'✅' if account_settings['can_work'] else '❌'}", 
                callback_data=f"toggle_work:{account_id}"
            )
        )
        builder.row(
            InlineKeyboardButton(
                text=f"🏪 Магазин: {'✅' if account_settings['can_use_shop'] else '❌'}", 
                callback_data=f"toggle_shop:{account_id}"
            )
        )
        builder.row(
            InlineKeyboardButton(
                text=f"🎁 Бонус: {'✅' if account_settings['can_claim_bonus'] else '❌'}", 
                callback_data=f"toggle_bonus:{account_id}"
            )
        )
        builder.row(
            InlineKeyboardButton(
                text=f"⭐ VIP: {'✅' if account_settings['can_use_vip'] else '❌'}", 
                callback_data=f"toggle_vip:{account_id}"
            )
        )
        
        # Управление владельцем
        if account['owner_user_id']:
            builder.row(
                InlineKeyboardButton(
                    text="👤 Блокировать владельца", 
                    callback_data=f"block_owner:{account['owner_user_id']}"
                )
            )
        
        builder.row(
            InlineKeyboardButton(text="🔙 Назад", callback_data="admin:accounts")
        )
        
        return builder.as_markup()
    
    @staticmethod
    def session_management_keyboard(account_id: int, sessions: List[Dict], user_id: int) -> InlineKeyboardMarkup:
        """Клавиатура управления сессиями"""
        builder = InlineKeyboardBuilder()
        
        for session in sessions[:10]:  # Показываем первые 10
            user_link = f"tg://user?id={session['user_id']}"
            is_active = session['logout_time'] is None
            
            builder.row(
                InlineKeyboardButton(
                    text=f"{'🟢' if is_active else '🔴'} {session['telegram_username'] or 'Без ника'}",
                    url=user_link
                ),
                InlineKeyboardButton(
                    text="👢 Выйти" if is_active else "🗑 Удалить",
                    callback_data=f"logout_user:{session['session_id']}:{session['user_id']}"
                )
            )
        
        builder.row(
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"manage_account:{account_id}")
        )
        
        return builder.as_markup()

# ========== СОСТОЯНИЯ РЕГИСТРАЦИИ ==========
class RegistrationStates:
    waiting_for_username = "waiting_for_username"
    waiting_for_password = "waiting_for_password"
    waiting_for_recovery = "waiting_for_recovery"
    waiting_for_login_username = "waiting_for_login_username"
    waiting_for_login_password = "waiting_for_login_password"
    waiting_for_account_search = "waiting_for_account_search"
    waiting_for_block_time = "waiting_for_block_time"

user_states = {}

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
    user_states[user_id] = {"state": RegistrationStates.waiting_for_username}
    await message.answer(
        "📝 <b>Регистрация нового аккаунта</b>\n\n"
        "Придумайте логин (имя пользователя):\n"
        "• Минимум 3 символа\n"
        "• Только буквы, цифры и _\n"
        "• Уникальный для системы",
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
    
    user_states[user_id] = {"state": RegistrationStates.waiting_for_login_username}
    await message.answer(
        "🔐 <b>Вход в аккаунт</b>\n\n"
        "Введите ваш логин:",
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

# ========== ОБРАБОТКА ВВОДА ДАННЫХ ==========
@dp.message(F.text)
async def handle_text_input(message: Message):
    """Обработчик текстового ввода"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    if user_id not in user_states:
        # Проверяем, не админ ли ищет аккаунт
        if user_id in ADMIN_IDS:
            # Проверяем, не в состоянии ли поиска
            if user_id in user_states and user_states[user_id].get("state") == RegistrationStates.waiting_for_account_search:
                # Поиск аккаунта
                accounts = db.get_all_accounts()
                found_accounts = []
                
                for account in accounts:
                    if text.lower() in account['username'].lower() or str(text) == str(account['account_id']):
                        found_accounts.append(account)
                
                if found_accounts:
                    result_text = "🔍 <b>Найденные аккаунты:</b>\n\n"
                    for acc in found_accounts[:5]:  # Показываем первые 5
                        is_blocked = db.is_account_blocked(acc['account_id'])
                        result_text += (
                            f"<b>ID: {acc['account_id']}</b>\n"
                            f"👤 Логин: {acc['username']}\n"
                            f"🔐 Пароль: <code>{acc['password']}</code>\n"
                            f"🗝️ Код: <code>{acc['recovery_code'] or 'Нет'}</code>\n"
                            f"📊 Баланс: {acc['balance']} Pulse\n"
                            f"🚫 Статус: {'Заблокирован' if is_blocked else 'Активен'}\n"
                            f"📅 Создан: {datetime.fromisoformat(acc['created_at']).strftime('%d.%m.%Y %H:%M')}\n"
                            f"🔗 [Управление](tg://user?id={ADMIN_IDS[0]}?start=manage_{acc['account_id']})\n\n"
                        )
                    
                    await message.answer(result_text, reply_markup=Keyboards.admin_menu())
                else:
                    await message.answer("❌ Аккаунты не найдены.", reply_markup=Keyboards.admin_menu())
                
                if user_id in user_states:
                    del user_states[user_id]
        return
    
    state_data = user_states[user_id]
    state = state_data.get("state")
    
    if state == RegistrationStates.waiting_for_username:
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
        state_data["username"] = text
        state_data["state"] = RegistrationStates.waiting_for_password
        await message.answer(
            "Отлично! Теперь придумайте пароль:\n\n"
            "<b>Требования к паролю:</b>\n"
            "• Минимум 5 символов\n"
            "• Хотя бы 1 буква\n"
            "• Хотя бы 1 цифра\n"
            "• Максимум 15 символов"
        )
    
    elif state == RegistrationStates.waiting_for_password:
        # Проверяем пароль
        is_valid, error_msg = validate_password(text)
        if not is_valid:
            await message.answer(f"{error_msg}\n\nПопробуйте еще раз:")
            return
        
        # Сохраняем пароль и запрашиваем кодовое слово
        state_data["password"] = text
        state_data["state"] = RegistrationStates.waiting_for_recovery
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
    
    elif state == RegistrationStates.waiting_for_recovery:
        # Проверяем кодовое слово
        is_valid, error_msg = validate_recovery_code(text)
        if not is_valid:
            await message.answer(f"{error_msg}\n\nПопробуйте еще раз:")
            return
        
        # Завершаем регистрацию
        username = state_data["username"]
        password = state_data["password"]
        recovery_code = text
        
        account_id = db.create_account(username, password, recovery_code, user_id)
        if not account_id:
            await message.answer("Произошла ошибка при создании аккаунта. Попробуйте еще раз.")
            del user_states[user_id]
            return
        
        # Создаем сессию
        db.create_session(user_id, account_id, message.from_user.username)
        
        await message.answer(
            "🎉 <b>Поздравляем с успешной регистрацией!</b>\n\n"
            f"📝 <b>Ваши данные:</b>\n"
            f"👤 Логин: <code>{username}</code>\n"
            f"🔐 Пароль: <code>{password}</code>\n"
            f"🗝️ Кодовое слово: <code>{recovery_code}</code>\n\n"
            "<b>⚠️ СОХРАНИТЕ ЭТИ ДАННЫЕ!</b>\n"
            "• Никому не передавайте свои данные\n"
            "• Кодовое слово нужно для восстановления аккаунта\n"
            "• Администрация никогда не просит пароли\n\n"
            "Теперь вы можете пользоваться всеми функциями бота!",
            reply_markup=Keyboards.main_menu(user_id)
        )
        del user_states[user_id]
    
    elif state == RegistrationStates.waiting_for_login_username:
        # Сохраняем логин для входа
        state_data["login_username"] = text
        state_data["state"] = RegistrationStates.waiting_for_login_password
        await message.answer("Введите пароль:")
    
    elif state == RegistrationStates.waiting_for_login_password:
        # Пытаемся войти
        username = state_data["login_username"]
        password = text
        
        account = db.get_account_by_credentials(username, password)
        if not account:
            await message.answer("Неверный логин или пароль. Попробуйте еще раз или зарегистрируйтесь.")
            del user_states[user_id]
            return
        
        # Проверяем, не заблокирован ли аккаунт
        if db.is_account_blocked(account['account_id']):
            await message.answer("❌ Этот аккаунт заблокирован.")
            del user_states[user_id]
            return
        
        # Создаем сессию
        db.create_session(user_id, account['account_id'], message.from_user.username)
        
        game_data = db.get_game_data(account['account_id'])
        
        await message.answer(
            f"✅ <b>Успешный вход!</b>\n\n"
            f"👤 Аккаунт: <code>{username}</code>\n"
            f"💰 Баланс: {game_data['balance']} Pulse Coins\n"
            f"⭐ Статус: {'✅ VIP' if db.check_vip(account['account_id']) else '❌ Обычный'}\n\n"
            "Добро пожаловать обратно!",
            reply_markup=Keyboards.main_menu(user_id)
        )
        del user_states[user_id]
    
    elif state == RegistrationStates.waiting_for_block_time:
        # Обработка времени блокировки
        account_id = state_data.get("account_id")
        if not account_id:
            await message.answer("Ошибка: не найден ID аккаунта")
            del user_states[user_id]
            return
        
        try:
            # Парсим время: 1d, 2h, 30m
            text = text.lower()
            days = 0
            hours = 0
            minutes = 0
            
            if 'd' in text:
                days = int(text.split('d')[0])
                text = text.split('d')[1] if 'd' in text and len(text.split('d')) > 1 else ''
            if 'h' in text:
                hours = int(text.split('h')[0].strip())
                text = text.split('h')[1] if 'h' in text and len(text.split('h')) > 1 else ''
            if 'm' in text:
                minutes = int(text.split('m')[0].strip())
            
            if days == 0 and hours == 0 and minutes == 0:
                await message.answer("Неверный формат времени. Пример: 1d 2h 30m")
                return
            
            block_until = datetime.now() + timedelta(days=days, hours=hours, minutes=minutes)
            db.block_account(account_id, "Временная блокировка администратором", block_until)
            
            account = db.get_account_by_id(account_id)
            await message.answer(
                f"✅ Аккаунт {account['username']} заблокирован до {block_until.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"ID: {account_id}\n"
                f"Логин: {account['username']}\n"
                f"Владелец: {account['owner_user_id'] or 'Неизвестно'}",
                reply_markup=Keyboards.account_management_keyboard(account_id, user_id)
            )
            
        except ValueError:
            await message.answer("Неверный формат времени. Пример: 1d 2h 30m")
            return
        
        del user_states[user_id]

# ========== ОБРАБОТЧИКИ КНОПОК ==========
@dp.callback_query(F.data.startswith("auth:"))
async def auth_handler(callback: CallbackQuery):
    """Обработчик кнопок авторизации"""
    user_id = callback.from_user.id
    action = callback.data.split(":")[1]
    
    if action == "register":
        # Исправлено: используем callback.message вместо message
        if callback.message.chat.type != "private":
            await callback.answer("Регистрация только в ЛС! Я написал вам.", show_alert=True)
            try:
                await bot.send_message(
                    user_id,
                    "Для регистрации нажмите кнопку '📝 Регистрация' в главном меню."
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
        
        user_states[user_id] = {"state": RegistrationStates.waiting_for_username}
        await callback.message.edit_text(
            "📝 <b>Регистрация нового аккаунта</b>\n\n"
            "Придумайте логин (имя пользователя):\n"
            "• Минимум 3 символа\n"
            "• Только буквы, цифры и _\n"
            "• Уникальный для системы",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "login":
        if callback.message.chat.type != "private":
            await callback.answer("Вход только в ЛС!", show_alert=True)
            return
        
        if is_logged_in(user_id):
            await callback.answer("Вы уже авторизованы!", show_alert=True)
            return
        
        user_states[user_id] = {"state": RegistrationStates.waiting_for_login_username}
        await callback.message.edit_text(
            "🔐 <b>Вход в аккаунт</b>\n\n"
            "Введите ваш логин:",
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
    
    if user_id not in user_states:
        await callback.answer("Ошибка состояния", show_alert=True)
        return
    
    state_data = user_states[user_id]
    if state_data.get("state") != RegistrationStates.waiting_for_recovery:
        await callback.answer("Неверное состояние", show_alert=True)
        return
    
    # Завершаем регистрацию без кодового слова
    username = state_data["username"]
    password = state_data["password"]
    
    account_id = db.create_account(username, password, None, user_id)
    if not account_id:
        await callback.answer("Ошибка создания аккаунта", show_alert=True)
        del user_states[user_id]
        return
    
    # Создаем сессию
    db.create_session(user_id, account_id, callback.from_user.username)
    
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
    del user_states[user_id]
    await callback.answer()

@dp.callback_query(F.data.startswith("menu:"))
async def menu_handler(callback: CallbackQuery):
    """Обработчик главного меню"""
    user_id = callback.from_user.id
    action = callback.data.split(":")[1]
    
    # Проверяем авторизацию для всех действий кроме профиля и админки
    if action not in ["profile", "admin"] and not is_logged_in(user_id):
        await callback.answer("Сначала войдите в аккаунт!", show_alert=True)
        return
    
    # Проверяем владельца кнопки
    if not await ButtonSecurity.check_owner(callback):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    session = get_user_session(user_id) if is_logged_in(user_id) else None
    account_id = session['account_id'] if session else None
    
    if action == "main":
        await callback.message.edit_text(
            "🎮 <b>Главное меню</b>\n\nВыбери действие:",
            reply_markup=Keyboards.main_menu(user_id)
        )
    
    elif action == "games":
        # Проверяем доступность игр
        if session:
            account_settings = db.get_account_settings(account_id)
            if not account_settings['can_play_games']:
                await callback.answer("❌ Игры отключены для этого аккаунта!", show_alert=True)
                return
            
            db.update_last_action(account_id)
        
        await callback.message.edit_text(
            "🎮 <b>Игры</b>\n\nВыбери игру:\n"
            "⚡ <b>Импульс</b> - проверь свою реакцию\n"
            "📶 <b>Три сигнала</b> - найди настоящий сигнал\n"
            "🎯 <b>Тактическое решение</b> - переиграй противника\n\n"
            f"Минимальная ставка: {MIN_BET} Pulse Coins",
            reply_markup=Keyboards.games_menu(user_id)
        )
    
    elif action == "work":
        if session:
            account_settings = db.get_account_settings(account_id)
            if not account_settings['can_work']:
                await callback.answer("❌ Работа отключена для этого аккаунта!", show_alert=True)
                return
            
            db.update_last_action(account_id)
        
        await work_command(callback.message)
        await callback.answer()
    
    elif action == "shop":
        if session:
            account_settings = db.get_account_settings(account_id)
            if not account_settings['can_use_shop']:
                await callback.answer("❌ Магазин отключен для этого аккаунта!", show_alert=True)
                return
            
            db.update_last_action(account_id)
        
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
        if session:
            account_settings = db.get_account_settings(account_id)
            if not account_settings['can_claim_bonus']:
                await callback.answer("❌ Бонус отключен для этого аккаунта!", show_alert=True)
                return
            
            db.update_last_action(account_id)
        
        await bonus_command(callback.message)
        await callback.answer()
    
    elif action == "admin":
        if user_id not in ADMIN_IDS:
            await callback.answer("Доступ запрещен", show_alert=True)
            return
        
        # Показываем админ-панель с запросом пароля
        await callback.message.edit_text(
            "🔐 <b>Админ-панель</b>\n\n"
            "Введите пароль для доступа:",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
        await callback.answer()
    
    # Проверка КД после обработки меню
    if session and action not in ["main", "admin"]:
        allowed, error = await CooldownManager.check_cooldown(callback.message, user_id)
        if not allowed:
            await callback.answer(error, show_alert=True)

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

@dp.callback_query(F.data.startswith("cancel:"))
async def cancel_handler(callback: CallbackQuery):
    """Обработчик отмены"""
    if not await ButtonSecurity.check_owner(callback):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Отменяем текущее действие
    if user_id in user_states:
        del user_states[user_id]
    
    if user_id in ADMIN_IDS:
        await callback.message.edit_text(
            "🔐 <b>Админ-панель</b>\n\nВыберите действие:",
            reply_markup=Keyboards.admin_menu()
        )
    else:
        await callback.message.edit_text(
            "🎮 <b>Главное меню</b>\n\nВыбери действие:",
            reply_markup=Keyboards.main_menu(user_id)
        )
    
    await callback.answer()

# ========== АДМИН-ПАНЕЛЬ ==========
class AdminSession:
    """Управление админскими сессиями"""
    
    @staticmethod
    def check_session(user_id: int) -> bool:
        db.cursor.execute("SELECT expires_at FROM admin_sessions WHERE user_id = ?", (user_id,))
        result = db.cursor.fetchone()
        
        if not result:
            return False
        
        expires_at = datetime.fromisoformat(result[0])
        if expires_at < datetime.now():
            db.cursor.execute("DELETE FROM admin_sessions WHERE user_id = ?", (user_id,))
            db.conn.commit()
            return False
        
        return True
    
    @staticmethod
    def create_session(user_id: int):
        expires_at = datetime.now() + timedelta(minutes=30)
        db.cursor.execute(
            "INSERT OR REPLACE INTO admin_sessions (user_id, expires_at) VALUES (?, ?)",
            (user_id, expires_at.isoformat())
        )
        db.conn.commit()
    
    @staticmethod
    def delete_session(user_id: int):
        db.cursor.execute("DELETE FROM admin_sessions WHERE user_id = ?", (user_id,))
        db.conn.commit()

@dp.message(F.text)
async def admin_password_handler(message: Message):
    """Обработчик ввода пароля админки"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    # Проверяем, является ли это ответом на запрос пароля
    if not message.reply_to_message or "пароль" not in (message.reply_to_message.text or "").lower():
        return
    
    # Проверяем пароль
    if message.text == ADMIN_PASSWORD:
        AdminSession.create_session(user_id)
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

@dp.callback_query(F.data.startswith("admin:"))
async def admin_handler(callback: CallbackQuery):
    """Обработчик админ-меню"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS or not AdminSession.check_session(user_id):
        await callback.answer("Сессия истекла или доступ запрещен", show_alert=True)
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
    
    elif action == "accounts":
        accounts = db.get_all_accounts()
        
        if not accounts:
            await callback.message.edit_text("Нет зарегистрированных аккаунтов.", reply_markup=Keyboards.admin_menu())
            return
        
        # Показываем первую страницу аккаунтов
        await show_accounts_page(callback, accounts, 0)
    
    elif action == "sessions":
        sessions = db.get_all_sessions()
        
        if not sessions:
            await callback.message.edit_text("Нет активных сессий.", reply_markup=Keyboards.admin_menu())
            return
        
        sessions_text = "📋 <b>Последние 10 сессий:</b>\n\n"
        for i, sess in enumerate(sessions[:10]):
            login_time = datetime.fromisoformat(sess['login_time']).strftime('%d.%m.%Y %H:%M')
            logout_time = datetime.fromisoformat(sess['logout_time']).strftime('%d.%m.%Y %H:%M') if sess['logout_time'] else "Активна"
            status = "🟢 Активна" if sess['logout_time'] is None else "🔴 Завершена"
            
            sessions_text += (
                f"<b>Сессия #{sess['session_id']}</b>\n"
                f"   Пользователь: <a href='tg://user?id={sess['user_id']}'>{sess['telegram_username'] or 'Без ника'}</a>\n"
                f"   ID: {sess['user_id']}\n"
                f"   Аккаунт: {sess['username']}\n"
                f"   Статус: {status}\n"
                f"   Вход: {login_time}\n"
                f"   Выход: {logout_time}\n\n"
            )
        
        await callback.message.edit_text(sessions_text, reply_markup=Keyboards.admin_menu())
    
    elif action == "search":
        user_states[user_id] = {"state": RegistrationStates.waiting_for_account_search}
        await callback.message.edit_text(
            "🔍 <b>Поиск аккаунта</b>\n\n"
            "Введите логин или ID аккаунта для поиска:",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "balance":
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
        accounts = db.get_all_accounts()
        if not accounts:
            await callback.message.edit_text("Нет аккаунтов для управления.", reply_markup=Keyboards.admin_menu())
            return
        
        # Показываем управление первым аккаунтом
        await show_account_management(callback, accounts[0]['account_id'])
    
    elif action == "logout":
        AdminSession.delete_session(user_id)
        await callback.message.edit_text("✅ Сессия завершена")
    
    await callback.answer()

async def show_accounts_page(callback: CallbackQuery, accounts: List[Dict], page: int):
    """Показывает страницу аккаунтов"""
    user_id = callback.from_user.id
    items_per_page = 5
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    
    accounts_page = accounts[start_idx:end_idx]
    
    if not accounts_page and page > 0:
        # Если страница пуста, возвращаемся на предыдущую
        await show_accounts_page(callback, accounts, page - 1)
        return
    
    accounts_text = f"📋 <b>Аккаунты (страница {page + 1})</b>\n\n"
    
    for i, acc in enumerate(accounts_page):
        idx = start_idx + i + 1
        is_blocked = db.is_account_blocked(acc['account_id'])
        status = "🚫" if is_blocked else "🟢"
        owner_info = f"👤 {acc['owner_user_id']}" if acc['owner_user_id'] else "👤 Неизвестно"
        
        accounts_text += (
            f"<b>{idx}. {status} {acc['username']}</b>\n"
            f"   ID: {acc['account_id']}\n"
            f"   {owner_info}\n"
            f"   Баланс: {acc['balance']} Pulse\n"
            f"   Создан: {datetime.fromisoformat(acc['created_at']).strftime('%d.%m.%Y')}\n"
            f"   [Управление](tg://user?id={user_id}?start=manage_{acc['account_id']})\n\n"
        )
    
    builder = InlineKeyboardBuilder()
    
    # Кнопки навигации
    if page > 0:
        builder.row(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"accounts_page:{page-1}")
        )
    
    if end_idx < len(accounts):
        if page > 0:
            builder.add(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"accounts_page:{page+1}"))
        else:
            builder.row(
                InlineKeyboardButton(text="Вперед ➡️", callback_data=f"accounts_page:{page+1}")
            )
    
    builder.row(
        InlineKeyboardButton(text="🔙 Назад", callback_data="admin:stats")
    )
    
    await callback.message.edit_text(accounts_text, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("accounts_page:"))
async def accounts_page_handler(callback: CallbackQuery):
    """Обработчик перелистывания страниц аккаунтов"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS or not AdminSession.check_session(user_id):
        await callback.answer("Сессия истекла", show_alert=True)
        return
    
    page = int(callback.data.split(":")[1])
    accounts = db.get_all_accounts()
    await show_accounts_page(callback, accounts, page)
    await callback.answer()

async def show_account_management(callback: CallbackQuery, account_id: int):
    """Показывает управление аккаунтом"""
    user_id = callback.from_user.id
    
    account = db.get_account_by_id(account_id)
    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    is_blocked = db.is_account_blocked(account_id)
    game_data = db.get_game_data(account_id)
    
    account_info = (
        f"🔧 <b>Управление аккаунтом</b>\n\n"
        f"👤 Логин: {account['username']}\n"
        f"🆔 ID: {account_id}\n"
        f"🔐 Пароль: <code>{account['password']}</code>\n"
        f"🗝️ Кодовое слово: <code>{account['recovery_code'] or 'Нет'}</code>\n"
        f"💰 Баланс: {game_data['balance']} Pulse\n"
        f"⭐ VIP: {'✅ Да' if db.check_vip(account_id) else '❌ Нет'}\n"
        f"🚫 Статус: {'Заблокирован' if is_blocked else 'Активен'}\n"
        f"👤 Владелец: {account['owner_user_id'] or 'Неизвестно'}\n"
        f"📅 Создан: {datetime.fromisoformat(account['created_at']).strftime('%d.%m.%Y %H:%M')}\n"
    )
    
    if is_blocked and account['blocked_until']:
        blocked_until = datetime.fromisoformat(account['blocked_until'])
        account_info += f"📅 Блокировка до: {blocked_until.strftime('%d.%m.%Y %H:%M')}\n"
    
    await callback.message.edit_text(
        account_info,
        reply_markup=Keyboards.account_management_keyboard(account_id, user_id)
    )

# Обработчики управления аккаунтами
@dp.callback_query(F.data.startswith("manage_account:"))
async def manage_account_handler(callback: CallbackQuery):
    """Переход к управлению аккаунтом"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS or not AdminSession.check_session(user_id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    account_id = int(callback.data.split(":")[1])
    await show_account_management(callback, account_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("view_login:"))
async def view_login_handler(callback: CallbackQuery):
    """Показывает логин"""
    account_id = int(callback.data.split(":")[1])
    account = db.get_account_by_id(account_id)
    
    await callback.answer(f"Логин: {account['username']}", show_alert=True)

@dp.callback_query(F.data.startswith("view_password:"))
async def view_password_handler(callback: CallbackQuery):
    """Показывает пароль"""
    account_id = int(callback.data.split(":")[1])
    account = db.get_account_by_id(account_id)
    
    await callback.answer(f"Пароль: {account['password']}", show_alert=True)

@dp.callback_query(F.data.startswith("view_recovery:"))
async def view_recovery_handler(callback: CallbackQuery):
    """Показывает кодовое слово"""
    account_id = int(callback.data.split(":")[1])
    account = db.get_account_by_id(account_id)
    
    if account['recovery_code']:
        await callback.answer(f"Кодовое слово: {account['recovery_code']}", show_alert=True)
    else:
        await callback.answer("Кодовое слово не установлено", show_alert=True)

@dp.callback_query(F.data.startswith("block_temp:"))
async def block_temp_handler(callback: CallbackQuery):
    """Временная блокировка аккаунта"""
    user_id = callback.from_user.id
    account_id = int(callback.data.split(":")[1])
    
    user_states[user_id] = {
        "state": RegistrationStates.waiting_for_block_time,
        "account_id": account_id
    }
    
    await callback.message.edit_text(
        "⏰ <b>Временная блокировка аккаунта</b>\n\n"
        "Введите время блокировки в формате:\n"
        "<code>1d 2h 30m</code>\n\n"
        "Примеры:\n"
        "• 1d - на 1 день\n"
        "• 2h - на 2 часа\n"
        "• 30m - на 30 минут\n"
        "• 1d 2h 30m - на 1 день, 2 часа и 30 минут",
        reply_markup=Keyboards.cancel_keyboard(user_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("block_perm:"))
async def block_perm_handler(callback: CallbackQuery):
    """Перманентная блокировка аккаунта"""
    account_id = int(callback.data.split(":")[1])
    db.block_account(account_id, "Перманентная блокировка администратором")
    
    account = db.get_account_by_id(account_id)
    await callback.answer(f"Аккаунт {account['username']} заблокирован навсегда", show_alert=True)
    
    # Обновляем интерфейс
    await show_account_management(callback, account_id)

@dp.callback_query(F.data.startswith("unblock_account:"))
async def unblock_account_handler(callback: CallbackQuery):
    """Разблокировка аккаунта"""
    account_id = int(callback.data.split(":")[1])
    db.unblock_account(account_id)
    
    account = db.get_account_by_id(account_id)
    await callback.answer(f"Аккаунт {account['username']} разблокирован", show_alert=True)
    
    # Обновляем интерфейс
    await show_account_management(callback, account_id)

@dp.callback_query(F.data.startswith("view_sessions:"))
async def view_sessions_handler(callback: CallbackQuery):
    """Показывает сессии аккаунта"""
    user_id = callback.from_user.id
    account_id = int(callback.data.split(":")[1])
    
    sessions = db.get_account_sessions(account_id)
    active_sessions = [s for s in sessions if s['logout_time'] is None]
    
    if not sessions:
        await callback.answer("Нет сессий для этого аккаунта", show_alert=True)
        return
    
    sessions_text = f"📋 <b>Сессии аккаунта</b>\n\n"
    sessions_text += f"🟢 Активных: {len(active_sessions)}\n"
    sessions_text += f"🔴 Всего: {len(sessions)}\n\n"
    
    for i, sess in enumerate(sessions[:5]):
        login_time = datetime.fromisoformat(sess['login_time']).strftime('%d.%m.%Y %H:%M')
        status = "🟢" if sess['logout_time'] is None else "🔴"
        sessions_text += f"{status} {sess['telegram_username'] or 'Без ника'} - {login_time}\n"
    
    await callback.message.edit_text(
        sessions_text,
        reply_markup=Keyboards.session_management_keyboard(account_id, sessions, user_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("logout_all:"))
async def logout_all_handler(callback: CallbackQuery):
    """Выходит всех из аккаунта"""
    account_id = int(callback.data.split(":")[1])
    db.logout_all_from_account(account_id)
    
    account = db.get_account_by_id(account_id)
    await callback.answer(f"Все пользователи вышли из аккаунта {account['username']}", show_alert=True)
    
    # Обновляем интерфейс
    await show_account_management(callback, account_id)

@dp.callback_query(F.data.startswith("logout_user:"))
async def logout_user_handler(callback: CallbackQuery):
    """Выходит конкретного пользователя"""
    data = callback.data.split(":")
    session_id = int(data[1])
    target_user_id = int(data[2])
    
    db.logout_session(session_id)
    await callback.answer("Пользователь вышел из аккаунта", show_alert=True)
    
    # Получаем account_id из сессии
    db.cursor.execute("SELECT account_id FROM sessions WHERE session_id = ?", (session_id,))
    result = db.cursor.fetchone()
    if result:
        account_id = result[0]
        sessions = db.get_account_sessions(account_id)
        
        # Обновляем интерфейс
        callback.data = f"view_sessions:{account_id}"
        await view_sessions_handler(callback)

# Обработчики переключения настроек
@dp.callback_query(F.data.startswith("toggle_"))
async def toggle_setting_handler(callback: CallbackQuery):
    """Переключает настройки аккаунта"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS or not AdminSession.check_session(user_id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    data = callback.data.split(":")
    setting_action = data[0]
    account_id = int(data[1])
    
    setting_name = setting_action.replace("toggle_", "")
    
    # Маппинг названий настроек
    setting_map = {
        "games": "can_play_games",
        "work": "can_work",
        "shop": "can_use_shop",
        "bonus": "can_claim_bonus",
        "vip": "can_use_vip"
    }
    
    if setting_name not in setting_map:
        await callback.answer("Неизвестная настройка", show_alert=True)
        return
    
    db_setting_name = setting_map[setting_name]
    current_settings = db.get_account_settings(account_id)
    new_value = not current_settings[db_setting_name]
    
    db.update_account_setting(account_id, db_setting_name, new_value)
    
    status = "включена" if new_value else "отключена"
    setting_names = {
        "games": "Игры",
        "work": "Работа",
        "shop": "Магазин",
        "bonus": "Бонус",
        "vip": "VIP"
    }
    
    await callback.answer(f"{setting_names[setting_name]} {status}", show_alert=True)
    
    # Обновляем интерфейс
    await show_account_management(callback, account_id)

@dp.callback_query(F.data.startswith("block_owner:"))
async def block_owner_handler(callback: CallbackQuery):
    """Блокирует владельца аккаунта"""
    owner_user_id = int(callback.data.split(":")[1])
    
    db.block_user_accounts(owner_user_id, "Блокировка администратором")
    await callback.answer(f"Владелец {owner_user_id} заблокирован от создания аккаунтов", show_alert=True)

@dp.message(F.text.regexp(r'^\d+ [-+]?\d+$'))
async def admin_balance_change(message: Message):
    """Изменение баланса аккаунта (админ)"""
    user_id = message.from_user.id
    
    if not AdminSession.check_session(user_id) or user_id not in ADMIN_IDS:
        return
    
    try:
        account_id_str, amount_str = message.text.split()
        account_id = int(account_id_str)
        amount = int(amount_str)
        
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
    except:
        await message.answer("❌ Неверный формат")

@dp.message(F.photo | F.video | F.text)
async def admin_broadcast(message: Message):
    """Рассылка сообщений (админ)"""
    user_id = message.from_user.id
    
    if not AdminSession.check_session(user_id) or user_id not in ADMIN_IDS:
        return
    
    # Проверяем, что это ответ на сообщение о рассылке
    if not message.reply_to_message:
        return
    
    reply_text = message.reply_to_message.text or ""
    if "рассылка" not in reply_text.lower():
        return
    
    account_ids = db.get_all_account_ids()
    total = len(account_ids)
    successful = 0
    failed = 0
    
    progress_msg = await message.answer(f"📤 Рассылка начата...\nОтправлено: 0/{total}")
    
    # Получаем все сессии для рассылки
    for i, account_id in enumerate(account_ids):
        # Находим активные сессии для этого аккаунта
        db.cursor.execute(
            "SELECT user_id FROM sessions WHERE account_id = ? AND logout_time IS NULL",
            (account_id,)
        )
        sessions = db.cursor.fetchall()
        
        for session in sessions:
            user_id_target = session[0]
            try:
                if message.photo:
                    await bot.send_photo(user_id_target, message.photo[-1].file_id, caption=message.caption)
                elif message.video:
                    await bot.send_video(user_id_target, message.video.file_id, caption=message.caption)
                else:
                    await bot.send_message(user_id_target, message.text)
                successful += 1
            except Exception as e:
                failed += 1
                logger.error(f"Ошибка при отправке пользователю {user_id_target}: {e}")
        
        # Обновляем прогресс каждые 5 аккаунтов
        if (i + 1) % 5 == 0 or (i + 1) == total:
            await progress_msg.edit_text(f"📤 Рассылка...\nОбработано аккаунтов: {i+1}/{total}")
    
    await progress_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📊 Статистика:\n"
        f"👥 Всего аккаунтов: {total}\n"
        f"✅ Успешно отправлено: {successful}\n"
        f"❌ Не отправлено: {failed}"
    )
    
    await message.answer("📊 Админ-панель", reply_markup=Keyboards.admin_menu())

@dp.callback_query(F.data.startswith("withdraw_treasury:"))
async def withdraw_treasury_handler(callback: CallbackQuery):
    """Вывод казны"""
    if not await ButtonSecurity.check_owner(callback):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    user_id = callback.from_user.id
    treasury = db.get_treasury()
    
    if treasury > 0:
        db.cursor.execute(
            "INSERT INTO transactions (account_id, amount, type) VALUES (?, ?, ?)",
            (0, treasury, "bot_treasury")
        )
        db.reset_treasury()
        
        await callback.message.edit_text(
            f"✅ <b>Казна выведена</b>\n\n"
            f"Сумма {treasury} Pulse записана на баланс бота.",
            reply_markup=Keyboards.admin_menu()
        )
    else:
        await callback.answer("Казна пуста", show_alert=True)
    
    await callback.answer()

# ========== ГРУППОВЫЕ КОМАНДЫ ==========
@dp.message(F.chat.type.in_(["group", "supergroup"]))
async def group_handler(message: Message):
    """Обработчик сообщений в группах"""
    if message.text and message.text.startswith("/"):
        command = message.text.split()[0].lower()
        
        if command in ["/start", "/startpuls", "/registerpuls", "/login", "/logout"]:
            is_admin = False
            try:
                chat_member = await bot.get_chat_member(message.chat.id, message.from_user.id)
                is_admin = chat_member.status in ["administrator", "creator"]
            except:
                pass
            
            user_id = message.from_user.id
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
                    "Доступные команды:\n"
                    "🚀 /start или /startpuls - Начать работу с ботом\n"
                    "📝 /registerpuls - Регистрация (только в ЛС)\n"
                    "🔐 /login - Вход в аккаунт (только в ЛС)\n"
                    "🚪 /logout - Выход из аккаунта\n\n"
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
                
                await message.answer("✅ Вы успешно вышли из аккаунта!")

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция"""
    logger.info("Запуск бота Pulse Bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


