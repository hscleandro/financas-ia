import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings

CATEGORIES = [
    "Alimentação", "Transporte", "Moradia", "Saúde", "Lazer",
    "Educação", "Vestuário", "Tecnologia", "Serviços", "Outros",
]

PAYMENT_METHODS = ["dinheiro", "crédito", "débito", "pix", "transferência"]


def get_connection() -> sqlite3.Connection:
    # check_same_thread=False permite uso em múltiplas threads (asyncio)
    # SQLite é thread-safe para leituras, e nosso uso é sequencial por usuário
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def setup_database() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER   PRIMARY KEY AUTOINCREMENT,
                telegram_id BIGINT    NOT NULL UNIQUE,
                name        TEXT,
                is_active   INTEGER   NOT NULL DEFAULT 1,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS categories (
                id          INTEGER   PRIMARY KEY AUTOINCREMENT,
                name        TEXT      NOT NULL,
                is_system   INTEGER   NOT NULL DEFAULT 0,
                user_id     INTEGER   REFERENCES users(id),
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, user_id)
            );

            CREATE TABLE IF NOT EXISTS payment_methods (
                id          INTEGER   PRIMARY KEY AUTOINCREMENT,
                name        TEXT      NOT NULL,
                is_system   INTEGER   NOT NULL DEFAULT 0,
                user_id     INTEGER   REFERENCES users(id),
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, user_id)
            );

            CREATE TABLE IF NOT EXISTS expenses (
                id           INTEGER   PRIMARY KEY AUTOINCREMENT,
                amount       REAL      NOT NULL CHECK(amount > 0 AND amount < 100000),
                description  TEXT      NOT NULL,
                category     TEXT      NOT NULL REFERENCES categories(name),
                method       TEXT      NOT NULL DEFAULT 'dinheiro',
                expense_date DATE      NOT NULL DEFAULT CURRENT_DATE,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hash         TEXT      NOT NULL,
                deleted_at   TIMESTAMP DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER   PRIMARY KEY AUTOINCREMENT,
                operation   TEXT      NOT NULL CHECK(operation IN ('delete', 'update')),
                expense_id  INTEGER   NOT NULL,
                old_data    TEXT      NOT NULL,
                new_data    TEXT      DEFAULT NULL,
                user_id     INTEGER   REFERENCES users(id),
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS income_categories (
                id          INTEGER   PRIMARY KEY AUTOINCREMENT,
                name        TEXT      NOT NULL,
                is_system   INTEGER   NOT NULL DEFAULT 0,
                user_id     INTEGER   REFERENCES users(id),
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, user_id)
            );

            CREATE TABLE IF NOT EXISTS incomes (
                id            INTEGER   PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER   NOT NULL REFERENCES users(id),
                amount        REAL      NOT NULL CHECK(amount > 0 AND amount < 10000000),
                description   TEXT      NOT NULL,
                category      TEXT      NOT NULL REFERENCES income_categories(name),
                income_date   DATE      NOT NULL DEFAULT CURRENT_DATE,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hash          TEXT      NOT NULL,
                deleted_at    TIMESTAMP DEFAULT NULL
            );
        """)

        income_categories = [
            "Salário", "Freela", "Investimentos", "Reembolso", "Outros",
        ]

        for name in income_categories:
            conn.execute(
                "INSERT OR IGNORE INTO income_categories (name, is_system, user_id) VALUES (?, 1, NULL)",
                (name,),
            )

        for name in CATEGORIES:
            conn.execute(
                "INSERT OR IGNORE INTO categories (name, is_system) VALUES (?, 1)", (name,)
            )
        for name in PAYMENT_METHODS:
            conn.execute(
                "INSERT OR IGNORE INTO payment_methods (name, is_system) VALUES (?, 1)", (name,)
            )
        conn.commit()


if __name__ == "__main__":
    setup_database()
    print("Banco de dados criado com sucesso.")
