import sqlite3
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import asyncio
import completion_bd

# Настройки базы данных
DB_NAME = "themes.db"


#def init_db():
#    conn = sqlite3.connect(DB_NAME)
#    cursor = conn.cursor()
#    cursor.execute('''CREATE TABLE IF NOT EXISTS themes
#                     (id INTEGER PRIMARY KEY,
#                      category TEXT NOT NULL,
#                      theme_text TEXT NOT NULL,
#                      used INTEGER DEFAULT 0)''')
#    conn.commit()
#    conn.close()


def get_themes(category, count=2):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, theme_text FROM themes WHERE category = ? AND used = 0 LIMIT ?",
                   (category, count))
    themes = cursor.fetchall()
    conn.close()
    return themes


def mark_theme_used(theme_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE themes SET used = 1 WHERE id = ?", (theme_id,))
    conn.commit()
    conn.close()


def reset_all_themes():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE themes SET used = 0")
    conn.commit()
    conn.close()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_all_themes()
    context.user_data['round'] = 1
    await show_round_themes(update, context)


async def show_round_themes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    round_number = context.user_data['round']

    if round_number > 6:
        await update.message.reply_text("Игра завершена!")
        return

    # Определяем категорию для раунда
    if round_number <= 2:
        category = 'match'
    elif round_number <= 4:
        category = 'different'
    else:
        category = 'blitz'

    themes = get_themes(category)

    if len(themes) < 2:
        await update.message.reply_text("Недостаточно тем в базе данных!")
        return

    keyboard = [
        [InlineKeyboardButton(themes[0][1], callback_data=f"theme_{themes[0][0]}"),
         InlineKeyboardButton(themes[1][1], callback_data=f"theme_{themes[1][1]}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Раунд {round_number}. Выберите тему:",
        reply_markup=reply_markup
    )


async def handle_theme_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    theme_id = int(query.data.split('_')[1])
    mark_theme_used(theme_id)

    await query.edit_message_text(text=f"Начало раунда! У вас 1 минута...")

    # Запускаем таймер
    context.job_queue.run_once(
        callback=end_round,
        when=60,
        data=query.message.chat_id
    )


async def end_round(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data

    keyboard = [[InlineKeyboardButton("Следующий раунд", callback_data="next_round")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=chat_id,
        text="Время вышло!",
        reply_markup=reply_markup
    )


async def handle_next_round(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['round'] += 1
    await show_round_themes(update, context)


def main():
    completion_bd.init_db()

    application = Application.builder().token("8481141708:AAHBtJWBC6SqZYjpMWHEpXmYLpDi5Hv2BTw").build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_theme_selection, pattern="^theme_"))
    application.add_handler(CallbackQueryHandler(handle_next_round, pattern="^next_round"))

    application.run_polling()


if __name__ == "__main__":
    main()