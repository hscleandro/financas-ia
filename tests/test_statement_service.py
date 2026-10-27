"""Testes do serviço de conciliação de faturas."""
from datetime import date

import pytest

from database.setup import get_connection
from services.statement_parser import ParsedTransaction
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

    result = service.reconcile(statement_id, card_last_four="3006")

    assert len(result.matched) == 1
    assert result.matched[0].expense["id"] == exp_id
    assert result.matched[0].statement_tx.amount_cents == 5000
    assert len(result.only_on_statement) == 0
    assert len(result.only_on_database) == 0


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

    result = service.reconcile(statement_id, card_last_four="3006")
    assert len(result.matched) == 1
    assert result.matched[0].expense["id"] == exp_id


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

    result = service.reconcile(statement_id, card_last_four="3006")
    assert len(result.matched) == 0
    assert len(result.only_on_statement) == 1
    assert len(result.only_on_database) == 1


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

    result = service.reconcile(statement_id, card_last_four="3006")
    # Como há múltiplos candidatos, deve ir para ambíguo
    assert len(result.ambiguous) == 1
    assert len(result.matched) == 0


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

    # Verifica atualização
    updated = conn.execute("SELECT description, expense_date FROM expenses WHERE id = ?", (exp_id,)).fetchone()
    assert updated["description"] == "CAFE DA MANHA"

    # Verifica inserção
    inserted = conn.execute("SELECT description FROM expenses WHERE description = ? AND user_id = ?", ("SUPERMERCADO", user_id)).fetchone()
    assert inserted is not None

    # Verifica soft delete
    deleted = conn.execute("SELECT deleted_at FROM expenses WHERE id = ?", (del_id,)).fetchone()
    assert deleted["deleted_at"] is not None
