"""
Testes para query_expenses com keyword.

Isolamento: cada teste usa banco temporário independente (fixture test_db).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.setup import get_connection
from services.expense_service import ExpenseService


class TestQueryExpensesWithKeyword:
    """Testes para a funcionalidade de busca por keyword."""

    @pytest.fixture(autouse=True)
    def populate_db(self, test_db, sample_expenses):
        """Usa os fixtures test_db e sample_expenses para popular o banco."""
        yield

    @pytest.fixture
    def service(self, test_db):
        conn = get_connection()
        return ExpenseService(conn, user_id=None)

    def test_keyword_exact_match(self, service):
        """Testa busca por keyword com match exato."""
        result = service.query_expenses(keyword="almoço")
        assert len(result) == 1
        assert result[0]["description"] == "almoço no restaurante"
        assert result[0]["amount"] == 55.00

    def test_keyword_partial_match(self, service):
        """Testa busca por keyword com match parcial."""
        result = service.query_expenses(keyword="restaurante")
        assert len(result) == 1
        assert "restaurante" in result[0]["description"]

    def test_keyword_case_insensitive(self, service):
        """Testa busca case-insensitive."""
        result1 = service.query_expenses(keyword="ALMOÇO")
        result2 = service.query_expenses(keyword="Almoço")
        result3 = service.query_expenses(keyword="almoço")

        assert len(result1) == 1
        assert len(result2) == 1
        assert len(result3) == 1
        assert result1[0]["id"] == result2[0]["id"] == result3[0]["id"]

    def test_keyword_no_match(self, service):
        """Testa busca que não encontra resultado."""
        result = service.query_expenses(keyword="inexistente")
        assert len(result) == 0

    def test_keyword_with_date_filter(self, service):
        """Testa busca por keyword combinada com filtro de data."""
        result = service.query_expenses(
            keyword="energia",
            start_date="2026-05-01",
            end_date="2026-05-10"
        )
        assert len(result) >= 1
        assert all("energia" in r["description"].lower() for r in result)

    def test_keyword_with_category_filter(self, service):
        """Testa busca por keyword combinada com filtro de categoria."""
        result = service.query_expenses(
            keyword="café",
            category="Alimentação"
        )
        assert len(result) >= 1
        assert all(r["category"] == "Alimentação" for r in result)

    def test_backward_compatibility_without_keyword(self, service):
        """Testa que query_expenses continua funcionando sem keyword."""
        result = service.query_expenses()
        assert len(result) == 6

    def test_soft_delete_excluded(self, service):
        """Testa que registros soft-deleted não aparecem na busca."""
        conn = get_connection()
        conn.execute("UPDATE expenses SET deleted_at = CURRENT_TIMESTAMP WHERE id = 1")
        conn.commit()
        conn.close()

        result = service.query_expenses(keyword="almoço")
        assert len(result) == 0

    def test_keyword_ordering(self, service):
        """Testa que resultados estão ordenados por data DESC."""
        result = service.query_expenses(keyword="")

        dates = [r["expense_date"] for r in result]
        assert dates == sorted(dates, reverse=True)

    def test_empty_keyword_matches_all(self, service):
        """Testa que keyword vazio retorna todos os registros."""
        result = service.query_expenses(keyword="")
        assert len(result) == 6
