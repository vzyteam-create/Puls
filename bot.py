# PULSE BOT - ПОЛНЫЙ ФУНКЦИОНАЛ
import asyncio
import logging
import sqlite3
import random
import string
import time
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton, 
    InlineKeyboardMarkup, ReplyKeyboardRemove
)
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8557190026:AAGnqxtrAyZz-huihyGctKWNHgjt7w9lQTo"
OWNER_ID = 6708209142  # Владелец бота
ADMIN_IDS = [OWNER_ID]  # Начальный список админов
BOT_USERNAME = "@PulsOfficialManager_bot"

# Настройки по умолчанию
DEFAULT_SETTINGS = {
    "max_accounts_per_user": 3,
    "account_creation_cooldown": 3,  # дня
    "registration_bonus": 100,
    "min_bet": 25,
    "max_bet": 10000,
    "daily_bonus": 50,
    "daily_cooldown": 24,  # часа
    "work_cooldown": 30,  # минут
    "work_limit": 5,
    "work_limit_cooldown": 10,  # часов
    "game_limit": 5,
    "game_limit_cooldown": 3,  # часов
    "vip_multiplier": 1.5,
    "draw_participation_cooldown": 1,  # час
    "max_active_draws": 10,
}

# Игры
class GameType(Enum):
    RANDOM = "random"
    CHOICE = "choice"
    REACTION = "reaction"

GAMES_CONFIG = {
    GameType.RANDOM.value: {
        "name": "🎲 Рандом",
        "description": "Классическая игра на удачу",
        "win_chance": 0.45,
        "multiplier": 2.0,
        "min_bet": 25,
        "emoji": "🎲"
    },
    GameType.CHOICE.value: {
        "name": "🧠 Выбор",
        "description": "Выбери уровень риска",
        "options": [
            {"name": "🛡️ Безопасный", "multiplier": 1.5, "chance": 0.7},
            {"name": "⚔️ Рисковый", "multiplier": 3.0, "chance": 0.3},
            {"name": "☠️ Экстрим", "multiplier": 5.0, "chance": 0.15},
        ],
        "emoji": "🧠"
    },
    GameType.REACTION.value: {
        "name": "⚡ Реакция",
        "description": "Нажми кнопку в нужный момент",
        "min_bet": 50,
        "multiplier": 2.5,
        "emoji": "⚡"
    }
}

# Работа
WORK_TYPES = [
    {
        "name": "программист",
        "description": "Написание кода и решение технических задач",
        "min_reward": 80,
        "max_reward": 150,
        "questions": [
            "Что такое переменная в программировании?",
            "Какой язык программирования начинается с 'Py'?",
            "Что означает ООП?",
            "Какая структура данных используется для хранения пар ключ-значение?",
            "Что такое цикл for?"
        ],
        "answers": [
            ["переменная", "variable", "хранилище"],
            ["python", "питон"],
            ["объектно ориентированное программирование", "ооп", "object oriented"],
            ["словарь", "dictionary", "dict", "map", "хэш-таблица"],
            ["цикл", "for", "повторение", "iteration"]
        ],
        "emoji": "👨‍💻"
    },
    {
        "name": "дизайнер",
        "description": "Создание визуального контента и графики",
        "min_reward": 60,
        "max_reward": 120,
        "questions": [
            "Что такое RGB в дизайне?",
            "Назовите программу для векторной графики",
            "Что такое кернинг в типографике?",
            "Какой цвет получается при смешении красного и синего?",
            "Что такое UI/UX дизайн?"
        ],
        "answers": [
            ["цветовая модель", "red green blue", "rgb", "цвет"],
            ["illustrator", "adobe illustrator", "coreldraw", "figma", "вектор"],
            ["расстояние между буквами", "kerning", "интервал"],
            ["фиолетовый", "purple", "magenta", "пурпурный"],
            ["интерфейс", "user interface", "юзабилити", "опыт пользователя"]
        ],
        "emoji": "🎨"
    },
    {
        "name": "менеджер",
        "description": "Управление проектами и командами",
        "min_reward": 50,
        "max_reward": 100,
        "questions": [
            "Что такое KPI?",
            "Назовите методологию управления проектами",
            "Что такое дедлайн?",
            "Что такое agile?",
            "Как расшифровывается SWOT анализ?"
        ],
        "answers": [
            ["ключевой показатель эффективности", "kpi", "метрика"],
            ["agile", "scrum", "kanban", "waterfall", "методология"],
            ["крайний срок", "deadline", "срок сдачи"],
            ["гибкая методология", "agile", "подход", "гибкий"],
            ["сильные стороны слабые стороны возможности угрозы", "swot", "анализ"]
        ],
        "emoji": "👔"
    }
]

# VIP пакеты
VIP_PACKAGES = {
    30: {
        "price": 1000,
        "vip_price": 900,
        "bonuses": [
            "×1.5 к заработку с работы",
            "Скидка 10% в магазине",
            "Доступ к эксклюзивным играм"
        ],
        "description": "VIP на 30 дней с основными бонусами"
    },
    90: {
        "price": 2940,
        "vip_price": 2646,
        "bonuses": [
            "×1.5 к заработку с работы",
            "Скидка 10% в магазине",
            "Доступ ко всем играм",
            "Бонусные задания"
        ],
        "description": "VIP на 90 дней со скидкой 10%"
    },
    150: {
        "price": 4850,
        "vip_price": 4365,
        "bonuses": [
            "×1.5 к заработку с работы",
            "Скидка 10% в магазине",
            "Все игры и бонусы",
            "Приоритетная поддержка"
        ],
        "description": "VIP на 150 дней с максимальными бонусами"
    },
    365: {
        "price": 11400,
        "vip_price": 10260,
        "bonuses": [
            "×1.5 к заработку с работы",
            "Скидка 10% в магазине",
            "Все премиум функции",
            "Личная поддержка",
            "Эксклюзивные розыгрыши"
        ],
        "description": "Годовой VIP со всеми привилегиями"
    }
}

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pulse_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('pulse_bot.db', check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.create_tables()
        self.initialize_settings()
    
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
                FOREIGN KEY (owner_user_id) REFERENCES telegram_users(user_id)
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
            # Сессии
            '''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
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
            # Розыгрыши
            '''
            CREATE TABLE IF NOT EXISTS draws (
                draw_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                draw_type TEXT NOT NULL,
                prize_amount INTEGER,
                prize_description TEXT,
                max_participants INTEGER,
                current_participants INTEGER DEFAULT 0,
                winners_count INTEGER DEFAULT 1,
                start_date TIMESTAMP,
                end_date TIMESTAMP NOT NULL,
                require_channel_subscription BOOLEAN DEFAULT FALSE,
                channel_username TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by INTEGER
            )
            ''',
            # Участники розыгрышей
            '''
            CREATE TABLE IF NOT EXISTS draw_participants (
                participant_id INTEGER PRIMARY KEY AUTOINCREMENT,
                draw_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                ticket_number INTEGER,
                is_winner BOOLEAN DEFAULT FALSE,
                prize_received BOOLEAN DEFAULT FALSE,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (draw_id) REFERENCES draws(draw_id),
                FOREIGN KEY (account_id) REFERENCES accounts(account_id),
                UNIQUE(draw_id, account_id)
            )
            ''',
            # Администраторы
            '''
            CREATE TABLE IF NOT EXISTS admin_users (
                admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                role TEXT NOT NULL,
                permissions TEXT,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                FOREIGN KEY (user_id) REFERENCES telegram_users(user_id)
            )
            ''',
            # Настройки бота
            '''
            CREATE TABLE IF NOT EXISTS bot_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                description TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''',
            # Кулдауны
            '''
            CREATE TABLE IF NOT EXISTS cooldowns (
                cooldown_id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                last_action TIMESTAMP NOT NULL,
                expires_at TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id),
                UNIQUE(account_id, action_type)
            )
            ''',
        ]
        
        for table_sql in tables:
            try:
                self.cursor.execute(table_sql)
            except sqlite3.Error as e:
                logger.error(f"Ошибка создания таблицы: {e}")
        
        self.conn.commit()
    
    def initialize_settings(self):
        """Инициализация настроек по умолчанию"""
        for key, value in DEFAULT_SETTINGS.items():
            self.cursor.execute(
                "INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES (?, ?)",
                (key, str(value))
            )
        self.conn.commit()
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Получение настройки"""
        self.cursor.execute(
            "SELECT setting_value FROM bot_settings WHERE setting_key = ?",
            (key,)
        )
        result = self.cursor.fetchone()
        
        if result:
            try:
                return int(result[0])
            except ValueError:
                try:
                    return float(result[0])
                except ValueError:
                    return result[0]
        
        return default
    
    # Пользователи Telegram
    def create_or_update_telegram_user(self, user):
        """Создание или обновление пользователя Telegram"""
        self.cursor.execute('''
            INSERT OR REPLACE INTO telegram_users 
            (user_id, username, first_name, last_name, language_code, last_seen)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user.id, user.username, user.first_name, user.last_name, user.language_code))
        self.conn.commit()
    
    # Аккаунты
    def create_account(self, username: str, password: str, owner_id: int, recovery_code: str = None) -> Optional[int]:
        """Создание нового аккаунта"""
        try:
            # Проверяем лимит аккаунтов
            max_accounts = self.get_setting('max_accounts_per_user', 3)
            self.cursor.execute(
                "SELECT COUNT(*) FROM accounts WHERE owner_user_id = ?",
                (owner_id,)
            )
            account_count = self.cursor.fetchone()[0]
            
            if account_count >= max_accounts:
                return None
            
            # Проверяем кулдаун создания
            cooldown_days = self.get_setting('account_creation_cooldown', 3)
            self.cursor.execute('''
                SELECT created_at FROM accounts 
                WHERE owner_user_id = ? 
                ORDER BY created_at DESC LIMIT 1
            ''', (owner_id,))
            
            last_account = self.cursor.fetchone()
            if last_account:
                last_created = datetime.fromisoformat(last_account[0])
                if (datetime.now() - last_created).days < cooldown_days:
                    return None
            
            # Создаем аккаунт
            self.cursor.execute('''
                INSERT INTO accounts (username, password, recovery_code, owner_user_id)
                VALUES (?, ?, ?, ?)
            ''', (username, password, recovery_code, owner_id))
            
            account_id = self.cursor.lastrowid
            
            # Создаем профиль
            self.cursor.execute(
                "INSERT INTO profiles (account_id, balance) VALUES (?, ?)",
                (account_id, self.get_setting('registration_bonus', 100))
            )
            
            # Создаем сессию
            self.create_session(owner_id, account_id)
            
            # Добавляем транзакцию
            self.add_transaction(
                account_id,
                self.get_setting('registration_bonus', 100),
                'registration_bonus',
                'Бонус за регистрацию'
            )
            
            self.conn.commit()
            return account_id
            
        except sqlite3.IntegrityError as e:
            logger.error(f"Ошибка создания аккаунта: {e}")
            return None
    
    def get_account(self, username: str = None, account_id: int = None) -> Optional[Dict]:
        """Получение аккаунта"""
        if username:
            self.cursor.execute("SELECT * FROM accounts WHERE username = ?", (username,))
        elif account_id:
            self.cursor.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,))
        else:
            return None
        
        row = self.cursor.fetchone()
        return dict(row) if row else None
    
    def verify_account(self, username: str, password: str) -> Optional[Dict]:
        """Проверка учетных данных"""
        self.cursor.execute('''
            SELECT * FROM accounts 
            WHERE username = ? AND password = ? AND is_blocked = FALSE
        ''', (username, password))
        
        row = self.cursor.fetchone()
        if row:
            account = dict(row)
            
            # Обновляем последнюю активность
            self.cursor.execute('''
                UPDATE telegram_users 
                SET last_seen = CURRENT_TIMESTAMP 
                WHERE user_id = ?
            ''', (account['owner_user_id'],))
            
            self.conn.commit()
            return account
        
        return None
    
    # Сессии
    def create_session(self, user_id: int, account_id: int, duration_days: int = 30) -> int:
        """Создание новой сессии"""
        expires_at = datetime.now() + timedelta(days=duration_days)
        
        # Деактивируем старые сессии
        self.cursor.execute('''
            UPDATE sessions SET is_active = FALSE 
            WHERE user_id = ? AND is_active = TRUE
        ''', (user_id,))
        
        # Создаем новую сессию
        self.cursor.execute('''
            INSERT INTO sessions (user_id, account_id, expires_at)
            VALUES (?, ?, ?)
        ''', (user_id, account_id, expires_at.isoformat()))
        
        session_id = self.cursor.lastrowid
        self.conn.commit()
        return session_id
    
    def get_active_session(self, user_id: int) -> Optional[Dict]:
        """Получение активной сессии"""
        self.cursor.execute('''
            SELECT s.*, a.username, a.owner_user_id, p.balance, p.vip_until,
                   (p.vip_until IS NOT NULL AND p.vip_until > CURRENT_TIMESTAMP) as is_vip
            FROM sessions s
            JOIN accounts a ON s.account_id = a.account_id
            LEFT JOIN profiles p ON s.account_id = p.account_id
            WHERE s.user_id = ? AND s.is_active = TRUE 
            AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP)
            ORDER BY s.created_at DESC LIMIT 1
        ''', (user_id,))
        
        row = self.cursor.fetchone()
        return dict(row) if row else None
    
    # Профили и балансы
    def get_profile(self, account_id: int) -> Optional[Dict]:
        """Получение профиля"""
        self.cursor.execute('''
            SELECT p.*, a.username, a.owner_user_id
            FROM profiles p
            JOIN accounts a ON p.account_id = a.account_id
            WHERE p.account_id = ?
        ''', (account_id,))
        
        row = self.cursor.fetchone()
        return dict(row) if row else None
    
    def update_balance(self, account_id: int, amount: int, transaction_type: str, description: str = None) -> bool:
        """Обновление баланса"""
        try:
            self.cursor.execute('''
                UPDATE profiles 
                SET balance = balance + ?, 
                    updated_at = CURRENT_TIMESTAMP,
                    total_earned = total_earned + CASE WHEN ? > 0 THEN ? ELSE 0 END,
                    total_spent = total_spent + CASE WHEN ? < 0 THEN ABS(?) ELSE 0 END
                WHERE account_id = ?
            ''', (amount, amount, amount, amount, amount, account_id))
            
            # Добавляем транзакцию
            self.add_transaction(account_id, amount, transaction_type, description)
            
            return True
        except Exception as e:
            logger.error(f"Ошибка обновления баланса: {e}")
            self.conn.rollback()
            return False
    
    def add_transaction(self, account_id: int, amount: int, transaction_type: str, description: str = None):
        """Добавление транзакции"""
        self.cursor.execute('''
            INSERT INTO transactions (account_id, amount, type, description)
            VALUES (?, ?, ?, ?)
        ''', (account_id, amount, transaction_type, description))
        self.conn.commit()
    
    # Игры
    def record_game(self, account_id: int, game_type: str, bet: int, win: bool, win_amount: int = None, details: str = None) -> int:
        """Запись результата игры"""
        self.cursor.execute('''
            INSERT INTO game_history (account_id, game_type, bet_amount, is_win, win_amount, details)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (account_id, game_type, bet, win, win_amount, details))
        
        game_id = self.cursor.lastrowid
        
        # Обновляем статистику
        self.cursor.execute('''
            UPDATE profiles 
            SET games_played = games_played + 1,
                games_won = games_won + ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE account_id = ?
        ''', (1 if win else 0, account_id))
        
        self.conn.commit()
        return game_id
    
    # Работа
    def record_work(self, account_id: int, work_type: str, earnings: int, task_details: str = None):
        """Запись выполненной работы"""
        self.cursor.execute('''
            INSERT INTO work_history (account_id, work_type, earnings, task_details)
            VALUES (?, ?, ?, ?)
        ''', (account_id, work_type, earnings, task_details))
        
        # Обновляем профиль
        self.cursor.execute('''
            UPDATE profiles 
            SET work_count = work_count + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE account_id = ?
        ''', (account_id,))
        
        self.conn.commit()
    
    def get_last_work_time(self, account_id: int) -> Optional[datetime]:
        """Получение времени последней работы"""
        self.cursor.execute('''
            SELECT MAX(completed_at) as last_work 
            FROM work_history 
            WHERE account_id = ?
        ''', (account_id,))
        
        result = self.cursor.fetchone()
        if result and result[0]:
            return datetime.fromisoformat(result[0])
        return None
    
    # VIP
    def activate_vip(self, account_id: int, days: int) -> bool:
        """Активация VIP статуса"""
        try:
            profile = self.get_profile(account_id)
            if not profile:
                return False
            
            current_vip_until = profile.get('vip_until')
            if current_vip_until and datetime.fromisoformat(current_vip_until) > datetime.now():
                new_vip_until = datetime.fromisoformat(current_vip_until) + timedelta(days=days)
            else:
                new_vip_until = datetime.now() + timedelta(days=days)
            
            self.cursor.execute('''
                UPDATE profiles 
                SET vip_until = ?, vip_level = vip_level + 1
                WHERE account_id = ?
            ''', (new_vip_until.isoformat(), account_id))
            
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка активации VIP: {e}")
            return False
    
    # Розыгрыши
    def create_draw(self, name: str, description: str, draw_type: str, prize_amount: int, 
                    prize_description: str, max_participants: int, winners_count: int,
                    end_date: datetime, require_channel_subscription: bool = False,
                    channel_username: str = None, created_by: int = None) -> Optional[int]:
        """Создание розыгрыша"""
        try:
            self.cursor.execute('''
                INSERT INTO draws 
                (name, description, draw_type, prize_amount, prize_description, 
                 max_participants, winners_count, end_date, 
                 require_channel_subscription, channel_username, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (name, description, draw_type, prize_amount, prize_description,
                  max_participants, winners_count, end_date.isoformat(),
                  require_channel_subscription, channel_username, created_by))
            
            draw_id = self.cursor.lastrowid
            self.conn.commit()
            return draw_id
        except Exception as e:
            logger.error(f"Ошибка создания розыгрыша: {e}")
            return None
    
    def join_draw(self, draw_id: int, account_id: int) -> Tuple[bool, str, Optional[int]]:
        """Участие в розыгрыше"""
        try:
            # Проверяем существование розыгрыша
            self.cursor.execute("SELECT * FROM draws WHERE draw_id = ? AND is_active = TRUE", (draw_id,))
            draw = self.cursor.fetchone()
            if not draw:
                return False, "Розыгрыш не найден или завершен", None
            
            draw = dict(draw)
            
            # Проверяем время розыгрыша
            end_date = datetime.fromisoformat(draw['end_date'])
            if datetime.now() > end_date:
                return False, "Розыгрыш уже завершен", None
            
            # Проверяем лимит участников
            if draw['max_participants'] and draw['current_participants'] >= draw['max_participants']:
                return False, "Достигнут лимит участников", None
            
            # Проверяем, не участвует ли уже пользователь
            self.cursor.execute(
                "SELECT 1 FROM draw_participants WHERE draw_id = ? AND account_id = ?",
                (draw_id, account_id)
            )
            if self.cursor.fetchone():
                return False, "Вы уже участвуете в этом розыгрыше", None
            
            # Генерируем номер билета
            ticket_number = random.randint(1000, 9999)
            
            # Добавляем участника
            self.cursor.execute('''
                INSERT INTO draw_participants (draw_id, account_id, ticket_number)
                VALUES (?, ?, ?)
            ''', (draw_id, account_id, ticket_number))
            
            # Обновляем счетчик участников
            self.cursor.execute('''
                UPDATE draws 
                SET current_participants = current_participants + 1 
                WHERE draw_id = ?
            ''', (draw_id,))
            
            self.conn.commit()
            return True, f"Вы успешно присоединились к розыгрышу! Ваш билет №{ticket_number}", ticket_number
            
        except Exception as e:
            logger.error(f"Ошибка участия в розыгрыше: {e}")
            return False, f"Ошибка: {str(e)}", None
    
    def get_active_draws(self, limit: int = 10) -> List[Dict]:
        """Получение активных розыгрышей"""
        self.cursor.execute('''
            SELECT * FROM draws 
            WHERE is_active = TRUE AND end_date > CURRENT_TIMESTAMP
            ORDER BY end_date ASC 
            LIMIT ?
        ''', (limit,))
        
        return [dict(row) for row in self.cursor.fetchall()]
    
    # Администраторы
    def is_admin(self, user_id: int) -> bool:
        """Проверка, является ли пользователь администратором"""
        if user_id == OWNER_ID:
            return True
        
        self.cursor.execute('''
            SELECT 1 FROM admin_users 
            WHERE user_id = ? AND is_active = TRUE
        ''', (user_id,))
        
        return self.cursor.fetchone() is not None
    
    def add_admin(self, user_id: int, role: str, permissions: str, added_by: int) -> bool:
        """Добавление администратора"""
        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO admin_users (user_id, role, permissions, added_by)
                VALUES (?, ?, ?, ?)
            ''', (user_id, role, permissions, added_by))
            
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка добавления администратора: {e}")
            return False
    
    def remove_admin(self, user_id: int) -> bool:
        """Удаление администратора"""
        try:
            self.cursor.execute('''
                UPDATE admin_users 
                SET is_active = FALSE 
                WHERE user_id = ?
            ''', (user_id,))
            
            affected = self.cursor.rowcount
            self.conn.commit()
            return affected > 0
        except Exception as e:
            logger.error(f"Ошибка удаления администратора: {e}")
            return False
    
    # Кулдауны
    def check_cooldown(self, account_id: int, action_type: str) -> Tuple[bool, Optional[datetime]]:
        """Проверка кулдауна"""
        self.cursor.execute('''
            SELECT last_action, expires_at 
            FROM cooldowns 
            WHERE account_id = ? AND action_type = ?
        ''', (account_id, action_type))
        
        result = self.cursor.fetchone()
        if not result:
            return True, None
        
        last_action = datetime.fromisoformat(result[0])
        expires_at = datetime.fromisoformat(result[1]) if result[1] else None
        
        if expires_at and datetime.now() < expires_at:
            return False, expires_at
        
        return True, None
    
    def set_cooldown(self, account_id: int, action_type: str, duration_seconds: int):
        """Установка кулдауна"""
        last_action = datetime.now()
        expires_at = last_action + timedelta(seconds=duration_seconds)
        
        self.cursor.execute('''
            INSERT OR REPLACE INTO cooldowns (account_id, action_type, last_action, expires_at)
            VALUES (?, ?, ?, ?)
        ''', (account_id, action_type, last_action.isoformat(), expires_at.isoformat()))
        
        self.conn.commit()
    
    # Статистика
    def get_statistics(self) -> Dict[str, Any]:
        """Получение статистики бота"""
        stats = {}
        
        # Количество пользователей
        self.cursor.execute("SELECT COUNT(*) FROM telegram_users")
        stats['total_users'] = self.cursor.fetchone()[0]
        
        # Количество аккаунтов
        self.cursor.execute("SELECT COUNT(*) FROM accounts")
        stats['total_accounts'] = self.cursor.fetchone()[0]
        
        # Общий баланс
        self.cursor.execute("SELECT SUM(balance) FROM profiles")
        stats['total_balance'] = self.cursor.fetchone()[0] or 0
        
        # Игр сегодня
        self.cursor.execute("SELECT COUNT(*) FROM game_history WHERE DATE(created_at) = DATE('now')")
        stats['games_today'] = self.cursor.fetchone()[0]
        
        # Активных розыгрышей
        self.cursor.execute("SELECT COUNT(*) FROM draws WHERE is_active = TRUE AND end_date > CURRENT_TIMESTAMP")
        stats['active_draws'] = self.cursor.fetchone()[0]
        
        return stats

# Инициализация базы данных
db = Database()

# ========== СОСТОЯНИЯ ==========
class RegistrationState(StatesGroup):
    waiting_for_username = State()
    waiting_for_password = State()
    waiting_for_recovery = State()

class LoginState(StatesGroup):
    waiting_for_username = State()
    waiting_for_password = State()

class GameState(StatesGroup):
    choosing_bet = State()
    playing = State()

class WorkState(StatesGroup):
    choosing_type = State()
    answering_question = State()

class DrawState(StatesGroup):
    creating = State()
    joining = State()

class AdminState(StatesGroup):
    managing_users = State()
    managing_draws = State()
    managing_settings = State()

# ========== ИНИЦИАЛИЗАЦИЯ БОТА ==========
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ========== КЛАВИАТУРЫ ==========
class Keyboards:
    @staticmethod
    def main_menu(user_id: int, is_logged_in: bool = False, is_admin: bool = False) -> InlineKeyboardMarkup:
        """Главное меню"""
        buttons = []
        
        if not is_logged_in:
            buttons.append([
                InlineKeyboardButton(text="🔐 Войти", callback_data=f"auth:login:{user_id}"),
                InlineKeyboardButton(text="📝 Регистрация", callback_data=f"auth:register:{user_id}")
            ])
        else:
            buttons.append([
                InlineKeyboardButton(text="🎮 Игры", callback_data=f"menu:games:{user_id}"),
                InlineKeyboardButton(text="💼 Работа", callback_data=f"menu:work:{user_id}")
            ])
            buttons.append([
                InlineKeyboardButton(text="🏪 Магазин", callback_data=f"menu:shop:{user_id}"),
                InlineKeyboardButton(text="🎁 Бонус", callback_data=f"menu:bonus:{user_id}")
            ])
            buttons.append([
                InlineKeyboardButton(text="👤 Профиль", callback_data=f"menu:profile:{user_id}"),
                InlineKeyboardButton(text="📊 Статистика", callback_data=f"menu:stats:{user_id}")
            ])
            buttons.append([
                InlineKeyboardButton(text="🎫 Розыгрыши", callback_data=f"menu:draws:{user_id}"),
                InlineKeyboardButton(text="ℹ️ Помощь", callback_data=f"menu:help:{user_id}")
            ])
            buttons.append([
                InlineKeyboardButton(text="🚪 Выйти", callback_data=f"auth:logout:{user_id}")
            ])
        
        if is_admin:
            buttons.append([
                InlineKeyboardButton(text="🛠 Админ-панель", callback_data=f"admin:main:{user_id}")
            ])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def help_menu(user_id: int, page: int = 1) -> InlineKeyboardMarkup:
        """Меню помощи с пагинацией"""
        help_pages = [
            {
                "title": "🎮 ИГРЫ",
                "content": (
                    "🎲 <b>Рандом</b> - классическая игра на удачу (шанс 45%, ×2)\n"
                    "🧠 <b>Выбор</b> - выбери уровень риска (×1.5-×5.0)\n"
                    "⚡ <b>Реакция</b> - нажми кнопку в нужный момент (×2.5)\n\n"
                    "💰 <b>Минимальная ставка:</b> 25 Pulse\n"
                    "💎 <b>VIP бонус:</b> ×1.5 к выигрышам!"
                ),
                "buttons": ["🎲 Рандом", "🧠 Выбор", "⚡ Реакция"]
            },
            {
                "title": "💼 РАБОТА",
                "content": (
                    "👨‍💻 <b>Программист</b> - 80-150 Pulse\n"
                    "🎨 <b>Дизайнер</b> - 60-120 Pulse\n"
                    "👔 <b>Менеджер</b> - 50-100 Pulse\n\n"
                    "⏰ <b>Кулдаун:</b> 30 минут\n"
                    "📊 <b>Лимит:</b> 5 работ в 10 часов\n"
                    "⭐ <b>VIP бонус:</b> ×1.5 к заработку!"
                ),
                "buttons": ["👨‍💻 Программист", "🎨 Дизайнер", "👔 Менеджер"]
            },
            {
                "title": "💎 VIP СТАТУС",
                "content": (
                    "💎 <b>VIP 30 дней</b> - 1000 Pulse (скидка 10%)\n"
                    "💎 <b>VIP 90 дней</b> - 2940 Pulse\n"
                    "💎 <b>VIP 150 дней</b> - 4850 Pulse\n"
                    "💎 <b>VIP 365 дней</b> - 11400 Pulse\n\n"
                    "🎁 <b>Бонусы VIP:</b>\n"
                    "• ×1.5 к заработку и выигрышам\n"
                    "• Скидка 10% в магазине\n"
                    "• Доступ к эксклюзивным функциям"
                ),
                "buttons": ["💎 Купить VIP", "⭐ Мои бонусы"]
            },
            {
                "title": "🎫 РОЗЫГРЫШИ",
                "content": (
                    "🎁 <b>Пульс-розыгрыши</b> - автоматические призы\n"
                    "🎯 <b>Произвольные</b> - ручное вручение\n\n"
                    "📝 <b>Как участвовать:</b>\n"
                    "1. Выберите активный розыгрыш\n"
                    "2. Нажмите 'Участвовать'\n"
                    "3. Получите номер билета\n"
                    "4. Ждите результатов!\n\n"
                    "⏰ <b>Кулдаун:</b> 1 час между участиями"
                ),
                "buttons": ["🎫 Активные розыгрыши", "🎁 Участвовать"]
            },
            {
                "title": "🔐 АККАУНТ",
                "content": (
                    "📝 <b>Регистрация:</b> максимум 3 аккаунта\n"
                    "⏰ <b>Кулдаун:</b> 3 дня между созданиями\n"
                    "🔐 <b>Пароль:</b> 5-20 символов, буквы+цифры\n"
                    "🗝️ <b>Кодовое слово:</b> для восстановления\n\n"
                    "💰 <b>Бонус за регистрацию:</b> 100 Pulse\n"
                    "🎁 <b>Ежедневный бонус:</b> 50 Pulse"
                ),
                "buttons": ["📝 Регистрация", "🔐 Войти", "🗝️ Восстановить"]
            },
            {
                "title": "📊 СТАТИСТИКА",
                "content": (
                    "👤 <b>Ваш профиль:</b> баланс, игры, работа\n"
                    "🏆 <b>Топ игроков:</b> по балансу и победам\n"
                    "📈 <b>Общая статистика:</b> бота и сообщества\n\n"
                    "💡 <b>Советы:</b>\n"
                    "• Начинайте с безопасных ставок\n"
                    "• Регулярно получайте бонусы\n"
                    "• Приобретайте VIP для ускорения\n"
                    "• Участвуйте в розыгрышах"
                ),
                "buttons": ["👤 Мой профиль", "🏆 Топ игроков", "📈 Статистика"]
            }
        ]
        
        page_data = help_pages[page - 1]
        total_pages = len(help_pages)
        
        buttons = []
        
        # Кнопки раздела
        if page == 1:  # Игры
            buttons.append([InlineKeyboardButton(text="🎲 Играть в Рандом", callback_data=f"help:game:random:{user_id}")])
            buttons.append([InlineKeyboardButton(text="🧠 Играть в Выбор", callback_data=f"help:game:choice:{user_id}")])
        elif page == 2:  # Работа
            buttons.append([InlineKeyboardButton(text="💼 Начать работать", callback_data=f"help:work:start:{user_id}")])
        elif page == 3:  # VIP
            buttons.append([InlineKeyboardButton(text="💎 Купить VIP статус", callback_data=f"help:shop:vip:{user_id}")])
        elif page == 4:  # Розыгрыши
            buttons.append([InlineKeyboardButton(text="🎫 Участвовать в розыгрыше", callback_data=f"help:draw:join:{user_id}")])
        elif page == 5:  # Аккаунт
            buttons.append([InlineKeyboardButton(text="📝 Зарегистрироваться", callback_data=f"help:auth:register:{user_id}")])
            buttons.append([InlineKeyboardButton(text="🔐 Войти в аккаунт", callback_data=f"help:auth:login:{user_id}")])
        elif page == 6:  # Статистика
            buttons.append([InlineKeyboardButton(text="👤 Открыть профиль", callback_data=f"help:profile:{user_id}")])
        
        # Навигация
        nav_buttons = []
        
        # Первая страница
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⏪", callback_data=f"help:page:1:{user_id}"))
        
        # Предыдущая страница
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"help:page:{page-1}:{user_id}"))
        
        # Номер страницы
        nav_buttons.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data=f"help:current:{user_id}"))
        
        # Следующая страница
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"help:page:{page+1}:{user_id}"))
        
        # Последняя страница
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="⏩", callback_data=f"help:page:{total_pages}:{user_id}"))
        
        if nav_buttons:
            buttons.append(nav_buttons)
        
        # Кнопки навигации
        buttons.append([
            InlineKeyboardButton(text="🎮 Игры", callback_data=f"help:page:1:{user_id}"),
            InlineKeyboardButton(text="💼 Работа", callback_data=f"help:page:2:{user_id}"),
            InlineKeyboardButton(text="💎 VIP", callback_data=f"help:page:3:{user_id}")
        ])
        buttons.append([
            InlineKeyboardButton(text="🎫 Розыгрыши", callback_data=f"help:page:4:{user_id}"),
            InlineKeyboardButton(text="🔐 Аккаунт", callback_data=f"help:page:5:{user_id}"),
            InlineKeyboardButton(text="📊 Статистика", callback_data=f"help:page:6:{user_id}")
        ])
        
        buttons.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data=f"menu:main:{user_id}")])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def games_menu(user_id: int) -> InlineKeyboardMarkup:
        """Меню игр"""
        buttons = []
        
        for game_type, game_config in GAMES_CONFIG.items():
            min_bet = game_config.get('min_bet', db.get_setting('min_bet', 25))
            buttons.append([
                InlineKeyboardButton(
                    text=f"{game_config['emoji']} {game_config['name']} - от {min_bet} Pulse",
                    callback_data=f"game:select:{game_type}:{user_id}"
                )
            ])
        
        buttons.append([
            InlineKeyboardButton(text="ℹ️ Правила игр", callback_data=f"help:page:1:{user_id}"),
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"menu:main:{user_id}")
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def bet_menu(user_id: int, game_type: str, balance: int) -> InlineKeyboardMarkup:
        """Меню выбора ставки"""
        min_bet = GAMES_CONFIG.get(game_type, {}).get('min_bet', db.get_setting('min_bet', 25))
        max_bet = min(balance, db.get_setting('max_bet', 10000))
        
        # Стандартные ставки
        bet_options = [min_bet, min_bet*2, min_bet*5, min_bet*10, min_bet*20]
        bet_options = [b for b in bet_options if b <= max_bet and b >= min_bet]
        
        # Добавляем пользовательскую ставку если есть варианты
        if len(bet_options) < 5:
            bet_options.append(max_bet)
        
        buttons = []
        row = []
        
        for i, bet in enumerate(bet_options[:6]):  # Максимум 6 кнопок
            if i % 2 == 0 and i > 0:
                buttons.append(row)
                row = []
            row.append(InlineKeyboardButton(
                text=f"{bet} Pulse",
                callback_data=f"game:bet:{game_type}:{bet}:{user_id}"
            ))
        
        if row:
            buttons.append(row)
        
        # Кнопка "Другая сумма"
        if max_bet > bet_options[-1]:
            buttons.append([
                InlineKeyboardButton(
                    text=f"💎 Другая сумма (до {max_bet} Pulse)",
                    callback_data=f"game:custom:{game_type}:{user_id}"
                )
            ])
        
        buttons.append([
            InlineKeyboardButton(text="🔙 Назад к играм", callback_data=f"menu:games:{user_id}"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data=f"menu:main:{user_id}")
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def choice_game_menu(user_id: int) -> InlineKeyboardMarkup:
        """Меню выбора уровня риска для игры Choice"""
        buttons = []
        
        for option in GAMES_CONFIG[GameType.CHOICE.value]['options']:
            chance_percent = option['chance'] * 100
            buttons.append([
                InlineKeyboardButton(
                    text=f"{option['name']} (шанс {chance_percent:.0f}%, ×{option['multiplier']})",
                    callback_data=f"game:choice:{option['name'].split()[1].lower()}:{user_id}"
                )
            ])
        
        buttons.append([
            InlineKeyboardButton(text="🔙 Назад к играм", callback_data=f"menu:games:{user_id}"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data=f"menu:main:{user_id}")
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def work_menu(user_id: int) -> InlineKeyboardMarkup:
        """Меню работы"""
        buttons = []
        
        for work in WORK_TYPES:
            buttons.append([
                InlineKeyboardButton(
                    text=f"{work['emoji']} {work['name'].capitalize()} ({work['min_reward']}-{work['max_reward']} Pulse)",
                    callback_data=f"work:select:{work['name']}:{user_id}"
                )
            ])
        
        buttons.append([
            InlineKeyboardButton(text="ℹ️ О работе", callback_data=f"help:page:2:{user_id}"),
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"menu:main:{user_id}")
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def shop_menu(user_id: int, balance: int) -> InlineKeyboardMarkup:
        """Меню магазина"""
        buttons = []
        
        # VIP пакеты
        for days, data in VIP_PACKAGES.items():
            price = data['vip_price']  # Уже со скидкой для VIP
            buttons.append([
                InlineKeyboardButton(
                    text=f"💎 VIP {days} дней - {price} Pulse",
                    callback_data=f"shop:vip:{days}:{user_id}"
                )
            ])
        
        # Разделитель
        buttons.append([
            InlineKeyboardButton(text="🚀 Бустеры (скоро)", callback_data=f"shop:soon:{user_id}"),
            InlineKeyboardButton(text="🎁 Предметы (скоро)", callback_data=f"shop:soon:{user_id}")
        ])
        
        # Баланс
        buttons.append([
            InlineKeyboardButton(text=f"💰 Баланс: {balance:,} Pulse", callback_data=f"menu:profile:{user_id}")
        ])
        
        buttons.append([
            InlineKeyboardButton(text="ℹ️ О магазине", callback_data=f"help:page:3:{user_id}"),
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"menu:main:{user_id}")
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def draws_menu(user_id: int) -> InlineKeyboardMarkup:
        """Меню розыгрышей"""
        buttons = []
        
        # Активные розыгрыши
        active_draws = db.get_active_draws(3)
        
        if not active_draws:
            buttons.append([
                InlineKeyboardButton(text="🎫 Нет активных розыгрышей", callback_data=f"draws:none:{user_id}")
            ])
        else:
            for draw in active_draws[:3]:  # Показываем максимум 3
                draw_name = draw['name'][:20] + "..." if len(draw['name']) > 20 else draw['name']
                participants = f"{draw['current_participants']}/{draw['max_participants'] or '∞'}"
                
                buttons.append([
                    InlineKeyboardButton(
                        text=f"🎁 {draw_name} ({participants} участ.)",
                        callback_data=f"draw:view:{draw['draw_id']}:{user_id}"
                    )
                ])
        
        # Кнопки действий
        buttons.append([
            InlineKeyboardButton(text="🎯 Участвовать", callback_data=f"draw:join:{user_id}"),
            InlineKeyboardButton(text="📋 Мои участия", callback_data=f"draw:mylist:{user_id}")
        ])
        
        # Для админов
        if db.is_admin(user_id):
            buttons.append([
                InlineKeyboardButton(text="🛠 Создать розыгрыш", callback_data=f"admin:draw:create:{user_id}")
            ])
        
        buttons.append([
            InlineKeyboardButton(text="ℹ️ О розыгрышах", callback_data=f"help:page:4:{user_id}"),
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"menu:main:{user_id}")
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def admin_menu(user_id: int) -> InlineKeyboardMarkup:
        """Админ-панель"""
        buttons = [
            [InlineKeyboardButton(text="👥 Управление пользователями", callback_data=f"admin:users:{user_id}")],
            [InlineKeyboardButton(text="🎮 Управление играми", callback_data=f"admin:games:{user_id}")],
            [InlineKeyboardButton(text="🎫 Управление розыгрышами", callback_data=f"admin:draws:{user_id}")],
            [InlineKeyboardButton(text="⚙️ Настройки бота", callback_data=f"admin:settings:{user_id}")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data=f"admin:stats:{user_id}")],
            [InlineKeyboardButton(text="📋 Логи действий", callback_data=f"admin:logs:{user_id}")],
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data=f"menu:main:{user_id}")]
        ]
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@dp.message(Command("start", "startpuls"))
async def cmd_start(message: Message, command: CommandObject = None):
    """Команда старт"""
    user_id = message.from_user.id
    db.create_or_update_telegram_user(message.from_user)
    
    # Проверяем реферальную ссылку
    if command and command.args and command.args.startswith('ref_'):
        # Здесь можно добавить логику реферальной системы
        pass
    
    session = db.get_active_session(user_id)
    is_admin = db.is_admin(user_id)
    
    welcome_text = (
        "🎮 <b>Добро пожаловать в PulseBot!</b>\n\n"
        "🌟 <i>Здесь вы можете играть в игры, участвовать в розыгрышах, "
        "выполнять работу, получать бонусы, повышать VIP-статус и управлять аккаунтом.</i>\n\n"
    )
    
    if session:
        profile = db.get_profile(session['account_id'])
        if profile:
            welcome_text += (
                f"👤 <b>Вы вошли как:</b> <code>{session['username']}</code>\n"
                f"💰 <b>Ваш баланс:</b> <b>{profile['balance']:,}</b> Pulse\n"
                f"⭐ <b>VIP статус:</b> {'<b>✅ АКТИВЕН</b>' if session.get('is_vip') else '❌ Неактивен'}\n\n"
            )
    else:
        welcome_text += (
            "👤 <b>Если у вас уже есть аккаунт</b> — войдите через кнопку «Войти».\n"
            "📝 <b>Если вы новый пользователь</b> — зарегистрируйтесь через кнопку «Регистрация».\n\n"
            "🔒 <i>Все функции доступны только в личных сообщениях.</i>\n\n"
        )
    
    welcome_text += "👇 <b>Выберите действие:</b>"
    
    await message.answer(
        welcome_text,
        reply_markup=Keyboards.main_menu(user_id, bool(session), is_admin)
    )

@dp.message(Command("help", "helppuls", "хелп"))
async def cmd_help(message: Message):
    """Команда помощи"""
    user_id = message.from_user.id
    
    help_text = (
        "ℹ️ <b>ЦЕНТР ПОМОЩИ PULSEBOT</b>\n\n"
        "📚 <b>Основные разделы:</b>\n"
        "• 🎮 Игры и правила\n"
        "• 💼 Работа и заработок\n"
        "• 💎 VIP статус и бонусы\n"
        "• 🎫 Розыгрыши и участие\n"
        "• 🔐 Аккаунт и безопасность\n"
        "• 📊 Статистика и прогресс\n\n"
        "👇 <b>Выберите интересующий раздел:</b>"
    )
    
    await message.answer(
        help_text,
        reply_markup=Keyboards.help_menu(user_id, 1)
    )

@dp.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext):
    """Команда регистрации"""
    user_id = message.from_user.id
    
    if message.chat.type != "private":
        await message.answer(
            "🔒 <b>Регистрация доступна только в личных сообщениях!</b>\n\n"
            "Для безопасности вашего аккаунта перейдите в личные сообщения с ботом."
        )
        return
    
    session = db.get_active_session(user_id)
    if session:
        await message.answer(
            "✅ <b>Вы уже авторизованы!</b>\n\n"
            f"👤 Аккаунт: <code>{session['username']}</code>\n"
            "🚪 Используйте команду /logout для выхода."
        )
        return
    
    await state.set_state(RegistrationState.waiting_for_username)
    await message.answer(
        "📝 <b>РЕГИСТРАЦИЯ НОВОГО АККАУНТА</b>\n\n"
        "🎁 <b>После регистрации вы получите 100 Pulse в подарок!</b>\n\n"
        "✏️ <b>Придумайте логин:</b>\n"
        "• 3-20 символов\n"
        "• Только английские буквы, цифры и _\n"
        "• Пример: <code>player123</code> или <code>gamer_pro</code>\n\n"
        "📝 <i>Введите ваш логин:</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{user_id}")]
        ])
    )

@dp.message(RegistrationState.waiting_for_username)
async def process_register_username(message: Message, state: FSMContext):
    """Обработка логина при регистрации"""
    username = message.text.strip()
    user_id = message.from_user.id
    
    # Проверка логина
    if len(username) < 3 or len(username) > 20:
        await message.answer(
            "❌ <b>Неправильная длина логина!</b>\n\n"
            "Логин должен быть от 3 до 20 символов.\n"
            "📝 <i>Попробуйте еще раз:</i>"
        )
        return
    
    if not re.match(r'^[A-Za-z0-9_]+$', username):
        await message.answer(
            "❌ <b>Недопустимые символы в логине!</b>\n\n"
            "Логин может содержать только:\n"
            "• Латинские буквы (A-Z, a-z)\n"
            "• Цифры (0-9)\n"
            "• Символ подчеркивания (_)\n\n"
            "🚫 <b>Запрещено:</b> пробелы, кириллица, спецсимволы\n\n"
            "📝 <i>Попробуйте еще раз:</i>"
        )
        return
    
    # Проверка на существующий логин
    existing_account = db.get_account(username=username)
    if existing_account:
        await message.answer(
            f"❌ <b>Логин '{username}' уже занят!</b>\n\n"
            f"💡 <i>Придумайте другой логин:</i>"
        )
        return
    
    await state.update_data(username=username)
    await state.set_state(RegistrationState.waiting_for_password)
    
    await message.answer(
        "✅ <b>Отличный логин!</b> <code>{username}</code> свободен.\n\n"
        "🔐 <b>Теперь придумайте надежный пароль:</b>\n"
        "• 5-20 символов\n"
        "• Хотя бы 1 латинская буква\n"
        "• Хотя бы 1 цифра\n\n"
        "💡 <b>Примеры хороших паролей:</b>\n"
        "<code>Game2024!</code>, <code>Pulse_Bot123</code>, <code>SecretPass99</code>\n\n"
        "🚫 <b>Не используйте:</b> простые пароли, даты рождения, имена\n\n"
        "📝 <i>Введите ваш пароль:</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{user_id}")]
        ])
    )

@dp.message(RegistrationState.waiting_for_password)
async def process_register_password(message: Message, state: FSMContext):
    """Обработка пароля при регистрации"""
    password = message.text.strip()
    user_id = message.from_user.id
    
    # Проверка пароля
    if len(password) < 5 or len(password) > 20:
        await message.answer(
            "❌ <b>Неправильная длина пароля!</b>\n\n"
            "Пароль должен быть от 5 до 20 символов.\n"
            "📝 <i>Попробуйте еще раз:</i>"
        )
        return
    
    if not re.search(r'[A-Za-z]', password):
        await message.answer(
            "❌ <b>В пароле нет букв!</b>\n\n"
            "Пароль должен содержать хотя бы 1 латинскую букву.\n"
            "📝 <i>Попробуйте еще раз:</i>"
        )
        return
    
    if not re.search(r'\d', password):
        await message.answer(
            "❌ <b>В пароле нет цифр!</b>\n\n"
            "Пароль должен содержать хотя бы 1 цифру.\n"
            "📝 <i>Попробуйте еще раз:</i>"
        )
        return
    
    await state.update_data(password=password)
    await state.set_state(RegistrationState.waiting_for_recovery)
    
    await message.answer(
        "🔐 <b>Надежный пароль установлен!</b>\n\n"
        "🗝️ <b>Кодовое слово для восстановления (необязательно):</b>\n\n"
        "💡 <i>Придумайте кодовое слово, которое поможет восстановить доступ "
        "к аккаунту в случае утери пароля.</i>\n\n"
        "📝 <i>Введите кодовое слово или 'пропустить':</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data=f"skip_recovery:{user_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{user_id}")]
        ])
    )

@dp.callback_query(F.data.startswith("skip_recovery:"))
async def skip_recovery(callback: CallbackQuery, state: FSMContext):
    """Пропуск кодового слова"""
    user_id = int(callback.data.split(":")[1])
    
    if callback.from_user.id != user_id:
        await callback.answer("⚠️ Эта кнопка не для вас!")
        return
    
    await callback.answer()
    
    data = await state.get_data()
    await complete_registration(callback.message, data, user_id)
    await state.clear()

@dp.message(RegistrationState.waiting_for_recovery)
async def process_register_recovery(message: Message, state: FSMContext):
    """Обработка кодового слова"""
    recovery_code = message.text.strip()
    user_id = message.from_user.id
    data = await state.get_data()
    
    if recovery_code.lower() == 'пропустить':
        recovery_code = None
    
    data['recovery_code'] = recovery_code
    await complete_registration(message, data, user_id)
    await state.clear()

async def complete_registration(message: Message, data: dict, user_id: int):
    """Завершение регистрации"""
    username = data['username']
    password = data['password']
    recovery_code = data.get('recovery_code')
    
    # Создаем аккаунт
    account_id = db.create_account(username, password, user_id, recovery_code)
    
    if not account_id:
        await message.answer(
            "❌ <b>Ошибка при создании аккаунта!</b>\n\n"
            "💡 <i>Возможно, достигнут лимит аккаунтов или не прошел кулдаун. "
            "Попробуйте позже или обратитесь в поддержку.</i>"
        )
        return
    
    # Получаем сессию для отображения баланса
    session = db.get_active_session(user_id)
    profile = db.get_profile(account_id)
    
    registration_text = (
        "🎉 <b>ВЫ УСПЕШНО ЗАРЕГИСТРИРОВАНЫ!</b>\n\n"
        f"👤 <b>Логин:</b> <code>{username}</code>\n"
        f"🔐 <b>Пароль:</b> <code>{password}</code>\n"
    )
    
    if recovery_code:
        registration_text += f"🗝️ <b>Кодовое слово:</b> <code>{recovery_code}</code>\n"
    
    registration_text += (
        f"💰 <b>Начальный баланс:</b> {profile['balance']} Pulse\n\n"
        "⚠️ <b>СОХРАНИТЕ ЭТИ ДАННЫЕ!</b>\n\n"
        "🌟 <b>Теперь вы можете пользоваться всеми функциями PulseBot!</b>\n"
        "🎮 <i>Играйте, работайте, участвуйте в розыгрышах и повышайте VIP-статус!</i>"
    )
    
    await message.answer(
        registration_text,
        reply_markup=Keyboards.main_menu(user_id, True, db.is_admin(user_id))
    )

@dp.message(Command("login"))
async def cmd_login(message: Message, state: FSMContext):
    """Команда входа в аккаунт"""
    user_id = message.from_user.id
    
    if message.chat.type != "private":
        await message.answer(
            "🔒 <b>Вход доступен только в личных сообщениях!</b>\n\n"
            "Для безопасности вашего аккаунта перейдите в личные сообщения с ботом."
        )
        return
    
    session = db.get_active_session(user_id)
    if session:
        await message.answer(
            "✅ <b>Вы уже авторизованы!</b>\n\n"
            f"👤 Аккаунт: <code>{session['username']}</code>\n"
            "🚪 Используйте команду /logout для выхода."
        )
        return
    
    await state.set_state(LoginState.waiting_for_username)
    await message.answer(
        "🔐 <b>ВХОД В АККАУНТ PULSEBOT</b>\n\n"
        "✏️ <b>Введите ваш логин:</b>\n"
        "<i>Это имя аккаунта, которое вы указали при регистрации</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{user_id}")]
        ])
    )

@dp.message(LoginState.waiting_for_username)
async def process_login_username(message: Message, state: FSMContext):
    """Обработка логина при входе"""
    username = message.text.strip()
    user_id = message.from_user.id
    
    # Проверяем существование аккаунта
    account = db.get_account(username=username)
    if not account:
        await message.answer(
            f"❌ <b>Аккаунт '{username}' не найден!</b>\n\n"
            "💡 <i>Проверьте правильность логина или зарегистрируйтесь командой /register</i>"
        )
        await state.clear()
        return
    
    await state.update_data(username=username)
    await state.set_state(LoginState.waiting_for_password)
    
    await message.answer(
        "🔐 <b>Теперь введите пароль:</b>\n\n"
        "💡 <i>Пароль должен совпадать с тем, который вы указали при регистрации</i>\n"
        "🔒 <i>Сообщение автоматически удалится через время</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{user_id}")]
        ])
    )

@dp.message(LoginState.waiting_for_password)
async def process_login_password(message: Message, state: FSMContext):
    """Обработка пароля при входе"""
    password = message.text.strip()
    user_id = message.from_user.id
    data = await state.get_data()
    username = data.get('username')
    
    # Проверяем учетные данные
    account = db.verify_account(username, password)
    
    if not account:
        await message.answer(
            "❌ <b>Неверный пароль!</b>\n\n"
            "💡 <i>Проверьте правильность ввода:</i>\n"
            "• Пароль чувствителен к регистру\n"
            "• Убедитесь, что Caps Lock выключен\n\n"
            "🔐 <i>Попробуйте снова командой /login</i>"
        )
        await state.clear()
        return
    
    # Создаем сессию
    db.create_session(user_id, account['account_id'])
    session = db.get_active_session(user_id)
    profile = db.get_profile(account['account_id'])
    
    await message.answer(
        f"✅ <b>УСПЕШНЫЙ ВХОД!</b>\n\n"
        f"👤 <b>Добро пожаловать, {username}!</b>\n"
        f"💰 <b>Баланс:</b> <b>{profile['balance']:,}</b> Pulse\n"
        f"⭐ <b>VIP:</b> {'<b>✅ АКТИВЕН</b>' if session.get('is_vip') else '❌ Неактивен'}\n\n"
        "🌟 <b>Бот обновил вашу последнюю активность и сессию.</b>",
        reply_markup=Keyboards.main_menu(user_id, True, db.is_admin(user_id))
    )
    
    await state.clear()

@dp.message(Command("logout"))
async def cmd_logout(message: Message):
    """Выход из аккаунта"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
        await message.answer(
            "❌ <b>Вы не авторизованы!</b>\n\n"
            "🔐 <i>Сначала войдите в аккаунт командой /login</i>"
        )
        return
    
    # В реальной реализации здесь нужно деактивировать сессию в БД
    await message.answer(
        "✅ <b>Вы успешно вышли из аккаунта!</b>\n\n"
        "🔐 <i>Для входа снова используйте команду /login</i>",
        reply_markup=Keyboards.main_menu(user_id, False, db.is_admin(user_id))
    )

@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    """Профиль пользователя"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
        await message.answer(
            "🔒 <b>Доступ к профилю закрыт!</b>\n\n"
            "💡 <i>Сначала войдите в аккаунт командой /login</i>"
        )
        return
    
    profile = db.get_profile(session['account_id'])
    if not profile:
        await message.answer("❌ <b>Ошибка загрузки профиля!</b>")
        return
    
    # Статистика игр
    win_rate = (profile['games_won'] / profile['games_played'] * 100) if profile['games_played'] > 0 else 0
    
    profile_text = (
        f"👤 <b>ПРОФИЛЬ АККАУНТА</b>\n\n"
        f"📛 <b>Логин:</b> <code>{session['username']}</code>\n"
        f"💰 <b>Баланс:</b> <b>{profile['balance']:,}</b> Pulse\n"
        f"📈 <b>Уровень:</b> {profile['level']}\n"
        f"⭐ <b>VIP статус:</b> "
    )
    
    if session.get('is_vip'):
        vip_until = datetime.fromisoformat(session['vip_until'])
        days_left = (vip_until - datetime.now()).days
        hours_left = (vip_until - datetime.now()).seconds // 3600
        profile_text += f"<b>✅ АКТИВЕН</b> (осталось {days_left} дней {hours_left} часов)\n"
    else:
        profile_text += "❌ Неактивен\n"
    
    profile_text += (
        f"\n📊 <b>СТАТИСТИКА:</b>\n"
        f"🎮 <b>Игр сыграно:</b> {profile['games_played']}\n"
        f"✅ <b>Побед:</b> {profile['games_won']}\n"
        f"📈 <b>Процент побед:</b> {win_rate:.1f}%\n"
        f"💼 <b>Работ выполнено:</b> {profile['work_count']}\n"
        f"📈 <b>Всего заработано:</b> {profile['total_earned']:,} Pulse\n"
        f"📉 <b>Всего потрачено:</b> {profile['total_spent']:,} Pulse\n\n"
        f"🌟 <b>Продолжайте в том же духе!</b>"
    )
    
    await message.answer(
        profile_text,
        reply_markup=Keyboards.main_menu(user_id, True, db.is_admin(user_id))
    )

@dp.message(Command("games"))
async def cmd_games(message: Message):
    """Меню игр"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
        await message.answer(
            "🎮 <b>Доступ к играм закрыт!</b>\n\n"
            "💡 <i>Сначала войдите в аккаунт командой /login</i>"
        )
        return
    
    profile = db.get_profile(session['account_id'])
    
    games_text = (
        "🎮 <b>ИГРОВОЙ КЛУБ PULSEBOT</b>\n\n"
        "💰 <b>Ваш баланс:</b> <b>{:,}</b> Pulse\n\n"
        "🎯 <b>Доступные игры:</b>\n\n"
    ).format(profile['balance'])
    
    for game_type, config in GAMES_CONFIG.items():
        min_bet = config.get('min_bet', db.get_setting('min_bet', 25))
        games_text += f"{config['emoji']} <b>{config['name']}</b>\n"
        games_text += f"<i>{config['description']}</i>\n"
        
        if game_type == GameType.RANDOM.value:
            games_text += f"🎯 Шанс: {config['win_chance']*100:.0f}% | Множитель: ×{config['multiplier']}\n"
        elif game_type == GameType.CHOICE.value:
            games_text += "🎯 Выбор уровня риска (×1.5-×5.0)\n"
        elif game_type == GameType.REACTION.value:
            games_text += f"🎯 Множитель: ×{config['multiplier']}\n"
        
        games_text += f"💰 От {min_bet} Pulse\n\n"
    
    games_text += (
        "💡 <b>Как играть:</b>\n"
        "1. Выберите игру\n"
        "2. Поставьте желаемую сумму\n"
        "3. Испытайте удачу!\n\n"
        "⭐ <b>VIP статус увеличивает выигрыши в 1.5 раза!</b>"
    )
    
    await message.answer(
        games_text,
        reply_markup=Keyboards.games_menu(user_id)
    )

@dp.message(Command("work"))
async def cmd_work(message: Message):
    """Меню работы"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
        await message.answer(
            "💼 <b>Доступ к работе закрыт!</b>\n\n"
            "💡 <i>Сначала войдите в аккаунт командой /login</i>"
        )
        return
    
    # Проверяем кулдаун
    can_work, cooldown_until = db.check_cooldown(session['account_id'], 'work')
    
    if not can_work:
        remaining = cooldown_until - datetime.now()
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        
        await message.answer(
            f"⏰ <b>Работа временно недоступна!</b>\n\n"
            f"💼 <b>Следующая работа через:</b> {hours:02d}:{minutes:02d}\n\n"
            f"💡 <i>Отдохните или займитесь другими активностями!</i>",
            reply_markup=Keyboards.main_menu(user_id, True, db.is_admin(user_id))
        )
        return
    
    work_text = (
        "💼 <b>ТРУДОВОЙ ЦЕНТР PULSEBOT</b>\n\n"
        "👨‍💼 <b>Доступные профессии:</b>\n\n"
    )
    
    for work in WORK_TYPES:
        work_text += (
            f"{work['emoji']} <b>{work['name'].capitalize()}</b>\n"
            f"<i>{work['description']}</i>\n"
            f"💰 <b>Зарплата:</b> {work['min_reward']}-{work['max_reward']} Pulse\n\n"
        )
    
    work_text += (
        "💡 <b>Как работает:</b>\n"
        "1. Выберите профессию\n"
        "2. Ответьте на профессиональный вопрос\n"
        "3. Получите зарплату в Pulse\n\n"
        "⏰ <b>Кулдаун:</b> 30 минут между работами\n"
        "📊 <b>Лимит:</b> 5 работ в 10 часов\n\n"
        "⭐ <b>VIP статус увеличивает заработок в 1.5 раза!</b>"
    )
    
    await message.answer(
        work_text,
        reply_markup=Keyboards.work_menu(user_id)
    )

@dp.message(Command("shop"))
async def cmd_shop(message: Message):
    """Магазин"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
        await message.answer(
            "🏪 <b>Доступ к магазину закрыт!</b>\n\n"
            "💡 <i>Сначала войдите в аккаунт командой /login</i>"
        )
        return
    
    profile = db.get_profile(session['account_id'])
    
    shop_text = (
        "🏪 <b>МАГАЗИН PULSEBOT</b>\n\n"
        "💰 <b>Ваш баланс:</b> <b>{:,}</b> Pulse\n\n"
        "🛍️ <b>Категории товаров:</b>\n\n"
        "💎 <b>VIP ПАКЕТЫ:</b>\n"
        "• Повышенный заработок (×1.5)\n"
        "• Скидка 10% на все товары\n"
        "• Эксклюзивные возможности\n\n"
        "🚀 <b>БУСТЕРЫ (скоро):</b>\n"
        "• Удвоение заработка\n"
        "• Повышение шанса выигрыша\n"
        "• Ускорение прогресса\n\n"
        "🎁 <b>ПРЕДМЕТЫ (скоро):</b>\n"
        "• Сундук с сокровищами\n"
        "• Ключ удачи\n\n"
        "👇 <b>Выберите товар:</b>".format(profile['balance'])
    )
    
    await message.answer(
        shop_text,
        reply_markup=Keyboards.shop_menu(user_id, profile['balance'])
    )

@dp.message(Command("bonus"))
async def cmd_bonus(message: Message):
    """Ежедневный бонус"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
        await message.answer(
            "🎁 <b>Доступ к бонусам закрыт!</b>\n\n"
            "💡 <i>Сначала войдите в аккаунт командой /login</i>"
        )
        return
    
    # Проверяем кулдаун
    can_get_bonus, cooldown_until = db.check_cooldown(session['account_id'], 'daily_bonus')
    
    if not can_get_bonus:
        remaining = cooldown_until - datetime.now()
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        
        await message.answer(
            f"⏰ <b>Бонус уже получен сегодня!</b>\n\n"
            f"🎁 <b>Следующий бонус через:</b> {hours:02d}:{minutes:02d}\n\n"
            f"💡 <i>Возвращайтесь завтра за новым бонусом!</i>",
            reply_markup=Keyboards.main_menu(user_id, True, db.is_admin(user_id))
        )
        return
    
    bonus_amount = db.get_setting('daily_bonus', 50)
    db.update_balance(session['account_id'], bonus_amount, 'daily_bonus', 'Ежедневный бонус')
    db.set_cooldown(session['account_id'], 'daily_bonus', db.get_setting('daily_cooldown', 24) * 3600)
    
    profile = db.get_profile(session['account_id'])
    
    await message.answer(
        f"🎁 <b>ЕЖЕДНЕВНЫЙ БОНУС!</b>\n\n"
        f"✅ <b>Вы получили ежедневный бонус: {bonus_amount} Pulse!</b>\n\n"
        f"💰 <b>Новый баланс:</b> <b>{profile['balance']:,}</b> Pulse\n\n"
        f"⏰ <b>Следующий бонус будет доступен через 24 часа.</b>\n\n"
        f"🌟 <b>Не забудьте завтра снова получить бонус!</b>",
        reply_markup=Keyboards.main_menu(user_id, True, db.is_admin(user_id))
    )

@dp.message(Command("draws"))
async def cmd_draws(message: Message):
    """Розыгрыши"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
        await message.answer(
            "🎫 <b>Доступ к розыгрышам закрыт!</b>\n\n"
            "💡 <i>Сначала войдите в аккаунт командой /login</i>"
        )
        return
    
    active_draws = db.get_active_draws()
    
    if not active_draws:
        draws_text = (
            "🎫 <b>РОЗЫГРЫШИ PULSEBOT</b>\n\n"
            "😔 <b>В данный момент нет активных розыгрышей.</b>\n\n"
            "💡 <b>Следите за обновлениями!</b>\n"
            "• Новые розыгрыши появляются регулярно\n"
            "• Участие только с аккаунтом\n"
            "• Призы начисляются на баланс\n\n"
            "🌟 <b>Возвращайтесь позже!</b>"
        )
    else:
        draws_text = (
            "🎫 <b>АКТИВНЫЕ РОЗЫГРЫШИ</b>\n\n"
            f"🎁 <b>Доступно розыгрышей:</b> {len(active_draws)}\n\n"
        )
        
        for draw in active_draws[:3]:  # Показываем первые 3
            end_date = datetime.fromisoformat(draw['end_date'])
            time_left = end_date - datetime.now()
            days = time_left.days
            hours = time_left.seconds // 3600
            
            draws_text += (
                f"🎯 <b>{draw['name']}</b>\n"
                f"💰 <b>Приз:</b> {draw['prize_amount']} Pulse\n"
                f"👥 <b>Участников:</b> {draw['current_participants']}/{draw['max_participants'] or '∞'}\n"
                f"⏰ <b>Осталось:</b> {days}д {hours}ч\n\n"
            )
        
        if len(active_draws) > 3:
            draws_text += f"📋 <i>И еще {len(active_draws) - 3} розыгрыша...</i>\n\n"
        
        draws_text += (
            "💡 <b>Как участвовать:</b>\n"
            "1. Выберите розыгрыш\n"
            "2. Нажмите 'Участвовать'\n"
            "3. Получите номер билета\n"
            "4. Ждите результатов!\n\n"
            "🎁 <b>Удачи!</b>"
        )
    
    await message.answer(
        draws_text,
        reply_markup=Keyboards.draws_menu(user_id)
    )

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    """Админ-панель"""
    user_id = message.from_user.id
    
    if not db.is_admin(user_id):
        await message.answer(
            "🚫 <b>Доступ запрещен!</b>\n\n"
            "У вас нет прав администратора."
        )
        return
    
    if message.chat.type != "private":
        await message.answer(
            "🔒 <b>Админ-панель доступна только в личных сообщениях!</b>"
        )
        return
    
    admin_text = (
        "🛠 <b>АДМИНИСТРАТИВНАЯ ПАНЕЛЬ PULSEBOT</b>\n\n"
        "👑 <b>Добро пожаловать, администратор!</b>\n\n"
        "⚙️ <b>Доступные функции:</b>\n\n"
        "👥 <b>Управление пользователями:</b>\n"
        "• Поиск и просмотр аккаунтов\n"
        "• Изменение балансов\n"
        "• Блокировка/разблокировка\n\n"
        "🎮 <b>Управление играми:</b>\n"
        "• Настройка параметров игр\n"
        "• Просмотр статистики\n"
        "• Добавление новых игр\n\n"
        "🎫 <b>Управление розыгрышами:</b>\n"
        "• Создание и редактирование\n"
        "• Управление участниками\n"
        "• Определение победителей\n\n"
        "⚙️ <b>Настройки бота:</b>\n"
        "• Изменение параметров\n"
        "• Управление VIP\n"
        "• Настройка бонусов\n\n"
        "👇 <b>Выберите раздел:</b>"
    )
    
    await message.answer(
        admin_text,
        reply_markup=Keyboards.admin_menu(user_id)
    )

# ========== ОБРАБОТЧИКИ КНОПОК ==========
@dp.callback_query(F.data.startswith("menu:"))
async def handle_menu_callback(callback: CallbackQuery):
    """Обработчик меню"""
    data = callback.data.split(":")
    action = data[1]
    user_id = int(data[2])
    
    if callback.from_user.id != user_id:
        await callback.answer("⚠️ Эта кнопка не для вас!")
        return
    
    await callback.answer()
    
    if action == "main":
        session = db.get_active_session(user_id)
        await callback.message.edit_text(
            "🎮 <b>Главное меню PulseBot</b>\n\n"
            "👇 <b>Выберите действие:</b>",
            reply_markup=Keyboards.main_menu(user_id, bool(session), db.is_admin(user_id))
        )
    
    elif action == "games":
        session = db.get_active_session(user_id)
        if not session:
            await callback.message.edit_text("🔒 <b>Сначала войдите в аккаунт!</b>")
            return
        
        await cmd_games(callback.message)
    
    elif action == "work":
        session = db.get_active_session(user_id)
        if not session:
            await callback.message.edit_text("🔒 <b>Сначала войдите в аккаунт!</b>")
            return
        
        await cmd_work(callback.message)
    
    elif action == "shop":
        session = db.get_active_session(user_id)
        if not session:
            await callback.message.edit_text("🔒 <b>Сначала войдите в аккаунт!</b>")
            return
        
        await cmd_shop(callback.message)
    
    elif action == "bonus":
        session = db.get_active_session(user_id)
        if not session:
            await callback.message.edit_text("🔒 <b>Сначала войдите в аккаунт!</b>")
            return
        
        await cmd_bonus(callback.message)
    
    elif action == "profile":
        session = db.get_active_session(user_id)
        if not session:
            await callback.message.edit_text("🔒 <b>Сначала войдите в аккаунт!</b>")
            return
        
        await cmd_profile(callback.message)
    
    elif action == "stats":
        session = db.get_active_session(user_id)
        if not session:
            await callback.message.edit_text("🔒 <b>Сначала войдите в аккаунт!</b>")
            return
        
        stats = db.get_statistics()
        stats_text = (
            "📊 <b>СТАТИСТИКА PULSEBOT</b>\n\n"
            f"👥 <b>Пользователей:</b> {stats['total_users']:,}\n"
            f"👤 <b>Аккаунтов:</b> {stats['total_accounts']:,}\n"
            f"💰 <b>Общий баланс:</b> {stats['total_balance']:,} Pulse\n"
            f"🎮 <b>Игр сегодня:</b> {stats['games_today']}\n"
            f"🎫 <b>Активных розыгрышей:</b> {stats['active_draws']}\n\n"
            f"⚡ <b>Бот работает стабильно!</b>"
        )
        
        await callback.message.edit_text(
            stats_text,
            reply_markup=Keyboards.main_menu(user_id, True, db.is_admin(user_id))
        )
    
    elif action == "draws":
        session = db.get_active_session(user_id)
        if not session:
            await callback.message.edit_text("🔒 <b>Сначала войдите в аккаунт!</b>")
            return
        
        await cmd_draws(callback.message)
    
    elif action == "help":
        await callback.message.edit_text(
            "ℹ️ <b>ЦЕНТР ПОМОЩИ PULSEBOT</b>\n\n"
            "📚 <b>Основные разделы:</b>\n\n"
            "1. 🎮 Игры и правила\n"
            "2. 💼 Работа и заработок\n"
            "3. 💎 VIP статус и бонусы\n"
            "4. 🎫 Розыгрыши и участие\n"
            "5. 🔐 Аккаунт и безопасность\n"
            "6. 📊 Статистика и прогресс\n\n"
            "👇 <b>Выберите раздел:</b>",
            reply_markup=Keyboards.help_menu(user_id, 1)
        )

@dp.callback_query(F.data.startswith("help:"))
async def handle_help_callback(callback: CallbackQuery):
    """Обработчик помощи"""
    data = callback.data.split(":")
    action = data[1]
    user_id = int(data[-1])  # Последний элемент всегда user_id
    
    if callback.from_user.id != user_id:
        await callback.answer("⚠️ Эта кнопка не для вас!")
        return
    
    await callback.answer()
    
    if action == "page":
        page = int(data[2])
        await callback.message.edit_text(
            f"ℹ️ <b>ПОМОЩЬ: Раздел {page}/6</b>\n\n"
            f"👇 <b>Выберите действие:</b>",
            reply_markup=Keyboards.help_menu(user_id, page)
        )
    
    elif action == "game":
        game_type = data[2]
        session = db.get_active_session(user_id)
        
        if not session:
            await callback.message.edit_text("🔒 <b>Сначала войдите в аккаунт!</b>")
            return
        
        if game_type == "random":
            await callback.message.edit_text(
                "🎮 <b>ИГРА: РАНДОМ</b>\n\n"
                "👇 <b>Начните игру:</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎲 Играть в Рандом", callback_data=f"game:select:random:{user_id}")],
                    [InlineKeyboardButton(text="🔙 Назад к помощи", callback_data=f"help:page:1:{user_id}")]
                ])
            )
        elif game_type == "choice":
            await callback.message.edit_text(
                "🎮 <b>ИГРА: ВЫБОР</b>\n\n"
                "👇 <b>Начните игру:</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🧠 Играть в Выбор", callback_data=f"game:select:choice:{user_id}")],
                    [InlineKeyboardButton(text="🔙 Назад к помощи", callback_data=f"help:page:1:{user_id}")]
                ])
            )
    
    elif action == "work":
        subaction = data[2]
        
        if subaction == "start":
            session = db.get_active_session(user_id)
            if not session:
                await callback.message.edit_text("🔒 <b>Сначала войдите в аккаунт!</b>")
                return
            
            await callback.message.edit_text(
                "💼 <b>РАБОТА</b>\n\n"
                "👇 <b>Начните работу:</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💼 Начать работать", callback_data=f"menu:work:{user_id}")],
                    [InlineKeyboardButton(text="🔙 Назад к помощи", callback_data=f"help:page:2:{user_id}")]
                ])
            )
    
    elif action == "shop":
        subaction = data[2]
        
        if subaction == "vip":
            session = db.get_active_session(user_id)
            if not session:
                await callback.message.edit_text("🔒 <b>Сначала войдите в аккаунт!</b>")
                return
            
            await callback.message.edit_text(
                "💎 <b>VIP СТАТУС</b>\n\n"
                "👇 <b>Приобретите VIP:</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💎 Купить VIP", callback_data=f"menu:shop:{user_id}")],
                    [InlineKeyboardButton(text="🔙 Назад к помощи", callback_data=f"help:page:3:{user_id}")]
                ])
            )
    
    elif action == "draw":
        subaction = data[2]
        
        if subaction == "join":
            session = db.get_active_session(user_id)
            if not session:
                await callback.message.edit_text("🔒 <b>Сначала войдите в аккаунт!</b>")
                return
            
            await callback.message.edit_text(
                "🎫 <b>РОЗЫГРЫШИ</b>\n\n"
                "👇 <b>Участвуйте в розыгрышах:</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎫 Участвовать", callback_data=f"menu:draws:{user_id}")],
                    [InlineKeyboardButton(text="🔙 Назад к помощи", callback_data=f"help:page:4:{user_id}")]
                ])
            )
    
    elif action == "auth":
        subaction = data[2]
        
        if subaction == "register":
            await callback.message.edit_text(
                "📝 <b>РЕГИСТРАЦИЯ</b>\n\n"
                "👇 <b>Начните регистрацию:</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📝 Зарегистрироваться", callback_data=f"auth:register:{user_id}")],
                    [InlineKeyboardButton(text="🔙 Назад к помощи", callback_data=f"help:page:5:{user_id}")]
                ])
            )
        elif subaction == "login":
            await callback.message.edit_text(
                "🔐 <b>ВХОД В АККАУНТ</b>\n\n"
                "👇 <b>Войдите в аккаунт:</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔐 Войти в аккаунт", callback_data=f"auth:login:{user_id}")],
                    [InlineKeyboardButton(text="🔙 Назад к помощи", callback_data=f"help:page:5:{user_id}")]
                ])
            )
    
    elif action == "profile":
        session = db.get_active_session(user_id)
        if not session:
            await callback.message.edit_text("🔒 <b>Сначала войдите в аккаунт!</b>")
            return
        
        await callback.message.edit_text(
            "👤 <b>ПРОФИЛЬ</b>\n\n"
            "👇 <b>Откройте профиль:</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👤 Открыть профиль", callback_data=f"menu:profile:{user_id}")],
                [InlineKeyboardButton(text="🔙 Назад к помощи", callback_data=f"help:page:6:{user_id}")]
            ])
        )
    
    elif action == "current":
        await callback.answer("ℹ️ Текущая страница")

@dp.callback_query(F.data.startswith("auth:"))
async def handle_auth_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик авторизации"""
    data = callback.data.split(":")
    action = data[1]
    user_id = int(data[2])
    
    if callback.from_user.id != user_id:
        await callback.answer("⚠️ Эта кнопка не для вас!")
        return
    
    await callback.answer()
    
    if action == "login":
        session = db.get_active_session(user_id)
        if session:
            await callback.message.edit_text("✅ <b>Вы уже авторизованы!</b>")
            return
        
        await callback.message.edit_text(
            "🔐 <b>ВХОД В АККАУНТ</b>\n\n"
            "📝 <i>Введите ваш логин:</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{user_id}")]
            ])
        )
        await state.set_state(LoginState.waiting_for_username)
    
    elif action == "register":
        session = db.get_active_session(user_id)
        if session:
            await callback.message.edit_text("✅ <b>Вы уже авторизованы!</b>")
            return
        
        await callback.message.edit_text(
            "📝 <b>РЕГИСТРАЦИЯ НОВОГО АККАУНТА</b>\n\n"
            "📝 <i>Введите ваш логин:</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{user_id}")]
            ])
        )
        await state.set_state(RegistrationState.waiting_for_username)
    
    elif action == "logout":
        session = db.get_active_session(user_id)
        if not session:
            await callback.message.edit_text("❌ <b>Вы не авторизованы!</b>")
            return
        
        await callback.message.edit_text(
            "✅ <b>Вы успешно вышли из аккаунта!</b>",
            reply_markup=Keyboards.main_menu(user_id, False, db.is_admin(user_id))
        )

@dp.callback_query(F.data.startswith("cancel:"))
async def handle_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена действия"""
    user_id = int(callback.data.split(":")[1])
    
    if callback.from_user.id != user_id:
        await callback.answer("⚠️ Эта кнопка не для вас!")
        return
    
    await state.clear()
    session = db.get_active_session(user_id)
    
    await callback.message.edit_text(
        "❌ <b>Действие отменено.</b>",
        reply_markup=Keyboards.main_menu(user_id, bool(session), db.is_admin(user_id))
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("game:"))
async def handle_game_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик игр"""
    data = callback.data.split(":")
    action = data[1]
    user_id = int(data[-1])  # Последний элемент всегда user_id
    
    if callback.from_user.id != user_id:
        await callback.answer("⚠️ Эта кнопка не для вас!")
        return
    
    session = db.get_active_session(user_id)
    if not session:
        await callback.message.edit_text("🔒 <b>Сначала войдите в аккаунт!</b>")
        await callback.answer()
        return
    
    await callback.answer()
    
    if action == "select":
        game_type = data[2]
        profile = db.get_profile(session['account_id'])
        
        if game_type not in GAMES_CONFIG:
            await callback.message.edit_text("❌ <b>Игра не найдена!</b>")
            return
        
        game_config = GAMES_CONFIG[game_type]
        min_bet = game_config.get('min_bet', db.get_setting('min_bet', 25))
        
        if profile['balance'] < min_bet:
            await callback.message.edit_text(
                f"❌ <b>НЕДОСТАТОЧНО СРЕДСТВ!</b>\n\n"
                f"💰 <b>Минимальная ставка:</b> {min_bet} Pulse\n"
                f"💰 <b>Ваш баланс:</b> {profile['balance']} Pulse\n\n"
                f"💡 <i>Пополните баланс через работу или бонусы.</i>"
            )
            return
        
        if game_type == GameType.CHOICE.value:
            await callback.message.edit_text(
                f"🧠 <b>ИГРА: ВЫБОР УРОВНЯ РИСКА</b>\n\n"
                f"💰 <b>Ваш баланс:</b> <b>{profile['balance']:,}</b> Pulse\n\n"
                f"👇 <b>Выберите уровень риска:</b>",
                reply_markup=Keyboards.choice_game_menu(user_id)
            )
        else:
            await callback.message.edit_text(
                f"{game_config['emoji']} <b>ИГРА: {game_config['name'].upper()}</b>\n\n"
                f"💰 <b>Ваш баланс:</b> <b>{profile['balance']:,}</b> Pulse\n\n"
                f"👇 <b>Выберите ставку:</b>",
                reply_markup=Keyboards.bet_menu(user_id, game_type, profile['balance'])
            )
    
    elif action == "bet":
        game_type = data[2]
        bet = int(data[3])
        
        profile = db.get_profile(session['account_id'])
        game_config = GAMES_CONFIG.get(game_type)
        
        if not game_config:
            await callback.message.edit_text("❌ <b>Игра не найдена!</b>")
            return
        
        if profile['balance'] < bet:
            await callback.message.edit_text("❌ <b>Недостаточно средств!</b>")
            return
        
        min_bet = game_config.get('min_bet', db.get_setting('min_bet', 25))
        if bet < min_bet:
            await callback.message.edit_text(f"❌ <b>Минимальная ставка: {min_bet} Pulse!</b>")
            return
        
        # Играем в игру
        if game_type == GameType.RANDOM.value:
            win_chance = game_config['win_chance']
            multiplier = game_config['multiplier']
            
            # Применяем VIP множитель
            if session.get('is_vip'):
                multiplier *= db.get_setting('vip_multiplier', 1.5)
            
            win = random.random() < win_chance
            win_amount = int(bet * multiplier) if win else 0
            
            result_text = (
                f"🎲 <b>ИГРА: РАНДОМ</b>\n\n"
                f"💰 <b>Ставка:</b> {bet} Pulse\n"
                f"🎯 <b>Шанс:</b> {win_chance*100:.0f}%\n"
                f"💰 <b>Множитель:</b> ×{multiplier:.1f}\n\n"
            )
            
            if win:
                result_text += f"🎉 <b>ПОБЕДА! Вы выиграли {win_amount} Pulse!</b>\n\n"
            else:
                result_text += f"😔 <b>ПОРАЖЕНИЕ. Вы проиграли {bet} Pulse.</b>\n\n"
            
            # Обновляем баланс и записываем игру
            new_balance = profile['balance'] - bet + win_amount
            db.update_balance(session['account_id'], -bet + win_amount, 
                            'game_win' if win else 'game_loss',
                            f"Игра: Рандом, ставка: {bet}")
            db.record_game(session['account_id'], game_type, bet, win, win_amount)
            
            result_text += f"💰 <b>Новый баланс:</b> <b>{new_balance:,}</b> Pulse"
            
            if win:
                result_text += "\n\n🌟 <b>Ваша удача сегодня на высоте!</b>"
            else:
                result_text += "\n\n💪 <b>Не расстраивайтесь! Удача обязательно улыбнется в следующий раз!</b>"
            
            await callback.message.edit_text(
                result_text,
                reply_markup=Keyboards.games_menu(user_id)
            )
        
        elif game_type == GameType.CHOICE.value:
            # Для игры Choice нужен дополнительный выбор уровня риска
            await state.update_data(game_type=game_type, bet=bet)
            await callback.message.edit_text(
                f"🧠 <b>ИГРА: ВЫБОР УРОВНЯ РИСКА</b>\n\n"
                f"💰 <b>Ставка:</b> {bet} Pulse\n\n"
                f"👇 <b>Выберите уровень риска:</b>",
                reply_markup=Keyboards.choice_game_menu(user_id)
            )
    
    elif action == "choice":
        choice_name = data[2].lower()
        
        data_state = await state.get_data()
        game_type = data_state.get('game_type')
        bet = data_state.get('bet')
        
        if not game_type or not bet:
            await callback.message.edit_text("❌ <b>Ошибка: данные игры утеряны!</b>")
            await state.clear()
            return
        
        profile = db.get_profile(session['account_id'])
        
        if profile['balance'] < bet:
            await callback.message.edit_text("❌ <b>Недостаточно средств!</b>")
            await state.clear()
            return
        
        # Находим выбранный уровень риска
        selected_option = None
        for option in GAMES_CONFIG[GameType.CHOICE.value]['options']:
            if choice_name in option['name'].lower():
                selected_option = option
                break
        
        if not selected_option:
            await callback.message.edit_text("❌ <b>Уровень риска не найден!</b>")
            await state.clear()
            return
        
        chance = selected_option['chance']
        multiplier = selected_option['multiplier']
        
        # Применяем VIP множитель
        if session.get('is_vip'):
            multiplier *= db.get_setting('vip_multiplier', 1.5)
        
        win = random.random() < chance
        win_amount = int(bet * multiplier) if win else 0
        
        result_text = (
            f"🧠 <b>ИГРА: ВЫБОР</b>\n\n"
            f"{selected_option['name'].split()[0]} <b>Уровень:</b> {selected_option['name']}\n"
            f"💰 <b>Ставка:</b> {bet} Pulse\n"
            f"🎯 <b>Шанс:</b> {chance*100:.0f}%\n"
            f"💰 <b>Множитель:</b> ×{multiplier:.1f}\n\n"
        )
        
        if win:
            result_text += f"🎉 <b>ПОБЕДА! Вы выиграли {win_amount} Pulse!</b>\n\n"
        else:
            result_text += f"😔 <b>ПОРАЖЕНИЕ. Вы проиграли {bet} Pulse.</b>\n\n"
        
        # Обновляем баланс и записываем игру
        new_balance = profile['balance'] - bet + win_amount
        db.update_balance(session['account_id'], -bet + win_amount, 
                        'game_win' if win else 'game_loss',
                        f"Игра: Выбор ({selected_option['name']}), ставка: {bet}")
        db.record_game(session['account_id'], f"choice_{choice_name}", bet, win, win_amount)
        
        result_text += f"💰 <b>Новый баланс:</b> <b>{new_balance:,}</b> Pulse"
        
        if win:
            result_text += "\n\n🎯 <b>Отличный стратегический выбор!</b>"
        else:
            result_text += f"\n\n💪 <b>Риск - благородное дело! Шанс был {chance*100:.0f}%.</b>"
        
        await callback.message.edit_text(
            result_text,
            reply_markup=Keyboards.games_menu(user_id)
        )
        
        await state.clear()
    
    elif action == "custom":
        game_type = data[2]
        await state.update_data(game_type=game_type)
        await state.set_state(GameState.choosing_bet)
        
        profile = db.get_profile(session['account_id'])
        max_bet = min(profile['balance'], db.get_setting('max_bet', 10000))
        
        await callback.message.edit_text(
            f"💰 <b>ВВЕДИТЕ СТАВКУ</b>\n\n"
            f"💎 <b>Доступно:</b> {profile['balance']:,} Pulse\n"
            f"📊 <b>Максимум:</b> {max_bet:,} Pulse\n\n"
            f"📝 <i>Введите сумму от {db.get_setting('min_bet', 25)} до {max_bet:,} Pulse:</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{user_id}")]
            ])
        )

@dp.message(GameState.choosing_bet)
async def process_custom_bet(message: Message, state: FSMContext):
    """Обработка пользовательской ставки"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
        await message.answer("🔒 <b>Сначала войдите в аккаунт!</b>")
        await state.clear()
        return
    
    try:
        bet = int(message.text.strip())
    except ValueError:
        await message.answer("❌ <b>Введите число!</b>")
        return
    
    profile = db.get_profile(session['account_id'])
    data = await state.get_data()
    game_type = data.get('game_type')
    
    if not game_type:
        await message.answer("❌ <b>Ошибка: тип игры не указан!</b>")
        await state.clear()
        return
    
    game_config = GAMES_CONFIG.get(game_type)
    if not game_config:
        await message.answer("❌ <b>Игра не найдена!</b>")
        await state.clear()
        return
    
    min_bet = game_config.get('min_bet', db.get_setting('min_bet', 25))
    max_bet = min(profile['balance'], db.get_setting('max_bet', 10000))
    
    if bet < min_bet:
        await message.answer(f"❌ <b>Минимальная ставка: {min_bet} Pulse!</b>")
        return
    
    if bet > max_bet:
        await message.answer(f"❌ <b>Максимальная ставка: {max_bet} Pulse!</b>")
        return
    
    if profile['balance'] < bet:
        await message.answer("❌ <b>Недостаточно средств!</b>")
        await state.clear()
        return
    
    # Продолжаем игру с пользовательской ставкой
    if game_type == GameType.CHOICE.value:
        await state.update_data(bet=bet)
        await message.answer(
            f"🧠 <b>ИГРА: ВЫБОР УРОВНЯ РИСКА</b>\n\n"
            f"💰 <b>Ставка:</b> {bet} Pulse\n\n"
            f"👇 <b>Выберите уровень риска:</b>",
            reply_markup=Keyboards.choice_game_menu(user_id)
        )
    else:
        # Для других игр сразу играем
        win_chance = game_config.get('win_chance', 0.5)
        multiplier = game_config.get('multiplier', 2.0)
        
        # Применяем VIP множитель
        if session.get('is_vip'):
            multiplier *= db.get_setting('vip_multiplier', 1.5)
        
        win = random.random() < win_chance
        win_amount = int(bet * multiplier) if win else 0
        
        result_text = (
            f"{game_config['emoji']} <b>ИГРА: {game_config['name'].upper()}</b>\n\n"
            f"💰 <b>Ставка:</b> {bet} Pulse\n"
            f"🎯 <b>Шанс:</b> {win_chance*100:.0f}%\n"
            f"💰 <b>Множитель:</b> ×{multiplier:.1f}\n\n"
        )
        
        if win:
            result_text += f"🎉 <b>ПОБЕДА! Вы выиграли {win_amount} Pulse!</b>\n\n"
        else:
            result_text += f"😔 <b>ПОРАЖЕНИЕ. Вы проиграли {bet} Pulse.</b>\n\n"
        
        # Обновляем баланс и записываем игру
        new_balance = profile['balance'] - bet + win_amount
        db.update_balance(session['account_id'], -bet + win_amount, 
                        'game_win' if win else 'game_loss',
                        f"Игра: {game_config['name']}, ставка: {bet}")
        db.record_game(session['account_id'], game_type, bet, win, win_amount)
        
        result_text += f"💰 <b>Новый баланс:</b> <b>{new_balance:,}</b> Pulse"
        
        await message.answer(
            result_text,
            reply_markup=Keyboards.games_menu(user_id)
        )
        
        await state.clear()

@dp.callback_query(F.data.startswith("work:"))
async def handle_work_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик работы"""
    data = callback.data.split(":")
    action = data[1]
    user_id = int(data[-1])
    
    if callback.from_user.id != user_id:
        await callback.answer("⚠️ Эта кнопка не для вас!")
        return
    
    session = db.get_active_session(user_id)
    if not session:
        await callback.message.edit_text("🔒 <b>Сначала войдите в аккаунт!</b>")
        await callback.answer()
        return
    
    await callback.answer()
    
    if action == "select":
        work_type = data[2]
        
        # Проверяем кулдаун
        can_work, cooldown_until = db.check_cooldown(session['account_id'], 'work')
        
        if not can_work:
            remaining = cooldown_until - datetime.now()
            minutes = int(remaining.total_seconds() // 60)
            seconds = int(remaining.total_seconds() % 60)
            
            await callback.message.edit_text(
                f"⏰ <b>Работа временно недоступна!</b>\n\n"
                f"💼 <b>Следующая работа через:</b> {minutes:02d}:{seconds:02d}\n\n"
                f"💡 <i>Отдохните или займитесь другими активностями!</i>",
                reply_markup=Keyboards.back_button("work")
            )
            return
        
        # Находим выбранную работу
        selected_work = None
        for work in WORK_TYPES:
            if work['name'] == work_type:
                selected_work = work
                break
        
        if not selected_work:
            await callback.message.edit_text("❌ <b>Профессия не найдена!</b>")
            return
        
        # Выбираем случайный вопрос
        question_index = random.randint(0, len(selected_work['questions']) - 1)
        question = selected_work['questions'][question_index]
        correct_answers = selected_work['answers'][question_index]
        
        await state.update_data(
            work_type=work_type,
            question_index=question_index,
            correct_answers=correct_answers,
            min_reward=selected_work['min_reward'],
            max_reward=selected_work['max_reward']
        )
        
        await callback.message.edit_text(
            f"{selected_work['emoji']} <b>РАБОТА: {work_type.upper()}</b>\n\n"
            f"📝 <b>Вопрос:</b>\n{question}\n\n"
            f"💰 <b>Награда:</b> {selected_work['min_reward']}-{selected_work['max_reward']} Pulse\n\n"
            f"✏️ <b>Введите ваш ответ:</b>\n\n"
            f"💡 <i>Ответ должен быть точным или содержать ключевые слова.</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{user_id}")]
            ])
        )
        
        await state.set_state(WorkState.answering_question)

@dp.message(WorkState.answering_question)
async def process_work_answer(message: Message, state: FSMContext):
    """Обработка ответа на вопрос работы"""
    user_id = message.from_user.id
    session = db.get_active_session(user_id)
    
    if not session:
        await message.answer("❌ <b>Ошибка сессии!</b>")
        await state.clear()
        return
    
    data = await state.get_data()
    work_type = data.get('work_type')
    correct_answers = data.get('correct_answers', [])
    min_reward = data.get('min_reward', 50)
    max_reward = data.get('max_reward', 100)
    
    if not work_type or not correct_answers:
        await message.answer("❌ <b>Ошибка: данные задания утеряны!</b>")
        await state.clear()
        return
    
    user_answer = message.text.strip().lower()
    
    # Проверяем ответ
    is_correct = any(correct_answer in user_answer for correct_answer in correct_answers)
    
    if is_correct:
        # Начисляем награду
        base_reward = random.randint(min_reward, max_reward)
        
        # Применяем VIP множитель
        if session.get('is_vip'):
            base_reward = int(base_reward * db.get_setting('vip_multiplier', 1.5))
        
        db.update_balance(session['account_id'], base_reward, 'work', f"Работа: {work_type}")
        db.record_work(session['account_id'], work_type, base_reward, f"Вопрос #{data.get('question_index', 0)}")
        db.set_cooldown(session['account_id'], 'work', db.get_setting('work_cooldown', 30) * 60)
        
        profile = db.get_profile(session['account_id'])
        
        await message.answer(
            f"✅ <b>ОТЛИЧНАЯ РАБОТА!</b>\n\n"
            f"💼 <b>Профессия:</b> {work_type.capitalize()}\n"
            f"💰 <b>Заработано:</b> {base_reward} Pulse\n"
            f"💰 <b>Новый баланс:</b> <b>{profile['balance']:,}</b> Pulse\n\n"
            f"⏰ <b>Следующая работа будет доступна через 30 минут.</b>\n\n"
            f"🌟 <b>Продолжайте в том же духе!</b>",
            reply_markup=Keyboards.main_menu(user_id, True, db.is_admin(user_id))
        )
    else:
        await message.answer(
            f"❌ <b>НЕПРАВИЛЬНЫЙ ОТВЕТ!</b>\n\n"
            f"💡 <b>Правильный ответ содержит:</b> {', '.join(correct_answers)}\n\n"
            f"😔 <b>К сожалению, за эту работу вы не получите оплату.</b>\n\n"
            f"💪 <b>Попробуйте другую работу или вернитесь позже!</b>",
            reply_markup=Keyboards.main_menu(user_id, True, db.is_admin(user_id))
        )
    
    await state.clear()

@dp.callback_query(F.data.startswith("shop:"))
async def handle_shop_callback(callback: CallbackQuery):
    """Обработчик магазина"""
    data = callback.data.split(":")
    action = data[1]
    user_id = int(data[-1])
    
    if callback.from_user.id != user_id:
        await callback.answer("⚠️ Эта кнопка не для вас!")
        return
    
    session = db.get_active_session(user_id)
    if not session:
        await callback.message.edit_text("🔒 <б>Сначала войдите в аккаунт!</b>")
        await callback.answer()
        return
    
    await callback.answer()
    
    if action == "vip":
        days = int(data[2])
        
        if days not in VIP_PACKAGES:
            await callback.message.edit_text("❌ <b>VIP пакет не найден!</b>")
            return
        
        vip_data = VIP_PACKAGES[days]
        price = vip_data['price']  # Базовая цена
        
        # Проверяем, есть ли у пользователя VIP для скидки
        if session.get('is_vip'):
            price = vip_data['vip_price']  # Цена со скидкой для VIP
        
        profile = db.get_profile(session['account_id'])
        
        if profile['balance'] < price:
            await callback.message.edit_text(
                f"❌ <b>НЕДОСТАТОЧНО СРЕДСТВ!</b>\n\n"
                f"💎 <b>VIP {days} дней:</b> {price} Pulse\n"
                f"💰 <b>Ваш баланс:</b> {profile['balance']} Pulse\n\n"
                f"💡 <i>Пополните баланс через работу или бонусы.</i>"
            )
            return
        
        # Покупка VIP
        db.update_balance(session['account_id'], -price, 'vip_purchase', f"VIP на {days} дней")
        db.activate_vip(session['account_id'], days)
        
        new_balance = profile['balance'] - price
        
        await callback.message.edit_text(
            f"⭐ <b>VIP АКТИВИРОВАН!</b>\n\n"
            f"💎 <b>Пакет:</b> VIP на {days} дней\n"
            f"💰 <b>Стоимость:</b> {price} Pulse\n"
            f"💰 <b>Новый баланс:</b> <b>{new_balance:,}</b> Pulse\n\n"
            f"🎁 <b>Бонусы:</b>\n"
            + "\n".join([f"• {bonus}" for bonus in vip_data['bonuses']]) + "\n\n"
            f"🌟 <b>Ваш VIP активен. Все выигрыши увеличены на ×1.5!</b>",
            reply_markup=Keyboards.main_menu(user_id, True, db.is_admin(user_id))
        )
    
    elif action == "soon":
        await callback.answer("🚀 Скоро в магазине!", show_alert=True)

@dp.callback_query(F.data.startswith("draw:"))
async def handle_draw_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик розыгрышей"""
    data = callback.data.split(":")
    action = data[1]
    user_id = int(data[-1])
    
    if callback.from_user.id != user_id:
        await callback.answer("⚠️ Эта кнопка не для вас!")
        return
    
    session = db.get_active_session(user_id)
    if not session:
        await callback.message.edit_text("🔒 <b>Сначала войдите в аккаунт!</b>")
        await callback.answer()
        return
    
    await callback.answer()
    
    if action == "view":
        if len(data) > 3:
            draw_id = int(data[2])
            # Здесь можно показать детали розыгрыша
            await callback.answer("📋 Детали розыгрыша скоро будут доступны!", show_alert=True)
    
    elif action == "join":
        active_draws = db.get_active_draws()
        
        if not active_draws:
            await callback.message.edit_text(
                "🎫 <b>Нет активных розыгрышей для участия!</b>\n\n"
                "💡 <i>Следите за новыми розыгрышами.</i>",
                reply_markup=Keyboards.draws_menu(user_id)
            )
            return
        
        # Показываем первый доступный розыгрыш
        draw = active_draws[0]
        
        # Проверяем кулдаун участия
        can_join, cooldown_until = db.check_cooldown(session['account_id'], 'draw_participation')
        
        if not can_join:
            remaining = cooldown_until - datetime.now()
            minutes = int(remaining.total_seconds() // 60)
            
            await callback.message.edit_text(
                f"⏰ <b>Вы недавно участвовали в розыгрыше!</b>\n\n"
                f"🎫 <b>Следующее участие через:</b> {minutes} минут\n\n"
                f"💡 <i>Подождите немного перед следующим участием.</i>",
                reply_markup=Keyboards.draws_menu(user_id)
            )
            return
        
        # Участвуем в розыгрыше
        success, message, ticket_number = db.join_draw(draw['draw_id'], session['account_id'])
        
        if success:
            db.set_cooldown(session['account_id'], 'draw_participation', 
                          db.get_setting('draw_participation_cooldown', 3600))
            
            await callback.message.edit_text(
                f"🎁 <b>ВЫ УЧАСТВУЕТЕ В РОЗЫГРЫШЕ!</b>\n\n"
                f"🎯 <b>Розыгрыш:</b> {draw['name']}\n"
                f"💰 <b>Приз:</b> {draw['prize_amount']} Pulse\n"
                f"🎫 <b>Ваш билет:</b> №{ticket_number}\n\n"
                f"👥 <b>Участников:</b> {draw['current_participants']}/{draw['max_participants'] or '∞'}\n\n"
                f"💡 <b>Результаты будут объявлены после окончания розыгрыша.</b>\n\n"
                f"🌟 <b>Удачи!</b>",
                reply_markup=Keyboards.draws_menu(user_id)
            )
        else:
            await callback.message.edit_text(
                f"❌ <b>НЕ УДАЛОСЬ ПРИСОЕДИНИТЬСЯ!</b>\n\n"
                f"{message}\n\n"
                f"💡 <i>Попробуйте другой розыгрыш или вернитесь позже.</i>",
                reply_markup=Keyboards.draws_menu(user_id)
            )
    
    elif action == "mylist":
        # Здесь можно показать список участий пользователя
        await callback.answer("📋 Список ваших участий скоро будет доступен!", show_alert=True)
    
    elif action == "none":
        await callback.answer("🎫 Пока нет активных розыгрышей!", show_alert=True)

@dp.callback_query(F.data.startswith("admin:"))
async def handle_admin_callback(callback: CallbackQuery):
    """Обработчик админ-панели"""
    data = callback.data.split(":")
    action = data[1]
    user_id = int(data[-1])
    
    if callback.from_user.id != user_id:
        await callback.answer("⚠️ Эта кнопка не для вас!")
        return
    
    if not db.is_admin(user_id):
        await callback.answer("🚫 Доступ запрещен!")
        return
    
    await callback.answer()
    
    if action == "main":
        await callback.message.edit_text(
            "🛠 <b>АДМИНИСТРАТИВНАЯ ПАНЕЛЬ</b>\n\n"
            "👇 <b>Выберите раздел:</b>",
            reply_markup=Keyboards.admin_menu(user_id)
        )
    
    elif action == "users":
        stats = db.get_statistics()
        
        await callback.message.edit_text(
            "👥 <b>УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ</b>\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"• Пользователей: {stats['total_users']:,}\n"
            f"• Аккаунтов: {stats['total_accounts']:,}\n"
            f"• Общий баланс: {stats['total_balance']:,} Pulse\n\n"
            "⚡ <i>Расширенные функции управления скоро будут доступны!</i>",
            reply_markup=Keyboards.admin_menu(user_id)
        )
    
    elif action == "games":
        await callback.message.edit_text(
            "🎮 <b>УПРАВЛЕНИЕ ИГРАМИ</b>\n\n"
            "🎯 <b>Доступные игры:</b>\n"
            + "\n".join([f"• {config['name']}" for config in GAMES_CONFIG.values()]) + "\n\n"
            "⚡ <i>Настройка параметров игр скоро будет доступна!</i>",
            reply_markup=Keyboards.admin_menu(user_id)
        )
    
    elif action == "draws":
        active_draws = db.get_active_draws()
        
        draws_text = (
            "🎫 <b>УПРАВЛЕНИЕ РОЗЫГРЫШАМИ</b>\n\n"
            f"🎁 <b>Активных розыгрышей:</b> {len(active_draws)}\n\n"
        )
        
        if active_draws:
            for draw in active_draws[:3]:
                end_date = datetime.fromisoformat(draw['end_date'])
                time_left = end_date - datetime.now()
                days = time_left.days
                
                draws_text += (
                    f"🎯 <b>{draw['name']}</b>\n"
                    f"👥 Участников: {draw['current_participants']}\n"
                    f"⏰ Осталось: {days} дней\n\n"
                )
        
        draws_text += "⚡ <i>Создание и управление розыгрышами скоро будет доступно!</i>"
        
        await callback.message.edit_text(
            draws_text,
            reply_markup=Keyboards.admin_menu(user_id)
        )
    
    elif action == "settings":
        await callback.message.edit_text(
            "⚙️ <b>НАСТРОЙКИ БОТА</b>\n\n"
            "🔧 <b>Текущие настройки:</b>\n"
            f"• Макс аккаунтов на пользователя: {db.get_setting('max_accounts_per_user', 3)}\n"
            f"• Минимальная ставка: {db.get_setting('min_bet', 25)} Pulse\n"
            f"• Ежедневный бонус: {db.get_setting('daily_bonus', 50)} Pulse\n"
            f"• Множитель VIP: ×{db.get_setting('vip_multiplier', 1.5)}\n\n"
            "⚡ <i>Изменение настроек скоро будет доступно!</i>",
            reply_markup=Keyboards.admin_menu(user_id)
        )
    
    elif action == "stats":
        stats = db.get_statistics()
        
        stats_text = (
            "📊 <b>СТАТИСТИКА БОТА</b>\n\n"
            f"👥 <b>Пользователей:</b> {stats['total_users']:,}\n"
            f"👤 <b>Аккаунтов:</b> {stats['total_accounts']:,}\n"
            f"💰 <b>Общий баланс:</b> {stats['total_balance']:,} Pulse\n"
            f"🎮 <b>Игр сегодня:</b> {stats['games_today']}\n"
            f"🎫 <b>Активных розыгрышей:</b> {stats['active_draws']}\n\n"
            f"⚡ <b>Бот работает стабильно!</b>"
        )
        
        await callback.message.edit_text(
            stats_text,
            reply_markup=Keyboards.admin_menu(user_id)
        )
    
    elif action == "logs":
        await callback.message.edit_text(
            "📋 <b>ЛОГИ ДЕЙСТВИЙ</b>\n\n"
            "⚡ <i>Просмотр логов скоро будет доступен!</i>\n\n"
            "💡 <i>Логи сохраняются в файл pulse_bot.log</i>",
            reply_markup=Keyboards.admin_menu(user_id)
        )
    
    elif action == "draw":
        subaction = data[2]
        
        if subaction == "create":
            await callback.message.edit_text(
                "🎫 <b>СОЗДАНИЕ РОЗЫГРЫША</b>\n\n"
                "⚡ <i>Функция создания розыгрышей скоро будет доступна!</i>\n\n"
                "💡 <i>Пока что розыгрыши можно создавать только через базу данных.</i>",
                reply_markup=Keyboards.admin_menu(user_id)
            )

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция запуска бота"""
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 50)
    print("🚀 ЗАПУСК PULSEBOT...")
    print(f"🤖 Бот: {BOT_USERNAME}")
    print(f"👑 Владелец: {OWNER_ID}")
    print("=" * 50)
    
    try:
        # Добавляем владельца как администратора
        db.create_or_update_telegram_user(type('User', (), {'id': OWNER_ID, 'username': 'owner', 
                                                           'first_name': 'Owner', 'last_name': '', 
                                                           'language_code': 'ru'})())
        
        # Запускаем бота
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(main())
