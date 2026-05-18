import sqlite3
import sys
from pathlib import Path
from datetime import date as date_class

import pytest

sys.path = [str(Path(__file__).parent.parent)] + sys.path


@pytest.fixture(scope="function")
def test_db(tmp_path, monkeypatch):
    """Banco isolado por teste via tmp_path — resolve o problema de DB locking."""
    import config

    db_path = str(tmp_path / "test_financas.db")
    monkeypatch.setattr(config.settings, "db_path", db_path)

    from database.setup import setup_database
    setup_database()

    yield db_path


@pytest.fixture
def sample_expenses(test_db):
    """Popula o banco com 6 gastos de exemplo."""
    from database.setup import get_connection
    from mcp_server.server import _compute_hash

    conn = get_connection()
    cursor = conn.cursor()

    expenses_data = [
        (55.00,  "almoço no restaurante", "Alimentação", "dinheiro",     "2026-05-10"),
        (120.00, "conta de energia",       "Serviços",    "pix",          "2026-05-08"),
        (35.50,  "café da manhã",          "Alimentação", "crédito",      "2026-05-13"),
        (80.00,  "uber para casa",         "Transporte",  "débito",       "2026-05-12"),
        (250.00, "farmácia - remédios",    "Saúde",       "dinheiro",     "2026-05-11"),
        (45.00,  "luz residencial",        "Serviços",    "transferência","2026-05-09"),
    ]

    for amount, desc, cat, method, expense_date in expenses_data:
        hash_val = _compute_hash(amount, desc, date_class.fromisoformat(expense_date))
        cursor.execute(
            "INSERT INTO expenses (amount, description, category, method, expense_date, hash) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (amount, desc, cat, method, expense_date, hash_val),
        )

    conn.commit()
    conn.close()

    yield


@pytest.fixture
def inserted_expense(test_db):
    """Insere uma despesa via record_expense e retorna seu ID."""
    from mcp_server.server import record_expense
    result = record_expense(55.0, "almoço no restaurante", "Alimentação", "dinheiro", "2026-05-10")
    assert "id" in result, f"Falha ao inserir despesa de teste: {result}"
    return result["id"]
