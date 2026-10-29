"""add installment support

Revision ID: 0014
Revises: 0013
"""
from alembic import op
from sqlalchemy import text

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    columns = {row[1] for row in conn.execute(text("PRAGMA table_info(statement_transactions)")).fetchall()}

    if "installment_current" not in columns:
        op.execute("ALTER TABLE statement_transactions ADD COLUMN installment_current INTEGER")
    if "installment_total" not in columns:
        op.execute("ALTER TABLE statement_transactions ADD COLUMN installment_total INTEGER")
    if "original_purchase_date" not in columns:
        op.execute("ALTER TABLE statement_transactions ADD COLUMN original_purchase_date DATE")

    op.execute("""
        CREATE TABLE IF NOT EXISTS installment_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            description TEXT NOT NULL,
            card_last_four TEXT,
            total_parcels INTEGER NOT NULL,
            original_purchase_date DATE,
            amount_cents INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS installment_parcels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES installment_groups(id),
            parcel_number INTEGER NOT NULL,
            reference_date DATE NOT NULL,
            expense_id INTEGER REFERENCES expenses(id),
            statement_transaction_id INTEGER REFERENCES statement_transactions(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(group_id, parcel_number)
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_installment_parcels_group ON installment_parcels(group_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_installment_parcels_expense ON installment_parcels(expense_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_installment_groups_user ON installment_groups(user_id)")


def downgrade() -> None:
    pass
