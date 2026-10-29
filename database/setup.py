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

            CREATE TABLE IF NOT EXISTS card_statements (
                id           INTEGER   PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER   NOT NULL REFERENCES users(id),
                file_hash    TEXT      NOT NULL,
                file_name    TEXT      NOT NULL,
                statement_date DATE,
                due_date     DATE,
                total_cents  INTEGER,
                card_last_four TEXT,
                card_holder  TEXT,
                status       TEXT      NOT NULL DEFAULT 'pending'
                             CHECK(status IN ('pending', 'confirmed', 'failed')),
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                review_warnings TEXT NOT NULL DEFAULT '[]',
                UNIQUE(user_id, file_hash, card_last_four)
            );

            CREATE TABLE IF NOT EXISTS statement_transactions (
                id                INTEGER   PRIMARY KEY AUTOINCREMENT,
                statement_id      INTEGER   NOT NULL REFERENCES card_statements(id),
                card_holder       TEXT,
                card_last_four    TEXT,
                transaction_date  DATE      NOT NULL,
                description       TEXT      NOT NULL,
                amount_cents      INTEGER   NOT NULL,
                installment_info  TEXT,
                installment_current INTEGER,
                installment_total INTEGER,
                original_purchase_date DATE,
                raw_line          TEXT,
                matched_expense_id INTEGER,
                selected_category TEXT,
                status            TEXT      NOT NULL DEFAULT 'pending'
                                  CHECK(status IN ('pending', 'matched', 'approved', 'inserted', 'ignored', 'rejected')),
                reviewed_at       TIMESTAMP,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS expenses (
                id           INTEGER   PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER   NOT NULL REFERENCES users(id),
                amount       REAL      NOT NULL CHECK(amount > 0 AND amount < 100000),
                description  TEXT      NOT NULL,
                category     TEXT      NOT NULL REFERENCES categories(name),
                method       TEXT      NOT NULL DEFAULT 'dinheiro',
                expense_date DATE      NOT NULL DEFAULT CURRENT_DATE,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hash         TEXT      NOT NULL,
                deleted_at   TIMESTAMP DEFAULT NULL,
                card_last_four TEXT,
                card_holder  TEXT,
                statement_id INTEGER   REFERENCES card_statements(id)
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

            CREATE TABLE IF NOT EXISTS statement_review_items (
                statement_id INTEGER NOT NULL REFERENCES card_statements(id),
                item_id TEXT NOT NULL,
                tx_id INTEGER UNIQUE REFERENCES statement_transactions(id),
                expense_id INTEGER REFERENCES expenses(id),
                claimed_expense_id INTEGER UNIQUE REFERENCES expenses(id),
                section TEXT NOT NULL CHECK(section IN ('new', 'matched', 'bank')),
                decision TEXT NOT NULL DEFAULT 'pending'
                         CHECK(decision IN ('pending', 'approved', 'ignored')),
                category TEXT,
                category_edited INTEGER NOT NULL DEFAULT 0,
                snapshot TEXT NOT NULL,
                warning TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                reviewed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(statement_id, item_id),
                CHECK((section = 'bank' AND tx_id IS NULL AND expense_id IS NOT NULL)
                      OR (section IN ('new', 'matched') AND tx_id IS NOT NULL)),
                CHECK(claimed_expense_id IS NULL
                      OR (tx_id IS NOT NULL AND decision != 'ignored'))
            );

            CREATE INDEX IF NOT EXISTS idx_statement_reviews_pending
            ON statement_review_items(statement_id, decision, active);

            CREATE INDEX IF NOT EXISTS idx_card_statements_user_hash
            ON card_statements(user_id, file_hash);

            CREATE TABLE IF NOT EXISTS statement_review_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                statement_id INTEGER NOT NULL REFERENCES card_statements(id),
                request_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                processed INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, request_id)
            );

            CREATE TABLE IF NOT EXISTS installment_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                description TEXT NOT NULL,
                card_last_four TEXT,
                total_parcels INTEGER NOT NULL,
                original_purchase_date DATE,
                amount_cents INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS installment_parcels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL REFERENCES installment_groups(id),
                parcel_number INTEGER NOT NULL,
                reference_date DATE NOT NULL,
                expense_id INTEGER REFERENCES expenses(id),
                statement_transaction_id INTEGER REFERENCES statement_transactions(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, parcel_number)
            );

            CREATE INDEX IF NOT EXISTS idx_installment_parcels_group
            ON installment_parcels(group_id);

            CREATE INDEX IF NOT EXISTS idx_installment_parcels_expense
            ON installment_parcels(expense_id);

            CREATE INDEX IF NOT EXISTS idx_installment_groups_user
            ON installment_groups(user_id);

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
