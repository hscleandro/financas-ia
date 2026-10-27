"""add review fields to statement_transactions

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-27

Adiciona campos para aprovação individual de lançamentos, categoria
selecionada/sugerida e data de revisão. Atualiza os status possíveis.
"""
from alembic import op
from sqlalchemy import text

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {row[1]: row[2] for row in conn.execute(text("PRAGMA table_info(statement_transactions)")).fetchall()}

    if "selected_category" not in cols:
        op.execute("ALTER TABLE statement_transactions ADD COLUMN selected_category TEXT")
    if "reviewed_at" not in cols:
        op.execute("ALTER TABLE statement_transactions ADD COLUMN reviewed_at TIMESTAMP")

    # Recria tabela para atualizar CHECK de status (SQLite não permite ALTER CHECK)
    op.execute("""
        CREATE TABLE statement_transactions_new (
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
            selected_category TEXT,
            status            TEXT      NOT NULL DEFAULT 'pending'
                              CHECK(status IN ('pending', 'matched', 'approved', 'inserted', 'ignored', 'rejected')),
            reviewed_at       TIMESTAMP,
            created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
        INSERT INTO statement_transactions_new (
            id, statement_id, card_holder, card_last_four, transaction_date,
            description, amount_cents, installment_info, raw_line,
            matched_expense_id, selected_category, status, reviewed_at, created_at
        )
        SELECT
            id, statement_id, card_holder, card_last_four, transaction_date,
            description, amount_cents, installment_info, raw_line,
            matched_expense_id, selected_category, status, reviewed_at, created_at
        FROM statement_transactions
    """)

    op.execute("DROP TABLE statement_transactions")
    op.execute("ALTER TABLE statement_transactions_new RENAME TO statement_transactions")
    op.execute("CREATE INDEX IF NOT EXISTS idx_statement_transactions_statement_id ON statement_transactions(statement_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_statement_transactions_transaction_date ON statement_transactions(transaction_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_statement_transactions_status ON statement_transactions(status)")


def downgrade() -> None:
    conn = op.get_bind()
    cols = {row[1]: row[2] for row in conn.execute(text("PRAGMA table_info(statement_transactions)")).fetchall()}

    op.execute("""
        CREATE TABLE statement_transactions_new (
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
        INSERT INTO statement_transactions_new (
            id, statement_id, card_holder, card_last_four, transaction_date,
            description, amount_cents, installment_info, raw_line,
            matched_expense_id, status, created_at
        )
        SELECT
            id, statement_id, card_holder, card_last_four, transaction_date,
            description, amount_cents, installment_info, raw_line,
            matched_expense_id, status, created_at
        FROM statement_transactions
    """)

    op.execute("DROP TABLE statement_transactions")
    op.execute("ALTER TABLE statement_transactions_new RENAME TO statement_transactions")
    op.execute("CREATE INDEX IF NOT EXISTS idx_statement_transactions_statement_id ON statement_transactions(statement_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_statement_transactions_transaction_date ON statement_transactions(transaction_date)")
