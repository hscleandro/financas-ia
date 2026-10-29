"""add card statement tables and card holder fields

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-27

Adiciona tabelas para importação de faturas de cartão (card_statements e
statement_transactions) e campos opcionais em expenses para vínculo com
fatura, titular e final do cartão.
"""
from alembic import op
from sqlalchemy import text

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Tabela de faturas/importações
    op.execute("""
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
            UNIQUE(file_hash, card_last_four)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_card_statements_user_id
        ON card_statements(user_id)
    """)

    # Tabela de transações extraídas da fatura
    op.execute("""
        CREATE TABLE IF NOT EXISTS statement_transactions (
            id                INTEGER   PRIMARY KEY AUTOINCREMENT,
            statement_id      INTEGER   NOT NULL REFERENCES card_statements(id),
            card_holder       TEXT,
            card_last_four    TEXT,
            transaction_date  DATE      NOT NULL,
            description       TEXT      NOT NULL,
            amount_cents      INTEGER   NOT NULL,
            installment_info  TEXT,
            raw_line          TEXT,
            matched_expense_id INTEGER,
            status            TEXT      NOT NULL DEFAULT 'pending'
                              CHECK(status IN ('pending', 'matched', 'inserted', 'ignored')),
            created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_statement_transactions_statement_id
        ON statement_transactions(statement_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_statement_transactions_transaction_date
        ON statement_transactions(transaction_date)
    """)

    # Adiciona colunas à tabela expenses para vínculo com fatura/cartão.
    # Como SQLite tem limitações com ALTER TABLE, usamos recriação apenas se
    # necessário.
    cols = {row[1]: row[2] for row in conn.execute(text("PRAGMA table_info(expenses)")).fetchall()}

    if "card_last_four" not in cols or "card_holder" not in cols or "statement_id" not in cols:
        op.execute("""
            CREATE TABLE expenses_new (
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
            )
        """)

        op.execute("""
            INSERT INTO expenses_new (
                id, user_id, amount, description, category, method,
                expense_date, created_at, hash, deleted_at
            )
            SELECT
                id, user_id, amount, description, category, method,
                expense_date, created_at, hash, deleted_at
            FROM expenses
        """)

        op.execute("DROP TABLE expenses")
        op.execute("ALTER TABLE expenses_new RENAME TO expenses")

        op.execute("CREATE INDEX IF NOT EXISTS idx_expenses_user_id ON expenses(user_id)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_expenses_expense_date ON expenses(expense_date)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_expenses_statement_id ON expenses(statement_id)")


def downgrade() -> None:
    conn = op.get_bind()
    tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}

    if "statement_transactions" in tables:
        op.execute("DROP TABLE statement_transactions")
    if "card_statements" in tables:
        op.execute("DROP TABLE card_statements")

    cols = {row[1]: row[2] for row in conn.execute(text("PRAGMA table_info(expenses)")).fetchall()}
    if "card_last_four" in cols or "card_holder" in cols or "statement_id" in cols:
        op.execute("""
            CREATE TABLE expenses_new (
                id           INTEGER   PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER   NOT NULL REFERENCES users(id),
                amount       REAL      NOT NULL CHECK(amount > 0 AND amount < 100000),
                description  TEXT      NOT NULL,
                category     TEXT      NOT NULL REFERENCES categories(name),
                method       TEXT      NOT NULL DEFAULT 'dinheiro',
                expense_date DATE      NOT NULL DEFAULT CURRENT_DATE,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hash         TEXT      NOT NULL,
                deleted_at   TIMESTAMP DEFAULT NULL
            )
        """)
        op.execute("""
            INSERT INTO expenses_new (
                id, user_id, amount, description, category, method,
                expense_date, created_at, hash, deleted_at
            )
            SELECT
                id, user_id, amount, description, category, method,
                expense_date, created_at, hash, deleted_at
            FROM expenses
        """)
        op.execute("DROP TABLE expenses")
        op.execute("ALTER TABLE expenses_new RENAME TO expenses")
        op.execute("CREATE INDEX IF NOT EXISTS idx_expenses_user_id ON expenses(user_id)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_expenses_expense_date ON expenses(expense_date)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category)")
