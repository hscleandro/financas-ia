"""Testes de isolamento multi-tenant — Sprint 2.

Valida que dados de diferentes usuários estão corretamente isolados.
"""
import sqlite3
import tempfile
import os
from database.user_setup import create_user
from services.expense_service import ExpenseService


def test_multitenant_isolation():
    """Testa isolamento completo entre usuários."""
    # Usar banco temporário para não interferir com dados reais
    temp_db = tempfile.NamedTemporaryFile(mode='w', suffix='.db', delete=False)
    temp_db.close()
    db_path = temp_db.name

    try:
        # Configurar banco temporário
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Aplicar migrations manualmente (simplified)
        print("=" * 70)
        print("Teste de Isolamento Multi-Tenant (Sprint 2)")
        print("=" * 70)

        print("\n[Preparação] Criando schema...")
        conn.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id BIGINT NOT NULL UNIQUE,
                name TEXT,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                is_system INTEGER NOT NULL DEFAULT 0,
                user_id INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE payment_methods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                is_system INTEGER NOT NULL DEFAULT 0,
                user_id INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                amount REAL NOT NULL CHECK(amount > 0 AND amount < 100000),
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                method TEXT NOT NULL,
                expense_date DATE NOT NULL DEFAULT CURRENT_DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hash TEXT NOT NULL UNIQUE,
                deleted_at TIMESTAMP DEFAULT NULL
            );

            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation TEXT NOT NULL CHECK(operation IN ('delete', 'update')),
                expense_id INTEGER NOT NULL,
                old_data TEXT NOT NULL,
                new_data TEXT DEFAULT NULL,
                user_id INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Seeds system (compartilhados, user_id NULL)
        categories = ["Alimentação", "Transporte", "Moradia", "Saúde", "Lazer"]
        methods = ["dinheiro", "pix", "crédito"]

        for cat in categories:
            conn.execute("INSERT INTO categories (name, is_system, user_id) VALUES (?, 1, NULL)", (cat,))
        for method in methods:
            conn.execute("INSERT INTO payment_methods (name, is_system, user_id) VALUES (?, 1, NULL)", (method,))
        conn.commit()

        print("   ✅ Schema criado com seeds system")

        # ─── Criar 2 usuários ───
        print("\n[1] Criando dois usuários...")
        user1_id = create_user(conn, telegram_id=111222333, name="Alice")
        user2_id = create_user(conn, telegram_id=444555666, name="Bob")
        print(f"   User 1 (Alice): ID {user1_id}")
        print(f"   User 2 (Bob): ID {user2_id}")

        # ─── Services para cada usuário ───
        service_alice = ExpenseService(conn, user_id=user1_id)
        service_bob = ExpenseService(conn, user_id=user2_id)

        # ─── Alice registra gastos ───
        print("\n[2] Alice registra 2 gastos...")
        r1 = service_alice.record_expense(30.0, "Almoço Alice", "Alimentação", "pix", "2026-05-19")
        r2 = service_alice.record_expense(50.0, "Uber Alice", "Transporte", "crédito", "2026-05-19")
        assert "id" in r1, "Alice deve conseguir registrar gasto"
        assert "id" in r2, "Alice deve conseguir registrar gasto"
        print(f"   ✅ Alice registrou gastos: #{r1['id']}, #{r2['id']}")

        # ─── Bob registra gastos ───
        print("\n[3] Bob registra 2 gastos...")
        r3 = service_bob.record_expense(25.0, "Café Bob", "Alimentação", "dinheiro", "2026-05-19")
        r4 = service_bob.record_expense(100.0, "Cinema Bob", "Lazer", "pix", "2026-05-19")
        assert "id" in r3, "Bob deve conseguir registrar gasto"
        assert "id" in r4, "Bob deve conseguir registrar gasto"
        print(f"   ✅ Bob registrou gastos: #{r3['id']}, #{r4['id']}")

        # ─── Isolamento: Alice só vê seus gastos ───
        print("\n[4] Validando isolamento de consultas...")
        alice_expenses = service_alice.query_expenses()
        bob_expenses = service_bob.query_expenses()

        print(f"   Alice vê {len(alice_expenses)} gastos")
        print(f"   Bob vê {len(bob_expenses)} gastos")

        assert len(alice_expenses) == 2, f"Alice deve ver apenas 2 gastos, viu {len(alice_expenses)}"
        assert len(bob_expenses) == 2, f"Bob deve ver apenas 2 gastos, viu {len(bob_expenses)}"

        alice_descs = {e["description"] for e in alice_expenses}
        bob_descs = {e["description"] for e in bob_expenses}

        assert "Almoço Alice" in alice_descs, "Alice deve ver seu próprio gasto"
        assert "Café Bob" not in alice_descs, "Alice NÃO deve ver gastos de Bob"
        assert "Café Bob" in bob_descs, "Bob deve ver seu próprio gasto"
        assert "Almoço Alice" not in bob_descs, "Bob NÃO deve ver gastos de Alice"

        print("   ✅ Isolamento de consultas OK")

        # ─── Isolamento: Alice não pode deletar gastos de Bob ───
        print("\n[5] Validando isolamento de delete...")
        bob_expense_id = r3["id"]
        delete_result = service_alice.delete_expense(bob_expense_id, confirmed=True)

        assert "error" in delete_result, "Alice NÃO deve poder deletar gasto de Bob"
        assert delete_result["tipo"] == "nao_encontrado", "Deve retornar 'nao_encontrado'"
        print(f"   ✅ Alice não pode deletar gasto #{bob_expense_id} de Bob")

        # ─── Bob deleta seu próprio gasto ───
        print("\n[6] Bob deletando seu próprio gasto...")
        delete_result2 = service_bob.delete_expense(bob_expense_id, confirmed=True)
        assert delete_result2.get("deleted") is True, "Bob deve poder deletar seu próprio gasto"
        print(f"   ✅ Bob deletou gasto #{bob_expense_id} com sucesso")

        # ─── Categories e methods custom por usuário ───
        print("\n[7] Criando categorias custom por usuário...")
        # Nomes diferentes para evitar conflito de UNIQUE global (será resolvido na migration 0008)
        cat_alice = service_alice.create_category("Pets", confirmed=True)
        cat_bob = service_bob.create_category("Assinaturas", confirmed=True)

        assert cat_alice.get("created") is True, "Alice deve criar categoria custom"
        assert cat_bob.get("created") is True, "Bob deve criar categoria custom"

        alice_cats = service_alice.list_categories()
        bob_cats = service_bob.list_categories()

        print(f"   Alice vê {len(alice_cats)} categorias")
        print(f"   Bob vê {len(bob_cats)} categorias")

        assert "Pets" in alice_cats, "Alice deve ver sua categoria custom"
        assert "Assinaturas" not in alice_cats, "Alice NÃO deve ver categoria custom de Bob"
        assert "Assinaturas" in bob_cats, "Bob deve ver sua categoria custom"
        assert "Pets" not in bob_cats, "Bob NÃO deve ver categoria custom de Alice"

        # Ambos devem ver categorias system
        assert "Alimentação" in alice_cats, "Alice deve ver categoria system"
        assert "Alimentação" in bob_cats, "Bob deve ver categoria system"

        print("   ✅ Isolamento de categorias custom OK")

        print("\n" + "=" * 70)
        print("✅ TODOS OS TESTES DE ISOLAMENTO PASSARAM!")
        print("=" * 70)

    finally:
        conn.close()
        os.unlink(db_path)


if __name__ == "__main__":
    test_multitenant_isolation()
