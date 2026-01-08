#!/usr/bin/env python3
"""
🎖️ Telegram Bot с наказаниями и системой рангов
"""

import asyncio
import logging
import sqlite3
import random
import sys
from typing import Optional

from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.types import Message
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command
from aiogram.exceptions import TelegramUnauthorizedError

# ===================== ПРОВЕРЬ ТОКЕН =====================
# Твой токен должен быть такой же как в @BotFather
BOT_TOKEN = "8566099089:AAFKQa3PHKEBqVspwpHrmn6WhIcmZg83RLo"  # ЗАМЕНИ ЕСЛИ НЕ РАБОТАЕТ
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

# Триггеры "пульс"
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

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
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

    async def check_bot_token(self):
        """Проверить валидность токена"""
        try:
            me = await self.bot.get_me()
            logger.info(f"✅ Бот авторизован: @{me.username} (ID: {me.id})")
            return True
        except TelegramUnauthorizedError:
            logger.error("❌ Неверный токен бота! Проверь токен в @BotFather")
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка при проверке токена: {e}")
            return False

    async def set_creator_rank(self, chat_id, user_id):
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
        # Проверяем токен перед запуском
        if not await self.check_bot_token():
            print("=" * 60)
            print("❌ ОШИБКА: Неверный токен бота!")
            print("=" * 60)
            print("1. Зайди в @BotFather")
            print("2. Нажми /mybots")
            print("3. Выбери своего бота")
            print("4. Нажми API Token")
            print("5. Скопируй новый токен")
            print("6. Замени BOT_TOKEN в коде")
            print("=" * 60)
            return
        
        self.register_handlers()
        
        print("=" * 60)
        print("🎖️ VANEZY - Упрощенная версия")
        print("=" * 60)
        print("Команды:")
        print("• пульс - проверить работу бота")
        print("• /start, /startpuls - активация")
        print("• мой профиль - информация о себе")
        print("• мут [ответом] - мут на 30 мин")
        print("• размут [ответом] - снять мут")
        print("• варн [ответом] - предупреждение")
        print("• кик [ответом] - кик (уведомление)")
        print("• бан [ответом] - бан")
        print("• разбан [ответом] - разбан")
        print("• км @user ранг - изменить ранг")
        print("• доб прав [текст] - установить правила")
        print("• прав - показать правила")
        print("=" * 60)
        
        logger.info("🚀 Бот запускается...")
        
        try:
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Ошибка при работе бота: {e}")

    # ===================== ХЭНДЛЕРЫ =====================
    def register_handlers(self):

        # ============ ПУЛЬС ============
        @self.router.message(F.text.lower() == "пульс")
        async def pulse_trigger(message: Message):
            response = random.choice(PULSE_TRIGGERS)
            await message.reply(response)

        # ============ СТАРТ ============
        @self.router.message(Command("start", "startpuls"))
        async def start_message(message: Message):
            self.db.add_user(
                message.from_user.id, 
                message.chat.id,
                message.from_user.username or "",
                message.from_user.first_name
            )
            
            is_creator = await self.set_creator_rank(message.chat.id, message.from_user.id)
            
            user = self.db.get_user(message.from_user.id, message.chat.id)
            rank_name = RANKS.get(user['rank'] if user else 0, "👤 Участник")
            
            welcome_text = f"""🎖️ Бот активирован!

👤 Вы: {message.from_user.first_name}
🎖️ Ваш ранг: {rank_name}
{"👑 Вы - создатель чата!" if is_creator else ""}

⚡ Основные команды:
• пульс - Проверить работу бота
• мой профиль - Ваша информация
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

💡 Все команды работают без / и в любом регистре!"""
            await message.reply(welcome_text)

        # ============ МОЙ ПРОФИЛЬ ============
        @self.router.message(F.text.lower().contains("мой профиль"))
        @self.router.message(F.text.lower() == "профиль")
        async def my_profile(message: Message):
            user = self.db.get_user(message.from_user.id, message.chat.id)
            if not user:
                await message.reply("❌ Сначала активируйте бота командой /start")
                return
                
            rank_name = RANKS.get(user['rank'], "👤 Участник")
            
            profile_text = f"""👤 Ваш профиль:
┌─────────────────
├ Имя: {message.from_user.first_name}
├ ID: {message.from_user.id}
├ Username: @{message.from_user.username or "нет"}
├ Ранг: {rank_name}
├ Предупреждения: {user['warnings']}/{MAX_WARNINGS}
└ Муты/Баны: {user['mutes']}/{user['bans']}

💡 Доступные команды зависят от вашего ранга"""
            
            await message.reply(profile_text)

        # ============ ПРАВИЛА ============
        @self.router.message(F.text.startswith("доб прав"))
        async def add_rules(message: Message):
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

        # ============ НАКАЗАНИЯ ============
        async def get_target_user(message: Message) -> Optional[types.User]:
            try:
                if message.reply_to_message:
                    return message.reply_to_message.from_user
                    
                text = message.text
                parts = text.split()
                if len(parts) >= 2:
                    target_ref = parts[1]
                    
                    if target_ref.isdigit():
                        try:
                            member = await self.bot.get_chat_member(message.chat.id, int(target_ref))
                            return member.user
                        except:
                            pass
                    
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

        async def can_act(actor_id: int, chat_id: int, target_user: types.User, min_rank: int) -> bool:
            actor = self.db.get_user(actor_id, chat_id)
            target = self.db.get_user(target_user.id, chat_id)
            
            if not actor:
                return False
                
            actor_rank = actor['rank']
            if actor_rank < min_rank:
                return False
                
            target_rank = target['rank'] if target else 0
            
            if target_rank >= actor_rank:
                return False
                
            return True

        # МУТ
        @self.router.message(F.text.lower().startswith("мут"))
        async def mute_user(message: Message):
            target_user = await get_target_user(message)
            if not target_user:
                await message.reply("❌ Укажите пользователя (ответом на сообщение или @username)")
                return
                
            if not await can_act(message.from_user.id, message.chat.id, target_user, 1):
                await message.reply("❌ Недостаточно прав или нельзя замутить этого пользователя")
                return
                
            await message.reply(f"✅ Пользователь {target_user.first_name} замучен на 30 минут")

        # РАЗМУТ
        @self.router.message(F.text.lower().startswith("размут"))
        async def unmute_user(message: Message):
            target_user = await get_target_user(message)
            if not target_user:
                await message.reply("❌ Укажите пользователя (ответом на сообщение или @username)")
                return
                
            if not await can_act(message.from_user.id, message.chat.id, target_user, 1):
                await message.reply("❌ Недостаточно прав")
                return
                
            await message.reply(f"✅ Пользователь {target_user.first_name} размучен")

        # ВАРН
        @self.router.message(F.text.lower().startswith("варн"))
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
            
            await message.reply(f"⚠️ Пользователь {target_user.first_name} получил предупреждение\nВсего предупреждений: {warnings}/{MAX_WARNINGS}")

        # КИК
        @self.router.message(F.text.lower().startswith("кик"))
        async def kick_user(message: Message):
            target_user = await get_target_user(message)
            if not target_user:
                await message.reply("❌ Укажите пользователя (ответом на сообщение или @username)")
                return
                
            if not await can_act(message.from_user.id, message.chat.id, target_user, 2):
                await message.reply("❌ Недостаточно прав или нельзя кикнуть этого пользователя")
                return
                
            await message.reply(f"✅ Пользователь {target_user.first_name} кикнут\nℹ️ Это только уведомление, Telegram не удаляет пользователя")

        # БАН
        @self.router.message(F.text.lower().startswith("бан"))
        async def ban_user(message: Message):
            target_user = await get_target_user(message)
            if not target_user:
                await message.reply("❌ Укажите пользователя (ответом на сообщение или @username)")
                return
                
            if not await can_act(message.from_user.id, message.chat.id, target_user, 3):
                await message.reply("❌ Недостаточно прав или нельзя забанить этого пользователя")
                return
                
            await message.reply(f"🚫 Пользователь {target_user.first_name} забанен")

        # РАЗБАН
        @self.router.message(F.text.lower().startswith("разбан"))
        async def unban_user(message: Message):
            target_user = await get_target_user(message)
            if not target_user:
                await message.reply("❌ Укажите пользователя (ответом на сообщение или @username)")
                return
                
            if not await can_act(message.from_user.id, message.chat.id, target_user, 3):
                await message.reply("❌ Недостаточно прав")
                return
                
            await message.reply(f"✅ Пользователь {target_user.first_name} разбанен")

        # ИЗМЕНЕНИЕ РАНГА
        @self.router.message(F.text.lower().startswith("км"))
        async def change_rank(message: Message):
            user = self.db.get_user(message.from_user.id, message.chat.id)
            if not user or user['rank'] != 5:
                await message.reply("❌ Только создатель (ранг 5) может менять ранги")
                return
                
            parts = message.text.split()
            if len(parts) < 3:
                await message.reply("❌ Формат: км @user ранг\nПример: км @username 2")
                return
                
            target_ref = parts[1]
            rank_str = parts[2]
            
            try:
                new_rank = int(rank_str)
                if new_rank not in RANKS:
                    await message.reply(f"❌ Доступные ранги: 0-5")
                    return
            except ValueError:
                await message.reply("❌ Ранг должен быть числом (0-5)")
                return
            
            target_user = await get_target_user(message)
            if not target_user:
                await message.reply("❌ Пользователь не найден")
                return
                
            if target_user.id == message.from_user.id:
                await message.reply("❌ Нельзя менять свой собственный ранг")
                return
                
            self.db.set_rank(target_user.id, message.chat.id, new_rank)
            rank_name = RANKS.get(new_rank, "Неизвестно")
            
            await message.reply(f"✅ Пользователю {target_user.first_name} установлен ранг: {rank_name}")

        # ПОМОЩЬ
        @self.router.message(F.text.lower().contains("помощь"))
        @self.router.message(F.text.lower() == "команды")
        async def help_command(message: Message):
            user = self.db.get_user(message.from_user.id, message.chat.id)
            rank = user['rank'] if user else 0
            
            help_text = f"""🆘 КОМАНДЫ БОТА:

👤 Основные команды (всем):
• пульс - Проверить работу бота
• мой профиль - Ваша информация
• прав - Показать правила
• помощь - Эта справка

📜 Правила:
• доб прав [текст] - Установить правила

🎖️ Система рангов:
• 0 👤 Участник - базовые команды
• 1 👮 Младший модератор - муты, варны
• 2 🛡️ Старший модератор - +кики
• 3 👑 Администратор - +баны
• 5 ✨ СОЗДАТЕЛЬ - изменение рангов

⚡ Ваш ранг: {RANKS.get(rank, "👤 Участник")}

💡 Все команды работают без / и в любом регистре!
Примеры: пульс, ПУЛЬС, Пульс"""
            
            await message.reply(help_text)

# ===================== ЗАПУСК =====================
if __name__ == "__main__":
    print("=" * 60)
    print("🎖️ VANEZY - Упрощенная версия")
    print("=" * 60)
    print("Запуск бота...")
    
    try:
        bot_core = BotCore()
        asyncio.run(bot_core.run())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
