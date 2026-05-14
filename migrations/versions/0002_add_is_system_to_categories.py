"""add is_system to categories

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-12

Distingue categorias do sistema (imutáveis, is_system=1) das criadas pelo
usuário (is_system=0). As 10 categorias originais são marcadas como sistema.
"""
from alembic import op
from sqlalchemy import text

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {row[1] for row in conn.execute(text("PRAGMA table_info(categories)")).fetchall()}
    if "is_system" not in cols:
        op.execute("ALTER TABLE categories ADD COLUMN is_system INTEGER NOT NULL DEFAULT 0")
        op.execute("UPDATE categories SET is_system = 1")


def downgrade() -> None:
    # SQLite não suporta DROP COLUMN; recria a tabela sem is_system
    op.execute("""
        CREATE TABLE categories_backup (
            id         INTEGER   PRIMARY KEY AUTOINCREMENT,
            name       TEXT      NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("INSERT INTO categories_backup (id, name, created_at) SELECT id, name, created_at FROM categories")
    op.execute("DROP TABLE categories")
    op.execute("ALTER TABLE categories_backup RENAME TO categories")
