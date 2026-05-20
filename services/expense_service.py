"""ExpenseService — lógica de negócio de gastos, escopo por user_id.

Refactored de mcp_server/server.py para produção web multi-tenant.
"""
import hashlib
import json
import logging
import re
import sqlite3
import unicodedata
from datetime import date
from typing import Optional

from models.schemas import ExpenseCreate

logger = logging.getLogger(__name__)


class ExpenseService:
    """Service de gestão de gastos com escopo de user_id.

    Args:
        conn: Conexão SQLite (será Connection do asyncpg no Sprint 2)
        user_id: ID do usuário (opcional no Sprint 1 para compatibilidade)
    """

    def __init__(self, conn: sqlite3.Connection, user_id: Optional[int] = None):
        self.conn = conn
        self.user_id = user_id

    # ─── Utilitários privados ───────────────────────────────────────────

    def _get_valid_categories(self) -> set[str]:
        """Retorna categorias disponíveis (no Sprint 2: filtradas por user_id)."""
        query = "SELECT name FROM categories"
        rows = self.conn.execute(query).fetchall()
        return {row["name"] for row in rows}

    def _get_valid_methods(self) -> set[str]:
        """Retorna métodos de pagamento disponíveis (no Sprint 2: filtrados por user_id)."""
        query = "SELECT name FROM payment_methods"
        rows = self.conn.execute(query).fetchall()
        return {row["name"] for row in rows}

    @staticmethod
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

    @staticmethod
    def _validate_method_name(name: str) -> tuple[str, str | None]:
        """Normaliza e valida um nome de método de pagamento. Retorna (nome_normalizado, erro_ou_None)."""
        clean = name.strip().lower()
        if len(clean) < 2:
            return clean, "Nome do método deve ter pelo menos 2 caracteres."
        if len(clean) > 30:
            return clean, "Nome do método não pode exceder 30 caracteres."
        if not all(c == " " or c == "-" or unicodedata.category(c).startswith("L") for c in clean):
            return clean, "Nome do método deve conter apenas letras, espaços e hífens."
        return clean, None

    @staticmethod
    def _normalize_description(text: str) -> str:
        """Remove acentos e normaliza para busca case-insensitive."""
        text = text.lower().strip()
        text = unicodedata.normalize("NFD", text)
        text = "".join(c for c in text if unicodedata.category(c) != "Mn")
        text = re.sub(r"\s+", " ", text)
        return text

    @staticmethod
    def _compute_hash(amount: float, description: str, expense_date: date) -> str:
        """Gera hash único para detecção de duplicatas."""
        normalized = ExpenseService._normalize_description(description)
        raw = f"{amount:.2f}|{normalized}|{expense_date.isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """Converte Row em dict, transformando date em string."""
        return {k: str(v) if isinstance(v, date) else v for k, v in dict(row).items()}

    # ─── Métodos públicos (business logic) ──────────────────────────────

    def record_expense(
        self,
        amount: float,
        description: str,
        category: str,
        method: str,
        expense_date: Optional[str] = None,
    ) -> dict:
        """Registra um gasto no banco de dados financeiro pessoal.

        Args:
            amount: Valor do gasto em reais (ex: 55.90)
            description: Descrição do gasto (ex: "almoço no restaurante")
            category: Categoria do gasto (deve ser uma das categorias válidas)
            method: Método de pagamento — use list_payment_methods para ver os disponíveis
            expense_date: Data do gasto no formato YYYY-MM-DD (padrão: hoje)

        Returns:
            dict com id e campos do gasto, ou {"error": ..., "tipo": ...}
        """
        valid_categories = self._get_valid_categories()
        if category not in valid_categories:
            return {
                "error": f"Categoria inválida: '{category}'. Use list_categories para ver as disponíveis.",
                "tipo": "invalido",
            }

        valid_methods = self._get_valid_methods()
        if method not in valid_methods:
            return {
                "error": f"Método inválido: '{method}'. Use list_payment_methods para ver os disponíveis.",
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

        expense_hash = self._compute_hash(expense.amount, expense.description, expense.expense_date)

        try:
            cursor = self.conn.execute(
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
            self.conn.commit()
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

    def query_expenses(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        method: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> list[dict]:
        """Consulta gastos ativos com filtros opcionais.

        Args:
            start_date: Data inicial no formato YYYY-MM-DD
            end_date: Data final no formato YYYY-MM-DD
            category: Filtrar por categoria específica
            method: Filtrar por método de pagamento
            keyword: Palavra-chave para busca textual na descrição

        Returns:
            Lista de dicts com dados dos gastos
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

        rows = self.conn.execute(query, params).fetchall()
        results = [dict(row) for row in rows]

        # Filtragem em Python para suporte correto a Unicode/acentos
        if keyword:
            normalized_kw = self._normalize_description(keyword)
            results = [
                r for r in results
                if normalized_kw in self._normalize_description(r["description"])
            ]

        return results

    def get_summary(
        self,
        start_date: str,
        end_date: str,
        group_by: str = "category",
    ) -> dict:
        """Retorna resumo de gastos agrupados por dimensão.

        Args:
            start_date: Data inicial no formato YYYY-MM-DD
            end_date: Data final no formato YYYY-MM-DD
            group_by: Dimensão de agrupamento: 'category', 'method', 'day' ou 'month'

        Returns:
            dict com items agrupados e total_geral
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

        rows = self.conn.execute(query, (start_date, end_date)).fetchall()
        total_row = self.conn.execute(
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

    def list_categories(self) -> list[str]:
        """Retorna a lista de categorias de gastos disponíveis."""
        rows = self.conn.execute("SELECT name FROM categories ORDER BY name").fetchall()
        return [row["name"] for row in rows]

    def list_payment_methods(self) -> list[str]:
        """Retorna a lista de métodos de pagamento disponíveis."""
        rows = self.conn.execute("SELECT name FROM payment_methods ORDER BY name").fetchall()
        return [row["name"] for row in rows]

    def create_payment_method(self, name: str, confirmed: bool) -> dict:
        """Cria um novo método de pagamento definido pelo usuário.

        ATENÇÃO: confirmed=True somente após confirmação explícita do usuário nessa mensagem.
        Métodos do sistema (is_system=1) não podem ser substituídos.

        Args:
            name: Nome do novo método (será normalizado para lowercase)
            confirmed: True apenas se o usuário confirmou explicitamente agora

        Returns:
            dict com {"created": True, "name": ...} ou {"error": ..., "tipo": ...}
        """
        if not confirmed:
            return {
                "error": "Criação de método requer confirmed=True. Mostre o nome ao usuário e aguarde confirmação.",
                "tipo": "nao_confirmado",
            }

        clean, error = self._validate_method_name(name)
        if error:
            return {"error": error, "tipo": "invalido"}

        existing = self.conn.execute(
            "SELECT name FROM payment_methods WHERE LOWER(name) = LOWER(?)", (clean,)
        ).fetchone()
        if existing:
            return {"error": f"Método '{existing['name']}' já existe.", "tipo": "duplicata"}

        self.conn.execute("INSERT INTO payment_methods (name, is_system) VALUES (?, 0)", (clean,))
        self.conn.commit()

        logger.info("Método de pagamento criado pelo usuário: %s", clean)
        return {"created": True, "name": clean}

    def create_category(self, name: str, confirmed: bool) -> dict:
        """Cria uma nova categoria de gastos definida pelo usuário.

        ATENÇÃO: confirmed=True somente após confirmação explícita do usuário nessa mensagem.
        Categorias do sistema (is_system=1) não podem ser substituídas; esta tool só cria
        categorias novas (is_system=0).

        Args:
            name: Nome da nova categoria (será normalizado para title case)
            confirmed: True apenas se o usuário confirmou explicitamente agora

        Returns:
            dict com {"created": True, "name": ...} ou {"error": ..., "tipo": ...}
        """
        if not confirmed:
            return {
                "error": "Criação de categoria requer confirmed=True. Mostre o nome ao usuário e aguarde confirmação.",
                "tipo": "nao_confirmado",
            }

        clean, error = self._validate_category_name(name)
        if error:
            return {"error": error, "tipo": "invalido"}

        existing = self.conn.execute(
            "SELECT name FROM categories WHERE LOWER(name) = LOWER(?)", (clean,)
        ).fetchone()
        if existing:
            return {
                "error": f"Categoria '{existing['name']}' já existe.",
                "tipo": "duplicata",
            }

        self.conn.execute(
            "INSERT INTO categories (name, is_system) VALUES (?, 0)", (clean,)
        )
        self.conn.commit()

        logger.info("Categoria criada pelo usuário: %s", clean)
        return {"created": True, "name": clean}

    def find_expense_candidates(
        self,
        keyword: str,
        expense_date: Optional[str] = None,
    ) -> dict:
        """Busca registros candidatos para edição ou exclusão.

        Use esta função ANTES de delete_expense ou update_expense.

        - Com expense_date: retorna registros daquela data que contêm o keyword.
        - Sem expense_date: retorna registros da DATA MAIS RECENTE que contém o keyword.

        Args:
            keyword: Palavra-chave da descrição (ex: "almoço", "uber", "farmácia")
            expense_date: Data em YYYY-MM-DD. Só informe se o usuário mencionou data específica.

        Returns:
            dict com keyword, date_searched, total_found e records
        """
        normalized_kw = self._normalize_description(keyword)

        all_rows = self.conn.execute(
            "SELECT id, amount, description, category, method, expense_date "
            "FROM expenses WHERE deleted_at IS NULL "
            "ORDER BY expense_date DESC, id DESC"
        ).fetchall()

        # Filtragem em Python para suporte correto a Unicode/acentos
        matching = [
            row for row in all_rows
            if normalized_kw in self._normalize_description(row["description"])
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

    def delete_expense(self, expense_id: int, confirmed: bool) -> dict:
        """Exclui um único registro de gasto (soft delete — dado preservado no banco).

        Use após identificar o registro com find_expense_candidates.
        O sistema de confirmação HITL gerencia o parâmetro confirmed automaticamente.

        Args:
            expense_id: ID único do registro a ser excluído
            confirmed: gerenciado pelo sistema — não altere manualmente

        Returns:
            dict com {"deleted": True, "expense_id": ..., "record": ...} ou {"error": ..., "tipo": ...}
        """
        if not confirmed:
            return {
                "error": "Exclusão requer confirmed=True. Mostre o registro ao usuário e aguarde confirmação.",
                "tipo": "nao_confirmado",
            }

        row = self.conn.execute(
            "SELECT id, amount, description, category, method, expense_date "
            "FROM expenses WHERE id = ? AND deleted_at IS NULL",
            (expense_id,),
        ).fetchone()

        if not row:
            return {
                "error": f"Registro #{expense_id} não encontrado ou já excluído.",
                "tipo": "nao_encontrado",
            }

        old_data = self._row_to_dict(row)

        self.conn.execute(
            "UPDATE expenses SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (expense_id,),
        )
        self.conn.execute(
            "INSERT INTO audit_log (operation, expense_id, old_data) VALUES (?, ?, ?)",
            ("delete", expense_id, json.dumps(old_data, ensure_ascii=False)),
        )
        self.conn.commit()

        logger.info("Registro #%d excluído: %s", expense_id, old_data.get("description"))
        return {"deleted": True, "expense_id": expense_id, "record": old_data}

    def update_expense(
        self,
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

        Returns:
            dict com {"updated": True, "expense_id": ..., "old": ..., "new": ...} ou {"error": ..., "tipo": ...}
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
            if category not in self._get_valid_categories():
                return {
                    "error": f"Categoria inválida: '{category}'. Use list_categories para ver as disponíveis.",
                    "tipo": "invalido",
                }
            changes["category"] = category

        if method is not None:
            if method not in self._get_valid_methods():
                return {
                    "error": f"Método inválido: '{method}'. Use list_payment_methods para ver os disponíveis.",
                    "tipo": "invalido",
                }
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

        row = self.conn.execute(
            "SELECT id, amount, description, category, method, expense_date, hash "
            "FROM expenses WHERE id = ? AND deleted_at IS NULL",
            (expense_id,),
        ).fetchone()

        if not row:
            return {
                "error": f"Registro #{expense_id} não encontrado ou já excluído.",
                "tipo": "nao_encontrado",
            }

        old_data = self._row_to_dict(row)

        # Recalcula hash se amount, description ou expense_date mudaram
        hash_fields = {"amount", "description", "expense_date"}
        if hash_fields & set(changes.keys()):
            new_amount = changes.get("amount", old_data["amount"])
            new_desc = changes.get("description", old_data["description"])
            new_date = date.fromisoformat(changes.get("expense_date", old_data["expense_date"]))
            changes["hash"] = self._compute_hash(float(new_amount), new_desc, new_date)

        set_clause = ", ".join(f"{col} = ?" for col in changes)
        values = list(changes.values()) + [expense_id]

        try:
            self.conn.execute(f"UPDATE expenses SET {set_clause} WHERE id = ?", values)
        except sqlite3.IntegrityError:
            return {"error": "A alteração geraria um registro duplicado.", "tipo": "duplicata"}

        new_row = self.conn.execute(
            "SELECT id, amount, description, category, method, expense_date FROM expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
        new_data = self._row_to_dict(new_row)

        self.conn.execute(
            "INSERT INTO audit_log (operation, expense_id, old_data, new_data) VALUES (?, ?, ?, ?)",
            (
                "update",
                expense_id,
                json.dumps(old_data, ensure_ascii=False),
                json.dumps(new_data, ensure_ascii=False),
            ),
        )
        self.conn.commit()

        logger.info("Registro #%d atualizado", expense_id)
        return {"updated": True, "expense_id": expense_id, "old": old_data, "new": new_data}
