"""Serviço de importação e conciliação de faturas de cartão.

Este módulo integra o parser de fatura Bradesco com o banco de dados do
Finanças IA, oferecendo:

- Persistência da fatura e transações extraídas.
- Motor de conciliação 1:1 com tolerância de ±2 dias no valor exato.
- Três seções de revisão: só na fatura, na fatura e no banco, só no banco.
- Confirmação transacional com idempotência e audit log.

Observação importante sobre o vínculo de cartão/titular:
A tabela expenses passou a ter os campos card_last_four e card_holder na
migration 0011, mas despesas cadastradas antes da V1 via Telegram podem não
ter esses valores preenchidos. Portanto, o conjunto elegível do banco usa
method = 'crédito' + user_id + período. O usuário deve revisar as sugestões
quando o vínculo não puder ser determinado com segurança.
"""
import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from services._base import compute_hash, log_audit, soft_delete
from services.statement_parser import (
    ParsedStatement,
    ParsedTransaction,
    filter_transactions_by_holder,
    parse_bradesco_statement,
)


CREDIT_CARD_METHODS = {"crédito", "credito"}


@dataclass
class CandidateMatch:
    statement_tx: ParsedTransaction
    expense: dict
    date_diff: int


@dataclass
class ReconciliationResult:
    only_on_statement: list[ParsedTransaction] = field(default_factory=list)
    matched: list[CandidateMatch] = field(default_factory=list)
    ambiguous: list[tuple[ParsedTransaction, list[dict]]] = field(default_factory=list)
    only_on_database: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class StatementService:
    """Service de importação/conciliação de faturas de cartão."""

    def __init__(self, conn: sqlite3.Connection, user_id: int):
        self.conn = conn
        self.user_id = user_id

    def import_statement(
        self,
        pdf_path: Path | str,
        card_last_four: Optional[str] = None,
        card_holder: Optional[str] = None,
    ) -> tuple[int, ParsedStatement]:
        """Parseia o PDF, persiste metadados e transações e retorna statement_id.

        Se o mesmo arquivo (mesmo hash) já tiver sido importado para o mesmo
        cartão, retorna o statement_id existente (idempotência).
        """
        pdf_path = Path(pdf_path)
        statement = parse_bradesco_statement(pdf_path)

        # Seleciona cartão/titular padrão quando não informado
        if not card_last_four and statement.card_holders:
            card_last_four = statement.card_holders[0].last_four
        if not card_holder and statement.card_holders:
            for h in statement.card_holders:
                if h.last_four == card_last_four:
                    card_holder = h.name
                    break

        file_hash = statement.file_hash
        existing = self.conn.execute(
            "SELECT id, status FROM card_statements WHERE file_hash = ? AND card_last_four = ?",
            (file_hash, card_last_four),
        ).fetchone()
        if existing:
            statement_id = existing["id"]
            # Sobrescreve transações pendentes para permitir reprocessamento
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
                    card_last_four,
                    card_holder,
                ),
            )
            statement_id = cursor.lastrowid

        for tx in statement.transactions:
            self.conn.execute(
                """
                INSERT INTO statement_transactions (
                    statement_id, card_holder, card_last_four, transaction_date,
                    description, amount_cents, installment_info, raw_line
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )

        self.conn.commit()
        return statement_id, statement

    def _eligible_expenses(
        self,
        start_date: date,
        end_date: date,
        method: str = "crédito",
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

    def reconcile(
        self,
        statement_id: int,
        card_last_four: Optional[str] = None,
        card_holder: Optional[str] = None,
    ) -> ReconciliationResult:
        """Executa o motor de conciliação e retorna as três seções.

        Regras:
        - Valor exato em centavos.
        - Diferença de datas <= 2 dias (inclusive).
        - Matching estritamente 1:1.
        - Despesas do banco elegíveis: method = 'crédito', mesmo user_id, no
          período da fatura.
        """
        result = ReconciliationResult()

        statement_row = self.conn.execute(
            "SELECT statement_date, due_date FROM card_statements WHERE id = ? AND user_id = ?",
            (statement_id, self.user_id),
        ).fetchone()
        if not statement_row:
            raise ValueError("Fatura não encontrada ou não pertence ao usuário.")

        due_date = date.fromisoformat(statement_row["due_date"])
        # Período elegível: até 50 dias antes do vencimento cobre ciclos de
        # fatura do Bradesco (cerca de 30-40 dias).
        start_date = due_date - timedelta(days=50)
        end_date = due_date

        rows = self.conn.execute(
            """
            SELECT id, card_holder, card_last_four, transaction_date,
                   description, amount_cents, installment_info, raw_line
            FROM statement_transactions
            WHERE statement_id = ?
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

        # Filtra titular/cartão selecionado e descarta créditos/pagamentos
        selected_txs = [
            tx
            for tx in statement_txs
            if (
                not tx.is_credit
                and (not card_last_four or tx.card_last_four == card_last_four)
                and (not card_holder or not tx.card_holder or tx.card_holder == card_holder)
            )
        ]

        # Lançamentos ambíguos (sem titular/cartão identificado) são sinalizados
        ambiguous_txs = [tx for tx in statement_txs if tx.ambiguous and not tx.is_credit]
        if ambiguous_txs:
            result.warnings.append(
                f"{len(ambiguous_txs)} lançamento(s) da fatura não puderam ser "
                "associados a um titular/cartão e foram sinalizados para revisão."
            )

        eligible_expenses = self._eligible_expenses(start_date, end_date)

        # Motor de matching 1:1
        matched_pairs: list[CandidateMatch] = []
        used_expense_ids: set[int] = set()
        only_on_statement: list[ParsedTransaction] = []

        for tx in selected_txs:
            candidates: list[tuple[int, dict]] = []
            for exp in eligible_expenses:
                exp_id = exp["id"]
                if exp_id in used_expense_ids:
                    continue
                # Valor exato em centavos
                exp_cents = int(round(exp["amount"] * 100))
                if exp_cents != tx.amount_cents:
                    continue
                # Data ±2 dias
                exp_date = date.fromisoformat(exp["expense_date"])
                diff = abs((tx.transaction_date - exp_date).days)
                if diff <= 2:
                    candidates.append((diff, exp))

            if not candidates:
                only_on_statement.append(tx)
                continue

            if len(candidates) == 1:
                diff, exp = candidates[0]
                used_expense_ids.add(exp["id"])
                matched_pairs.append(CandidateMatch(tx, exp, diff))
            else:
                # Ambiguidade: múltiplos candidatos. Não associa automaticamente.
                # Ordena por proximidade de data e apresenta todos.
                candidates.sort(key=lambda x: x[0])
                result.ambiguous.append((tx, [c[1] for c in candidates]))

        only_on_database = [
            exp for exp in eligible_expenses if exp["id"] not in used_expense_ids
        ]

        result.only_on_statement = only_on_statement
        result.matched = matched_pairs
        result.only_on_database = only_on_database
        return result

    def confirm_reconciliation(
        self,
        statement_id: int,
        insert_ids: list[int],
        update_pairs: list[tuple[int, int]],
        delete_ids: list[int],
        default_category: str = "Outros",
    ) -> dict:
        """Persiste as ações aprovadas na conciliação em uma única transação.

        Args:
            statement_id: ID da fatura.
            insert_ids: IDs de statement_transactions a inserir como despesas.
            update_pairs: lista de (statement_transaction_id, expense_id) para
                atualizar a despesa existente com data/descrição da fatura.
            delete_ids: IDs de expenses a excluir (soft delete).
            default_category: categoria padrão para novas despesas.

        Returns:
            Resumo da operação.
        """
        if not self._category_exists(default_category):
            raise ValueError(f"Categoria padrão inválida: {default_category}")

        statement_row = self.conn.execute(
            "SELECT due_date, card_last_four, card_holder FROM card_statements WHERE id = ? AND user_id = ?",
            (statement_id, self.user_id),
        ).fetchone()
        if not statement_row:
            raise ValueError("Fatura não encontrada ou não pertence ao usuário.")

        # Verifica se a fatura já foi confirmada para evitar duplicatas
        status_row = self.conn.execute(
            "SELECT status FROM card_statements WHERE id = ?", (statement_id,)
        ).fetchone()
        if status_row and status_row["status"] == "confirmed":
            # Permite reconfirmação apenas se não houver nada a fazer
            if not insert_ids and not update_pairs and not delete_ids:
                return {
                    "status": "already_confirmed",
                    "inserted": 0,
                    "updated": 0,
                    "deleted": 0,
                    "errors": [],
                }

        cursor = self.conn.cursor()
        inserted = 0
        updated = 0
        deleted = 0
        errors: list[str] = []

        try:
            # Inserções
            for tx_id in insert_ids:
                tx_row = cursor.execute(
                    """
                    SELECT transaction_date, description, amount_cents,
                           installment_info, card_last_four, card_holder
                    FROM statement_transactions
                    WHERE id = ? AND statement_id = ?
                    """,
                    (tx_id, statement_id),
                ).fetchone()
                if not tx_row:
                    errors.append(f"Lançamento {tx_id} não encontrado.")
                    continue

                amount = tx_row["amount_cents"] / 100
                desc = tx_row["description"]
                tx_date = tx_row["transaction_date"]
                expense_hash = compute_hash(amount, desc, date.fromisoformat(tx_date))

                cursor.execute(
                    """
                    INSERT INTO expenses (
                        user_id, amount, description, category, method,
                        expense_date, hash, card_last_four, card_holder, statement_id
                    ) VALUES (?, ?, ?, ?, 'crédito', ?, ?, ?, ?, ?)
                    """,
                    (
                        self.user_id,
                        amount,
                        desc,
                        default_category,
                        tx_date,
                        expense_hash,
                        tx_row["card_last_four"] or statement_row["card_last_four"],
                        tx_row["card_holder"] or statement_row["card_holder"],
                        statement_id,
                    ),
                )
                inserted += 1

            # Atualizações
            for tx_id, expense_id in update_pairs:
                tx_row = cursor.execute(
                    """
                    SELECT transaction_date, description, amount_cents,
                           card_last_four, card_holder
                    FROM statement_transactions
                    WHERE id = ? AND statement_id = ?
                    """,
                    (tx_id, statement_id),
                ).fetchone()
                if not tx_row:
                    errors.append(f"Lançamento {tx_id} não encontrado.")
                    continue

                old_row = cursor.execute(
                    """
                    SELECT id, amount, description, category, method, expense_date,
                           hash, card_last_four, card_holder, statement_id
                    FROM expenses
                    WHERE id = ? AND user_id = ? AND deleted_at IS NULL
                    """,
                    (expense_id, self.user_id),
                ).fetchone()
                if not old_row:
                    errors.append(f"Despesa {expense_id} não encontrada.")
                    continue

                old_data = dict(old_row)
                new_date = tx_row["transaction_date"]
                new_desc = tx_row["description"]
                new_amount = tx_row["amount_cents"] / 100
                new_hash = compute_hash(new_amount, new_desc, date.fromisoformat(new_date))
                new_card_last_four = tx_row["card_last_four"] or statement_row["card_last_four"]
                new_card_holder = tx_row["card_holder"] or statement_row["card_holder"]

                cursor.execute(
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
                        new_card_last_four,
                        new_card_holder,
                        statement_id,
                        expense_id,
                    ),
                )

                new_row = cursor.execute(
                    "SELECT * FROM expenses WHERE id = ?", (expense_id,)
                ).fetchone()
                log_audit(self.conn, "update", expense_id, old_data, dict(new_row), user_id=self.user_id)
                updated += 1

            # Exclusões (soft delete)
            for expense_id in delete_ids:
                old_data = soft_delete(self.conn, "expenses", expense_id, self.user_id)
                if old_data is None:
                    errors.append(f"Despesa {expense_id} não encontrada ou já excluída.")
                    continue
                log_audit(self.conn, "delete", expense_id, old_data, user_id=self.user_id)
                deleted += 1

            # Marca fatura como confirmada
            cursor.execute(
                "UPDATE card_statements SET status = 'confirmed' WHERE id = ?",
                (statement_id,),
            )

            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise

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
