"""remove unique hash constraint from expenses and incomes

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-26

Remove a constraint UNIQUE da coluna hash em expenses e incomes.
A detecção de duplicatas passa a ser feita pelo service layer,
com confirmação HITL antes de inserir registros idênticos.
"""
from alembic import op
from sqlalchemy import text

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _drop_unique_hash(conn, table_name: str) -> None:
    """Recria a tabela sem a constraint UNIQUE no hash."""
    # SQLite não permite ALTER TABLE DROP CONSTRAINT; recriamos a tabela
    cols = {row[1]: row[2] for row in conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()}

    if "hash" not in cols:
        return

    # Criar tabela temporária com o novo schema
    if table_name == "expenses":
        op.execute(f"""
            CREATE TABLE {table_name}_new (
                id           INTEGER   PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER   NOT NULL REFERENCES users(id),
                amount       REAL      NOT NULL CHECK(amount > 0 AND amount < 100000),
                description  TEXT      NOT NULL,
                category     TEXT      NOT NULL REFERENCES categories(name),
                method       TEXT      NOT NULL DEFAULT 'dinheiro',
                expense_date DATE      NOT NULL DEFAULT CURRENT_DATE,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hash         TEXT      NOT NULL,
                deleted_at   TIMESTAMP DEFAULT NULL
            )
        """)
    else:  # incomes
        op.execute(f"""
            CREATE TABLE {table_name}_new (
                id            INTEGER   PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER   NOT NULL REFERENCES users(id),
                amount        REAL      NOT NULL CHECK(amount > 0 AND amount < 10000000),
                description   TEXT      NOT NULL,
                category      TEXT      NOT NULL REFERENCES income_categories(name),
                income_date   DATE      NOT NULL DEFAULT CURRENT_DATE,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hash          TEXT      NOT NULL,
                deleted_at    TIMESTAMP DEFAULT NULL
            )
        """)

    # Copiar dados
    op.execute(f"""
        INSERT INTO {table_name}_new (
            id, user_id, amount, description, category,
            {'method, expense_date' if table_name == 'expenses' else 'income_date'},
            created_at, hash, deleted_at
        )
        SELECT
            id, user_id, amount, description, category,
            {'method, expense_date' if table_name == 'expenses' else 'income_date'},
            created_at, hash, deleted_at
        FROM {table_name}
    """)

    op.execute(f"DROP TABLE {table_name}")
    op.execute(f"ALTER TABLE {table_name}_new RENAME TO {table_name}")

    # Recriar índices úteis
    op.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_user_id ON {table_name}(user_id)")
    if table_name == "expenses":
        op.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_expense_date ON {table_name}(expense_date)")
    else:
        op.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_income_date ON {table_name}(income_date)")
    op.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_category ON {table_name}(category)")


def upgrade() -> None:
    conn = op.get_bind()
    tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}

    if "expenses" in tables:
        _drop_unique_hash(conn, "expenses")
    if "incomes" in tables:
        _drop_unique_hash(conn, "incomes")


def downgrade() -> None:
    # Recriar com UNIQUE hash (perde duplicatas se houver)
    conn = op.get_bind()
    tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}

    if "expenses" in tables:
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
            INSERT INTO expenses_new (id, user_id, amount, description, category, method, expense_date, created_at, hash, deleted_at)
            SELECT id, user_id, amount, description, category, method, expense_date, created_at, hash, deleted_at FROM expenses
        """)
        op.execute("DROP TABLE expenses")
        op.execute("ALTER TABLE expenses_new RENAME TO expenses")

    if "incomes" in tables:
        op.execute("""
            CREATE TABLE incomes_new (
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
        op.execute("""
            INSERT INTO incomes_new (id, user_id, amount, description, category, income_date, created_at, hash, deleted_at)
            SELECT id, user_id, amount, description, category, income_date, created_at, hash, deleted_at FROM incomes
        """)
        op.execute("DROP TABLE incomes")
        op.execute("ALTER TABLE incomes_new RENAME TO incomes")
