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
from typing import Optional, List, Tuple, Dict
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
ADMIN_IDS = [6708209142]
MAX_WARNINGS = 5

RANKS = {
    0: "👤 Участник",
    1: "👮 Младший модератор", 
    2: "🛡️ Старший модератор",
    3: "👑 Администратор",
    4: "🌟 Продвинутый админ",
    5: "✨ СОЗДАТЕЛЬ"
}

# ===================== ЛОГИ =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ===================== БАЗА ДАННЫХ =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("bot.db", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()
        logger.info("База данных подключена")

    def create_tables(self):
        cur = self.conn.cursor()
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
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, chat_id)
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS rules (
            chat_id INTEGER PRIMARY KEY,
            text TEXT
        )''')
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
        cur.execute('''CREATE TABLE IF NOT EXISTS chat_owners (
            chat_id INTEGER PRIMARY KEY,
            owner_id INTEGER,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        self.conn.commit()

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

    def register_handlers(self):
        """Регистрация всех обработчиков"""
        
        # ===================== КОМАНДЫ СО СЛЕШОМ =====================
        
        @self.router.message(CommandStart())
        async def start_command(message: Message):
            await self.handle_start(message)
        
        @self.router.message(Command("startpulse"))
        async def startpulse_command(message: Message):
            await self.handle_startpulse(message)
        
        # ===================== ОБРАБОТКА СООБЩЕНИЙ В ГРУППАХ =====================
        
        @self.router.message(F.chat.type.in_({"group", "supergroup"}))
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
                
                # Обрабатываем команды без слеша
                if message.text:
                    await self.handle_command_without_slash(message)
                    
            except Exception as e:
                logger.error(f"Ошибка обработки группового сообщения: {e}")
        
        # ===================== CALLBACK ОБРАБОТЧИКИ =====================
        
        @self.router.callback_query(F.data == "show_rules")
        async def show_rules_cb(query: CallbackQuery):
            await self.handle_show_rules(query)
        
        @self.router.callback_query(F.data == "support")
        async def support_cb(query: CallbackQuery):
            await self.handle_support(query)
        
        @self.router.callback_query(F.data == "help")
        async def help_cb(query: CallbackQuery):
            await self.handle_help_callback(query)
        
        @self.router.callback_query(F.data == "channel")
        async def channel_cb(query: CallbackQuery):
            await self.handle_channel_callback(query)
        
        @self.router.callback_query(F.data == "bot_rules")
        async def bot_rules_cb(query: CallbackQuery):
            await self.handle_bot_rules_callback(query)
        
        @self.router.callback_query(F.data.startswith("remove_punish_"))
        async def remove_punishment_cb(query: CallbackQuery):
            await self.handle_remove_punishment(query)
        
        # ===================== ТРИГГЕРЫ =====================
        
        @self.router.message(F.text)
        async def handle_text_messages(message: Message):
            """Обработчик текстовых сообщений"""
            if not message.text:
                return
                
            text = message.text.strip().lower()
            
            # Триггеры (не команды)
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
                msg1 = await message.reply("🔄 Обновляю все изменения и бота...")
                await asyncio.sleep(0.8)
                await msg1.edit_text("✅ Все функции применены, бот работает нормально")
                return
            
            # Обработка команд без слеша (только в группах)
            if message.chat.type in ["group", "supergroup"]:
                await self.handle_command_without_slash(message)
    
    async def detect_chat_owner(self, chat_id: int):
        """Определяет создателя чата"""
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
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📜 Правила чата", callback_data="show_rules"),
                 InlineKeyboardButton(text="🛠 Техподдержка", callback_data="support")],
                [InlineKeyboardButton(text="📖 Помощь по командам", callback_data="help")],
                [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/VanezyScripts"),
                 InlineKeyboardButton(text="📋 Правила бота", callback_data="bot_rules")]
            ]
        )
        
        if message.chat.type == "private":
            text = f"""👋 Привет, {message.from_user.first_name}!

Рад тебя видеть! Я — Puls Bot, твой помощник в управлении группами и чатами.

✨ Что я умею:
• Управление участниками
• Система рангов
• Наказания (муты, баны, предупреждения)
• Автоматические функции

🎮 **Основные команды (просто напиши в чат):**
• `пульс` — проверка работы бота
• `обновить пульс` — обновление всех систем
• `помощь` — все доступные команды

Для работы в группе просто добавь меня туда и дай права администратора!

Нажимай на кнопки ниже, чтобы узнать больше ⬇️"""
        else:
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

👮 **Модерация:**
• `м 30м причина` — мут на 30 минут
• `б причина` — бан  
• `к причина` — кик
• `в причина` — предупреждение

Не забудь подписаться на наш канал с обновлениями! ⬇️"""
        
        await message.reply(text, reply_markup=kb)
    
    async def handle_startpulse(self, message: Message):
        """Обработка /startpulse"""
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/VanezyScripts"),
                 InlineKeyboardButton(text="📖 Помощь", callback_data="help")]
            ]
        )
        
        msg1 = await message.reply("🔄 Обновляю все изменения и бота...")
        await asyncio.sleep(0.8)
        await msg1.edit_text("✅ Все функции применены, бот работает нормально", reply_markup=kb)
    
    async def handle_command_without_slash(self, message: Message):
        """Обработка команд без слеша"""
        text = message.text.strip().lower()
        
        # Разбиваем на части
        parts = text.split(maxsplit=3)
        command = parts[0].lower()
        
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

⚠️ Предупреждения: {user_data['warnings']}/{MAX_WARNINGS}
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
• `/startpulse` — обновление бота

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
• `/startpulse` — обновление бота

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
• `/startpulse` — обновление бота

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
• `/startpulse` — обновление бота

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
    
    async def handle_rules(self, message: Message):
        """Показать правила"""
        try:
            if message.chat.type == "private":
                await message.reply("ℹ️ Правила устанавливаются для каждого чата отдельно.\nВ личных сообщениях правил нет.")
                return
            
            rules = self.db.get_rules(message.chat.id)
            await message.reply(rules)
        except Exception as e:
            logger.error(f"Ошибка показа правил: {e}")
            await message.reply("❌ Не удалось загрузить правила.")
    
    async def handle_setrules(self, message: Message, text: str):
        """Установить правила"""
        try:
            if message.chat.type == "private":
                await message.reply("❌ Эта команда работает только в группах.")
                return
            
            user_data = self.db.get_user(message.from_user.id, message.chat.id)
            if not user_data or user_data['rank'] < 3:
                await message.reply("❌ У тебя нет прав на эту команду.\nНужен ранг 3 или выше.")
                return
            
            self.db.set_rules(message.chat.id, text)
            await message.reply("✅ Правила успешно обновлены!")
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
        ranks_text += "1+ - Просмотр профилей\n"
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
    
    # Остальные методы (handle_warn, handle_mute, handle_unmute, handle_ban, handle_unban, 
    # handle_kick, handle_warnings, handle_setrank, parse_user, parse_time) остаются такими же
    # как в предыдущем коде, только без добавления кнопок в наказания
    
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
            
            # Добавляем предупреждение
            warnings = self.db.add_warning(target_user.id, message.chat.id)
            
            await message.reply(
                f"⚠️ Пользователю {target_user.mention_html()} выдано предупреждение!\n"
                f"📝 Причина: {reason}\n"
                f"🔢 Предупреждений: {warnings}/{MAX_WARNINGS}\n"
                f"👮 Модератор: {message.from_user.mention_html()}",
                parse_mode="HTML"
            )
            
            # Проверяем лимит предупреждений
            if warnings >= MAX_WARNINGS:
                end_time = datetime.now() + timedelta(hours=24)
                await self.mute_user(
                    chat_id=message.chat.id,
                    user_id=target_user.id,
                    duration_minutes=1440,
                    reason=f"Автоматический мут за {MAX_WARNINGS} предупреждений",
                    moderator_id=message.from_user.id
                )
                
                self.db.reset_warnings(target_user.id, message.chat.id)
                
                await message.reply(
                    f"🚨 Пользователь {target_user.mention_html()} получил {MAX_WARNINGS} предупреждений!\n"
                    f"🔇 Автоматически замучен на 24 часа.",
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
                
                await message.reply(
                    f"🔇 Пользователь {target_user.mention_html()} замучен на {time_display}!\n"
                    f"📝 Причина: {reason}\n"
                    f"👮 Модератор: {message.from_user.mention_html()}",
                    parse_mode="HTML"
                )
            else:
                await message.reply("❌ Не удалось замутить пользователя.")
                
        except Exception as e:
            logger.error(f"Ошибка в муте: {e}")
            await message.reply("❌ Не удалось замутить пользователя.")
    
    async def mute_user(self, chat_id: int, user_id: int, duration_minutes: int, 
                       reason: str, moderator_id: int):
        """Мутит пользователя"""
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
            
            # Кнопка снятия наказания (только для наказаний)
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔓 Снять наказание", 
                        callback_data=f"remove_punish_{punishment_id}"
                    )]
                ]
            )
            
            # Форматируем время
            if duration_minutes < 60:
                time_str = f"{duration_minutes} минут"
            elif duration_minutes < 1440:
                hours = duration_minutes // 60
                time_str = f"{hours} часов"
            else:
                days = duration_minutes // 1440
                time_str = f"{days} дней"
            
            # Отправляем уведомление
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"🔇 Пользователь замучен на {time_str}!\n"
                     f"📝 Причина: {reason}\n"
                     f"⏰ До: {end_time.strftime('%d.%m.%Y %H:%M')}\n"
                     f"👮 Модератор ID: {moderator_id}",
                reply_markup=kb
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
            
            await message.reply(
                f"🔊 Мут с {target_user.mention_html()} снят!\n"
                f"👮 Модератор: {message.from_user.mention_html()}",
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
                await message.reply(
                    f"🔨 Пользователь {target_user.mention_html()} забанен на 30 дней!\n"
                    f"📝 Причина: {reason}\n"
                    f"👮 Модератор: {message.from_user.mention_html()}",
                    parse_mode="HTML"
                )
            else:
                await message.reply("❌ Не удалось забанить пользователя.")
                
        except Exception as e:
            logger.error(f"Ошибка в бане: {e}")
            await message.reply("❌ Не удалось забанить пользователя.")
    
    async def ban_user(self, chat_id: int, user_id: int, reason: str, 
                      moderator_id: int, duration_days: int = 30):
        """Банит пользователя"""
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
            
            # Кнопка снятия наказания (только для наказаний)
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔓 Снять наказание", 
                        callback_data=f"remove_punish_{punishment_id}"
                    )]
                ]
            )
            
            # Отправляем уведомление
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"🔨 Пользователь забанен на {duration_days} дней!\n"
                     f"📝 Причина: {reason}\n"
                     f"⏰ До: {end_time.strftime('%d.%m.%Y %H:%M')}\n"
                     f"👮 Модератор ID: {moderator_id}",
                reply_markup=kb
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
            
            await message.reply(
                f"🔓 Пользователь {target_user.mention_html()} разбанен!\n"
                f"👮 Модератор: {message.from_user.mention_html()}",
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
                
                await message.reply(
                    f"👢 Пользователь {target_user.mention_html()} кикнут!\n"
                    f"📝 Причина: {reason}\n"
                    f"👮 Модератор: {message.from_user.mention_html()}",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ошибка при кике: {e}")
                await message.reply("❌ Не удалось кикнуть пользователя.")
                
        except Exception as e:
            logger.error(f"Ошибка в кике: {e}")
            await message.reply("❌ Не удалось кикнуть пользователя.")
    
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
            
            if not parts and not message.reply_to_message:
                # Свои предупреждения
                warnings = self.db.get_warnings(message.from_user.id, message.chat.id)
                await message.reply(f"⚠️ У тебя {warnings}/{MAX_WARNINGS} предупреждений.")
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
                    f"⚠️ У {target_user.mention_html()} {warnings}/{MAX_WARNINGS} предупреждений.",
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
    
    async def handle_show_rules(self, query: CallbackQuery):
        """Показать правила (callback)"""
        try:
            if query.message.chat.type == "private":
                await query.message.answer("ℹ️ Правила устанавливаются для каждого чата отдельно.\nВ личных сообщениях правил нет.")
            else:
                rules = self.db.get_rules(query.message.chat.id)
                await query.message.answer(rules)
            await query.answer()
        except Exception as e:
            logger.error(f"Ошибка показа правил (callback): {e}")
            await query.answer("Ошибка загрузки правил", show_alert=True)
    
    async def handle_support(self, query: CallbackQuery):
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
    
    async def handle_remove_punishment(self, query: CallbackQuery):
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
            
            # Обновляем сообщение
            try:
                await query.message.edit_text(
                    f"✅ Наказание снято!\n"
                    f"👮 Модератор: {query.from_user.mention_html()}\n"
                    f"📝 Тип: {punishment['type']}",
                    parse_mode="HTML"
                )
            except:
                await query.message.answer(
                    f"✅ Наказание снято!\n"
                    f"👮 Модератор: {query.from_user.mention_html()}\n"
                    f"📝 Тип: {punishment['type']}",
                    parse_mode="HTML"
                )
            
            await query.answer("Наказание снято!")
            
        except Exception as e:
            logger.error(f"Ошибка снятия наказания: {e}")
            await query.answer("Ошибка", show_alert=True)
    
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
        
        self.register_handlers()
        
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
