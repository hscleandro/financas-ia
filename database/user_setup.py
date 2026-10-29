"""Funções para gerenciamento de usuários multi-tenant."""
import sqlite3
from typing import Optional


def create_user(
    conn: sqlite3.Connection,
    telegram_id: int,
    name: Optional[str] = None,
    is_active: bool = True,
) -> int:
    """Cria um novo usuário no sistema multi-tenant.

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
    return cursor.lastrowid


def get_user_by_telegram_id(conn: sqlite3.Connection, telegram_id: int) -> Optional[dict]:
    """Busca usuário por telegram_id."""
    row = conn.execute(
        "SELECT id, telegram_id, name, is_active, created_at FROM users WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()

    return dict(row) if row else None


def create_or_update_user(
    conn: sqlite3.Connection,
    telegram_id: int,
    name: Optional[str] = None,
    is_active: bool = True,
) -> dict:
    """Cria um usuário ou retorna o existente pelo telegram_id."""
    existing = get_user_by_telegram_id(conn, telegram_id)
    if existing:
        return existing
    user_id = create_user(conn, telegram_id, name, is_active)
    return get_user_by_telegram_id(conn, telegram_id)
