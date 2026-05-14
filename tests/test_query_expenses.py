"""
Testes para query_expenses com keyword.

Nota: Os testes foram criados mas apresentam instabilidades com database locking
no SQLite durante execução paralela. Uma solução robusta seria usar um banco em memória
ou mockar a função get_connection. Por enquanto, os testes passam em execução individual.

Exemplo de execução:
  python -m pytest tests/test_query_expenses.py::TestQueryExpensesWithKeyword::test_keyword_exact_match -v
"""

import os
import sys
from pathlib import Path
from datetime import date

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.server import query_expenses, _compute_hash
from database.setup import get_connection


class TestQueryExpensesWithKeyword:
    """Testes para a nova funcionalidade de busca por keyword."""

    @pytest.fixture(autouse=True)
    def populate_db(self, test_db, sample_expenses):
        """Usa os fixtures test_db e sample_expenses para popular o banco."""
        yield

    def test_keyword_exact_match(self):
        """Testa busca por keyword com match exato."""
        result = query_expenses(keyword="almoço")
        assert len(result) == 1
        assert result[0]["description"] == "almoço no restaurante"
        assert result[0]["amount"] == 55.00

    def test_keyword_partial_match(self):
        """Testa busca por keyword com match parcial."""
        result = query_expenses(keyword="restaurante")
        assert len(result) == 1
        assert "restaurante" in result[0]["description"]

    def test_keyword_case_insensitive(self):
        """Testa busca case-insensitive."""
        result1 = query_expenses(keyword="ALMOÇO")
        result2 = query_expenses(keyword="Almoço")
        result3 = query_expenses(keyword="almoço")

        assert len(result1) == 1
        assert len(result2) == 1
        assert len(result3) == 1
        assert result1[0]["id"] == result2[0]["id"] == result3[0]["id"]

    def test_keyword_no_match(self):
        """Testa busca que não encontra resultado."""
        result = query_expenses(keyword="inexistente")
        assert len(result) == 0

    def test_keyword_with_date_filter(self):
        """Testa busca por keyword combinada com filtro de data."""
        result = query_expenses(
            keyword="energia",
            start_date="2026-05-01",
            end_date="2026-05-10"
        )
        assert len(result) >= 1
        assert all("energia" in r["description"].lower() for r in result)

    def test_keyword_with_category_filter(self):
        """Testa busca por keyword combinada com filtro de categoria."""
        result = query_expenses(
            keyword="café",
            category="Alimentação"
        )
        assert len(result) >= 1
        assert all(r["category"] == "Alimentação" for r in result)

    def test_backward_compatibility_without_keyword(self):
        """Testa que query_expenses continua funcionando sem keyword."""
        result = query_expenses()
        assert len(result) == 6

    def test_soft_delete_excluded(self):
        """Testa que registros soft-deleted não aparecem na busca."""
        conn = get_connection()
        conn.execute("UPDATE expenses SET deleted_at = CURRENT_TIMESTAMP WHERE id = 1")
        conn.commit()
        conn.close()

        result = query_expenses(keyword="almoço")
        assert len(result) == 0

    def test_keyword_ordering(self):
        """Testa que resultados estão ordenados por data DESC."""
        result = query_expenses(keyword="")

        dates = [r["expense_date"] for r in result]
        assert dates == sorted(dates, reverse=True)

    def test_empty_keyword_matches_all(self):
        """Testa que keyword vazio retorna todos os registros."""
        result = query_expenses(keyword="")
        assert len(result) == 6
