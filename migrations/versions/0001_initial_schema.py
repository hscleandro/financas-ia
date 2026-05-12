"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-12

Baseline do MVP 1: categories + expenses (com soft delete) + audit_log.
DBs existentes devem ser marcados com: alembic stamp 0001
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

CATEGORIES = [
    "Alimentação", "Transporte", "Moradia", "Saúde", "Lazer",
    "Educação", "Vestuário", "Tecnologia", "Serviços", "Outros",
]


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id          INTEGER   PRIMARY KEY AUTOINCREMENT,
            name        TEXT      NOT NULL UNIQUE,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
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
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER   PRIMARY KEY AUTOINCREMENT,
            operation   TEXT      NOT NULL CHECK(operation IN ('delete', 'update')),
            expense_id  INTEGER   NOT NULL,
            old_data    TEXT      NOT NULL,
            new_data    TEXT      DEFAULT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    for name in CATEGORIES:
        # INSERT OR IGNORE garante idempotência
        op.execute(f"INSERT OR IGNORE INTO categories (name) VALUES ('{name}')")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log")
    op.execute("DROP TABLE IF EXISTS expenses")
    op.execute("DROP TABLE IF EXISTS categories")
