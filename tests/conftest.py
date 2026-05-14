import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from datetime import date

import pytest

sys.path = [str(Path(__file__).parent.parent)] + sys.path


@pytest.fixture(scope="function")
def test_db():
    """Fixture que cria um banco de dados isolado para cada teste."""
    # Cria um arquivo temporário para o banco
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.db') as f:
        db_path = f.name

    try:
        # Configura o ambiente para usar o banco de teste
        os.environ['DB_PATH'] = db_path

        # Importa e executa setup após configurar DB_PATH
        from database.setup import setup_database, get_connection
        setup_database()

        yield db_path

    finally:
        # Remove o arquivo temporário
        try:
            os.unlink(db_path)
        except FileNotFoundError:
            pass

        # Limpa a variável de ambiente
        os.environ.pop('DB_PATH', None)


@pytest.fixture
def sample_expenses(test_db):
    """Fixture que popula o banco com alguns gastos de exemplo."""
    from database.setup import get_connection
    from mcp_server.server import _compute_hash
    from datetime import date as date_class

    conn = get_connection()
    cursor = conn.cursor()

    # Insere despesas de exemplo (sem hash — será computado)
    expenses_data = [
        (55.00, "almoço no restaurante", "Alimentação", "dinheiro", "2026-05-10"),
        (120.00, "conta de energia", "Serviços", "pix", "2026-05-08"),
        (35.50, "café da manhã", "Alimentação", "crédito", "2026-05-13"),
        (80.00, "uber para casa", "Transporte", "débito", "2026-05-12"),
        (250.00, "farmácia - remédios", "Saúde", "dinheiro", "2026-05-11"),
        (45.00, "luz residencial", "Serviços", "transferência", "2026-05-09"),
    ]

    for amount, desc, cat, method, expense_date in expenses_data:
        # Computa o hash corretamente
        hash_val = _compute_hash(amount, desc, date_class.fromisoformat(expense_date))
        cursor.execute(
            "INSERT INTO expenses (amount, description, category, method, expense_date, hash) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (amount, desc, cat, method, expense_date, hash_val)
        )

    conn.commit()
    conn.close()

    yield

    # Cleanup é feito por test_db
