import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import unicodedata
from datetime import date
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastmcp import FastMCP

from database.setup import get_connection, setup_database
from models.schemas import ExpenseCreate

logger = logging.getLogger(__name__)

mcp = FastMCP("financas-mcp")

VALID_METHODS = {"dinheiro", "crédito", "débito", "pix", "transferência"}


# ─── Utilitários internos ────────────────────────────────────────────────────

def _get_valid_categories() -> set[str]:
    with get_connection() as conn:
        rows = conn.execute("SELECT name FROM categories").fetchall()
    return {row["name"] for row in rows}


def _validate_category_name(name: str) -> tuple[str, str | None]:
    """Normaliza e valida um nome de categoria. Retorna (nome_normalizado, erro_ou_None)."""
    clean = name.strip().title()
    if len(clean) < 2:
        return clean, "Nome da categoria deve ter pelo menos 2 caracteres."
    if len(clean) > 30:
        return clean, "Nome da categoria não pode exceder 30 caracteres."
    if not all(c == " " or c == "-" or unicodedata.category(c).startswith("L") for c in clean):
        return clean, "Nome da categoria deve conter apenas letras, espaços e hífens."
    return clean, None


def _normalize_description(text: str) -> str:
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return text


def _compute_hash(amount: float, description: str, expense_date: date) -> str:
    normalized = _normalize_description(description)
    raw = f"{amount:.2f}|{normalized}|{expense_date.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: str(v) if isinstance(v, date) else v for k, v in dict(row).items()}


# ─── Tools de registro e consulta ────────────────────────────────────────────

@mcp.tool()
def record_expense(
    amount: float,
    description: str,
    category: str,
    method: str = "dinheiro",
    expense_date: Optional[str] = None,
) -> dict:
    """Registra um gasto no banco de dados financeiro pessoal.

    Args:
        amount: Valor do gasto em reais (ex: 55.90)
        description: Descrição do gasto (ex: "almoço no restaurante")
        category: Categoria do gasto (deve ser uma das categorias válidas)
        method: Método de pagamento (dinheiro, crédito, débito, pix, transferência)
        expense_date: Data do gasto no formato YYYY-MM-DD (padrão: hoje)
    """
    valid_categories = _get_valid_categories()
    if category not in valid_categories:
        return {
            "error": f"Categoria inválida: '{category}'. Use list_categories para ver as disponíveis.",
            "tipo": "invalido",
        }

    try:
        expense = ExpenseCreate(
            amount=amount,
            description=description,
            category=category,
            method=method,
            expense_date=expense_date,
        )
    except Exception as e:
        return {"error": str(e), "tipo": "invalido"}

    expense_hash = _compute_hash(expense.amount, expense.description, expense.expense_date)

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO expenses (amount, description, category, method, expense_date, hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    expense.amount,
                    expense.description,
                    expense.category,
                    expense.method,
                    expense.expense_date.isoformat(),
                    expense_hash,
                ),
            )
            conn.commit()
            expense_id = cursor.lastrowid

        return {
            "id": expense_id,
            "amount": expense.amount,
            "description": expense.description,
            "category": expense.category,
            "method": expense.method,
            "expense_date": expense.expense_date.isoformat(),
        }
    except sqlite3.IntegrityError:
        logger.warning(
            "Duplicata detectada: %s · R$%.2f · %s",
            expense.description,
            expense.amount,
            expense.expense_date,
        )
        return {"error": "Gasto duplicado: já existe um registro idêntico.", "tipo": "duplicata"}


@mcp.tool()
def query_expenses(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    method: Optional[str] = None,
) -> list[dict]:
    """Consulta gastos ativos com filtros opcionais.

    Args:
        start_date: Data inicial no formato YYYY-MM-DD
        end_date: Data final no formato YYYY-MM-DD
        category: Filtrar por categoria específica
        method: Filtrar por método de pagamento
    """
    query = (
        "SELECT id, amount, description, category, method, expense_date, created_at "
        "FROM expenses WHERE deleted_at IS NULL"
    )
    params: list = []

    if start_date:
        query += " AND expense_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND expense_date <= ?"
        params.append(end_date)
    if category:
        query += " AND category = ?"
        params.append(category)
    if method:
        query += " AND method = ?"
        params.append(method)

    query += " ORDER BY expense_date DESC, created_at DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return [dict(row) for row in rows]


@mcp.tool()
def get_summary(
    start_date: str,
    end_date: str,
    group_by: str = "category",
) -> dict:
    """Retorna resumo de gastos agrupados por dimensão.

    Args:
        start_date: Data inicial no formato YYYY-MM-DD
        end_date: Data final no formato YYYY-MM-DD
        group_by: Dimensão de agrupamento: 'category', 'method', 'day' ou 'month'
    """
    valid_groups = {"category", "method", "day", "month"}
    if group_by not in valid_groups:
        return {"error": f"group_by deve ser um de: {', '.join(valid_groups)}"}

    group_expr = {
        "category": "category",
        "method": "method",
        "day": "expense_date",
        "month": "strftime('%Y-%m', expense_date)",
    }[group_by]

    query = f"""
        SELECT {group_expr} AS dimension, SUM(amount) AS total, COUNT(*) AS count
        FROM expenses
        WHERE expense_date BETWEEN ? AND ?
          AND deleted_at IS NULL
        GROUP BY {group_expr}
        ORDER BY total DESC
    """

    with get_connection() as conn:
        rows = conn.execute(query, (start_date, end_date)).fetchall()
        total_row = conn.execute(
            "SELECT SUM(amount) FROM expenses WHERE expense_date BETWEEN ? AND ? AND deleted_at IS NULL",
            (start_date, end_date),
        ).fetchone()

    return {
        "group_by": group_by,
        "start_date": start_date,
        "end_date": end_date,
        "items": [
            {"dimension": r["dimension"], "total": r["total"], "count": r["count"]}
            for r in rows
        ],
        "total_geral": total_row[0] or 0.0,
    }


@mcp.tool()
def list_categories() -> list[str]:
    """Retorna a lista de categorias de gastos disponíveis."""
    with get_connection() as conn:
        rows = conn.execute("SELECT name FROM categories ORDER BY name").fetchall()
    return [row["name"] for row in rows]


@mcp.tool()
def create_category(name: str, confirmed: bool) -> dict:
    """Cria uma nova categoria de gastos definida pelo usuário.

    ATENÇÃO: confirmed=True somente após confirmação explícita do usuário nessa mensagem.
    Categorias do sistema (is_system=1) não podem ser substituídas; esta tool só cria
    categorias novas (is_system=0).

    Args:
        name: Nome da nova categoria (será normalizado para title case)
        confirmed: True apenas se o usuário confirmou explicitamente agora
    """
    if not confirmed:
        return {
            "error": "Criação de categoria requer confirmed=True. Mostre o nome ao usuário e aguarde confirmação.",
            "tipo": "nao_confirmado",
        }

    clean, error = _validate_category_name(name)
    if error:
        return {"error": error, "tipo": "invalido"}

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT name FROM categories WHERE LOWER(name) = LOWER(?)", (clean,)
        ).fetchone()
        if existing:
            return {
                "error": f"Categoria '{existing['name']}' já existe.",
                "tipo": "duplicata",
            }

        conn.execute(
            "INSERT INTO categories (name, is_system) VALUES (?, 0)", (clean,)
        )
        conn.commit()

    logger.info("Categoria criada pelo usuário: %s", clean)
    return {"created": True, "name": clean}


# ─── Tools de busca e operações destrutivas ──────────────────────────────────

@mcp.tool()
def find_expense_candidates(
    keyword: str,
    expense_date: Optional[str] = None,
) -> dict:
    """Busca registros candidatos para edição ou exclusão.

    Use esta tool ANTES de delete_expense ou update_expense.

    - Com expense_date: retorna registros daquela data que contêm o keyword.
    - Sem expense_date: retorna registros da DATA MAIS RECENTE que contém o keyword.

    Args:
        keyword: Palavra-chave da descrição (ex: "almoço", "uber", "farmácia")
        expense_date: Data em YYYY-MM-DD. Só informe se o usuário mencionou data específica.
    """
    normalized_kw = _normalize_description(keyword)

    with get_connection() as conn:
        all_rows = conn.execute(
            "SELECT id, amount, description, category, method, expense_date "
            "FROM expenses WHERE deleted_at IS NULL "
            "ORDER BY expense_date DESC, id DESC"
        ).fetchall()

    # Filtragem em Python para suporte correto a Unicode/acentos
    matching = [
        row for row in all_rows
        if normalized_kw in _normalize_description(row["description"])
    ]

    if not matching:
        return {"keyword": keyword, "date_searched": expense_date, "total_found": 0, "records": []}

    if expense_date is None:
        # Usa a data mais recente entre os registros encontrados
        date_searched = max(row["expense_date"] for row in matching)
    else:
        date_searched = expense_date

    records = [dict(row) for row in matching if row["expense_date"] == date_searched]

    return {
        "keyword": keyword,
        "date_searched": date_searched,
        "total_found": len(records),
        "records": records,
    }


@mcp.tool()
def delete_expense(expense_id: int, confirmed: bool) -> dict:
    """Exclui um único registro de gasto (soft delete — dado preservado no banco).

    Use após identificar o registro com find_expense_candidates.
    O sistema de confirmação HITL gerencia o parâmetro confirmed automaticamente.

    Args:
        expense_id: ID único do registro a ser excluído
        confirmed: gerenciado pelo sistema — não altere manualmente
    """
    if not confirmed:
        return {
            "error": "Exclusão requer confirmed=True. Mostre o registro ao usuário e aguarde confirmação.",
            "tipo": "nao_confirmado",
        }

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, amount, description, category, method, expense_date "
            "FROM expenses WHERE id = ? AND deleted_at IS NULL",
            (expense_id,),
        ).fetchone()

        if not row:
            return {
                "error": f"Registro #{expense_id} não encontrado ou já excluído.",
                "tipo": "nao_encontrado",
            }

        old_data = _row_to_dict(row)

        conn.execute(
            "UPDATE expenses SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (expense_id,),
        )
        conn.execute(
            "INSERT INTO audit_log (operation, expense_id, old_data) VALUES (?, ?, ?)",
            ("delete", expense_id, json.dumps(old_data, ensure_ascii=False)),
        )
        conn.commit()

    logger.info("Registro #%d excluído: %s", expense_id, old_data.get("description"))
    return {"deleted": True, "expense_id": expense_id, "record": old_data}


@mcp.tool()
def update_expense(
    expense_id: int,
    confirmed: bool,
    amount: Optional[float] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    method: Optional[str] = None,
    expense_date: Optional[str] = None,
) -> dict:
    """Atualiza campos de um único registro de gasto.

    Use após identificar o registro com find_expense_candidates.
    O sistema de confirmação HITL gerencia o parâmetro confirmed automaticamente.

    Args:
        expense_id: ID único do registro a ser atualizado
        confirmed: gerenciado pelo sistema — não altere manualmente
        amount: Novo valor em reais (opcional)
        description: Nova descrição (opcional)
        category: Nova categoria (opcional)
        method: Novo método de pagamento (opcional)
        expense_date: Nova data em YYYY-MM-DD (opcional)
    """
    if not confirmed:
        return {
            "error": "Atualização requer confirmed=True. Mostre as mudanças ao usuário e aguarde confirmação.",
            "tipo": "nao_confirmado",
        }

    # Valida cada campo fornecido antes de tocar no banco
    changes: dict = {}

    if amount is not None:
        if amount <= 0 or amount >= 100_000:
            return {"error": f"Valor inválido: {amount}. Deve ser entre 0 e 100.000.", "tipo": "invalido"}
        changes["amount"] = round(amount, 2)

    if description is not None:
        stripped = description.strip()
        if not stripped:
            return {"error": "Descrição não pode ser vazia.", "tipo": "invalido"}
        changes["description"] = stripped

    if category is not None:
        if category not in _get_valid_categories():
            return {
                "error": f"Categoria inválida: '{category}'. Use list_categories para ver as disponíveis.",
                "tipo": "invalido",
            }
        changes["category"] = category

    if method is not None:
        if method not in VALID_METHODS:
            return {"error": f"Método inválido: '{method}'. Use: {', '.join(sorted(VALID_METHODS))}.", "tipo": "invalido"}
        changes["method"] = method

    if expense_date is not None:
        try:
            parsed_date = date.fromisoformat(expense_date)
        except ValueError:
            return {"error": f"Data inválida: '{expense_date}'. Use YYYY-MM-DD.", "tipo": "invalido"}
        if parsed_date > date.today():
            return {"error": "Data não pode ser futura.", "tipo": "invalido"}
        changes["expense_date"] = expense_date

    if not changes:
        return {"error": "Nenhum campo para atualizar foi fornecido.", "tipo": "invalido"}

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, amount, description, category, method, expense_date, hash "
            "FROM expenses WHERE id = ? AND deleted_at IS NULL",
            (expense_id,),
        ).fetchone()

        if not row:
            return {
                "error": f"Registro #{expense_id} não encontrado ou já excluído.",
                "tipo": "nao_encontrado",
            }

        old_data = _row_to_dict(row)

        # Recalcula hash se amount, description ou expense_date mudaram
        hash_fields = {"amount", "description", "expense_date"}
        if hash_fields & set(changes.keys()):
            new_amount = changes.get("amount", old_data["amount"])
            new_desc = changes.get("description", old_data["description"])
            new_date = date.fromisoformat(changes.get("expense_date", old_data["expense_date"]))
            changes["hash"] = _compute_hash(float(new_amount), new_desc, new_date)

        set_clause = ", ".join(f"{col} = ?" for col in changes)
        values = list(changes.values()) + [expense_id]

        try:
            conn.execute(f"UPDATE expenses SET {set_clause} WHERE id = ?", values)
        except sqlite3.IntegrityError:
            return {"error": "A alteração geraria um registro duplicado.", "tipo": "duplicata"}

        new_row = conn.execute(
            "SELECT id, amount, description, category, method, expense_date FROM expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
        new_data = _row_to_dict(new_row)

        conn.execute(
            "INSERT INTO audit_log (operation, expense_id, old_data, new_data) VALUES (?, ?, ?, ?)",
            (
                "update",
                expense_id,
                json.dumps(old_data, ensure_ascii=False),
                json.dumps(new_data, ensure_ascii=False),
            ),
        )
        conn.commit()

    logger.info("Registro #%d atualizado", expense_id)
    return {"updated": True, "expense_id": expense_id, "old": old_data, "new": new_data}


if __name__ == "__main__":
    setup_database()
    mcp.run(transport="stdio")
