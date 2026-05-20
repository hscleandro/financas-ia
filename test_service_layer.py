"""Teste manual do Service Layer — Sprint 1.

Valida que a refatoração de MCP → Service funciona corretamente.
"""
from database.setup import get_connection
from services.expense_service import ExpenseService


def test_service_layer():
    """Testa operações básicas do ExpenseService."""
    conn = get_connection()
    service = ExpenseService(conn, user_id=None)

    print("=" * 60)
    print("Teste do Service Layer (Sprint 1)")
    print("=" * 60)

    # 1. Listar categorias
    print("\n1. Categorias disponíveis:")
    categories = service.list_categories()
    print(f"   {', '.join(categories)}")
    assert len(categories) >= 10, "Deve ter pelo menos 10 categorias"

    # 2. Listar métodos de pagamento
    print("\n2. Métodos de pagamento disponíveis:")
    methods = service.list_payment_methods()
    print(f"   {', '.join(methods)}")
    assert len(methods) >= 5, "Deve ter pelo menos 5 métodos"

    # 3. Registrar um gasto de teste
    print("\n3. Registrando gasto de teste...")
    result = service.record_expense(
        amount=25.50,
        description="Teste Service Layer",
        category="Alimentação",
        method="pix",
        expense_date="2026-05-19",
    )
    print(f"   Resultado: {result}")
    assert "id" in result, "Deve retornar id do gasto criado"
    expense_id = result["id"]

    # 4. Consultar gastos
    print("\n4. Consultando gastos com keyword...")
    expenses = service.query_expenses(keyword="teste service")
    print(f"   Encontrados: {len(expenses)} gastos")
    assert len(expenses) >= 1, "Deve encontrar pelo menos o gasto criado"

    # 5. Find candidates
    print("\n5. Buscando candidatos para edição...")
    candidates = service.find_expense_candidates("teste service")
    print(f"   Candidatos: {candidates['total_found']}")
    assert candidates["total_found"] >= 1

    # 6. Deletar gasto (com confirmação)
    print("\n6. Deletando gasto de teste...")
    delete_result = service.delete_expense(expense_id, confirmed=True)
    print(f"   Deletado: {delete_result.get('deleted', False)}")
    assert delete_result.get("deleted") is True

    # 7. Verificar que foi soft deleted
    print("\n7. Verificando soft delete...")
    expenses_after = service.query_expenses(keyword="teste service")
    print(f"   Gastos ativos: {len(expenses_after)}")
    assert len(expenses_after) == 0, "Gasto deve estar soft deleted"

    print("\n" + "=" * 60)
    print("✅ TODOS OS TESTES PASSARAM!")
    print("=" * 60)

    conn.close()


if __name__ == "__main__":
    test_service_layer()
