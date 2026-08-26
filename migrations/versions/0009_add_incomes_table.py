"""add incomes table

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-26

Cria a tabela incomes para registro de ganhos/receitas,
com estrutura similar a expenses, mas sem método de pagamento.
"""
from alembic import op
from sqlalchemy import text

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}

    if "incomes" not in tables:
        op.execute("""
            CREATE TABLE incomes (
                id            INTEGER   PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER   NOT NULL REFERENCES users(id),
                amount        REAL      NOT NULL CHECK(amount > 0 AND amount < 10000000),
                description   TEXT      NOT NULL,
                category      TEXT      NOT NULL REFERENCES income_categories(name),
                income_date   DATE      NOT NULL DEFAULT CURRENT_DATE,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hash          TEXT      NOT NULL UNIQUE,
                deleted_at    TIMESTAMP DEFAULT NULL
            )
        """)

        op.execute("CREATE INDEX IF NOT EXISTS idx_incomes_user_id ON incomes(user_id)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_incomes_income_date ON incomes(income_date)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_incomes_category ON incomes(category)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS incomes")
