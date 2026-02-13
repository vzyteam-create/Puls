import asyncio
import logging
import sqlite3
import re
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ContentType, ParseMode

# --------------------- НАСТРОЙКИ ---------------------
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"                  # ← @PulsSupport
ADMIN_IDS = [123456789, 987654321]            # ← ID администраторов
MAIN_BOT_USERNAME = "@PulsOfficialManager_bot"
DB_FILE = "tickets.db"

# --------------------- БАЗА ДАННЫХ ---------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            username TEXT,
            first_name TEXT,
            created_at TEXT NOT NULL,
            last_message_at TEXT,
            status TEXT DEFAULT 'open'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS support_admins (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# --------------------- СОСТОЯНИЯ ---------------------
class AdminRegistration(StatesGroup):
    waiting_for_name = State()

class TicketStates(StatesGroup):
    in_dialog = State()

# --------------------- ПОМОЩЬ ФУНКЦИИ ---------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def get_admin_name(user_id: int) -> Optional[str]:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT display_name FROM support_admins WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def save_admin_name(user_id: int, display_name: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO support_admins (user_id, display_name) VALUES (?, ?)",
                   (user_id, display_name))
    conn.commit()
    conn.close()

def get_or_create_ticket(user: types.User) -> int:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM tickets WHERE user_id = ?", (user.id,))
    row = cursor.fetchone()
    
    if row:
        ticket_id = row[0]
        cursor.execute("UPDATE tickets SET last_message_at = ? WHERE id = ?",
                       (datetime.utcnow().isoformat(), ticket_id))
    else:
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            INSERT INTO tickets (user_id, username, first_name, created_at, last_message_at, status)
            VALUES (?, ?, ?, ?, ?, 'open')
        """, (user.id, user.username, user.first_name, now, now))
        ticket_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    return ticket_id

# --------------------- КЛАВИАТУРЫ ---------------------
def get_main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📩 Написать в поддержку", callback_data="support:start")
    builder.button(text="🌐 Главный бот", url=f"https://t.me/{MAIN_BOT_USERNAME.lstrip('@')}")
    builder.button(text="ℹ️ О проекте", callback_data="info:about")
    builder.adjust(1)
    return builder.as_markup()

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="support:cancel")
    return builder.as_markup()

def get_after_message_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✉️ Продолжить", callback_data="support:continue")
    builder.button(text="🔙 В меню", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()

def get_group_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📩 Поддержка в ЛС", url="https://t.me/PulsSupport")
    builder.button(text="🌐 Главный бот", url=f"https://t.me/{MAIN_BOT_USERNAME.lstrip('@')}")
    builder.adjust(1)
    return builder.as_markup()

# --------------------- ИНИЦИАЛИЗАЦИЯ ---------------------
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --------------------- /start ---------------------
@dp.message(CommandStart())
async def cmd_start(message: Message):
    if message.chat.type != 'private':
        await message.answer(
            "👋 Привет! Для вопросов и предложений пиши мне в личные сообщения.",
            reply_markup=get_group_menu()
        )
        return

    user = message.from_user

    if is_admin(user.id) and not get_admin_name(user.id):
        await message.answer(
            "👋 Добро пожаловать в панель поддержки!\n\n"
            "Введите своё имя в формате:\n"
            "Имя Ф.\n\nПример: Иван З."
        )
        await state.set_state(AdminRegistration.waiting_for_name)
        return

    ticket_id = get_or_create_ticket(user)

    await message.answer(
        f"👋 Добро пожаловать в поддержку Puls!\n\n"
        f"Ваш номер обращения: **#{ticket_id}**\n\n"
        "Напишите ваш вопрос, предложение или пришлите фото/видео/голосовое.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu()
    )

    await state.set_state(TicketStates.in_dialog)

# --------------------- РЕГИСТРАЦИЯ АДМИНА ---------------------
@dp.message(AdminRegistration.waiting_for_name)
async def register_admin(message: Message, state: FSMContext):
    name = message.text.strip()
    if not re.match(r'^[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z]\.$', name):
        await message.answer("Неверный формат. Пример: Иван З.\nПопробуйте ещё раз.")
        return

    save_admin_name(message.from_user.id, name)
    await state.clear()
    await message.answer(f"Вы зарегистрированы как **{name}**.\nТеперь можете отвечать пользователям.")

# --------------------- CALLBACK ---------------------
@dp.callback_query()
async def process_callback(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data

    if data == "support:start":
        await state.set_state(TicketStates.in_dialog)
        await callback.message.answer(
            "Напишите сообщение в поддержку.\nМожно отправлять текст, фото, видео, альбомы, голосовые.",
            reply_markup=get_cancel_keyboard()
        )

    elif data == "support:cancel":
        await state.clear()
        await callback.message.edit_text("Обращение отменено.", reply_markup=get_main_menu())

    elif data == "support:continue":
        await state.set_state(TicketStates.in_dialog)
        await callback.message.answer("Продолжаем диалог. Напишите сообщение.")

    elif data == "menu:main":
        await callback.message.edit_text("Главное меню:", reply_markup=get_main_menu())

    elif data == "info:about":
        await callback.message.answer("Puls — удобный инструмент для крипты и трейдинга.")

    await callback.answer()

# --------------------- СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЯ ---------------------
@dp.message(TicketStates.in_dialog, lambda m: m.chat.type == 'private')
async def handle_user_message(message: Message, state: FSMContext):
    user = message.from_user

    # Запрет мусора (стикеры, GIF, только эмодзи)
    if message.sticker or message.animation or (
        message.text and all(c in '😀😁😂🤣😃😄😅😆😉😊😋😎😍😘🥰🤩🤔🤨😐😑😶🙄😏😣😥😮🤐😯😪😫😴😌😛😜😝🤤😒😓😔😕🙃🤑😲☹️🙁😖😞😟😤😢😭😦😧😨😩🤯😬😰😱🥵🥶😳🤪😵🥴😠😡🤬😷🤒🤕🤢🤮🤧😇🤠🥳🥸🤥🤫🤭🧐🤓😈👿🤡' for c in message.text.strip())
    ):
        await message.answer("Пожалуйста, отправляйте осмысленные сообщения. Бот для вопросов и предложений.")
        return

    ticket_id = get_or_create_ticket(user)

    user_info = (
        f"<b>Тикет #{ticket_id}</b>\n"
        f"<a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
        f"ID: <code>{user.id}</code>\n"
        f"@{user.username or 'нет'}\n"
        f"──────────────────────\n"
    )

    for admin_id in ADMIN_IDS:
        try:
            if message.text:
                await bot.send_message(admin_id, user_info + message.text, parse_mode=ParseMode.HTML)
            else:
                await message.forward(admin_id)
                await bot.send_message(admin_id, user_info, parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.error(f"Ошибка отправки админу {admin_id}: {e}")

    await message.answer(
        f"Сообщение отправлено в тикет **#{ticket_id}**.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_after_message_menu()
    )

# --------------------- ОТВЕТ АДМИНА ---------------------
@dp.message(lambda m: is_admin(m.from_user.id) and m.reply_to_message)
async def handle_admin_reply(message: Message):
    replied = message.reply_to_message

    if not replied.forward_from:
        return

    user_id = replied.forward_from.id
    admin_name = get_admin_name(message.from_user.id)

    if not admin_name:
        await message.reply("Вы не зарегистрированы. Напишите /start.")
        return

    try:
        prefix = f"Вам ответил **{admin_name}** из поддержки:\n\n"

        if message.text:
            await bot.send_message(user_id, prefix + message.text, parse_mode=ParseMode.MARKDOWN)
        else:
            await message.copy_to(user_id)
            await bot.send_message(user_id, prefix + "↑", parse_mode=ParseMode.MARKDOWN)

        await message.reply(f"Ответ отправлен от имени {admin_name}")
    except Exception as e:
        await message.reply(f"Ошибка: {e}")

# --------------------- ЗАПУСК ---------------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
