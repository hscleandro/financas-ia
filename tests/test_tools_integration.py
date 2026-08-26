"""Teste de integração agent/tools.py com ExpenseService e IncomeService."""
import pytest

from agent.tools import build_tools
from database.setup import get_connection
from database.user_setup import create_user
from services.expense_service import ExpenseService
from services.income_service import IncomeService


@pytest.fixture
def tools(test_db):
    conn = get_connection()
    user_id = create_user(conn, telegram_id=123456789, name="Test User")
    expense_service = ExpenseService(conn, user_id=user_id)
    income_service = IncomeService(conn, user_id=user_id)
    yield build_tools(expense_service, income_service)
    conn.close()


def test_tools_integration(tools):
    """Testa que as tools construídas funcionam."""
    print("=" * 60)
    print("Teste de Integração: agent/tools.py")
    print("=" * 60)

    tool_names = [t.name for t in tools]
    expected_tools = [
        "record_expense",
        "query_expenses",
        "get_summary",
        "list_categories",
        "list_payment_methods",
        "create_payment_method",
        "create_category",
        "find_expense_candidates",
        "delete_expense",
        "update_expense",
        "record_income",
        "query_incomes",
        "get_income_summary",
        "list_income_categories",
        "create_income_category",
        "find_income_candidates",
        "delete_income",
        "update_income",
    ]

    print("\n1. Verificando tools criadas:")
    print(f"   Esperadas: {len(expected_tools)}")
    print(f"   Criadas: {len(tools)}")
    print(f"   Nomes: {tool_names}")

    for expected in expected_tools:
        assert expected in tool_names, f"Tool '{expected}' não encontrada"

    # Testar invocação de list_categories
    print("\n2. Testando invocação de list_categories:")
    list_categories_tool = next(t for t in tools if t.name == "list_categories")
    result = list_categories_tool.invoke({})
    print(f"   Categorias: {result}")
    assert len(result) >= 10, "Deve retornar pelo menos 10 categorias"

    # Testar invocação de list_income_categories
    print("\n3. Testando invocação de list_income_categories:")
    list_income_categories_tool = next(t for t in tools if t.name == "list_income_categories")
    result = list_income_categories_tool.invoke({})
    print(f"   Categorias de ganho: {result}")
    assert "Salário" in result, "Deve retornar categoria Salário"

    # Testar record_income
    print("\n4. Testando record_income:")
    record_income_tool = next(t for t in tools if t.name == "record_income")
    result = record_income_tool.invoke({
        "amount": 5000.0,
        "description": "Teste Income Tool",
        "category": "Outros",
        "income_date": "2026-08-26",
    })
    print(f"   Resultado: {result}")
    assert "id" in result, "Deve retornar id do ganho"
    income_id = result["id"]

    # Testar query_incomes
    print("\n5. Testando query_incomes:")
    query_incomes_tool = next(t for t in tools if t.name == "query_incomes")
    result = query_incomes_tool.invoke({"keyword": "teste income"})
    print(f"   Resultado: {result}")
    assert len(result) >= 1

    # Limpar ganho de teste
    print("\n6. Limpando ganho de teste...")
    delete_income_tool = next(t for t in tools if t.name == "delete_income")
    delete_result = delete_income_tool.invoke({
        "income_id": income_id,
        "confirmed": True,
    })
    assert delete_result.get("deleted") is True

    print("\n" + "=" * 60)
    print("✅ INTEGRAÇÃO DE TOOLS FUNCIONANDO!")
    print("=" * 60)


if __name__ == "__main__":
    test_tools_integration()
