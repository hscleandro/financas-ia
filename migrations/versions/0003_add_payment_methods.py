"""add payment_methods table and remove method CHECK from expenses

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-12

Remove CHECK(method IN (...)) de expenses — SQLite não suporta DROP CONSTRAINT,
então a tabela é recriada. Adiciona payment_methods com is_system para distinguir
métodos do sistema dos criados pelo usuário.
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

PAYMENT_METHODS = ["dinheiro", "crédito", "débito", "pix", "transferência"]


def upgrade() -> None:
    # 1. Cria tabela payment_methods
    op.execute("""
        CREATE TABLE IF NOT EXISTS payment_methods (
            id          INTEGER   PRIMARY KEY AUTOINCREMENT,
            name        TEXT      NOT NULL UNIQUE,
            is_system   INTEGER   NOT NULL DEFAULT 0,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    for method in PAYMENT_METHODS:
        op.execute(
            f"INSERT OR IGNORE INTO payment_methods (name, is_system) VALUES ('{method}', 1)"
        )

    # 2. Recria expenses sem CHECK(method IN (...))
    # SQLite não suporta DROP CONSTRAINT — tabela recriada via rename
    op.execute("""
        CREATE TABLE expenses_new (
            id           INTEGER   PRIMARY KEY AUTOINCREMENT,
            amount       REAL      NOT NULL CHECK(amount > 0 AND amount < 100000),
            description  TEXT      NOT NULL,
            category     TEXT      NOT NULL REFERENCES categories(name),
            method       TEXT      NOT NULL DEFAULT 'dinheiro',
            expense_date DATE      NOT NULL DEFAULT CURRENT_DATE,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            hash         TEXT      NOT NULL UNIQUE,
            deleted_at   TIMESTAMP DEFAULT NULL
        )
    """)
    op.execute("INSERT INTO expenses_new SELECT * FROM expenses")
    op.execute("DROP TABLE expenses")
    op.execute("ALTER TABLE expenses_new RENAME TO expenses")


def downgrade() -> None:
    # Recria expenses com CHECK constraint original
    op.execute("""
        CREATE TABLE expenses_old (
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
        )
    """)
    op.execute("INSERT INTO expenses_old SELECT * FROM expenses")
    op.execute("DROP TABLE expenses")
    op.execute("ALTER TABLE expenses_old RENAME TO expenses")
    op.execute("DROP TABLE IF EXISTS payment_methods")
