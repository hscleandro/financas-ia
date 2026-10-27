"""Serviço de importação e conciliação de faturas de cartão.

V1.1:
- Suporte a múltiplos cartões selecionados na mesma fatura.
- Aprovação individual de lançamentos (inserção, match, revisão).
- Persistência de progresso via status em statement_transactions.
- Sugestão automática de categoria via histórico + IA.
"""
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from services._base import compute_hash, log_audit, soft_delete
from services.category_suggester import CategorySuggester
from services.statement_parser import (
    ParsedStatement,
    ParsedTransaction,
    parse_bradesco_statement,
)


CREDIT_CARD_METHOD = "crédito"


@dataclass
class CandidateMatch:
    statement_tx: ParsedTransaction
    expense: dict
    date_diff: int


@dataclass
class ReconciliationSection:
    only_on_statement: list[ParsedTransaction] = field(default_factory=list)
    matched: list[CandidateMatch] = field(default_factory=list)
    only_on_database: list[dict] = field(default_factory=list)


@dataclass
class ReconciliationResult:
    sections: dict[str, ReconciliationSection] = field(default_factory=dict)
    ambiguous: list[tuple[ParsedTransaction, list[dict]]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class StatementService:
    """Service de importação/conciliação de faturas de cartão."""

    def __init__(self, conn: sqlite3.Connection, user_id: int):
        self.conn = conn
        self.user_id = user_id
        self._suggester = CategorySuggester(conn, user_id)

    def import_statement(
        self,
        pdf_path: Path | str,
        selected_cards: Optional[list[str]] = None,
    ) -> tuple[int, ParsedStatement, list[str]]:
        """Parseia o PDF, persiste metadados e transações e retorna statement_id.

        Args:
            pdf_path: caminho para o arquivo PDF.
            selected_cards: lista de últimos 4 dígitos dos cartões selecionados.
                Se None, processa todos os cartões identificados.

        Returns:
            (statement_id, statement parseado, lista de cartões processados).
        """
        pdf_path = Path(pdf_path)
        statement = parse_bradesco_statement(pdf_path)

        # Determina cartões a processar
        all_cards = list({tx.card_last_four for tx in statement.transactions if tx.card_last_four})
        if selected_cards:
            cards_to_process = [c for c in all_cards if c in selected_cards]
        else:
            cards_to_process = all_cards

        if not cards_to_process and all_cards:
            cards_to_process = all_cards

        file_hash = statement.file_hash
        existing = self.conn.execute(
            "SELECT id FROM card_statements WHERE file_hash = ?",
            (file_hash,),
        ).fetchone()

        if existing:
            statement_id = existing["id"]
            # Limpa transações pendentes para reprocessamento
            self.conn.execute(
                "DELETE FROM statement_transactions WHERE statement_id = ?",
                (statement_id,),
            )
        else:
            cursor = self.conn.execute(
                """
                INSERT INTO card_statements (
                    user_id, file_hash, file_name, statement_date, due_date,
                    total_cents, card_last_four, card_holder, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    self.user_id,
                    file_hash,
                    statement.file_name,
                    statement.statement_date.isoformat() if statement.statement_date else None,
                    statement.due_date.isoformat() if statement.due_date else None,
                    statement.total_cents,
                    ",".join(cards_to_process) if cards_to_process else None,
                    statement.holder_name,
                ),
            )
            statement_id = cursor.lastrowid

        # Persiste apenas transações dos cartões selecionados
        for tx in statement.transactions:
            if tx.is_credit:
                continue
            if tx.card_last_four and tx.card_last_four not in cards_to_process:
                continue
            if tx.ambiguous and not tx.card_last_four:
                # Lançamento sem cartão identificado: só processa se não houver
                # seleção específica ou se for o único cartão
                if cards_to_process and len(cards_to_process) == 1:
                    tx.card_last_four = cards_to_process[0]
                    tx.card_holder = statement.holder_name
                else:
                    continue

            # Sugestão rápida via histórico; IA sob demanda na revisão.
            suggested = self._suggester.suggest_from_history(tx.description)

            self.conn.execute(
                """
                INSERT INTO statement_transactions (
                    statement_id, card_holder, card_last_four, transaction_date,
                    description, amount_cents, installment_info, raw_line,
                    selected_category, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    statement_id,
                    tx.card_holder,
                    tx.card_last_four,
                    tx.transaction_date.isoformat(),
                    tx.description,
                    tx.amount_cents,
                    tx.installment_info,
                    tx.raw_line,
                    suggested,
                ),
            )

        self.conn.commit()
        return statement_id, statement, cards_to_process

    def _eligible_expenses(
        self,
        start_date: date,
        end_date: date,
        method: str = CREDIT_CARD_METHOD,
    ) -> list[dict]:
        """Retorna despesas elegíveis de cartão de crédito do período."""
        rows = self.conn.execute(
            """
            SELECT id, amount, description, category, method, expense_date,
                   card_last_four, card_holder, statement_id
            FROM expenses
            WHERE user_id = ?
              AND method = ?
              AND deleted_at IS NULL
              AND expense_date BETWEEN ? AND ?
            ORDER BY expense_date DESC, id DESC
            """,
            (self.user_id, method, start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
        return [dict(row) for row in rows]

    def reconcile(self, statement_id: int) -> ReconciliationResult:
        """Executa o motor de conciliação e retorna seções por cartão.

        Processa apenas transações com status 'pending'. Transações já
        aprovadas/rejeitadas não aparecem.
        """
        result = ReconciliationResult()

        statement_row = self.conn.execute(
            "SELECT due_date, card_last_four FROM card_statements WHERE id = ? AND user_id = ?",
            (statement_id, self.user_id),
        ).fetchone()
        if not statement_row:
            raise ValueError("Fatura não encontrada ou não pertence ao usuário.")

        due_date = date.fromisoformat(statement_row["due_date"])
        start_date = due_date - timedelta(days=50)
        end_date = due_date

        # Carrega transações pendentes
        rows = self.conn.execute(
            """
            SELECT id, card_holder, card_last_four, transaction_date,
                   description, amount_cents, installment_info, raw_line,
                   selected_category, status, matched_expense_id
            FROM statement_transactions
            WHERE statement_id = ? AND status IN ('pending', 'matched')
            ORDER BY transaction_date, id
            """,
            (statement_id,),
        ).fetchall()

        statement_txs = [
            ParsedTransaction(
                id=row["id"],
                transaction_date=date.fromisoformat(row["transaction_date"]),
                description=row["description"],
                amount_cents=row["amount_cents"],
                card_holder=row["card_holder"],
                card_last_four=row["card_last_four"],
                installment_info=row["installment_info"],
                raw_line=row["raw_line"],
            )
            for row in rows
        ]

        # Indexa sugestões de categoria
        suggestions = {row["id"]: row["selected_category"] for row in rows}

        eligible_expenses = self._eligible_expenses(start_date, end_date)

        # Agrupa por cartão
        cards = sorted({tx.card_last_four or "não identificado" for tx in statement_txs})

        used_expense_ids: set[int] = set()

        for card in cards:
            card_txs = [tx for tx in statement_txs if (tx.card_last_four or "não identificado") == card]
            section = ReconciliationSection()

            for tx in card_txs:
                candidates: list[tuple[int, dict]] = []
                for exp in eligible_expenses:
                    exp_id = exp["id"]
                    if exp_id in used_expense_ids:
                        continue
                    exp_cents = int(round(exp["amount"] * 100))
                    if exp_cents != tx.amount_cents:
                        continue
                    exp_date = date.fromisoformat(exp["expense_date"])
                    diff = abs((tx.transaction_date - exp_date).days)
                    if diff <= 2:
                        candidates.append((diff, exp))

                if not candidates:
                    section.only_on_statement.append(tx)
                    continue

                if len(candidates) == 1:
                    diff, exp = candidates[0]
                    used_expense_ids.add(exp["id"])
                    section.matched.append(CandidateMatch(tx, exp, diff))
                else:
                    candidates.sort(key=lambda x: x[0])
                    result.ambiguous.append((tx, [c[1] for c in candidates]))

            # Despesas elegíveis não usadas para este cartão
            # Na V1.1, "só no banco" é mostrado por cartão quando possível;
            # quando não há vínculo de cartão no banco, mostra todas.
            card_db = [
                exp for exp in eligible_expenses
                if exp["id"] not in used_expense_ids
                and (
                    card == "não identificado"
                    or not exp.get("card_last_four")
                    or exp.get("card_last_four") == card
                )
            ]
            section.only_on_database = card_db

            result.sections[card] = section

        if any(tx.ambiguous for tx in statement_txs):
            result.warnings.append(
                "Alguns lançamentos não puderam ser associados a um cartão/titular "
                "e foram sinalizados para revisão."
            )

        return result

    def approve_insert(self, tx_id: int, category: Optional[str] = None) -> dict:
        """Aprova a inserção de um lançamento da fatura no banco."""
        tx_row = self.conn.execute(
            """
            SELECT statement_id, transaction_date, description, amount_cents,
                   card_last_four, card_holder, selected_category
            FROM statement_transactions
            WHERE id = ? AND status = 'pending'
            """,
            (tx_id,),
        ).fetchone()
        if not tx_row:
            return {"error": "Lançamento não encontrado ou já revisado."}

        statement_id = tx_row["statement_id"]
        self._verify_statement_ownership(statement_id)

        chosen_category = category or tx_row["selected_category"] or "Outros"
        if not self._category_exists(chosen_category):
            return {"error": f"Categoria inválida: {chosen_category}"}

        amount = tx_row["amount_cents"] / 100
        desc = tx_row["description"]
        tx_date = tx_row["transaction_date"]
        expense_hash = compute_hash(amount, desc, date.fromisoformat(tx_date))

        cursor = self.conn.execute(
            """
            INSERT INTO expenses (
                user_id, amount, description, category, method,
                expense_date, hash, card_last_four, card_holder, statement_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.user_id,
                amount,
                desc,
                chosen_category,
                CREDIT_CARD_METHOD,
                tx_date,
                expense_hash,
                tx_row["card_last_four"],
                tx_row["card_holder"],
                statement_id,
            ),
        )

        self.conn.execute(
            """
            UPDATE statement_transactions
            SET status = 'inserted', selected_category = ?, reviewed_at = CURRENT_TIMESTAMP,
                matched_expense_id = ?
            WHERE id = ?
            """,
            (chosen_category, cursor.lastrowid, tx_id),
        )

        self._update_statement_status(statement_id)
        self.conn.commit()

        return {"success": True, "expense_id": cursor.lastrowid, "category": chosen_category}

    def approve_match(self, tx_id: int, expense_id: int) -> dict:
        """Aprova a correspondência entre fatura e despesa existente."""
        tx_row = self.conn.execute(
            """
            SELECT statement_id, transaction_date, description, amount_cents,
                   card_last_four, card_holder
            FROM statement_transactions
            WHERE id = ? AND status IN ('pending', 'matched')
            """,
            (tx_id,),
        ).fetchone()
        if not tx_row:
            return {"error": "Lançamento não encontrado ou já revisado."}

        statement_id = tx_row["statement_id"]
        self._verify_statement_ownership(statement_id)

        old_row = self.conn.execute(
            """
            SELECT id, amount, description, category, method, expense_date,
                   hash, card_last_four, card_holder, statement_id
            FROM expenses
            WHERE id = ? AND user_id = ? AND deleted_at IS NULL
            """,
            (expense_id, self.user_id),
        ).fetchone()
        if not old_row:
            return {"error": "Despesa não encontrada."}

        old_data = dict(old_row)
        new_date = tx_row["transaction_date"]
        new_desc = tx_row["description"]
        new_amount = tx_row["amount_cents"] / 100
        new_hash = compute_hash(new_amount, new_desc, date.fromisoformat(new_date))

        self.conn.execute(
            """
            UPDATE expenses
            SET expense_date = ?, description = ?, hash = ?,
                card_last_four = ?, card_holder = ?, statement_id = ?
            WHERE id = ?
            """,
            (
                new_date,
                new_desc,
                new_hash,
                tx_row["card_last_four"],
                tx_row["card_holder"],
                statement_id,
                expense_id,
            ),
        )

        new_row = self.conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        log_audit(self.conn, "update", expense_id, old_data, dict(new_row), user_id=self.user_id)

        self.conn.execute(
            """
            UPDATE statement_transactions
            SET status = 'approved', matched_expense_id = ?, reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (expense_id, tx_id),
        )

        self._update_statement_status(statement_id)
        self.conn.commit()

        return {"success": True, "expense_id": expense_id}

    def approve_review(self, expense_id: int, statement_id: int) -> dict:
        """Aprova a revisão de uma despesa 'só no banco' sem duplicar.

        Registra que a despesa foi revisada, mas não a altera.
        """
        self._verify_statement_ownership(statement_id)

        row = self.conn.execute(
            "SELECT id FROM expenses WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
            (expense_id, self.user_id),
        ).fetchone()
        if not row:
            return {"error": "Despesa não encontrada."}

        # Registra revisão sem alterar a despesa
        self.conn.execute(
            """
            UPDATE expenses SET statement_id = ? WHERE id = ?
            """,
            (statement_id, expense_id),
        )

        self._update_statement_status(statement_id)
        self.conn.commit()

        return {"success": True, "expense_id": expense_id}

    def reject(self, tx_id: int) -> dict:
        """Rejeita um lançamento da fatura (não insere)."""
        tx_row = self.conn.execute(
            "SELECT statement_id FROM statement_transactions WHERE id = ? AND status = 'pending'",
            (tx_id,),
        ).fetchone()
        if not tx_row:
            return {"error": "Lançamento não encontrado ou já revisado."}

        self._verify_statement_ownership(tx_row["statement_id"])

        self.conn.execute(
            """
            UPDATE statement_transactions
            SET status = 'rejected', reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (tx_id,),
        )

        self._update_statement_status(tx_row["statement_id"])
        self.conn.commit()

        return {"success": True}

    def update_category(self, tx_id: int, category: str) -> dict:
        """Atualiza a categoria sugerida/selecionada de um lançamento."""
        if not self._category_exists(category):
            return {"error": f"Categoria inválida: {category}"}

        tx_row = self.conn.execute(
            "SELECT statement_id FROM statement_transactions WHERE id = ?",
            (tx_id,),
        ).fetchone()
        if not tx_row:
            return {"error": "Lançamento não encontrado."}

        self._verify_statement_ownership(tx_row["statement_id"])

        self.conn.execute(
            "UPDATE statement_transactions SET selected_category = ? WHERE id = ?",
            (category, tx_id),
        )
        self.conn.commit()

        return {"success": True}

    def get_pending_summary(self) -> dict:
        """Retorna resumo de conciliações pendentes para o usuário."""
        row = self.conn.execute(
            """
            SELECT cs.id, cs.file_name, cs.due_date, cs.card_last_four,
                   COUNT(st.id) AS pending_count
            FROM card_statements cs
            LEFT JOIN statement_transactions st
              ON st.statement_id = cs.id AND st.status IN ('pending', 'matched')
            WHERE cs.user_id = ? AND cs.status = 'pending'
            GROUP BY cs.id
            ORDER BY cs.created_at DESC
            LIMIT 1
            """,
            (self.user_id,),
        ).fetchone()

        if not row or row["pending_count"] == 0:
            return {"has_pending": False}

        return {
            "has_pending": True,
            "statement_id": row["id"],
            "file_name": row["file_name"],
            "due_date": row["due_date"],
            "card_last_four": row["card_last_four"],
            "pending_count": row["pending_count"],
        }

    def list_statements(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT id, file_name, statement_date, due_date, total_cents,
                   card_last_four, card_holder, status, created_at
            FROM card_statements
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (self.user_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _verify_statement_ownership(self, statement_id: int) -> None:
        row = self.conn.execute(
            "SELECT 1 FROM card_statements WHERE id = ? AND user_id = ?",
            (statement_id, self.user_id),
        ).fetchone()
        if not row:
            raise ValueError("Fatura não encontrada ou não pertence ao usuário.")

    def _update_statement_status(self, statement_id: int) -> None:
        """Atualiza status da fatura para 'confirmed' quando não houver pendentes."""
        pending = self.conn.execute(
            """
            SELECT COUNT(*) FROM statement_transactions
            WHERE statement_id = ? AND status IN ('pending', 'matched')
            """,
            (statement_id,),
        ).fetchone()[0]

        if pending == 0:
            self.conn.execute(
                "UPDATE card_statements SET status = 'confirmed' WHERE id = ?",
                (statement_id,),
            )

    def confirm_reconciliation(
        self,
        statement_id: int,
        insert_ids: list[int],
        update_pairs: list[tuple[int, int]],
        delete_ids: list[int],
        default_category: str = "Outros",
    ) -> dict:
        """Método legado de confirmação em lote. Mantido para compatibilidade
        com testes e scripts antigos. Na V1.1 prefira approve_insert etc."""
        if not self._category_exists(default_category):
            raise ValueError(f"Categoria padrão inválida: {default_category}")

        self._verify_statement_ownership(statement_id)

        inserted = 0
        updated = 0
        deleted = 0
        errors: list[str] = []

        for tx_id in insert_ids:
            res = self.approve_insert(tx_id, default_category)
            if res.get("success"):
                inserted += 1
            else:
                errors.append(res.get("error", f"Erro ao inserir {tx_id}"))

        for tx_id, expense_id in update_pairs:
            res = self.approve_match(tx_id, expense_id)
            if res.get("success"):
                updated += 1
            else:
                errors.append(res.get("error", f"Erro ao atualizar {expense_id}"))

        for expense_id in delete_ids:
            old_data = soft_delete(self.conn, "expenses", expense_id, self.user_id)
            if old_data is None:
                errors.append(f"Despesa {expense_id} não encontrada.")
                continue
            log_audit(self.conn, "delete", expense_id, old_data, user_id=self.user_id)
            deleted += 1

        self._update_statement_status(statement_id)
        self.conn.commit()

        return {
            "status": "confirmed",
            "inserted": inserted,
            "updated": updated,
            "deleted": deleted,
            "errors": errors,
        }

    def _category_exists(self, name: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM categories WHERE LOWER(name) = LOWER(?) AND (user_id IS NULL OR user_id = ?)",
            (name, self.user_id),
        ).fetchone()
        return row is not None
