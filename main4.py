import sqlite3
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import asyncio
import completion_bd

# Настройки базы данных
DB_NAME = "sovpadenie_main.db"


def get_user_current_game(chat_id, username):
    """Получить активную игру пользователя"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, game_number FROM Games WHERE username = ? ORDER BY id DESC LIMIT 1", (username,))
    game = cursor.fetchone()
    conn.close()
    return game


def create_new_game(username):
    """Создать новую игру"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Получаем максимальный номер игры для генерации нового
    cursor.execute("SELECT MAX(game_number) FROM Games")
    max_number = cursor.fetchone()[0]
    new_game_number = 1 if max_number is None else max_number + 1

    # Создаем новую игру
    cursor.execute("INSERT INTO Games (game_number, username) VALUES (?, ?)",
                   (new_game_number, username))
    game_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_game_number, game_id


def get_game_by_number(game_number, username):
    """Найти игру по номеру и пользователю"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM Games WHERE game_number = ? AND username = ?",
                   (game_number, username))
    game = cursor.fetchone()
    conn.close()
    return game[0] if game else None


def get_theme_name(theme_id, category):
    """Получить название темы по ID и категории"""
    table_map = {'owl': 'Owls', 'lark': 'Larks', 'blitz': 'Blitz'}
    table_name = table_map.get(category)
    if not table_name:
        return None

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f"SELECT theme FROM {table_name} WHERE id = ?", (theme_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


def get_themes_for_game(game_id, category):
    """Получить темы для конкретной игры (учитывая уже использованные)"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Получаем ID уже использованных тем в этой игре для конкретной категории
    column_name = f"{category}_id"
    cursor.execute(f"""
        SELECT {column_name} FROM register 
        WHERE game_id = ? AND {column_name} IS NOT NULL
    """, (game_id,))

    # Собираем список использованных ID
    used_themes = [row[0] for row in cursor.fetchall()]

    # Определяем таблицу для каждой категории
    table_map = {
        'owl': 'Owls',
        'lark': 'Larks',
        'blitz': 'Blitz'
    }

    table_name = table_map.get(category)
    if not table_name:
        conn.close()
        return []

    # Формируем условие для исключения использованных тем
    exclude_condition = ""
    params = []

    if used_themes:
        placeholders = ','.join(['?' for _ in used_themes])
        exclude_condition = f"AND id NOT IN ({placeholders})"
        params.extend(used_themes)

    themes = []

    # Для категорий owl и lark
    if category in ['owl', 'lark']:
        # ПЕРВЫЙ ЗАПРОС: случайная НЕсложная тема
        query1 = f"""
            SELECT id, theme, difficult
            FROM {table_name}
            WHERE difficult = 0 {exclude_condition}
            ORDER BY RANDOM()
            LIMIT 1
        """

        cursor.execute(query1, params)
        theme1 = cursor.fetchone()

        if theme1:
            themes.append(theme1)

            # ВТОРОЙ ЗАПРОС: случайная любая тема, но не такая же как первая
            second_params = params.copy()
            second_params.append(theme1[0])  # Добавляем ID первой темы

            second_placeholders = ','.join(['?' for _ in second_params])
            query2 = f"""
                SELECT id, theme, difficult
                FROM {table_name}
                WHERE id NOT IN ({second_placeholders})
                ORDER BY RANDOM()
                LIMIT 1
            """

            cursor.execute(query2, second_params)
            theme2 = cursor.fetchone()

            if theme2:
                themes.append(theme2)

    # Для категории blitz
    elif category == 'blitz':
        # Один запрос на 6 случайных тем
        params.append(6)  # Добавляем лимит

        if used_themes:
            placeholders = ','.join(['?' for _ in used_themes])
            query = f"""
                SELECT id, theme, difficult
                FROM {table_name}
                WHERE id NOT IN ({placeholders})
                ORDER BY RANDOM()
                LIMIT ?
            """
        else:
            query = f"""
                SELECT id, theme, difficult
                FROM {table_name}
                ORDER BY RANDOM()
                LIMIT ?
            """

        cursor.execute(query, params)
        themes = cursor.fetchall()

    conn.close()
    return themes


def add_theme_to_game(game_id, theme_id, theme_type):
    """Добавить тему в регистр игры"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Определяем столбец для типа темы
    column_map = {'owl': 'owl_id', 'lark': 'lark_id', 'blitz': 'blitz_id'}
    column = column_map.get(theme_type)

    if column:
        # Всегда создаем новую запись для каждого раунда
        cursor.execute(f"INSERT INTO register (game_id, {column}) VALUES (?, ?)",
                       (game_id, theme_id))

    conn.commit()
    conn.close()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало работы с ботом - выбор: новая игра или продолжить"""
    username = update.effective_user.username or str(update.effective_user.id)
    context.user_data['username'] = username

    # Проверяем есть ли активные игры у пользователя
    active_game = get_user_current_game(update.effective_chat.id, username)

    keyboard = [
        ["🎮 Новая игра"],
        ["▶️ Продолжить игру"],
        ["📊 Мои игры"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "Добро пожаловать в игру 'Совпадение'!\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )


async def handle_new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание новой игры"""
    username = context.user_data.get('username')
    if not username:
        await update.message.reply_text("Пожалуйста, сначала используйте /start")
        return

    # Создаем новую игру
    game_number, game_id = create_new_game(username)

    # Сохраняем данные в контексте чата
    context.chat_data['game_id'] = game_id
    context.chat_data['game_number'] = game_number
    context.user_data['round'] = 1

    await update.message.reply_text(
        f"🎉 Игра #{game_number} создана!\n"
        f"Запомните номер игры для продолжения: {game_number}\n\n"
        "Начинаем первый раунд!"
    )

    await show_round_themes(update, context)


async def handle_continue_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса продолжения игры"""
    await update.message.reply_text(
        "Введите номер игры для продолжения (например: 42):\n"
        "Или отправьте /cancel для отмены"
    )
    context.user_data['waiting_for_game_number'] = True


async def handle_game_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка введенного номера игры"""
    if not context.user_data.get('waiting_for_game_number'):
        return

    try:
        game_number = int(update.message.text)
        username = context.user_data.get('username')

        # Ищем игру
        game_id = get_game_by_number(game_number, username)

        if game_id:
            # Сохраняем данные игры
            context.chat_data['game_id'] = game_id
            context.chat_data['game_number'] = game_number

            # Определяем текущий раунд (по количеству записей в register)
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM register WHERE game_id = ?", (game_id,))
            round_count = cursor.fetchone()[0]
            conn.close()

            # Устанавливаем текущий раунд (следующий после сыгранных)
            context.user_data['round'] = min(round_count + 1, 7)

            await update.message.reply_text(
                f"✅ Игровая сессия #{game_number} загружена!\n"
                f"Сыграно раундов {round_count}. Продолжаем с раунда {context.user_data['round']}."
            )

            # Показываем темы для текущего раунда
            await show_round_themes(update, context)
        else:
            await update.message.reply_text(
                f"❌ Игра #{game_number} не найдена или у вас нет к ней доступа.\n"
                "Проверьте номер и попробуйте снова."
            )

    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректный номер игры (только цифры)")

    # Сбрасываем состояние ожидания
    context.user_data['waiting_for_game_number'] = False


async def handle_my_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать все игры пользователя"""
    username = context.user_data.get('username')
    if not username:
        await update.message.reply_text("Пожалуйста, сначала используйте /start")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT game_number, COUNT(r.id) as rounds_played 
        FROM Games g 
        LEFT JOIN register r ON g.id = r.game_id 
        WHERE username = ? 
        GROUP BY g.id 
        ORDER BY g.id DESC 
        LIMIT 10
    """, (username,))

    games = cursor.fetchall()
    conn.close()

    if games:
        games_list = "\n".join([f"Игра #{num}: {rounds} раундов" for num, rounds in games])
        await update.message.reply_text(f"Ваши последние игры:\n{games_list}")
    else:
        await update.message.reply_text("У вас пока нет сохраненных игр.")


async def show_round_themes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать темы для текущего раунда (с привязкой к игре)"""
    round_number = context.user_data.get('round', 1)
    game_id = context.chat_data.get('game_id')

    if not game_id:
        await update.message.reply_text("Ошибка: игра не инициализирована. Используйте /start")
        return

    if round_number > 6:
        await update.message.reply_text("🎉 Игра завершена! Спасибо за участие!")
        return

    # Определяем категорию для раунда
    if round_number in (1, 4):
        category = 'owl'
        theme_type = 'owl'
        required_themes = 2
    elif round_number in (2, 5):
        category = 'lark'
        theme_type = 'lark'
        required_themes = 2
    else:  # Раунды 3 и 6 - блиц
        category = 'blitz'
        theme_type = 'blitz'
        required_themes = 6

    # Получаем темы для конкретной игры
    themes = get_themes_for_game(game_id, category)

    # Проверяем достаточно ли тем
    if len(themes) < required_themes:
        await update.message.reply_text(
            f"Недостаточно доступных тем для этого раунда! Нужно {required_themes}, есть {len(themes)}")
        return

    # Для блиц-раундов
    if category == 'blitz':
        # Сохраняем темы для этого раунда в контексте
        context.user_data['blitz_themes'] = themes

        # Формируем список тем для отображения
        themes_text = "\n".join([f"{i + 1}. {theme[1]}" for i, theme in enumerate(themes[:6])])

        # Создаем клавиатуру с одной кнопкой для запуска таймера
        keyboard = [[InlineKeyboardButton("🚀 Запустить таймер (1 мин)", callback_data="start_blitz_timer")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Определяем тип раунда для сообщения
        round_types = {3: "третий", 6: "шестой"}
        round_name = round_types.get(round_number, "")

        await update.message.reply_text(
            f"⚡ {round_name.capitalize()} раунд - Блиц! ⚡\n\n"
            f"Ваши темы:\n{themes_text}\n\n"
            f"У вас есть 1 минута на все 6 тем!\n"
            f"Нажмите кнопку ниже, чтобы начать:",
            reply_markup=reply_markup
        )
        return

    # Для обычных раундов (owl/lark) - показываем выбор темы
    keyboard = [
        [
            InlineKeyboardButton(themes[0][1], callback_data=f"theme_{themes[0][0]}_{theme_type}"),
            InlineKeyboardButton(themes[1][1], callback_data=f"theme_{themes[1][0]}_{theme_type}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    round_names = {1: "первый", 2: "второй", 4: "четвертый", 5: "пятый"}
    round_name = round_names.get(round_number, "")
    type_names = {'owl': "Совы", 'lark': "Жаворонки"}
    type_name = type_names.get(theme_type, "")

    await update.message.reply_text(
        f"🔄 {round_name.capitalize()} раунд - {type_name}\nВыберите тему:",
        reply_markup=reply_markup
    )


async def handle_theme_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора темы (с привязкой к игре)"""
    query = update.callback_query
    await query.answer()

    data_parts = query.data.split('_')
    theme_id = int(data_parts[1])
    theme_type = data_parts[2]  # owl, lark или blitz

    # Получаем ID текущей игры
    game_id = context.chat_data.get('game_id')
    if not game_id:
        await query.edit_message_text("Ошибка: игра не найдена")
        return

    # Получаем название темы
    theme_name = get_theme_name(theme_id, theme_type)

    # Определяем название раунда
    round_number = context.user_data.get('round', 1)
    round_names = {1: "первом", 2: "втором", 4: "четвертом", 5: "пятом"}
    round_name = round_names.get(round_number, "")
    type_names = {'owl': "Сов", 'lark': "Жаворонков"}
    type_name = type_names.get(theme_type, "")

    # Добавляем тему в регистр игры
    add_theme_to_game(game_id, theme_id, theme_type)

    if theme_name:
        await query.edit_message_text(
            text=f"✅ В {round_name} раунде ({type_name}) выбрана тема:\n"
                 f"<b>{theme_name}</b>\n\n"
                 f"⏳ У вас 1 минута...",
            parse_mode='HTML'
        )
    else:
        await query.edit_message_text(text=f"Выбрана тема! У вас 1 минута...")

    # Запускаем таймер
    context.job_queue.run_once(
        callback=end_round,
        when=60,
        data=query.message.chat_id
    )


async def handle_blitz_timer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик запуска таймера для блиц-раунда"""
    query = update.callback_query
    await query.answer()

    game_id = context.chat_data.get('game_id')
    if not game_id:
        await query.edit_message_text("Ошибка: игра не найдена")
        return

    # Получаем темы блица из контекста
    blitz_themes = context.user_data.get('blitz_themes', [])

    # Записываем каждую тему в регистр
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    for theme in blitz_themes:
        theme_id = theme[0]
        cursor.execute("INSERT INTO register (game_id, blitz_id) VALUES (?, ?)", (game_id, theme_id))
    conn.commit()
    conn.close()

    # Удаляем темы из контекста
    if 'blitz_themes' in context.user_data:
        del context.user_data['blitz_themes']

    round_number = context.user_data.get('round', 1)
    round_names = {3: "третьем", 6: "шестом"}
    round_name = round_names.get(round_number, "")

    await query.edit_message_text(
        text=f"⚡ В {round_name} раунде (Блиц) начался!\n"
             f"⏳ У вас 1 минута на 6 тем..."
    )

    # Запускаем таймер
    context.job_queue.run_once(
        callback=end_round,
        when=60,
        data=query.message.chat_id
    )


async def end_round(context: ContextTypes.DEFAULT_TYPE):
    """Завершение раунда"""
    job = context.job
    chat_id = job.data

    # Получаем context для этого чата
    # В реальном боте нужно получить контекст чата, но здесь упрощенно
    # Вместо этого будем использовать bot_data для хранения состояний

    # Используем application.context для доступа к данным
    application = context.application
    chat_context = application.chat_data.get(chat_id, {})

    # Увеличиваем раунд в user_data (упрощенно)
    # В реальности нужно получить user_data для пользователя в этом чате

    keyboard = [[InlineKeyboardButton("Следующий раунд", callback_data="next_round")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=chat_id,
        text="⏰ Время вышло!",
        reply_markup=reply_markup
    )


async def handle_next_round(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход к следующему раунду"""
    query = update.callback_query
    await query.answer()

    # Увеличиваем номер раунда
    if 'round' in context.user_data:
        context.user_data['round'] += 1
    else:
        context.user_data['round'] = 2

    await show_round_themes(update, context)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия"""
    if 'waiting_for_game_number' in context.user_data:
        context.user_data['waiting_for_game_number'] = False
        await update.message.reply_text("Действие отменено.")
    else:
        await update.message.reply_text("Нечего отменять.")


def main():
    """Основная функция запуска бота"""
    completion_bd.init_db()

    application = Application.builder().token("8481141708:AAHBtJWBC6SqZYjpMWHEpXmYLpDi5Hv2BTw").build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(MessageHandler(filters.Text(["🎮 Новая игра"]), handle_new_game))
    application.add_handler(MessageHandler(filters.Text(["▶️ Продолжить игру"]), handle_continue_game))
    application.add_handler(MessageHandler(filters.Text(["📊 Мои игры"]), handle_my_games))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_game_number_input))
    application.add_handler(CallbackQueryHandler(handle_theme_selection, pattern="^theme_"))
    application.add_handler(CallbackQueryHandler(handle_next_round, pattern="^next_round"))
    application.add_handler(CallbackQueryHandler(handle_blitz_timer_start, pattern="^start_blitz_timer"))

    application.run_polling()


if __name__ == "__main__":
    main()