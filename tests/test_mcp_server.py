"""
Testes do mcp_server/server.py.

Cobertura alvo: ≥80% do módulo.
Isolamento: cada teste usa banco temporário independente (fixture test_db).
"""

import json
import sys
from pathlib import Path
from datetime import date

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.server import (
    record_expense,
    query_expenses,
    get_summary,
    list_categories,
    list_payment_methods,
    create_category,
    create_payment_method,
    find_expense_candidates,
    delete_expense,
    update_expense,
    _compute_hash,
    _normalize_description,
    _validate_category_name,
    _validate_method_name,
)
from database.setup import get_connection


# ─── Utilitários internos ─────────────────────────────────────────────────────

class TestUtilities:
    def test_normalize_description_lowercase(self):
        assert _normalize_description("ALMOÇO") == "almoco"

    def test_normalize_description_remove_accents(self):
        assert _normalize_description("café") == "cafe"

    def test_normalize_description_collapse_spaces(self):
        assert _normalize_description("  uber   para  casa  ") == "uber para casa"

    def test_normalize_description_mixed(self):
        assert _normalize_description("Farmácia - Remédios") == "farmacia - remedios"

    def test_compute_hash_deterministic(self):
        h1 = _compute_hash(55.0, "almoço", date(2026, 5, 10))
        h2 = _compute_hash(55.0, "almoço", date(2026, 5, 10))
        assert h1 == h2

    def test_compute_hash_different_amounts(self):
        h1 = _compute_hash(55.0, "almoço", date(2026, 5, 10))
        h2 = _compute_hash(56.0, "almoço", date(2026, 5, 10))
        assert h1 != h2

    def test_compute_hash_normalizes_description(self):
        h1 = _compute_hash(55.0, "ALMOÇO",  date(2026, 5, 10))
        h2 = _compute_hash(55.0, "almoço",  date(2026, 5, 10))
        assert h1 == h2

    def test_validate_category_name_valid(self):
        clean, err = _validate_category_name("entretenimento")
        assert err is None
        assert clean == "Entretenimento"

    def test_validate_category_name_too_short(self):
        _, err = _validate_category_name("x")
        assert err is not None

    def test_validate_category_name_too_long(self):
        _, err = _validate_category_name("a" * 31)
        assert err is not None

    def test_validate_category_name_invalid_chars(self):
        _, err = _validate_category_name("Categoria123")
        assert err is not None

    def test_validate_method_name_valid(self):
        clean, err = _validate_method_name("Boleto")
        assert err is None
        assert clean == "boleto"

    def test_validate_method_name_too_short(self):
        _, err = _validate_method_name("x")
        assert err is not None


# ─── record_expense ───────────────────────────────────────────────────────────

class TestRecordExpense:
    @pytest.fixture(autouse=True)
    def use_db(self, test_db):
        pass

    def test_success_returns_id_and_fields(self):
        result = record_expense(55.0, "almoço no restaurante", "Alimentação", "dinheiro", "2026-05-10")
        assert "id" in result
        assert result["amount"] == 55.0
        assert result["description"] == "almoço no restaurante"
        assert result["category"] == "Alimentação"
        assert result["method"] == "dinheiro"
        assert result["expense_date"] == "2026-05-10"

    def test_success_default_date(self):
        result = record_expense(30.0, "café", "Alimentação", "pix")
        assert "expense_date" in result
        assert result["expense_date"] == date.today().isoformat()

    def test_duplicate_rejected(self):
        record_expense(55.0, "almoço", "Alimentação", "dinheiro", "2026-05-10")
        result = record_expense(55.0, "almoço", "Alimentação", "dinheiro", "2026-05-10")
        assert result.get("tipo") == "duplicata"

    def test_duplicate_case_insensitive_description(self):
        record_expense(55.0, "ALMOÇO", "Alimentação", "dinheiro", "2026-05-10")
        result = record_expense(55.0, "almoço", "Alimentação", "dinheiro", "2026-05-10")
        assert result.get("tipo") == "duplicata"

    def test_invalid_category(self):
        result = record_expense(55.0, "gasto", "CategoriaInexistente", "dinheiro")
        assert result.get("tipo") == "invalido"
        assert "Categoria" in result["error"]

    def test_invalid_method(self):
        result = record_expense(55.0, "gasto", "Alimentação", "cheque")
        assert result.get("tipo") == "invalido"
        assert "Método" in result["error"]

    def test_invalid_amount_zero(self):
        result = record_expense(0, "gasto", "Alimentação", "dinheiro")
        assert result.get("tipo") == "invalido"

    def test_invalid_amount_negative(self):
        result = record_expense(-10.0, "gasto", "Alimentação", "dinheiro")
        assert result.get("tipo") == "invalido"

    def test_invalid_amount_too_large(self):
        result = record_expense(200_000.0, "gasto", "Alimentação", "dinheiro")
        assert result.get("tipo") == "invalido"

    def test_persisted_in_db(self):
        record_expense(42.0, "cinema", "Lazer", "crédito", "2026-05-15")
        conn = get_connection()
        row = conn.execute("SELECT * FROM expenses WHERE description = 'cinema'").fetchone()
        conn.close()
        assert row is not None
        assert row["amount"] == 42.0


# ─── query_expenses ────────────────────────────────────────────────────────────

class TestQueryExpenses:
    @pytest.fixture(autouse=True)
    def use_db(self, test_db, sample_expenses):
        pass

    def test_returns_all_without_filters(self):
        result = query_expenses()
        assert len(result) == 6

    def test_filter_by_category(self):
        result = query_expenses(category="Alimentação")
        assert len(result) == 2
        assert all(r["category"] == "Alimentação" for r in result)

    def test_filter_by_method(self):
        result = query_expenses(method="dinheiro")
        assert len(result) == 2

    def test_filter_by_date_range(self):
        result = query_expenses(start_date="2026-05-11", end_date="2026-05-13")
        assert len(result) == 3

    def test_keyword_exact(self):
        result = query_expenses(keyword="uber")
        assert len(result) == 1
        assert "uber" in result[0]["description"]

    def test_keyword_accent_insensitive(self):
        result = query_expenses(keyword="farmacia")
        assert len(result) == 1

    def test_keyword_no_match(self):
        assert query_expenses(keyword="inexistente") == []

    def test_ordered_by_date_desc(self):
        result = query_expenses()
        dates = [r["expense_date"] for r in result]
        assert dates == sorted(dates, reverse=True)

    def test_soft_deleted_excluded(self):
        conn = get_connection()
        conn.execute("UPDATE expenses SET deleted_at = CURRENT_TIMESTAMP WHERE id = 1")
        conn.commit()
        conn.close()
        assert len(query_expenses()) == 5


# ─── get_summary ──────────────────────────────────────────────────────────────

class TestGetSummary:
    @pytest.fixture(autouse=True)
    def use_db(self, test_db, sample_expenses):
        pass

    def test_summary_by_category(self):
        result = get_summary("2026-05-01", "2026-05-31", "category")
        assert result["group_by"] == "category"
        assert "items" in result
        assert result["total_geral"] > 0
        dimensions = [i["dimension"] for i in result["items"]]
        assert "Alimentação" in dimensions

    def test_summary_by_method(self):
        result = get_summary("2026-05-01", "2026-05-31", "method")
        assert result["group_by"] == "method"
        methods = [i["dimension"] for i in result["items"]]
        assert "dinheiro" in methods

    def test_summary_by_day(self):
        result = get_summary("2026-05-10", "2026-05-13", "day")
        assert result["group_by"] == "day"
        assert len(result["items"]) > 0

    def test_summary_by_month(self):
        result = get_summary("2026-05-01", "2026-05-31", "month")
        assert result["group_by"] == "month"
        assert result["items"][0]["dimension"] == "2026-05"

    def test_invalid_group_by(self):
        result = get_summary("2026-05-01", "2026-05-31", "semana")
        assert "error" in result

    def test_empty_period(self):
        result = get_summary("2025-01-01", "2025-01-31", "category")
        assert result["total_geral"] == 0
        assert result["items"] == []


# ─── list_categories / list_payment_methods ───────────────────────────────────

class TestListTools:
    @pytest.fixture(autouse=True)
    def use_db(self, test_db):
        pass

    def test_list_categories_returns_seeds(self):
        cats = list_categories()
        assert isinstance(cats, list)
        assert "Alimentação" in cats
        assert "Transporte" in cats
        assert len(cats) == 10

    def test_list_payment_methods_returns_seeds(self):
        methods = list_payment_methods()
        assert isinstance(methods, list)
        assert "dinheiro" in methods
        assert "pix" in methods
        assert len(methods) == 5


# ─── create_category ──────────────────────────────────────────────────────────

class TestCreateCategory:
    @pytest.fixture(autouse=True)
    def use_db(self, test_db):
        pass

    def test_confirmed_false_rejected(self):
        result = create_category("Entretenimento", confirmed=False)
        assert result["tipo"] == "nao_confirmado"

    def test_success(self):
        result = create_category("Entretenimento", confirmed=True)
        assert result["created"] is True
        assert result["name"] == "Entretenimento"

    def test_success_appears_in_list(self):
        create_category("Hobbies", confirmed=True)
        assert "Hobbies" in list_categories()

    def test_duplicate_rejected(self):
        create_category("Entretenimento", confirmed=True)
        result = create_category("entretenimento", confirmed=True)
        assert result["tipo"] == "duplicata"

    def test_system_category_duplicate(self):
        result = create_category("Alimentação", confirmed=True)
        assert result["tipo"] == "duplicata"

    def test_invalid_name_too_short(self):
        result = create_category("x", confirmed=True)
        assert result["tipo"] == "invalido"

    def test_invalid_name_with_numbers(self):
        result = create_category("Cat123", confirmed=True)
        assert result["tipo"] == "invalido"


# ─── create_payment_method ────────────────────────────────────────────────────

class TestCreatePaymentMethod:
    @pytest.fixture(autouse=True)
    def use_db(self, test_db):
        pass

    def test_confirmed_false_rejected(self):
        result = create_payment_method("boleto", confirmed=False)
        assert result["tipo"] == "nao_confirmado"

    def test_success(self):
        result = create_payment_method("boleto", confirmed=True)
        assert result["created"] is True
        assert result["name"] == "boleto"

    def test_success_lowercase_normalized(self):
        result = create_payment_method("BOLETO", confirmed=True)
        assert result["name"] == "boleto"

    def test_success_appears_in_list(self):
        create_payment_method("vale-refeição", confirmed=True)
        assert "vale-refeição" in list_payment_methods()

    def test_duplicate_rejected(self):
        create_payment_method("boleto", confirmed=True)
        result = create_payment_method("Boleto", confirmed=True)
        assert result["tipo"] == "duplicata"

    def test_system_method_duplicate(self):
        result = create_payment_method("pix", confirmed=True)
        assert result["tipo"] == "duplicata"

    def test_invalid_name_too_short(self):
        result = create_payment_method("x", confirmed=True)
        assert result["tipo"] == "invalido"


# ─── find_expense_candidates ─────────────────────────────────────────────────

class TestFindExpenseCandidates:
    @pytest.fixture(autouse=True)
    def use_db(self, test_db, sample_expenses):
        pass

    def test_no_results(self):
        result = find_expense_candidates("inexistente")
        assert result["total_found"] == 0
        assert result["records"] == []

    def test_finds_by_keyword(self):
        result = find_expense_candidates("uber")
        assert result["total_found"] == 1
        assert result["keyword"] == "uber"

    def test_keyword_accent_insensitive(self):
        result = find_expense_candidates("farmacia")
        assert result["total_found"] == 1

    def test_without_date_uses_most_recent(self):
        result = find_expense_candidates("luz")
        assert result["total_found"] == 1
        assert result["date_searched"] == "2026-05-09"

    def test_with_explicit_date(self):
        result = find_expense_candidates("energia", expense_date="2026-05-08")
        assert result["total_found"] == 1
        assert result["date_searched"] == "2026-05-08"

    def test_with_wrong_date_returns_empty(self):
        result = find_expense_candidates("uber", expense_date="2026-01-01")
        assert result["total_found"] == 0

    def test_soft_deleted_excluded(self):
        conn = get_connection()
        conn.execute("UPDATE expenses SET deleted_at = CURRENT_TIMESTAMP WHERE description LIKE '%uber%'")
        conn.commit()
        conn.close()
        result = find_expense_candidates("uber")
        assert result["total_found"] == 0


# ─── delete_expense ───────────────────────────────────────────────────────────

class TestDeleteExpense:
    @pytest.fixture(autouse=True)
    def use_db(self, test_db):
        pass

    def test_confirmed_false_rejected(self, inserted_expense):
        result = delete_expense(expense_id=inserted_expense, confirmed=False)
        assert result["tipo"] == "nao_confirmado"

    def test_confirmed_false_does_not_touch_db(self, inserted_expense):
        delete_expense(expense_id=inserted_expense, confirmed=False)
        conn = get_connection()
        row = conn.execute(
            "SELECT deleted_at FROM expenses WHERE id = ?", (inserted_expense,)
        ).fetchone()
        conn.close()
        assert row["deleted_at"] is None

    def test_success_returns_deleted_true(self, inserted_expense):
        result = delete_expense(expense_id=inserted_expense, confirmed=True)
        assert result["deleted"] is True
        assert result["expense_id"] == inserted_expense
        assert "record" in result

    def test_success_soft_delete_in_db(self, inserted_expense):
        delete_expense(expense_id=inserted_expense, confirmed=True)
        conn = get_connection()
        row = conn.execute(
            "SELECT deleted_at FROM expenses WHERE id = ?", (inserted_expense,)
        ).fetchone()
        conn.close()
        assert row["deleted_at"] is not None

    def test_success_creates_audit_log(self, inserted_expense):
        delete_expense(expense_id=inserted_expense, confirmed=True)
        conn = get_connection()
        log = conn.execute(
            "SELECT * FROM audit_log WHERE expense_id = ? AND operation = 'delete'",
            (inserted_expense,),
        ).fetchone()
        conn.close()
        assert log is not None
        old_data = json.loads(log["old_data"])
        assert old_data["amount"] == 55.0

    def test_not_found(self):
        result = delete_expense(expense_id=9999, confirmed=True)
        assert result["tipo"] == "nao_encontrado"

    def test_already_deleted(self, inserted_expense):
        delete_expense(expense_id=inserted_expense, confirmed=True)
        result = delete_expense(expense_id=inserted_expense, confirmed=True)
        assert result["tipo"] == "nao_encontrado"

    def test_deleted_excluded_from_query(self, inserted_expense):
        delete_expense(expense_id=inserted_expense, confirmed=True)
        results = query_expenses(keyword="almoço")
        assert all(r["id"] != inserted_expense for r in results)


# ─── update_expense ───────────────────────────────────────────────────────────

class TestUpdateExpense:
    @pytest.fixture(autouse=True)
    def use_db(self, test_db):
        pass

    def test_confirmed_false_rejected(self, inserted_expense):
        result = update_expense(expense_id=inserted_expense, confirmed=False, amount=60.0)
        assert result["tipo"] == "nao_confirmado"

    def test_confirmed_false_does_not_touch_db(self, inserted_expense):
        update_expense(expense_id=inserted_expense, confirmed=False, amount=999.0)
        conn = get_connection()
        row = conn.execute("SELECT amount FROM expenses WHERE id = ?", (inserted_expense,)).fetchone()
        conn.close()
        assert row["amount"] == 55.0

    def test_update_amount(self, inserted_expense):
        result = update_expense(expense_id=inserted_expense, confirmed=True, amount=75.0)
        assert result["updated"] is True
        assert result["new"]["amount"] == 75.0
        assert result["old"]["amount"] == 55.0

    def test_update_category(self, inserted_expense):
        result = update_expense(expense_id=inserted_expense, confirmed=True, category="Lazer")
        assert result["updated"] is True
        assert result["new"]["category"] == "Lazer"

    def test_update_method(self, inserted_expense):
        result = update_expense(expense_id=inserted_expense, confirmed=True, method="pix")
        assert result["updated"] is True
        assert result["new"]["method"] == "pix"

    def test_update_description(self, inserted_expense):
        result = update_expense(expense_id=inserted_expense, confirmed=True, description="jantar")
        assert result["updated"] is True
        assert result["new"]["description"] == "jantar"

    def test_update_date(self, inserted_expense):
        result = update_expense(expense_id=inserted_expense, confirmed=True, expense_date="2026-05-01")
        assert result["updated"] is True
        assert result["new"]["expense_date"] == "2026-05-01"

    def test_update_invalid_category(self, inserted_expense):
        result = update_expense(expense_id=inserted_expense, confirmed=True, category="Inexistente")
        assert result["tipo"] == "invalido"

    def test_update_invalid_method(self, inserted_expense):
        result = update_expense(expense_id=inserted_expense, confirmed=True, method="cheque")
        assert result["tipo"] == "invalido"

    def test_update_invalid_amount_zero(self, inserted_expense):
        result = update_expense(expense_id=inserted_expense, confirmed=True, amount=0)
        assert result["tipo"] == "invalido"

    def test_update_invalid_future_date(self, inserted_expense):
        result = update_expense(expense_id=inserted_expense, confirmed=True, expense_date="2099-01-01")
        assert result["tipo"] == "invalido"

    def test_update_no_fields(self, inserted_expense):
        result = update_expense(expense_id=inserted_expense, confirmed=True)
        assert result["tipo"] == "invalido"

    def test_update_not_found(self):
        result = update_expense(expense_id=9999, confirmed=True, amount=60.0)
        assert result["tipo"] == "nao_encontrado"

    def test_update_creates_audit_log(self, inserted_expense):
        update_expense(expense_id=inserted_expense, confirmed=True, amount=75.0)
        conn = get_connection()
        log = conn.execute(
            "SELECT * FROM audit_log WHERE expense_id = ? AND operation = 'update'",
            (inserted_expense,),
        ).fetchone()
        conn.close()
        assert log is not None
        new_data = json.loads(log["new_data"])
        assert new_data["amount"] == 75.0

    def test_update_hash_recalculated_on_amount_change(self, inserted_expense):
        conn = get_connection()
        old_hash = conn.execute("SELECT hash FROM expenses WHERE id = ?", (inserted_expense,)).fetchone()["hash"]
        conn.close()
        update_expense(expense_id=inserted_expense, confirmed=True, amount=75.0)
        conn = get_connection()
        new_hash = conn.execute("SELECT hash FROM expenses WHERE id = ?", (inserted_expense,)).fetchone()["hash"]
        conn.close()
        assert old_hash != new_hash
