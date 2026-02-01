import asyncio
import logging
import sqlite3
import random
import re
import json
import time
import string
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union
from enum import Enum
from dataclasses import dataclass, asdict
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, ReplyKeyboardRemove, ReplyKeyboardMarkup,
    KeyboardButton, FSInputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters.state import StateFilter
from aiogram.methods import DeleteMessage
from aiogram.utils.media_group import MediaGroupBuilder

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8557190026:AAGnqxtrAyZz-huihyGctKWNHgjt7w9lQTo"
ADMIN_IDS = [6708209142]
BOT_USERNAME = "@PulsOfficialManager_bot"

# Настройки по умолчанию
DEFAULT_SETTINGS = {
    "cooldown_pm": 3,
    "cooldown_group": 5,
    "bonus_amount": 50,
    "bonus_cooldown": 24 * 3600,
    "work_cooldown": 30 * 60,
    "work_limit": 5,
    "work_limit_cooldown": 10 * 3600,
    "game_limit": 5,
    "game_limit_cooldown": 3 * 3600,
    "min_bet": 25,
    "vip_multiplier": 1.5,
    "max_accounts_per_user": 3,
    "account_creation_cooldown": 3 * 24 * 3600,
    "registration_timeout": 300,
    "login_timeout": 400,
    "draw_participation_cooldown": 3600,
    "max_active_draws": 10,
}

VIP_PACKAGES = {
    30: 1000,
    90: 2940,
    150: 4850,
    365: 11400
}

ADMIN_PASSWORD = "vanezypulsbot13579"
WORK_TYPES = ["программист", "дизайнер", "менеджер", "тестировщик", "аналитик"]
WORK_REWARDS = {
    "программист": {"min": 80, "max": 150},
    "дизайнер": {"min": 60, "max": 120},
    "менеджер": {"min": 50, "max": 100},
    "тестировщик": {"min": 40, "max": 90},
    "аналитик": {"min": 70, "max": 130},
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== КЛАССЫ ДАННЫХ ==========
class GameType(Enum):
    RANDOM = "random"
    CHOICE = "choice"
    REACTION = "reaction"
    INPUT = "input"
    SCENARIO = "scenario"

class DrawStatus(Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    PROCESSING = "processing"

class DiscountType(Enum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"

class UserRole(Enum):
    USER = "user"
    VIP = "vip"
    MODERATOR = "moderator"
    ADMIN = "admin"

class TransactionType(Enum):
    GAME_WIN = "game_win"
    GAME_LOSS = "game_loss"
    WORK = "work"
    BONUS = "bonus"
    SHOP_PURCHASE = "shop_purchase"
    ADMIN_ADD = "admin_add"
    ADMIN_REMOVE = "admin_remove"
    DRAW_WIN = "draw_win"
    REFERRAL = "referral"

@dataclass
class GameResult:
    win: bool
    amount: int
    description: str
    game_type: str
    timestamp: datetime

@dataclass
class WorkTask:
    work_type: str
    description: str
    question: str
    correct_answer: str
    reward: int
    difficulty: str

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('pulse_bot.db', check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.create_tables()
        self.migrate_tables()
        self.initialize_default_settings()
    
    def create_tables(self):
        """Создание всех таблиц"""
        tables = [
            # Telegram пользователи
            '''
            CREATE TABLE IF NOT EXISTS telegram_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                referrals_count INTEGER DEFAULT 0,
                is_banned BOOLEAN DEFAULT FALSE,
                ban_reason TEXT
            )
            ''',
            # Аккаунты
            '''
            CREATE TABLE IF NOT EXISTS accounts (
                account_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                recovery_code TEXT,
                owner_user_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_blocked BOOLEAN DEFAULT FALSE,
                block_reason TEXT,
                blocked_until TIMESTAMP,
                last_login TIMESTAMP,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                FOREIGN KEY (owner_user_id) REFERENCES telegram_users(user_id),
                FOREIGN KEY (referred_by) REFERENCES accounts(account_id)
            )
            ''',
            # Профили
            '''
            CREATE TABLE IF NOT EXISTS profiles (
                profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER UNIQUE NOT NULL,
                balance INTEGER DEFAULT 0,
                total_earned INTEGER DEFAULT 0,
                total_spent INTEGER DEFAULT 0,
                games_played INTEGER DEFAULT 0,
                games_won INTEGER DEFAULT 0,
                work_count INTEGER DEFAULT 0,
                vip_level INTEGER DEFAULT 0,
                vip_until TIMESTAMP,
                experience INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id)
            )
            ''',
            # Настройки аккаунтов
            '''
            CREATE TABLE IF NOT EXISTS account_settings (
                setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                can_play_games BOOLEAN DEFAULT TRUE,
                can_work BOOLEAN DEFAULT TRUE,
                can_use_shop BOOLEAN DEFAULT TRUE,
                can_claim_bonus BOOLEAN DEFAULT TRUE,
                can_participate_draws BOOLEAN DEFAULT TRUE,
                can_use_referral BOOLEAN DEFAULT TRUE,
                notifications_enabled BOOLEAN DEFAULT TRUE,
                language TEXT DEFAULT 'ru',
                FOREIGN KEY (account_id) REFERENCES accounts(account_id)
            )
            ''',
            # Сессии
            '''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                ip_address TEXT,
                user_agent TEXT,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id),
                FOREIGN KEY (user_id) REFERENCES telegram_users(user_id)
            )
            ''',
            # Логи действий
            '''
            CREATE TABLE IF NOT EXISTS action_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                action_name TEXT NOT NULL,
                details TEXT,
                ip_address TEXT,
                user_agent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id),
                FOREIGN KEY (user_id) REFERENCES telegram_users(user_id)
            )
            ''',
            # Транзакции
            '''
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                type TEXT NOT NULL,
                description TEXT,
                reference_id TEXT,
                balance_before INTEGER,
                balance_after INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id)
            )
            ''',
            # История игр
            '''
            CREATE TABLE IF NOT EXISTS game_history (
                game_id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                game_type TEXT NOT NULL,
                bet_amount INTEGER NOT NULL,
                win_amount INTEGER,
                is_win BOOLEAN,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id)
            )
            ''',
            # Розыгрыши
            '''
            CREATE TABLE IF NOT EXISTS draws (
                draw_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                prize_type TEXT NOT NULL,
                prize_value INTEGER,
                prize_text TEXT,
                winners_count INTEGER DEFAULT 1,
                participants_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                starts_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ends_at TIMESTAMP,
                completed_at TIMESTAMP,
                draw_code TEXT UNIQUE,
                FOREIGN KEY (created_by) REFERENCES telegram_users(user_id)
            )
            ''',
            # Участники розыгрышей
            '''
            CREATE TABLE IF NOT EXISTS draw_participants (
                participant_id INTEGER PRIMARY KEY AUTOINCREMENT,
                draw_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                is_winner BOOLEAN DEFAULT FALSE,
                prize_received BOOLEAN DEFAULT FALSE,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (draw_id) REFERENCES draws(draw_id),
                FOREIGN KEY (account_id) REFERENCES accounts(account_id),
                UNIQUE(draw_id, account_id)
            )
            ''',
            # Скидки
            '''
            CREATE TABLE IF NOT EXISTS discounts (
                discount_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                discount_type TEXT NOT NULL,
                value REAL NOT NULL,
                target_type TEXT NOT NULL,
                target_id INTEGER,
                starts_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ends_at TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                max_uses INTEGER DEFAULT NULL,
                used_count INTEGER DEFAULT 0,
                FOREIGN KEY (created_by) REFERENCES telegram_users(user_id)
            )
            ''',
            # Настройки бота
            '''
            CREATE TABLE IF NOT EXISTS bot_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                description TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_by INTEGER
            )
            ''',
            # Права на удаление
            '''
            CREATE TABLE IF NOT EXISTS delete_permissions (
                permission_id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                granted_by INTEGER NOT NULL,
                granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                FOREIGN KEY (user_id) REFERENCES telegram_users(user_id),
                FOREIGN KEY (granted_by) REFERENCES telegram_users(user_id),
                UNIQUE(chat_id, user_id)
            )
            ''',
            # Кулдауны
            '''
            CREATE TABLE IF NOT EXISTS cooldowns (
                cooldown_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                ends_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id),
                FOREIGN KEY (user_id) REFERENCES telegram_users(user_id)
            )
            ''',
            # История работы
            '''
            CREATE TABLE IF NOT EXISTS work_history (
                work_id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                work_type TEXT NOT NULL,
                earnings INTEGER NOT NULL,
                task_details TEXT,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id)
            )
            ''',
            # Магазин (товары)
            '''
            CREATE TABLE IF NOT EXISTS shop_items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                item_type TEXT NOT NULL,
                price INTEGER NOT NULL,
                vip_price INTEGER,
                duration_days INTEGER,
                effect_value INTEGER,
                is_active BOOLEAN DEFAULT TRUE,
                max_purchases INTEGER DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sort_order INTEGER DEFAULT 0
            )
            ''',
            # Покупки
            '''
            CREATE TABLE IF NOT EXISTS purchases (
                purchase_id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                price_paid INTEGER NOT NULL,
                purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id),
                FOREIGN KEY (item_id) REFERENCES shop_items(item_id)
            )
            ''',
            # Реферальные коды
            '''
            CREATE TABLE IF NOT EXISTS referral_codes (
                code_id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                code TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                uses_count INTEGER DEFAULT 0,
                max_uses INTEGER DEFAULT NULL,
                expires_at TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                reward_amount INTEGER DEFAULT 100,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id)
            )
            ''',
            # Уведомления
            '''
            CREATE TABLE IF NOT EXISTS notifications (
                notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                action_url TEXT,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id),
                FOREIGN KEY (user_id) REFERENCES telegram_users(user_id)
            )
            ''',
            # Чат-группы
            '''
            CREATE TABLE IF NOT EXISTS chat_groups (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                settings TEXT DEFAULT '{}'
            )
            ''',
            # Статистика игр
            '''
            CREATE TABLE IF NOT EXISTS game_statistics (
                stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_type TEXT NOT NULL,
                total_plays INTEGER DEFAULT 0,
                total_wins INTEGER DEFAULT 0,
                total_bets INTEGER DEFAULT 0,
                total_payouts INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''',
        ]
        
        for table_sql in tables:
            try:
                self.cursor.execute(table_sql)
            except sqlite3.Error as e:
                logger.error(f"Ошибка создания таблицы: {e}")
        
        self.conn.commit()
        
        # Инициализируем товары магазина
        self.initialize_shop_items()
    
    def migrate_tables(self):
        """Миграция старых таблиц к новой структуре"""
        try:
            # Проверяем существование старых таблиц и переносим данные
            self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='game_data'")
            if self.cursor.fetchone():
                # Мигрируем данные из game_data в profiles
                self.cursor.execute("""
                    INSERT OR IGNORE INTO profiles (account_id, balance, games_played, work_count, total_spent)
                    SELECT account_id, balance, games_played, work_count, total_spent 
                    FROM game_data
                """)
                
            # Проверяем наличие столбцов в accounts
            self.cursor.execute("PRAGMA table_info(accounts)")
            columns = [col[1] for col in self.cursor.fetchall()]
            
            if 'owner_user_id' not in columns:
                self.cursor.execute("ALTER TABLE accounts ADD COLUMN owner_user_id INTEGER")
            
            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка миграции: {e}")
    
    def initialize_default_settings(self):
        """Инициализация настроек по умолчанию"""
        for key, value in DEFAULT_SETTINGS.items():
            self.cursor.execute(
                "INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES (?, ?)",
                (key, str(value))
            )
        self.conn.commit()
    
    def initialize_shop_items(self):
        """Инициализация товаров магазина"""
        shop_items = [
            # VIP пакеты
            ("VIP на 30 дней", "VIP статус на 30 дней", "vip", 1000, 900, 30, None, 100),
            ("VIP на 90 дней", "VIP статус на 90 дней", "vip", 2940, 2646, 90, None, 200),
            ("VIP на 150 дней", "VIP статус на 150 дней", "vip", 4850, 4365, 150, None, 300),
            ("VIP на 365 дней", "VIP статус на 365 дней", "vip", 11400, 10260, 365, None, 400),
            
            # Бустеры
            ("Бустер заработка x2", "Удваивает заработок с работы на 24 часа", "booster", 500, 450, 1, 2, 10),
            ("Бустер удачи x1.5", "Увеличивает шанс выигрыша на 50% на 24 часа", "booster", 750, 675, 1, 1.5, 20),
            ("Бустер опыта x2", "Удваивает получаемый опыт на 24 часа", "booster", 300, 270, 1, 2, 30),
            
            # Предметы
            ("Сундук с сокровищами", "Случайная награда от 100 до 1000 Pulse", "chest", 250, 225, None, None, 40),
            ("Ключ удачи", "Гарантированный выигрыш в следующей игре", "item", 1500, 1350, None, None, 50),
        ]
        
        for i, item in enumerate(shop_items):
            self.cursor.execute("""
                INSERT OR IGNORE INTO shop_items 
                (name, description, item_type, price, vip_price, duration_days, effect_value, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (*item, i*10))
        
        self.conn.commit()
    
    # === Управление пользователями ===
    def create_or_update_telegram_user(self, user: types.User):
        """Создает или обновляет пользователя Telegram"""
        self.cursor.execute("""
            INSERT OR REPLACE INTO telegram_users 
            (user_id, username, first_name, last_name, language_code, last_seen)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (user.id, user.username, user.first_name, user.last_name, user.language_code))
        
        # Создаем реферальный код если его нет
        self.cursor.execute("""
            INSERT OR IGNORE INTO accounts (username, password, owner_user_id, referral_code)
            SELECT ?, ?, ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM accounts WHERE owner_user_id = ?)
        """, (f"temp_{user.id}", "temp", user.id, f"ref_{user.id}", user.id))
        
        self.conn.commit()
    
    def create_account(self, username: str, password: str, owner_id: int, recovery_code: str = None, referred_by: int = None) -> Optional[int]:
        """Создает новый аккаунт"""
        try:
            # Генерируем реферальный код
            referral_code = f"ref_{owner_id}_{int(time.time())}"
            
            self.cursor.execute("""
                INSERT INTO accounts (username, password, recovery_code, owner_user_id, referral_code, referred_by)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (username, password, recovery_code, owner_id, referral_code, referred_by))
            
            account_id = self.cursor.lastrowid
            
            # Создаем профиль
            self.cursor.execute("INSERT INTO profiles (account_id) VALUES (?)", (account_id,))
            
            # Создаем настройки
            self.cursor.execute("INSERT INTO account_settings (account_id) VALUES (?)", (account_id,))
            
            # Начисляем бонус приглашенному
            self.cursor.execute("UPDATE profiles SET balance = balance + 100 WHERE account_id = ?", (account_id,))
            self.add_transaction(account_id, 100, TransactionType.REFERRAL.value, "Бонус за регистрацию")
            
            # Начисляем бонус пригласившему
            if referred_by:
                self.cursor.execute("UPDATE profiles SET balance = balance + 200 WHERE account_id = ?", (referred_by,))
                self.add_transaction(referred_by, 200, TransactionType.REFERRAL.value, "Бонус за приглашение")
                
                # Увеличиваем счетчик рефералов
                self.cursor.execute("""
                    UPDATE telegram_users SET referrals_count = referrals_count + 1 
                    WHERE user_id = (SELECT owner_user_id FROM accounts WHERE account_id = ?)
                """, (referred_by,))
            
            self.conn.commit()
            
            # Логируем
            self.log_action(owner_id, account_id, "account_creation", f"Создан аккаунт {username}")
            
            return account_id
        except sqlite3.IntegrityError as e:
            logger.error(f"Ошибка создания аккаунта: {e}")
            return None
    
    def get_account(self, username: str = None, account_id: int = None) -> Optional[Dict]:
        """Получает аккаунт"""
        if username:
            self.cursor.execute("SELECT * FROM accounts WHERE username = ?", (username,))
        elif account_id:
            self.cursor.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,))
        else:
            return None
        
        row = self.cursor.fetchone()
        return dict(row) if row else None
    
    def verify_account(self, username: str, password: str) -> Optional[Dict]:
        """Проверяет учетные данные"""
        self.cursor.execute("""
            SELECT * FROM accounts 
            WHERE username = ? AND password = ? AND is_blocked = FALSE
        """, (username, password))
        
        row = self.cursor.fetchone()
        if row:
            account = dict(row)
            
            # Обновляем время последнего входа
            self.cursor.execute("""
                UPDATE accounts SET last_login = CURRENT_TIMESTAMP 
                WHERE account_id = ?
            """, (account['account_id'],))
            
            self.conn.commit()
            return account
        
        return None
    
    def get_accounts_by_owner(self, owner_id: int) -> List[Dict]:
        """Получает все аккаунты пользователя"""
        self.cursor.execute("""
            SELECT a.*, p.balance, p.vip_until 
            FROM accounts a 
            LEFT JOIN profiles p ON a.account_id = p.account_id
            WHERE a.owner_user_id = ? 
            ORDER BY a.created_at DESC
        """, (owner_id,))
        
        return [dict(row) for row in self.cursor.fetchall()]
    
    def get_account_count_by_owner(self, owner_id: int) -> int:
        """Количество аккаунтов у пользователя"""
        self.cursor.execute("SELECT COUNT(*) FROM accounts WHERE owner_user_id = ?", (owner_id,))
        return self.cursor.fetchone()[0]
    
    # === Управление сессиями ===
    def create_session(self, user_id: int, account_id: int, duration_hours: int = 720) -> int:
        """Создает новую сессию (30 дней по умолчанию)"""
        expires_at = datetime.now() + timedelta(hours=duration_hours)
        
        # Деактивируем старые сессии
        self.cursor.execute("""
            UPDATE sessions SET is_active = FALSE 
            WHERE user_id = ? AND is_active = TRUE
        """, (user_id,))
        
        # Создаем новую сессию
        self.cursor.execute("""
            INSERT INTO sessions (user_id, account_id, expires_at)
            VALUES (?, ?, ?)
        """, (user_id, account_id, expires_at.isoformat()))
        
        session_id = self.cursor.lastrowid
        self.conn.commit()
        
        # Логируем
        self.log_action(user_id, account_id, "login", "Вход в аккаунт")
        
        return session_id
    
    def get_active_session(self, user_id: int) -> Optional[Dict]:
        """Получает активную сессию"""
        self.cursor.execute("""
            SELECT s.*, a.username, a.owner_user_id, p.balance, p.vip_until,
                   (p.vip_until IS NOT NULL AND p.vip_until > CURRENT_TIMESTAMP) as is_vip
            FROM sessions s
            JOIN accounts a ON s.account_id = a.account_id
            LEFT JOIN profiles p ON s.account_id = p.account_id
            WHERE s.user_id = ? AND s.is_active = TRUE 
            AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP)
            ORDER BY s.created_at DESC LIMIT 1
        """, (user_id,))
        
        row = self.cursor.fetchone()
        return dict(row) if row else None
    
    def logout_session(self, user_id: int) -> bool:
        """Выход из аккаунта"""
        self.cursor.execute("""
            UPDATE sessions SET is_active = FALSE 
            WHERE user_id = ? AND is_active = TRUE
        """, (user_id,))
        
        affected = self.cursor.rowcount
        self.conn.commit()
        
        if affected > 0:
            session = self.get_active_session(user_id)
            if session:
                self.log_action(user_id, session['account_id'], "logout", "Выход из аккаунта")
        
        return affected > 0
    
    # === Профили и балансы ===
    def get_profile(self, account_id: int) -> Optional[Dict]:
        """Получает профиль аккаунта"""
        self.cursor.execute("""
            SELECT p.*, a.username, a.owner_user_id, a.referral_code,
                   (SELECT COUNT(*) FROM accounts WHERE referred_by = a.account_id) as referrals_count
            FROM profiles p
            JOIN accounts a ON p.account_id = a.account_id
            WHERE p.account_id = ?
        """, (account_id,))
        
        row = self.cursor.fetchone()
        return dict(row) if row else None
    
    def update_balance(self, account_id: int, amount: int, transaction_type: str, description: str = None, reference_id: str = None) -> bool:
        """Обновляет баланс"""
        try:
            # Получаем текущий баланс
            self.cursor.execute("SELECT balance FROM profiles WHERE account_id = ?", (account_id,))
            result = self.cursor.fetchone()
            
            if not result:
                return False
            
            current_balance = result['balance']
            
            if current_balance + amount < 0:
                return False
            
            # Обновляем баланс
            self.cursor.execute("""
                UPDATE profiles 
                SET balance = balance + ?, 
                    updated_at = CURRENT_TIMESTAMP,
                    total_earned = total_earned + CASE WHEN ? > 0 THEN ? ELSE 0 END,
                    total_spent = total_spent + CASE WHEN ? < 0 THEN ABS(?) ELSE 0 END
                WHERE account_id = ?
            """, (amount, amount, amount, amount, amount, account_id))
            
            # Добавляем транзакцию
            self.add_transaction(account_id, amount, transaction_type, description, reference_id, current_balance, current_balance + amount)
            
            # Логируем
            action_type = "deposit" if amount > 0 else "withdraw"
            self.log_action(None, account_id, "transaction", 
                          f"{action_type}: {amount} Pulse ({transaction_type})")
            
            return True
        except Exception as e:
            logger.error(f"Ошибка обновления баланса: {e}")
            self.conn.rollback()
            return False
    
    def add_transaction(self, account_id: int, amount: int, transaction_type: str, 
                       description: str = None, reference_id: str = None,
                       balance_before: int = None, balance_after: int = None):
        """Добавляет запись о транзакции"""
        if balance_before is None or balance_after is None:
            self.cursor.execute("SELECT balance FROM profiles WHERE account_id = ?", (account_id,))
            balance = self.cursor.fetchone()['balance']
            balance_before = balance - amount
            balance_after = balance
        
        self.cursor.execute("""
            INSERT INTO transactions 
            (account_id, amount, type, description, reference_id, balance_before, balance_after)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (account_id, amount, transaction_type, description, reference_id, balance_before, balance_after))
        
        self.conn.commit()
    
    def get_transactions(self, account_id: int, limit: int = 20) -> List[Dict]:
        """Получает историю транзакций"""
        self.cursor.execute("""
            SELECT * FROM transactions 
            WHERE account_id = ? 
            ORDER BY created_at DESC 
            LIMIT ?
        """, (account_id, limit))
        
        return [dict(row) for row in self.cursor.fetchall()]
    
    # === Игры ===
    def record_game(self, account_id: int, game_type: str, bet: int, win: bool, 
                   win_amount: int = None, details: str = None) -> int:
        """Записывает результат игры"""
        self.cursor.execute("""
            INSERT INTO game_history (account_id, game_type, bet_amount, is_win, win_amount, details)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (account_id, game_type, bet, win, win_amount, details))
        
        game_id = self.cursor.lastrowid
        
        # Обновляем статистику профиля
        self.cursor.execute("""
            UPDATE profiles 
            SET games_played = games_played + 1,
                games_won = games_won + ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE account_id = ?
        """, (1 if win else 0, account_id))
        
        # Обновляем общую статистику игр
        self.cursor.execute("""
            INSERT OR REPLACE INTO game_statistics (game_type, total_plays, total_wins, total_bets, total_payouts, updated_at)
            VALUES (
                ?,
                COALESCE((SELECT total_plays FROM game_statistics WHERE game_type = ?), 0) + 1,
                COALESCE((SELECT total_wins FROM game_statistics WHERE game_type = ?), 0) + ?,
                COALESCE((SELECT total_bets FROM game_statistics WHERE game_type = ?), 0) + ?,
                COALESCE((SELECT total_payouts FROM game_statistics WHERE game_type = ?), 0) + ?,
                CURRENT_TIMESTAMP
            )
        """, (game_type, game_type, game_type, 1 if win else 0, game_type, bet, game_type, win_amount if win else 0))
        
        self.conn.commit()
        
        # Логируем
        result = "выиграл" if win else "проиграл"
        self.log_action(None, account_id, "game", f"{game_type}: {result} {bet} Pulse", details)
        
        return game_id
    
    def get_game_statistics(self, account_id: int = None, game_type: str = None) -> Dict:
        """Получает статистику игр"""
        stats = {}
        
        if account_id:
            # Статистика пользователя
            self.cursor.execute("""
                SELECT 
                    COUNT(*) as total_games,
                    SUM(CASE WHEN is_win THEN 1 ELSE 0 END) as wins,
                    SUM(bet_amount) as total_bet,
                    SUM(CASE WHEN is_win THEN win_amount ELSE 0 END) as total_won,
                    AVG(CASE WHEN is_win THEN 1.0 ELSE 0.0 END) * 100 as win_rate
                FROM game_history 
                WHERE account_id = ?
            """, (account_id,))
            
            row = self.cursor.fetchone()
            if row:
                stats = dict(row)
        
        elif game_type:
            # Статистика по типу игры
            self.cursor.execute("""
                SELECT * FROM game_statistics WHERE game_type = ?
            """, (game_type,))
            
            row = self.cursor.fetchone()
            if row:
                stats = dict(row)
        
        return stats
    
    # === Розыгрыши ===
    def create_draw(self, name: str, description: str, prize_type: str, 
                   prize_value: int = None, prize_text: str = None,
                   winners_count: int = 1, ends_at: datetime = None, 
                   created_by: int = None) -> Optional[int]:
        """Создает розыгрыш"""
        try:
            draw_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            
            self.cursor.execute("""
                INSERT INTO draws 
                (name, description, prize_type, prize_value, prize_text, 
                 winners_count, ends_at, created_by, draw_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, description, prize_type, prize_value, prize_text, 
                  winners_count, ends_at.isoformat() if ends_at else None, 
                  created_by, draw_code))
            
            draw_id = self.cursor.lastrowid
            self.conn.commit()
            
            # Логируем
            self.log_action(created_by, None, "draw_creation", f"Создан розыгрыш: {name}")
            
            return draw_id
        except Exception as e:
            logger.error(f"Ошибка создания розыгрыша: {e}")
            return None
    
    def get_draw(self, draw_id: int = None, draw_code: str = None) -> Optional[Dict]:
        """Получает розыгрыш"""
        if draw_id:
            self.cursor.execute("SELECT * FROM draws WHERE draw_id = ?", (draw_id,))
        elif draw_code:
            self.cursor.execute("SELECT * FROM draws WHERE draw_code = ?", (draw_code,))
        else:
            return None
        
        row = self.cursor.fetchone()
        return dict(row) if row else None
    
    def get_active_draws(self, limit: int = 10) -> List[Dict]:
        """Получает активные розыгрыши"""
        self.cursor.execute("""
            SELECT d.*, 
                   (SELECT COUNT(*) FROM draw_participants WHERE draw_id = d.draw_id) as current_participants,
                   u.username as creator_username
            FROM draws d
            LEFT JOIN telegram_users u ON d.created_by = u.user_id
            WHERE d.status = 'active' 
            AND (d.ends_at IS NULL OR d.ends_at > CURRENT_TIMESTAMP)
            ORDER BY d.created_at DESC 
            LIMIT ?
        """, (limit,))
        
        return [dict(row) for row in self.cursor.fetchall()]
    
    def participate_in_draw(self, draw_id: int, account_id: int) -> bool:
        """Участие в розыгрыше"""
        try:
            # Проверяем, не участвует ли уже
            self.cursor.execute("""
                SELECT 1 FROM draw_participants 
                WHERE draw_id = ? AND account_id = ?
            """, (draw_id, account_id))
            
            if self.cursor.fetchone():
                return False
            
            # Проверяем лимит участников
            self.cursor.execute("SELECT winners_count FROM draws WHERE draw_id = ?", (draw_id,))
            draw = self.cursor.fetchone()
            
            if not draw:
                return False
            
            # Участвуем
            self.cursor.execute("""
                INSERT INTO draw_participants (draw_id, account_id)
                VALUES (?, ?)
            """, (draw_id, account_id))
            
            # Увеличиваем счетчик
            self.cursor.execute("""
                UPDATE draws 
                SET participants_count = participants_count + 1 
                WHERE draw_id = ?
            """, (draw_id,))
            
            self.conn.commit()
            
            # Логируем
            self.log_action(None, account_id, "draw_participation", f"Участие в розыгрыше #{draw_id}")
            
            return True
        except Exception as e:
            logger.error(f"Ошибка участия в розыгрыше: {e}")
            return False
    
    def complete_draw(self, draw_id: int) -> bool:
        """Завершает розыгрыш и выбирает победителей"""
        try:
            # Получаем информацию о розыгрыше
            draw = self.get_draw(draw_id)
            if not draw or draw['status'] != DrawStatus.ACTIVE.value:
                return False
            
            # Получаем участников
            self.cursor.execute("""
                SELECT account_id FROM draw_participants 
                WHERE draw_id = ? 
                ORDER BY RANDOM() 
                LIMIT ?
            """, (draw_id, draw['winners_count']))
            
            winners = [row['account_id'] for row in self.cursor.fetchall()]
            
            # Отмечаем победителей
            for winner_id in winners:
                self.cursor.execute("""
                    UPDATE draw_participants 
                    SET is_winner = TRUE 
                    WHERE draw_id = ? AND account_id = ?
                """, (draw_id, winner_id))
                
                # Выдаем приз
                if draw['prize_type'] == 'coins':
                    self.update_balance(winner_id, draw['prize_value'], 
                                      TransactionType.DRAW_WIN.value, 
                                      f"Победа в розыгрыше: {draw['name']}")
            
            # Обновляем статус розыгрыша
            self.cursor.execute("""
                UPDATE draws 
                SET status = 'completed', completed_at = CURRENT_TIMESTAMP 
                WHERE draw_id = ?
            """, (draw_id,))
            
            self.conn.commit()
            
            # Логируем
            self.log_action(None, None, "draw_completion", 
                          f"Завершен розыгрыш #{draw_id}, победителей: {len(winners)}")
            
            return True
        except Exception as e:
            logger.error(f"Ошибка завершения розыгрыша: {e}")
            return False
    
    # === Скидки ===
    def create_discount(self, name: str, description: str, discount_type: str, value: float,
                       target_type: str, target_id: int = None, ends_at: datetime = None,
                       max_uses: int = None, created_by: int = None) -> Optional[int]:
        """Создает скидку"""
        try:
            self.cursor.execute("""
                INSERT INTO discounts 
                (name, description, discount_type, value, target_type, target_id, ends_at, max_uses, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, description, discount_type, value, target_type, target_id,
                  ends_at.isoformat() if ends_at else None, max_uses, created_by))
            
            discount_id = self.cursor.lastrowid
            self.conn.commit()
            
            # Логируем
            self.log_action(created_by, None, "discount_creation", f"Создана скидка: {name}")
            
            return discount_id
        except Exception as e:
            logger.error(f"Ошибка создания скидки: {e}")
            return None
    
    def get_active_discounts(self, target_type: str = None, target_id: int = None) -> List[Dict]:
        """Получает активные скидки"""
        query = """
            SELECT * FROM discounts 
            WHERE is_active = TRUE 
            AND (ends_at IS NULL OR ends_at > CURRENT_TIMESTAMP)
            AND (max_uses IS NULL OR used_count < max_uses)
        """
        params = []
        
        if target_type:
            query += " AND target_type = ?"
            params.append(target_type)
        
        if target_id:
            query += " AND (target_id IS NULL OR target_id = ?)"
            params.append(target_id)
        
        query += " ORDER BY created_at DESC"
        
        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]
    
    def apply_discount(self, discount_id: int, account_id: int) -> Optional[float]:
        """Применяет скидку и возвращает множитель/фиксированную скидку"""
        try:
            self.cursor.execute("""
                SELECT * FROM discounts 
                WHERE discount_id = ? AND is_active = TRUE 
                AND (ends_at IS NULL OR ends_at > CURRENT_TIMESTAMP)
                AND (max_uses IS NULL OR used_count < max_uses)
            """, (discount_id,))
            
            discount = self.cursor.fetchone()
            if not discount:
                return None
            
            # Увеличиваем счетчик использований
            self.cursor.execute("""
                UPDATE discounts 
                SET used_count = used_count + 1 
                WHERE discount_id = ?
            """, (discount_id,))
            
            self.conn.commit()
            
            # Логируем
            self.log_action(None, account_id, "discount_use", 
                          f"Использована скидка: {discount['name']}")
            
            if discount['discount_type'] == DiscountType.PERCENTAGE.value:
                return (100 - discount['value']) / 100  # Возвращаем множитель
            else:
                return discount['value']  # Возвращаем фиксированную сумму
            
        except Exception as e:
            logger.error(f"Ошибка применения скидки: {e}")
            return None
    
    # === Работа ===
    def create_work_task(self, work_type: str) -> Optional[WorkTask]:
        """Создает задание для работы"""
        if work_type not in WORK_REWARDS:
            return None
        
        rewards = WORK_REWARDS[work_type]
        
        # Генерируем задание в зависимости от типа работы
        tasks = {
            "программист": [
                ("Напишите функцию для вычисления факториала", "def factorial(n):"),
                ("Исправьте ошибку в коде", "if x = 5:"),
                ("Напишите SQL запрос для выборки пользователей", "SELECT * FROM users"),
            ],
            "дизайнер": [
                ("Назовите три основных цвета в RGB", "255,0,0"),
                ("Что такое kerning в типографике?", "расстояние"),
                ("Назовите программу для векторной графики", "illustrator"),
            ],
            "менеджер": [
                ("Что такое KPI?", "ключевой показатель"),
                ("Назовите методологию agile", "scrum"),
                ("Что такое SWOT анализ?", "сильные стороны"),
            ],
            "тестировщик": [
                ("Что такое баг-репорт?", "отчет об ошибке"),
                ("Назовите тип тестирования", "регрессионное"),
                ("Что проверяет smoke тест?", "основной функционал"),
            ],
            "аналитик": [
                ("Что такое метрика конверсии?", "процент конверсии"),
                ("Назовите инструмент аналитики", "google analytics"),
                ("Что такое cohort анализ?", "анализ когорт"),
            ],
        }
        
        question, correct_answer = random.choice(tasks.get(work_type, [("Вопрос", "ответ")]))
        
        return WorkTask(
            work_type=work_type,
            description=f"Работа {work_type}ом",
            question=question,
            correct_answer=correct_answer.lower(),
            reward=random.randint(rewards["min"], rewards["max"]),
            difficulty="medium"
        )
    
    def complete_work(self, account_id: int, work_type: str, earnings: int, task_details: str = None) -> bool:
        """Завершает работу"""
        try:
            # Добавляем запись о работе
            self.cursor.execute("""
                INSERT INTO work_history (account_id, work_type, earnings, task_details)
                VALUES (?, ?, ?, ?)
            """, (account_id, work_type, earnings, task_details))
            
            # Обновляем профиль
            self.cursor.execute("""
                UPDATE profiles 
                SET work_count = work_count + 1,
                    balance = balance + ?,
                    total_earned = total_earned + ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE account_id = ?
            """, (earnings, earnings, account_id))
            
            # Добавляем транзакцию
            self.add_transaction(account_id, earnings, TransactionType.WORK.value, 
                               f"Работа: {work_type}")
            
            self.conn.commit()
            
            # Логируем
            self.log_action(None, account_id, "work", f"Выполнена работа: {work_type}, заработок: {earnings}")
            
            return True
        except Exception as e:
            logger.error(f"Ошибка завершения работы: {e}")
            return False
    
    def get_work_cooldown(self, account_id: int) -> Optional[datetime]:
        """Проверяет кулдаун работы"""
        cooldown_seconds = self.get_setting('work_cooldown', 1800)
        
        self.cursor.execute("""
            SELECT MAX(completed_at) as last_work 
            FROM work_history 
            WHERE account_id = ?
        """, (account_id,))
        
        result = self.cursor.fetchone()
        if result and result['last_work']:
            last_work = datetime.fromisoformat(result['last_work'])
            next_work = last_work + timedelta(seconds=cooldown_seconds)
            
            if datetime.now() < next_work:
                return next_work
        
        return None
    
    # === Магазин ===
    def get_shop_items(self, item_type: str = None, active_only: bool = True) -> List[Dict]:
        """Получает товары магазина"""
        query = "SELECT * FROM shop_items"
        params = []
        
        if active_only:
            query += " WHERE is_active = TRUE"
        
        if item_type:
            if active_only:
                query += " AND item_type = ?"
            else:
                query += " WHERE item_type = ?"
            params.append(item_type)
        
        query += " ORDER BY sort_order, price"
        
        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]
    
    def get_shop_item(self, item_id: int) -> Optional[Dict]:
        """Получает товар по ID"""
        self.cursor.execute("SELECT * FROM shop_items WHERE item_id = ?", (item_id,))
        row = self.cursor.fetchone()
        return dict(row) if row else None
    
    def purchase_item(self, account_id: int, item_id: int) -> Tuple[bool, str, Optional[Dict]]:
        """Покупка товара"""
        try:
            # Получаем товар
            item = self.get_shop_item(item_id)
            if not item or not item['is_active']:
                return False, "Товар не найден или недоступен", None
            
            # Получаем профиль
            profile = self.get_profile(account_id)
            if not profile:
                return False, "Профиль не найден", None
            
            # Проверяем баланс
            price = item['vip_price'] if profile.get('is_vip') else item['price']
            if profile['balance'] < price:
                return False, f"Недостаточно средств. Нужно: {price} Pulse", None
            
            # Применяем активные скидки
            discounts = self.get_active_discounts("shop_item", item_id)
            final_price = price
            
            for discount in discounts:
                if discount['discount_type'] == DiscountType.PERCENTAGE.value:
                    final_price = int(final_price * (100 - discount['value']) / 100)
                else:
                    final_price = max(0, final_price - discount['value'])
            
            # Проверяем лимиты покупок
            if item['max_purchases']:
                self.cursor.execute("""
                    SELECT COUNT(*) as purchase_count 
                    FROM purchases 
                    WHERE account_id = ? AND item_id = ?
                """, (account_id, item_id))
                
                purchase_count = self.cursor.fetchone()['purchase_count']
                if purchase_count >= item['max_purchases']:
                    return False, "Достигнут лимит покупок этого товара", None
            
            # Списываем средства
            if not self.update_balance(account_id, -final_price, 
                                     TransactionType.SHOP_PURCHASE.value,
                                     f"Покупка: {item['name']}"):
                return False, "Ошибка списания средств", None
            
            # Добавляем запись о покупке
            expires_at = None
            if item['duration_days']:
                expires_at = datetime.now() + timedelta(days=item['duration_days'])
            
            self.cursor.execute("""
                INSERT INTO purchases (account_id, item_id, price_paid, expires_at)
                VALUES (?, ?, ?, ?)
            """, (account_id, item_id, final_price, 
                  expires_at.isoformat() if expires_at else None))
            
            purchase_id = self.cursor.lastrowid
            
            # Применяем эффект товара
            if item['item_type'] == 'vip':
                # Активируем VIP
                current_vip_until = profile.get('vip_until')
                if current_vip_until and datetime.fromisoformat(current_vip_until) > datetime.now():
                    new_vip_until = datetime.fromisoformat(current_vip_until) + timedelta(days=item['duration_days'])
                else:
                    new_vip_until = datetime.now() + timedelta(days=item['duration_days'])
                
                self.cursor.execute("""
                    UPDATE profiles 
                    SET vip_until = ?, vip_level = vip_level + 1
                    WHERE account_id = ?
                """, (new_vip_until.isoformat(), account_id))
            
            self.conn.commit()
            
            # Логируем
            self.log_action(None, account_id, "shop_purchase", 
                          f"Куплен товар: {item['name']} за {final_price} Pulse")
            
            purchase_data = {
                'purchase_id': purchase_id,
                'item_name': item['name'],
                'price_paid': final_price,
                'expires_at': expires_at,
                'effect': item['effect_value']
            }
            
            return True, "Покупка успешна!", purchase_data
            
        except Exception as e:
            logger.error(f"Ошибка покупки: {e}")
            return False, f"Ошибка покупки: {str(e)}", None
    
    # === Логирование ===
    def log_action(self, user_id: int, account_id: int, action_type: str, 
                  action_name: str, details: str = None):
        """Логирует действие пользователя"""
        try:
            self.cursor.execute("""
                INSERT INTO action_logs (user_id, account_id, action_type, action_name, details)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, account_id, action_type, action_name, details))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка логирования: {e}")
    
    def get_user_logs(self, account_id: int, limit: int = 50, 
                     action_type: str = None) -> List[Dict]:
        """Получает логи пользователя"""
        query = """
            SELECT * FROM action_logs 
            WHERE account_id = ? 
        """
        params = [account_id]
        
        if action_type:
            query += " AND action_type = ?"
            params.append(action_type)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]
    
    # === Кулдауны ===
    def check_cooldown(self, user_id: int, action_type: str) -> Tuple[bool, Optional[datetime]]:
        """Проверяет кулдаун"""
        self.cursor.execute("""
            SELECT ends_at FROM cooldowns 
            WHERE user_id = ? AND action_type = ? AND ends_at > CURRENT_TIMESTAMP
            ORDER BY ends_at DESC LIMIT 1
        """, (user_id, action_type))
        
        result = self.cursor.fetchone()
        if result:
            ends_at = datetime.fromisoformat(result['ends_at'])
            return False, ends_at
        
        return True, None
    
    def set_cooldown(self, user_id: int, account_id: int, action_type: str, seconds: int):
        """Устанавливает кулдаун"""
        ends_at = datetime.now() + timedelta(seconds=seconds)
        
        self.cursor.execute("""
            INSERT INTO cooldowns (user_id, account_id, action_type, ends_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, account_id, action_type, ends_at.isoformat()))
        self.conn.commit()
    
    # === Настройки ===
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Получает настройку"""
        self.cursor.execute(
            "SELECT setting_value FROM bot_settings WHERE setting_key = ?",
            (key,)
        )
        result = self.cursor.fetchone()
        
        if result:
            try:
                return int(result['setting_value'])
            except ValueError:
                try:
                    return float(result['setting_value'])
                except ValueError:
                    return result['setting_value']
        
        return default
    
    def update_setting(self, key: str, value: Any, updated_by: int = None):
        """Обновляет настройку"""
        self.cursor.execute("""
            INSERT OR REPLACE INTO bot_settings (setting_key, setting_value, updated_by, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (key, str(value), updated_by))
        self.conn.commit()
    
    # === Управление сообщениями ===
    def grant_delete_permission(self, chat_id: int, user_id: int, granted_by: int, 
                              expires_at: datetime = None) -> bool:
        """Выдает право на удаление сообщений"""
        try:
            self.cursor.execute("""
                INSERT OR REPLACE INTO delete_permissions 
                (chat_id, user_id, granted_by, expires_at, is_active)
                VALUES (?, ?, ?, ?, TRUE)
            """, (chat_id, user_id, granted_by, 
                  expires_at.isoformat() if expires_at else None))
            
            self.conn.commit()
            
            # Логируем
            self.log_action(granted_by, None, "permission_grant", 
                          f"Выданы права на удаление в чате {chat_id} пользователю {user_id}")
            
            return True
        except Exception as e:
            logger.error(f"Ошибка выдачи прав: {e}")
            return False
    
    def revoke_delete_permission(self, chat_id: int, user_id: int) -> bool:
        """Отзывает право на удаление сообщений"""
        try:
            self.cursor.execute("""
                UPDATE delete_permissions 
                SET is_active = FALSE 
                WHERE chat_id = ? AND user_id = ? AND is_active = TRUE
            """, (chat_id, user_id))
            
            affected = self.cursor.rowcount
            self.conn.commit()
            
            if affected > 0:
                self.log_action(None, None, "permission_revoke", 
                              f"Отозваны права на удаление в чате {chat_id} у пользователя {user_id}")
            
            return affected > 0
        except Exception as e:
            logger.error(f"Ошибка отзыва прав: {e}")
            return False
    
    def has_delete_permission(self, chat_id: int, user_id: int) -> bool:
        """Проверяет право на удаление сообщений"""
        self.cursor.execute("""
            SELECT 1 FROM delete_permissions 
            WHERE chat_id = ? AND user_id = ? AND is_active = TRUE
            AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
        """, (chat_id, user_id))
        
        return self.cursor.fetchone() is not None
    
    # === Статистика ===
    def get_statistics(self) -> Dict:
        """Получает статистику бота"""
        stats = {}
        
        # Общая статистика
        queries = [
            ("total_accounts", "SELECT COUNT(*) FROM accounts"),
            ("total_users", "SELECT COUNT(DISTINCT owner_user_id) FROM accounts"),
            ("active_users_24h", """
                SELECT COUNT(DISTINCT user_id) FROM action_logs 
                WHERE created_at > datetime('now', '-1 day')
            """),
            ("total_balance", "SELECT SUM(balance) FROM profiles"),
            ("games_today", """
                SELECT COUNT(*) FROM game_history 
                WHERE DATE(created_at) = DATE('now')
            """),
            ("income_today", """
                SELECT SUM(amount) FROM transactions 
                WHERE DATE(created_at) = DATE('now') AND amount > 0
            """),
            ("total_transactions", "SELECT COUNT(*) FROM transactions"),
            ("active_draws", """
                SELECT COUNT(*) FROM draws 
                WHERE status = 'active' AND (ends_at IS NULL OR ends_at > CURRENT_TIMESTAMP)
            """),
            ("total_work", "SELECT COUNT(*) FROM work_history"),
        ]
        
        for key, query in queries:
            self.cursor.execute(query)
            stats[key] = self.cursor.fetchone()[0] or 0
        
        # Статистика по играм
        self.cursor.execute("""
            SELECT game_type, total_plays, total_wins, total_bets, total_payouts
            FROM game_statistics ORDER BY total_plays DESC
        """)
        
        stats['game_stats'] = [dict(row) for row in self.cursor.fetchall()]
        
        return stats
    
    # === Бонусы ===
    def claim_bonus(self, account_id: int) -> Tuple[bool, str, Optional[int]]:
        """Получение ежедневного бонуса"""
        try:
            # Проверяем кулдаун
            cooldown_seconds = self.get_setting('bonus_cooldown', 86400)
            
            self.cursor.execute("""
                SELECT MAX(created_at) as last_bonus 
                FROM transactions 
                WHERE account_id = ? AND type = 'bonus'
            """, (account_id,))
            
            result = self.cursor.fetchone()
            if result and result['last_bonus']:
                last_bonus = datetime.fromisoformat(result['last_bonus'])
                next_bonus = last_bonus + timedelta(seconds=cooldown_seconds)
                
                if datetime.now() < next_bonus:
                    remaining = next_bonus - datetime.now()
                    hours = int(remaining.total_seconds() // 3600)
                    minutes = int((remaining.total_seconds() % 3600) // 60)
                    return False, f"Бонус можно получить через {hours}ч {minutes}м", None
            
            # Выдаем бонус
            bonus_amount = self.get_setting('bonus_amount', 50)
            
            if not self.update_balance(account_id, bonus_amount, 
                                     TransactionType.BONUS.value, "Ежедневный бонус"):
                return False, "Ошибка начисления бонуса", None
            
            # Устанавливаем кулдаун
            self.set_cooldown(None, account_id, "bonus", cooldown_seconds)
            
            return True, f"Вы получили ежедневный бонус: {bonus_amount} Pulse!", bonus_amount
            
        except Exception as e:
            logger.error(f"Ошибка получения бонуса: {e}")
            return False, f"Ошибка: {str(e)}", None
    
    # === Реферальная система ===
    def get_referral_info(self, account_id: int) -> Dict:
        """Получает информацию о реферальной системе"""
        self.cursor.execute("""
            SELECT 
                a.referral_code,
                (SELECT COUNT(*) FROM accounts WHERE referred_by = a.account_id) as referrals_count,
                (SELECT SUM(amount) FROM transactions 
                 WHERE account_id = a.account_id AND type = 'referral') as total_earned
            FROM accounts a 
            WHERE a.account_id = ?
        """, (account_id,))
        
        result = self.cursor.fetchone()
        if result:
            return dict(result)
        
        return {"referral_code": "", "referrals_count": 0, "total_earned": 0}
    
    def use_referral_code(self, account_id: int, referral_code: str) -> Tuple[bool, str]:
        """Использование реферального кода"""
        try:
            # Проверяем, не использовал ли уже код
            self.cursor.execute("""
                SELECT referred_by FROM accounts WHERE account_id = ?
            """, (account_id,))
            
            result = self.cursor.fetchone()
            if result and result['referred_by']:
                return False, "Вы уже использовали реферальный код"
            
            # Ищем владельца кода
            self.cursor.execute("""
                SELECT account_id FROM accounts WHERE referral_code = ?
            """, (referral_code,))
            
            referrer = self.cursor.fetchone()
            if not referrer:
                return False, "Реферальный код не найден"
            
            referrer_id = referrer['account_id']
            
            if referrer_id == account_id:
                return False, "Нельзя использовать свой же реферальный код"
            
            # Обновляем запись
            self.cursor.execute("""
                UPDATE accounts SET referred_by = ? WHERE account_id = ?
            """, (referrer_id, account_id))
            
            # Начисляем бонусы
            self.update_balance(account_id, 100, TransactionType.REFERRAL.value, 
                              "Бонус за использование реферального кода")
            
            self.update_balance(referrer_id, 200, TransactionType.REFERRAL.value, 
                              "Бонус за привлечение реферала")
            
            # Увеличиваем счетчик рефералов
            self.cursor.execute("""
                UPDATE telegram_users 
                SET referrals_count = referrals_count + 1 
                WHERE user_id = (SELECT owner_user_id FROM accounts WHERE account_id = ?)
            """, (referrer_id,))
            
            self.conn.commit()
            
            return True, "Реферальный код успешно применен! Вы получили 100 Pulse"
            
        except Exception as e:
            logger.error(f"Ошибка применения реферального кода: {e}")
            return False, f"Ошибка: {str(e)}"
    
    # === Административные функции ===
    def get_all_accounts(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        """Получает все аккаунты"""
        self.cursor.execute("""
            SELECT a.*, p.balance, p.vip_until, u.username as owner_username
            FROM accounts a
            LEFT JOIN profiles p ON a.account_id = p.account_id
            LEFT JOIN telegram_users u ON a.owner_user_id = u.user_id
            ORDER BY a.created_at DESC 
            LIMIT ? OFFSET ?
        """, (limit, offset))
        
        return [dict(row) for row in self.cursor.fetchall()]
    
    def search_accounts(self, query: str) -> List[Dict]:
        """Поиск аккаунтов"""
        self.cursor.execute("""
            SELECT a.*, p.balance, p.vip_until, u.username as owner_username
            FROM accounts a
            LEFT JOIN profiles p ON a.account_id = p.account_id
            LEFT JOIN telegram_users u ON a.owner_user_id = u.user_id
            WHERE a.username LIKE ? OR a.account_id = ? OR u.username LIKE ?
            ORDER BY a.created_at DESC 
            LIMIT 20
        """, (f"%{query}%", query if query.isdigit() else 0, f"%{query}%"))
        
        return [dict(row) for row in self.cursor.fetchall()]
    
    def update_account_balance(self, account_id: int, amount: int, 
                             admin_id: int, reason: str = "") -> bool:
        """Изменение баланса аккаунта администратором"""
        try:
            transaction_type = TransactionType.ADMIN_ADD.value if amount > 0 else TransactionType.ADMIN_REMOVE.value
            
            if not self.update_balance(account_id, amount, transaction_type, 
                                     f"Админ: {reason if reason else 'Изменение баланса'}"):
                return False
            
            # Логируем действие администратора
            self.log_action(admin_id, account_id, "admin_action", 
                          f"Изменение баланса на {amount} Pulse: {reason}")
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка изменения баланса: {e}")
            return False
    
    def block_account(self, account_id: int, admin_id: int, reason: str, 
                     until: datetime = None) -> bool:
        """Блокировка аккаунта"""
        try:
            self.cursor.execute("""
                UPDATE accounts 
                SET is_blocked = TRUE, block_reason = ?, blocked_until = ?
                WHERE account_id = ?
            """, (reason, until.isoformat() if until else None, account_id))
            
            self.conn.commit()
            
            # Логируем
            self.log_action(admin_id, account_id, "admin_action", 
                          f"Блокировка аккаунта: {reason}")
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка блокировки аккаунта: {e}")
            return False
    
    def unblock_account(self, account_id: int, admin_id: int) -> bool:
        """Разблокировка аккаунта"""
        try:
            self.cursor.execute("""
                UPDATE accounts 
                SET is_blocked = FALSE, block_reason = NULL, blocked_until = NULL
                WHERE account_id = ?
            """, (account_id,))
            
            self.conn.commit()
            
            # Логируем
            self.log_action(admin_id, account_id, "admin_action", "Разблокировка аккаунта")
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка разблокировки аккаунта: {e}")
            return False

# ========== ИНИЦИАЛИЗАЦИЯ ==========
db = Database()
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=storage)

# ========== МИДЛВАРЫ ==========
class UserMiddleware:
    """Middleware для управления пользователями"""
    
    async def __call__(self, handler, event, data):
        if isinstance(event, (Message, CallbackQuery)):
            user = event.from_user
            
            # Обновляем информацию о пользователе
            db.create_or_update_telegram_user(user)
            
            # Проверяем активную сессию
            session = db.get_active_session(user.id)
            
            if session:
                data['session'] = session
                data['account_id'] = session['account_id']
                data['is_logged_in'] = True
                data['is_vip'] = session.get('is_vip', False)
                data['balance'] = session.get('balance', 0)
            else:
                data['session'] = None
                data['account_id'] = None
                data['is_logged_in'] = False
                data['is_vip'] = False
                data['balance'] = 0
            
            data['is_admin'] = user.id in ADMIN_IDS
        
        return await handler(event, data)

dp.update.middleware(UserMiddleware())

# ========== СОСТОЯНИЯ ==========
class RegistrationStates(StatesGroup):
    waiting_for_username = State()
    waiting_for_password = State()
    waiting_for_recovery = State()
    waiting_for_referral = State()

class LoginStates(StatesGroup):
    waiting_for_username = State()
    waiting_for_password = State()

class GameStates(StatesGroup):
    choosing_bet = State()
    playing_random = State()
    playing_choice = State()
    playing_reaction = State()
    playing_input = State()
    playing_scenario = State()

class WorkStates(StatesGroup):
    choosing_type = State()
    working = State()

class ShopStates(StatesGroup):
    browsing = State()
    viewing_item = State()
    confirming_purchase = State()

class DrawStates(StatesGroup):
    browsing = State()
    participating = State()

class AdminStates(StatesGroup):
    main_menu = State()
    managing_users = State()
    user_search = State()
    user_actions = State()
    managing_games = State()
    game_settings = State()
    managing_draws = State()
    creating_draw = State()
    managing_discounts = State()
    creating_discount = State()
    viewing_stats = State()
    managing_shop = State()
    broadcast_message = State()

# ========== КЛАССЫ ИГР ==========
class BaseGame:
    """Базовый класс игры"""
    
    def __init__(self, game_type: GameType):
        self.game_type = game_type
        self.min_bet = db.get_setting('min_bet', 25)
    
    async def play(self, account_id: int, bet: int, **kwargs) -> GameResult:
        raise NotImplementedError
    
    def calculate_payout(self, bet: int, multiplier: float = 2.0) -> int:
        return int(bet * multiplier)

class RandomGame(BaseGame):
    """Игра 'Рандом'"""
    
    def __init__(self):
        super().__init__(GameType.RANDOM)
        self.win_chance = 0.45
    
    async def play(self, account_id: int, bet: int) -> GameResult:
        win = random.random() < self.win_chance
        
        if win:
            win_amount = self.calculate_payout(bet)
            description = f"🎉 Поздравляем! Вы выиграли {win_amount} Pulse!"
            
            db.update_balance(account_id, win_amount, TransactionType.GAME_WIN.value, 
                            f"Выигрыш в игре {self.game_type.value}")
        else:
            win_amount = 0
            description = f"😔 Увы, вы проиграли {bet} Pulse. Попробуйте еще раз!"
            
            db.update_balance(account_id, -bet, TransactionType.GAME_LOSS.value, 
                            f"Проигрыш в игре {self.game_type.value}")
        
        db.record_game(account_id, self.game_type.value, bet, win, win_amount)
        
        return GameResult(
            win=win,
            amount=win_amount if win else -bet,
            description=description,
            game_type=self.game_type.value,
            timestamp=datetime.now()
        )

class ChoiceGame(BaseGame):
    """Игра с выбором"""
    
    def __init__(self):
        super().__init__(GameType.CHOICE)
        self.choices = [
            {"name": "🛡️ Безопасный", "multiplier": 1.5, "chance": 0.7, "emoji": "🛡️"},
            {"name": "⚔️ Рисковый", "multiplier": 3.0, "chance": 0.3, "emoji": "⚔️"},
            {"name": "☠️ Экстрим", "multiplier": 5.0, "chance": 0.15, "emoji": "☠️"},
        ]
    
    async def play(self, account_id: int, bet: int, choice_index: int) -> GameResult:
        if choice_index < 0 or choice_index >= len(self.choices):
            raise ValueError("Неверный выбор")
        
        choice = self.choices[choice_index]
        win = random.random() < choice['chance']
        
        if win:
            win_amount = self.calculate_payout(bet, choice['multiplier'])
            description = f"{choice['emoji']} Отличный выбор! Вы выиграли {win_amount} Pulse (x{choice['multiplier']})!"
            
            db.update_balance(account_id, win_amount, TransactionType.GAME_WIN.value, 
                            f"Выигрыш в игре {self.game_type.value}")
        else:
            win_amount = 0
            description = f"{choice['emoji']} Неудача! Вы проиграли {bet} Pulse. Шанс был {choice['chance']*100:.0f}%."
            
            db.update_balance(account_id, -bet, TransactionType.GAME_LOSS.value, 
                            f"Проигрыш в игре {self.game_type.value}")
        
        details = f"Выбор: {choice['name']}, Шанс: {choice['chance']}, Множитель: {choice['multiplier']}"
        db.record_game(account_id, self.game_type.value, bet, win, win_amount, details)
        
        return GameResult(
            win=win,
            amount=win_amount if win else -bet,
            description=description,
            game_type=self.game_type.value,
            timestamp=datetime.now()
        )

class ReactionGame(BaseGame):
    """Игра на реакцию"""
    
    def __init__(self):
        super().__init__(GameType.REACTION)
        self.max_reaction_time = 3.0
    
    async def play(self, account_id: int, bet: int, reaction_time: float) -> GameResult:
        if reaction_time <= self.max_reaction_time:
            win_amount = self.calculate_payout(bet)
            description = f"⚡ Отличная реакция! {reaction_time:.2f} сек. Выигрыш: {win_amount} Pulse!"
            win = True
            
            db.update_balance(account_id, win_amount, TransactionType.GAME_WIN.value, 
                            f"Выигрыш в игре {self.game_type.value}")
        else:
            win_amount = 0
            description = f"⚡ Слишком медленно! {reaction_time:.2f} сек. (нужно до {self.max_reaction_time} сек.)"
            win = False
            
            db.update_balance(account_id, -bet, TransactionType.GAME_LOSS.value, 
                            f"Проигрыш в игре {self.game_type.value}")
        
        details = f"Время реакции: {reaction_time:.2f}с, Лимит: {self.max_reaction_time}с"
        db.record_game(account_id, self.game_type.value, bet, win, win_amount, details)
        
        return GameResult(
            win=win,
            amount=win_amount if win else -bet,
            description=description,
            game_type=self.game_type.value,
            timestamp=datetime.now()
        )

class InputGame(BaseGame):
    """Игра с вводом числа"""
    
    def __init__(self):
        super().__init__(GameType.INPUT)
        self.max_number = 100
    
    async def play(self, account_id: int, bet: int, user_number: int) -> GameResult:
        target_number = random.randint(1, self.max_number)
        difference = abs(user_number - target_number)
        
        # Чем ближе к target, тем больше шанс выигрыша
        win_chance = max(0.1, 1.0 - (difference / self.max_number))
        win = random.random() < win_chance
        
        if win:
            # Множитель зависит от точности
            multiplier = 2.0 + (1.0 - (difference / self.max_number))
            win_amount = self.calculate_payout(bet, multiplier)
            description = f"🎯 Почти попал! Цель: {target_number}, ваше: {user_number}. Выигрыш: {win_amount} Pulse (x{multiplier:.1f})!"
            
            db.update_balance(account_id, win_amount, TransactionType.GAME_WIN.value, 
                            f"Выигрыш в игре {self.game_type.value}")
        else:
            win_amount = 0
            description = f"🎯 Мимо! Цель: {target_number}, ваше: {user_number}. Проигрыш: {bet} Pulse."
            
            db.update_balance(account_id, -bet, TransactionType.GAME_LOSS.value, 
                            f"Проигрыш в игре {self.game_type.value}")
        
        details = f"Цель: {target_number}, Введено: {user_number}, Разница: {difference}, Шанс: {win_chance:.1%}"
        db.record_game(account_id, self.game_type.value, bet, win, win_amount, details)
        
        return GameResult(
            win=win,
            amount=win_amount if win else -bet,
            description=description,
            game_type=self.game_type.value,
            timestamp=datetime.now()
        )

class ScenarioGame(BaseGame):
    """Сценарная игра"""
    
    def __init__(self):
        super().__init__(GameType.SCENARIO)
        self.scenarios = [
            {
                "name": "Квест в пещере",
                "description": "Вы находитесь в темной пещере. Перед вами три пути.",
                "choices": [
                    {"text": "Пойти налево", "outcome": "win", "chance": 0.4, "multiplier": 2.5},
                    {"text": "Пойти прямо", "outcome": "lose", "chance": 0.7, "multiplier": 1.0},
                    {"text": "Пойти направо", "outcome": "big_win", "chance": 0.2, "multiplier": 4.0},
                ]
            },
            {
                "name": "Пиратское сокровище",
                "description": "Вы нашли карту сокровищ. Куда пойдете?",
                "choices": [
                    {"text": "К реке", "outcome": "win", "chance": 0.5, "multiplier": 2.0},
                    {"text": "В лес", "outcome": "lose", "chance": 0.8, "multiplier": 1.0},
                    {"text": "На гору", "outcome": "big_win", "chance": 0.3, "multiplier": 3.5},
                ]
            },
        ]
    
    async def play(self, account_id: int, bet: int, scenario_index: int, choice_index: int) -> GameResult:
        if scenario_index < 0 or scenario_index >= len(self.scenarios):
            raise ValueError("Неверный сценарий")
        
        scenario = self.scenarios[scenario_index]
        
        if choice_index < 0 or choice_index >= len(scenario["choices"]):
            raise ValueError("Неверный выбор")
        
        choice = scenario["choices"][choice_index]
        win = random.random() < choice["chance"]
        
        if win:
            win_amount = self.calculate_payout(bet, choice["multiplier"])
            outcome_text = {
                "win": "Хороший выбор!",
                "big_win": "Отличный выбор!",
            }.get(choice["outcome"], "Удача!")
            
            description = f"🏴‍☠️ {outcome_text} Вы выиграли {win_amount} Pulse (x{choice['multiplier']})!"
            
            db.update_balance(account_id, win_amount, TransactionType.GAME_WIN.value, 
                            f"Выигрыш в игре {self.game_type.value}")
        else:
            win_amount = 0
            description = f"🏴‍☠️ Не повезло! Вы проиграли {bet} Pulse."
            
            db.update_balance(account_id, -bet, TransactionType.GAME_LOSS.value, 
                            f"Проигрыш в игре {self.game_type.value}")
        
        details = f"Сценарий: {scenario['name']}, Выбор: {choice['text']}, Шанс: {choice['chance']}, Множитель: {choice['multiplier']}"
        db.record_game(account_id, self.game_type.value, bet, win, win_amount, details)
        
        return GameResult(
            win=win,
            amount=win_amount if win else -bet,
            description=description,
            game_type=self.game_type.value,
            timestamp=datetime.now()
        )

# Менеджер игр
class GameManager:
    def __init__(self):
        self.games = {
            GameType.RANDOM.value: RandomGame(),
            GameType.CHOICE.value: ChoiceGame(),
            GameType.REACTION.value: ReactionGame(),
            GameType.INPUT.value: InputGame(),
            GameType.SCENARIO.value: ScenarioGame(),
        }
    
    def get_game(self, game_type: str) -> Optional[BaseGame]:
        return self.games.get(game_type)
    
    def get_available_games(self) -> List[Dict]:
        return [
            {
                "type": GameType.RANDOM.value,
                "name": "🎲 Рандом",
                "description": "Простая игра на удачу",
                "min_bet": self.games[GameType.RANDOM.value].min_bet,
                "emoji": "🎲"
            },
            {
                "type": GameType.CHOICE.value,
                "name": "🧠 Выбор",
                "description": "Выбери вариант с разными рисками",
                "min_bet": self.games[GameType.CHOICE.value].min_bet,
                "emoji": "🧠"
            },
            {
                "type": GameType.REACTION.value,
                "name": "⚡ Реакция",
                "description": "Проверь скорость реакции",
                "min_bet": self.games[GameType.REACTION.value].min_bet,
                "emoji": "⚡"
            },
            {
                "type": GameType.INPUT.value,
                "name": "🎯 Угадайка",
                "description": "Угадай число от 1 до 100",
                "min_bet": self.games[GameType.INPUT.value].min_bet,
                "emoji": "🎯"
            },
            {
                "type": GameType.SCENARIO.value,
                "name": "🏴‍☠️ Приключение",
                "description": "Сценарная игра с квестами",
                "min_bet": self.games[GameType.SCENARIO.value].min_bet,
                "emoji": "🏴‍☠️"
            },
        ]

game_manager = GameManager()

# ========== КЛАВИАТУРЫ ==========
class Keyboards:
    """Класс для создания клавиатур"""
    
    @staticmethod
    def main_menu(user_id: int, is_logged_in: bool = False, is_admin: bool = False) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        if not is_logged_in:
            builder.row(
                InlineKeyboardButton(text="🔐 Войти", callback_data=f"auth:login:{user_id}"),
                InlineKeyboardButton(text="📝 Регистрация", callback_data=f"auth:register:{user_id}")
            )
        else:
            # Основные функции
            builder.row(
                InlineKeyboardButton(text="🎮 Игры", callback_data=f"menu:games:{user_id}"),
                InlineKeyboardButton(text="💼 Работа", callback_data=f"menu:work:{user_id}")
            )
            builder.row(
                InlineKeyboardButton(text="🏪 Магазин", callback_data=f"menu:shop:{user_id}"),
                InlineKeyboardButton(text="🎁 Бонус", callback_data=f"menu:bonus:{user_id}")
            )
            builder.row(
                InlineKeyboardButton(text="👤 Профиль", callback_data=f"menu:profile:{user_id}"),
                InlineKeyboardButton(text="📊 Статистика", callback_data=f"menu:stats:{user_id}")
            )
            builder.row(
                InlineKeyboardButton(text="🎉 Розыгрыши", callback_data=f"menu:draws:{user_id}"),
                InlineKeyboardButton(text="👥 Рефералы", callback_data=f"menu:referrals:{user_id}")
            )
            builder.row(
                InlineKeyboardButton(text="🚪 Выйти", callback_data=f"auth:logout:{user_id}")
            )
        
        if is_admin:
            builder.row(
                InlineKeyboardButton(text="🛠 Админ-панель", callback_data=f"admin:main:{user_id}")
            )
        
        return builder.as_markup()
    
    @staticmethod
    def games_menu(user_id: int) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        games = game_manager.get_available_games()
        for game in games:
            builder.row(
                InlineKeyboardButton(
                    text=f"{game['emoji']} {game['name']} - от {game['min_bet']} Pulse",
                    callback_data=f"game:select:{user_id}:{game['type']}"
                )
            )
        
        builder.row(
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"menu:main:{user_id}")
        )
        
        return builder.as_markup()
    
    @staticmethod
    def bet_keyboard(user_id: int, game_type: str, balance: int) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        game = game_manager.get_game(game_type)
        if not game:
            return Keyboards.back_keyboard(user_id, "games")
        
        min_bet = game.min_bet
        bets = [min_bet, min_bet*2, min_bet*5, min_bet*10, min_bet*20]
        bets = [b for b in bets if b <= balance and b >= min_bet]
        
        for i, bet in enumerate(bets):
            if i % 2 == 0:
                builder.row()
            builder.add(InlineKeyboardButton(text=f"{bet} Pulse", callback_data=f"game:bet:{user_id}:{game_type}:{bet}"))
        
        if len(bets) % 2 != 0:
            builder.row()
        
        builder.row(
            InlineKeyboardButton(text="✏️ Своя сумма", callback_data=f"game:custom_bet:{user_id}:{game_type}"),
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"menu:games:{user_id}")
        )
        
        return builder.as_markup()
    
    @staticmethod
    def choice_game_keyboard(user_id: int) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        game = game_manager.get_game(GameType.CHOICE.value)
        if game:
            for i, choice in enumerate(game.choices):
                builder.row(
                    InlineKeyboardButton(
                        text=f"{choice['emoji']} {choice['name']} (шанс: {choice['chance']*100:.0f}%, x{choice['multiplier']})",
                        callback_data=f"game:choice:{user_id}:{i}"
                    )
                )
        
        builder.row(
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"menu:games:{user_id}")
        )
        
        return builder.as_markup()
    
    @staticmethod
    def scenario_game_keyboard(user_id: int, scenario_index: int) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        game = game_manager.get_game(GameType.SCENARIO.value)
        if game and scenario_index < len(game.scenarios):
            scenario = game.scenarios[scenario_index]
            for i, choice in enumerate(scenario["choices"]):
                builder.row(
                    InlineKeyboardButton(
                        text=choice["text"],
                        callback_data=f"game:scenario_choice:{user_id}:{scenario_index}:{i}"
                    )
                )
        
        builder.row(
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"menu:games:{user_id}")
        )
        
        return builder.as_markup()
    
    @staticmethod
    def work_menu(user_id: int) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        for work_type in WORK_TYPES:
            rewards = WORK_REWARDS[work_type]
            builder.row(
                InlineKeyboardButton(
                    text=f"{work_type.capitalize()} ({rewards['min']}-{rewards['max']} Pulse)",
                    callback_data=f"work:select:{user_id}:{work_type}"
                )
            )
        
        builder.row(
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"menu:main:{user_id}")
        )
        
        return builder.as_markup()
    
    @staticmethod
    def shop_menu(user_id: int, item_type: str = None) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        items = db.get_shop_items(item_type)
        for item in items[:10]:  # Ограничиваем 10 товарами
            price = item['vip_price'] if item['vip_price'] else item['price']
            builder.row(
                InlineKeyboardButton(
                    text=f"{item['name']} - {price} Pulse",
                    callback_data=f"shop:view:{user_id}:{item['item_id']}"
                )
            )
        
        # Фильтры по типам
        if not item_type:
            builder.row(
                InlineKeyboardButton(text="💎 VIP", callback_data=f"shop:filter:{user_id}:vip"),
                InlineKeyboardButton(text="🚀 Бустеры", callback_data=f"shop:filter:{user_id}:booster")
            )
            builder.row(
                InlineKeyboardButton(text="🎁 Предметы", callback_data=f"shop:filter:{user_id}:item"),
                InlineKeyboardButton(text="📦 Все", callback_data=f"shop:filter:{user_id}:all")
            )
        
        builder.row(
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"menu:main:{user_id}")
        )
        
        return builder.as_markup()
    
    @staticmethod
    def shop_item_keyboard(user_id: int, item_id: int, can_afford: bool) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        if can_afford:
            builder.row(
                InlineKeyboardButton(text="🛒 Купить", callback_data=f"shop:buy:{user_id}:{item_id}")
            )
        
        builder.row(
            InlineKeyboardButton(text="📋 Все товары", callback_data=f"menu:shop:{user_id}"),
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"menu:main:{user_id}")
        )
        
        return builder.as_markup()
    
    @staticmethod
    def draws_menu(user_id: int) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        draws = db.get_active_draws()
        for draw in draws:
            prize_text = f"{draw['prize_value']} Pulse" if draw['prize_type'] == 'coins' else draw['prize_text']
            builder.row(
                InlineKeyboardButton(
                    text=f"🎉 {draw['name']} ({draw['current_participants']} участ.)",
                    callback_data=f"draw:view:{user_id}:{draw['draw_id']}"
                )
            )
        
        builder.row(
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"menu:draws:{user_id}"),
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"menu:main:{user_id}")
        )
        
        return builder.as_markup()
    
    @staticmethod
    def draw_view_keyboard(user_id: int, draw_id: int, can_participate: bool) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        if can_participate:
            builder.row(
                InlineKeyboardButton(text="✅ Участвовать", callback_data=f"draw:participate:{user_id}:{draw_id}")
            )
        
        builder.row(
            InlineKeyboardButton(text="📋 Все розыгрыши", callback_data=f"menu:draws:{user_id}"),
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"menu:main:{user_id}")
        )
        
        return builder.as_markup()
    
    @staticmethod
    def admin_menu(user_id: int) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        builder.row(
            InlineKeyboardButton(text="👥 Пользователи", callback_data=f"admin:users:{user_id}"),
            InlineKeyboardButton(text="🎮 Игры", callback_data=f"admin:games:{user_id}")
        )
        builder.row(
            InlineKeyboardButton(text="🎉 Розыгрыши", callback_data=f"admin:draws:{user_id}"),
            InlineKeyboardButton(text="🏷️ Скидки", callback_data=f"admin:discounts:{user_id}")
        )
        builder.row(
            InlineKeyboardButton(text="📊 Статистика", callback_data=f"admin:stats:{user_id}"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"admin:settings:{user_id}")
        )
        builder.row(
            InlineKeyboardButton(text="🏪 Магазин", callback_data=f"admin:shop:{user_id}"),
            InlineKeyboardButton(text="📢 Рассылка", callback_data=f"admin:broadcast:{user_id}")
        )
        builder.row(
            InlineKeyboardButton(text="🔙 Главное меню", callback_data=f"menu:main:{user_id}")
        )
        
        return builder.as_markup()
    
    @staticmethod
    def admin_users_menu(user_id: int) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        builder.row(
            InlineKeyboardButton(text="🔍 Поиск", callback_data=f"admin:search:{user_id}"),
            InlineKeyboardButton(text="📋 Все аккаунты", callback_data=f"admin:all_accounts:{user_id}")
        )
        builder.row(
            InlineKeyboardButton(text="🚫 Заблокированные", callback_data=f"admin:banned:{user_id}"),
            InlineKeyboardButton(text="📈 Топ по балансу", callback_data=f"admin:top_balance:{user_id}")
        )
        builder.row(
            InlineKeyboardButton(text="🔙 В админ-панель", callback_data=f"admin:main:{user_id}")
        )
        
        return builder.as_markup()
    
    @staticmethod
    def admin_user_actions(user_id: int, target_account_id: int) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        builder.row(
            InlineKeyboardButton(text="💰 Изменить баланс", callback_data=f"admin:balance:{user_id}:{target_account_id}"),
            InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"admin:block:{user_id}:{target_account_id}")
        )
        builder.row(
            InlineKeyboardButton(text="✅ Разблокировать", callback_data=f"admin:unblock:{user_id}:{target_account_id}"),
            InlineKeyboardButton(text="📊 Статистика", callback_data=f"admin:user_stats:{user_id}:{target_account_id}")
        )
        builder.row(
            InlineKeyboardButton(text="📝 Логи", callback_data=f"admin:user_logs:{user_id}:{target_account_id}"),
            InlineKeyboardButton(text="🔙 К поиску", callback_data=f"admin:users:{user_id}")
        )
        
        return builder.as_markup()
    
    @staticmethod
    def cancel_keyboard(user_id: int) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{user_id}")
        )
        return builder.as_markup()
    
    @staticmethod
    def back_keyboard(user_id: int, back_to: str = "main") -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"menu:{back_to}:{user_id}")
        )
        return builder.as_markup()
    
    @staticmethod
    def admin_back_keyboard(user_id: int) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"admin:main:{user_id}")
        )
        return builder.as_markup()
    
    @staticmethod
    def yes_no_keyboard(user_id: int, action: str, data: str = "") -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        if data:
            builder.row(
                InlineKeyboardButton(text="✅ Да", callback_data=f"confirm:{action}:{user_id}:{data}"),
                InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel:{user_id}")
            )
        else:
            builder.row(
                InlineKeyboardButton(text="✅ Да", callback_data=f"confirm:{action}:{user_id}"),
                InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel:{user_id}")
            )
        
        return builder.as_markup()

# ========== ХЭНДЛЕРЫ КОМАНД ==========
@dp.message(Command("start", "startpuls"))
async def cmd_start(message: Message, is_logged_in: bool, session: Dict = None):
    """Команда старт"""
    user_id = message.from_user.id
    
    welcome_text = (
        "🎮 <b>Добро пожаловать в Pulse Bot!</b>\n\n"
        "<i>Игровой бот с экономикой, играми и розыгрышами</i>\n\n"
    )
    
    if is_logged_in and session:
        profile = db.get_profile(session['account_id'])
        if profile:
            welcome_text += (
                f"👤 Вы вошли как: <code>{session['username']}</code>\n"
                f"💰 Баланс: <b>{profile['balance']}</b> Pulse\n\n"
            )
    
    welcome_text += "Выберите действие:"
    
    await message.answer(
        welcome_text,
        reply_markup=Keyboards.main_menu(user_id, is_logged_in, user_id in ADMIN_IDS)
    )

@dp.message(Command("login"))
async def cmd_login(message: Message, state: FSMContext, is_logged_in: bool):
    """Команда входа"""
    user_id = message.from_user.id
    
    if message.chat.type != "private":
        await message.answer("Вход доступен только в личных сообщениях!")
        return
    
    if is_logged_in:
        await message.answer("Вы уже авторизованы!")
        return
    
    await state.set_state(LoginStates.waiting_for_username)
    await message.answer(
        "🔐 <b>Вход в аккаунт</b>\n\n"
        "Введите ваш логин:",
        reply_markup=Keyboards.cancel_keyboard(user_id)
    )

@dp.message(Command("register", "registerpuls"))
async def cmd_register(message: Message, state: FSMContext, is_logged_in: bool):
    """Команда регистрации"""
    user_id = message.from_user.id
    
    if message.chat.type != "private":
        await message.answer("Регистрация доступна только в личных сообщениях!")
        return
    
    if is_logged_in:
        await message.answer("Вы уже авторизованы!")
        return
    
    # Проверяем лимиты
    max_accounts = db.get_setting('max_accounts_per_user', 3)
    account_count = db.get_account_count_by_owner(user_id)
    
    if account_count >= max_accounts:
        await message.answer(
            f"❌ Вы уже создали максимальное количество аккаунтов ({max_accounts}).\n"
            "Используйте существующие аккаунты или обратитесь к администратору."
        )
        return
    
    await state.set_state(RegistrationStates.waiting_for_username)
    await message.answer(
        "📝 <b>Регистрация нового аккаунта</b>\n\n"
        "Придумайте логин (3-20 символов, буквы, цифры и _):",
        reply_markup=Keyboards.cancel_keyboard(user_id)
    )

@dp.message(Command("profile"))
async def cmd_profile(message: Message, is_logged_in: bool, session: Dict = None):
    """Команда профиля"""
    user_id = message.from_user.id
    
    if not is_logged_in or not session:
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    await show_profile(message, session)

@dp.message(Command("games"))
async def cmd_games(message: Message, is_logged_in: bool):
    """Команда игр"""
    user_id = message.from_user.id
    
    if not is_logged_in:
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    await show_games_menu(message, user_id)

@dp.message(Command("work"))
async def cmd_work(message: Message, is_logged_in: bool):
    """Команда работы"""
    user_id = message.from_user.id
    
    if not is_logged_in:
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    await show_work_menu(message, user_id)

@dp.message(Command("shop"))
async def cmd_shop(message: Message, is_logged_in: bool):
    """Команда магазина"""
    user_id = message.from_user.id
    
    if not is_logged_in:
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    await show_shop_menu(message, user_id)

@dp.message(Command("bonus"))
async def cmd_bonus(message: Message, is_logged_in: bool, session: Dict = None):
    """Команда бонуса"""
    user_id = message.from_user.id
    
    if not is_logged_in or not session:
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    await claim_bonus(message, session['account_id'])

@dp.message(Command("draws"))
async def cmd_draws(message: Message, is_logged_in: bool):
    """Команда розыгрышей"""
    user_id = message.from_user.id
    
    if not is_logged_in:
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    await show_draws_menu(message, user_id)

@dp.message(Command("referral"))
async def cmd_referral(message: Message, is_logged_in: bool, session: Dict = None):
    """Команда реферальной системы"""
    user_id = message.from_user.id
    
    if not is_logged_in or not session:
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    await show_referral_info(message, session['account_id'])

@dp.message(Command("logout"))
async def cmd_logout(message: Message, is_logged_in: bool):
    """Команда выхода"""
    user_id = message.from_user.id
    
    if not is_logged_in:
        await message.answer("Вы не авторизованы!")
        return
    
    db.logout_session(user_id)
    await message.answer(
        "✅ Вы успешно вышли из аккаунта!",
        reply_markup=Keyboards.main_menu(user_id, False, user_id in ADMIN_IDS)
    )

@dp.message(Command("admin"))
async def cmd_admin(message: Message, is_admin: bool):
    """Команда админ-панели"""
    user_id = message.from_user.id
    
    if not is_admin:
        await message.answer("Доступ запрещен!")
        return
    
    await show_admin_menu(message, user_id)

# ========== ОБРАБОТЧИКИ СОСТОЯНИЙ ==========
@dp.message(LoginStates.waiting_for_username)
async def process_login_username(message: Message, state: FSMContext):
    """Обработка логина для входа"""
    username = message.text.strip()
    user_id = message.from_user.id
    
    if len(username) < 3:
        await message.answer("Логин должен содержать минимум 3 символа. Попробуйте еще раз:")
        return
    
    await state.update_data(login_username=username)
    await state.set_state(LoginStates.waiting_for_password)
    
    await message.answer(
        "Введите пароль:",
        reply_markup=Keyboards.cancel_keyboard(user_id)
    )

@dp.message(LoginStates.waiting_for_password)
async def process_login_password(message: Message, state: FSMContext):
    """Обработка пароля для входа"""
    password = message.text.strip()
    user_id = message.from_user.id
    data = await state.get_data()
    username = data.get('login_username')
    
    if not username:
        await message.answer("Ошибка: логин не найден. Начните заново.")
        await state.clear()
        return
    
    # Проверяем учетные данные
    account = db.verify_account(username, password)
    
    if not account:
        await message.answer("Неверный логин или пароль!")
        await state.clear()
        await cmd_start(message, False, None)
        return
    
    # Создаем сессию
    db.create_session(user_id, account['account_id'])
    
    profile = db.get_profile(account['account_id'])
    
    await message.answer(
        f"✅ <b>Успешный вход!</b>\n\n"
        f"👤 Аккаунт: <code>{username}</code>\n"
        f"💰 Баланс: <b>{profile['balance']}</b> Pulse\n"
        f"⭐ Статус: {'✅ VIP' if profile['vip_until'] and datetime.fromisoformat(profile['vip_until']) > datetime.now() else '❌ Обычный'}\n\n"
        "Добро пожаловать обратно!",
        reply_markup=Keyboards.main_menu(user_id, True, user_id in ADMIN_IDS)
    )
    
    await state.clear()

@dp.message(RegistrationStates.waiting_for_username)
async def process_registration_username(message: Message, state: FSMContext):
    """Обработка логина для регистрации"""
    username = message.text.strip()
    user_id = message.from_user.id
    
    # Проверка логина
    if len(username) < 3 or len(username) > 20:
        await message.answer("Логин должен быть от 3 до 20 символов. Попробуйте еще раз:")
        return
    
    if not re.match(r'^[A-Za-z0-9_]+$', username):
        await message.answer("Логин может содержать только буквы, цифры и символ _. Попробуйте еще раз:")
        return
    
    # Проверяем, не занят ли логин
    existing_account = db.get_account(username=username)
    if existing_account:
        await message.answer("Этот логин уже занят. Придумайте другой:")
        return
    
    await state.update_data(username=username)
    await state.set_state(RegistrationStates.waiting_for_password)
    
    await message.answer(
        "✅ Отличный логин!\n\n"
        "Теперь придумайте пароль:\n"
        "• Минимум 5 символов\n"
        "• Хотя бы 1 буква и 1 цифра\n"
        "• Максимум 20 символов",
        reply_markup=Keyboards.cancel_keyboard(user_id)
    )

@dp.message(RegistrationStates.waiting_for_password)
async def process_registration_password(message: Message, state: FSMContext):
    """Обработка пароля для регистрации"""
    password = message.text.strip()
    user_id = message.from_user.id
    data = await state.get_data()
    username = data.get('username')
    
    # Проверка пароля
    if len(password) < 5:
        await message.answer("Пароль должен содержать минимум 5 символов. Попробуйте еще раз:")
        return
    
    if not re.search(r'[A-Za-z]', password):
        await message.answer("Пароль должен содержать хотя бы 1 букву. Попробуйте еще раз:")
        return
    
    if not re.search(r'\d', password):
        await message.answer("Пароль должен содержать хотя бы 1 цифру. Попробуйте еще раз:")
        return
    
    if len(password) > 20:
        await message.answer("Пароль не должен превышать 20 символов. Попробуйте еще раз:")
        return
    
    await state.update_data(password=password)
    await state.set_state(RegistrationStates.waiting_for_recovery)
    
    await message.answer(
        "✅ Отличный пароль!\n\n"
        "<b>Кодовое слово для восстановления (опционально):</b>\n"
        "• Только английские буквы\n"
        "• 5-20 символов\n\n"
        "<i>Это слово понадобится для восстановления доступа при потере пароля.</i>\n\n"
        "Введите кодовое слово или 'пропустить':",
        reply_markup=Keyboards.cancel_keyboard(user_id)
    )

@dp.message(RegistrationStates.waiting_for_recovery)
async def process_registration_recovery(message: Message, state: FSMContext):
    """Обработка кодового слова для регистрации"""
    recovery = message.text.strip()
    user_id = message.from_user.id
    data = await state.get_data()
    username = data.get('username')
    password = data.get('password')
    
    recovery_code = None
    
    if recovery.lower() != 'пропустить':
        # Проверка кодового слова
        if len(recovery) < 5 or len(recovery) > 20:
            await message.answer("Кодовое слово должно быть от 5 до 20 символов. Попробуйте еще раз:")
            return
        
        if not re.match(r'^[A-Za-z]+$', recovery):
            await message.answer("Кодовое слово должно содержать только английские буквы. Попробуйте еще раз:")
            return
        
        recovery_code = recovery
    
    await state.update_data(recovery_code=recovery_code)
    await state.set_state(RegistrationStates.waiting_for_referral)
    
    await message.answer(
        "📨 <b>Реферальный код (опционально):</b>\n\n"
        "Если у вас есть реферальный код от друга, введите его сейчас.\n"
        "Это принесет бонусы вам и вашему другу!\n\n"
        "Введите код или 'пропустить':",
        reply_markup=Keyboards.cancel_keyboard(user_id)
    )

@dp.message(RegistrationStates.waiting_for_referral)
async def process_registration_referral(message: Message, state: FSMContext):
    """Обработка реферального кода для регистрации"""
    referral_input = message.text.strip()
    user_id = message.from_user.id
    data = await state.get_data()
    username = data.get('username')
    password = data.get('password')
    recovery_code = data.get('recovery_code')
    
    referred_by = None
    
    if referral_input.lower() != 'пропустить':
        # Ищем аккаунт по реферальному коду
        db.cursor.execute("SELECT account_id FROM accounts WHERE referral_code = ?", (referral_input,))
        result = db.cursor.fetchone()
        
        if result:
            referred_by = result['account_id']
        else:
            await message.answer("Реферальный код не найден. Попробуйте еще раз или введите 'пропустить':")
            return
    
    # Создаем аккаунт
    account_id = db.create_account(username, password, user_id, recovery_code, referred_by)
    
    if not account_id:
        await message.answer("Ошибка при создании аккаунта. Попробуйте позже.")
        await state.clear()
        return
    
    # Создаем сессию
    db.create_session(user_id, account_id)
    
    await message.answer(
        f"🎉 <b>Регистрация успешна!</b>\n\n"
        f"👤 Логин: <code>{username}</code>\n"
        f"🔐 Пароль: <code>{password}</code>\n"
        f"🗝️ Кодовое слово: <code>{recovery_code or 'не установлено'}</code>\n"
        f"🎁 Начальный баланс: 100 Pulse\n\n"
        f"<b>Сохраните эти данные в надежном месте!</b>\n\n"
        f"Теперь вы можете пользоваться всеми функциями бота!",
        reply_markup=Keyboards.main_menu(user_id, True, user_id in ADMIN_IDS)
    )
    
    await state.clear()

# ========== ФУНКЦИИ ПОКАЗА МЕНЮ ==========
async def show_profile(message: Message, session: Dict):
    """Показывает профиль пользователя"""
    user_id = message.from_user.id
    account_id = session['account_id']
    
    profile = db.get_profile(account_id)
    if not profile:
        await message.answer("Ошибка загрузки профиля!")
        return
    
    # Получаем статистику игр
    game_stats = db.get_game_statistics(account_id)
    
    # Получаем реферальную информацию
    referral_info = db.get_referral_info(account_id)
    
    # Формируем текст профиля
    profile_text = (
        f"👤 <b>Профиль аккаунта</b>\n\n"
        f"📛 Логин: <code>{session['username']}</code>\n"
        f"🆔 ID: <code>{account_id}</code>\n"
        f"💰 Баланс: <b>{profile['balance']}</b> Pulse\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"🎮 Игр сыграно: {profile['games_played']}\n"
        f"✅ Побед: {game_stats.get('wins', 0)}\n"
        f"📈 Процент побед: {game_stats.get('win_rate', 0):.1f}%\n"
        f"💼 Работ выполнено: {profile['work_count']}\n"
        f"📈 Всего заработано: {profile['total_earned']} Pulse\n"
        f"📉 Всего потрачено: {profile['total_spent']} Pulse\n\n"
        f"👥 <b>Рефералы:</b>\n"
        f"🔗 Код: <code>{referral_info['referral_code']}</code>\n"
        f"👤 Приглашено: {referral_info['referrals_count']}\n"
        f"💰 Заработано: {referral_info['total_earned']} Pulse\n\n"
        f"⭐ <b>VIP статус:</b> "
    )
    
    if profile['vip_until']:
        vip_until = datetime.fromisoformat(profile['vip_until'])
        if vip_until > datetime.now():
            days_left = (vip_until - datetime.now()).days
            profile_text += f"✅ Активен (осталось {days_left} дней)"
        else:
            profile_text += "❌ Истек"
    else:
        profile_text += "❌ Неактивен"
    
    # Добавляем ссылку для приглашения
    profile_text += f"\n\n🔗 <b>Ссылка для приглашения:</b>\n"
    profile_text += f"https://t.me/{BOT_USERNAME}?start=ref_{referral_info['referral_code']}"
    
    await message.answer(
        profile_text,
        reply_markup=Keyboards.main_menu(user_id, True, user_id in ADMIN_IDS)
    )

async def show_games_menu(message: Message, user_id: int):
    """Показывает меню игр"""
    games_text = "🎮 <b>Доступные игры</b>\n\n"
    games = game_manager.get_available_games()
    
    for game in games:
        games_text += (
            f"{game['emoji']} <b>{game['name']}</b>\n"
            f"<i>{game['description']}</i>\n"
            f"Минимальная ставка: {game['min_bet']} Pulse\n\n"
        )
    
    await message.answer(
        games_text,
        reply_markup=Keyboards.games_menu(user_id)
    )

async def show_work_menu(message: Message, user_id: int):
    """Показывает меню работы"""
    # Проверяем кулдаун
    session = db.get_active_session(user_id)
    if not session:
        await message.answer("Ошибка сессии!")
        return
    
    cooldown = db.get_work_cooldown(session['account_id'])
    
    work_text = "💼 <b>Работа</b>\n\n"
    
    if cooldown:
        remaining = cooldown - datetime.now()
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        
        work_text += (
            f"⏰ Следующая работа доступна через: {hours}ч {minutes}м\n\n"
            f"Выберите профессию для просмотра информации:"
        )
    else:
        work_text += "✅ Вы можете начать работу сейчас!\n\nВыберите профессию:"
    
    await message.answer(
        work_text,
        reply_markup=Keyboards.work_menu(user_id)
    )

async def show_shop_menu(message: Message, user_id: int):
    """Показывает меню магазина"""
    session = db.get_active_session(user_id)
    if not session:
        await message.answer("Ошибка сессии!")
        return
    
    profile = db.get_profile(session['account_id'])
    is_vip = profile['vip_until'] and datetime.fromisoformat(profile['vip_until']) > datetime.now()
    
    shop_text = (
        f"🏪 <b>Магазин</b>\n\n"
        f"💰 Ваш баланс: <b>{profile['balance']}</b> Pulse\n"
        f"⭐ VIP статус: {'✅ Активен' if is_vip else '❌ Неактивен'}\n\n"
        f"<i>Выберите категорию товаров:</i>"
    )
    
    await message.answer(
        shop_text,
        reply_markup=Keyboards.shop_menu(user_id)
    )

async def show_draws_menu(message: Message, user_id: int):
    """Показывает меню розыгрышей"""
    draws = db.get_active_draws()
    
    if not draws:
        draws_text = "🎉 <b>Розыгрыши</b>\n\nВ данный момент нет активных розыгрышей."
    else:
        draws_text = "🎉 <b>Активные розыгрыши</b>\n\n"
        
        for draw in draws:
            prize_text = f"{draw['prize_value']} Pulse" if draw['prize_type'] == 'coins' else draw['prize_text']
            ends_at = datetime.fromisoformat(draw['ends_at']) if draw['ends_at'] else None
            
            draws_text += (
                f"🎁 <b>{draw['name']}</b>\n"
                f"📝 {draw['description'] or 'Без описания'}\n"
                f"💰 Приз: {prize_text}\n"
                f"👥 Участников: {draw['current_participants']}/{draw['winners_count']} победителей\n"
            )
            
            if ends_at:
                time_left = ends_at - datetime.now()
                if time_left.total_seconds() > 0:
                    days = time_left.days
                    hours = time_left.seconds // 3600
                    draws_text += f"⏳ Осталось: {days}д {hours}ч\n"
            
            draws_text += "\n"
    
    await message.answer(
        draws_text,
        reply_markup=Keyboards.draws_menu(user_id)
    )

async def show_referral_info(message: Message, account_id: int):
    """Показывает информацию о реферальной системе"""
    referral_info = db.get_referral_info(account_id)
    
    referral_text = (
        f"👥 <b>Реферальная система</b>\n\n"
        f"🔗 Ваш реферальный код:\n"
        f"<code>{referral_info['referral_code']}</code>\n\n"
        f"📊 Статистика:\n"
        f"👤 Приглашено: {referral_info['referrals_count']}\n"
        f"💰 Заработано: {referral_info['total_earned']} Pulse\n\n"
        f"🎁 <b>Как это работает:</b>\n"
        f"• Пригласите друга по вашей ссылке\n"
        f"• Друг получает 100 Pulse при регистрации\n"
        f"• Вы получаете 200 Pulse за каждого приглашенного\n\n"
        f"🔗 <b>Ваша ссылка для приглашения:</b>\n"
        f"https://t.me/{BOT_USERNAME}?start=ref_{referral_info['referral_code']}"
    )
    
    await message.answer(referral_text)

async def claim_bonus(message: Message, account_id: int):
    """Получение ежедневного бонуса"""
    success, message_text, amount = db.claim_bonus(account_id)
    
    if success:
        await message.answer(
            f"🎁 <b>Ежедневный бонус!</b>\n\n"
            f"{message_text}\n\n"
            f"Следующий бонус через 24 часа.",
            reply_markup=Keyboards.main_menu(message.from_user.id, True, message.from_user.id in ADMIN_IDS)
        )
    else:
        await message.answer(
            f"❌ {message_text}",
            reply_markup=Keyboards.main_menu(message.from_user.id, True, message.from_user.id in ADMIN_IDS)
        )

async def show_admin_menu(message: Message, user_id: int):
    """Показывает админ-меню"""
    await message.answer(
        "🛠 <b>Админ-панель</b>\n\nВыберите раздел:",
        reply_markup=Keyboards.admin_menu(user_id)
    )

# ========== ОБРАБОТЧИКИ КНОПОК ==========
@dp.callback_query(F.data.startswith("auth:"))
async def handle_auth_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопок авторизации"""
    data_parts = callback.data.split(":")
    action = data_parts[1]
    user_id = int(data_parts[2])
    
    if callback.from_user.id != user_id:
        await callback.answer("Эта кнопка не для вас!")
        return
    
    await callback.answer()
    
    if action == "login":
        if callback.message.chat.type != "private":
            await callback.message.edit_text("Вход доступен только в личных сообщениях!")
            return
        
        await state.set_state(LoginStates.waiting_for_username)
        await callback.message.edit_text(
            "🔐 <b>Вход в аккаунт</b>\n\n"
            "Введите ваш логин:",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "register":
        if callback.message.chat.type != "private":
            await callback.message.edit_text("Регистрация доступна только в личных сообщениях!")
            return
        
        # Проверяем лимиты
        max_accounts = db.get_setting('max_accounts_per_user', 3)
        account_count = db.get_account_count_by_owner(user_id)
        
        if account_count >= max_accounts:
            await callback.message.edit_text(
                f"❌ Вы уже создали максимальное количество аккаунтов ({max_accounts}).\n"
                "Используйте существующие аккаунты или обратитесь к администратору."
            )
            return
        
        await state.set_state(RegistrationStates.waiting_for_username)
        await callback.message.edit_text(
            "📝 <b>Регистрация нового аккаунта</b>\n\n"
            "Придумайте логин (3-20 символов, буквы, цифры и _):",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "logout":
        db.logout_session(user_id)
        await callback.message.edit_text(
            "✅ Вы вышли из аккаунта!",
            reply_markup=Keyboards.main_menu(user_id, False, user_id in ADMIN_IDS)
        )

@dp.callback_query(F.data.startswith("menu:"))
async def handle_menu_callback(callback: CallbackQuery, is_logged_in: bool, session: Dict = None):
    """Обработчик меню"""
    data_parts = callback.data.split(":")
    action = data_parts[1]
    user_id = int(data_parts[2])
    
    if callback.from_user.id != user_id:
        await callback.answer("Эта кнопка не для вас!")
        return
    
    await callback.answer()
    
    if action == "main":
        await callback.message.edit_text(
            "🎮 <b>Главное меню</b>\n\nВыберите действие:",
            reply_markup=Keyboards.main_menu(user_id, is_logged_in, user_id in ADMIN_IDS)
        )
    
    elif action == "games":
        if not is_logged_in:
            await callback.message.edit_text("Сначала войдите в аккаунт!")
            return
        
        await show_games_menu(callback.message, user_id)
    
    elif action == "work":
        if not is_logged_in:
            await callback.message.edit_text("Сначала войдите в аккаунт!")
            return
        
        await show_work_menu(callback.message, user_id)
    
    elif action == "shop":
        if not is_logged_in:
            await callback.message.edit_text("Сначала войдите в аккаунт!")
            return
        
        await show_shop_menu(callback.message, user_id)
    
    elif action == "bonus":
        if not is_logged_in or not session:
            await callback.message.edit_text("Сначала войдите в аккаунт!")
            return
        
        await claim_bonus(callback.message, session['account_id'])
    
    elif action == "profile":
        if not is_logged_in or not session:
            await callback.message.edit_text("Сначала войдите в аккаунт!")
            return
        
        await show_profile(callback.message, session)
    
    elif action == "stats":
        if not is_logged_in or not session:
            await callback.message.edit_text("Сначала войдите в аккаунт!")
            return
        
        await show_statistics(callback.message, session['account_id'])
    
    elif action == "draws":
        if not is_logged_in:
            await callback.message.edit_text("Сначала войдите в аккаунт!")
            return
        
        await show_draws_menu(callback.message, user_id)
    
    elif action == "referrals":
        if not is_logged_in or not session:
            await callback.message.edit_text("Сначала войдите в аккаунт!")
            return
        
        await show_referral_info(callback.message, session['account_id'])

async def show_statistics(message: Message, account_id: int):
    """Показывает статистику"""
    profile = db.get_profile(account_id)
    game_stats = db.get_game_statistics(account_id)
    
    stats_text = (
        f"📊 <b>Ваша статистика</b>\n\n"
        f"🎮 <b>Игры:</b>\n"
        f"• Сыграно: {profile['games_played']}\n"
        f"• Побед: {game_stats.get('wins', 0)}\n"
        f"• Процент побед: {game_stats.get('win_rate', 0):.1f}%\n"
        f"• Всего поставлено: {game_stats.get('total_bet', 0)} Pulse\n"
        f"• Всего выиграно: {game_stats.get('total_won', 0)} Pulse\n\n"
        f"💼 <b>Работа:</b>\n"
        f"• Выполнено работ: {profile['work_count']}\n"
        f"• Заработано: {profile['total_earned']} Pulse\n"
        f"• Потрачено: {profile['total_spent']} Pulse\n\n"
        f"💰 <b>Баланс:</b> {profile['balance']} Pulse"
    )
    
    await message.answer(stats_text)

@dp.callback_query(F.data.startswith("game:"))
async def handle_game_callback(callback: CallbackQuery, state: FSMContext, is_logged_in: bool, session: Dict = None):
    """Обработчик игр"""
    data_parts = callback.data.split(":")
    action = data_parts[1]
    user_id = int(data_parts[2])
    
    if callback.from_user.id != user_id:
        await callback.answer("Эта кнопка не для вас!")
        return
    
    if not is_logged_in or not session:
        await callback.answer("Сначала войдите в аккаунт!")
        return
    
    await callback.answer()
    
    if action == "select":
        # Выбор игры
        game_type = data_parts[3]
        game = game_manager.get_game(game_type)
        
        if not game:
            await callback.message.edit_text("Игра не найдена!")
            return
        
        # Проверяем баланс
        profile = db.get_profile(session['account_id'])
        if profile['balance'] < game.min_bet:
            await callback.message.edit_text(
                f"❌ Недостаточно средств!\n"
                f"Минимальная ставка: {game.min_bet} Pulse\n"
                f"Ваш баланс: {profile['balance']} Pulse"
            )
            return
        
        # Показываем выбор ставки
        await callback.message.edit_text(
            f"🎮 <b>Выберите ставку</b>\n\n"
            f"💰 Ваш баланс: {profile['balance']} Pulse\n"
            f"📊 Минимальная ставка: {game.min_bet} Pulse\n"
            f"🎯 Выигрыш: x2 от ставки\n\n"
            f"<i>Выберите сумму ставки:</i>",
            reply_markup=Keyboards.bet_keyboard(user_id, game_type, profile['balance'])
        )
    
    elif action == "bet":
        # Обработка ставки
        game_type = data_parts[3]
        bet = int(data_parts[4])
        
        game = game_manager.get_game(game_type)
        if not game:
            await callback.message.edit_text("Игра не найдена!")
            return
        
        # Проверяем баланс
        profile = db.get_profile(session['account_id'])
        if profile['balance'] < bet:
            await callback.message.edit_text("Недостаточно средств!")
            return
        
        if bet < game.min_bet:
            await callback.message.edit_text(f"Минимальная ставка: {game.min_bet} Pulse!")
            return
        
        # Играем в игру
        if game_type == GameType.RANDOM.value:
            result = await game.play(session['account_id'], bet)
            
            new_balance = profile['balance'] + result.amount
            await callback.message.edit_text(
                f"🎮 <b>Игра: Рандом</b>\n\n"
                f"💰 Ставка: {bet} Pulse\n\n"
                f"{result.description}\n\n"
                f"📊 Новый баланс: {new_balance} Pulse",
                reply_markup=Keyboards.back_keyboard(user_id, "games")
            )
        
        elif game_type == GameType.CHOICE.value:
            await callback.message.edit_text(
                f"🎮 <b>Игра: Выбор</b>\n\n"
                f"💰 Ставка: {bet} Pulse\n\n"
                f"Выберите вариант:",
                reply_markup=Keyboards.choice_game_keyboard(user_id)
            )
            # Сохраняем ставку в состоянии
            await state.update_data(bet=bet, game_type=game_type)
        
        elif game_type == GameType.REACTION.value:
            # Для игры на реакцию
            await callback.message.edit_text(
                f"🎮 <b>Игра: Реакция</b>\n\n"
                f"💰 Ставка: {bet} Pulse\n\n"
                f"⏱️ Нажмите кнопку КАК МОЖНО БЫСТРЕЕ после сигнала!\n\n"
                f"Готовы? Нажмите кнопку ниже чтобы начать!",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[
                        InlineKeyboardButton(
                            text="⚡ НАЧАТЬ!",
                            callback_data=f"game:react_start:{user_id}:{bet}:{time.time()}"
                        )
                    ]]
                )
            )
        
        elif game_type == GameType.INPUT.value:
            # Игра с вводом числа
            await callback.message.edit_text(
                f"🎮 <b>Игра: Угадайка</b>\n\n"
                f"💰 Ставка: {bet} Pulse\n\n"
                f"Угадайте число от 1 до 100.\n"
                f"Чем ближе к загаданному числу, тем больше шанс выигрыша!\n\n"
                f"Введите число от 1 до 100:"
            )
            await state.update_data(bet=bet, game_type=game_type)
            await state.set_state(GameStates.playing_input)
        
        elif game_type == GameType.SCENARIO.value:
            # Сценарная игра
            game = game_manager.get_game(GameType.SCENARIO.value)
            if game and game.scenarios:
                scenario_index = random.randint(0, len(game.scenarios) - 1)
                scenario = game.scenarios[scenario_index]
                
                await callback.message.edit_text(
                    f"🎮 <b>Игра: Приключение</b>\n\n"
                    f"💰 Ставка: {bet} Pulse\n\n"
                    f"🏴‍☠️ <b>{scenario['name']}</b>\n"
                    f"{scenario['description']}\n\n"
                    f"Выберите действие:",
                    reply_markup=Keyboards.scenario_game_keyboard(user_id, scenario_index)
                )
                await state.update_data(bet=bet, game_type=game_type, scenario_index=scenario_index)
    
    elif action == "choice":
        # Обработка выбора в игре с вариантами
        choice_index = int(data_parts[3])
        
        data = await state.get_data()
        bet = data.get('bet')
        game_type = data.get('game_type')
        
        if not bet or game_type != GameType.CHOICE.value:
            await callback.message.edit_text("Ошибка: данные игры утеряны!")
            return
        
        game = game_manager.get_game(GameType.CHOICE.value)
        if not game:
            await callback.message.edit_text("Игра не найдена!")
            return
        
        result = await game.play(session['account_id'], bet, choice_index)
        profile = db.get_profile(session['account_id'])
        
        await callback.message.edit_text(
            f"🎮 <b>Игра: Выбор</b>\n\n"
            f"💰 Ставка: {bet} Pulse\n\n"
            f"{result.description}\n\n"
            f"📊 Новый баланс: {profile['balance']} Pulse",
            reply_markup=Keyboards.back_keyboard(user_id, "games")
        )
        
        await state.clear()
    
    elif action == "scenario_choice":
        # Обработка выбора в сценарной игре
        scenario_index = int(data_parts[3])
        choice_index = int(data_parts[4])
        
        data = await state.get_data()
        bet = data.get('bet')
        
        if not bet:
            await callback.message.edit_text("Ошибка: данные игры утеряны!")
            return
        
        game = game_manager.get_game(GameType.SCENARIO.value)
        if not game:
            await callback.message.edit_text("Игра не найдена!")
            return
        
        result = await game.play(session['account_id'], bet, scenario_index, choice_index)
        profile = db.get_profile(session['account_id'])
        
        await callback.message.edit_text(
            f"🎮 <b>Игра: Приключение</b>\n\n"
            f"💰 Ставка: {bet} Pulse\n\n"
            f"{result.description}\n\n"
            f"📊 Новый баланс: {profile['balance']} Pulse",
            reply_markup=Keyboards.back_keyboard(user_id, "games")
        )
        
        await state.clear()
    
    elif action == "react_start":
        # Начало игры на реакцию
        bet = int(data_parts[3])
        start_time = float(data_parts[4])
        
        # Ждем случайное время (0.5-3 секунды)
        wait_time = random.uniform(0.5, 3.0)
        await asyncio.sleep(wait_time)
        
        # Показываем кнопку для нажатия
        await callback.message.edit_text(
            f"🎮 <b>Игра: Реакция</b>\n\n"
            f"💰 Ставка: {bet} Pulse\n\n"
            f"⚡ <b>НАЖМИТЕ СЕЙЧАС!</b>\n\n"
            f"У вас есть 3 секунды!",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text="⚡ НАЖМИ!",
                        callback_data=f"game:react_end:{user_id}:{bet}:{time.time()}"
                    )
                ]]
            )
        )
    
    elif action == "react_end":
        # Конец игры на реакцию
        bet = int(data_parts[3])
        button_time = float(data_parts[4])
        reaction_time = time.time() - button_time
        
        game = game_manager.get_game(GameType.REACTION.value)
        if not game:
            await callback.message.edit_text("Игра не найдена!")
            return
        
        result = await game.play(session['account_id'], bet, reaction_time)
        profile = db.get_profile(session['account_id'])
        
        await callback.message.edit_text(
            f"🎮 <b>Игра: Реакция</b>\n\n"
            f"💰 Ставка: {bet} Pulse\n"
            f"⏱️ Ваше время: {reaction_time:.3f} сек.\n\n"
            f"{result.description}\n\n"
            f"📊 Новый баланс: {profile['balance']} Pulse",
            reply_markup=Keyboards.back_keyboard(user_id, "games")
        )

@dp.message(GameStates.playing_input)
async def process_input_game(message: Message, state: FSMContext, is_logged_in: bool, session: Dict = None):
    """Обработка ввода числа для игры"""
    user_id = message.from_user.id
    
    if not is_logged_in or not session:
        await message.answer("Ошибка сессии!")
        await state.clear()
        return
    
    try:
        user_number = int(message.text.strip())
        
        if user_number < 1 or user_number > 100:
            await message.answer("Введите число от 1 до 100!")
            return
        
        data = await state.get_data()
        bet = data.get('bet')
        
        if not bet:
            await message.answer("Ошибка: данные игры утеряны!")
            await state.clear()
            return
        
        game = game_manager.get_game(GameType.INPUT.value)
        if not game:
            await message.answer("Игра не найдена!")
            await state.clear()
            return
        
        result = await game.play(session['account_id'], bet, user_number)
        profile = db.get_profile(session['account_id'])
        
        await message.answer(
            f"🎮 <b>Игра: Угадайка</b>\n\n"
            f"💰 Ставка: {bet} Pulse\n"
            f"🎯 Ваше число: {user_number}\n\n"
            f"{result.description}\n\n"
            f"📊 Новый баланс: {profile['balance']} Pulse",
            reply_markup=Keyboards.back_keyboard(user_id, "games")
        )
        
        await state.clear()
        
    except ValueError:
        await message.answer("Пожалуйста, введите целое число!")

@dp.callback_query(F.data.startswith("work:"))
async def handle_work_callback(callback: CallbackQuery, state: FSMContext, is_logged_in: bool, session: Dict = None):
    """Обработчик работы"""
    data_parts = callback.data.split(":")
    action = data_parts[1]
    user_id = int(data_parts[2])
    
    if callback.from_user.id != user_id:
        await callback.answer("Эта кнопка не для вас!")
        return
    
    if not is_logged_in or not session:
        await callback.answer("Сначала войдите в аккаунт!")
        return
    
    await callback.answer()
    
    if action == "select":
        work_type = data_parts[3]
        
        # Проверяем кулдаун
        cooldown = db.get_work_cooldown(session['account_id'])
        if cooldown:
            remaining = cooldown - datetime.now()
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            
            await callback.message.edit_text(
                f"⏰ Работа временно недоступна!\n\n"
                f"Следующая работа через: {hours}ч {minutes}м"
            )
            return
        
        # Создаем задание
        task = db.create_work_task(work_type)
        if not task:
            await callback.message.edit_text("Ошибка создания задания!")
            return
        
        await state.update_data(work_type=work_type, task=task)
        await state.set_state(WorkStates.working)
        
        await callback.message.edit_text(
            f"💼 <b>Работа: {work_type.capitalize()}</b>\n\n"
            f"📝 Задание:\n"
            f"{task.question}\n\n"
            f"💰 Награда: {task.reward} Pulse\n\n"
            f"Введите ваш ответ:"
        )

@dp.message(WorkStates.working)
async def process_work_answer(message: Message, state: FSMContext, is_logged_in: bool, session: Dict = None):
    """Обработка ответа на работу"""
    user_id = message.from_user.id
    
    if not is_logged_in or not session:
        await message.answer("Ошибка сессии!")
        await state.clear()
        return
    
    data = await state.get_data()
    work_type = data.get('work_type')
    task = data.get('task')
    
    if not work_type or not task:
        await message.answer("Ошибка: данные задания утеряны!")
        await state.clear()
        return
    
    user_answer = message.text.strip().lower()
    
    # Проверяем ответ (простая проверка на содержание правильного ответа)
    if task.correct_answer in user_answer:
        # Успех
        db.complete_work(session['account_id'], work_type, task.reward, task.question)
        profile = db.get_profile(session['account_id'])
        
        await message.answer(
            f"✅ <b>Отличная работа!</b>\n\n"
            f"💼 Профессия: {work_type.capitalize()}\n"
            f"💰 Заработано: {task.reward} Pulse\n"
            f"📊 Новый баланс: {profile['balance']} Pulse\n\n"
            f"Следующая работа будет доступна через 30 минут.",
            reply_markup=Keyboards.main_menu(user_id, True, user_id in ADMIN_IDS)
        )
    else:
        # Неудача
        await message.answer(
            f"❌ <b>Неправильный ответ!</b>\n\n"
            f"Правильный ответ был: {task.correct_answer}\n\n"
            f"Попробуйте другую работу или вернитесь позже.",
            reply_markup=Keyboards.main_menu(user_id, True, user_id in ADMIN_IDS)
        )
    
    await state.clear()

@dp.callback_query(F.data.startswith("shop:"))
async def handle_shop_callback(callback: CallbackQuery, is_logged_in: bool, session: Dict = None):
    """Обработчик магазина"""
    data_parts = callback.data.split(":")
    action = data_parts[1]
    user_id = int(data_parts[2])
    
    if callback.from_user.id != user_id:
        await callback.answer("Эта кнопка не для вас!")
        return
    
    if not is_logged_in or not session:
        await callback.answer("Сначала войдите в аккаунт!")
        return
    
    await callback.answer()
    
    if action == "filter":
        item_type = data_parts[3]
        
        if item_type == "all":
            await show_shop_menu(callback.message, user_id)
        else:
            items = db.get_shop_items(item_type)
            
            if not items:
                await callback.message.edit_text(
                    f"🏪 <b>Магазин: {item_type.capitalize()}</b>\n\n"
                    f"В этой категории пока нет товаров.",
                    reply_markup=Keyboards.shop_menu(user_id, item_type)
                )
                return
            
            shop_text = f"🏪 <b>Магазин: {item_type.capitalize()}</b>\n\n"
            
            for item in items[:10]:
                price = item['vip_price'] if item['vip_price'] else item['price']
                shop_text += f"• {item['name']} - {price} Pulse\n"
                if item['description']:
                    shop_text += f"  <i>{item['description']}</i>\n"
                shop_text += "\n"
            
            await callback.message.edit_text(
                shop_text,
                reply_markup=Keyboards.shop_menu(user_id, item_type)
            )
    
    elif action == "view":
        item_id = int(data_parts[3])
        item = db.get_shop_item(item_id)
        
        if not item:
            await callback.message.edit_text("Товар не найден!")
            return
        
        profile = db.get_profile(session['account_id'])
        is_vip = profile['vip_until'] and datetime.fromisoformat(profile['vip_until']) > datetime.now()
        
        price = item['vip_price'] if is_vip and item['vip_price'] else item['price']
        can_afford = profile['balance'] >= price
        
        item_text = (
            f"🏪 <b>{item['name']}</b>\n\n"
            f"{item['description'] or 'Без описания'}\n\n"
            f"💰 Цена: {price} Pulse"
        )
        
        if item['vip_price'] and is_vip:
            item_text += f" (VIP цена, обычная: {item['price']} Pulse)"
        elif item['vip_price']:
            item_text += f" (VIP цена: {item['vip_price']} Pulse)"
        
        if item['duration_days']:
            item_text += f"\n⏳ Длительность: {item['duration_days']} дней"
        
        if item['effect_value']:
            item_text += f"\n⚡ Эффект: x{item['effect_value']}"
        
        item_text += f"\n\n💰 Ваш баланс: {profile['balance']} Pulse"
        
        if not can_afford:
            item_text += f"\n❌ Недостаточно средств!"
        
        await callback.message.edit_text(
            item_text,
            reply_markup=Keyboards.shop_item_keyboard(user_id, item_id, can_afford)
        )
    
    elif action == "buy":
        item_id = int(data_parts[3])
        
        success, message_text, purchase_data = db.purchase_item(session['account_id'], item_id)
        
        if success:
            item = db.get_shop_item(item_id)
            await callback.message.edit_text(
                f"✅ <b>Покупка успешна!</b>\n\n"
                f"🎁 Товар: {item['name']}\n"
                f"💰 Стоимость: {purchase_data['price_paid']} Pulse\n"
                f"📦 Номер покупки: #{purchase_data['purchase_id']}\n\n"
                f"{message_text}",
                reply_markup=Keyboards.main_menu(user_id, True, user_id in ADMIN_IDS)
            )
        else:
            await callback.message.edit_text(
                f"❌ <b>Ошибка покупки!</b>\n\n{message_text}",
                reply_markup=Keyboards.main_menu(user_id, True, user_id in ADMIN_IDS)
            )

@dp.callback_query(F.data.startswith("draw:"))
async def handle_draw_callback(callback: CallbackQuery, is_logged_in: bool, session: Dict = None):
    """Обработчик розыгрышей"""
    data_parts = callback.data.split(":")
    action = data_parts[1]
    user_id = int(data_parts[2])
    
    if callback.from_user.id != user_id:
        await callback.answer("Эта кнопка не для вас!")
        return
    
    if not is_logged_in or not session:
        await callback.answer("Сначала войдите в аккаунт!")
        return
    
    await callback.answer()
    
    if action == "view":
        draw_id = int(data_parts[3])
        draw = db.get_draw(draw_id=draw_id)
        
        if not draw:
            await callback.message.edit_text("Розыгрыш не найден!")
            return
        
        # Проверяем, участвует ли уже пользователь
        db.cursor.execute("""
            SELECT 1 FROM draw_participants 
            WHERE draw_id = ? AND account_id = ?
        """, (draw_id, session['account_id']))
        
        already_participating = db.cursor.fetchone() is not None
        can_participate = not already_participating and draw['status'] == DrawStatus.ACTIVE.value
        
        prize_text = f"{draw['prize_value']} Pulse" if draw['prize_type'] == 'coins' else draw['prize_text']
        ends_at = datetime.fromisoformat(draw['ends_at']) if draw['ends_at'] else None
        
        draw_text = (
            f"🎉 <b>{draw['name']}</b>\n\n"
            f"📝 {draw['description'] or 'Без описания'}\n\n"
            f"💰 Приз: {prize_text}\n"
            f"👑 Победителей: {draw['winners_count']}\n"
            f"👥 Участников: {draw['participants_count']}\n"
        )
        
        if ends_at:
            time_left = ends_at - datetime.now()
            if time_left.total_seconds() > 0:
                days = time_left.days
                hours = time_left.seconds // 3600
                draw_text += f"⏳ Осталось: {days}д {hours}ч\n"
        
        if already_participating:
            draw_text += f"\n✅ Вы уже участвуете в этом розыгрыше!"
        elif draw['status'] != DrawStatus.ACTIVE.value:
            draw_text += f"\n❌ Розыгрыш завершен!"
        
        await callback.message.edit_text(
            draw_text,
            reply_markup=Keyboards.draw_view_keyboard(user_id, draw_id, can_participate)
        )
    
    elif action == "participate":
        draw_id = int(data_parts[3])
        
        success = db.participate_in_draw(draw_id, session['account_id'])
        
        if success:
            await callback.message.edit_text(
                f"✅ <b>Вы успешно зарегистрировались в розыгрыше!</b>\n\n"
                f"Результаты будут объявлены после завершения розыгрыша.\n"
                f"Удачи! 🍀",
                reply_markup=Keyboards.back_keyboard(user_id, "draws")
            )
        else:
            await callback.message.edit_text(
                f"❌ <b>Не удалось зарегистрироваться!</b>\n\n"
                f"Возможно, вы уже участвуете в этом розыгрыше или он завершен.",
                reply_markup=Keyboards.back_keyboard(user_id, "draws")
            )

@dp.callback_query(F.data.startswith("admin:"))
async def handle_admin_callback(callback: CallbackQuery, state: FSMContext, is_admin: bool):
    """Обработчик админ-панели"""
    data_parts = callback.data.split(":")
    action = data_parts[1]
    user_id = int(data_parts[2])
    
    if callback.from_user.id != user_id:
        await callback.answer("Эта кнопка не для вас!")
        return
    
    if not is_admin:
        await callback.answer("Доступ запрещен!")
        return
    
    await callback.answer()
    
    if action == "main":
        await callback.message.edit_text(
            "🛠 <b>Админ-панель</b>\n\nВыберите раздел:",
            reply_markup=Keyboards.admin_menu(user_id)
        )
    
    elif action == "users":
        await callback.message.edit_text(
            "👥 <b>Управление пользователями</b>\n\nВыберите действие:",
            reply_markup=Keyboards.admin_users_menu(user_id)
        )
    
    elif action == "search":
        await state.set_state(AdminStates.user_search)
        await callback.message.edit_text(
            "🔍 <b>Поиск пользователей</b>\n\n"
            "Введите логин, ID аккаунта или username пользователя:",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "all_accounts":
        accounts = db.get_all_accounts(limit=20)
        
        if not accounts:
            await callback.message.edit_text("Нет зарегистрированных аккаунтов.")
            return
        
        accounts_text = "📋 <b>Последние 20 аккаунтов</b>\n\n"
        
        for account in accounts:
            created_date = datetime.fromisoformat(account['created_at']).strftime("%d.%m.%Y")
            accounts_text += (
                f"👤 {account['username']} (ID: {account['account_id']})\n"
                f"💰 Баланс: {account['balance']} Pulse\n"
                f"👑 Владелец: {account['owner_username'] or account['owner_user_id']}\n"
                f"📅 Регистрация: {created_date}\n\n"
            )
        
        await callback.message.edit_text(
            accounts_text,
            reply_markup=Keyboards.admin_users_menu(user_id)
        )
    
    elif action == "stats":
        stats = db.get_statistics()
        
        stats_text = (
            f"📊 <b>Статистика бота</b>\n\n"
            f"👥 <b>Пользователи:</b>\n"
            f"• Всего аккаунтов: {stats['total_accounts']}\n"
            f"• Уникальных пользователей: {stats['total_users']}\n"
            f"• Активных (24ч): {stats['active_users_24h']}\n\n"
            f"💰 <b>Экономика:</b>\n"
            f"• Общий баланс: {stats['total_balance']} Pulse\n"
            f"• Доход сегодня: {stats['income_today']} Pulse\n"
            f"• Всего транзакций: {stats['total_transactions']}\n\n"
            f"🎮 <b>Игры:</b>\n"
            f"• Игр сегодня: {stats['games_today']}\n"
            f"• Всего работ: {stats['total_work']}\n"
            f"• Активных розыгрышей: {stats['active_draws']}\n\n"
            f"🎯 <b>Статистика по играм:</b>\n"
        )
        
        for game_stat in stats.get('game_stats', []):
            win_rate = (game_stat['total_wins'] / game_stat['total_plays'] * 100) if game_stat['total_plays'] > 0 else 0
            stats_text += (
                f"• {game_stat['game_type']}: "
                f"{game_stat['total_plays']} игр, "
                f"{win_rate:.1f}% побед, "
                f"{game_stat['total_payouts']} Pulse выплат\n"
            )
        
        await callback.message.edit_text(
            stats_text,
            reply_markup=Keyboards.admin_menu(user_id)
        )
    
    elif action == "balance":
        target_account_id = int(data_parts[3])
        
        await state.set_state(AdminStates.user_actions)
        await state.update_data(target_account_id=target_account_id, action="balance")
        
        account = db.get_account(account_id=target_account_id)
        if not account:
            await callback.message.edit_text("Аккаунт не найден!")
            return
        
        profile = db.get_profile(target_account_id)
        
        await callback.message.edit_text(
            f"💰 <b>Изменение баланса</b>\n\n"
            f"👤 Аккаунт: {account['username']} (ID: {target_account_id})\n"
            f"💰 Текущий баланс: {profile['balance']} Pulse\n\n"
            f"Введите сумму для изменения (положительная - добавить, отрицательная - снять):",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "block":
        target_account_id = int(data_parts[3])
        
        await state.set_state(AdminStates.user_actions)
        await state.update_data(target_account_id=target_account_id, action="block")
        
        account = db.get_account(account_id=target_account_id)
        if not account:
            await callback.message.edit_text("Аккаунт не найден!")
            return
        
        await callback.message.edit_text(
            f"🚫 <b>Блокировка аккаунта</b>\n\n"
            f"👤 Аккаунт: {account['username']} (ID: {target_account_id})\n\n"
            f"Введите причину блокировки:",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "unblock":
        target_account_id = int(data_parts[3])
        
        success = db.unblock_account(target_account_id, user_id)
        
        if success:
            await callback.message.edit_text(
                f"✅ Аккаунт успешно разблокирован!",
                reply_markup=Keyboards.admin_users_menu(user_id)
            )
        else:
            await callback.message.edit_text(
                f"❌ Ошибка при разблокировке аккаунта!",
                reply_markup=Keyboards.admin_users_menu(user_id)
            )
    
    elif action == "user_stats":
        target_account_id = int(data_parts[3])
        
        account = db.get_account(account_id=target_account_id)
        if not account:
            await callback.message.edit_text("Аккаунт не найден!")
            return
        
        profile = db.get_profile(target_account_id)
        game_stats = db.get_game_statistics(target_account_id)
        referral_info = db.get_referral_info(target_account_id)
        
        stats_text = (
            f"📊 <b>Статистика аккаунта</b>\n\n"
            f"👤 Аккаунт: {account['username']} (ID: {target_account_id})\n"
            f"👑 Владелец: {account['owner_user_id']}\n"
            f"💰 Баланс: {profile['balance']} Pulse\n\n"
            f"🎮 <b>Игры:</b>\n"
            f"• Сыграно: {profile['games_played']}\n"
            f"• Побед: {game_stats.get('wins', 0)}\n"
            f"• Процент побед: {game_stats.get('win_rate', 0):.1f}%\n"
            f"• Всего поставлено: {game_stats.get('total_bet', 0)} Pulse\n"
            f"• Всего выиграно: {game_stats.get('total_won', 0)} Pulse\n\n"
            f"💼 <b>Работа:</b>\n"
            f"• Выполнено работ: {profile['work_count']}\n"
            f"• Заработано: {profile['total_earned']} Pulse\n"
            f"• Потрачено: {profile['total_spent']} Pulse\n\n"
            f"👥 <b>Рефералы:</b>\n"
            f"• Приглашено: {referral_info['referrals_count']}\n"
            f"• Заработано: {referral_info['total_earned']} Pulse\n\n"
            f"📅 <b>Дата регистрации:</b> {datetime.fromisoformat(account['created_at']).strftime('%d.%m.%Y %H:%M')}"
        )
        
        if account['is_blocked']:
            stats_text += f"\n\n🚫 <b>Аккаунт заблокирован</b>\n"
            if account['block_reason']:
                stats_text += f"Причина: {account['block_reason']}\n"
            if account['blocked_until']:
                blocked_until = datetime.fromisoformat(account['blocked_until'])
                stats_text += f"До: {blocked_until.strftime('%d.%m.%Y %H:%M')}"
        
        await callback.message.edit_text(
            stats_text,
            reply_markup=Keyboards.admin_user_actions(user_id, target_account_id)
        )
    
    elif action == "user_logs":
        target_account_id = int(data_parts[3])
        
        logs = db.get_user_logs(target_account_id, limit=20)
        
        if not logs:
            await callback.message.edit_text("Нет логов для этого аккаунта.")
            return
        
        logs_text = f"📝 <b>Последние 20 действий аккаунта</b>\n\n"
        
        for log in logs:
            time_str = datetime.fromisoformat(log['created_at']).strftime("%H:%M")
            logs_text += f"• [{time_str}] {log['action_name']}\n"
            if log['details']:
                logs_text += f"  <i>{log['details']}</i>\n"
        
        await callback.message.edit_text(
            logs_text,
            reply_markup=Keyboards.admin_user_actions(user_id, target_account_id)
        )

@dp.message(AdminStates.user_search)
async def process_admin_user_search(message: Message, state: FSMContext):
    """Обработка поиска пользователей"""
    query = message.text.strip()
    user_id = message.from_user.id
    
    if not query:
        await message.answer("Пожалуйста, введите поисковый запрос!")
        return
    
    accounts = db.search_accounts(query)
    
    if not accounts:
        await message.answer(
            f"❌ Аккаунты по запросу '{query}' не найдены.",
            reply_markup=Keyboards.admin_users_menu(user_id)
        )
        await state.clear()
        return
    
    if len(accounts) == 1:
        # Если найден один аккаунт, показываем его действия
        account = accounts[0]
        await message.answer(
            f"✅ Найден аккаунт: {account['username']} (ID: {account['account_id']})",
            reply_markup=Keyboards.admin_user_actions(user_id, account['account_id'])
        )
    else:
        # Если несколько аккаунтов, показываем список
        accounts_text = f"🔍 <b>Найдено аккаунтов: {len(accounts)}</b>\n\n"
        
        for i, account in enumerate(accounts[:10], 1):
            accounts_text += (
                f"{i}. {account['username']} (ID: {account['account_id']})\n"
                f"   👑 Владелец: {account['owner_username'] or account['owner_user_id']}\n"
                f"   💰 Баланс: {account['balance']} Pulse\n\n"
            )
        
        if len(accounts) > 10:
            accounts_text += f"... и еще {len(accounts) - 10} аккаунтов\n\n"
        
        accounts_text += "Введите точный логин или ID для выбора аккаунта."
        
        await message.answer(
            accounts_text,
            reply_markup=Keyboards.admin_users_menu(user_id)
        )
    
    await state.clear()

@dp.message(AdminStates.user_actions)
async def process_admin_user_action(message: Message, state: FSMContext, is_admin: bool):
    """Обработка действий администратора над пользователями"""
    user_id = message.from_user.id
    
    if not is_admin:
        await message.answer("Доступ запрещен!")
        await state.clear()
        return
    
    data = await state.get_data()
    target_account_id = data.get('target_account_id')
    action = data.get('action')
    
    if not target_account_id or not action:
        await message.answer("Ошибка: данные утеряны!")
        await state.clear()
        return
    
    if action == "balance":
        try:
            amount = int(message.text.strip())
            
            success = db.update_account_balance(target_account_id, amount, user_id)
            
            if success:
                profile = db.get_profile(target_account_id)
                await message.answer(
                    f"✅ Баланс успешно обновлен!\n\n"
                    f"Новый баланс: {profile['balance']} Pulse",
                    reply_markup=Keyboards.admin_users_menu(user_id)
                )
            else:
                await message.answer(
                    f"❌ Ошибка при обновлении баланса!",
                    reply_markup=Keyboards.admin_users_menu(user_id)
                )
        except ValueError:
            await message.answer("Пожалуйста, введите целое число!")
            return
    
    elif action == "block":
        reason = message.text.strip()
        
        if not reason:
            await message.answer("Пожалуйста, укажите причину блокировки!")
            return
        
        success = db.block_account(target_account_id, user_id, reason)
        
        if success:
            await message.answer(
                f"✅ Аккаунт успешно заблокирован!\n\n"
                f"Причина: {reason}",
                reply_markup=Keyboards.admin_users_menu(user_id)
            )
        else:
            await message.answer(
                f"❌ Ошибка при блокировке аккаунта!",
                reply_markup=Keyboards.admin_users_menu(user_id)
            )
    
    await state.clear()

@dp.callback_query(F.data.startswith("cancel:"))
async def handle_cancel_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик отмены"""
    user_id = int(callback.data.split(":")[1])
    
    if callback.from_user.id != user_id:
        await callback.answer("Эта кнопка не для вас!")
        return
    
    await state.clear()
    await callback.message.edit_text(
        "❌ Действие отменено.",
        reply_markup=Keyboards.main_menu(user_id, False, user_id in ADMIN_IDS)
    )
    await callback.answer()

# ========== КОМАНДЫ УДАЛЕНИЯ СООБЩЕНИЙ В ГРУППАХ ==========
@dp.message(F.text.startswith("-соо"))
async def handle_delete_message(message: Message, is_logged_in: bool):
    """Команда удаления сообщений"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if message.chat.type not in ["group", "supergroup"]:
        return
    
    if not is_logged_in:
        await message.answer("❌ Вы должны быть зарегистрированы в боте!")
        try:
            await message.delete()
        except:
            pass
        return
    
    if not message.reply_to_message:
        await message.answer("❌ Ответьте на сообщение, которое нужно удалить!")
        try:
            await message.delete()
        except:
            pass
        return
    
    # Проверяем права
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        has_permission = chat_member.status in ["creator", "administrator"]
        
        # Проверяем права в базе данных
        if not has_permission:
            has_permission = db.has_delete_permission(chat_id, user_id)
        
        if not has_permission:
            await message.answer("❌ У вас нет прав на удаление сообщений!")
            try:
                await message.delete()
            except:
                pass
            return
        
        # Удаляем сообщение
        await message.reply_to_message.delete()
        await message.delete()
        
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения: {e}")

@dp.message(F.text.startswith("+удал соо"))
async def handle_grant_permission(message: Message, is_admin: bool):
    """Команда выдачи прав на удаление"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if message.chat.type not in ["group", "supergroup"]:
        return
    
    if not is_admin and user_id not in ADMIN_IDS:
        await message.answer("❌ Только администраторы могут выдавать права!")
        try:
            await message.delete()
        except:
            pass
        return
    
    # Проверяем, что отправитель - администратор или создатель чата
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        if chat_member.status not in ["creator", "administrator"]:
            await message.answer("❌ Только администраторы чата могут выдавать права!")
            try:
                await message.delete()
            except:
                pass
            return
    except:
        await message.answer("❌ Ошибка проверки прав!")
        try:
            await message.delete()
        except:
            pass
        return
    
    # Получаем целевого пользователя
    target_user_id = None
    
    if message.reply_to_message:
        target_user_id = message.reply_to_message.from_user.id
    else:
        parts = message.text.split()
        if len(parts) >= 3:
            try:
                target_user_id = int(parts[2])
            except ValueError:
                pass
    
    if not target_user_id:
        await message.answer(
            "❌ Не указан пользователь!\n\n"
            "Используйте:\n"
            "+удал соо (ответом на сообщение пользователя)\n"
            "или\n"
            "+удал соо [ID_пользователя]"
        )
        try:
            await message.delete()
        except:
            pass
        return
    
    # Проверяем, что целевой пользователь зарегистрирован в боте
    target_session = db.get_active_session(target_user_id)
    if not target_session:
        await message.answer("❌ Пользователь не зарегистрирован в боте!")
        try:
            await message.delete()
        except:
            pass
        return
    
    # Выдаем права
    success = db.grant_delete_permission(chat_id, target_user_id, user_id)
    
    if success:
        try:
            target_user = await bot.get_chat_member(chat_id, target_user_id)
            username = target_user.user.username or target_user.user.first_name
            await message.answer(f"✅ Пользователю @{username} выданы права на удаление сообщений!")
        except:
            await message.answer(f"✅ Пользователю с ID {target_user_id} выданы права на удаление сообщений!")
    else:
        await message.answer("❌ Ошибка при выдаче прав!")
    
    try:
        await message.delete()
    except:
        pass

@dp.message(F.text.startswith("-удал соо"))
async def handle_revoke_permission(message: Message, is_admin: bool):
    """Команда отзыва прав на удаление"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if message.chat.type not in ["group", "supergroup"]:
        return
    
    if not is_admin and user_id not in ADMIN_IDS:
        await message.answer("❌ Только администраторы могут отзывать права!")
        try:
            await message.delete()
        except:
            pass
        return
    
    # Проверяем, что отправитель - администратор или создатель чата
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        if chat_member.status not in ["creator", "administrator"]:
            await message.answer("❌ Только администраторы чата могут отзывать права!")
            try:
                await message.delete()
            except:
                pass
            return
    except:
        await message.answer("❌ Ошибка проверки прав!")
        try:
            await message.delete()
        except:
            pass
        return
    
    # Получаем целевого пользователя
    target_user_id = None
    
    if message.reply_to_message:
        target_user_id = message.reply_to_message.from_user.id
    else:
        parts = message.text.split()
        if len(parts) >= 3:
            try:
                target_user_id = int(parts[2])
            except ValueError:
                pass
    
    if not target_user_id:
        await message.answer(
            "❌ Не указан пользователь!\n\n"
            "Используйте:\n"
            "-удал соо (ответом на сообщение пользователя)\n"
            "или\n"
            "-удал соо [ID_пользователя]"
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
            username = target_user.user.username or target_user.user.first_name
            await message.answer(f"✅ Права на удаление сообщений отозваны у пользователя @{username}!")
        except:
            await message.answer(f"✅ Права на удаление сообщений отозваны у пользователя с ID {target_user_id}!")
    else:
        await message.answer("❌ Пользователь не имеет прав на удаление или произошла ошибка!")
    
    try:
        await message.delete()
    except:
        pass

@dp.message(Command("удалсписок"))
async def cmd_permission_list(message: Message, is_admin: bool):
    """Команда просмотра списка прав"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if message.chat.type not in ["group", "supergroup"]:
        return
    
    if not is_admin and user_id not in ADMIN_IDS:
        await message.answer("❌ Только администраторы могут просматривать список прав!")
        return
    
    # Получаем список пользователей с правами
    db.cursor.execute("""
        SELECT dp.user_id, dp.granted_by, dp.granted_at, dp.expires_at,
               tu.username as user_username, tu2.username as granter_username
        FROM delete_permissions dp
        LEFT JOIN telegram_users tu ON dp.user_id = tu.user_id
        LEFT JOIN telegram_users tu2 ON dp.granted_by = tu2.user_id
        WHERE dp.chat_id = ? AND dp.is_active = TRUE
        AND (dp.expires_at IS NULL OR dp.expires_at > CURRENT_TIMESTAMP)
        ORDER BY dp.granted_at DESC
    """, (chat_id,))
    
    permissions = db.cursor.fetchall()
    
    if not permissions:
        await message.answer("📋 <b>Список прав на удаление сообщений</b>\n\nНет активных прав в этом чате.")
        return
    
    permissions_text = "📋 <b>Список прав на удаление сообщений</b>\n\n"
    
    for perm in permissions:
        username = perm['user_username'] or f"ID: {perm['user_id']}"
        granter = perm['granter_username'] or f"ID: {perm['granted_by']}"
        granted_date = datetime.fromisoformat(perm['granted_at']).strftime("%d.%m.%Y %H:%M")
        
        expires_text = ""
        if perm['expires_at']:
            expires_date = datetime.fromisoformat(perm['expires_at'])
            expires_text = f"\n   ⏳ Истекает: {expires_date.strftime('%d.%m.%Y %H:%M')}"
        
        permissions_text += (
            f"👤 <b>{username}</b>\n"
            f"   🎖️ Выдал: {granter}\n"
            f"   📅 Дата выдачи: {granted_date}"
            f"{expires_text}\n\n"
        )
    
    await message.answer(permissions_text)

# ========== ОБРАБОТКА СТАРТА С РЕФЕРАЛЬНЫМ КОДОМ ==========
@dp.message(Command("start"))
async def cmd_start_with_ref(message: Message, command: CommandObject):
    """Обработка старта с реферальным кодом"""
    user_id = message.from_user.id
    
    if command.args and command.args.startswith("ref_"):
        referral_code = command.args[4:]  # Убираем "ref_"
        
        # Проверяем, не зарегистрирован ли уже пользователь
        session = db.get_active_session(user_id)
        if session:
            # Пользователь уже авторизован
            await cmd_start(message, True, session)
            return
        
        # Сохраняем реферальный код в состоянии
        from aiogram.fsm.context import FSMContext
        from aiogram.fsm.storage.base import StorageKey
        
        # Создаем состояние для регистрации с реферальным кодом
        # Это упрощенная версия, в реальном боте нужно использовать FSMContext
        await message.answer(
            f"👋 Добро пожаловать! Вы перешли по реферальной ссылке.\n\n"
            f"Код приглашения: {referral_code}\n\n"
            f"Чтобы получить бонус за регистрацию, используйте этот код при создании аккаунта.\n\n"
            f"Нажмите кнопку '📝 Регистрация' чтобы начать."
        )
    
    # Показываем обычное стартовое сообщение
    session = db.get_active_session(user_id)
    await cmd_start(message, session is not None, session)

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция"""
    logger.info("Запуск бота Pulse Bot...")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())

