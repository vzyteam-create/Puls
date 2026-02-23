import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, ChatMemberHandler
from telegram.constants import ParseMode
from datetime import datetime, timedelta
import asyncio
import os

TOKEN = "8533732699:AAHpYvVjmyAsTb6wvg-i5gaj8MhZ66kSAAo"
ADMIN_IDS = [6708209142, 8475965198]

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

admin_names = {}
user_requests = {}
request_counter = 0
support_chats = {}
group_welcome_settings = {}
group_goodbye_settings = {}
pending_group_settings = {}
group_admins_cache = {}

bot_clones = {}
clone_creation_sessions = {}
technical_breaks = {}
tech_break_messages = {}
bot_owners = {}
accepted_rules = {}
pending_requests = {}

async def is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    try:
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ['administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка проверки админа: {e}")
        return False

def get_new_request_id():
    global request_counter
    request_counter += 1
    return f"REQ-{request_counter:06d}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if user.id in technical_breaks and technical_breaks[user.id]:
        await update.message.reply_text(tech_break_messages.get(user.id, "🔧 В боте сейчас технические работы. Приходите позже!"))
        return
    
    if chat.type in ['group', 'supergroup']:
        await update.message.reply_text(
            f"👋 Привет, {user.first_name}!\n\nЯ бот поддержки Puls. Чтобы связаться с поддержкой, напишите мне в личные сообщения: @{context.bot.username}"
        )
        return
    
    if user.id in ADMIN_IDS:
        if user.id not in admin_names:
            await update.message.reply_text(
                "👋 Добро пожаловать в систему поддержки Puls!\n\nПожалуйста, введите ваше имя (например: Иван З.):"
            )
            context.user_data['awaiting_name'] = True
        else:
            await show_admin_menu(update, context)
    else:
        if user.id not in accepted_rules:
            await show_rules(update, context)
        else:
            await show_user_menu(update, context)

async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("✅ Я согласен с правилами", callback_data="accept_rules")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    rules_text = (
        "📋 Правила обращения в поддержку Puls:\n\n"
        "1. Одно обращение - одна тема\n"
        "2. Запрещены оскорбления и нецензурная лексика\n"
        "3. Фото не более 2 штук\n"
        "4. Видео не более 1 штуки\n"
        "5. Нельзя отправлять фото и видео вместе\n"
        "6. Название обращения от 5 до 20 символов\n"
        "7. Описание от 10 до 200 символов\n\n"
        "Нажимая 'Я согласен' вы принимаете эти правила"
    )
    
    await update.message.reply_text(rules_text, reply_markup=reply_markup)

async def show_user_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📝 Создать обращение", callback_data="create_request")],
        [InlineKeyboardButton("📊 Статус обращения", callback_data="check_status")],
        [InlineKeyboardButton("ℹ️ Правила", callback_data="show_rules")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 {update.effective_user.first_name}, выберите действие:",
        reply_markup=reply_markup
    )

async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📨 Активные чаты", callback_data="admin_active_chats")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("🤖 Управление клонами", callback_data="admin_clones")],
        [InlineKeyboardButton("🔧 Технический перерыв", callback_data="admin_tech_break")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👨‍💼 Панель администратора\n\nДобро пожаловать, {admin_names.get(update.effective_user.id, 'Администратор')}!",
        reply_markup=reply_markup
    )

async def create_clone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав для создания клонов")
        return
    
    clone_creation_sessions[user.id] = {
        'status': 'awaiting_token',
        'expires': datetime.now() + timedelta(minutes=10)
    }
    
    await update.message.reply_text(
        "🤖 Создание клона бота\n\n"
        "Отправьте токен нового бота в течение 10 минут:\n"
        "(можно получить у @BotFather)"
    )
    
    asyncio.create_task(check_clone_creation_timeout(user.id, context))

async def check_clone_creation_timeout(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(600)
    if user_id in clone_creation_sessions and clone_creation_sessions[user_id]['status'] == 'awaiting_token':
        del clone_creation_sessions[user_id]
        try:
            await context.bot.send_message(
                user_id,
                "⏰ Время на отправку токена истекло. Создание клона отменено."
            )
        except:
            pass

async def handle_clone_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    token = update.message.text.strip()
    
    if user.id not in clone_creation_sessions or clone_creation_sessions[user.id]['status'] != 'awaiting_token':
        return
    
    if datetime.now() > clone_creation_sessions[user.id]['expires']:
        del clone_creation_sessions[user.id]
        await update.message.reply_text("⏰ Время истекло. Начните создание клона заново.")
        return
    
    clone_creation_sessions[user.id]['token'] = token
    clone_creation_sessions[user.id]['status'] = 'awaiting_admins'
    
    await update.message.reply_text(
        "✅ Токен принят!\n\n"
        "Теперь отправьте ID администраторов поддержки через запятую\n"
        "(например: 123456789, 987654321):"
    )

async def handle_clone_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    admins_text = update.message.text.strip()
    
    if user.id not in clone_creation_sessions or clone_creation_sessions[user.id]['status'] != 'awaiting_admins':
        return
    
    try:
        admin_ids = [int(x.strip()) for x in admins_text.split(',')]
        
        clone_id = f"clone_{len(bot_clones) + 1}"
        bot_clones[clone_id] = {
            'token': clone_creation_sessions[user.id]['token'],
            'admin_ids': admin_ids,
            'owner_id': user.id,
            'tech_break': False,
            'tech_message': "🔧 В боте сейчас технические работы. Приходите позже!",
            'created_at': datetime.now().strftime("%d.%m.%Y %H:%M"),
            'status': 'active'
        }
        
        bot_owners[clone_id] = user.id
        
        del clone_creation_sessions[user.id]
        
        await update.message.reply_text(
            f"✅ Клон бота успешно создан!\n\n"
            f"ID клона: {clone_id}\n"
            f"Администраторы: {', '.join(map(str, admin_ids))}\n\n"
            f"Теперь вы можете управлять клоном через меню администратора"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}. Попробуйте снова.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not (update.message.text or update.message.photo or update.message.video):
        return
    
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type in ['group', 'supergroup']:
        return
    
    if user.id in ADMIN_IDS:
        if context.user_data.get('awaiting_name'):
            admin_names[user.id] = update.message.text
            context.user_data['awaiting_name'] = False
            await update.message.reply_text(f"✅ Принято, {update.message.text}! Теперь вы в системе поддержки.")
            await show_admin_menu(update, context)
            return
        
        if context.user_data.get('replying_to'):
            request_id = context.user_data['replying_to']
            if request_id in user_requests:
                user_id = user_requests[request_id]['user_id']
                support_chats[user_id] = {'request_id': request_id, 'admin_id': user.id}
                
                await context.bot.send_message(
                    user_id,
                    f"💬 Ответ от поддержки ({admin_names.get(user.id, 'Оператор')}):\n\n{update.message.text}"
                )
                await update.message.reply_text("✅ Ответ отправлен пользователю!")
                
                context.user_data['replying_to'] = None
            return
        
        if update.message.text and update.message.text.startswith('/reply'):
            try:
                request_id = update.message.text.split()[1]
                if request_id in user_requests:
                    context.user_data['replying_to'] = request_id
                    await update.message.reply_text("✍️ Введите ваш ответ:")
                else:
                    await update.message.reply_text("❌ Запрос не найден")
            except:
                await update.message.reply_text("❌ Используйте: /reply REQ-000001")
            return
        
        if context.user_data.get('awaiting_tech_message'):
            tech_message = update.message.text
            technical_breaks[user.id] = True
            tech_break_messages[user.id] = tech_message
            context.user_data['awaiting_tech_message'] = False
            await update.message.reply_text(f"✅ Технический перерыв включен. Сообщение: {tech_message}")
            return
        
        return
    
    if user.id in technical_breaks and technical_breaks[user.id]:
        await update.message.reply_text(tech_break_messages.get(user.id, "🔧 В боте сейчас технические работы. Приходите позже!"))
        return
    
    if user.id not in accepted_rules:
        await show_rules(update, context)
        return
    
    if user.id in pending_requests:
        request_data = pending_requests[user.id]
        
        if request_data['stage'] == 'awaiting_title':
            title = update.message.text
            if 5 <= len(title) <= 20:
                request_data['title'] = title
                request_data['stage'] = 'awaiting_description'
                await update.message.reply_text("✅ Название принято! Теперь напишите описание обращения (от 10 до 200 символов):")
            else:
                await update.message.reply_text("❌ Название должно быть от 5 до 20 символов. Попробуйте снова:")
        
        elif request_data['stage'] == 'awaiting_description':
            description = update.message.text
            if 10 <= len(description) <= 200:
                request_id = get_new_request_id()
                request_data['description'] = description
                request_data['request_id'] = request_id
                request_data['stage'] = 'awaiting_media'
                
                user_requests[request_id] = {
                    'user_id': user.id,
                    'username': user.username,
                    'first_name': user.first_name,
                    'title': request_data['title'],
                    'description': description,
                    'status': 'new',
                    'date': datetime.now().strftime("%d.%m.%Y %H:%M"),
                    'media': []
                }
                
                keyboard = [
                    [InlineKeyboardButton("✅ Отправить без медиа", callback_data=f"submit_request_{request_id}")],
                    [InlineKeyboardButton("❌ Отмена", callback_data="cancel_request")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    f"📝 Описание принято!\n\n"
                    f"Теперь вы можете прикрепить медиа:\n"
                    f"• Фото: максимум 2\n"
                    f"• Видео: максимум 1\n"
                    f"• Нельзя фото и видео вместе\n\n"
                    f"Или отправьте обращение сразу:",
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text("❌ Описание должно быть от 10 до 200 символов. Попробуйте снова:")
        
        elif request_data['stage'] == 'awaiting_media':
            await handle_request_media(update, context, request_data)
    
    else:
        await show_user_menu(update, context)

async def handle_request_media(update: Update, context: ContextTypes.DEFAULT_TYPE, request_data: dict):
    user = update.effective_user
    request_id = request_data['request_id']
    
    if update.message.photo:
        if request_data.get('has_video'):
            await update.message.reply_text("❌ Нельзя добавлять фото, если уже есть видео")
            return
        
        if len(request_data.get('photos', [])) >= 2:
            await update.message.reply_text("❌ Максимум 2 фото")
            return
        
        if 'photos' not in request_data:
            request_data['photos'] = []
        
        photo = update.message.photo[-1]
        request_data['photos'].append(photo.file_id)
        user_requests[request_id]['media'].append({'type': 'photo', 'file_id': photo.file_id})
        
        remaining = 2 - len(request_data['photos'])
        await update.message.reply_text(f"✅ Фото добавлено. Осталось мест: {remaining}")
    
    elif update.message.video:
        if request_data.get('has_photo'):
            await update.message.reply_text("❌ Нельзя добавлять видео, если уже есть фото")
            return
        
        if request_data.get('has_video'):
            await update.message.reply_text("❌ Только 1 видео")
            return
        
        video = update.message.video
        if video.duration > 60:
            await update.message.reply_text("❌ Видео должно быть не длиннее 60 секунд")
            return
        
        request_data['has_video'] = True
        request_data['video'] = video.file_id
        user_requests[request_id]['media'].append({'type': 'video', 'file_id': video.file_id})
        
        await update.message.reply_text("✅ Видео добавлено")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    data = query.data
    
    if data == "accept_rules":
        accepted_rules[user.id] = True
        context.user_data['creating_request'] = {
            'stage': 'awaiting_title'
        }
        pending_requests[user.id] = {
            'stage': 'awaiting_title'
        }
        await query.message.edit_text("✅ Правила приняты!\n\nТеперь введите название обращения (от 5 до 20 символов):")
    
    elif data == "create_request":
        if user.id not in accepted_rules:
            await show_rules_callback(query, context)
        else:
            context.user_data['creating_request'] = {
                'stage': 'awaiting_title'
            }
            pending_requests[user.id] = {
                'stage': 'awaiting_title'
            }
            await query.message.edit_text("📝 Введите название обращения (от 5 до 20 символов):")
    
    elif data == "check_status":
        user_reqs = [(rid, req) for rid, req in user_requests.items() if req['user_id'] == user.id]
        if user_reqs:
            text = "📊 Ваши обращения:\n\n"
            for rid, req in user_reqs[-5:]:
                status_emoji = "✅" if req['status'] == 'answered' else "⏳"
                text += f"{status_emoji} #{rid}: {req['title']} ({req['date']})\n"
        else:
            text = "📊 У вас пока нет обращений"
        await query.message.edit_text(text)
    
    elif data == "show_rules":
        await show_rules_callback(query, context)
    
    elif data.startswith('submit_request_'):
        request_id = data.replace('submit_request_', '')
        if request_id in user_requests:
            request = user_requests[request_id]
            
            for admin_id in ADMIN_IDS:
                try:
                    media_text = f"📸 Медиа: {len(request['media'])} файлов" if request['media'] else "📝 Без медиа"
                    
                    keyboard = [[InlineKeyboardButton("📝 Ответить", callback_data=f"reply_{request_id}")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    message = await context.bot.send_message(
                        admin_id,
                        f"🆕 Новое обращение #{request_id}\n\n"
                        f"От: {request['first_name']} (@{request['username']})\n"
                        f"ID: {request['user_id']}\n"
                        f"Тема: {request['title']}\n"
                        f"Описание: {request['description']}\n"
                        f"{media_text}\n"
                        f"Время: {request['date']}",
                        reply_markup=reply_markup
                    )
                    
                    for media in request['media']:
                        if media['type'] == 'photo':
                            await context.bot.send_photo(admin_id, media['file_id'])
                        elif media['type'] == 'video':
                            await context.bot.send_video(admin_id, media['file_id'])
                            
                except Exception as e:
                    logger.error(f"Ошибка отправки админу: {e}")
            
            if user.id in pending_requests:
                del pending_requests[user.id]
            
            await query.message.edit_text("✅ Обращение отправлено! Мы ответим вам в ближайшее время.")
    
    elif data == "cancel_request":
        if user.id in pending_requests:
            del pending_requests[user.id]
        await query.message.edit_text("❌ Создание обращения отменено")
    
    elif data.startswith('reply_'):
        if user.id not in ADMIN_IDS:
            await query.message.reply_text("❌ У вас нет прав для этого действия")
            return
        
        request_id = data.replace('reply_', '')
        if request_id in user_requests:
            context.user_data['replying_to'] = request_id
            await query.message.reply_text("✍️ Введите ваш ответ:")
            await query.message.delete()
    
    elif data == "admin_active_chats":
        if user.id not in ADMIN_IDS:
            await query.message.reply_text("❌ У вас нет прав для этого действия")
            return
        
        active = []
        for user_id, chat_info in support_chats.items():
            try:
                user_chat = await context.bot.get_chat(user_id)
                active.append(f"👤 {user_chat.first_name}: #{chat_info['request_id']}")
            except:
                continue
        
        if active:
            text = "📨 Активные чаты:\n\n" + "\n".join(active)
        else:
            text = "📨 Нет активных чатов"
        
        await query.message.edit_text(text)
    
    elif data == "admin_stats":
        if user.id not in ADMIN_IDS:
            await query.message.reply_text("❌ У вас нет прав для этого действия")
            return
        
        total = len(user_requests)
        new = len([r for r in user_requests.values() if r['status'] == 'new'])
        
        stats = (
            f"📊 Статистика поддержки\n\n"
            f"Всего запросов: {total}\n"
            f"Новых: {new}\n"
            f"Активных чатов: {len(support_chats)}\n"
            f"Клонов бота: {len(bot_clones)}"
        )
        await query.message.edit_text(stats)
    
    elif data == "admin_clones":
        if user.id not in ADMIN_IDS:
            await query.message.reply_text("❌ У вас нет прав для этого действия")
            return
        
        keyboard = [
            [InlineKeyboardButton("➕ Создать клона", callback_data="create_clone")],
            [InlineKeyboardButton("📋 Список клонов", callback_data="list_clones")],
            [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("🤖 Управление клонами бота:", reply_markup=reply_markup)
    
    elif data == "create_clone":
        if user.id not in ADMIN_IDS:
            await query.message.reply_text("❌ У вас нет прав для этого действия")
            return
        
        await create_clone_callback(query, context)
    
    elif data == "list_clones":
        if user.id not in ADMIN_IDS:
            await query.message.reply_text("❌ У вас нет прав для этого действия")
            return
        
        if bot_clones:
            text = "📋 Список клонов:\n\n"
            for clone_id, clone_info in bot_clones.items():
                status = "🟢 Активен" if clone_info['status'] == 'active' else "🔴 Неактивен"
                tech = "🔧 Техперерыв" if clone_info['tech_break'] else "✅ Работает"
                text += f"ID: {clone_id}\n{status} | {tech}\nВладелец: {clone_info['owner_id']}\nСоздан: {clone_info['created_at']}\n\n"
        else:
            text = "📋 Нет созданных клонов"
        
        await query.message.edit_text(text)
    
    elif data == "admin_tech_break":
        if user.id not in ADMIN_IDS:
            await query.message.reply_text("❌ У вас нет прав для этого действия")
            return
        
        keyboard = [
            [InlineKeyboardButton("🔧 Включить техперерыв", callback_data="tech_break_on")],
            [InlineKeyboardButton("✅ Выключить техперерыв", callback_data="tech_break_off")],
            [InlineKeyboardButton("✏️ Изменить сообщение", callback_data="tech_break_message")],
            [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("🔧 Управление техническим перерывом:", reply_markup=reply_markup)
    
    elif data == "tech_break_on":
        if user.id not in ADMIN_IDS:
            await query.message.reply_text("❌ У вас нет прав для этого действия")
            return
        
        technical_breaks[user.id] = True
        if user.id not in tech_break_messages:
            tech_break_messages[user.id] = "🔧 В боте сейчас технические работы. Приходите позже!"
        
        await query.message.edit_text("✅ Технический перерыв включен")
    
    elif data == "tech_break_off":
        if user.id not in ADMIN_IDS:
            await query.message.reply_text("❌ У вас нет прав для этого действия")
            return
        
        if user.id in technical_breaks:
            del technical_breaks[user.id]
        await query.message.edit_text("✅ Технический перерыв выключен")
    
    elif data == "tech_break_message":
        if user.id not in ADMIN_IDS:
            await query.message.reply_text("❌ У вас нет прав для этого действия")
            return
        
        context.user_data['awaiting_tech_message'] = True
        await query.message.edit_text(
            "✏️ Отправьте новое сообщение для технического перерыва:\n\n"
            "(оно будет показываться пользователям при /start)"
        )
    
    elif data == "admin_settings":
        if user.id not in ADMIN_IDS:
            await query.message.reply_text("❌ У вас нет прав для этого действия")
            return
        
        keyboard = [
            [InlineKeyboardButton("👥 Мои группы", callback_data="admin_my_groups")],
            [InlineKeyboardButton("🤖 Клоны", callback_data="admin_clones")],
            [InlineKeyboardButton("🔧 Техперерыв", callback_data="admin_tech_break")],
            [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("⚙️ Настройки бота:", reply_markup=reply_markup)
    
    elif data == "admin_my_groups":
        if user.id not in ADMIN_IDS:
            await query.message.reply_text("❌ У вас нет прав для этого действия")
            return
        
        groups = []
        for chat_id in group_welcome_settings.keys():
            try:
                chat = await context.bot.get_chat(chat_id)
                if await is_group_admin(update, context, chat_id, user.id):
                    groups.append(f"👥 {chat.title}")
            except:
                continue
        
        if groups:
            text = "Ваши группы:\n\n" + "\n".join(groups)
        else:
            text = "У вас нет групп с настроенными приветствиями"
        
        await query.message.edit_text(text)
    
    elif data == "admin_back":
        await show_admin_menu_callback(query, context)
    
    elif data.startswith('confirm_welcome_'):
        chat_id = int(data.replace('confirm_welcome_', ''))
        if chat_id in pending_group_settings:
            settings = pending_group_settings[chat_id]
            if settings['user_id'] == user.id:
                group_welcome_settings[chat_id] = settings['data']
                del pending_group_settings[chat_id]
                await query.message.edit_text("✅ Приветствие успешно сохранено!")
            else:
                await query.message.reply_text("❌ Только владелец может подтвердить изменения")
    
    elif data.startswith('cancel_welcome_'):
        chat_id = int(data.replace('cancel_welcome_', ''))
        if chat_id in pending_group_settings:
            if pending_group_settings[chat_id]['user_id'] == user.id:
                del pending_group_settings[chat_id]
                await query.message.edit_text("❌ Изменения отменены")
            else:
                await query.message.reply_text("❌ Только владелец может отменить изменения")
    
    elif data.startswith('confirm_goodbye_'):
        chat_id = int(data.replace('confirm_goodbye_', ''))
        if chat_id in pending_group_settings:
            settings = pending_group_settings[chat_id]
            if settings['user_id'] == user.id:
                group_goodbye_settings[chat_id] = settings['data']
                del pending_group_settings[chat_id]
                await query.message.edit_text("✅ Сообщение о выходе успешно сохранено!")
            else:
                await query.message.reply_text("❌ Только владелец может подтвердить изменения")
    
    elif data.startswith('cancel_goodbye_'):
        chat_id = int(data.replace('cancel_goodbye_', ''))
        if chat_id in pending_group_settings:
            if pending_group_settings[chat_id]['user_id'] == user.id:
                del pending_group_settings[chat_id]
                await query.message.edit_text("❌ Изменения отменены")
            else:
                await query.message.reply_text("❌ Только владелец может отменить изменения")

async def show_rules_callback(query, context):
    keyboard = [
        [InlineKeyboardButton("✅ Я согласен с правилами", callback_data="accept_rules")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    rules_text = (
        "📋 Правила обращения в поддержку Puls:\n\n"
        "1. Одно обращение - одна тема\n"
        "2. Запрещены оскорбления и нецензурная лексика\n"
        "3. Фото не более 2 штук\n"
        "4. Видео не более 1 штуки\n"
        "5. Нельзя отправлять фото и видео вместе\n"
        "6. Название обращения от 5 до 20 символов\n"
        "7. Описание от 10 до 200 символов\n\n"
        "Нажимая 'Я согласен' вы принимаете эти правила"
    )
    
    await query.message.edit_text(rules_text, reply_markup=reply_markup)

async def create_clone_callback(query, context):
    user = query.from_user
    
    clone_creation_sessions[user.id] = {
        'status': 'awaiting_token',
        'expires': datetime.now() + timedelta(minutes=10)
    }
    
    await query.message.edit_text(
        "🤖 Создание клона бота\n\n"
        "Отправьте токен нового бота в течение 10 минут:\n"
        "(можно получить у @BotFather)"
    )
    
    asyncio.create_task(check_clone_creation_timeout(user.id, context))

async def show_admin_menu_callback(query, context):
    keyboard = [
        [InlineKeyboardButton("📨 Активные чаты", callback_data="admin_active_chats")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("🤖 Управление клонами", callback_data="admin_clones")],
        [InlineKeyboardButton("🔧 Технический перерыв", callback_data="admin_tech_break")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(
        f"👨‍💼 Панель администратора\n\nДобро пожаловать, {admin_names.get(query.from_user.id, 'Администратор')}!",
        reply_markup=reply_markup
    )

async def group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ Эта команда работает только в группах")
        return
    
    if not await is_group_admin(update, context, chat.id, user.id):
        await update.message.reply_text("❌ Только администраторы группы могут использовать эту команду")
        return
    
    if len(context.args) == 0:
        await update.message.reply_text(
            "Использование:\n"
            "/welcome текст - установить текстовое приветствие\n"
            "/welcome (с фото/видео) - установить приветствие с медиа\n"
            "/goodbye текст - установить текстовое сообщение о выходе\n"
            "/goodbye (с фото/видео) - установить сообщение о выходе с медиа"
        )
        return
    
    command = context.args[0].lower()
    
    if command in ['welcome', 'goodbye']:
        context.user_data['awaiting_group_' + command] = chat.id
        await update.message.reply_text(
            f"📝 Отправьте текст и при необходимости приложите фото или видео (до 20 секунд)\n\n"
            f"Используйте %username% для имени пользователя"
        )

async def handle_group_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type not in ['group', 'supergroup']:
        return
    
    if not await is_group_admin(update, context, chat.id, user.id):
        return
    
    setting_type = None
    if 'awaiting_group_welcome' in context.user_data and context.user_data['awaiting_group_welcome'] == chat.id:
        setting_type = 'welcome'
        del context.user_data['awaiting_group_welcome']
    elif 'awaiting_group_goodbye' in context.user_data and context.user_data['awaiting_group_goodbye'] == chat.id:
        setting_type = 'goodbye'
        del context.user_data['awaiting_group_goodbye']
    else:
        return
    
    caption = update.message.caption or ""
    message_text = update.message.text or caption
    
    media_data = {}
    
    if update.message.photo:
        photo = update.message.photo[-1]
        media_data = {
            'type': 'photo',
            'content': photo.file_id,
            'caption': message_text
        }
    elif update.message.video:
        video = update.message.video
        if video.duration > 20:
            await update.message.reply_text("❌ Видео должно быть не длиннее 20 секунд")
            return
        media_data = {
            'type': 'video',
            'content': video.file_id,
            'caption': message_text
        }
    elif message_text:
        media_data = {
            'type': 'text',
            'content': message_text,
            'caption': None
        }
    else:
        await update.message.reply_text("❌ Отправьте текст или медиа с подписью")
        return
    
    preview_text = "Предпросмотр:\n\n"
    if setting_type == 'welcome':
        preview_text += media_data['content'].replace('%username%', user.first_name) if media_data['type'] == 'text' else media_data['caption'].replace('%username%', user.first_name)
    else:
        preview_text += media_data['content'].replace('%username%', user.first_name) if media_data['type'] == 'text' else media_data['caption'].replace('%username%', user.first_name)
    
    keyboard = [
        [InlineKeyboardButton("✅ Да", callback_data=f"confirm_{setting_type}_{chat.id}"),
         InlineKeyboardButton("❌ Нет", callback_data=f"cancel_{setting_type}_{chat.id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    pending_group_settings[chat.id] = {
        'user_id': user.id,
        'data': media_data
    }
    
    await update.message.reply_text(preview_text, reply_markup=reply_markup)

async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.chat_member:
        return
    
    chat = update.effective_chat
    new_member = update.chat_member.new_chat_member
    old_member = update.chat_member.old_chat_member
    
    if chat.type not in ['group', 'supergroup']:
        return
    
    if new_member.status == 'member' and old_member.status == 'left':
        user = new_member.user
        if chat.id in group_welcome_settings:
            settings = group_welcome_settings[chat.id]
            try:
                text = settings['content'] if settings['type'] == 'text' else settings['caption']
                text = text.replace('%username%', user.first_name)
                
                if settings['type'] == 'text':
                    await context.bot.send_message(chat.id, text)
                elif settings['type'] == 'photo':
                    await context.bot.send_photo(chat.id, settings['content'], caption=text)
                elif settings['type'] == 'video':
                    await context.bot.send_video(chat.id, settings['content'], caption=text)
            except Exception as e:
                logger.error(f"Ошибка отправки приветствия: {e}")
        else:
            await context.bot.send_message(
                chat.id,
                f"🥳 {user.first_name} зашел в группу! Будем знакомы! Рады видеть нового участника 🎉"
            )
    
    elif old_member.status == 'member' and new_member.status == 'left':
        user = old_member.user
        if chat.id in group_goodbye_settings:
            settings = group_goodbye_settings[chat.id]
            try:
                text = settings['content'] if settings['type'] == 'text' else settings['caption']
                text = text.replace('%username%', user.first_name)
                
                if settings['type'] == 'text':
                    await context.bot.send_message(chat.id, text)
                elif settings['type'] == 'photo':
                    await context.bot.send_photo(chat.id, settings['content'], caption=text)
                elif settings['type'] == 'video':
                    await context.bot.send_video(chat.id, settings['content'], caption=text)
            except Exception as e:
                logger.error(f"Ошибка отправки прощания: {e}")
        else:
            await context.bot.send_message(
                chat.id,
                f"👋 {user.first_name} покинул группу... Жалко терять таких участников 😢"
            )

async def handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id in clone_creation_sessions:
        if clone_creation_sessions[user.id]['status'] == 'awaiting_token':
            if datetime.now() > clone_creation_sessions[user.id]['expires']:
                del clone_creation_sessions[user.id]
                await update.message.reply_text("⏰ Время истекло. Начните создание клона заново с /start")
                return
            
            if update.message.text and not update.message.text.startswith('/'):
                await handle_clone_token(update, context)
                return
        
        elif clone_creation_sessions[user.id]['status'] == 'awaiting_admins':
            if update.message.text and not update.message.text.startswith('/'):
                await handle_clone_admins(update, context)
                return

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if chat.type in ['group', 'supergroup']:
        await update.message.reply_text(
            "👋 Команды для администраторов группы:\n"
            "/welcome - установить приветствие\n"
            "/goodbye - установить сообщение о выходе\n\n"
            "Используйте %username% в тексте для имени пользователя"
        )
    else:
        await update.message.reply_text(
            "👋 Команды:\n"
            "/start - начать работу\n"
            "/help - это сообщение\n"
            "/clone - создать клона бота (только для админов)"
        )

async def clone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав для создания клонов")
        return
    
    await create_clone(update, context)

def main():
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("⚠️ Пожалуйста, вставьте ваш токен бота в переменную TOKEN")
        return
    
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("clone", clone_command))
    application.add_handler(CommandHandler("welcome", group_command))
    application.add_handler(CommandHandler("goodbye", group_command))
    
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.CHAT_MEMBER))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.CAPTION, handle_group_media))
    application.add_handler(MessageHandler(filters.ALL, handle_command))
    
    print("🤖 Бот Puls запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()


