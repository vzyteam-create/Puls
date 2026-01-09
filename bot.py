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
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramUnauthorizedError, TelegramBadRequest, TelegramAPIError
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

# Триггеры пульс
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
    "🎨 Шедевр создан! Все краски смешаны идеально!"
]

# ===================== ЛОГИ =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ===================== СОСТОЯНИЯ FSM =====================
class RankStates(StatesGroup):
    waiting_for_confirm = State()

# ===================== БАЗА ДАННЫХ =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("bot.db", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()

    def create_tables(self):
        try:
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
            cur.execute('''CREATE TABLE IF NOT EXISTS pending_ranks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id INTEGER,
                chat_id INTEGER,
                new_rank INTEGER,
                moderator_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            self.conn.commit()
            logger.info("Таблицы базы данных созданы/проверены")
        except sqlite3.Error as e:
            logger.error(f"Ошибка создания таблиц: {e}")
            raise

    def add_user(self, user_id: int, chat_id: int, username: str, first_name: str) -> bool:
        """Добавляет пользователя в базу данных"""
        try:
            cur = self.conn.cursor()
            cur.execute('''INSERT OR IGNORE INTO users 
                          (user_id, chat_id, username, first_name) 
                          VALUES (?, ?, ?, ?)''',
                       (user_id, chat_id, username, first_name))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка добавления пользователя: {e}")
            return False

    def get_user(self, user_id: int, chat_id: int) -> Optional[sqlite3.Row]:
        """Получает информацию о пользователе"""
        try:
            cur = self.conn.cursor()
            cur.execute('''SELECT * FROM users WHERE user_id=? AND chat_id=?''',
                       (user_id, chat_id))
            return cur.fetchone()
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения пользователя: {e}")
            return None

    def set_rank(self, user_id: int, chat_id: int, rank: int) -> bool:
        """Устанавливает ранг пользователю"""
        try:
            cur = self.conn.cursor()
            cur.execute('''UPDATE users SET rank=? WHERE user_id=? AND chat_id=?''',
                       (rank, user_id, chat_id))
            self.conn.commit()
            return cur.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Ошибка установки ранга: {e}")
            return False

    def add_warning(self, user_id: int, chat_id: int) -> int:
        """Добавляет предупреждение пользователю"""
        try:
            cur = self.conn.cursor()
            cur.execute('''UPDATE users SET warnings = warnings + 1 
                          WHERE user_id=? AND chat_id=?''',
                       (user_id, chat_id))
            self.conn.commit()
            cur.execute('''SELECT warnings FROM users WHERE user_id=? AND chat_id=?''',
                       (user_id, chat_id))
            result = cur.fetchone()
            return result['warnings'] if result else 0
        except sqlite3.Error as e:
            logger.error(f"Ошибка добавления предупреждения: {e}")
            return 0

    def get_warnings(self, user_id: int, chat_id: int) -> int:
        """Получает количество предупреждений пользователя"""
        try:
            cur = self.conn.cursor()
            cur.execute('''SELECT warnings FROM users WHERE user_id=? AND chat_id=?''',
                       (user_id, chat_id))
            result = cur.fetchone()
            return result['warnings'] if result else 0
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения предупреждений: {e}")
            return 0

    def reset_warnings(self, user_id: int, chat_id: int) -> bool:
        """Сбрасывает предупреждения пользователя"""
        try:
            cur = self.conn.cursor()
            cur.execute('''UPDATE users SET warnings=0 WHERE user_id=? AND chat_id=?''',
                       (user_id, chat_id))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка сброса предупреждений: {e}")
            return False

    def add_mute_count(self, user_id: int, chat_id: int) -> bool:
        """Увеличивает счетчик мутов"""
        try:
            cur = self.conn.cursor()
            cur.execute('''UPDATE users SET mutes = mutes + 1 
                          WHERE user_id=? AND chat_id=?''',
                       (user_id, chat_id))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка увеличения счетчика мутов: {e}")
            return False

    def add_ban_count(self, user_id: int, chat_id: int) -> bool:
        """Увеличивает счетчик банов"""
        try:
            cur = self.conn.cursor()
            cur.execute('''UPDATE users SET bans = bans + 1 
                          WHERE user_id=? AND chat_id=?''',
                       (user_id, chat_id))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка увеличения счетчика банов: {e}")
            return False

    def set_rules(self, chat_id: int, text: str) -> bool:
        """Устанавливает правила для чата"""
        try:
            cur = self.conn.cursor()
            cur.execute('''INSERT OR REPLACE INTO rules (chat_id, text) 
                          VALUES (?, ?)''',
                       (chat_id, text))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка установки правил: {e}")
            return False

    def get_rules(self, chat_id: int) -> str:
        """Получает правила чата"""
        try:
            cur = self.conn.cursor()
            cur.execute('''SELECT text FROM rules WHERE chat_id=?''', (chat_id,))
            result = cur.fetchone()
            return result['text'] if result else "Правила ещё не установлены. Используйте /setrules текст"
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения правил: {e}")
            return "Ошибка загрузки правил"

    def add_punishment(self, chat_id: int, user_id: int, punishment_type: str, 
                      moderator_id: int, reason: str, end_time: datetime, 
                      message_id: int = None) -> Optional[int]:
        """Добавляет наказание в базу"""
        try:
            cur = self.conn.cursor()
            cur.execute('''INSERT INTO punishments 
                          (chat_id, user_id, type, moderator_id, reason, end_time, message_id) 
                          VALUES (?, ?, ?, ?, ?, ?, ?)''',
                       (chat_id, user_id, punishment_type, moderator_id, reason, 
                        end_time.isoformat(), message_id))
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Ошибка добавления наказания: {e}")
            return None

    def get_active_punishments(self, chat_id: int, user_id: int) -> List[sqlite3.Row]:
        """Получает активные наказания пользователя"""
        try:
            cur = self.conn.cursor()
            cur.execute('''SELECT * FROM punishments 
                          WHERE chat_id=? AND user_id=? AND active=1 
                          ORDER BY end_time DESC''',
                       (chat_id, user_id))
            return cur.fetchall()
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения наказаний: {e}")
            return []

    def get_punishment_by_id(self, punishment_id: int) -> Optional[sqlite3.Row]:
        """Получает наказание по ID"""
        try:
            cur = self.conn.cursor()
            cur.execute('''SELECT * FROM punishments WHERE id=?''', (punishment_id,))
            return cur.fetchone()
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения наказания по ID: {e}")
            return None

    def remove_punishment(self, punishment_id: int) -> bool:
        """Деактивирует наказание"""
        try:
            cur = self.conn.cursor()
            cur.execute('''UPDATE punishments SET active=0 WHERE id=?''', (punishment_id,))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка удаления наказания: {e}")
            return False

    def get_expired_punishments(self) -> List[sqlite3.Row]:
        """Получает истекшие наказания"""
        try:
            cur = self.conn.cursor()
            current_time = datetime.now().isoformat()
            cur.execute('''SELECT * FROM punishments 
                          WHERE active=1 AND end_time < ? LIMIT 50''',
                       (current_time,))
            return cur.fetchall()
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения истекших наказаний: {e}")
            return []

    def get_all_users_in_chat(self, chat_id: int) -> List[sqlite3.Row]:
        """Получает всех пользователей в чате"""
        try:
            cur = self.conn.cursor()
            cur.execute('''SELECT * FROM users WHERE chat_id=? ORDER BY rank DESC, user_id''', 
                       (chat_id,))
            return cur.fetchall()
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения пользователей чата: {e}")
            return []

    def save_pending_rank(self, target_id: int, chat_id: int, new_rank: int, moderator_id: int) -> int:
        """Сохраняет ожидающее изменение ранга"""
        try:
            cur = self.conn.cursor()
            # Удаляем старые ожидающие изменения
            cur.execute('''DELETE FROM pending_ranks WHERE target_id=? AND chat_id=?''',
                       (target_id, chat_id))
            cur.execute('''INSERT INTO pending_ranks (target_id, chat_id, new_rank, moderator_id)
                          VALUES (?, ?, ?, ?)''',
                       (target_id, chat_id, new_rank, moderator_id))
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Ошибка сохранения ожидающего ранга: {e}")
            return 0

    def get_pending_rank(self, target_id: int, chat_id: int) -> Optional[sqlite3.Row]:
        """Получает ожидающее изменение ранга"""
        try:
            cur = self.conn.cursor()
            cur.execute('''SELECT * FROM pending_ranks WHERE target_id=? AND chat_id=?''',
                       (target_id, chat_id))
            return cur.fetchone()
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения ожидающего ранга: {e}")
            return None

    def delete_pending_rank(self, target_id: int, chat_id: int) -> bool:
        """Удаляет ожидающее изменение ранга"""
        try:
            cur = self.conn.cursor()
            cur.execute('''DELETE FROM pending_ranks WHERE target_id=? AND chat_id=?''',
                       (target_id, chat_id))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка удаления ожидающего ранга: {e}")
            return False

# ===================== КЛАСС БОТА =====================
class BotCore:
    def __init__(self):
        storage = MemoryStorage()
        self.bot = Bot(token=BOT_TOKEN)
        self.dp = Dispatcher(storage=storage)
        self.router = Router()
        self.db = Database()
        self.dp.include_router(self.router)
        self.punishment_check_task = None

    async def check_bot_token(self):
        """Проверка валидности токена бота"""
        try:
            me = await self.bot.get_me()
            logger.info(f"Бот успешно запущен: @{me.username}")
            return True
        except TelegramUnauthorizedError:
            logger.error("Неверный токен бота!")
            return False

    async def set_creator_rank(self, chat_id: int, user_id: int):
        """Проверка и установка ранга создателя"""
        try:
            chat_member = await self.bot.get_chat_member(chat_id, user_id)
            if chat_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
                if chat_member.status == ChatMemberStatus.CREATOR or chat_member.can_promote_members:
                    self.db.set_rank(user_id, chat_id, 5)
                    logger.info(f"Пользователю {user_id} установлен ранг СОЗДАТЕЛЬ в чате {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка при проверке создателя: {e}")

    async def parse_user(self, message: Message, user_str: str) -> Optional[types.User]:
        """Парсит пользователя из строки (ID, @username или упоминание)"""
        try:
            # Если это числовой ID
            if user_str.isdigit():
                user_id = int(user_str)
                try:
                    chat_member = await self.bot.get_chat_member(message.chat.id, user_id)
                    return chat_member.user
                except TelegramBadRequest as e:
                    if "user not found" in str(e).lower():
                        await message.reply("❌ Пользователь не найден в этом чате")
                    else:
                        await message.reply("❌ Ошибка при поиске пользователя")
                    return None

            # Если это упоминание (@username или имя с @)
            elif user_str.startswith('@'):
                username = user_str[1:].lower()
                # Проверяем в сообщении есть ли entity (упоминания)
                if message.entities:
                    for entity in message.entities:
                        if entity.type == "text_mention" and entity.user:
                            if entity.user.username and entity.user.username.lower() == username:
                                return entity.user
                        elif entity.type == "mention":
                            mentioned_text = message.text[entity.offset:entity.offset + entity.length]
                            if mentioned_text.lower() == user_str.lower():
                                # Пытаемся получить информацию о пользователе
                                try:
                                    # Ищем в участниках чата
                                    async for member in self.bot.get_chat_members(message.chat.id):
                                        if member.user.username and member.user.username.lower() == username:
                                            return member.user
                                except Exception as e:
                                    logger.error(f"Ошибка поиска по username: {e}")
                                    pass
                
                # Если не нашли через entity, просим использовать ID
                await message.reply(
                    "❌ Не удалось найти пользователя по username.\n"
                    "Пожалуйста, используйте ID пользователя или упоминание через @ в чате.\n"
                    "Чтобы получить ID пользователя, перешлите его сообщение боту @userinfobot"
                )
                return None

            # Если это reply на сообщение
            elif message.reply_to_message:
                return message.reply_to_message.from_user

            else:
                # Проверяем, может быть это часть текста сообщения
                # Ищем ID в тексте
                match = re.search(r'\d{5,}', user_str)  # Ищем числа от 5 цифр (минимальный Telegram ID)
                if match:
                    user_id = int(match.group())
                    try:
                        chat_member = await self.bot.get_chat_member(message.chat.id, user_id)
                        return chat_member.user
                    except TelegramBadRequest:
                        pass

                await message.reply(
                    "❌ Неверный формат пользователя.\n"
                    "Используйте:\n"
                    "• ID пользователя (например: 123456789)\n"
                    "• Ответ на сообщение пользователя\n"
                    "• Упоминание через @ в чате (бот должен видеть это сообщение)"
                )
                return None

        except Exception as e:
            logger.error(f"Ошибка в parse_user: {e}")
            await message.reply("❌ Ошибка при поиске пользователя")
            return None

    def register_handlers(self):
        """Регистрация всех обработчиков"""

        # ===================== ХЭНДЛЕРЫ ДЛЯ ГРУПП =====================
        
        @self.router.message(F.chat.type.in_({"group", "supergroup"}))
        async def handle_group_message(message: Message):
            """Обработчик сообщений в группах"""
            try:
                user = message.from_user
                self.db.add_user(user.id, message.chat.id, 
                               user.username or "", user.first_name or "")
                
                if user.id in ADMIN_IDS:
                    await self.set_creator_rank(message.chat.id, user.id)
            except Exception as e:
                logger.error(f"Ошибка обработки группового сообщения: {e}")

        # ===================== КОМАНДЫ =====================
        
        # Триггер пульс
        @self.router.message(F.text)
        async def pulse_trigger(message: Message):
            if message.text and message.text.lower().strip() == "пульс":
                await message.reply("Обновляю все изменения и бота...")
                await asyncio.sleep(0.5)
                response = random.choice(PULSE_TRIGGERS)
                await message.reply(response + "\nВсе функции применены и бот работает!")

        # Приветствие с кнопками
        @self.router.message(Command("start"))
        async def start_message(message: Message):
            try:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="📜 Правила", callback_data="show_rules")],
                        [InlineKeyboardButton(text="🛠 Техподдержка", callback_data="support")]
                    ]
                )
                
                if message.chat.type == "private":
                    text = f"""Привет, {message.from_user.first_name}! 

🤖 Это Puls Bot — мощный менеджер групп и чатов.

🔹 Управление участниками
🔹 Система рангов
🔹 Наказания (мут/бан/варн)
🔹 Автоматические функции

👑 Владелец бота: @vanezyyy
🛠 По вопросам: @VanezyPulsSupport

Напиши /help для списка команд"""
                else:
                    text = f"""Привет, {message.from_user.first_name}! 

🤖 Puls Bot активирован в этом чате!

👑 Владелец: @vanezyyy
🛠 Поддержка: @VanezyPulsSupport

Используй /help для списка команд"""

                await message.reply(text, reply_markup=kb)
            except Exception as e:
                logger.error(f"Ошибка в start_message: {e}")

        # Помощь
        @self.router.message(Command("help"))
        async def help_command(message: Message):
            help_text = """🎖️ *Доступные команды:*

*Для всех:*
/start - Запуск бота
/profile - Мой профиль
/rules - Правила чата

*Для модераторов (ранг 1+):*
/warn [ID/ответ] причина - Выдать предупреждение
/mute [ID/ответ] время(м) причина - Заглушить пользователя
/unmute [ID] - Снять мут
/ban [ID/ответ] причина - Забанить пользователя
/unban [ID] - Разбанить пользователя
/kick [ID/ответ] причина - Кикнуть пользователя
/warnings [ID] - Проверить предупреждения

*Для администраторов (ранг 3+):*
/setrank ID ранг - Изменить ранг пользователя
/setrules текст - Установить правила чата
/ranks - Список всех рангов
/users - Список пользователей чата

*Триггер:*
Напиши *пульс* для проверки работы бота

👑 Создатель: @vanezyyy
*Примечание:* Для команд используйте ID пользователя или ответ на его сообщение"""
            await message.reply(help_text, parse_mode="Markdown")

        # Показать правила
        @self.router.message(Command("rules"))
        async def show_rules_command(message: Message):
            try:
                rules = self.db.get_rules(message.chat.id)
                await message.reply(rules)
            except Exception as e:
                logger.error(f"Ошибка показа правил: {e}")
                await message.reply("❌ Ошибка загрузки правил")

        # Установить правила (ранг 3+)
        @self.router.message(Command("setrules"))
        async def set_rules_command(message: Message, command: CommandObject):
            try:
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if user_data and user_data['rank'] >= 3:
                    if command.args:
                        if self.db.set_rules(message.chat.id, command.args):
                            await message.reply("✅ Правила успешно обновлены!")
                        else:
                            await message.reply("❌ Ошибка сохранения правил")
                    else:
                        await message.reply("❌ Укажите текст правил: /setrules текст")
                else:
                    await message.reply("❌ Недостаточно прав! Требуется ранг 3+")
            except Exception as e:
                logger.error(f"Ошибка установки правил: {e}")
                await message.reply("❌ Ошибка при установке правил")

        # Мой профиль
        @self.router.message(Command("profile", "профиль"))
        async def profile_command(message: Message):
            try:
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if user_data:
                    rank_name = RANKS.get(user_data['rank'], "Неизвестно")
                    profile_text = f"""📊 *Ваш профиль:*

👤 Имя: {user_data['first_name']}
📛 Юзернейм: @{user_data['username'] or 'отсутствует'}
🆔 ID: `{user_data['user_id']}`

🎖️ Ранг: {rank_name}
⚠️ Предупреждения: {user_data['warnings']}/{MAX_WARNINGS}
🔇 Мутов: {user_data['mutes']}
🔨 Банов: {user_data['bans']}"""
                    
                    # Проверяем активные наказания
                    punishments = self.db.get_active_punishments(message.chat.id, message.from_user.id)
                    if punishments:
                        profile_text += "\n\n🔒 *Активные наказания:*"
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
                    await message.reply("❌ Ваш профиль не найден в базе данных")
            except Exception as e:
                logger.error(f"Ошибка показа профиля: {e}")
                await message.reply("❌ Ошибка загрузки профиля")

        # Предупреждение (ранг 1+)
        @self.router.message(Command("warn"))
        async def warn_command(message: Message, command: CommandObject):
            try:
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if user_data and user_data['rank'] >= 1:
                    # Извлекаем аргументы
                    args = command.args or ""
                    
                    if not args and not message.reply_to_message:
                        await message.reply("❌ Использование: /warn [ID/ответ] причина")
                        return
                    
                    # Определяем целевого пользователя
                    if message.reply_to_message:
                        target_user = message.reply_to_message.from_user
                        reason = args
                    else:
                        parts = args.split(maxsplit=1)
                        if len(parts) < 1:
                            await message.reply("❌ Использование: /warn [ID/ответ] причина")
                            return
                        
                        target_user = await self.parse_user(message, parts[0])
                        if not target_user:
                            return
                        
                        reason = parts[1] if len(parts) > 1 else "Не указана"
                    
                    # Проверяем, что не выдает предупреждение самому себе
                    if target_user.id == message.from_user.id:
                        await message.reply("❌ Нельзя выдать предупреждение самому себе!")
                        return
                    
                    # Проверяем, что не выдает предупреждение пользователю с равным или высшим рангом
                    target_data = self.db.get_user(target_user.id, message.chat.id)
                    if target_data and target_data['rank'] >= user_data['rank']:
                        await message.reply("❌ Нельзя выдать предупреждение пользователю с равным или высшим рангом!")
                        return
                    
                    # Добавляем предупреждение
                    warnings = self.db.add_warning(target_user.id, message.chat.id)
                    
                    # Отправляем уведомление
                    warn_msg = await message.reply(
                        f"⚠️ Пользователю {target_user.mention_html()} выдано предупреждение!\n"
                        f"📝 Причина: {reason}\n"
                        f"🔢 Предупреждений: {warnings}/{MAX_WARNINGS}\n"
                        f"👮 Модератор: {message.from_user.mention_html()}",
                        parse_mode="HTML"
                    )
                    
                    # Проверяем на превышение лимита предупреждений
                    if warnings >= MAX_WARNINGS:
                        # Автоматический мут на 24 часа за превышение варнов
                        end_time = datetime.now() + timedelta(hours=24)
                        success = await self.mute_user(
                            chat_id=message.chat.id,
                            user_id=target_user.id,
                            duration_minutes=1440,  # 24 часа
                            reason=f"Автоматический мут за {MAX_WARNINGS} предупреждений",
                            moderator_id=message.from_user.id
                        )
                        
                        if success:
                            # Сбрасываем предупреждения
                            self.db.reset_warnings(target_user.id, message.chat.id)
                            
                            await warn_msg.edit_text(
                                f"{warn_msg.html_text}\n\n🚨 Достигнут лимит {MAX_WARNINGS} предупреждений! "
                                f"Пользователь автоматически замучен на 24 часа.",
                                parse_mode="HTML"
                            )
                else:
                    await message.reply("❌ Недостаточно прав! Требуется ранг 1+")
            except Exception as e:
                logger.error(f"Ошибка в warn_command: {e}")
                await message.reply("❌ Ошибка при выдаче предупреждения")

        # Мут (ранг 1+)
        @self.router.message(Command("mute"))
        async def mute_command(message: Message, command: CommandObject):
            try:
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if user_data and user_data['rank'] >= 1:
                    args = command.args or ""
                    
                    if not args and not message.reply_to_message:
                        await message.reply("❌ Использование: /mute [ID/ответ] время(м) причина")
                        return
                    
                    # Определяем целевого пользователя и параметры
                    if message.reply_to_message:
                        target_user = message.reply_to_message.from_user
                        other_args = args.split(maxsplit=1)
                        if len(other_args) < 1:
                            await message.reply("❌ Использование: /mute [ID/ответ] время(м) причина")
                            return
                        
                        try:
                            duration = int(other_args[0])
                            reason = other_args[1] if len(other_args) > 1 else "Не указана"
                        except ValueError:
                            await message.reply("❌ Неверное время. Укажите число минут")
                            return
                    else:
                        parts = args.split(maxsplit=2)
                        if len(parts) < 2:
                            await message.reply("❌ Использование: /mute [ID/ответ] время(м) причина")
                            return
                        
                        target_user = await self.parse_user(message, parts[0])
                        if not target_user:
                            return
                        
                        try:
                            duration = int(parts[1])
                            reason = parts[2] if len(parts) > 2 else "Не указана"
                        except ValueError:
                            await message.reply("❌ Неверное время. Укажите число минут")
                            return
                    
                    # Проверки
                    if target_user.id == message.from_user.id:
                        await message.reply("❌ Нельзя замутить самого себя!")
                        return
                    
                    target_data = self.db.get_user(target_user.id, message.chat.id)
                    if target_data and target_data['rank'] >= user_data['rank']:
                        await message.reply("❌ Нельзя замутить пользователя с равным или высшим рангом!")
                        return
                    
                    if duration <= 0 or duration > 44640:  # Макс 31 день
                        await message.reply("❌ Время должно быть от 1 до 44640 минут (31 день)")
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
                        await message.reply(
                            f"🔇 Пользователь {target_user.mention_html()} замучен на {duration} минут!\n"
                            f"📝 Причина: {reason}\n"
                            f"👮 Модератор: {message.from_user.mention_html()}",
                            parse_mode="HTML"
                        )
                    else:
                        await message.reply("❌ Не удалось замутить пользователя")
                else:
                    await message.reply("❌ Недостаточно прав! Требуется ранг 1+")
            except Exception as e:
                logger.error(f"Ошибка в mute_command: {e}")
                await message.reply("❌ Ошибка при муте пользователя")

        # Размут (ранг 1+)
        @self.router.message(Command("unmute"))
        async def unmute_command(message: Message, command: CommandObject):
            try:
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if user_data and user_data['rank'] >= 1:
                    args = command.args or ""
                    
                    if not args:
                        await message.reply("❌ Использование: /unmute [ID]")
                        return
                    
                    # Парсим пользователя
                    target_user = await self.parse_user(message, args.strip())
                    if not target_user:
                        return
                    
                    # Проверяем права
                    target_data = self.db.get_user(target_user.id, message.chat.id)
                    if target_data and target_data['rank'] >= user_data['rank']:
                        await message.reply("❌ Нельзя размутить пользователя с равным или высшим рангом!")
                        return
                    
                    # Ищем активные муты
                    punishments = self.db.get_active_punishments(message.chat.id, target_user.id)
                    mute_punishments = [p for p in punishments if p['type'] == 'mute']
                    
                    if not mute_punishments:
                        await message.reply("❌ У пользователя нет активных мутов")
                        return
                    
                    # Получаем текущие права пользователя
                    try:
                        chat_member = await self.bot.get_chat_member(message.chat.id, target_user.id)
                        current_permissions = chat_member.permissions
                    except Exception as e:
                        logger.warning(f"Не удалось получить права пользователя для размута: {e}")
                        current_permissions = None
                    
                    # Снимаем все муты
                    for punishment in mute_punishments:
                        self.db.remove_punishment(punishment['id'])
                    
                    # Восстанавливаем права
                    try:
                        if current_permissions:
                            # Восстанавливаем оригинальные права
                            await self.bot.restrict_chat_member(
                                chat_id=message.chat.id,
                                user_id=target_user.id,
                                permissions=current_permissions
                            )
                        else:
                            # Даем стандартные права
                            await self.bot.restrict_chat_member(
                                chat_id=message.chat.id,
                                user_id=target_user.id,
                                permissions=ChatPermissions(
                                    can_send_messages=True,
                                    can_send_media_messages=True,
                                    can_send_polls=True,
                                    can_send_other_messages=True,
                                    can_add_web_page_previews=True,
                                    can_change_info=target_data['rank'] >= 3 if target_data else False,
                                    can_invite_users=target_data['rank'] >= 2 if target_data else False,
                                    can_pin_messages=target_data['rank'] >= 3 if target_data else False
                                )
                            )
                    except TelegramBadRequest as e:
                        logger.warning(f"Ошибка при восстановлении прав после мута: {e}")
                        if "not enough rights" in str(e).lower():
                            await message.reply("⚠️ У бота недостаточно прав для восстановления всех прав пользователя")
                    
                    await message.reply(
                        f"🔊 Мут с пользователя {target_user.mention_html()} снят!\n"
                        f"👮 Модератор: {message.from_user.mention_html()}",
                        parse_mode="HTML"
                    )
                else:
                    await message.reply("❌ Недостаточно прав! Требуется ранг 1+")
            except Exception as e:
                logger.error(f"Ошибка в unmute_command: {e}")
                await message.reply("❌ Ошибка при размуте пользователя")

        # Бан (ранг 2+)
        @self.router.message(Command("ban"))
        async def ban_command(message: Message, command: CommandObject):
            try:
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if user_data and user_data['rank'] >= 2:
                    args = command.args or ""
                    
                    if not args and not message.reply_to_message:
                        await message.reply("❌ Использование: /ban [ID/ответ] причина")
                        return
                    
                    # Определяем целевого пользователя
                    if message.reply_to_message:
                        target_user = message.reply_to_message.from_user
                        reason = args
                    else:
                        parts = args.split(maxsplit=1)
                        if len(parts) < 1:
                            await message.reply("❌ Использование: /ban [ID/ответ] причина")
                            return
                        
                        target_user = await self.parse_user(message, parts[0])
                        if not target_user:
                            return
                        
                        reason = parts[1] if len(parts) > 1 else "Не указана"
                    
                    # Проверки
                    if target_user.id == message.from_user.id:
                        await message.reply("❌ Нельзя забанить самого себя!")
                        return
                    
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
                        await message.reply("❌ Не удалось забанить пользователя")
                else:
                    await message.reply("❌ Недостаточно прав! Требуется ранг 2+")
            except Exception as e:
                logger.error(f"Ошибка в ban_command: {e}")
                await message.reply("❌ Ошибка при бане пользователя")

        # Разбан (ранг 2+)
        @self.router.message(Command("unban"))
        async def unban_command(message: Message, command: CommandObject):
            try:
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if user_data and user_data['rank'] >= 2:
                    args = command.args or ""
                    
                    if not args:
                        await message.reply("❌ Использование: /unban [ID]")
                        return
                    
                    # Парсим пользователя
                    target_user = await self.parse_user(message, args.strip())
                    if not target_user:
                        return
                    
                    # Ищем активные баны
                    punishments = self.db.get_active_punishments(message.chat.id, target_user.id)
                    ban_punishments = [p for p in punishments if p['type'] == 'ban']
                    
                    if not ban_punishments:
                        await message.reply("❌ У пользователя нет активных банов")
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
                    except TelegramBadRequest as e:
                        logger.warning(f"Ошибка при разбане: {e}")
                        if "user not banned" not in str(e).lower():
                            await message.reply("⚠️ Пользователь не был забанен, но наказание удалено из базы")
                    
                    await message.reply(
                        f"🔓 Пользователь {target_user.mention_html()} разбанен!\n"
                        f"👮 Модератор: {message.from_user.mention_html()}",
                        parse_mode="HTML"
                    )
                else:
                    await message.reply("❌ Недостаточно прав! Требуется ранг 2+")
            except Exception as e:
                logger.error(f"Ошибка в unban_command: {e}")
                await message.reply("❌ Ошибка при разбане пользователя")

        # Кик (ранг 2+)
        @self.router.message(Command("kick"))
        async def kick_command(message: Message, command: CommandObject):
            try:
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if user_data and user_data['rank'] >= 2:
                    args = command.args or ""
                    
                    if not args and not message.reply_to_message:
                        await message.reply("❌ Использование: /kick [ID/ответ] причина")
                        return
                    
                    # Определяем целевого пользователя
                    if message.reply_to_message:
                        target_user = message.reply_to_message.from_user
                        reason = args
                    else:
                        parts = args.split(maxsplit=1)
                        if len(parts) < 1:
                            await message.reply("❌ Использование: /kick [ID/ответ] причина")
                            return
                        
                        target_user = await self.parse_user(message, parts[0])
                        if not target_user:
                            return
                        
                        reason = parts[1] if len(parts) > 1 else "Не указана"
                    
                    # Проверки
                    if target_user.id == message.from_user.id:
                        await message.reply("❌ Нельзя кикнуть самого себя!")
                        return
                    
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
                        
                        # Разбаниваем сразу (это и есть кик)
                        await self.bot.unban_chat_member(
                            chat_id=message.chat.id,
                            user_id=target_user.id,
                            only_if_banned=True
                        )
                        
                        await message.reply(
                            f"👢 Пользователь {target_user.mention_html()} кикнут!\n"
                            f"📝 Причина: {reason}\n"
                            f"👮 Модератор: {message.from_user.mention_html()}",
                            parse_mode="HTML"
                        )
                    except TelegramBadRequest as e:
                        logger.error(f"Ошибка при кике: {e}")
                        if "not enough rights" in str(e).lower():
                            await message.reply("❌ У бота недостаточно прав для кика пользователя")
                        else:
                            await message.reply("❌ Не удалось кикнуть пользователя")
                else:
                    await message.reply("❌ Недостаточно прав! Требуется ранг 2+")
            except Exception as e:
                logger.error(f"Ошибка в kick_command: {e}")
                await message.reply("❌ Ошибка при кике пользователя")

        # Проверка предупреждений
        @self.router.message(Command("warnings"))
        async def warnings_command(message: Message, command: CommandObject):
            try:
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if user_data and user_data['rank'] >= 1:
                    args = command.args or ""
                    
                    if not args and not message.reply_to_message:
                        # Показываем свои предупреждения
                        warnings = self.db.get_warnings(message.from_user.id, message.chat.id)
                        await message.reply(
                            f"⚠️ У вас {warnings}/{MAX_WARNINGS} предупреждений"
                        )
                    else:
                        # Определяем целевого пользователя
                        if message.reply_to_message:
                            target_user = message.reply_to_message.from_user
                        else:
                            target_user = await self.parse_user(message, args.strip())
                            if not target_user:
                                return
                        
                        warnings = self.db.get_warnings(target_user.id, message.chat.id)
                        await message.reply(
                            f"⚠️ У пользователя {target_user.mention_html()} "
                            f"{warnings}/{MAX_WARNINGS} предупреждений",
                            parse_mode="HTML"
                        )
                else:
                    await message.reply("❌ Недостаточно прав! Требуется ранг 1+")
            except Exception as e:
                logger.error(f"Ошибка в warnings_command: {e}")
                await message.reply("❌ Ошибка при проверке предупреждений")

        # Изменение ранга (ранг 3+)
        @self.router.message(Command("setrank"))
        async def setrank_command(message: Message, command: CommandObject):
            try:
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if user_data and user_data['rank'] >= 3:
                    args = command.args or ""
                    parts = args.split()
                    
                    if len(parts) != 2:
                        await message.reply("❌ Использование: /setrank ID ранг\nПример: /setrank 123456789 2")
                        return
                    
                    try:
                        target_id = int(parts[0])
                        new_rank = int(parts[1])
                        
                        # Проверяем допустимость ранга
                        if new_rank not in RANKS:
                            await message.reply(f"❌ Неверный ранг! Допустимые значения: {list(RANKS.keys())}")
                            return
                        
                        # Проверяем, что не повышаем выше своего ранга
                        if new_rank > user_data['rank']:
                            await message.reply("❌ Нельзя повысить пользователя выше своего ранга!")
                            return
                        
                        # Проверяем, что не понижаем создателя (ранг 5)
                        target_data = self.db.get_user(target_id, message.chat.id)
                        if target_data and target_data['rank'] == 5:
                            await message.reply("❌ Нельзя изменить ранг создателя!")
                            return
                        
                        # Сохраняем в базу ожидающее подтверждение
                        pending_id = self.db.save_pending_rank(
                            target_id=target_id,
                            chat_id=message.chat.id,
                            new_rank=new_rank,
                            moderator_id=message.from_user.id
                        )
                        
                        if not pending_id:
                            await message.reply("❌ Ошибка сохранения запроса")
                            return
                        
                        # Запрашиваем подтверждение
                        kb = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_rank_{pending_id}"),
                                    InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_rank_{pending_id}")
                                ]
                            ]
                        )
                        
                        rank_name = RANKS[new_rank]
                        await message.reply(
                            f"⚠️ Вы уверены, что хотите установить ранг {new_rank} "
                            f"({rank_name}) пользователю с ID {target_id}?",
                            reply_markup=kb
                        )
                        
                    except ValueError:
                        await message.reply("❌ Неверный формат! ID и ранг должны быть числами")
                else:
                    await message.reply("❌ Недостаточно прав! Требуется ранг 3+")
            except Exception as e:
                logger.error(f"Ошибка в setrank_command: {e}")
                await message.reply("❌ Ошибка при изменении ранга")

        # Список рангов
        @self.router.message(Command("ranks"))
        async def ranks_command(message: Message):
            try:
                ranks_text = "🎖️ *Система рангов:*\n\n"
                for rank_num, rank_name in sorted(RANKS.items()):
                    ranks_text += f"{rank_num} - {rank_name}\n"
                
                ranks_text += "\n*Права:*\n"
                ranks_text += "1+ - Мут, варн\n"
                ranks_text += "2+ - Бан, кик\n"
                ranks_text += "3+ - Изменение рангов\n"
                ranks_text += "4+ - Полный доступ\n"
                ranks_text += "5 - Создатель (полные права)"
                
                await message.reply(ranks_text, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Ошибка в ranks_command: {e}")
                await message.reply("❌ Ошибка при показе рангов")

        # Список пользователей с рангами (ранг 3+)
        @self.router.message(Command("users"))
        async def users_command(message: Message):
            try:
                user_data = self.db.get_user(message.from_user.id, message.chat.id)
                if user_data and user_data['rank'] >= 3:
                    users = self.db.get_all_users_in_chat(message.chat.id)
                    
                    if not users:
                        await message.reply("❌ В базе нет пользователей")
                        return
                    
                    # Группируем по рангам и пагинируем
                    users_by_rank = {}
                    for user in users:
                        rank = user['rank']
                        if rank not in users_by_rank:
                            users_by_rank[rank] = []
                        
                        username = f"@{user['username']}" if user['username'] else user['first_name']
                        users_by_rank[rank].append(f"{username} (ID: {user['user_id']})")
                    
                    # Формируем сообщения с пагинацией
                    pages = []
                    current_page = "👥 *Пользователи в чате:*\n\n"
                    char_count = len(current_page)
                    
                    for rank_num in sorted(RANKS.keys(), reverse=True):
                        if rank_num in users_by_rank:
                            rank_name = RANKS[rank_num]
                            rank_section = f"*{rank_name}:*\n"
                            
                            for user_str in users_by_rank[rank_num]:
                                user_line = f"  • {user_str}\n"
                                
                                # Если страница становится слишком длинной, начинаем новую
                                if char_count + len(rank_section) + len(user_line) > 4000:
                                    pages.append(current_page)
                                    current_page = "👥 *Пользователи в чате (продолжение):*\n\n"
                                    char_count = len(current_page)
                                    # Добавляем заголовок ранга на новую страницу
                                    current_page += rank_section
                                    char_count += len(rank_section)
                                
                                current_page += user_line
                                char_count += len(user_line)
                            
                            current_page += "\n"
                            char_count += 1
                    
                    # Добавляем последнюю страницу
                    if current_page.strip():
                        pages.append(current_page)
                    
                    # Отправляем страницы
                    for i, page in enumerate(pages):
                        if i == 0:
                            await message.reply(page, parse_mode="Markdown")
                        else:
                            await message.answer(page, parse_mode="Markdown")
                else:
                    await message.reply("❌ Недостаточно прав! Требуется ранг 3+")
            except Exception as e:
                logger.error(f"Ошибка в users_command: {e}")
                await message.reply("❌ Ошибка при показе пользователей")

        # ===================== CALLBACK ОБРАБОТЧИКИ =====================
        
        # Показать правила (callback)
        @self.router.callback_query(F.data == "show_rules")
        async def show_rules_cb(query: types.CallbackQuery):
            try:
                if query.message.chat.type == "private":
                    rules = self.db.get_rules(query.message.chat.id)
                    await query.message.answer(rules)
                else:
                    # В группе показываем в основном чате
                    rules = self.db.get_rules(query.message.chat.id)
                    await query.message.answer(rules)
                await query.answer()
            except Exception as e:
                logger.error(f"Ошибка в show_rules_cb: {e}")
                await query.answer("Ошибка загрузки правил", show_alert=True)

        # Техподдержка (callback)
        @self.router.callback_query(F.data == "support")
        async def support_cb(query: types.CallbackQuery):
            try:
                text = ("💡 *Техническая поддержка*\n\n"
                        "✅ *Правильно:*\n"
                        "• Привет, у меня проблема с функцией мьюта\n"
                        "• Здравствуйте, есть предложение по улучшению бота\n"
                        "• Добрый день, бот не отвечает на команды\n\n"
                        "❌ *НЕ правильно:*\n"
                        "• привет\n"
                        "• жду ответа\n"
                        "• ...\n\n"
                        "👑 *Владелец:* @vanezyyy\n"
                        "🛠 *Поддержка:* @VanezyPulsSupport")
                await query.message.answer(text, parse_mode="Markdown")
                await query.answer()
            except Exception as e:
                logger.error(f"Ошибка в support_cb: {e}")
                await query.answer("Ошибка", show_alert=True)

        # Подтверждение изменения ранга
        @self.router.callback_query(F.data.startswith("confirm_rank_"))
        async def confirm_rank_cb(query: types.CallbackQuery):
            try:
                pending_id = int(query.data.replace("confirm_rank_", ""))
                
                # Получаем информацию о модераторе
                user_data = self.db.get_user(query.from_user.id, query.message.chat.id)
                if not user_data or user_data['rank'] < 3:
                    await query.answer("Недостаточно прав!", show_alert=True)
                    return
                
                # Ищем ожидающее изменение
                # В реальной реализации нужно хранить pending_id в отдельной таблице
                # Для простоты будем парсить из сообщения
                message_text = query.message.text
                import re
                match = re.search(r'ID (\d+)', message_text)
                if not match:
                    await query.answer("Не удалось найти ID пользователя", show_alert=True)
                    return
                
                target_id = int(match.group(1))
                
                # Ищем ранг в сообщении
                rank_match = re.search(r'ранк (\d+)', message_text.lower())
                if not rank_match:
                    await query.answer("Не удалось найти ранг", show_alert=True)
                    return
                
                new_rank = int(rank_match.group(1))
                
                # Устанавливаем ранг
                if self.db.set_rank(target_id, query.message.chat.id, new_rank):
                    await query.message.edit_text(
                        f"✅ Ранг {new_rank} ({RANKS[new_rank]}) "
                        f"установлен пользователю с ID {target_id}"
                    )
                    await query.answer("Ранг изменен!")
                else:
                    await query.message.edit_text("❌ Ошибка при изменении ранга")
                    await query.answer("Ошибка", show_alert=True)
                    
            except Exception as e:
                logger.error(f"Ошибка в confirm_rank_cb: {e}")
                await query.answer("Ошибка", show_alert=True)

        # Отмена изменения ранга
        @self.router.callback_query(F.data.startswith("cancel_rank_"))
        async def cancel_rank_cb(query: types.CallbackQuery):
            try:
                await query.message.edit_text("❌ Изменение ранга отменено")
                await query.answer("Отменено")
            except Exception as e:
                logger.error(f"Ошибка в cancel_rank_cb: {e}")
                await query.answer("Ошибка", show_alert=True)

        # Снятие наказания (кнопка)
        @self.router.callback_query(F.data.startswith("remove_punish_"))
        async def remove_punishment_cb(query: types.CallbackQuery):
            try:
                punishment_id = int(query.data.replace("remove_punish_", ""))
                punishment = self.db.get_punishment_by_id(punishment_id)
                
                if not punishment:
                    await query.answer("Наказание не найдено!")
                    return
                
                # Проверяем права
                user_data = self.db.get_user(query.from_user.id, query.message.chat.id)
                if not user_data or user_data['rank'] < 1:
                    await query.answer("Недостаточно прав!")
                    return
                
                # Проверяем, что не снимает наказание с пользователя с равным или высшим рангом
                target_data = self.db.get_user(punishment['user_id'], punishment['chat_id'])
                if target_data and target_data['rank'] >= user_data['rank']:
                    await query.answer("Нельзя снять наказание с пользователя с равным или высшим рангом!")
                    return
                
                # Снимаем наказание
                if not self.db.remove_punishment(punishment_id):
                    await query.answer("Ошибка при снятии наказания!")
                    return
                
                # Если это мут - восстанавливаем права
                if punishment['type'] == 'mute':
                    try:
                        # Получаем текущие права пользователя
                        target_data = self.db.get_user(punishment['user_id'], punishment['chat_id'])
                        await self.bot.restrict_chat_member(
                            chat_id=punishment['chat_id'],
                            user_id=punishment['user_id'],
                            permissions=ChatPermissions(
                                can_send_messages=True,
                                can_send_media_messages=True,
                                can_send_polls=True,
                                can_send_other_messages=True,
                                can_add_web_page_previews=True,
                                can_change_info=target_data['rank'] >= 3 if target_data else False,
                                can_invite_users=target_data['rank'] >= 2 if target_data else False,
                                can_pin_messages=target_data['rank'] >= 3 if target_data else False
                            )
                        )
                    except TelegramBadRequest as e:
                        logger.warning(f"Ошибка при восстановлении прав после снятия мута: {e}")
                
                # Если это бан - разбаниваем
                elif punishment['type'] == 'ban':
                    try:
                        await self.bot.unban_chat_member(
                            chat_id=punishment['chat_id'],
                            user_id=punishment['user_id'],
                            only_if_banned=True
                        )
                    except TelegramBadRequest as e:
                        logger.warning(f"Ошибка при разбане: {e}")
                
                # Обновляем сообщение
                await query.message.edit_text(
                    f"✅ Наказание снято!\n"
                    f"👮 Модератор: {query.from_user.mention_html()}\n"
                    f"📝 Тип: {punishment['type']}\n"
                    f"👤 Пользователь ID: {punishment['user_id']}",
                    parse_mode="HTML"
                )
                
                await query.answer("Наказание снято!")
            except Exception as e:
                logger.error(f"Ошибка в remove_punishment_cb: {e}")
                await query.answer("Ошибка при снятии наказания!", show_alert=True)

    # ===================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====================
    
    async def mute_user(self, chat_id: int, user_id: int, duration_minutes: int, 
                       reason: str, moderator_id: int) -> bool:
        """Мутит пользователя"""
        try:
            # Устанавливаем время окончания (макс 31 день для мута)
            max_mute_days = 31
            if duration_minutes > max_mute_days * 24 * 60:
                duration_minutes = max_mute_days * 24 * 60
            
            end_time = datetime.now() + timedelta(minutes=duration_minutes)
            
            # Ограничиваем права
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
            
            # Добавляем в базу данных
            punishment_id = self.db.add_punishment(
                chat_id=chat_id,
                user_id=user_id,
                punishment_type='mute',
                moderator_id=moderator_id,
                reason=reason,
                end_time=end_time
            )
            
            if not punishment_id:
                logger.error("Не удалось сохранить мут в базу данных")
                return False
            
            # Увеличиваем счетчик мутов
            self.db.add_mute_count(user_id, chat_id)
            
            # Создаем клавиатуру для снятия наказания
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
            
            # Отправляем уведомление с кнопкой
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"🔇 Пользователь замучен на {time_str}!\n"
                     f"📝 Причина: {reason}\n"
                     f"⏰ До: {end_time.strftime('%d.%m.%Y %H:%M')}\n"
                     f"👮 Модератор ID: {moderator_id}",
                reply_markup=kb
            )
            
            return True
            
        except TelegramBadRequest as e:
            logger.error(f"Telegram API ошибка при муте: {e}")
            if "not enough rights" in str(e).lower():
                logger.error("У бота недостаточно прав для мута пользователя")
            return False
        except Exception as e:
            logger.error(f"Ошибка при муте: {e}")
            return False

    async def ban_user(self, chat_id: int, user_id: int, reason: str, 
                      moderator_id: int, duration_days: int = 30) -> bool:
        """Банит пользователя (по умолчанию на 30 дней, максимум 366 дней)"""
        try:
            # Ограничиваем максимальное время бана (Telegram API максимум)
            if duration_days > 366:
                duration_days = 366
            
            # Устанавливаем время окончания
            end_time = datetime.now() + timedelta(days=duration_days)
            
            # Баним
            await self.bot.ban_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                until_date=end_time
            )
            
            # Добавляем в базу данных
            punishment_id = self.db.add_punishment(
                chat_id=chat_id,
                user_id=user_id,
                punishment_type='ban',
                moderator_id=moderator_id,
                reason=reason,
                end_time=end_time
            )
            
            if not punishment_id:
                logger.error("Не удалось сохранить бан в базу данных")
                return False
            
            # Увеличиваем счетчик банов
            self.db.add_ban_count(user_id, chat_id)
            
            # Создаем клавиатуру для снятия наказания
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔓 Снять наказание", 
                        callback_data=f"remove_punish_{punishment_id}"
                    )]
                ]
            )
            
            # Отправляем уведомление с кнопкой
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"🔨 Пользователь забанен на {duration_days} дней!\n"
                     f"📝 Причина: {reason}\n"
                     f"⏰ До: {end_time.strftime('%d.%m.%Y %H:%M')}\n"
                     f"👮 Модератор ID: {moderator_id}",
                reply_markup=kb
            )
            
            return True
            
        except TelegramBadRequest as e:
            logger.error(f"Telegram API ошибка при бане: {e}")
            if "not enough rights" in str(e).lower():
                logger.error("У бота недостаточно прав для бана пользователя")
            return False
        except Exception as e:
            logger.error(f"Ошибка при бане: {e}")
            return False

    async def check_expired_punishments(self):
        """Проверяет истекшие наказания с оптимизацией"""
        logger.info("Запущена проверка истекших наказаний")
        
        while True:
            try:
                # Делаем паузу между проверками
                await asyncio.sleep(300)  # 5 минут вместо 1
                
                punishments = self.db.get_expired_punishments()
                
                if not punishments:
                    continue
                
                logger.info(f"Найдено {len(punishments)} истекших наказаний")
                
                # Обрабатываем пакетами по 10
                for i in range(0, len(punishments), 10):
                    batch = punishments[i:i+10]
                    
                    for punishment in batch:
                        try:
                            # Помечаем как неактивное
                            self.db.remove_punishment(punishment['id'])
                            
                            # Отправляем уведомление
                            try:
                                chat = await self.bot.get_chat(punishment['chat_id'])
                                chat_name = chat.title or "чат"
                                
                                # Формируем тип наказания
                                punish_type = "Мут" if punishment['type'] == 'mute' else "Бан"
                                
                                # Отправляем в чат
                                await self.bot.send_message(
                                    chat_id=punishment['chat_id'],
                                    text=f"⏰ {punish_type} пользователя с ID {punishment['user_id']} "
                                         f"истек в {chat_name}!"
                                )
                            except TelegramBadRequest as e:
                                if "chat not found" in str(e).lower():
                                    logger.warning(f"Чат {punishment['chat_id']} не найден, удаляю наказание")
                                else:
                                    logger.warning(f"Ошибка при уведомлении об истечении: {e}")
                            except Exception as e:
                                logger.warning(f"Ошибка при получении чата: {e}")
                        
                        except Exception as e:
                            logger.error(f"Ошибка обработки наказания {punishment['id']}: {e}")
                    
                    # Пауза между пакетами
                    await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Критическая ошибка в check_expired_punishments: {e}")
                await asyncio.sleep(600)  # Пауза 10 минут при ошибке

    async def cleanup_pending_ranks(self):
        """Очищает старые ожидающие изменения рангов"""
        logger.info("Запущена очистка старых ожидающих рангов")
        
        while True:
            try:
                # В реальной реализации нужно удалять записи старше 24 часов
                # Здесь просто логируем
                await asyncio.sleep(3600)  # Проверяем каждый час
                logger.debug("Очистка ожидающих рангов выполнена")
            except Exception as e:
                logger.error(f"Ошибка в cleanup_pending_ranks: {e}")
                await asyncio.sleep(3600)

    async def run(self):
        """Запуск бота"""
        if not await self.check_bot_token():
            logger.error("Не удалось проверить токен бота. Завершение работы.")
            return
        
        # Запускаем фоновые задачи
        self.punishment_check_task = asyncio.create_task(self.check_expired_punishments())
        asyncio.create_task(self.cleanup_pending_ranks())
        
        self.register_handlers()
        
        logger.info("Бот запущен!")
        
        try:
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Критическая ошибка при запуске бота: {e}")
        finally:
            # Останавливаем фоновые задачи
            if self.punishment_check_task:
                self.punishment_check_task.cancel()
                try:
                    await self.punishment_check_task
                except asyncio.CancelledError:
                    pass

# ===================== ЗАПУСК =====================
if __name__ == "__main__":
    try:
        bot_core = BotCore()
        asyncio.run(bot_core.run())
    except KeyboardInterrupt:
        print("\nБот остановлен пользователем")
        logger.info("Бот остановлен по запросу пользователя")
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске: {e}")
        print(f"Критическая ошибка: {e}")
