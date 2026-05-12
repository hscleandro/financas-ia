import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings

CATEGORIES = [
    "Alimentação", "Transporte", "Moradia", "Saúde", "Lazer",
    "Educação", "Vestuário", "Tecnologia", "Serviços", "Outros",
]


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def setup_database() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS categories (
                id          INTEGER   PRIMARY KEY AUTOINCREMENT,
                name        TEXT      NOT NULL UNIQUE,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS expenses (
                id           INTEGER   PRIMARY KEY AUTOINCREMENT,
                amount       REAL      NOT NULL CHECK(amount > 0 AND amount < 100000),
                description  TEXT      NOT NULL,
                category     TEXT      NOT NULL REFERENCES categories(name),
                method       TEXT      NOT NULL DEFAULT 'dinheiro'
                             CHECK(method IN ('dinheiro','crédito','débito','pix','transferência')),
                expense_date DATE      NOT NULL DEFAULT CURRENT_DATE,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hash         TEXT      NOT NULL UNIQUE,
                deleted_at   TIMESTAMP DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER   PRIMARY KEY AUTOINCREMENT,
                operation   TEXT      NOT NULL CHECK(operation IN ('delete', 'update')),
                expense_id  INTEGER   NOT NULL,
                old_data    TEXT      NOT NULL,
                new_data    TEXT      DEFAULT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Migração para bancos existentes: adiciona deleted_at se não existir
        try:
            conn.execute("ALTER TABLE expenses ADD COLUMN deleted_at TIMESTAMP DEFAULT NULL")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Coluna já existe

        for name in CATEGORIES:
            conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
        conn.commit()


if __name__ == "__main__":
    setup_database()
    print("Banco de dados criado com sucesso.")
