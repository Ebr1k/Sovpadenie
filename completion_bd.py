import sqlite3
import os
import pandas as pd
import openpyxl
DB_NAME = "sovpadenie_main.db"
def create_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.executescript('''CREATE TABLE Blitz (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            theme TEXT NOT NULL UNIQUE,
            difficult BOOLEAN DEFAULT 0 CHECK (difficult IN (0, 1))
        );
        
        CREATE TABLE Larks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            theme TEXT NOT NULL UNIQUE,
            difficult BOOLEAN DEFAULT 0 CHECK (difficult IN (0, 1))
        );
        
        CREATE TABLE Owls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            theme TEXT NOT NULL UNIQUE,
            difficult BOOLEAN DEFAULT 0 CHECK (difficult IN (0, 1))
        );
        
        CREATE TABLE Games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_number INTEGER NOT NULL UNIQUE,
            username TEXT NOT NULL
        );
        
        CREATE TABLE Register (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            blitz_id INTEGER,
            lark_id INTEGER,
            owl_id INTEGER,
            FOREIGN KEY(game_id) REFERENCES Games(id),
            FOREIGN KEY(blitz_id) REFERENCES Blitz(id),
            FOREIGN KEY(lark_id) REFERENCES Larks(id),
            FOREIGN KEY(owl_id) REFERENCES Owls(id)
        );''')
    conn.commit()
    conn.close()

def init_db():
    if not os.path.exists(DB_NAME):
        create_db()
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Проверяем существование таблиц
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()

        if not tables:
            create_db()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()

        # Проверяем, есть ли данные в какой-либо таблице
        for table in tables:
            table_name = table[0]
            if table_name == 'sqlite_sequence' or table_name == 'Games' or table_name == 'Register':
                continue
            cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
            count = cursor.fetchone()[0]
            if count == 0:
                mark_col = normalize_string(table_name)
                insert_data(table_name, 'theme', mark_col, 'difficult')


    except sqlite3.Error as e:
        print(f"Ошибка при работе с БД: {e}")
        return False
    finally:
        if conn:
            conn.close()

def normalize_string(s: str) -> str:
    s = s.lower()
    if s.endswith('s'):
        s = s[:-1]
    return s

# Функция для добавления данных в таблицы
def insert_data(table_name, theme_col, mark_col, diff_col):
    # Чтение Excel-файла
    df = pd.read_excel('темы для совпадений.xlsx', sheet_name='Лист1')

    # Подключение к базе данных
    conn = sqlite3.connect(DB_NAME)  # Укажите имя вашей БД
    cursor = conn.cursor()
    for _, row in df.iterrows():
        theme = row[theme_col]
        mark = row[mark_col]
        difficult = row['difficult']
        if difficult == '+':
            difficult = 1
        else:
            difficult = 0
        if mark == '+':
            try:
                cursor.execute(
                    f'INSERT OR IGNORE INTO "{table_name}" (theme, difficult) VALUES (?, ?)',
                    (theme, difficult)
                )
            except sqlite3.IntegrityError:
                continue
    # Сохраняем изменения и закрываем соединение
    conn.commit()
    conn.close()
