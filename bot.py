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
from dataclasses import dataclass
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters.state import StateFilter

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
        # VIP пакеты (было 9 элементов, стало 8 - убрали последнее число)
        ("VIP на 30 дней", "VIP статус на 30 дней", "vip", 1000, 900, 30, None),
        ("VIP на 90 дней", "VIP статус на 90 дней", "vip", 2940, 2646, 90, None),
        ("VIP на 150 дней", "VIP статус на 150 дней", "vip", 4850, 4365, 150, None),
        ("VIP на 365 дней", "VIP статус на 365 дней", "vip", 11400, 10260, 365, None),
        
        # Бустеры
        ("Бустер заработка x2", "Удваивает заработок с работы на 24 часа", "booster", 500, 450, 1, 2),
        ("Бустер удачи x1.5", "Увеличивает шанс выигрыша на 50% на 24 часа", "booster", 750, 675, 1, 1.5),
        ("Бустер опыта x2", "Удваивает получаемый опыт на 24 часа", "booster", 300, 270, 1, 2),
        
        # Предметы
        ("Сундук с сокровищами", "Случайная награда от 100 до 1000 Pulse", "chest", 250, 225, None, None),
        ("Ключ удачи", "Гарантированный выигрыш в следующей игре", "item", 1500, 1350, None, None),
    ]
    
    for i, item in enumerate(shop_items):
        self.cursor.execute("""
            INSERT OR IGNORE INTO shop_items 
            (name, description, item_type, price, vip_price, duration_days, effect_value, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (*item, i*10))  # ← Здесь i*10 это 8-й параметр sort_order
    
    self.conn.commit()
    
    # === Управление пользователями ===
    def create_or_update_telegram_user(self, user: types.User):
        """Создает или обновляет пользователя Telegram"""
        self.cursor.execute("""
            INSERT OR REPLACE INTO telegram_users 
            (user_id, username, first_name, last_name, language_code, last_seen)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (user.id, user.username, user.first_name, user.last_name, user.language_code))
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
        return affected > 0
    
    # === Профили и балансы ===
    def get_profile(self, account_id: int) -> Optional[Dict]:
        """Получает профиль аккаунта"""
        self.cursor.execute("""
            SELECT p.*, a.username, a.owner_user_id, a.referral_code
            FROM profiles p
            JOIN accounts a ON p.account_id = a.account_id
            WHERE p.account_id = ?
        """, (account_id,))
        
        row = self.cursor.fetchone()
        return dict(row) if row else None
    
    def update_balance(self, account_id: int, amount: int, transaction_type: str, description: str = None) -> bool:
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
            self.add_transaction(account_id, amount, transaction_type, description)
            
            return True
        except Exception as e:
            logger.error(f"Ошибка обновления баланса: {e}")
            self.conn.rollback()
            return False
    
    def add_transaction(self, account_id: int, amount: int, transaction_type: str, description: str = None):
        """Добавляет запись о транзакции"""
        # Получаем текущий баланс
        self.cursor.execute("SELECT balance FROM profiles WHERE account_id = ?", (account_id,))
        balance_result = self.cursor.fetchone()
        
        if not balance_result:
            return
        
        current_balance = balance_result['balance']
        balance_before = current_balance - amount
        balance_after = current_balance
        
        self.cursor.execute("""
            INSERT INTO transactions 
            (account_id, amount, type, description, balance_before, balance_after)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (account_id, amount, transaction_type, description, balance_before, balance_after))
        
        self.conn.commit()
    
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
        
        self.conn.commit()
        return game_id
    
    def get_game_statistics(self, account_id: int = None) -> Dict:
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
                    CASE 
                        WHEN COUNT(*) > 0 THEN 
                            (SUM(CASE WHEN is_win THEN 1 ELSE 0 END) * 100.0 / COUNT(*))
                        ELSE 0 
                    END as win_rate
                FROM game_history 
                WHERE account_id = ?
            """, (account_id,))
            
            row = self.cursor.fetchone()
            if row:
                stats = dict(row)
        
        return stats
    
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
            price = item['price']  # Упрощенно, без VIP цены
            if profile['balance'] < price:
                return False, f"Недостаточно средств. Нужно: {price} Pulse", None
            
            # Списываем средства
            if not self.update_balance(account_id, -price, 
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
            """, (account_id, item_id, price, 
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
            
            purchase_data = {
                'purchase_id': purchase_id,
                'item_name': item['name'],
                'price_paid': price,
                'expires_at': expires_at,
                'effect': item['effect_value']
            }
            
            return True, "Покупка успешна!", purchase_data
            
        except Exception as e:
            logger.error(f"Ошибка покупки: {e}")
            return False, f"Ошибка покупки: {str(e)}", None
    
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

# ========== ИНИЦИАЛИЗАЦИЯ ==========
db = Database()
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=storage)

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

# Менеджер игр
class GameManager:
    def __init__(self):
        self.games = {
            GameType.RANDOM.value: RandomGame(),
            GameType.CHOICE.value: ChoiceGame(),
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
        bets = [min_bet, min_bet*2, min_bet*5, min_bet*10]
        bets = [b for b in bets if b <= balance and b >= min_bet]
        
        for i, bet in enumerate(bets):
            if i % 2 == 0:
                builder.row()
            builder.add(InlineKeyboardButton(text=f"{bet} Pulse", callback_data=f"game:bet:{user_id}:{game_type}:{bet}"))
        
        if len(bets) % 2 != 0:
            builder.row()
        
        builder.row(
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

# ========== ХЭНДЛЕРЫ КОМАНД ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Команда старт"""
    user_id = message.from_user.id
    
    # Обновляем информацию о пользователе
    db.create_or_update_telegram_user(message.from_user)
    
    # Проверяем активную сессию
    session = db.get_active_session(user_id)
    is_admin = user_id in ADMIN_IDS
    
    welcome_text = (
        "🎮 <b>Добро пожаловать в Pulse Bot!</b>\n\n"
        "<i>Игровой бот с экономикой, играми и розыгрышами</i>\n\n"
    )
    
    if session:
        profile = db.get_profile(session['account_id'])
        if profile:
            welcome_text += (
                f"👤 Вы вошли как: <code>{session['username']}</code>\n"
                f"💰 Баланс: <b>{profile['balance']}</b> Pulse\n\n"
            )
    
    welcome_text += "Выберите действие:"
    
    await message.answer(
        welcome_text,
        reply_markup=Keyboards.main_menu(user_id, session is not None, is_admin)
    )

@dp.message(Command("login"))
async def cmd_login(message: Message, state: FSMContext):
    """Команда входа"""
    user_id = message.from_user.id
    
    if message.chat.type != "private":
        await message.answer("Вход доступен только в личных сообщениях!")
        return
    
    session = db.get_active_session(user_id)
    if session:
        await message.answer("Вы уже авторизованы!")
        return
    
    await state.set_state(LoginStates.waiting_for_username)
    await message.answer(
        "🔐 <b>Вход в аккаунт</b>\n\n"
        "Введите ваш логин:",
        reply_markup=Keyboards.cancel_keyboard(user_id)
    )

@dp.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext):
    """Команда регистрации"""
    user_id = message.from_user.id
    
    if message.chat.type != "private":
        await message.answer("Регистрация доступна только в личных сообщениях!")
        return
    
    session = db.get_active_session(user_id)
    if session:
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
async def cmd_profile(message: Message):
    """Команда профиля"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    await show_profile(message, session)

@dp.message(Command("games"))
async def cmd_games(message: Message):
    """Команда игр"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    await show_games_menu(message, user_id)

@dp.message(Command("work"))
async def cmd_work(message: Message):
    """Команда работы"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    await show_work_menu(message, user_id)

@dp.message(Command("shop"))
async def cmd_shop(message: Message):
    """Команда магазина"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    await show_shop_menu(message, user_id)

@dp.message(Command("bonus"))
async def cmd_bonus(message: Message):
    """Команда бонуса"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
        await message.answer("Сначала войдите в аккаунт!")
        return
    
    await claim_bonus(message, session['account_id'])

@dp.message(Command("logout"))
async def cmd_logout(message: Message):
    """Команда выхода"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
        await message.answer("Вы не авторизованы!")
        return
    
    db.logout_session(user_id)
    await message.answer(
        "✅ Вы успешно вышли из аккаунта!",
        reply_markup=Keyboards.main_menu(user_id, False, user_id in ADMIN_IDS)
    )

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    """Команда админ-панели"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await message.answer("Доступ запрещен!")
        return
    
    await show_admin_menu(message, user_id)

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
        f"📉 Всего потрачено: {profile['total_spent']} Pulse\n"
    )
    
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

async def claim_bonus(message: Message, account_id: int):
    """Получение ежедневного бонуса"""
    # Упрощенная версия бонуса
    bonus_amount = 50
    
    if db.update_balance(account_id, bonus_amount, TransactionType.BONUS.value, "Ежедневный бонус"):
        await message.answer(
            f"🎁 <b>Ежедневный бонус!</b>\n\n"
            f"Вы получили ежедневный бонус: {bonus_amount} Pulse!\n\n"
            f"Следующий бонус через 24 часа.",
            reply_markup=Keyboards.main_menu(message.from_user.id, True, message.from_user.id in ADMIN_IDS)
        )
    else:
        await message.answer(
            f"❌ Ошибка получения бонуса!",
            reply_markup=Keyboards.main_menu(message.from_user.id, True, message.from_user.id in ADMIN_IDS)
        )

async def show_admin_menu(message: Message, user_id: int):
    """Показывает админ-меню"""
    await message.answer(
        "🛠 <b>Админ-панель</b>\n\nВ разработке...",
        reply_markup=Keyboards.main_menu(user_id, True, True)
    )

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
        await cmd_start(message)
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
    
    # Создаем аккаунт
    account_id = db.create_account(username, password, user_id)
    
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
        f"🎁 Начальный баланс: 100 Pulse\n\n"
        f"<b>Сохраните эти данные в надежном месте!</b>\n\n"
        f"Теперь вы можете пользоваться всеми функциями бота!",
        reply_markup=Keyboards.main_menu(user_id, True, user_id in ADMIN_IDS)
    )
    
    await state.clear()

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
        
        session = db.get_active_session(user_id)
        if session:
            await callback.message.edit_text("Вы уже авторизованы!")
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
        
        session = db.get_active_session(user_id)
        if session:
            await callback.message.edit_text("Вы уже авторизованы!")
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
async def handle_menu_callback(callback: CallbackQuery):
    """Обработчик меню"""
    data_parts = callback.data.split(":")
    action = data_parts[1]
    user_id = int(data_parts[2])
    
    if callback.from_user.id != user_id:
        await callback.answer("Эта кнопка не для вас!")
        return
    
    await callback.answer()
    
    session = db.get_active_session(user_id)
    is_admin = user_id in ADMIN_IDS
    
    if action == "main":
        await callback.message.edit_text(
            "🎮 <b>Главное меню</b>\n\nВыберите действие:",
            reply_markup=Keyboards.main_menu(user_id, session is not None, is_admin)
        )
    
    elif action == "games":
        if not session:
            await callback.message.edit_text("Сначала войдите в аккаунт!")
            return
        
        await show_games_menu(callback.message, user_id)
    
    elif action == "work":
        if not session:
            await callback.message.edit_text("Сначала войдите в аккаунт!")
            return
        
        await show_work_menu(callback.message, user_id)
    
    elif action == "shop":
        if not session:
            await callback.message.edit_text("Сначала войдите в аккаунт!")
            return
        
        await show_shop_menu(callback.message, user_id)
    
    elif action == "bonus":
        if not session:
            await callback.message.edit_text("Сначала войдите в аккаунт!")
            return
        
        await claim_bonus(callback.message, session['account_id'])
    
    elif action == "profile":
        if not session:
            await callback.message.edit_text("Сначала войдите в аккаунт!")
            return
        
        await show_profile(callback.message, session)
    
    elif action == "admin":
        if not is_admin:
            await callback.message.edit_text("Доступ запрещен!")
            return
        
        await show_admin_menu(callback.message, user_id)

@dp.callback_query(F.data.startswith("game:"))
async def handle_game_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик игр"""
    data_parts = callback.data.split(":")
    action = data_parts[1]
    user_id = int(data_parts[2])
    
    if callback.from_user.id != user_id:
        await callback.answer("Эта кнопка не для вас!")
        return
    
    session = db.get_active_session(user_id)
    if not session:
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

@dp.callback_query(F.data.startswith("work:"))
async def handle_work_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик работы"""
    data_parts = callback.data.split(":")
    action = data_parts[1]
    user_id = int(data_parts[2])
    
    if callback.from_user.id != user_id:
        await callback.answer("Эта кнопка не для вас!")
        return
    
    session = db.get_active_session(user_id)
    if not session:
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
async def process_work_answer(message: Message, state: FSMContext):
    """Обработка ответа на работу"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
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
async def handle_shop_callback(callback: CallbackQuery):
    """Обработчик магазина"""
    data_parts = callback.data.split(":")
    action = data_parts[1]
    user_id = int(data_parts[2])
    
    if callback.from_user.id != user_id:
        await callback.answer("Эта кнопка не для вас!")
        return
    
    session = db.get_active_session(user_id)
    if not session:
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
        price = item['price']
        can_afford = profile['balance'] >= price
        
        item_text = (
            f"🏪 <b>{item['name']}</b>\n\n"
            f"{item['description'] or 'Без описания'}\n\n"
            f"💰 Цена: {price} Pulse"
        )
        
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

@dp.callback_query(F.data.startswith("cancel:"))
async def handle_cancel_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик отмены"""
    user_id = int(callback.data.split(":")[1])
    
    if callback.from_user.id != user_id:
        await callback.answer("Эта кнопка не для вас!")
        return
    
    await state.clear()
    session = db.get_active_session(user_id)
    is_admin = user_id in ADMIN_IDS
    
    await callback.message.edit_text(
        "❌ Действие отменено.",
        reply_markup=Keyboards.main_menu(user_id, session is not None, is_admin)
    )
    await callback.answer()

# ========== КОМАНДЫ УДАЛЕНИЯ СООБЩЕНИЙ В ГРУППАХ ==========
@dp.message(F.text.startswith("-соо"))
async def handle_delete_message(message: Message):
    """Команда удаления сообщений"""
    user_id = message.from_user.id
    
    if message.chat.type not in ["group", "supergroup"]:
        return
    
    session = db.get_active_session(user_id)
    if not session:
        await message.answer("❌ Вы должны быть зарегистрированы в боте!")
        try:
            await message.delete()
        except Exception:
            pass
        return
    
    if not message.reply_to_message:
        await message.answer("❌ Ответьте на сообщение, которое нужно удалить!")
        try:
            await message.delete()
        except Exception:
            pass
        return
    
    # Проверяем права
    try:
        chat_member = await bot.get_chat_member(message.chat.id, user_id)
        has_permission = chat_member.status in ["creator", "administrator"]
        
        if not has_permission:
            await message.answer("❌ У вас нет прав на удаление сообщений!")
            try:
                await message.delete()
            except Exception:
                pass
            return
        
        # Удаляем сообщение
        await message.reply_to_message.delete()
        await message.delete()
        
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения: {e}")

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

