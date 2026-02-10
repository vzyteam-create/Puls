import asyncio
import sqlite3
import random
import datetime
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
from aiogram.enums import ParseMode

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = '7966298894:AAHMwxQR-obWG6wNuFioSmMeDPtYyRVfrjU'
DB_FILE = 'puls_bot.db'

# ========== СИСТЕМА УРОВНЕЙ ==========
LEVELS = {
    1:  {"exp": 0,       "reward_coins": 0,    "bonus_win": 0.00, "bonus_daily": 0.00, "bonus_salary": 0.00, "max_attempts_bonus": 0,  "double_win_chance": 0.00},
    2:  {"exp": 300,     "reward_coins": 5,    "bonus_win": 0.005, "bonus_daily": 0.00, "bonus_salary": 0.00, "max_attempts_bonus": 0,  "double_win_chance": 0.00},
    3:  {"exp": 700,     "reward_coins": 10,   "bonus_win": 0.01,  "bonus_daily": 0.02, "bonus_salary": 0.00, "max_attempts_bonus": 0,  "double_win_chance": 0.005},
    4:  {"exp": 1200,    "reward_coins": 20,   "bonus_win": 0.015, "bonus_daily": 0.04, "bonus_salary": 0.00, "max_attempts_bonus": 0,  "double_win_chance": 0.01},
    5:  {"exp": 2000,    "reward_coins": 30,   "bonus_win": 0.02,  "bonus_daily": 0.06, "bonus_salary": 0.00, "max_attempts_bonus": 0,  "double_win_chance": 0.015},
    6:  {"exp": 3500,    "reward_coins": 45,   "bonus_win": 0.025, "bonus_daily": 0.08, "bonus_salary": 0.02, "max_attempts_bonus": 0,  "double_win_chance": 0.02},
    7:  {"exp": 6000,    "reward_coins": 60,   "bonus_win": 0.03,  "bonus_daily": 0.10, "bonus_salary": 0.03, "max_attempts_bonus": 1,  "double_win_chance": 0.025},
    8:  {"exp": 10000,   "reward_coins": 80,   "bonus_win": 0.035, "bonus_daily": 0.12, "bonus_salary": 0.04, "max_attempts_bonus": 1,  "double_win_chance": 0.03},
    9:  {"exp": 17000,   "reward_coins": 100,  "bonus_win": 0.04,  "bonus_daily": 0.14, "bonus_salary": 0.05, "max_attempts_bonus": 1,  "double_win_chance": 0.035},
    10: {"exp": 28000,   "reward_coins": 125,  "bonus_win": 0.045, "bonus_daily": 0.16, "bonus_salary": 0.06, "max_attempts_bonus": 2,  "double_win_chance": 0.04},
    11: {"exp": 45000,   "reward_coins": 150,  "bonus_win": 0.05,  "bonus_daily": 0.18, "bonus_salary": 0.07, "max_attempts_bonus": 2,  "double_win_chance": 0.045},
    12: {"exp": 70000,   "reward_coins": 180,  "bonus_win": 0.055, "bonus_daily": 0.20, "bonus_salary": 0.08, "max_attempts_bonus": 2,  "double_win_chance": 0.05},
    13: {"exp": 110000,  "reward_coins": 220,  "bonus_win": 0.06,  "bonus_daily": 0.22, "bonus_salary": 0.09, "max_attempts_bonus": 3,  "double_win_chance": 0.055},
    14: {"exp": 170000,  "reward_coins": 270,  "bonus_win": 0.065, "bonus_daily": 0.24, "bonus_salary": 0.10, "max_attempts_bonus": 3,  "double_win_chance": 0.06},
    15: {"exp": 250000,  "reward_coins": 320,  "bonus_win": 0.07,  "bonus_daily": 0.26, "bonus_salary": 0.11, "max_attempts_bonus": 3,  "double_win_chance": 0.065},
    16: {"exp": 380000,  "reward_coins": 380,  "bonus_win": 0.075, "bonus_daily": 0.28, "bonus_salary": 0.12, "max_attempts_bonus": 4,  "double_win_chance": 0.07},
    17: {"exp": 550000,  "reward_coins": 450,  "bonus_win": 0.08,  "bonus_daily": 0.30, "bonus_salary": 0.13, "max_attempts_bonus": 4,  "double_win_chance": 0.075},
    18: {"exp": 800000,  "reward_coins": 530,  "bonus_win": 0.085, "bonus_daily": 0.35, "bonus_salary": 0.14, "max_attempts_bonus": 4,  "double_win_chance": 0.08},
    19: {"exp": 1150000, "reward_coins": 620,  "bonus_win": 0.09,  "bonus_daily": 0.40, "bonus_salary": 0.15, "max_attempts_bonus": 5,  "double_win_chance": 0.085},
    20: {"exp": 1650000, "reward_coins": 750,  "bonus_win": 0.095, "bonus_daily": 0.45, "bonus_salary": 0.16, "max_attempts_bonus": 5,  "double_win_chance": 0.09},
    21: {"exp": 2300000, "reward_coins": 900,  "bonus_win": 0.10,  "bonus_daily": 0.50, "bonus_salary": 0.17, "max_attempts_bonus": 6,  "double_win_chance": 0.095},
    22: {"exp": 3200000, "reward_coins": 1100, "bonus_win": 0.105, "bonus_daily": 0.52, "bonus_salary": 0.175, "max_attempts_bonus": 6,  "double_win_chance": 0.10},
    23: {"exp": 4300000, "reward_coins": 1350, "bonus_win": 0.11,  "bonus_daily": 0.54, "bonus_salary": 0.18, "max_attempts_bonus": 7,  "double_win_chance": 0.105},
    24: {"exp": 5700000, "reward_coins": 1650, "bonus_win": 0.115, "bonus_daily": 0.56, "bonus_salary": 0.185, "max_attempts_bonus": 7,  "double_win_chance": 0.11},
    25: {"exp": 7500000, "reward_coins": 2000, "bonus_win": 0.12,  "bonus_daily": 0.58, "bonus_salary": 0.19, "max_attempts_bonus": 8,  "double_win_chance": 0.115},
    26: {"exp": 10000000,"reward_coins": 2500, "bonus_win": 0.125, "bonus_daily": 0.59, "bonus_salary": 0.195, "max_attempts_bonus": 8,  "double_win_chance": 0.12},
    27: {"exp": 13000000,"reward_coins": 3000, "bonus_win": 0.13,  "bonus_daily": 0.595, "bonus_salary": 0.198, "max_attempts_bonus": 9,  "double_win_chance": 0.125},
    28: {"exp": 17000000,"reward_coins": 3700, "bonus_win": 0.135, "bonus_daily": 0.597, "bonus_salary": 0.199, "max_attempts_bonus": 9,  "double_win_chance": 0.13},
    29: {"exp": 22000000,"reward_coins": 4500, "bonus_win": 0.14,  "bonus_daily": 0.598, "bonus_salary": 0.1995, "max_attempts_bonus": 10, "double_win_chance": 0.135},
    30: {"exp": 28000000,"reward_coins": 5000, "bonus_win": 0.15,  "bonus_daily": 0.60, "bonus_salary": 0.20,  "max_attempts_bonus": 10, "double_win_chance": 0.14},
}

# ========== ПРОФЕССИИ ==========
PROFESSIONS = {
    "none": 0,
    "junior": 50,
    "middle": 120,
    "senior": 250,
    "manager": 400,
    "director": 600
}

# ========== FSM СОСТОЯНИЯ ==========
class AuthStates(StatesGroup):
    login = State()
    password = State()
    new_username = State()
    new_password = State()

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
bot = Bot(token=BOT_TOKEN)  # просто без parse_mode
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        tg_id           INTEGER PRIMARY KEY,
        max_accounts    INTEGER DEFAULT 3,
        admin           INTEGER DEFAULT 0
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
        ('middle', 1500),
        ('senior', 3500),
        ('manager', 7000),
        ('director', 12000),
        ('temp_attempts', 100),
        ('perm_attempts', 750)
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
        
        # Добавляем опыт
        cursor.execute(
            "UPDATE accounts SET exp = exp + ?, total_exp = total_exp + ? WHERE account_id = ?",
            (amount, amount, account_id)
        )
        
        # Проверяем уровень
        cursor.execute("SELECT level, exp, tg_id FROM accounts WHERE account_id = ?", (account_id,))
        level, exp, tg_id = cursor.fetchone()
        
        leveled_up = False
        while level < 30:
            next_req = LEVELS.get(level + 1, {"exp": 9999999999})["exp"]
            if exp >= next_req:
                level += 1
                leveled_up = True
                reward = LEVELS[level]["reward_coins"]
                
                # Обновляем уровень и выдаём награду
                cursor.execute(
                    "UPDATE accounts SET level = ?, coins = coins + ?, exp = exp - ? WHERE account_id = ?",
                    (level, reward, next_req, account_id)
                )
                
                # Получаем бонусы нового уровня
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
                
                # Отправляем уведомление
                try:
                    await bot.send_message(
                        tg_id,
                        f"🌟 *Новый уровень {level}!*\n\n"
                        f"+{reward} Puls Coins\n\n"
                        f"*Бонусы:*\n{bonus_text}",
                        parse_mode="Markdown"
                    )
                except:
                    pass
                
                # Обновляем exp для следующей проверки
                exp -= next_req
            else:
                break
        
        conn.commit()
        return leveled_up

def check_attempts(account_id: int, game_name: str) -> Tuple[bool, int]:
    """Проверить доступные попытки для игры"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Получаем информацию об уровне для бонусных попыток
        cursor.execute(
            "SELECT level FROM accounts WHERE account_id = ?",
            (account_id,)
        )
        level = cursor.fetchone()['level']
        level_bonus = LEVELS.get(level, LEVELS[1])["max_attempts_bonus"]
        
        # Получаем или создаем запись о попытках
        cursor.execute('''
        SELECT daily_attempts, last_date, permanent_max, extra_attempts 
        FROM game_attempts 
        WHERE account_id = ? AND game_name = ?
        ''', (account_id, game_name))
        
        result = cursor.fetchone()
        today = datetime.date.today().isoformat()
        
        if result:
            daily_attempts, last_date, permanent_max, extra_attempts = result
            
            # Сбрасываем ежедневные попытки
            if last_date != today:
                daily_attempts = 0
                cursor.execute('''
                UPDATE game_attempts 
                SET daily_attempts = 0, last_date = ?
                WHERE account_id = ? AND game_name = ?
                ''', (today, account_id, game_name))
                conn.commit()
            
            # Вычисляем максимальное количество попыток
            total_max = permanent_max + extra_attempts + level_bonus
            
            if daily_attempts < total_max:
                return True, total_max - daily_attempts
            else:
                return False, 0
        else:
            # Создаем новую запись
            total_max = 5 + level_bonus  # Базовые 5 + бонус уровня
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
    """Сброс ежедневной статистики (вызывается раз в день)"""
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
        KeyboardButton(text="Играть 🎮"),
        KeyboardButton(text="Магазин 🛒"),
        KeyboardButton(text="Квесты 📜"),
        KeyboardButton(text="Работа 💼"),
        KeyboardButton(text="Ежедневный бонус 🎁"),
        KeyboardButton(text="Лидерборд 🏆"),
        KeyboardButton(text="Мой уровень 📊"),
        KeyboardButton(text="Помощь ❓")
    ]
    
    for i in range(0, len(buttons), 2):
        if i+1 < len(buttons):
            kb.add(buttons[i], buttons[i+1])
        else:
            kb.add(buttons[i])
    
    if is_admin and is_private:
        kb.add(KeyboardButton(text="Админ панель ⚙️"))
    
    return kb

def login_keyboard():
    """Клавиатура для входа/регистрации"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Войти", callback_data="auth_login"),
         InlineKeyboardButton(text="Регистрация", callback_data="auth_register")]
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
    
    # Профессии
    professions = [
        ("👨‍💻 Junior (50 PC/час)", "shop_junior"),
        ("👨‍💼 Middle (120 PC/час)", "shop_middle"),
        ("👨‍🔬 Senior (250 PC/час)", "shop_senior"),
        ("👨‍💼 Manager (400 PC/час)", "shop_manager"),
        ("👨‍💼 Director (600 PC/час)", "shop_director")
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
        [InlineKeyboardButton(text=f"✅ Купить ({quantity} шт.)", callback_data=f"buy_{item}_{quantity}"),
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
        [InlineKeyboardButton(text="📝 Добавить квест", callback_data="admin_add_quest")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🏷️ Создать акцию", callback_data="admin_promotion")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    return kb

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await state.clear()
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Проверяем, зарегистрирован ли пользователь
        cursor.execute("SELECT * FROM users WHERE tg_id = ?", (message.from_user.id,))
        user = cursor.fetchone()
        
        if not user:
            # Регистрируем нового пользователя
            cursor.execute(
                "INSERT INTO users (tg_id, max_accounts, admin) VALUES (?, 3, 0)",
                (message.from_user.id,)
            )
            conn.commit()
            
            await message.answer(
                "👋 *Добро пожаловать в Puls Bot!*\n\n"
                "Это экономический бот с играми, работой, квестами и системой уровней.\n\n"
                "Для начала работы необходимо войти в аккаунт или создать новый:",
                reply_markup=login_keyboard(),
                parse_mode="Markdown"
            )
        else:
            # Проверяем, есть ли активные аккаунты
            cursor.execute(
                "SELECT * FROM accounts WHERE tg_id = ?",
                (message.from_user.id,)
            )
            accounts = cursor.fetchall()
            
            if accounts:
                # Показываем выбор аккаунта
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
                    reply_markup=kb.as_markup(),
                    parse_mode="Markdown"
                )
            else:
                await message.answer(
                    "👋 *С возвращением!*\n\n"
                    "У вас пока нет аккаунтов. Создайте новый:",
                    reply_markup=login_keyboard(),
                    parse_mode="Markdown"
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
        "• *Лидерборд* - Соревнуйтесь с другими игроками\n\n"
        "*Система уровней:*\n"
        "Повышайте уровень, получая опыт в играх. "
        "Каждый уровень дает уникальные бонусы!\n\n"
        "*Баланс:*\n"
        "Бот имеет жесткую экономику - зарабатывать сложно, "
        "чтобы сохранялся азарт и ценность монет."
    )
    
    await message.answer(help_text, parse_mode="Markdown")

# ========== ОБРАБОТЧИКИ АВТОРИЗАЦИИ ==========
@router.callback_query(F.data.startswith("auth_"))
async def auth_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик авторизации"""
    action = callback.data.split("_")[1]
    
    if action == "login":
        await callback.message.edit_text(
            "🔑 *Вход в аккаунт*\n\n"
            "Введите имя пользователя:",
            parse_mode="Markdown"
        )
        await state.set_state(AuthStates.login)
    
    elif action == "register":
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Проверяем максимальное количество аккаунтов
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
                    f"❌ Достигнут лимит аккаунтов ({max_acc}). "
                    "Удалите старый или купите увеличение в магазине.",
                    show_alert=True
                )
                return
        
        await callback.message.edit_text(
            "📝 *Создание аккаунта*\n\n"
            "Придумайте имя пользователя (3-20 символов, только буквы и цифры):",
            parse_mode="Markdown"
        )
        await state.set_state(AuthStates.new_username)
    
    await callback.answer()

@router.message(AuthStates.login)
async def process_login_username(message: Message, state: FSMContext):
    """Обработка ввода имени пользователя при входе"""
    username = message.text.strip()
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Ищем аккаунт
        cursor.execute(
            "SELECT * FROM accounts WHERE tg_id = ? AND username = ?",
            (message.from_user.id, username)
        )
        account = cursor.fetchone()
        
        if not account:
            await message.answer(
                "❌ Аккаунт не найден. Проверьте имя пользователя или создайте новый аккаунт.",
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
                "❌ Неверный пароль. Попробуйте снова.",
                reply_markup=login_keyboard()
            )
            await state.clear()
            return
        
        # Проверяем права администратора
        cursor.execute(
            "SELECT admin FROM users WHERE tg_id = ?",
            (message.from_user.id,)
        )
        user = cursor.fetchone()
        is_admin = user['admin'] == 1 if user else False
        
        # Сохраняем ID аккаунта в состоянии
        await state.update_data(current_account=account_id)
        
        await message.answer(
            f"✅ *Вход выполнен!*\n\n"
            f"👤 *Аккаунт:* {account['username']}\n"
            f"💰 *Баланс:* {account['coins']} PC\n"
            f"⭐ *Уровень:* {account['level']}\n"
            f"💼 *Профессия:* {account['profession']}\n\n"
            f"Добро пожаловать в главное меню:",
            reply_markup=main_menu_keyboard(is_admin, message.chat.type == "private"),
            parse_mode="Markdown"
        )
        await state.clear()

@router.message(AuthStates.new_username)
async def process_new_username(message: Message, state: FSMContext):
    """Обработка нового имени пользователя"""
    username = message.text.strip()
    
    # Проверка имени пользователя
    if len(username) < 3 or len(username) > 20:
        await message.answer(
            "❌ Имя пользователя должно быть от 3 до 20 символов. Попробуйте снова:"
        )
        return
    
    if not username.isalnum():
        await message.answer(
            "❌ Имя пользователя должно содержать только буквы и цифры. Попробуйте снова:"
        )
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Проверяем уникальность имени
        cursor.execute(
            "SELECT * FROM accounts WHERE tg_id = ? AND username = ?",
            (message.from_user.id, username)
        )
        if cursor.fetchone():
            await message.answer(
                "❌ Это имя пользователя уже занято. Выберите другое:"
            )
            return
    
    await state.update_data(new_username=username)
    await message.answer(
        "🔐 Придумайте пароль (минимум 6 символов):"
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
    
    data = await state.get_data()
    username = data['new_username']
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Создаем аккаунт
        cursor.execute('''
        INSERT INTO accounts (tg_id, username, password, coins, level, exp)
        VALUES (?, ?, ?, 100, 1, 0)
        ''', (message.from_user.id, username, password))
        
        account_id = cursor.lastrowid
        
        # Инициализируем попытки для игр
        games = ["Угадай число", "Камень-Ножницы-Бумага", "Крестики-Нолики", "Слот-машина"]
        for game in games:
            cursor.execute('''
            INSERT OR IGNORE INTO game_attempts 
            (account_id, game_name, daily_attempts, last_date, permanent_max, extra_attempts)
            VALUES (?, ?, 0, ?, 5, 0)
            ''', (account_id, game, datetime.date.today().isoformat()))
        
        conn.commit()
        
        # Проверяем права администратора
        cursor.execute(
            "SELECT admin FROM users WHERE tg_id = ?",
            (message.from_user.id,)
        )
        user = cursor.fetchone()
        is_admin = user['admin'] == 1 if user else False
        
        await state.update_data(current_account=account_id)
        
        await message.answer(
            f"🎉 *Аккаунт создан!*\n\n"
            f"👤 *Имя пользователя:* {username}\n"
            f"💰 *Стартовый баланс:* 100 PC\n"
            f"⭐ *Уровень:* 1\n\n"
            f"✅ *Сохраните данные для входа!*\n"
            f"👤 Логин: `{username}`\n"
            f"🔐 Пароль: `{password}`\n\n"
            f"Добро пожаловать в главное меню:",
            reply_markup=main_menu_keyboard(is_admin, message.chat.type == "private"),
            parse_mode="Markdown"
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
        
        # Проверяем права администратора
        cursor.execute(
            "SELECT admin FROM users WHERE tg_id = ?",
            (callback.from_user.id,)
        )
        user = cursor.fetchone()
        is_admin = user['admin'] == 1 if user else False
        
        # Сохраняем ID аккаунта в состоянии
        await state.update_data(current_account=account_id)
        
        await callback.message.edit_text(
            f"✅ *Аккаунт выбран!*\n\n"
            f"👤 *Аккаунт:* {account['username']}\n"
            f"💰 *Баланс:* {account['coins']} PC\n"
            f"⭐ *Уровень:* {account['level']}\n"
            f"💼 *Профессия:* {account['profession']}\n\n"
            f"Добро пожаловать в главное меню!",
            parse_mode="Markdown"
        )
        
        await callback.message.answer(
            "Главное меню:",
            reply_markup=main_menu_keyboard(is_admin, callback.message.chat.type == "private")
        )
    
    await callback.answer()

# ========== ОБРАБОТЧИКИ ГЛАВНОГО МЕНЮ ==========
@router.message(F.text == "Играть 🎮")
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
        "• *Угадай число* - Угадайте число от 1 до 100\n"
        "• *Камень-Ножницы-Бумага* - Сыграйте против бота\n"
        "• *Крестики-Нолики* - Сыграйте против бота\n"
        "• *Слот-машина* - Испытайте удачу\n\n"
        "У вас ограниченное количество попыток в день!",
        reply_markup=games_keyboard(),
        parse_mode="Markdown"
    )

@router.message(F.text == "Магазин 🛒")
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
        reply_markup=shop_keyboard(account_id),
        parse_mode="Markdown"
    )
    await state.set_state(ShopStates.browsing)

@router.message(F.text == "Квесты 📜")
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
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Получаем активные квесты
        cursor.execute('''
        SELECT q.*, 
               CASE WHEN cq.quest_id IS NOT NULL THEN 1 ELSE 0 END as completed
        FROM quests q
        LEFT JOIN completed_quests cq ON q.id = cq.quest_id AND cq.account_id = ?
        ORDER BY q.type, q.reward DESC
        ''', (account_id,))
        
        quests = cursor.fetchall()
        
        if not quests:
            text = "📜 *Квесты*\n\nНа данный момент квестов нет."
        else:
            text = "📜 *Квесты*\n\n"
            for quest in quests:
                status = "✅ Выполнено" if quest['completed'] else "🔄 Доступно"
                text += f"*{quest['description']}*\n"
                text += f"Награда: {quest['reward']} PC\n"
                if quest['link']:
                    text += f"[Ссылка]({quest['link']})\n"
                text += f"Статус: {status}\n\n"
        
        await message.answer(text, parse_mode="Markdown")

@router.message(F.text == "Работа 💼")
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
        
        # Получаем информацию об аккаунте
        cursor.execute(
            "SELECT profession, coins, level FROM accounts WHERE account_id = ?",
            (account_id,)
        )
        account = cursor.fetchone()
        
        # Получаем информацию об уровне для бонуса зарплаты
        level_info = get_level_info(account)
        
        # Вычисляем зарплату
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
        
        await message.answer(text, parse_mode="Markdown")
        
        # Автоматически начисляем зарплату если прошёл час
        cursor.execute('''
        SELECT timestamp FROM actions 
        WHERE account_id = ? AND action LIKE 'work_salary%'
        ORDER BY timestamp DESC LIMIT 1
        ''', (account_id,))
        
        last_salary = cursor.fetchone()
        now = datetime.datetime.now()
        
        if not last_salary or (now - datetime.datetime.fromisoformat(last_salary['timestamp'])).seconds >= 3600:
            # Начисляем зарплату
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
                f"💳 Новый баланс: {account['coins'] + salary} PC",
                parse_mode="Markdown"
            )

@router.message(F.text == "Ежедневный бонус 🎁")
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
        
        # Получаем информацию об аккаунте
        cursor.execute(
            "SELECT coins, level, last_bonus FROM accounts WHERE account_id = ?",
            (account_id,)
        )
        account = cursor.fetchone()
        
        # Получаем информацию об уровне для бонуса
        level_info = get_level_info(account)
        
        # Проверяем, получал ли уже сегодня бонус
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
                    f"Приходите завтра!",
                    parse_mode="Markdown"
                )
                return
        
        # Выдаем бонус
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
            f"Приходите завтра за новым бонусом!",
            parse_mode="Markdown"
        )

@router.message(F.text == "Лидерборд 🏆")
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
        
        # Получаем информацию о текущем аккаунте
        cursor.execute(
            "SELECT username, coins, level, total_exp FROM accounts WHERE account_id = ?",
            (account_id,)
        )
        current = cursor.fetchone()
        
        # Общий лидерборд по балансу
        cursor.execute('''
        SELECT username, coins, level 
        FROM accounts 
        ORDER BY coins DESC 
        LIMIT 10
        ''')
        top_balance = cursor.fetchall()
        
        # Лидерборд по опыту
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
        
        await message.answer(text, parse_mode="Markdown")

@router.message(F.text == "Мой уровень 📊")
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
        
        # Создаем прогресс-бар
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
        
        await message.answer(text, parse_mode="Markdown")

@router.message(F.text == "Помощь ❓")
async def help_menu(message: Message):
    """Меню помощи"""
    await cmd_help(message)

@router.message(F.text == "Админ панель ⚙️")
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
        
        # Проверяем права администратора
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
        reply_markup=admin_keyboard(),
        parse_mode="Markdown"
    )

# ========== ОБРАБОТЧИКИ ИГР ==========
@router.callback_query(F.data.startswith("game_"))
async def game_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора игры"""
    game_type = callback.data.split("_")[1]
    data = await state.get_data()
    account_id = data.get('current_account')
    
    if not account_id:
        await callback.answer("❌ Сначала войдите в аккаунт", show_alert=True)
        return
    
    # Проверяем доступные попытки
    game_names = {
        "guess": "Угадай число",
        "rps": "Камень-Ножницы-Бумага",
        "ttt": "Крестики-Нолики",
        "slots": "Слот-машина"
    }
    
    game_name = game_names.get(game_type)
    if not game_name:
        await callback.answer("❌ Игра не найдена", show_alert=True)
        return
    
    available, remaining = check_attempts(account_id, game_name)
    
    if not available:
        await callback.answer(
            f"❌ Попытки закончились. Доступно {remaining}/день",
            show_alert=True
        )
        return
    
    await state.update_data(game_type=game_type, game_name=game_name)
    
    if game_type == "guess":
        await callback.message.edit_text(
            "🎲 *Угадай число*\n\n"
            "Я загадал число от 1 до 100.\n"
            "У вас есть 7 попыток чтобы угадать.\n\n"
            "Введите вашу ставку (целое число):",
            parse_mode="Markdown"
        )
        await state.set_state(GameStates.bet)
    
    elif game_type == "rps":
        await callback.message.edit_text(
            "✊✋✌️ *Камень-Ножницы-Бумага*\n\n"
            "Выберите ваш ход:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✊ Камень", callback_data="rps_rock"),
                 InlineKeyboardButton(text="✋ Бумага", callback_data="rps_paper"),
                 InlineKeyboardButton(text="✌️ Ножницы", callback_data="rps_scissors")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_games")]
            ])
        )
        await state.set_state(GameStates.rps_choice)
    
    elif game_type == "ttt":
        await callback.message.edit_text(
            "❌⭕️ *Крестики-Нолики*\n\n"
            "Вы играете за ❌. Сделайте первый ход:",
            parse_mode="Markdown"
        )
        # Инициализируем поле 3x3
        board = [[" " for _ in range(3)] for _ in range(3)]
        await state.update_data(ttt_board=board, ttt_turn="X")
        await show_ttt_board(callback.message, board)
        await state.set_state(GameStates.ttt_move)
    
    elif game_type == "slots":
        await callback.message.edit_text(
            "🎰 *Слот-машина*\n\n"
            "Введите вашу ставку (целое число):",
            parse_mode="Markdown"
        )
        await state.set_state(GameStates.bet)
    
    await callback.answer()

@router.message(GameStates.bet)
async def process_bet(message: Message, state: FSMContext):
    """Обработка ставки"""
    try:
        bet = int(message.text.strip())
        
        if bet <= 0:
            await message.answer("❌ Ставка должна быть положительным числом. Попробуйте снова:")
            return
        
        data = await state.get_data()
        account_id = data.get('current_account')
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT coins FROM accounts WHERE account_id = ?",
                (account_id,)
            )
            coins = cursor.fetchone()['coins']
            
            if bet > coins:
                await message.answer(
                    f"❌ Недостаточно средств. Ваш баланс: {coins} PC\n"
                    f"Введите ставку не более {coins} PC:"
                )
                return
        
        await state.update_data(bet=bet)
        
        game_type = data.get('game_type')
        if game_type == "guess":
            # Загадываем число
            secret = random.randint(1, 100)
            await state.update_data(
                secret_number=secret,
                attempts_left=7,
                game_state="playing"
            )
            
            await message.answer(
                f"🎲 *Угадай число*\n\n"
                f"✅ Ставка принята: {bet} PC\n"
                f"Я загадал число от 1 до 100.\n"
                f"У вас 7 попыток.\n\n"
                f"Введите ваше предположение:",
                parse_mode="Markdown"
            )
            await state.set_state(GameStates.play)
        
        elif game_type == "slots":
            await message.answer(
                f"🎰 *Слот-машина*\n\n"
                f"✅ Ставка принята: {bet} PC\n\n"
                f"Нажмите кнопку, чтобы крутить:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎰 Крутить!", callback_data="spin_slots")],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_games")]
                ]),
                parse_mode="Markdown"
            )
            await state.set_state(GameStates.play)
    
    except ValueError:
        await message.answer("❌ Пожалуйста, введите целое число. Попробуйте снова:")

async def show_ttt_board(message: Message, board: List[List[str]]):
    """Показать поле крестиков-ноликов"""
    symbols = {" ": "⬜", "X": "❌", "O": "⭕️"}
    
    board_text = ""
    for i in range(3):
        row = []
        for j in range(3):
            cell_id = i * 3 + j + 1
            if board[i][j] == " ":
                row.append(f"[{cell_id}](ttt_{cell_id})")
            else:
                row.append(symbols[board[i][j]])
        board_text += " | ".join(row) + "\n"
        if i < 2:
            board_text += "───┼───┼───\n"
    
    await message.answer(
        f"❌⭕️ *Крестики-Нолики*\n\n{board_text}\nВы играете за ❌",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

@router.callback_query(GameStates.ttt_move, F.data.startswith("ttt_"))
async def process_ttt_move(callback: CallbackQuery, state: FSMContext):
    """Обработка хода в крестиках-ноликах"""
    try:
        cell = int(callback.data.split("_")[1]) - 1
        row, col = cell // 3, cell % 3
        
        data = await state.get_data()
        board = data['ttt_board']
        turn = data['ttt_turn']
        account_id = data['current_account']
        bet = data.get('bet')
        
        if board[row][col] != " ":
            await callback.answer("❌ Эта клетка уже занята!", show_alert=True)
            return
        
        # Ход игрока
        board[row][col] = "X"
        
        # Проверяем победу игрока
        if check_ttt_win(board, "X"):
            await finish_game(callback, state, account_id, bet, 2.0, "win")
            return
        
        # Проверяем ничью
        if all(cell != " " for row in board for cell in row):
            await finish_game(callback, state, account_id, bet, 1.0, "draw")
            return
        
        # Ход бота
        bot_move = get_bot_move(board)
        if bot_move:
            br, bc = bot_move
            board[br][bc] = "O"
            
            # Проверяем победу бота
            if check_ttt_win(board, "O"):
                await finish_game(callback, state, account_id, bet, 0.0, "loss")
                return
            
            # Проверяем ничью
            if all(cell != " " for row in board for cell in row):
                await finish_game(callback, state, account_id, bet, 1.0, "draw")
                return
        
        await state.update_data(ttt_board=board)
        await callback.message.delete()
        await show_ttt_board(callback.message, board)
        
        await callback.answer()
    
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)

def check_ttt_win(board: List[List[str]], player: str) -> bool:
    """Проверка победы в крестиках-ноликах"""
    # Проверка строк и столбцов
    for i in range(3):
        if all(board[i][j] == player for j in range(3)):
            return True
        if all(board[j][i] == player for j in range(3)):
            return True
    
    # Проверка диагоналей
    if all(board[i][i] == player for i in range(3)):
        return True
    if all(board[i][2-i] == player for i in range(3)):
        return True
    
    return False

def get_bot_move(board: List[List[str]]) -> Optional[Tuple[int, int]]:
    """Ход бота в крестиках-ноликах"""
    # Проверяем, может ли бот выиграть
    for i in range(3):
        for j in range(3):
            if board[i][j] == " ":
                board[i][j] = "O"
                if check_ttt_win(board, "O"):
                    board[i][j] = " "
                    return (i, j)
                board[i][j] = " "
    
    # Проверяем, может ли игрок выиграть (блокируем)
    for i in range(3):
        for j in range(3):
            if board[i][j] == " ":
                board[i][j] = "X"
                if check_ttt_win(board, "X"):
                    board[i][j] = " "
                    return (i, j)
                board[i][j] = " "
    
    # Пытаемся занять центр
    if board[1][1] == " ":
        return (1, 1)
    
    # Занимаем углы
    corners = [(0, 0), (0, 2), (2, 0), (2, 2)]
    random.shuffle(corners)
    for i, j in corners:
        if board[i][j] == " ":
            return (i, j)
    
    # Занимаем оставшиеся клетки
    for i in range(3):
        for j in range(3):
            if board[i][j] == " ":
                return (i, j)
    
    return None

@router.message(GameStates.play)
async def process_guess(message: Message, state: FSMContext):
    """Обработка угадывания числа"""
    data = await state.get_data()
    game_type = data.get('game_type')
    
    if game_type != "guess":
        return
    
    try:
        guess = int(message.text.strip())
        secret = data['secret_number']
        attempts_left = data['attempts_left'] - 1
        bet = data['bet']
        account_id = data['current_account']
        
        if guess < 1 or guess > 100:
            await message.answer("❌ Число должно быть от 1 до 100. Попробуйте снова:")
            return
        
        if guess < secret:
            hint = "⬆️ Загаданное число больше"
        elif guess > secret:
            hint = "⬇️ Загаданное число меньше"
        else:
            # Угадали!
            await finish_game(message, state, account_id, bet, 3.0, "win")
            return
        
        if attempts_left <= 0:
            # Проиграли
            await finish_game(message, state, account_id, bet, 0.0, "loss")
            return
        
        await state.update_data(attempts_left=attempts_left)
        await message.answer(
            f"{hint}\n"
            f"Осталось попыток: {attempts_left}\n"
            f"Введите следующее предположение:"
        )
    
    except ValueError:
        await message.answer("❌ Пожалуйста, введите целое число. Попробуйте снова:")

@router.callback_query(GameStates.rps_choice, F.data.startswith("rps_"))
async def process_rps_choice(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора в камень-ножницы-бумага"""
    choice = callback.data.split("_")[1]
    choices = {"rock": "✊", "paper": "✋", "scissors": "✌️"}
    
    data = await state.get_data()
    account_id = data.get('current_account')
    
    # Запрашиваем ставку
    await callback.message.edit_text(
        f"✊✋✌️ *Камень-Ножницы-Бумага*\n\n"
        f"Ваш выбор: {choices[choice]}\n\n"
        f"Введите вашу ставку (целое число):",
        parse_mode="Markdown"
    )
    await state.update_data(rps_choice=choice)
    await state.set_state(GameStates.bet)
    await callback.answer()

@router.callback_query(GameStates.play, F.data == "spin_slots")
async def spin_slots(callback: CallbackQuery, state: FSMContext):
    """Крутить слот-машину"""
    data = await state.get_data()
    account_id = data.get('current_account')
    bet = data.get('bet')
    
    # Генерируем символы
    symbols = ["🍒", "🍋", "🍊", "🍇", "🔔", "⭐", "7️⃣"]
    reels = [random.choice(symbols) for _ in range(3)]
    
    # Определяем выигрыш
    if reels[0] == reels[1] == reels[2]:
        if reels[0] == "7️⃣":
            multiplier = 10.0
        elif reels[0] == "⭐":
            multiplier = 5.0
        else:
            multiplier = 3.0
    elif reels[0] == reels[1] or reels[1] == reels[2]:
        multiplier = 1.5
    else:
        multiplier = 0.0
    
    await finish_game(callback, state, account_id, bet, multiplier, "win" if multiplier > 0 else "loss")
    await callback.answer()

async def finish_game(source, state: FSMContext, account_id: int, bet: int, multiplier: float, result: str):
    """Завершение игры и обработка результата"""
    data = await state.get_data()
    game_name = data.get('game_name')
    
    # Используем попытку
    use_attempt(account_id, game_name)
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Получаем информацию об аккаунте для бонусов уровня
        cursor.execute(
            "SELECT level, exp FROM accounts WHERE account_id = ?",
            (account_id,)
        )
        account = cursor.fetchone()
        level_info = get_level_info(account)
        
        # Применяем бонус уровня к множителю
        win_multiplier = multiplier * (1 + level_info["bonus_win"])
        
        # Проверяем шанс удвоения
        double_win = False
        if result == "win" and random.random() < level_info["double_win_chance"]:
            win_multiplier *= 2
            double_win = True
        
        win_amount = int(bet * win_multiplier)
        
        # Обновляем баланс
        if result == "win":
            cursor.execute(
                "UPDATE accounts SET coins = coins + ? WHERE account_id = ?",
                (win_amount - bet, account_id)
            )
        else:
            cursor.execute(
                "UPDATE accounts SET coins = coins - ? WHERE account_id = ?",
                (bet, account_id)
            )
        
        # Добавляем опыт
        exp_gained = int(bet * 0.1)  # 10% от ставки в опыт
        await add_exp(account_id, exp_gained)
        
        # Обновляем статистику
        cursor.execute(
            "UPDATE accounts SET games_played = games_played + 1 WHERE account_id = ?",
            (account_id,)
        )
        
        # Записываем действие
        cursor.execute(
            "INSERT INTO actions (account_id, action) VALUES (?, ?)",
            (account_id, f"game_{game_name}_{result}_{win_amount}")
        )
        
        conn.commit()
        
        # Формируем сообщение о результате
        if isinstance(source, CallbackQuery):
            message = source.message
        else:
            message = source
        
        result_text = ""
        if result == "win":
            result_text = f"✅ *Победа!*\n\n"
            result_text += f"Вы выиграли: {win_amount} PC\n"
            result_text += f"Множитель: {multiplier}x\n"
            if level_info["bonus_win"] > 0:
                result_text += f"Бонус уровня: +{int(level_info['bonus_win']*100)}%\n"
            if double_win:
                result_text += f"✨ *ДВОЙНОЙ ВЫИГРЫШ благодаря уровню!*\n"
        elif result == "loss":
            result_text = f"❌ *Поражение*\n\n"
            result_text += f"Вы проиграли: {bet} PC\n"
        else:  # draw
            result_text = f"🤝 *Ничья*\n\n"
            result_text += f"Ставка возвращена\n"
        
        # Получаем обновленный баланс
        cursor.execute(
            "SELECT coins FROM accounts WHERE account_id = ?",
            (account_id,)
        )
        new_balance = cursor.fetchone()['coins']
        
        result_text += f"\n💳 Новый баланс: {new_balance} PC"
        
        await message.answer(
            result_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎮 Играть снова", callback_data="game_" + data.get('game_type'))],
                [InlineKeyboardButton(text="📊 Главное меню", callback_data="back_to_menu")]
            ]),
            parse_mode="Markdown"
        )
    
    await state.clear()

# ========== ОБРАБОТЧИКИ МАГАЗИНА ==========
@router.callback_query(ShopStates.browsing, F.data.startswith("shop_"))
async def shop_item_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора товара в магазине"""
    item = callback.data.split("_")[1]
    data = await state.get_data()
    account_id = data.get('current_account')
    
    if not account_id:
        await callback.answer("❌ Сначала войдите в аккаунт", show_alert=True)
        return
    
    if item == "cancel":
        await callback.message.delete()
        await state.clear()
        await callback.answer()
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Получаем информацию о товаре
        cursor.execute(
            "SELECT price FROM shop_prices WHERE item = ?",
            (item,)
        )
        price_info = cursor.fetchone()
        
        if not price_info:
            await callback.answer("❌ Товар не найден", show_alert=True)
            return
        
        base_price = price_info['price']
        discount = get_promotion_discount(item)
        final_price = int(base_price * (1 - discount/100))
        
        # Проверяем, есть ли уже этот товар
        if item in PROFESSIONS:
            cursor.execute(
                "SELECT profession FROM accounts WHERE account_id = ?",
                (account_id,)
            )
            current_prof = cursor.fetchone()['profession']
            if current_prof == item:
                await callback.answer("❌ У вас уже есть эта профессия", show_alert=True)
                return
        
        await state.update_data(
            shop_item=item,
            shop_price=final_price,
            shop_quantity=1
        )
        
        item_names = {
            "junior": "👨‍💻 Профессия Junior",
            "middle": "👨‍💼 Профессия Middle",
            "senior": "👨‍🔬 Профессия Senior",
            "manager": "👨‍💼 Профессия Manager",
            "director": "👨‍💼 Профессия Director",
            "temp_attempts": "🔄 Временные попытки",
            "perm_attempts": "⭐ Перманентные попытки"
        }
        
        item_name = item_names.get(item, item)
        
        text = f"🛒 *Покупка*\n\n"
        text += f"*Товар:* {item_name}\n"
        text += f"*Цена:* {final_price} PC"
        if discount > 0:
            text += f" (скидка {discount}%)\n"
        else:
            text += "\n"
        
        if item in ["temp_attempts", "perm_attempts"]:
            text += f"\n*Количество:* 1\n\n"
            text += "Подтвердите покупку:"
            await callback.message.edit_text(
                text,
                reply_markup=confirm_keyboard(item, 1),
                parse_mode="Markdown"
            )
        else:
            await callback.message.edit_text(
                text + "\nПодтвердите покупку:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Купить", callback_data=f"buy_{item}_1"),
                     InlineKeyboardButton(text="❌ Отмена", callback_data="shop_cancel")]
                ]),
                parse_mode="Markdown"
            )
    
    await callback.answer()

@router.callback_query(ShopStates.browsing, F.data.startswith(("buy_", "inc_", "dec_")))
async def shop_purchase_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик покупки в магазине"""
    data = await state.get_data()
    account_id = data.get('current_account')
    
    if not account_id:
        await callback.answer("❌ Сначала войдите в аккаунт", show_alert=True)
        return
    
    action, item, *rest = callback.data.split("_")
    quantity = int(rest[0]) if rest else 1
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Получаем баланс
        cursor.execute(
            "SELECT coins FROM accounts WHERE account_id = ?",
            (account_id,)
        )
        balance = cursor.fetchone()['coins']
        
        # Получаем цену товара
        cursor.execute(
            "SELECT price FROM shop_prices WHERE item = ?",
            (item,)
        )
        price_info = cursor.fetchone()
        
        if not price_info:
            await callback.answer("❌ Товар не найден", show_alert=True)
            return
        
        base_price = price_info['price']
        discount = get_promotion_discount(item)
        final_price = int(base_price * (1 - discount/100))
        total_price = final_price * quantity
        
        if action == "buy":
            # Проверяем баланс
            if balance < total_price:
                await callback.answer(
                    f"❌ Недостаточно средств. Нужно: {total_price} PC",
                    show_alert=True
                )
                return
            
            # Совершаем покупку
            if item in PROFESSIONS:
                # Покупка профессии
                cursor.execute(
                    "UPDATE accounts SET profession = ?, coins = coins - ? WHERE account_id = ?",
                    (item, total_price, account_id)
                )
                
                # Записываем действие
                cursor.execute(
                    "INSERT INTO actions (account_id, action) VALUES (?, ?)",
                    (account_id, f"buy_profession_{item}_{total_price}")
                )
                
                await callback.message.edit_text(
                    f"✅ *Покупка совершена!*\n\n"
                    f"Вы приобрели профессию: {item}\n"
                    f"Списано: {total_price} PC\n"
                    f"Новый баланс: {balance - total_price} PC\n\n"
                    f"Теперь вы будете получать {PROFESSIONS[item]} PC каждый час!",
                    parse_mode="Markdown"
                )
            
            elif item == "temp_attempts":
                # Временные попытки
                cursor.execute(
                    "UPDATE game_attempts SET extra_attempts = extra_attempts + ? WHERE account_id = ?",
                    (5 * quantity, account_id)
                )
                
                cursor.execute(
                    "UPDATE accounts SET coins = coins - ? WHERE account_id = ?",
                    (total_price, account_id)
                )
                
                cursor.execute(
                    "INSERT INTO actions (account_id, action) VALUES (?, ?)",
                    (account_id, f"buy_temp_attempts_{total_price}")
                )
                
                await callback.message.edit_text(
                    f"✅ *Покупка совершена!*\n\n"
                    f"Вы приобрели временные попытки\n"
                    f"+{5 * quantity} попыток ко всем играм на сегодня\n"
                    f"Списано: {total_price} PC\n"
                    f"Новый баланс: {balance - total_price} PC",
                    parse_mode="Markdown"
                )
            
            elif item == "perm_attempts":
                # Перманентные попытки
                cursor.execute(
                    "UPDATE game_attempts SET permanent_max = permanent_max + ? WHERE account_id = ?",
                    (quantity, account_id)
                )
                
                cursor.execute(
                    "UPDATE accounts SET coins = coins - ? WHERE account_id = ?",
                    (total_price, account_id)
                )
                
                cursor.execute(
                    "INSERT INTO actions (account_id, action) VALUES (?, ?)",
                    (account_id, f"buy_perm_attempts_{total_price}")
                )
                
                await callback.message.edit_text(
                    f"✅ *Покупка совершена!*\n\n"
                    f"Вы приобрели перманентные попытки\n"
                    f"+{quantity} к максимальному количеству попыток во всех играх\n"
                    f"Списано: {total_price} PC\n"
                    f"Новый баланс: {balance - total_price} PC",
                    parse_mode="Markdown"
                )
            
            conn.commit()
            await state.clear()
        
        elif action in ["inc", "dec"]:
            # Изменение количества
            current_qty = data.get('shop_quantity', 1)
            
            if action == "inc":
                new_qty = current_qty + 1
                if new_qty > 10:  # Максимум 10
                    await callback.answer("❌ Максимум 10 штук", show_alert=True)
                    return
            else:  # dec
                new_qty = current_qty - 1
                if new_qty < 1:
                    await callback.answer("❌ Минимум 1 штука", show_alert=True)
                    return
            
            total_price = final_price * new_qty
            
            item_names = {
                "temp_attempts": "🔄 Временные попытки",
                "perm_attempts": "⭐ Перманентные попытки"
            }
            
            item_name = item_names.get(item, item)
            
            text = f"🛒 *Покупка*\n\n"
            text += f"*Товар:* {item_name}\n"
            text += f"*Цена за шт:* {final_price} PC"
            if discount > 0:
                text += f" (скидка {discount}%)\n"
            else:
                text += "\n"
            text += f"*Количество:* {new_qty}\n"
            text += f"*Итого:* {total_price} PC\n\n"
            text += f"*Ваш баланс:* {balance} PC\n\n"
            
            if balance < total_price:
                text += "❌ *Недостаточно средств*\n"
            
            text += "Подтвердите покупку:"
            
            await state.update_data(shop_quantity=new_qty)
            await callback.message.edit_text(
                text,
                reply_markup=confirm_keyboard(item, new_qty),
                parse_mode="Markdown"
            )
    
    await callback.answer()

# ========== ОБРАБОТЧИКИ АДМИН ПАНЕЛИ ==========
@router.callback_query(F.data.startswith("admin_"))
async def admin_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик админ панели"""
    action = callback.data.split("_")[1]
    data = await state.get_data()
    account_id = data.get('current_account')
    
    if not account_id:
        await callback.answer("❌ Сначала войдите в аккаунт", show_alert=True)
        return
    
    # Проверяем права администратора
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
            await callback.answer("❌ У вас нет прав администратора", show_alert=True)
            return
    
    if action == "stats":
        # Статистика
        cursor.execute("SELECT COUNT(*) as count FROM users")
        users_count = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) as count FROM accounts")
        accounts_count = cursor.fetchone()['count']
        
        cursor.execute("SELECT SUM(coins) as total FROM accounts")
        total_coins = cursor.fetchone()['total'] or 0
        
        cursor.execute("SELECT COUNT(*) as count FROM giveaways WHERE status = 'active'")
        active_giveaways = cursor.fetchone()['count']
        
        await callback.message.edit_text(
            f"📊 *Статистика бота*\n\n"
            f"👥 *Пользователи:* {users_count}\n"
            f"👤 *Аккаунты:* {accounts_count}\n"
            f"💰 *Всего монет:* {total_coins} PC\n"
            f"🎁 *Активные розыгрыши:* {active_giveaways}\n\n"
            f"Выберите действие:",
            reply_markup=admin_keyboard(),
            parse_mode="Markdown"
        )
    
    elif action == "prices":
        await callback.message.edit_text(
            "💰 *Изменение цен*\n\n"
            "Введите данные в формате:\n"
            "`товар:цена`\n\n"
            "Пример: `junior:600`\n\n"
            "Доступные товары: junior, middle, senior, manager, director, "
            "temp_attempts, perm_attempts",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.manage_prices)
    
    elif action == "giveaway":
        await callback.message.edit_text(
            "🎁 *Создание розыгрыша*\n\n"
            "Введите данные в формате:\n"
            "`приз:дата-время`\n\n"
            "Пример: `1000 PC:2024-12-31 23:59`",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.create_giveaway)
    
    elif action == "max_accounts":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Для всех пользователей", callback_data="max_all")],
            [InlineKeyboardButton(text="Для конкретного пользователя", callback_data="max_user")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
        ])
        await callback.message.edit_text(
            "👥 *Установка максимального количества аккаунтов*\n\n"
            "Выберите действие:",
            reply_markup=kb,
            parse_mode="Markdown"
        )
    
    elif action == "add_quest":
        await callback.message.edit_text(
            "📝 *Добавление квеста*\n\n"
            "Введите описание квеста:",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.add_quest)
    
    elif action == "broadcast":
        await callback.message.edit_text(
            "📢 *Рассылка*\n\n"
            "Введите сообщение для рассылки всем пользователям:",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.broadcast)
    
    elif action == "promotion":
        await callback.message.edit_text(
            "🏷️ *Создание акции*\n\n"
            "Введите данные в формате:\n"
            "`товар:скидка%:дата-время`\n\n"
            "Пример: `junior:20:2024-12-31 23:59`\n\n"
            "Скидка действует до указанной даты.",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.create_promotion)
    
    elif action == "accounts":
        # Просмотр аккаунтов
        cursor.execute('''
        SELECT a.*, u.tg_id 
        FROM accounts a
        JOIN users u ON a.tg_id = u.tg_id
        ORDER BY a.coins DESC
        LIMIT 20
        ''')
        
        accounts = cursor.fetchall()
        
        text = "👤 *Последние 20 аккаунтов*\n\n"
        for acc in accounts:
            text += f"👤 {acc['username']}\n"
            text += f"💰 {acc['coins']} PC | ⭐ Ур. {acc['level']}\n"
            text += f"📅 {acc['created_at'][:10]}\n"
            text += f"ID: {acc['account_id']}\n\n"
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
            ]),
            parse_mode="Markdown"
        )
    
    await callback.answer()

@router.message(AdminStates.manage_prices)
async def admin_process_prices(message: Message, state: FSMContext):
    """Обработка изменения цен"""
    try:
        item, price = message.text.split(":")
        item = item.strip()
        price = int(price.strip())
        
        if price < 0:
            await message.answer("❌ Цена не может быть отрицательной. Попробуйте снова:")
            return
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Проверяем, существует ли товар
            cursor.execute(
                "SELECT * FROM shop_prices WHERE item = ?",
                (item,)
            )
            if not cursor.fetchone():
                await message.answer(
                    f"❌ Товар '{item}' не найден. Доступные товары: "
                    "junior, middle, senior, manager, director, temp_attempts, perm_attempts\n"
                    "Попробуйте снова:"
                )
                return
            
            # Обновляем цену
            cursor.execute(
                "UPDATE shop_prices SET price = ? WHERE item = ?",
                (price, item)
            )
            conn.commit()
            
            await message.answer(
                f"✅ Цена товара '{item}' изменена на {price} PC",
                reply_markup=admin_keyboard()
            )
            await state.clear()
    
    except ValueError:
        await message.answer("❌ Неверный формат. Используйте: `товар:цена`\nПопробуйте снова:", parse_mode="Markdown")

@router.message(AdminStates.create_giveaway)
async def admin_process_giveaway(message: Message, state: FSMContext):
    """Обработка создания розыгрыша"""
    try:
        prize, date_str = message.text.split(":", 1)
        prize = prize.strip()
        date_str = date_str.strip()
        
        # Парсим дату
        try:
            end_time = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        except:
            end_time = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            end_time = end_time.replace(hour=23, minute=59)
        
        if end_time < datetime.datetime.now():
            await message.answer("❌ Дата должна быть в будущем. Попробуйте снова:")
            return
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
            INSERT INTO giveaways (prize, end_time, status)
            VALUES (?, ?, 'active')
            ''', (prize, end_time.isoformat()))
            
            giveaway_id = cursor.lastrowid
            
            conn.commit()
            
            # Запускаем таймер для завершения розыгрыша
            asyncio.create_task(finish_giveaway(giveaway_id, end_time))
            
            await message.answer(
                f"✅ Розыгрыш создан!\n\n"
                f"🎁 *Приз:* {prize}\n"
                f"⏰ *Завершится:* {end_time.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"ID розыгрыша: {giveaway_id}",
                reply_markup=admin_keyboard(),
                parse_mode="Markdown"
            )
            await state.clear()
    
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}\nПопробуйте снова:")

async def finish_giveaway(giveaway_id: int, end_time: datetime.datetime):
    """Завершение розыгрыша"""
    # Ждем до времени завершения
    now = datetime.datetime.now()
    if end_time > now:
        await asyncio.sleep((end_time - now).total_seconds())
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Получаем участников
        cursor.execute('''
        SELECT gp.account_id, a.tg_id, a.username
        FROM giveaway_participants gp
        JOIN accounts a ON gp.account_id = a.account_id
        WHERE gp.giveaway_id = ?
        ''', (giveaway_id,))
        
        participants = cursor.fetchall()
        
        if participants:
            # Выбираем победителя
            winner = random.choice(participants)
            
            # Обновляем статус розыгрыша
            cursor.execute(
                "UPDATE giveaways SET status = 'ended' WHERE id = ?",
                (giveaway_id,)
            )
            
            conn.commit()
            
            # Уведомляем победителя
            try:
                await bot.send_message(
                    winner['tg_id'],
                    f"🎉 *Поздравляем!*\n\n"
                    f"Вы выиграли в розыгрыше!\n"
                    f"🎁 *Приз:* {prize}\n\n"
                    f"Свяжитесь с администратором для получения приза.",
                    parse_mode="Markdown"
                )
            except:
                pass
            
            # Уведомляем администратора
            cursor.execute(
                "SELECT prize FROM giveaways WHERE id = ?",
                (giveaway_id,)
            )
            prize = cursor.fetchone()['prize']
            
            admin_ids = []
            cursor.execute("SELECT tg_id FROM users WHERE admin = 1")
            for row in cursor.fetchall():
                admin_ids.append(row['tg_id'])
            
            for admin_id in admin_ids:
                try:
                    await bot.send_message(
                        admin_id,
                        f"🏆 *Розыгрыш завершен!*\n\n"
                        f"🎁 *Приз:* {prize}\n"
                        f"👤 *Победитель:* {winner['username']}\n"
                        f"🆔 *ID аккаунта:* {winner['account_id']}\n"
                        f"🎫 *Участников:* {len(participants)}",
                        parse_mode="Markdown"
                    )
                except:
                    pass

# ========== ОБРАБОТЧИК ВОЗВРАТА ==========
@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    await state.clear()
    
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
        
        await callback.message.edit_text(
            "📊 *Главное меню*\n\n"
            "Выберите действие:",
            parse_mode="Markdown"
        )
        
        await callback.message.answer(
            "Главное меню:",
            reply_markup=main_menu_keyboard(is_admin, callback.message.chat.type == "private")
        )
    else:
        await callback.message.edit_text(
            "Главное меню",
            reply_markup=login_keyboard()
        )
    
    await callback.answer()

@router.callback_query(F.data == "back_to_games")
async def back_to_games(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору игры"""
    await state.clear()
    await callback.message.edit_text(
        "🎮 *Выберите игру:*",
        reply_markup=games_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: CallbackQuery, state: FSMContext):
    """Возврат в админ панель"""
    await callback.message.edit_text(
        "⚙️ *Админ панель*\n\n"
        "Выберите действие:",
        reply_markup=admin_keyboard(),
        parse_mode="Markdown"
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

# ========== ЗАПУСК БОТА ==========
async def main():
    """Основная функция запуска бота"""
    # Инициализируем базу данных
    init_db()
    
    # Запускаем периодические задачи
    asyncio.create_task(periodic_tasks())
    
    # Запускаем бота
    await dp.start_polling(bot)

async def periodic_tasks():
    """Периодические задачи"""
    while True:
        # Сбрасываем ежедневную статистику в полночь
        now = datetime.datetime.now()
        if now.hour == 0 and now.minute == 0:
            reset_daily_stats()
        
        # Проверяем просроченные акции
        with get_db() as conn:
            cursor = conn.cursor()
            now_iso = datetime.datetime.now().isoformat()
            cursor.execute(
                "DELETE FROM promotions WHERE end_time < ?",
                (now_iso,)
            )
            conn.commit()
        
        # Ждем 1 минуту перед следующей проверкой
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())

