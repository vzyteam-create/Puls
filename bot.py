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
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.exceptions import TelegramUnauthorizedError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = "ВАШ_ТОКЕН"
ADMIN_IDS = [ВАШ_ID]  # Замените на ваш ID
MAX_WARNINGS = 5

RANKS = {
    0: "👤 Участник",
    1: "👮 Младший модератор",
    2: "🛡️ Старший модератор",
    3: "👑 Администратор",
    4: "🌟 Продвинутый админ",
    5: "✨ СОЗДАТЕЛЬ"
}

# Картинка для приветствия
WELCOME_IMAGE = "https://img.freepik.com/free-photo/3d-render-handshake-icon-isolated_107791-15725.jpg"

# Триггеры "пульс" - 30 разных ответов
PULSE_TRIGGERS = [
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
    "🔥 Огненная мощь! Бот заряжен энергией!",
    "❄️ Холодный расчет! Все алгоритмы работают идеально!",
    "🌈 Мультиспектральный анализ! Все каналы открыты!",
    "🌪️ Вихрь активности! Бот в полной боевой готовности!",
    "🔄 Синхронизация завершена! Все процессы стабильны!",
    "🎪 Цирк технологий! Все трюки выполняются безупречно!",
    "⚗️ Химическая формула успеха! Все элементы сбалансированы!",
    "🎭 Драма завершена! Бот в главной роли работает идеально!",
    "🎰 Джекпот! Все системы выигрывают!",
    "🏆 Победа! Бот чемпион по стабильности!",
    "🎖️ Медали заслужил! Все награды за отличную работу!",
    "🚂 Полный вперед! Все вагоны прицеплены, поехали!",
    "🎸 Рок-н-ролл! Бот на сцене и гремит на весь чат!",
    "🍕 Пицца доставлена! Все ингредиенты свежие, бот работает!",
    "🎨 Шедевр создан! Все краски смешаны идеально!",
    "🌟 Звездный свет! Бот сияет ярче всех!",
    "🎮 Игра началась! Все уровни пройдены успешно!",
    "📡 Сигнал отличный! Связь стабильна на 100%!",
    "💎 Алмазная прочность! Ни одна ошибка не пройдет!",
    "🚁 Вертолетный обзор! Все под контролем с высоты!"
]

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
        self.conn.commit()

    def add_user(self, user_id: int, chat_id: int, username: str, first_name: str):
        """Добавляет пользователя в базу"""
        cur = self.conn.cursor()
        cur.execute('''INSERT OR IGNORE INTO users 
                      (user_id, chat_id, username, first_name) 
                      VALUES (?, ?, ?, ?)''',
                   (user_id, chat_id, username, first_name))
        self.conn.commit()

    def get_user(self, user_id: int, chat_id: int):
        """Получает информацию о пользователе"""
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM users WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        return cur.fetchone()

    def set_rank(self, user_id: int, chat_id: int, rank: int):
        """Устанавливает ранг пользователю"""
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET rank=? WHERE user_id=? AND chat_id=?''',
                   (rank, user_id, chat_id))
        self.conn.commit()

    def add_warning(self, user_id: int, chat_id: int):
        """Добавляет предупреждение"""
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
        """Получает количество предупреждений"""
        cur = self.conn.cursor()
        cur.execute('''SELECT warnings FROM users WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        result = cur.fetchone()
        return result['warnings'] if result else 0

    def reset_warnings(self, user_id: int, chat_id: int):
        """Сбрасывает предупреждения"""
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET warnings=0 WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        self.conn.commit()

    def add_mute_count(self, user_id: int, chat_id: int):
        """Увеличивает счетчик мутов"""
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET mutes = mutes + 1 
                      WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        self.conn.commit()

    def add_ban_count(self, user_id: int, chat_id: int):
        """Увеличивает счетчик банов"""
        cur = self.conn.cursor()
        cur.execute('''UPDATE users SET bans = bans + 1 
                      WHERE user_id=? AND chat_id=?''',
                   (user_id, chat_id))
        self.conn.commit()

    def set_rules(self, chat_id: int, text: str):
        """Устанавливает правила"""
        cur = self.conn.cursor()
        cur.execute('''INSERT OR REPLACE INTO rules (chat_id, text) 
                      VALUES (?, ?)''',
                   (chat_id, text))
        self.conn.commit()

    def get_rules(self, chat_id: int):
        """Получает правила"""
        cur = self.conn.cursor()
        cur.execute('''SELECT text FROM rules WHERE chat_id=?''', (chat_id,))
        result = cur.fetchone()
        return result['text'] if result else "Правила ещё не установлены. Используй /setrules текст"

    def add_punishment(self, chat_id: int, user_id: int, punishment_type: str, 
                      moderator_id: int, reason: str, end_time: datetime, 
                      message_id: int = None):
        """Добавляет наказание"""
        cur = self.conn.cursor()
        cur.execute('''INSERT INTO punishments 
                      (chat_id, user_id, type, moderator_id, reason, end_time, message_id) 
                      VALUES (?, ?, ?, ?, ?, ?, ?)''',
                   (chat_id, user_id, punishment_type, moderator_id, reason, 
                    end_time.isoformat(), message_id))
        self.conn.commit()
        return cur.lastrowid

    def get_active_punishments(self, chat_id: int, user_id: int):
        """Получает активные наказания"""
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM punishments 
                      WHERE chat_id=? AND user_id=? AND active=1 
                      ORDER BY end_time DESC''',
                   (chat_id, user_id))
        return cur.fetchall()

    def get_punishment_by_id(self, punishment_id: int):
        """Получает наказание по ID"""
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM punishments WHERE id=?''', (punishment_id,))
        return cur.fetchone()

    def remove_punishment(self, punishment_id: int):
        """Удаляет наказание"""
        cur = self.conn.cursor()
        cur.execute('''UPDATE punishments SET active=0 WHERE id=?''', (punishment_id,))
        self.conn.commit()

    def get_expired_punishments(self):
        """Получает истекшие наказания"""
        cur = self.conn.cursor()
        current_time = datetime.now().isoformat()
        cur.execute('''SELECT * FROM punishments 
                      WHERE active=1 AND end_time < ?''',
                   (current_time,))
        return cur.fetchall()

    def get_all_users_in_chat(self, chat_id: int):
        """Получает всех пользователей в чате"""
        cur = self.conn.cursor()
        cur.execute('''SELECT * FROM users WHERE chat_id=?''', (chat_id,))
        return cur.fetchall()

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
        """Проверка токена"""
        try:
            self.bot_info = await self.bot.get_me()
            logger.info(f"Бот запущен: @{self.bot_info.username}")
            return True
        except TelegramUnauthorizedError:
            logger.error("Неверный токен бота!")
            return False

    async def check_user_permissions(self, chat_id: int, user_id: int):
        """Проверяет права пользователя"""
        try:
            chat_member = await self.bot.get_chat_member(chat_id, user_id)
            is_admin = chat_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
            is_creator = chat_member.status == ChatMemberStatus.CREATOR
            return is_admin, is_creator
        except Exception as e:
            logger.error(f"Ошибка проверки прав: {e}")
            return False, False

    async def parse_user(self, message: Message, user_text: str = None):
        """Парсит пользователя"""
        try:
            # Если это ответ на сообщение
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
            
            # Если указан @username
            if user_text and user_text.startswith('@'):
                await message.reply("🤔 Я не могу найти пользователя по @username.\n\n"
                                  "Просто ответь на сообщение этого пользователя моей командой, или укажи его ID.")
                return None
            
            # Если ничего не указано
            await message.reply("🤔 Не понял, кого ты имеешь в виду.\n\n"
                              "Либо ответь на сообщение пользователя, либо укажи его ID.")
            return None
            
        except Exception as e:
            logger.error(f"Ошибка в parse_user: {e}")
            await message.reply("❌ Что-то пошло не так. Попробуй ещё раз.")
            return None

    def register_handlers(self):
        """Регистрация обработчиков"""

        # ===================== ХЭНДЛЕРЫ ДЛЯ ГРУПП =====================
        
        @self.router.message(F.chat.type.in_({"group", "supergroup"}))
        async def handle_group_message(message: Message):
            """Обработчик сообщений в группах"""
            try:
                user = message.from_user
                self.db.add_user(user.id, message.chat.id, 
                               user.username or "", user.first_name or "")
            except Exception as e:
                logger.error(f"Ошибка обработки группового сообщения: {e}")

        # ===================== ТРИГГЕРЫ =====================
        
        @self.router.message(F.text)
        async def handle_triggers(message: Message):
            """Обработчик всех триггеров"""
            if not message.text:
                return
            
            text = message.text.lower().strip()
            
            # Точное совпадение "пульс"
            if text == "пульс":
                response = random.choice(PULSE_TRIGGERS)
                await message.reply(response)
                return
            
            # Точное совпадение "обновить пульс"
            elif text == "обновить пульс":
                msg1 = await message.reply("🔄 Обновляю все изменения и бота...")
                await asyncio.sleep(0.8)
                await msg1.edit_text("✅ Все функции применены, бот работает нормально")
                return

        # ===================== КОМАНДЫ =====================

        # Команда /startpulse
        @self.router.message(Command("startpulse"))
        async def startpulse_command(message: Message):
            """Обновление пульса"""
            msg1 = await message.reply("🔄 Обновляю все изменения и бота...")
            await asyncio.sleep(0.8)
            await msg1.edit_text("✅ Все функции применены, бот работает нормально")

        # Приветствие
        @self.router.message(CommandStart())
        async def start_message(message: Message):
            """Приветствие с картинкой"""
            try:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="📜 Правила", callback_data="show_rules")],
                        [InlineKeyboardButton(text="🛠 Техподдержка", callback_data="support")]
                    ]
                )
                
                if message.chat.type == "private":
                    # В личных сообщениях
                    text = f"""👋 Привет, {message.from_user.first_name}!

Я — Puls Bot, помогаю управлять группами и чатами.

✨ Что я умею:
• Система рангов для участников
• Наказания (муты, баны, предупреждения)
• Автоматические проверки
• И многое другое

🎯 Просто напиши мне в группе:
• `пульс` — проверка работы
• `обновить пульс` — обновление систем

👑 Создатель: @vanezyyy
🛠 Поддержка: @VanezyPulsSupport

📖 Подробнее: /help"""
                    
                    try:
                        await self.bot.send_photo(
                            chat_id=message.chat.id,
                            photo=WELCOME_IMAGE,
                            caption=text,
                            reply_markup=kb
                        )
                    except:
                        await message.reply(text, reply_markup=kb)
                else:
                    # В группе
                    text = f"""👋 Привет, {message.from_user.first_name}!

Я — Puls Bot, теперь буду помогать управлять этой группой.

✨ Доступные команды в этом чате:
• `пульс` — проверка работы
• `обновить пульс` — обновление систем
• /help — все команды

👑 Создатель: @vanezyyy
🛠 Поддержка: @VanezyPulsSupport"""
                    
                    try:
                        await self.bot.send_photo(
                            chat_id=message.chat.id,
                            photo=WELCOME_IMAGE,
                            caption=text,
                            reply_markup=kb
                        )
                    except:
                        await message.reply(text, reply_markup=kb)
                        
            except Exception as e:
                logger.error(f"Ошибка в start_message: {e}")

        # Помощь
        @self.router.message(Command("help"))
        async def help_command(message: Message):
            """Справка по командам"""
            if message.chat.type == "private":
                help_text = """📖 **Помощь по командам:**

👋 **Для всех:**
/start — Показать приветствие
/profile — Твой профиль
/help — Эта справка

🎮 **Триггеры (в группах):**
• `пульс` — 30 разных ответов
• `обновить пульс` — обновление бота

👮 **Для модераторов (только в группах):**
/warn — Выдать предупреждение
/mute — Заглушить пользователя
/ban — Забанить пользователя
/kick — Кикнуть пользователя

⚙️ **Для администраторов (только в группах):**
/setrank — Изменить ранг
/setrules — Установить правила
/ranks — Список рангов

👑 Создатель: @vanezyyy
🛠 Поддержка: @VanezyPulsSupport"""
            else:
                help_text = """📖 **Доступные команды в этом чате:**

👋 **Для всех:**
/start — Показать приветствие
/profile — Твой профиль в этом чате
/rules — Правила чата

🎮 **Триггеры (просто напиши):**
• `пульс` — 30 разных ответов
• `обновить пульс` — обновление бота

👮 **Для модераторов (ранг 2+):**
/warn [ответ/ID] причина — Предупреждение
/mute [ответ/ID] время(м) причина — Мут
/ban [ответ/ID] причина — Бан
/kick [ответ/ID] причина — Кик
/unmute [ID] — Снять мут
/unban [ID] — Снять бан
/warnings [ответ/ID] — Проверить предупреждения

⚙️ **Для администраторов (ранг 3+):**
/setrank ID ранг — Изменить ранг
/setrules текст — Установить правила
/ranks — Список рангов
/users — Все пользователи чата

🔧 **Технические:**
/startpulse — Обновить системы бота

📌 **Как указывать пользователя:**
• Ответь на сообщение пользователя командой
• Или укажи его ID (например: /warn 123456789 причина)

👑 Создатель: @vanezyyy
🛠 Поддержка: @VanezyPulsSupport"""
            
            await message.reply(help_text, parse_mode="Markdown")

        # Профиль
        @self.router.message(Command("profile", "профиль"))
        async def profile_command(message: Message):
            """Профиль пользователя"""
            try:
                if message.chat.type == "private":
                    # В личных сообщениях
                    profile_text = f"""📊 **Твой профиль:**

👤 Имя: {message.from_user.first_name}
📛 Юзернейм: @{message.from_user.username or 'не указан'}
🆔 ID: `{message.from_user.id}`

ℹ️ **Информация:**
• Твой профиль в группах будет виден только там
• В каждой группе отдельный профиль
• Ранг и наказания сохраняются для каждого чата

📖 Используй /help для списка команд"""
                    
                    await message.reply(profile_text, parse_mode="Markdown")
                else:
                    # В группе
                    user_data = self.db.get_user(message.from_user.id, message.chat.id)
                    if user_data:
                        rank_name = RANKS.get(user_data['rank'], "Неизвестно")
                        profile_text = f"""📊 **Твой профиль в этом чате:**

👤 Имя: {user_data['first_name']}
📛 Юзернейм: @{user_data['username'] or 'не указан'}
🆔 ID: `{user_data['user_id']}`

🎖️ Ранг: {rank_name}
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
                        
                        await message.reply(profile_text, parse_mode="Markdown")
                    else:
                        await message.reply("🤔 Твой профиль ещё не создан в этом чате.\n"
                                          "Напиши что-нибудь в чат, и он появится автоматически.")
            except Exception as e:
                logger.error(f"Ошибка в profile_command: {e}")
                await message.reply("❌ Не удалось загрузить профиль.")

        # Правила
        @self.router.message(Command("rules"))
        async def show_rules_command(message: Message):
            """Показать правила"""
            try:
                if message.chat.type == "private":
                    await message.reply("ℹ️ Правила устанавливаются для каждого чата отдельно.\n"
                                      "В личных сообщениях правил нет.")
                    return
                
                rules = self.db.get_rules(message.chat.id)
                await message.reply(rules)
            except Exception as e:
                logger.error(f"Ошибка показа правил: {e}")
                await message.reply("❌ Не удалось загрузить правила.")

        # Установить правила
        @self.router.message(Command("setrules"))
        async def set_rules_command(message: Message, command: CommandObject):
            """Установить правила"""
            try:
                # Только в группах
                if message.chat.type == "private":
                    await message.reply("❌ Эта команда работает только в группах.")
                    return
                
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if not user_data or user_data['rank'] < 3:
                    await message.reply("❌ У тебя нет прав на эту команду.\n"
                                      "Нужен ранг 3 или выше.")
                    return
                
                if not command.args:
                    await message.reply("❌ Укажи текст правил:\n"
                                      "`/setrules здесь будут правила чата`")
                    return
                
                self.db.set_rules(message.chat.id, command.args)
                await message.reply("✅ Правила успешно обновлены!")
            except Exception as e:
                logger.error(f"Ошибка установки правил: {e}")
                await message.reply("❌ Не удалось установить правила.")

        # Предупреждение
        @self.router.message(Command("warn"))
        async def warn_command(message: Message, command: CommandObject):
            """Выдать предупреждение"""
            try:
                # Только в группах
                if message.chat.type == "private":
                    await message.reply("❌ Эта команда работает только в группах.")
                    return
                
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if not user_data or user_data['rank'] < 2:
                    await message.reply("❌ У тебя нет прав на эту команду.\n"
                                      "Нужен ранг 2 или выше.")
                    return
                
                # Получаем аргументы
                args = command.args or ""
                
                # Парсим пользователя
                if message.reply_to_message:
                    target_user = message.reply_to_message.from_user
                    reason = args
                else:
                    parts = args.split(maxsplit=1)
                    if len(parts) < 1:
                        await message.reply("❌ Укажи пользователя:\n"
                                          "• Ответь на сообщение этой командой\n"
                                          "• Или укажи ID: `/warn 123456789 причина`")
                        return
                    
                    target_user = await self.parse_user(message, parts[0])
                    if not target_user:
                        return
                    
                    reason = parts[1] if len(parts) > 1 else "Не указана"
                
                # Проверяем, что не сам себя
                if target_user.id == message.from_user.id:
                    await message.reply("❌ Нельзя выдать предупреждение самому себе!")
                    return
                
                # Проверяем, что не бота
                if target_user.id == self.bot_info.id:
                    await message.reply("❌ Нельзя наказывать бота!")
                    return
                
                # Проверяем права пользователя в чате
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
                    # Мут на 24 часа
                    end_time = datetime.now() + timedelta(hours=24)
                    await self.mute_user(
                        chat_id=message.chat.id,
                        user_id=target_user.id,
                        duration_minutes=1440,
                        reason=f"Автоматический мут за {MAX_WARNINGS} предупреждений",
                        moderator_id=message.from_user.id
                    )
                    
                    # Сбрасываем предупреждения
                    self.db.reset_warnings(target_user.id, message.chat.id)
                    
                    await message.reply(
                        f"🚨 Пользователь {target_user.mention_html()} получил {MAX_WARNINGS} предупреждений!\n"
                        f"🔇 Автоматически замучен на 24 часа.",
                        parse_mode="HTML"
                    )
                    
            except Exception as e:
                logger.error(f"Ошибка в warn_command: {e}")
                await message.reply("❌ Не удалось выдать предупреждение.")

        # Мут
        @self.router.message(Command("mute"))
        async def mute_command(message: Message, command: CommandObject):
            """Заглушить пользователя"""
            try:
                # Только в группах
                if message.chat.type == "private":
                    await message.reply("❌ Эта команда работает только в группах.")
                    return
                
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if not user_data or user_data['rank'] < 4:  # Только с 4 ранга
                    await message.reply("❌ У тебя нет прав на эту команду.\n"
                                      "Нужен ранг 4 или выше.")
                    return
                
                # Получаем аргументы
                args = command.args or ""
                
                # Парсим пользователя и параметры
                if message.reply_to_message:
                    target_user = message.reply_to_message.from_user
                    other_args = args.split(maxsplit=1)
                    if len(other_args) < 1:
                        await message.reply("❌ Укажи время:\n"
                                          "`/mute [ответ] 60 причина`")
                        return
                    
                    try:
                        duration = int(other_args[0])
                        reason = other_args[1] if len(other_args) > 1 else "Не указана"
                    except ValueError:
                        await message.reply("❌ Время должно быть числом (минуты).")
                        return
                else:
                    parts = args.split(maxsplit=2)
                    if len(parts) < 2:
                        await message.reply("❌ Укажи пользователя и время:\n"
                                          "• Ответь на сообщение\n"
                                          "• Или укажи ID: `/mute 123456789 60 причина`")
                        return
                    
                    target_user = await self.parse_user(message, parts[0])
                    if not target_user:
                        return
                    
                    try:
                        duration = int(parts[1])
                        reason = parts[2] if len(parts) > 2 else "Не указана"
                    except ValueError:
                        await message.reply("❌ Время должно быть числом (минуты).")
                        return
                
                # Проверяем, что не сам себя
                if target_user.id == message.from_user.id:
                    await message.reply("❌ Нельзя замутить самого себя!")
                    return
                
                # Проверяем, что не бота
                if target_user.id == self.bot_info.id:
                    await message.reply("❌ Нельзя замутить бота!")
                    return
                
                # Проверяем права пользователя в чате
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
                
                # Проверяем время
                if duration <= 0 or duration > 44640:  # Макс 31 день
                    await message.reply("❌ Время должно быть от 1 до 44640 минут (31 день).")
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
                    # Форматируем время
                    if duration < 60:
                        time_str = f"{duration} минут"
                    elif duration < 1440:
                        hours = duration // 60
                        time_str = f"{hours} часов"
                    else:
                        days = duration // 1440
                        time_str = f"{days} дней"
                    
                    await message.reply(
                        f"🔇 Пользователь {target_user.mention_html()} замучен на {time_str}!\n"
                        f"📝 Причина: {reason}\n"
                        f"👮 Модератор: {message.from_user.mention_html()}",
                        parse_mode="HTML"
                    )
                else:
                    await message.reply("❌ Не удалось замутить пользователя.")
                    
            except Exception as e:
                logger.error(f"Ошибка в mute_command: {e}")
                await message.reply("❌ Не удалось замутить пользователя.")

        # Размут
        @self.router.message(Command("unmute"))
        async def unmute_command(message: Message, command: CommandObject):
            """Снять мут"""
            try:
                # Только в группах
                if message.chat.type == "private":
                    await message.reply("❌ Эта команда работает только в группах.")
                    return
                
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if not user_data or user_data['rank'] < 2:
                    await message.reply("❌ У тебя нет прав на эту команду.\n"
                                      "Нужен ранг 2 или выше.")
                    return
                
                args = command.args or ""
                if not args:
                    await message.reply("❌ Укажи ID пользователя:\n"
                                      "`/unmute 123456789`")
                    return
                
                # Парсим пользователя
                target_user = await self.parse_user(message, args.strip())
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
                logger.error(f"Ошибка в unmute_command: {e}")
                await message.reply("❌ Не удалось снять мут.")

        # Бан
        @self.router.message(Command("ban"))
        async def ban_command(message: Message, command: CommandObject):
            """Забанить пользователя"""
            try:
                # Только в группах
                if message.chat.type == "private":
                    await message.reply("❌ Эта команда работает только в группах.")
                    return
                
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if not user_data or user_data['rank'] < 2:
                    await message.reply("❌ У тебя нет прав на эту команду.\n"
                                      "Нужен ранг 2 или выше.")
                    return
                
                # Получаем аргументы
                args = command.args or ""
                
                # Парсим пользователя
                if message.reply_to_message:
                    target_user = message.reply_to_message.from_user
                    reason = args
                else:
                    parts = args.split(maxsplit=1)
                    if len(parts) < 1:
                        await message.reply("❌ Укажи пользователя:\n"
                                          "• Ответь на сообщение\n"
                                          "• Или укажи ID: `/ban 123456789 причина`")
                        return
                    
                    target_user = await self.parse_user(message, parts[0])
                    if not target_user:
                        return
                    
                    reason = parts[1] if len(parts) > 1 else "Не указана"
                
                # Проверяем, что не сам себя
                if target_user.id == message.from_user.id:
                    await message.reply("❌ Нельзя забанить самого себя!")
                    return
                
                # Проверяем, что не бота
                if target_user.id == self.bot_info.id:
                    await message.reply("❌ Нельзя забанить бота!")
                    return
                
                # Проверяем права пользователя в чате
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
                logger.error(f"Ошибка в ban_command: {e}")
                await message.reply("❌ Не удалось забанить пользователя.")

        # Разбан
        @self.router.message(Command("unban"))
        async def unban_command(message: Message, command: CommandObject):
            """Снять бан"""
            try:
                # Только в группах
                if message.chat.type == "private":
                    await message.reply("❌ Эта команда работает только в группах.")
                    return
                
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if not user_data or user_data['rank'] < 2:
                    await message.reply("❌ У тебя нет прав на эту команду.\n"
                                      "Нужен ранг 2 или выше.")
                    return
                
                args = command.args or ""
                if not args:
                    await message.reply("❌ Укажи ID пользователя:\n"
                                      "`/unban 123456789`")
                    return
                
                # Парсим пользователя
                target_user = await self.parse_user(message, args.strip())
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
                logger.error(f"Ошибка в unban_command: {e}")
                await message.reply("❌ Не удалось снять бан.")

        # Кик
        @self.router.message(Command("kick"))
        async def kick_command(message: Message, command: CommandObject):
            """Кикнуть пользователя"""
            try:
                # Только в группах
                if message.chat.type == "private":
                    await message.reply("❌ Эта команда работает только в группах.")
                    return
                
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if not user_data or user_data['rank'] < 2:
                    await message.reply("❌ У тебя нет прав на эту команду.\n"
                                      "Нужен ранг 2 или выше.")
                    return
                
                # Получаем аргументы
                args = command.args or ""
                
                # Парсим пользователя
                if message.reply_to_message:
                    target_user = message.reply_to_message.from_user
                    reason = args
                else:
                    parts = args.split(maxsplit=1)
                    if len(parts) < 1:
                        await message.reply("❌ Укажи пользователя:\n"
                                          "• Ответь на сообщение\n"
                                          "• Или укажи ID: `/kick 123456789 причина`")
                        return
                    
                    target_user = await self.parse_user(message, parts[0])
                    if not target_user:
                        return
                    
                    reason = parts[1] if len(parts) > 1 else "Не указана"
                
                # Проверяем, что не сам себя
                if target_user.id == message.from_user.id:
                    await message.reply("❌ Нельзя кикнуть самого себя!")
                    return
                
                # Проверяем, что не бота
                if target_user.id == self.bot_info.id:
                    await message.reply("❌ Нельзя кикнуть бота!")
                    return
                
                # Проверяем права пользователя в чате
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
                logger.error(f"Ошибка в kick_command: {e}")
                await message.reply("❌ Не удалось кикнуть пользователя.")

        # Проверка предупреждений
        @self.router.message(Command("warnings"))
        async def warnings_command(message: Message, command: CommandObject):
            """Проверить предупреждения"""
            try:
                # Только в группах
                if message.chat.type == "private":
                    await message.reply("❌ Эта команда работает только в группах.")
                    return
                
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if not user_data or user_data['rank'] < 2:
                    await message.reply("❌ У тебя нет прав на эту команду.\n"
                                      "Нужен ранг 2 или выше.")
                    return
                
                args = command.args or ""
                
                if not args and not message.reply_to_message:
                    # Свои предупреждения
                    warnings = self.db.get_warnings(message.from_user.id, message.chat.id)
                    await message.reply(f"⚠️ У тебя {warnings}/{MAX_WARNINGS} предупреждений.")
                else:
                    # Предупреждения другого пользователя
                    if message.reply_to_message:
                        target_user = message.reply_to_message.from_user
                    else:
                        target_user = await self.parse_user(message, args.strip())
                        if not target_user:
                            return
                    
                    warnings = self.db.get_warnings(target_user.id, message.chat.id)
                    await message.reply(
                        f"⚠️ У {target_user.mention_html()} {warnings}/{MAX_WARNINGS} предупреждений.",
                        parse_mode="HTML"
                    )
                    
            except Exception as e:
                logger.error(f"Ошибка в warnings_command: {e}")
                await message.reply("❌ Не удалось проверить предупреждения.")

        # Изменить ранг
        @self.router.message(Command("setrank"))
        async def setrank_command(message: Message, command: CommandObject):
            """Изменить ранг пользователя"""
            try:
                # Только в группах
                if message.chat.type == "private":
                    await message.reply("❌ Эта команда работает только в группах.")
                    return
                
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if not user_data or user_data['rank'] < 3:
                    await message.reply("❌ У тебя нет прав на эту команду.\n"
                                      "Нужен ранг 3 или выше.")
                    return
                
                args = command.args or ""
                parts = args.split()
                
                if len(parts) != 2:
                    await message.reply("❌ Укажи ID и ранг:\n"
                                      "`/setrank 123456789 2`")
                    return
                
                try:
                    target_id = int(parts[0])
                    new_rank = int(parts[1])
                    
                    # Проверяем ранг
                    if new_rank not in RANKS:
                        await message.reply(f"❌ Неверный ранг! Допустимые: {list(RANKS.keys())}")
                        return
                    
                    # Нельзя повышать выше своего ранга
                    if new_rank > user_data['rank']:
                        await message.reply("❌ Нельзя повысить пользователя выше своего ранга!")
                        return
                    
                    # Запрашиваем подтверждение
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_rank_{target_id}_{new_rank}"),
                                InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_rank")
                            ]
                        ]
                    )
                    
                    rank_name = RANKS[new_rank]
                    await message.reply(
                        f"⚠️ Установить ранг {new_rank} ({rank_name}) пользователю с ID {target_id}?",
                        reply_markup=kb
                    )
                    
                except ValueError:
                    await message.reply("❌ ID и ранг должны быть числами.")
                    
            except Exception as e:
                logger.error(f"Ошибка в setrank_command: {e}")
                await message.reply("❌ Не удалось изменить ранг.")

        # Список рангов
        @self.router.message(Command("ranks"))
        async def ranks_command(message: Message):
            """Показать список рангов"""
            ranks_text = "🎖️ **Система рангов:**\n\n"
            for rank_num, rank_name in sorted(RANKS.items()):
                ranks_text += f"{rank_num} - {rank_name}\n"
            
            ranks_text += "\n**Права:**\n"
            ranks_text += "1+ - Просмотр профилей\n"
            ranks_text += "2+ - Варны, кики, размуты, разбаны\n"
            ranks_text += "3+ - Изменение рангов, правила\n"
            ranks_text += "4+ - Муты\n"
            ranks_text += "5 - Создатель (все права)"
            
            await message.reply(ranks_text, parse_mode="Markdown")

        # Список пользователей
        @self.router.message(Command("users"))
        async def users_command(message: Message):
            """Показать пользователей чата"""
            try:
                # Только в группах
                if message.chat.type == "private":
                    await message.reply("❌ Эта команда работает только в группах.")
                    return
                
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if not user_data or user_data['rank'] < 3:
                    await message.reply("❌ У тебя нет прав на эту команду.\n"
                                      "Нужен ранг 3 или выше.")
                    return
                
                users = self.db.get_all_users_in_chat(message.chat.id)
                
                if not users:
                    await message.reply("🤔 В базе пока нет пользователей.")
                    return
                
                # Группируем по рангам
                users_by_rank = {}
                for user in users:
                    rank = user['rank']
                    if rank not in users_by_rank:
                        users_by_rank[rank] = []
                    
                    username = f"@{user['username']}" if user['username'] else user['first_name']
                    users_by_rank[rank].append(f"{username} (ID: {user['user_id']})")
                
                # Формируем сообщение
                users_text = "👥 **Пользователи в этом чате:**\n\n"
                for rank_num in sorted(RANKS.keys(), reverse=True):
                    if rank_num in users_by_rank:
                        rank_name = RANKS[rank_num]
                        users_text += f"**{rank_name}:**\n"
                        for user_str in users_by_rank[rank_num]:
                            users_text += f"  • {user_str}\n"
                        users_text += "\n"
                
                # Отправляем
                if len(users_text) > 4000:
                    parts = [users_text[i:i+4000] for i in range(0, len(users_text), 4000)]
                    for part in parts:
                        await message.reply(part, parse_mode="Markdown")
                else:
                    await message.reply(users_text, parse_mode="Markdown")
                    
            except Exception as e:
                logger.error(f"Ошибка в users_command: {e}")
                await message.reply("❌ Не удалось показать пользователей.")

        # ===================== CALLBACK ОБРАБОТЧИКИ =====================
        
        # Показать правила
        @self.router.callback_query(F.data == "show_rules")
        async def show_rules_cb(query: types.CallbackQuery):
            try:
                if query.message.chat.type == "private":
                    await query.message.answer("ℹ️ Правила устанавливаются для каждого чата отдельно.\n"
                                             "В личных сообщениях правил нет.")
                else:
                    rules = self.db.get_rules(query.message.chat.id)
                    await query.message.answer(rules)
                await query.answer()
            except Exception as e:
                logger.error(f"Ошибка в show_rules_cb: {e}")
                await query.answer("Ошибка загрузки правил", show_alert=True)

        # Техподдержка
        @self.router.callback_query(F.data == "support")
        async def support_cb(query: types.CallbackQuery):
            try:
                text = ("💡 **Техническая поддержка**\n\n"
                        "✅ **Как правильно писать:**\n"
                        "• Привет, у меня проблема с функцией мьюта\n"
                        "• Здравствуйте, есть предложение по улучшению бота\n"
                        "• Добрый день, бот не отвечает на команды\n\n"
                        "❌ **Как НЕ надо писать:**\n"
                        "• привет\n"
                        "• жду ответа\n"
                        "• ...\n\n"
                        "👑 **Владелец:** @vanezyyy\n"
                        "🛠 **Поддержка:** @VanezyPulsSupport")
                await query.message.answer(text, parse_mode="Markdown")
                await query.answer()
            except Exception as e:
                logger.error(f"Ошибка в support_cb: {e}")
                await query.answer("Ошибка", show_alert=True)

        # Подтверждение изменения ранга
        @self.router.callback_query(F.data.startswith("confirm_rank_"))
        async def confirm_rank_cb(query: types.CallbackQuery):
            try:
                # Получаем данные из callback
                data = query.data.replace("confirm_rank_", "")
                target_id, new_rank = map(int, data.split("_"))
                
                # Проверяем права
                user_data = self.db.get_user(query.from_user.id, query.message.chat.id)
                if not user_data or user_data['rank'] < 3:
                    await query.answer("У тебя нет прав на это!", show_alert=True)
                    return
                
                # Устанавливаем ранг
                self.db.set_rank(target_id, query.message.chat.id, new_rank)
                
                rank_name = RANKS[new_rank]
                await query.message.edit_text(
                    f"✅ Ранг {new_rank} ({rank_name}) установлен пользователю с ID {target_id}"
                )
                await query.answer("Ранг изменён!")
                
            except Exception as e:
                logger.error(f"Ошибка в confirm_rank_cb: {e}")
                await query.answer("Ошибка", show_alert=True)

        # Отмена изменения ранга
        @self.router.callback_query(F.data == "cancel_rank")
        async def cancel_rank_cb(query: types.CallbackQuery):
            try:
                await query.message.edit_text("❌ Изменение ранга отменено.")
                await query.answer("Отменено")
            except Exception as e:
                logger.error(f"Ошибка в cancel_rank_cb: {e}")
                await query.answer("Ошибка", show_alert=True)

        # Снятие наказания
        @self.router.callback_query(F.data.startswith("remove_punish_"))
        async def remove_punishment_cb(query: types.CallbackQuery):
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
                logger.error(f"Ошибка в remove_punishment_cb: {e}")
                await query.answer("Ошибка", show_alert=True)

    # ===================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====================
    
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
            
            # Кнопка снятия наказания
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
            
            # Кнопка снятия наказания
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

    async def check_expired_punishments(self):
        """Проверяет истекшие наказания"""
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
                        
                        # Формируем тип наказания
                        if punishment['type'] == 'mute':
                            punish_type = "Мут"
                            action = "закончился"
                        else:
                            punish_type = "Бан"
                            action = "закончился"
                        
                        # Отправляем в чат
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
        
        logger.info("Бот запущен!")
        
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
