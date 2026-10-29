"""Migration 0013 uses only synthetic, temporary SQLite databases."""
import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from database.setup import get_connection
from services.statement_service import StatementService


def _config():
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


def _rows(conn, table):
    return [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    import config

    path = tmp_path / "migration-0012.db"
    monkeypatch.setattr(config.settings, "db_path", str(path))
    command.upgrade(_config(), "0012")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO users (telegram_id, name) VALUES (700001, 'Synthetic owner')")
    conn.execute("INSERT INTO users (telegram_id, name) VALUES (700002, 'Other synthetic owner')")
    conn.commit()
    yield conn
    conn.close()


def _statement(conn, file_hash, card="3006", status="pending"):
    return conn.execute(
        """INSERT INTO card_statements (
            user_id, file_hash, file_name, due_date, card_last_four, status, created_at
        ) VALUES (1, ?, 'synthetic.pdf', '2026-10-10', ?, ?, '2026-10-01 12:00:00')""",
        (file_hash, card, status),
    ).lastrowid


def _expense(conn, description, amount, statement_id=None):
    return conn.execute(
        """INSERT INTO expenses (
            user_id, description, amount, category, method, expense_date, hash, statement_id
        ) VALUES (1, ?, ?, 'Outros', 'crédito', '2026-09-10', 'synthetic-hash', ?)""",
        (description, amount, statement_id),
    ).lastrowid


def _tx(conn, statement_id, status, expense_id=None, description="STATEMENT ORIGINAL", cents=5000):
    return conn.execute(
        """INSERT INTO statement_transactions (
            statement_id, description, transaction_date, amount_cents, card_last_four,
            selected_category, status, matched_expense_id, reviewed_at, created_at
        ) VALUES (?, ?, '2026-09-10', ?, '3006', 'Lazer', ?, ?, ?, '2026-10-01 12:00:00')""",
        (statement_id, description, cents, status, expense_id,
         "2026-10-02 10:00:00" if status in ("approved", "inserted", "ignored", "rejected") else None),
    ).lastrowid


def _audit_match(conn, expense_id, statement_id, description="STATEMENT ORIGINAL", old_name="Original Telegram"):
    new = dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone())
    new.update(statement_id=statement_id, description=description)
    old = {**new, "description": old_name, "expense_date": "2026-09-12", "statement_id": None}
    conn.execute(
        """INSERT INTO audit_log (operation, expense_id, old_data, new_data, user_id)
           VALUES ('update', ?, ?, ?, 1)""", (expense_id, json.dumps(old), json.dumps(new))
    )


def test_0013_preserves_0012_states_ids_imports_and_recovers_only_unambiguous_audit(legacy_db):
    conn = legacy_db
    statement_id = _statement(conn, "same-file", status="confirmed")
    other_card = _statement(conn, "same-file", card="2222")
    recoverable = _expense(conn, "STATEMENT ORIGINAL", 50, statement_id)
    unavailable = _expense(conn, "ALREADY OVERWRITTEN", 60, statement_id)
    inserted_expense = _expense(conn, "INSERTED ORIGINAL", 70, statement_id)
    bank_expense = _expense(conn, "LEGACY BANK REVIEW", 90, statement_id)
    approved = _tx(conn, statement_id, "approved", recoverable)
    missing_audit = _tx(conn, statement_id, "approved", unavailable, "ALREADY OVERWRITTEN", 6000)
    duplicate = _tx(conn, statement_id, "approved", recoverable)
    inserted = _tx(conn, statement_id, "inserted", inserted_expense, "INSERTED ORIGINAL", 7000)
    pending = _tx(conn, statement_id, "pending", cents=2000)
    matched = _tx(conn, statement_id, "matched", cents=3000)
    ignored = _tx(conn, statement_id, "ignored", cents=4000)
    rejected = _tx(conn, statement_id, "rejected", cents=4100)
    _audit_match(conn, recoverable, statement_id)
    conn.commit()
    before = {table: _rows(conn, table) for table in ("card_statements", "statement_transactions", "expenses", "audit_log")}
    command.upgrade(_config(), "0013")
    assert [{key: value for key, value in row.items() if key != "review_warnings"}
            for row in _rows(conn, "card_statements")] == before["card_statements"]
    for table in ("statement_transactions", "expenses", "audit_log"):
        assert _rows(conn, table) == before[table]
    reviews = {row["item_id"]: row for row in _rows(conn, "statement_review_items")}
    for tx in (pending, matched):
        assert reviews[f"tx:{tx}"]["decision"] == "pending"
        assert reviews[f"tx:{tx}"]["reviewed_at"] is None
    for tx in (approved, missing_audit, duplicate, inserted):
        assert reviews[f"tx:{tx}"]["decision"] == "approved"
        assert reviews[f"tx:{tx}"]["reviewed_at"] == "2026-10-02 10:00:00"
    for tx in (ignored, rejected):
        assert reviews[f"tx:{tx}"]["decision"] == "ignored"
    recovered = json.loads(reviews[f"tx:{approved}"]["snapshot"])
    assert recovered["name"] == "STATEMENT ORIGINAL"
    assert recovered["bank_name"] == "Original Telegram"
    assert recovered["date"] == "2026-09-10" and recovered["bank_date"] == "2026-09-12"
    assert recovered["expense_id"] == recoverable and recovered["tx_id"] == approved
    assert json.loads(reviews[f"tx:{missing_audit}"]["snapshot"])["bank_name"] is None
    assert "indisponível" in reviews[f"tx:{missing_audit}"]["warning"]
    assert "duplicado" in reviews[f"tx:{duplicate}"]["warning"]
    assert reviews[f"expense:{bank_expense}"]["decision"] == "pending"
    assert "sem decisão comprovada" in reviews[f"expense:{bank_expense}"]["warning"]
    assert conn.execute("SELECT COUNT(*) FROM statement_review_items WHERE claimed_expense_id = ?", (recoverable,)).fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0

    conn.execute("""INSERT INTO card_statements (user_id, file_hash, file_name, card_last_four)
                    VALUES (2, 'same-file', 'other-user.pdf', '3006')""")
    conn.commit()
    assert {row["id"] for row in before["card_statements"]} == {statement_id, other_card}
    assert conn.execute("SELECT COUNT(*) FROM card_statements").fetchone()[0] == 3
    state = StatementService(conn, 1).get_review_state(statement_id)
    assert state["progress"]["reviewed"] == 6
    assert state["progress"]["pending"] == 3
    assert len(state["history"]) == 6
    assert any("indisponível" in warning for warning in state["warnings"])


def test_0013_does_not_guess_when_more_than_one_audit_could_supply_original(legacy_db):
    conn = legacy_db
    statement_id = _statement(conn, "ambiguous-audit")
    expense_id = _expense(conn, "STATEMENT ORIGINAL", 50, statement_id)
    tx_id = _tx(conn, statement_id, "approved", expense_id)
    _audit_match(conn, expense_id, statement_id, old_name="Possible original one")
    _audit_match(conn, expense_id, statement_id, old_name="Possible original two")
    conn.commit()
    command.upgrade(_config(), "0013")
    state = StatementService(conn, 1).get_review_state(statement_id)
    assert state["history"][0]["tx_id"] == tx_id
    assert state["history"][0]["bank_name"] is None
    assert any("indisponível" in warning for warning in state["warnings"])


@pytest.mark.parametrize("legacy_status", ["pending", "matched"])
@pytest.mark.parametrize("has_audit", [True, False])
def test_0013_does_not_assume_confirmed_pending_matches_are_approved_or_original(legacy_db, legacy_status, has_audit):
    conn = legacy_db
    statement_id = _statement(conn, "legacy-confirmed-pending", status="confirmed")
    expense_id = _expense(conn, "STATEMENT ORIGINAL", 50, statement_id)
    tx_id = _tx(conn, statement_id, legacy_status, expense_id)
    if has_audit:
        _audit_match(conn, expense_id, statement_id, old_name="Real original Telegram")
    conn.commit()
    original_expense = dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone())
    command.upgrade(_config(), "0013")
    review = conn.execute("SELECT * FROM statement_review_items WHERE tx_id = ?", (tx_id,)).fetchone()
    assert review["decision"] == "pending" and review["reviewed_at"] is None
    assert conn.execute("SELECT status FROM statement_transactions WHERE id = ?", (tx_id,)).fetchone()[0] == legacy_status
    expected_name = "Real original Telegram" if has_audit else None
    assert json.loads(review["snapshot"])["bank_name"] == expected_name
    service = StatementService(conn, 1)
    state = service.get_review_state(statement_id)
    assert state["history"] == [] and state["items"][0]["bank_name"] == expected_name
    state = service.review_batch(statement_id, "matched", "approve", [{"id": f"tx:{tx_id}"}], "legacy-explicit-approval")["state"]
    assert state["history"][0]["bank_name"] == expected_name
    assert state["history"][0]["name"] == "STATEMENT ORIGINAL"
    assert any("indisponível" in warning for warning in state["warnings"]) == (not has_audit)
    assert dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()) == original_expense
    assert service.get_review_state(statement_id)["history"] == state["history"]


def test_0013_applies_to_setup_schema_without_replacing_new_history_or_batches(test_db):
    conn = get_connection()
    conn.execute("INSERT INTO users (telegram_id, name) VALUES (700003, 'Setup owner')")
    statement_id = _statement(conn, "setup-file")
    tx_id = _tx(conn, statement_id, "pending", cents=1000)
    bank_id = _expense(conn, "SETUP BANK", 90)
    conn.commit()
    service = StatementService(conn, 1)
    service.review_batch(statement_id, "new", "approve", [{"id": f"tx:{tx_id}"}], "setup-request")
    service.update_review_category(statement_id, f"expense:{bank_id}", "Saúde")
    state = service.get_review_state(statement_id)
    tables = ("card_statements", "statement_transactions", "statement_review_items", "statement_review_batches", "expenses", "audit_log")
    before = {table: _rows(conn, table) for table in tables}
    command.stamp(_config(), "0012")
    command.upgrade(_config(), "0013")
    assert {table: _rows(conn, table) for table in tables} == before
    assert service.get_review_state(statement_id) == state
    retry = service.review_batch(statement_id, "new", "approve", [{"id": f"tx:{tx_id}"}], "setup-request")
    assert retry["processed"] == 1 and retry["state"] == state
    conn.close()


def test_0013_downgrade_refuses_to_destroy_history(legacy_db):
    conn = legacy_db
    statement_id = _statement(conn, "keep-history")
    _tx(conn, statement_id, "rejected")
    conn.commit()
    command.upgrade(_config(), "0013")
    before = _rows(conn, "statement_review_items")
    with pytest.raises(ValueError, match="downgrade destrutivo"):
        command.downgrade(_config(), "0012")
    assert _rows(conn, "statement_review_items") == before
    assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0013"


@pytest.mark.parametrize("backfill", ["migration", "service"])
@pytest.mark.parametrize("evidence,expected", [
    ("audit", "Educação"), ("expense", "Educação"), ("later_change", "Educação"),
    ("conflicting_audits", None), ("missing_expense", None), ("foreign_expense", None),
    ("invalid_category", None), ("unlinked_expense", None), ("later_audit_only", None),
])
def test_legacy_approved_match_category_is_a_fact_not_the_old_draft(legacy_db, backfill, evidence, expected):
    conn = legacy_db
    if backfill == "service":
        command.upgrade(_config(), "0013")
    statement_id = _statement(conn, "legacy-category-evidence", status="confirmed")
    if evidence == "missing_expense":
        expense_id = 987654
    else:
        expense_id = _expense(conn, "STATEMENT ORIGINAL", 50, statement_id)
        conn.execute("UPDATE expenses SET category = 'Educação' WHERE id = ?", (expense_id,))
    tx_id = _tx(conn, statement_id, "approved", expense_id)
    if evidence in ("audit", "later_change", "conflicting_audits"):
        _audit_match(conn, expense_id, statement_id)
        audit = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        old = json.loads(audit["old_data"])
        old["category"] = "Outros"
        conn.execute("UPDATE audit_log SET old_data = ? WHERE id = ?", (json.dumps(old), audit["id"]))
    if evidence in ("later_change", "later_audit_only"):
        old = dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone())
        new = {**old, "category": "Saúde"}
        conn.execute("UPDATE expenses SET category = 'Saúde' WHERE id = ?", (expense_id,))
        conn.execute(
            "INSERT INTO audit_log (operation, expense_id, old_data, new_data, user_id) VALUES ('update', ?, ?, ?, 1)",
            (expense_id, json.dumps(old), json.dumps(new)),
        )
    elif evidence == "conflicting_audits":
        conn.execute("UPDATE expenses SET category = 'Saúde' WHERE id = ?", (expense_id,))
        _audit_match(conn, expense_id, statement_id, old_name="Another possible original")
    elif evidence == "foreign_expense":
        conn.execute("UPDATE expenses SET user_id = 2 WHERE id = ?", (expense_id,))
    elif evidence == "invalid_category":
        conn.execute("UPDATE expenses SET category = 'Categoria inexistente' WHERE id = ?", (expense_id,))
    elif evidence == "unlinked_expense":
        conn.execute("UPDATE expenses SET statement_id = NULL WHERE id = ?", (expense_id,))
    conn.commit()
    before = {table: _rows(conn, table) for table in ("statement_transactions", "expenses", "audit_log")}
    if backfill == "migration":
        command.upgrade(_config(), "0013")
    service = StatementService(conn, 1)
    state = service.get_review_state(statement_id)
    review = conn.execute("SELECT * FROM statement_review_items WHERE tx_id = ?", (tx_id,)).fetchone()
    assert review["decision"] == "approved" and review["category"] == expected
    assert json.loads(review["snapshot"])["category"] == expected
    assert state["history"][0]["category"] == expected
    assert conn.execute("SELECT selected_category FROM statement_transactions WHERE id = ?", (tx_id,)).fetchone()[0] == "Lazer"
    assert {table: _rows(conn, table) for table in before} == before
    if expected is None:
        assert any("Categoria efetiva" in warning and "indisponível" in warning for warning in state["warnings"])
    assert service._suggester.suggest_from_history("STATEMENT ORIGINAL") != "Lazer"
    if evidence in ("audit", "expense"):
        assert service._suggester.suggest_from_history("STATEMENT ORIGINAL") == "Educação"
    assert service.get_review_state(statement_id)["history"] == state["history"]
