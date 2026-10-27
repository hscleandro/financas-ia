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

    # Verifica atualização
    updated = conn.execute("SELECT description, expense_date FROM expenses WHERE id = ?", (exp_id,)).fetchone()
    assert updated["description"] == "CAFE DA MANHA"

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


def test_approve_match_updates_expense(test_db):
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
    assert updated["description"] == "ALMOCO RESTAURANTE"

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
