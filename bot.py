import asyncio
import time
import random
import sqlite3
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ================== CONFIG ==================
BOT_TOKEN = "8557190026:AAGnqxtrAyZz-huihyGctKWNHgjt7w9lQTo"
ADMIN_ID = 6708209142
ADMIN_PASSWORD = "pulsvanezymanager13579"
ADMIN_SESSION_TIME = 30 * 60  # 30 минут
# ============================================

bot = Bot(BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)

# ================== DATABASE ==================
db = sqlite3.connect("pulse_game.db")
sql = db.cursor()

sql.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    coins INTEGER DEFAULT 100,
    games_used INTEGER DEFAULT 0,
    game_cd INTEGER DEFAULT 0,
    bonus_cd INTEGER DEFAULT 0,
    last_action INTEGER DEFAULT 0
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS admin_sessions (
    user_id INTEGER,
    expire INTEGER
)
""")

db.commit()

# ================== HELPERS ==================
def get_user(uid):
    sql.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    u = sql.fetchone()
    if not u:
        sql.execute("INSERT INTO users (user_id) VALUES (?)", (uid,))
        db.commit()
        return get_user(uid)
    return u


def is_admin(uid):
    sql.execute("SELECT expire FROM admin_sessions WHERE user_id=?", (uid,))
    row = sql.fetchone()
    return row and row[0] > int(time.time())


async def clear_admin_messages(uid):
    sql.execute("DELETE FROM admin_sessions WHERE user_id=?", (uid,))
    db.commit()
    # сообщения удаляются «тихо» — логика реализована через хранение message_id
    # (специально не делаем уведомлений)


def anti_spam(uid):
    now = int(time.time())
    user = get_user(uid)
    if now - user[5] < 2:
        return False
    sql.execute("UPDATE users SET last_action=? WHERE user_id=?", (now, uid))
    db.commit()
    return True

# ================== KEYBOARDS ==================
def main_menu(is_admin=False):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎮 Играть", callback_data="game"),
        InlineKeyboardButton("👷 Работа", callback_data="work"),
        InlineKeyboardButton("🎁 Бонус", callback_data="bonus"),
        InlineKeyboardButton("🏆 Рейтинг", callback_data="rating"),
        InlineKeyboardButton("🛒 Магазин", callback_data="shop")
    )
    if is_admin:
        kb.add(InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin"))
    return kb


def admin_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📊 Статистика", callback_data="adm_stats"),
        InlineKeyboardButton("💰 Выдать коины", callback_data="adm_add"),
        InlineKeyboardButton("➖ Уменьшить коины", callback_data="adm_remove"),
        InlineKeyboardButton("🔁 Изменить баланс", callback_data="adm_set"),
        InlineKeyboardButton("❌ Обнулить баланс", callback_data="adm_clear"),
        InlineKeyboardButton("📢 Рассылка", callback_data="adm_broadcast"),
        InlineKeyboardButton("🎲 Сюрприз", callback_data="adm_fun")
    )
    return kb

# ================== START ==================
@dp.message_handler(commands=["start", "startpuls"])
async def start(message: types.Message):
    get_user(message.from_user.id)
    await message.answer(
        "⚡ <b>RealDonate Pulse</b>\n\n"
        "Добро пожаловать в игровой мир Pulse.\n"
        "Зарабатывай коины, рискуй в играх, соревнуйся в рейтинге\n"
        "и прокачивай свой баланс.\n\n"
        "Выбери действие ниже 👇",
        reply_markup=main_menu(is_admin(message.from_user.id))
    )

# ================== WORK ==================
@dp.callback_query_handler(lambda c: c.data == "work")
async def work(call):
    uid = call.from_user.id
    if not anti_spam(uid): return
    earn = random.randint(20, 40)
    sql.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (earn, uid))
    db.commit()
    await call.message.edit_text(
        f"👷 <b>Работа выполнена</b>\n\n"
        f"Ты получил: <b>+{earn}</b> Pulse Coins 💰",
        reply_markup=main_menu(is_admin(uid))
    )

# ================== BONUS ==================
@dp.callback_query_handler(lambda c: c.data == "bonus")
async def bonus(call):
    uid = call.from_user.id
    user = get_user(uid)
    now = int(time.time())

    if user[4] > now:
        await call.answer("Бонус ещё недоступен", show_alert=True)
        return

    sql.execute(
        "UPDATE users SET coins = coins + 50, bonus_cd=? WHERE user_id=?",
        (now + 86400, uid)
    )
    db.commit()

    await call.message.edit_text(
        "🎁 <b>Ежедневный бонус</b>\n\n"
        "+50 Pulse Coins 💎",
        reply_markup=main_menu(is_admin(uid))
    )

# ================== GAME ==================
@dp.callback_query_handler(lambda c: c.data == "game")
async def game(call):
    uid = call.from_user.id
    user = get_user(uid)
    now = int(time.time())

    if user[3] > now:
        await call.answer("Игровой КД активен", show_alert=True)
        return

    if user[2] >= 3:
        sql.execute(
            "UPDATE users SET games_used=0, game_cd=? WHERE user_id=?",
            (now + 5 * 3600, uid)
        )
        db.commit()
        await call.answer("Попытки закончились", show_alert=True)
        return

    await call.message.answer(
        "🎮 <b>Игра</b>\n\n"
        "Отправь сумму ставки\n"
        "Минимум: <b>25</b> Pulse Coins"
    )


@dp.message_handler(lambda m: m.text.isdigit())
async def game_bet(message: types.Message):
    uid = message.from_user.id
    bet = int(message.text)
    user = get_user(uid)

    if bet < 25 or user[1] < bet:
        return

    win = random.choice([True, False])

    if win:
        reward = bet * 2
        sql.execute(
            "UPDATE users SET coins = coins + ?, games_used = games_used + 1 WHERE user_id=?",
            (reward, uid)
        )
        text = f"🎉 Победа!\nТы выиграл <b>{reward}</b> 💰"
    else:
        sql.execute(
            "UPDATE users SET coins = coins - ?, games_used = games_used + 1 WHERE user_id=?",
            (bet, uid)
        )
        text = "💀 Поражение\nСтавка потеряна"

    db.commit()
    await message.answer(text, reply_markup=main_menu(is_admin(uid)))

# ================== RATING ==================
@dp.callback_query_handler(lambda c: c.data == "rating")
async def rating(call):
    sql.execute("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    top = sql.fetchall()
    text = "🏆 <b>Топ игроков</b>\n\n"
    for i, u in enumerate(top, 1):
        text += f"{i}. <code>{u[0]}</code> — {u[1]} 💰\n"
    await call.message.edit_text(text, reply_markup=main_menu(is_admin(call.from_user.id)))

# ================== SHOP ==================
@dp.callback_query_handler(lambda c: c.data == "shop")
async def shop(call):
    await call.message.edit_text(
        "🛒 <b>Магазин</b>\n\n"
        "Скоро здесь появятся бустеры,\n"
        "уникальные возможности и предметы.",
        reply_markup=main_menu(is_admin(call.from_user.id))
    )

# ================== ADMIN LOGIN ==================
@dp.callback_query_handler(lambda c: c.data == "admin")
async def admin_login(call):
    if call.from_user.id != ADMIN_ID:
        return

    if is_admin(call.from_user.id):
        await call.message.edit_text(
            "⚙️ <b>Админ-панель</b>",
            reply_markup=admin_menu()
        )
        return

    await call.message.answer("🔐 Введите пароль администратора:")


@dp.message_handler(lambda m: m.from_user.id == ADMIN_ID)
async def admin_password(message: types.Message):
    if message.text.lower() == ADMIN_PASSWORD.lower():
        expire = int(time.time()) + ADMIN_SESSION_TIME
        sql.execute(
            "INSERT OR REPLACE INTO admin_sessions VALUES (?,?)",
            (ADMIN_ID, expire)
        )
        db.commit()

        asyncio.create_task(admin_session_timer(ADMIN_ID, expire))

        await message.answer(
            "⚙️ <b>Админ-панель</b>",
            reply_markup=admin_menu()
        )

# ================== ADMIN SESSION TIMER ==================
async def admin_session_timer(uid, expire):
    await asyncio.sleep(ADMIN_SESSION_TIME)
    if not is_admin(uid):
        await clear_admin_messages(uid)

# ================== ADMIN FEATURES ==================
@dp.callback_query_handler(lambda c: c.data.startswith("adm_"))
async def admin_actions(call):
    if not is_admin(call.from_user.id):
        return

    action = call.data

    if action == "adm_stats":
        sql.execute("SELECT COUNT(*) FROM users")
        users = sql.fetchone()[0]
        await call.message.answer(
            f"📊 <b>Статистика</b>\n\n"
            f"👥 Пользователей: <b>{users}</b>"
        )

    elif action == "adm_fun":
        await call.message.answer(
            "🎲 <b>Сюрприз</b>\n\n"
            "Админ всегда на шаг впереди 😎"
        )

# ================== RUN ==================
if __name__ == "__main__":
    executor.start_polling(dp)
