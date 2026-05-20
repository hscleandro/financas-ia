"""add user_id to payment_methods and audit_log tables

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-19

Adiciona coluna user_id em payment_methods e audit_log com FK para users.

Estratégia payment_methods: similar a categories —
  - Métodos system (is_system=1) permanecem compartilhados (user_id NULL)
  - Métodos custom (is_system=0) pertencem a um usuário específico

Estratégia audit_log:
  - Coluna user_id nullable para compatibilidade com registros antigos
  - Novos registros sempre terão user_id preenchido

DA-027: Isolamento completo de dados por usuário.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ─── payment_methods ───
    cols_pm = {row[1] for row in conn.execute(text("PRAGMA table_info(payment_methods)")).fetchall()}
    if "user_id" not in cols_pm:
        op.execute("ALTER TABLE payment_methods ADD COLUMN user_id INTEGER REFERENCES users(id)")

        # Métodos custom recebem user_id do primeiro usuário
        # Métodos system permanecem com user_id NULL
        op.execute("""
            UPDATE payment_methods
            SET user_id = (SELECT MIN(id) FROM users)
            WHERE is_system = 0
        """)

        op.execute("CREATE INDEX IF NOT EXISTS idx_payment_methods_user_id ON payment_methods(user_id)")

    # ─── audit_log ───
    cols_al = {row[1] for row in conn.execute(text("PRAGMA table_info(audit_log)")).fetchall()}
    if "user_id" not in cols_al:
        op.execute("ALTER TABLE audit_log ADD COLUMN user_id INTEGER REFERENCES users(id)")

        # Audit logs antigos permanecem com user_id NULL (registros históricos)
        # Novos registros serão populados pelo service layer

        op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id)")


def downgrade() -> None:
    # ─── payment_methods ───
    op.execute("""
        CREATE TABLE payment_methods_backup (
            id         INTEGER   PRIMARY KEY AUTOINCREMENT,
            name       TEXT      NOT NULL UNIQUE,
            is_system  INTEGER   NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
        INSERT INTO payment_methods_backup (id, name, is_system, created_at)
        SELECT id, name, is_system, created_at FROM payment_methods
    """)

    op.execute("DROP TABLE payment_methods")
    op.execute("ALTER TABLE payment_methods_backup RENAME TO payment_methods")

    # ─── audit_log ───
    op.execute("""
        CREATE TABLE audit_log_backup (
            id          INTEGER   PRIMARY KEY AUTOINCREMENT,
            operation   TEXT      NOT NULL CHECK(operation IN ('delete', 'update')),
            expense_id  INTEGER   NOT NULL,
            old_data    TEXT      NOT NULL,
            new_data    TEXT      DEFAULT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
        INSERT INTO audit_log_backup (id, operation, expense_id, old_data, new_data, created_at)
        SELECT id, operation, expense_id, old_data, new_data, created_at FROM audit_log
    """)

    op.execute("DROP TABLE audit_log")
    op.execute("ALTER TABLE audit_log_backup RENAME TO audit_log")
