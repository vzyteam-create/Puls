import asyncio
import re
from datetime import datetime, timedelta
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.enums import ParseMode, ChatMemberStatus

# ─────────── НАСТРОЙКИ ───────────
BOT_TOKEN = "8557190026:AAHAhHOxPQ4HlFHbGokpyTFoQ2R_a634rE4"

# ─────────── ИНИЦИАЛИЗАЦИЯ ───────────
bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# ─────────── SQLite ───────────
conn = sqlite3.connect("permissions.db")
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS permissions(
    chat_id INTEGER,
    user_id INTEGER,
    can_mute INTEGER DEFAULT 0,
    can_ban INTEGER DEFAULT 0,
    can_kick INTEGER DEFAULT 0,
    PRIMARY KEY(chat_id, user_id)
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS punishments(
    chat_id INTEGER,
    user_id INTEGER,
    type TEXT,
    until TIMESTAMP,
    reason TEXT
)
""")
conn.commit()

# ─────────── УТИЛИТЫ ───────────
TIME_RE = re.compile(r"(\d+)([смчд])")

def parse_time(text: str):
    if text in ("0", "inf", "навсегда"):
        return None
    m = TIME_RE.match(text)
    if not m:
        return None
    value, unit = m.groups()
    value = int(value)
    return {
        "с": timedelta(seconds=value),
        "м": timedelta(minutes=value),
        "ч": timedelta(hours=value),
        "д": timedelta(days=value),
    }[unit]

async def is_creator(message: Message):
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status == ChatMemberStatus.OWNER

async def is_admin_with_permission(chat_id, user_id, command):
    cur.execute(f"SELECT {command} FROM permissions WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    row = cur.fetchone()
    return row and row[0]

async def resolve_user(message: Message, arg: str | None):
    if message.reply_to_message:
        return message.reply_to_message.from_user
    if not arg:
        return None
    if arg.startswith("@"):
        member = await bot.get_chat_member(message.chat.id, arg[1:])
        return member.user
    if arg.isdigit():
        member = await bot.get_chat_member(message.chat.id, int(arg))
        return member.user
    return None

def perms_all():
    return ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True
    )

# ─────────── ПРАВА НА КОМАНДЫ ───────────
@dp.message(F.text.regexp(r"^(\+лм|\-лм) (мут|бан|кик)"))
async def manage_permissions(message: Message):
    if not await is_creator(message):
        return
    parts = message.text.split()
    action = parts[0]  # +лм или -лм
    command = parts[1]  # мут, бан, кик
    target_arg = parts[2] if len(parts) > 2 else None
    user = await resolve_user(message, target_arg)
    if not user:
        return
    cur.execute("SELECT * FROM permissions WHERE chat_id=? AND user_id=?", (message.chat.id, user.id))
    if not cur.fetchone():
        cur.execute("INSERT OR IGNORE INTO permissions(chat_id, user_id) VALUES (?,?)", (message.chat.id, user.id))
    col = {"мут": "can_mute", "бан": "can_ban", "кик": "can_kick"}[command]
    value = 1 if action == "+лм" else 0
    cur.execute(f"UPDATE permissions SET {col}=? WHERE chat_id=? AND user_id=?", (value, message.chat.id, user.id))
    conn.commit()
    await message.answer(f"✅ Права {'добавлены' if value else 'удалены'}: {command} для {user.full_name}")

# ─────────── ФУНКЦИЯ НАКАЗАНИЯ ───────────
async def apply_punishment(message: Message, command: str):
    parts = message.text.split()
    duration_str = parts[1] if len(parts) > 1 else "inf"
    target_arg = parts[2] if len(parts) > 2 and not message.reply_to_message else None
    reason = " ".join(parts[3:] if target_arg else parts[2:]) or "не указана"
    user_target = await resolve_user(message, target_arg)
    if not user_target:
        return
    # Проверка прав
    cmd_map = {"мут": "can_mute", "бан": "can_ban", "кик": "can_kick"}
    if not await is_admin_with_permission(message.chat.id, message.from_user.id, cmd_map[command]):
        await message.answer(f"❌ У вас нет права {command}")
        return
    until_time = parse_time(duration_str)
    until_ts = datetime.utcnow() + until_time if until_time else None

    # Создание кнопки снять ограничение
    kb = InlineKeyboardMarkup().add(
        InlineKeyboardButton("Снять ограничение", callback_data=f"un{command}_{message.chat.id}_{user_target.id}")
    ) if command in ("мут", "бан") else None

    if command == "мут":
        await bot.restrict_chat_member(message.chat.id, user_target.id,
                                      permissions=ChatPermissions(can_send_messages=False),
                                      until_date=until_ts)
    elif command == "бан":
        await bot.ban_chat_member(message.chat.id, user_target.id, until_date=until_ts)
    elif command == "кик":
        await bot.ban_chat_member(message.chat.id, user_target.id)
        await bot.unban_chat_member(message.chat.id, user_target.id)
    await message.answer(
        f"⚠️ <b>{user_target.full_name}</b> {command}!\n"
        f"⏱ Время: {duration_str}\n📄 Причина: {reason}\n🛡 Модератор: {message.from_user.full_name}",
        reply_markup=kb
    )
    # Сохраняем в SQLite для авто-размут/разбан
    if command in ("мут", "бан"):
        cur.execute("INSERT INTO punishments(chat_id,user_id,type,until,reason) VALUES(?,?,?,?,?)",
                    (message.chat.id, user_target.id, command, until_ts, reason))
        conn.commit()

# ─────────── КОМАНДЫ ───────────
@dp.message(F.text.regexp(r"^/?(м|mute)"))  # мут
async def mute_cmd(message: Message):
    await apply_punishment(message, "мут")

@dp.message(F.text.regexp(r"^/?(б|ban)"))  # бан
async def ban_cmd(message: Message):
    await apply_punishment(message, "бан")

@dp.message(F.text.regexp(r"^/?(к|kick)"))  # кик
async def kick_cmd(message: Message):
    await apply_punishment(message, "кик")

@dp.message(F.text.regexp(r"^/?(рм|rm)"))  # размут
async def unmute_cmd(message: Message):
    parts = message.text.split()
    target_arg = parts[1] if len(parts)>1 else None
    user_target = await resolve_user(message, target_arg)
    if not user_target:
        return
    if not await is_admin_with_permission(message.chat.id, message.from_user.id, "can_mute"):
        await message.answer("❌ У вас нет права размучивать, бывает же такое, ну обратись к Ванезу хотя-бы,может он поможет...")
        return
    await bot.restrict_chat_member(message.chat.id, user_target.id, permissions=perms_all())
    await message.answer(f"🔓 <b>{user_target.full_name}</b> размучен\n🛡 Модератор: {message.from_user.full_name}")
    cur.execute("DELETE FROM punishments WHERE chat_id=? AND user_id=? AND type='мут'", (message.chat.id, user_target.id))
    conn.commit()

@dp.message(F.text.regexp(r"^/?(рб|rb)"))  # разбан
async def unban_cmd(message: Message):
    parts = message.text.split()
    target_arg = parts[1] if len(parts)>1 else None
    user_target = await resolve_user(message, target_arg)
    if not user_target:
        return
    if not await is_admin_with_permission(message.chat.id, message.from_user.id, "can_ban"):
        await message.answer("❌ У вас нет права разбанивать, даже не пытайтесь...")
        return
    await bot.unban_chat_member(message.chat.id, user_target.id)
    await message.answer(f"🔓 <b>{user_target.full_name}</b> разбанен\n🛡 Модератор: {message.from_user.full_name}")
    cur.execute("DELETE FROM punishments WHERE chat_id=? AND user_id=? AND type='бан'", (message.chat.id, user_target.id))
    conn.commit()

# ─────────── КНОПКИ СНЯТИЯ ───────────
@dp.callback_query(F.data.regexp(r"^un(мут|бан)_"))
async def un_punish_cb(query: CallbackQuery):
    cmd, chat_id, user_id = query.data.split("_")
    chat_id, user_id = int(chat_id), int(user_id)
    if cmd == "мут":
        await bot.restrict_chat_member(chat_id, user_id, permissions=perms_all())
        cur.execute("DELETE FROM punishments WHERE chat_id=? AND user_id=? AND type='мут'", (chat_id, user_id))
    elif cmd == "бан":
        await bot.unban_chat_member(chat_id, user_id)
        cur.execute("DELETE FROM punishments WHERE chat_id=? AND user_id=? AND type='бан'", (chat_id, user_id))
    conn.commit()
    await query.message.edit_text(f"✅ Ограничение снято (автор: {query.from_user.full_name})")

# ─────────── ВХОД / ВЫХОД ───────────
@dp.message(F.new_chat_members)
async def on_join(message: Message):
    for user in message.new_chat_members:
        text = (
            f"👋 <b>Новый участник!</b>\n\n"
            f"👤 Имя: {user.full_name}\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"🔗 Username: @{user.username if user.username else 'нет'}\n"
            f"🤖 Бот: {'Да' if user.is_bot else 'Нет'}\n"
            f"🌍 Язык: {user.language_code if user.language_code else 'не указан'}\n"
            f"💬 Статус в чате: member\n\n"
            f"🎉 Добро пожаловать в чат! Здесь будет весело 🎈"
        )
        await message.answer(text)

@dp.message(F.left_chat_member)
async def on_leave(message: Message):
    user = message.left_chat_member
    text = (
        f"🚪 <b>Участник покинул чат</b>\n\n"
        f"👤 Имя: {user.full_name}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"🔗 Username: @{user.username if user.username else 'нет'}\n"
        f"🤖 Бот: {'Да' if user.is_bot else 'Нет'}\n"
        f"💬 Статус в чате: member\n\n"
        f"😔 Пока, надеемся вернёшься!"
    )
    await message.answer(text)

# ─────────── START ───────────
@dp.message(F.text == "/start")
async def start_cmd(message: Message):
    await message.answer(
        "🤖 <b>Модератор-бот</b>\n\n"
        "Команды:\n"
        "🔇 м / mute — мут\n"
        "🔓 рм / rm — размут\n"
        "🚫 б / ban — бан\n"
        "🔓 рб / rb — разбан\n"
        "👢 к / kick — кик\n\n"
        "Команды выдачи прав: +лм / -лм\n"
        "Только создатель группы может выдавать права.\n"
        "Работает по ответу, @username и ID"
    )

# ─────────── АВТО-ОГРАНИЧЕНИЯ ───────────
async def punishment_watcher():
    while True:
        now = datetime.utcnow()
        cur.execute("SELECT chat_id, user_id, type FROM punishments WHERE until IS NOT NULL AND until<=?", (now,))
        rows = cur.fetchall()
        for chat_id, user_id, type_ in rows:
            try:
                if type_ == "мут":
                    await bot.restrict_chat_member(chat_id, user_id, permissions=perms_all())
                elif type_ == "бан":
                    await bot.unban_chat_member(chat_id, user_id)
                cur.execute("DELETE FROM punishments WHERE chat_id=? AND user_id=? AND type=?", (chat_id, user_id, type_))
            except:
                pass
        conn.commit()
        await asyncio.sleep(10)

# ─────────── ЗАПУСК ───────────
async def main():
    asyncio.create_task(punishment_watcher())
    print("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

