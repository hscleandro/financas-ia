"""IncomeService — lógica de negócio de ganhos/receitas, escopo por user_id."""
import hashlib
import json
import logging
import re
import sqlite3
import unicodedata
from datetime import date
from typing import Optional

from models.schemas import IncomeCreate

logger = logging.getLogger(__name__)


class IncomeService:
    """Service de gestão de ganhos com escopo de user_id.

    Args:
        conn: Conexão SQLite
        user_id: ID do usuário (obrigatório para multi-tenant)
    """

    def __init__(self, conn: sqlite3.Connection, user_id: Optional[int] = None):
        self.conn = conn
        self.user_id = user_id

    # ─── Utilitários privados ───────────────────────────────────────────

    def _get_valid_categories(self) -> set[str]:
        """Retorna categorias de ganho disponíveis — system + custom do usuário."""
        if self.user_id is not None:
            query = "SELECT name FROM income_categories WHERE user_id IS NULL OR user_id = ?"
            rows = self.conn.execute(query, (self.user_id,)).fetchall()
        else:
            query = "SELECT name FROM income_categories"
            rows = self.conn.execute(query).fetchall()
        return {row["name"] for row in rows}

    @staticmethod
    def _validate_category_name(name: str) -> tuple[str, str | None]:
        """Normaliza e valida um nome de categoria de ganho."""
        clean = name.strip().title()
        if len(clean) < 2:
            return clean, "Nome da categoria deve ter pelo menos 2 caracteres."
        if len(clean) > 30:
            return clean, "Nome da categoria não pode exceder 30 caracteres."
        if not all(c == " " or c == "-" or unicodedata.category(c).startswith("L") for c in clean):
            return clean, "Nome da categoria deve conter apenas letras, espaços e hífens."
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
    def _compute_hash(amount: float, description: str, income_date: date) -> str:
        """Gera hash único para detecção de duplicatas."""
        normalized = IncomeService._normalize_description(description)
        raw = f"{amount:.2f}|{normalized}|{income_date.isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """Converte Row em dict, transformando date em string."""
        return {k: str(v) if isinstance(v, date) else v for k, v in dict(row).items()}

    # ─── Métodos públicos (business logic) ──────────────────────────────

    def record_income(
        self,
        amount: float,
        description: str,
        category: str,
        income_date: Optional[str] = None,
    ) -> dict:
        """Registra um ganho no banco de dados.

        Args:
            amount: Valor do ganho em reais (ex: 5000.00)
            description: Descrição do ganho (ex: "Salário agosto")
            category: Categoria do ganho (deve ser uma das válidas)
            income_date: Data do ganho no formato YYYY-MM-DD (padrão: hoje)

        Returns:
            dict com id e campos do ganho, ou {"error": ..., "tipo": ...}
        """
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

        income_hash = self._compute_hash(income.amount, income.description, income.income_date)

        try:
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
        except sqlite3.IntegrityError:
            logger.warning(
                "Duplicata detectada: %s · R$%.2f · %s",
                income.description,
                income.amount,
                income.income_date,
            )
            return {"error": "Ganho duplicado: já existe um registro idêntico.", "tipo": "duplicata"}

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
            normalized_kw = self._normalize_description(keyword)
            results = [
                r for r in results
                if normalized_kw in self._normalize_description(r["description"])
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
        """Retorna a lista de categorias de ganho disponíveis."""
        return sorted(list(self._get_valid_categories()))

    def create_income_category(self, name: str, confirmed: bool) -> dict:
        """Cria uma nova categoria de ganho definida pelo usuário."""
        if not confirmed:
            return {
                "error": "Criação de categoria requer confirmed=True. Mostre o nome ao usuário e aguarde confirmação.",
                "tipo": "nao_confirmado",
            }

        clean, error = self._validate_category_name(name)
        if error:
            return {"error": error, "tipo": "invalido"}

        if self.user_id is not None:
            existing = self.conn.execute(
                "SELECT name FROM income_categories WHERE LOWER(name) = LOWER(?) AND (user_id IS NULL OR user_id = ?)",
                (clean, self.user_id),
            ).fetchone()
        else:
            existing = self.conn.execute(
                "SELECT name FROM income_categories WHERE LOWER(name) = LOWER(?)", (clean,)
            ).fetchone()

        if existing:
            return {"error": f"Categoria '{existing['name']}' já existe.", "tipo": "duplicata"}

        if self.user_id is not None:
            self.conn.execute(
                "INSERT INTO income_categories (name, is_system, user_id) VALUES (?, 0, ?)",
                (clean, self.user_id),
            )
        else:
            self.conn.execute(
                "INSERT INTO income_categories (name, is_system) VALUES (?, 0)", (clean,)
            )

        self.conn.commit()

        logger.info("Categoria de ganho criada pelo usuário: %s", clean)
        return {"created": True, "name": clean}

    def find_income_candidates(
        self,
        keyword: str,
        income_date: Optional[str] = None,
    ) -> dict:
        """Busca registros candidatos para edição ou exclusão."""
        normalized_kw = self._normalize_description(keyword)

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
            if normalized_kw in self._normalize_description(row["description"])
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

        if self.user_id is not None:
            row = self.conn.execute(
                "SELECT id, amount, description, category, income_date "
                "FROM incomes WHERE id = ? AND deleted_at IS NULL AND user_id = ?",
                (income_id, self.user_id),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT id, amount, description, category, income_date "
                "FROM incomes WHERE id = ? AND deleted_at IS NULL",
                (income_id,),
            ).fetchone()

        if not row:
            return {
                "error": f"Registro #{income_id} não encontrado ou já excluído.",
                "tipo": "nao_encontrado",
            }

        old_data = self._row_to_dict(row)

        self.conn.execute(
            "UPDATE incomes SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (income_id,),
        )

        if self.user_id is not None:
            self.conn.execute(
                "INSERT INTO audit_log (operation, expense_id, old_data, user_id) VALUES (?, ?, ?, ?)",
                ("delete", income_id, json.dumps(old_data, ensure_ascii=False), self.user_id),
            )
        else:
            self.conn.execute(
                "INSERT INTO audit_log (operation, expense_id, old_data) VALUES (?, ?, ?)",
                ("delete", income_id, json.dumps(old_data, ensure_ascii=False)),
            )

        self.conn.commit()

        logger.info("Registro de ganho #%d excluído: %s", income_id, old_data.get("description"))
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

        if self.user_id is not None:
            row = self.conn.execute(
                "SELECT id, amount, description, category, income_date, hash "
                "FROM incomes WHERE id = ? AND deleted_at IS NULL AND user_id = ?",
                (income_id, self.user_id),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT id, amount, description, category, income_date, hash "
                "FROM incomes WHERE id = ? AND deleted_at IS NULL",
                (income_id,),
            ).fetchone()

        if not row:
            return {
                "error": f"Registro #{income_id} não encontrado ou já excluído.",
                "tipo": "nao_encontrado",
            }

        old_data = self._row_to_dict(row)

        hash_fields = {"amount", "description", "income_date"}
        if hash_fields & set(changes.keys()):
            new_amount = changes.get("amount", old_data["amount"])
            new_desc = changes.get("description", old_data["description"])
            new_date = date.fromisoformat(changes.get("income_date", old_data["income_date"]))
            changes["hash"] = self._compute_hash(float(new_amount), new_desc, new_date)

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
        new_data = self._row_to_dict(new_row)

        if self.user_id is not None:
            self.conn.execute(
                "INSERT INTO audit_log (operation, expense_id, old_data, new_data, user_id) VALUES (?, ?, ?, ?, ?)",
                (
                    "update",
                    income_id,
                    json.dumps(old_data, ensure_ascii=False),
                    json.dumps(new_data, ensure_ascii=False),
                    self.user_id,
                ),
            )
        else:
            self.conn.execute(
                "INSERT INTO audit_log (operation, expense_id, old_data, new_data) VALUES (?, ?, ?, ?)",
                (
                    "update",
                    income_id,
                    json.dumps(old_data, ensure_ascii=False),
                    json.dumps(new_data, ensure_ascii=False),
                ),
            )

        self.conn.commit()

        logger.info("Registro de ganho #%d atualizado", income_id)
        return {"updated": True, "income_id": income_id, "old": old_data, "new": new_data}
