import sqlite3
import os
DB_NAME = "sovpadenie_test_function.db"
def create_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.executescript('''CREATE TABLE "Blitz" (
                    "blitzid"	INTEGER,
                    "theme"	TEXT NOT NULL UNIQUE,
                    "difficult"	INTEGER DEFAULT 0,
                    PRIMARY KEY("blitzid" AUTOINCREMENT)
                );
                    CREATE TABLE "Larks" (
                    "larkid"	INTEGER,
                    "theme"	TEXT NOT NULL UNIQUE,
                    "difficult"	INTEGER DEFAULT 0,
                    PRIMARY KEY("larkid" AUTOINCREMENT)
                );
                    CREATE TABLE "Owls" (
                    "owlid"	INTEGER,
                    "theme"	TEXT NOT NULL UNIQUE,
                    "difficult"	INTEGER DEFAULT 0,
                    PRIMARY KEY("owlid" AUTOINCREMENT)
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
            if table_name == 'sqlite_sequence':
                continue
            cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
            count = cursor.fetchone()[0]
            if count > 0:
                print(f"В таблице {table_name} есть данные ({count} записей).")
                return True

        print("Все таблицы пусты.")
        return False

    except sqlite3.Error as e:
        print(f"Ошибка при работе с БД: {e}")
        return False
    finally:
        if conn:
            conn.close()



init_db()