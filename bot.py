import asyncio
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, List
import random

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, ChatMemberUpdated, InlineKeyboardMarkup,
    InlineKeyboardButton, CallbackQuery
)
from aiogram.filters import Command, CommandStart, ChatMemberUpdatedFilter, JOIN_TRANSITION, LEAVE_TRANSITION
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ============ НАСТРОЙКИ БОТА ============
BOT_TOKEN = "8557190026:AAHAhHOxPQ4HlFHbGokpyTFoQ2R_a634rE4"  # Ваш токен
ADMIN_PASSWORD = "vanezypuls13579cod"
ADMIN_IDS = [6708209142]  # Ваш Telegram ID
DATABASE_NAME = "bot.db"
BOT_USERNAME = "PulsOfficialManager_bot"  # Username бота

# ============ ИНИЦИАЛИЗАЦИЯ БОТА ============
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ============ СОСТОЯНИЯ FSM ============
class AdminStates(StatesGroup):
    waiting_password = State()
    admin_panel_active = State()
    waiting_broadcast = State()
    waiting_mute = State()
    waiting_ban = State()
    waiting_kick = State()
    waiting_mod_rights = State()

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
    
    # Таблица ограничений (муты/баны)
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
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    
    # Создаем индексы для быстрого поиска
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
                       until: datetime, reason: str, moderator_id: int, moderator_name: str):
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO restrictions (user_id, chat_id, restriction_type, until, reason, moderator_id, moderator_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, chat_id, restriction_type, until, reason, moderator_id, moderator_name))
        conn.commit()
        conn.close()
    
    @staticmethod
    def remove_restriction(user_id: int, chat_id: int, restriction_type: str = None):
        conn = Database.get_connection()
        cursor = conn.cursor()
        if restriction_type:
            cursor.execute('''
                DELETE FROM restrictions 
                WHERE user_id = ? AND chat_id = ? AND restriction_type = ?
            ''', (user_id, chat_id, restriction_type))
        else:
            cursor.execute('''
                DELETE FROM restrictions 
                WHERE user_id = ? AND chat_id = ?
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
                WHERE user_id = ? AND chat_id = ? AND restriction_type = ?
            ''', (user_id, chat_id, restriction_type))
        else:
            cursor.execute('''
                SELECT * FROM restrictions 
                WHERE user_id = ? AND chat_id = ?
            ''', (user_id, chat_id))
        restriction = cursor.fetchone()
        conn.close()
        return restriction
    
    @staticmethod
    def get_active_restrictions():
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM restrictions WHERE until > ?', (datetime.now().isoformat(),))
        restrictions = cursor.fetchall()
        conn.close()
        return restrictions
    
    @staticmethod
    def add_moderator_right(user_id: int, chat_id: int, rights: dict, granted_by: int):
        conn = Database.get_connection()
        cursor = conn.cursor()
        
        # Удаляем старые права
        cursor.execute('DELETE FROM moderator_rights WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
        
        # Добавляем новые права
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
        """Проверяет блокировку админ-панели для пользователя"""
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
        """Обновляет данные блокировки админ-панели"""
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

# Инициализация базы данных
init_database()

# ============ УТИЛИТЫ ============
class Utils:
    # Случайные эмодзи для сообщений
    EMOJIS = ["🎉", "✨", "🌟", "🎊", "🎈", "💫", "🔥", "💥", "⭐", "😊", "🤗", "👋", "💖", "🎁", "🏆"]
    
    # Приветственные сообщения (БЕЗ HTML-тегов)
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
    
    # Прощальные сообщения (БЕЗ HTML-тегов)
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
    def get_random_emoji():
        return random.choice(Utils.EMOJIS)
    
    @staticmethod
    def get_random_greeting():
        return random.choice(Utils.GREETINGS)
    
    @staticmethod
    def get_random_farewell():
        return random.choice(Utils.FAREWELLS)
    
    @staticmethod
    def parse_time(time_str: str) -> Optional[timedelta]:
        """Парсит строку времени в timedelta"""
        if not time_str:
            return None
            
        time_str = time_str.lower().strip()
        
        # Если это просто число - считаем как минуты
        if time_str.isdigit():
            return timedelta(minutes=int(time_str))
        
        multipliers = {
            's': 1, 'сек': 1, 'с': 1, 'секунд': 1, 'секунды': 1,
            'm': 60, 'мин': 60, 'м': 60, 'минут': 60, 'минуты': 60,
            'h': 3600, 'час': 3600, 'ч': 3600, 'часов': 3600,
            'd': 86400, 'дней': 86400, 'д': 86400, 'день': 86400, 'дня': 86400
        }
        
        try:
            # Пробуем найти суффикс
            for suffix, multiplier in multipliers.items():
                if time_str.endswith(suffix):
                    num_str = time_str[:-len(suffix)].strip()
                    if num_str.isdigit():
                        num = int(num_str)
                        return timedelta(seconds=num * multiplier)
            
            # Пробуем парсить как число
            return timedelta(seconds=int(time_str))
        except:
            return None
    
    @staticmethod
    def format_time(delta: timedelta) -> str:
        """Форматирует timedelta в читаемую строку"""
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

# ============ КЛАВИАТУРЫ ============
class Keyboards:
    @staticmethod
    def get_main_keyboard(user_id: int):
        """Главное меню - кнопка Админ-панель только для админов"""
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="📜 Правила бота", callback_data="rules")
        
        # Проверяем, является ли пользователь админом
        if user_id in ADMIN_IDS:
            keyboard.button(text="⚙️ Админ-панель", callback_data="admin_panel")
        
        keyboard.button(text="🎮 Играть", callback_data="play_game")
        keyboard.button(text="💰 Баланс", callback_data="balance")
        keyboard.button(text="🏆 Топ игроков", callback_data="top_players")
        keyboard.button(text="➕ Добавить в группу", 
                       url=f"https://t.me/{BOT_USERNAME}?startgroup=true")
        
        if user_id in ADMIN_IDS:
            keyboard.adjust(2, 2, 1, 1)
        else:
            keyboard.adjust(1, 2, 1, 1)
        
        return keyboard.as_markup()
    
    @staticmethod
    def get_admin_keyboard():
        """Клавиатура админ-панели"""
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="📊 Статистика", callback_data="admin_stats")
        keyboard.button(text="🔧 Модерация", callback_data="admin_moderation")
        keyboard.button(text="📣 Рассылка", callback_data="admin_broadcast")
        keyboard.button(text="👮 Управление модераторами", callback_data="admin_moderators")
        keyboard.button(text="🔄 Сбросить ограничения", callback_data="admin_reset_restrictions")
        keyboard.button(text="🔙 Выйти из админ-панели", callback_data="admin_exit")
        keyboard.adjust(2, 2, 1, 1)
        return keyboard.as_markup()
    
    @staticmethod
    def get_moderation_keyboard():
        """Клавиатура модерации"""
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🔇 Выдать мут", callback_data="admin_mute")
        keyboard.button(text="🔨 Выдать бан", callback_data="admin_ban")
        keyboard.button(text="👢 Кикнуть", callback_data="admin_kick")
        keyboard.button(text="➕ Дать права модератора", callback_data="admin_add_mod")
        keyboard.button(text="📋 Активные ограничения", callback_data="admin_active_restrictions")
        keyboard.button(text="🔙 Назад в админ-панель", callback_data="admin_panel")
        keyboard.adjust(2, 2, 1, 1)
        return keyboard.as_markup()
    
    @staticmethod
    def get_back_to_admin_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🔙 Назад в админ-панель", callback_data="admin_panel")
        return keyboard.as_markup()
    
    @staticmethod
    def get_cancel_keyboard():
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="❌ Отмена", callback_data="admin_cancel")
        return keyboard.as_markup()
    
    @staticmethod
    def get_back_to_main_keyboard(user_id: int):
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🔙 Назад в меню", callback_data="main_menu")
        return keyboard.as_markup()

# ============ ФУНКЦИИ ПРОВЕРКИ ============
async def check_admin_lock(user_id: int) -> tuple:
    """Проверяет, заблокирован ли доступ к админ-панели"""
    failed_attempts, lock_until, last_attempt = Database.check_admin_lock(user_id)
    
    if failed_attempts >= 2 and lock_until:
        if datetime.now() < lock_until:
            time_left = lock_until - datetime.now()
            minutes = time_left.seconds // 60
            seconds = time_left.seconds % 60
            return False, f"⛔ Доступ заблокирован! Попробуйте через {minutes} минут {seconds} секунд."
        else:
            Database.update_admin_lock(user_id, 0, None)
            return True, None
    elif failed_attempts >= 2:
        Database.update_admin_lock(user_id, 0, None)
        return True, None
    
    return True, None

# ============ ОСНОВНЫЕ КОМАНДЫ ============

@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработка команды /start"""
    user_id = message.from_user.id
    username = message.from_user.username or "Нет username"
    full_name = message.from_user.full_name
    
    # Проверяем, является ли пользователь админом
    is_admin = user_id in ADMIN_IDS
    Database.create_user(user_id, username, full_name, is_admin)
    
    welcome_text = (
        f"🎉 Привет! Я — Puls Bot! ✨\n\n"
        f"Я универсальный бот для модерации, игр и мини-экономики!\n"
        f"Спасибо, что добавили меня! Для начала прочитайте правила бота, "
        f"нажав кнопку «Правила бота».\n\n"
        f"{Utils.get_random_emoji()} Ваши данные:\n"
        f"• ID: {user_id}\n"
        f"• Username: @{username if username else 'Нет'}\n"
        f"• Имя: {full_name}"
    )
    
    await message.answer(welcome_text, reply_markup=Keyboards.get_main_keyboard(user_id))

# ============ АДМИН-ПАНЕЛЬ ============

@router.callback_query(F.data == "admin_panel")
async def callback_admin_panel(callback: CallbackQuery, state: FSMContext):
    """Обработка нажатия на кнопку Админ-панель"""
    user_id = callback.from_user.id
    
    # Проверяем, является ли пользователь админом
    if user_id not in ADMIN_IDS:
        await callback.answer("❌ У вас нет доступа к админ-панели!", show_alert=True)
        return
    
    # Проверяем, не в группе ли это
    if callback.message.chat.type != "private":
        await callback.answer("⚠️ Админ-панель доступна только в личных сообщениях с ботом!", show_alert=True)
        await callback.message.answer(
            f"🔒 Админ-панель доступна только в личных сообщениях.\n"
            f"Перейдите в ЛС с ботом: @{BOT_USERNAME}"
        )
        return
    
    # Проверяем блокировку
    is_allowed, lock_message = await check_admin_lock(user_id)
    
    if not is_allowed:
        await callback.answer(lock_message, show_alert=True)
        await callback.message.edit_text(
            f"🔐 Админ-панель\n\n{lock_message}\n\n"
            f"Используйте другие функции бота:",
            reply_markup=Keyboards.get_main_keyboard(user_id)
        )
        return
    
    # Запрашиваем пароль
    await state.set_state(AdminStates.waiting_password)
    
    try:
        await callback.message.edit_text(
            "🔐 <b>Админ-панель</b>\n\n"
            "Для доступа введите пароль:\n"
            "<i>У вас есть 2 попытки, после чего блокировка на 5 минут.</i>",
            reply_markup=Keyboards.get_cancel_keyboard()
        )
    except:
        await callback.message.answer(
            "🔐 <b>Админ-панель</b>\n\n"
            "Для доступа введите пароль:\n"
            "<i>У вас есть 2 попытки, после чего блокировка на 5 минут.</i>",
            reply_markup=Keyboards.get_cancel_keyboard()
        )
    
    await callback.answer()

@router.callback_query(F.data == "admin_cancel")
async def callback_admin_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена действия в админ-панели"""
    await state.clear()
    user_id = callback.from_user.id
    
    try:
        await callback.message.edit_text(
            "❌ Действие отменено.",
            reply_markup=Keyboards.get_main_keyboard(user_id)
        )
    except:
        await callback.message.answer(
            "❌ Действие отменено.",
            reply_markup=Keyboards.get_main_keyboard(user_id)
        )
    
    await callback.answer()

@router.message(AdminStates.waiting_password)
async def process_admin_password(message: Message, state: FSMContext):
    """Проверка пароля админ-панели"""
    user_id = message.from_user.id
    
    # Проверяем, является ли пользователь админом
    if user_id not in ADMIN_IDS:
        await state.clear()
        await message.answer("❌ У вас нет доступа к админ-панели!")
        return
    
    password = message.text.strip()
    failed_attempts, lock_until, last_attempt = Database.check_admin_lock(user_id)
    
    # Проверяем блокировку
    if failed_attempts >= 2 and lock_until:
        if datetime.now() < lock_until:
            time_left = lock_until - datetime.now()
            minutes = time_left.seconds // 60
            await message.answer(
                f"⛔ Доступ заблокирован! Попробуйте через {minutes} минут."
            )
            await state.clear()
            return
    
    if password == ADMIN_PASSWORD:
        # Пароль верный - сбрасываем счетчик попыток
        Database.update_admin_lock(user_id, 0, None)
        
        # Устанавливаем активную сессию
        await state.set_state(AdminStates.admin_panel_active)
        
        # Удаляем сообщение с паролем
        try:
            await message.delete()
        except:
            pass
        
        await message.answer(
            "✅ <b>Пароль верный!</b>\n\n"
            "Добро пожаловать в админ-панель!",
            reply_markup=Keyboards.get_admin_keyboard()
        )
    else:
        # Неверный пароль
        failed_attempts += 1
        
        if failed_attempts >= 2:
            # Блокируем на 5 минут
            lock_until = datetime.now() + timedelta(minutes=5)
            Database.update_admin_lock(user_id, failed_attempts, lock_until)
            
            time_left = lock_until - datetime.now()
            minutes = time_left.seconds // 60
            
            await message.answer(
                f"⛔ <b>Слишком много неверных попыток!</b>\n\n"
                f"Доступ к админ-панели заблокирован на {minutes} минут.\n\n"
                f"Возвращаемся в главное меню...",
                reply_markup=Keyboards.get_main_keyboard(user_id)
            )
        else:
            Database.update_admin_lock(user_id, failed_attempts, None)
            attempts_left = 2 - failed_attempts
            
            await message.answer(
                f"❌ <b>Неверный пароль!</b>\n\n"
                f"Осталось попыток: {attempts_left}\n"
                f"Введите пароль еще раз:"
            )
    
    await state.clear()

# ============ АДМИНСКИЕ ДЕЙСТВИЯ ============

@router.callback_query(F.data.startswith("admin_"))
async def callback_admin_actions(callback: CallbackQuery, state: FSMContext):
    """Обработка всех админских действий"""
    user_id = callback.from_user.id
    
    # Проверяем, является ли пользователь админом
    if user_id not in ADMIN_IDS:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    # Проверяем активную сессию
    current_state = await state.get_state()
    if current_state != AdminStates.admin_panel_active.state:
        await callback.answer("⚠️ Сессия истекла! Войдите заново.", show_alert=True)
        
        try:
            await callback.message.edit_text(
                "🔐 Сессия админ-панели истекла.\n\n"
                "Нажмите «Админ-панель» для повторного входа.",
                reply_markup=Keyboards.get_main_keyboard(user_id)
            )
        except:
            await callback.message.answer(
                "🔐 Сессия админ-панели истекла.\n\n"
                "Нажмите «Админ-панель» для повторного входа.",
                reply_markup=Keyboards.get_main_keyboard(user_id)
            )
        
        return
    
    data = callback.data
    
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
        
        cursor.execute('SELECT COUNT(*) FROM restrictions WHERE until > ?', (datetime.now().isoformat(),))
        active_restrictions = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM moderator_rights')
        total_moderators = cursor.fetchone()[0]
        
        conn.close()
        
        stats_text = (
            f"📊 <b>Статистика бота</b>\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"🎮 Всего Puls Coins: {total_coins}\n"
            f"💵 Всего долларов: ${total_dollars}\n"
            f"🔇 Активных ограничений: {active_restrictions}\n"
            f"👮 Всего модераторов: {total_moderators}\n"
            f"👑 Админов: {len(ADMIN_IDS)}"
        )
        
        try:
            await callback.message.edit_text(
                stats_text,
                reply_markup=Keyboards.get_admin_keyboard()
            )
        except:
            await callback.message.answer(
                stats_text,
                reply_markup=Keyboards.get_admin_keyboard()
            )
    
    elif data == "admin_moderation":
        # Панель модерации
        try:
            await callback.message.edit_text(
                "🔧 <b>Панель модерации</b>\n\n"
                "Выберите действие:",
                reply_markup=Keyboards.get_moderation_keyboard()
            )
        except:
            await callback.message.answer(
                "🔧 <b>Панель модерации</b>\n\n"
                "Выберите действие:",
                reply_markup=Keyboards.get_moderation_keyboard()
            )
    
    elif data == "admin_broadcast":
        # Рассылка
        await state.set_state(AdminStates.waiting_broadcast)
        
        try:
            await callback.message.edit_text(
                "📣 <b>Рассылка сообщений</b>\n\n"
                "Введите сообщение для рассылки всем пользователям бота:\n"
                "<i>Можно использовать HTML-разметку</i>",
                reply_markup=Keyboards.get_cancel_keyboard()
            )
        except:
            await callback.message.answer(
                "📣 <b>Рассылка сообщений</b>\n\n"
                "Введите сообщение для рассылки всем пользователям бота:\n"
                "<i>Можно использовать HTML-разметку</i>",
                reply_markup=Keyboards.get_cancel_keyboard()
            )
    
    elif data == "admin_moderators":
        # Управление модераторами
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT m.user_id, u.username, u.full_name, m.can_mute, m.can_ban, m.can_kick 
            FROM moderator_rights m
            LEFT JOIN users u ON m.user_id = u.user_id
        ''')
        moderators = cursor.fetchall()
        conn.close()
        
        if not moderators:
            mod_text = "👮 <b>Список модераторов пуст</b>"
        else:
            mod_text = "👮 <b>Список модераторов:</b>\n\n"
            for mod in moderators:
                user_id, username, full_name, can_mute, can_ban, can_kick = mod
                name = f"@{username}" if username else full_name
                rights = []
                if can_mute: rights.append("мут")
                if can_ban: rights.append("бан")
                if can_kick: rights.append("кик")
                rights_str = ", ".join(rights) if rights else "нет прав"
                mod_text += f"• {name} (ID: {user_id}): {rights_str}\n"
        
        try:
            await callback.message.edit_text(
                mod_text,
                reply_markup=Keyboards.get_back_to_admin_keyboard()
            )
        except:
            await callback.message.answer(
                mod_text,
                reply_markup=Keyboards.get_back_to_admin_keyboard()
            )
    
    elif data == "admin_active_restrictions":
        # Активные ограничения
        restrictions = Database.get_active_restrictions()
        
        if not restrictions:
            restr_text = "🔇 <b>Активных ограничений нет</b>"
        else:
            restr_text = f"🔇 <b>Активные ограничения ({len(restrictions)}):</b>\n\n"
            for restr in restrictions:
                user_id, chat_id, rtype, until, reason, mod_id, mod_name, created = restr
                until_time = datetime.fromisoformat(until)
                time_left = until_time - datetime.now()
                
                if time_left.total_seconds() > 0:
                    if time_left.total_seconds() < 3600:
                        time_str = f"{int(time_left.total_seconds() // 60)} мин"
                    elif time_left.total_seconds() < 86400:
                        time_str = f"{int(time_left.total_seconds() // 3600)} час"
                    else:
                        time_str = f"{int(time_left.total_seconds() // 86400)} дн"
                    
                    restr_text += f"• {rtype.upper()} | ID: {user_id} | Осталось: {time_str}"
                    if reason and reason != "Не указана":
                        restr_text += f" | Причина: {reason[:20]}..."
                    restr_text += "\n"
        
        try:
            await callback.message.edit_text(
                restr_text,
                reply_markup=Keyboards.get_back_to_admin_keyboard()
            )
        except:
            await callback.message.answer(
                restr_text,
                reply_markup=Keyboards.get_back_to_admin_keyboard()
            )
    
    elif data == "admin_reset_restrictions":
        # Сброс ограничений
        conn = Database.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM restrictions')
        conn.commit()
        conn.close()
        
        try:
            await callback.message.edit_text(
                "✅ <b>Все ограничения сброшены!</b>\n\n"
                "Все муты и баны удалены из базы данных.",
                reply_markup=Keyboards.get_admin_keyboard()
            )
        except:
            await callback.message.answer(
                "✅ <b>Все ограничения сброшены!</b>\n\n"
                "Все муты и баны удалены из базы данных.",
                reply_markup=Keyboards.get_admin_keyboard()
            )
    
    elif data == "admin_mute":
        # Выдать мут
        await state.set_state(AdminStates.waiting_mute)
        
        try:
            await callback.message.edit_text(
                "🔇 <b>Выдача мута</b>\n\n"
                "Введите данные в формате:\n"
                "<code>ID_пользователя время причина</code>\n\n"
                "Примеры:\n"
                "<code>123456789 30m спам</code>\n"
                "<code>123456789 2h флуд</code>\n"
                "<code>123456789 1d оскорбления</code>",
                reply_markup=Keyboards.get_cancel_keyboard()
            )
        except:
            await callback.message.answer(
                "🔇 <b>Выдача мута</b>\n\n"
                "Введите данные в формате:\n"
                "<code>ID_пользователя время причина</code>\n\n"
                "Примеры:\n"
                "<code>123456789 30m спам</code>\n"
                "<code>123456789 2h флуд</code>\n"
                "<code>123456789 1d оскорбления</code>",
                reply_markup=Keyboards.get_cancel_keyboard()
            )
    
    elif data == "admin_ban":
        # Выдать бан
        await state.set_state(AdminStates.waiting_ban)
        
        try:
            await callback.message.edit_text(
                "🔨 <b>Выдача бана</b>\n\n"
                "Введите данные в формате:\n"
                "<code>ID_пользователя время причина</code>\n\n"
                "Примеры:\n"
                "<code>123456789 7d нарушение правил</code>\n"
                "<code>123456789 30d спам</code>",
                reply_markup=Keyboards.get_cancel_keyboard()
            )
        except:
            await callback.message.answer(
                "🔨 <b>Выдача бана</b>\n\n"
                "Введите данные в формате:\n"
                "<code>ID_пользователя время причина</code>\n\n"
                "Примеры:\n"
                "<code>123456789 7d нарушение правил</code>\n"
                "<code>123456789 30d спам</code>",
                reply_markup=Keyboards.get_cancel_keyboard()
            )
    
    elif data == "admin_kick":
        # Кикнуть
        await state.set_state(AdminStates.waiting_kick)
        
        try:
            await callback.message.edit_text(
                "👢 <b>Кик пользователя</b>\n\n"
                "Введите данные в формате:\n"
                "<code>ID_пользователя причина</code>\n\n"
                "Пример:\n"
                "<code>123456789 нарушение правил</code>",
                reply_markup=Keyboards.get_cancel_keyboard()
            )
        except:
            await callback.message.answer(
                "👢 <b>Кик пользователя</b>\n\n"
                "Введите данные в формате:\n"
                "<code>ID_пользователя причина</code>\n\n"
                "Пример:\n"
                "<code>123456789 нарушение правил</code>",
                reply_markup=Keyboards.get_cancel_keyboard()
            )
    
    elif data == "admin_add_mod":
        # Дать права модератора
        await state.set_state(AdminStates.waiting_mod_rights)
        
        try:
            await callback.message.edit_text(
                "➕ <b>Выдача прав модератора</b>\n\n"
                "Введите данные в формате:\n"
                "<code>ID_пользователя права</code>\n\n"
                "Права указываются через + (например: +м+б)\n"
                "• +м или +mute - право на мут\n"
                "• +б или +ban - право на бан\n"
                "• +к или +kick - право на кик\n\n"
                "Примеры:\n"
                "<code>123456789 +м+б</code>\n"
                "<code>123456789 +м+б+к</code>",
                reply_markup=Keyboards.get_cancel_keyboard()
            )
        except:
            await callback.message.answer(
                "➕ <b>Выдача прав модератора</b>\n\n"
                "Введите данные в формате:\n"
                "<code>ID_пользователя права</code>\n\n"
                "Права указываются через + (например: +м+б)\n"
                "• +м или +mute - право на мут\n"
                "• +б или +ban - право на бан\n"
                "• +к или +kick - право на кик\n\n"
                "Примеры:\n"
                "<code>123456789 +м+б</code>\n"
                "<code>123456789 +м+б+к</code>",
                reply_markup=Keyboards.get_cancel_keyboard()
            )
    
    elif data == "admin_exit":
        # Выход из админ-панели
        await state.clear()
        
        try:
            await callback.message.edit_text(
                "✅ Вы вышли из админ-панели.",
                reply_markup=Keyboards.get_main_keyboard(user_id)
            )
        except:
            await callback.message.answer(
                "✅ Вы вышли из админ-панели.",
                reply_markup=Keyboards.get_main_keyboard(user_id)
            )
    
    await callback.answer()

# ============ ОБРАБОТКА АДМИНСКИХ СООБЩЕНИЙ ============

@router.message(AdminStates.waiting_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    """Обработка рассылки"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await state.clear()
        return
    
    broadcast_text = message.text
    users = Database.get_all_users()
    
    # Удаляем сообщение с текстом рассылки
    try:
        await message.delete()
    except:
        pass
    
    sent_count = 0
    failed_count = 0
    
    # Отправляем предупреждение
    warning_msg = await message.answer("📣 Начинаю рассылку...")
    
    for user in users:
        try:
            await bot.send_message(user, broadcast_text, parse_mode=ParseMode.HTML)
            sent_count += 1
            await asyncio.sleep(0.05)  # Защита от флуда
        except Exception as e:
            logger.error(f"Ошибка при рассылке пользователю {user}: {e}")
            failed_count += 1
    
    # Удаляем предупреждение
    try:
        await warning_msg.delete()
    except:
        pass
    
    await message.answer(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📊 Статистика:\n"
        f"• Отправлено: {sent_count}\n"
        f"• Не отправлено: {failed_count}\n\n"
        f"Итого охвачено пользователей: {sent_count}",
        reply_markup=Keyboards.get_admin_keyboard()
    )
    
    await state.set_state(AdminStates.admin_panel_active)

@router.message(AdminStates.waiting_mute)
async def process_mute_command(message: Message, state: FSMContext):
    """Обработка команды мута"""
    await process_restriction_command(message, state, "mute")

@router.message(AdminStates.waiting_ban)
async def process_ban_command(message: Message, state: FSMContext):
    """Обработка команды бана"""
    await process_restriction_command(message, state, "ban")

@router.message(AdminStates.waiting_kick)
async def process_kick_command(message: Message, state: FSMContext):
    """Обработка команды кика"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await state.clear()
        return
    
    text = message.text.strip()
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2:
        await message.answer(
            "❌ Неверный формат!\n"
            "Используйте: <code>ID_пользователя причина</code>\n\n"
            "Пример: <code>123456789 нарушение правил</code>",
            reply_markup=Keyboards.get_cancel_keyboard()
        )
        return
    
    target_id_str, reason = parts
    
    if not target_id_str.isdigit():
        await message.answer(
            "❌ Неверный ID пользователя!",
            reply_markup=Keyboards.get_cancel_keyboard()
        )
        return
    
    target_id = int(target_id_str)
    moderator_name = message.from_user.full_name
    
    # Удаляем сообщение с командой
    try:
        await message.delete()
    except:
        pass
    
    # Сохраняем в БД (для кика можно сохранить на 1 минуту или как пометку)
    until_date = datetime.now() + timedelta(minutes=1)
    Database.add_restriction(
        target_id, 0, 'kick',
        until_date, reason, user_id, moderator_name
    )
    
    await message.answer(
        f"✅ <b>Пользователь кикнут!</b>\n\n"
        f"👤 Пользователь ID: <code>{target_id}</code>\n"
        f"📝 Причина: {reason}\n"
        f"👮 Модератор: {moderator_name}",
        reply_markup=Keyboards.get_admin_keyboard()
    )
    
    await state.set_state(AdminStates.admin_panel_active)

@router.message(AdminStates.waiting_mod_rights)
async def process_mod_rights_command(message: Message, state: FSMContext):
    """Обработка выдачи прав модератора"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await state.clear()
        return
    
    text = message.text.strip()
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2:
        await message.answer(
            "❌ Неверный формат!\n"
            "Используйте: <code>ID_пользователя права</code>\n\n"
            "Пример: <code>123456789 +м+б</code>",
            reply_markup=Keyboards.get_cancel_keyboard()
        )
        return
    
    target_id_str, rights_str = parts
    
    if not target_id_str.isdigit():
        await message.answer(
            "❌ Неверный ID пользователя!",
            reply_markup=Keyboards.get_cancel_keyboard()
        )
        return
    
    target_id = int(target_id_str)
    rights_str = rights_str.lower()
    
    # Парсим права
    rights = {
        'mute': '+м' in rights_str or '+mute' in rights_str or 'мут' in rights_str,
        'ban': '+б' in rights_str or '+ban' in rights_str or 'бан' in rights_str,
        'kick': '+к' in rights_str or '+kick' in rights_str or 'кик' in rights_str
    }
    
    # Если нет ни одного права
    if not any(rights.values()):
        await message.answer(
            "❌ Не указаны права!\n"
            "Используйте: +м, +б, +к или их комбинации",
            reply_markup=Keyboards.get_cancel_keyboard()
        )
        return
    
    # Удаляем сообщение с командой
    try:
        await message.delete()
    except:
        pass
    
    # Сохраняем права в БД (chat_id=0 для глобальных прав)
    Database.add_moderator_right(target_id, 0, rights, user_id)
    
    # Получаем пользователя
    user_data = Database.get_user(target_id)
    if user_data:
        target_name = user_data[2]  # full_name
        Database.update_user(target_id, is_admin=0)  # Снимаем админский статус если был
    else:
        target_name = f"ID: {target_id}"
    
    rights_list = []
    if rights['mute']: rights_list.append("мут")
    if rights['ban']: rights_list.append("бан")
    if rights['kick']: rights_list.append("кик")
    
    await message.answer(
        f"✅ <b>Права модератора выданы!</b>\n\n"
        f"👤 Пользователь: {target_name}\n"
        f"🆔 ID: <code>{target_id}</code>\n"
        f"🔧 Права: {', '.join(rights_list)}\n"
        f"👮 Выдал: {message.from_user.full_name}",
        reply_markup=Keyboards.get_admin_keyboard()
    )
    
    await state.set_state(AdminStates.admin_panel_active)

async def process_restriction_command(message: Message, state: FSMContext, restriction_type: str):
    """Общая функция обработки команд ограничений"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await state.clear()
        return
    
    text = message.text.strip()
    parts = text.split(maxsplit=2)
    
    if len(parts) < 3:
        await message.answer(
            f"❌ Неверный формат!\n"
            f"Используйте: <code>ID_пользователя время причина</code>\n\n"
            f"Пример: <code>123456789 30m спам</code>",
            reply_markup=Keyboards.get_cancel_keyboard()
        )
        return
    
    target_id_str, time_str, reason = parts
    
    if not target_id_str.isdigit():
        await message.answer(
            "❌ Неверный ID пользователя!",
            reply_markup=Keyboards.get_cancel_keyboard()
        )
        return
    
    target_id = int(target_id_str)
    duration = Utils.parse_time(time_str)
    
    if not duration:
        await message.answer(
            "❌ Неверный формат времени!\n"
            "Примеры: 30m, 2h, 1d, 60 (минут)",
            reply_markup=Keyboards.get_cancel_keyboard()
        )
        return
    
    until_date = datetime.now() + duration
    moderator_name = message.from_user.full_name
    
    # Удаляем сообщение с командой
    try:
        await message.delete()
    except:
        pass
    
    # Сохраняем в БД (chat_id=0 для админ-панели)
    Database.add_restriction(
        target_id, 0, restriction_type,
        until_date, reason, user_id, moderator_name
    )
    
    type_name = "мут" if restriction_type == "mute" else "бан"
    
    await message.answer(
        f"✅ <b>Пользователь получил {type_name}!</b>\n\n"
        f"👤 Пользователь ID: <code>{target_id}</code>\n"
        f"⏰ Длительность: {Utils.format_time(duration)}\n"
        f"📝 Причина: {reason}\n"
        f"👮 Модератор: {moderator_name}\n\n"
        f"<i>Ограничение будет снято автоматически.</i>",
        reply_markup=Keyboards.get_admin_keyboard()
    )
    
    await state.set_state(AdminStates.admin_panel_active)

# ============ ОБРАБОТКА КОМАНД МОДЕРАЦИИ В ЧАТАХ ============

@router.message(F.chat.type.in_(["group", "supergroup"]))
async def handle_chat_commands(message: Message):
    """Обработка команд модерации в чатах"""
    if not message.text:
        return
    
    text = message.text.strip().lower()
    words = text.split()
    
    if len(words) < 2:
        return
    
    # Проверяем команду модерации
    command = words[0].lstrip('/')
    
    # Маппинг команд
    command_map = {
        'm': 'mute', 'мут': 'mute', 'mute': 'mute',
        'б': 'ban', 'бан': 'ban', 'ban': 'ban',
        'к': 'kick', 'кик': 'kick', 'kick': 'kick',
        '+м': 'add_mute', '+мут': 'add_mute', '+mute': 'add_mute',
        '+б': 'add_ban', '+бан': 'add_ban', '+ban': 'add_ban',
        '+к': 'add_kick', '+кик': 'add_kick', '+kick': 'add_kick'
    }
    
    if command not in command_map:
        return
    
    action = command_map[command]
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права
    if action.startswith('add_'):
        # Только админы могут давать права
        if user_id not in ADMIN_IDS:
            return
        right_type = action.split('_')[1]
        await handle_add_mod_rights(message, words, right_type, chat_id)
    else:
        # Проверяем права модератора или админа
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
            await message.reply("❌ У вас нет прав для этого действия!")
            return
        
        await handle_chat_punishment(message, words, action, chat_id)

async def handle_add_mod_rights(message: Message, words: List[str], right_type: str, chat_id: int):
    """Обработка выдачи прав модератора в чате"""
    if len(words) < 2:
        await message.reply(f"❌ Использование: +{right_type} [ID/@username/reply]")
        return
    
    target = words[1]
    
    # Определяем целевого пользователя
    target_user = None
    
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    elif target.startswith('@'):
        # По username - в реальном боте нужен поиск пользователя
        await message.reply("❌ Укажите ID пользователя или сделайте reply")
        return
    elif target.isdigit():
        target_id = int(target)
        # Получаем данные пользователя
        user_data = Database.get_user(target_id)
        if user_data:
            target_user = type('User', (), {
                'id': target_id,
                'full_name': user_data[2],
                'username': user_data[1] or 'Нет'
            })()
    
    if not target_user:
        await message.reply("❌ Не удалось найти пользователя.")
        return
    
    # Определяем какие права давать
    rights = {'mute': False, 'ban': False, 'kick': False}
    
    if right_type == 'mute':
        rights['mute'] = True
    elif right_type == 'ban':
        rights['ban'] = True
    elif right_type == 'kick':
        rights['kick'] = True
    
    # Сохраняем права
    Database.add_moderator_right(target_user.id, chat_id, rights, message.from_user.id)
    
    await message.reply(
        f"✅ Пользователю <b>{target_user.full_name}</b> выданы права на {right_type}!\n"
        f"ID: <code>{target_user.id}</code>\n"
        f"Теперь он может использовать команды {right_type} в этом чате."
    )

async def handle_chat_punishment(message: Message, words: List[str], action: str, chat_id: int):
    """Обработка наказаний в чате"""
    # Определяем цель
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
        time_index = 1
        reason_index = 2
    else:
        if len(words) < 3:
            await message.reply(f"❌ Использование: {action} [время] [причина] или reply + {action} [время] [причина]")
            return
        target = words[1]
        
        # Ищем пользователя
        if target.startswith('@'):
            await message.reply("❌ Укажите ID пользователя или сделайте reply")
            return
        elif target.isdigit():
            target_id = int(target)
            user_data = Database.get_user(target_id)
            if user_data:
                target_user = type('User', (), {
                    'id': target_id,
                    'full_name': user_data[2],
                    'username': user_data[1] or 'Нет'
                })()
            else:
                await message.reply("❌ Пользователь не найден в базе данных.")
                return
        else:
            await message.reply("❌ Укажите ID пользователя или сделайте reply")
            return
        
        time_index = 2
        reason_index = 3
    
    # Парсим время (если нужно)
    duration = None
    if action in ['mute', 'ban']:
        if len(words) > time_index:
            time_str = words[time_index]
            duration = Utils.parse_time(time_str)
        
        if not duration:
            duration = timedelta(hours=1)  # По умолчанию 1 час
    
    # Получаем причину
    reason = "Не указана"
    if len(words) > reason_index:
        reason = ' '.join(words[reason_index:])
    
    # Применяем наказание
    until_date = datetime.now() + duration if duration else datetime.now() + timedelta(minutes=1)
    moderator = message.from_user
    
    Database.add_restriction(
        target_user.id, chat_id, action,
        until_date, reason, moderator.id, moderator.full_name
    )
    
    # Формируем ответ
    if action == 'mute':
        response = (
            f"🔇 <b>Пользователь получил мут!</b>\n\n"
            f"👤 Пользователь: {target_user.full_name}\n"
            f"🆔 ID: <code>{target_user.id}</code>\n"
            f"⏰ Длительность: {Utils.format_time(duration)}\n"
            f"📝 Причина: {reason}\n"
            f"👮 Модератор: {moderator.full_name}"
        )
    elif action == 'ban':
        response = (
            f"🔨 <b>Пользователь забанен!</b>\n\n"
            f"👤 Пользователь: {target_user.full_name}\n"
            f"🆔 ID: <code>{target_user.id}</code>\n"
            f"⏰ Длительность: {Utils.format_time(duration)}\n"
            f"📝 Причина: {reason}\n"
            f"👮 Модератор: {moderator.full_name}"
        )
    else:  # kick
        response = (
            f"👢 <b>Пользователь кикнут!</b>\n\n"
            f"👤 Пользователь: {target_user.full_name}\n"
            f"🆔 ID: <code>{target_user.id}</code>\n"
            f"📝 Причина: {reason}\n"
            f"👮 Модератор: {moderator.full_name}"
        )
    
    await message.reply(response)

# ============ ОСТАЛЬНЫЕ ФУНКЦИИ ============

@router.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def new_chat_member(event: ChatMemberUpdated):
    """Приветствие новых участников"""
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
    
    await bot.send_message(
        chat_id=chat.id,
        text=greeting + member_info
    )

@router.chat_member(ChatMemberUpdatedFilter(LEAVE_TRANSITION))
async def left_chat_member(event: ChatMemberUpdated):
    """Прощание с участниками"""
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
    
    await bot.send_message(
        chat_id=chat.id,
        text=farewell + member_info
    )

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
        await callback.message.edit_text(rules_text, reply_markup=Keyboards.get_back_to_admin_keyboard())
    except:
        await callback.message.answer(rules_text, reply_markup=Keyboards.get_back_to_admin_keyboard())
    
    await callback.answer()

@router.callback_query(F.data == "play_game")
async def callback_play_game(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_data = Database.get_user(user_id)
    
    if not user_data:
        await callback.answer("Ошибка! Начните с /start")
        return
    
    coins_won = random.randint(5, 50)
    new_coins = (user_data[3] or 0) + coins_won
    
    Database.update_user(user_id, coins=new_coins)
    
    response = (
        f"🎮 Вы выиграли {coins_won} Puls Coins!\n\n"
        f"💰 Ваш баланс: {new_coins} монет\n\n"
        f"🏆 Продолжайте в том же духе!"
    )
    
    try:
        await callback.message.edit_text(response, reply_markup=Keyboards.get_back_to_admin_keyboard())
    except:
        await callback.message.answer(response, reply_markup=Keyboards.get_back_to_admin_keyboard())
    
    await callback.answer()

@router.callback_query(F.data == "balance")
async def callback_balance(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_data = Database.get_user(user_id)
    
    if not user_data:
        await callback.answer("Ошибка! Начните с /start")
        return
    
    coins = user_data[3] or 0
    dollars = user_data[4] or 0
    
    response = (
        f"💰 Ваш баланс\n\n"
        f"🎮 Puls Coins: {coins}\n"
        f"💵 Доллары: ${dollars}\n\n"
        f"Играйте в игры и работайте, чтобы увеличить баланс!"
    )
    
    try:
        await callback.message.edit_text(response, reply_markup=Keyboards.get_back_to_admin_keyboard())
    except:
        await callback.message.answer(response, reply_markup=Keyboards.get_back_to_admin_keyboard())
    
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
            top_text += f"{medal} {name_display} - {coins} Puls Coins\n"
    
    try:
        await callback.message.edit_text(top_text, reply_markup=Keyboards.get_back_to_admin_keyboard())
    except:
        await callback.message.answer(top_text, reply_markup=Keyboards.get_back_to_admin_keyboard())
    
    await callback.answer()

@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    
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

# ============ КОМАНДА ПОМОЩИ ============

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Команда помощи"""
    help_text = (
        f"🆘 <b>Помощь по командам Puls Bot</b>\n\n"
        f"<b>Основные команды:</b>\n"
        f"/start - Запустить бота\n"
        f"/help - Эта справка\n"
        f"/rules - Правила бота\n\n"
        f"<b>Игровые команды:</b>\n"
        f"• Нажмите «Играть» в меню\n"
        f"• Нажмите «Баланс» для проверки\n"
        f"• Нажмите «Топ игроков» для рейтинга\n\n"
        f"<b>Модерация (для модераторов):</b>\n"
        f"• мут/mute [время] [причина] - Замутить\n"
        f"• бан/ban [время] [причина] - Забанить\n"
        f"• кик/kick [причина] - Кикнуть\n"
        f"• +мут/+mute [пользователь] - Дать право мута\n"
        f"• +бан/+ban [пользователь] - Дать право бана\n"
        f"• +кик/+kick [пользователь] - Дать право кика\n\n"
        f"<b>Примеры:</b>\n"
        f"<code>мут 30м спам</code> (reply на сообщение)\n"
        f"<code>бан 123456789 7d нарушение</code>\n"
        f"<code>+мут @username</code>\n\n"
        f"<i>Бот автоматически удаляет просроченные ограничения.</i>"
    )
    
    await message.answer(help_text)

# ============ ФОНОВАЯ ЗАДАЧА ДЛЯ ПРОВЕРКИ ОГРАНИЧЕНИЙ ============

async def check_restrictions():
    """Периодическая проверка и снятие просроченных ограничений"""
    while True:
        try:
            conn = Database.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM restrictions WHERE until < ?', (datetime.now().isoformat(),))
            expired = cursor.fetchall()
            
            for restriction in expired:
                cursor.execute('DELETE FROM restrictions WHERE id = ?', (restriction[0],))
            
            conn.commit()
            conn.close()
            
            if expired:
                logger.info(f"Снято {len(expired)} просроченных ограничений")
        except Exception as e:
            logger.error(f"Ошибка при проверке ограничений: {e}")
        
        await asyncio.sleep(60)  # Проверка каждую минуту

# ============ ЗАПУСК БОТА ============

async def main():
    # Запускаем фоновую задачу
    asyncio.create_task(check_restrictions())
    
    logger.info("Бот запускается...")
    logger.info(f"Админ ID: {ADMIN_IDS}")
    logger.info(f"Бот username: @{BOT_USERNAME}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
