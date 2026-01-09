import logging
import asyncio
import sqlite3
import random
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions,
    CallbackQuery
)
from aiogram.utils import executor

# ================= НАСТРОЙКИ =================
BOT_TOKEN = "ТОКЕН_БОТА"
OWNER_ID = 6708209142

CHANNEL_URL = "https://t.me/VanezyScripts"
SUPPORT_MAIN = "@vanezyyy"
SUPPORT_BOT = "@VanezyPulsSupport"

WELCOME_IMAGE = "https://i.yapx.ru/cfBKc.jpg"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)

# ================= БАЗА ДАННЫХ =================
db = sqlite3.connect("bot.db")
sql = db.cursor()

sql.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER,
    chat_id INTEGER,
    rank INTEGER DEFAULT 1,
    warns INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, chat_id)
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS mutes (
    user_id INTEGER,
    chat_id INTEGER,
    until INTEGER,
    reason TEXT,
    moderator INTEGER,
    msg_link TEXT
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS settings (
    chat_id INTEGER PRIMARY KEY,
    rules TEXT
)
""")

db.commit()

# ================= УТИЛИТЫ =================
def get_rank(user_id: int, chat_id: int) -> int:
    sql.execute(
        "SELECT rank FROM users WHERE user_id=? AND chat_id=?",
        (user_id, chat_id)
    )
    result = sql.fetchone()
    return result[0] if result else 1


def set_user(user_id: int, chat_id: int):
    sql.execute(
        "INSERT OR IGNORE INTO users (user_id, chat_id) VALUES (?, ?)",
        (user_id, chat_id)
    )
    db.commit()


def set_rank(user_id: int, chat_id: int, rank: int):
    sql.execute(
        "UPDATE users SET rank=? WHERE user_id=? AND chat_id=?",
        (rank, user_id, chat_id)
    )
    db.commit()


def require_rank(min_rank: int):
    async def decorator(handler):
        async def wrapper(message: Message, *args, **kwargs):
            user_rank = get_rank(message.from_user.id, message.chat.id)
            if user_rank < min_rank:
                await message.reply(
                    f"⛔ Недостаточно прав\n"
                    f"Требуется ранг: {min_rank}\n"
                    f"Ваш ранг: {user_rank}"
                )
                return
            return await handler(message, *args, **kwargs)
        return wrapper
    return decorator

# ================= РЕГИСТРАЦИЯ ПОЛЬЗОВАТЕЛЯ =================
@dp.message_handler()
async def register_user(message: Message):
    if message.chat.type in ["group", "supergroup"]:
        set_user(message.from_user.id, message.chat.id)

# ================= ПРОВЕРКА ЗАПУСКА =================
if __name__ == "__main__":
    print("🤖 PULS BOT | ЧАСТЬ 1 загружена")
    executor.start_polling(dp, skip_updates=True)
