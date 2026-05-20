"""Script para criar usuário inicial no sistema multi-tenant.

Usage:
    python setup_telegram_user.py <telegram_id> [nome]

Exemplo:
    python setup_telegram_user.py 123456789 "João Silva"

Para descobrir seu telegram_id:
    1. Abra o Telegram
    2. Busque por @userinfobot
    3. Envie /start
    4. O bot responderá com seu ID
"""
import sys

from alembic import command
from alembic.config import Config

from database.setup import get_connection
from database.user_setup import create_user, get_user_by_telegram_id


def run_migrations() -> None:
    """Aplica todas as migrations pendentes."""
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    try:
        telegram_id = int(sys.argv[1])
    except ValueError:
        print(f"❌ Erro: telegram_id deve ser um número inteiro")
        print(f"Recebido: {sys.argv[1]}")
        sys.exit(1)

    name = sys.argv[2] if len(sys.argv) > 2 else None

    print("=" * 60)
    print("Setup de Usuário Telegram")
    print("=" * 60)

    # Aplicar migrations
    print("\n[1] Aplicando migrations...")
    run_migrations()
    print("   ✅ Migrations aplicadas")

    # Verificar se usuário já existe
    conn = get_connection()
    existing = get_user_by_telegram_id(conn, telegram_id)

    if existing:
        print(f"\n[2] Usuário já existe:")
        print(f"   ID: {existing['id']}")
        print(f"   Telegram ID: {existing['telegram_id']}")
        print(f"   Nome: {existing['name']}")
        print(f"   Ativo: {existing['is_active']}")
        conn.close()
        return

    # Criar novo usuário
    print(f"\n[2] Criando novo usuário...")
    print(f"   Telegram ID: {telegram_id}")
    if name:
        print(f"   Nome: {name}")

    user_id = create_user(conn, telegram_id, name=name, is_active=True)
    print(f"   ✅ Usuário criado com ID: {user_id}")

    conn.close()

    print("\n" + "=" * 60)
    print("✅ Setup concluído!")
    print("=" * 60)
    print("\nPróximos passos:")
    print("  1. python main_telegram_polling.py")
    print("  2. Abra o Telegram e envie uma mensagem para o bot")
    print("\n")


if __name__ == "__main__":
    main()
