"""IncomeService — lógica de negócio de ganhos/receitas, escopo por user_id."""
import sqlite3
from datetime import date
from typing import Optional

from models.schemas import IncomeCreate
from services._base import (
    compute_hash,
    create_custom_category,
    get_valid_categories,
    log_audit,
    normalize_description,
    row_to_dict,
    soft_delete,
)


class IncomeService:
    """Service de gestão de ganhos com escopo de user_id."""

    def __init__(self, conn: sqlite3.Connection, user_id: Optional[int] = None):
        self.conn = conn
        self.user_id = user_id

    def _get_valid_categories(self) -> set[str]:
        return get_valid_categories(self.conn, "income_categories", self.user_id)

    def _find_duplicate(self, income_hash: str) -> dict | None:
        """Busca registro ativo com mesmo hash para o usuário atual."""
        if self.user_id is not None:
            row = self.conn.execute(
                "SELECT id, amount, description, category, income_date "
                "FROM incomes WHERE hash = ? AND deleted_at IS NULL AND user_id = ?",
                (income_hash, self.user_id),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT id, amount, description, category, income_date "
                "FROM incomes WHERE hash = ? AND deleted_at IS NULL",
                (income_hash,),
            ).fetchone()
        return dict(row) if row else None

    def record_income(
        self,
        amount: float,
        description: str,
        category: str,
        income_date: Optional[str] = None,
        force: bool = False,
    ) -> dict:
        """Registra um ganho no banco de dados."""
        valid_categories = self._get_valid_categories()
        if category not in valid_categories:
            return {
                "error": f"Categoria inválida: '{category}'. Use list_income_categories para ver as disponíveis.",
                "tipo": "invalido",
            }

        try:
            income = IncomeCreate(
                amount=amount,
                description=description,
                category=category,
                income_date=income_date,
            )
        except Exception as e:
            return {"error": str(e), "tipo": "invalido"}

        income_hash = compute_hash(income.amount, income.description, income.income_date)

        if not force:
            duplicate = self._find_duplicate(income_hash)
            if duplicate:
                return {
                    "warning": "Já existe um ganho idêntico. Deseja cadastrar mesmo assim?",
                    "tipo": "duplicata",
                    "record": duplicate,
                }

        cursor = self.conn.execute(
            """
            INSERT INTO incomes (user_id, amount, description, category, income_date, hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self.user_id,
                income.amount,
                income.description,
                income.category,
                income.income_date.isoformat(),
                income_hash,
            ),
        )
        self.conn.commit()
        income_id = cursor.lastrowid

        return {
            "id": income_id,
            "amount": income.amount,
            "description": income.description,
            "category": income.category,
            "income_date": income.income_date.isoformat(),
        }

    def query_incomes(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> list[dict]:
        """Consulta ganhos ativos com filtros opcionais."""
        query = (
            "SELECT id, amount, description, category, income_date, created_at "
            "FROM incomes WHERE deleted_at IS NULL"
        )
        params: list = []

        if self.user_id is not None:
            query += " AND user_id = ?"
            params.append(self.user_id)

        if start_date:
            query += " AND income_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND income_date <= ?"
            params.append(end_date)
        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY income_date DESC, created_at DESC"

        rows = self.conn.execute(query, params).fetchall()
        results = [dict(row) for row in rows]

        if keyword:
            normalized_kw = normalize_description(keyword)
            results = [
                r for r in results
                if normalized_kw in normalize_description(r["description"])
            ]

        return results

    def get_income_summary(
        self,
        start_date: str,
        end_date: str,
        group_by: str = "category",
    ) -> dict:
        """Retorna resumo de ganhos agrupados por dimensão."""
        valid_groups = {"category", "day", "month"}
        if group_by not in valid_groups:
            return {"error": f"group_by deve ser um de: {', '.join(valid_groups)}"}

        group_expr = {
            "category": "category",
            "day": "income_date",
            "month": "strftime('%Y-%m', income_date)",
        }[group_by]

        user_filter = " AND user_id = ?" if self.user_id is not None else ""
        params = [start_date, end_date]
        if self.user_id is not None:
            params.append(self.user_id)

        query = f"""
            SELECT {group_expr} AS dimension, SUM(amount) AS total, COUNT(*) AS count
            FROM incomes
            WHERE income_date BETWEEN ? AND ?
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
            f"SELECT SUM(amount) FROM incomes WHERE income_date BETWEEN ? AND ? AND deleted_at IS NULL{user_filter}",
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

    def list_income_categories(self) -> list[str]:
        return sorted(list(self._get_valid_categories()))

    def create_income_category(self, name: str, confirmed: bool) -> dict:
        """Cria uma nova categoria de ganho definida pelo usuário."""
        return create_custom_category(self.conn, "income_categories", name, confirmed, self.user_id)

    def find_income_candidates(
        self,
        keyword: str,
        income_date: Optional[str] = None,
    ) -> dict:
        """Busca registros candidatos para edição ou exclusão."""
        normalized_kw = normalize_description(keyword)

        if self.user_id is not None:
            all_rows = self.conn.execute(
                "SELECT id, amount, description, category, income_date "
                "FROM incomes WHERE deleted_at IS NULL AND user_id = ? "
                "ORDER BY income_date DESC, id DESC",
                (self.user_id,),
            ).fetchall()
        else:
            all_rows = self.conn.execute(
                "SELECT id, amount, description, category, income_date "
                "FROM incomes WHERE deleted_at IS NULL "
                "ORDER BY income_date DESC, id DESC"
            ).fetchall()

        matching = [
            row for row in all_rows
            if normalized_kw in normalize_description(row["description"])
        ]

        if not matching:
            return {"keyword": keyword, "date_searched": income_date, "total_found": 0, "records": []}

        if income_date is None:
            date_searched = max(row["income_date"] for row in matching)
        else:
            date_searched = income_date

        records = [dict(row) for row in matching if row["income_date"] == date_searched]

        return {
            "keyword": keyword,
            "date_searched": date_searched,
            "total_found": len(records),
            "records": records,
        }

    def delete_income(self, income_id: int, confirmed: bool) -> dict:
        """Exclui um único registro de ganho (soft delete)."""
        if not confirmed:
            return {
                "error": "Exclusão requer confirmed=True. Mostre o registro ao usuário e aguarde confirmação.",
                "tipo": "nao_confirmado",
            }

        old_data = soft_delete(self.conn, "incomes", income_id, self.user_id)
        if old_data is None:
            return {
                "error": f"Registro #{income_id} não encontrado ou já excluído.",
                "tipo": "nao_encontrado",
            }

        log_audit(self.conn, "delete", income_id, old_data, user_id=self.user_id)
        self.conn.commit()
        return {"deleted": True, "income_id": income_id, "record": old_data}

    def update_income(
        self,
        income_id: int,
        confirmed: bool,
        amount: Optional[float] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        income_date: Optional[str] = None,
    ) -> dict:
        """Atualiza campos de um único registro de ganho."""
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
                    "error": f"Categoria inválida: '{category}'. Use list_income_categories para ver as disponíveis.",
                    "tipo": "invalido",
                }
            changes["category"] = category

        if income_date is not None:
            try:
                parsed_date = date.fromisoformat(income_date)
            except ValueError:
                return {"error": f"Data inválida: '{income_date}'. Use YYYY-MM-DD.", "tipo": "invalido"}
            if parsed_date > date.today():
                return {"error": "Data não pode ser futura.", "tipo": "invalido"}
            changes["income_date"] = income_date

        if not changes:
            return {"error": "Nenhum campo para atualizar foi fornecido.", "tipo": "invalido"}

        user_filter = " AND user_id = ?" if self.user_id is not None else ""
        params = (income_id, self.user_id) if self.user_id is not None else (income_id,)
        row = self.conn.execute(
            f"SELECT id, amount, description, category, income_date, hash "
            f"FROM incomes WHERE id = ? AND deleted_at IS NULL{user_filter}",
            params,
        ).fetchone()

        if not row:
            return {
                "error": f"Registro #{income_id} não encontrado ou já excluído.",
                "tipo": "nao_encontrado",
            }

        old_data = row_to_dict(row)

        hash_fields = {"amount", "description", "income_date"}
        if hash_fields & set(changes.keys()):
            new_amount = changes.get("amount", old_data["amount"])
            new_desc = changes.get("description", old_data["description"])
            new_date = date.fromisoformat(changes.get("income_date", old_data["income_date"]))
            changes["hash"] = compute_hash(float(new_amount), new_desc, new_date)

        set_clause = ", ".join(f"{col} = ?" for col in changes)
        values = list(changes.values()) + [income_id]

        try:
            self.conn.execute(f"UPDATE incomes SET {set_clause} WHERE id = ?", values)
        except sqlite3.IntegrityError:
            return {"error": "A alteração geraria um registro duplicado.", "tipo": "duplicata"}

        new_row = self.conn.execute(
            "SELECT id, amount, description, category, income_date FROM incomes WHERE id = ?",
            (income_id,),
        ).fetchone()
        new_data = row_to_dict(new_row)

        log_audit(self.conn, "update", income_id, old_data, new_data, user_id=self.user_id)
        self.conn.commit()

        return {"updated": True, "income_id": income_id, "old": old_data, "new": new_data}
