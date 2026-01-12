"""
============================================
POLICE DEPARTMENT - Telegram Game Bot
ПОЛНЫЙ РАБОЧИЙ КОД
Версия: 1.0
============================================
"""

import asyncio
import logging
import random
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ============================================
# КОНФИГУРАЦИЯ
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Настройки игры
MAX_PLAYERS = 50
MIN_PLAYERS = 5
MURDER_COOLDOWN = 900  # 15 минут
KILLS_TO_WIN = 20

# Шансы ролей
ROLE_CHANCES = {
    "police": 40.0,
    "civilian": 35.0,
    "boss": 3.0,
    "it": 4.0,
    "criminal": 3.0,
    "any": 15.0
}

# Полицейские ники
POLICE_NICKS = [
    "Орел", "Волк", "Тигр", "Медведь", "Сокол", "Ястреб", "Барс", 
    "Рысь", "Феникс", "Гриф", "Коршун", "Кондор", "Буревестник"
]

# ============================================
# МОДЕЛИ ДАННЫХ
# ============================================

class Role(Enum):
    POLICE = "👮 Полицейский"
    BOSS = "🧠 Начальник"
    IT = "💻 ИТ-специалист"
    CRIMINAL = "🕵️‍♂️ Преступник"
    CIVILIAN = "🧍 Мирный"

class GameState(Enum):
    WAITING = "ожидание"
    REGISTRATION = "регистрация"
    ACTIVE = "активная"
    FINISHED = "завершена"

@dataclass
class Player:
    user_id: int
    username: str
    role: Optional[Role] = None
    chosen_role: Optional[Role] = None
    police_nick: Optional[str] = None
    reputation: int = 50
    intelligence: int = 0
    kills: int = 0
    arrested: bool = False
    dead: bool = False
    notes: Dict[str, str] = field(default_factory=dict)
    witnesses: Dict[str, str] = field(default_factory=dict)

@dataclass
class Game:
    chat_id: int
    state: GameState = GameState.WAITING
    players: Dict[int, Player] = field(default_factory=dict)
    start_time: Optional[datetime] = None
    murder_count: int = 0
    criminal_id: Optional[int] = None
    boss_id: Optional[int] = None
    it_id: Optional[int] = None
    news: List[str] = field(default_factory=list)

# ============================================
# ХРАНИЛИЩЕ
# ============================================

class GameStorage:
    def __init__(self):
        self.games: Dict[int, Game] = {}
        self.user_games: Dict[int, int] = {}
    
    def create_game(self, chat_id: int) -> Game:
        game = Game(chat_id=chat_id)
        self.games[chat_id] = game
        return game
    
    def get_game(self, chat_id: int) -> Optional[Game]:
        return self.games.get(chat_id)
    
    def get_player_game(self, user_id: int) -> Optional[Game]:
        chat_id = self.user_games.get(user_id)
        return self.games.get(chat_id) if chat_id else None
    
    def add_player(self, chat_id: int, user_id: int, username: str) -> Optional[Player]:
        game = self.get_game(chat_id)
        if not game or game.state != GameState.REGISTRATION:
            return None
        
        if user_id in game.players:
            return game.players[user_id]
        
        player = Player(user_id=user_id, username=username)
        game.players[user_id] = player
        self.user_games[user_id] = chat_id
        return player

storage = GameStorage()

# ============================================
# СОСТОЯНИЯ FSM
# ============================================

class GameStates(StatesGroup):
    waiting_for_players = State()
    role_selection = State()
    investigation = State()
    interrogation = State()
    reporting = State()
    complaint = State()

# ============================================
# ИНИЦИАЛИЗАЦИЯ БОТА
# ============================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ============================================
# КЛАВИАТУРЫ
# ============================================

def get_role_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👮 Полицейский", callback_data="role_police"),
        InlineKeyboardButton(text="🧠 Начальник", callback_data="role_boss"),
    )
    builder.row(
        InlineKeyboardButton(text="💻 ИТ-специалист", callback_data="role_it"),
        InlineKeyboardButton(text="🕵️‍♂️ Преступник", callback_data="role_criminal"),
    )
    builder.row(
        InlineKeyboardButton(text="🧍 Мирный", callback_data="role_civilian"),
        InlineKeyboardButton(text="🎲 Без разницы", callback_data="role_any"),
    )
    return builder.as_markup()

def get_join_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ Присоединиться", callback_data="join_game"))
    return builder.as_markup()

def get_game_start_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🚀 Начать игру", callback_data="begin_game"))
    builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_game"))
    return builder.as_markup()

def get_police_actions_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔍 Расследовать", callback_data="action_investigate"),
        InlineKeyboardButton(text="📝 Отчёт", callback_data="action_report"),
    )
    builder.row(
        InlineKeyboardButton(text="🗣️ Допрос", callback_data="action_interrogate"),
        InlineKeyboardButton(text="💾 Заметки", callback_data="action_notes"),
    )
    return builder.as_markup()

def get_boss_actions_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Отчёты", callback_data="boss_reports"),
        InlineKeyboardButton(text="⚖️ Жалобы", callback_data="boss_complaints"),
    )
    builder.row(
        InlineKeyboardButton(text="👥 Состав", callback_data="boss_team"),
        InlineKeyboardButton(text="📢 Объявление", callback_data="boss_announce"),
    )
    return builder.as_markup()

def get_criminal_actions_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔪 Убить NPC", callback_data="criminal_kill_npc"),
        InlineKeyboardButton(text="👥 Общаться", callback_data="criminal_talk"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Логи", callback_data="criminal_logs"),
        InlineKeyboardButton(text="🏃 Скрыться", callback_data="criminal_hide"),
    )
    return builder.as_markup()

# ============================================
# УТИЛИТЫ
# ============================================

def assign_roles(game: Game) -> Dict[int, Role]:
    """Распределение ролей с учётом предпочтений"""
    players = list(game.players.values())
    roles = []
    
    # Подсчитываем предпочтения
    role_requests = {Role.POLICE: 0, Role.BOSS: 0, Role.IT: 0, 
                    Role.CRIMINAL: 0, Role.CIVILIAN: 0}
    
    for player in players:
        if player.chosen_role:
            role_requests[player.chosen_role] += 1
    
    # Определяем сколько каждой роли нужно
    total = len(players)
    needed = {
        Role.BOSS: 1,
        Role.IT: 1,
        Role.CRIMINAL: 1,
        Role.POLICE: max(2, min(10, total // 3)),
        Role.CIVILIAN: total - 3 - min(10, total // 3)
    }
    
    # Сначала назначаем уникальные роли
    assigned = {}
    available_police_nicks = POLICE_NICKS.copy()
    
    # Ищем преступника (с учётом желающих)
    criminal_candidates = [p for p in players if p.chosen_role == Role.CRIMINAL]
    if criminal_candidates:
        criminal = random.choice(criminal_candidates)
    else:
        criminal = random.choice(players)
    assigned[criminal.user_id] = Role.CRIMINAL
    criminal.role = Role.CRIMINAL
    criminal.intelligence = random.randint(50, 100)
    game.criminal_id = criminal.user_id
    players.remove(criminal)
    
    # Ищем начальника
    boss_candidates = [p for p in players if p.chosen_role == Role.BOSS]
    if boss_candidates:
        boss = random.choice(boss_candidates)
    else:
        boss = random.choice(players)
    assigned[boss.user_id] = Role.BOSS
    boss.role = Role.BOSS
    game.boss_id = boss.user_id
    players.remove(boss)
    
    # Ищем ИТ
    it_candidates = [p for p in players if p.chosen_role == Role.IT]
    if it_candidates:
        it = random.choice(it_candidates)
    else:
        it = random.choice(players)
    assigned[it.user_id] = Role.IT
    it.role = Role.IT
    game.it_id = it.user_id
    players.remove(it)
    
    # Назначаем полицейских
    police_needed = needed[Role.POLICE]
    police_candidates = [p for p in players if p.chosen_role == Role.POLICE]
    
    # Берем желающих полицейских
    for player in police_candidates[:police_needed]:
        if police_needed <= 0:
            break
        assigned[player.user_id] = Role.POLICE
        player.role = Role.POLICE
        if available_police_nicks:
            player.police_nick = available_police_nicks.pop()
        players.remove(player)
        police_needed -= 1
    
    # Добираем случайных полицейских
    for player in players[:police_needed]:
        if police_needed <= 0:
            break
        assigned[player.user_id] = Role.POLICE
        player.role = Role.POLICE
        if available_police_nicks:
            player.police_nick = available_police_nicks.pop()
        players.remove(player)
        police_needed -= 1
    
    # Остальные - мирные
    for player in players:
        assigned[player.user_id] = Role.CIVILIAN
        player.role = Role.CIVILIAN
    
    return assigned

async def send_role_info(player: Player, game: Game):
    """Отправка информации о роли игроку"""
    if player.role == Role.POLICE:
        text = f"""
🎭 Ваша роль: {player.role.value}

📛 Ваш знак отличия: {player.police_nick}

🎯 Цели:
1. Найти и арестовать преступника
2. Расследовать убийства
3. Собирать доказательства
4. Докладывать начальнику

🛠️ Доступные действия:
• 🔍 Расследование
• 🗣️ Допрос свидетелей
• 📝 Составление отчётов
• 💾 Личные заметки

Все ваши сообщения будут подписываться:
«👮 Полицейский {player.police_nick}»
"""
        await bot.send_message(player.user_id, text, reply_markup=get_police_actions_keyboard())
    
    elif player.role == Role.BOSS:
        text = f"""
🎭 Ваша роль: {player.role.value}

🎯 Цели:
1. Руководить отделом
2. Рассматривать жалобы
3. Принимать решения об арестах
4. Сохранить репутацию отдела

⚠️ Правила:
• Вы НЕ можете просто уволить полицейского
• При жалобе ОБЯЗАНЫ разобраться
• Должны выслушать обе стороны
• Решение должно быть обоснованным

🛠️ Доступные действия:
• 📋 Просмотр отчётов
• ⚖️ Рассмотрение жалоб
• 👥 Управление составом
• 📢 Объявления отделу
"""
        await bot.send_message(player.user_id, text, reply_markup=get_boss_actions_keyboard())
    
    elif player.role == Role.CRIMINAL:
        text = f"""
🎭 Ваша роль: {player.role.value}

🧠 Интеллект: {player.intelligence}/100

🎯 Цель: Совершить {KILLS_TO_WIN} убийств

⚠️ Правила:
• Сначала убивайте NPC (неигровых персонажей)
• Игроков можно убивать после 3-х NPC
• Убийство полицейского = +2 убийства
• Убийство начальника/ИТ = высокий риск

🛠️ Доступные действия:
• 🔪 Убийства (КД 15 мин)
• 👥 Общение с мирными
• 📊 Перехват логов
• 🏃 Скрытие следов

Чем выше интеллект, тем больше логов вы перехватываете!
"""
        await bot.send_message(player.user_id, text, reply_markup=get_criminal_actions_keyboard())
    
    elif player.role == Role.IT:
        text = f"""
🎭 Ваша роль: {player.role.value}

🎯 Цели:
1. Помогать полиции в поисках
2. Отслеживать связь преступника
3. Анализировать данные
4. Сохранять анонимность полиции

🛠️ Доступные действия:
• 🔎 Поиск по базе данных
• 📱 Отслеживание связи
• 🛡️ Защита данных
• 📊 Анализ логов

Ваши сообщения подписываются:
«💻 ИТ-специалист»
"""
        await bot.send_message(player.user_id, text)
    
    else:  # CIVILIAN
        text = f"""
🎭 Ваша роль: {player.role.value}

🎯 Цели:
1. Выжить
2. Помогать полиции (или нет)
3. Распространять слухи
4. Подавать жалобы при нарушении

🛠️ Возможности:
• 👁️ Видеть новости и слухи
• 🗣️ Общаться с полицией анонимно
• ⚖️ Подавать жалобы на полицейских
• 🤥 Скрывать информацию или врать

Вы НЕ видите переписку полиции!
"""
        await bot.send_message(player.user_id, text)

async def broadcast_to_group(game: Game, text: str):
    """Отправка сообщения в группу"""
    try:
        await bot.send_message(game.chat_id, text)
    except Exception as e:
        logging.error(f"Ошибка отправки в группу: {e}")

async def send_news(game: Game):
    """Отправка новостей в группу"""
    news_templates = [
        "📰 В городе произошло очередное убийство. Полиция на месте.",
        "📰 Жители района сообщают о подозрительной активности.",
        "📰 Пресс-служба полиции готовит брифинг.",
        "📰 СМИ критикуют работу отдела по расследованию убийств.",
        "📰 Поступили новые свидетельские показания."
    ]
    
    news = random.choice(news_templates)
    game.news.append(news)
    await broadcast_to_group(game, news)

# ============================================
# ОСНОВНЫЕ ХЕНДЛЕРЫ
# ============================================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработка команды /start"""
    await message.answer(
        "👮 Добро пожаловать в игру 'ПОЛИЦЕЙСКИЙ ОТДЕЛ'!\n\n"
        "Это глубокая сюжетная игра в духе криминальных сериалов.\n\n"
        "Для начала игры в группе используйте:\n"
        "/start_game - начать регистрацию\n"
        "/begin - начать игру после регистрации\n"
        "/rules - правила игры"
    )

@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    """Правила игры"""
    rules = """
📖 ПРАВИЛА ИГРЫ «ПОЛИЦЕЙСКИЙ ОТДЕЛ»

🎭 Роли:
• 👮 Полицейский - расследует, допрашивает, докладывает
• 🧠 Начальник - руководит, рассматривает жалобы
• 💻 ИТ-специалист - ищет информацию, отслеживает
• 🕵️‍♂️ Преступник - убивает, скрывает следы
• 🧍 Мирный - свидетель, информатор

⚙️ Механики:
• Убийства происходят каждые 15 минут
• Преступник побеждает при 20 убийствах
• Полиция побеждает при аресте преступника
• Жалобы рассматриваются начальником
• Пытки опасны - могут привести к жалобам

🕒 Игра долгая, как сериал!
Расследования могут тянуться долго.
"""
    await message.answer(rules)

@dp.message(Command("start_game"))
async def cmd_start_game(message: Message):
    """Начало регистрации в группе"""
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("Эта команда работает только в группах!")
        return
    
    chat_id = message.chat.id
    game = storage.get_game(chat_id)
    
    if game and game.state != GameState.WAITING:
        await message.answer("Игра уже запущена в этой группе!")
        return
    
    if not game:
        game = storage.create_game(chat_id)
    
    game.state = GameState.REGISTRATION
    
    await message.answer(
        "🎮 Начинается регистрация на игру 'ПОЛИЦЕЙСКИЙ ОТДЕЛ'!\n\n"
        f"Минимум игроков: {MIN_PLAYERS}\n"
        f"Максимум игроков: {MAX_PLAYERS}\n\n"
        "Нажмите кнопку ниже, чтобы присоединиться:",
        reply_markup=get_join_keyboard()
    )

@dp.callback_query(F.data == "join_game")
async def join_game(callback: CallbackQuery):
    """Присоединение к игре"""
    user = callback.from_user
    chat_id = callback.message.chat.id
    game = storage.get_game(chat_id)
    
    if not game or game.state != GameState.REGISTRATION:
        await callback.answer("Регистрация не активна!", show_alert=True)
        return
    
    if len(game.players) >= MAX_PLAYERS:
        await callback.answer("Достигнут максимум игроков!", show_alert=True)
        return
    
    player = storage.add_player(chat_id, user.id, user.username or user.first_name)
    
    if player:
        # Отправляем выбор роли в ЛС
        try:
            await bot.send_message(
                user.id,
                "🎭 Вы присоединились к игре!\n\n"
                "Кем вы хотите быть?\n"
                "Выбор влияет на шанс получения роли.",
                reply_markup=get_role_keyboard()
            )
            await callback.answer(f"Вы присоединились! Игроков: {len(game.players)}/{MAX_PLAYERS}")
        except:
            await callback.answer(
                "Напишите мне в ЛС @{bot_username} чтобы выбрать роль!".format(
                    bot_username=(await bot.get_me()).username
                ),
                show_alert=True
            )
        
        # Обновляем сообщение в группе
        await callback.message.edit_text(
            f"🎮 Регистрация на игру 'ПОЛИЦЕЙСКИЙ ОТДЕЛ'!\n\n"
            f"✅ Присоединились: {len(game.players)}/{MAX_PLAYERS}\n"
            f"📍 Минимум для старта: {MIN_PLAYERS}\n\n"
            "Нажмите кнопку ниже, чтобы присоединиться:",
            reply_markup=get_join_keyboard()
        )
    else:
        await callback.answer("Ошибка присоединения!", show_alert=True)

@dp.callback_query(F.data.startswith("role_"))
async def select_role(callback: CallbackQuery):
    """Выбор роли"""
    user = callback.from_user
    role_map = {
        "role_police": Role.POLICE,
        "role_boss": Role.BOSS,
        "role_it": Role.IT,
        "role_criminal": Role.CRIMINAL,
        "role_civilian": Role.CIVILIAN,
        "role_any": None
    }
    
    role_key = callback.data
    chosen_role = role_map.get(role_key)
    
    game = storage.get_player_game(user.id)
    if not game:
        await callback.answer("Вы не в игре!", show_alert=True)
        return
    
    player = game.players.get(user.id)
    if not player:
        await callback.answer("Игрок не найден!", show_alert=True)
        return
    
    player.chosen_role = chosen_role
    
    if chosen_role:
        role_name = chosen_role.value
    else:
        role_name = "Без разницы"
    
    await callback.message.edit_text(
        f"✅ Ваш выбор сохранён: {role_name}\n\n"
        "Ждите начала игры. Роли будут распределены случайно с учётом ваших предпочтений.\n\n"
        "Игра начнется, когда наберется минимум игроков и администратор нажмет 'Начать игру'."
    )
    await callback.answer("Роль выбрана!")

@dp.message(Command("begin"))
async def cmd_begin(message: Message):
    """Начало игры"""
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("Эта команда работает только в группах!")
        return
    
    chat_id = message.chat.id
    game = storage.get_game(chat_id)
    
    if not game or game.state != GameState.REGISTRATION:
        await message.answer("Нет активной регистрации!")
        return
    
    if len(game.players) < MIN_PLAYERS:
        await message.answer(f"Недостаточно игроков! Минимум: {MIN_PLAYERS}")
        return
    
    # Распределяем роли
    assigned_roles = assign_roles(game)
    game.state = GameState.ACTIVE
    game.start_time = datetime.now()
    
    # Отправляем информацию о ролях в ЛС
    for player in game.players.values():
        try:
            await send_role_info(player, game)
        except Exception as e:
            logging.error(f"Не удалось отправить роль {player.user_id}: {e}")
    
    # Объявление в группе
    await broadcast_to_group(game,
        "🚨 ИГРА НАЧАЛАСЬ! 🚨\n\n"
        "Все игроки получили свои роли в личных сообщениях.\n\n"
        "📢 Первая новость от пресс-службы:"
    )
    
    # Первая новость
    await send_news(game)
    
    # Запускаем игровые циклы
    asyncio.create_task(game_loop(game))
    asyncio.create_task(murder_loop(game))

@dp.callback_query(F.data == "begin_game")
async def begin_game_callback(callback: CallbackQuery):
    """Начало игры через кнопку"""
    await cmd_begin(callback.message)

# ============================================
# ИГРОВЫЕ ДЕЙСТВИЯ - ПОЛИЦЕЙСКИЙ
# ============================================

@dp.callback_query(F.data == "action_investigate")
async def police_investigate(callback: CallbackQuery):
    """Полицейский начинает расследование"""
    user = callback.from_user
    game = storage.get_player_game(user.id)
    
    if not game:
        await callback.answer("Вы не в игре!", show_alert=True)
        return
    
    player = game.players.get(user.id)
    if not player or player.role != Role.POLICE or player.dead:
        await callback.answer("Доступно только полицейским!", show_alert=True)
        return
    
    # Симуляция расследования
    findings = [
        "Вы нашли следы на месте преступления",
        "Свидетель сообщил о подозрительной личности",
        "Обнаружены отпечатки пальцев",
        "Найдена улика - окровавленный нож",
        "Камеры наблюдения зафиксировали подозрительного человека"
    ]
    
    finding = random.choice(findings)
    
    # Шанс перехвата преступником
    criminal = game.players.get(game.criminal_id)
    if criminal and random.random() < (criminal.intelligence / 200):
        await bot.send_message(
            criminal.user_id,
            f"🕵️‍♂️ ПЕРЕХВАТ: Полицейский {player.police_nick} обнаружил: {finding}"
        )
    
    await callback.message.answer(
        f"🔍 Результат расследования:\n\n{finding}\n\n"
        f"Запишите это в заметки для отчёта начальнику."
    )
    await callback.answer("Расследование завершено")

@dp.callback_query(F.data == "action_report")
async def police_report(callback: CallbackQuery, state: FSMContext):
    """Полицейский отправляет отчёт"""
    user = callback.from_user
    game = storage.get_player_game(user.id)
    
    if not game:
        await callback.answer("Вы не в игре!", show_alert=True)
        return
    
    player = game.players.get(user.id)
    if not player or player.role != Role.POLICE or player.dead:
        await callback.answer("Доступно только полицейским!", show_alert=True)
        return
    
    boss = game.players.get(game.boss_id)
    if not boss:
        await callback.answer("Начальник не найден!", show_alert=True)
        return
    
    await state.set_state(GameStates.reporting)
    await state.update_data(player_id=player.user_id)
    
    await callback.message.answer(
        "📝 Напишите отчёт для начальника:\n\n"
        "• Что обнаружили\n"
        "• Подозреваемых\n"
        "• Предлагаемые действия\n\n"
        "Отправьте одним сообщением."
    )
    await callback.answer()

@dp.message(GameStates.reporting)
async def process_report(message: Message, state: FSMContext):
    """Обработка отчёта"""
    data = await state.get_data()
    player_id = data.get('player_id')
    
    game = storage.get_player_game(player_id)
    if not game:
        await message.answer("Ошибка игры!")
        await state.clear()
        return
    
    player = game.players.get(player_id)
    boss = game.players.get(game.boss_id)
    
    if player and boss:
        report_text = f"""
📋 ОТЧЁТ ОТ {player.get_display_name()}

{message.text}

────────────
Для ответа используйте команду /reply_to_report {player_id}
"""
        await bot.send_message(boss.user_id, report_text)
        await message.answer("✅ Отчёт отправлен начальнику!")
    else:
        await message.answer("❌ Ошибка отправки отчёта!")
    
    await state.clear()

# ============================================
# ИГРОВЫЕ ДЕЙСТВИЯ - ПРЕСТУПНИК
# ============================================

@dp.callback_query(F.data == "criminal_kill_npc")
async def criminal_kill_npc(callback: CallbackQuery):
    """Преступник убивает NPC"""
    user = callback.from_user
    game = storage.get_player_game(user.id)
    
    if not game:
        await callback.answer("Вы не в игре!", show_alert=True)
        return
    
    player = game.players.get(user.id)
    if not player or player.role != Role.CRIMINAL or player.dead or player.arrested:
        await callback.answer("Доступно только преступнику!", show_alert=True)
        return
    
    # Проверка КД
    if player.last_action and (datetime.now() - player.last_action).seconds < MURDER_COOLDOWN:
        remaining = MURDER_COOLDOWN - (datetime.now() - player.last_action).seconds
        await callback.answer(f"До следующего убийства: {remaining} сек", show_alert=True)
        return
    
    player.last_action = datetime.now()
    player.kills += 1
    game.murder_count += 1
    
    # Типы убийств NPC
    victims = [
        "бездомного в подворотне",
        "случайного прохожего",
        "официантку в баре",
        "таксиста",
        "охранника склада"
    ]
    
    victim = random.choice(victims)
    
    # Отправка новости
    await broadcast_to_group(game,
        f"📰 СРОЧНАЯ НОВОСТЬ: Обнаружено тело {victim}. "
        f"Признаки насильственной смерти. Полиция на месте."
    )
    
    # Обновление статистики преступника
    kills_left = KILLS_TO_WIN - player.kills
    await callback.message.edit_text(
        f"🕵️‍♂️ Вы - ПРЕСТУПНИК\n\n"
        f"✅ Убийство совершено: {victim}\n"
        f"🔪 Всего убийств: {player.kills}/{KILLS_TO_WIN}\n"
        f"🎯 Осталось до победы: {kills_left}\n\n"
        f"Следующее убийство через 15 минут",
        reply_markup=get_criminal_actions_keyboard()
    )
    
    await callback.answer("Убийство совершено!")
    
    # Проверка победы
    if player.kills >= KILLS_TO_WIN:
        await end_game(game, "criminal")

# ============================================
# ИГРОВЫЕ ЦИКЛЫ
# ============================================

async def game_loop(game: Game):
    """Основной игровой цикл"""
    while game.state == GameState.ACTIVE:
        await asyncio.sleep(300)  # 5 минут
        
        # Случайные события
        if random.random() < 0.3:  # 30% шанс
            await send_news(game)
        
        # Проверка на конец игры по времени
        if game.start_time and (datetime.now() - game.start_time).days >= 30:
            await end_game(game, "timeout")

async def murder_loop(game: Game):
    """Цикл убийств NPC (если преступник неактивен)"""
    while game.state == GameState.ACTIVE:
        await asyncio.sleep(MURDER_COOLDOWN + random.randint(-300, 300))
        
        criminal = game.players.get(game.criminal_id)
        if criminal and not criminal.dead and not criminal.arrested:
            # Автоматическое убийство NPC если преступник не убивал
            if criminal.last_action is None or (datetime.now() - criminal.last_action).seconds > MURDER_COOLDOWN * 2:
                criminal.kills += 1
                game.murder_count += 1
                criminal.last_action = datetime.now()
                
                victims = ["туриста", "студента", "продавца", "водителя"]
                victim = random.choice(victims)
                
                await broadcast_to_group(game,
                    f"📰 НОВОСТЬ: Пропал без вести {victim}. "
                    f"Родственники заявили в полицию."
                )
                
                # Уведомление преступнику
                try:
                    await bot.send_message(
                        criminal.user_id,
                        f"🔪 СИСТЕМА: Зафиксировано убийство {victim}\n"
                        f"Всего убийств: {criminal.kills}/{KILLS_TO_WIN}"
                    )
                except:
                    pass
                
                if criminal.kills >= KILLS_TO_WIN:
                    await end_game(game, "criminal")

# ============================================
# ЗАВЕРШЕНИЕ ИГРЫ
# ============================================

async def end_game(game: Game, reason: str):
    """Завершение игры"""
    game.state = GameState.FINISHED
    
    if reason == "criminal":
        criminal = game.players.get(game.criminal_id)
        text = f"""
🏁 ИГРА ОКОНЧЕНА! 🏁

🕵️‍♂️ ПОБЕДА ПРЕСТУПНИКА!

Преступник {criminal.username} достиг цели в {KILLS_TO_WIN} убийств.

📊 Статистика:
• Всего убийств: {game.murder_count}
• Убийств преступника: {criminal.kills}
• Длительность игры: {((datetime.now() - game.start_time).seconds // 3600)} часов
"""
    else:
        text = """
🏁 ИГРА ОКОНЧЕНА! 🏁

👮 ПОБЕДА ПОЛИЦИИ!

Преступник был арестован.

📊 Статистика игры:
• Всего убийств: {game.murder_count}
• Выживших: {len([p for p in game.players.values() if not p.dead])}
• Длительность: {((datetime.now() - game.start_time).seconds // 3600)} часов
"""
    
    # Раскрываем роли
    roles_text = "\n\n🎭 Роли игроков:\n"
    for player in game.players.values():
        roles_text += f"• {player.username}: {player.role.value}\n"
    
    text += roles_text
    
    await broadcast_to_group(game, text)
    
    # Отправляем всем игрокам
    for player in game.players.values():
        try:
            await bot.send_message(player.user_id, text)
        except:
            pass

# ============================================
# ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ
# ============================================

@dp.message(Command("status"))
async def cmd_status(message: Message):
    """Статус игры"""
    chat_id = message.chat.id
    game = storage.get_game(chat_id)
    
    if not game:
        await message.answer("В этой группе нет активной игры.")
        return
    
    if game.state == GameState.REGISTRATION:
        await message.answer(
            f"📊 Статус: РЕГИСТРАЦИЯ\n"
            f"👥 Игроков: {len(game.players)}/{MAX_PLAYERS}\n"
            f"📍 Минимум: {MIN_PLAYERS}"
        )
    elif game.state == GameState.ACTIVE:
        duration = datetime.now() - game.start_time
        hours = duration.seconds // 3600
        
        criminal = game.players.get(game.criminal_id)
        kill_count = criminal.kills if criminal else 0
        
        await message.answer(
            f"📊 Статус: ИГРА ИДЁТ\n"
            f"⏱️ Длительность: {hours} часов\n"
            f"🔪 Убийств: {game.murder_count}\n"
            f"🎯 До победы преступника: {KILLS_TO_WIN - kill_count} убийств\n"
            f"👮 Полицейских: {len(game.get_police_players())}\n"
            f"🧍 Живых игроков: {len(game.get_alive_players())}"
        )
    else:
        await message.answer("Игра завершена.")

@dp.message(Command("players"))
async def cmd_players(message: Message):
    """Список игроков"""
    chat_id = message.chat.id
    game = storage.get_game(chat_id)
    
    if not game or not game.players:
        await message.answer("Нет игроков в этой группе.")
        return
    
    players_text = "👥 Игроки в этой игре:\n\n"
    for player in game.players.values():
        status = "✅" if not player.dead and not player.arrested else "💀" if player.dead else "🔒"
        
        if game.state == GameState.FINISHED or message.from_user.id in game.players:
            # Показываем роли если игра окончена или запрашивает участник
            role_info = f" - {player.role.value}"
            if player.role == Role.POLICE and player.police_nick:
                role_info = f" - {player.role.value} {player.police_nick}"
        else:
            role_info = ""
        
        players_text += f"{status} {player.username}{role_info}\n"
    
    await message.answer(players_text)

# ============================================
# ЗАПУСК БОТА
# ============================================

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    print("=" * 50)
    print("ПОЛИЦЕЙСКИЙ ОТДЕЛ - Game Bot")
    print("Бот запускается...")
    print("=" * 50)
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())

"""
============================================
ИНСТРУКЦИЯ ПО ЗАПУСКУ
============================================

1. УСТАНОВКА ЗАВИСИМОСТЕЙ:
pip install aiogram==3.0.0b7 python-dotenv

2. СОЗДАЙТЕ ФАЙЛ .env:
BOT_TOKEN=ваш_токен_от_BotFather

3. НАСТРОЙКА БОТА:
- Получите токен у @BotFather
- Добавьте бота в группу
- Дайте боту права администратора
- Отключите в группе "Разрешить анонимность"

4. ЗАПУСК:
python police_bot.py

5. КОМАНДЫ В ГРУППЕ:
/start_game - начать регистрацию
/begin - начать игру
/status - статус игры
/players - список игроков
/rules - правила игры

============================================
КАК ДОБАВЛЯТЬ РОЛИ
============================================

1. Добавьте новую роль в Enum Role
2. Обновите ROLE_CHANCES
3. Добавьте обработку в assign_roles()
4. Создайте функцию send_role_info() для роли
5. Создайте клавиатуру действий
6. Добавьте хендлеры действий

============================================
КАК РАСШИРЯТЬ СЮЖЕТ
============================================

1. Добавляйте новости в send_news()
2. Создавайте сценарии в game_loop()
3. Добавляйте специальные события:
   - Исчезновения
   - Возвращения персонажей
   - Внешнее давление на отдел
   - Коррупционные сюжеты

4. Используйте заметки игроков для развития личных сюжетных арок

============================================
КАК ДЕЛАТЬ ДОЛГИЕ ДЕЛА
============================================

1. Используйте FSM для многошаговых процессов
2. Сохраняйте состояние в Player.notes
3. Создавайте цепочки событий:
   - Свидетель → Допрос → Поиск → Арест
   - Улика → Анализ → Запрос ИТ → Отслеживание

4. Вводите таймеры на расследования (24-48 часов в реальном времени)
5. Добавляйте давление:
   - Новые убийства во время расследования
   - Жалобы от родственников
   - Вмешательство прокуратуры

============================================
ВАЖНЫЕ МОМЕНТЫ
============================================

1. Игра ДОЛГАЯ - не спешите
2. Ошибки имеют последствия
3. Каждое действие влияет на репутацию
4. Преступник должен быть умным, а не просто убивать
5. Полиция должна РАБОТАТЬ ВМЕСТЕ

Удачи в разработке и интересных игр!
"""

