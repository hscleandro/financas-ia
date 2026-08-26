"""Funções para gerenciamento de usuários e seeds multi-tenant.

DA-027: Seeds is_system=1 replicados na criação de cada usuário.
"""
import sqlite3
from typing import Optional


def create_user(
    conn: sqlite3.Connection,
    telegram_id: int,
    name: Optional[str] = None,
    is_active: bool = True,
) -> int:
    """Cria um novo usuário no sistema multi-tenant.

    IMPORTANTE: Após criar o usuário, chama seed_user_data para replicar
    categorias e métodos system.

    Args:
        conn: Conexão SQLite
        telegram_id: ID do Telegram do usuário (único)
        name: Nome do usuário (opcional)
        is_active: Se o usuário está ativo (default: True)

    Returns:
        user_id do usuário criado

    Raises:
        sqlite3.IntegrityError: Se telegram_id já existe
    """
    cursor = conn.execute(
        "INSERT INTO users (telegram_id, name, is_active) VALUES (?, ?, ?)",
        (telegram_id, name, is_active),
    )
    conn.commit()
    user_id = cursor.lastrowid

    # Replica seeds system para o novo usuário
    seed_user_data(conn, user_id)

    return user_id


def seed_user_data(conn: sqlite3.Connection, user_id: int) -> None:
    """Replica categorias e métodos system para um usuário específico.

    Categorias e métodos marcados como is_system=1 são compartilhados (user_id NULL).
    Esta função NÃO duplica esses registros — apenas garante que o usuário
    possa criar seus próprios custom.

    Args:
        conn: Conexão SQLite
        user_id: ID do usuário para seed
    """
    # Nota: Categorias e métodos system (is_system=1) são compartilhados (user_id NULL)
    # e disponíveis para todos os usuários automaticamente via query:
    # SELECT name FROM categories WHERE user_id IS NULL OR user_id = ?
    #
    # Esta função é um placeholder para seeds custom futuros por usuário,
    # se necessário (ex: categoria "Presente" automática para todos).
    #
    # Por enquanto, não há ação necessária — seeds system já estão disponíveis.
    pass


def get_user_by_telegram_id(conn: sqlite3.Connection, telegram_id: int) -> Optional[dict]:
    """Busca usuário por telegram_id.

    Args:
        conn: Conexão SQLite
        telegram_id: ID do Telegram

    Returns:
        dict com dados do usuário ou None se não encontrado
    """
    row = conn.execute(
        "SELECT id, telegram_id, name, is_active, created_at FROM users WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()

    return dict(row) if row else None


def deactivate_user(conn: sqlite3.Connection, user_id: int) -> None:
    """Desativa um usuário (soft delete em users).

    Args:
        conn: Conexão SQLite
        user_id: ID do usuário a desativar
    """
    conn.execute("UPDATE users SET is_active = FALSE WHERE id = ?", (user_id,))
    conn.commit()


def activate_user(conn: sqlite3.Connection, user_id: int) -> None:
    """Reativa um usuário.

    Args:
        conn: Conexão SQLite
        user_id: ID do usuário a reativar
    """
    conn.execute("UPDATE users SET is_active = TRUE WHERE id = ?", (user_id,))
    conn.commit()
