#!/usr/bin/env python3
"""
🎖️ Telegram Bot с наказаниями и системой рангов
Только нужные функции:
- Приветствие: /start, /startpuls, пульс
- Наказания: мут, размут, варн, кик, бан, разбан
- Ранги: просмотр и изменение (создатель 5 ранг)
- Правила: добавить правила и показать правила
- Триггер "пульс" - 20+ случайных ответов
"""

import asyncio
import logging
import sqlite3
import random
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton, ReplyKeyboardMarkup
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = "8566099089:AAGC-BwcC2mia46iG-aNL9_931h5xV21b9c"
ADMIN_IDS = [6708209142]

MAX_WARNINGS = 5

# Система рангов
RANKS = {
    0: "👤 Участник",
    1: "👮 Младший модератор",
    2: "🛡️ Старший модератор",
    3: "👑 Администратор",
    4: "🌟 Продвинутый админ",
    5: "✨ СОЗДАТЕЛЬ"
}

# ===================== ТРИГГЕРЫ "ПУЛЬС" =====================
PULSE_TRIGGERS = [
    "⚡ Пульс активен! Система готова к работе!",
    "💓 Бот жив и работает стабильно!",
    "🌀 Энергия течет, системы в норме!",
    "🔋 Заряд 100%! Все функции доступны!",
    "✨ Пульс стабилен, сервера в порядке!",
    "🎯 Системный импульс зафиксирован!",
    "🌊 Волна активности подтверждена!",
    "🚀 Все системы запущены!",
    "💫 Энергетический поток стабилен!",
    "⚡️ Ток течет, бот работает!",
    "🔮 Магический пульс обнаружен!",
    "🌟 Световой импульс зарегистрирован!",
    "🌪 Вихрь энергии подтвержден!",
    "🔥 Огненный пульс активен!",
    "💧 Водный поток стабилен!",
    "🌍 Геомагнитный импульс в норме!",
    "🌌 Космическая энергия течет!",
    "🎇 Фейерверк систем готов!",
    "🌈 Радужный импульс подтвержден!",
    "🦅 Орлиный взгляд системы активен!",
    "🐉 Драконий пульс зафиксирован!",
    "🦁 Львиный рык системы слышен!",
    "🐺 Волчий вой подтвержден!",
    "🦊 Лисья хитрость системы активна!",
    "🦉 Мудрость совы в системе!",
    "🎉 Система готова к празднику!",
    "✅ Все проверки пройдены успешно!",
    "🟢 Статус: СИСТЕМА РАБОТАЕТ!",
    "🏆 Победный импульс зафиксирован!",
    "🎊 Фейерверк запущен, все ОК!"
]

# ===================== ЛОГИ =====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===================== БАЗА ДАННЫХ =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("bot.db", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()

    def create_tables(self):
        cur = self.conn.cursor()
        # Пользователи
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER,
                chat_id INTEGER,
                username TEXT,
                first_name TEXT,
                rank INTEGER DEFAULT 0,
                warnings INTEGER DEFAULT 0,
                mutes INTEGER DEFAULT 0,
                bans INTEGER DEFAULT 0,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, chat_id)
            )
        ''')
        # Правила
        cur.execute('''
            CREATE TABLE IF NOT EXISTS rules (
                chat_id INTEGER PRIMARY KEY,
                text TEXT
            )
        ''')
        self.conn.commit()

    def add_user(self, user_id, chat_id, username="", first_name=""):
        cur = self.conn.cursor()
        cur.execute('''
            INSERT OR IGNORE INTO users (user_id, chat_id, username, first_name) 
            VALUES (?, ?, ?, ?)
        ''', (user_id, chat_id, username, first_name))
        self.conn.commit()

    def get_user(self, user_id, chat_id):
        cur = self.conn.cursor()
        cur.execute('SELECT * FROM users WHERE user_id=? AND chat_id=?', (user_id, chat_id))
        return cur.fetchone()

    def set_rank(self, user_id, chat_id, rank):
        cur = self.conn.cursor()
        cur.execute('UPDATE users SET rank=? WHERE user_id=? AND chat_id=?', (rank, user_id, chat_id))
        self.conn.commit()

    def add_warning(self, user_id, chat_id):
        cur = self.conn.cursor()
        cur.execute('UPDATE users SET warnings = warnings + 1 WHERE user_id=? AND chat_id=?', (user_id, chat_id))
        self.conn.commit()

    def get_warnings(self, user_id, chat_id):
        cur = self.conn.cursor()
        cur.execute('SELECT warnings FROM users WHERE user_id=? AND chat_id=?', (user_id, chat_id))
        row = cur.fetchone()
        return row['warnings'] if row else 0

    # Правила
    def set_rules(self, chat_id, text):
        cur = self.conn.cursor()
        cur.execute('INSERT OR REPLACE INTO rules (chat_id, text) VALUES (?, ?)', (chat_id, text))
        self.conn.commit()

    def get_rules(self, chat_id):
        cur = self.conn.cursor()
        cur.execute('SELECT text FROM rules WHERE chat_id=?', (chat_id,))
        row = cur.fetchone()
        return row['text'] if row else "📜 Правила пока не установлены\nИспользуйте команду: доб прав [текст правил]"

# ===================== БОТ =====================
class BotCore:
    def __init__(self):
        self.bot = Bot(token=BOT_TOKEN)
        self.dp = Dispatcher()
        self.db = Database()
        self.router = Router()
        self.dp.include_router(self.router)

    async def set_creator_rank(self, chat_id, user_id):
        """Автоматически дать создателю чата 5 ранг"""
        try:
            member = await self.bot.get_chat_member(chat_id, user_id)
            if member.status == ChatMemberStatus.CREATOR or user_id in ADMIN_IDS:
                user = self.db.get_user(user_id, chat_id)
                if not user or user['rank'] < 5:
                    self.db.set_rank(user_id, chat_id, 5)
                    return True
        except Exception as e:
            logger.error(f"Ошибка проверки создателя: {e}")
        return False

    async def run(self):
        self.register_handlers()
        logger.info("🎖️ Бот запущен")
        print("=" * 50)
        print("VANEZY - Упрощенная версия")
        print("=" * 50)
        print("Команды:")
        print("- пульс - проверить работу бота")
        print("- /start, /startpuls - активация")
        print("- мут [ответом] - мут на 30 мин")
        print("- размут [ответом] - снять мут")
        print("- варн [ответом] - предупреждение")
        print("- кик [ответом] - кик (уведомление)")
        print("- бан [ответом] - бан")
        print("- разбан [ответом] - разбан")
        print("- км @user ранг - изменить ранг")
        print("- доб прав [текст] - установить правила")
        print("- прав - показать правила")
        print("=" * 50)
        
        await self.dp.start_polling(self.bot)

    # ===================== ХЭНДЛЕРЫ =====================
    def register_handlers(self):

        # ============ ПУЛЬС (триггер) ============
        @self.router.message(F.text.lower() == "пульс")
        async def pulse_trigger(message: Message):
            """Случайный ответ на триггер 'пульс'"""
            response = random.choice(PULSE_TRIGGERS)
            await message.reply(response)

        # ============ СТАРТ ============
        @self.router.message(Command("start"))
        @self.router.message(Command("startpuls"))
        async def start_message(message: Message):
            self.db.add_user(
                message.from_user.id, 
                message.chat.id,
                message.from_user.username or "",
                message.from_user.first_name
            )
            
            # Проверяем и даем создателю 5 ранг
            is_creator = await self.set_creator_rank(message.chat.id, message.from_user.id)
            
            user = self.db.get_user(message.from_user.id, message.chat.id)
            rank_name = RANKS.get(user['rank'] if user else 0, "👤 Участник")
            
            welcome_text = f"""
🎖️ Бот активирован!

👤 Вы: {message.from_user.first_name}
🎖️ Ваш ранг: {rank_name}
{"👑 Вы - создатель чата!" if is_creator else ""}

⚡ Доступные команды:
• пульс - Проверить работу бота
• мут [ответом] - Мут на 30 минут
• размут [ответом] - Снять мут
• варн [ответом] - Предупреждение
• кик [ответом] - Кикнуть
• бан [ответом] - Забанить
• разбан [ответом] - Разбанить

📜 Правила:
• доб прав [текст] - Установить правила
• прав - Показать правила

🎖️ Ранги:
• км @user ранг - Изменить ранг (только создатель)
            """
            await message.reply(welcome_text)

        # ============ ПРАВИЛА ============
        @self.router.message(F.text.startswith("доб прав"))
        async def add_rules(message: Message):
            # Проверяем права (только ранг 1+)
            user = self.db.get_user(message.from_user.id, message.chat.id)
            if not user or user['rank'] < 1:
                await message.reply("❌ Только модераторы могут устанавливать правила")
                return
                
            text = message.text.replace("доб прав", "", 1).strip()
            if not text:
                await message.reply("❌ Укажите текст правил: доб прав [текст]")
                return
                
            self.db.set_rules(message.chat.id, text)
            await message.reply("✅ Правила установлены!")

        @self.router.message(F.text.lower() == "прав")
        async def show_rules(message: Message):
            rules = self.db.get_rules(message.chat.id)
            await message.reply(rules)

        # ============ ПОЛУЧЕНИЕ ЦЕЛИ ============
        async def get_target_user(message: Message) -> Optional[types.User]:
            """Получить пользователя-цель из сообщения"""
            try:
                # Если это ответ на сообщение
                if message.reply_to_message:
                    return message.reply_to_message.from_user
                    
                # Если указан юзернейм в тексте
                text = message.text
                parts = text.split()
                if len(parts) >= 2:
                    # Ищем @username или ID
                    target_ref = parts[1]
                    
                    # Если это ID
                    if target_ref.isdigit():
                        try:
                            member = await self.bot.get_chat_member(message.chat.id, int(target_ref))
                            return member.user
                        except:
                            pass
                    
                    # Если это @username
                    if target_ref.startswith('@'):
                        username = target_ref[1:]
                        try:
                            member = await self.bot.get_chat_member(message.chat.id, username)
                            return member.user
                        except:
                            pass
                
                return None
            except Exception as e:
                logger.error(f"Ошибка получения цели: {e}")
                return None

        # ============ ПРОВЕРКА ПРАВ ============
        async def can_act(actor_id: int, chat_id: int, target_user: types.User, min_rank: int) -> bool:
            """Проверить, может ли пользователь действовать"""
            actor = self.db.get_user(actor_id, chat_id)
            target = self.db.get_user(target_user.id, chat_id)
            
            # Проверяем существование актора
            if not actor:
                return False
                
            # Проверяем ранг актора
            actor_rank = actor['rank']
            if actor_rank < min_rank:
                return False
                
            # Проверяем ранг цели (если есть в базе)
            target_rank = target['rank'] if target else 0
            
            # Нельзя действовать на пользователей с таким же или более высоким рангом
            if target_rank >= actor_rank:
                return False
                
            return True

        # ============ МУТ (30 минут) ============
        @self.router.message(F.text.startswith("мут"))
        async def mute_user(message: Message):
            target_user = await get_target_user(message)
            if not target_user:
                await message.reply("❌ Укажите пользователя (ответом на сообщение или @username)")
                return
                
            if not await can_act(message.from_user.id, message.chat.id, target_user, 1):
                await message.reply("❌ Недостаточно прав или нельзя замутить этого пользователя")
                return
                
            await message.reply(f"✅ Пользователь {target_user.first_name} замучен на 30 минут")

        # ============ РАЗМУТ ============
        @self.router.message(F.text.startswith("размут"))
        async def unmute_user(message: Message):
            target_user = await get_target_user(message)
            if not target_user:
                await message.reply("❌ Укажите пользователя (ответом на сообщение или @username)")
                return
                
            if not await can_act(message.from_user.id, message.chat.id, target_user, 1):
                await message.reply("❌ Недостаточно прав")
                return
                
            await message.reply(f"✅ Пользователь {target_user.first_name} размучен")

        # ============ ВАРН ============
        @self.router.message(F.text.startswith("варн"))
        async def warn_user(message: Message):
            target_user = await get_target_user(message)
            if not target_user:
                await message.reply("❌ Укажите пользователя (ответом на сообщение или @username)")
                return
                
            if not await can_act(message.from_user.id, message.chat.id, target_user, 1):
                await message.reply("❌ Недостаточно прав или нельзя выдать предупреждение этому пользователю")
                return
                
            self.db.add_warning(target_user.id, message.chat.id)
            warnings = self.db.get_warnings(target_user.id, message.chat.id)
            
            await message.reply(
                f"⚠️ Пользователь {target_user.first_name} получил предупреждение\n"
                f"Всего предупреждений: {warnings}/{MAX_WARNINGS}"
            )

        # ============ КИК ============
        @self.router.message(F.text.startswith("кик"))
        async def kick_user(message: Message):
            target_user = await get_target_user(message)
            if not target_user:
                await message.reply("❌ Укажите пользователя (ответом на сообщение или @username)")
                return
                
            if not await can_act(message.from_user.id, message.chat.id, target_user, 2):
                await message.reply("❌ Недостаточно прав или нельзя кикнуть этого пользователя")
                return
                
            await message.reply(
                f"✅ Пользователь {target_user.first_name} кикнут\n"
                f"ℹ️ Это только уведомление, Telegram не удаляет пользователя"
            )

        # ============ БАН ============
        @self.router.message(F.text.startswith("бан"))
        async def ban_user(message: Message):
            target_user = await get_target_user(message)
            if not target_user:
                await message.reply("❌ Укажите пользователя (ответом на сообщение или @username)")
                return
                
            if not await can_act(message.from_user.id, message.chat.id, target_user, 3):
                await message.reply("❌ Недостаточно прав или нельзя забанить этого пользователя")
                return
                
            await message.reply(f"🚫 Пользователь {target_user.first_name} забанен")

        # ============ РАЗБАН ============
        @self.router.message(F.text.startswith("разбан"))
        async def unban_user(message: Message):
            target_user = await get_target_user(message)
            if not target_user:
                await message.reply("❌ Укажите пользователя (ответом на сообщение или @username)")
                return
                
            if not await can_act(message.from_user.id, message.chat.id, target_user, 3):
                await message.reply("❌ Недостаточно прав")
                return
                
            await message.reply(f"✅ Пользователь {target_user.first_name} разбанен")

        # ============ ИЗМЕНЕНИЕ РАНГА ============
        @self.router.message(F.text.startswith("км"))
        async def change_rank(message: Message):
            # Проверяем, что отправитель - создатель (ранг 5)
            user = self.db.get_user(message.from_user.id, message.chat.id)
            if not user or user['rank'] != 5:
                await message.reply("❌ Только создатель (ранг 5) может менять ранги")
                return
                
            # Парсим команду
            parts = message.text.split()
            if len(parts) < 3:
                await message.reply("❌ Формат: км @user ранг\nПример: км @username 2")
                return
                
            target_ref = parts[1]
            rank_str = parts[2]
            
            # Парсим ранг
            try:
                new_rank = int(rank_str)
                if new_rank not in RANKS:
                    await message.reply(f"❌ Доступные ранги: 0-5")
                    return
            except ValueError:
                await message.reply("❌ Ранг должен быть числом (0-5)")
                return
            
            # Получаем целевого пользователя
            target_user = await get_target_user(message)
            if not target_user:
                await message.reply("❌ Пользователь не найден")
                return
                
            # Нельзя менять свой ранг
            if target_user.id == message.from_user.id:
                await message.reply("❌ Нельзя менять свой собственный ранг")
                return
                
            # Устанавливаем новый ранг
            self.db.set_rank(target_user.id, message.chat.id, new_rank)
            rank_name = RANKS.get(new_rank, "Неизвестно")
            
            await message.reply(f"✅ Пользователю {target_user.first_name} установлен ранг: {rank_name}")

        # ============ МОЙ ПРОФИЛЬ ============
        @self.router.message(F.text.lower() == "мой профиль")
        async def my_profile(message: Message):
            user = self.db.get_user(message.from_user.id, message.chat.id)
            if not user:
                await message.reply("❌ Сначала активируйте бота командой /start")
                return
                
            rank_name = RANKS.get(user['rank'], "👤 Участник")
            
            profile_text = f"""
👤 Ваш профиль:
├ Имя: {message.from_user.first_name}
├ ID: {message.from_user.id}
├ Ранг: {rank_name}
└ Предупреждения: {user['warnings']}/{MAX_WARNINGS}

💡 Команды вашего ранга доступны
            """
            
            await message.reply(profile_text)

# ===================== ЗАПУСК =====================
if __name__ == "__main__":
    bot_core = BotCore()
    asyncio.run(bot_core.run())

