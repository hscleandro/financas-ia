"""ExpenseService — lógica de negócio de gastos, escopo por user_id."""
import sqlite3
from datetime import date
from typing import Optional

from models.schemas import ExpenseCreate
from services._base import (
    compute_hash,
    create_custom_category,
    get_valid_categories,
    log_audit,
    normalize_description,
    row_to_dict,
    soft_delete,
    validate_method_name,
)


class ExpenseService:
    """Service de gestão de gastos com escopo de user_id."""

    def __init__(self, conn: sqlite3.Connection, user_id: Optional[int] = None):
        self.conn = conn
        self.user_id = user_id

    def _get_valid_categories(self) -> set[str]:
        return get_valid_categories(self.conn, "categories", self.user_id)

    def _get_valid_methods(self) -> set[str]:
        """Retorna métodos de pagamento disponíveis — system + custom do usuário."""
        if self.user_id is not None:
            query = "SELECT name FROM payment_methods WHERE user_id IS NULL OR user_id = ?"
            rows = self.conn.execute(query, (self.user_id,)).fetchall()
        else:
            query = "SELECT name FROM payment_methods"
            rows = self.conn.execute(query).fetchall()
        return {row["name"] for row in rows}

    def _find_duplicate(self, expense_hash: str) -> dict | None:
        """Busca registro ativo com mesmo hash para o usuário atual."""
        if self.user_id is not None:
            row = self.conn.execute(
                "SELECT id, amount, description, category, method, expense_date "
                "FROM expenses WHERE hash = ? AND deleted_at IS NULL AND user_id = ?",
                (expense_hash, self.user_id),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT id, amount, description, category, method, expense_date "
                "FROM expenses WHERE hash = ? AND deleted_at IS NULL",
                (expense_hash,),
            ).fetchone()
        return dict(row) if row else None

    def record_expense(
        self,
        amount: float,
        description: str,
        category: str,
        method: str,
        expense_date: Optional[str] = None,
        force: bool = False,
    ) -> dict:
        """Registra um gasto no banco de dados financeiro pessoal."""
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

        expense_hash = compute_hash(expense.amount, expense.description, expense.expense_date)

        if not force:
            duplicate = self._find_duplicate(expense_hash)
            if duplicate:
                return {
                    "warning": "Já existe um gasto idêntico. Deseja cadastrar mesmo assim?",
                    "tipo": "duplicata",
                    "record": duplicate,
                }

        if self.user_id is not None:
            cursor = self.conn.execute(
                """
                INSERT INTO expenses (user_id, amount, description, category, method, expense_date, hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.user_id,
                    expense.amount,
                    expense.description,
                    expense.category,
                    expense.method,
                    expense.expense_date.isoformat(),
                    expense_hash,
                ),
            )
        else:
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

    def query_expenses(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        method: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> list[dict]:
        """Consulta gastos ativos com filtros opcionais."""
        query = (
            "SELECT id, amount, description, category, method, expense_date, created_at "
            "FROM expenses WHERE deleted_at IS NULL"
        )
        params: list = []

        if self.user_id is not None:
            query += " AND user_id = ?"
            params.append(self.user_id)

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

        if keyword:
            normalized_kw = normalize_description(keyword)
            results = [
                r for r in results
                if normalized_kw in normalize_description(r["description"])
            ]

        return results

    def get_summary(
        self,
        start_date: str,
        end_date: str,
        group_by: str = "category",
    ) -> dict:
        """Retorna resumo de gastos agrupados por dimensão."""
        valid_groups = {"category", "method", "day", "month"}
        if group_by not in valid_groups:
            return {"error": f"group_by deve ser um de: {', '.join(valid_groups)}"}

        group_expr = {
            "category": "category",
            "method": "method",
            "day": "expense_date",
            "month": "strftime('%Y-%m', expense_date)",
        }[group_by]

        user_filter = " AND user_id = ?" if self.user_id is not None else ""
        params = [start_date, end_date]
        if self.user_id is not None:
            params.append(self.user_id)

        query = f"""
            SELECT {group_expr} AS dimension, SUM(amount) AS total, COUNT(*) AS count
            FROM expenses
            WHERE expense_date BETWEEN ? AND ?
              AND deleted_at IS NULL
              {user_filter}
            GROUP BY {group_expr}
            ORDER BY total DESC
        """

        rows = self.conn.execute(query, tuple(params)).fetchall()

        total_params = [start_date, end_date]
        if self.user_id is not None:
            total_params.append(self.user_id)

        total_row = self.conn.execute(
            f"SELECT SUM(amount) FROM expenses WHERE expense_date BETWEEN ? AND ? AND deleted_at IS NULL{user_filter}",
            tuple(total_params),
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
        return sorted(list(self._get_valid_categories()))

    def list_payment_methods(self) -> list[str]:
        return sorted(list(self._get_valid_methods()))

    def create_payment_method(self, name: str, confirmed: bool) -> dict:
        """Cria um novo método de pagamento definido pelo usuário."""
        if not confirmed:
            return {
                "error": "Criação de método requer confirmed=True. Mostre o nome ao usuário e aguarde confirmação.",
                "tipo": "nao_confirmado",
            }

        clean, error = validate_method_name(name)
        if error:
            return {"error": error, "tipo": "invalido"}

        if self.user_id is not None:
            existing = self.conn.execute(
                "SELECT name FROM payment_methods WHERE LOWER(name) = LOWER(?) AND (user_id IS NULL OR user_id = ?)",
                (clean, self.user_id),
            ).fetchone()
        else:
            existing = self.conn.execute(
                "SELECT name FROM payment_methods WHERE LOWER(name) = LOWER(?)", (clean,)
            ).fetchone()

        if existing:
            return {"error": f"Método '{existing['name']}' já existe.", "tipo": "duplicata"}

        if self.user_id is not None:
            self.conn.execute(
                "INSERT INTO payment_methods (name, is_system, user_id) VALUES (?, 0, ?)",
                (clean, self.user_id),
            )
        else:
            self.conn.execute("INSERT INTO payment_methods (name, is_system) VALUES (?, 0)", (clean,))

        self.conn.commit()
        return {"created": True, "name": clean}

    def create_category(self, name: str, confirmed: bool) -> dict:
        """Cria uma nova categoria de gastos definida pelo usuário."""
        result = create_custom_category(self.conn, "categories", name, confirmed, self.user_id)
        if result.get("created"):
            # Log removido para manter simplicidade; adicione se necessário.
            pass
        return result

    def find_expense_candidates(
        self,
        keyword: str,
        expense_date: Optional[str] = None,
    ) -> dict:
        """Busca registros candidatos para edição ou exclusão."""
        normalized_kw = normalize_description(keyword)

        if self.user_id is not None:
            all_rows = self.conn.execute(
                "SELECT id, amount, description, category, method, expense_date "
                "FROM expenses WHERE deleted_at IS NULL AND user_id = ? "
                "ORDER BY expense_date DESC, id DESC",
                (self.user_id,),
            ).fetchall()
        else:
            all_rows = self.conn.execute(
                "SELECT id, amount, description, category, method, expense_date "
                "FROM expenses WHERE deleted_at IS NULL "
                "ORDER BY expense_date DESC, id DESC"
            ).fetchall()

        matching = [
            row for row in all_rows
            if normalized_kw in normalize_description(row["description"])
        ]

        if not matching:
            return {"keyword": keyword, "date_searched": expense_date, "total_found": 0, "records": []}

        if expense_date is None:
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
        """Exclui um único registro de gasto (soft delete)."""
        if not confirmed:
            return {
                "error": "Exclusão requer confirmed=True. Mostre o registro ao usuário e aguarde confirmação.",
                "tipo": "nao_confirmado",
            }

        old_data = soft_delete(self.conn, "expenses", expense_id, self.user_id)
        if old_data is None:
            return {
                "error": f"Registro #{expense_id} não encontrado ou já excluído.",
                "tipo": "nao_encontrado",
            }

        log_audit(self.conn, "delete", expense_id, old_data, user_id=self.user_id)
        self.conn.commit()
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
        """Atualiza campos de um único registro de gasto."""
        if not confirmed:
            return {
                "error": "Atualização requer confirmed=True. Mostre as mudanças ao usuário e aguarde confirmação.",
                "tipo": "nao_confirmado",
            }

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

        user_filter = " AND user_id = ?" if self.user_id is not None else ""
        params = (expense_id, self.user_id) if self.user_id is not None else (expense_id,)
        row = self.conn.execute(
            f"SELECT id, amount, description, category, method, expense_date, hash "
            f"FROM expenses WHERE id = ? AND deleted_at IS NULL{user_filter}",
            params,
        ).fetchone()

        if not row:
            return {
                "error": f"Registro #{expense_id} não encontrado ou já excluído.",
                "tipo": "nao_encontrado",
            }

        old_data = row_to_dict(row)

        hash_fields = {"amount", "description", "expense_date"}
        if hash_fields & set(changes.keys()):
            new_amount = changes.get("amount", old_data["amount"])
            new_desc = changes.get("description", old_data["description"])
            new_date = date.fromisoformat(changes.get("expense_date", old_data["expense_date"]))
            changes["hash"] = compute_hash(float(new_amount), new_desc, new_date)

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
        new_data = row_to_dict(new_row)

        log_audit(self.conn, "update", expense_id, old_data, new_data, user_id=self.user_id)
        self.conn.commit()

        return {"updated": True, "expense_id": expense_id, "old": old_data, "new": new_data}
