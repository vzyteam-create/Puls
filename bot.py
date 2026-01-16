import asyncio
import re
from datetime import datetime, timedelta
import sqlite3

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.enums import ChatMemberStatus, ParseMode

# ─────────── НАСТРОЙКИ ───────────
BOT_TOKEN = "ВСТАВЬ_СЮДА_ТОКЕН"
OWNER_ID = 6708209142  # @vanezyyy
ADMIN_PANEL_PASSWORD = "vanezyypuls13579cod"

# ─────────── ИНИЦИАЛИЗАЦИЯ ───────────
bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# ─────────── SQLite ───────────
conn = sqlite3.connect("puls_bot.db")
cur = conn.cursor()

# Права модераторов
cur.execute("""
CREATE TABLE IF NOT EXISTS permissions(
    chat_id INTEGER,
    user_id INTEGER,
    command TEXT,
    PRIMARY KEY(chat_id, user_id, command)
)
""")
# Система наказаний
cur.execute("""
CREATE TABLE IF NOT EXISTS punishments(
    chat_id INTEGER,
    user_id INTEGER,
    type TEXT,
    until TIMESTAMP,
    reason TEXT
)
""")
# Пользователи и игры
cur.execute("""
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    puls_coins INTEGER DEFAULT 0,
    dollars INTEGER DEFAULT 0,
    last_work TIMESTAMP,
    work_count INTEGER DEFAULT 0,
    last_game TIMESTAMP,
    game_count INTEGER DEFAULT 0
)
""")
# Админ-панель блокировки
cur.execute("""
CREATE TABLE IF NOT EXISTS admin_block(
    user_id INTEGER PRIMARY KEY,
    attempts INTEGER DEFAULT 0,
    blocked_until TIMESTAMP
)
""")
conn.commit()

# ─────────── УТИЛИТЫ ───────────
TIME_RE = re.compile(r"(\d+)([smhd])", re.IGNORECASE)

def parse_time(text: str):
    if text.lower() in ("0", "inf", "навсегда"):
        return None
    m = TIME_RE.match(text)
    if not m:
        return None
    value, unit = m.groups()
    value = int(value)
    return {
        "s": timedelta(seconds=value),
        "m": timedelta(minutes=value),
        "h": timedelta(hours=value),
        "d": timedelta(days=value),
    }[unit.lower()]

def perms_all():
    return ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True
    )

def perms_mute():
    return ChatPermissions(
        can_send_messages=False,
        can_send_media_messages=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False
    )

async def resolve_user(message: Message, arg: str | None):
    if message.reply_to_message:
        return message.reply_to_message.from_user
    if not arg:
        return None
    if arg.startswith("@"):
        try:
            member = await bot.get_chat_member(message.chat.id, arg[1:])
            return member.user
        except:
            return None
    if arg.isdigit():
        try:
            member = await bot.get_chat_member(message.chat.id, int(arg))
            return member.user
        except:
            return None
    return None

async def has_permission(chat_id, user_id, command):
    if user_id == OWNER_ID:
        return True
    cur.execute("SELECT 1 FROM permissions WHERE chat_id=? AND user_id=? AND command=?", (chat_id, user_id, command))
    return cur.fetchone() is not None

async def is_creator(message: Message):
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status == ChatMemberStatus.OWNER

# ─────────── ПРИВЕТСТВИЕ ───────────
@dp.message(F.new_chat_members)
async def on_join(message: Message):
    for user in message.new_chat_members:
        if user.id == (await bot.me).id:
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                InlineKeyboardButton("📜 Правила бота", url="https://t.me/RulesPulsOfficial/8"),
                InlineKeyboardButton("🛠 Админ-панель", callback_data="admin_panel"),
                InlineKeyboardButton("➕ Добавить в группу", url=f"https://t.me/{(await bot.me).username}?startgroup=true"),
                InlineKeyboardButton("🎮 Играть", callback_data="game")
            )
            text = (
                f"🎉 Добро пожаловать в Puls Bot! 🎊\n\n"
                f"Я универсальный бот, который может наказывать участников, которые нарушают ваши правила.\n"
                f"Для начала прочитайте правила бота, нажав кнопку «Правила бота» ниже.\n\n"
                f"Продолжая использовать бота, вы соглашаетесь с правилами.\n\n"
                f"Добавьте меня в группу и веселитесь!"
            )
            await message.answer(text, reply_markup=kb)
        else:
            await message.answer(
                f"👋 <b>Новый участник!</b>\n\n"
                f"👤 Имя: {user.full_name}\n"
                f"🆔 ID: <code>{user.id}</code>\n"
                f"🔗 Username: @{user.username if user.username else 'нет'}\n"
                f"🤖 Бот: {'Да' if user.is_bot else 'Нет'}"
            )

@dp.message(F.left_chat_member)
async def on_leave(message: Message):
    user = message.left_chat_member
    await message.answer(
        f"🚪 <b>Участник покинул чат</b>\n\n"
        f"👤 Имя: {user.full_name}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"🔗 Username: @{user.username if user.username else 'нет'}"
    )

# ─────────── НАКАЗАНИЯ ───────────
async def apply_punishment(message: Message, command: str):
    parts = message.text.split()
    duration_str = parts[1] if len(parts) > 1 else "inf"
    target_arg = parts[2] if len(parts) > 2 and not message.reply_to_message else None
    reason = " ".join(parts[3:] if target_arg else parts[2:]) or "не указана"
    user_target = await resolve_user(message, target_arg)
    if not user_target:
        await message.answer("❌ Пользователь не найден.")
        return

    cmd_map = {"м": "can_mute", "мут": "can_mute", "бан": "can_ban", "б": "can_ban", "кик": "can_kick", "к": "can_kick"}
    if not await has_permission(message.chat.id, message.from_user.id, cmd_map.get(command, "")):
        await message.answer("❌ У вас нет прав на это действие.")
        return

    until_time = parse_time(duration_str)
    until_ts = datetime.utcnow() + until_time if until_time else None

    kb = InlineKeyboardMarkup().add(
        InlineKeyboardButton("Снять ограничение", callback_data=f"un_{command}_{message.chat.id}_{user_target.id}")
    )

    if command in ("м", "мут"):
        await bot.restrict_chat_member(message.chat.id, user_target.id, permissions=perms_mute(), until_date=until_ts)
    elif command in ("б", "бан"):
        await bot.ban_chat_member(message.chat.id, user_target.id, until_date=until_ts)
    elif command in ("к", "кик"):
        await bot.ban_chat_member(message.chat.id, user_target.id)
        await bot.unban_chat_member(message.chat.id, user_target.id)

    await message.answer(
        f"⚠️ <b>{user_target.full_name}</b> {command}!\n"
        f"⏱ Время: {duration_str}\n📄 Причина: {reason}\n🛡 Модератор: {message.from_user.full_name}",
        reply_markup=kb
    )

    if command in ("м", "мут", "б", "бан"):
        cur.execute("INSERT INTO punishments(chat_id,user_id,type,until,reason) VALUES(?,?,?,?,?)",
                    (message.chat.id, user_target.id, command, until_ts, reason))
        conn.commit()

# ─────────── СНЯТИЕ ОГРАНИЧЕНИЙ ───────────
@dp.callback_query(F.data.regexp(r"^un_"))
async def un_punish_cb(query: CallbackQuery):
    parts = query.data.split("_")
    command, chat_id, user_id = parts[1], int(parts[2]), int(parts[3])
    if command in ("м", "мут"):
        await bot.restrict_chat_member(chat_id, user_id, permissions=perms_all())
        cur.execute("DELETE FROM punishments WHERE chat_id=? AND user_id=? AND type IN ('м','мут')", (chat_id, user_id))
    elif command in ("б", "бан"):
        await bot.unban_chat_member(chat_id, user_id)
        cur.execute("DELETE FROM punishments WHERE chat_id=? AND user_id=? AND type IN ('б','бан')", (chat_id, user_id))
    conn.commit()
    await query.message.edit_text(f"✅ Ограничение снято пользователю (по запросу {query.from_user.full_name})")

# ─────────── АВТО-СНЯТИЕ ───────────
async def punishment_watcher():
    while True:
        now = datetime.utcnow()
        cur.execute("SELECT chat_id, user_id, type FROM punishments WHERE until IS NOT NULL AND until<=?", (now,))
        rows = cur.fetchall()
        for chat_id, user_id, type_ in rows:
            try:
                if type_ in ("м", "мут"):
                    await bot.restrict_chat_member(chat_id, user_id, permissions=perms_all())
                elif type_ in ("б", "бан"):
                    await bot.unban_chat_member(chat_id, user_id)
                cur.execute("DELETE FROM punishments WHERE chat_id=? AND user_id=? AND type=?", (chat_id, user_id, type_))
            except:
                pass
        conn.commit()
        await asyncio.sleep(5)

# ─────────── СТАРТ И ПОМОЩЬ ───────────
@dp.message(F.text.lower().regexp(r"^/start$|^/startpuls$", flags=re.IGNORECASE))
async def start_cmd(message: Message):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📜 Правила бота", url="https://t.me/RulesPulsOfficial/8"),
        InlineKeyboardButton("🛠 Админ-панель", callback_data="admin_panel"),
        InlineKeyboardButton("🎮 Играть", callback_data="game")
    )
    await message.answer(
        "🎉 Добро пожаловать в Puls Bot!\nЯ помогу вам с модерацией, играми и мини-экономикой.\nИспользуйте кнопки ниже, чтобы ознакомиться с функциями!",
        reply_markup=kb
    )

@dp.message(F.text.lower().regexp(r"^/helppuls$|^Помощь$", flags=re.IGNORECASE))
async def help_cmd(message: Message):
    await message.answer(
        "📖 Доступные команды:\n"
        "Модерация:\n/m - мут, /rm - размут\n/b - бан, /rb - разбан\n/k - кик\n\n"
        "Экономика и игры:\n/работать - заработать деньги\n/gamepuls - мини-игра\n\n"
        "Прочее:\n/start, /startpuls - старт и приветствие\n"
        "⚠️ Некоторые функции в разработке."
    )

# ─────────── ЗАПУСК ───────────
async def main():
    asyncio.create_task(punishment_watcher())
    print("Puls Bot запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
