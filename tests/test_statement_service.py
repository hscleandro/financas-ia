"""Testes do serviço de conciliação de faturas."""
import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import pytest

from database.setup import get_connection
from services.statement_parser import CardHolder, ParsedStatement, ParsedTransaction
from services.statement_service import StatementService


def _build_tx(**kwargs):
    defaults = {
        "transaction_date": date(2026, 9, 10),
        "description": "TESTE",
        "amount_cents": 5000,
        "card_holder": "LEANDRO",
        "card_last_four": "3006",
    }
    defaults.update(kwargs)
    return ParsedTransaction(**defaults)


def _insert_credit_expense(conn, user_id, amount, description, expense_date):
    from services._base import compute_hash
    hash_val = compute_hash(amount, description, expense_date)
    cursor = conn.execute(
        """
        INSERT INTO expenses (user_id, amount, description, category, method, expense_date, hash)
        VALUES (?, ?, ?, 'Outros', 'crédito', ?, ?)
        """,
        (user_id, amount, description, expense_date.isoformat(), hash_val),
    )
    conn.commit()
    return cursor.lastrowid


def test_reconcile_matches_exact_value_and_date(test_db):
    from database.setup import get_connection
    from database.user_setup import create_or_update_user

    conn = get_connection()
    user = create_or_update_user(conn, telegram_id=123456, name="Teste")
    user_id = user["id"]

    # Despesa existente no banco
    exp_id = _insert_credit_expense(conn, user_id, 50.0, "Almoço", date(2026, 9, 10))

    service = StatementService(conn, user_id)

    # Insere fatura e transações manualmente
    cursor = conn.execute(
        """
        INSERT INTO card_statements (user_id, file_hash, file_name, statement_date, due_date, total_cents, card_last_four, card_holder, status)
        VALUES (?, 'hash1', 'fatura.pdf', '2026-10-10', '2026-10-10', 5000, '3006', 'LEANDRO', 'pending')
        """,
        (user_id,),
    )
    statement_id = cursor.lastrowid

    tx = _build_tx(transaction_date=date(2026, 9, 10), description="ALMOCO RESTAURANTE", amount_cents=5000)
    conn.execute(
        """
        INSERT INTO statement_transactions (statement_id, card_holder, card_last_four, transaction_date, description, amount_cents, raw_line)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (statement_id, tx.card_holder, tx.card_last_four, tx.transaction_date.isoformat(), tx.description, tx.amount_cents, tx.raw_line),
    )
    conn.commit()

    result = service.reconcile(statement_id)

    section = result.sections.get("3006")
    assert section is not None
    assert len(section.matched) == 1
    assert section.matched[0].expense["id"] == exp_id
    assert section.matched[0].statement_tx.amount_cents == 5000
    assert len(section.only_on_statement) == 0
    assert len(section.only_on_database) == 0


def test_reconcile_tolerates_two_day_date_difference(test_db):
    from database.setup import get_connection
    from database.user_setup import create_or_update_user

    conn = get_connection()
    user = create_or_update_user(conn, telegram_id=123457, name="Teste2")
    user_id = user["id"]

    exp_id = _insert_credit_expense(conn, user_id, 50.0, "Uber", date(2026, 9, 12))

    service = StatementService(conn, user_id)

    cursor = conn.execute(
        """
        INSERT INTO card_statements (user_id, file_hash, file_name, statement_date, due_date, total_cents, card_last_four, card_holder, status)
        VALUES (?, 'hash2', 'fatura.pdf', '2026-10-10', '2026-10-10', 5000, '3006', 'LEANDRO', 'pending')
        """,
        (user_id,),
    )
    statement_id = cursor.lastrowid

    tx = _build_tx(transaction_date=date(2026, 9, 10), description="UBER TRIP", amount_cents=5000)
    conn.execute(
        """
        INSERT INTO statement_transactions (statement_id, card_holder, card_last_four, transaction_date, description, amount_cents, raw_line)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (statement_id, tx.card_holder, tx.card_last_four, tx.transaction_date.isoformat(), tx.description, tx.amount_cents, tx.raw_line),
    )
    conn.commit()

    result = service.reconcile(statement_id)
    section = result.sections.get("3006")
    assert section is not None
    assert len(section.matched) == 1
    assert section.matched[0].expense["id"] == exp_id


def test_reconcile_does_not_match_three_day_difference(test_db):
    from database.setup import get_connection
    from database.user_setup import create_or_update_user

    conn = get_connection()
    user = create_or_update_user(conn, telegram_id=123458, name="Teste3")
    user_id = user["id"]

    _insert_credit_expense(conn, user_id, 50.0, "Uber", date(2026, 9, 13))

    service = StatementService(conn, user_id)

    cursor = conn.execute(
        """
        INSERT INTO card_statements (user_id, file_hash, file_name, statement_date, due_date, total_cents, card_last_four, card_holder, status)
        VALUES (?, 'hash3', 'fatura.pdf', '2026-10-10', '2026-10-10', 5000, '3006', 'LEANDRO', 'pending')
        """,
        (user_id,),
    )
    statement_id = cursor.lastrowid

    tx = _build_tx(transaction_date=date(2026, 9, 10), description="UBER TRIP", amount_cents=5000)
    conn.execute(
        """
        INSERT INTO statement_transactions (statement_id, card_holder, card_last_four, transaction_date, description, amount_cents, raw_line)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (statement_id, tx.card_holder, tx.card_last_four, tx.transaction_date.isoformat(), tx.description, tx.amount_cents, tx.raw_line),
    )
    conn.commit()

    result = service.reconcile(statement_id)
    section = result.sections.get("3006")
    assert section is not None
    assert len(section.matched) == 0
    assert len(section.only_on_statement) == 1
    assert len(section.only_on_database) == 1


def test_reconcile_one_to_one_blocks_multiple_matches(test_db):
    from database.setup import get_connection
    from database.user_setup import create_or_update_user

    conn = get_connection()
    user = create_or_update_user(conn, telegram_id=123459, name="Teste4")
    user_id = user["id"]

    # Duas despesas idênticas no banco
    exp1 = _insert_credit_expense(conn, user_id, 50.0, "Lanche", date(2026, 9, 10))
    exp2 = _insert_credit_expense(conn, user_id, 50.0, "Lanche", date(2026, 9, 10))

    service = StatementService(conn, user_id)

    cursor = conn.execute(
        """
        INSERT INTO card_statements (user_id, file_hash, file_name, statement_date, due_date, total_cents, card_last_four, card_holder, status)
        VALUES (?, 'hash4', 'fatura.pdf', '2026-10-10', '2026-10-10', 5000, '3006', 'LEANDRO', 'pending')
        """,
        (user_id,),
    )
    statement_id = cursor.lastrowid

    tx = _build_tx(transaction_date=date(2026, 9, 10), description="LANCHE", amount_cents=5000)
    conn.execute(
        """
        INSERT INTO statement_transactions (statement_id, card_holder, card_last_four, transaction_date, description, amount_cents, raw_line)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (statement_id, tx.card_holder, tx.card_last_four, tx.transaction_date.isoformat(), tx.description, tx.amount_cents, tx.raw_line),
    )
    conn.commit()

    result = service.reconcile(statement_id)
    # Como há múltiplos candidatos, deve ir para ambíguo
    assert len(result.ambiguous) == 1
    section = result.sections.get("3006")
    assert section is not None
    assert len(section.matched) == 0


def test_confirm_reconciliation_inserts_and_updates_and_deletes(test_db):
    from database.setup import get_connection
    from database.user_setup import create_or_update_user

    conn = get_connection()
    user = create_or_update_user(conn, telegram_id=123460, name="Teste5")
    user_id = user["id"]

    exp_id = _insert_credit_expense(conn, user_id, 75.0, "Cafe", date(2026, 9, 10))
    del_id = _insert_credit_expense(conn, user_id, 30.0, "Balada", date(2026, 9, 5))

    service = StatementService(conn, user_id)

    cursor = conn.execute(
        """
        INSERT INTO card_statements (user_id, file_hash, file_name, statement_date, due_date, total_cents, card_last_four, card_holder, status)
        VALUES (?, 'hash5', 'fatura.pdf', '2026-10-10', '2026-10-10', 5000, '3006', 'LEANDRO', 'pending')
        """,
        (user_id,),
    )
    statement_id = cursor.lastrowid

    tx_match = _build_tx(transaction_date=date(2026, 9, 10), description="CAFE DA MANHA", amount_cents=7500)
    tx_insert = _build_tx(transaction_date=date(2026, 9, 8), description="SUPERMERCADO", amount_cents=12000)

    cur = conn.execute(
        """
        INSERT INTO statement_transactions (statement_id, card_holder, card_last_four, transaction_date, description, amount_cents, raw_line)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (statement_id, tx_match.card_holder, tx_match.card_last_four, tx_match.transaction_date.isoformat(), tx_match.description, tx_match.amount_cents, tx_match.raw_line),
    )
    match_tx_id = cur.lastrowid
    cur = conn.execute(
        """
        INSERT INTO statement_transactions (statement_id, card_holder, card_last_four, transaction_date, description, amount_cents, raw_line)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (statement_id, tx_insert.card_holder, tx_insert.card_last_four, tx_insert.transaction_date.isoformat(), tx_insert.description, tx_insert.amount_cents, tx_insert.raw_line),
    )
    insert_tx_id = cur.lastrowid
    conn.commit()

    summary = service.confirm_reconciliation(
        statement_id,
        insert_ids=[insert_tx_id],
        update_pairs=[(match_tx_id, exp_id)],
        delete_ids=[del_id],
        default_category="Outros",
    )

    assert summary["inserted"] == 1
    assert summary["updated"] == 1
    assert summary["deleted"] == 1
    assert summary["status"] == "confirmed"

    # A conciliacao vincula a fatura sem sobrescrever a descricao do banco.
    updated = conn.execute("SELECT description, expense_date FROM expenses WHERE id = ?", (exp_id,)).fetchone()
    assert updated["description"] == "Cafe"

    # Verifica inserção
    inserted = conn.execute("SELECT description FROM expenses WHERE description = ? AND user_id = ?", ("SUPERMERCADO", user_id)).fetchone()
    assert inserted is not None

    # Verifica soft delete
    deleted = conn.execute("SELECT deleted_at FROM expenses WHERE id = ?", (del_id,)).fetchone()
    assert deleted["deleted_at"] is not None


def test_import_statement_filters_selected_cards(test_db):
    from database.setup import get_connection
    from database.user_setup import create_or_update_user

    conn = get_connection()
    user = create_or_update_user(conn, telegram_id=123461, name="Teste6")
    user_id = user["id"]

    service = StatementService(conn, user_id)

    # Cria um PDF mínimo em memória para os dois cartões. Como não queremos
    # depender do parser de PDF real, vamos mockar o parse injetando dados
    # manualmente no banco e testar a lógica de reconcile por cartão.
    cursor = conn.execute(
        """
        INSERT INTO card_statements (user_id, file_hash, file_name, statement_date, due_date, total_cents, card_last_four, card_holder, status)
        VALUES (?, 'hash6', 'fatura.pdf', '2026-10-10', '2026-10-10', 17000, '1111,2222', 'LEANDRO', 'pending')
        """,
        (user_id,),
    )
    statement_id = cursor.lastrowid

    for last_four, desc, amount in [("1111", "COMPRA A", 5000), ("2222", "COMPRA B", 12000)]:
        conn.execute(
            """
            INSERT INTO statement_transactions (statement_id, card_holder, card_last_four, transaction_date, description, amount_cents, raw_line, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (statement_id, "LEANDRO", last_four, date(2026, 9, 10).isoformat(), desc, amount, f"{desc} {amount}",),
        )
    conn.commit()

    result = service.reconcile(statement_id)
    assert set(result.sections.keys()) == {"1111", "2222"}
    assert len(result.sections["1111"].only_on_statement) == 1
    assert len(result.sections["2222"].only_on_statement) == 1


def test_approve_insert_creates_expense(test_db):
    from database.setup import get_connection
    from database.user_setup import create_or_update_user

    conn = get_connection()
    user = create_or_update_user(conn, telegram_id=123462, name="Teste7")
    user_id = user["id"]

    service = StatementService(conn, user_id)
    cursor = conn.execute(
        """
        INSERT INTO card_statements (user_id, file_hash, file_name, statement_date, due_date, total_cents, card_last_four, card_holder, status)
        VALUES (?, 'hash7', 'fatura.pdf', '2026-10-10', '2026-10-10', 10000, '3006', 'LEANDRO', 'pending')
        """,
        (user_id,),
    )
    statement_id = cursor.lastrowid
    cur = conn.execute(
        """
        INSERT INTO statement_transactions (statement_id, card_holder, card_last_four, transaction_date, description, amount_cents, raw_line, selected_category, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Transporte', 'pending')
        """,
        (statement_id, "LEANDRO", "3006", date(2026, 9, 10).isoformat(), "UBER", 4500, "UBER 45,00"),
    )
    tx_id = cur.lastrowid
    conn.commit()

    result = service.approve_insert(tx_id, category="Transporte")
    assert result["success"] is True
    assert result["category"] == "Transporte"

    expense = conn.execute(
        "SELECT * FROM expenses WHERE user_id = ? AND description = ?",
        (user_id, "UBER"),
    ).fetchone()
    assert expense is not None
    assert expense["amount"] == 45.0
    assert expense["category"] == "Transporte"
    assert expense["method"] == "crédito"

    tx_status = conn.execute(
        "SELECT status, selected_category FROM statement_transactions WHERE id = ?",
        (tx_id,),
    ).fetchone()
    assert tx_status["status"] == "inserted"
    assert tx_status["selected_category"] == "Transporte"


def test_approve_match_preserves_expense(test_db):
    from database.setup import get_connection
    from database.user_setup import create_or_update_user

    conn = get_connection()
    user = create_or_update_user(conn, telegram_id=123463, name="Teste8")
    user_id = user["id"]

    exp_id = _insert_credit_expense(conn, user_id, 50.0, "Almoco", date(2026, 9, 10))

    service = StatementService(conn, user_id)
    cursor = conn.execute(
        """
        INSERT INTO card_statements (user_id, file_hash, file_name, statement_date, due_date, total_cents, card_last_four, card_holder, status)
        VALUES (?, 'hash8', 'fatura.pdf', '2026-10-10', '2026-10-10', 5000, '3006', 'LEANDRO', 'pending')
        """,
        (user_id,),
    )
    statement_id = cursor.lastrowid
    cur = conn.execute(
        """
        INSERT INTO statement_transactions (statement_id, card_holder, card_last_four, transaction_date, description, amount_cents, raw_line, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'matched')
        """,
        (statement_id, "LEANDRO", "3006", date(2026, 9, 10).isoformat(), "ALMOCO RESTAURANTE", 5000, "ALMOCO 50,00"),
    )
    tx_id = cur.lastrowid
    conn.commit()

    result = service.approve_match(tx_id, exp_id)
    assert result["success"] is True

    updated = conn.execute("SELECT description FROM expenses WHERE id = ?", (exp_id,)).fetchone()
    assert updated["description"] == "Almoco"

    tx_status = conn.execute("SELECT status, matched_expense_id FROM statement_transactions WHERE id = ?", (tx_id,)).fetchone()
    assert tx_status["status"] == "approved"
    assert tx_status["matched_expense_id"] == exp_id


def test_reject_marks_transaction_rejected(test_db):
    from database.setup import get_connection
    from database.user_setup import create_or_update_user

    conn = get_connection()
    user = create_or_update_user(conn, telegram_id=123464, name="Teste9")
    user_id = user["id"]

    service = StatementService(conn, user_id)
    cursor = conn.execute(
        """
        INSERT INTO card_statements (user_id, file_hash, file_name, statement_date, due_date, total_cents, card_last_four, card_holder, status)
        VALUES (?, 'hash9', 'fatura.pdf', '2026-10-10', '2026-10-10', 5000, '3006', 'LEANDRO', 'pending')
        """,
        (user_id,),
    )
    statement_id = cursor.lastrowid
    cur = conn.execute(
        """
        INSERT INTO statement_transactions (statement_id, card_holder, card_last_four, transaction_date, description, amount_cents, raw_line, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (statement_id, "LEANDRO", "3006", date(2026, 9, 10).isoformat(), "DUMMY", 5000, "DUMMY 50,00"),
    )
    tx_id = cur.lastrowid
    conn.commit()

    result = service.reject(tx_id)
    assert result["success"] is True

    tx_status = conn.execute("SELECT status FROM statement_transactions WHERE id = ?", (tx_id,)).fetchone()
    assert tx_status["status"] == "rejected"


def test_update_category_persists_selection(test_db):
    from database.setup import get_connection
    from database.user_setup import create_or_update_user

    conn = get_connection()
    user = create_or_update_user(conn, telegram_id=123465, name="Teste10")
    user_id = user["id"]

    service = StatementService(conn, user_id)
    cursor = conn.execute(
        """
        INSERT INTO card_statements (user_id, file_hash, file_name, statement_date, due_date, total_cents, card_last_four, card_holder, status)
        VALUES (?, 'hash10', 'fatura.pdf', '2026-10-10', '2026-10-10', 5000, '3006', 'LEANDRO', 'pending')
        """,
        (user_id,),
    )
    statement_id = cursor.lastrowid
    cur = conn.execute(
        """
        INSERT INTO statement_transactions (statement_id, card_holder, card_last_four, transaction_date, description, amount_cents, raw_line, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (statement_id, "LEANDRO", "3006", date(2026, 9, 10).isoformat(), "DUMMY", 5000, "DUMMY 50,00"),
    )
    tx_id = cur.lastrowid
    conn.commit()

    result = service.update_category(tx_id, "Lazer")
    assert result["success"] is True

    tx_cat = conn.execute("SELECT selected_category FROM statement_transactions WHERE id = ?", (tx_id,)).fetchone()
    assert tx_cat["selected_category"] == "Lazer"


def test_get_pending_summary_returns_latest_pending_statement(test_db):
    from database.setup import get_connection
    from database.user_setup import create_or_update_user

    conn = get_connection()
    user = create_or_update_user(conn, telegram_id=123466, name="Teste11")
    user_id = user["id"]

    service = StatementService(conn, user_id)
    cursor = conn.execute(
        """
        INSERT INTO card_statements (user_id, file_hash, file_name, statement_date, due_date, total_cents, card_last_four, card_holder, status)
        VALUES (?, 'hash11', 'fatura.pdf', '2026-10-10', '2026-10-10', 15000, '3006', 'LEANDRO', 'pending')
        """,
        (user_id,),
    )
    statement_id = cursor.lastrowid
    for i in range(3):
        conn.execute(
            """
            INSERT INTO statement_transactions (statement_id, card_holder, card_last_four, transaction_date, description, amount_cents, raw_line, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (statement_id, "LEANDRO", "3006", date(2026, 9, 10 + i).isoformat(), f"TX{i}", 5000, f"TX{i} 50,00"),
        )
    conn.commit()

    summary = service.get_pending_summary()
    assert summary["has_pending"] is True
    assert summary["statement_id"] == statement_id
    assert summary["pending_count"] == 3


@pytest.fixture
def review_env(test_db):
    from database.user_setup import create_or_update_user

    conn = get_connection()
    user = create_or_update_user(conn, telegram_id=600001, name="Review test")
    yield conn, StatementService(conn, user["id"]), user["id"]
    conn.close()


def _statement(conn, user_id, file_hash="review-hash", cards="3006", due="2026-10-10"):
    cursor = conn.execute(
        """INSERT INTO card_statements (user_id, file_hash, file_name, due_date, card_last_four)
           VALUES (?, ?, 'synthetic.pdf', ?, ?)""", (user_id, file_hash, due, cards)
    )
    conn.commit()
    return cursor.lastrowid


def _review_tx(conn, statement_id, name="FATURA", cents=5000, day="2026-09-10", card="3006", category=None):
    cursor = conn.execute(
        """INSERT INTO statement_transactions (
            statement_id, description, amount_cents, transaction_date, card_last_four,
            card_holder, installment_info, selected_category
        ) VALUES (?, ?, ?, ?, ?, 'TITULAR', '01/03', ?)""",
        (statement_id, name, cents, day, card, category),
    )
    conn.commit()
    return cursor.lastrowid


def _tables(conn):
    return {table: [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in ("card_statements", "statement_transactions", "statement_review_items",
                          "statement_review_batches", "expenses", "audit_log", "sqlite_sequence")}


def _three_tabs(conn, service, user_id):
    statement_id = _statement(conn, user_id)
    for index in range(2):
        _review_tx(conn, statement_id, f"NOVA {index}", 1000 + index, category="Outros")
        _review_tx(conn, statement_id, f"FATURA {index}", 5000 + index)
        _insert_credit_expense(conn, user_id, (5000 + index) / 100, f"TELEGRAM {index}", date(2026, 9, 12))
        _insert_credit_expense(conn, user_id, 90 + index, f"BANCO {index}", date(2026, 9, 20))
    assert service.get_review_state(statement_id)["counts"] == {"new": 2, "matched": 2, "bank": 2}
    return statement_id


def test_match_preserves_both_descriptions_ids_and_original_expense_after_reload(review_env):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id)
    expense_id = _insert_credit_expense(conn, user_id, 50.29, "Almoco registrado pelo bot", date(2026, 9, 12))
    tx_id = _review_tx(conn, statement_id, "RESTAURANTE FATURA", 5029)
    original = dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone())
    state = service.get_review_state(statement_id)
    item = state["items"][0]
    assert item["id"] == f"tx:{tx_id}"
    assert item["expense_id"] == expense_id
    assert item["name"] == "RESTAURANTE FATURA"
    assert item["bank_name"] == "Almoco registrado pelo bot"
    assert item["date"] == "2026-09-10" and item["bank_date"] == "2026-09-12"
    assert item["amount_cents"] == item["bank_amount_cents"] == 5029
    service.update_review_category(statement_id, item["id"], "Alimentação")
    assert dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()) == original
    result = service.review_batch(statement_id, "matched", "approve", [{"id": item["id"]}], "match-1")
    changed = dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone())
    assert changed == {**original, "category": "Alimentação"}
    history = result["state"]["history"]
    assert history[0]["name"] == "RESTAURANTE FATURA"
    assert history[0]["bank_name"] == "Almoco registrado pelo bot"
    assert history[0]["tx_id"] == tx_id and history[0]["expense_id"] == expense_id
    assert history[0]["category"] == "Alimentação"
    assert history[0]["bank_category"] == "Outros"
    assert history[0]["reviewed_at"] is not None
    audits = conn.execute("SELECT * FROM audit_log").fetchall()
    assert len(audits) == 1 and audits[0]["operation"] == "update"
    before, after = json.loads(audits[0]["old_data"]), json.loads(audits[0]["new_data"])
    assert {key for key in before if before[key] != after[key]} == {"category"}

    with get_connection() as reloaded:
        assert StatementService(reloaded, user_id).get_review_state(statement_id)["history"] == history
    conn.execute("UPDATE expenses SET description = 'Edicao posterior do bot', expense_date = '2026-10-01' WHERE id = ?", (expense_id,))
    conn.commit()
    assert service.get_review_state(statement_id)["history"] == history
    json.dumps(result["state"])


@pytest.mark.parametrize("section", ["new", "matched", "bank"])
@pytest.mark.parametrize("action", ["approve", "ignore"])
def test_batches_in_all_three_tabs_persist_without_deleting(review_env, section, action):
    conn, service, user_id = review_env
    statement_id = _three_tabs(conn, service, user_id)
    before_expenses = [dict(row) for row in conn.execute("SELECT * FROM expenses ORDER BY id")]
    selected = [{"id": item["id"], "category": "Lazer"}
                for item in service.get_review_state(statement_id)["items"] if item["section"] == section]
    result = service.review_batch(statement_id, section, action, selected, f"{section}-{action}")
    assert result["success"] and result["processed"] == 2
    state = result["state"]
    assert state["counts"][section] == 0
    assert state["progress"] == {"total": 6, "pending": 4, "approved": 2 if action == "approve" else 0,
                                 "ignored": 2 if action == "ignore" else 0, "reviewed": 2, "percent": 33.33}
    assert all(item["section"] == section and item["decision"] == ("approved" if action == "approve" else "ignored")
               for item in state["history"])
    after_expenses = [dict(row) for row in conn.execute("SELECT * FROM expenses ORDER BY id")]
    if action == "ignore":
        assert after_expenses == before_expenses
        assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0
    elif section == "new":
        assert len(after_expenses) == len(before_expenses) + 2
    else:
        assert len(after_expenses) == len(before_expenses)
        assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 2
        assert sum(expense["category"] == "Lazer" for expense in after_expenses) == 2
    with get_connection() as reloaded:
        assert StatementService(reloaded, user_id).get_review_state(statement_id) == state


def test_later_insert_failure_rolls_back_the_entire_batch_and_request(review_env):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id)
    first = _review_tx(conn, statement_id, "GOOD", 1000, category="Outros")
    second = _review_tx(conn, statement_id, "FAIL", 2000, category="Outros")
    service.get_review_state(statement_id)
    conn.execute("""CREATE TRIGGER fail_late_insert BEFORE INSERT ON expenses
                    WHEN NEW.description = 'FAIL' BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
    conn.commit()
    before = _tables(conn)
    items = [{"id": f"tx:{first}"}, {"id": f"tx:{second}"}]
    with pytest.raises(ValueError, match="nenhuma decisão"):
        service.review_batch(statement_id, "new", "approve", items, "rollback-insert")
    assert _tables(conn) == before
    conn.execute("DROP TRIGGER fail_late_insert")
    conn.commit()
    assert service.review_batch(statement_id, "new", "approve", items, "rollback-insert")["processed"] == 2
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 2


def test_later_invalid_category_rolls_back_category_audit_and_match(review_env):
    conn, service, user_id = review_env
    statement_id = _three_tabs(conn, service, user_id)
    selected = [item for item in service.get_review_state(statement_id)["items"] if item["section"] == "matched"]
    before = _tables(conn)
    with pytest.raises(ValueError, match="Categoria inválida"):
        service.review_batch(statement_id, "matched", "approve",
                             [{"id": selected[0]["id"], "category": "Saúde"},
                              {"id": selected[1]["id"], "category": "Inexistente"}], "rollback-audit")
    assert _tables(conn) == before


def test_request_retry_is_idempotent_returns_fresh_state_and_rejects_payload_change(review_env):
    conn, service, user_id = review_env
    statement_id = _three_tabs(conn, service, user_id)
    selected = [{"id": item["id"], "category": "Lazer"}
                for item in service.get_review_state(statement_id)["items"] if item["section"] == "new"]
    first = service.review_batch(statement_id, "new", "approve", selected, "request-1")
    bank = [{"id": item["id"]} for item in first["state"]["items"] if item["section"] == "bank"]
    fresh = service.review_batch(statement_id, "bank", "ignore", bank, "request-2")["state"]
    before = _tables(conn)
    retry = service.review_batch(statement_id, "new", "approve", list(reversed(selected)), "request-1")
    assert retry["processed"] == 2 and retry["state"] == fresh
    assert _tables(conn) == before
    changed = [{**item, "category": "Outros"} for item in selected]
    with pytest.raises(ValueError, match="request_id.*diferente"):
        service.review_batch(statement_id, "new", "approve", changed, "request-1")
    with pytest.raises(ValueError, match="request_id.*diferente"):
        service.review_batch(statement_id, "new", "ignore", selected, "request-1")
    assert _tables(conn) == before
    assert service.review_batch(statement_id, "new", "approve", selected, "another-click")["processed"] == 0
    with pytest.raises(ValueError, match="já revisado"):
        service.review_batch(statement_id, "new", "ignore", selected, "conflicting-click")
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 6


@pytest.mark.parametrize("same_request", [True, False])
@pytest.mark.parametrize("connection_mode", ["separate_connections", "shared_service", "shared_connection"])
def test_concurrent_approvals_create_exactly_one_expense(review_env, same_request, connection_mode):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id)
    tx_id = _review_tx(conn, statement_id, "CONCURRENT", 1234, category="Outros")
    service.get_review_state(statement_id)
    barrier = Barrier(2)

    def approve(index):
        connection = get_connection() if connection_mode == "separate_connections" else None
        try:
            worker = service if connection_mode == "shared_service" else StatementService(connection or conn, user_id)
            barrier.wait(timeout=10)
            return worker.review_batch(statement_id, "new", "approve", [{"id": f"tx:{tx_id}"}],
                                       "concurrent" if same_request else f"concurrent-{index}")
        finally:
            if connection is not None:
                connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(approve, range(2)))
    assert all(result["success"] for result in results)
    assert sorted(result["processed"] for result in results) == ([1, 1] if same_request else [0, 1])
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM statement_review_batches").fetchone()[0] == (1 if same_request else 2)
    assert len(service.get_review_state(statement_id)["history"]) == 1


def test_category_clear_and_conditional_suggestion_preserve_manual_choice(review_env):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id)
    tx_id = _review_tx(conn, statement_id, "DRAFT", 1234)
    item_id = f"tx:{tx_id}"
    assert service.get_review_state(statement_id)["items"][0]["category_edited"] is False
    suggested = service.update_review_category(statement_id, item_id, "Transporte", only_if_empty=True)
    assert suggested["updated"]
    assert suggested["state"]["items"][0]["category_edited"] is False
    service.update_review_category(statement_id, item_id, "Lazer")
    assert not service.update_review_category(statement_id, item_id, "Saúde", only_if_empty=True)["updated"]
    cleared = service.update_review_category(statement_id, item_id, "")
    assert cleared["category"] is None
    late = service.update_review_category(statement_id, item_id, "Outros", only_if_empty=True)
    assert not late["updated"] and late["category"] is None
    assert conn.execute("SELECT selected_category FROM statement_transactions WHERE id = ?", (tx_id,)).fetchone()[0] is None
    with pytest.raises(ValueError, match="Selecione uma categoria"):
        service.review_batch(statement_id, "new", "approve", [{"id": item_id}], "empty-category")
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 0
    service.update_review_category(statement_id, item_id, "lazer")
    service.review_batch(statement_id, "new", "approve", [{"id": item_id}], "filled-category")
    assert not service.update_review_category(statement_id, item_id, "Saúde", only_if_empty=True)["updated"]
    with pytest.raises(ValueError, match="já revisado"):
        service.update_review_category(statement_id, item_id, "Saúde")


@pytest.mark.parametrize("section", ["matched", "bank"])
def test_cleared_existing_expense_draft_does_not_default_or_modify_expense(review_env, section):
    conn, service, user_id = review_env
    statement_id = _three_tabs(conn, service, user_id)
    item = next(item for item in service.get_review_state(statement_id)["items"] if item["section"] == section)
    original = dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (item["expense_id"],)).fetchone())
    service.update_review_category(statement_id, item["id"], "")
    state = service.review_batch(statement_id, section, "approve", [{"id": item["id"]}], "clear-existing")["state"]
    assert state["history"][0]["category"] is None
    assert dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (item["expense_id"],)).fetchone()) == original
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_bank_only_remains_pending_after_last_tx_and_oldest_is_not_hidden(review_env):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id)
    tx_id = _review_tx(conn, statement_id, "NEW", 1200, category="Outros")
    expense_id = _insert_credit_expense(conn, user_id, 80, "SOMENTE BANCO", date(2026, 9, 20))
    state = service.review_batch(statement_id, "new", "approve", [{"id": f"tx:{tx_id}"}], "last-tx")["state"]
    assert state["counts"] == {"new": 0, "matched": 0, "bank": 1}
    newer = _statement(conn, user_id, "newer-empty", due="2027-03-10")
    conn.execute("UPDATE card_statements SET status = 'confirmed' WHERE id = ?", (statement_id,))
    conn.commit()
    assert service.get_pending_summary()["statement_id"] == statement_id
    listed = {row["id"]: row for row in service.list_statements()}
    assert listed[statement_id]["status"] == "pending" and listed[newer]["status"] == "confirmed"
    assert service.approve_review(expense_id, statement_id)["success"]
    state = service.get_review_state(statement_id)
    assert state["items"] == [] and state["progress"]["percent"] == 100
    assert len(state["history"]) == 2
    assert conn.execute("SELECT statement_id FROM expenses WHERE id = ?", (expense_id,)).fetchone()[0] is None
    assert not service.get_pending_summary()["has_pending"]
    with get_connection() as reloaded:
        assert StatementService(reloaded, user_id).get_review_state(statement_id) == state


def test_ambiguous_matches_never_choose_automatically_and_enforce_one_to_one(review_env):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id)
    expense_id = _insert_credit_expense(conn, user_id, 50, "ONE EXPENSE", date(2026, 9, 10))
    first = _review_tx(conn, statement_id, "FIRST", 5000)
    second = _review_tx(conn, statement_id, "SECOND", 5000)
    state = service.get_review_state(statement_id)
    assert state["counts"] == {"new": 0, "matched": 2, "bank": 0}
    assert all(item["ambiguous"] and item["expense_id"] is None for item in state["items"])
    assert all(item["candidates"][0]["expense_id"] == expense_id for item in state["items"])
    before = _tables(conn)
    with pytest.raises(ValueError, match="correspondência válida"):
        service.review_batch(statement_id, "matched", "approve", [{"id": f"tx:{first}"}], "missing-choice")
    with pytest.raises(ValueError, match="já vinculada"):
        service.review_batch(statement_id, "matched", "approve",
                             [{"id": f"tx:{first}", "expense_id": expense_id},
                              {"id": f"tx:{second}", "expense_id": expense_id}], "double-choice")
    assert _tables(conn) == before
    state = service.review_batch(statement_id, "matched", "approve",
                                 [{"id": f"tx:{first}", "expense_id": expense_id}], "choose-first")["state"]
    assert state["counts"] == {"new": 1, "matched": 0, "bank": 0}
    assert state["items"][0]["tx_id"] == second
    assert service.get_review_state(statement_id) == state
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM statement_review_items WHERE claimed_expense_id = ?", (expense_id,)).fetchone()[0] == 1


def test_ambiguous_selection_releases_remaining_candidate_into_bank_tab(review_env):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id)
    first = _insert_credit_expense(conn, user_id, 50, "FIRST DB", date(2026, 9, 10))
    second = _insert_credit_expense(conn, user_id, 50, "SECOND DB", date(2026, 9, 12))
    tx_id = _review_tx(conn, statement_id, "AMBIGUOUS", 5000)
    state = service.get_review_state(statement_id)
    assert state["items"][0]["expense_id"] is None
    assert [candidate["expense_id"] for candidate in state["items"][0]["candidates"]] == [first, second]
    state = service.review_batch(statement_id, "matched", "approve",
                                 [{"id": f"tx:{tx_id}", "expense_id": second, "category": "Transporte"}], "pick-second")["state"]
    assert state["items"][0]["id"] == f"expense:{first}"
    assert state["history"][0]["bank_name"] == "SECOND DB"
    assert state["history"][0]["expense_id"] == second
    assert conn.execute("SELECT category FROM expenses WHERE id = ?", (second,)).fetchone()[0] == "Transporte"


def test_bank_expense_is_not_repeated_across_cards_and_match_reservation_persists(review_env):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id, cards="1111,2222")
    _review_tx(conn, statement_id, "CARD ONE", 1000, card="1111")
    _review_tx(conn, statement_id, "CARD TWO", 2000, card="2222")
    _insert_credit_expense(conn, user_id, 90, "UNKNOWN CARD BANK", date(2026, 9, 20))
    expense_id = _insert_credit_expense(conn, user_id, 10, "MATCH CARD ONE", date(2026, 9, 10))
    state = service.get_review_state(statement_id)
    assert state["counts"] == {"new": 1, "matched": 1, "bank": 1}
    reconciled = service.reconcile(statement_id)
    assert sum(len(section.only_on_database) for section in reconciled.sections.values()) == 1
    other = _statement(conn, user_id, "another-file", cards="1111")
    _review_tx(conn, other, "SHOULD NOT CLAIM AGAIN", 1000, card="1111")
    assert service.get_review_state(other)["counts"]["matched"] == 0
    assert conn.execute("SELECT COUNT(*) FROM statement_review_items WHERE claimed_expense_id = ?", (expense_id,)).fetchone()[0] == 1
    assert service.get_review_state(statement_id) == state


@pytest.mark.parametrize("day,amount,matched", [
    (8, 0.29, True), (10, 0.29, True), (12, 0.29, True),
    (7, 0.29, False), (13, 0.29, False), (10, 0.30, False),
])
def test_matching_uses_exact_cents_and_two_day_inclusive_boundary(review_env, day, amount, matched):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id, due="2026-09-10")
    expense_id = _insert_credit_expense(conn, user_id, amount, "CENTS DB", date(2026, 9, day))
    _review_tx(conn, statement_id, "CENTS STATEMENT", 29)
    state = service.get_review_state(statement_id)
    assert state["counts"]["matched"] == int(matched)
    assert state["items"][0]["amount_cents"] == 29
    if matched:
        assert state["items"][0]["expense_id"] == expense_id
        assert state["items"][0]["bank_amount_cents"] == 29


def test_reimport_preserves_ids_decisions_categories_and_can_add_selected_card(review_env, monkeypatch, tmp_path):
    conn, service, user_id = review_env
    parsed = ParsedStatement(
        holder_name="SYNTHETIC", due_date=date(2026, 10, 10), file_name="synthetic.pdf",
        file_hash=hashlib.sha256(b"synthetic statement bytes").hexdigest(), warnings=["Aviso sintético"],
        transactions=[_build_tx(description="APPROVE", amount_cents=1000),
                      _build_tx(description="IGNORE", amount_cents=2000),
                      _build_tx(description="DRAFT", amount_cents=3000),
                      _build_tx(description="SECOND CARD", amount_cents=4000, card_last_four="2222")],
    )
    monkeypatch.setattr("services.statement_service.parse_bradesco_statement", lambda path: copy.deepcopy(parsed))
    statement_id, _, cards = service.import_statement(tmp_path / "not-read.pdf", ["3006"])
    assert cards == ["3006"]
    rows = conn.execute("SELECT * FROM statement_transactions WHERE statement_id = ? ORDER BY id", (statement_id,)).fetchall()
    approved, ignored, draft = rows
    service.review_batch(statement_id, "new", "approve", [{"id": f"tx:{approved['id']}", "category": "Lazer"}], "import-approve")
    service.review_batch(statement_id, "new", "ignore", [{"id": f"tx:{ignored['id']}"}], "import-ignore")
    service.update_review_category(statement_id, f"tx:{draft['id']}", "Educação")
    before = _tables(conn)
    state = service.get_review_state(statement_id)
    reimported, _, _ = service.import_statement(tmp_path / "not-read.pdf", ["3006"])
    assert reimported == statement_id
    assert _tables(conn) == before
    assert service.get_review_state(statement_id) == state
    assert "Aviso sintético" in state["warnings"]
    service.import_statement(tmp_path / "not-read.pdf", ["3006", "2222"])
    updated = service.get_review_state(statement_id)
    assert updated["history"] == state["history"]
    assert updated["progress"]["reviewed"] == 2 and updated["progress"]["pending"] == 2
    assert next(item for item in updated["items"] if item["tx_id"] == draft["id"])["category"] == "Educação"
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 1


def test_reimport_preserves_distinct_identical_transaction_occurrences(review_env, monkeypatch, tmp_path):
    conn, service, user_id = review_env
    parsed = ParsedStatement(file_hash="identical-lines", file_name="synthetic.pdf", due_date=date(2026, 10, 10),
                             transactions=[_build_tx(), _build_tx()])
    monkeypatch.setattr("services.statement_service.parse_bradesco_statement", lambda path: copy.deepcopy(parsed))
    statement_id, _, _ = service.import_statement(tmp_path / "not-read.pdf")
    before = _tables(conn)
    service.import_statement(tmp_path / "not-read.pdf")
    assert _tables(conn) == before
    assert len(service.get_review_state(statement_id)["items"]) == 2


def test_same_bytes_and_request_keys_are_isolated_by_user(review_env, monkeypatch, tmp_path):
    from database.user_setup import create_or_update_user

    conn, service, user_id = review_env
    other_user = create_or_update_user(conn, telegram_id=600002, name="Other user")["id"]
    other_service = StatementService(conn, other_user)
    parsed = ParsedStatement(file_hash="same-bytes", file_name="synthetic.pdf", due_date=date(2026, 10, 10),
                             transactions=[_build_tx()])
    monkeypatch.setattr("services.statement_service.parse_bradesco_statement", lambda path: copy.deepcopy(parsed))
    first_id, _, _ = service.import_statement(tmp_path / "not-read.pdf")
    second_id, _, _ = other_service.import_statement(tmp_path / "not-read.pdf")
    assert first_id != second_id
    first_item = service.get_review_state(first_id)["items"][0]["id"]
    second_item = other_service.get_review_state(second_id)["items"][0]["id"]
    for own_service, own_id, own_item in ((service, first_id, first_item), (other_service, second_id, second_item)):
        own_service.review_batch(own_id, "new", "approve", [{"id": own_item, "category": "Outros"}], "shared-request-key")
    before = _tables(conn)
    with pytest.raises(ValueError, match="não pertence"):
        service.get_review_state(second_id)
    with pytest.raises(ValueError, match="não pertence"):
        service.review_batch(second_id, "new", "ignore", [{"id": second_item}], "foreign-statement")
    with pytest.raises(ValueError, match="não pertence"):
        service.update_review_category(second_id, second_item, "Lazer")
    with pytest.raises(ValueError, match="não encontrado"):
        service.review_batch(first_id, "new", "approve", [{"id": second_item, "category": "Outros"}], "foreign-item")
    assert "error" in service.approve_match(int(second_item.split(":")[1]), 1)
    assert _tables(conn) == before
    assert [row["id"] for row in service.list_statements()] == [first_id]
    assert conn.execute("SELECT COUNT(*) FROM expenses WHERE user_id = ?", (user_id,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM expenses WHERE user_id = ?", (other_user,)).fetchone()[0] == 1


@pytest.mark.parametrize("section,action,items,request_id", [
    ("invalid", "approve", [{"id": "tx:1"}], "bad"),
    ("new", "delete", [{"id": "tx:1"}], "bad"),
    ("new", "approve", [], "bad"),
    ("new", "approve", [{"id": "tx:1"}], ""),
    ("new", "approve", [{"id": "tx:01"}], "bad"),
    ("new", "approve", [{"id": "tx:1"}, {"id": "tx:1"}], "bad"),
    ("new", "approve", [{"id": "expense:1"}], "bad"),
    ("new", "approve", [{"id": "tx:1", "expense_id": 1}], "bad"),
    ("matched", "approve", [{"id": "tx:1", "expense_id": True}], "bad"),
    ("new", "approve", [{"id": "tx:1", "category": None}], "bad"),
    ("new", "approve", [{"id": "tx:1", "description": "overwrite"}], "bad"),
    ("new", "approve", [{"id": "tx:9999", "category": "Outros"}], "bad"),
    ("new", "approve", [{"id": "tx:1", "category": "Categoria inventada"}], "bad"),
])
def test_invalid_batch_input_is_rejected_without_any_writes(review_env, section, action, items, request_id):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id)
    _review_tx(conn, statement_id, category="Outros")
    service.get_review_state(statement_id)
    before = _tables(conn)
    categories = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    with pytest.raises(ValueError):
        service.review_batch(statement_id, section, action, items, request_id)
    assert _tables(conn) == before
    assert conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == categories


def test_other_users_category_and_non_candidate_expense_are_not_accepted(review_env):
    from database.user_setup import create_or_update_user

    conn, service, user_id = review_env
    other_user = create_or_update_user(conn, telegram_id=600003, name="Category owner")["id"]
    conn.execute("INSERT INTO categories (name, user_id) VALUES ('Privada', ?)", (other_user,))
    conn.commit()
    statement_id = _three_tabs(conn, service, user_id)
    state = service.get_review_state(statement_id)
    new = next(item for item in state["items"] if item["section"] == "new")
    matched = next(item for item in state["items"] if item["section"] == "matched")
    bank = next(item for item in state["items"] if item["section"] == "bank")
    before = _tables(conn)
    with pytest.raises(ValueError, match="Categoria inválida"):
        service.update_review_category(statement_id, new["id"], "Privada")
    with pytest.raises(ValueError, match="correspondência válida"):
        service.review_batch(statement_id, "matched", "approve",
                             [{"id": matched["id"], "expense_id": bank["expense_id"]}], "not-candidate")
    assert _tables(conn) == before


def test_ignoring_ambiguous_match_can_record_a_selected_candidate_without_touching_expenses(review_env):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id)
    first = _insert_credit_expense(conn, user_id, 50, "DB FIRST", date(2026, 9, 10))
    second = _insert_credit_expense(conn, user_id, 50, "DB SECOND", date(2026, 9, 12))
    tx_id = _review_tx(conn, statement_id, "STATEMENT AMBIGUOUS", 5000)
    expenses = [dict(row) for row in conn.execute("SELECT * FROM expenses ORDER BY id")]
    state = service.review_batch(statement_id, "matched", "ignore",
                                 [{"id": f"tx:{tx_id}", "expense_id": second, "category": "Saúde"}], "ignore-choice")["state"]
    assert state["history"][0]["decision"] == "ignored"
    assert state["history"][0]["name"] == "STATEMENT AMBIGUOUS"
    assert state["history"][0]["bank_name"] == "DB SECOND"
    assert state["history"][0]["expense_id"] == second
    assert state["items"][0]["expense_id"] == first
    assert [dict(row) for row in conn.execute("SELECT * FROM expenses ORDER BY id")] == expenses
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_bank_only_statement_with_no_transactions_can_finish_and_remain_finished(review_env):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id)
    expense_id = _insert_credit_expense(conn, user_id, 75, "BANK ONLY", date(2026, 9, 10))
    state = service.get_review_state(statement_id)
    assert state["counts"] == {"new": 0, "matched": 0, "bank": 1}
    assert service.get_pending_summary()["pending_count"] == 1
    state = service.review_batch(statement_id, "bank", "ignore", [{"id": f"expense:{expense_id}"}], "bank-only")["state"]
    assert state["progress"] == {"total": 1, "pending": 0, "approved": 0, "ignored": 1, "reviewed": 1, "percent": 100}
    assert service.get_review_state(statement_id) == state
    assert conn.execute("SELECT deleted_at FROM expenses WHERE id = ?", (expense_id,)).fetchone()[0] is None


def test_runtime_failure_during_later_audit_rolls_back_all_changes(review_env, monkeypatch):
    from services._base import log_audit as actual_log_audit

    conn, service, user_id = review_env
    statement_id = _three_tabs(conn, service, user_id)
    selected = [{"id": item["id"], "category": "Saúde"}
                for item in service.get_review_state(statement_id)["items"] if item["section"] == "matched"]
    calls = 0

    def failing_audit(*args, **kwargs):
        nonlocal calls
        calls += 1
        actual_log_audit(*args, **kwargs)
        if calls == 2:
            raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr("services.statement_service.log_audit", failing_audit)
    before = _tables(conn)
    with pytest.raises(ValueError, match="nenhuma decisão"):
        service.review_batch(statement_id, "matched", "approve", selected, "runtime-rollback")
    assert calls == 2 and _tables(conn) == before


def test_batch_uses_savepoint_without_committing_callers_transaction(review_env):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id)
    tx_id = _review_tx(conn, statement_id, "SAVEPOINT", 1100, category="Outros")
    before = _tables(conn)
    conn.execute("UPDATE users SET name = 'Uncommitted caller change' WHERE id = ?", (user_id,))
    service.review_batch(statement_id, "new", "approve", [{"id": f"tx:{tx_id}"}], "savepoint")
    assert conn.in_transaction
    with get_connection() as isolated:
        assert isolated.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 0
    conn.rollback()
    assert _tables(conn) == before
    assert service.review_batch(statement_id, "new", "approve", [{"id": f"tx:{tx_id}"}], "savepoint")["processed"] == 1


def test_request_id_cannot_be_reused_for_another_owned_statement(review_env):
    conn, service, user_id = review_env
    first = _statement(conn, user_id)
    first_tx = _review_tx(conn, first, cents=1000, category="Outros")
    second = _statement(conn, user_id, "second-owned", due="2027-01-10")
    second_tx = _review_tx(conn, second, cents=2000, day="2027-01-01", category="Outros")
    service.review_batch(first, "new", "approve", [{"id": f"tx:{first_tx}"}], "same-key")
    before = _tables(conn)
    with pytest.raises(ValueError, match="request_id.*diferente"):
        service.review_batch(second, "new", "approve", [{"id": f"tx:{second_tx}"}], "same-key")
    assert _tables(conn) == before


def test_legacy_wrappers_are_idempotent_and_keep_one_expense(review_env):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id)
    tx_id = _review_tx(conn, statement_id, "LEGACY RETRY", 1300)
    first = service.approve_insert(tx_id, "Lazer")
    assert first["success"]
    assert service.approve_insert(tx_id, "Lazer") == first
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 1
    assert "error" in service.reject(tx_id)
    assert "error" in service.approve_insert(True, "Lazer")
    assert service.get_review_state(statement_id)["progress"]["reviewed"] == 1


def test_reimport_retains_separate_legacy_imports_without_copying_their_transactions(review_env, monkeypatch, tmp_path):
    conn, service, user_id = review_env
    first = _statement(conn, user_id, "legacy-same-file", cards="1111")
    second = _statement(conn, user_id, "legacy-same-file", cards="2222")
    first_tx = _review_tx(conn, first, "LEGACY FIRST", 1000, card="1111", category="Lazer")
    second_tx = _review_tx(conn, second, "LEGACY SECOND", 2000, card="2222", category="Educação")
    service.reject(first_tx)
    service.reject(second_tx)
    saved = [dict(row) for row in conn.execute("SELECT * FROM statement_transactions ORDER BY id")]
    parsed = ParsedStatement(file_hash="legacy-same-file", file_name="synthetic.pdf", due_date=date(2026, 10, 10),
                             transactions=[_build_tx(description="LEGACY FIRST", amount_cents=1000, card_last_four="1111", installment_info="01/03"),
                                           _build_tx(description="LEGACY SECOND", amount_cents=2000, card_last_four="2222", installment_info="01/03")])
    monkeypatch.setattr("services.statement_service.parse_bradesco_statement", lambda path: copy.deepcopy(parsed))
    statement_id, _, _ = service.import_statement(tmp_path / "not-read.pdf", ["2222"])
    assert statement_id == second
    service.import_statement(tmp_path / "not-read.pdf")
    assert [dict(row) for row in conn.execute("SELECT * FROM statement_transactions ORDER BY id")] == saved
    assert conn.execute("SELECT COUNT(*) FROM card_statements").fetchone()[0] == 2
    assert all(item["decision"] == "ignored" for item in service.get_review_state(second)["history"])


def test_concurrent_reimport_of_selected_cards_keeps_one_import_and_original_tx_ids(review_env, monkeypatch, tmp_path):
    conn, service, user_id = review_env
    parsed = ParsedStatement(file_hash="concurrent-import", file_name="synthetic.pdf", due_date=date(2026, 10, 10),
                             transactions=[_build_tx(description="ONE", amount_cents=1000, card_last_four="1111"),
                                           _build_tx(description="TWO", amount_cents=2000, card_last_four="2222")])
    monkeypatch.setattr("services.statement_service.parse_bradesco_statement", lambda path: copy.deepcopy(parsed))
    barrier = Barrier(2)

    def import_card(card):
        connection = get_connection()
        try:
            barrier.wait(timeout=10)
            return StatementService(connection, user_id).import_statement(tmp_path / "not-read.pdf", [card])[0]
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(import_card, ["1111", "2222"]))
    assert ids[0] == ids[1]
    assert conn.execute("SELECT COUNT(*) FROM card_statements").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM statement_transactions").fetchone()[0] == 2
    saved = [dict(row) for row in conn.execute("SELECT * FROM statement_transactions ORDER BY id")]
    service.import_statement(tmp_path / "not-read.pdf")
    assert [dict(row) for row in conn.execute("SELECT * FROM statement_transactions ORDER BY id")] == saved


@pytest.mark.parametrize("existing_import", [False, True])
@pytest.mark.parametrize("selected_cards", [
    [], ["9999"], ["3006", "9999"], [""], ["306"], [3006], [None],
    ["3006", "3006"], "3006", (), False,
])
def test_import_rejects_invalid_or_explicitly_empty_card_selection_without_writes(
    review_env, monkeypatch, tmp_path, existing_import, selected_cards
):
    conn, service, user_id = review_env
    parsed = ParsedStatement(
        file_hash="validate-selected-cards", file_name="synthetic.pdf", due_date=date(2026, 10, 10),
        card_holders=[CardHolder(name="SYNTHETIC", last_four="2222")],
        transactions=[_build_tx(description="FIRST", amount_cents=1000),
                      _build_tx(description="SECOND", amount_cents=2000, card_last_four="1111")],
    )
    monkeypatch.setattr("services.statement_service.parse_bradesco_statement", lambda path: copy.deepcopy(parsed))
    if existing_import:
        statement_id, _, _ = service.import_statement(tmp_path / "not-read.pdf")
        tx_id = service.get_review_state(statement_id)["items"][0]["id"]
        service.review_batch(statement_id, "new", "ignore", [{"id": tx_id}], "preserve-before-invalid-import")
    before = _tables(conn)
    with pytest.raises(ValueError, match="cartão|Cartão|cartões"):
        service.import_statement(tmp_path / "not-read.pdf", selected_cards)
    assert _tables(conn) == before
    assert not conn.in_transaction


@pytest.mark.parametrize("selected_cards,expected_cards", [
    (None, ["1111", "2222", "3006"]),
    (["2222"], ["2222"]),
    (["1111"], ["1111"]),
    (["3006", "2222"], ["2222", "3006"]),
])
def test_import_accepts_cards_detected_in_transactions_or_card_holders(
    review_env, monkeypatch, tmp_path, selected_cards, expected_cards
):
    conn, service, user_id = review_env
    parsed = ParsedStatement(
        file_hash="detected-card-holders", file_name="synthetic.pdf", due_date=date(2026, 10, 10),
        card_holders=[CardHolder(name="HEADER ONLY", last_four="2222"),
                      CardHolder(name="ALSO IN TRANSACTIONS", last_four="3006")],
        transactions=[_build_tx(description="FIRST", amount_cents=1000),
                      _build_tx(description="SECOND", amount_cents=2000, card_last_four="1111")],
    )
    monkeypatch.setattr("services.statement_service.parse_bradesco_statement", lambda path: copy.deepcopy(parsed))
    expense_id = _insert_credit_expense(conn, user_id, 50, "HEADER CARD BANK", date(2026, 9, 10))
    conn.execute("UPDATE expenses SET card_last_four = '2222' WHERE id = ?", (expense_id,))
    conn.commit()
    statement_id, _, cards = service.import_statement(tmp_path / "not-read.pdf", selected_cards)
    assert cards == expected_cards
    assert conn.execute("SELECT card_last_four FROM card_statements WHERE id = ?", (statement_id,)).fetchone()[0] == ",".join(expected_cards)
    actual_cards = [row[0] for row in conn.execute(
        "SELECT card_last_four FROM statement_transactions WHERE statement_id = ? ORDER BY card_last_four",
        (statement_id,),
    )]
    assert actual_cards == [card for card in expected_cards if card != "2222"]
    state = service.get_review_state(statement_id)
    assert state["counts"] == {"new": len(actual_cards), "matched": 0, "bank": int("2222" in expected_cards)}
    before = _tables(conn)
    assert service.import_statement(tmp_path / "not-read.pdf", selected_cards)[0] == statement_id
    assert _tables(conn) == before


@pytest.mark.parametrize("section", ["new", "matched", "bank"])
def test_pending_category_edited_flag_survives_manual_clear_without_changing_history_snapshots(review_env, section):
    conn, service, user_id = review_env
    statement_id = _three_tabs(conn, service, user_id)
    state = service.get_review_state(statement_id)
    assert all(item["category_edited"] is False for item in state["items"])
    selected = next(item for item in state["items"] if item["section"] == section)
    cleared = service.update_review_category(statement_id, selected["id"], "")
    current = next(item for item in cleared["state"]["items"] if item["id"] == selected["id"])
    assert current["category"] is None and current["category_edited"] is True
    late = service.update_review_category(statement_id, selected["id"], "Outros", only_if_empty=True)
    assert not late["updated"]
    with get_connection() as reloaded:
        current = next(item for item in StatementService(reloaded, user_id).get_review_state(statement_id)["items"]
                       if item["id"] == selected["id"])
        assert current["category"] is None and current["category_edited"] is True
    state = service.review_batch(statement_id, section, "ignore", [{"id": selected["id"]}], "finish-edited-category")["state"]
    history = state["history"]
    assert history[0]["category"] is None and "category_edited" not in history[0]
    snapshot = conn.execute(
        "SELECT snapshot FROM statement_review_items WHERE statement_id = ? AND item_id = ?",
        (statement_id, selected["id"]),
    ).fetchone()[0]
    assert "category_edited" not in json.loads(snapshot)
    assert service.get_review_state(statement_id)["history"] == history
    assert conn.execute(
        "SELECT snapshot FROM statement_review_items WHERE statement_id = ? AND item_id = ?",
        (statement_id, selected["id"]),
    ).fetchone()[0] == snapshot


@pytest.mark.parametrize("bank_action", ["approve", "ignore"])
def test_reviewed_bank_expense_can_match_a_card_added_by_reimport(review_env, monkeypatch, tmp_path, bank_action):
    conn, service, user_id = review_env
    parsed = ParsedStatement(
        file_hash="bank-before-card-expansion", file_name="synthetic.pdf", due_date=date(2026, 10, 10),
        transactions=[_build_tx(description="FIRST CARD", amount_cents=1000, card_last_four="1111"),
                      _build_tx(description="SECOND CARD", amount_cents=5000, card_last_four="2222")],
    )
    monkeypatch.setattr("services.statement_service.parse_bradesco_statement", lambda path: copy.deepcopy(parsed))
    expense_id = _insert_credit_expense(conn, user_id, 50, "ORIGINAL BOT DESCRIPTION", date(2026, 9, 12))
    original = dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone())
    statement_id, _, _ = service.import_statement(tmp_path / "not-read.pdf", ["1111"])
    state = service.get_review_state(statement_id)
    first = next(item for item in state["items"] if item["section"] == "new")
    service.review_batch(statement_id, "new", "ignore", [{"id": first["id"]}], "finish-first-card")
    bank_request = [{"id": f"expense:{expense_id}"}]
    before = service.review_batch(statement_id, "bank", bank_action, bank_request, "review-before-expansion")["state"]
    assert before["progress"]["reviewed"] == 2 and before["progress"]["pending"] == 0
    assert service.import_statement(tmp_path / "not-read.pdf", ["1111", "2222"])[0] == statement_id
    expanded = service.get_review_state(statement_id)
    assert expanded["counts"] == {"new": 0, "matched": 1, "bank": 0}
    assert expanded["history"] == before["history"]
    assert expanded["progress"]["reviewed"] == 2 and expanded["progress"]["total"] == 3
    matched = expanded["items"][0]
    assert matched["expense_id"] == expense_id and matched["bank_name"] == original["description"]
    final = service.review_batch(statement_id, "matched", "approve", [{"id": matched["id"]}], "match-added-card")["state"]
    assert final["progress"]["reviewed"] == 3 and final["progress"]["percent"] == 100
    assert all(item in final["history"] for item in before["history"])
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 1
    assert dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()) == original
    assert conn.execute("SELECT COUNT(*) FROM statement_review_items WHERE claimed_expense_id = ?", (expense_id,)).fetchone()[0] == 1
    retry = service.review_batch(statement_id, "bank", bank_action, bank_request, "review-before-expansion")
    assert retry["processed"] == 1 and retry["state"] == final
    with get_connection() as reloaded:
        assert StatementService(reloaded, user_id).get_review_state(statement_id) == final


@pytest.mark.parametrize("action", ["approve", "ignore"])
@pytest.mark.parametrize("unknown_count", [1, 2])
@pytest.mark.parametrize("same_known_line", [False, True])
def test_unknown_card_origin_survives_reimport_under_another_selection(
    review_env, monkeypatch, tmp_path, action, unknown_count, same_known_line
):
    conn, service, user_id = review_env
    unknown = _build_tx(description="IDENTICAL PURCHASE", raw_line="10/09 IDENTICAL PURCHASE 50,00",
                        ambiguous=True, card_last_four=None, card_holder=None)
    txs = [copy.deepcopy(unknown) for _ in range(unknown_count)]
    if same_known_line:
        txs.insert(0, _build_tx(description=unknown.description, raw_line=unknown.raw_line, card_last_four="1111"))
    parsed = ParsedStatement(
        file_hash="stable-unknown-origins", file_name="synthetic.pdf", due_date=date(2026, 10, 10),
        card_holders=[CardHolder(name="FIRST", last_four="1111"), CardHolder(name="SECOND", last_four="2222")],
        transactions=txs,
    )
    monkeypatch.setattr("services.statement_service.parse_bradesco_statement", lambda path: copy.deepcopy(parsed))
    statement_id, returned, _ = service.import_statement(tmp_path / "not-read.pdf", ["1111"])
    state = service.get_review_state(statement_id)
    assert len(state["items"]) == unknown_count + int(same_known_line)
    selected = [{"id": item["id"], "category": "Lazer"} for item in state["items"]]
    before = service.review_batch(statement_id, "new", action, selected, "review-unknown-origins")["state"]
    saved = [dict(row) for row in conn.execute("SELECT * FROM statement_transactions ORDER BY id")]
    for cards in (["2222"], ["1111", "2222"], None):
        assert service.import_statement(tmp_path / "not-read.pdf", cards)[0] == statement_id
        assert [dict(row) for row in conn.execute("SELECT * FROM statement_transactions ORDER BY id")] == saved
        assert service.get_review_state(statement_id)["history"] == before["history"]
        assert service.get_review_state(statement_id)["progress"] == before["progress"]
    assert sum(row["card_last_four"] is None for row in saved) == unknown_count
    assert all(tx.card_last_four is None for tx in returned.transactions if tx.ambiguous)
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == (len(saved) if action == "approve" else 0)


@pytest.mark.parametrize("action", ["approve", "ignore"])
def test_reimport_recognizes_legacy_inferred_unknown_occurrences_without_merging_known_lines(
    review_env, monkeypatch, tmp_path, action
):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id, "legacy-inferred-origins", cards="1111")
    for _ in range(3):
        tx_id = _review_tx(conn, statement_id, "IDENTICAL PURCHASE", 5000, card="1111")
        conn.execute("UPDATE statement_transactions SET raw_line = '10/09 IDENTICAL PURCHASE 50,00' WHERE id = ?", (tx_id,))
    conn.commit()
    selected = [{"id": item["id"], "category": "Lazer"} for item in service.get_review_state(statement_id)["items"]]
    before = service.review_batch(statement_id, "new", action, selected, "legacy-origin-decisions")["state"]
    saved = [dict(row) for row in conn.execute("SELECT * FROM statement_transactions ORDER BY id")]
    tx = _build_tx(description="IDENTICAL PURCHASE", raw_line="10/09 IDENTICAL PURCHASE 50,00",
                   installment_info="01/03", card_last_four="1111")
    unknown = copy.deepcopy(tx)
    unknown.card_last_four, unknown.ambiguous = None, True
    parsed = ParsedStatement(
        file_hash="legacy-inferred-origins", file_name="synthetic.pdf", due_date=date(2026, 10, 10),
        card_holders=[CardHolder(name="FIRST", last_four="1111"), CardHolder(name="SECOND", last_four="2222")],
        transactions=[tx, unknown, copy.deepcopy(unknown)],
    )
    monkeypatch.setattr("services.statement_service.parse_bradesco_statement", lambda path: copy.deepcopy(parsed))
    for cards in (["2222"], None):
        assert service.import_statement(tmp_path / "not-read.pdf", cards)[0] == statement_id
        assert [dict(row) for row in conn.execute("SELECT * FROM statement_transactions ORDER BY id")] == saved
        assert service.get_review_state(statement_id)["history"] == before["history"]
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == (3 if action == "approve" else 0)


def test_match_without_category_edit_records_the_expense_category_not_an_unapplied_suggestion(review_env):
    conn, service, user_id = review_env
    statement_id = _statement(conn, user_id)
    expense_id = _insert_credit_expense(conn, user_id, 50, "ORIGINAL BOT DESCRIPTION", date(2026, 9, 10))
    conn.execute("UPDATE expenses SET category = 'Educação' WHERE id = ?", (expense_id,))
    conn.commit()
    tx_id = _review_tx(conn, statement_id, "STATEMENT ORIGINAL", 5000, category="Lazer")
    item = service.get_review_state(statement_id)["items"][0]
    assert item["category"] == "Lazer" and item["category_edited"] is False
    before = dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone())
    state = service.review_batch(statement_id, "matched", "approve", [{"id": f"tx:{tx_id}"}], "no-category-edit")["state"]
    assert state["history"][0]["category"] == "Educação"
    assert dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()) == before
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0
    assert service._suggester.suggest_from_history("STATEMENT ORIGINAL") == "Educação"


def test_separate_legacy_imports_of_a_known_line_do_not_consume_an_unknown_origin(review_env, monkeypatch, tmp_path):
    conn, service, user_id = review_env
    first = _statement(conn, user_id, "separate-known-copies", cards="1111,3333")
    second = _statement(conn, user_id, "separate-known-copies", cards="1111,2222")
    for statement_id in (first, second):
        tx_id = _review_tx(conn, statement_id, "IDENTICAL PURCHASE", 5000, card="1111")
        conn.execute("UPDATE statement_transactions SET raw_line = '10/09 IDENTICAL PURCHASE 50,00' WHERE id = ?", (tx_id,))
        conn.commit()
        assert service.reject(tx_id)["success"]
    originals = [dict(row) for row in conn.execute("SELECT * FROM statement_transactions ORDER BY id")]
    known = _build_tx(description="IDENTICAL PURCHASE", raw_line="10/09 IDENTICAL PURCHASE 50,00",
                      installment_info="01/03", card_last_four="1111")
    unknown = copy.deepcopy(known)
    unknown.card_last_four, unknown.ambiguous = None, True
    parsed = ParsedStatement(
        file_hash="separate-known-copies", file_name="synthetic.pdf", due_date=date(2026, 10, 10),
        card_holders=[CardHolder(name="SYNTHETIC", last_four=card) for card in ("1111", "2222", "3333")],
        transactions=[known, unknown],
    )
    monkeypatch.setattr("services.statement_service.parse_bradesco_statement", lambda path: copy.deepcopy(parsed))
    statement_id, _, _ = service.import_statement(tmp_path / "not-read.pdf", ["2222"])
    state = service.get_review_state(statement_id)
    assert state["counts"] == {"new": 1, "matched": 0, "bank": 0}
    assert state["items"][0]["card_last_four"] is None
    assert [dict(row) for row in conn.execute("SELECT * FROM statement_transactions ORDER BY id LIMIT 2")] == originals
    unknown_id = state["items"][0]["id"]
    service.review_batch(statement_id, "new", "approve", [{"id": unknown_id, "category": "Lazer"}], "distinct-unknown-origin")
    service.import_statement(tmp_path / "not-read.pdf")
    assert conn.execute("SELECT COUNT(*) FROM statement_transactions").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 1


def test_approve_installment_generates_future_parcels(test_db):
    """Aprovar uma parcela deve gerar as parcelas futuras como despesas."""
    from database.setup import get_connection
    from database.user_setup import create_or_update_user

    conn = get_connection()
    user = create_or_update_user(conn, telegram_id=123499, name="TesteParcela")
    user_id = user["id"]

    service = StatementService(conn, user_id)

    cursor = conn.execute(
        """
        INSERT INTO card_statements (user_id, file_hash, file_name, statement_date, due_date, total_cents, card_last_four, card_holder, status)
        VALUES (?, 'hash-install', 'fatura.pdf', '2026-09-10', '2026-09-10', 15445, '3006', 'LEANDRO', 'pending')
        """,
        (user_id,),
    )
    statement_id = cursor.lastrowid

    cur = conn.execute(
        """
        INSERT INTO statement_transactions (statement_id, card_holder, card_last_four, transaction_date, description, amount_cents, installment_info, installment_current, installment_total, original_purchase_date, raw_line)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (statement_id, "LEANDRO", "3006", "2026-08-01", "PAYPAL *DSA ACADEMY", 15445, "07/11", 7, 11, "2026-03-13", "13/03 PAYPAL *DSA ACADEMY 07/11 SAO PAULO 154,45"),
    )
    tx_id = cur.lastrowid
    conn.commit()

    summary = service.confirm_reconciliation(
        statement_id,
        insert_ids=[tx_id],
        update_pairs=[],
        delete_ids=[],
        default_category="Outros",
    )

    assert summary["inserted"] == 1

    # Deve ter criado 1 despesa atual + 4 futuras (parcelas 8 a 11)
    expenses = conn.execute(
        """SELECT expense_date, amount, description FROM expenses
           WHERE user_id = ? AND deleted_at IS NULL
           ORDER BY expense_date""",
        (user_id,),
    ).fetchall()
    assert len(expenses) == 5
    assert [str(row["expense_date"]) for row in expenses] == [
        "2026-08-01", "2026-09-01", "2026-10-01", "2026-11-01", "2026-12-01"
    ]
    for row in expenses:
        assert row["amount"] == 154.45
        assert row["description"] == "PAYPAL *DSA ACADEMY"

    # Deve ter criado o grupo e as parcelas no controle de parcelamento
    group = conn.execute("SELECT * FROM installment_groups WHERE user_id = ?", (user_id,)).fetchone()
    assert group is not None
    assert group["total_parcels"] == 11
    parcels = conn.execute(
        "SELECT * FROM installment_parcels WHERE group_id = ? ORDER BY parcel_number",
        (group["id"],),
    ).fetchall()
    assert len(parcels) == 5
    assert parcels[0]["parcel_number"] == 7
    assert parcels[0]["expense_id"] is not None
    assert parcels[4]["parcel_number"] == 11


def test_future_installment_statement_matches_generated_expense(test_db):
    """Importar fatura futura deve casar com despesa gerada anteriormente."""
    from database.setup import get_connection
    from database.user_setup import create_or_update_user

    conn = get_connection()
    user = create_or_update_user(conn, telegram_id=123500, name="TesteParcelaFutura")
    user_id = user["id"]

    service = StatementService(conn, user_id)

    # Fatura atual com parcela 7/11
    cursor = conn.execute(
        """
        INSERT INTO card_statements (user_id, file_hash, file_name, statement_date, due_date, total_cents, card_last_four, card_holder, status)
        VALUES (?, 'hash-current', 'fatura_atual.pdf', '2026-09-10', '2026-09-10', 15445, '3006', 'LEANDRO', 'pending')
        """,
        (user_id,),
    )
    current_statement_id = cursor.lastrowid

    cur = conn.execute(
        """
        INSERT INTO statement_transactions (statement_id, card_holder, card_last_four, transaction_date, description, amount_cents, installment_info, installment_current, installment_total, original_purchase_date, raw_line)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (current_statement_id, "LEANDRO", "3006", "2026-08-01", "PAYPAL *DSA ACADEMY", 15445, "07/11", 7, 11, "2026-03-13", "13/03 PAYPAL *DSA ACADEMY 07/11 SAO PAULO 154,45"),
    )
    current_tx_id = cur.lastrowid
    conn.commit()

    service.confirm_reconciliation(
        current_statement_id,
        insert_ids=[current_tx_id],
        update_pairs=[],
        delete_ids=[],
        default_category="Outros",
    )

    # Fatura futura com parcela 8/11
    cursor = conn.execute(
        """
        INSERT INTO card_statements (user_id, file_hash, file_name, statement_date, due_date, total_cents, card_last_four, card_holder, status)
        VALUES (?, 'hash-future', 'fatura_futura.pdf', '2026-10-10', '2026-10-10', 15445, '3006', 'LEANDRO', 'pending')
        """,
        (user_id,),
    )
    future_statement_id = cursor.lastrowid

    conn.execute(
        """
        INSERT INTO statement_transactions (statement_id, card_holder, card_last_four, transaction_date, description, amount_cents, installment_info, installment_current, installment_total, original_purchase_date, raw_line)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (future_statement_id, "LEANDRO", "3006", "2026-09-01", "PAYPAL *DSA ACADEMY", 15445, "08/11", 8, 11, "2026-03-13", "13/03 PAYPAL *DSA ACADEMY 08/11 SAO PAULO 154,45"),
    )
    conn.commit()

    result = service.reconcile(future_statement_id)
    section = result.sections.get("3006")
    assert section is not None
    assert len(section.matched) == 1
    assert len(section.only_on_statement) == 0
    # A parcela 8/11 deve ter sido casada com a despesa gerada no passo anterior
    assert section.matched[0].statement_tx.installment_current == 8
    assert section.matched[0].expense["expense_date"] == "2026-09-01"
