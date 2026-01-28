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
MAX_ACCOUNTS_PER_USER = 3  # Максимум 3 аккаунта на пользователя
ACCOUNT_CREATION_COOLDOWN = 3 * 24 * 3600  # 3 дня между созданием аккаунтов
REGISTRATION_TIMEOUT = 300
LOGIN_TIMEOUT = 400

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
    
    # === Проверка лимитов аккаунтов ===
    def can_user_create_account(self, user_id: int) -> Tuple[bool, str]:
        """Проверяет, может ли пользователь создать новый аккаунт"""
        try:
            # 1. Проверяем блокировку пользователя
            self.cursor.execute(
                "SELECT is_blocked, blocked_until FROM user_blocks WHERE user_id = ?",
                (user_id,)
            )
            block_data = self.cursor.fetchone()
            
            if block_data and block_data[0]:
                blocked_until = None
                if block_data[1]:
                    blocked_until = datetime.fromisoformat(block_data[1])
                
                if blocked_until and blocked_until > datetime.now():
                    remaining = (blocked_until - datetime.now()).total_seconds()
                    days = int(remaining // 86400)
                    hours = int((remaining % 86400) // 3600)
                    minutes = int((remaining % 3600) // 60)
                    return False, f"Вы заблокированы от создания аккаунтов на {days} дней {hours} часов {minutes} минут"
                elif blocked_until is None:  # Перманентная блокировка
                    return False, "Вы заблокированы от создания аккаунтов навсегда"
            
            # 2. Проверяем лимит аккаунтов (максимум 3 на пользователя)
            self.cursor.execute(
                "SELECT COUNT(*) FROM accounts WHERE owner_user_id = ?",
                (user_id,)
            )
            accounts_count = self.cursor.fetchone()[0]
            
            if accounts_count >= MAX_ACCOUNTS_PER_USER:
                return False, f"Вы можете создать максимум {MAX_ACCOUNTS_PER_USER} аккаунта(ов)"
            
            # 3. Проверяем кулдаун 3 дня между созданиями
            self.cursor.execute(
                "SELECT MAX(last_account_creation) FROM accounts WHERE owner_user_id = ?",
                (user_id,)
            )
            result = self.cursor.fetchone()[0]
            
            if result:
                last_creation = datetime.fromisoformat(result)
                next_creation = last_creation + timedelta(seconds=ACCOUNT_CREATION_COOLDOWN)
                
                if next_creation > datetime.now():
                    remaining = (next_creation - datetime.now()).total_seconds()
                    days = int(remaining // 86400)
                    hours = int((remaining % 86400) // 3600)
                    minutes = int((remaining % 3600) // 60)
                    return False, f"Вы можете создать следующий аккаунт через {days} дней {hours} часов {minutes} минут"
            
            return True, "OK"
            
        except Exception as e:
            logger.error(f"Ошибка проверки лимитов: {e}")
            return False, "Ошибка проверки лимитов"
    
    def get_user_accounts_count(self, user_id: int) -> int:
        """Сколько аккаунтов создал пользователь"""
        try:
            self.cursor.execute(
                "SELECT COUNT(*) FROM accounts WHERE owner_user_id = ?",
                (user_id,)
            )
            return self.cursor.fetchone()[0]
        except:
            return 0
    
    def get_user_last_account_creation(self, user_id: int) -> Optional[datetime]:
        """Когда пользователь последний раз создавал аккаунт"""
        try:
            self.cursor.execute(
                "SELECT MAX(last_account_creation) FROM accounts WHERE owner_user_id = ?",
                (user_id,)
            )
            result = self.cursor.fetchone()[0]
            if result:
                return datetime.fromisoformat(result)
        except:
            pass
        return None
    
    # === Создание аккаунта ===
    def create_account(self, username: str, password: str, recovery_code: str = None, owner_user_id: int = None) -> int:
        """Создает новый аккаунт с проверкой лимитов"""
        try:
            # Проверяем уникальность логина
            self.cursor.execute("SELECT 1 FROM accounts WHERE username = ?", (username,))
            if self.cursor.fetchone():
                return None
            
            # Создаем аккаунт
            now = datetime.now()
            self.cursor.execute(
                "INSERT INTO accounts (username, password, recovery_code, owner_user_id, last_account_creation) VALUES (?, ?, ?, ?, ?)",
                (username, password, recovery_code, owner_user_id, now.isoformat())
            )
            account_id = self.cursor.lastrowid
            
            # Создаем игровые данные
            self.cursor.execute("INSERT INTO game_data (account_id) VALUES (?)", (account_id,))
            
            # Создаем настройки
            self.cursor.execute("INSERT INTO account_settings (account_id) VALUES (?)", (account_id,))
            
            self.conn.commit()
            return account_id
            
        except sqlite3.IntegrityError as e:
            logger.error(f"Ошибка создания аккаунта: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка создания аккаунта: {e}")
            return None
    
    # === Управление блокировками ===
    def block_user_accounts(self, user_id: int, reason: str = None, until: datetime = None):
        """Блокирует пользователю создание аккаунтов"""
        try:
            self.cursor.execute(
                "INSERT OR REPLACE INTO user_blocks (user_id, is_blocked, block_reason, blocked_until) VALUES (?, ?, ?, ?)",
                (user_id, True, reason, until.isoformat() if until else None)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка блокировки пользователя: {e}")
    
    def unblock_user_accounts(self, user_id: int):
        """Разблокирует пользователю создание аккаунтов"""
        try:
            self.cursor.execute(
                "UPDATE user_blocks SET is_blocked = FALSE WHERE user_id = ?",
                (user_id,)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка разблокировки пользователя: {e}")
    
    # === Управление сессиями ===
    def create_session(self, user_id: int, account_id: int, telegram_username: str = None) -> int:
        """Создает новую сессию"""
        try:
            # Завершаем все активные сессии этого пользователя
            self.cursor.execute(
                "UPDATE sessions SET logout_time = CURRENT_TIMESTAMP WHERE user_id = ? AND logout_time IS NULL",
                (user_id,)
            )
            
            # Создаем новую сессию
            self.cursor.execute(
                "INSERT INTO sessions (user_id, account_id, telegram_username) VALUES (?, ?, ?)",
                (user_id, account_id, telegram_username)
            )
            session_id = self.cursor.lastrowid
            self.conn.commit()
            return session_id
        except Exception as e:
            logger.error(f"Ошибка создания сессии: {e}")
            return None
    
    def get_active_session(self, user_id: int) -> Optional[Dict]:
        """Получает активную сессию пользователя"""
        try:
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
        except Exception as e:
            logger.error(f"Ошибка получения сессии: {e}")
            return None
    
    def logout_session(self, session_id: int):
        """Завершает сессию"""
        try:
            self.cursor.execute(
                "UPDATE sessions SET logout_time = CURRENT_TIMESTAMP WHERE session_id = ?",
                (session_id,)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка завершения сессии: {e}")
    
    def logout_user_from_account(self, user_id: int, account_id: int):
        """Выходит пользователя из аккаунта"""
        try:
            self.cursor.execute(
                "UPDATE sessions SET logout_time = CURRENT_TIMESTAMP WHERE user_id = ? AND account_id = ? AND logout_time IS NULL",
                (user_id, account_id)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка выхода пользователя: {e}")
    
    # === Игровые данные ===
    def get_game_data(self, account_id: int) -> Dict:
        """Получает игровые данные аккаунта"""
        try:
            self.cursor.execute("SELECT * FROM game_data WHERE account_id = ?", (account_id,))
            columns = [desc[0] for desc in self.cursor.description]
            row = self.cursor.fetchone()
            return dict(zip(columns, row)) if row else None
        except Exception as e:
            logger.error(f"Ошибка получения игровых данных: {e}")
            return None
    
    def update_balance(self, account_id: int, amount: int, transaction_type: str = "other"):
        """Обновляет баланс"""
        try:
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
        except Exception as e:
            logger.error(f"Ошибка обновления баланса: {e}")
    
    def update_last_action(self, account_id: int):
        """Обновляет время последнего действия"""
        try:
            self.cursor.execute(
                "UPDATE game_data SET last_action = CURRENT_TIMESTAMP WHERE account_id = ?",
                (account_id,)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка обновления времени: {e}")
    
    # === Проверка логина ===
    def get_account_by_credentials(self, username: str, password: str) -> Optional[Dict]:
        """Получает аккаунт по логину и паролю"""
        try:
            self.cursor.execute(
                "SELECT * FROM accounts WHERE username = ? AND password = ?",
                (username, password)
            )
            columns = [desc[0] for desc in self.cursor.description]
            row = self.cursor.fetchone()
            return dict(zip(columns, row)) if row else None
        except Exception as e:
            logger.error(f"Ошибка проверки учетных данных: {e}")
            return None
    
    def username_exists(self, username: str) -> bool:
        """Проверяет, существует ли username"""
        try:
            self.cursor.execute("SELECT 1 FROM accounts WHERE username = ?", (username,))
            return self.cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Ошибка проверки username: {e}")
            return True
    
    # === Админ сессии ===
    def create_admin_session(self, user_id: int):
        """Создает админскую сессию"""
        try:
            expires_at = datetime.now() + timedelta(minutes=30)
            self.cursor.execute(
                "INSERT OR REPLACE INTO admin_sessions (user_id, expires_at) VALUES (?, ?)",
                (user_id, expires_at.isoformat())
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка создания админ сессии: {e}")
    
    def check_admin_session(self, user_id: int) -> bool:
        """Проверяет админскую сессию"""
        try:
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
        except Exception as e:
            logger.error(f"Ошибка проверки админ сессии: {e}")
            return False
    
    def delete_admin_session(self, user_id: int):
        """Удаляет админскую сессию"""
        try:
            self.cursor.execute("DELETE FROM admin_sessions WHERE user_id = ?", (user_id,))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка удаления админ сессии: {e}")
    
    # === Права на удаление ===
    def has_delete_permission(self, chat_id: int, user_id: int) -> bool:
        """Проверяет, имеет ли пользователь право удалять сообщения"""
        try:
            self.cursor.execute(
                "SELECT 1 FROM delete_permissions WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            return self.cursor.fetchone() is not None
        except:
            return False
    
    def grant_delete_permission(self, chat_id: int, user_id: int, granted_by: int):
        """Выдает право на удаление сообщений"""
        try:
            self.cursor.execute(
                "INSERT OR REPLACE INTO delete_permissions (chat_id, user_id, granted_by) VALUES (?, ?, ?)",
                (chat_id, user_id, granted_by)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка выдачи прав: {e}")

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

# ========== СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЕЙ ==========
class UserState:
    def __init__(self):
        self.states = {}
        self.timers = {}
    
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
            del self.states[user_id]
    
    def update_data(self, user_id: int, key: str, value: Any):
        """Обновляет данные состояния"""
        if user_id in self.states:
            self.states[user_id]["data"][key] = value

user_state = UserState()

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
    
    in_group = message.chat.type in ["group", "supergroup"]
    
    if in_group:
        # В группах показываем простую клавиатуру
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="🔐 Войти в аккаунт", callback_data=f"auth:login:{user_id}"),
            InlineKeyboardButton(text="📝 Регистрация", callback_data=f"auth:register:{user_id}")
        )
        
        if is_logged_in(user_id):
            builder.row(
                InlineKeyboardButton(text="👤 Профиль", callback_data=f"menu:profile:{user_id}")
            )
        
        await message.answer(welcome_text, reply_markup=builder.as_markup())
    else:
        # В ЛС показываем полное меню
        await message.answer(welcome_text, reply_markup=Keyboards.main_menu(user_id, in_group))

@dp.message(Command("registerpuls"))
async def cmd_register(message: Message):
    """Команда регистрации с проверкой лимитов"""
    user_id = message.from_user.id
    
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
        return
    
    if is_logged_in(user_id):
        await message.answer("Вы уже авторизованы в аккаунте. Сначала выйдите.")
        return
    
    # Проверяем лимиты на создание аккаунтов
    can_create, reason = db.can_user_create_account(user_id)
    if not can_create:
        await message.answer(f"❌ {reason}")
        return
    
    # Показываем информацию о лимитах
    accounts_count = db.get_user_accounts_count(user_id)
    remaining_accounts = MAX_ACCOUNTS_PER_USER - accounts_count
    
    info_text = (
        "📝 <b>Регистрация нового аккаунта</b>\n\n"
        f"📊 <b>Ваши лимиты:</b>\n"
        f"• Создано аккаунтов: {accounts_count}/{MAX_ACCOUNTS_PER_USER}\n"
        f"• Можно создать еще: {remaining_accounts} аккаунт(ов)\n\n"
    )
    
    last_creation = db.get_user_last_account_creation(user_id)
    if last_creation:
        next_creation = last_creation + timedelta(seconds=ACCOUNT_CREATION_COOLDOWN)
        if next_creation > datetime.now():
            remaining = (next_creation - datetime.now()).total_seconds()
            days = int(remaining // 86400)
            hours = int((remaining % 86400) // 3600)
            minutes = int((remaining % 3600) // 60)
            info_text += f"⏰ <b>Следующий аккаунт можно создать через:</b> {days} дней {hours} часов {minutes} минут\n\n"
    
    info_text += (
        "<b>Придумайте логин (имя пользователя):</b>\n"
        "• Минимум 3 символа\n"
        "• Только буквы, цифры и _\n"
        "• Уникальный для системы"
    )
    
    user_state.set_state(user_id, "waiting_for_username")
    
    await message.answer(
        info_text,
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
        reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"])
    )

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
    
    if not state_data:
        # Проверяем админский пароль
        if user_id in ADMIN_IDS and message.reply_to_message and "пароль" in (message.reply_to_message.text or "").lower():
            if text == ADMIN_PASSWORD:
                db.create_admin_session(user_id)
                await message.answer(
                    "✅ <b>Пароль правильный!</b>\n\n"
                    "Доступ к админ-панели разрешен.\n"
                    "Сессия активна 30 минут.",
                    reply_markup=Keyboards.admin_menu(user_id)
                )
            else:
                await message.answer("❌ Неверный пароль!")
        return
    
    state = state_data["state"]
    data = state_data["data"]
    
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
            await message.answer("Главное меню:", reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"]))
            return
        
        # Проверяем лимиты еще раз перед созданием
        can_create, reason = db.can_user_create_account(user_id)
        if not can_create:
            await message.answer(f"❌ {reason}")
            user_state.clear_state(user_id)
            return
        
        account_id = db.create_account(username, password, text, user_id)
        if not account_id:
            await message.answer("Произошла ошибка при создании аккаунта. Попробуйте еще раз.")
            user_state.clear_state(user_id)
            return
        
        # Создаем сессию
        db.create_session(user_id, account_id, message.from_user.username)
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
            await message.answer("Главное меню:", reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"]))
            return
        
        account = db.get_account_by_credentials(username, password)
        if not account:
            await message.answer("Неверный логин или пароль. Попробуйте еще раз или зарегистрируйтесь.")
            user_state.clear_state(user_id)
            await message.answer("Главное меню:", reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"]))
            return
        
        # Создаем сессию
        db.create_session(user_id, account['account_id'], message.from_user.username)
        user_state.clear_state(user_id)
        
        game_data = db.get_game_data(account['account_id'])
        
        await message.answer(
            f"✅ <b>Успешный вход!</b>\n\n"
            f"👤 Аккаунт: <code>{username}</code>\n"
            f"💰 Баланс: {game_data['balance']} Pulse Coins\n\n"
            "Добро пожаловать обратно!",
            reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"])
        )

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
                InlineKeyboardButton(text="🔐 Войти в аккаунт", callback_data=f"auth:login:{user_id}"),
                InlineKeyboardButton(text="📝 Регистрация", callback_data=f"auth:register:{user_id}")
            )
        else:
            builder.row(
                InlineKeyboardButton(text="🎮 Игры", callback_data=f"menu:games:{user_id}"),
            )
            builder.row(
                InlineKeyboardButton(text="💼 Работа", callback_data=f"menu:work:{user_id}"),
            )
            builder.row(
                InlineKeyboardButton(text="🏪 Магазин", callback_data=f"menu:shop:{user_id}"),
            )
            
            builder.row(
                InlineKeyboardButton(text="👤 Профиль", callback_data=f"menu:profile:{user_id}"),
                InlineKeyboardButton(text="🎁 Бонус", callback_data=f"menu:bonus:{user_id}")
            )
            
            builder.row(
                InlineKeyboardButton(text="🚪 Выйти", callback_data=f"auth:logout:{user_id}")
            )
        
        # Кнопка админ-панели только для админа и ТОЛЬКО в ЛС (не в группах)
        if is_admin and not in_group:
            builder.row(
                InlineKeyboardButton(text="🛠 Админ панель", callback_data=f"menu:admin:{user_id}")
            )
        
        return builder.as_markup()
    
    @staticmethod
    def admin_menu(user_id: int) -> InlineKeyboardMarkup:
        """Меню админ-панели"""
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="📊 Статистика", callback_data=f"admin:stats:{user_id}"),
            InlineKeyboardButton(text="👥 Все аккаунты", callback_data=f"admin:accounts:{user_id}")
        )
        builder.row(
            InlineKeyboardButton(text="📋 Все сессии", callback_data=f"admin:sessions:{user_id}"),
            InlineKeyboardButton(text="🔍 Найти аккаунт", callback_data=f"admin:search:{user_id}")
        )
        builder.row(
            InlineKeyboardButton(text="💰 Управление балансами", callback_data=f"admin:balance:{user_id}"),
            InlineKeyboardButton(text="📢 Рассылка", callback_data=f"admin:broadcast:{user_id}")
        )
        builder.row(
            InlineKeyboardButton(text="🏦 Казна", callback_data=f"admin:treasury:{user_id}"),
            InlineKeyboardButton(text="⚙️ Управление", callback_data=f"admin:manage:{user_id}")
        )
        return builder.as_markup()
    
    @staticmethod
    def cancel_keyboard(user_id: int) -> InlineKeyboardMarkup:
        """Клавиатура с отменой"""
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{user_id}")
        )
        return builder.as_markup()
    
    @staticmethod
    def skip_recovery_keyboard(user_id: int) -> InlineKeyboardMarkup:
        """Клавиатура для пропуска кодового слова"""
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"skip_recovery:{user_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{user_id}")
        )
        return builder.as_markup()

# ========== ОБРАБОТЧИКИ КНОПОК ==========
@dp.callback_query(F.data.startswith("auth:"))
async def auth_handler(callback: CallbackQuery):
    """Обработчик кнопок авторизации"""
    try:
        data = callback.data.split(":")
        action = data[1]
        owner_id = int(data[2])
        user_id = callback.from_user.id
        
        # Проверяем владельца кнопки
        if user_id != owner_id:
            await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
            return
        
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
            
            # Проверяем лимиты на создание аккаунтов
            can_create, reason = db.can_user_create_account(user_id)
            if not can_create:
                await callback.answer(f"❌ {reason}", show_alert=True)
                return
            
            user_state.set_state(user_id, "waiting_for_username")
            
            # Показываем информацию о лимитах
            accounts_count = db.get_user_accounts_count(user_id)
            remaining_accounts = MAX_ACCOUNTS_PER_USER - accounts_count
            
            info_text = (
                "📝 <b>Регистрация нового аккаунта</b>\n\n"
                f"📊 <b>Ваши лимиты:</b>\n"
                f"• Создано аккаунтов: {accounts_count}/{MAX_ACCOUNTS_PER_USER}\n"
                f"• Можно создать еще: {remaining_accounts} аккаунт(ов)\n\n"
            )
            
            last_creation = db.get_user_last_account_creation(user_id)
            if last_creation:
                next_creation = last_creation + timedelta(seconds=ACCOUNT_CREATION_COOLDOWN)
                if next_creation > datetime.now():
                    remaining = (next_creation - datetime.now()).total_seconds()
                    days = int(remaining // 86400)
                    hours = int((remaining % 86400) // 3600)
                    minutes = int((remaining % 3600) // 60)
                    info_text += f"⏰ <b>Следующий аккаунт можно создать через:</b> {days} дней {hours} часов {minutes} минут\n\n"
            
            info_text += (
                "<b>Придумайте логин (имя пользователя):</b>\n"
                "• Минимум 3 символа\n"
                "• Только буквы, цифры и _\n"
                "• Уникальный для системы"
            )
            
            await callback.message.edit_text(
                info_text,
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
            
            in_group = callback.message.chat.type in ["group", "supergroup"]
            
            await callback.message.edit_text(
                "✅ <b>Вы успешно вышли из аккаунта!</b>\n\n"
                "Теперь вы можете войти в другой аккаунт или зарегистрировать новый.",
                reply_markup=Keyboards.main_menu(user_id, in_group)
            )
        
    except Exception as e:
        logger.error(f"Ошибка в auth_handler: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith("menu:"))
async def menu_handler(callback: CallbackQuery):
    """Обработчик главного меню"""
    try:
        data = callback.data.split(":")
        action = data[1]
        owner_id = int(data[2])
        user_id = callback.from_user.id
        
        # Проверяем владельца кнопки
        if user_id != owner_id:
            await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
            return
        
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
            else:
                # Показываем админ-панель
                await callback.message.edit_text(
                    "🛠 <b>Админ-панель</b>\n\nВыберите действие:",
                    reply_markup=Keyboards.admin_menu(user_id)
                )
            
            await callback.answer()
            return
        
        # Для остальных действий проверяем авторизацию
        if not is_logged_in(user_id):
            await callback.answer("Сначала войдите в аккаунт!", show_alert=True)
            return
        
        in_group = callback.message.chat.type in ["group", "supergroup"]
        
        if action == "games":
            await callback.message.edit_text(
                "🎮 <b>Игры</b>\n\nВыбери игру:\n"
                "⚡ <b>Импульс</b> - проверь свою реакцию\n"
                "📶 <b>Три сигнала</b> - найди настоящий сигнал\n"
                "🎯 <b>Тактическое решение</b> - переиграй противника\n\n"
                f"Минимальная ставка: {MIN_BET} Pulse Coins",
                reply_markup=None  # Здесь должна быть клавиатура игр
            )
        
        elif action == "work":
            await work_command(callback.message)
        
        elif action == "shop":
            await callback.message.edit_text(
                "🏪 <b>Магазин</b>\n\nДоступные товары:\n"
                "💎 <b>VIP статус</b> - уменьшает все кулдауны в 1.5 раза\n\n"
                "Выбери пакет:",
                reply_markup=None  # Здесь должна быть клавиатура магазина
            )
        
        elif action == "profile":
            await show_profile(callback.message)
        
        elif action == "bonus":
            await bonus_command(callback.message)
        
        elif action == "main":
            await callback.message.edit_text(
                "🎮 <b>Главное меню</b>\n\nВыбери действие:",
                reply_markup=Keyboards.main_menu(user_id, in_group)
            )
        
    except Exception as e:
        logger.error(f"Ошибка в menu_handler: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)
    
    await callback.answer()

@dp.callback_query(F.data.startswith("cancel:"))
async def cancel_handler(callback: CallbackQuery):
    """Обработчик отмены действия"""
    try:
        owner_id = int(callback.data.split(":")[1])
        user_id = callback.from_user.id
        
        if user_id != owner_id:
            await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
            return
        
        user_state.clear_state(user_id)
        
        in_group = callback.message.chat.type in ["group", "supergroup"]
        await callback.message.edit_text(
            "❌ Действие отменено.\n\nГлавное меню:",
            reply_markup=Keyboards.main_menu(user_id, in_group)
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cancel_handler: {e}")
    
    await callback.answer()

@dp.callback_query(F.data.startswith("skip_recovery:"))
async def skip_recovery_handler(callback: CallbackQuery):
    """Пропуск кодового слова"""
    try:
        owner_id = int(callback.data.split(":")[1])
        user_id = callback.from_user.id
        
        if user_id != owner_id:
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
        
        # Проверяем лимиты еще раз перед созданием
        can_create, reason = db.can_user_create_account(user_id)
        if not can_create:
            await callback.answer(f"❌ {reason}", show_alert=True)
            user_state.clear_state(user_id)
            return
        
        account_id = db.create_account(username, password, None, user_id)
        if not account_id:
            await callback.answer("Ошибка создания аккаунта", show_alert=True)
            user_state.clear_state(user_id)
            return
        
        # Создаем сессию
        db.create_session(user_id, account_id, callback.from_user.username)
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
            reply_markup=Keyboards.main_menu(user_id, callback.message.chat.type in ["group", "supergroup"])
        )
        
    except Exception as e:
        logger.error(f"Ошибка в skip_recovery_handler: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)
    
    await callback.answer()

# ========== ОСТАЛЬНЫЕ ФУНКЦИИ ==========
async def work_command(message: Message):
    """Обработчик работы"""
    user_id = message.from_user.id
    
    if not is_logged_in(user_id):
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    session = get_user_session(user_id)
    account_id = session['account_id']
    
    # Проверяем кулдаун
    game_data = db.get_game_data(account_id)
    
    if game_data['last_work']:
        last_work = datetime.fromisoformat(game_data['last_work'])
        next_work = last_work + timedelta(seconds=WORK_COOLDOWN)
        if next_work > datetime.now():
            remaining = (next_work - datetime.now()).total_seconds()
            await message.answer(
                f"Работа пока недоступна.\n"
                f"Осталось: {int(remaining // 60)} минут {int(remaining % 60)} секунд"
            )
            return
    
    # Проверяем лимит работ
    if game_data['work_count'] >= WORK_LIMIT:
        await message.answer(
            f"Достигнут лимит работ ({WORK_LIMIT}).\n"
            f"Следующая работа через: {format_time(WORK_LIMIT_COOLDOWN)}"
        )
        return
    
    # Выполняем работу
    reward = random.randint(20, 100)
    db.update_balance(account_id, reward, "work")
    db.update_last_action(account_id)
    
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
        reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"])
    )

async def bonus_command(message: Message):
    """Обработчик бонуса"""
    user_id = message.from_user.id
    
    if not is_logged_in(user_id):
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    session = get_user_session(user_id)
    account_id = session['account_id']
    
    # Проверяем кулдаун
    game_data = db.get_game_data(account_id)
    
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
    db.update_last_action(account_id)
    
    db.cursor.execute(
        "UPDATE game_data SET last_bonus = CURRENT_TIMESTAMP WHERE account_id = ?",
        (account_id,)
    )
    db.conn.commit()
    
    await message.answer(
        f"🎁 <b>Ежедневный бонус!</b>\n\n"
        f"Ты получил: {BONUS_AMOUNT} Pulse Coins\n"
        f"Баланс: {game_data['balance'] + BONUS_AMOUNT} Pulse",
        reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"])
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
        f"💰 Баланс: {game_data['balance']} Pulse Coins\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"🎮 Игр сыграно: {game_data['games_played']}\n"
        f"💼 Работ выполнено: {game_data['work_count']}\n"
        f"💸 Потрачено: {game_data['total_spent']} Pulse\n\n"
        f"⏰ <b>Таймеры:</b>\n"
        f"🎁 Бонус: {bonus_time}\n"
        f"💼 Работа: {work_time}"
    )
    
    await message.answer(profile_text, reply_markup=Keyboards.main_menu(user_id, message.chat.type in ["group", "supergroup"]))

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция"""
    logger.info("Запуск бота Pulse Bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
