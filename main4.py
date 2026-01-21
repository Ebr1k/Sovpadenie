import sqlite3
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import asyncio
import completion_bd

DB_NAME = "sovpadenie_main.db"

#Получить активную игру пользователя
def get_user_current_game(chat_id, username):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, game_number FROM Games WHERE username = ? ORDER BY id DESC LIMIT 1", (username,))
    game = cursor.fetchone()
    conn.close()
    return game

#Создать новую игровую сессию
def create_new_game(username):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Получить последний номер игры
    cursor.execute("SELECT MAX(game_number) FROM Games")
    max_number = cursor.fetchone()[0]
    new_game_number = 1 if max_number is None else max_number + 1

    # Создание новой сессии
    cursor.execute("INSERT INTO Games (game_number, username) VALUES (?, ?)",
                   (new_game_number, username))
    game_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_game_number, game_id

#Найти игру по номеру и пользователю
def get_game_by_number(game_number, username):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM Games WHERE game_number = ? AND username = ?",
                   (game_number, username))
    game = cursor.fetchone()
    conn.close()
    return game[0] if game else None

#Получить название темы по ID и категории
def get_theme_name(theme_id, category):
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

#Получить темы для конкретной игровой сессии (учитывая уже использованные ВО ВСЕХ играх этого пользователя)
def get_themes_for_game_session(game_id, category):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Получаем username по game_id
    cursor.execute("SELECT username FROM Games WHERE id = ?", (game_id,))
    result = cursor.fetchone()
    if not result:
        conn.close()
        return []

    username = result[0]

    # Получить ID всех игр этого пользователя
    cursor.execute("SELECT id FROM Games WHERE username = ?", (username,))
    user_game_ids = [row[0] for row in cursor.fetchall()]

    if not user_game_ids:
        conn.close()
        return []

    # Получить ВСЕ использованные темы пользователя в игре для указанной категории
    column_name = f"{category}_id"
    placeholders = ','.join(['?' for _ in [game_id]])

    cursor.execute(f"""
        SELECT {column_name} FROM register 
        WHERE game_id IN ({placeholders}) AND {column_name} IS NOT NULL
    """, [game_id])

    used_themes = [row[0] for row in cursor.fetchall()]

    table_map = {
        'owl': 'Owls',
        'lark': 'Larks',
        'blitz': 'Blitz'
    }

    table_name = table_map.get(category)
    if not table_name:
        conn.close()
        return []

    themes = []

    if category in ['owl', 'lark']:
        # Ищем несложную тему, не использованную ранее
        if used_themes:
            used_placeholders = ','.join(['?' for _ in used_themes])
            query1 = f"""
                SELECT id, theme, difficult
                FROM {table_name}
                WHERE difficult = 0 AND id NOT IN ({used_placeholders})
                ORDER BY RANDOM()
                LIMIT 1
            """
            cursor.execute(query1, used_themes)
        else:
            query1 = f"""
                SELECT id, theme, difficult
                FROM {table_name}
                WHERE difficult = 0
                ORDER BY RANDOM()
                LIMIT 1
            """
            cursor.execute(query1)

        theme1 = cursor.fetchone()

        if theme1:
            themes.append(theme1)

            # Ищем любую тему, не использованную ранее и не такую же как первая
            second_excluded = used_themes + [theme1[0]]
            second_placeholders = ','.join(['?' for _ in second_excluded])

            query2 = f"""
                SELECT id, theme, difficult
                FROM {table_name}
                WHERE id NOT IN ({second_placeholders})
                ORDER BY RANDOM()
                LIMIT 1
            """
            cursor.execute(query2, second_excluded)
            theme2 = cursor.fetchone()

            if theme2:
                themes.append(theme2)

    # Для категории blitz
    elif category == 'blitz':
        # Получить 6 случайных тем, не использованных ранее
        if used_themes:
            used_placeholders = ','.join(['?' for _ in used_themes])
            query = f"""
                SELECT id, theme, difficult
                FROM {table_name}
                WHERE id NOT IN ({used_placeholders})
                ORDER BY RANDOM()
                LIMIT 6
            """
            cursor.execute(query, used_themes)
        else:
            query = f"""
                SELECT id, theme, difficult
                FROM {table_name}
                ORDER BY RANDOM()
                LIMIT 6
            """
            cursor.execute(query)

        themes = cursor.fetchall()

    conn.close()
    return themes

#Добавить тему в регистр игры
def add_theme_to_game(game_id, theme_id, theme_type):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    column_map = {'owl': 'owl_id', 'lark': 'lark_id', 'blitz': 'blitz_id'}
    column = column_map.get(theme_type)

    if column:
        cursor.execute(f"INSERT INTO register (game_id, {column}) VALUES (?, ?)",
                       (game_id, theme_id))

    conn.commit()
    conn.close()

#Начало работы с ботом - выбор: новая игровая сессия или продолжить
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    context.user_data['username'] = username

    keyboard = [
        ["🎮 Новая игровая сессия"],
        ["▶️ Продолжить сессию"],
        ["📊 Мои сессии"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "Добро пожаловать в игру 'Совпадение'!\n"
        "Каждая сессия состоит из 6 раундов.\n"
        "Темы не повторяются в рамках всех ваших сессий!\n\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

#Создание новой игровой сессии
async def handle_new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get('username')
    if not username:
        await update.message.reply_text("Пожалуйста, сначала используйте /start")
        return

    game_number, game_id = create_new_game(username)

    context.chat_data['game_id'] = game_id
    context.chat_data['game_number'] = game_number
    context.user_data['round'] = 1
    context.user_data['session_active'] = True

    await update.message.reply_text(
        f"🎉 Игровая сессия #{game_number} создана!\n"
        f"Запомните номер сессии для продолжения: {game_number}\n"
        f"Темы не будут повторяться с предыдущими вашими сессиями.\n\n"
        "Начинаем первый раунд!"
    )

    await show_round_themes(update, context)

#Начало процесса продолжения сессии
async def handle_continue_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Введите номер сессии для продолжения (например: 42):\n"
        "Или отправьте /cancel для отмена"
    )
    context.user_data['waiting_for_game_number'] = True

#Обработка введенного номера сессии
async def handle_game_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('waiting_for_game_number'):
        return

    try:
        game_number = int(update.message.text)
        username = context.user_data.get('username')

        # Ищем сессию
        game_id = get_game_by_number(game_number, username)

        if game_id:
            # Сохраняем данные сессии
            context.chat_data['game_id'] = game_id
            context.chat_data['game_number'] = game_number
            context.user_data['round'] = 1
            context.user_data['session_active'] = True

            await update.message.reply_text(
                f"✅ Игровая сессия #{game_number} загружена!\n"
                f"Начинаем новую игру из 6 раундов.\n"
                f"Темы не будут повторяться с предыдущими вашими сессиями."
            )

            # Показать темы для первого раунда
            await show_round_themes(update, context)
        else:
            await update.message.reply_text(
                f"❌ Сессия #{game_number} не найдена или у вас нет к ней доступа.\n"
                "Проверьте номер и попробуйте снова."
            )

    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректный номер сессии (только цифры)")

    # Сброс состояние ожидания
    context.user_data['waiting_for_game_number'] = False

#Показать все сессии пользователя
async def handle_my_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get('username')
    if not username:
        await update.message.reply_text("Пожалуйста, сначала используйте /start")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT g.game_number, 
               COUNT(r.id) as themes_played
        FROM Games g 
        LEFT JOIN register r ON g.id = r.game_id 
        WHERE g.username = ? 
        GROUP BY g.id 
        ORDER BY g.id DESC 
        LIMIT 10
    """, (username,))

    games = cursor.fetchall()
    conn.close()

    if games:
        games_list = "\n".join([f"Сессия #{num}: сыграно {themes} тем" for num, themes in games])
        await update.message.reply_text(f"Ваши последние сессии:\n{games_list}")
    else:
        await update.message.reply_text("У вас пока нет сохраненных сессий.")

#Показать темы для текущего раунда
async def show_round_themes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    round_number = context.user_data.get('round', 1)
    game_id = context.chat_data.get('game_id')

    if not game_id:
        if update.message:
            await update.message.reply_text("Ошибка: сессия не инициализирована. Используйте /start")
        elif update.callback_query:
            await update.callback_query.message.reply_text("Ошибка: сессия не инициализирована. Используйте /start")
        return

    if round_number > 6:
        if update.message:
            await update.message.reply_text(
                "🎉 Игра завершена! Спасибо за участие!\n\n"
                "Хотите сыграть еще раз?\n"
                "Используйте /start для начала новой сессии."
            )
        elif update.callback_query:
            await update.callback_query.message.reply_text(
                "🎉 Игра завершена! Спасибо за участие!\n\n"
                "Хотите сыграть еще раз?\n"
                "Используйте /start для начала новой сессии."
            )
        context.user_data['session_active'] = False
        return

    if round_number in (1, 4):
        category = 'owl'
        theme_type = 'owl'
        required_themes = 2
    elif round_number in (2, 5):
        category = 'lark'
        theme_type = 'lark'
        required_themes = 2
    else:
        category = 'blitz'
        theme_type = 'blitz'
        required_themes = 6

    # Получить темы для текущей игровой сессии
    themes = get_themes_for_game_session(game_id, category)

    # Если тем недостаточно, переходим к следующему раунду
    if len(themes) < required_themes:
        context.user_data['round'] = round_number + 1

        if update.message:
            await update.message.reply_text(
                f"⚠️ В раунде {round_number} недостаточно уникальных тем!\n"
                f"Нужно {required_themes}, доступно {len(themes)}\n\n"
                f"Пропускаем этот раунд и переходим к следующему..."
            )
        elif update.callback_query:
            await update.callback_query.message.reply_text(
                f"⚠️ В раунде {round_number} недостаточно уникальных тем!\n"
                f"Нужно {required_themes}, доступно {len(themes)}\n\n"
                f"Пропускаем этот раунд и переходим к следующему..."
            )

        # Рекурсивный вызыов себя для следующего раунда
        await show_round_themes(update, context)
        return

    # Для блиц-раундов
    if category == 'blitz':
        # Сохраняем темы для этого раунда в контексте
        context.user_data['blitz_themes'] = themes
        context.user_data['blitz_themes_text'] = "\n".join(
            [f"{i + 1}. {theme[1]}" for i, theme in enumerate(themes[:6])])

        # Формируем список тем для отображения
        themes_text = context.user_data['blitz_themes_text']

        # Создаем клавиатуру с одной кнопкой для запуска таймера
        keyboard = [[InlineKeyboardButton("🚀 Запустить таймер (1 мин)", callback_data="start_blitz_timer")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Определяем тип раунда для сообщения
        round_types = {3: "третий", 6: "шестой"}
        round_name = round_types.get(round_number, "")

        if update.message:
            await update.message.reply_text(
                f"⚡ {round_name.capitalize()} раунд - Блиц! ⚡\n\n"
                f"Ваши темы:\n{themes_text}\n\n"
                f"У вас есть 1 минута на все 6 тем!\n"
                f"Нажмите кнопку ниже, чтобы начать:",
                reply_markup=reply_markup
            )
        elif update.callback_query:
            await update.callback_query.message.reply_text(
                f"⚡ {round_name.capitalize()} раунд - Блиц! ⚡\n\n"
                f"Ваши темы:\n{themes_text}\n\n"
                f"У вас есть 1 минута на все 6 тем!\n"
                f"Нажмите кнопку ниже, чтобы начать:",
                reply_markup=reply_markup
            )
        return

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

    if update.message:
        await update.message.reply_text(
            f"🔄 {round_name.capitalize()} раунд - {type_name}\nВыберите тему:",
            reply_markup=reply_markup
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            f"🔄 {round_name.capitalize()} раунд - {type_name}\nВыберите тему:",
            reply_markup=reply_markup
        )

#Обработка выбора темы
async def handle_theme_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data_parts = query.data.split('_')
    theme_id = int(data_parts[1])
    theme_type = data_parts[2]  # owl, lark или blitz

    # Получаем ID текущей сессии
    game_id = context.chat_data.get('game_id')
    if not game_id:
        await query.edit_message_text("Ошибка: сессия не найдена")
        return

    # Получаем название темы
    theme_name = get_theme_name(theme_id, theme_type)

    # Определяем название раунда
    round_number = context.user_data.get('round', 1)
    round_names = {1: "первом", 2: "втором", 4: "четвертом", 5: "пятом"}
    round_name = round_names.get(round_number, "")
    type_names = {'owl': "Сов", 'lark': "Жаворонков"}
    type_name = type_names.get(theme_type, "")

    # Добавляем тему в регистр сессии
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

    # Запускаем таймер - передаем chat_id и game_id
    context.job_queue.run_once(
        callback=end_round_callback,
        when=2,
        data={
            'chat_id': query.message.chat_id,
            'game_id': game_id,
            'round_number': round_number,
            'theme_type': theme_type
        }
    )

#Обработчик запуска таймера для блиц-раунда
async def handle_blitz_timer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    game_id = context.chat_data.get('game_id')
    if not game_id:
        await query.edit_message_text("Ошибка: сессия не найдена")
        return

    # Получить темы блица из контекста
    blitz_themes = context.user_data.get('blitz_themes', [])
    themes_text = context.user_data.get('blitz_themes_text', "")

    # Запись каждой темы в регистр
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    for theme in blitz_themes:
        theme_id = theme[0]
        cursor.execute("INSERT INTO register (game_id, blitz_id) VALUES (?, ?)", (game_id, theme_id))
    conn.commit()
    conn.close()

    # Удаление темы из контекста (но сохранение текста тем)
    if 'blitz_themes' in context.user_data:
        del context.user_data['blitz_themes']

    round_number = context.user_data.get('round', 1)
    round_names = {3: "третий", 6: "шестой"}
    round_name = round_names.get(round_number, "")

    await query.edit_message_text(
        text=f"⚡ {round_name.capitalize()} раунд (Блиц) начался!\n\n"
             f"Ваши темы:\n{themes_text}\n\n"
             f"⏳ У вас 1 минута на все 6 тем...",
        parse_mode='HTML'
    )

    # Запуск таймера - передаем chat_id и game_id
    context.job_queue.run_once(
        callback=end_round_callback,
        when=2,
        data={
            'chat_id': query.message.chat_id,
            'game_id': game_id,
            'round_number': round_number,
            'theme_type': 'blitz'
        }
    )


async def end_round_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data

    chat_id = data['chat_id']
    game_id = data['game_id']
    round_number = data['round_number']
    theme_type = data['theme_type']

    type_names = {'owl': "Совы", 'lark': "Жаворонки", 'blitz': "Блиц"}
    type_name = type_names.get(theme_type, "")

    # Если это последний раунд (6-й), показать кнопку "Завершить игру"
    if round_number == 6:
        keyboard = [[InlineKeyboardButton("🏁 Завершить игру", callback_data="finish_game")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⏰ Время вышло! Раунд {round_number} ({type_name}) завершен.\n\n"
                 f"🎉 Поздравляем! Вы завершили все 6 раундов игры!",
            reply_markup=reply_markup
        )
    else:
        # Иначе показать кнопку "Следующий раунд"
        keyboard = [[InlineKeyboardButton("➡️ Следующий раунд", callback_data="next_round")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⏰ Время вышло! Раунд {round_number} ({type_name}) завершен.",
            reply_markup=reply_markup
        )

#Переход к следующему раунду
async def handle_next_round(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if 'round' in context.user_data:
        context.user_data['round'] += 1
    else:
        context.user_data['round'] = 2

    # Показать темы для следующего раунда
    await show_round_themes(update, context)

#Завершение игры после 6 раундов
async def handle_finish_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Получаем номер сессии
    game_number = context.chat_data.get('game_number', '?')

    await query.edit_message_text(
        text=f"🎉 Игра в сессии #{game_number} завершена!\n\n"
             f"Спасибо за участие!\n\n"
             f"Хотите сыграть еще раз?\n"
             f"Используйте /start для выбора действий."
    )

#Отмена текущего действия
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'waiting_for_game_number' in context.user_data:
        context.user_data['waiting_for_game_number'] = False
        await update.message.reply_text("Действие отменено.")
    else:
        await update.message.reply_text("Нечего отменять.")

#Основная функция запуска бота
def main():
    completion_bd.init_db()

    application = Application.builder().token("8481141708:AAHBtJWBC6SqZYjpMWHEpXmYLpDi5Hv2BTw").build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(MessageHandler(filters.Text(["🎮 Новая игровая сессия"]), handle_new_game))
    application.add_handler(MessageHandler(filters.Text(["▶️ Продолжить сессию"]), handle_continue_game))
    application.add_handler(MessageHandler(filters.Text(["📊 Мои сессии"]), handle_my_games))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_game_number_input))
    application.add_handler(CallbackQueryHandler(handle_theme_selection, pattern="^theme_"))
    application.add_handler(CallbackQueryHandler(handle_next_round, pattern="^next_round"))
    application.add_handler(CallbackQueryHandler(handle_blitz_timer_start, pattern="^start_blitz_timer"))
    application.add_handler(CallbackQueryHandler(handle_finish_game, pattern="^finish_game"))

    application.run_polling()


if __name__ == "__main__":
    main()