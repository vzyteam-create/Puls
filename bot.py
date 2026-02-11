import asyncio
import asyncio
import sqlite3
import random
import datetime
import string
from typing import Dict, List, Tuple, Optional
from contextlib import contextmanager
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup,
    KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import FSInputFile

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = 'YOUR_BOT_TOKEN_HERE'
DB_FILE = 'puls_bot.db'

# ========== СИСТЕМА УРОВНЕЙ ==========
LEVELS = {
    1:  {"exp": 0,       "reward_coins": 0,    "bonus_win": 0.00, "bonus_daily": 0.00, "bonus_salary": 0.00, "max_attempts_bonus": 0,  "double_win_chance": 0.00},
    2:  {"exp": 300,     "reward_coins": 10,    "bonus_win": 0.005, "bonus_daily": 0.00, "bonus_salary": 0.00, "max_attempts_bonus": 0,  "double_win_chance": 0.00},
    3:  {"exp": 700,     "reward_coins": 20,   "bonus_win": 0.01,  "bonus_daily": 0.02, "bonus_salary": 0.00, "max_attempts_bonus": 0,  "double_win_chance": 0.005},
    4:  {"exp": 1200,    "reward_coins": 30,   "bonus_win": 0.015, "bonus_daily": 0.04, "bonus_salary": 0.00, "max_attempts_bonus": 0,  "double_win_chance": 0.01},
    5:  {"exp": 2000,    "reward_coins": 50,   "bonus_win": 0.02,  "bonus_daily": 0.06, "bonus_salary": 0.00, "max_attempts_bonus": 1,  "double_win_chance": 0.015},
    6:  {"exp": 3500,    "reward_coins": 60,   "bonus_win": 0.025, "bonus_daily": 0.08, "bonus_salary": 0.02, "max_attempts_bonus": 1,  "double_win_chance": 0.02},
    7:  {"exp": 6000,    "reward_coins": 70,   "bonus_win": 0.03,  "bonus_daily": 0.10, "bonus_salary": 0.03, "max_attempts_bonus": 1,  "double_win_chance": 0.025},
    8:  {"exp": 10000,   "reward_coins": 80,   "bonus_win": 0.035, "bonus_daily": 0.12, "bonus_salary": 0.04, "max_attempts_bonus": 1,  "double_win_chance": 0.03},
    9:  {"exp": 17000,   "reward_coins": 100,  "bonus_win": 0.04,  "bonus_daily": 0.14, "bonus_salary": 0.05, "max_attempts_bonus": 1,  "double_win_chance": 0.035},
    10: {"exp": 28000,   "reward_coins": 125,  "bonus_win": 0.045, "bonus_daily": 0.16, "bonus_salary": 0.06, "max_attempts_bonus": 2,  "double_win_chance": 0.04},
    11: {"exp": 45000,   "reward_coins": 150,  "bonus_win": 0.05,  "bonus_daily": 0.18, "bonus_salary": 0.07, "max_attempts_bonus": 2,  "double_win_chance": 0.045},
    12: {"exp": 70000,   "reward_coins": 180,  "bonus_win": 0.055, "bonus_daily": 0.20, "bonus_salary": 0.08, "max_attempts_bonus": 2,  "double_win_chance": 0.05},
    13: {"exp": 110000,  "reward_coins": 220,  "bonus_win": 0.06,  "bonus_daily": 0.22, "bonus_salary": 0.09, "max_attempts_bonus": 2,  "double_win_chance": 0.055},
    14: {"exp": 170000,  "reward_coins": 270,  "bonus_win": 0.065, "bonus_daily": 0.24, "bonus_salary": 0.10, "max_attempts_bonus": 2,  "double_win_chance": 0.06},
    15: {"exp": 250000,  "reward_coins": 320,  "bonus_win": 0.07,  "bonus_daily": 0.26, "bonus_salary": 0.11, "max_attempts_bonus": 2,  "double_win_chance": 0.065},
    16: {"exp": 380000,  "reward_coins": 380,  "bonus_win": 0.075, "bonus_daily": 0.28, "bonus_salary": 0.12, "max_attempts_bonus": 3,  "double_win_chance": 0.07},
    17: {"exp": 550000,  "reward_coins": 450,  "bonus_win": 0.08,  "bonus_daily": 0.30, "bonus_salary": 0.13, "max_attempts_bonus": 3,  "double_win_chance": 0.075},
    18: {"exp": 800000,  "reward_coins": 530,  "bonus_win": 0.085, "bonus_daily": 0.35, "bonus_salary": 0.14, "max_attempts_bonus": 3,  "double_win_chance": 0.08},
    19: {"exp": 1150000, "reward_coins": 620,  "bonus_win": 0.09,  "bonus_daily": 0.40, "bonus_salary": 0.15, "max_attempts_bonus": 3,  "double_win_chance": 0.085},
    20: {"exp": 1650000, "reward_coins": 750,  "bonus_win": 0.095, "bonus_daily": 0.45, "bonus_salary": 0.16, "max_attempts_bonus": 3,  "double_win_chance": 0.09},
    21: {"exp": 2300000, "reward_coins": 900,  "bonus_win": 0.10,  "bonus_daily": 0.50, "bonus_salary": 0.17, "max_attempts_bonus": 4,  "double_win_chance": 0.095},
    22: {"exp": 3200000, "reward_coins": 1100, "bonus_win": 0.105, "bonus_daily": 0.52, "bonus_salary": 0.175, "max_attempts_bonus": 4,  "double_win_chance": 0.10},
    23: {"exp": 4300000, "reward_coins": 1350, "bonus_win": 0.11,  "bonus_daily": 0.54, "bonus_salary": 0.18, "max_attempts_bonus": 4,  "double_win_chance": 0.105},
    24: {"exp": 5700000, "reward_coins": 1650, "bonus_win": 0.115, "bonus_daily": 0.56, "bonus_salary": 0.185, "max_attempts_bonus": 4,  "double_win_chance": 0.11},
    25: {"exp": 7500000, "reward_coins": 2000, "bonus_win": 0.12,  "bonus_daily": 0.58, "bonus_salary": 0.19, "max_attempts_bonus": 4,  "double_win_chance": 0.115},
    26: {"exp": 10000000,"reward_coins": 2500, "bonus_win": 0.125, "bonus_daily": 0.59, "bonus_salary": 0.195, "max_attempts_bonus": 5,  "double_win_chance": 0.12},
    27: {"exp": 13000000,"reward_coins": 3000, "bonus_win": 0.13,  "bonus_daily": 0.595, "bonus_salary": 0.198, "max_attempts_bonus": 5,  "double_win_chance": 0.125},
    28: {"exp": 17000000,"reward_coins": 3700, "bonus_win": 0.135, "bonus_daily": 0.597, "bonus_salary": 0.199, "max_attempts_bonus": 5,  "double_win_chance": 0.13},
    29: {"exp": 22000000,"reward_coins": 4500, "bonus_win": 0.14,  "bonus_daily": 0.598, "bonus_salary": 0.1995, "max_attempts_bonus": 5, "double_win_chance": 0.135},
    30: {"exp": 28000000,"reward_coins": 5000, "bonus_win": 0.15,  "bonus_daily": 0.60, "bonus_salary": 0.20,  "max_attempts_bonus": 5, "double_win_chance": 0.14},
}

# ========== ПРОФЕССИИ ==========
PROFESSIONS = {
    "none": 0,
    "junior": 50,
    "middle": 100,
    "senior": 300,
    "manager": 400,
    "director": 500
}

# ========== FSM СОСТОЯНИЯ ==========
class AuthStates(StatesGroup):
    login = State()
    password = State()
    new_username = State()
    new_password = State()
    change_old_password = State()
    change_new_password = State()
    change_username = State()

class SettingsStates(StatesGroup):
    main = State()
    language = State()
    auto_bet = State()
    add_account = State()
    change_data = State()
    confirm_change = State()

class AdminStates(StatesGroup):
    password = State()
    manage_prices = State()
    create_giveaway = State()
    set_max_accounts_all = State()
    set_max_accounts_user = State()
    add_quest = State()
    add_quest_reward = State()
    broadcast = State()
    view_account = State()
    create_promotion = State()

class GameStates(StatesGroup):
    choose_difficulty = State()
    choose_game = State()
    bet = State()
    play = State()
    rps_choice = State()
    ttt_move = State()

class ShopStates(StatesGroup):
    browsing = State()
    select_quantity = State()
    confirm_purchase = State()

class LeaderboardStates(StatesGroup):
    viewing = State()

# ========== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ==========
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ========== НАСТРОЙКИ ПОЛЬЗОВАТЕЛЕЙ ==========
USER_SETTINGS = {}  # user_id -> settings

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        tg_id           INTEGER PRIMARY KEY,
        max_accounts    INTEGER DEFAULT 3,
        admin           INTEGER DEFAULT 0,
        language        TEXT DEFAULT 'ru',
        auto_bet        INTEGER DEFAULT 25
    )
    ''')
    
    # Таблица аккаунтов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS accounts (
        account_id          INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id               INTEGER,
        username            TEXT,
        password            TEXT,
        coins               INTEGER DEFAULT 100,
        created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_bonus          DATETIME,
        games_played        INTEGER DEFAULT 0,
        profession          TEXT DEFAULT 'none',
        quest_count_today   INTEGER DEFAULT 0,
        last_quest_date     DATE,
        level               INTEGER DEFAULT 1,
        exp                 INTEGER DEFAULT 0,
        total_exp           INTEGER DEFAULT 0,
        daily_games         INTEGER DEFAULT 0,
        daily_wins          INTEGER DEFAULT 0,
        weekly_games        INTEGER DEFAULT 0,
        weekly_wins         INTEGER DEFAULT 0,
        monthly_games       INTEGER DEFAULT 0,
        monthly_wins        INTEGER DEFAULT 0,
        last_daily_reset    DATE,
        last_week_reset     DATE,
        last_month_reset    DATE
    )
    ''')
    
    # Таблица действий
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS actions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id  INTEGER,
        action      TEXT,
        timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица квестов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS quests (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        type            TEXT,
        description     TEXT,
        reward          INTEGER,
        link            TEXT
    )
    ''')
    
    # Таблица выполненных квестов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS completed_quests (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id      INTEGER,
        quest_id        INTEGER,
        completed_at    DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица цен в магазине
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS shop_prices (
        item    TEXT PRIMARY KEY,
        price   INTEGER
    )
    ''')
    
    # Заполняем стандартные цены
    default_prices = [
        ('junior', 500),
        ('middle', 1000),
        ('senior', 3000),
        ('manager', 7000),
        ('director', 10000),
        ('temp_attempts', 50),
        ('perm_attempts', 800)
    ]
    cursor.executemany('''
    INSERT OR IGNORE INTO shop_prices (item, price) VALUES (?, ?)
    ''', default_prices)
    
    # Таблица розыгрышей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS giveaways (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        prize       TEXT,
        end_time    DATETIME,
        status      TEXT DEFAULT 'active'
    )
    ''')
    
    # Таблица участников розыгрышей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS giveaway_participants (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        giveaway_id     INTEGER,
        account_id      INTEGER,
        UNIQUE(giveaway_id, account_id)
    )
    ''')
    
    # Таблица акций
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS promotions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        item            TEXT,
        discount_percent INTEGER,
        end_time        DATETIME
    )
    ''')
    
    # Таблица попыток игр
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS game_attempts (
        account_id      INTEGER,
        game_name       TEXT,
        daily_attempts  INTEGER DEFAULT 0,
        last_date       DATE,
        permanent_max   INTEGER DEFAULT 5,
        extra_attempts  INTEGER DEFAULT 0,
        PRIMARY KEY (account_id, game_name)
    )
    ''')
    
    conn.commit()
    conn.close()

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def generate_strong_password(length=12):
    """Генерация надежного пароля"""
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(random.choice(characters) for _ in range(length))
    return password

def get_level_info(account):
    """Получить информацию об уровне аккаунта"""
    level = account['level']
    exp = account['exp']
    next_level = level + 1
    next_req = LEVELS.get(next_level, {"exp": 9999999999})["exp"]
    to_next = next_req - exp
    progress = exp / next_req if next_req > 0 else 1.0
    current = LEVELS.get(level, LEVELS[1])
    return {
        "level": level,
        "exp": exp,
        "to_next": to_next,
        "progress": progress,
        "bonus_win": current["bonus_win"],
        "bonus_daily": current["bonus_daily"],
        "bonus_salary": current["bonus_salary"],
        "max_attempts_bonus": current["max_attempts_bonus"],
        "double_win_chance": current["double_win_chance"]
    }

async def add_exp(account_id: int, amount: int):
    """Добавить опыт и проверить повышение уровня"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE accounts SET exp = exp + ?, total_exp = total_exp + ? WHERE account_id = ?",
            (amount, amount, account_id)
        )
        
        cursor.execute("SELECT level, exp, tg_id FROM accounts WHERE account_id = ?", (account_id,))
        level, exp, tg_id = cursor.fetchone()
        
        while level < 30:
            next_req = LEVELS.get(level + 1, {"exp": 9999999999})["exp"]
            if exp >= next_req:
                level += 1
                reward = LEVELS[level]["reward_coins"]
                
                cursor.execute(
                    "UPDATE accounts SET level = ?, coins = coins + ?, exp = exp - ? WHERE account_id = ?",
                    (level, reward, next_req, account_id)
                )
                
                ld = LEVELS[level]
                bonuses = []
                if ld["bonus_win"] > 0: 
                    bonuses.append(f"+{int(ld['bonus_win']*100)}% к выигрышу")
                if ld["bonus_daily"] > 0: 
                    bonuses.append(f"+{int(ld['bonus_daily']*100)}% к ежедневке")
                if ld["bonus_salary"] > 0: 
                    bonuses.append(f"+{int(ld['bonus_salary']*100)}% к зарплате")
                if ld["max_attempts_bonus"] > 0: 
                    bonuses.append(f"+{ld['max_attempts_bonus']} попыток/день")
                if ld["double_win_chance"] > 0: 
                    bonuses.append(f"{int(ld['double_win_chance']*100)}% шанс ×2")
                
                bonus_text = "\n".join(f"• {b}" for b in bonuses) if bonuses else "Новые возможности!"
                
                try:
                    await bot.send_message(
                        tg_id,
                        f"🌟 *Новый уровень: {level}!*\n\n"
                        f"+{reward} Puls Coins\n\n"
                        f"*Бонусы:*\n{bonus_text}"
                    )
                except:
                    pass
                
                exp -= next_req
            else:
                break
        
        conn.commit()
        return level

def check_attempts(account_id: int, game_name: str) -> Tuple[bool, int]:
    """Проверить доступные попытки для игры"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT level FROM accounts WHERE account_id = ?",
            (account_id,)
        )
        level = cursor.fetchone()['level']
        level_bonus = LEVELS.get(level, LEVELS[1])["max_attempts_bonus"]
        
        cursor.execute('''
        SELECT daily_attempts, last_date, permanent_max, extra_attempts 
        FROM game_attempts 
        WHERE account_id = ? AND game_name = ?
        ''', (account_id, game_name))
        
        result = cursor.fetchone()
        today = datetime.date.today().isoformat()
        
        if result:
            daily_attempts, last_date, permanent_max, extra_attempts = result
            
            if last_date != today:
                daily_attempts = 0
                cursor.execute('''
                UPDATE game_attempts 
                SET daily_attempts = 0, last_date = ?
                WHERE account_id = ? AND game_name = ?
                ''', (today, account_id, game_name))
                conn.commit()
            
            total_max = permanent_max + extra_attempts + level_bonus
            
            if daily_attempts < total_max:
                return True, total_max - daily_attempts
            else:
                return False, 0
        else:
            total_max = 5 + level_bonus
            cursor.execute('''
            INSERT INTO game_attempts 
            (account_id, game_name, daily_attempts, last_date, permanent_max, extra_attempts)
            VALUES (?, ?, 0, ?, 5, 0)
            ''', (account_id, game_name, today))
            conn.commit()
            return True, total_max

def use_attempt(account_id: int, game_name: str):
    """Использовать одну попытку"""
    with get_db() as conn:
        cursor = conn.cursor()
        today = datetime.date.today().isoformat()
        
        cursor.execute('''
        UPDATE game_attempts 
        SET daily_attempts = daily_attempts + 1, last_date = ?
        WHERE account_id = ? AND game_name = ?
        ''', (today, account_id, game_name))
        conn.commit()

def reset_daily_stats():
    """Сброс ежедневной статистики"""
    with get_db() as conn:
        cursor = conn.cursor()
        today = datetime.date.today().isoformat()
        
        cursor.execute('''
        UPDATE accounts 
        SET daily_games = 0, daily_wins = 0, last_daily_reset = ?
        WHERE last_daily_reset IS NULL OR last_daily_reset < ?
        ''', (today, today))
        
        conn.commit()

def get_promotion_discount(item: str) -> int:
    """Получить текущую скидку на товар"""
    with get_db() as conn:
        cursor = conn.cursor()
        now = datetime.datetime.now().isoformat()
        
        cursor.execute('''
        SELECT discount_percent FROM promotions 
        WHERE item = ? AND end_time > ? AND discount_percent > 0
        ORDER BY end_time DESC LIMIT 1
        ''', (item, now))
        
        result = cursor.fetchone()
        return result['discount_percent'] if result else 0

# ========== КЛАВИАТУРЫ ==========
def main_menu_keyboard(is_admin=False, is_private=True):
    """Главное меню"""
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        KeyboardButton(text="🎮 Играть"),
        KeyboardButton(text="🛒 Магазин"),
        KeyboardButton(text="📜 Задания"),
        KeyboardButton(text="💼 Работа"),
        KeyboardButton(text="🎁 Ежедневный бонус"),
        KeyboardButton(text="🏆 Лидерборд"),
        KeyboardButton(text="📊 Мой уровень"),
        KeyboardButton(text="⚙️ Настройки"),
        KeyboardButton(text="❓ Помощь")
    ]
    
    for i in range(0, len(buttons), 2):
        if i+1 < len(buttons):
            kb.add(buttons[i], buttons[i+1])
        else:
            kb.add(buttons[i])
    
    if is_admin and is_private:
        kb.add(KeyboardButton(text="⚙️ Админ панель"))
    
    return kb

def login_keyboard():
    """Клавиатура для входа/регистрации"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Войти", callback_data="auth_login"),
         InlineKeyboardButton(text="📝 Регистрация", callback_data="auth_register")]
    ])
    return kb

def cancel_keyboard():
    """Клавиатура отмены"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_registration")]
    ])
    return kb

def generate_password_keyboard():
    """Клавиатура для генерации пароля"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔐 Сгенерировать надежный пароль", callback_data="generate_password")]
    ])
    return kb

def settings_keyboard():
    """Клавиатура настроек"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Язык", callback_data="settings_language"),
         InlineKeyboardButton(text="🎲 Автоставка", callback_data="settings_auto_bet")],
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="settings_add_account")],
        [InlineKeyboardButton(text="✏️ Изменить данные", callback_data="settings_change_data")],
        [InlineKeyboardButton(text="🚪 Выйти из аккаунта", callback_data="settings_logout")],
        [InlineKeyboardButton(text="💾 Сохранить и выйти", callback_data="settings_save")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    return kb

def games_keyboard():
    """Клавиатура выбора игры"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Угадай число", callback_data="game_guess")],
        [InlineKeyboardButton(text="✊✋✌️ Камень-Ножницы-Бумага", callback_data="game_rps")],
        [InlineKeyboardButton(text="❌⭕️ Крестики-Нолики", callback_data="game_ttt")],
        [InlineKeyboardButton(text="🎰 Слот-машина", callback_data="game_slots")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    return kb

def shop_keyboard(account_id: int):
    """Клавиатура магазина"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT profession FROM accounts WHERE account_id = ?", (account_id,))
        current_prof = cursor.fetchone()['profession']
    
    kb = InlineKeyboardBuilder()
    
    professions = [
        ("👨‍💻 Junior (50 PC/час)", "shop_junior"),
        ("👨‍💼 Middle (100 PC/час)", "shop_middle"),
        ("👨‍🔬 Senior (300 PC/час)", "shop_senior"),
        ("👨‍💼 Manager (400 PC/час)", "shop_manager"),
        ("👨‍💼 Director (500 PC/час)", "shop_director")
    ]
    
    for text, data in professions:
        prof_name = data.replace("shop_", "")
        if current_prof == prof_name:
            kb.button(text=f"✓ {text}", callback_data="already_owned")
        else:
            discount = get_promotion_discount(prof_name)
            if discount > 0:
                kb.button(text=f"🏷️ {text} -{discount}%", callback_data=data)
            else:
                kb.button(text=text, callback_data=data)
    
    kb.button(text="🔄 Временные попытки (+5 на день)", callback_data="shop_temp_attempts")
    kb.button(text="⭐ Перманентные попытки (+1 макс.)", callback_data="shop_perm_attempts")
    kb.button(text="◀️ Назад", callback_data="back_to_menu")
    
    kb.adjust(1)
    return kb.as_markup()

def confirm_keyboard(item: str, quantity: int = 1):
    """Клавиатура подтверждения покупки"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Подтверждаю ({quantity} шт.)", callback_data=f"buy_{item}_{quantity}"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="shop_cancel")],
        [InlineKeyboardButton(text="➖", callback_data=f"dec_{item}"),
         InlineKeyboardButton(text="➕", callback_data=f"inc_{item}")]
    ])
    return kb

def admin_keyboard():
    """Админ панель"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👤 Управление аккаунтами", callback_data="admin_accounts")],
        [InlineKeyboardButton(text="💰 Изменить цены", callback_data="admin_prices")],
        [InlineKeyboardButton(text="🎁 Создать розыгрыш", callback_data="admin_giveaway")],
        [InlineKeyboardButton(text="📈 Установить макс. аккаунтов", callback_data="admin_max_accounts")],
        [InlineKeyboardButton(text="📝 Добавить задание", callback_data="admin_add_quest")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🏷️ Создать акцию", callback_data="admin_promotion")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    return kb

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@router.message(CommandStart())
@router.message(Command("startpuls"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start и /startpuls"""
    await state.clear()
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE tg_id = ?", (message.from_user.id,))
        user = cursor.fetchone()
        
        if not user:
            cursor.execute(
                "INSERT INTO users (tg_id, max_accounts, admin, auto_bet) VALUES (?, 3, 0, 25)",
                (message.from_user.id,)
            )
            conn.commit()
            
            await message.answer(
                "👋 *Добро пожаловать в Puls Bot!*\n\n"
                "Это экономический бот с играми, работой, квестами и системой уровней.\n\n"
                "📋 *Что я умею:*\n"
                "• 🎮 Играть в мини-игры и зарабатывать\n"
                "• 💼 Работать и получать зарплату\n"
                "• 📜 Выполнять квесты\n"
                "• 🛒 Покупать профессии и улучшения\n"
                "• 📊 Повышать уровень и получать бонусы\n"
                "• 🏆 Соревноваться с другими игроками\n\n"
                "🔐 Для начала работы войдите в аккаунт или создайте новый:",
                reply_markup=login_keyboard()
            )
        else:
            cursor.execute(
                "SELECT * FROM accounts WHERE tg_id = ?",
                (message.from_user.id,)
            )
            accounts = cursor.fetchall()
            
            if accounts:
                kb = InlineKeyboardBuilder()
                for acc in accounts:
                    kb.button(
                        text=f"{acc['username']} (💰 {acc['coins']} PC)",
                        callback_data=f"select_account_{acc['account_id']}"
                    )
                kb.button(text="➕ Создать новый", callback_data="auth_register")
                kb.adjust(1)
                
                await message.answer(
                    "🔑 *Выберите аккаунт:*",
                    reply_markup=kb.as_markup()
                )
            else:
                await message.answer(
                    "👋 *С возвращением!*\n\n"
                    "У вас пока нет аккаунтов. Создайте новый:",
                    reply_markup=login_keyboard()
                )

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    help_text = (
        "🎮 *Puls Bot - Помощь*\n\n"
        "*Основные команды:*\n"
        "• /start - Начать работу с ботом\n"
        "• /help - Показать это сообщение\n\n"
        "*Основные функции:*\n"
        "• *Игры* - Зарабатывайте монеты в мини-играх\n"
        "• *Магазин* - Покупайте профессии и попытки\n"
        "• *Квесты* - Выполняйте задания за награды\n"
        "• *Работа* - Получайте зарплату каждый час\n"
        "• *Уровни* - Повышайте уровень для бонусов\n"
        "• *Лидерборд* - Соревнуйтесь с другими игроками\n"
        "• *Настройки* - Настройте бота под себя\n\n"
        "*Система уровней:*\n"
        "Повышайте уровень, получая опыт в играх. "
        "Каждый уровень дает уникальные бонусы!"
    )
    
    await message.answer(help_text)

# ========== ОБРАБОТЧИКИ АВТОРИЗАЦИИ ==========
@router.callback_query(F.data == "cancel_registration")
async def cancel_registration(callback: CallbackQuery, state: FSMContext):
    """Отмена регистрации"""
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(
        "❌ Регистрация отменена.",
        reply_markup=login_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "generate_password")
async def generate_password_handler(callback: CallbackQuery, state: FSMContext):
    """Генерация надежного пароля"""
    password = generate_strong_password(14)
    
    data = await state.get_data()
    username = data.get('new_username')
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO accounts (tg_id, username, password, coins, level, exp)
        VALUES (?, ?, ?, 100, 1, 0)
        ''', (callback.from_user.id, username, password))
        
        account_id = cursor.lastrowid
        
        games = ["Угадай число", "Камень-Ножницы-Бумага", "Крестики-Нолики", "Слот-машина"]
        for game in games:
            cursor.execute('''
            INSERT OR IGNORE INTO game_attempts 
            (account_id, game_name, daily_attempts, last_date, permanent_max, extra_attempts)
            VALUES (?, ?, 0, ?, 5, 0)
            ''', (account_id, game, datetime.date.today().isoformat()))
        
        cursor.execute("SELECT admin, auto_bet FROM users WHERE tg_id = ?", (callback.from_user.id,))
        user = cursor.fetchone()
        is_admin = user['admin'] == 1 if user else False
        auto_bet = user['auto_bet'] if user else 25
        
        conn.commit()
        
        await state.update_data(current_account=account_id)
        
        await callback.message.delete()
        
        await callback.message.answer(
            f"🎉 *Аккаунт создан!*\n\n"
            f"👤 *Логин:* `{username}`\n"
            f"🔐 *Пароль:* `{password}`\n\n"
            f"❗ Сохраните эти данные! Администрация никогда не запросит их.\n\n"
            f"💰 *Стартовый баланс:* 100 PC\n"
            f"⭐ *Уровень:* 1\n\n"
            f"⚙️ *Автоставка по умолчанию:* {auto_bet} PC\n\n"
            f"Добро пожаловать в главное меню:",
            reply_markup=main_menu_keyboard(is_admin, callback.message.chat.type == "private")
        )
    
    await state.set_state(None)
    await callback.answer()

@router.callback_query(F.data.startswith("auth_"))
async def auth_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик авторизации"""
    action = callback.data.split("_")[1]
    
    if action == "login":
        await callback.message.edit_text(
            "🔑 *Вход в аккаунт*\n\n"
            "Введите логин:"
        )
        await state.set_state(AuthStates.login)
    
    elif action == "register":
        with get_db() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT max_accounts FROM users WHERE tg_id = ?",
                (callback.from_user.id,)
            )
            max_acc = cursor.fetchone()['max_accounts']
            
            cursor.execute(
                "SELECT COUNT(*) as count FROM accounts WHERE tg_id = ?",
                (callback.from_user.id,)
            )
            current_acc = cursor.fetchone()['count']
            
            if current_acc >= max_acc:
                await callback.answer(
                    f"❌ Достигнут лимит аккаунтов ({max_acc}).",
                    show_alert=True
                )
                return
        
        await callback.message.edit_text(
            "📝 *Регистрация*\n\n"
            "Придумайте логин (3-20 символов, только буквы и цифры):",
            reply_markup=cancel_keyboard()
        )
        await state.set_state(AuthStates.new_username)
    
    await callback.answer()

@router.message(AuthStates.login)
async def process_login_username(message: Message, state: FSMContext):
    """Обработка ввода логина при входе"""
    username = message.text.strip()
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM accounts WHERE tg_id = ? AND username = ?",
            (message.from_user.id, username)
        )
        account = cursor.fetchone()
        
        if not account:
            await message.answer(
                "❌ Аккаунт не найден.",
                reply_markup=login_keyboard()
            )
            await state.clear()
            return
        
        await state.update_data(account_id=account['account_id'])
        await message.answer(
            "🔐 Введите пароль:"
        )
        await state.set_state(AuthStates.password)

@router.message(AuthStates.password)
async def process_login_password(message: Message, state: FSMContext):
    """Обработка ввода пароля при входе"""
    password = message.text.strip()
    data = await state.get_data()
    account_id = data['account_id']
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM accounts WHERE account_id = ? AND password = ?",
            (account_id, password)
        )
        account = cursor.fetchone()
        
        if not account:
            await message.answer(
                "❌ Неверный пароль.",
                reply_markup=login_keyboard()
            )
            await state.clear()
            return
        
        cursor.execute(
            "SELECT admin FROM users WHERE tg_id = ?",
            (message.from_user.id,)
        )
        user = cursor.fetchone()
        is_admin = user['admin'] == 1 if user else False
        
        await state.update_data(current_account=account_id)
        
        await message.answer(
            f"✅ *Вход выполнен!*\n\n"
            f"👤 *Аккаунт:* {account['username']}\n"
            f"💰 *Баланс:* {account['coins']} PC\n"
            f"⭐ *Уровень:* {account['level']}\n"
            f"💼 *Профессия:* {account['profession']}\n\n"
            f"Добро пожаловать в главное меню:",
            reply_markup=main_menu_keyboard(is_admin, message.chat.type == "private")
        )
        await state.clear()

@router.message(AuthStates.new_username)
async def process_new_username(message: Message, state: FSMContext):
    """Обработка нового логина"""
    username = message.text.strip()
    
    if len(username) < 3 or len(username) > 20:
        await message.answer(
            "❌ Логин должен быть от 3 до 20 символов. Попробуйте снова:"
        )
        return
    
    if not username.isalnum():
        await message.answer(
            "❌ Логин должен содержать только буквы и цифры. Попробуйте снова:"
        )
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM accounts WHERE tg_id = ? AND username = ?",
            (message.from_user.id, username)
        )
        if cursor.fetchone():
            await message.answer(
                "❌ Этот логин уже занят. Выберите другой:"
            )
            return
    
    await state.update_data(new_username=username)
    
    await message.answer(
        "✅ *Логин создан!*\n\n"
        "Теперь придумайте пароль для аккаунта\n"
        "(минимум 6 символов) или сгенерируйте надежный:",
        reply_markup=generate_password_keyboard()
    )
    await state.set_state(AuthStates.new_password)

@router.message(AuthStates.new_password)
async def process_new_password(message: Message, state: FSMContext):
    """Обработка нового пароля"""
    password = message.text.strip()
    
    if len(password) < 6:
        await message.answer(
            "❌ Пароль должен быть не менее 6 символов. Попробуйте снова:"
        )
        return
    
    if len(password) > 20:
        await message.answer(
            "❌ Пароль должен быть не более 20 символов. Попробуйте снова:"
        )
        return
    
    data = await state.get_data()
    username = data['new_username']
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO accounts (tg_id, username, password, coins, level, exp)
        VALUES (?, ?, ?, 100, 1, 0)
        ''', (message.from_user.id, username, password))
        
        account_id = cursor.lastrowid
        
        games = ["Угадай число", "Камень-Ножницы-Бумага", "Крестики-Нолики", "Слот-машина"]
        for game in games:
            cursor.execute('''
            INSERT OR IGNORE INTO game_attempts 
            (account_id, game_name, daily_attempts, last_date, permanent_max, extra_attempts)
            VALUES (?, ?, 0, ?, 5, 0)
            ''', (account_id, game, datetime.date.today().isoformat()))
        
        cursor.execute("SELECT admin, auto_bet FROM users WHERE tg_id = ?", (message.from_user.id,))
        user = cursor.fetchone()
        is_admin = user['admin'] == 1 if user else False
        auto_bet = user['auto_bet'] if user else 25
        
        conn.commit()
        
        await state.update_data(current_account=account_id)
        
        await message.answer(
            f"🎉 *Аккаунт создан!*\n\n"
            f"👤 *Логин:* `{username}`\n"
            f"🔐 *Пароль:* `{password}`\n\n"
            f"❗ Сохраните эти данные! Администрация никогда не запросит их.\n\n"
            f"💰 *Стартовый баланс:* 100 PC\n"
            f"⭐ *Уровень:* 1\n\n"
            f"⚙️ *Автоставка по умолчанию:* {auto_bet} PC\n\n"
            f"Добро пожаловать в главное меню:",
            reply_markup=main_menu_keyboard(is_admin, message.chat.type == "private")
        )
        await state.clear()

@router.callback_query(F.data.startswith("select_account_"))
async def select_account_handler(callback: CallbackQuery, state: FSMContext):
    """Выбор аккаунта из списка"""
    account_id = int(callback.data.split("_")[-1])
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM accounts WHERE account_id = ?",
            (account_id,)
        )
        account = cursor.fetchone()
        
        if not account or account['tg_id'] != callback.from_user.id:
            await callback.answer("❌ Аккаунт не найден", show_alert=True)
            return
        
        cursor.execute(
            "SELECT admin FROM users WHERE tg_id = ?",
            (callback.from_user.id,)
        )
        user = cursor.fetchone()
        is_admin = user['admin'] == 1 if user else False
        
        await state.update_data(current_account=account_id)
        
        await callback.message.delete()
        
        await callback.message.answer(
            f"✅ *Аккаунт выбран!*\n\n"
            f"👤 *Аккаунт:* {account['username']}\n"
            f"💰 *Баланс:* {account['coins']} PC\n"
            f"⭐ *Уровень:* {account['level']}\n"
            f"💼 *Профессия:* {account['profession']}\n\n"
            f"Добро пожаловать в главное меню:",
            reply_markup=main_menu_keyboard(is_admin, callback.message.chat.type == "private")
        )
    
    await callback.answer()

# ========== ОБРАБОТЧИКИ НАСТРОЕК ==========
@router.message(F.text == "⚙️ Настройки")
async def settings_menu(message: Message, state: FSMContext):
    """Меню настроек"""
    data = await state.get_data()
    account_id = data.get('current_account')
    
    if not account_id:
        await message.answer(
            "❌ Сначала войдите в аккаунт",
            reply_markup=login_keyboard()
        )
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM accounts WHERE account_id = ?", (account_id,))
        account = cursor.fetchone()
        cursor.execute("SELECT auto_bet, language FROM users WHERE tg_id = ?", (message.from_user.id,))
        user = cursor.fetchone()
    
    await message.answer(
        f"⚙️ *Настройки*\n\n"
        f"👤 *Аккаунт:* {account['username']}\n"
        f"🌐 *Язык:* {user['language']}\n"
        f"🎲 *Автоставка:* {user['auto_bet']} PC\n\n"
        f"Выберите действие:",
        reply_markup=settings_keyboard()
    )
    await state.set_state(SettingsStates.main)

@router.callback_query(F.data == "settings_auto_bet")
async def settings_auto_bet(callback: CallbackQuery, state: FSMContext):
    """Настройка автоставки"""
    await callback.message.edit_text(
        "🎲 *Автоставка*\n\n"
        "Введите сумму автоставки для игр\n"
        "(минимум 25, целое число):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_settings")]
        ])
    )
    await state.set_state(SettingsStates.auto_bet)
    await callback.answer()

@router.message(SettingsStates.auto_bet)
async def process_auto_bet(message: Message, state: FSMContext):
    """Обработка автоставки"""
    try:
        bet = int(message.text.strip())
        
        if bet < 25:
            await message.answer("❌ Автоставка не может быть меньше 25. Попробуйте снова:")
            return
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET auto_bet = ? WHERE tg_id = ?",
                (bet, message.from_user.id)
            )
            conn.commit()
        
        await message.answer(
            f"✅ Автоставка установлена: {bet} PC"
        )
        
        # Возврат в настройки
        await settings_menu(message, state)
        
    except ValueError:
        await message.answer("❌ Введите целое число. Попробуйте снова:")

@router.callback_query(F.data == "settings_add_account")
async def settings_add_account(callback: CallbackQuery, state: FSMContext):
    """Добавление аккаунта из настроек"""
    await callback.message.delete()
    await callback.message.answer(
        "📝 *Регистрация*\n\n"
        "Придумайте логин (3-20 символов, только буквы и цифры):",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(AuthStates.new_username)
    await callback.answer()

@router.callback_query(F.data == "settings_change_data")
async def settings_change_data(callback: CallbackQuery, state: FSMContext):
    """Изменение данных аккаунта"""
    data = await state.get_data()
    account_id = data.get('current_account')
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM accounts WHERE account_id = ?", (account_id,))
        account = cursor.fetchone()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить логин", callback_data="change_username")],
        [InlineKeyboardButton(text="🔐 Изменить пароль", callback_data="change_password")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_settings")]
    ])
    
    await callback.message.edit_text(
        f"✏️ *Изменение данных*\n\n"
        f"👤 *Текущий логин:* {account['username']}\n\n"
        f"Выберите, что хотите изменить:",
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data == "change_password")
async def change_password_start(callback: CallbackQuery, state: FSMContext):
    """Начало смены пароля"""
    await callback.message.edit_text(
        "🔐 *Смена пароля*\n\n"
        "Введите текущий пароль:"
    )
    await state.set_state(AuthStates.change_old_password)
    await callback.answer()

@router.message(AuthStates.change_old_password)
async def change_password_old(message: Message, state: FSMContext):
    """Проверка старого пароля"""
    password = message.text.strip()
    data = await state.get_data()
    account_id = data.get('current_account')
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM accounts WHERE account_id = ? AND password = ?",
            (account_id, password)
        )
        account = cursor.fetchone()
        
        if not account:
            await message.answer(
                "❌ Неверный пароль. Попробуйте снова или отмените:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_settings")]
                ])
            )
            return
        
        await message.answer(
            "✅ Пароль подтвержден!\n\n"
            "Введите новый пароль (минимум 6 символов):",
            reply_markup=generate_password_keyboard()
        )
        await state.set_state(AuthStates.change_new_password)

@router.message(AuthStates.change_new_password)
async def change_password_new(message: Message, state: FSMContext):
    """Установка нового пароля"""
    new_password = message.text.strip()
    
    if len(new_password) < 6:
        await message.answer(
            "❌ Пароль должен быть не менее 6 символов. Попробуйте снова:"
        )
        return
    
    data = await state.get_data()
    account_id = data.get('current_account')
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE accounts SET password = ? WHERE account_id = ?",
            (new_password, account_id)
        )
        conn.commit()
    
    await message.answer(
        f"✅ Пароль успешно изменен!\n\n"
        f"🔐 *Новый пароль:* `{new_password}`\n\n"
        f"❗ Сохраните его в надежном месте."
    )
    
    await state.set_state(SettingsStates.main)
    await settings_menu(message, state)

@router.callback_query(F.data == "change_username")
async def change_username_start(callback: CallbackQuery, state: FSMContext):
    """Начало смены логина"""
    await callback.message.edit_text(
        "✏️ *Смена логина*\n\n"
        "Введите новый логин (3-20 символов, только буквы и цифры):"
    )
    await state.set_state(AuthStates.change_username)
    await callback.answer()

@router.message(AuthStates.change_username)
async def change_username_process(message: Message, state: FSMContext):
    """Смена логина"""
    new_username = message.text.strip()
    
    if len(new_username) < 3 or len(new_username) > 20:
        await message.answer(
            "❌ Логин должен быть от 3 до 20 символов. Попробуйте снова:"
        )
        return
    
    if not new_username.isalnum():
        await message.answer(
            "❌ Логин должен содержать только буквы и цифры. Попробуйте снова:"
        )
        return
    
    data = await state.get_data()
    account_id = data.get('current_account')
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM accounts WHERE tg_id = ? AND username = ?",
            (message.from_user.id, new_username)
        )
        if cursor.fetchone():
            await message.answer(
                "❌ Этот логин уже занят. Выберите другой:"
            )
            return
        
        cursor.execute(
            "UPDATE accounts SET username = ? WHERE account_id = ?",
            (new_username, account_id)
        )
        conn.commit()
    
    await message.answer(
        f"✅ Логин успешно изменен!\n\n"
        f"👤 *Новый логин:* {new_username}"
    )
    
    await state.set_state(SettingsStates.main)
    await settings_menu(message, state)

@router.callback_query(F.data == "settings_logout")
async def settings_logout(callback: CallbackQuery, state: FSMContext):
    """Выход из аккаунта"""
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(
        "👋 *Вы вышли из аккаунта*\n\n"
        "Войдите снова или создайте новый:",
        reply_markup=login_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "settings_save")
async def settings_save(callback: CallbackQuery, state: FSMContext):
    """Сохранение настроек и выход"""
    await callback.message.delete()
    await callback.message.answer(
        "💾 Настройки сохранены!",
        reply_markup=main_menu_keyboard(False, callback.message.chat.type == "private")
    )
    await state.set_state(None)
    await callback.answer()

@router.callback_query(F.data == "back_to_settings")
async def back_to_settings(callback: CallbackQuery, state: FSMContext):
    """Возврат в настройки"""
    await callback.message.delete()
    await settings_menu(callback.message, state)
    await callback.answer()

# ========== ОБРАБОТЧИКИ ГЛАВНОГО МЕНЮ ==========
@router.message(F.text == "🎮 Играть")
async def play_menu(message: Message, state: FSMContext):
    """Меню игр"""
    data = await state.get_data()
    account_id = data.get('current_account')
    
    if not account_id:
        await message.answer(
            "❌ Сначала войдите в аккаунт",
            reply_markup=login_keyboard()
        )
        return
    
    await message.answer(
        "🎮 *Выберите игру:*\n\n"
        "• 🎲 *Угадай число* - Угадайте число от 1 до 100\n"
        "• ✊✋✌️ *Камень-Ножницы-Бумага* - Сыграйте против бота\n"
        "• ❌⭕️ *Крестики-Нолики* - Сыграйте против бота\n"
        "• 🎰 *Слот-машина* - Испытайте удачу\n\n"
        "У вас ограниченное количество попыток в день!",
        reply_markup=games_keyboard()
    )

@router.message(F.text == "🛒 Магазин")
async def shop_menu(message: Message, state: FSMContext):
    """Меню магазина"""
    data = await state.get_data()
    account_id = data.get('current_account')
    
    if not account_id:
        await message.answer(
            "❌ Сначала войдите в аккаунт",
            reply_markup=login_keyboard()
        )
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT coins FROM accounts WHERE account_id = ?", (account_id,))
        coins = cursor.fetchone()['coins']
    
    await message.answer(
        f"🛒 *Магазин*\n\n"
        f"💰 *Ваш баланс:* {coins} PC\n\n"
        f"*Доступные товары:*",
        reply_markup=shop_keyboard(account_id)
    )
    await state.set_state(ShopStates.browsing)

@router.message(F.text == "📜 Задания")
async def quests_menu(message: Message, state: FSMContext):
    """Меню квестов"""
    data = await state.get_data()
    account_id = data.get('current_account')
    
    if not account_id:
        await message.answer(
            "❌ Сначала войдите в аккаунт",
            reply_markup=login_keyboard()
        )
        return
    
    await message.answer("📜 *Квесты*\n\nВ разработке...")

@router.message(F.text == "💼 Работа")
async def work_menu(message: Message, state: FSMContext):
    """Меню работы"""
    data = await state.get_data()
    account_id = data.get('current_account')
    
    if not account_id:
        await message.answer(
            "❌ Сначала войдите в аккаунт",
            reply_markup=login_keyboard()
        )
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT profession, coins, level FROM accounts WHERE account_id = ?",
            (account_id,)
        )
        account = cursor.fetchone()
        
        level_info = get_level_info(account)
        
        base_salary = PROFESSIONS.get(account['profession'], 0)
        salary = int(base_salary * (1 + level_info['bonus_salary']))
        
        text = f"💼 *Работа*\n\n"
        text += f"*Текущая профессия:* {account['profession']}\n"
        text += f"*Базовая зарплата:* {base_salary} PC/час\n"
        if level_info['bonus_salary'] > 0:
            text += f"*Бонус уровня:* +{int(level_info['bonus_salary']*100)}%\n"
        text += f"*Итоговая зарплата:* {salary} PC/час\n\n"
        text += "🕐 Зарплата начисляется автоматически каждый час\n"
        text += "🛒 Новые профессии можно купить в магазине"
        
        await message.answer(text)
        
        cursor.execute('''
        SELECT timestamp FROM actions 
        WHERE account_id = ? AND action LIKE 'work_salary%'
        ORDER BY timestamp DESC LIMIT 1
        ''', (account_id,))
        
        last_salary = cursor.fetchone()
        now = datetime.datetime.now()
        
        if not last_salary or (now - datetime.datetime.fromisoformat(last_salary['timestamp'])).seconds >= 3600:
            cursor.execute(
                "UPDATE accounts SET coins = coins + ? WHERE account_id = ?",
                (salary, account_id)
            )
            
            cursor.execute(
                "INSERT INTO actions (account_id, action) VALUES (?, ?)",
                (account_id, f"work_salary_{salary}")
            )
            
            conn.commit()
            
            await message.answer(
                f"💰 *Зарплата получена!*\n\n"
                f"+{salary} Puls Coins\n"
                f"💳 Новый баланс: {account['coins'] + salary} PC"
            )

@router.message(F.text == "🎁 Ежедневный бонус")
async def daily_bonus(message: Message, state: FSMContext):
    """Ежедневный бонус"""
    data = await state.get_data()
    account_id = data.get('current_account')
    
    if not account_id:
        await message.answer(
            "❌ Сначала войдите в аккаунт",
            reply_markup=login_keyboard()
        )
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT coins, level, last_bonus FROM accounts WHERE account_id = ?",
            (account_id,)
        )
        account = cursor.fetchone()
        
        level_info = get_level_info(account)
        
        now = datetime.datetime.now()
        last_bonus = account['last_bonus']
        
        if last_bonus:
            last_bonus_dt = datetime.datetime.fromisoformat(last_bonus)
            if (now - last_bonus_dt).days < 1:
                next_bonus = last_bonus_dt + datetime.timedelta(days=1)
                wait_time = next_bonus - now
                hours = wait_time.seconds // 3600
                minutes = (wait_time.seconds % 3600) // 60
                
                await message.answer(
                    f"⏳ *Вы уже получали бонус сегодня*\n\n"
                    f"Следующий бонус через: {hours}ч {minutes}м\n"
                    f"Приходите завтра!"
                )
                return
        
        base_bonus = random.randint(200, 300)
        bonus = int(base_bonus * (1 + level_info['bonus_daily']))
        
        cursor.execute('''
        UPDATE accounts 
        SET coins = coins + ?, last_bonus = ?
        WHERE account_id = ?
        ''', (bonus, now.isoformat(), account_id))
        
        cursor.execute(
            "INSERT INTO actions (account_id, action) VALUES (?, ?)",
            (account_id, f"daily_bonus_{bonus}")
        )
        
        conn.commit()
        
        await message.answer(
            f"🎁 *Ежедневный бонус!*\n\n"
            f"💰 *Базовый бонус:* {base_bonus} PC\n"
            f"⭐ *Бонус уровня:* +{int(level_info['bonus_daily']*100)}%\n"
            f"💰 *Итоговый бонус:* {bonus} PC\n"
            f"💳 *Новый баланс:* {account['coins'] + bonus} PC\n\n"
            f"Приходите завтра за новым бонусом!"
        )

@router.message(F.text == "🏆 Лидерборд")
async def leaderboard_menu(message: Message, state: FSMContext):
    """Лидерборд"""
    data = await state.get_data()
    account_id = data.get('current_account')
    
    if not account_id:
        await message.answer(
            "❌ Сначала войдите в аккаунт",
            reply_markup=login_keyboard()
        )
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT username, coins, level, total_exp FROM accounts WHERE account_id = ?",
            (account_id,)
        )
        current = cursor.fetchone()
        
        cursor.execute('''
        SELECT username, coins, level 
        FROM accounts 
        ORDER BY coins DESC 
        LIMIT 10
        ''')
        top_balance = cursor.fetchall()
        
        cursor.execute('''
        SELECT username, total_exp, level 
        FROM accounts 
        ORDER BY total_exp DESC 
        LIMIT 10
        ''')
        top_exp = cursor.fetchall()
        
        text = "🏆 *Лидерборд*\n\n"
        
        text += "*Топ-10 по балансу:*\n"
        for i, player in enumerate(top_balance, 1):
            medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
            text += f"{medal} {player['username']} - {player['coins']} PC (Ур. {player['level']})\n"
        
        text += f"\n*Ваше место:* "
        cursor.execute('''
        SELECT COUNT(*) + 1 as rank
        FROM accounts 
        WHERE coins > ?
        ''', (current['coins'],))
        rank = cursor.fetchone()['rank']
        text += f"{rank}\n"
        
        text += f"👤 {current['username']} - {current['coins']} PC (Ур. {current['level']})\n\n"
        
        text += "*Топ-10 по опыту:*\n"
        for i, player in enumerate(top_exp, 1):
            medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
            text += f"{medal} {player['username']} - {player['total_exp']} опыта (Ур. {player['level']})\n"
        
        await message.answer(text)

@router.message(F.text == "📊 Мой уровень")
async def my_level(message: Message, state: FSMContext):
    """Информация об уровне"""
    data = await state.get_data()
    account_id = data.get('current_account')
    
    if not account_id:
        await message.answer(
            "❌ Сначала войдите в аккаунт",
            reply_markup=login_keyboard()
        )
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT level, exp, coins FROM accounts WHERE account_id = ?",
            (account_id,)
        )
        account = cursor.fetchone()
        
        level_info = get_level_info(account)
        
        progress_bar_length = 20
        filled = int(level_info['progress'] * progress_bar_length)
        progress_bar = "█" * filled + "░" * (progress_bar_length - filled)
        
        text = f"📊 *Уровень {level_info['level']}*\n\n"
        text += f"*Опыт:* {level_info['exp']} / {LEVELS.get(level_info['level'] + 1, {'exp': 'MAX'})['exp']}\n"
        text += f"*До след. уровня:* {level_info['to_next']} опыта\n"
        text += f"{progress_bar} {int(level_info['progress']*100)}%\n\n"
        
        text += "*Текущие бонусы:*\n"
        if level_info['bonus_win'] > 0:
            text += f"• +{int(level_info['bonus_win']*100)}% к выигрышам\n"
        if level_info['bonus_daily'] > 0:
            text += f"• +{int(level_info['bonus_daily']*100)}% к ежедневке\n"
        if level_info['bonus_salary'] > 0:
            text += f"• +{int(level_info['bonus_salary']*100)}% к зарплате\n"
        if level_info['max_attempts_bonus'] > 0:
            text += f"• +{level_info['max_attempts_bonus']} попыток в день\n"
        if level_info['double_win_chance'] > 0:
            text += f"• {int(level_info['double_win_chance']*100)}% шанс удвоить выигрыш\n"
        
        if level_info['level'] < 30:
            next_level = level_info['level'] + 1
            next_bonuses = LEVELS[next_level]
            text += f"\n*Бонусы уровня {next_level}:*\n"
            text += f"• Награда: {next_bonuses['reward_coins']} PC\n"
            if next_bonuses['bonus_win'] > level_info['bonus_win']:
                text += f"• +{int(next_bonuses['bonus_win']*100)}% к выигрышам\n"
            if next_bonuses['bonus_daily'] > level_info['bonus_daily']:
                text += f"• +{int(next_bonuses['bonus_daily']*100)}% к ежедневке\n"
            if next_bonuses['bonus_salary'] > level_info['bonus_salary']:
                text += f"• +{int(next_bonuses['bonus_salary']*100)}% к зарплате\n"
            if next_bonuses['max_attempts_bonus'] > level_info['max_attempts_bonus']:
                text += f"• +{next_bonuses['max_attempts_bonus']} попыток в день\n"
            if next_bonuses['double_win_chance'] > level_info['double_win_chance']:
                text += f"• {int(next_bonuses['double_win_chance']*100)}% шанс удвоить выигрыш\n"
        
        await message.answer(text)

@router.message(F.text == "❓ Помощь")
async def help_menu(message: Message):
    """Меню помощи"""
    await cmd_help(message)

@router.message(F.text == "⚙️ Админ панель")
async def admin_panel(message: Message, state: FSMContext):
    """Админ панель"""
    data = await state.get_data()
    account_id = data.get('current_account')
    
    if not account_id:
        await message.answer(
            "❌ Сначала войдите в аккаунт",
            reply_markup=login_keyboard()
        )
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT u.admin 
        FROM users u
        JOIN accounts a ON u.tg_id = a.tg_id
        WHERE a.account_id = ?
        ''', (account_id,))
        
        result = cursor.fetchone()
        
        if not result or result['admin'] != 1:
            await message.answer("❌ У вас нет прав администратора")
            return
    
    await message.answer(
        "⚙️ *Админ панель*\n\n"
        "Выберите действие:",
        reply_markup=admin_keyboard()
    )

# ========== ОБРАБОТЧИКИ ВОЗВРАТА ==========
@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    await callback.message.delete()
    
    data = await state.get_data()
    account_id = data.get('current_account')
    
    if account_id:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT u.admin 
            FROM users u
            JOIN accounts a ON u.tg_id = a.tg_id
            WHERE a.account_id = ?
            ''', (account_id,))
            
            result = cursor.fetchone()
            is_admin = result['admin'] == 1 if result else False
        
        await callback.message.answer(
            "📊 *Главное меню*\n\n"
            "Выберите действие:",
            reply_markup=main_menu_keyboard(is_admin, callback.message.chat.type == "private")
        )
    else:
        await callback.message.answer(
            "Главное меню",
            reply_markup=login_keyboard()
        )
    
    await callback.answer()

@router.callback_query(F.data == "back_to_games")
async def back_to_games(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору игры"""
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(
        "🎮 *Выберите игру:*",
        reply_markup=games_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: CallbackQuery, state: FSMContext):
    """Возврат в админ панель"""
    await callback.message.delete()
    await callback.message.answer(
        "⚙️ *Админ панель*\n\n"
        "Выберите действие:",
        reply_markup=admin_keyboard()
    )
    await callback.answer()

# ========== ЗАЩИТА ОТ ЧУЖИХ КНОПОК ==========
@router.callback_query()
async def unknown_callback(callback: CallbackQuery):
    """Обработчик неизвестных callback-ов"""
    messages = [
        "❌ Это не ваша кнопка!",
        "🚫 Доступ запрещен!",
        "⚠️ Эту кнопку нажал не ты!",
        "🔒 Кнопка заблокирована!",
        "🙅‍♂️ Не твоя кнопка!"
    ]
    await callback.answer(random.choice(messages), show_alert=True)

# ========== CD ДЛЯ КНОПОК ==========
last_click_time = {}

@router.callback_query(lambda c: True)
async def cooldown_check(callback: CallbackQuery):
    """Проверка CD для кнопок"""
    user_id = callback.from_user.id
    now = datetime.datetime.now()
    
    if user_id in last_click_time:
        diff = (now - last_click_time[user_id]).total_seconds()
        if diff < 1:
            await callback.answer(f"⏳ Подожди {int(1 - diff)}с", show_alert=True)
            return
    
    last_click_time[user_id] = now
    await callback.continue_propagation()

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция запуска бота"""
    init_db()
    asyncio.create_task(periodic_tasks())
    await dp.start_polling(bot)

async def periodic_tasks():
    """Периодические задачи"""
    while True:
        now = datetime.datetime.now()
        if now.hour == 0 and now.minute == 0:
            reset_daily_stats()
        
        with get_db() as conn:
            cursor = conn.cursor()
            now_iso = datetime.datetime.now().isoformat()
            cursor.execute(
                "DELETE FROM promotions WHERE end_time < ?",
                (now_iso,)
            )
            conn.commit()
        
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())









