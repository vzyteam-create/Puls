import logging
import sqlite3
import json
import uuid
import hashlib
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from enum import Enum
import asyncio

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    Message, Chat, InputFile
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode

# === КОНФИГУРАЦИЯ ===
BOT_TOKEN = "8557190026:AAGnqxtrAyZz-huihyGctKWNHgjt7w9lQTo"
ADMIN_ID = 6708209142  # Ваш ID
BOT_USERNAME = "@PulsOfficialManager_bot"

# Валюта платформы (виртуальные монеты)
CURRENCY_NAME = "PULS Coin"
CURRENCY_SYMBOL = "Ⓟ"
INITIAL_BALANCE = 100  # Стартовый баланс для новых пользователей
DAILY_BONUS = 50  # Ежедневный бонус

# Статусы
REG_EMAIL, REG_PASSWORD, REG_CONFIRM_PASSWORD, LOGIN_EMAIL, LOGIN_PASSWORD = range(5)
PRODUCT_TITLE, PRODUCT_DESC, PRODUCT_PRICE, PRODUCT_QUANTITY = range(5, 9)

# === НАСТРОЙКА ЛОГГИНГА ===
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === БАЗА ДАННЫХ ===
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('puls_marketplace.db', check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Пользователи (игровые аккаунты)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS players (
                player_id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                username TEXT,
                display_name TEXT,
                email TEXT UNIQUE,
                password_hash TEXT,
                balance INTEGER DEFAULT 1000,
                level INTEGER DEFAULT 1,
                xp INTEGER DEFAULT 0,
                reputation FLOAT DEFAULT 0.0,
                total_sales INTEGER DEFAULT 0,
                total_purchases INTEGER DEFAULT 0,
                is_verified BOOLEAN DEFAULT 1,
                is_banned BOOLEAN DEFAULT 0,
                daily_bonus_claimed DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Игровые товары
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS game_items (
                item_id TEXT PRIMARY KEY,
                seller_id INTEGER,
                game_name TEXT,
                item_name TEXT,
                item_type TEXT,
                rarity TEXT,
                description TEXT,
                price INTEGER,
                quantity INTEGER DEFAULT 1,
                image_url TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                views INTEGER DEFAULT 0,
                FOREIGN KEY (seller_id) REFERENCES players (player_id)
            )
        ''')
        
        # Торговые сделки
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                item_id TEXT,
                buyer_id INTEGER,
                seller_id INTEGER,
                price INTEGER,
                quantity INTEGER,
                status TEXT DEFAULT 'escrow',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                dispute_opened BOOLEAN DEFAULT 0,
                dispute_winner INTEGER,
                FOREIGN KEY (item_id) REFERENCES game_items (item_id),
                FOREIGN KEY (buyer_id) REFERENCES players (player_id),
                FOREIGN KEY (seller_id) REFERENCES players (player_id)
            )
        ''')
        
        # Эскроу-счета (удержание средств)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS escrow_accounts (
                escrow_id TEXT PRIMARY KEY,
                trade_id TEXT,
                amount INTEGER,
                status TEXT DEFAULT 'held',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                released_at TIMESTAMP,
                FOREIGN KEY (trade_id) REFERENCES trades (trade_id)
            )
        ''')
        
        # Подтверждения получения
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS confirmations (
                confirmation_id TEXT PRIMARY KEY,
                trade_id TEXT,
                player_id INTEGER,
                action TEXT,
                message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (trade_id) REFERENCES trades (trade_id)
            )
        ''')
        
        # Споры и арбитраж
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS disputes (
                dispute_id TEXT PRIMARY KEY,
                trade_id TEXT,
                opener_id INTEGER,
                reason TEXT,
                status TEXT DEFAULT 'open',
                admin_id INTEGER,
                resolution TEXT,
                resolved_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (trade_id) REFERENCES trades (trade_id)
            )
        ''')
        
        # Отзывы и репутация
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reviews (
                review_id TEXT PRIMARY KEY,
                trade_id TEXT,
                reviewer_id INTEGER,
                target_id INTEGER,
                rating INTEGER CHECK(rating >= 1 AND rating <= 5),
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (trade_id) REFERENCES trades (trade_id)
            )
        ''')
        
        # Игровая статистика
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS player_stats (
                stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER,
                stat_name TEXT,
                stat_value INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (player_id) REFERENCES players (player_id)
            )
        ''')
        
        # Чат сделки
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trade_chats (
                chat_id TEXT PRIMARY KEY,
                trade_id TEXT,
                buyer_id INTEGER,
                seller_id INTEGER,
                last_message TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (trade_id) REFERENCES trades (trade_id)
            )
        ''')
        
        # Сообщения в чате
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_messages (
                message_id TEXT PRIMARY KEY,
                chat_id TEXT,
                sender_id INTEGER,
                message_type TEXT,
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES trade_chats (chat_id)
            )
        ''')
        
        # Игровые достижения
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS achievements (
                achievement_id TEXT PRIMARY KEY,
                player_id INTEGER,
                achievement_name TEXT,
                description TEXT,
                icon TEXT,
                unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (player_id) REFERENCES players (player_id)
            )
        ''')
        
        # Уведомления администратора
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_alerts (
                alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT,
                player_id INTEGER,
                item_id TEXT,
                trade_id TEXT,
                message TEXT,
                priority TEXT DEFAULT 'normal',
                is_resolved BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
    
    # === ИГРОВЫЕ МЕТОДЫ ===
    def create_player(self, telegram_id: int, username: str, display_name: str, 
                     email: str, password: str) -> Tuple[bool, str]:
        """Создание игрового аккаунта"""
        if not self.validate_email(email):
            return False, "🎮 Неверный формат email"
        
        if self.check_email_exists(email):
            return False, "🎮 Этот email уже зарегистрирован"
        
        if len(password) < 6:
            return False, "🎮 Пароль должен содержать минимум 6 символов"
        
        password_hash = self.hash_password(password)
        
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO players (telegram_id, username, display_name, email, password_hash, balance)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (telegram_id, username, display_name, email, password_hash, INITIAL_BALANCE))
            
            player_id = cursor.lastrowid
            
            # Создаем начальные достижения
            achievements = [
                ("welcome", "🎉 Добро пожаловать!", "Первые шаги в PULS Marketplace"),
                ("first_account", "👤 Аккаунт создан", "Регистрация в системе"),
                ("initial_balance", f"💰 Стартовый капитал {INITIAL_BALANCE}{CURRENCY_SYMBOL}", "Получение начальных средств")
            ]
            
            for ach_id, name, desc in achievements:
                cursor.execute('''
                    INSERT INTO achievements (achievement_id, player_id, achievement_name, description)
                    VALUES (?, ?, ?, ?)
                ''', (f"{player_id}_{ach_id}", player_id, name, desc))
            
            # Создаем статистику
            stats = [
                ("trades_completed", 0),
                ("items_sold", 0),
                ("items_bought", 0),
                ("positive_reviews", 0),
                ("disputes_won", 0)
            ]
            
            for stat_name, stat_value in stats:
                cursor.execute('''
                    INSERT INTO player_stats (player_id, stat_name, stat_value)
                    VALUES (?, ?, ?)
                ''', (player_id, stat_name, stat_value))
            
            # Отправляем уведомление админу
            cursor.execute('''
                INSERT INTO admin_alerts (alert_type, player_id, message, priority)
                VALUES (?, ?, ?, 'low')
            ''', ('new_player', player_id, f"🎮 Новый игрок: {display_name} (@{username})"))
            
            self.conn.commit()
            return True, str(player_id)
            
        except Exception as e:
            logger.error(f"Player creation error: {e}")
            return False, "🎮 Ошибка при создании аккаунта"
    
    def login_player(self, email: str, password: str, telegram_id: int) -> Tuple[bool, str]:
        """Вход в игровой аккаунт"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT player_id, password_hash, display_name, is_banned 
            FROM players 
            WHERE email = ?
        ''', (email,))
        
        result = cursor.fetchone()
        if not result:
            return False, "🎮 Аккаунт не найден"
        
        player_id, stored_hash, display_name, is_banned = result
        
        if is_banned:
            return False, "🎮 Аккаунт заблокирован"
        
        if self.hash_password(password) != stored_hash:
            return False, "🎮 Неверный пароль"
        
        # Обновляем данные телеграма и активность
        cursor.execute('''
            UPDATE players 
            SET telegram_id = ?, last_active = CURRENT_TIMESTAMP 
            WHERE player_id = ?
        ''', (telegram_id, player_id))
        
        # Проверяем ежедневный бонус
        cursor.execute('SELECT daily_bonus_claimed FROM players WHERE player_id = ?', (player_id,))
        last_claim = cursor.fetchone()[0]
        
        today = datetime.now().date().isoformat()
        if not last_claim or last_claim != today:
            cursor.execute('''
                UPDATE players 
                SET balance = balance + ?, daily_bonus_claimed = ?
                WHERE player_id = ?
            ''', (DAILY_BONUS, today, player_id))
            
            cursor.execute('''
                INSERT INTO achievements (achievement_id, player_id, achievement_name, description)
                VALUES (?, ?, ?, ?)
            ''', (f"{player_id}_daily_{today}", player_id, "💰 Ежедневный бонус", f"Получено {DAILY_BONUS}{CURRENCY_SYMBOL}"))
            
            bonus_message = f"\n🎁 Получен ежедневный бонус: +{DAILY_BONUS}{CURRENCY_SYMBOL}"
        else:
            bonus_message = ""
        
        self.conn.commit()
        return True, f"{player_id}|{display_name}|{bonus_message}"
    
    def get_player(self, player_id: int) -> Optional[Tuple]:
        """Получение информации об игроке"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM players WHERE player_id = ?
        ''', (player_id,))
        return cursor.fetchone()
    
    def get_player_by_telegram(self, telegram_id: int) -> Optional[Tuple]:
        """Получение игрока по Telegram ID"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM players WHERE telegram_id = ?', (telegram_id,))
        return cursor.fetchone()
    
    # === ВАЛИДАЦИЯ ===
    def hash_password(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()
    
    def validate_email(self, email: str) -> bool:
        pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        return re.match(pattern, email) is not None
    
    def check_email_exists(self, email: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute('SELECT 1 FROM players WHERE email = ?', (email,))
        return cursor.fetchone() is not None
    
    # === ИГРОВАЯ ЭКОНОМИКА ===
    def update_balance(self, player_id: int, amount: int, reason: str):
        """Обновление баланса игрока"""
        cursor = self.conn.cursor()
        cursor.execute('UPDATE players SET balance = balance + ? WHERE player_id = ?', (amount, player_id))
        
        # Логируем операцию (в реальной системе здесь была бы транзакция)
        if amount > 0:
            logger.info(f"Player {player_id} получил {amount}{CURRENCY_SYMBOL}: {reason}")
        else:
            logger.info(f"Player {player_id} потратил {-amount}{CURRENCY_SYMBOL}: {reason}")
        
        # Проверяем достижения
        if reason == "продажа товара":
            cursor.execute('''
                SELECT total_sales FROM players WHERE player_id = ?
            ''', (player_id,))
            total_sales = cursor.fetchone()[0] + 1
            
            if total_sales >= 10:
                cursor.execute('''
                    INSERT OR IGNORE INTO achievements (achievement_id, player_id, achievement_name, description)
                    VALUES (?, ?, ?, ?)
                ''', (f"{player_id}_seller_10", player_id, "🏪 Начинающий продавец", "Продано 10 товаров"))
            
            if total_sales >= 100:
                cursor.execute('''
                    INSERT OR IGNORE INTO achievements (achievement_id, player_id, achievement_name, description)
                    VALUES (?, ?, ?, ?)
                ''', (f"{player_id}_seller_100", player_id, "🏬 Опытный торговец", "Продано 100 товаров"))
        
        self.conn.commit()
    
    def get_balance(self, player_id: int) -> int:
        """Получение баланса игрока"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT balance FROM players WHERE player_id = ?', (player_id,))
        result = cursor.fetchone()
        return result[0] if result else 0
    
    # === МАРКЕТПЛЕЙС ===
    def create_game_item(self, seller_id: int, game_name: str, item_name: str, 
                        item_type: str, rarity: str, description: str, 
                        price: int, quantity: int) -> Tuple[bool, str]:
        """Создание игрового товара"""
        item_id = str(uuid.uuid4())
        
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO game_items (item_id, seller_id, game_name, item_name, 
                                      item_type, rarity, description, price, quantity)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (item_id, seller_id, game_name, item_name, item_type, rarity, description, price, quantity))
            
            # Уведомление админу о новом товаре
            cursor.execute('''
                INSERT INTO admin_alerts (alert_type, player_id, item_id, message, priority)
                VALUES (?, ?, ?, ?, 'low')
            ''', ('new_item', seller_id, item_id, f"🆕 Новый товар: {item_name} ({game_name})"))
            
            # Достижение за первый товар
            cursor.execute('SELECT COUNT(*) FROM game_items WHERE seller_id = ?', (seller_id,))
            item_count = cursor.fetchone()[0]
            
            if item_count == 1:
                cursor.execute('''
                    INSERT INTO achievements (achievement_id, player_id, achievement_name, description)
                    VALUES (?, ?, ?, ?)
                ''', (f"{seller_id}_first_item", seller_id, "📦 Первый товар", "Выставлен первый товар на продажу"))
            
            self.conn.commit()
            return True, item_id
            
        except Exception as e:
            logger.error(f"Item creation error: {e}")
            return False, str(e)
    
    def get_marketplace_items(self, game_filter: str = None, type_filter: str = None, 
                             rarity_filter: str = None, limit: int = 50) -> List[Tuple]:
        """Получение товаров для маркетплейса"""
        cursor = self.conn.cursor()
        query = '''
            SELECT gi.*, p.display_name as seller_name, p.reputation
            FROM game_items gi
            JOIN players p ON gi.seller_id = p.player_id
            WHERE gi.status = 'active' AND gi.quantity > 0
        '''
        params = []
        
        if game_filter:
            query += " AND gi.game_name = ?"
            params.append(game_filter)
        
        if type_filter:
            query += " AND gi.item_type = ?"
            params.append(type_filter)
        
        if rarity_filter:
            query += " AND gi.rarity = ?"
            params.append(rarity_filter)
        
        query += " ORDER BY gi.created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        return cursor.fetchall()
    
    def get_item(self, item_id: str) -> Optional[Tuple]:
        """Получение информации о товаре"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT gi.*, p.display_name as seller_name, p.reputation, p.total_sales
            FROM game_items gi
            JOIN players p ON gi.seller_id = p.player_id
            WHERE gi.item_id = ?
        ''', (item_id,))
        return cursor.fetchone()
    
    # === СИСТЕМА ТОРГОВЛИ ===
    def create_trade(self, item_id: str, buyer_id: int, quantity: int) -> Tuple[bool, str]:
        """Создание торговой сделки"""
        try:
            cursor = self.conn.cursor()
            
            # Получаем информацию о товаре
            item = self.get_item(item_id)
            if not item:
                return False, "🎮 Товар не найден"
            
            item_idx = {i[0]: i for i in cursor.description}
            price = item[item_idx['price'][0]]
            seller_id = item[item_idx['seller_id'][0]]
            available_quantity = item[item_idx['quantity'][0]]
            
            if seller_id == buyer_id:
                return False, "🎮 Нельзя купить свой товар"
            
            if quantity > available_quantity:
                return False, f"🎮 Доступно только {available_quantity} шт."
            
            # Проверяем баланс покупателя
            buyer_balance = self.get_balance(buyer_id)
            total_price = price * quantity
            
            if buyer_balance < total_price:
                return False, f"🎮 Недостаточно {CURRENCY_NAME}. Нужно: {total_price}{CURRENCY_SYMBOL}"
            
            # Создаем сделку
            trade_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT INTO trades (trade_id, item_id, buyer_id, seller_id, price, quantity, status)
                VALUES (?, ?, ?, ?, ?, ?, 'escrow')
            ''', (trade_id, item_id, buyer_id, seller_id, price, quantity))
            
            # Создаем эскроу-счет
            escrow_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT INTO escrow_accounts (escrow_id, trade_id, amount)
                VALUES (?, ?, ?)
            ''', (escrow_id, trade_id, total_price))
            
            # Блокируем средства покупателя
            cursor.execute('UPDATE players SET balance = balance - ? WHERE player_id = ?', 
                          (total_price, buyer_id))
            
            # Резервируем товар
            cursor.execute('UPDATE game_items SET quantity = quantity - ? WHERE item_id = ?', 
                          (quantity, item_id))
            
            # Создаем чат для сделки
            chat_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT INTO trade_chats (chat_id, trade_id, buyer_id, seller_id)
                VALUES (?, ?, ?, ?)
            ''', (chat_id, trade_id, buyer_id, seller_id))
            
            # Уведомление админу
            cursor.execute('''
                INSERT INTO admin_alerts (alert_type, trade_id, message, priority)
                VALUES (?, ?, ?, 'medium')
            ''', ('new_trade', trade_id, f"🔄 Новая сделка: {trade_id}"))
            
            # Добавляем просмотр товару
            cursor.execute('UPDATE game_items SET views = views + 1 WHERE item_id = ?', (item_id,))
            
            self.conn.commit()
            return True, trade_id
            
        except Exception as e:
            logger.error(f"Trade creation error: {e}")
            return False, str(e)
    
    def confirm_delivery(self, trade_id: str, player_id: int) -> Tuple[bool, str]:
        """Подтверждение получения товара"""
        try:
            cursor = self.conn.cursor()
            
            # Получаем информацию о сделке
            cursor.execute('''
                SELECT t.*, e.amount 
                FROM trades t
                JOIN escrow_accounts e ON t.trade_id = e.trade_id
                WHERE t.trade_id = ? AND (t.buyer_id = ? OR t.seller_id = ?)
            ''', (trade_id, player_id, player_id))
            
            trade = cursor.fetchone()
            if not trade:
                return False, "🎮 Сделка не найдена"
            
            trade_idx = {i[0]: i for i in cursor.description}
            buyer_id = trade[trade_idx['buyer_id'][0]]
            seller_id = trade[trade_idx['seller_id'][0]]
            amount = trade[trade_idx['amount'][0]]
            status = trade[trade_idx['status'][0]]
            
            if status != 'escrow':
                return False, "🎮 Неверный статус сделки"
            
            # Проверяем, кто подтверждает
            is_buyer = player_id == buyer_id
            
            if is_buyer:
                # Покупатель подтверждает получение
                cursor.execute('''
                    UPDATE trades 
                    SET status = 'completed', completed_at = CURRENT_TIMESTAMP
                    WHERE trade_id = ?
                ''', (trade_id,))
                
                cursor.execute('''
                    UPDATE escrow_accounts 
                    SET status = 'released', released_at = CURRENT_TIMESTAMP
                    WHERE trade_id = ?
                ''', (trade_id,))
                
                # Переводим средства продавцу
                cursor.execute('UPDATE players SET balance = balance + ? WHERE player_id = ?', 
                              (amount, seller_id))
                
                cursor.execute('''
                    UPDATE players 
                    SET total_sales = total_sales + 1 
                    WHERE player_id = ?
                ''', (seller_id,))
                
                cursor.execute('''
                    UPDATE players 
                    SET total_purchases = total_purchases + 1 
                    WHERE player_id = ?
                ''', (buyer_id,))
                
                # Создаем подтверждение
                confirmation_id = str(uuid.uuid4())
                cursor.execute('''
                    INSERT INTO confirmations (confirmation_id, trade_id, player_id, action)
                    VALUES (?, ?, ?, 'delivery_confirmed')
                ''', (confirmation_id, trade_id, buyer_id))
                
                message = f"✅ Получение подтверждено! {amount}{CURRENCY_SYMBOL} переведены продавцу."
            
            else:
                # Продавец подтверждает отправку
                cursor.execute('''
                    INSERT INTO confirmations (confirmation_id, trade_id, player_id, action, message)
                    VALUES (?, ?, ?, 'shipping_confirmed', ?)
                ''', (str(uuid.uuid4()), trade_id, seller_id, "Товар отправлен покупателю"))
                
                message = "📦 Отправка товара подтверждена. Ожидайте подтверждения получения от покупателя."
            
            # Обновляем статистику
            cursor.execute('''
                UPDATE player_stats 
                SET stat_value = stat_value + 1 
                WHERE player_id = ? AND stat_name = 'trades_completed'
            ''', (player_id,))
            
            self.conn.commit()
            return True, message
            
        except Exception as e:
            logger.error(f"Delivery confirmation error: {e}")
            return False, str(e)
    
    def open_dispute(self, trade_id: str, player_id: int, reason: str) -> Tuple[bool, str]:
        """Открытие спора по сделке"""
        try:
            cursor = self.conn.cursor()
            
            # Проверяем существование сделки
            cursor.execute('''
                SELECT 1 FROM trades 
                WHERE trade_id = ? AND (buyer_id = ? OR seller_id = ?) AND status = 'escrow'
            ''', (trade_id, player_id, player_id))
            
            if not cursor.fetchone():
                return False, "🎮 Сделка не найдена или не может быть оспорена"
            
            # Проверяем, не открыт ли уже спор
            cursor.execute('SELECT 1 FROM disputes WHERE trade_id = ? AND status = "open"', (trade_id,))
            if cursor.fetchone():
                return False, "🎮 Спор по этой сделке уже открыт"
            
            # Создаем спор
            dispute_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT INTO disputes (dispute_id, trade_id, opener_id, reason, status)
                VALUES (?, ?, ?, ?, 'open')
            ''', (dispute_id, trade_id, player_id, reason))
            
            # Обновляем статус сделки
            cursor.execute('UPDATE trades SET dispute_opened = 1 WHERE trade_id = ?', (trade_id,))
            
            # Уведомление админу
            cursor.execute('''
                INSERT INTO admin_alerts (alert_type, trade_id, dispute_id, message, priority)
                VALUES (?, ?, ?, ?, 'high')
            ''', ('dispute_opened', trade_id, dispute_id, f"⚠️ Открыт спор: {reason}"))
            
            self.conn.commit()
            return True, dispute_id
            
        except Exception as e:
            logger.error(f"Dispute opening error: {e}")
            return False, str(e)
    
    # === СИСТЕМА ОТЗЫВОВ ===
    def create_review(self, trade_id: str, reviewer_id: int, target_id: int, 
                     rating: int, comment: str) -> Tuple[bool, str]:
        """Создание отзыва"""
        try:
            # Проверяем существование сделки
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT 1 FROM trades 
                WHERE trade_id = ? AND (buyer_id = ? OR seller_id = ?) AND status = 'completed'
            ''', (trade_id, reviewer_id, reviewer_id))
            
            if not cursor.fetchone():
                return False, "🎮 Сделка не найдена или не завершена"
            
            # Проверяем, не оставлял ли уже отзыв
            cursor.execute('SELECT 1 FROM reviews WHERE trade_id = ? AND reviewer_id = ?', 
                          (trade_id, reviewer_id))
            if cursor.fetchone():
                return False, "🎮 Вы уже оставляли отзыв на эту сделку"
            
            # Создаем отзыв
            review_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT INTO reviews (review_id, trade_id, reviewer_id, target_id, rating, comment)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (review_id, trade_id, reviewer_id, target_id, rating, comment))
            
            # Обновляем репутацию
            cursor.execute('''
                UPDATE players 
                SET reputation = (
                    SELECT AVG(rating) FROM reviews WHERE target_id = ?
                )
                WHERE player_id = ?
            ''', (target_id, target_id))
            
            # Обновляем статистику
            if rating >= 4:
                cursor.execute('''
                    UPDATE player_stats 
                    SET stat_value = stat_value + 1 
                    WHERE player_id = ? AND stat_name = 'positive_reviews'
                ''', (target_id,))
            
            # Достижение за первый отзыв
            cursor.execute('SELECT COUNT(*) FROM reviews WHERE reviewer_id = ?', (reviewer_id,))
            review_count = cursor.fetchone()[0]
            
            if review_count == 1:
                cursor.execute('''
                    INSERT INTO achievements (achievement_id, player_id, achievement_name, description)
                    VALUES (?, ?, ?, ?)
                ''', (f"{reviewer_id}_first_review", reviewer_id, "⭐ Первый отзыв", "Оставлен первый отзыв"))
            
            self.conn.commit()
            return True, "✅ Отзыв успешно добавлен"
            
        except Exception as e:
            logger.error(f"Review creation error: {e}")
            return False, str(e)
    
    # === АДМИН-МЕТОДЫ ===
    def get_admin_alerts(self, priority: str = None) -> List[Tuple]:
        """Получение уведомлений для админа"""
        cursor = self.conn.cursor()
        
        if priority:
            cursor.execute('''
                SELECT * FROM admin_alerts 
                WHERE priority = ? AND is_resolved = 0
                ORDER BY created_at DESC
                LIMIT 50
            ''', (priority,))
        else:
            cursor.execute('''
                SELECT * FROM admin_alerts 
                WHERE is_resolved = 0
                ORDER BY 
                    CASE priority 
                        WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2
                        WHEN 'low' THEN 3
                    END,
                    created_at DESC
                LIMIT 50
            ''')
        
        return cursor.fetchall()
    
    def resolve_alert(self, alert_id: int):
        """Пометка уведомления как решенного"""
        cursor = self.conn.cursor()
        cursor.execute('UPDATE admin_alerts SET is_resolved = 1 WHERE alert_id = ?', (alert_id,))
        self.conn.commit()
    
    def get_platform_stats(self) -> Dict:
        """Получение статистики платформы"""
        cursor = self.conn.cursor()
        
        stats = {}
        
        cursor.execute('SELECT COUNT(*) FROM players')
        stats['total_players'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM game_items WHERE status = "active"')
        stats['active_items'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM trades WHERE status = "completed"')
        stats['completed_trades'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(amount) FROM escrow_accounts WHERE status = "released"')
        total_trade_volume = cursor.fetchone()[0] or 0
        stats['total_volume'] = total_trade_volume
        
        cursor.execute('SELECT SUM(balance) FROM players')
        total_wealth = cursor.fetchone()[0] or 0
        stats['total_wealth'] = total_wealth
        
        cursor.execute('SELECT COUNT(*) FROM disputes WHERE status = "open"')
        stats['open_disputes'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM players WHERE DATE(last_active) = DATE("now")')
        stats['active_today'] = cursor.fetchone()[0]
        
        return stats
    
    def admin_resolve_dispute(self, dispute_id: str, winner_id: int, resolution: str):
        """Разрешение спора администратором"""
        try:
            cursor = self.conn.cursor()
            
            # Получаем информацию о споре
            cursor.execute('''
                SELECT d.trade_id, t.amount, t.buyer_id, t.seller_id
                FROM disputes d
                JOIN escrow_accounts t ON d.trade_id = t.trade_id
                WHERE d.dispute_id = ?
            ''', (dispute_id,))
            
            result = cursor.fetchone()
            if not result:
                return False
            
            trade_id, amount, buyer_id, seller_id = result
            
            # Обновляем спор
            cursor.execute('''
                UPDATE disputes 
                SET status = 'resolved', admin_id = ?, resolution = ?, resolved_at = CURRENT_TIMESTAMP
                WHERE dispute_id = ?
            ''', (ADMIN_ID, resolution, dispute_id))
            
            # Определяем кому перевести средства
            if winner_id == buyer_id:
                # Возвращаем средства покупателю
                cursor.execute('UPDATE players SET balance = balance + ? WHERE player_id = ?', 
                              (amount, buyer_id))
                cursor.execute('UPDATE trades SET dispute_winner = ? WHERE trade_id = ?', 
                              (buyer_id, trade_id))
            elif winner_id == seller_id:
                # Переводим средства продавцу
                cursor.execute('UPDATE players SET balance = balance + ? WHERE player_id = ?', 
                              (amount, seller_id))
                cursor.execute('UPDATE trades SET dispute_winner = ? WHERE trade_id = ?', 
                              (seller_id, trade_id))
            else:
                # Возвращаем 50/50 (компромисс)
                half_amount = amount // 2
                cursor.execute('UPDATE players SET balance = balance + ? WHERE player_id = ?', 
                              (half_amount, buyer_id))
                cursor.execute('UPDATE players SET balance = balance + ? WHERE player_id = ?', 
                              (half_amount, seller_id))
                cursor.execute('UPDATE trades SET dispute_winner = 0 WHERE trade_id = ?', (trade_id,))
            
            # Обновляем статусы
            cursor.execute('''
                UPDATE trades 
                SET status = 'dispute_resolved', completed_at = CURRENT_TIMESTAMP
                WHERE trade_id = ?
            ''', (trade_id,))
            
            cursor.execute('''
                UPDATE escrow_accounts 
                SET status = 'released', released_at = CURRENT_TIMESTAMP
                WHERE trade_id = ?
            ''', (trade_id,))
            
            self.conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Dispute resolution error: {e}")
            return False

# Инициализация базы данных
db = Database()

# === ХЕЛПЕР-ФУНКЦИИ ===
def get_player_session(context: ContextTypes.DEFAULT_TYPE) -> Optional[Tuple]:
    """Получение сессии игрока"""
    player_data = context.user_data.get('player_data')
    if not player_data:
        return None
    return player_data

def require_player(func):
    """Декоратор для проверки авторизации игрока"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        player_data = get_player_session(context)
        if not player_data:
            await update.message.reply_text(
                "🎮 Вы не вошли в игровой аккаунт.\n\n"
                "Используйте:\n"
                "/register - Создать аккаунт\n"
                "/login - Войти в аккаунт"
            )
            return
        
        player_id, display_name, _ = player_data.split('|')
        player = db.get_player(int(player_id))
        
        if not player:
            await update.message.reply_text("🎮 Сессия устарела. Пожалуйста, войдите снова: /login")
            context.user_data.clear()
            return
        
        return await func(update, context, player, *args, **kwargs)
    return wrapper

def require_admin(func):
    """Декоратор для проверки прав администратора"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            await update.message.reply_text("🎮 Эта команда доступна только администратору.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# === КОМАНДЫ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начальная команда с игровой тематикой"""
    user = update.effective_user
    
    welcome_text = f"""
    🎮 *Добро пожаловать в PULS | Vanezy Test Platform!*

    🔬 *Тестовая платформа виртуальной экономики*
    🎯 *Бета-версия маркетплейса игровых товаров*

    🌟 *Особенности системы:*
    • Виртуальная валюта {CURRENCY_SYMBOL} {CURRENCY_NAME}
    • Торговля игровыми предметами
    • Система эскроу (удержания средств)
    • Арбитраж и разрешение споров
    • Система репутации и отзывов
    • Игровые достижения и статистика

    💰 *Каждый новый игрок получает:* {INITIAL_BALANCE}{CURRENCY_SYMBOL}
    🎁 *Ежедневный бонус:* {DAILY_BONUS}{CURRENCY_SYMBOL}

    🚀 *Быстрый старт:*
    1️⃣ /register - Создать игровой аккаунт
    2️⃣ /login - Войти в систему
    3️⃣ /balance - Проверить баланс
    4️⃣ /market - Посмотреть маркетплейс

    📊 *Это тестовая платформа* - все транзакции виртуальные
    ⚠️ *Бета-тестирование* - система в активной разработке

    🛠️ *Администратор:* @vanezyyy
    🎯 *Цель:* Создание безопасной игровой экономики
    """
    
    keyboard = [
        [InlineKeyboardButton("🎮 Создать аккаунт", callback_data="quick_register")],
        [InlineKeyboardButton("🔐 Войти в аккаунт", callback_data="quick_login")],
        [InlineKeyboardButton("🛒 Маркетплейс", callback_data="quick_market")],
        [InlineKeyboardButton("📚 Инструкция", callback_data="tutorial")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обучение работе с платформой"""
    tutorial_text = """
    📚 *Руководство по PULS Test Platform*

    🎮 *1. Создание аккаунта*
    • Используйте /register
    • Укажите email и пароль
    • Получите стартовый капитал

    💰 *2. Экономика платформы*
    • Валюта: {CURRENCY_SYMBOL} {CURRENCY_NAME}
    • Стартовый баланс: {INITIAL_BALANCE}{CURRENCY_SYMBOL}
    • Ежедневный бонус: {DAILY_BONUS}{CURRENCY_SYMBOL}
    • Баланс виртуальный (тестовая среда)

    🛒 *3. Как купить товар:*
    1. /market - Просмотр товаров
    2. Выберите товар
    3. Нажмите "Купить"
    4. Средства блокируются в эскроу
    5. После получения - подтвердите
    6. Средства переводятся продавцу

    📦 *4. Как продать товар:*
    1. /sell - Создать товар
    2. Заполните информацию
    3. Товар появляется на маркетплейсе
    4. При продаже - средства в эскроу
    5. После подтверждения покупателем - получаете деньги

    🔒 *5. Система эскроу:*
    • Средства блокируются при покупке
    • Переводятся продавцу только после подтверждения
    • Защита от мошенничества
    • Возможность открыть спор

    ⚖️ *6. Споры и арбитраж:*
    • При проблемах - откройте спор
    • Администратор рассмотрит ситуацию
    • Принятие решения в течение 24 часов
    • Возврат/перевод средств по решению админа

    ⭐ *7. Система репутации:*
    • Оставляйте отзывы после сделок
    • Рейтинг влияет на доверие
    • Высокий рейтинг = больше покупателей

    🏆 *8. Достижения:*
    • Разблокируйте достижения
    • Увеличивайте уровень
    • Соревнуйтесь с другими игроками

    ⚠️ *Важно:*
    • Это тестовая платформа
    • Все транзакции виртуальные
    • Цель - тестирование экономики
    • Администратор @vanezyyy
    """.format(
        CURRENCY_SYMBOL=CURRENCY_SYMBOL,
        CURRENCY_NAME=CURRENCY_NAME,
        INITIAL_BALANCE=INITIAL_BALANCE,
        DAILY_BONUS=DAILY_BONUS
    )
    
    await update.message.reply_text(
        tutorial_text,
        parse_mode=ParseMode.MARKDOWN
    )

# === РЕГИСТРАЦИЯ И АВТОРИЗАЦИЯ ===
async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Регистрация игрового аккаунта"""
    await update.message.reply_text(
        "🎮 *Создание игрового аккаунта*\n\n"
        "📧 Введите ваш email:",
        parse_mode=ParseMode.MARKDOWN
    )
    return REG_EMAIL

async def register_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка email при регистрации"""
    email = update.message.text.strip().lower()
    
    if not db.validate_email(email):
        await update.message.reply_text(
            "🎮 Неверный формат email. Пожалуйста, введите корректный email:"
        )
        return REG_EMAIL
    
    if db.check_email_exists(email):
        await update.message.reply_text(
            "🎮 Этот email уже зарегистрирован. Введите другой email или войдите: /login"
        )
        return ConversationHandler.END
    
    context.user_data['register_email'] = email
    await update.message.reply_text(
        "🔐 Придумайте пароль (минимум 6 символов):\n\n"
        "Это пароль для входа в ваш игровой аккаунт"
    )
    return REG_PASSWORD

async def register_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка пароля при регистрации"""
    password = update.message.text.strip()
    
    if len(password) < 6:
        await update.message.reply_text(
            "🎮 Пароль должен содержать минимум 6 символов. Попробуйте снова:"
        )
        return REG_PASSWORD
    
    context.user_data['register_password'] = password
    await update.message.reply_text(
        "🔐 Подтвердите пароль (введите его еще раз):"
    )
    return REG_CONFIRM_PASSWORD

async def register_confirm_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение пароля"""
    confirm_password = update.message.text.strip()
    password = context.user_data.get('register_password')
    
    if password != confirm_password:
        await update.message.reply_text(
            "🎮 Пароли не совпадают. Начните заново: /register"
        )
        return ConversationHandler.END
    
    # Регистрируем игрока
    user = update.effective_user
    email = context.user_data['register_email']
    display_name = user.first_name or user.username or f"Игрок_{user.id}"
    
    success, result = db.create_player(
        telegram_id=user.id,
        username=user.username or "",
        display_name=display_name,
        email=email,
        password=password
    )
    
    if success:
        player_id = result
        
        # Входим в аккаунт автоматически
        login_success, login_result = db.login_player(email, password, user.id)
        
        if login_success:
            player_data = login_result
            context.user_data['player_data'] = player_data
            
            player_info = player_data.split('|')
            display_name = player_info[1]
            bonus_message = player_info[2] if len(player_info) > 2 else ""
            
            await update.message.reply_text(
                f"""
                🎉 *Аккаунт успешно создан!*
                
                👤 Игрок: {display_name}
                🆔 ID: {player_id}
                💰 Баланс: {INITIAL_BALANCE}{CURRENCY_SYMBOL}
                {bonus_message}
                
                🏆 *Разблокированы достижения:*
                • 🎉 Добро пожаловать!
                • 👤 Аккаунт создан
                • 💰 Стартовый капитал
                
                🚀 *Начните играть:*
                • /market - Маркетплейс
                • /balance - Баланс
                • /profile - Профиль
                • /tutorial - Обучение
                
                ⚠️ *Это тестовая платформа*
                💡 Все транзакции виртуальные
                """,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                f"✅ Регистрация успешна! Войдите в аккаунт: /login"
            )
    else:
        await update.message.reply_text(f"🎮 Ошибка: {result}")
    
    # Очищаем временные данные
    context.user_data.pop('register_email', None)
    context.user_data.pop('register_password', None)
    
    return ConversationHandler.END

async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в игровой аккаунт"""
    await update.message.reply_text(
        "🎮 *Вход в игровой аккаунт*\n\n"
        "📧 Введите ваш email:",
        parse_mode=ParseMode.MARKDOWN
    )
    return LOGIN_EMAIL

async def login_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка email при входе"""
    email = update.message.text.strip().lower()
    context.user_data['login_email'] = email
    await update.message.reply_text("🔐 Введите пароль:")
    return LOGIN_PASSWORD

async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка пароля при входе"""
    password = update.message.text.strip()
    email = context.user_data.get('login_email')
    user = update.effective_user
    
    success, result = db.login_player(email, password, user.id)
    
    if success:
        context.user_data['player_data'] = result
        
        player_info = result.split('|')
        player_id = player_info[0]
        display_name = player_info[1]
        bonus_message = player_info[2] if len(player_info) > 2 else ""
        
        player = db.get_player(int(player_id))
        player_idx = {i[0]: i for i in db.conn.execute('SELECT * FROM players LIMIT 1').description}
        balance = player[player_idx['balance'][0]]
        level = player[player_idx['level'][0]]
        reputation = player[player_idx['reputation'][0]]
        
        await update.message.reply_text(
            f"""
            ✅ *Вход выполнен!*
            
            👤 Добро пожаловать, {display_name}!
            🆔 ID: {player_id}
            💼 Уровень: {level}
            ⭐ Репутация: {reputation:.1f}/5.0
            💰 Баланс: {balance}{CURRENCY_SYMBOL}
            {bonus_message}
            
            🎮 *Доступные команды:*
            • /market - Маркетплейс
            • /sell - Продать товар
            • /orders - Мои сделки
            • /profile - Профиль
            • /achievements - Достижения
            • /chats - Чаты сделок
            
            ⚠️ *Бета-тестирование*
            💡 Виртуальная экономика
            """,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(f"🎮 {result}")
    
    # Очищаем временные данные
    context.user_data.pop('login_email', None)
    
    return ConversationHandler.END

async def logout_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выход из игрового аккаунта"""
    if 'player_data' in context.user_data:
        context.user_data.pop('player_data', None)
    
    await update.message.reply_text(
        "✅ Вы вышли из игрового аккаунта.\n\n"
        "Используйте /login для входа или /register для создания нового аккаунта."
    )

# === КОМАНДЫ МАРКЕТПЛЕЙСА ===
@require_player
async def market_command(update: Update, context: ContextTypes.DEFAULT_TYPE, player: Tuple):
    """Просмотр маркетплейса"""
    player_idx = {i[0]: i for i in db.conn.execute('SELECT * FROM players LIMIT 1').description}
    player_id = player[player_idx['player_id'][0]]
    
    # Популярные игры для фильтрации
    popular_games = ["CS2", "Dota 2", "Valorant", "Minecraft", "Rust", "TF2", "GTA V", "Warframe", "Россия"]
    
    keyboard = [
        [InlineKeyboardButton("🎮 Все товары", callback_data="market_all")],
        [InlineKeyboardButton("🔥 Популярное", callback_data="market_popular")],
        [InlineKeyboardButton("💰 Дешевые", callback_data="market_cheap")],
        [InlineKeyboardButton("🏆 Премиум", callback_data="market_premium")],
    ]
    
    # Кнопки игр
    row = []
    for i, game in enumerate(popular_games):
        row.append(InlineKeyboardButton(game, callback_data=f"market_game_{game}"))
        if len(row) == 3 or i == len(popular_games) - 1:
            keyboard.append(row)
            row = []
    
    keyboard.append([
        InlineKeyboardButton("🔍 Поиск", callback_data="market_search"),
        InlineKeyboardButton("📦 Мои товары", callback_data="my_items")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"""
        🛒 *PULS Маркетплейс | Бета-тестирование*
        
        🌟 *Торговая площадка виртуальных товаров*
        💰 *Валюта:* {CURRENCY_SYMBOL} {CURRENCY_NAME}
        ⚠️ *Виртуальная экономика | Тестовая платформа*
        
        📊 *Доступные категории:*
        • 🎮 Игровые аккаунты
        • 🔑 Ключи и коды
        • 💎 Игровая валюта
        • 🛡️ Предметы и скины
        • 👥 Услуги и бустинг
        
        🔍 *Используйте фильтры для поиска*
        """,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def market_filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фильтров маркетплейса"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    items = []
    
    if data == "market_all":
        items = db.get_marketplace_items(limit=30)
        title = "🛒 Все товары"
    elif data == "market_popular":
        # Здесь можно добавить логику популярности
        items = db.get_marketplace_items(limit=30)
        items = sorted(items, key=lambda x: x[11] if len(x) > 11 else 0, reverse=True)[:20]  # Сортировка по просмотрам
        title = "🔥 Популярные товары"
    elif data == "market_cheap":
        items = db.get_marketplace_items(limit=50)
        items = sorted(items, key=lambda x: x[7] if len(x) > 7 else 0)[:20]  # Сортировка по цене
        title = "💰 Самые дешевые"
    elif data == "market_premium":
        items = db.get_marketplace_items(rarity_filter="Легендарный", limit=20)
        title = "🏆 Премиум товары"
    elif data.startswith("market_game_"):
        game_name = data.replace("market_game_", "")
        items = db.get_marketplace_items(game_filter=game_name, limit=20)
        title = f"🎮 {game_name}"
    else:
        await query.edit_message_text("🎮 Функция в разработке")
        return
    
    if not items:
        await query.edit_message_text(
            f"📭 {title}\n\n"
            "Товаров пока нет. Будьте первым!\n"
            "Продать товар: /sell"
        )
        return
    
    # Сохраняем товары для пагинации
    context.user_data['market_items'] = items
    context.user_data['market_title'] = title
    context.user_data['current_item_index'] = 0
    
    await show_market_item(update, context)

async def show_market_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ товара на маркетплейсе"""
    query = update.callback_query
    items = context.user_data.get('market_items', [])
    current_index = context.user_data.get('current_item_index', 0)
    title = context.user_data.get('market_title', 'Маркетплейс')
    
    if not items or current_index >= len(items):
        await query.edit_message_text("🎮 Товары не найдены.")
        return
    
    item = items[current_index]
    item_idx = {i[0]: i for i in db.conn.execute('SELECT * FROM game_items LIMIT 1').description}
    
    # Извлекаем данные с проверкой индексов
    item_id = item[0]
    game_name = item[2] if len(item) > 2 else "Неизвестно"
    item_name = item[3] if len(item) > 3 else "Без названия"
    item_type = item[4] if len(item) > 4 else "Разное"
    rarity = item[5] if len(item) > 5 else "Обычный"
    description = item[6] if len(item) > 6 else "Описание отсутствует"
    price = item[7] if len(item) > 7 else 0
    quantity = item[8] if len(item) > 8 else 1
    seller_name = item[13] if len(item) > 13 else "Неизвестен"
    reputation = item[14] if len(item) > 14 else 0.0
    
    # Иконки редкости
    rarity_icons = {
        "Обычный": "⚪",
        "Необычный": "🔵", 
        "Редкий": "🟣",
        "Эпический": "🟠",
        "Легендарный": "🟡",
        "Уникальный": "🔴"
    }
    
    rarity_icon = rarity_icons.get(rarity, "⚪")
    
    item_text = f"""
    {rarity_icon} *{item_name}*
    🎮 Игра: {game_name}
    📦 Тип: {item_type}
    🏷️ Редкость: {rarity}
    
    📝 Описание:
    {description[:200]}{'...' if len(description) > 200 else ''}
    
    💰 Цена: *{price}{CURRENCY_SYMBOL}* за шт.
    📊 Количество: {quantity} шт.
    
    👤 Продавец: {seller_name}
    ⭐ Репутация: {reputation:.1f}/5.0
    
    🆔 ID: `{item_id}`
    """
    
    keyboard = []
    
    # Кнопки навигации
    nav_buttons = []
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton("◀️", callback_data="market_prev"))
    
    nav_buttons.append(InlineKeyboardButton(f"{current_index + 1}/{len(items)}", callback_data="none"))
    
    if current_index < len(items) - 1:
        nav_buttons.append(InlineKeyboardButton("▶️", callback_data="market_next"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Кнопки действий
    action_buttons = [
        InlineKeyboardButton("🛒 Купить", callback_data=f"buy_item_{item_id}"),
        InlineKeyboardButton("⭐ В избранное", callback_data=f"favorite_{item_id}")
    ]
    keyboard.append(action_buttons)
    
    keyboard.append([InlineKeyboardButton("💬 Написать продавцу", callback_data=f"message_seller_{item_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад к фильтрам", callback_data="back_to_filters")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"{title}\n\n{item_text}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def market_navigation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по товарам маркетплейса"""
    query = update.callback_query
    await query.answer()
    
    action = query.data
    
    if action == "market_prev":
        context.user_data['current_item_index'] -= 1
    elif action == "market_next":
        context.user_data['current_item_index'] += 1
    elif action == "back_to_filters":
        await market_command(update, context)
        return
    
    await show_market_item(update, context)

@require_player
async def buy_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, player: Tuple):
    """Покупка товара"""
    query = update.callback_query
    await query.answer()
    
    item_id = query.data.replace("buy_item_", "")
    player_idx = {i[0]: i for i in db.conn.execute('SELECT * FROM players LIMIT 1').description}
    buyer_id = player[player_idx['player_id'][0]]
    
    # Получаем информацию о товаре
    item = db.get_item(item_id)
    if not item:
        await query.message.reply_text("🎮 Товар не найден.")
        return
    
    item_idx = {i[0]: i for i in db.conn.execute('SELECT * FROM game_items LIMIT 1').description}
    item_name = item[3]
    price = item[7]
    seller_id = item[1]
    
    if seller_id == buyer_id:
        await query.message.reply_text("🎮 Вы не можете купить свой собственный товар.")
        return
    
    # Спрашиваем количество
    context.user_data['buy_item_id'] = item_id
    context.user_data['buy_item_price'] = price
    
    await query.message.reply_text(
        f"""
        🛒 *Покупка товара*
        
        🎮 Товар: {item_name}
        💰 Цена за шт.: {price}{CURRENCY_SYMBOL}
        
        Введите количество (от 1):
        """,
        parse_mode=ParseMode.MARKDOWN
    )
    
    context.user_data['awaiting_purchase_quantity'] = True

async def process_purchase_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка количества при покупке"""
    if not context.user_data.get('awaiting_purchase_quantity'):
        return
    
    try:
        quantity = int(update.message.text.strip())
        item_id = context.user_data.get('buy_item_id')
        
        if quantity < 1:
            await update.message.reply_text("🎮 Количество должно быть не менее 1.")
            return
        
        # Получаем информацию об игроке
        player_data = get_player_session(context)
        if not player_data:
            return
        
        player_id = int(player_data.split('|')[0])
        
        # Создаем сделку
        success, result = db.create_trade(item_id, player_id, quantity)
        
        if success:
            trade_id = result
            
            # Получаем детали товара для сообщения
            item = db.get_item(item_id)
            item_idx = {i[0]: i for i in db.conn.execute('SELECT * FROM game_items LIMIT 1').description}
            item_name = item[3] if len(item) > 3 else "Товар"
            price = context.user_data.get('buy_item_price', 0)
            total_price = price * quantity
            
            await update.message.reply_text(
                f"""
                ✅ *Сделка создана!*
                
                🆔 Номер сделки: `{trade_id}`
                🎮 Товар: {item_name}
                💰 Сумма: {total_price}{CURRENCY_SYMBOL}
                📦 Количество: {quantity} шт.
                
                🔒 *Средства заморожены в эскроу*
                💡 После получения товара подтвердите его
                
                📋 Детали сделки: /trade_{trade_id}
                💬 Чат с продавцом: /chat_{trade_id}
                
                ⚠️ *Тестовая сделка* - виртуальные средства
                """,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(f"🎮 Ошибка: {result}")
        
        # Очищаем состояние
        context.user_data.pop('awaiting_purchase_quantity', None)
        context.user_data.pop('buy_item_id', None)
        context.user_data.pop('buy_item_price', None)
        
    except ValueError:
        await update.message.reply_text("🎮 Пожалуйста, введите корректное число.")
    except Exception as e:
        logger.error(f"Purchase processing error: {e}")
        await update.message.reply_text("🎮 Произошла ошибка при создании сделки.")

# === КОМАНДЫ ДЛЯ ПРОДАЖИ ===
@require_player
async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE, player: Tuple):
    """Продажа товара - начало"""
    player_idx = {i[0]: i for i in db.conn.execute('SELECT * FROM players LIMIT 1').description}
    player_id = player[player_idx['player_id'][0]]
    balance = player[player_idx['balance'][0]]
    
    # Игры для выбора
    games = ["CS2", "Dota 2", "Valorant", "Minecraft", "Rust", "TF2", "GTA V", "Warframe", "Другая"]
    
    keyboard = []
    row = []
    for i, game in enumerate(games):
        row.append(InlineKeyboardButton(game, callback_data=f"sell_game_{game}"))
        if len(row) == 2 or i == len(games) - 1:
            keyboard.append(row)
            row = []
    
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_sell")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"""
        📤 *Выставить товар на продажу*
        
        💰 Ваш баланс: {balance}{CURRENCY_SYMBOL}
        ⚠️ *Тестовая платформа* - виртуальные товары
        
        📋 *Правила продажи:*
        • Только игровые предметы и услуги
        • Запрещены реальные товары
        • Цена должна быть адекватной
        • Описание должно быть честным
        
        🎮 *Выберите игру:*
        """,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def sell_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор игры при продаже"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_sell":
        await query.edit_message_text("❌ Создание товара отменено.")
        return
    
    game_name = query.data.replace("sell_game_", "")
    context.user_data['sell_game'] = game_name
    
    # Типы товаров
    item_types = ["Аккаунт", "Ключ/Код", "Валюта", "Предмет/Скин", "Услуга", "Набор", "Другое"]
    
    keyboard = []
    row = []
    for i, item_type in enumerate(item_types):
        row.append(InlineKeyboardButton(item_type, callback_data=f"sell_type_{item_type}"))
        if len(row) == 2 or i == len(item_types) - 1:
            keyboard.append(row)
            row = []
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"""
        📝 *Создание товара*
        
        🎮 Игра: *{game_name}*
        
        📦 *Выберите тип товара:*
        """,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def sell_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор типа товара"""
    query = update.callback_query
    await query.answer()
    
    item_type = query.data.replace("sell_type_", "")
    context.user_data['sell_type'] = item_type
    
    # Редкость (если предмет)
    rarities = ["Обычный", "Необычный", "Редкий", "Эпический", "Легендарный", "Уникальный"]
    
    keyboard = []
    row = []
    for i, rarity in enumerate(rarities):
        row.append(InlineKeyboardButton(rarity, callback_data=f"sell_rarity_{rarity}"))
        if len(row) == 2 or i == len(rarities) - 1:
            keyboard.append(row)
            row = []
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"""
        📝 *Создание товара*
        
        🎮 Игра: {context.user_data['sell_game']}
        📦 Тип: {item_type}
        
        🏷️ *Выберите редкость:*
        """,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def sell_rarity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор редкости"""
    query = update.callback_query
    await query.answer()
    
    rarity = query.data.replace("sell_rarity_", "")
    context.user_data['sell_rarity'] = rarity
    context.user_data['sell_step'] = 'title'
    
    await query.edit_message_text(
        f"""
        📝 *Создание товара*
        
        🎮 Игра: {context.user_data['sell_game']}
        📦 Тип: {context.user_data['sell_type']}
        🏷️ Редкость: {rarity}
        
        ✏️ *Введите название товара:*
        (Например: "Аккаунт CS2 с ножами", "1000 голды WoW")
        """,
        parse_mode=ParseMode.MARKDOWN
    )

async def process_sell_steps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка шагов создания товара"""
    if 'sell_step' not in context.user_data:
        return
    
    step = context.user_data['sell_step']
    text = update.message.text
    
    if step == 'title':
        if len(text) < 3:
            await update.message.reply_text("🎮 Название должно содержать минимум 3 символа.")
            return
        
        context.user_data['sell_title'] = text
        context.user_data['sell_step'] = 'description'
        
        await update.message.reply_text(
            "📝 *Введите описание товара:*\n\n"
            "Опишите подробно что вы продаете, условия, требования.\n"
            "Пример: 'Аккаунт Steam с CS2, 1000 часов, 10 ножей, привязана почта'"
        )
    
    elif step == 'description':
        if len(text) < 10:
            await update.message.reply_text("🎮 Описание должно содержать минимум 10 символов.")
            return
        
        context.user_data['sell_description'] = text
        context.user_data['sell_step'] = 'price'
        
        await update.message.reply_text(
            f"""
            💰 *Введите цену за единицу товара (в {CURRENCY_SYMBOL}):*
            
            Пример: 1000
            Минимальная цена: 1{CURRENCY_SYMBOL}
            Максимальная цена: 1000000{CURRENCY_SYMBOL}
            
            ⚠️ *Тестовая цена* - виртуальная валюта
            """
        )
    
    elif step == 'price':
        try:
            price = int(text)
            if price < 1 or price > 1000000:
                await update.message.reply_text(f"🎮 Цена должна быть от 1 до 1000000{CURRENCY_SYMBOL}.")
                return
            
            context.user_data['sell_price'] = price
            context.user_data['sell_step'] = 'quantity'
            
            await update.message.reply_text(
                "📦 *Введите количество товара:*\n\n"
                "Сколько единиц этого товара вы продаете?\n"
                "Пример: 1 (если это аккаунт) или 1000 (если это игровая валюта)"
            )
        
        except ValueError:
            await update.message.reply_text("🎮 Пожалуйста, введите корректную цену (целое число).")
    
    elif step == 'quantity':
        try:
            quantity = int(text)
            if quantity < 1:
                await update.message.reply_text("🎮 Количество должно быть не менее 1.")
                return
            
            # Получаем информацию об игроке
            player_data = get_player_session(context)
            if not player_data:
                return
            
            player_id = int(player_data.split('|')[0])
            
            # Создаем товар
            success, item_id = db.create_game_item(
                seller_id=player_id,
                game_name=context.user_data['sell_game'],
                item_name=context.user_data['sell_title'],
                item_type=context.user_data['sell_type'],
                rarity=context.user_data['sell_rarity'],
                description=context.user_data['sell_description'],
                price=context.user_data['sell_price'],
                quantity=quantity
            )
            
            if success:
                await update.message.reply_text(
                    f"""
                    ✅ *Товар успешно выставлен!*
                    
                    🎮 Товар: {context.user_data['sell_title']}
                    💰 Цена: {context.user_data['sell_price']}{CURRENCY_SYMBOL}
                    📦 Количество: {quantity} шт.
                    🆔 ID: `{item_id}`
                    
                    📍 *Товар теперь доступен на маркетплейсе*
                    👁️‍🗨️ Посмотреть: /market
                    
                    ⚠️ *Тестовый товар* - виртуальная экономика
                    💡 Товар сразу доступен для покупки
                    
                    🎯 *Совет:* Чем подробнее описание, тем быстрее продадите!
                    """,
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # Очищаем данные
                keys_to_remove = ['sell_step', 'sell_game', 'sell_type', 'sell_rarity',
                                'sell_title', 'sell_description', 'sell_price']
                for key in keys_to_remove:
                    context.user_data.pop(key, None)
            else:
                await update.message.reply_text(f"🎮 Ошибка при создании товара: {item_id}")
        
        except ValueError:
            await update.message.reply_text("🎮 Пожалуйста, введите корректное число.")
        except Exception as e:
            logger.error(f"Item creation error: {e}")
            await update.message.reply_text("🎮 Произошла ошибка при создании товара.")

# === КОМАНДЫ БАЛАНСА И ПРОФИЛЯ ===
@require_player
async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE, player: Tuple):
    """Просмотр баланса и статистики"""
    player_idx = {i[0]: i for i in db.conn.execute('SELECT * FROM players LIMIT 1').description}
    player_id = player[player_idx['player_id'][0]]
    balance = player[player_idx['balance'][0]]
    level = player[player_idx['level'][0]]
    xp = player[player_idx['xp'][0]]
    reputation = player[player_idx['reputation'][0]]
    total_sales = player[player_idx['total_sales'][0]]
    total_purchases = player[player_idx['total_purchases'][0]]
    display_name = player[player_idx['display_name'][0]]
    
    # Получаем статистику
    cursor = db.conn.cursor()
    cursor.execute('SELECT stat_name, stat_value FROM player_stats WHERE player_id = ?', (player_id,))
    stats = cursor.fetchall()
    
    stats_dict = {name: value for name, value in stats}
    
    keyboard = [
        [InlineKeyboardButton("📤 Выставить товар", callback_data="sell_item")],
        [InlineKeyboardButton("🛒 Маркетплейс", callback_data="go_to_market")],
        [InlineKeyboardButton("📊 Подробная статистика", callback_data="full_stats")],
        [InlineKeyboardButton("🎁 Ежедневный бонус", callback_data="daily_bonus")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"""
        💰 *Игровая экономика | Тестовая платформа*
        
        👤 Игрок: *{display_name}*
        🆔 ID: `{player_id}`
        💼 Уровень: *{level}*
        ⭐ XP: *{xp}/1000*
        
        💰 *Баланс:* *{balance}{CURRENCY_SYMBOL}*
        ⭐ *Репутация:* {reputation:.1f}/5.0
        
        📊 *Статистика:*
        🛒 Продано: {total_sales} товаров
        🛍️ Куплено: {total_purchases} товаров
        ✅ Завершено сделок: {stats_dict.get('trades_completed', 0)}
        👍 Положительных отзывов: {stats_dict.get('positive_reviews', 0)}
        
        ⚠️ *Виртуальная валюта* | Бета-тестирование
        💡 {CURRENCY_SYMBOL} {CURRENCY_NAME} не имеет реальной стоимости
        """,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

@require_player
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE, player: Tuple):
    """Просмотр профиля игрока"""
    player_idx = {i[0]: i for i in db.conn.execute('SELECT * FROM players LIMIT 1').description}
    player_id = player[player_idx['player_id'][0]]
    display_name = player[player_idx['display_name'][0]]
    reputation = player[player_idx['reputation'][0]]
    created_at = player[player_idx['created_at'][0]]
    
    # Получаем достижения
    cursor = db.conn.cursor()
    cursor.execute('''
        SELECT achievement_name, description, unlocked_at 
        FROM achievements 
        WHERE player_id = ?
        ORDER BY unlocked_at DESC
        LIMIT 10
    ''', (player_id,))
    
    achievements = cursor.fetchall()
    
    # Получаем последние отзывы
    cursor.execute('''
        SELECT r.rating, r.comment, p.display_name, r.created_at
        FROM reviews r
        JOIN players p ON r.reviewer_id = p.player_id
        WHERE r.target_id = ?
        ORDER BY r.created_at DESC
        LIMIT 5
    ''', (player_id,))
    
    reviews = cursor.fetchall()
    
    profile_text = f"""
    👤 *Профиль игрока*
    
    🏷️ Имя: *{display_name}*
    🆔 ID: `{player_id}`
    ⭐ Репутация: {reputation:.1f}/5.0
    📅 Зарегистрирован: {created_at[:10]}
    
    🏆 *Последние достижения:* ({len(achievements)} всего)
    """
    
    for i, (name, desc, date) in enumerate(achievements[:5], 1):
        profile_text += f"\n{i}. {name}\n   {desc}"
    
    if reviews:
        profile_text += "\n\n⭐ *Последние отзывы:*"
        for rating, comment, reviewer, date in reviews[:3]:
            stars = "⭐" * rating
            profile_text += f"\n\n{stars}\n{comment}\n— {reviewer}"
    
    keyboard = [
        [InlineKeyboardButton("📊 Моя статистика", callback_data="my_stats")],
        [InlineKeyboardButton("🏆 Все достижения", callback_data="all_achievements")],
        [InlineKeyboardButton("📦 Мои товары", callback_data="my_active_items")],
        [InlineKeyboardButton("💬 Мои отзывы", callback_data="my_reviews")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        profile_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

# === КОМАНДЫ ДЛЯ СДЕЛОК ===
@require_player
async def trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE, player: Tuple):
    """Просмотр сделок игрока"""
    player_idx = {i[0]: i for i in db.conn.execute('SELECT * FROM players LIMIT 1').description}
    player_id = player[player_idx['player_id'][0]]
    
    cursor = db.conn.cursor()
    cursor.execute('''
        SELECT t.*, gi.item_name, gi.game_name,
               buyer.display_name as buyer_name,
               seller.display_name as seller_name
        FROM trades t
        LEFT JOIN game_items gi ON t.item_id = gi.item_id
        LEFT JOIN players buyer ON t.buyer_id = buyer.player_id
        LEFT JOIN players seller ON t.seller_id = seller.player_id
        WHERE t.buyer_id = ? OR t.seller_id = ?
        ORDER BY t.created_at DESC
        LIMIT 20
    ''', (player_id, player_id))
    
    trades = cursor.fetchall()
    
    if not trades:
        await update.message.reply_text(
            """
            📭 *У вас пока нет сделок*
            
            🛒 *Начните торговать:*
            • /market - Просмотр товаров
            • /sell - Выставить свой товар
            
            💡 *Сделка в тестовой платформе:*
            1. Купите товар
            2. Средства замораживаются
            3. После получения - подтвердите
            4. Средства переводятся продавцу
            """
        )
        return
    
    trade_idx = {i[0]: i for i in cursor.description}
    
    # Статусы с иконками
    status_icons = {
        'escrow': '🔒',
        'completed': '✅',
        'dispute_resolved': '⚖️',
        'cancelled': '❌'
    }
    
    keyboard = []
    for trade in trades:
        trade_id = trade[trade_idx['trade_id'][0]]
        item_name = trade[trade_idx['item_name'][0]] or "Товар"
        status = trade[trade_idx['status'][0]]
        amount = trade[trade_idx['price'][0]] * trade[trade_idx['quantity'][0]]
        
        icon = status_icons.get(status, '📝')
        is_buyer = trade[trade_idx['buyer_id'][0]] == player_id
        role = "🛒 Купил" if is_buyer else "💰 Продал"
        
        button_text = f"{icon} {role}: {item_name[:15]}... - {amount}{CURRENCY_SYMBOL}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"view_trade_{trade_id}")])
    
    keyboard.append([
        InlineKeyboardButton("🔒 В эскроу", callback_data="trades_escrow"),
        InlineKeyboardButton("✅ Завершённые", callback_data="trades_completed")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"""
        📋 *Ваши сделки*
        
        🔒 *Эскроу:* Средства заморожены до подтверждения
        ✅ *Завершённые:* Сделки с полученными отзывами
        
        💰 *Выберите сделку для просмотра:*
        """,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def view_trade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр деталей сделки"""
    query = update.callback_query
    await query.answer()
    
    trade_id = query.data.replace("view_trade_", "")
    
    cursor = db.conn.cursor()
    cursor.execute('''
        SELECT t.*, gi.item_name, gi.description, gi.game_name,
               buyer.display_name as buyer_name, buyer.player_id as buyer_id,
               seller.display_name as seller_name, seller.player_id as seller_id,
               e.amount, e.status as escrow_status
        FROM trades t
        LEFT JOIN game_items gi ON t.item_id = gi.item_id
        LEFT JOIN players buyer ON t.buyer_id = buyer.player_id
        LEFT JOIN players seller ON t.seller_id = seller.player_id
        LEFT JOIN escrow_accounts e ON t.trade_id = e.trade_id
        WHERE t.trade_id = ?
    ''', (trade_id,))
    
    trade = cursor.fetchone()
    
    if not trade:
        await query.edit_message_text("🎮 Сделка не найдена.")
        return
    
    trade_idx = {i[0]: i for i in cursor.description}
    
    # Формируем текст сделки
    trade_text = f"""
    📋 *Детали сделки*
    
    🆔 ID: `{trade_id}`
    🎮 Товар: {trade[trade_idx['item_name'][0]]}
    🎯 Игра: {trade[trade_idx['game_name'][0]]}
    
    👤 Покупатель: {trade[trade_idx['buyer_name'][0]]}
    👤 Продавец: {trade[trade_idx['seller_name'][0]]}
    
    💰 Цена за шт.: {trade[trade_idx['price'][0]]}{CURRENCY_SYMBOL}
    📦 Количество: {trade[trade_idx['quantity'][0]]} шт.
    💵 Общая сумма: {trade[trade_idx['amount'][0]]}{CURRENCY_SYMBOL}
    
    📊 Статус: {trade[trade_idx['status'][0]]}
    🔒 Эскроу: {trade[trade_idx['escrow_status'][0]]}
    🕐 Создана: {trade[trade_idx['created_at'][0]]}
    """
    
    keyboard = []
    
    # Проверяем, является ли пользователь участником сделки
    player_data = get_player_session(context)
    if player_data:
        player_id = int(player_data.split('|')[0])
        buyer_id = trade[trade_idx['buyer_id'][0]]
        seller_id = trade[trade_idx['seller_id'][0]]
        status = trade[trade_idx['status'][0]]
        
        if status == 'escrow':
            if player_id == buyer_id:
                keyboard.append([InlineKeyboardButton("✅ Подтвердить получение", callback_data=f"confirm_trade_{trade_id}")])
            elif player_id == seller_id:
                keyboard.append([InlineKeyboardButton("📦 Подтвердить отправку", callback_data=f"confirm_shipping_{trade_id}")])
            
            keyboard.append([InlineKeyboardButton("⚠️ Открыть спор", callback_data=f"open_dispute_{trade_id}")])
        
        # Чат доступен всем участникам
        keyboard.append([InlineKeyboardButton("💬 Чат сделки", callback_data=f"trade_chat_{trade_id}")])
    
    if trade[trade_idx['status'][0]] == 'completed':
        # Проверяем, оставлял ли уже отзыв
        if player_data:
            player_id = int(player_data.split('|')[0])
            cursor.execute('SELECT 1 FROM reviews WHERE trade_id = ? AND reviewer_id = ?', 
                          (trade_id, player_id))
            if not cursor.fetchone():
                target_id = seller_id if player_id == buyer_id else buyer_id
                keyboard.append([InlineKeyboardButton("⭐ Оставить отзыв", callback_data=f"leave_review_{trade_id}_{target_id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад к сделкам", callback_data="back_to_trades")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        trade_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def confirm_trade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение получения товара"""
    query = update.callback_query
    await query.answer()
    
    trade_id = query.data.replace("confirm_trade_", "")
    
    player_data = get_player_session(context)
    if not player_data:
        await query.message.reply_text("🎮 Вы не авторизованы.")
        return
    
    player_id = int(player_data.split('|')[0])
    
    success, message = db.confirm_delivery(trade_id, player_id)
    
    if success:
        await query.message.reply_text(
            f"""
            {message}
            
            ⭐ *Теперь вы можете оставить отзыв продавцу*
            💬 Используйте команду: /review_{trade_id}
            
            🎯 *Сделка завершена успешно!*
            """,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Обновляем сообщение
        await view_trade_callback(update, context)
    else:
        await query.message.reply_text(f"🎮 Ошибка: {message}")

# === СИСТЕМА ОТЗЫВОВ ===
async def leave_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало оставления отзыва"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.replace("leave_review_", "")
    parts = data.split('_')
    
    if len(parts) >= 2:
        trade_id = parts[0]
        target_id = parts[1]
        
        context.user_data['review_trade_id'] = trade_id
        context.user_data['review_target_id'] = target_id
        
        await query.message.reply_text(
            """
            ⭐ *Оставить отзыв*
            
            Оцените пользователя от 1 до 5 звезд:
            
            1 ⭐ - Очень плохо
            2 ⭐ - Плохо
            3 ⭐ - Нормально
            4 ⭐ - Хорошо
            5 ⭐ - Отлично
            
            Введите оценку (число от 1 до 5):
            """,
            parse_mode=ParseMode.MARKDOWN
        )
        
        context.user_data['awaiting_review_rating'] = True

async def process_review_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка оценки отзыва"""
    if not context.user_data.get('awaiting_review_rating'):
        return
    
    try:
        rating = int(update.message.text.strip())
        
        if rating < 1 or rating > 5:
            await update.message.reply_text("🎮 Оценка должна быть от 1 до 5.")
            return
        
        context.user_data['review_rating'] = rating
        context.user_data['awaiting_review_rating'] = False
        context.user_data['awaiting_review_comment'] = True
        
        await update.message.reply_text(
            "💬 *Напишите комментарий к отзыву:*\n\n"
            "Опишите ваше впечатление от сделки.\n"
            "Максимум 500 символов."
        )
        
    except ValueError:
        await update.message.reply_text("🎮 Пожалуйста, введите число от 1 до 5.")

async def process_review_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка комментария отзыва"""
    if not context.user_data.get('awaiting_review_comment'):
        return
    
    comment = update.message.text.strip()[:500]
    
    if len(comment) < 5:
        await update.message.reply_text("🎮 Комментарий должен содержать минимум 5 символов.")
        return
    
    player_data = get_player_session(context)
    if not player_data:
        return
    
    reviewer_id = int(player_data.split('|')[0])
    trade_id = context.user_data.get('review_trade_id')
    target_id = context.user_data.get('review_target_id')
    rating = context.user_data.get('review_rating')
    
    success, message = db.create_review(trade_id, reviewer_id, int(target_id), rating, comment)
    
    if success:
        stars = "⭐" * rating
        await update.message.reply_text(
            f"""
            ✅ *Отзыв успешно добавлен!*
            
            {stars}
            {comment}
            
            📊 *Репутация пользователя обновлена*
            💡 Спасибо за ваш отзыв!
            """,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(f"🎮 Ошибка: {message}")
    
    # Очищаем состояние
    keys_to_remove = ['review_trade_id', 'review_target_id', 'review_rating',
                     'awaiting_review_comment', 'awaiting_review_rating']
    for key in keys_to_remove:
        context.user_data.pop(key, None)

# === АДМИН-ПАНЕЛЬ ===
@require_admin
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Панель администратора"""
    keyboard = [
        [InlineKeyboardButton("📊 Статистика платформы", callback_data="admin_stats")],
        [InlineKeyboardButton("⚠️ Активные споры", callback_data="admin_disputes")],
        [InlineKeyboardButton("👤 Управление игроками", callback_data="admin_players")],
        [InlineKeyboardButton("🛒 Управление товарами", callback_data="admin_items")],
        [InlineKeyboardButton("🔔 Уведомления", callback_data="admin_alerts")],
        [InlineKeyboardButton("💰 Управление экономикой", callback_data="admin_economy")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        """
        ⚙️ *Панель администратора | Тестовая платформа*
        
        🎮 *PULS Marketplace Beta*
        ⚠️ *Виртуальная экономика для тестирования*
        
        📊 *Функции администрирования:*
        • Мониторинг активности
        • Разрешение споров
        • Управление пользователями
        • Контроль экономики
        
        🔧 *Выберите раздел:*
        """,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

@require_admin
async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика платформы"""
    query = update.callback_query
    await query.answer()
    
    stats = db.get_platform_stats()
    
    stats_text = f"""
    📊 *Статистика платформы | Бета-тестирование*
    
    👥 Игроков: *{stats['total_players']}*
    🛒 Активных товаров: *{stats['active_items']}*
    ✅ Завершённых сделок: *{stats['completed_trades']}*
    
    💰 Общий оборот: *{stats['total_volume']}{CURRENCY_SYMBOL}*
    💵 Общее богатство: *{stats['total_wealth']}{CURRENCY_SYMBOL}*
    
    ⚠️ Активных споров: *{stats['open_disputes']}*
    🎯 Активных сегодня: *{stats['active_today']}*
    
    ⚠️ *Тестовая платформа*
    💡 Виртуальная экономика для тестирования
    """
    
    keyboard = [
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats")],
        [InlineKeyboardButton("📈 Детальная статистика", callback_data="admin_detailed_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        stats_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

@require_admin
async def admin_disputes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление спорами"""
    query = update.callback_query
    await query.answer()
    
    disputes = db.get_admin_alerts('high')
    
    if not disputes:
        await query.edit_message_text(
            """
            ⚖️ *Активные споры*
            
            ✅ На данный момент активных споров нет.
            
            🎮 Все сделки проходят успешно.
            """
        )
        return
    
    dispute_text = "⚠️ *Активные споры, требующие внимания:*\n\n"
    
    for alert in disputes[:10]:
        alert_idx = {i[0]: i for i in db.conn.execute('SELECT * FROM admin_alerts LIMIT 1').description}
        alert_id = alert[0]
        message = alert[5] if len(alert) > 5 else "Сообщение"
        created_at = alert[7] if len(alert) > 7 else ""
        
        dispute_text += f"🆔 {alert_id}: {message}\n"
        dispute_text += f"   📅 {created_at}\n"
        dispute_text += f"   [Рассмотреть](/resolve_{alert_id})\n\n"
    
    keyboard = []
    for alert in disputes[:5]:
        alert_id = alert[0]
        keyboard.append([InlineKeyboardButton(f"Рассмотреть спор {alert_id}", callback_data=f"resolve_dispute_{alert_id}")])
    
    keyboard.append([
        InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin"),
        InlineKeyboardButton("🔄 Обновить", callback_data="admin_disputes")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        dispute_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

# === ОСНОВНАЯ ФУНКЦИЯ ===
def main():
    """Запуск бота"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("tutorial", tutorial))
    application.add_handler(CommandHandler("market", market_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("trades", trades_command))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("logout", logout_command))
    
    # Регистрация ConversationHandler для регистрации
    reg_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("register", register_command)],
        states={
            REG_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_email)],
            REG_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)],
            REG_CONFIRM_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_confirm_password)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)]
    )
    
    # Регистрация ConversationHandler для входа
    login_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("login", login_command)],
        states={
            LOGIN_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_email)],
            LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)]
    )
    
    application.add_handler(reg_conv_handler)
    application.add_handler(login_conv_handler)
    
    # Обработчики callback-запросов
    application.add_handler(CallbackQueryHandler(market_filter_callback, pattern="^market_"))
    application.add_handler(CallbackQueryHandler(market_navigation_callback, pattern="^(market_prev|market_next|back_to_filters)$"))
    application.add_handler(CallbackQueryHandler(buy_item_callback, pattern="^buy_item_"))
    application.add_handler(CallbackQueryHandler(sell_game_callback, pattern="^sell_game_"))
    application.add_handler(CallbackQueryHandler(sell_type_callback, pattern="^sell_type_"))
    application.add_handler(CallbackQueryHandler(sell_rarity_callback, pattern="^sell_rarity_"))
    application.add_handler(CallbackQueryHandler(view_trade_callback, pattern="^view_trade_"))
    application.add_handler(CallbackQueryHandler(confirm_trade_callback, pattern="^confirm_trade_"))
    application.add_handler(CallbackQueryHandler(leave_review_callback, pattern="^leave_review_"))
    application.add_handler(CallbackQueryHandler(admin_stats_callback, pattern="^admin_stats$"))
    application.add_handler(CallbackQueryHandler(admin_disputes_callback, pattern="^admin_disputes$"))
    
    # Обработчики сообщений для многошаговых процессов
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_purchase_quantity))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_sell_steps))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_review_rating))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_review_comment))
    
    # Обработка быстрых команд
    application.add_handler(CallbackQueryHandler(lambda u, c: market_command(u, c), pattern="^quick_market$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: register_command(u, c), pattern="^quick_register$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: login_command(u, c), pattern="^quick_login$"))
    application.add_handler(CallbackQueryHandler(tutorial, pattern="^tutorial$"))
    application.add_handler(CallbackQueryHandler(sell_command, pattern="^sell_item$"))
    application.add_handler(CallbackQueryHandler(market_command, pattern="^go_to_market$"))
    application.add_handler(CallbackQueryHandler(trades_command, pattern="^back_to_trades$"))
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^back_to_admin$"))
    
    # Запуск бота
    print(f"🎮 Бот PULS Marketplace запущен!")
    print(f"⚙️ Режим: Тестовая платформа")
    print(f"💰 Валюта: {CURRENCY_SYMBOL} {CURRENCY_NAME}")
    print(f"👑 Админ: @vanezyyy")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
