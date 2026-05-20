"""add users table for multi-tenant support

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-19

Adiciona tabela users com telegram_id para autenticação multi-tenant.
Preparação para whitelist de usuários autorizados.

DA-027: Multi-tenant whitelist — usuários identificados por telegram_id (BIGINT).
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL: SERIAL = INTEGER AUTOINCREMENT
    # SQLite: INTEGER PRIMARY KEY = AUTOINCREMENT
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER   PRIMARY KEY AUTOINCREMENT,
            telegram_id  BIGINT    NOT NULL UNIQUE,
            name         TEXT,
            is_active    BOOLEAN   NOT NULL DEFAULT TRUE,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS users")
