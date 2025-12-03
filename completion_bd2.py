import sqlite3
import os
import pandas as pd
import numpy as np
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

DB_NAME = "themes2.db"


def create_db():
    """Создание структуры базы данных"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS Blitz (
            blitzid INTEGER PRIMARY KEY AUTOINCREMENT,
            theme TEXT NOT NULL UNIQUE,
            difficult INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS Larks (
            larkid INTEGER PRIMARY KEY AUTOINCREMENT,
            theme TEXT NOT NULL UNIQUE,
            difficult INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS Owls (
            owlid INTEGER PRIMARY KEY AUTOINCREMENT,
            theme TEXT NOT NULL UNIQUE,
            difficult INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS Games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_number TEXT NOT NULL UNIQUE,
            username TEXT NOT NULL,
            finished INTEGER DEFAULT 0,
            current_round INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS register (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            blitz_id INTEGER,
            lark_id INTEGER,
            owl_id INTEGER,
            FOREIGN KEY(game_id) REFERENCES Games(id),
            FOREIGN KEY(blitz_id) REFERENCES Blitz(blitzid),
            FOREIGN KEY(lark_id) REFERENCES Larks(larkid),
            FOREIGN KEY(owl_id) REFERENCES Owls(owlid)
        );
    ''')
    conn.commit()
    conn.close()


def init_db():
    """Инициализация базы данных"""
    create_db()

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Проверяем, есть ли данные в таблицах тем
        for table in ['Blitz', 'Larks', 'Owls']:
            cursor.execute(f"SELECT COUNT(*) FROM {table};")
            count = cursor.fetchone()[0]
            if count == 0:
                print(f"Таблица {table} пуста, загружаем данные из Excel...")

                # Определяем правильное имя столбца для пометки
                mark_col = normalize_string(table)
                success = insert_data(table, 'theme', mark_col, 'difficult')
                if not success:
                    print(f"Не удалось загрузить данные для таблицы {table}. Добавляем тестовые данные...")
                    add_test_data_for_table(table, cursor)
                else:
                    cursor.execute(f"SELECT COUNT(*) FROM {table};")
                    new_count = cursor.fetchone()[0]
                    print(f"Добавлено {new_count} тем в таблицу {table}")

        conn.commit()
        conn.close()
        print("База данных инициализирована успешно")
        return True

    except Exception as e:
        print(f"Ошибка при инициализации БД: {e}")
        return False


def normalize_string(s: str) -> str:
    """Нормализация названия таблицы для получения имени столбца"""
    s = s.lower()
    if s.endswith('s'):
        s = s[:-1]
    return s


def insert_data(table_name: str, theme_col: str, mark_col: str, diff_col: str) -> bool:
    """Добавление данных из Excel файла"""
    try:
        # Проверяем существование файла
        excel_path = os.getenv('THEMES_EXCEL_PATH', 'темы для совпадений.xlsx')
        if not os.path.exists(excel_path):
            print(f"Файл '{excel_path}' не найден")
            return False

        # Чтение Excel-файла
        try:
            df = pd.read_excel(excel_path, sheet_name='Лист1')
            print(f"Файл успешно загружен. Столбцы: {df.columns.tolist()}")
        except Exception as e:
            print(f"Ошибка при чтении Excel файла: {e}")
            return False

        # Проверяем наличие необходимых столбцов
        required_columns = [theme_col, mark_col]
        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            print(f"В файле отсутствуют столбцы: {missing_columns}")
            return False

        # Если столбца diff_col нет, создаем его с нулями
        if diff_col not in df.columns:
            df[diff_col] = 0
            print(f"Столбец '{diff_col}' не найден, создан со значением 0 по умолчанию")

        # Подключение к базе данных
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        added_count = 0
        skipped_count = 0

        for index, row in df.iterrows():
            try:
                # Получаем значения из строки
                theme_value = row.get(theme_col)
                mark_value = row.get(mark_col)
                diff_value = row.get(diff_col, 0)  # По умолчанию 0

                # Проверяем на NaN и пропускаем пустые значения
                if pd.isna(theme_value) or pd.isna(mark_value):
                    skipped_count += 1
                    continue

                # Преобразуем в строку и очищаем
                theme_str = str(theme_value).strip()
                mark_str = str(mark_value).strip()

                # Проверяем, отмечена ли тема для этой категории
                if mark_str == '+':
                    # Обрабатываем сложность
                    if pd.isna(diff_value):
                        difficult = 0
                    else:
                        # Пробуем преобразовать в int
                        try:
                            difficult = int(float(diff_value))
                        except (ValueError, TypeError):
                            difficult = 0

                    # Добавляем тему в базу
                    try:
                        cursor.execute(
                            f'INSERT OR IGNORE INTO "{table_name}" (theme, difficult) VALUES (?, ?)',
                            (theme_str, difficult)
                        )
                        if cursor.rowcount > 0:
                            added_count += 1
                    except sqlite3.IntegrityError:
                        # Тема уже существует, пропускаем
                        pass
                    except Exception as e:
                        print(f"Ошибка при вставке темы '{theme_str}': {e}")
            except Exception as e:
                skipped_count += 1
                print(f"Ошибка при обработке строки {index}: {e}")
                continue

        conn.commit()
        conn.close()

        print(f"Таблица {table_name}: добавлено {added_count} тем, пропущено {skipped_count} строк")
        return added_count > 0

    except Exception as e:
        print(f"Ошибка в функции insert_data: {e}")
        return False


def add_test_data_for_table(table_name: str, cursor):
    """Добавление тестовых данных для конкретной таблицы"""
    test_data = {
        'Blitz': [
            ("Фильмы про супергероев", 0),
            ("Столицы мира", 0),
            ("Химические элементы", 1),
            ("Великие художники", 1),
            ("Породы собак", 0),
            ("Виды спорта", 0),
            ("Программирование", 1),
            ("Литературные жанры", 0)
        ],
        'Larks': [
            ("Фрукты и овощи", 0),
            ("Транспорт", 0),
            ("Музыкальные инструменты", 0),
            ("Профессии", 0),
            ("Архитектурные стили", 1),
            ("Философские течения", 1),
            ("Страны Азии", 0),
            ("Научные открытия", 1)
        ],
        'Owls': [
            ("Города России", 0),
            ("Мультфильмы Disney", 0),
            ("Исторические события", 1),
            ("Кухни мира", 0),
            ("Великие ученые", 1),
            ("Животные Африки", 0),
            ("IT-компании", 1),
            ("Виды искусства", 0)
        ]
    }

    if table_name in test_data:
        for theme, diff in test_data[table_name]:
            try:
                cursor.execute(
                    f'INSERT OR IGNORE INTO "{table_name}" (theme, difficult) VALUES (?, ?)',
                    (theme, diff)
                )
            except Exception as e:
                print(f"Ошибка при добавлении тестовой темы '{theme}': {e}")
        print(f"Добавлены тестовые данные для таблицы {table_name}")


def add_test_data():
    """Добавление тестовых данных для проверки"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Добавляем тестовые данные для каждой таблицы
    for table_name in ['Blitz', 'Larks', 'Owls']:
        add_test_data_for_table(table_name, cursor)

    conn.commit()
    conn.close()
    print("Тестовые данные добавлены успешно")


if __name__ == "__main__":
    print("Инициализация базы данных...")
    if init_db():
        # Проверяем, есть ли темы в базе
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        for table in ['Blitz', 'Larks', 'Owls']:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"Тем в таблице {table}: {count}")

        conn.close()

        # Если какая-то таблица пуста, добавляем тестовые данные
        any_empty = False
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        for table in ['Blitz', 'Larks', 'Owls']:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            if count == 0:
                any_empty = True
                break
        conn.close()

        if any_empty:
            print("Некоторые таблицы пусты, добавляем тестовые данные...")
            add_test_data()
    else:
        print("Ошибка инициализации базы данных")