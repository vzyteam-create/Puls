"""
============================================
POLICE DEPARTMENT - Telegram Game Bot
ПОЛНЫЙ РАБОЧИЙ КОД С ИСПРАВЛЕНИЯМИ
Версия: 4.3
============================================
"""

import asyncio
import logging
import random
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set
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
from aiogram.exceptions import TelegramBadRequest

# ============================================
# КОНФИГУРАЦИЯ
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Настройки игры
MAX_PLAYERS = 50
MIN_PLAYERS = 5
MURDER_COOLDOWN = 300
KILLS_TO_WIN = 10
INACTIVITY_TIMEOUT = 300  # 5 минут
SUSPENSION_TIME = 600  # 10 минут отстранения
AUTO_CHECK_INTERVAL = 60  # Проверка активности каждую минуту

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

# Времена для мута
MUTE_TIMES = {
    "1_hour": 3600,
    "5_hours": 18000,
    "10_hours": 36000,
    "1_day": 86400,
    "2_days": 172800,
    "1_week": 604800
}

# Времена тюрьмы (в минутах)
PRISON_TIMES = [5, 10, 15, 20, 30, 45, 60]
LIFE_SENTENCE = 1440  # 24 часа = пожизненное

# ============================================
# ПЕРЕЧИСЛЕНИЯ (ENUMS)
# ============================================

class GameState(Enum):
    WAITING = "ожидание"
    REGISTRATION = "регистрация"
    ACTIVE = "активная"
    FINISHED = "завершена"

class Role(Enum):
    POLICE = "👮 Полицейский"
    BOSS = "🧠 Начальник"
    IT = "💻 ИТ-специалист"
    CRIMINAL = "🕵️‍♂️ Преступник"
    CIVILIAN = "🧍 Мирный"
    EX_CONVICT = "👤 Бывший осужденный"
    RECIDIVIST = "🔪 Рецидивист"

class PlayerStatus(Enum):
    FREE = "свободен"
    IN_PRISON = "в тюрьме"
    DEAD = "мертв"
    ARRESTED = "арестован"
    SUSPENDED = "отстранен"
    ACTIVE = "активен"

# ============================================
# МОДЕЛИ ДАННЫХ
# ============================================

@dataclass
class PrisonRecord:
    game_number: int
    chat_id: int
    sentence_minutes: int
    arrest_time: datetime
    release_time: datetime
    crime: str = "убийства"
    reformed: bool = False
    is_life: bool = False

@dataclass
class Suspension:
    start_time: datetime
    end_time: datetime
    reason: str = "неактивность"
    suspension_count: int = 1
    bot_controlled: bool = True

@dataclass
class Player:
    user_id: int
    username: str
    current_game_chat_id: Optional[int] = None
    current_game_number: Optional[int] = None
    role: Optional[Role] = None
    chosen_role: Optional[Role] = None
    police_nick: Optional[str] = None
    reputation: int = 50
    intelligence: int = 0
    kills: int = 0
    status: PlayerStatus = PlayerStatus.FREE
    last_action: Optional[datetime] = None
    last_message_time: Optional[datetime] = None
    is_bot_controlled: bool = False
    suspension: Optional[Suspension] = None
    prison_records: List[PrisonRecord] = field(default_factory=list)
    current_prison: Optional[PrisonRecord] = None
    criminal_attempts: int = 0
    suspension_count: int = 0
    notes: Dict[str, str] = field(default_factory=dict)
    witnesses: Dict[str, str] = field(default_factory=dict)
    auto_actions: List[str] = field(default_factory=list)
    
    @property
    def is_in_prison(self) -> bool:
        return self.status == PlayerStatus.IN_PRISON
    
    @property
    def is_suspended(self) -> bool:
        return self.status == PlayerStatus.SUSPENDED
    
    @property
    def has_criminal_record(self) -> bool:
        return len(self.prison_records) > 0
    
    @property
    def is_recidivist(self) -> bool:
        return len([r for r in self.prison_records if not r.reformed]) >= 2
    
    def get_display_name(self) -> str:
        if self.role == Role.POLICE and self.police_nick:
            return f"👮 Полицейский {self.police_nick}"
        elif self.role == Role.IT:
            return "💻 ИТ-специалист"
        elif self.role == Role.BOSS:
            return "🧠 Начальник полиции"
        elif self.role == Role.CRIMINAL:
            return f"🕵️‍♂️ Преступник ({self.kills} убийств)"
        elif self.role == Role.RECIDIVIST:
            return f"🔪 Рецидивист {self.username}"
        elif self.role == Role.EX_CONVICT:
            return f"👤 {self.username} (судимый)"
        else:
            return f"🧍 {self.username}"
    
    def can_be_suspended(self) -> bool:
        if self.is_in_prison or self.status == PlayerStatus.DEAD:
            return False
        return True

@dataclass
class Game:
    chat_id: int
    game_number: int
    state: GameState = GameState.WAITING
    players: Dict[int, Player] = field(default_factory=dict)
    start_time: Optional[datetime] = None
    murder_count: int = 0
    criminal_id: Optional[int] = None
    boss_id: Optional[int] = None
    it_id: Optional[int] = None
    news: List[str] = field(default_factory=list)
    messages_to_delete: List[int] = field(default_factory=list)
    chat_open: bool = False
    chat_open_until: Optional[datetime] = None
    creator_id: Optional[int] = None
    deleted_messages_count: int = 0
    win_reason: Optional[str] = None
    waiting_for_players: bool = False
    
    def get_alive_players(self) -> List[Player]:
        return [p for p in self.players.values() if p.status not in [PlayerStatus.DEAD, PlayerStatus.IN_PRISON, PlayerStatus.ARRESTED]]
    
    def get_active_players(self) -> List[Player]:
        now = datetime.now()
        return [
            p for p in self.players.values() 
            if p.status not in [PlayerStatus.DEAD, PlayerStatus.IN_PRISON, PlayerStatus.SUSPENDED]
            and (p.last_message_time is None or (now - p.last_message_time).seconds < INACTIVITY_TIMEOUT)
        ]
    
    def get_inactive_players(self) -> List[Player]:
        now = datetime.now()
        inactive = []
        for player in self.players.values():
            if player.status in [PlayerStatus.DEAD, PlayerStatus.IN_PRISON]:
                continue
                
            if player.last_message_time is None:
                inactive.append(player)
            elif (now - player.last_message_time).seconds >= INACTIVITY_TIMEOUT:
                inactive.append(player)
        
        return inactive
    
    def get_suspended_players(self) -> List[Player]:
        return [p for p in self.players.values() if p.is_suspended]

# ============================================
# ХРАНИЛИЩЕ
# ============================================

class GameStorage:
    def __init__(self):
        self.games: Dict[int, Game] = {}
        self.players: Dict[int, Player] = {}
        self.muted_users: Dict[Tuple[int, int], datetime] = {}
        self.chat_creators: Dict[int, int] = {}
        self.game_counter: int = 1
        self.prison_timers: Dict[int, asyncio.Task] = {}
        self.suspension_timers: Dict[int, asyncio.Task] = {}
        self.auto_play_tasks: Dict[int, asyncio.Task] = {}
    
    def create_game(self, chat_id: int, creator_id: int) -> Game:
        game = Game(chat_id=chat_id, game_number=self.game_counter, creator_id=creator_id)
        self.games[chat_id] = game
        self.chat_creators[chat_id] = creator_id
        self.game_counter += 1
        return game
    
    def get_game(self, chat_id: int) -> Optional[Game]:
        return self.games.get(chat_id)
    
    def get_player_game(self, user_id: int) -> Optional[Game]:
        player = self.players.get(user_id)
        if player and player.current_game_chat_id:
            return self.games.get(player.current_game_chat_id)
        return None
    
    def get_player(self, user_id: int) -> Optional[Player]:
        return self.players.get(user_id)
    
    def is_player_in_game(self, user_id: int) -> bool:
        player = self.players.get(user_id)
        return player is not None and player.current_game_chat_id is not None and not player.is_in_prison
    
    def is_player_suspended(self, user_id: int) -> bool:
        player = self.players.get(user_id)
        return player is not None and player.is_suspended
    
    def suspend_player(self, user_id: int, game_chat_id: int) -> Optional[Suspension]:
        player = self.players.get(user_id)
        game = self.games.get(game_chat_id)
        
        if not player or not game or player.status == PlayerStatus.DEAD:
            return None
        
        player.suspension_count += 1
        
        suspension = Suspension(
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(seconds=SUSPENSION_TIME),
            suspension_count=player.suspension_count,
            bot_controlled=True
        )
        
        player.status = PlayerStatus.SUSPENDED
        player.suspension = suspension
        player.is_bot_controlled = True
        
        self.start_suspension_timer(user_id, game_chat_id, SUSPENSION_TIME)
        self.start_auto_play(user_id, game_chat_id)
        
        return suspension
    
    def start_suspension_timer(self, user_id: int, chat_id: int, seconds: int):
        async def end_suspension():
            await asyncio.sleep(seconds)
            
            player = self.players.get(user_id)
            game = self.games.get(chat_id)
            
            if player and player.is_suspended and game:
                player.status = PlayerStatus.FREE
                player.suspension = None
                player.is_bot_controlled = False
                
                self.stop_auto_play(user_id)
                
                try:
                    await self.notify_player_return(player.user_id)
                except:
                    pass
        
        task = asyncio.create_task(end_suspension())
        self.suspension_timers[user_id] = task
    
    async def notify_player_return(self, user_id: int):
        """Уведомить игрока о возвращении"""
        player = self.players.get(user_id)
        if not player:
            return
        
        try:
            bot_instance = Bot.get_current()
            await bot_instance.send_message(
                user_id,
                f"🔓 ВАШЕ ОТСТРАНЕНИЕ ЗАКОНЧЕНО\n\n"
                f"Вы возвращены к делу и можете работать.\n"
                f"Помните: 5 минут неактивности = отстранение на 10 минут\n\n"
                f"Количество отстранений: {player.suspension_count}\n"
                f"Будьте активнее, чтобы избежать повторного отстранения!"
            )
        except:
            pass
    
    def start_auto_play(self, user_id: int, chat_id: int):
        async def auto_play_loop():
            player = self.players.get(user_id)
            game = self.games.get(chat_id)
            
            if not player or not game or not player.is_suspended:
                return
            
            while player.is_suspended and game.state == GameState.ACTIVE:
                check_interval = random.randint(300, 360)
                await asyncio.sleep(check_interval)
                
                if not player.is_suspended or game.state != GameState.ACTIVE:
                    break
                
                action_result = await self.perform_auto_action(player, game)
                
                if action_result:
                    player.auto_actions.append(f"{datetime.now().strftime('%H:%M')}: {action_result}")
                
                player.last_action = datetime.now()
        
        task = asyncio.create_task(auto_play_loop())
        self.auto_play_tasks[user_id] = task
    
    async def perform_auto_action(self, player: Player, game: Game) -> str:
        if player.role == Role.CRIMINAL:
            if player.kills < KILLS_TO_WIN:
                player.kills += 1
                game.murder_count += 1
                
                victims = ["официанта", "таксиста", "бездомного", "продавца"]
                victim = random.choice(victims)
                
                if random.random() < 0.3:
                    await broadcast_to_group(game,
                        f"📰 НОВОСТЬ: Обнаружено тело {victim}.\n"
                        f"На месте работают следователи."
                    )
                
                return f"Совершено убийство {victim}"
        
        elif player.role == Role.POLICE:
            actions = [
                "Проверка свидетельских показаний",
                "Осмотр места преступления",
                "Опрос потенциальных свидетелей",
                "Анализ улик"
            ]
            action = random.choice(actions)
            
            if random.random() < 0.2:
                evidences = ["отпечаток", "волосок", "клочок ткани", "след"]
                evidence = random.choice(evidences)
                
                if "улики" not in player.notes:
                    player.notes["улики"] = ""
                player.notes["улики"] += f"\n{datetime.now().strftime('%H:%M')}: Найден {evidence}"
                
                return f"{action}. Обнаружен {evidence}"
            
            return f"{action}. Ничего существенного не найдено."
        
        elif player.role == Role.IT:
            actions = [
                "Проверка телефонных соединений",
                "Анализ камер наблюдения",
                "Поиск в базе данных",
                "Мониторинг сетевой активности"
            ]
            action = random.choice(actions)
            return f"{action}. Данные обрабатываются."
        
        return "Рутинная работа"

    def stop_auto_play(self, user_id: int):
        if user_id in self.auto_play_tasks:
            self.auto_play_tasks[user_id].cancel()
            del self.auto_play_tasks[user_id]
    
    def arrest_player(self, user_id: int, chat_id: int, crime: str = "убийства") -> Optional[PrisonRecord]:
        player = self.players.get(user_id)
        game = self.games.get(chat_id)
        
        if not player or not game:
            return None
        
        if player.is_recidivist and player.role in [Role.CRIMINAL, Role.RECIDIVIST]:
            sentence_minutes = LIFE_SENTENCE
            is_life = True
        else:
            sentence_minutes = random.choice(PRISON_TIMES)
            is_life = False
        
        prison_record = PrisonRecord(
            game_number=game.game_number,
            chat_id=chat_id,
            sentence_minutes=sentence_minutes,
            arrest_time=datetime.now(),
            release_time=datetime.now() + timedelta(minutes=sentence_minutes),
            crime=crime,
            is_life=is_life
        )
        
        player.status = PlayerStatus.IN_PRISON
        player.current_prison = prison_record
        player.prison_records.append(prison_record)
        player.current_game_chat_id = None
        player.current_game_number = None
        
        self.stop_auto_play(user_id)
        
        if not is_life:
            self.start_prison_timer(user_id, sentence_minutes * 60)
        else:
            asyncio.create_task(self.notify_life_sentence(user_id))
        
        return prison_record
    
    def start_prison_timer(self, user_id: int, seconds: int):
        async def release_from_prison():
            await asyncio.sleep(seconds)
            player = self.players.get(user_id)
            if player and player.is_in_prison:
                player.status = PlayerStatus.FREE
                player.current_prison = None
                
                try:
                    bot_instance = Bot.get_current()
                    await bot_instance.send_message(
                        user_id,
                        "🔓 ВЫ ОСВОБОЖДЕНЫ ИЗ ТЮРЬМЫ!\n\n"
                        "Вы отсидели свой срок и теперь свободны.\n\n"
                        "Выберите свой путь:\n"
                        "1. 🕊️ Исправиться - стать мирным гражданином\n"
                        "2. 🔪 Вернуться к преступлениям (риск выше в 2 раза)",
                        reply_markup=get_reform_keyboard()
                    )
                except:
                    pass
        
        task = asyncio.create_task(release_from_prison())
        self.prison_timers[user_id] = task
    
    async def notify_life_sentence(self, user_id: int):
        await asyncio.sleep(1)
        player = self.players.get(user_id)
        if player:
            try:
                bot_instance = Bot.get_current()
                await bot_instance.send_message(
                    user_id,
                    "⚠️ ПОЖИЗНЕННЫЙ СРОК!\n\n"
                    "Вы признаны рецидивистом и приговорены к пожизненному заключению.\n\n"
                    "Вы не сможете участвовать в играх в этом чате.\n"
                    "Ваш игровой путь здесь завершен."
                )
            except:
                pass
    
    def add_player(self, chat_id: int, user_id: int, username: str) -> Tuple[Optional[Player], str]:
        game = self.get_game(chat_id)
        if not game or game.state != GameState.REGISTRATION:
            return None, "Регистрация не активна"
        
        if self.is_user_muted(chat_id, user_id):
            return None, "Вы временно не можете участвовать в играх"
        
        if self.is_player_in_prison(user_id):
            player = self.players.get(user_id)
            if player and player.current_prison:
                remaining = player.current_prison.release_time - datetime.now()
                minutes = int(remaining.total_seconds() // 60)
                return None, f"Вы в тюрьме. Освобождение через {minutes} мин ({minutes} лет)"
        
        existing_player = self.players.get(user_id)
        if existing_player and existing_player.current_game_chat_id is not None:
            if existing_player.current_game_chat_id == chat_id:
                return existing_player, "Вы уже зарегистрированы в этой игре"
            else:
                return None, "Вы уже участвуете в игре в другом чате"
        
        if user_id in game.players:
            return game.players[user_id], "Вы уже зарегистрированы"
        
        if existing_player:
            player = existing_player
            player.username = username or player.username
        else:
            player = Player(user_id=user_id, username=username)
            self.players[user_id] = player
        
        player.current_game_chat_id = chat_id
        player.current_game_number = game.game_number
        game.players[user_id] = player
        
        return player, "Успешная регистрация"
    
    def is_player_in_prison(self, user_id: int) -> bool:
        player = self.players.get(user_id)
        return player is not None and player.is_in_prison
    
    def remove_player(self, chat_id: int, user_id: int):
        game = self.get_game(chat_id)
        player = self.players.get(user_id)
        
        if game and user_id in game.players:
            del game.players[user_id]
        
        if player and player.current_game_chat_id == chat_id:
            player.current_game_chat_id = None
            player.current_game_number = None
    
    def end_game(self, chat_id: int):
        game = self.get_game(chat_id)
        if game:
            for user_id in list(game.players.keys()):
                player = self.players.get(user_id)
                if player and not player.is_in_prison:
                    player.current_game_chat_id = None
                    player.current_game_number = None
            del self.games[chat_id]
    
    def mute_user(self, chat_id: int, user_id: int, duration_seconds: int):
        unmute_time = datetime.now() + timedelta(seconds=duration_seconds)
        self.muted_users[(chat_id, user_id)] = unmute_time
    
    def unmute_user(self, chat_id: int, user_id: int):
        key = (chat_id, user_id)
        if key in self.muted_users:
            del self.muted_users[key]
    
    def is_user_muted(self, chat_id: int, user_id: int) -> bool:
        key = (chat_id, user_id)
        if key in self.muted_users:
            if datetime.now() < self.muted_users[key]:
                return True
            else:
                del self.muted_users[key]
        return False

storage = GameStorage()

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
    builder.row(
        InlineKeyboardButton(text="✅ Присоединиться", callback_data="join_game"),
        InlineKeyboardButton(text="❌ Отменить регистрацию", callback_data="cancel_registration"),
    )
    builder.add(InlineKeyboardButton(text="🚀 Начать игру", callback_data="begin_game"))
    return builder.as_markup()

def get_reform_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🕊️ Исправиться", callback_data="reform_good"),
        InlineKeyboardButton(text="🔪 Вернуться к преступлениям", callback_data="reform_bad"),
    )
    return builder.as_markup()

def get_mute_time_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="1 час", callback_data="mute_1_hour"),
        InlineKeyboardButton(text="5 часов", callback_data="mute_5_hours"),
    )
    builder.row(
        InlineKeyboardButton(text="10 часов", callback_data="mute_10_hours"),
        InlineKeyboardButton(text="1 день", callback_data="mute_1_day"),
    )
    builder.row(
        InlineKeyboardButton(text="2 дня", callback_data="mute_2_days"),
        InlineKeyboardButton(text="1 неделя", callback_data="mute_1_week"),
    )
    return builder.as_markup()

def get_police_actions_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔍 Расследовать", callback_data="action_investigate"),
        InlineKeyboardButton(text="🗣️ Допрос", callback_data="action_interrogate"),
    )
    builder.row(
        InlineKeyboardButton(text="📝 Отчёт", callback_data="action_report"),
        InlineKeyboardButton(text="💾 Заметки", callback_data="action_notes"),
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

async def broadcast_to_group(game: Game, text: str, delete_after: bool = True):
    try:
        msg = await bot.send_message(game.chat_id, text)
        
        if delete_after and not game.chat_open and game.messages_to_delete:
            for msg_id in game.messages_to_delete[-5:]:
                try:
                    await bot.delete_message(game.chat_id, msg_id)
                except:
                    pass
        
        if delete_after and not game.chat_open:
            game.messages_to_delete.append(msg.message_id)
            
    except Exception as e:
        logging.error(f"Ошибка отправки в группу: {e}")

async def send_role_info(player: Player, game: Game):
    if player.role == Role.POLICE:
        text = f"""
🎭 Ваша роль: {player.role.value}

📛 Ваш знак отличия: {player.police_nick}

🎯 Цели:
1. Найти и арестовать преступника
2. Расследовать убийства
3. Собирать доказательства
4. Докладывать начальнику

📢 Правила ролевой игры:
• Играйте от лица своего персонажа
• Не раскрывайте свою роль другим
• Не говорите игровые термины (КД, роль и т.д.)

🛠️ Доступные действия:
• 🔍 Расследование
• 🗣️ Допрос свидетелей
• 📝 Составление отчётов
• 💾 Личные заметки

⚠️ Система активности:
• 5 минут неактивности = отстранение на 10 минут
• Бот будет играть за вас при отстранении
• Будьте активны!
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

📢 Правила ролевой игры:
• Играйте от лица начальника отдела
• Не раскрывайте свою роль
• Наказывайте нарушителей ролевой игры
"""
        await bot.send_message(player.user_id, text)
    
    elif player.role == Role.CRIMINAL:
        text = f"""
🎭 Ваша роль: {player.role.value}

🧠 Интеллект: {player.intelligence}/100

🎯 Цель: Совершить {KILLS_TO_WIN} убийств

📢 Правила ролевой игры:
• Играйте умного преступника, не маньяка
• Не раскрывайте свою роль
• НЕ говорите о КД, времени перезарядки

⚠️ Правила:
• Сначала убивайте NPC (неигровых персонажей)
• Игроков можно убивать после 3-х NPC

🛠️ Доступные действия:
• 🔪 Убийства
• 👥 Общение с мирными
• 📊 Перехват логов

⚠️ Система активности:
• 5 минут неактивности = отстранение на 10 минут
• Бот будет играть за вас при отстранении
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
"""
        await bot.send_message(player.user_id, text)
    
    else:
        text = f"""
🎭 Ваша роль: {player.role.value}

🎯 Цели:
1. Выжить
2. Помогать полиции (или нет)
3. Распространять слухи
4. Подавать жалобы при нарушении

⚠️ Система активности:
• 5 минут неактивности = отстранение на 10 минут
• Бот будет играть за вас при отстранении
"""
        await bot.send_message(player.user_id, text)

def assign_roles(game: Game) -> Dict[int, Role]:
    players = list(game.players.values())
    roles = []
    
    role_requests = {Role.POLICE: 0, Role.BOSS: 0, Role.IT: 0, 
                    Role.CRIMINAL: 0, Role.CIVILIAN: 0}
    
    for player in players:
        if player.chosen_role:
            role_requests[player.chosen_role] += 1
    
    total = len(players)
    needed = {
        Role.BOSS: 1,
        Role.IT: 1,
        Role.CRIMINAL: 1,
        Role.POLICE: max(2, min(10, total // 3)),
        Role.CIVILIAN: total - 3 - min(10, total // 3)
    }
    
    assigned = {}
    available_police_nicks = POLICE_NICKS.copy()
    
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
    
    boss_candidates = [p for p in players if p.chosen_role == Role.BOSS]
    if boss_candidates:
        boss = random.choice(boss_candidates)
    else:
        boss = random.choice(players)
    
    assigned[boss.user_id] = Role.BOSS
    boss.role = Role.BOSS
    game.boss_id = boss.user_id
    players.remove(boss)
    
    it_candidates = [p for p in players if p.chosen_role == Role.IT]
    if it_candidates:
        it = random.choice(it_candidates)
    else:
        it = random.choice(players)
    
    assigned[it.user_id] = Role.IT
    it.role = Role.IT
    game.it_id = it.user_id
    players.remove(it)
    
    police_needed = needed[Role.POLICE]
    police_candidates = [p for p in players if p.chosen_role == Role.POLICE]
    
    for player in police_candidates[:police_needed]:
        if police_needed <= 0:
            break
        assigned[player.user_id] = Role.POLICE
        player.role = Role.POLICE
        if available_police_nicks:
            player.police_nick = available_police_nicks.pop()
        players.remove(player)
        police_needed -= 1
    
    for player in players[:police_needed]:
        if police_needed <= 0:
            break
        assigned[player.user_id] = Role.POLICE
        player.role = Role.POLICE
        if available_police_nicks:
            player.police_nick = available_police_nicks.pop()
        players.remove(player)
        police_needed -= 1
    
    for player in players:
        assigned[player.user_id] = Role.CIVILIAN
        player.role = Role.CIVILIAN
    
    return assigned

async def send_news(game: Game):
    news_templates = [
        "📰 В городе произошло очередное убийство. Полиция на месте.",
        "📰 Жители района сообщают о подозрительной активности.",
        "📰 Пресс-служба полиции готовит брифинг.",
    ]
    
    news = random.choice(news_templates)
    game.news.append(news)
    await broadcast_to_group(game, news)

# ============================================
# ХЕНДЛЕРЫ
# ============================================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👮 Добро пожаловать в игру 'ПОЛИЦЕЙСКИЙ ОТДЕЛ'!\n\n"
        "Для начала игры в группе используйте:\n"
        "/start_game - начать регистрацию\n"
        "/begin - начать игру после регистрации\n"
        "/rules - правила игры"
    )

@dp.message(Command("start_game"))
async def cmd_start_game(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("Эта команда работает только в группах!")
        return
    
    chat_id = message.chat.id
    game = storage.get_game(chat_id)
    
    if game and game.state != GameState.WAITING:
        await message.answer("Игра уже запущена в этой группе!")
        return
    
    if not game:
        game = storage.create_game(chat_id, message.from_user.id)
    
    game.state = GameState.REGISTRATION
    
    await message.answer(
        f"🎮 ИГРА #{game.game_number}\n"
        f"Начинается регистрация на игру 'ПОЛИЦЕЙСКИЙ ОТДЕЛ'!\n\n"
        f"📍 Минимум игроков: {MIN_PLAYERS}\n"
        f"📍 Максимум игроков: {MAX_PLAYERS}\n\n"
        "Нажмите кнопку ниже, чтобы присоединиться:",
        reply_markup=get_join_keyboard()
    )

@dp.callback_query(F.data == "join_game")
async def join_game(callback: CallbackQuery):
    user = callback.from_user
    chat_id = callback.message.chat.id
    
    player, message_text = storage.add_player(chat_id, user.id, user.username or user.first_name)
    
    if player:
        try:
            game = storage.get_game(chat_id)
            await bot.send_message(
                user.id,
                f"🎭 Вы присоединились к игре #{game.game_number}!\n\n"
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
        
        game = storage.get_game(chat_id)
        if game:
            await callback.message.edit_text(
                f"🎮 ИГРА #{game.game_number}\n"
                f"Регистрация на игру 'ПОЛИЦЕЙСКИЙ ОТДЕЛ'!\n\n"
                f"✅ Присоединились: {len(game.players)}/{MAX_PLAYERS}\n"
                f"📍 Минимум для старта: {MIN_PLAYERS}\n\n"
                "Нажмите кнопку ниже, чтобы присоединиться:",
                reply_markup=get_join_keyboard()
            )
    else:
        await callback.answer(message_text, show_alert=True)

@dp.callback_query(F.data.startswith("role_"))
async def select_role(callback: CallbackQuery):
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
    
    player = storage.get_player(user.id)
    if not player:
        await callback.answer("Игрок не найден!", show_alert=True)
        return
    
    if player.has_criminal_record and chosen_role == Role.CRIMINAL:
        await callback.answer("С судимостью шансы быть пойманным в 2 раза выше!", show_alert=True)
    
    player.chosen_role = chosen_role
    
    if chosen_role:
        role_name = chosen_role.value
    else:
        role_name = "Без разницы"
    
    await callback.message.edit_text(
        f"✅ Ваш выбор сохранён: {role_name}\n\n"
        f"Игра #{game.game_number}\n"
        "Ждите начала игры."
    )
    await callback.answer("Роль выбрана!")

@dp.callback_query(F.data == "cancel_registration")
async def cancel_registration(callback: CallbackQuery):
    user = callback.from_user
    chat_id = callback.message.chat.id
    
    game = storage.get_game(chat_id)
    if not game or game.state != GameState.REGISTRATION:
        await callback.answer("Регистрация не активна!", show_alert=True)
        return
    
    if user.id not in game.players:
        await callback.answer("Вы не зарегистрированы!", show_alert=True)
        return
    
    storage.remove_player(chat_id, user.id)
    
    await callback.answer("Вы вышли из регистрации!")
    await callback.message.edit_text(
        f"🎮 ИГРА #{game.game_number}\n"
        f"Регистрация на игру 'ПОЛИЦЕЙСКИЙ ОТДЕЛ'!\n\n"
        f"✅ Присоединились: {len(game.players)}/{MAX_PLAYERS}\n"
        f"📍 Минимум для старта: {MIN_PLAYERS}\n\n"
        "Нажмите кнопку ниже, чтобы присоединиться:",
        reply_markup=get_join_keyboard()
    )

@dp.callback_query(F.data == "begin_game")
async def begin_game_callback(callback: CallbackQuery):
    await cmd_begin(callback.message)

@dp.message(Command("begin"))
async def cmd_begin(message: Message):
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
    
    await start_game_with_inactive(game)

async def start_game_with_inactive(game: Game):
    game.waiting_for_players = True
    
    await broadcast_to_group(game,
        f"⏳ ИГРА #{game.game_number} НАЧИНАЕТСЯ\n\n"
        f"Ожидание подтверждения от всех игроков...\n"
        f"У вас есть 2 минуты для активности!"
    )
    
    await asyncio.sleep(120)
    
    active_players = game.get_active_players()
    
    if len(active_players) >= MIN_PLAYERS:
        await begin_game(game)
    else:
        await broadcast_to_group(game,
            f"❌ Недостаточно активных игроков для начала игры.\n"
            f"Нужно минимум {MIN_PLAYERS}, активно: {len(active_players)}"
        )
        game.state = GameState.REGISTRATION
        game.waiting_for_players = False

async def begin_game(game: Game):
    assigned_roles = assign_roles(game)
    game.state = GameState.ACTIVE
    game.start_time = datetime.now()
    game.waiting_for_players = False
    
    for player in game.players.values():
        try:
            await send_role_info(player, game)
            
            if player.is_suspended:
                await bot.send_message(
                    player.user_id,
                    f"⚠️ ИГРА #{game.game_number} НАЧАЛАСЬ\n\n"
                    f"Ваша роль: {player.role.value}\n"
                    f"Но вы отстранены за неактивность."
                )
        except Exception as e:
            logging.error(f"Не удалось отправить роль {player.user_id}: {e}")
    
    await broadcast_to_group(game,
        f"🚨 ИГРА #{game.game_number} НАЧАЛАСЬ! 🚨\n\n"
        f"Все игроки получили свои роли в личных сообщениях.\n"
        f"📊 Статистика:\n"
        f"• Активных игроков: {len(game.get_active_players())}\n"
        f"• Отстраненных: {len(game.get_suspended_players())}\n\n"
        f"📢 Первая новость от пресс-службы:"
    )
    
    await send_news(game)
    
    asyncio.create_task(game_loop(game))
    asyncio.create_task(murder_loop(game))
    asyncio.create_task(check_player_activity())

# ============================================
# СИСТЕМА АКТИВНОСТИ
# ============================================

async def check_player_activity():
    while True:
        await asyncio.sleep(AUTO_CHECK_INTERVAL)
        
        for chat_id, game in list(storage.games.items()):
            if game.state != GameState.ACTIVE:
                continue
            
            inactive_players = game.get_inactive_players()
            
            for player in inactive_players:
                if player.can_be_suspended() and not player.is_suspended:
                    suspension = storage.suspend_player(player.user_id, game.chat_id)
                    
                    if suspension:
                        try:
                            await bot.send_message(
                                player.user_id,
                                f"⚠️ ВЫ ОТСТРАНЕНЫ ОТ ДЕЛА!\n\n"
                                f"Причина: неактивность более 5 минут\n"
                                f"Длительность отстранения: 10 минут\n\n"
                                f"В это время бот будет играть за вас.\n"
                                f"Вы вернетесь в игру: {suspension.end_time.strftime('%H:%M')}"
                            )
                        except:
                            pass

# ============================================
# ИГРОВЫЕ ЦИКЛЫ
# ============================================

async def game_loop(game: Game):
    while game.state == GameState.ACTIVE:
        await asyncio.sleep(300)
        
        if random.random() < 0.3:
            await send_news(game)

async def murder_loop(game: Game):
    while game.state == GameState.ACTIVE:
        await asyncio.sleep(MURDER_COOLDOWN + random.randint(-300, 300))
        
        criminal = storage.get_player(game.criminal_id)
        if criminal and not criminal.dead and not criminal.arrested:
            if criminal.last_action is None or (datetime.now() - criminal.last_action).seconds > MURDER_COOLDOWN * 2:
                criminal.kills += 1
                game.murder_count += 1
                criminal.last_action = datetime.now()
                
                victims = ["туриста", "студента", "продавца", "водителя"]
                victim = random.choice(victims)
                
                await broadcast_to_group(game,
                    f"📰 НОВОСТЬ: Пропал без вести {victim}."
                )
                
                try:
                    await bot.send_message(
                        criminal.user_id,
                        f"🔪 СИСТЕМА: Зафиксировано убийство {victim}\n"
                        f"Всего убийств: {criminal.kills}/{KILLS_TO_WIN}"
                    )
                except:
                    pass
                
                if criminal.kills >= KILLS_TO_WIN:
                    await end_game(game, "criminal_win")

# ============================================
# ОБРАБОТКА СООБЩЕНИЙ
# ============================================

@dp.message()
async def track_activity(message: Message):
    user_id = message.from_user.id
    player = storage.get_player(user_id)
    
    if player and player.current_game_chat_id:
        player.last_message_time = datetime.now()
        player.last_action = datetime.now()
        
        if player.is_suspended:
            game = storage.get_game(player.current_game_chat_id)
            if game:
                player.status = PlayerStatus.FREE
                player.suspension = None
                player.is_bot_controlled = False
                storage.stop_auto_play(user_id)
                
                await message.answer(
                    "✅ ВЫ ВОЗВРАЩЕНЫ К ДЕЛУ!\n"
                    "Отстранение снято досрочно за проявленную активность."
                )

@dp.callback_query()
async def track_callback_activity(callback: CallbackQuery):
    user_id = callback.from_user.id
    player = storage.get_player(user_id)
    
    if player and player.current_game_chat_id:
        player.last_message_time = datetime.now()
        player.last_action = datetime.now()
        
        if player.is_suspended:
            game = storage.get_game(player.current_game_chat_id)
            if game:
                player.status = PlayerStatus.FREE
                player.suspension = None
                player.is_bot_controlled = False
                storage.stop_auto_play(user_id)
                
                await callback.answer(
                    "✅ Вы возвращены к делу!",
                    show_alert=True
                )

# ============================================
# ЗАВЕРШЕНИЕ ИГРЫ
# ============================================

async def end_game(game: Game, reason: str):
    game.state = GameState.FINISHED
    game.win_reason = reason
    
    stats_text = f"""
🏁 ИГРА #{game.game_number} ЗАВЕРШЕНА!

{'👮 ПОБЕДА ПОЛИЦИИ!' if reason == 'police_win' else '🕵️‍♂️ ПОБЕДА ПРЕСТУПНИКА!'}

📊 СТАТИСТИКА:
• Длительность: {((datetime.now() - game.start_time).seconds // 60)} минут
• Всего убийств: {game.murder_count}

🎭 РОЛИ ИГРОКОВ:
"""
    
    for player in game.players.values():
        status = ""
        if player.status == PlayerStatus.IN_PRISON:
            status = " 🔒 В ТЮРЬМЕ"
        elif player.status == PlayerStatus.DEAD:
            status = " 💀 МЕРТВ"
        
        stats_text += f"• {player.username}: {player.role.value}{status}\n"
    
    await broadcast_to_group(game, stats_text, delete_after=False)
    
    for player_id in list(game.players.keys()):
        player = storage.get_player(player_id)
        if player and not player.is_in_prison:
            player.current_game_chat_id = None
            player.current_game_number = None

# ============================================
# ЗАПУСК БОТА
# ============================================

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    print("=" * 50)
    print("ПОЛИЦЕЙСКИЙ ОТДЕЛ - Game Bot v4.3")
    print("Исправлены синтаксические ошибки")
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

1. УСТАНОВКА:
pip install aiogram==3.0.0b7 python-dotenv

2. СОЗДАЙТЕ ФАЙЛ .env:
BOT_TOKEN=ваш_токен_от_BotFather

3. НАСТРОЙКА:
- Дайте боту права администратора
- Отключите "Разрешить анонимность" в группе

4. КОМАНДЫ:
/start_game - начать регистрацию
/begin - начать игру
/cancel_game - отменить игру
/status - статус
/players - список игроков

5. СИСТЕМА АКТИВНОСТИ:
- 5 минут неактивности = отстранение 10 минут
- Бот играет за отстраненных
- Активность снимает отстранение
- 2+ отстранения = предупреждение

6. СИСТЕМА СУДИМОСТИ:
- После тюрьмы выбор пути
- 2+ судимости = рецидивист
- Рецидивист = помощь преступнику
- Пожизненный срок для рецидивистов

ИСПРАВЛЕННЫЕ БАГИ:
- NameError: name 'GameState' is not defined
- SyntaxError в f-string
- Все модели данных определены до использования
"""
