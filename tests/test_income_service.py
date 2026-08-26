"""Testes do IncomeService."""
import pytest

from database.setup import get_connection
from database.user_setup import create_user
from services.income_service import IncomeService


@pytest.fixture
def income_service(test_db):
    conn = get_connection()
    user_id = create_user(conn, telegram_id=123456789, name="Test User")
    yield IncomeService(conn, user_id=user_id)
    conn.close()


class TestRecordIncome:
    def test_success(self, income_service):
        result = income_service.record_income(5000.0, "Salário agosto", "Salário", "2026-08-01")
        assert "id" in result
        assert result["amount"] == 5000.0
        assert result["description"] == "Salário agosto"
        assert result["category"] == "Salário"
        assert result["income_date"] == "2026-08-01"

    def test_default_date(self, income_service):
        from datetime import date
        result = income_service.record_income(1000.0, "Freela", "Freela")
        assert result["income_date"] == date.today().isoformat()

    def test_duplicate_rejected(self, income_service):
        income_service.record_income(1000.0, "Freela", "Freela", "2026-08-01")
        result = income_service.record_income(1000.0, "Freela", "Freela", "2026-08-01")
        assert result.get("tipo") == "duplicata"

    def test_invalid_category(self, income_service):
        result = income_service.record_income(1000.0, "Teste", "CategoriaInexistente")
        assert result.get("tipo") == "invalido"

    def test_invalid_amount_zero(self, income_service):
        result = income_service.record_income(0, "Teste", "Salário")
        assert result.get("tipo") == "invalido"

    def test_invalid_future_date(self, income_service):
        result = income_service.record_income(1000.0, "Teste", "Salário", "2099-01-01")
        assert result.get("tipo") == "invalido"


class TestQueryIncomes:
    @pytest.fixture(autouse=True)
    def populate(self, test_db):
        conn = get_connection()
        user_id = create_user(conn, telegram_id=123456789, name="Test User")
        service = IncomeService(conn, user_id=user_id)
        service.record_income(5000.0, "Salário agosto", "Salário", "2026-08-01")
        service.record_income(1500.0, "Freela site", "Freela", "2026-08-10")
        service.record_income(300.0, "Dividendos", "Investimentos", "2026-08-15")
        conn.close()

    @pytest.fixture
    def income_service(self, test_db):
        conn = get_connection()
        # Reutiliza o usuário criado no populate
        row = conn.execute("SELECT id FROM users WHERE telegram_id = ?", (123456789,)).fetchone()
        user_id = row["id"]
        return IncomeService(conn, user_id=user_id)

    def test_all_without_filters(self, income_service):
        result = income_service.query_incomes()
        assert len(result) == 3

    def test_filter_by_category(self, income_service):
        result = income_service.query_incomes(category="Salário")
        assert len(result) == 1
        assert result[0]["category"] == "Salário"

    def test_filter_by_date_range(self, income_service):
        result = income_service.query_incomes(start_date="2026-08-01", end_date="2026-08-05")
        assert len(result) == 1

    def test_keyword_search(self, income_service):
        result = income_service.query_incomes(keyword="freela")
        assert len(result) == 1
        assert "Freela" in result[0]["description"]

    def test_keyword_accent_insensitive(self, income_service):
        result = income_service.query_incomes(keyword="dividendo")
        assert len(result) == 1


class TestIncomeSummary:
    @pytest.fixture(autouse=True)
    def populate(self, test_db):
        conn = get_connection()
        user_id = create_user(conn, telegram_id=123456789, name="Test User")
        service = IncomeService(conn, user_id=user_id)
        service.record_income(5000.0, "Salário", "Salário", "2026-08-01")
        service.record_income(1500.0, "Freela", "Freela", "2026-08-10")
        service.record_income(300.0, "Dividendos", "Investimentos", "2026-08-15")
        conn.close()

    @pytest.fixture
    def income_service(self, test_db):
        conn = get_connection()
        row = conn.execute("SELECT id FROM users WHERE telegram_id = ?", (123456789,)).fetchone()
        user_id = row["id"]
        return IncomeService(conn, user_id=user_id)

    def test_summary_by_category(self, income_service):
        result = income_service.get_income_summary("2026-08-01", "2026-08-31", "category")
        assert result["group_by"] == "category"
        assert result["total_geral"] == 6800.0
        dimensions = [i["dimension"] for i in result["items"]]
        assert "Salário" in dimensions

    def test_summary_by_month(self, income_service):
        result = income_service.get_income_summary("2026-08-01", "2026-08-31", "month")
        assert result["items"][0]["dimension"] == "2026-08"

    def test_invalid_group_by(self, income_service):
        result = income_service.get_income_summary("2026-08-01", "2026-08-31", "semana")
        assert "error" in result


class TestIncomeCategories:
    def test_list_default_categories(self, income_service):
        cats = income_service.list_income_categories()
        assert "Salário" in cats
        assert "Freela" in cats
        assert "Investimentos" in cats
        assert "Outros" in cats

    def test_create_category_success(self, income_service):
        result = income_service.create_income_category("Comissões", confirmed=True)
        assert result.get("created") is True
        assert "Comissões" in income_service.list_income_categories()

    def test_create_category_unconfirmed(self, income_service):
        result = income_service.create_income_category("Comissões", confirmed=False)
        assert result.get("tipo") == "nao_confirmado"

    def test_create_duplicate_category(self, income_service):
        income_service.create_income_category("Comissões", confirmed=True)
        result = income_service.create_income_category("comissões", confirmed=True)
        assert result.get("tipo") == "duplicata"


class TestDeleteIncome:
    @pytest.fixture
    def income_id(self, income_service):
        result = income_service.record_income(1000.0, "Teste", "Outros", "2026-08-01")
        return result["id"]

    def test_delete_unconfirmed(self, income_service, income_id):
        result = income_service.delete_income(income_id, confirmed=False)
        assert result.get("tipo") == "nao_confirmado"

    def test_delete_success(self, income_service, income_id):
        result = income_service.delete_income(income_id, confirmed=True)
        assert result.get("deleted") is True
        assert len(income_service.query_incomes(keyword="teste")) == 0


class TestUpdateIncome:
    @pytest.fixture
    def income_id(self, income_service):
        result = income_service.record_income(1000.0, "Teste", "Outros", "2026-08-01")
        return result["id"]

    def test_update_unconfirmed(self, income_service, income_id):
        result = income_service.update_income(income_id, confirmed=False, amount=2000.0)
        assert result.get("tipo") == "nao_confirmado"

    def test_update_amount(self, income_service, income_id):
        result = income_service.update_income(income_id, confirmed=True, amount=2000.0)
        assert result.get("updated") is True
        assert result["new"]["amount"] == 2000.0
        assert result["old"]["amount"] == 1000.0

    def test_update_invalid_category(self, income_service, income_id):
        result = income_service.update_income(income_id, confirmed=True, category="Inexistente")
        assert result.get("tipo") == "invalido"
