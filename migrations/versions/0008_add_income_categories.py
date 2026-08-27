"""add income_categories table

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-26

Cria a tabela income_categories para categorias de ganho/receita,
separada de categories (despesas).

Estratégia:
  - Categorias system (is_system=1) são compartilhadas (user_id NULL)
  - Categorias custom (is_system=0) pertencem a um usuário específico
"""
from alembic import op
from sqlalchemy import text

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Criar tabela income_categories se não existir
    tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}

    if "income_categories" not in tables:
        op.execute("""
            CREATE TABLE income_categories (
                id          INTEGER   PRIMARY KEY AUTOINCREMENT,
                name        TEXT      NOT NULL,
                is_system   INTEGER   NOT NULL DEFAULT 0,
                user_id     INTEGER   REFERENCES users(id),
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, user_id)
            )
        """)

        op.execute("CREATE INDEX IF NOT EXISTS idx_income_categories_user_id ON income_categories(user_id)")

        # Seeds system
        seeds = [
            "Salário",
            "Freela",
            "Investimentos",
            "Reembolso",
            "Outros",
        ]
        for name in seeds:
            op.execute(
                f"INSERT OR IGNORE INTO income_categories (name, is_system, user_id) VALUES ('{name}', 1, NULL)"
            )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS income_categories")
