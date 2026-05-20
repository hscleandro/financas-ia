#!/usr/bin/env python
"""
Teste manual para DA-016: Busca textual por descrição em query_expenses.
Executa sem dependências complexas de pytest fixtures.

Uso:
  python test_da016_manual.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.getcwd())

from datetime import date
from database.setup import setup_database, get_connection
from mcp_server.server import query_expenses, _compute_hash


def test_da016():
    """Testa a implementação de busca por keyword em query_expenses."""
    # Cria banco de teste
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.db') as f:
        db_path = f.name

    os.environ['DB_PATH'] = db_path

    try:
        setup_database()

        # Insere dados de teste
        conn = get_connection()
        cursor = conn.cursor()

        expenses_data = [
            (55.00, "almoço no restaurante", "Alimentação", "dinheiro", "2026-05-10"),
            (120.00, "conta de energia", "Serviços", "pix", "2026-05-08"),
            (35.50, "café da manhã", "Alimentação", "crédito", "2026-05-13"),
            (80.00, "uber para casa", "Transporte", "débito", "2026-05-12"),
            (250.00, "farmácia - remédios", "Saúde", "dinheiro", "2026-05-11"),
            (45.00, "luz residencial", "Serviços", "transferência", "2026-05-09"),
        ]

        for amount, desc, cat, method, expense_date in expenses_data:
            hash_val = _compute_hash(amount, desc, date.fromisoformat(expense_date))
            cursor.execute(
                "INSERT INTO expenses (amount, description, category, method, expense_date, hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (amount, desc, cat, method, expense_date, hash_val)
            )

        conn.commit()
        conn.close()

        # === TESTES ===
        passed = 0
        total = 0

        # Test 1: Busca por keyword exato
        total += 1
        result = query_expenses(keyword="almoço")
        if len(result) == 1 and result[0]["description"] == "almoço no restaurante":
            print("✓ Test 1: Busca por keyword exato")
            passed += 1
        else:
            print(f"✗ Test 1: Esperado 1 resultado, obteve {len(result)}")

        # Test 2: Busca por keyword parcial
        total += 1
        result = query_expenses(keyword="restaurante")
        if len(result) == 1 and "restaurante" in result[0]["description"]:
            print("✓ Test 2: Busca por keyword parcial")
            passed += 1
        else:
            print(f"✗ Test 2: Esperado 1 resultado com 'restaurante'")

        # Test 3: Case-insensitive
        total += 1
        result1 = query_expenses(keyword="ALMOÇO")
        result2 = query_expenses(keyword="almoço")
        if len(result1) == 1 and len(result2) == 1 and result1[0]["id"] == result2[0]["id"]:
            print("✓ Test 3: Case-insensitive")
            passed += 1
        else:
            print("✗ Test 3: Busca case-insensitive não funcionou")

        # Test 4: Sem keyword (backward compatibility)
        total += 1
        result = query_expenses()
        if len(result) == 6:
            print("✓ Test 4: Backward compatibility (sem keyword)")
            passed += 1
        else:
            print(f"✗ Test 4: Esperado 6 resultados, obteve {len(result)}")

        # Test 5: Busca inexistente
        total += 1
        result = query_expenses(keyword="xyz123abc")
        if len(result) == 0:
            print("✓ Test 5: Busca inexistente retorna vazio")
            passed += 1
        else:
            print(f"✗ Test 5: Esperado 0 resultados, obteve {len(result)}")

        # Test 6: Combinação com filtro de data
        total += 1
        result = query_expenses(
            keyword="energia",
            start_date="2026-05-01",
            end_date="2026-05-10"
        )
        if len(result) >= 1 and all("energia" in r["description"].lower() for r in result):
            print("✓ Test 6: Keyword combinado com filtro de data")
            passed += 1
        else:
            print("✗ Test 6: Filtro de data com keyword falhou")

        # Test 7: Combinação com filtro de categoria
        total += 1
        result = query_expenses(keyword="café", category="Alimentação")
        if len(result) >= 1 and all(r["category"] == "Alimentação" for r in result):
            print("✓ Test 7: Keyword combinado com categoria")
            passed += 1
        else:
            print("✗ Test 7: Filtro de categoria com keyword falhou")

        # Test 8: Soft delete excluído
        total += 1
        conn = get_connection()
        conn.execute("UPDATE expenses SET deleted_at = CURRENT_TIMESTAMP WHERE id = 1")
        conn.commit()
        conn.close()
        result = query_expenses(keyword="almoço")
        if len(result) == 0:
            print("✓ Test 8: Soft delete excluído da busca")
            passed += 1
        else:
            print(f"✗ Test 8: Soft delete não foi excluído (obteve {len(result)} resultados)")

        # Test 9: Ordenação DESC
        total += 1
        result = query_expenses(keyword="")
        dates = [r["expense_date"] for r in result]
        if dates == sorted(dates, reverse=True):
            print("✓ Test 9: Resultados ordenados por data DESC")
            passed += 1
        else:
            print("✗ Test 9: Ordenação incorreta")

        # Test 10: Accent-insensitive
        total += 1
        result = query_expenses(keyword="energia")
        if len(result) >= 1:
            print("✓ Test 10: Busca accent-insensitive")
            passed += 1
        else:
            print("✗ Test 10: Busca por 'energia' falhou")

        # === RESULTADO FINAL ===
        print(f"\n{'='*50}")
        print(f"Resultado: {passed}/{total} testes passaram")
        if passed == total:
            print("✅ Todos os testes passaram!")
            return 0
        else:
            print(f"❌ {total - passed} testes falharam")
            return 1

    finally:
        os.unlink(db_path)
        os.environ.pop('DB_PATH', None)


if __name__ == "__main__":
    sys.exit(test_da016())
