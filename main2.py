import os
import random
import asyncio
import aiosqlite  # Заменяем sqlite3 на асинхронную версию
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from dotenv import load_dotenv  # Для загрузки токена из .env файла

# Загружаем переменные окружения
load_dotenv()

# Настройки базы данных
DB_NAME = "themes2.db"

# Состояния для ConversationHandler
MENU, NEW_GAME, CONTINUE_GAME, PLAYING = range(4)

# Эмодзи для кода игры
EMOJI_LIST = ['🎮', '🎲', '🎯', '🎨', '🎭', '🎪', '🎫', '🎬', '🎤', '🎧',
              '🎼', '🎹', '🎷', '🎺', '🎸', '🎻', '🥁', '⚽', '🏀', '🏈',
              '⚾', '🎾', '🏐', '🏉', '🎱', '🏓', '🏸', '🏒', '🏑', '🏏']

def escape_markdown_v2(text: str) -> str:
    """Экранирует специальные символы для MarkdownV2"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, '\\' + char)
    return text

# ========== АСИНХРОННЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С БД ==========
async def get_connection():
    """Асинхронное подключение к БД"""
    return await aiosqlite.connect(DB_NAME)


async def create_new_game(username: str):
    """Создание новой игры и возврат кода игры"""
    async with await get_connection() as conn:
        cursor = await conn.cursor()

        # Генерация уникального кода игры из эмодзи
        while True:
            game_code = ''.join(random.choices(EMOJI_LIST, k=4))
            await cursor.execute("SELECT id FROM Games WHERE game_number = ?", (game_code,))
            if not await cursor.fetchone():
                break

        # Создание записи об игре
        await cursor.execute(
            "INSERT INTO Games (game_number, username) VALUES (?, ?)",
            (game_code, username)
        )
        await conn.commit()
        game_id = cursor.lastrowid

        return game_id, game_code


async def get_game_by_code(game_code: str):
    """Получение игры по коду"""
    async with await get_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "SELECT id, username, finished, current_round FROM Games WHERE game_number = ?",
            (game_code,)
        )
        game = await cursor.fetchone()

    if game:
        return {
            'id': game[0],
            'username': game[1],
            'finished': bool(game[2]),
            'current_round': game[3]
        }
    return None


async def update_game_round(game_id: int, round_number: int):
    """Обновление текущего раунда игры"""
    async with await get_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "UPDATE Games SET current_round = ? WHERE id = ?",
            (round_number, game_id)
        )
        await conn.commit()


async def finish_game(game_id: int):
    """Завершение игры"""
    async with await get_connection() as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "UPDATE Games SET finished = 1 WHERE id = ?",
            (game_id,)
        )
        await conn.commit()


async def get_used_themes_for_game(game_id: int, category: str):
    """Получение всех использованных тем для игры по категории"""
    async with await get_connection() as conn:
        cursor = await conn.cursor()

        if category == 'blitz':
            await cursor.execute("""
                SELECT r.blitz_id 
                FROM register r
                JOIN Blitz b ON r.blitz_id = b.blitzid
                WHERE r.game_id = ?
            """, (game_id,))
        elif category == 'lark':
            await cursor.execute("""
                SELECT r.lark_id 
                FROM register r
                JOIN Larks l ON r.lark_id = l.larkid
                WHERE r.game_id = ?
            """, (game_id,))
        else:  # owl
            await cursor.execute("""
                SELECT r.owl_id 
                FROM register r
                JOIN Owls o ON r.owl_id = o.owlid
                WHERE r.game_id = ?
            """, (game_id,))

        used_ids = [row[0] for row in await cursor.fetchall() if row[0] is not None]
        return used_ids


async def add_theme_to_register(game_id: int, category: str, theme_id: int):
    """Добавление использованной темы в регистр"""
    async with await get_connection() as conn:
        cursor = await conn.cursor()

        if category == 'blitz':
            await cursor.execute(
                "INSERT INTO register (game_id, blitz_id) VALUES (?, ?)",
                (game_id, theme_id)
            )
        elif category == 'lark':
            await cursor.execute(
                "INSERT INTO register (game_id, lark_id) VALUES (?, ?)",
                (game_id, theme_id)
            )
        elif category == 'owl':
            await cursor.execute(
                "INSERT INTO register (game_id, owl_id) VALUES (?, ?)",
                (game_id, theme_id)
            )

        await conn.commit()


async def get_themes_for_round(game_id: int, category: str):
    """Получение тем для раунда с учетом ограничений"""
    async with await get_connection() as conn:
        cursor = await conn.cursor()

        # Определяем таблицу и поле id по категории
        if category == 'blitz':
            table = 'Blitz'
            id_field = 'blitzid'
        elif category == 'lark':
            table = 'Larks'
            id_field = 'larkid'
        else:  # owl
            table = 'Owls'
            id_field = 'owlid'

        # Получаем использованные темы для этой игры и категории
        used_ids = await get_used_themes_for_game(game_id, category)

        # Если использованных тем нет, берем все
        if not used_ids:
            await cursor.execute(f"SELECT {id_field}, theme, difficult FROM {table}")
        else:
            placeholders = ','.join(['?'] * len(used_ids))
            await cursor.execute(
                f"SELECT {id_field}, theme, difficult FROM {table} WHERE {id_field} NOT IN ({placeholders})",
                used_ids
            )

        all_themes = await cursor.fetchall()

    if not all_themes:
        return []

    # Разделяем темы по сложности
    easy_themes = [t for t in all_themes if t[2] == 0]
    hard_themes = [t for t in all_themes if t[2] == 1]

    selected_themes = []

    # Логика выбора тем с учетом ограничения на сложность
    # 1. Пробуем взять 2 легкие темы
    if len(easy_themes) >= 2:
        selected_themes = random.sample(easy_themes, 2)
    # 2. Если есть 1 легкая и хотя бы 1 сложная
    elif len(easy_themes) == 1 and len(hard_themes) >= 1:
        selected_themes = [easy_themes[0], random.choice(hard_themes)]
    # 3. Если есть только 1 легкая
    elif len(easy_themes) == 1:
        selected_themes = [easy_themes[0]]
    # 4. Если есть только сложные темы
    elif len(hard_themes) >= 2:
        # Берем только одну сложную тему
        selected_themes = [random.choice(hard_themes)]
    # 5. Если есть только одна сложная
    elif len(hard_themes) == 1:
        selected_themes = [hard_themes[0]]

    return selected_themes[:2]  # Возвращаем не более 2 тем


# ========== ОСНОВНЫЕ ФУНКЦИИ БОТА ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню"""
    # Очищаем предыдущие данные
    context.user_data.clear()

    keyboard = [
        ["📖 Справка", "🎮 Начать игру"],
        ["🔄 Обновить базу данных"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "🎲 *Добро пожаловать в игру SiXeS*\n\n"
        "Выберите действие:",
        reply_markup=reply_markup,
        parse_mode='MarkdownV2'
    )

    return MENU


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик главного меню"""
    text = update.message.text

    if text == "📖 Справка":
        await show_help(update, context)
        return MENU
    elif text == "🎮 Начать игру":
        await start_game_menu(update, context)
        return NEW_GAME
    elif text == "🔄 Обновить базу данных":
        await update_database(update, context)
        return MENU
    else:
        await update.message.reply_text("Неизвестная команда. Используйте меню для навигации.")
        return MENU


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать справку"""
    help_text = (
        "📋 *Правила игры SiXeS:*\n\n"
        "🎯 *Цель игры:*\n"
        "Набрать как можно больше очков за 6 раундов.\n\n"
        "🔄 *Структура игры:*\n"
        "1️⃣\-2️⃣ раунд: *Совпадения* \(Owls\) \- находите общее\n"
        "3️⃣\-4️⃣ раунд: *Разные ответы* \(Larks\) \- разнообразие приветствуется\n"
        "5️⃣\-6️⃣ раунд: *Блиц* \(Blitz\) \- быстрота и точность\n\n"
        "⏱ *Тайминг:*\n"
        "• 1 минута на каждый раунд\n"
        "• Выбор темы из двух вариантов\n"
        "• Ответы записываются на бланке\n\n"
        "📝 *Бланк для печати:*\n"
        "Скачайте по ссылке: https://example\.com/sixes\_form\.pdf\n\n"
        "🔢 *Создание игры:*\n"
        "1\. Нажмите '🎮 Начать игру'\n"
        "2\. Выберите '🆕 Новая игра'\n"
        "3\. Получите уникальный код из эмодзи\n"
        "4\. Поделитесь кодом с друзьями\n\n"
        "🔄 *Продолжение игры:*\n"
        "1\. Нажмите '🎮 Начать игру'\n"
        "2\. Выберите '↪️ Продолжить игру'\n"
        "3\. Введите код из 4 эмодзи\n\n"
        "*Удачи в игре* 🍀"
    )

    await update.message.reply_text(help_text, parse_mode='MarkdownV2')


async def update_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновление базы данных"""
    try:
        from completion_bd2 import init_db
        await update.message.reply_text("🔄 Обновление базы данных...")

        # Выполняем синхронную функцию в отдельном потоке
        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(None, init_db)

        if success:
            await update.message.reply_text("✅ База данных успешно обновлена")
        else:
            await update.message.reply_text("❌ Ошибка при обновлении базы данных")
    except Exception as e:
        await update.message.reply_text(f"❌ Произошла ошибка: {str(e)}")
        print(f"Ошибка при обновлении БД: {e}")


async def start_game_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню начала игры"""
    keyboard = [
        ["🆕 Новая игра", "↪️ Продолжить игру"],
        ["🔙 Назад в меню"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "*Начать новую игру или продолжить существующую\?*\n\n"
        "🆕 *Новая игра* \- создание новой сессии\n"
        "↪️ *Продолжить игру* \- ввод кода игры",
        reply_markup=reply_markup,
        parse_mode='MarkdownV2'
    )

    return NEW_GAME


async def new_game_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик меню новой игры"""
    text = update.message.text

    if text == "🆕 Новая игра":
        await create_new_game_handler(update, context)
        return PLAYING
    elif text == "↪️ Продолжить игру":
        await continue_game_handler(update, context)
        return CONTINUE_GAME
    elif text == "🔙 Назад в меню":
        await start(update, context)
        return MENU
    else:
        await update.message.reply_text("Пожалуйста, используйте кнопки меню для выбора.")
        return NEW_GAME


async def create_new_game_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание новой игры"""
    username = update.message.from_user.username or update.message.from_user.first_name

    # Создаем новую игру
    game_id, game_code = await create_new_game(username)

    # Сохраняем данные игры в контексте
    context.user_data['game_id'] = game_id
    context.user_data['game_code'] = game_code
    context.user_data['round'] = 1

    # Показываем код игры
    await update.message.reply_text(
        f"🎉 *Игра создана\\!*\n\n"
        f"📝 *Код игры:* `{game_code}`\n\n"
        f"📋 *Скопируйте этот код и поделитесь с другими игроками\\.*\n"
        f"Чтобы присоединиться к игре, нужно ввести этот код\\.\n\n"
        f"Раунд 1 начинается\\...",
        parse_mode='MarkdownV2'
    )

    # Начинаем первый раунд
    await show_round_themes(update, context)
    return PLAYING


async def continue_game_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос кода игры для продолжения"""
    await update.message.reply_text(
        "*Введите код игры \(4 эмодзи\):*\n\n"
        "Пример: `🎮🎲🎯🎨`\n"
        "Код должен состоять ровно из 4 эмодзи\.",
        parse_mode='MarkdownV2'
    )

    return CONTINUE_GAME


async def handle_game_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка введенного кода игры"""
    game_code = update.message.text.strip()

    # Проверяем длину кода
    if len(game_code) != 4:
        await update.message.reply_text(
            "❌ *Неверный код\!*\n\n"
            "Код должен состоять из 4 эмодзи\.\n"
            "Попробуйте еще раз:",
            parse_mode='MarkdownV2'
        )
        return CONTINUE_GAME

    # Ищем игру
    game = await get_game_by_code(game_code)

    if not game:
        await update.message.reply_text(
            "❌ *Игра не найдена\!*\n\n"
            "Проверьте правильность кода и попробуйте еще раз:",
            parse_mode='MarkdownV2'
        )
        return CONTINUE_GAME

    if game['finished']:
        await update.message.reply_text(
            "❌ *Игра уже завершена\!*\n\n"
            "Эта игра уже завершена\.\n"
            "Создайте новую игру\.",
            parse_mode='MarkdownV2'
        )
        await start_game_menu(update, context)
        return NEW_GAME

    # Сохраняем данные игры
    context.user_data['game_id'] = game['id']
    context.user_data['game_code'] = game_code
    context.user_data['round'] = game['current_round']

    await update.message.reply_text(
        f"✅ *Игра найдена\!*\n\n"
        f"Продолжаем с раунда {game['current_round']}",
        parse_mode='MarkdownV2'
    )

    # Показываем темы текущего раунда
    await show_round_themes(update, context)
    return PLAYING


async def show_round_themes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать темы для текущего раунда"""
    round_number = context.user_data.get('round', 1)
    game_id = context.user_data.get('game_id')

    if not game_id:
        await update.message.reply_text("❌ Ошибка: игра не найдена. Начните новую игру.")
        await start(update, context)
        return MENU

    if round_number > 6:
        await finish_current_game(update, context)
        return PLAYING

    # Определяем категорию для раунда
    if round_number <= 2:
        category = 'owl'
        category_name = "🦉 Совпадения"
        category_desc = "Найдите общее в ассоциациях"
    elif round_number <= 4:
        category = 'lark'
        category_name = "🐦 Разные ответы"
        category_desc = "Разнообразие приветствуется"
    else:
        category = 'blitz'
        category_name = "⚡ Блиц-раунд"
        category_desc = "Быстрота и точность"

    # Получаем темы
    try:
        themes = await get_themes_for_round(game_id, category)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при загрузке тем: {str(e)}")
        return PLAYING

    if not themes:
        # Если тем нет, пропускаем раунд
        message = await update.message.reply_text(
            f"*Раунд {round_number}: {category_name}*\n\n"
            f"❌ *Темы для этого раунда закончились\.*\n"
            f"Переходим к следующему раунду\.",
            parse_mode='MarkdownV2'
        )

        context.user_data['round'] = round_number + 1
        await update_game_round(game_id, context.user_data['round'])

        if context.user_data['round'] <= 6:
            # Создаем кнопку для следующего раунда
            keyboard = [[InlineKeyboardButton("▶️ Следующий раунд", callback_data="next_round")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                "Нажмите для продолжения:",
                reply_markup=reply_markup
            )
        else:
            await finish_current_game(update, context)
        return PLAYING

    # Создаем клавиатуру с темами
    keyboard = []
    for theme in themes:
        theme_id = theme[0]
        theme_text = theme[1]
        difficulty = "🔴" if theme[2] == 1 else "🟢"
        button_text = f"{difficulty} {theme_text}"
        callback_data = f"{category}_{theme_id}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"*Раунд {round_number}: {category_name}*\n"
        f"{category_desc}\n\n"
        f"*Выберите тему:* \(🟢 легко, 🔴 сложно\)",
        reply_markup=reply_markup,
        parse_mode='MarkdownV2'
    )
    return PLAYING


async def handle_theme_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора темы"""
    query = update.callback_query
    await query.answer()

    # Разбираем callback_data
    data_parts = query.data.split('_')
    category = data_parts[0]
    theme_id = int(data_parts[1])

    # Добавляем тему в регистр
    game_id = context.user_data['game_id']
    await add_theme_to_register(game_id, category, theme_id)

    await query.edit_message_text(
        text=f"✅ *Тема выбрана\\!*\n\n"
             f"⏱ *У вас 1 минута на обсуждение\\...*\n\n"
             f"Засекайте время и записывайте ответы на бланке\\!",
        parse_mode='MarkdownV2'
    )

    # Запускаем таймер - исправленный вариант для v20+
    context.job_queue.run_once(
        end_round,  # callback функция
        60,  # через 60 секунд
        chat_id=query.message.chat_id,
        user_id=query.from_user.id,
        data={
            'chat_id': query.message.chat_id,
            'game_id': game_id,
            'message_id': query.message.id
        }
    )
    return PLAYING


async def end_round(context: ContextTypes.DEFAULT_TYPE):
    """Завершение раунда"""
    job = context.job
    data = job.data
    chat_id = data['chat_id']
    game_id = data['game_id']

    # Обновляем номер раунда в базе данных
    try:
        async with await get_connection() as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                "SELECT current_round FROM Games WHERE id = ?",
                (game_id,)
            )
            result = await cursor.fetchone()
            if not result:
                return

            current_round = result[0]
            await cursor.execute(
                "UPDATE Games SET current_round = ? WHERE id = ?",
                (current_round + 1, game_id)
            )
            await conn.commit()
    except Exception as e:
        print(f"Ошибка при обновлении раунда: {e}")
        return

    keyboard = [[InlineKeyboardButton("▶️ Следующий раунд", callback_data="next_round")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=chat_id,
        text="⏰ *Время вышло\\!*\n\nЗаписывайте ответы и готовьтесь к следующему раунду\\.",
        reply_markup=reply_markup,
        parse_mode='MarkdownV2'
    )


async def handle_next_round(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка перехода к следующему раунду"""
    query = update.callback_query
    await query.answer()

    if 'round' not in context.user_data or 'game_id' not in context.user_data:
        await query.edit_message_text("❌ Ошибка: данные игры утеряны. Начните новую игру.")
        return MENU

    # Обновляем номер раунда
    context.user_data['round'] += 1
    game_id = context.user_data['game_id']
    await update_game_round(game_id, context.user_data['round'])

    if context.user_data['round'] > 6:
        await finish_current_game(update, context)
        return ConversationHandler.END

    # Показываем темы следующего раунда
    await show_round_themes(update, context)
    return PLAYING


async def finish_current_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершение текущей игры"""
    game_id = context.user_data.get('game_id')
    if game_id:
        await finish_game(game_id)

    # Очищаем данные игры
    context.user_data.clear()

    # Возвращаемся к обычной клавиатуре
    keyboard = [
        ["📖 Справка", "🎮 Начать игру"],
        ["🔄 Обновить базу данных"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "🎉 *Игра завершена\\!*\n\n"
        "Спасибо за игру\\! 🎮\n\n"
        "Для начала новой игры нажмите /start",
        parse_mode='MarkdownV2'
    )

    return MENU


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия"""
    # Очищаем данные
    context.user_data.clear()

    keyboard = [
        ["📖 Справка", "🎮 Начать игру"],
        ["🔄 Обновить базу данных"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "Действие отменено\. Для возврата в меню используйте кнопки ниже\.",
        reply_markup=reply_markup
    )

    return MENU


def main():
    # Получаем токен из переменной окружения
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        print("Ошибка: не установлен TELEGRAM_BOT_TOKEN в .env файле")
        return

    # Создаем приложение
    application = Application.builder().token(token).build()

    # Создаем ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler)],
            NEW_GAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_game_handler)],
            CONTINUE_GAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_game_code)],
            PLAYING: [
                CallbackQueryHandler(handle_theme_selection, pattern="^(owl|blitz|lark)_"),
                CallbackQueryHandler(handle_next_round, pattern="^next_round$")
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )

    # Добавляем обработчики
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))

    # Запускаем бота
    print("Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()