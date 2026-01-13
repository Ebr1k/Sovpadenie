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


def get_themes_for_game(game_id, category, count=2):
    """Получить темы для конкретной игры (учитывая уже использованные)"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    theme_id = category + "_id"
    # Получаем ID уже использованных тем в этой игре
    cursor.execute("""
        SELECT ? FROM register 
        WHERE game_id = ?
    """, (theme_id, game_id,))
    used_theme_ids = []
    used_themes = cursor.fetchall()
    """ for row in cursor.fetchall():
        if row[0]: used_theme_ids.append(row[0])
        if row[1]: used_theme_ids.append(row[1])
        if row[2]: used_theme_ids.append(row[2])"""

    # Если есть использованные темы, исключаем их
    # if used_theme_ids:
    #     placeholders = ','.join('?' * len(used_theme_ids))
    #     cursor.execute(f"""
    #         SELECT id, theme_text FROM themes
    #         WHERE category = ? AND used = 0
    #         AND id NOT IN ({placeholders})
    #         LIMIT ?
    #     """, (category, *used_theme_ids, count))
    # else:
    #     cursor.execute("""
    #         SELECT id, theme_text FROM themes
    #         WHERE category = ? AND used = 0
    #         LIMIT ?
    #     """, (category, count))


    themes = cursor.fetchall()
    conn.close()
    return themes


def add_theme_to_game(game_id, theme_id, theme_type):
    """Добавить тему в регистр игры"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Определяем столбец для типа темы
    column_map = {'match': 'lark_id', 'different': 'owl_id', 'blitz': 'blitz_id'}
    column = column_map.get(theme_type)

    if column:
        # Ищем существующую запись для текущего раунда
        cursor.execute(f"SELECT id FROM register WHERE game_id = ? AND {column} IS NULL LIMIT 1", (game_id,))
        existing = cursor.fetchone()

        if existing:
            # Обновляем существующую запись
            cursor.execute(f"UPDATE register SET {column} = ? WHERE id = ?", (theme_id, existing[0]))
        else:
            # Создаем новую запись
            insert_data = {'game_id': game_id}
            insert_data[column] = theme_id
            columns = ', '.join(insert_data.keys())
            placeholders = ', '.join('?' * len(insert_data))
            cursor.execute(f"INSERT INTO register ({columns}) VALUES ({placeholders})", tuple(insert_data.values()))

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
        ["▶️ Продолжить игру"] if active_game else [],
        ["📊 Мои игры"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

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

            context.user_data['count_round'] = round_count  # Максимум 6 раундов

            await update.message.reply_text(
                f"✅ Игровая сессия #{game_number} загружена!\n"
                f"Сыграно тем {context.user_data['count_round']}"
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
    if round_number == 1 or 3:
        category = 'owl'
        theme_type = 'match'
    elif round_number == 2 or 4:
        category = 'lark'
        theme_type = 'different'
    else:
        category = 'blitz'
        theme_type = 'blitz'

    # Получаем темы для конкретной игры
    themes = get_themes_for_game(game_id, category)

    if len(themes) < 2:
        await update.message.reply_text("Недостаточно доступных тем для этого раунда!")
        return

    keyboard = [
        [InlineKeyboardButton(themes[0][1], callback_data=f"theme_{themes[0][0]}_{theme_type}"),
         InlineKeyboardButton(themes[1][1], callback_data=f"theme_{themes[1][0]}_{theme_type}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Раунд {round_number}. Выберите тему:",
        reply_markup=reply_markup
    )


async def handle_theme_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора темы (с привязкой к игре)"""
    query = update.callback_query
    await query.answer()

    data_parts = query.data.split('_')
    theme_id = int(data_parts[1])
    theme_type = data_parts[2]  # match, different или blitz

    # Получаем ID текущей игры
    game_id = context.chat_data.get('game_id')
    if not game_id:
        await query.edit_message_text("Ошибка: игра не найдена")
        return

    # Добавляем тему в регистр игры
    add_theme_to_game(game_id, theme_id, theme_type)

    await query.edit_message_text(text=f"Выбрана тема! У вас 1 минута...")

    # Запускаем таймер
    context.job_queue.run_once(
        callback=end_round,
        when=60,
        data=(query.message.chat_id, game_id)
    )


async def end_round(context: ContextTypes.DEFAULT_TYPE):
    """Завершение раунда"""
    job = context.job
    chat_id, game_id = job.data

    # Сохраняем round в контексте пользователя
    if 'round' not in context.user_data:
        context.user_data['round'] = 1
    else:
        context.user_data['round'] += 1

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

    application.run_polling()


if __name__ == "__main__":
    main()