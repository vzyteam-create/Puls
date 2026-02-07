import sqlite3
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

# ================= НАСТРОЙКИ =================
BOT_TOKEN = "7966298894:AAGweQLZrxjWh4AziSl5P5WqVCnsPqU2S0U"
OWNER_ID = 6802316
ADMIN_PANEL_PASSWORD = "vanezypuls13579"

DEFAULT_MAX_ACCOUNTS = 3
DEFAULT_ACCOUNT_COOLDOWN_HOURS = 72

# ================= БОТ =================
bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================= БАЗА =================
db = sqlite3.connect("bot.db")
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER,
    username TEXT,
    password TEXT,
    created_at TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS sessions (
    tg_id INTEGER PRIMARY KEY,
    account_id INTEGER,
    login_time TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS user_limits (
    tg_id INTEGER PRIMARY KEY,
    max_accounts INTEGER,
    cooldown_hours INTEGER
)
""")

db.commit()

# ================= FSM =================
class RegisterFSM(StatesGroup):
    username = State()
    password = State()

class LoginFSM(StatesGroup):
    username = State()
    password = State()

class AdminPasswordFSM(StatesGroup):
    password = State()

# ================= УТИЛИТЫ =================
def get_limits(tg_id):
    cur.execute("SELECT max_accounts, cooldown_hours FROM user_limits WHERE tg_id=?", (tg_id,))
    row = cur.fetchone()
    if row:
        return row
    return DEFAULT_MAX_ACCOUNTS, DEFAULT_ACCOUNT_COOLDOWN_HOURS

def is_logged_in(tg_id):
    cur.execute("SELECT 1 FROM sessions WHERE tg_id=?", (tg_id,))
    return cur.fetchone() is not None

def get_active_account(tg_id):
    cur.execute("""
    SELECT a.id, a.username FROM sessions s
    JOIN accounts a ON a.id = s.account_id
    WHERE s.tg_id=?
    """, (tg_id,))
    return cur.fetchone()

# ================= START =================
@dp.message(CommandStart())
async def start(msg: Message):
    kb = []

    if not is_logged_in(msg.from_user.id):
        kb.append([InlineKeyboardButton(text="📝 Регистрация", callback_data="register")])
        kb.append([InlineKeyboardButton(text="🔐 Войти", callback_data="login")])
    else:
        kb.append([InlineKeyboardButton(text="🔓 Закрытая функция", callback_data="private")])
        kb.append([InlineKeyboardButton(text="🚪 Выйти из аккаунта", callback_data="logout")])

        if msg.chat.type == "private" and msg.from_user.id == OWNER_ID:
            kb.append([InlineKeyboardButton(text="⚙ Админ-панель", callback_data="admin")])

    text = (
        "👋 Привет!\n\n"
        "Это тестовый Pulse-бот.\n"
        "Здесь ты можешь создавать игровые аккаунты и входить в них.\n\n"
        "🔒 Часть функций доступна только после входа."
    )

    await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# ================= РЕГИСТРАЦИЯ =================
@dp.callback_query(F.data == "register")
async def register_start(cb: CallbackQuery, state: FSMContext):
    tg_id = cb.from_user.id

    max_acc, cooldown = get_limits(tg_id)

    cur.execute("SELECT COUNT(*) FROM accounts WHERE tg_id=?", (tg_id,))
    count = cur.fetchone()[0]

    if count >= max_acc:
        await cb.message.answer(
            f"⛔ Ты уже создал {count} из {max_acc} возможных аккаунтов.\n"
            "Удаление аккаунтов пока недоступно."
        )
        return

    cur.execute(
        "SELECT created_at FROM accounts WHERE tg_id=? ORDER BY created_at DESC LIMIT 1",
        (tg_id,)
    )
    row = cur.fetchone()
    if row:
        last = datetime.fromisoformat(row[0])
        if datetime.now() < last + timedelta(hours=cooldown):
            await cb.message.answer(
                f"⏳ Ты недавно создавал аккаунт.\n"
                f"Следующий можно создать после {last + timedelta(hours=cooldown)}"
            )
            return

    await cb.message.answer("📝 Введи логин для нового аккаунта:")
    await state.set_state(RegisterFSM.username)

@dp.message(RegisterFSM.username)
async def reg_username(msg: Message, state: FSMContext):
    await state.update_data(username=msg.text)
    await msg.answer("🔑 Теперь введи пароль:")
    await state.set_state(RegisterFSM.password)

@dp.message(RegisterFSM.password)
async def reg_password(msg: Message, state: FSMContext):
    data = await state.get_data()
    cur.execute(
        "INSERT INTO accounts (tg_id, username, password, created_at) VALUES (?, ?, ?, ?)",
        (msg.from_user.id, data["username"], msg.text, datetime.now().isoformat())
    )
    db.commit()
    await state.clear()
    await msg.answer("✅ Аккаунт успешно создан! Теперь можешь войти.")

# ================= ВХОД =================
@dp.callback_query(F.data == "login")
async def login_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer("🔐 Введи логин:")
    await state.set_state(LoginFSM.username)

@dp.message(LoginFSM.username)
async def login_user(msg: Message, state: FSMContext):
    await state.update_data(username=msg.text)
    await msg.answer("🔑 Введи пароль:")
    await state.set_state(LoginFSM.password)

@dp.message(LoginFSM.password)
async def login_pass(msg: Message, state: FSMContext):
    data = await state.get_data()
    cur.execute(
        "SELECT id FROM accounts WHERE tg_id=? AND username=? AND password=?",
        (msg.from_user.id, data["username"], msg.text)
    )
    row = cur.fetchone()
    if not row:
        await msg.answer("❌ Неверные данные.")
        return

    cur.execute("REPLACE INTO sessions VALUES (?, ?, ?)",
                (msg.from_user.id, row[0], datetime.now().isoformat()))
    db.commit()
    await state.clear()
    await msg.answer("🎉 Ты успешно вошёл в аккаунт!")

# ================= ЗАКРЫТАЯ ФУНКЦИЯ =================
@dp.callback_query(F.data == "private")
async def private(cb: CallbackQuery):
    if not is_logged_in(cb.from_user.id):
        await cb.message.answer("🔒 Эта функция доступна только после входа.")
        return

    acc = get_active_account(cb.from_user.id)
    await cb.message.answer(
        f"✅ Закрытая функция работает!\n\n"
        f"Ты вошёл в аккаунт: {acc[1]}"
    )

# ================= ВЫХОД =================
@dp.callback_query(F.data == "logout")
async def logout(cb: CallbackQuery):
    cur.execute("DELETE FROM sessions WHERE tg_id=?", (cb.from_user.id,))
    db.commit()
    await cb.message.answer("🚪 Ты вышел из аккаунта.")

# ================= АДМИНКА =================
@dp.callback_query(F.data == "admin")
async def admin(cb: CallbackQuery, state: FSMContext):
    if cb.message.chat.type != "private":
        return
    if not is_logged_in(cb.from_user.id):
        await cb.message.answer("🔒 Сначала войди в аккаунт.")
        return
    if cb.from_user.id != OWNER_ID:
        await cb.message.answer("❌ Доступ запрещён.")
        return

    await cb.message.answer("🔑 Введи пароль админ-панели:")
    await state.set_state(AdminPasswordFSM.password)

@dp.message(AdminPasswordFSM.password)
async def admin_panel(msg: Message, state: FSMContext):
    if msg.text != ADMIN_PANEL_PASSWORD:
        await msg.answer("❌ Неверный пароль.")
        return

    cur.execute("SELECT COUNT(*) FROM accounts")
    accs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM sessions")
    online = cur.fetchone()[0]

    await state.clear()
    await msg.answer(
        "⚙ Админ-панель\n\n"
        f"👥 Всего аккаунтов: {accs}\n"
        f"🟢 Активных сессий: {online}\n\n"
        "Это тестовая админка."
    )

# ================= ЗАПУСК =================
if __name__ == "__main__":
    import asyncio
    asyncio.run(dp.start_polling(bot))



