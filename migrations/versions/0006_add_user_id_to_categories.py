"""add user_id to categories table

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-19

Adiciona coluna user_id em categories com FK para users.
Estratégia: categorias system (is_system=1) permanecem compartilhadas (user_id NULL permitido).
Categorias custom (is_system=0) pertencem a um usuário específico.

IMPORTANTE: Migration assume que existe pelo menos 1 usuário na tabela users.

DA-027: Categorias por usuário — seeds is_system=1 replicados na criação de cada usuário.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Verifica se coluna já existe (idempotência)
    cols = {row[1] for row in conn.execute(text("PRAGMA table_info(categories)")).fetchall()}
    if "user_id" in cols:
        return  # Já aplicado

    # Adiciona coluna user_id (nullable para categorias system)
    op.execute("ALTER TABLE categories ADD COLUMN user_id INTEGER REFERENCES users(id)")

    # Categorias criadas por usuário (is_system=0) recebem user_id do primeiro usuário
    # Categorias system (is_system=1) permanecem com user_id NULL (compartilhadas)
    op.execute("""
        UPDATE categories
        SET user_id = (SELECT MIN(id) FROM users)
        WHERE is_system = 0
    """)

    # Índice para performance de queries por usuário
    op.execute("CREATE INDEX IF NOT EXISTS idx_categories_user_id ON categories(user_id)")


def downgrade() -> None:
    # SQLite não suporta DROP COLUMN; recria tabela sem user_id
    op.execute("""
        CREATE TABLE categories_backup (
            id         INTEGER   PRIMARY KEY AUTOINCREMENT,
            name       TEXT      NOT NULL UNIQUE,
            is_system  INTEGER   NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
        INSERT INTO categories_backup (id, name, is_system, created_at)
        SELECT id, name, is_system, created_at FROM categories
    """)

    op.execute("DROP TABLE categories")
    op.execute("ALTER TABLE categories_backup RENAME TO categories")
