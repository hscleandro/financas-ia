"""Persist statement reviews, snapshots and idempotent batches.

Revision ID: 0013
Revises: 0012
"""
import json
from decimal import Decimal, ROUND_HALF_UP

from alembic import op
from sqlalchemy import text


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _cents(amount):
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _scope_imports(conn):
    columns = {row[1] for row in conn.execute(text("PRAGMA table_info(card_statements)"))}
    global_indexes = set()
    for index in conn.execute(text("PRAGMA index_list(card_statements)")).fetchall():
        name = index[1].replace('"', '""')
        indexed = [row[2] for row in conn.execute(text(f'PRAGMA index_info("{name}")'))]
        if index[2] and indexed == ["file_hash", "card_last_four"]:
            global_indexes.add(index[1])
    if not global_indexes:
        if "review_warnings" not in columns:
            op.execute("ALTER TABLE card_statements ADD COLUMN review_warnings TEXT NOT NULL DEFAULT '[]'")
        return

    schema_objects = conn.execute(text(
        "SELECT name, sql FROM sqlite_master WHERE tbl_name = 'card_statements' "
        "AND type IN ('index', 'trigger') AND sql IS NOT NULL"
    )).fetchall()
    sequence = conn.execute(text("SELECT seq FROM sqlite_sequence WHERE name = 'card_statements'")).scalar() or 0
    op.execute("""
        CREATE TABLE card_statements_0013 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            file_hash TEXT NOT NULL,
            file_name TEXT NOT NULL,
            statement_date DATE,
            due_date DATE,
            total_cents INTEGER,
            card_last_four TEXT,
            card_holder TEXT,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'confirmed', 'failed')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            review_warnings TEXT NOT NULL DEFAULT '[]',
            UNIQUE(user_id, file_hash, card_last_four)
        )
    """)
    warnings = "review_warnings" if "review_warnings" in columns else "'[]'"
    op.execute(f"""
        INSERT INTO card_statements_0013 (
            id, user_id, file_hash, file_name, statement_date, due_date, total_cents,
            card_last_four, card_holder, status, created_at, review_warnings
        ) SELECT id, user_id, file_hash, file_name, statement_date, due_date, total_cents,
                 card_last_four, card_holder, status, created_at, {warnings}
          FROM card_statements
    """)
    op.execute("DROP TABLE card_statements")
    op.execute("ALTER TABLE card_statements_0013 RENAME TO card_statements")
    conn.execute(text("UPDATE sqlite_sequence SET seq = MAX(seq, :seq) WHERE name = 'card_statements'"), {"seq": sequence})
    for name, sql in schema_objects:
        if name not in global_indexes:
            op.execute(sql)


def _backfill(conn):
    txs = conn.execute(text("""
        SELECT st.*, cs.user_id FROM statement_transactions st
        JOIN card_statements cs ON cs.id = st.statement_id
        LEFT JOIN statement_review_items ri ON ri.tx_id = st.id
        WHERE ri.tx_id IS NULL ORDER BY st.id
    """)).mappings().all()
    for tx in txs:
        expense = conn.execute(text("SELECT * FROM expenses WHERE id = :id AND user_id = :user"),
                               {"id": tx["matched_expense_id"], "user": tx["user_id"]}).mappings().first()
        original = dict(expense) if expense else None
        warnings = []
        category = tx["selected_category"]
        recovered, audits = [], []
        decision = {"approved": "approved", "inserted": "approved", "ignored": "ignored", "rejected": "ignored"}.get(tx["status"], "pending")
        section = "new" if tx["status"] == "inserted" else (
            "matched" if tx["matched_expense_id"] or tx["status"] in ("approved", "matched") else "new"
        )
        if section == "matched" and (tx["status"] == "approved" or (expense and expense["statement_id"] == tx["statement_id"])):
            audits = conn.execute(text("""
                SELECT old_data, new_data FROM audit_log WHERE expense_id = :id
                AND operation = 'update' AND (user_id = :user OR user_id IS NULL)
            """), {"id": tx["matched_expense_id"], "user": tx["user_id"]}).mappings().all()
            for audit in audits:
                try:
                    old, new = json.loads(audit["old_data"]), json.loads(audit["new_data"] or "null")
                    if (isinstance(old, dict) and isinstance(new, dict)
                            and old.get("id") == new.get("id") == tx["matched_expense_id"]
                            and new.get("user_id") == tx["user_id"]
                            and old.get("user_id", tx["user_id"]) == tx["user_id"]
                            and "statement_id" in old and old["statement_id"] != tx["statement_id"]
                            and new.get("statement_id") == tx["statement_id"]
                            and new.get("description") == tx["description"]
                            and new.get("expense_date") == tx["transaction_date"]
                            and _cents(new["amount"]) == tx["amount_cents"]
                            and isinstance(old.get("description"), str)
                            and all(key in old for key in ("expense_date", "amount", "category"))):
                        recovered.append((old, new))
                except (ValueError, TypeError, KeyError, ArithmeticError):
                    continue
            original = recovered[0][0] if len(recovered) == 1 else None
            if original is None:
                warnings.append(f"Descrição original da despesa {tx['matched_expense_id']} indisponível no histórico legado.")
        if tx["status"] == "approved":
            category = None
            applied = [new.get("category") for _, new in recovered]
            if applied and isinstance(applied[0], str) and all(value == applied[0] for value in applied):
                category = applied[0]
            elif (not audits and expense and expense["statement_id"] == tx["statement_id"]
                  and expense["description"] == tx["description"]
                  and expense["expense_date"] == tx["transaction_date"]
                  and _cents(expense["amount"]) == tx["amount_cents"]):
                category = expense["category"]
            valid = conn.execute(text("SELECT name FROM categories WHERE user_id IS NULL OR user_id = :user ORDER BY id"),
                                 {"user": tx["user_id"]}).scalars().all()
            category = next((name for name in valid if isinstance(category, str)
                             and name.casefold() == category.strip().casefold()), None)
            if category is None:
                warnings.append(f"Categoria efetiva da despesa {tx['matched_expense_id']} indisponível no histórico legado.")
        if section != "matched":
            original = None
        snapshot = {
            "id": f"tx:{tx['id']}", "section": section, "tx_id": tx["id"],
            "expense_id": tx["matched_expense_id"], "name": tx["description"],
            "date": str(tx["transaction_date"]), "amount_cents": tx["amount_cents"],
            "category": category, "card_last_four": tx["card_last_four"],
            "installment_info": tx["installment_info"],
            "bank_name": original["description"] if original else None,
            "bank_date": str(original["expense_date"]) if original else None,
            "bank_amount_cents": _cents(original["amount"]) if original else None,
            "bank_category": original["category"] if original else None,
        }
        claim = tx["matched_expense_id"] if decision == "approved" and expense else None
        if claim and conn.execute(text("SELECT 1 FROM statement_review_items WHERE claimed_expense_id = :id"), {"id": claim}).first():
            warnings.append(f"Vínculo legado duplicado para a despesa {claim}; requer conferência.")
            claim = None
        conn.execute(text("""
            INSERT INTO statement_review_items (
                statement_id, item_id, tx_id, expense_id, claimed_expense_id, section,
                decision, category, snapshot, warning, reviewed_at
            ) VALUES (:statement, :item, :tx, :expense, :claim, :section,
                      :decision, :category, :snapshot, :warning, :reviewed)
        """), {"statement": tx["statement_id"], "item": snapshot["id"], "tx": tx["id"],
               "expense": tx["matched_expense_id"], "claim": claim, "section": section,
               "decision": decision, "category": category,
               "snapshot": json.dumps(snapshot, ensure_ascii=False), "warning": " ".join(warnings) or None,
               "reviewed": tx["reviewed_at"]})

    # statement_id sozinho nao comprova uma aprovacao da antiga aba "so no banco".
    banks = conn.execute(text("""
        SELECT e.* FROM expenses e JOIN card_statements cs ON cs.id = e.statement_id AND cs.user_id = e.user_id
        WHERE NOT EXISTS (SELECT 1 FROM statement_transactions st WHERE st.matched_expense_id = e.id)
          AND NOT EXISTS (SELECT 1 FROM statement_review_items ri
                          WHERE ri.statement_id = e.statement_id AND ri.item_id = 'expense:' || e.id)
        ORDER BY e.id
    """)).mappings().all()
    for expense in banks:
        snapshot = {
            "id": f"expense:{expense['id']}", "section": "bank", "tx_id": None,
            "expense_id": expense["id"], "name": expense["description"],
            "date": str(expense["expense_date"]), "amount_cents": _cents(expense["amount"]),
            "category": expense["category"], "card_last_four": expense["card_last_four"],
            "installment_info": None, "bank_name": expense["description"],
            "bank_date": str(expense["expense_date"]), "bank_amount_cents": _cents(expense["amount"]),
            "bank_category": expense["category"],
        }
        conn.execute(text("""
            INSERT INTO statement_review_items (statement_id, item_id, expense_id, section, category, snapshot, warning)
            VALUES (:statement, :item, :expense, 'bank', :category, :snapshot,
                    'Revisão legada sem decisão comprovada; confirme ou ignore a despesa.')
        """), {"statement": expense["statement_id"], "item": snapshot["id"], "expense": expense["id"],
               "category": expense["category"], "snapshot": json.dumps(snapshot, ensure_ascii=False)})


def upgrade() -> None:
    conn = op.get_bind()
    _scope_imports(conn)
    op.execute("""
        CREATE TABLE IF NOT EXISTS statement_review_items (
            statement_id INTEGER NOT NULL REFERENCES card_statements(id),
            item_id TEXT NOT NULL,
            tx_id INTEGER UNIQUE REFERENCES statement_transactions(id),
            expense_id INTEGER REFERENCES expenses(id),
            claimed_expense_id INTEGER UNIQUE REFERENCES expenses(id),
            section TEXT NOT NULL CHECK(section IN ('new', 'matched', 'bank')),
            decision TEXT NOT NULL DEFAULT 'pending' CHECK(decision IN ('pending', 'approved', 'ignored')),
            category TEXT,
            category_edited INTEGER NOT NULL DEFAULT 0,
            snapshot TEXT NOT NULL,
            warning TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            reviewed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(statement_id, item_id),
            CHECK((section = 'bank' AND tx_id IS NULL AND expense_id IS NOT NULL)
                  OR (section IN ('new', 'matched') AND tx_id IS NOT NULL)),
            CHECK(claimed_expense_id IS NULL OR (tx_id IS NOT NULL AND decision != 'ignored'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_statement_reviews_pending ON statement_review_items(statement_id, decision, active)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_card_statements_user_hash ON card_statements(user_id, file_hash)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS statement_review_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            statement_id INTEGER NOT NULL REFERENCES card_statements(id),
            request_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            processed INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, request_id)
        )
    """)
    _backfill(conn)


def downgrade() -> None:
    # Restoring a global unique key or dropping history would lose user data.
    raise ValueError("A migration 0013 não permite downgrade destrutivo do histórico de conciliação.")
