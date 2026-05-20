"""Teste de integração agent/tools.py com ExpenseService.

Valida que as tools LangChain funcionam corretamente.
"""
from agent.tools import build_tools
from database.setup import get_connection
from services.expense_service import ExpenseService


def test_tools_integration():
    """Testa que as tools construídas funcionam."""
    conn = get_connection()
    service = ExpenseService(conn, user_id=None)
    tools = build_tools(service)

    print("=" * 60)
    print("Teste de Integração: agent/tools.py")
    print("=" * 60)

    # Validar que todas as tools esperadas foram criadas
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
    ]

    print("\n1. Verificando tools criadas:")
    print(f"   Esperadas: {len(expected_tools)}")
    print(f"   Criadas: {len(tools)}")
    print(f"   Nomes: {tool_names}")

    for expected in expected_tools:
        assert expected in tool_names, f"Tool '{expected}' não encontrada"

    # Testar invocação de uma tool
    print("\n2. Testando invocação de list_categories:")
    list_categories_tool = next(t for t in tools if t.name == "list_categories")
    result = list_categories_tool.invoke({})
    print(f"   Categorias: {result}")
    assert len(result) >= 10, "Deve retornar pelo menos 10 categorias"

    print("\n3. Testando invocação de list_payment_methods:")
    list_methods_tool = next(t for t in tools if t.name == "list_payment_methods")
    result = list_methods_tool.invoke({})
    print(f"   Métodos: {result}")
    assert len(result) >= 5, "Deve retornar pelo menos 5 métodos"

    print("\n4. Testando record_expense:")
    record_tool = next(t for t in tools if t.name == "record_expense")
    result = record_tool.invoke({
        "amount": 15.75,
        "description": "Teste Tools Integration",
        "category": "Transporte",
        "method": "débito",
        "expense_date": "2026-05-19",
    })
    print(f"   Resultado: {result}")
    assert "id" in result, "Deve retornar id do gasto"

    print("\n5. Limpando gasto de teste...")
    delete_tool = next(t for t in tools if t.name == "delete_expense")
    delete_result = delete_tool.invoke({
        "expense_id": result["id"],
        "confirmed": True,
    })
    assert delete_result.get("deleted") is True

    print("\n" + "=" * 60)
    print("✅ INTEGRAÇÃO DE TOOLS FUNCIONANDO!")
    print("=" * 60)

    conn.close()


if __name__ == "__main__":
    test_tools_integration()
