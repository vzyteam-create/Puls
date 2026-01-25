import logging
import re
import sqlite3
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8557190026:AAGnqxtrAyZz-huihyGctKWNHgjt7w9lQTo"
ADMIN_ID = 6802316  # ТВОЙ Telegram ID
ADMIN_PASSWORD = "pulsvanezymanager13579"

# ================== БОТ ==================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot, storage=MemoryStorage())

# ================== БАЗА ДАННЫХ ==================
db = sqlite3.connect("pulse_full.db", check_same_thread=False)
sql = db.cursor()

sql.execute("""
CREATE TABLE IF NOT EXISTS pulse_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT UNIQUE,
    password TEXT,
    secret_word TEXT,
    blocked INTEGER DEFAULT 0,
    created_at TEXT
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS tg_sessions (
    tg_id INTEGER PRIMARY KEY,
    login TEXT,
    login_time TEXT
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS admin_sessions (
    tg_id INTEGER PRIMARY KEY,
    expires_at TEXT
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER,
    username TEXT,
    action TEXT,
    login TEXT,
    time TEXT
)
""")

db.commit()

# ================== FSM ==================
class RegisterFSM(StatesGroup):
    login = State()
    password = State()
    secret = State()

class LoginFSM(StatesGroup):
    login = State()
    password = State()

class AdminFSM(StatesGroup):
    password = State()

# ================== УТИЛИТЫ ==================
def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log_action(user, action, login=None):
    sql.execute(
        "INSERT INTO logs VALUES (NULL, ?, ?, ?, ?, ?)",
        (
            user.id,
            user.username,
            action,
            login,
            now()
        )
    )
    db.commit()

def is_admin_session(tg_id):
    sql.execute("SELECT expires_at FROM admin_sessions WHERE tg_id=?", (tg_id,))
    row = sql.fetchone()
    if not row:
        return False
    return datetime.fromisoformat(row[0]) > datetime.now()

# ================== START ==================
@dp.message_handler(commands=["start"])
async def start(msg: types.Message):
    await msg.answer(
        "👋 <b>Pulse Bot</b>\n\n"
        "Это внутренняя система Pulse-аккаунтов.\n"
        "Регистрация, вход и управление доступны в личных сообщениях."
    )

# ================== РЕГИСТРАЦИЯ ==================
@dp.message_handler(commands=["registerpuls"])
async def register_start(msg: types.Message):
    if msg.chat.type != "private":
        await msg.answer("❌ Регистрация доступна только в личных сообщениях.")
        await bot.send_message(
            msg.from_user.id,
            "🔐 <b>Регистрация Pulse-аккаунта</b>\n\n"
            "Никому не передавайте логин, пароль и кодовое слово.\n"
            "Администрация никогда не просит ваши данные."
        )
        return

    await msg.answer("Введите логин (латиница, 4–20 символов):")
    await RegisterFSM.login.set()

@dp.message_handler(state=RegisterFSM.login)
async def reg_login(msg: types.Message, state: FSMContext):
    login = msg.text.lower()

    if not re.fullmatch(r"[a-z0-9_]{4,20}", login):
        await msg.answer("❌ Неверный формат логина.")
        return

    sql.execute("SELECT 1 FROM pulse_accounts WHERE login=?", (login,))
    if sql.fetchone():
        await msg.answer("❌ Такой логин уже существует.")
        return

    await state.update_data(login=login)
    await msg.answer("Введите пароль (мин. 5 символов, буквы + цифры):")
    await RegisterFSM.password.set()

@dp.message_handler(state=RegisterFSM.password)
async def reg_password(msg: types.Message, state: FSMContext):
    password = msg.text

    if (
        len(password) < 5
        or not re.search(r"[A-Za-z]", password)
        or not re.search(r"\d", password)
    ):
        await msg.answer("❌ Слишком простой пароль.")
        return

    await state.update_data(password=password)
    await msg.answer(
        "Введите кодовое слово (английские буквы 5–20)\n"
        "Или напишите <b>пропустить</b>"
    )
    await RegisterFSM.secret.set()

@dp.message_handler(state=RegisterFSM.secret)
async def reg_secret(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    secret = None

    if msg.text.lower() != "пропустить":
        if not re.fullmatch(r"[A-Za-z]{5,20}", msg.text):
            await msg.answer("❌ Неверный формат кодового слова.")
            return
        secret = msg.text

    sql.execute(
        "INSERT INTO pulse_accounts VALUES (NULL, ?, ?, ?, 0, ?)",
        (data["login"], data["password"], secret, now())
    )
    db.commit()

    log_action(msg.from_user, "REGISTER", data["login"])

    await msg.answer(
        f"✅ <b>Регистрация успешна!</b>\n\n"
        f"Логин: <code>{data['login']}</code>\n"
        f"Не передавайте данные третьим лицам."
    )
    await state.finish()

# ================== ВХОД ==================
@dp.message_handler(commands=["loginpuls"])
async def login_start(msg: types.Message):
    if msg.chat.type != "private":
        return

    await msg.answer("Введите логин:")
    await LoginFSM.login.set()

@dp.message_handler(state=LoginFSM.login)
async def login_login(msg: types.Message, state: FSMContext):
    await state.update_data(login=msg.text.lower())
    await msg.answer("Введите пароль:")
    await LoginFSM.password.set()

@dp.message_handler(state=LoginFSM.password)
async def login_password(msg: types.Message, state: FSMContext):
    data = await state.get_data()

    sql.execute(
        "SELECT blocked FROM pulse_accounts WHERE login=? AND password=?",
        (data["login"], msg.text)
    )
    row = sql.fetchone()

    if not row:
        await msg.answer("❌ Неверные данные.")
        await state.finish()
        return

    if row[0] == 1:
        await msg.answer("🚫 Этот аккаунт заблокирован.")
        await state.finish()
        return

    sql.execute(
        "REPLACE INTO tg_sessions VALUES (?, ?, ?)",
        (msg.from_user.id, data["login"], now())
    )
    db.commit()

    log_action(msg.from_user, "LOGIN", data["login"])

    await msg.answer(f"✅ Вы вошли в аккаунт <b>{data['login']}</b>")
    await state.finish()

# ================== ВЫХОД ==================
@dp.message_handler(commands=["logoutpuls"])
async def logout(msg: types.Message):
    sql.execute("DELETE FROM tg_sessions WHERE tg_id=?", (msg.from_user.id,))
    db.commit()
    log_action(msg.from_user, "LOGOUT")
    await msg.answer("🚪 Вы вышли из Pulse-аккаунта.")

# ================== АДМИН ВХОД ==================
@dp.message_handler(commands=["admin"])
async def admin(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return

    if is_admin_session(msg.from_user.id):
        await admin_panel(msg)
        return

    await msg.answer("🔐 Введите пароль админ-панели:")
    await AdminFSM.password.set()

@dp.message_handler(state=AdminFSM.password)
async def admin_password(msg: types.Message, state: FSMContext):
    if msg.text != ADMIN_PASSWORD:
        await msg.answer("❌ Неверный пароль.")
        return

    expires = datetime.now() + timedelta(minutes=30)
    sql.execute(
        "REPLACE INTO admin_sessions VALUES (?, ?)",
        (msg.from_user.id, expires.isoformat())
    )
    db.commit()

    await state.finish()
    await admin_panel(msg)

async def admin_panel(msg):
    sql.execute("SELECT login, password, secret_word, blocked FROM pulse_accounts")
    rows = sql.fetchall()

    text = "🛠 <b>Pulse Admin Panel</b>\n\n"
    for login, password, secret, blocked in rows:
        text += (
            f"👤 <b>{login}</b>\n"
            f"🔑 Пароль: <code>{password}</code>\n"
            f"🗝 Кодовое: <code>{secret}</code>\n"
            f"🚫 Блокировка: {'Да' if blocked else 'Нет'}\n\n"
        )

    await msg.answer(text or "Нет аккаунтов.")

# ================== ЗАПУСК ==================
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
