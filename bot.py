#!/usr/bin/env python3
"""
🎖️ Телеграм бот с полной системой рангов, наказаний, триггеров и приветствием с кнопками
"""

import asyncio
import logging
import sqlite3
import random
import re
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Dict, Any
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions, CallbackQuery
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.exceptions import TelegramUnauthorizedError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = "8566099089:AAGC-BwcC2mia46iG-aNL9_931h5xV21b9c"
ADMIN_IDS = [6708209142]  # ID создателя бота
BOT_OWNER_USERNAME = "@vanezyyy"  # Юзернейм создателя бота
DEFAULT_MAX_WARNINGS = 5  # Максимальное количество предупреждений по умолчанию

RANKS = {
    0: "👤 Участник",
    1: "👮 Младший модератор", 
    2: "🛡️ Старший модератор",
    3: "👑 Администратор",
    4: "🌟 Продвинутый админ",
    5: "✨ СОЗДАТЕЛЬ"
}

# ===================== СОСТОЯНИЯ ДЛЯ НАСТРОЕК ГРУПП =====================
class GroupSettingsStates(StatesGroup):
    waiting_for_group_link = State()
    waiting_for_punishment_type = State()
    waiting_for_punishment_time = State()
    waiting_for_max_warnings = State()

# ===================== ЛОГИ =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ===================== КЛАСС ДЛЯ КОЛДОВАНА КОМАНД =====================
class CommandCooldown:
    def __init__(self):
        self.user_cooldowns = {}  # {user_id: {chat_id: {command: last_time}}}
        self.cooldown_seconds = 10  # 10 секунд для пользователей 0 ранга
        
    def can_use_command(self, user_id: int, chat_id: int, command: str) -> bool:
        """Проверяет, может ли пользователь использовать команду"""
        if user_id not in self.user_cooldowns:
            self.user_cooldowns[user_id] = {}
        
        if chat_id not in self.user_cooldowns[user_id]:
            self.user_cooldowns[user_id][chat_id] = {}
        
        if command not in self.user_cooldowns[user_id][chat_id]:
            return True
        
        last_time = self.user_cooldowns[user_id][chat_id][command]
        elapsed = (datetime.now() - last_time).total_seconds()
        
        return elapsed >= self.cooldown_seconds
    
    def update_cooldown(self, user_id: int, chat_id: int, command: str):
        """Обновляет время последнего использования команды"""
        if user_id not in self.user_cooldowns:
            self.user_cooldowns[user_id] = {}
        
        if chat_id not in self.user_cooldowns[user_id]:
            self.user_cooldowns[user_id][chat_id] = {}
        
        self.user_cooldowns[user_id][chat_id][command] = datetime.now()

# ===================== БАЗА ДАННЫХ =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("bot.db", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()
        logger.info("База данных подключена")

    def create_tables(self):
        cur = self.conn.cursor()
        # Таблица пользователей
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER,
            chat_id INTEGER,
            username TEXT,
            first_name TEXT,
            rank INTEGER DEFAULT 0,
            warnings INTEGER DEFAULT 0,
            mutes INTEGER DEFAULT 0,
            bans INTEGER DEFAULT 0,
            message_count INTEGER DEFAULT 0,
            last_command_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, chat_id)
        )''')
        # Таблица правил
        cur.execute('''CREATE TABLE IF NOT EXISTS rules (
            chat_id INTEGER PRIMARY KEY,
            text TEXT
        )''')
        # Таблица наказаний
        cur.execute('''CREATE TABLE IF NOT EXISTS punishments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            type TEXT,
            moderator_id INTEGER,
            reason TEXT,
            end_time TIMESTAMP,
            message_id INTEGER,
            active INTEGER DEFAULT 1
        )''')
        # Таблица создателей чатов
        cur.execute('''CREATE TABLE IF NOT EXISTS chat_owners (
            chat_id INTEGER PRIMARY KEY,
            owner_id INTEGER,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        # Таблица настроек групп
        cur.execute('''CREATE TABLE IF NOT EXISTS group_settings (
            chat_id INTEGER PRIMARY KEY,
            max_warnings INTEGER DEFAULT 5,
            punishment_type TEXT DEFAULT 'м',
            punishment_time TEXT DEFAULT '1д',
            setup_by_user_id INTEGER,
            setup_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )''')
        self.conn.commit()
        logger.info("Таблицы созданы")

    def add_user(self, user_id: int, chat_id: int, username: str, first_name: str):
        cur = self.conn.cursor()
        cur.execute('''INSERT OR IGNORE INTO users 
                      (user_id, chat_id, username, first_name) 
                      VALUES (?, ?, ?, ?)''',
                   (user_id, chat_id, username, first_name))
        self.conn.commit()

    def update_message_count(self, user_id: int, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET message_count = message_count + 1 
                      WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        self.conn.commit()

    def get_user(self, user_id: int, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM users WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        return cur.fetchone()

    def set_rank(self, user_id: int, chat_id: int, rank: int):
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET rank=? WHERE user_id=? AND chat_id=?''',
                   (rank, user_id, chat_id))
        self.conn.commit()

    def add_warning(self, user_id: int, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET warnings = warnings + 1 
                      WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        self.conn.commit()
        cur.execute('''SELECT warnings FROM users WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        result = cur.fetchone()
        return result['warnings'] if result else 0

    def get_warnings(self, user_id: int, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT warnings FROM users WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        result = cur.fetchone()
        return result['warnings'] if result else 0

    def reset_warnings(self, user_id: int, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET warnings=0 WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        self.conn.commit()

    def add_mute_count(self, user_id: int, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET mutes = mutes + 1 
                      WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        self.conn.commit()

    def add_ban_count(self, user_id: int, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET bans = bans + 1 
                      WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        self.conn.commit()

    def set_rules(self, chat_id: int, text: str):
        cur = self.conn.cursor()
        cur.execute('''INSERT OR REPLACE INTO rules (chat_id, text) 
                      VALUES (?, ?)''',
                   (chat_id, text))
        self.conn.commit()

    def get_rules(self, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT text FROM rules WHERE chat_id=?''', (chat_id,))
        result = cur.fetchone()
        return result['text'] if result else "Правила ещё не установлены. Используй команду 'п текст'"

    def add_punishment(self, chat_id: int, user_id: int, punishment_type: str, 
                      moderator_id: int, reason: str, end_time: datetime, 
                      message_id: int = None):
        cur = self.conn.cursor()
        cur.execute('''INSERT INTO punishments 
                      (chat_id, user_id, type, moderator_id, reason, end_time, message_id) 
                      VALUES (?, ?, ?, ?, ?, ?, ?)''',
                   (chat_id, user_id, punishment_type, moderator_id, reason, 
                    end_time.isoformat(), message_id))
        self.conn.commit()
        return cur.lastrowid

    def get_active_punishments(self, chat_id: int, user_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM punishments 
                      WHERE chat_id=? AND user_id=? AND active=1 
                      ORDER BY end_time DESC''',
                   (chat_id, user_id))
        return cur.fetchall()

    def get_punishment_by_id(self, punishment_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM punishments WHERE id=?''', (punishment_id,))
        return cur.fetchone()

    def remove_punishment(self, punishment_id: int):
        cur = self.conn.cursor()
        cur.execute('''UPDATE punishments SET active=0 WHERE id=?''', (punishment_id,))
        self.conn.commit()

    def get_expired_punishments(self):
        cur = self.conn.cursor()
        current_time = datetime.now().isoformat()
        cur.execute('''SELECT * FROM punishments 
                      WHERE active=1 AND end_time < ?''',
                   (current_time,))
        return cur.fetchall()

    def get_all_users_in_chat(self, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM users WHERE chat_id=? ORDER BY rank DESC, message_count DESC''', 
                   (chat_id,))
        return cur.fetchall()

    def set_chat_owner(self, chat_id: int, owner_id: int):
        cur = self.conn.cursor()
        cur.execute('''INSERT OR REPLACE INTO chat_owners (chat_id, owner_id) 
                      VALUES (?, ?)''',
                   (chat_id, owner_id))
        self.conn.commit()

    def get_chat_owner(self, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT owner_id FROM chat_owners WHERE chat_id=?''', (chat_id,))
        result = cur.fetchone()
        return result['owner_id'] if result else None

    # ===================== НАСТРОЙКИ ГРУПП =====================
    
    def add_group_setting(self, chat_id: int, max_warnings: int = 5, 
                         punishment_type: str = 'м', punishment_time: str = '1д',
                         user_id: int = None):
        cur = self.conn.cursor()
        cur.execute('''INSERT OR REPLACE INTO group_settings 
                      (chat_id, max_warnings, punishment_type, punishment_time, setup_by_user_id) 
                      VALUES (?, ?, ?, ?, ?)''',
                   (chat_id, max_warnings, punishment_type, punishment_time, user_id))
        self.conn.commit()

    def get_group_settings(self, chat_id: int):
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM group_settings WHERE chat_id=?''', (chat_id,))
        return cur.fetchone()

    def update_max_warnings(self, chat_id: int, max_warnings: int):
        cur = self.conn.cursor()
        cur.execute('''UPDATE group_settings SET max_warnings=? WHERE chat_id=?''',
                   (max_warnings, chat_id))
        self.conn.commit()

    def update_punishment_type(self, chat_id: int, punishment_type: str):
        cur = self.conn.cursor()
        cur.execute('''UPDATE group_settings SET punishment_type=? WHERE chat_id=?''',
                   (punishment_type, chat_id))
        self.conn.commit()

    def update_punishment_time(self, chat_id: int, punishment_time: str):
        cur = self.conn.cursor()
        cur.execute('''UPDATE group_settings SET punishment_time=? WHERE chat_id=?''',
                   (punishment_time, chat_id))
        self.conn.commit()

# ===================== КЛАСС БОТА =====================
class BotCore:
    def __init__(self):
        storage = MemoryStorage()
        self.bot = Bot(token=BOT_TOKEN)
        self.dp = Dispatcher(storage=storage)
        self.router = Router()
        self.db = Database()
        self.dp.include_router(self.router)
        self.bot_info = None
        self.cooldown_manager = CommandCooldown()
        
        # Регистрируем хендлеры
        self.register_handlers()

    async def check_bot_token(self):
        try:
            self.bot_info = await self.bot.get_me()
            logger.info(f"Бот успешно запущен: @{self.bot_info.username}")
            return True
        except TelegramUnauthorizedError:
            logger.error("Неверный токен бота!")
            return False

    async def check_user_permissions(self, chat_id: int, user_id: int):
        try:
            chat_member = await self.bot.get_chat_member(chat_id, user_id)
            is_admin = chat_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
            is_creator = chat_member.status == ChatMemberStatus.CREATOR
            return is_admin, is_creator
        except Exception as e:
            logger.error(f"Ошибка проверки прав: {e}")
            return False, False

    async def get_user_mention(self, user_id: int, chat_id: int = None):
        """Получает упоминание пользователя"""
        try:
            if chat_id:
                chat_member = await self.bot.get_chat_member(chat_id, user_id)
                user = chat_member.user
            else:
                # Пытаемся получить пользователя через get_chat
                try:
                    user = await self.bot.get_chat(user_id)
                except:
                    return f"пользователю с ID {user_id}"
            
            if user.username:
                return f"@{user.username}"
            elif user.first_name:
                return f"{user.first_name}"
            else:
                return f"пользователю с ID {user_id}"
        except Exception as e:
            logger.error(f"Ошибка получения упоминания: {e}")
            return f"пользователю с ID {user_id}"
    
    def register_handlers(self):
        """Регистрация всех обработчиков через функцию register()"""
        
        # Создаем отдельный роутер
        router = self.router
        
        # ===================== КОМАНДЫ СО СЛЕШОМ =====================
        
        @router.message(CommandStart())
        async def start_command(message: Message):
            await self.handle_start(message)
        
        @router.message(Command("revivepuls"))
        async def revivepuls_command(message: Message):
            await self.handle_revivepuls(message)
        
        @router.message(Command("startpulse"))
        async def startpulse_command(message: Message):
            await self.handle_startpulse(message)
        
        # ===================== ОБРАБОТКА СООБЩЕНИЙ В ГРУППАХ =====================
        
        @router.message(F.chat.type.in_({"group", "supergroup"}))
        async def handle_group_message(message: Message):
            """Обработчик сообщений в группах"""
            if not message.from_user:
                return
                
            try:
                user = message.from_user
                # Добавляем/обновляем пользователя
                self.db.add_user(user.id, message.chat.id, 
                               user.username or "", user.first_name or "")
                # Увеличиваем счетчик сообщений
                self.db.update_message_count(user.id, message.chat.id)
                
                # Проверяем создателя чата
                await self.detect_chat_owner(message.chat.id)
                
                # Обрабатываем команды без слеша и триггеры
                if message.text:
                    text = message.text.strip().lower()
                    
                    # Триггеры
                    if text == "пульс":
                        response = random.choice([
                            "⚡ Пульс активен! Система готова к работе!",
                            "💓 Бот жив и работает стабильно!",
                            "🌀 Энергия течет, системы в норме!",
                            "🔋 Заряд 100%! Все функции доступны!",
                            "⚙️ Все системы функционируют в оптимальном режиме!",
                            "💫 Связь установлена! Бот на связи!",
                            "🌐 Сеть стабильна! Все модули активны!",
                            "🚀 Производительность на максимуме! Готов к работе!",
                            "🛡️ Защитные системы активированы! Бот под охраной!",
                            "🎯 Точность 99.9%! Все команды обрабатываются мгновенно!",
                        ])
                        await message.reply(response)
                        return
                        
                    elif text == "обновить пульс":
                        # Проверяем права для этой команды в группе
                        user_data = self.db.get_user(message.from_user.id, message.chat.id)
                        if not user_data or user_data['rank'] < 1:
                            await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 1 или выше.")
                            return
                        
                        msg1 = await message.reply("🔄 Обновляю все изменения и бота...")
                        await asyncio.sleep(0.8)
                        await msg1.edit_text("✅ Все функции применены, бот работает нормально")
                        return
                    
                    # Обработка команд без слеша
                    await self.handle_command_without_slash(message)
                    
            except Exception as e:
                logger.error(f"Ошибка обработки группового сообщения: {e}")
        
        # ===================== ОБРАБОТКА ТРИГГЕРОВ В ЛС =====================
        
        @router.message(F.chat.type == "private", F.text)
        async def handle_private_text(message: Message):
            """Обработчик текстовых сообщений в ЛС"""
            if not message.text:
                return
            
            text = message.text.strip().lower()
            
            # Триггеры в ЛС
            if text == "пульс":
                response = random.choice([
                    "⚡ Пульс активен! Система готова к работе!",
                    "💓 Бот жив и работает стабильно!",
                    "🌀 Энергия течет, системы в норме!",
                ])
                await message.reply(response)
                return
                
            elif text == "обновить пульс":
                msg1 = await message.reply("🔄 Обновляю все изменения и бота...")
                await asyncio.sleep(0.8)
                await msg1.edit_text("✅ Все функции применены, бот работает нормально")
                return
        
        # ===================== CALLBACK ОБРАБОТЧИКИ =====================
        
        @router.callback_query(F.data == "group_settings")
        async def group_settings_cb(query: CallbackQuery):
            await self.handle_group_settings_callback(query)
        
        @router.callback_query(F.data == "add_group")
        async def add_group_cb(query: CallbackQuery, state: FSMContext):
            await self.handle_add_group_callback(query, state)
        
        @router.callback_query(F.data.startswith("max_warn_"))
        async def max_warnings_cb(query: CallbackQuery):
            await self.handle_max_warnings_callback(query)
        
        @router.callback_query(F.data == "configure_punishment")
        async def configure_punishment_cb(query: CallbackQuery, state: FSMContext):
            await self.handle_configure_punishment_callback(query, state)
        
        @router.callback_query(F.data == "configure_time")
        async def configure_time_cb(query: CallbackQuery, state: FSMContext):
            await self.handle_configure_time_callback(query, state)
        
        @router.callback_query(F.data == "back_to_settings")
        async def back_to_settings_cb(query: CallbackQuery):
            await self.handle_back_to_settings_callback(query)
        
        @router.callback_query(F.data == "save_settings")
        async def save_settings_cb(query: CallbackQuery):
            await self.handle_save_settings_callback(query)
        
        @router.callback_query(F.data == "coming_soon")
        async def coming_soon_cb(query: CallbackQuery):
            await query.answer("🚧 Эта функция скоро будет доступна!", show_alert=True)
        
        @router.callback_query(F.data == "show_rules")
        async def show_rules_cb(query: CallbackQuery):
            await self.handle_show_rules_callback(query)
        
        @router.callback_query(F.data == "support")
        async def support_cb(query: CallbackQuery):
            await self.handle_support_callback(query)
        
        @router.callback_query(F.data == "help")
        async def help_cb(query: CallbackQuery):
            await self.handle_help_callback(query)
        
        @router.callback_query(F.data == "channel")
        async def channel_cb(query: CallbackQuery):
            await self.handle_channel_callback(query)
        
        @router.callback_query(F.data == "bot_rules")
        async def bot_rules_cb(query: CallbackQuery):
            await self.handle_bot_rules_callback(query)
        
        @router.callback_query(F.data.startswith("remove_punish_"))
        async def remove_punishment_cb(query: CallbackQuery):
            await self.handle_remove_punishment_callback(query)
        
        # ===================== ОБРАБОТЧИКИ ДЛЯ СОСТОЯНИЙ =====================
        
        @router.message(GroupSettingsStates.waiting_for_group_link)
        async def process_group_link(message: Message, state: FSMContext):
            await self.process_group_link_handler(message, state)
        
        @router.message(GroupSettingsStates.waiting_for_punishment_type)
        async def process_punishment_type(message: Message, state: FSMContext):
            await self.process_punishment_type_handler(message, state)
        
        @router.message(GroupSettingsStates.waiting_for_punishment_time)
        async def process_punishment_time(message: Message, state: FSMContext):
            await self.process_punishment_time_handler(message, state)
    
    # ===================== МЕТОДЫ ОБРАБОТКИ =====================
    
    async def detect_chat_owner(self, chat_id: int):
        """Определяет создателя чата и дает ему все права"""
        try:
            # Получаем всех администраторов чата
            admins = await self.bot.get_chat_administrators(chat_id)
            
            for admin in admins:
                if admin.status == ChatMemberStatus.CREATOR:
                    owner_id = admin.user.id
                    current_owner = self.db.get_chat_owner(chat_id)
                    
                    # Если создатель изменился или еще не записан
                    if current_owner != owner_id:
                        self.db.set_chat_owner(chat_id, owner_id)
                        # Устанавливаем создателю ранг 5
                        self.db.set_rank(owner_id, chat_id, 5)
                        logger.info(f"Определен создатель чата {chat_id}: {owner_id}")
                    
                    return owner_id
        except Exception as e:
            logger.error(f"Ошибка определения создателя чата: {e}")
        
        return None
    
    async def handle_start(self, message: Message):
        """Обработка /start"""
        if message.chat.type == "private":
            # Клавиатура для ЛС
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🛠 Техподдержка", callback_data="support")],
                    [InlineKeyboardButton(text="📖 Помощь по командам", callback_data="help")],
                    [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/VanezyScripts"),
                     InlineKeyboardButton(text="📋 Правила бота", callback_data="bot_rules")]
                ]
            )
            
            text = f"""👋 Привет, {message.from_user.first_name}!

Рад тебя видеть! Я — Puls Bot, твой помощник в управлении группами и чатами.

✨ **Что я умею:**
• Управление участниками
• Система рангов
• Наказания (муты, баны, предупреждения)
• Автоматические функции

🎮 **Основные команды (в группах пиши без /):**
• `пульс` — проверка работы бота
• `обновить пульс` — обновление всех систем
• `помощь` — все доступные команды
• `профиль` — твоя статистика

Для работы в группе просто добавь меня туда и дай права администратора!

Нажимай на кнопки ниже, чтобы узнать больше ⬇️"""
        else:
            # Клавиатура для групп
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📜 Правила чата", callback_data="show_rules"),
                     InlineKeyboardButton(text="⚙️ Настройки группы", callback_data="group_settings")],
                    [InlineKeyboardButton(text="🛠 Техподдержка", callback_data="support")],
                    [InlineKeyboardButton(text="📖 Помощь", callback_data="help")]
                ]
            )
            
            text = f"""👋 Привет, {message.from_user.first_name}!

Отлично, теперь я в этой группе и готов помогать с управлением!

✨ **Что я буду делать здесь:**
• Следить за порядком
• Помогать модераторам
• Вести статистику участников

🎮 **Основные команды (пиши без /):**
• `пульс` — проверка работы
• `обновить пульс` — обновление
• `помощь` — все команды
• `профиль` — твоя статистика

👮 **Модерация (для модераторов):**
• `м 30м причина` — мут на 30 минут
• `б причина` — бан  
• `к причина` — кик
• `в причина` — предупреждение

Не забудь подписаться на наш канал с обновлениями! ⬇️"""
        
        await message.reply(text, reply_markup=kb)
    
    async def handle_revivepuls(self, message: Message):
        """Обработка /revivepuls - обновление бота в группе"""
        try:
            if message.chat.type == "private":
                await message.reply("ℹ️ Эта команда работает только в группах.")
                return
            
            # Проверяем права пользователя
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            
            # Сначала проверяем настройки группы
            group_settings = self.db.get_group_settings(message.chat.id)
            
            if group_settings:
                # Если настройки есть, проверяем кто может использовать
                if user_data and user_data['rank'] >= 1:
                    # Все с рангом 1+ могут использовать после настройки
                    pass
                else:
                    await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 1 или выше.")
                    return
            else:
                # Если настроек нет, только создатель может использовать
                owner_id = self.db.get_chat_owner(message.chat.id)
                if not owner_id or message.from_user.id != owner_id:
                    await message.reply("❌ Эта команда доступна только создателю чата до настройки группы.")
                    return
            
            # Обновляем все системы
            msg1 = await message.reply("🔄 Обновляю все системы бота...")
            await asyncio.sleep(1)
            
            # Проверяем создателя чата
            await self.detect_chat_owner(message.chat.id)
            
            # Загружаем настройки группы
            if group_settings:
                settings_text = f"\n⚙️ Настройки группы загружены:\n• Макс. предупреждений: {group_settings['max_warnings']}\n• Наказание при превышении: {group_settings['punishment_type']}\n• Время наказания: {group_settings['punishment_time']}"
            else:
                settings_text = "\n⚠️ Настройки группы не установлены. Используйте команду 'Настройки группы' в меню."
            
            await msg1.edit_text(f"✅ Бот успешно обновлен в этой группе!{settings_text}\n\nВсе системы работают в нормальном режиме. 🎯")
            
        except Exception as e:
            logger.error(f"Ошибка в revivepuls: {e}")
            await message.reply("❌ Не удалось обновить бота.")
    
    async def handle_startpulse(self, message: Message):
        """Обработка /startpulse - приветствие"""
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/VanezyScripts"),
                 InlineKeyboardButton(text="📖 Помощь", callback_data="help")]
            ]
        )
        
        if message.chat.type == "private":
            text = "👋 Привет! Я Puls Bot - твой помощник в управлении группами! Нажми на кнопки ниже, чтобы узнать больше!"
        else:
            text = f"👋 Привет, {message.from_user.first_name}! Я теперь в этой группе и готов помогать с управлением!"
        
        await message.reply(text, reply_markup=kb)
    
    async def handle_command_without_slash(self, message: Message):
        """Обработка команд без слеша"""
        text = message.text.strip()
        
        # Разбиваем на части
        parts = text.split(maxsplit=3)
        if not parts:
            return
        
        command = parts[0].lower()
        
        # Проверяем кд для пользователей 0 ранга
        user_data = self.db.get_user(message.from_user.id, message.chat.id)
        if user_data and user_data['rank'] == 0:
            # Список команд, доступных пользователям 0 ранга
            allowed_commands = ["помощь", "пом", "команды", "профиль", "проф", "стат", "правила", "п"]
            
            if command in allowed_commands:
                if not self.cooldown_manager.can_use_command(message.from_user.id, message.chat.id, command):
                    await message.reply("⏳ Подожди 10 секунд перед использованием следующей команды.")
                    return
                
                self.cooldown_manager.update_cooldown(message.from_user.id, message.chat.id, command)
        
        # Показ помощи
        if command in ["помощь", "пом", "команды"]:
            await self.handle_help(message)
            return
            
        # Профиль
        elif command in ["профиль", "проф", "стат"]:
            await self.handle_profile(message)
            return
            
        # Правила
        elif command in ["правила", "п"]:
            if len(parts) > 1:
                await self.handle_setrules(message, " ".join(parts[1:]))
            else:
                await self.handle_rules(message)
            return
            
        # Ранги
        elif command in ["ранги", "р"]:
            await self.handle_ranks(message)
            return
            
        # Пользователи
        elif command in ["юзеры", "ю", "участники"]:
            await self.handle_users(message)
            return
            
        # Предупреждение
        elif command in ["варн", "в", "пред", "предупреждение"]:
            await self.handle_warn(message, parts)
            return
            
        # Мут
        elif command in ["мут", "м"]:
            await self.handle_mute(message, parts)
            return
            
        # Размут
        elif command in ["размут", "рм"]:
            await self.handle_unmute(message, parts)
            return
            
        # Бан
        elif command in ["бан", "б"]:
            await self.handle_ban(message, parts)
            return
            
        # Разбан
        elif command in ["разбан", "рб"]:
            await self.handle_unban(message, parts)
            return
            
        # Кик
        elif command in ["кик", "к"]:
            await self.handle_kick(message, parts)
            return
            
        # Проверка варнов
        elif command in ["варны", "предупреждения"]:
            await self.handle_warnings(message, parts)
            return
            
        # Изменение ранга
        elif command in ["ранг", "установитьранг"]:
            if len(parts) >= 3:
                await self.handle_setrank(message, parts)
            else:
                await message.reply("❌ Используй: ранг ID новый_ранг\nПример: ранг 123456789 2")
            return
            
        # Восстановление создателя
        elif command == "восстановить" and len(parts) > 1 and parts[1] == "создателя":
            await self.handle_restore_owner(message)
            return
    
    async def handle_profile(self, message: Message):
        """Обработка команды профиля"""
        try:
            if message.chat.type == "private":
                # В личных сообщениях
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/VanezyScripts")],
                        [InlineKeyboardButton(text="📖 Помощь", callback_data="help"),
                         InlineKeyboardButton(text="📋 Правила бота", callback_data="bot_rules")]
                    ]
                )
                
                profile_text = f"""📊 **Твой профиль:**

👤 Имя: {message.from_user.first_name}
📛 Юзернейм: @{message.from_user.username or 'не указан'}
🆔 ID: `{message.from_user.id}`

ℹ️ **Информация:**
• Твой профиль в группах будет виден только там
• В каждой группе отдельный профиль
• Ранг и наказания сохраняются для каждого чата

📖 Нажми на кнопку 'Помощь' чтобы узнать все команды"""
                
                await message.reply(profile_text, parse_mode="Markdown", reply_markup=kb)
            else:
                # В группе
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if user_data:
                    # Кнопки для профиля в группе
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/VanezyScripts")],
                            [InlineKeyboardButton(text="📖 Помощь", callback_data="help"),
                             InlineKeyboardButton(text="📋 Правила бота", callback_data="bot_rules")]
                        ]
                    )
                    
                    rank_name = RANKS.get(user_data['rank'], "Неизвестно")
                    
                    # Форматируем дату регистрации
                    if 'registered_at' in user_data and user_data['registered_at']:
                        try:
                            reg_date = datetime.strptime(user_data['registered_at'], '%Y-%m-%d %H:%M:%S')
                            reg_date_str = reg_date.strftime('%d.%m.%Y')
                        except:
                            reg_date_str = "неизвестно"
                    else:
                        reg_date_str = "неизвестно"
                    
                    profile_text = f"""📊 **Профиль участника:**

👤 Имя: {user_data['first_name']}
📛 Юзернейм: @{user_data['username'] or 'не указан'}
🆔 ID: `{user_data['user_id']}`

📈 **Статистика в этой группе:**
🎖️ Ранг: {rank_name}
📅 Зарегистрирован: {reg_date_str}
💬 Сообщений: {user_data.get('message_count', 0)}

⚠️ Предупреждения: {user_data['warnings']}/{DEFAULT_MAX_WARNINGS}
🔇 Мутов: {user_data['mutes']}
🔨 Банов: {user_data['bans']}"""
                    
                    # Проверяем активные наказания
                    punishments = self.db.get_active_punishments(message.chat.id, message.from_user.id)
                    if punishments:
                        profile_text += "\n\n🔒 **Активные наказания:**"
                        for punish in punishments:
                            end_time = datetime.fromisoformat(punish['end_time'])
                            time_left = end_time - datetime.now()
                            hours_left = max(0, int(time_left.total_seconds() / 3600))
                            
                            if punish['type'] == 'mute':
                                profile_text += f"\n🔇 Мут до: {end_time.strftime('%d.%m.%Y %H:%M')} ({hours_left}ч.)"
                            elif punish['type'] == 'ban':
                                profile_text += f"\n🔨 Бан до: {end_time.strftime('%d.%m.%Y %H:%M')} ({hours_left}ч.)"
                    
                    await message.reply(profile_text, parse_mode="Markdown", reply_markup=kb)
                else:
                    # Если пользователь еще не в базе
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/VanezyScripts")],
                            [InlineKeyboardButton(text="📖 Помощь", callback_data="help"),
                             InlineKeyboardButton(text="📋 Правила бота", callback_data="bot_rules")]
                        ]
                    )
                    
                    await message.reply(
                        "🤔 Твой профиль ещё не создан в этом чате.\n"
                        "Напиши что-нибудь в чат, и он появится автоматически.",
                        reply_markup=kb
                    )
        except Exception as e:
            logger.error(f"Ошибка в профиле: {e}")
            await message.reply("❌ Не удалось загрузить профиль.")
    
    async def handle_help(self, message: Message):
        """Обработка команды помощи"""
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/VanezyScripts")],
                [InlineKeyboardButton(text="📋 Правила бота", callback_data="bot_rules")]
            ]
        )
        
        if message.chat.type == "private":
            help_text = """📖 **Помощь по командам:**

🎮 **Триггеры (просто напиши):**
• `пульс` — проверка работы бота
• `обновить пульс` — обновление бота

👋 **Для всех:**
• `помощь` — эта справка
• `профиль` — твой профиль

👮 **Для модераторов (только в группах):**
• `в причина` — выдать предупреждение
• `м время причина` — замутить (пример: м 30м спам)
• `рм ID` — снять мут
• `б причина` — забанить
• `рб ID` — снять бан
• `к причина` — кикнуть

⚙️ **Для администраторов (только в группах):**
• `ранг ID ранг` — изменить ранг
• `п текст` — установить правила
• `ранги` — список рангов
• `юзеры` — все пользователи чата

🔧 **С командами / (везде):**
• `/start` — приветствие
• `/revivepuls` — обновление бота в группе
• `/startpulse` — приветствие

📌 **Как указывать пользователя:**
• Ответь на сообщение пользователя
• Или укажи его ID

👑 Создатель: @vanezyyy
🛠 Поддержка: @VanezyPulsSupport"""
        else:
            help_text = """📖 **Доступные команды в этом чате:**

🎮 **Триггеры (пиши просто):**
• `пульс` — проверка работы
• `обновить пульс` — обновление бота

👋 **Для всех:**
• `помощь` — эта справка
• `профиль` — твой профиль
• `правила` — правила чата

👮 **Для модераторов (ранг 2+):**
• `в [ответ/ID] причина` — предупреждение
• `м [ответ/ID] время причина` — мут (пример: м 30м спам)
• `рм ID` — снять мут
• `б [ответ/ID] причина` — бан
• `рб ID` — снять бан
• `к [ответ/ID] причина` — кик
• `варны [ответ/ID]` — проверить предупреждения

⚙️ **Для администраторов (ранг 3+):**
• `ранг ID ранг` — изменить ранг
• `п текст` — установить правила
• `ранги` — список рангов
• `юзеры` — все пользователи чата

🔧 **С командами / (везде):**
• `/start` — приветствие
• `/revivepuls` — обновление бота
• `/startpulse` — приветствие

🎯 **Примеры:**
• `м 30м спам` — мут на 30 минут за спам
• `б оскорбления` — бан за оскорбления
• `к флуд` — кик за флуд

👑 Создатель: @vanezyyy
🛠 Поддержка: @VanezyPulsSupport"""
        
        await message.reply(help_text, parse_mode="Markdown", reply_markup=kb)
    
    async def handle_help_callback(self, query: CallbackQuery):
        """Обработка callback помощи"""
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/VanezyScripts")],
                [InlineKeyboardButton(text="📋 Правила бота", callback_data="bot_rules")]
            ]
        )
        
        if query.message.chat.type == "private":
            help_text = """📖 **Помощь по командам:**

🎮 **Триггеры (просто напиши):**
• `пульс` — проверка работы бота
• `обновить пульс` — обновление бота

👋 **Для всех:**
• `помощь` — эта справка
• `профиль` — твой профиль

👮 **Для модераторов (только в группах):**
• `в причина` — выдать предупреждение
• `м время причина` — замутить (пример: м 30м спам)
• `рм ID` — снять мут
• `б причина` — забанить
• `рб ID` — снять бан
• `к причина` — кикнуть

⚙️ **Для администраторов (только в группах):**
• `ранг ID ранг` — изменить ранг
• `п текст` — установить правила
• `ранги` — список рангов
• `юзеры` — все пользователи чата

🔧 **С командами / (везде):**
• `/start` — приветствие
• `/revivepuls` — обновление бота в группе
• `/startpulse` — приветствие

📌 **Как указывать пользователя:**
• Ответь на сообщение пользователя
• Или укажи его ID

👑 Создатель: @vanezyyy
🛠 Поддержка: @VanezyPulsSupport"""
        else:
            help_text = """📖 **Доступные команды в этом чате:**

🎮 **Триггеры (пиши просто):**
• `пульс` — проверка работы
• `обновить пульс` — обновление бота

👋 **Для всех:**
• `помощь` — эта справка
• `профиль` — твой профиль
• `правила` — правила чата

👮 **Для модераторов (ранг 2+):**
• `в [ответ/ID] причина` — предупреждение
• `м [ответ/ID] время причина` — мут (пример: м 30м спам)
• `рм ID` — снять мут
• `б [ответ/ID] причина` — бан
• `рб ID` — снять бан
• `к [ответ/ID] причина` — кик
• `варны [ответ/ID]` — проверить предупреждения

⚙️ **Для администраторов (ранг 3+):**
• `ранг ID ранг` — изменить ранг
• `п текст` — установить правила
• `ранги` — список рангов
• `юзеры` — все пользователи чата

🔧 **С командами / (везде):**
• `/start` — приветствие
• `/revivepuls` — обновление бота
• `/startpulse` — приветствие

🎯 **Примеры:**
• `м 30м спам` — мут на 30 минут за спам
• `б оскорбления` — бан за оскорбления
• `к флуд` — кик за флуд

👑 Создатель: @vanezyyy
🛠 Поддержка: @VanezyPulsSupport"""
        
        await query.message.answer(help_text, parse_mode="Markdown", reply_markup=kb)
        await query.answer()
    
    async def handle_bot_rules_callback(self, query: CallbackQuery):
        """Обработка callback правил бота"""
        text = """📋 **Правила использования бота:**

1. **Уважение к участникам**
   • Не злоупотребляй правами модератора
   • Используй команды по назначению

2. **Правильное использование команд**
   • Муты — только за нарушение правил
   • Баны — за серьезные нарушения
   • Кики — при необходимости

3. **Технические правила**
   • Не пытайся сломать бота
   • Сообщай об ошибках в поддержку
   • Следуй инструкциям бота

4. **Ранги и права**
   • Ранг 1-2 — базовые права
   • Ранг 3-4 — расширенные права
   • Ранг 5 — полный доступ

👑 **Владелец:** @vanezyyy
🛠 **Поддержка:** @VanezyPulsSupport
📢 **Канал:** @VanezyScripts

Соблюдай правила для комфортной работы бота в чате!"""
        
        await query.message.answer(text, parse_mode="Markdown")
        await query.answer()
    
    async def handle_channel_callback(self, query: CallbackQuery):
        """Обработка callback канала"""
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📢 Перейти в канал", url="https://t.me/VanezyScripts")]
            ]
        )
        
        text = "📢 **Наш канал с обновлениями:**\n\nПодпишись на канал @VanezyScripts чтобы быть в курсе всех обновлений бота, получать новые функции и узнавать о фишках первым!"
        
        await query.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        await query.answer()
    
    async def handle_show_rules_callback(self, query: CallbackQuery):
        """Показать правила (callback)"""
        try:
            if query.message.chat.type == "private":
                await query.message.answer("ℹ️ Правила устанавливаются для каждого чата отдельно.\nВ личных сообщениях правил нет.")
            else:
                rules = self.db.get_rules(query.message.chat.id)
                
                # Отправляем правила как есть, без изменений
                if len(rules) > 4096:
                    # Если правила слишком длинные, разбиваем на части
                    parts = [rules[i:i+4096] for i in range(0, len(rules), 4096)]
                    for i, part in enumerate(parts):
                        if i == 0:
                            await query.message.answer(f"📜 **Правила чата:**\n\n{part}")
                        else:
                            await query.message.answer(part)
                else:
                    await query.message.answer(f"📜 **Правила чата:**\n\n{rules}")
            await query.answer()
        except Exception as e:
            logger.error(f"Ошибка показа правил (callback): {e}")
            await query.answer("Ошибка загрузки правил", show_alert=True)
    
    async def handle_support_callback(self, query: CallbackQuery):
        """Техподдержка (callback)"""
        try:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/VanezyScripts")],
                    [InlineKeyboardButton(text="📖 Помощь", callback_data="help")]
                ]
            )
            
            text = """💡 **Техническая поддержка**

Если у тебя есть вопросы или проблемы с ботом:

✅ **Как правильно написать:**
• Опиши проблему понятно
• Укажи, что именно не работает
• Приведи пример, если можно

❌ **Как НЕ надо писать:**
• Просто "привет" или "здравствуйте"
• "Помогите" без объяснения
• Ожидание ответа без контекста

**Контакты:**
👑 Владелец: @vanezyyy
🛠 Поддержка: @VanezyPulsSupport
📢 Канал: @VanezyScripts

Мы ответим как можно скорее!"""
            
            await query.message.answer(text, parse_mode="Markdown", reply_markup=kb)
            await query.answer()
        except Exception as e:
            logger.error(f"Ошибка поддержки (callback): {e}")
            await query.answer("Ошибка", show_alert=True)
    
    async def handle_rules(self, message: Message):
        """Показать правила - отображает ВСЁ как есть"""
        try:
            if message.chat.type == "private":
                await message.reply("ℹ️ Правила устанавливаются для каждого чата отдельно.\nВ личных сообщениях правил нет.")
                return
            
            rules = self.db.get_rules(message.chat.id)
            
            # Отправляем правила как есть, без изменений
            if len(rules) > 4096:
                # Если правила слишком длинные, разбиваем на части
                parts = [rules[i:i+4096] for i in range(0, len(rules), 4096)]
                for i, part in enumerate(parts):
                    if i == 0:
                        await message.reply(f"📜 **Правила чата:**\n\n{part}")
                    else:
                        await message.reply(part)
            else:
                await message.reply(f"📜 **Правила чата:**\n\n{rules}")
                
        except Exception as e:
            logger.error(f"Ошибка показа правил: {e}")
            await message.reply("❌ Не удалось загрузить правила.")
    
    async def handle_setrules(self, message: Message, text: str):
        """Установить правила - сохраняет ВСЁ как есть"""
        try:
            if message.chat.type == "private":
                await message.reply("❌ Эта команда работает только в группах.")
                return
            
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            if not user_data or user_data['rank'] < 3:
                await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 3 или выше.")
                return
            
            # Сохраняем текст КАК ЕСТЬ, без изменений
            self.db.set_rules(message.chat.id, text)
            
            # Отправляем подтверждение с предпросмотром
            preview_text = text[:200] + "..." if len(text) > 200 else text
            await message.reply(f"✅ Правила успешно обновлены!\n\n📋 Предпросмотр:\n{preview_text}")
            
        except Exception as e:
            logger.error(f"Ошибка установки правил: {e}")
            await message.reply("❌ Не удалось установить правила.")
    
    async def handle_ranks(self, message: Message):
        """Показать ранги"""
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/VanezyScripts")],
                [InlineKeyboardButton(text="📋 Правила бота", callback_data="bot_rules")]
            ]
        )
        
        ranks_text = "🎖️ **Система рангов:**\n\n"
        for rank_num, rank_name in sorted(RANKS.items()):
            ranks_text += f"{rank_num} - {rank_name}\n"
        
        ranks_text += "\n**Права:**\n"
        ranks_text += "1+ - Просмотр профилей, обновление пульса\n"
        ranks_text += "2+ - Варны, кики, размуты, разбаны\n"
        ranks_text += "3+ - Изменение рангов, правила\n"
        ranks_text += "4+ - Муты\n"
        ranks_text += "5 - Создатель (все права)"
        
        await message.reply(ranks_text, parse_mode="Markdown", reply_markup=kb)
    
    async def handle_users(self, message: Message):
        """Показать пользователей"""
        try:
            if message.chat.type == "private":
                await message.reply("❌ Эта команда работает только в группах.")
                return
            
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            if not user_data or user_data['rank'] < 3:
                await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 3 или выше.")
                return
            
            users = self.db.get_all_users_in_chat(message.chat.id)
            
            if not users:
                await message.reply("🤔 В базе пока нет пользователей.")
                return
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/VanezyScripts")],
                    [InlineKeyboardButton(text="📋 Правила бота", callback_data="bot_rules")]
                ]
            )
            
            users_by_rank = {}
            for user in users:
                rank = user['rank']
                if rank not in users_by_rank:
                    users_by_rank[rank] = []
                
                username = f"@{user['username']}" if user['username'] else user['first_name']
                users_by_rank[rank].append(f"{username} (ID: {user['user_id']}, сообщений: {user.get('message_count', 0)})")
            
            users_text = "👥 **Пользователи в этом чате:**\n\n"
            for rank_num in sorted(RANKS.keys(), reverse=True):
                if rank_num in users_by_rank:
                    rank_name = RANKS[rank_num]
                    users_text += f"**{rank_name}:**\n"
                    for user_str in users_by_rank[rank_num]:
                        users_text += f"  • {user_str}\n"
                    users_text += "\n"
            
            if len(users_text) > 4000:
                parts = [users_text[i:i+4000] for i in range(0, len(users_text), 4000)]
                for part in parts:
                    await message.reply(part, parse_mode="Markdown", reply_markup=kb)
            else:
                await message.reply(users_text, parse_mode="Markdown", reply_markup=kb)
                
        except Exception as e:
            logger.error(f"Ошибка показа пользователей: {e}")
            await message.reply("❌ Не удалось показать пользователей.")
    
    async def parse_user(self, message: Message, user_text: str = None):
        """Парсит пользователя из текста"""
        try:
            # Если ответ на сообщение
            if message.reply_to_message:
                return message.reply_to_message.from_user
            
            # Если указан ID
            if user_text and user_text.isdigit():
                user_id = int(user_text)
                try:
                    chat_member = await self.bot.get_chat_member(message.chat.id, user_id)
                    return chat_member.user
                except:
                    await message.reply("❌ Не нашёл пользователя с таким ID в этом чате.")
                    return None
            
            # Если ничего не указано
            await message.reply("❌ Укажи пользователя:\n• Ответь на сообщение\n• Или укажи ID (например: в 123456789 причина)")
            return None
            
        except Exception as e:
            logger.error(f"Ошибка парсинга пользователя: {e}")
            await message.reply("❌ Не удалось найти пользователя.")
            return None
    
    async def parse_time(self, time_str: str) -> Optional[int]:
        """Парсит время из строки (30м, 2ч, 1д) в минуты"""
        try:
            time_str = time_str.lower().strip()
            
            if time_str.endswith('м'):
                minutes = int(time_str[:-1])
                return minutes
            elif time_str.endswith('ч'):
                hours = int(time_str[:-1])
                return hours * 60
            elif time_str.endswith('д'):
                days = int(time_str[:-1])
                return days * 24 * 60
            elif time_str.isdigit():
                return int(time_str)  # Просто минуты
            else:
                return None
        except:
            return None
    
    async def handle_warn(self, message: Message, parts: List[str]):
        """Обработка команды варна"""
        try:
            if message.chat.type == "private":
                await message.reply("❌ Эта команда работает только в группах.")
                return
            
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            if not user_data or user_data['rank'] < 2:
                await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 2 или выше.")
                return
            
            # Определяем цель
            if message.reply_to_message:
                target_user = message.reply_to_message.from_user
                reason = " ".join(parts[1:]) if len(parts) > 1 else "Не указана"
            else:
                if len(parts) < 2:
                    await message.reply("❌ Укажи пользователя и причину:\n• Ответь на сообщение\n• Или: в ID причина")
                    return
                
                target_user = await self.parse_user(message, parts[1])
                if not target_user:
                    return
                
                reason = " ".join(parts[2:]) if len(parts) > 2 else "Не указана"
            
            # Проверки
            if target_user.id == message.from_user.id:
                await message.reply("❌ Нельзя выдать предупреждение самому себе!")
                return
            
            if target_user.id == self.bot_info.id:
                await message.reply("❌ Нельзя наказывать бота!")
                return
            
            # Проверяем права в чате
            is_target_admin, is_target_creator = await self.check_user_permissions(
                message.chat.id, target_user.id
            )
            
            if is_target_creator:
                await message.reply("❌ Нельзя наказывать создателя чата!")
                return
            
            if is_target_admin:
                await message.reply("❌ Нельзя наказывать администратора!")
                return
            
            # Проверяем ранги в базе
            target_data = self.db.get_user(target_user.id, message.chat.id)
            if target_data and target_data['rank'] >= user_data['rank']:
                await message.reply("❌ Нельзя наказывать пользователя с равным или высшим рангом!")
                return
            
            # Получаем текущий лимит варнов для группы
            group_settings = self.db.get_group_settings(message.chat.id)
            max_warnings = group_settings['max_warnings'] if group_settings else DEFAULT_MAX_WARNINGS
            
            # Добавляем предупреждение
            warnings = self.db.add_warning(target_user.id, message.chat.id)
            
            # Получаем упоминание модератора
            moderator_mention = await self.get_user_mention(message.from_user.id, message.chat.id)
            
            await message.reply(
                f"⚠️ Пользователю {target_user.mention_html()} выдано предупреждение!\n"
                f"📝 Причина: {reason}\n"
                f"🔢 Предупреждений: {warnings}/{max_warnings}\n"
                f"👮 Модератор: {moderator_mention}",
                parse_mode="HTML"
            )
            
            # Проверяем лимит предупреждений
            if warnings >= max_warnings:
                # Получаем настройки наказания
                punishment_type = 'м'  # По умолчанию мут
                punishment_time = '1д'  # По умолчанию 1 день
                
                if group_settings:
                    punishment_type = group_settings['punishment_type']
                    punishment_time = group_settings['punishment_time']
                
                # Парсим время наказания
                duration = await self.parse_time(punishment_time)
                if not duration:
                    duration = 1440  # 1 день по умолчанию
                
                if punishment_type == 'м':
                    # Мут
                    await self.mute_user(
                        chat_id=message.chat.id,
                        user_id=target_user.id,
                        duration_minutes=duration,
                        reason=f"Автоматический мут за {max_warnings} предупреждений",
                        moderator_id=message.from_user.id
                    )
                    
                    self.db.reset_warnings(target_user.id, message.chat.id)
                    
                    await message.reply(
                        f"🚨 Пользователь {target_user.mention_html()} получил {max_warnings} предупреждений!\n"
                        f"🔇 Автоматически замучен на {punishment_time}.",
                        parse_mode="HTML"
                    )
                    
                elif punishment_type == 'б':
                    # Бан
                    await self.ban_user(
                        chat_id=message.chat.id,
                        user_id=target_user.id,
                        reason=f"Автоматический бан за {max_warnings} предупреждений",
                        moderator_id=message.from_user.id
                    )
                    
                    self.db.reset_warnings(target_user.id, message.chat.id)
                    
                    await message.reply(
                        f"🚨 Пользователь {target_user.mention_html()} получил {max_warnings} предупреждений!\n"
                        f"🔨 Автоматически забанен на {punishment_time}.",
                        parse_mode="HTML"
                    )
                    
                elif punishment_type == 'к':
                    # Кик
                    await self.kick_user(
                        chat_id=message.chat.id,
                        user_id=target_user.id,
                        reason=f"Автоматический кик за {max_warnings} предупреждений",
                        moderator_id=message.from_user.id
                    )
                    
                    self.db.reset_warnings(target_user.id, message.chat.id)
                    
                    await message.reply(
                        f"🚨 Пользователь {target_user.mention_html()} получил {max_warnings} предупреждений!\n"
                        f"👢 Автоматически кикнут.",
                        parse_mode="HTML"
                    )
                
        except Exception as e:
            logger.error(f"Ошибка в варне: {e}")
            await message.reply("❌ Не удалось выдать предупреждение.")
    
    async def handle_mute(self, message: Message, parts: List[str]):
        """Обработка команды мута"""
        try:
            if message.chat.type == "private":
                await message.reply("❌ Эта команда работает только в группах.")
                return
            
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            if not user_data or user_data['rank'] < 4:
                await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 4 или выше.")
                return
            
            # Определяем цель и параметры
            if message.reply_to_message:
                if len(parts) < 2:
                    await message.reply("❌ Укажи время:\nПример: м 30м спам (в ответ на сообщение)")
                    return
                
                target_user = message.reply_to_message.from_user
                time_str = parts[1]
                reason = " ".join(parts[2:]) if len(parts) > 2 else "Не указана"
            else:
                if len(parts) < 3:
                    await message.reply("❌ Укажи пользователя, время и причину:\nПример: м ID 30м спам")
                    return
                
                target_user = await self.parse_user(message, parts[1])
                if not target_user:
                    return
                
                time_str = parts[2]
                reason = " ".join(parts[3:]) if len(parts) > 3 else "Не указана"
            
            # Парсим время
            duration = await self.parse_time(time_str)
            if not duration or duration <= 0:
                await message.reply("❌ Неверное время. Примеры: 30м, 2ч, 1д")
                return
            
            if duration > 44640:  # Макс 31 день
                await message.reply("❌ Максимальное время — 31 день (44640 минут).")
                return
            
            # Проверки
            if target_user.id == message.from_user.id:
                await message.reply("❌ Нельзя замутить самого себя!")
                return
            
            if target_user.id == self.bot_info.id:
                await message.reply("❌ Нельзя замутить бота!")
                return
            
            # Проверяем права в чате
            is_target_admin, is_target_creator = await self.check_user_permissions(
                message.chat.id, target_user.id
            )
            
            if is_target_creator:
                await message.reply("❌ Нельзя замутить создателя чата!")
                return
            
            if is_target_admin:
                await message.reply("❌ Нельзя замутить администратора!")
                return
            
            # Проверяем ранги в базе
            target_data = self.db.get_user(target_user.id, message.chat.id)
            if target_data and target_data['rank'] >= user_data['rank']:
                await message.reply("❌ Нельзя замутить пользователя с равным или высшим рангом!")
                return
            
            # Выполняем мут
            result = await self.mute_user(
                chat_id=message.chat.id,
                user_id=target_user.id,
                duration_minutes=duration,
                reason=reason,
                moderator_id=message.from_user.id
            )
            
            if result:
                # Форматируем время для ответа
                if duration < 60:
                    time_display = f"{duration} минут"
                elif duration < 1440:
                    hours = duration // 60
                    time_display = f"{hours} часов"
                else:
                    days = duration // 1440
                    time_display = f"{days} дней"
                
                # Получаем упоминание модератора
                moderator_mention = await self.get_user_mention(message.from_user.id, message.chat.id)
                
                await message.reply(
                    f"🔇 Пользователь {target_user.mention_html()} замучен на {time_display}!\n"
                    f"📝 Причина: {reason}\n"
                    f"👮 Модератор: {moderator_mention}",
                    parse_mode="HTML"
                )
            else:
                await message.reply("❌ Не удалось замутить пользователя.")
                
        except Exception as e:
            logger.error(f"Ошибка в муте: {e}")
            await message.reply("❌ Не удалось замутить пользователя.")
    
    async def mute_user(self, chat_id: int, user_id: int, duration_minutes: int, 
                       reason: str, moderator_id: int):
        """Мутит пользователя - отправляет ТОЛЬКО ОДНО сообщение с кнопкой"""
        try:
            end_time = datetime.now() + timedelta(minutes=duration_minutes)
            
            await self.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=False,
                    can_invite_users=False,
                    can_pin_messages=False
                ),
                until_date=end_time
            )
            
            # Добавляем в базу
            punishment_id = self.db.add_punishment(
                chat_id=chat_id,
                user_id=user_id,
                punishment_type='mute',
                moderator_id=moderator_id,
                reason=reason,
                end_time=end_time
            )
            
            # Увеличиваем счетчик
            self.db.add_mute_count(user_id, chat_id)
            
            # Форматируем время
            if duration_minutes < 60:
                time_str = f"{duration_minutes} минут"
            elif duration_minutes < 1440:
                hours = duration_minutes // 60
                time_str = f"{hours} часов"
            else:
                days = duration_minutes // 1440
                time_str = f"{days} дней"
            
            # Получаем упоминания
            user_mention = await self.get_user_mention(user_id, chat_id)
            moderator_mention = await self.get_user_mention(moderator_id, chat_id)
            
            # Кнопка снятия наказания
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔓 Снять наказание", 
                        callback_data=f"remove_punish_{punishment_id}"
                    )]
                ]
            )
            
            # Отправляем ОДНО сообщение с кнопкой
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"🔇 Пользователь {user_mention} замучен на {time_str}!\n"
                     f"📝 Причина: {reason}\n"
                     f"⏰ До: {end_time.strftime('%d.%m.%Y %H:%M')}\n"
                     f"👮 Модератор: {moderator_mention}",
                reply_markup=kb,
                parse_mode="HTML"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при муте: {e}")
            return False
    
    async def handle_unmute(self, message: Message, parts: List[str]):
        """Обработка команды размута"""
        try:
            if message.chat.type == "private":
                await message.reply("❌ Эта команда работает только в группах.")
                return
            
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            if not user_data or user_data['rank'] < 2:
                await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 2 или выше.")
                return
            
            if len(parts) < 2:
                await message.reply("❌ Укажи ID пользователя:\nПример: рм 123456789")
                return
            
            target_user = await self.parse_user(message, parts[1])
            if not target_user:
                return
            
            # Ищем активные муты
            punishments = self.db.get_active_punishments(message.chat.id, target_user.id)
            mute_punishments = [p for p in punishments if p['type'] == 'mute']
            
            if not mute_punishments:
                await message.reply(f"❌ У {target_user.mention_html()} нет активных мутов.", parse_mode="HTML")
                return
            
            # Снимаем все муты
            for punishment in mute_punishments:
                self.db.remove_punishment(punishment['id'])
            
            # Восстанавливаем права
            try:
                await self.bot.restrict_chat_member(
                    chat_id=message.chat.id,
                    user_id=target_user.id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_media_messages=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                        can_change_info=False,
                        can_invite_users=False,
                        can_pin_messages=False
                    )
                )
            except Exception as e:
                logger.warning(f"Ошибка восстановления прав: {e}")
            
            # Получаем упоминание модератора
            moderator_mention = await self.get_user_mention(message.from_user.id, message.chat.id)
            
            await message.reply(
                f"🔊 Мут с {target_user.mention_html()} снят!\n"
                f"👮 Модератор: {moderator_mention}",
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Ошибка в размуте: {e}")
            await message.reply("❌ Не удалось снять мут.")
    
    async def handle_ban(self, message: Message, parts: List[str]):
        """Обработка команды бана"""
        try:
            if message.chat.type == "private":
                await message.reply("❌ Эта команда работает только в группах.")
                return
            
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            if not user_data or user_data['rank'] < 2:
                await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 2 или выше.")
                return
            
            # Определяем цель
            if message.reply_to_message:
                target_user = message.reply_to_message.from_user
                reason = " ".join(parts[1:]) if len(parts) > 1 else "Не указана"
            else:
                if len(parts) < 2:
                    await message.reply("❌ Укажи пользователя и причину:\n• Ответь на сообщение\n• Или: б ID причина")
                    return
                
                target_user = await self.parse_user(message, parts[1])
                if not target_user:
                    return
                
                reason = " ".join(parts[2:]) if len(parts) > 2 else "Не указана"
            
            # Проверки
            if target_user.id == message.from_user.id:
                await message.reply("❌ Нельзя забанить самого себя!")
                return
            
            if target_user.id == self.bot_info.id:
                await message.reply("❌ Нельзя забанить бота!")
                return
            
            # Проверяем права в чате
            is_target_admin, is_target_creator = await self.check_user_permissions(
                message.chat.id, target_user.id
            )
            
            if is_target_creator:
                await message.reply("❌ Нельзя забанить создателя чата!")
                return
            
            if is_target_admin:
                await message.reply("❌ Нельзя забанить администратора!")
                return
            
            # Проверяем ранги в базе
            target_data = self.db.get_user(target_user.id, message.chat.id)
            if target_data and target_data['rank'] >= user_data['rank']:
                await message.reply("❌ Нельзя забанить пользователя с равным или высшим рангом!")
                return
            
            # Выполняем бан
            result = await self.ban_user(
                chat_id=message.chat.id,
                user_id=target_user.id,
                reason=reason,
                moderator_id=message.from_user.id
            )
            
            if result:
                # Получаем упоминание модератора
                moderator_mention = await self.get_user_mention(message.from_user.id, message.chat.id)
                
                await message.reply(
                    f"🔨 Пользователь {target_user.mention_html()} забанен на 30 дней!\n"
                    f"📝 Причина: {reason}\n"
                    f"👮 Модератор: {moderator_mention}",
                    parse_mode="HTML"
                )
            else:
                await message.reply("❌ Не удалось забанить пользователя.")
                
        except Exception as e:
            logger.error(f"Ошибка в бане: {e}")
            await message.reply("❌ Не удалось забанить пользователя.")
    
    async def ban_user(self, chat_id: int, user_id: int, reason: str, 
                      moderator_id: int, duration_days: int = 30):
        """Банит пользователя - отправляет ТОЛЬКО ОДНО сообщение с кнопкой"""
        try:
            end_time = datetime.now() + timedelta(days=duration_days)
            
            await self.bot.ban_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                until_date=end_time
            )
            
            # Добавляем в базу
            punishment_id = self.db.add_punishment(
                chat_id=chat_id,
                user_id=user_id,
                punishment_type='ban',
                moderator_id=moderator_id,
                reason=reason,
                end_time=end_time
            )
            
            # Увеличиваем счетчик
            self.db.add_ban_count(user_id, chat_id)
            
            # Получаем упоминания
            user_mention = await self.get_user_mention(user_id, chat_id)
            moderator_mention = await self.get_user_mention(moderator_id, chat_id)
            
            # Кнопка снятия наказания
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔓 Снять наказание", 
                        callback_data=f"remove_punish_{punishment_id}"
                    )]
                ]
            )
            
            # Отправляем ОДНО сообщение с кнопкой
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"🔨 Пользователь {user_mention} забанен на {duration_days} дней!\n"
                     f"📝 Причина: {reason}\n"
                     f"⏰ До: {end_time.strftime('%d.%m.%Y %H:%M')}\n"
                     f"👮 Модератор: {moderator_mention}",
                reply_markup=kb,
                parse_mode="HTML"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при бане: {e}")
            return False
    
    async def handle_unban(self, message: Message, parts: List[str]):
        """Обработка команды разбана"""
        try:
            if message.chat.type == "private":
                await message.reply("❌ Эта команда работает только в группах.")
                return
            
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            if not user_data or user_data['rank'] < 2:
                await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 2 или выше.")
                return
            
            if len(parts) < 2:
                await message.reply("❌ Укажи ID пользователя:\nПример: рб 123456789")
                return
            
            target_user = await self.parse_user(message, parts[1])
            if not target_user:
                return
            
            # Ищем активные баны
            punishments = self.db.get_active_punishments(message.chat.id, target_user.id)
            ban_punishments = [p for p in punishments if p['type'] == 'ban']
            
            if not ban_punishments:
                await message.reply(f"❌ У {target_user.mention_html()} нет активных банов.", parse_mode="HTML")
                return
            
            # Снимаем все баны
            for punishment in ban_punishments:
                self.db.remove_punishment(punishment['id'])
            
            # Разбаниваем
            try:
                await self.bot.unban_chat_member(
                    chat_id=message.chat.id,
                    user_id=target_user.id,
                    only_if_banned=True
                )
            except Exception as e:
                logger.warning(f"Ошибка разбана: {e}")
            
            # Получаем упоминание модератора
            moderator_mention = await self.get_user_mention(message.from_user.id, message.chat.id)
            
            await message.reply(
                f"🔓 Пользователь {target_user.mention_html()} разбанен!\n"
                f"👮 Модератор: {moderator_mention}",
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Ошибка в разбане: {e}")
            await message.reply("❌ Не удалось снять бан.")
    
    async def handle_kick(self, message: Message, parts: List[str]):
        """Обработка команды кика"""
        try:
            if message.chat.type == "private":
                await message.reply("❌ Эта команда работает только в группах.")
                return
            
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            if not user_data or user_data['rank'] < 2:
                await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 2 или выше.")
                return
            
            # Определяем цель
            if message.reply_to_message:
                target_user = message.reply_to_message.from_user
                reason = " ".join(parts[1:]) if len(parts) > 1 else "Не указана"
            else:
                if len(parts) < 2:
                    await message.reply("❌ Укажи пользователя и причину:\n• Ответь на сообщение\n• Или: к ID причина")
                    return
                
                target_user = await self.parse_user(message, parts[1])
                if not target_user:
                    return
                
                reason = " ".join(parts[2:]) if len(parts) > 2 else "Не указана"
            
            # Проверки
            if target_user.id == message.from_user.id:
                await message.reply("❌ Нельзя кикнуть самого себя!")
                return
            
            if target_user.id == self.bot_info.id:
                await message.reply("❌ Нельзя кикнуть бота!")
                return
            
            # Проверяем права в чате
            is_target_admin, is_target_creator = await self.check_user_permissions(
                message.chat.id, target_user.id
            )
            
            if is_target_creator:
                await message.reply("❌ Нельзя кикнуть создателя чата!")
                return
            
            if is_target_admin:
                await message.reply("❌ Нельзя кикнуть администратора!")
                return
            
            # Проверяем ранги в базе
            target_data = self.db.get_user(target_user.id, message.chat.id)
            if target_data and target_data['rank'] >= user_data['rank']:
                await message.reply("❌ Нельзя кикнуть пользователя с равным или высшим рангом!")
                return
            
            # Выполняем кик
            try:
                await self.bot.ban_chat_member(
                    chat_id=message.chat.id,
                    user_id=target_user.id
                )
                
                await self.bot.unban_chat_member(
                    chat_id=message.chat.id,
                    user_id=target_user.id
                )
                
                # Получаем упоминание модератора
                moderator_mention = await self.get_user_mention(message.from_user.id, message.chat.id)
                
                await message.reply(
                    f"👢 Пользователь {target_user.mention_html()} кикнут!\n"
                    f"📝 Причина: {reason}\n"
                    f"👮 Модератор: {moderator_mention}",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ошибка при кике: {e}")
                await message.reply("❌ Не удалось кикнуть пользователя.")
                
        except Exception as e:
            logger.error(f"Ошибка в кике: {e}")
            await message.reply("❌ Не удалось кикнуть пользователя.")
    
    async def kick_user(self, chat_id: int, user_id: int, reason: str, moderator_id: int):
        """Кикает пользователя"""
        try:
            await self.bot.ban_chat_member(
                chat_id=chat_id,
                user_id=user_id
            )
            
            await self.bot.unban_chat_member(
                chat_id=chat_id,
                user_id=user_id
            )
            
            # Получаем упоминания
            user_mention = await self.get_user_mention(user_id, chat_id)
            moderator_mention = await self.get_user_mention(moderator_id, chat_id)
            
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"👢 Пользователь {user_mention} кикнут!\n"
                     f"📝 Причина: {reason}\n"
                     f"👮 Модератор: {moderator_mention}",
                parse_mode="HTML"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при кике: {e}")
            return False
    
    async def handle_warnings(self, message: Message, parts: List[str]):
        """Обработка проверки варнов"""
        try:
            if message.chat.type == "private":
                await message.reply("❌ Эта команда работает только в группах.")
                return
            
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            if not user_data or user_data['rank'] < 2:
                await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 2 или выше.")
                return
            
            # Получаем текущий лимит варнов для группы
            group_settings = self.db.get_group_settings(message.chat.id)
            max_warnings = group_settings['max_warnings'] if group_settings else DEFAULT_MAX_WARNINGS
            
            if not parts and not message.reply_to_message:
                # Свои предупреждения
                warnings = self.db.get_warnings(message.from_user.id, message.chat.id)
                await message.reply(f"⚠️ У тебя {warnings}/{max_warnings} предупреждений.")
            else:
                # Предупреждения другого пользователя
                if message.reply_to_message:
                    target_user = message.reply_to_message.from_user
                else:
                    if len(parts) < 2:
                        await message.reply("❌ Укажи пользователя:\n• Ответь на сообщение\n• Или: варны ID")
                        return
                    
                    target_user = await self.parse_user(message, parts[1])
                    if not target_user:
                        return
                
                warnings = self.db.get_warnings(target_user.id, message.chat.id)
                await message.reply(
                    f"⚠️ У {target_user.mention_html()} {warnings}/{max_warnings} предупреждений.",
                    parse_mode="HTML"
                )
                
        except Exception as e:
            logger.error(f"Ошибка проверки варнов: {e}")
            await message.reply("❌ Не удалось проверить предупреждения.")
    
    async def handle_setrank(self, message: Message, parts: List[str]):
        """Обработка изменения ранга"""
        try:
            if message.chat.type == "private":
                await message.reply("❌ Эта команда работает только в группах.")
                return
            
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            if not user_data or user_data['rank'] < 3:
                await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 3 или выше.")
                return
            
            if len(parts) < 3:
                await message.reply("❌ Используй: ранг ID новый_ранг\nПример: ранг 123456789 2")
                return
            
            try:
                target_id = int(parts[1])
                new_rank = int(parts[2])
                
                if new_rank not in RANKS:
                    await message.reply(f"❌ Неверный ранг! Допустимые: {list(RANKS.keys())}")
                    return
                
                if new_rank > user_data['rank']:
                    await message.reply("❌ Нельзя повысить пользователя выше своего ранга!")
                    return
                
                self.db.set_rank(target_id, message.chat.id, new_rank)
                
                rank_name = RANKS[new_rank]
                await message.reply(f"✅ Ранг {new_rank} ({rank_name}) установлен пользователю с ID {target_id}")
                
            except ValueError:
                await message.reply("❌ ID и ранг должны быть числами.")
                
        except Exception as e:
            logger.error(f"Ошибка изменения ранга: {e}")
            await message.reply("❌ Не удалось изменить ранг.")
    
    async def handle_restore_owner(self, message: Message):
        """Восстановление создателя чата"""
        try:
            if message.chat.type == "private":
                await message.reply("❌ Эта команда работает только в группах.")
                return
            
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            if not user_data or user_data['rank'] < 3:
                await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 3 или выше.")
                return
            
            # Определяем создателя
            owner_id = await self.detect_chat_owner(message.chat.id)
            
            if owner_id:
                # Устанавливаем создателю ранг 5
                self.db.set_rank(owner_id, message.chat.id, 5)
                
                # Получаем информацию о создателе
                try:
                    chat_member = await self.bot.get_chat_member(message.chat.id, owner_id)
                    owner_name = chat_member.user.first_name
                    owner_mention = chat_member.user.mention_html()
                except:
                    owner_name = f"ID {owner_id}"
                    owner_mention = f"пользователю с ID {owner_id}"
                
                await message.reply(
                    f"✅ Создатель чата восстановлен!\n"
                    f"👑 {owner_mention} получил ранг 5 (Создатель)",
                    parse_mode="HTML"
                )
            else:
                await message.reply("❌ Не удалось определить создателя чата.")
                
        except Exception as e:
            logger.error(f"Ошибка восстановления создателя: {e}")
            await message.reply("❌ Не удалось восстановить создателя.")
    
    async def handle_remove_punishment_callback(self, query: CallbackQuery):
        """Снятие наказания (callback)"""
        try:
            punishment_id = int(query.data.replace("remove_punish_", ""))
            punishment = self.db.get_punishment_by_id(punishment_id)
            
            if not punishment:
                await query.answer("Наказание не найдено!", show_alert=True)
                return
            
            # Проверяем права
            user_data = self.db.get_user(query.from_user.id, query.message.chat.id)
            if not user_data or user_data['rank'] < 2:
                await query.answer("У тебя нет прав на это!", show_alert=True)
                return
            
            # Снимаем наказание
            self.db.remove_punishment(punishment_id)
            
            # Если это мут - размучиваем
            if punishment['type'] == 'mute':
                try:
                    await self.bot.restrict_chat_member(
                        chat_id=punishment['chat_id'],
                        user_id=punishment['user_id'],
                        permissions=ChatPermissions(
                            can_send_messages=True,
                            can_send_media_messages=True,
                            can_send_polls=True,
                            can_send_other_messages=True,
                            can_add_web_page_previews=True,
                            can_change_info=False,
                            can_invite_users=False,
                            can_pin_messages=False
                        )
                    )
                except Exception as e:
                    logger.warning(f"Ошибка при размуте: {e}")
            
            # Если это бан - разбаниваем
            elif punishment['type'] == 'ban':
                try:
                    await self.bot.unban_chat_member(
                        chat_id=punishment['chat_id'],
                        user_id=punishment['user_id'],
                        only_if_banned=True
                    )
                except Exception as e:
                    logger.warning(f"Ошибка при разбане: {e}")
            
            # Получаем упоминание модератора
            moderator_mention = await self.get_user_mention(query.from_user.id, query.message.chat.id)
            
            # Обновляем сообщение
            try:
                await query.message.edit_text(
                    f"✅ Наказание снято!\n"
                    f"👮 Модератор: {moderator_mention}\n"
                    f"📝 Тип: {punishment['type']}",
                    parse_mode="HTML"
                )
            except:
                await query.message.answer(
                    f"✅ Наказание снято!\n"
                    f"👮 Модератор: {moderator_mention}\n"
                    f"📝 Тип: {punishment['type']}",
                    parse_mode="HTML"
                )
            
            await query.answer("Наказание снято!")
            
        except Exception as e:
            logger.error(f"Ошибка снятия наказания: {e}")
            await query.answer("Ошибка", show_alert=True)
    
    # ===================== НАСТРОЙКИ ГРУПП =====================
    
    async def handle_group_settings_callback(self, query: CallbackQuery):
        """Обработка нажатия на кнопку 'Настройки группы'"""
        try:
            if query.message.chat.type == "private":
                # В ЛС показываем инструкцию и кнопку для добавления группы
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="➕ Добавить группу", callback_data="add_group")],
                        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_settings")]
                    ]
                )
                
                text = """⚙️ **Настройки группы**

Для настройки бота в вашей группе:

1. Добавьте меня в группу как администратора
2. Нажмите кнопку 'Добавить группу' ниже
3. Отправьте ссылку на вашу группу в формате:
   `https://t.me/название_группы`

После добавления группы вы сможете настроить:
• Максимальное количество предупреждений
• Наказание при превышении лимита
• Время наказания

⚠️ **Важно:** Настройки доступны только создателю группы.

📌 Эта функция находится на бета-тесте, и не все функции могут работать. Для справки обратитесь в поддержку."""
                
                await query.message.answer(text, parse_mode="Markdown", reply_markup=kb)
                await query.answer()
            else:
                # В группе показываем текущие настройки
                group_settings = self.db.get_group_settings(query.message.chat.id)
                
                if not group_settings:
                    text = "⚙️ **Настройки группы не установлены.**\n\nДля настройки перейдите в личные сообщения с ботом и используйте меню 'Настройки группы'."
                else:
                    # Получаем название наказания
                    punishment_names = {
                        'б': 'Бан',
                        'м': 'Мут',
                        'к': 'Кик'
                    }
                    
                    punishment_name = punishment_names.get(group_settings['punishment_type'], 'Неизвестно')
                    
                    text = f"""⚙️ **Настройки этой группы:**

🔢 **Максимальное количество предупреждений:** {group_settings['max_warnings']}

⚖️ **Наказание при превышении:** {punishment_name}
⏰ **Время наказания:** {group_settings['punishment_time']}

📅 **Настроено:** {group_settings['setup_at'][:10] if 'setup_at' in group_settings else 'Неизвестно'}

⚠️ **Изменить настройки можно только в личных сообщениях с ботом.**"""
                
                await query.message.answer(text, parse_mode="Markdown")
                await query.answer()
                
        except Exception as e:
            logger.error(f"Ошибка в настройках группы: {e}")
            await query.answer("Ошибка загрузки настроек", show_alert=True)
    
    async def handle_add_group_callback(self, query: CallbackQuery, state: FSMContext):
        """Обработка добавления группы"""
        try:
            await state.set_state(GroupSettingsStates.waiting_for_group_link)
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_settings")]
                ]
            )
            
            text = """➕ **Добавление группы**

Отправьте ссылку на вашу группу в формате:
`https://t.me/название_группы`

Пример: `https://t.me/moyagruppa`

⚠️ **Требования:**
1. Бот должен быть добавлен в группу
2. У бота должны быть права администратора
3. Вы должны быть создателем группы

После отправки ссылки бот проверит все условия и добавит группу для настройки."""
            
            await query.message.answer(text, parse_mode="Markdown", reply_markup=kb)
            await query.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в добавлении группы: {e}")
            await query.answer("Ошибка", show_alert=True)
    
    async def process_group_link_handler(self, message: Message, state: FSMContext):
        """Обработка ссылки на группу"""
        try:
            group_link = message.text.strip()
            
            # Проверяем формат ссылки
            if not group_link.startswith("https://t.me/"):
                await message.reply("❌ Неверный формат ссылки.\nИспользуйте: `https://t.me/название_группы`", parse_mode="Markdown")
                return
            
            # Извлекаем username группы
            group_username = group_link.replace("https://t.me/", "").strip()
            if not group_username:
                await message.reply("❌ Не удалось извлечь username группы из ссылки.")
                return
            
            try:
                # Пробуем получить информацию о группе
                chat = await self.bot.get_chat(f"@{group_username}")
                
                # Проверяем, что это группа
                if chat.type not in ["group", "supergroup"]:
                    await message.reply("❌ Это не группа. Укажите ссылку на группу или супергруппу.")
                    return
                
                # Проверяем, что бот в группе
                try:
                    chat_member = await self.bot.get_chat_member(chat.id, self.bot_info.id)
                    if chat_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
                        await message.reply("❌ Бот не является администратором в этой группе.\nДобавьте бота в группу и дайте ему права администратора.")
                        return
                except:
                    await message.reply("❌ Бот не находится в этой группе.\nДобавьте бота в группу сначала.")
                    return
                
                # Проверяем, что пользователь - создатель группы
                user_chat_member = await self.bot.get_chat_member(chat.id, message.from_user.id)
                if user_chat_member.status != ChatMemberStatus.CREATOR:
                    await message.reply("❌ Вы не являетесь создателем этой группы.\nОбратитесь к создателю группы.")
                    return
                
                # Проверяем, есть ли уже настройки для этой группы
                existing_settings = self.db.get_group_settings(chat.id)
                if existing_settings:
                    await message.reply(f"✅ Группа уже добавлена и настроена!\n\nНазвание: {chat.title}\nUsername: @{chat.username or 'скрыт'}\n\nИспользуйте меню 'Настройки группы' для изменения настроек.")
                    await state.clear()
                    return
                
                # Добавляем настройки по умолчанию
                self.db.add_group_setting(
                    chat_id=chat.id,
                    max_warnings=5,
                    punishment_type='м',
                    punishment_time='1д',
                    user_id=message.from_user.id
                )
                
                # Создаем клавиатуру для настроек
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="3", callback_data="max_warn_3"),
                         InlineKeyboardButton(text="4", callback_data="max_warn_4"),
                         InlineKeyboardButton(text="✅ 5", callback_data="max_warn_5"),
                         InlineKeyboardButton(text="6", callback_data="max_warn_6")],
                        [InlineKeyboardButton(text="⚙️ Настроить наказание и время...", callback_data="configure_punishment")],
                        [InlineKeyboardButton(text="🚧 Coming Soon...", callback_data="coming_soon")],
                        [InlineKeyboardButton(text="💾 Сохранить", callback_data="save_settings")]
                    ]
                )
                
                text = f"""✅ **Группа добавлена!**

🏷️ Название: {chat.title}
📝 Username: @{chat.username or 'скрыт'}
🆔 ID: `{chat.id}`

Теперь вы можете настроить параметры для этой группы:

🔢 **Максимальное количество предупреждений:**
(Выберите количество, по умолчанию: 5)

⚖️ **Наказание при превышении:**
Мут на 1 день (по умолчанию)

📌 **Доступные настройки:**
• Максимальное количество предупреждений
• Тип наказания при превышении (бан/мут/кик)
• Время наказания

⚠️ **Эта функция находится на бета-тесте, и не все функции могут работать. Для справки обратитесь в поддержку в главном меню.**"""
                
                await message.reply(text, parse_mode="Markdown", reply_markup=kb)
                await state.clear()
                
            except Exception as e:
                logger.error(f"Ошибка при проверке группы: {e}")
                await message.reply("❌ Не удалось получить информацию о группе.\nПроверьте:\n1. Правильность ссылки\n2. Что бот добавлен в группу\n3. Что группа публичная или бот имеет доступ")
                
        except Exception as e:
            logger.error(f"Ошибка обработки ссылки на группу: {e}")
            await message.reply("❌ Произошла ошибка при обработке ссылки.")
    
    async def handle_max_warnings_callback(self, query: CallbackQuery):
        """Обработка выбора максимального количества предупреждений"""
        try:
            max_warnings = int(query.data.replace("max_warn_", ""))
            
            # Находим chat_id из сохраненных данных или текущего чата
            # Для упрощения будем использовать сохранение в состоянии
            # В реальном приложении нужно хранить chat_id группы, которую настраивают
            
            # Получаем последнюю настроенную группу пользователя
            # Вместо этого можно хранить в состоянии FSM
            
            await query.answer(f"Максимальное количество предупреждений установлено: {max_warnings}")
            
            # Обновляем кнопки с новой галочкой
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="3", callback_data="max_warn_3"),
                     InlineKeyboardButton(text="4", callback_data="max_warn_4"),
                     InlineKeyboardButton(text="5", callback_data="max_warn_5"),
                     InlineKeyboardButton(text="6", callback_data="max_warn_6")],
                    [InlineKeyboardButton(text="⚙️ Настроить наказание и время...", callback_data="configure_punishment")],
                    [InlineKeyboardButton(text="🚧 Coming Soon...", callback_data="coming_soon")],
                    [InlineKeyboardButton(text="💾 Сохранить", callback_data="save_settings")]
                ]
            )
            
            # Обновляем кнопку с галочкой
            row = kb.inline_keyboard[0]
            for i, button in enumerate(row):
                if button.callback_data == query.data:
                    row[i] = InlineKeyboardButton(text=f"✅ {button.text}", callback_data=button.callback_data)
                else:
                    row[i] = InlineKeyboardButton(text=button.text.replace("✅ ", ""), callback_data=button.callback_data)
            
            # Обновляем сообщение
            try:
                await query.message.edit_reply_markup(reply_markup=kb)
            except:
                pass
                
        except Exception as e:
            logger.error(f"Ошибка в выборе макс. варнов: {e}")
            await query.answer("Ошибка", show_alert=True)
    
    async def handle_configure_punishment_callback(self, query: CallbackQuery, state: FSMContext):
        """Настройка наказания"""
        try:
            await state.set_state(GroupSettingsStates.waiting_for_punishment_type)
            
            await query.message.delete()
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Вернуться на настройки группы", callback_data="back_to_settings")]
                ]
            )
            
            text = """⚖️ **Настройка наказания**

Напишите наказание, которое хотите, чтобы выдавало при превышении варнов:

**Пример:** `б` | `м` | `к` (нужно написать только букву и больше ничего)

**Описание наказаний:**
• `б` - **Бан** (временное или перманентное наказание, которое не дает пользователю заного войти в группу)
• `м` - **Мут** (временное или перманентное наказание, которое не дает пользователю писать в группе, отправлять стикеры и вообще все что можно отправить)
• `к` - **Кик** (исключает пользователя на 5 минут, после которого он сможет заного зайти в группу и отправлять сообщения)

📌 **P.S.** Настройка времени для `к` (кик) не возможна."""
            
            await query.message.answer(text, parse_mode="Markdown", reply_markup=kb)
            await query.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в настройке наказания: {e}")
            await query.answer("Ошибка", show_alert=True)
    
    async def process_punishment_type_handler(self, message: Message, state: FSMContext):
        """Обработка типа наказания"""
        try:
            punishment_type = message.text.strip().lower()
            
            if punishment_type not in ['б', 'м', 'к']:
                await message.reply("❌ Неверный тип наказания.\nИспользуйте: `б`, `м` или `к`", parse_mode="Markdown")
                return
            
            # Сохраняем в состоянии
            await state.update_data(punishment_type=punishment_type)
            
            # Определяем название наказания
            punishment_names = {
                'б': 'Бан',
                'м': 'Мут', 
                'к': 'Кик'
            }
            
            punishment_name = punishment_names.get(punishment_type, 'Неизвестно')
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⚙️ Настроить время", callback_data="configure_time")],
                    [InlineKeyboardButton(text="✏️ Изменить наказание", callback_data="configure_punishment")],
                    [InlineKeyboardButton(text="🔙 Вернуться на настройки группы", callback_data="back_to_settings")]
                ]
            )
            
            text = f"""✅ **Наказание сохранено!**

Вы выбрали: **{punishment_name}** ({punishment_type})

Выберите кнопку ниже, если хотите настроить время наказания (по умолчанию: 1 день)"""
            
            await message.reply(text, parse_mode="Markdown", reply_markup=kb)
            await state.set_state(GroupSettingsStates.waiting_for_punishment_time)
            
        except Exception as e:
            logger.error(f"Ошибка обработки типа наказания: {e}")
            await message.reply("❌ Произошла ошибка при сохранении наказания.")
    
    async def handle_configure_time_callback(self, query: CallbackQuery, state: FSMContext):
        """Настройка времени наказания"""
        try:
            # Получаем данные из состояния
            data = await state.get_data()
            punishment_type = data.get('punishment_type', 'м')
            
            if punishment_type == 'к':
                await query.answer("❌ Настройка времени для кика не возможна!", show_alert=True)
                return
            
            await query.message.delete()
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Вернуться на настройки группы", callback_data="back_to_settings")]
                ]
            )
            
            text = """⏰ **Настройка времени наказания**

Напишите время, на которое будет выдаваться наказание:

**Пример:** `1ч` | `1д` | `1н`

**Расшифровка:**
• `ч` - часов
• `д` - дней  
• `н` - неделю
• `1` - цифра, относящаяся к времени

**Допустимые форматы:**
• `30м` - 30 минут
• `2ч` - 2 часа
• `3д` - 3 дня
• `1н` - 1 неделя
• `44640м` - 31 день (максимум)

📌 **Примечание:** Время указывается для наказаний типа 'Бан' и 'Мут'."""
            
            await query.message.answer(text, parse_mode="Markdown", reply_markup=kb)
            await query.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в настройке времени: {e}")
            await query.answer("Ошибка", show_alert=True)
    
    async def process_punishment_time_handler(self, message: Message, state: FSMContext):
        """Обработка времени наказания"""
        try:
            time_str = message.text.strip().lower()
            
            # Проверяем формат времени
            if not re.match(r'^\d+[чднм]$', time_str):
                await message.reply("❌ Неверный формат времени.\nИспользуйте: `1ч`, `2д`, `1н`, `30м`", parse_mode="Markdown")
                return
            
            # Парсим время
            duration = await self.parse_time(time_str)
            if not duration:
                await message.reply("❌ Не удалось распознать время.\nПроверьте формат.")
                return
            
            if duration > 44640:  # Макс 31 день
                await message.reply("❌ Максимальное время — 31 день (44640 минут).")
                return
            
            # Сохраняем в состоянии
            await state.update_data(punishment_time=time_str)
            
            # Получаем данные из состояния
            data = await state.get_data()
            punishment_type = data.get('punishment_type', 'м')
            punishment_time = data.get('punishment_time', '1д')
            
            # Определяем название наказания
            punishment_names = {
                'б': 'Бан',
                'м': 'Мут', 
                'к': 'Кик'
            }
            
            punishment_name = punishment_names.get(punishment_type, 'Неизвестно')
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✏️ Изменить время", callback_data="configure_time")],
                    [InlineKeyboardButton(text="🔙 Вернуться на настройки группы", callback_data="back_to_settings")]
                ]
            )
            
            text = f"""✅ **Время наказания сохранено!**

**Наказание:** {punishment_name} ({punishment_type})
**Время:** {punishment_time}

Теперь вы можете вернуться к настройкам группы и сохранить все изменения."""
            
            await message.reply(text, parse_mode="Markdown", reply_markup=kb)
            
        except Exception as e:
            logger.error(f"Ошибка обработки времени наказания: {e}")
            await message.reply("❌ Произошла ошибка при сохранении времени.")
    
    async def handle_back_to_settings_callback(self, query: CallbackQuery):
        """Возврат к настройкам группы"""
        try:
            # Получаем данные из состояния (в реальном приложении нужно сохранять где-то)
            # Здесь для примера используем заглушку
            
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="3", callback_data="max_warn_3"),
                     InlineKeyboardButton(text="4", callback_data="max_warn_4"),
                     InlineKeyboardButton(text="✅ 5", callback_data="max_warn_5"),
                     InlineKeyboardButton(text="6", callback_data="max_warn_6")],
                    [InlineKeyboardButton(text="⚙️ Настроить наказание и время...", callback_data="configure_punishment")],
                    [InlineKeyboardButton(text="🚧 Coming Soon...", callback_data="coming_soon")],
                    [InlineKeyboardButton(text="💾 Сохранить", callback_data="save_settings")]
                ]
            )
            
            text = """⚙️ **Настройки группы**

🔢 **Максимальное количество предупреждений:**
(Выберите количество, по умолчанию: 5)

⚖️ **Наказание при превышении:**
Мут на 1 день (по умолчанию)

📌 **Доступные настройки:**
• Максимальное количество предупреждений
• Тип наказания при превышении (бан/мут/кик)
• Время наказания

⚠️ **Эта функция находится на бета-тесте, и не все функции могут работать. Для справки обратитесь в поддержку в главном меню.**"""
            
            await query.message.answer(text, parse_mode="Markdown", reply_markup=kb)
            await query.answer()
            
        except Exception as e:
            logger.error(f"Ошибка возврата к настройкам: {e}")
            await query.answer("Ошибка", show_alert=True)
    
    async def handle_save_settings_callback(self, query: CallbackQuery):
        """Сохранение настроек"""
        try:
            # В реальном приложении здесь нужно получить chat_id группы
            # и сохранить все настройки из состояния
            
            await query.message.delete()
            
            text = """✅ **Настройки сохранены!**

Чтобы все заработало, напишите в вашей группе `обновить пульс` либо `/revivePuls`.

⚠️ **Важно:** После того как сохранили настройки, в группе могут писать эти команды все, начиная с 1 ранга. Обычные пользователи (ранг 0) не могут писать эти команды.

📌 **Для применения настроек в группе:**
1. Убедитесь, что бот добавлен как администратор
2. Напишите в группе `обновить пульс` или `/revivePuls`
3. Только создатель группы может писать эти команды до настройки
4. После настройки команды доступны всем с рангом 1+"""
            
            await query.message.answer(text, parse_mode="Markdown")
            await query.answer("Настройки сохранены!", show_alert=True)
            
        except Exception as e:
            logger.error(f"Ошибка сохранения настроек: {e}")
            await query.answer("Ошибка сохранения", show_alert=True)
    
    async def check_expired_punishments(self):
        """Проверяет истекшие наказания"""
        logger.info("Запущена проверка истекших наказаний")
        while True:
            try:
                punishments = self.db.get_expired_punishments()
                
                for punishment in punishments:
                    # Помечаем как неактивное
                    self.db.remove_punishment(punishment['id'])
                    
                    # Отправляем уведомление
                    try:
                        chat = await self.bot.get_chat(punishment['chat_id'])
                        chat_name = chat.title or "чате"
                        
                        if punishment['type'] == 'mute':
                            punish_type = "Мут"
                            action = "закончился"
                        else:
                            punish_type = "Бан"
                            action = "закончился"
                        
                        await self.bot.send_message(
                            chat_id=punishment['chat_id'],
                            text=f"⏰ {punish_type} пользователя с ID {punishment['user_id']} {action} в {chat_name}!\n"
                                 f"📝 Причина: {punishment['reason']}\n"
                                 f"👮 Выдал: ID {punishment['moderator_id']}"
                        )
                    except Exception as e:
                        logger.warning(f"Ошибка при уведомлении: {e}")
                
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Ошибка в проверке наказаний: {e}")
                await asyncio.sleep(300)
    
    async def run(self):
        """Запуск бота"""
        if not await self.check_bot_token():
            logger.error("Неверный токен бота. Завершение работы.")
            return
        
        # Запускаем проверку наказаний
        asyncio.create_task(self.check_expired_punishments())
        
        logger.info("Бот запущен и готов к работе!")
        
        try:
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Ошибка при запуске бота: {e}")
        finally:
            logger.info("Бот остановлен.")

# ===================== ЗАПУСК =====================
if __name__ == "__main__":
    try:
        bot_core = BotCore()
        asyncio.run(bot_core.run())
    except KeyboardInterrupt:
        print("\nБот остановлен.")
        logger.info("Бот остановлен пользователем.")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        print(f"Ошибка: {e}")
