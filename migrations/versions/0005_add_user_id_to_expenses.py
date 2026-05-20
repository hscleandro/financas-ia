"""add user_id to expenses table

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-19

Adiciona coluna user_id em expenses com FK para users.
Escopo de isolamento: cada gasto pertence a um usuário específico.

IMPORTANTE: Migration assume que existe pelo menos 1 usuário na tabela users.
Para DBs em desenvolvimento/testes sem dados, criar usuário dummy antes de rodar.

DA-027: Todas as tabelas recebem user_id para isolamento multi-tenant.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Verifica se coluna já existe (idempotência)
    cols = {row[1] for row in conn.execute(text("PRAGMA table_info(expenses)")).fetchall()}
    if "user_id" in cols:
        return  # Já aplicado

    # SQLite não suporta ADD COLUMN com NOT NULL + FK diretamente
    # Estratégia: adicionar como nullable, popular, tornar NOT NULL via recriação

    # 1. Adiciona coluna nullable
    op.execute("ALTER TABLE expenses ADD COLUMN user_id INTEGER")

    # 2. Popular com user_id=1 (assumindo que existe pelo menos 1 usuário)
    # Em produção, isso seria um migration de dados mais sofisticado
    op.execute("UPDATE expenses SET user_id = (SELECT MIN(id) FROM users)")

    # 3. Recria tabela com NOT NULL + FK
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
            hash         TEXT      NOT NULL UNIQUE,
            deleted_at   TIMESTAMP DEFAULT NULL
        )
    """)

    op.execute("""
        INSERT INTO expenses_new
        SELECT id, user_id, amount, description, category, method,
               expense_date, created_at, hash, deleted_at
        FROM expenses
    """)

    op.execute("DROP TABLE expenses")
    op.execute("ALTER TABLE expenses_new RENAME TO expenses")

    # Índice para performance de queries por usuário
    op.execute("CREATE INDEX IF NOT EXISTS idx_expenses_user_id ON expenses(user_id)")


def downgrade() -> None:
    # Remove user_id recriando tabela
    op.execute("""
        CREATE TABLE expenses_old (
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

    op.execute("""
        INSERT INTO expenses_old
        SELECT id, amount, description, category, method,
               expense_date, created_at, hash, deleted_at
        FROM expenses
    """)

    op.execute("DROP TABLE expenses")
    op.execute("ALTER TABLE expenses_old RENAME TO expenses")
