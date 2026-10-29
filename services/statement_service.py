"""Importacao e revisao persistente de faturas, sem alterar despesas conciliadas."""
import json
import re
import sqlite3
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from threading import Lock, RLock
from typing import Optional
from uuid import uuid4
from weakref import WeakValueDictionary

from services._base import compute_hash, log_audit, soft_delete
from services.category_suggester import CategorySuggester
from services.statement_parser import ParsedStatement, ParsedTransaction, parse_bradesco_statement


CREDIT_CARD_METHOD = "crédito"
_CONNECTION_LOCKS = WeakValueDictionary()
_CONNECTION_LOCKS_GUARD = Lock()


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
    """Mantem decisoes, drafts e vinculos separados dos dados originais."""

    def __init__(self, conn: sqlite3.Connection, user_id: int):
        self.conn = conn
        self.user_id = user_id
        self._suggester = CategorySuggester(conn, user_id)
        # O registro deixa de reter a conexao quando seus services sao liberados.
        with _CONNECTION_LOCKS_GUARD:
            self._lock = _CONNECTION_LOCKS.setdefault(conn, RLock())

    @contextmanager
    def _transaction(self):
        # BEGIN IMMEDIATE serializa leitura do estado e escrita entre conexoes.
        with self._lock:
            nested = self.conn.in_transaction
            self.conn.execute("SAVEPOINT statement_review" if nested else "BEGIN IMMEDIATE")
            try:
                yield
                if nested:
                    self.conn.execute("RELEASE SAVEPOINT statement_review")
                else:
                    self.conn.commit()
            except BaseException:
                if nested:
                    self.conn.execute("ROLLBACK TO SAVEPOINT statement_review")
                    self.conn.execute("RELEASE SAVEPOINT statement_review")
                else:
                    self.conn.rollback()
                raise

    @staticmethod
    def _cents(amount) -> int:
        return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @staticmethod
    def _installment_reference_date(due_date: date, current: int, parcel: int) -> date:
        """Primeiro dia do mês de referência de uma parcela.

        O mês de referência da fatura é o mês anterior ao vencimento.
        A parcela corrente (current) cai nesse mês; parcelas posteriores
        avançam mês a mês.
        """
        if due_date.month == 1:
            base = date(due_date.year - 1, 12, 1)
        else:
            base = date(due_date.year, due_date.month - 1, 1)
        months = parcel - current
        year = base.year + (base.month - 1 + months) // 12
        month = (base.month - 1 + months) % 12 + 1
        return date(year, month, 1)

    def _category(self, category: str) -> Optional[str]:
        if not isinstance(category, str):
            raise ValueError("Categoria inválida: informe uma categoria cadastrada.")
        clean = category.strip()
        if not clean:
            return None
        rows = self.conn.execute(
            "SELECT name FROM categories WHERE user_id IS NULL OR user_id = ? ORDER BY id",
            (self.user_id,),
        ).fetchall()
        for row in rows:
            if row["name"].casefold() == clean.casefold():
                return row["name"]
        raise ValueError(f"Categoria inválida: {clean}")

    def _verify_statement_ownership(self, statement_id: int):
        if type(statement_id) is not int or statement_id <= 0:
            raise ValueError("Fatura não encontrada ou não pertence ao usuário.")
        row = self.conn.execute(
            "SELECT * FROM card_statements WHERE id = ? AND user_id = ?",
            (statement_id, self.user_id),
        ).fetchone()
        if not row:
            raise ValueError("Fatura não encontrada ou não pertence ao usuário.")
        return row

    @staticmethod
    def _snapshot(tx=None, expense=None) -> dict:
        bank = expense is not None
        return {
            "id": f"tx:{tx['id']}" if tx is not None else f"expense:{expense['id']}",
            "section": "new" if tx is not None else "bank",
            "tx_id": tx["id"] if tx is not None else None,
            "expense_id": expense["id"] if bank else None,
            "name": tx["description"] if tx is not None else expense["description"],
            "date": str(tx["transaction_date"] if tx is not None else expense["expense_date"]),
            "amount_cents": tx["amount_cents"] if tx is not None else StatementService._cents(expense["amount"]),
            "category": tx["selected_category"] if tx is not None else expense["category"],
            "card_last_four": tx["card_last_four"] if tx is not None else expense["card_last_four"],
            "installment_info": tx["installment_info"] if tx is not None else None,
            "installment_current": tx["installment_current"] if tx is not None and "installment_current" in tx.keys() else None,
            "installment_total": tx["installment_total"] if tx is not None and "installment_total" in tx.keys() else None,
            "original_purchase_date": str(tx["original_purchase_date"]) if tx is not None and "original_purchase_date" in tx.keys() and tx["original_purchase_date"] else None,
            "bank_name": expense["description"] if bank else None,
            "bank_date": str(expense["expense_date"]) if bank else None,
            "bank_amount_cents": StatementService._cents(expense["amount"]) if bank else None,
            "bank_category": expense["category"] if bank else None,
        }

    def import_statement(
        self,
        pdf_path: Path | str,
        selected_cards: Optional[list[str]] = None,
    ) -> tuple[int, ParsedStatement, list[str]]:
        """Reimporta os mesmos bytes sem substituir transacoes nem decisoes."""
        statement = parse_bradesco_statement(Path(pdf_path))
        all_cards = sorted({tx.card_last_four for tx in statement.transactions if tx.card_last_four}
                           | {holder.last_four for holder in statement.card_holders if holder.last_four})
        if selected_cards is None:
            cards = all_cards
        else:
            if not isinstance(selected_cards, list) or not selected_cards:
                raise ValueError("Selecione ao menos um cartão identificado na fatura.")
            if any(not isinstance(card, str) or not re.fullmatch(r"[0-9]{4}", card)
                   or card not in all_cards for card in selected_cards):
                raise ValueError("Cartão selecionado inválido ou não identificado na fatura.")
            if len(set(selected_cards)) != len(selected_cards):
                raise ValueError("Há cartões duplicados na seleção.")
            cards = sorted(selected_cards)

        with self._transaction():
            imports = self.conn.execute(
                "SELECT * FROM card_statements WHERE user_id = ? AND file_hash = ? ORDER BY id",
                (self.user_id, statement.file_hash),
            ).fetchall()
            existing = next((row for row in imports
                             if set((row["card_last_four"] or "").split(",")) - {""} == set(cards)),
                            imports[0] if imports else None)
            if existing:
                statement_id = existing["id"]
                saved_cards = set((existing["card_last_four"] or "").split(",")) - {""}
                saved_cards.update(cards)
                self.conn.execute(
                    "UPDATE card_statements SET card_last_four = ? WHERE id = ?",
                    (",".join(sorted(saved_cards)) or None, statement_id),
                )
                if len(imports) > 1:
                    warnings = json.loads(existing["review_warnings"])
                    warnings.append("Este arquivo tem importações legadas separadas; confira também as outras conciliações do arquivo.")
                    self.conn.execute("UPDATE card_statements SET review_warnings = ? WHERE id = ?",
                                      (json.dumps(list(dict.fromkeys(warnings)), ensure_ascii=False), statement_id))
            else:
                cursor = self.conn.execute(
                    """
                    INSERT INTO card_statements (
                        user_id, file_hash, file_name, statement_date, due_date,
                        total_cents, card_last_four, card_holder, review_warnings
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.user_id, statement.file_hash, statement.file_name,
                        statement.statement_date.isoformat() if statement.statement_date else None,
                        statement.due_date.isoformat() if statement.due_date else None,
                        statement.total_cents, ",".join(cards) or None, statement.holder_name,
                        json.dumps(statement.warnings, ensure_ascii=False),
                    ),
                )
                statement_id = cursor.lastrowid

            # Uma ocorrencia por linha, incluindo compras identicas repetidas.
            saved_by_statement = Counter(
                (row["statement_id"], row["card_last_four"], row["transaction_date"], row["description"],
                 row["amount_cents"], row["installment_info"], row["raw_line"] or "")
                for row in self.conn.execute(
                    """SELECT st.* FROM statement_transactions st JOIN card_statements cs ON cs.id = st.statement_id
                       WHERE cs.user_id = ? AND cs.file_hash = ?""", (self.user_id, statement.file_hash)
                ).fetchall()
            )
            identified = Counter(
                (tx.card_last_four, tx.transaction_date.isoformat(), tx.description,
                 tx.amount_cents, tx.installment_info, tx.raw_line or "")
                for tx in statement.transactions if tx.card_last_four and not tx.is_credit
            )
            saved, unknown_saved = Counter(), Counter()
            for origin, count in saved_by_statement.items():
                key = origin[1:]
                saved[key] += count
                # Desconta linhas comprovadas em cada importacao antes de reconhecer inferencias legadas.
                unknown_saved[key[1:]] += count if not key[0] else max(0, count - identified[key])
            occurrences = Counter()
            for tx in statement.transactions:
                if tx.is_credit or (tx.card_last_four and tx.card_last_four not in cards):
                    continue
                key = (tx.card_last_four, tx.transaction_date.isoformat(), tx.description,
                       tx.amount_cents, tx.installment_info, tx.raw_line or "")
                occurrences[key] += 1
                saved_count = saved[key] if tx.card_last_four else unknown_saved[key[1:]]
                if occurrences[key] <= saved_count:
                    continue
                suggested = self._suggester.suggest_from_history(tx.description)
                try:
                    suggested = self._category(suggested) if suggested else None
                except ValueError:
                    suggested = None
                self.conn.execute(
                    """
                    INSERT INTO statement_transactions (
                        statement_id, card_holder, card_last_four, transaction_date,
                        description, amount_cents, installment_info, installment_current,
                        installment_total, original_purchase_date, raw_line, selected_category
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (statement_id, tx.card_holder, tx.card_last_four, tx.transaction_date.isoformat(),
                     tx.description, tx.amount_cents, tx.installment_info, tx.installment_current,
                     tx.installment_total,
                     tx.original_purchase_date.isoformat() if tx.original_purchase_date else None,
                     tx.raw_line, suggested),
                )
            self._materialize(statement_id)
        return statement_id, statement, cards

    def _eligible_expenses(self, start_date: date, end_date: date,
                           method: str = CREDIT_CARD_METHOD) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT * FROM expenses
            WHERE user_id = ? AND method = ? AND deleted_at IS NULL
              AND expense_date BETWEEN ? AND ?
            ORDER BY expense_date, id
            """,
            (self.user_id, method, start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
        return [dict(row) for row in rows]

    def _match_snapshot(self, tx, expense):
        """So um audit de match inequivoco permite recuperar o texto sobrescrito."""
        expense_id = expense["id"] if expense else tx["matched_expense_id"]
        warning = None
        original = dict(expense) if expense else None
        recovered, audits = [], []
        if tx["status"] == "approved" or (expense and expense["statement_id"] == tx["statement_id"]):
            audits = self.conn.execute(
                """SELECT old_data, new_data FROM audit_log WHERE expense_id = ?
                   AND operation = 'update' AND (user_id = ? OR user_id IS NULL)""",
                (expense_id, self.user_id),
            ).fetchall()
            for audit in audits:
                try:
                    old, new = json.loads(audit["old_data"]), json.loads(audit["new_data"] or "null")
                    if (isinstance(old, dict) and isinstance(new, dict)
                            and old.get("id") == new.get("id") == expense_id
                            and new.get("user_id") == self.user_id
                            and old.get("user_id", self.user_id) == self.user_id
                            and "statement_id" in old and old["statement_id"] != tx["statement_id"]
                            and new.get("statement_id") == tx["statement_id"]
                            and new.get("description") == tx["description"]
                            and new.get("expense_date") == tx["transaction_date"]
                            and self._cents(new["amount"]) == tx["amount_cents"]
                            and isinstance(old.get("description"), str)
                            and all(key in old for key in ("expense_date", "amount", "category"))):
                        recovered.append((old, new))
                except (ValueError, TypeError, KeyError, ArithmeticError):
                    continue
            original = recovered[0][0] if len(recovered) == 1 else None
            if original is None:
                warning = f"Descrição original da despesa {expense_id} indisponível no histórico legado."
        snapshot = self._snapshot(tx, original)
        snapshot.update(section="matched", expense_id=expense_id)
        if tx["status"] == "approved":
            category = None
            applied = [new.get("category") for _, new in recovered]
            if applied and isinstance(applied[0], str) and all(value == applied[0] for value in applied):
                category = applied[0]
            elif (not audits and expense and expense["statement_id"] == tx["statement_id"]
                  and expense["description"] == tx["description"]
                  and expense["expense_date"] == tx["transaction_date"]
                  and self._cents(expense["amount"]) == tx["amount_cents"]):
                category = expense["category"]
            try:
                snapshot["category"] = self._category(category) if isinstance(category, str) else None
            except ValueError:
                snapshot["category"] = None
            if snapshot["category"] is None:
                warning = " ".join(filter(None, [warning, f"Categoria efetiva da despesa {expense_id} indisponível no histórico legado."]))
        return snapshot, warning

    def _legacy_item(self, tx):
        decision = {"approved": "approved", "inserted": "approved",
                    "ignored": "ignored", "rejected": "ignored"}.get(tx["status"], "pending")
        expense = self.conn.execute(
            "SELECT * FROM expenses WHERE id = ? AND user_id = ?",
            (tx["matched_expense_id"], self.user_id),
        ).fetchone()
        section = "new" if tx["status"] == "inserted" else (
            "matched" if tx["matched_expense_id"] or tx["status"] in ("approved", "matched") else "new"
        )
        snapshot, warning = self._match_snapshot(tx, expense) if section == "matched" else (self._snapshot(tx), None)
        snapshot["section"] = section
        snapshot["expense_id"] = tx["matched_expense_id"]
        claim = tx["matched_expense_id"] if decision == "approved" and expense else None
        if claim and self.conn.execute(
            "SELECT 1 FROM statement_review_items WHERE claimed_expense_id = ?", (claim,)
        ).fetchone():
            warning = " ".join(filter(None, [warning, f"Vínculo legado duplicado para a despesa {claim}; requer conferência."]))
            claim = None
        self.conn.execute(
            """
            INSERT INTO statement_review_items (
                statement_id, item_id, tx_id, expense_id, claimed_expense_id, section,
                decision, category, snapshot, warning, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tx["statement_id"], snapshot["id"], tx["id"], tx["matched_expense_id"], claim,
             section, decision, snapshot["category"], json.dumps(snapshot, ensure_ascii=False),
             warning, tx["reviewed_at"]),
        )

    def _materialize(self, statement_id: int):
        statement = self._verify_statement_ownership(statement_id)
        txs = self.conn.execute(
            "SELECT * FROM statement_transactions WHERE statement_id = ? ORDER BY transaction_date, id",
            (statement_id,),
        ).fetchall()
        reviews = {row["tx_id"]: row for row in self.conn.execute(
            "SELECT * FROM statement_review_items WHERE statement_id = ? AND tx_id IS NOT NULL",
            (statement_id,),
        ).fetchall()}
        for tx in txs:
            if tx["id"] not in reviews:
                self._legacy_item(tx)
        reviews = {row["tx_id"]: row for row in self.conn.execute(
            "SELECT * FROM statement_review_items WHERE statement_id = ? AND tx_id IS NOT NULL",
            (statement_id,),
        ).fetchall()}
        pending = [tx for tx in txs if reviews[tx["id"]]["decision"] == "pending"]
        anchor = statement["due_date"] or statement["statement_date"]
        dates = [date.fromisoformat(tx["transaction_date"]) for tx in txs]
        expenses = []
        if anchor or dates:
            end = date.fromisoformat(anchor) if anchor else max(dates)
            start = end - timedelta(days=50)
            if dates:
                start = min(start, min(dates) - timedelta(days=2))
                end = max(end, max(dates) + timedelta(days=2))
            expenses = self._eligible_expenses(start, end)

        self.conn.execute(
            """UPDATE statement_review_items SET claimed_expense_id = NULL
               WHERE statement_id = ? AND decision = 'pending' AND tx_id IS NOT NULL""",
            (statement_id,),
        )
        occupied = {row[0] for row in self.conn.execute(
            "SELECT claimed_expense_id FROM statement_review_items WHERE claimed_expense_id IS NOT NULL"
        ).fetchall()}
        occupied.update(row[0] for row in self.conn.execute(
            """SELECT st.matched_expense_id FROM statement_transactions st
               JOIN card_statements cs ON cs.id = st.statement_id
               WHERE cs.user_id = ? AND st.status IN ('approved', 'inserted')
                 AND st.matched_expense_id IS NOT NULL""", (self.user_id,)
        ).fetchall())
        occupied.update(row[0] for row in self.conn.execute(
            """SELECT expense_id FROM statement_review_items
               WHERE statement_id = ? AND decision != 'pending' AND expense_id IS NOT NULL
                 AND tx_id IS NOT NULL""",
            (statement_id,),
        ).fetchall())
        cards = set((statement["card_last_four"] or "").split(",")) - {""}
        expenses = [exp for exp in expenses if exp["id"] not in occupied
                    and exp["statement_id"] in (None, statement_id)
                    and (not cards or not exp["card_last_four"] or exp["card_last_four"] in cards)]
        candidates = {}
        for tx in pending:
            tx_date = date.fromisoformat(tx["transaction_date"])
            candidates[tx["id"]] = [exp for exp in expenses
                if self._cents(exp["amount"]) == tx["amount_cents"]
                and abs((date.fromisoformat(exp["expense_date"]) - tx_date).days) <= 2
                and (not tx["card_last_four"] or not exp["card_last_four"]
                     or tx["card_last_four"] == exp["card_last_four"])]
        frequency = Counter(exp["id"] for matches in candidates.values() for exp in matches)
        for tx in pending:
            matches = candidates[tx["id"]]
            chosen = matches[0] if len(matches) == 1 and frequency[matches[0]["id"]] == 1 else None
            snapshot, warning = self._match_snapshot(tx, chosen) if chosen else (self._snapshot(tx), None)
            snapshot["section"] = "matched" if matches else "new"
            if matches and chosen is None:
                snapshot["ambiguous"] = True
                snapshot["candidates"] = [
                    {"expense_id": exp["id"], "name": exp["description"], "date": str(exp["expense_date"]),
                     "amount_cents": self._cents(exp["amount"]), "category": exp["category"]}
                    for exp in matches
                ]
                warning = " ".join(filter(None, (self._match_snapshot(tx, exp)[1] for exp in matches))) or None
            review = reviews[tx["id"]]
            category = review["category"]
            if category is None and not review["category_edited"] and chosen:
                category = chosen["category"]
            snapshot["category"] = category
            self.conn.execute(
                """UPDATE statement_review_items
                   SET section = ?, expense_id = ?, claimed_expense_id = ?, snapshot = ?, category = ?, warning = ?
                   WHERE statement_id = ? AND item_id = ?""",
                (snapshot["section"], snapshot["expense_id"], snapshot["expense_id"],
                 json.dumps(snapshot, ensure_ascii=False), category, warning, statement_id, snapshot["id"]),
            )

        self.conn.execute(
            "UPDATE statement_review_items SET active = 0 WHERE statement_id = ? AND section = 'bank' AND decision = 'pending'",
            (statement_id,),
        )
        for expense in expenses:
            if expense["id"] in frequency:
                continue
            snapshot = self._snapshot(expense=expense)
            self.conn.execute(
                """
                INSERT INTO statement_review_items (statement_id, item_id, expense_id, section, category, snapshot, warning)
                VALUES (?, ?, ?, 'bank', ?, ?, ?)
                ON CONFLICT(statement_id, item_id) DO UPDATE SET
                    active = 1, snapshot = excluded.snapshot
                WHERE statement_review_items.decision = 'pending'
                """,
                (statement_id, snapshot["id"], expense["id"], expense["category"],
                 json.dumps(snapshot, ensure_ascii=False),
                 "Revisão legada sem decisão comprovada; confirme ou ignore a despesa."
                 if expense["statement_id"] == statement_id else None),
            )
        self._update_statement_status(statement_id)
        return statement

    def _state(self, statement_id: int) -> dict:
        statement = self._verify_statement_ownership(statement_id)
        items, history = [], []
        warnings = json.loads(statement["review_warnings"])
        for row in self.conn.execute(
            "SELECT * FROM statement_review_items WHERE statement_id = ? ORDER BY item_id", (statement_id,)
        ).fetchall():
            if row["decision"] == "pending" and not row["active"]:
                continue
            item = json.loads(row["snapshot"])
            item.update(section=row["section"], expense_id=row["expense_id"], category=row["category"])
            if row["warning"]:
                warnings.append(row["warning"])
            if row["decision"] == "pending":
                item["category_edited"] = bool(row["category_edited"])
                items.append(item)
            else:
                item.update(decision=row["decision"], reviewed_at=row["reviewed_at"])
                history.append(item)
        items.sort(key=lambda item: ({"new": 0, "matched": 1, "bank": 2}[item["section"]], item["date"], item["id"]))
        history.sort(key=lambda item: (item["reviewed_at"] or "", item["id"]))
        if any(item.get("ambiguous") for item in items):
            warnings.append("Há correspondências ambíguas; selecione a despesa antes de aprovar.")
        if any(not item["card_last_four"] for item in items if item["tx_id"] is not None):
            warnings.append("Alguns lançamentos não têm cartão identificado e precisam de revisão.")
        if not statement["due_date"]:
            warnings.append("Fatura sem vencimento identificado; confira o período da conciliação.")
        total = len(items) + len(history)
        return {
            "statement_id": statement_id, "file_name": statement["file_name"], "items": items,
            "counts": {section: sum(item["section"] == section for item in items) for section in ("new", "matched", "bank")},
            "progress": {"total": total, "pending": len(items),
                         "approved": sum(item["decision"] == "approved" for item in history),
                         "ignored": sum(item["decision"] == "ignored" for item in history),
                         "reviewed": len(history), "percent": round(len(history) * 100 / total, 2) if total else 0},
            "history": history, "warnings": list(dict.fromkeys(warnings)),
        }

    def get_review_state(self, statement_id: int) -> dict:
        with self._transaction():
            self._materialize(statement_id)
            return self._state(statement_id)

    def _apply_category(self, expense_id: int, category: str):
        old = self.conn.execute(
            "SELECT * FROM expenses WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
            (expense_id, self.user_id),
        ).fetchone()
        if not old:
            raise ValueError("Despesa não encontrada ou não pertence ao usuário.")
        if category == old["category"]:
            return
        self.conn.execute("UPDATE expenses SET category = ? WHERE id = ? AND user_id = ?",
                          (category, expense_id, self.user_id))
        new = dict(old)
        new["category"] = category
        log_audit(self.conn, "update", expense_id, dict(old), new, user_id=self.user_id)

    def _generate_installment_parcels(self, tx: dict, expense_id: int, category: str):
        """Gera parcelas futuras como despesas normais, evitando duplicatas."""
        current = tx["installment_current"]
        total = tx["installment_total"]
        if not current or not total or current > total:
            return
        due_row = self.conn.execute(
            "SELECT due_date FROM card_statements WHERE id = ?", (tx["statement_id"],)
        ).fetchone()
        if not due_row or not due_row["due_date"]:
            return
        due_date = date.fromisoformat(due_row["due_date"])

        group = self.conn.execute(
            """SELECT id FROM installment_groups
               WHERE user_id = ? AND description = ? AND card_last_four = ?
                 AND total_parcels = ? AND original_purchase_date = ?""",
            (self.user_id, tx["description"], tx["card_last_four"], total, tx["original_purchase_date"]),
        ).fetchone()
        if not group:
            cursor = self.conn.execute(
                """INSERT INTO installment_groups
                   (user_id, description, card_last_four, total_parcels,
                    original_purchase_date, amount_cents)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (self.user_id, tx["description"], tx["card_last_four"], total,
                 tx["original_purchase_date"], tx["amount_cents"]),
            )
            group_id = cursor.lastrowid
        else:
            group_id = group["id"]

        for parcel in range(current, total + 1):
            reference_date = self._installment_reference_date(due_date, current, parcel)
            if parcel == current:
                parcel_expense_id = expense_id
                statement_tx_id = tx["id"]
            else:
                existing = self.conn.execute(
                    """SELECT id FROM expenses
                       WHERE user_id = ? AND description = ? AND amount = ?
                         AND expense_date = ? AND card_last_four = ?
                         AND method = ? AND deleted_at IS NULL""",
                    (self.user_id, tx["description"], tx["amount_cents"] / 100,
                     reference_date.isoformat(), tx["card_last_four"], CREDIT_CARD_METHOD),
                ).fetchone()
                if existing:
                    parcel_expense_id = existing["id"]
                else:
                    amount = tx["amount_cents"] / 100
                    cursor = self.conn.execute(
                        """INSERT INTO expenses
                           (user_id, amount, description, category, method, expense_date,
                            hash, card_last_four, card_holder, statement_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (self.user_id, amount, tx["description"], category,
                         CREDIT_CARD_METHOD, reference_date.isoformat(),
                         compute_hash(amount, tx["description"], reference_date),
                         tx["card_last_four"], tx["card_holder"], None),
                    )
                    parcel_expense_id = cursor.lastrowid
                statement_tx_id = None

            self.conn.execute(
                """INSERT INTO installment_parcels
                   (group_id, parcel_number, reference_date, expense_id, statement_transaction_id)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(group_id, parcel_number) DO UPDATE SET
                       reference_date = excluded.reference_date,
                       expense_id = excluded.expense_id,
                       statement_transaction_id = COALESCE(excluded.statement_transaction_id,
                                                              installment_parcels.statement_transaction_id)""",
                (group_id, parcel, reference_date.isoformat(), parcel_expense_id, statement_tx_id),
            )

    def _review(self, statement_id: int, section: str, action: str, items: list[dict]) -> int:
        processed = 0
        for item in items:
            review = self.conn.execute(
                "SELECT * FROM statement_review_items WHERE statement_id = ? AND item_id = ?",
                (statement_id, item["id"]),
            ).fetchone()
            if not review or (review["decision"] == "pending" and not review["active"]):
                raise ValueError("Item não encontrado nesta fatura.")
            if review["section"] != section:
                raise ValueError("O item não pertence à aba informada; atualize a conciliação.")
            category = self._category(item["category"]) if "category" in item else review["category"]
            expense_id = item.get("expense_id", review["expense_id"])
            decision = "approved" if action == "approve" else "ignored"
            if review["decision"] != "pending":
                if (review["decision"] != decision
                        or ("category" in item and category != review["category"])
                        or ("expense_id" in item and expense_id != review["expense_id"])):
                    raise ValueError("Item já revisado com outra decisão ou outros dados.")
                continue
            snapshot = json.loads(review["snapshot"])
            warning = review["warning"]
            edited = review["category_edited"] or "category" in item
            if section == "matched" and (action == "approve" or "expense_id" in item):
                allowed = {candidate["expense_id"] for candidate in snapshot.get("candidates", [])}
                if review["expense_id"]:
                    allowed.add(review["expense_id"])
                if not expense_id or expense_id not in allowed:
                    raise ValueError("Selecione uma correspondência válida para o lançamento ambíguo.")
                if action == "approve" and self.conn.execute(
                    """SELECT 1 FROM statement_review_items WHERE claimed_expense_id = ?
                       AND NOT (statement_id = ? AND item_id = ?)""",
                    (expense_id, statement_id, item["id"]),
                ).fetchone():
                    raise ValueError("Despesa já vinculada a outro lançamento; atualize a conciliação.")
                expense = self.conn.execute(
                    "SELECT * FROM expenses WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
                    (expense_id, self.user_id),
                ).fetchone()
                if not expense:
                    raise ValueError("Despesa não encontrada ou não pertence ao usuário.")
                tx = self.conn.execute("SELECT * FROM statement_transactions WHERE id = ?", (review["tx_id"],)).fetchone()
                if (expense["method"] != CREDIT_CARD_METHOD
                        or self._cents(expense["amount"]) != tx["amount_cents"]
                        or abs((date.fromisoformat(expense["expense_date"]) - date.fromisoformat(tx["transaction_date"])).days) > 2):
                    raise ValueError("A despesa não corresponde ao valor e à data do lançamento.")
                snapshot, warning = self._match_snapshot(tx, expense)
            if action == "approve":
                if section == "new":
                    if not category:
                        raise ValueError("Selecione uma categoria cadastrada antes de aprovar o lançamento.")
                    category = self._category(category)
                    tx = self.conn.execute(
                        "SELECT * FROM statement_transactions WHERE id = ? AND statement_id = ?",
                        (review["tx_id"], statement_id),
                    ).fetchone()
                    amount = tx["amount_cents"] / 100
                    cursor = self.conn.execute(
                        """INSERT INTO expenses (
                            user_id, amount, description, category, method, expense_date, hash,
                            card_last_four, card_holder, statement_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (self.user_id, amount, tx["description"], category, CREDIT_CARD_METHOD,
                         tx["transaction_date"], compute_hash(amount, tx["description"], date.fromisoformat(tx["transaction_date"])),
                         tx["card_last_four"], tx["card_holder"], statement_id),
                    )
                    expense_id = cursor.lastrowid
                    if "installment_current" in tx.keys() and tx["installment_current"]:
                        self._generate_installment_parcels(tx, expense_id, category)
                elif not edited:
                    category = expense["category"] if section == "matched" else snapshot["bank_category"]
                if section != "new" and edited and category:
                    category = self._category(category)
                    self._apply_category(expense_id, category)
                if section == "matched" and action == "approve" and "installment_current" in tx.keys() and tx["installment_current"]:
                    self._generate_installment_parcels(tx, expense_id, category)

            snapshot["expense_id"] = expense_id
            snapshot["category"] = category
            self.conn.execute(
                """UPDATE statement_review_items SET decision = ?, expense_id = ?, claimed_expense_id = ?,
                   category = ?, category_edited = ?, snapshot = ?, warning = ?, reviewed_at = CURRENT_TIMESTAMP
                   WHERE statement_id = ? AND item_id = ? AND decision = 'pending'""",
                (decision, expense_id, expense_id if action == "approve" and section != "bank" else None,
                 category, int(edited), json.dumps(snapshot, ensure_ascii=False), warning, statement_id, item["id"]),
            )
            if review["tx_id"] is not None:
                status = "rejected" if action == "ignore" else ("inserted" if section == "new" else "approved")
                self.conn.execute(
                    """UPDATE statement_transactions SET status = ?, selected_category = ?, matched_expense_id = ?,
                       reviewed_at = CURRENT_TIMESTAMP WHERE id = ? AND statement_id = ?""",
                    (status, category, expense_id, review["tx_id"], statement_id),
                )
            processed += 1
        return processed

    def review_batch(self, statement_id: int, section: str, action: str,
                     items: list[dict], request_id: str) -> dict:
        if type(statement_id) is not int or statement_id <= 0:
            raise ValueError("Fatura não encontrada ou não pertence ao usuário.")
        if section not in ("new", "matched", "bank") or action not in ("approve", "ignore"):
            raise ValueError("Aba ou ação de revisão inválida.")
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("Informe um request_id válido para a revisão.")
        if not isinstance(items, list) or not items:
            raise ValueError("Selecione ao menos um item para revisar.")
        seen = set()
        for item in items:
            if (not isinstance(item, dict) or set(item) - {"id", "category", "expense_id"}
                    or not isinstance(item.get("id"), str)
                    or not re.fullmatch(r"(?:tx|expense):[1-9][0-9]*", item["id"])):
                raise ValueError("Item de revisão inválido.")
            if item["id"] in seen:
                raise ValueError("Há itens duplicados no lote.")
            seen.add(item["id"])
            if item["id"].startswith("expense:") != (section == "bank"):
                raise ValueError("O identificador do item não pertence à aba informada.")
            if "category" in item and not isinstance(item["category"], str):
                raise ValueError("Categoria inválida: informe uma categoria cadastrada.")
            if "expense_id" in item and (section != "matched" or type(item["expense_id"]) is not int or item["expense_id"] <= 0):
                raise ValueError("Identificador de correspondência inválido.")
        payload = json.dumps({"statement_id": statement_id, "section": section, "action": action,
                              "items": sorted(items, key=lambda item: item["id"])},
                             sort_keys=True, ensure_ascii=False)
        try:
            with self._transaction():
                self._verify_statement_ownership(statement_id)
                previous = self.conn.execute(
                    "SELECT payload, processed FROM statement_review_batches WHERE user_id = ? AND request_id = ?",
                    (self.user_id, request_id),
                ).fetchone()
                if previous and previous["payload"] != payload:
                    raise ValueError("request_id já utilizado com um pedido diferente.")
                self._materialize(statement_id)
                processed = previous["processed"] if previous else self._review(statement_id, section, action, items)
                if not previous:
                    self.conn.execute(
                        """INSERT INTO statement_review_batches (user_id, statement_id, request_id, payload, processed)
                           VALUES (?, ?, ?, ?, ?)""",
                        (self.user_id, statement_id, request_id, payload, processed),
                    )
                self._materialize(statement_id)
                return {"success": True, "processed": processed, "state": self._state(statement_id)}
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Não foi possível concluir o lote; nenhuma decisão do pedido foi aplicada.") from exc

    def update_review_category(self, statement_id: int, item_id: str, category: str,
                               only_if_empty: bool = False) -> dict:
        if not isinstance(item_id, str) or not re.fullmatch(r"(?:tx|expense):[1-9][0-9]*", item_id):
            raise ValueError("Identificador de revisão inválido.")
        if not isinstance(category, str) or type(only_if_empty) is not bool:
            raise ValueError("Categoria ou condição de atualização inválida.")
        with self._transaction():
            self._materialize(statement_id)
            review = self.conn.execute(
                "SELECT * FROM statement_review_items WHERE statement_id = ? AND item_id = ?",
                (statement_id, item_id),
            ).fetchone()
            if not review or (review["decision"] == "pending" and not review["active"]):
                raise ValueError("Item não encontrado nesta fatura.")
            if review["decision"] != "pending":
                if not only_if_empty:
                    raise ValueError("Item já revisado; sua categoria não pode mais ser editada aqui.")
                updated = False
            elif only_if_empty and (review["category"] or review["category_edited"]):
                updated = False
            else:
                category = self._category(category)
                snapshot = json.loads(review["snapshot"])
                snapshot["category"] = category
                self.conn.execute(
                    """UPDATE statement_review_items SET category = ?, category_edited = ?, snapshot = ?
                       WHERE statement_id = ? AND item_id = ?""",
                    (category, int(not only_if_empty), json.dumps(snapshot, ensure_ascii=False), statement_id, item_id),
                )
                if review["tx_id"] is not None:
                    self.conn.execute("UPDATE statement_transactions SET selected_category = ? WHERE id = ?",
                                      (category, review["tx_id"]))
                updated = True
            state = self._state(statement_id)
            current = next(item for item in state["items"] + state["history"] if item["id"] == item_id)
            return {"success": True, "updated": updated, "category": current["category"], "state": state}

    def reconcile(self, statement_id: int) -> ReconciliationResult:
        """Adaptador das dataclasses legadas sobre o mesmo estado persistente."""
        state = self.get_review_state(statement_id)
        result = ReconciliationResult(warnings=state["warnings"])
        statement = self._verify_statement_ownership(statement_id)
        cards = [card for card in (statement["card_last_four"] or "").split(",") if card]
        for item in state["items"]:
            card = item["card_last_four"] or (cards[0] if len(cards) == 1 else "não identificado")
            section = result.sections.setdefault(card, ReconciliationSection())
            if item["section"] == "bank":
                expense = self.conn.execute("SELECT * FROM expenses WHERE id = ? AND user_id = ?",
                                            (item["expense_id"], self.user_id)).fetchone()
                section.only_on_database.append(dict(expense))
                continue
            row = self.conn.execute("SELECT * FROM statement_transactions WHERE id = ?", (item["tx_id"],)).fetchone()
            tx = ParsedTransaction(
                id=row["id"], transaction_date=date.fromisoformat(row["transaction_date"]),
                description=row["description"], amount_cents=row["amount_cents"], card_holder=row["card_holder"],
                card_last_four=row["card_last_four"], installment_info=row["installment_info"],
                installment_current=row["installment_current"], installment_total=row["installment_total"],
                original_purchase_date=date.fromisoformat(row["original_purchase_date"]) if row["original_purchase_date"] else None,
                raw_line=row["raw_line"] or "", selected_category=item["category"],
                ambiguous=bool(item.get("ambiguous")),
            )
            if item["section"] == "new":
                section.only_on_statement.append(tx)
            elif item.get("ambiguous"):
                expenses = [dict(self.conn.execute("SELECT * FROM expenses WHERE id = ? AND user_id = ?",
                                                   (candidate["expense_id"], self.user_id)).fetchone())
                            for candidate in item["candidates"]]
                result.ambiguous.append((tx, expenses))
            else:
                expense = dict(self.conn.execute("SELECT * FROM expenses WHERE id = ? AND user_id = ?",
                                                  (item["expense_id"], self.user_id)).fetchone())
                section.matched.append(CandidateMatch(tx, expense, abs((tx.transaction_date - date.fromisoformat(expense["expense_date"])).days)))
        return result

    def _legacy_action(self, tx_id: int, section: Optional[str], action: str, **values) -> dict:
        if type(tx_id) is not int or tx_id <= 0:
            raise ValueError("Lançamento não encontrado ou não pertence ao usuário.")
        with self._transaction():
            row = self.conn.execute(
                """SELECT st.statement_id FROM statement_transactions st
                   JOIN card_statements cs ON cs.id = st.statement_id WHERE st.id = ? AND cs.user_id = ?""",
                (tx_id, self.user_id),
            ).fetchone()
            if not row:
                raise ValueError("Lançamento não encontrado ou não pertence ao usuário.")
            state = self.get_review_state(row["statement_id"])
            current = next(item for item in state["items"] + state["history"] if item["tx_id"] == tx_id)
            result = self.review_batch(row["statement_id"], section or current["section"], action,
                                       [{"id": current["id"], **values}], f"legacy:{uuid4()}")
            reviewed = next(item for item in result["state"]["history"] if item["tx_id"] == tx_id)
            return {"success": True, "expense_id": reviewed["expense_id"], "category": reviewed["category"]}

    def approve_insert(self, tx_id: int, category: Optional[str] = None) -> dict:
        try:
            return self._legacy_action(tx_id, "new", "approve", **({"category": category} if category is not None else {}))
        except ValueError as exc:
            return {"error": str(exc)}

    def approve_match(self, tx_id: int, expense_id: int) -> dict:
        try:
            return self._legacy_action(tx_id, "matched", "approve", expense_id=expense_id)
        except ValueError as exc:
            return {"error": str(exc)}

    def approve_review(self, expense_id: int, statement_id: int) -> dict:
        try:
            self.review_batch(statement_id, "bank", "approve", [{"id": f"expense:{expense_id}"}], f"legacy:{uuid4()}")
            return {"success": True, "expense_id": expense_id}
        except ValueError as exc:
            return {"error": str(exc)}

    def reject(self, tx_id: int) -> dict:
        try:
            return self._legacy_action(tx_id, None, "ignore")
        except ValueError as exc:
            return {"error": str(exc)}

    def update_category(self, tx_id: int, category: str) -> dict:
        row = self.conn.execute(
            """SELECT st.statement_id FROM statement_transactions st JOIN card_statements cs ON cs.id = st.statement_id
               WHERE st.id = ? AND cs.user_id = ?""", (tx_id, self.user_id)
        ).fetchone()
        if not row:
            return {"error": "Lançamento não encontrado ou não pertence ao usuário."}
        try:
            return self.update_review_category(row["statement_id"], f"tx:{tx_id}", category)
        except ValueError as exc:
            return {"error": str(exc)}

    def _update_statement_status(self, statement_id: int):
        pending = self.conn.execute(
            "SELECT COUNT(*) FROM statement_review_items WHERE statement_id = ? AND decision = 'pending' AND active = 1",
            (statement_id,),
        ).fetchone()[0]
        self.conn.execute(
            "UPDATE card_statements SET status = ? WHERE id = ? AND user_id = ? AND status != 'failed'",
            ("pending" if pending else "confirmed", statement_id, self.user_id),
        )

    def get_pending_summary(self) -> dict:
        with self._transaction():
            rows = self.conn.execute(
                "SELECT * FROM card_statements WHERE user_id = ? AND status != 'failed' ORDER BY created_at, id",
                (self.user_id,),
            ).fetchall()
            for row in rows:
                self._materialize(row["id"])
                state = self._state(row["id"])
                if state["progress"]["pending"]:
                    return {"has_pending": True, "statement_id": row["id"], "file_name": row["file_name"],
                            "due_date": row["due_date"], "card_last_four": row["card_last_four"],
                            "pending_count": state["progress"]["pending"]}
        return {"has_pending": False}

    def list_statements(self) -> list[dict]:
        with self._transaction():
            ids = self.conn.execute("SELECT id FROM card_statements WHERE user_id = ? ORDER BY id", (self.user_id,)).fetchall()
            for row in ids:
                self._materialize(row["id"])
            return [dict(row) for row in self.conn.execute(
                """SELECT id, file_name, statement_date, due_date, total_cents, card_last_four,
                          card_holder, status, created_at FROM card_statements
                   WHERE user_id = ? ORDER BY created_at DESC, id DESC""", (self.user_id,)
            ).fetchall()]

    def confirm_reconciliation(self, statement_id: int, insert_ids: list[int],
                               update_pairs: list[tuple[int, int]], delete_ids: list[int],
                               default_category: str = "Outros") -> dict:
        """Compatibilidade explicita: somente este metodo permite soft delete."""
        with self._transaction():
            self._verify_statement_ownership(statement_id)
            category = self._category(default_category)
            if not category:
                raise ValueError("Categoria padrão inválida.")
            self._materialize(statement_id)
            inserted = self._review(statement_id, "new", "approve", [{"id": f"tx:{tx}", "category": category} for tx in insert_ids])
            updated = self._review(statement_id, "matched", "approve", [{"id": f"tx:{tx}", "expense_id": exp} for tx, exp in update_pairs])
            deleted = 0
            errors = []
            for expense_id in delete_ids:
                review = self.conn.execute(
                    "SELECT * FROM statement_review_items WHERE statement_id = ? AND item_id = ? AND section = 'bank' AND active = 1",
                    (statement_id, f"expense:{expense_id}"),
                ).fetchone()
                if not review:
                    raise ValueError("Despesa não pertence aos itens de banco desta fatura.")
                if review["decision"] != "pending":
                    continue
                old = soft_delete(self.conn, "expenses", expense_id, self.user_id)
                if old is None:
                    errors.append(f"Despesa {expense_id} não encontrada.")
                    continue
                log_audit(self.conn, "delete", expense_id, old, user_id=self.user_id)
                self.conn.execute(
                    """UPDATE statement_review_items SET decision = 'ignored', reviewed_at = CURRENT_TIMESTAMP
                       WHERE statement_id = ? AND item_id = ?""", (statement_id, f"expense:{expense_id}")
                )
                deleted += 1
            self._materialize(statement_id)
            status = self.conn.execute("SELECT status FROM card_statements WHERE id = ?", (statement_id,)).fetchone()[0]
            return {"status": status, "inserted": inserted, "updated": updated, "deleted": deleted, "errors": errors}

    def _category_exists(self, name: str) -> bool:
        try:
            return self._category(name) is not None
        except ValueError:
            return False
