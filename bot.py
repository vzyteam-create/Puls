import asyncio
import logging
import sqlite3
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8557190026:AAGnqxtrAyZz-huihyGctKWNHgjt7w9lQTo"
ADMIN_IDS = [6708209142]  # ID для админ-панели (теперь список)
BOT_USERNAME = "@PulsOfficialManager_bot"

# Настройки
COOLDOWN_PM = 3  # КД в ЛС (сек)
COOLDOWN_GROUP = 5  # КД в группах (сек)
BONUS_AMOUNT = 50  # Размер бонуса
BONUS_COOLDOWN = 24 * 3600  # КД бонуса (сек)
WORK_COOLDOWN = 30 * 60  # КД работы (сек)
WORK_LIMIT = 5  # Лимит работ
WORK_LIMIT_COOLDOWN = 10 * 3600  # КД после 5 работ (сек)
GAME_LIMIT = 5  # Лимит игр
GAME_LIMIT_COOLDOWN = 3 * 3600  # КД после 5 игр (сек)
MIN_BET = 25  # Минимальная ставка
VIP_MULTIPLIER = 1.5  # Множитель для VIP

# VIP пакеты
VIP_PACKAGES = {
    30: 1000,    # 1 месяц
    90: 2940,    # 3 месяца
    150: 4850,   # 5 месяцев
    365: 11400   # 12 месяцев
}

# Пароль админки
ADMIN_PASSWORD = "vanezypulsbot13579"

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('pulse_bot.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
    
    def create_tables(self):
        # Пользователи
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
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
                game3_cooldown TIMESTAMP
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
                user_id INTEGER,
                amount INTEGER,
                type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Храним информацию о последних сообщениях для проверки кнопок в группах
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS group_messages (
                message_id INTEGER,
                chat_id INTEGER,
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
    
    def user_exists(self, user_id: int) -> bool:
        self.cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone() is not None
    
    def register_user(self, user_id: int, username: str):
        if not self.user_exists(user_id):
            username = username if username else "Без ника"
            self.cursor.execute(
                "INSERT INTO users (user_id, username) VALUES (?, ?)",
                (user_id, username)
            )
            self.conn.commit()
    
    def get_user(self, user_id: int) -> Dict:
        self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        columns = [desc[0] for desc in self.cursor.description]
        row = self.cursor.fetchone()
        return dict(zip(columns, row)) if row else None
    
    def update_balance(self, user_id: int, amount: int, transaction_type: str = "other"):
        self.cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        if amount < 0:
            self.cursor.execute("UPDATE users SET total_spent = total_spent + ? WHERE user_id = ?", (abs(amount), user_id))
            self.cursor.execute(
                "INSERT INTO transactions (user_id, amount, type) VALUES (?, ?, ?)",
                (user_id, abs(amount), transaction_type)
            )
        self.conn.commit()
    
    def update_last_action(self, user_id: int):
        self.cursor.execute(
            "UPDATE users SET last_action = CURRENT_TIMESTAMP WHERE user_id = ?",
            (user_id,)
        )
        self.conn.commit()
    
    def set_vip(self, user_id: int, days: int):
        user = db.get_user(user_id)
        current_time = datetime.now()
        
        if user['vip_until'] and datetime.fromisoformat(user['vip_until']) > current_time:
            vip_until = datetime.fromisoformat(user['vip_until']) + timedelta(days=days)
        else:
            vip_until = current_time + timedelta(days=days)
        
        self.cursor.execute(
            "UPDATE users SET is_vip = TRUE, vip_until = ? WHERE user_id = ?",
            (vip_until.isoformat(), user_id)
        )
        self.conn.commit()
    
    def check_vip(self, user_id: int) -> bool:
        user = db.get_user(user_id)
        if not user['is_vip']:
            return False
        
        vip_until = datetime.fromisoformat(user['vip_until'])
        if vip_until < datetime.now():
            self.cursor.execute(
                "UPDATE users SET is_vip = FALSE WHERE user_id = ?",
                (user_id,)
            )
            self.conn.commit()
            return False
        return True
    
    def get_top_balance(self, limit: int = 10) -> List[Dict]:
        self.cursor.execute(
            "SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT ?",
            (limit,)
        )
        return [
            {"user_id": row[0], "username": row[1], "balance": row[2]}
            for row in self.cursor.fetchall()
        ]
    
    def get_top_spent(self, limit: int = 10) -> List[Dict]:
        self.cursor.execute(
            "SELECT user_id, username, total_spent FROM users ORDER BY total_spent DESC LIMIT ?",
            (limit,)
        )
        return [
            {"user_id": row[0], "username": row[1], "total_spent": row[2]}
            for row in self.cursor.fetchall()
        ]
    
    def get_treasury(self) -> int:
        self.cursor.execute("SELECT SUM(amount) FROM transactions")
        result = self.cursor.fetchone()[0]
        return result if result else 0
    
    def reset_treasury(self):
        self.cursor.execute("DELETE FROM transactions")
        self.conn.commit()
    
    def get_all_users(self) -> List[int]:
        self.cursor.execute("SELECT user_id FROM users")
        return [row[0] for row in self.cursor.fetchall()]
    
    def save_group_message(self, message_id: int, chat_id: int, user_id: int):
        """Сохраняет информацию о сообщении в группе для проверки кнопок"""
        self.cursor.execute(
            "INSERT INTO group_messages (message_id, chat_id, user_id) VALUES (?, ?, ?)",
            (message_id, chat_id, user_id)
        )
        self.conn.commit()
    
    def check_group_message_owner(self, message_id: int, chat_id: int, user_id: int) -> bool:
        """Проверяет, принадлежит ли сообщение в группе пользователю"""
        self.cursor.execute(
            "SELECT 1 FROM group_messages WHERE message_id = ? AND chat_id = ? AND user_id = ?",
            (message_id, chat_id, user_id)
        )
        return self.cursor.fetchone() is not None

db = Database()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def check_registration(user_id: int) -> bool:
    """Проверяет, зарегистрирован ли пользователь"""
    return db.user_exists(user_id)

async def ensure_registration(message: Message):
    """Проверяет и регистрирует пользователя при необходимости"""
    user_id = message.from_user.id
    username = message.from_user.username
    
    if not check_registration(user_id):
        db.register_user(user_id, username)
        db.update_last_action(user_id)
        return False
    return True

class CooldownManager:
    @staticmethod
    async def check_cooldown(message: Message, is_admin_in_group: bool = False) -> Tuple[bool, Optional[str]]:
        """Проверяет кулдаун перед выполнением действия"""
        user_id = message.from_user.id
        chat_type = message.chat.type
        
        # Админы Telegram в группах без КД
        if chat_type in ["group", "supergroup"] and is_admin_in_group:
            return True, None
        
        user = db.get_user(user_id)
        if not user:
            return True, None
        
        last_action = datetime.fromisoformat(user['last_action'])
        now = datetime.now()
        
        # Определяем КД в зависимости от типа чата
        cooldown_seconds = COOLDOWN_GROUP if chat_type in ["group", "supergroup"] else COOLDOWN_PM
        if db.check_vip(user_id):
            cooldown_seconds = int(cooldown_seconds / VIP_MULTIPLIER)
        
        elapsed = (now - last_action).total_seconds()
        
        if elapsed < cooldown_seconds:
            remaining = cooldown_seconds - elapsed
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            seconds = int(remaining % 60)
            return False, f"Подожди перед следующим действием\nОсталось: {hours} часов {minutes} минут {seconds} секунд"
        
        return True, None
    
    @staticmethod
    def format_time(seconds: float) -> str:
        """Форматирует время в ЧЧ:ММ:СС"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = int(seconds % 60)
        return f"{hours} часов {minutes} минут {seconds} секунд"

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
    
    @staticmethod
    async def check_group_button_owner(callback: CallbackQuery) -> bool:
        """Проверяет владельца кнопки в группе"""
        # В группах проверяем через базу данных
        return db.check_group_message_owner(
            callback.message.message_id,
            callback.message.chat.id,
            callback.from_user.id
        )

# ========== ИГРЫ ==========
class Games:
    """Класс для управления играми"""
    
    @staticmethod
    async def check_game_cooldown(user_id: int, game_number: int) -> Tuple[bool, Optional[str]]:
        """Проверяет кулдаун игры"""
        user = db.get_user(user_id)
        game_count_field = f"game{game_number}_count"
        cooldown_field = f"game{game_number}_cooldown"
        
        # Проверяем лимит игр
        if user[game_count_field] >= GAME_LIMIT:
            cooldown_time = datetime.fromisoformat(user[cooldown_field]) if user[cooldown_field] else datetime.now()
            now = datetime.now()
            
            if cooldown_time > now:
                remaining = (cooldown_time - now).total_seconds()
                if db.check_vip(user_id):
                    remaining = int(remaining / VIP_MULTIPLIER)
                return False, f"Лимит игр исчерпан. Подожди: {CooldownManager.format_time(remaining)}"
            else:
                # Сбрасываем счетчик
                db.cursor.execute(f"UPDATE users SET {game_count_field} = 0 WHERE user_id = ?", (user_id,))
                db.conn.commit()
        
        return True, None
    
    @staticmethod
    async def impulse_game(user_id: int, bet: int) -> Dict[str, Any]:
        """Игра 'Импульс'"""
        # Симуляция игры
        await asyncio.sleep(random.uniform(2, 4))
        
        # Шанс победы ~60%
        win_chance = 0.6
        is_win = random.random() < win_chance
        
        if is_win:
            win_amount = int(bet * 1.6)  # Выигрыш 60% от ставки
            db.update_balance(user_id, win_amount, "game_win")
            result = {
                "win": True,
                "amount": win_amount,
                "message": "🎮 <b>Импульс</b>\nТы успешно поймал момент стабильности! Отличная реакция!"
            }
        else:
            # Ставка уже списана
            result = {
                "win": False,
                "amount": -bet,
                "message": "🎮 <b>Импульс</b>\nУвы, импульс был нестабилен. Попробуй ещё раз!"
            }
        
        # Обновляем статистику
        db.cursor.execute("UPDATE users SET game1_count = game1_count + 1 WHERE user_id = ?", (user_id,))
        if db.get_user(user_id)['game1_count'] >= GAME_LIMIT:
            cooldown_time = datetime.now() + timedelta(seconds=GAME_LIMIT_COOLDOWN)
            db.cursor.execute(
                "UPDATE users SET game1_cooldown = ? WHERE user_id = ?",
                (cooldown_time.isoformat(), user_id)
            )
        db.conn.commit()
        
        return result
    
    @staticmethod
    async def three_signals_game(user_id: int, bet: int) -> Dict[str, Any]:
        """Игра 'Три сигнала'"""
        # Симуляция анализа
        await asyncio.sleep(random.uniform(1, 3))
        
        # Шанс победы ~60%
        win_chance = 0.6
        is_win = random.random() < win_chance
        
        if is_win:
            win_amount = int(bet * 1.5)  # Выигрыш 50% от ставки
            db.update_balance(user_id, win_amount, "game_win")
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
        
        # Обновляем статистику
        db.cursor.execute("UPDATE users SET game2_count = game2_count + 1 WHERE user_id = ?", (user_id,))
        if db.get_user(user_id)['game2_count'] >= GAME_LIMIT:
            cooldown_time = datetime.now() + timedelta(seconds=GAME_LIMIT_COOLDOWN)
            db.cursor.execute(
                "UPDATE users SET game2_cooldown = ? WHERE user_id = ?",
                (cooldown_time.isoformat(), user_id)
            )
        db.conn.commit()
        
        return result
    
    @staticmethod
    async def tactical_decision_game(user_id: int, bet: int) -> Dict[str, Any]:
        """Игра 'Тактическое решение'"""
        # Симуляция размышления
        await asyncio.sleep(random.uniform(1, 3))
        
        # Шанс победы ~60%
        win_chance = 0.6
        is_win = random.random() < win_chance
        
        if is_win:
            win_amount = int(bet * 1.7)  # Выигрыш 70% от ставки
            db.update_balance(user_id, win_amount, "game_win")
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
        
        # Обновляем статистику
        db.cursor.execute("UPDATE users SET game3_count = game3_count + 1 WHERE user_id = ?", (user_id,))
        if db.get_user(user_id)['game3_count'] >= GAME_LIMIT:
            cooldown_time = datetime.now() + timedelta(seconds=GAME_LIMIT_COOLDOWN)
            db.cursor.execute(
                "UPDATE users SET game3_cooldown = ? WHERE user_id = ?",
                (cooldown_time.isoformat(), user_id)
            )
        db.conn.commit()
        
        return result

# ========== КЛАВИАТУРЫ ==========
class Keyboards:
    """Класс для создания клавиатур"""
    
    @staticmethod
    def main_menu() -> InlineKeyboardMarkup:
        """Главное меню"""
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="🎮 Игры", callback_data="menu:games"),
            InlineKeyboardButton(text="💼 Работа", callback_data="menu:work")
        )
        builder.row(
            InlineKeyboardButton(text="🏪 Магазин", callback_data="menu:shop"),
            InlineKeyboardButton(text="👤 Профиль", callback_data="menu:profile")
        )
        builder.row(
            InlineKeyboardButton(text="🎁 Бонус", callback_data="menu:bonus")
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
            InlineKeyboardButton(text="💰 Управление балансами", callback_data="admin:balance")
        )
        builder.row(
            InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast"),
            InlineKeyboardButton(text="🏦 Казна", callback_data="admin:treasury")
        )
        builder.row(
            InlineKeyboardButton(text="🔙 Выйти", callback_data="admin:logout")
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
    def group_welcome_keyboard(user_id: int) -> InlineKeyboardMarkup:
        """Клавиатура приветствия в группе"""
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text="👤 Профиль", 
                callback_data=ButtonSecurity.create_callback_data("group_profile", user_id)
            )
        )
        return builder.as_markup()

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start", "startpuls"))
async def cmd_start(message: Message):
    """Обработчик команд /start и /startpuls"""
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Регистрация пользователя
    db.register_user(user_id, username)
    db.update_last_action(user_id)
    
    # Приветственное сообщение
    welcome_text = (
        "🎮 <b>Добро пожаловать в Pulse Bot!</b>\n\n"
        "Это развлекательный игровой бот, где всё зависит от твоей активности.\n"
        "Зарабатывай Pulse Coins, играй в игры, выполняй работу и улучшай свой профиль!\n\n"
        "Выбери действие:"
    )
    
    await message.answer(welcome_text, reply_markup=Keyboards.main_menu())

@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    """Обработчик команды /profile"""
    user_id = message.from_user.id
    
    # Проверяем регистрацию
    if not check_registration(user_id):
        await message.answer("Сначала зарегистрируйся через /start или /startpuls")
        return
    
    await show_profile(message)

async def show_profile(message: Message):
    """Показывает профиль пользователя"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await message.answer("Сначала зарегистрируйся через /start или /startpuls")
        return
    
    # Статус VIP
    is_vip = db.check_vip(user_id)
    vip_status = "✅ VIP" if is_vip else "❌ Обычный"
    vip_until = ""
    
    if is_vip and user['vip_until']:
        vip_date = datetime.fromisoformat(user['vip_until'])
        vip_until = f"\nVIP до: {vip_date.strftime('%d.%m.%Y %H:%M')}"
    
    # Время до бонуса
    bonus_time = "Доступен сейчас"
    if user['last_bonus']:
        last_bonus = datetime.fromisoformat(user['last_bonus'])
        next_bonus = last_bonus + timedelta(seconds=BONUS_COOLDOWN)
        if next_bonus > datetime.now():
            remaining = (next_bonus - datetime.now()).total_seconds()
            bonus_time = f"Через {CooldownManager.format_time(remaining)}"
    
    # Время до работы
    work_time = "Доступна сейчас"
    if user['last_work']:
        last_work = datetime.fromisoformat(user['last_work'])
        next_work = last_work + timedelta(seconds=WORK_COOLDOWN)
        if next_work > datetime.now():
            remaining = (next_work - datetime.now()).total_seconds()
            work_time = f"Через {CooldownManager.format_time(remaining)}"
    
    # Формируем текст профиля
    profile_text = (
        f"👤 <b>Профиль</b>\n\n"
        f"📛 Ник: {user['username']}\n"
        f"⭐ Статус: {vip_status}{vip_until}\n"
        f"💰 Баланс: {user['balance']} Pulse Coins\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"🎮 Игр сыграно: {user['games_played']}\n"
        f"💼 Работ выполнено: {user['work_count']}\n"
        f"💸 Потрачено: {user['total_spent']} Pulse\n\n"
        f"⏰ <b>Таймеры:</b>\n"
        f"🎁 Бонус: {bonus_time}\n"
        f"💼 Работа: {work_time}"
    )
    
    await message.answer(profile_text, reply_markup=Keyboards.main_menu())

@dp.callback_query(F.data.startswith("menu:"))
async def menu_handler(callback: CallbackQuery):
    """Обработчик меню"""
    user_id = callback.from_user.id
    
    # Проверяем регистрацию
    if not check_registration(user_id):
        await callback.answer("Сначала зарегистрируйся через /start или /startpuls", show_alert=True)
        return
    
    # Проверяем владельца кнопки (кроме кнопки профиля в группе)
    if not callback.data.startswith("menu:profile") and not await ButtonSecurity.check_owner(callback):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    action = callback.data.split(":")[1]
    
    # Проверка КД
    allowed, error = await CooldownManager.check_cooldown(callback.message)
    if not allowed:
        await callback.answer(error, show_alert=True)
        return
    
    db.update_last_action(user_id)
    
    if action == "main":
        await callback.message.edit_text(
            "🎮 <b>Главное меню</b>\n\nВыбери действие:",
            reply_markup=Keyboards.main_menu()
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
        await show_profile(callback.message)
        await callback.answer()
    
    elif action == "bonus":
        await bonus_command(callback.message)
        await callback.answer()

@dp.callback_query(F.data.startswith("game:"))
async def game_handler(callback: CallbackQuery):
    """Обработчик выбора игры"""
    # Проверяем владельца кнопки
    if not await ButtonSecurity.check_owner(callback):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Проверяем регистрацию
    if not check_registration(user_id):
        await callback.answer("Сначала зарегистрируйся через /start или /startpuls", show_alert=True)
        return
    
    prefix, owner_id, params = ButtonSecurity.parse_callback_data(callback.data)
    game_type = params.get("type")
    
    # Проверка КД
    allowed, error = await CooldownManager.check_cooldown(callback.message)
    if not allowed:
        await callback.answer(error, show_alert=True)
        return
    
    # Проверяем баланс
    user = db.get_user(user_id)
    if user['balance'] < MIN_BET:
        await callback.answer(
            f"Недостаточно Pulse Coins. Нужно {MIN_BET}, а у тебя {user['balance']}.", 
            show_alert=True
        )
        return
    
    # Определяем номер игры для проверки КД
    game_number = {"impulse": 1, "three_signals": 2, "tactical": 3}[game_type]
    
    # Проверяем кулдаун игры
    allowed_game, error_game = await Games.check_game_cooldown(user_id, game_number)
    if not allowed_game:
        await callback.answer(error_game, show_alert=True)
        return
    
    # Списываем минимальную ставку
    db.update_balance(user_id, -MIN_BET, "game_bet")
    db.update_last_action(user_id)
    
    # Обновляем общий счетчик игр
    db.cursor.execute(
        "UPDATE users SET games_played = games_played + 1 WHERE user_id = ?",
        (user_id,)
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
        result = await Games.impulse_game(user_id, MIN_BET)
    elif game_type == "three_signals":
        result = await Games.three_signals_game(user_id, MIN_BET)
    else:  # tactical
        result = await Games.tactical_decision_game(user_id, MIN_BET)
    
    # Получаем актуальный баланс
    user = db.get_user(user_id)
    
    # Отправляем результат
    result_text = (
        f"{result['message']}\n\n"
        f"💰 Ставка: {MIN_BET} Pulse Coins\n"
        f"📈 Результат: {'Выигрыш' if result['win'] else 'Проигрыш'} "
        f"({'+' if result['win'] else ''}{result['amount']})\n"
        f"💳 Баланс сейчас: {user['balance']}"
    )
    
    await callback.message.edit_text(
        result_text,
        reply_markup=Keyboards.games_menu(user_id)
    )
    await callback.answer()

async def work_command(message: Message):
    """Обработчик работы"""
    user_id = message.from_user.id
    
    # Проверяем регистрацию
    if not check_registration(user_id):
        await message.answer("Сначала зарегистрируйся через /start или /startpuls")
        return
    
    user = db.get_user(user_id)
    
    # Проверяем лимит работ
    if user['work_count'] >= WORK_LIMIT:
        await message.answer(
            f"Достигнут лимит работ ({WORK_LIMIT}).\n"
            f"Следующая работа через: {CooldownManager.format_time(WORK_LIMIT_COOLDOWN)}"
        )
        return
    
    # Проверяем кулдаун
    if user['last_work']:
        last_work = datetime.fromisoformat(user['last_work'])
        cooldown = WORK_COOLDOWN
        if db.check_vip(user_id):
            cooldown = int(cooldown / VIP_MULTIPLIER)
        
        next_work = last_work + timedelta(seconds=cooldown)
        if next_work > datetime.now():
            remaining = (next_work - datetime.now()).total_seconds()
            await message.answer(
                f"Работа пока недоступна.\n"
                f"Осталось: {CooldownManager.format_time(remaining)}"
            )
            return
    
    # Выполняем работу
    reward = random.randint(20, 100)
    db.update_balance(user_id, reward, "work")
    
    # Обновляем статистику
    db.cursor.execute(
        "UPDATE users SET work_count = work_count + 1, last_work = CURRENT_TIMESTAMP WHERE user_id = ?",
        (user_id,)
    )
    db.conn.commit()
    
    await message.answer(
        f"💼 <b>Работа выполнена!</b>\n\n"
        f"Ты заработал: {reward} Pulse Coins\n"
        f"Баланс: {user['balance'] + reward} Pulse\n\n"
        f"Осталось работ сегодня: {WORK_LIMIT - user['work_count'] - 1}",
        reply_markup=Keyboards.main_menu()
    )

async def bonus_command(message: Message):
    """Обработчик бонуса"""
    user_id = message.from_user.id
    
    # Проверяем регистрацию
    if not check_registration(user_id):
        await message.answer("Сначала зарегистрируйся через /start или /startpuls")
        return
    
    user = db.get_user(user_id)
    
    # Проверяем кулдаун
    if user['last_bonus']:
        last_bonus = datetime.fromisoformat(user['last_bonus'])
        next_bonus = last_bonus + timedelta(seconds=BONUS_COOLDOWN)
        
        if next_bonus > datetime.now():
            remaining = (next_bonus - datetime.now()).total_seconds()
            await message.answer(
                f"Бонус пока недоступен.\n"
                f"Осталось: {CooldownManager.format_time(remaining)}"
            )
            return
    
    # Выдаем бонус
    db.update_balance(user_id, BONUS_AMOUNT, "bonus")
    db.cursor.execute(
        "UPDATE users SET last_bonus = CURRENT_TIMESTAMP WHERE user_id = ?",
        (user_id,)
    )
    db.conn.commit()
    
    await message.answer(
        f"🎁 <b>Ежедневный бонус!</b>\n\n"
        f"Ты получил: {BONUS_AMOUNT} Pulse Coins\n"
        f"Баланс: {user['balance'] + BONUS_AMOUNT} Pulse",
        reply_markup=Keyboards.main_menu()
    )

@dp.callback_query(F.data.startswith("buy_vip:"))
async def buy_vip_handler(callback: CallbackQuery):
    """Обработчик покупки VIP"""
    # Проверяем владельца кнопки
    if not await ButtonSecurity.check_owner(callback):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Проверяем регистрацию
    if not check_registration(user_id):
        await callback.answer("Сначала зарегистрируйся через /start или /startpuls", show_alert=True)
        return
    
    prefix, owner_id, params = ButtonSecurity.parse_callback_data(callback.data)
    days = int(params.get("days"))
    
    # Проверка КД
    allowed, error = await CooldownManager.check_cooldown(callback.message)
    if not allowed:
        await callback.answer(error, show_alert=True)
        return
    
    price = VIP_PACKAGES[days]
    user = db.get_user(user_id)
    
    # Проверяем баланс
    if user['balance'] < price:
        await callback.answer(
            f"Недостаточно Pulse Coins. Нужно {price}, а у тебя {user['balance']}.", 
            show_alert=True
        )
        return
    
    # Покупаем VIP
    db.update_balance(user_id, -price, "vip_purchase")
    db.set_vip(user_id, days)
    db.update_last_action(user_id)
    
    months = days // 30
    
    await callback.message.edit_text(
        f"🎉 <b>Поздравляем с покупкой VIP!</b>\n\n"
        f"⭐ Теперь у тебя VIP статус на {months} месяцев\n"
        f"💎 Все кулдауны уменьшены в 1.5 раза\n"
        f"💰 Списано: {price} Pulse Coins\n"
        f"💳 Баланс: {user['balance'] - price} Pulse",
        reply_markup=Keyboards.main_menu()
    )
    await callback.answer()

# ========== АДМИН-ПАНЕЛЬ ==========
class AdminSession:
    """Управление админскими сессиями"""
    
    @staticmethod
    def check_session(user_id: int) -> bool:
        """Проверяет активность админской сессии"""
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
        """Создает админскую сессию"""
        expires_at = datetime.now() + timedelta(minutes=30)
        db.cursor.execute(
            "INSERT OR REPLACE INTO admin_sessions (user_id, expires_at) VALUES (?, ?)",
            (user_id, expires_at.isoformat())
        )
        db.conn.commit()
    
    @staticmethod
    def delete_session(user_id: int):
        """Удаляет админскую сессию"""
        db.cursor.execute("DELETE FROM admin_sessions WHERE user_id = ?", (user_id,))
        db.conn.commit()

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    """Обработчик админ-панели"""
    if message.chat.type != "private":
        await message.answer("Админ-панель доступна только в личных сообщениях.")
        return
    
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await message.answer("Доступ запрещен.")
        return
    
    if AdminSession.check_session(user_id):
        await message.answer(
            "🔐 <b>Админ-панель</b>\n\nВыберите действие:",
            reply_markup=Keyboards.admin_menu()
        )
    else:
        await message.answer("Введите пароль для доступа к админ-панели:")

@dp.message(F.text == ADMIN_PASSWORD)
async def admin_login(message: Message):
    """Вход в админ-панель"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    AdminSession.create_session(message.from_user.id)
    await message.answer(
        "✅ <b>Доступ разрешен</b>\n\n"
        "Сессия активна 30 минут.\n"
        "Выберите действие:",
        reply_markup=Keyboards.admin_menu(),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("admin:"))
async def admin_handler(callback: CallbackQuery):
    """Обработчик админ-меню"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS or not AdminSession.check_session(user_id):
        await callback.answer("Сессия истекла", show_alert=True)
        return
    
    action = callback.data.split(":")[1]
    
    if action == "stats":
        # Статистика
        total_users = len(db.get_all_users())
        treasury = db.get_treasury()
        
        top_balance = db.get_top_balance(5)
        top_spent = db.get_top_spent(5)
        
        balance_text = "\n".join([
            f"{i+1}. {user['username']}: {user['balance']} Pulse"
            for i, user in enumerate(top_balance)
        ])
        
        spent_text = "\n".join([
            f"{i+1}. {user['username']}: {user['total_spent']} Pulse"
            for i, user in enumerate(top_spent)
        ])
        
        stats_text = (
            f"📊 <b>Статистика бота</b>\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"🏦 Казна: {treasury} Pulse\n\n"
            f"🏆 <b>Топ по балансу:</b>\n{balance_text}\n\n"
            f"💸 <b>Топ по тратам:</b>\n{spent_text}"
        )
        
        await callback.message.edit_text(stats_text, reply_markup=Keyboards.admin_menu())
    
    elif action == "balance":
        await callback.message.edit_text(
            "💰 <b>Управление балансами</b>\n\n"
            "Отправьте в формате:\n"
            "<code>ID_пользователя СУММА</code>\n\n"
            "Пример: <code>123456789 100</code>\n"
            "Для снятия: <code>123456789 -50</code>",
            reply_markup=Keyboards.cancel_keyboard(user_id)
        )
    
    elif action == "broadcast":
        await callback.message.edit_text(
            "📢 <b>Рассылка</b>\n\n"
            "Отправьте сообщение для рассылки.\n"
            "Поддерживается текст, фото и видео.",
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
    
    elif action == "logout":
        AdminSession.delete_session(user_id)
        await callback.message.edit_text("✅ Сессия завершена")
    
    await callback.answer()

@dp.callback_query(F.data.startswith("withdraw_treasury:"))
async def withdraw_treasury_handler(callback: CallbackQuery):
    """Вывод казны"""
    if not await ButtonSecurity.check_owner(callback):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    user_id = callback.from_user.id
    treasury = db.get_treasury()
    
    if treasury > 0:
        # Записываем сумму на баланс бота (в реальности это нужно было бы хранить отдельно)
        db.cursor.execute(
            "INSERT INTO transactions (user_id, amount, type) VALUES (?, ?, ?)",
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

@dp.message(F.text.regexp(r'^\d+ [-+]?\d+$'))
async def admin_balance_change(message: Message):
    """Изменение баланса пользователя (админ)"""
    if not AdminSession.check_session(message.from_user.id) or message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        user_id_str, amount_str = message.text.split()
        target_user_id = int(user_id_str)
        amount = int(amount_str)
        
        if not db.user_exists(target_user_id):
            await message.answer("❌ Пользователь не найден")
            return
        
        db.update_balance(target_user_id, amount, "admin_change")
        user = db.get_user(target_user_id)
        
        await message.answer(
            f"✅ Баланс изменен\n\n"
            f"Пользователь: {user['username']}\n"
            f"Изменение: {'+' if amount > 0 else ''}{amount} Pulse\n"
            f"Новый баланс: {user['balance']} Pulse",
            reply_markup=Keyboards.admin_menu()
        )
    except:
        await message.answer("❌ Неверный формат")

@dp.message(F.photo | F.video | F.text)
async def admin_broadcast(message: Message):
    """Рассылка сообщений (админ)"""
    if not AdminSession.check_session(message.from_user.id) or message.from_user.id not in ADMIN_IDS:
        return
    
    # Проверяем, что это ответ на сообщение о рассылке
    if not message.reply_to_message:
        return
    
    # Безопасная проверка текста
    reply_text = message.reply_to_message.text or message.reply_to_message.caption or ""
    
    if "рассылка" not in reply_text.lower():
        return
    
    users = db.get_all_users()
    total = len(users)
    successful = 0
    
    progress_msg = await message.answer(f"📤 Рассылка начата... 0/{total}")
    
    for i, user_id in enumerate(users):
        try:
            if message.photo:
                await bot.send_photo(user_id, message.photo[-1].file_id, caption=message.caption)
            elif message.video:
                await bot.send_video(user_id, message.video.file_id, caption=message.caption)
            else:
                await bot.send_message(user_id, message.text)
            successful += 1
        except:
            pass
        
        if i % 10 == 0:
            await progress_msg.edit_text(f"📤 Рассылка... {i}/{total}")
    
    await progress_msg.edit_text(
        f"✅ Рассылка завершена\n\n"
        f"Отправлено: {successful}/{total} пользователей"
    )
    await message.answer("📊 Админ-панель", reply_markup=Keyboards.admin_menu())

@dp.callback_query(F.data.startswith("cancel:"))
async def cancel_handler(callback: CallbackQuery):
    """Обработчик отмены"""
    if not await ButtonSecurity.check_owner(callback):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🔐 <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=Keyboards.admin_menu()
    )
    await callback.answer()

# ========== ГРУППОВЫЕ КОМАНДЫ ==========
@dp.message(F.chat.type.in_(["group", "supergroup"]))
async def group_handler(message: Message):
    """Обработчик сообщений в группах"""
    if message.text and message.text.startswith("/"):
        command = message.text.split()[0].lower()
        
        if command in ["/games", "/work", "/shop", "/profile", "/bonus", "/admin", "/start", "/startpuls"]:
            # Проверяем, является ли пользователь админом Telegram в группе
            is_admin = False
            try:
                chat_member = await bot.get_chat_member(message.chat.id, message.from_user.id)
                is_admin = chat_member.status in ["administrator", "creator"]
            except:
                pass
            
            # Проверяем КД (для админов в группах КД не действует)
            allowed, error = await CooldownManager.check_cooldown(message, is_admin)
            if not allowed:
                await message.answer(error)
                return
            
            # Регистрируем пользователя
            db.register_user(message.from_user.id, message.from_user.username)
            db.update_last_action(message.from_user.id)
            
            # Сохраняем информацию о сообщении для проверки кнопок
            db.save_group_message(message.message_id, message.chat.id, message.from_user.id)
            
            # Отправляем сообщение в ЛС
            try:
                if command in ["/start", "/startpuls"]:
                    welcome_text = (
                        "🎮 <b>Добро пожаловать в Pulse Bot!</b>\n\n"
                        "Это развлекательный игровой бот, где всё зависит от твоей активности.\n"
                        "Зарабатывай Pulse Coins, играй в игры, выполняй работу и улучшай свой профиль!\n\n"
                        "Выбери действие:"
                    )
                    await bot.send_message(
                        message.from_user.id,
                        welcome_text,
                        reply_markup=Keyboards.main_menu()
                    )
                elif command == "/games":
                    await bot.send_message(
                        message.from_user.id,
                        "🎮 <b>Игры</b>\n\nВыбери игру:",
                        reply_markup=Keyboards.games_menu(message.from_user.id)
                    )
                elif command == "/work":
                    await work_command(types.Message(chat=types.Chat(id=message.from_user.id, type="private")))
                elif command == "/shop":
                    await bot.send_message(
                        message.from_user.id,
                        "🏪 <b>Магазин</b>\n\nДоступные товары:",
                        reply_markup=Keyboards.shop_menu(message.from_user.id)
                    )
                elif command == "/profile":
                    # В группе показываем только профиль
                    user = db.get_user(message.from_user.id)
                    is_vip = db.check_vip(message.from_user.id)
                    vip_status = "✅ VIP" if is_vip else "❌ Обычный"
                    
                    profile_text = (
                        f"👤 <b>Профиль</b>\n\n"
                        f"📛 Ник: {user['username']}\n"
                        f"⭐ Статус: {vip_status}\n"
                        f"💰 Баланс: {user['balance']} Pulse Coins\n"
                        f"🎮 Игр сыграно: {user['games_played']}\n"
                        f"💼 Работ выполнено: {user['work_count']}"
                    )
                    
                    await message.answer(
                        profile_text,
                        reply_markup=Keyboards.group_welcome_keyboard(message.from_user.id),
                        reply_to_message_id=message.message_id
                    )
                    return
                elif command == "/bonus":
                    await bonus_command(types.Message(chat=types.Chat(id=message.from_user.id, type="private")))
                elif command == "/admin":
                    await bot.send_message(message.from_user.id, "Админ-панель доступна только при прямом входе.")
                
                await message.answer(
                    "Эта функция работает в личных сообщениях. Я уже написал тебе в ЛС.",
                    reply_to_message_id=message.message_id
                )
            except:
                await message.answer(
                    "Не могу написать тебе в ЛС. Проверь настройки приватности и начни диалог с ботом.",
                    reply_to_message_id=message.message_id
                )
        elif command == "/help":
            # Приветственное сообщение в группе
            welcome_text = (
                "🎮 <b>Pulse Bot - Игровой бот</b>\n\n"
                "Доступные команды в группе:\n"
                "👤 /profile - Показать профиль\n"
                "🚀 /start или /startpuls - Начать работу с ботом\n\n"
                "Для полного функционала (игры, работа, магазин, бонус) перейдите в личные сообщения с ботом."
            )
            
            # Регистрируем пользователя при первом обращении
            db.register_user(message.from_user.id, message.from_user.username)
            db.save_group_message(message.message_id, message.chat.id, message.from_user.id)
            
            await message.answer(
                welcome_text,
                reply_markup=Keyboards.group_welcome_keyboard(message.from_user.id)
            )

@dp.callback_query(F.data.startswith("group_profile:"))
async def group_profile_handler(callback: CallbackQuery):
    """Обработчик кнопки профиля в группе"""
    # В группе проверяем владельца через базу данных
    if not db.check_group_message_owner(
        callback.message.message_id,
        callback.message.chat.id,
        callback.from_user.id
    ):
        await callback.answer("Эта кнопка не для тебя! ❌", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Проверяем регистрацию
    if not check_registration(user_id):
        await callback.answer("Сначала зарегистрируйся через /start или /startpuls", show_alert=True)
        return
    
    user = db.get_user(user_id)
    is_vip = db.check_vip(user_id)
    vip_status = "✅ VIP" if is_vip else "❌ Обычный"
    
    profile_text = (
        f"👤 <b>Профиль</b>\n\n"
        f"📛 Ник: {user['username']}\n"
        f"⭐ Статус: {vip_status}\n"
        f"💰 Баланс: {user['balance']} Pulse Coins\n"
        f"🎮 Игр сыграно: {user['games_played']}\n"
        f"💼 Работ выполнено: {user['work_count']}"
    )
    
    await callback.message.edit_text(
        profile_text,
        reply_markup=Keyboards.group_welcome_keyboard(user_id)
    )
    await callback.answer()

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция"""
    logger.info("Запуск бота Pulse Bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
