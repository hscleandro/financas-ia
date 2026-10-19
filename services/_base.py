"""Helpers compartilhados entre os services."""
import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import date
from typing import Optional


def normalize_description(text: str) -> str:
    """Remove acentos e normaliza para busca case-insensitive."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return text


def compute_hash(amount: float, description: str, record_date: date) -> str:
    """Gera hash único para detecção de duplicatas."""
    normalized = normalize_description(description)
    raw = f"{amount:.2f}|{normalized}|{record_date.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def row_to_dict(row: sqlite3.Row) -> dict:
    """Converte Row em dict, transformando date em string."""
    return {k: str(v) if isinstance(v, date) else v for k, v in dict(row).items()}


def validate_category_name(name: str) -> tuple[str, str | None]:
    """Normaliza e valida um nome de categoria."""
    clean = name.strip().title()
    if len(clean) < 2:
        return clean, "Nome da categoria deve ter pelo menos 2 caracteres."
    if len(clean) > 30:
        return clean, "Nome da categoria não pode exceder 30 caracteres."
    if not all(c == " " or c == "-" or unicodedata.category(c).startswith("L") for c in clean):
        return clean, "Nome da categoria deve conter apenas letras, espaços e hífens."
    return clean, None


def validate_method_name(name: str) -> tuple[str, str | None]:
    """Normaliza e valida um nome de método de pagamento."""
    clean = name.strip().lower()
    if len(clean) < 2:
        return clean, "Nome do método deve ter pelo menos 2 caracteres."
    if len(clean) > 30:
        return clean, "Nome do método não pode exceder 30 caracteres."
    if not all(c == " " or c == "-" or unicodedata.category(c).startswith("L") for c in clean):
        return clean, "Nome do método deve conter apenas letras, espaços e hífens."
    return clean, None


def soft_delete(
    conn: sqlite3.Connection,
    table: str,
    record_id: int,
    user_id: Optional[int],
) -> Optional[dict]:
    """Executa soft delete de um registro e retorna os dados antigos.

    Returns:
        dict com os dados do registro excluído ou None se não encontrado.
    """
    user_filter = " AND user_id = ?" if user_id is not None else ""
    params = (record_id, user_id) if user_id is not None else (record_id,)

    row = conn.execute(
        f"SELECT * FROM {table} WHERE id = ? AND deleted_at IS NULL{user_filter}",
        params,
    ).fetchone()

    if not row:
        return None

    old_data = row_to_dict(row)
    conn.execute(f"UPDATE {table} SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?", (record_id,))
    return old_data


def log_audit(
    conn: sqlite3.Connection,
    operation: str,
    record_id: int,
    old_data: dict,
    new_data: Optional[dict] = None,
    user_id: Optional[int] = None,
) -> None:
    """Insere registro de auditoria para delete ou update."""
    if user_id is not None:
        conn.execute(
            """
            INSERT INTO audit_log (operation, expense_id, old_data, new_data, user_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                operation,
                record_id,
                json.dumps(old_data, ensure_ascii=False),
                json.dumps(new_data, ensure_ascii=False) if new_data else None,
                user_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO audit_log (operation, expense_id, old_data, new_data)
            VALUES (?, ?, ?, ?)
            """,
            (
                operation,
                record_id,
                json.dumps(old_data, ensure_ascii=False),
                json.dumps(new_data, ensure_ascii=False) if new_data else None,
            ),
        )


def get_valid_categories(
    conn: sqlite3.Connection,
    table: str,
    user_id: Optional[int],
) -> set[str]:
    """Retorna categorias disponíveis — system + custom do usuário."""
    if user_id is not None:
        query = f"SELECT name FROM {table} WHERE user_id IS NULL OR user_id = ?"
        rows = conn.execute(query, (user_id,)).fetchall()
    else:
        query = f"SELECT name FROM {table}"
        rows = conn.execute(query).fetchall()
    return {row["name"] for row in rows}


def create_custom_category(
    conn: sqlite3.Connection,
    table: str,
    name: str,
    confirmed: bool,
    user_id: Optional[int],
) -> dict:
    """Cria uma nova categoria customizada."""
    if not confirmed:
        return {
            "error": "Criação de categoria requer confirmed=True. Mostre o nome ao usuário e aguarde confirmação.",
            "tipo": "nao_confirmado",
        }

    clean, error = validate_category_name(name)
    if error:
        return {"error": error, "tipo": "invalido"}

    if user_id is not None:
        existing = conn.execute(
            f"SELECT name FROM {table} WHERE LOWER(name) = LOWER(?) AND (user_id IS NULL OR user_id = ?)",
            (clean, user_id),
        ).fetchone()
    else:
        existing = conn.execute(
            f"SELECT name FROM {table} WHERE LOWER(name) = LOWER(?)", (clean,)
        ).fetchone()

    if existing:
        return {"error": f"Categoria '{existing['name']}' já existe.", "tipo": "duplicata"}

    if user_id is not None:
        conn.execute(
            f"INSERT INTO {table} (name, is_system, user_id) VALUES (?, 0, ?)",
            (clean, user_id),
        )
    else:
        conn.execute(f"INSERT INTO {table} (name, is_system) VALUES (?, 0)", (clean,))

    conn.commit()
    return {"created": True, "name": clean}
