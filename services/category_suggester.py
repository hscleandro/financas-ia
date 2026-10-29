"""Serviço de sugestão automática de categoria para lançamentos de fatura.

Estratégia:
1. Buscar nas despesas e conciliações aprovadas do usuário a mesma descrição
   normalizada, com uma categoria válida e sem conflitos.
2. Sem histórico confiável, usar o agente em modo somente classificação,
   permitindo abstinência quando não houver certeza.
3. Nunca criar categorias novas; apenas sugerir entre as disponíveis.
"""
import json
import sqlite3
import unicodedata
from typing import Optional

from agent.category_classifier import classify_category


def _normalize(text: str) -> str:
    """Normaliza caixa, acentos e separadores, preservando letras e números."""
    text = unicodedata.normalize("NFD", text.casefold())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = "".join(c if c.isalnum() else " " for c in text)
    return " ".join(text.split())


class CategorySuggester:
    """Sugere categoria para uma descrição de despesa."""

    def __init__(self, conn: sqlite3.Connection, user_id: int):
        self.conn = conn
        self.user_id = user_id

    def _get_valid_categories(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT name FROM categories WHERE user_id IS NULL OR user_id = ?",
            (self.user_id,),
        ).fetchall()
        return sorted({row["name"] for row in rows if row["name"].strip()})

    def _find_in_history(self, description: str, categories: list[str]) -> Optional[str]:
        """Combina fontes por descrição normalizada exata e exige categoria unânime."""
        normalized = _normalize(description)
        if not normalized or not categories:
            return None

        rows = self.conn.execute(
            """
            SELECT DISTINCT description, category
            FROM expenses
            WHERE user_id = ? AND deleted_at IS NULL AND category IS NOT NULL
            """,
            (self.user_id,),
        ).fetchall()

        matches = {
            row["category"]
            for row in rows
            if _normalize(row["description"]) == normalized
        }
        reviews = self.conn.execute(
            """
            SELECT ri.snapshot, ri.category
            FROM statement_review_items ri
            JOIN card_statements cs ON cs.id = ri.statement_id
            JOIN expenses e ON e.id = ri.expense_id
            WHERE cs.user_id = ? AND e.user_id = ? AND e.deleted_at IS NULL
              AND ri.decision = 'approved' AND ri.tx_id IS NOT NULL
              AND ri.active = 1 AND ri.category IS NOT NULL
            """,
            (self.user_id, self.user_id),
        ).fetchall()
        for row in reviews:
            try:
                snapshot = json.loads(row["snapshot"])
            except (TypeError, ValueError):
                continue
            name = snapshot.get("name") if isinstance(snapshot, dict) else None
            if isinstance(name, str) and _normalize(name) == normalized:
                matches.add(row["category"])

        if len(matches) == 1:
            category = matches.pop()
            if category in categories:
                return category
        return None

    def suggest_from_history(self, description: str) -> Optional[str]:
        """Sugere categoria apenas com base no histórico (rápido, sem IA)."""
        return self._find_in_history(description, self._get_valid_categories())

    def suggest(self, description: str) -> Optional[str]:
        """Sugere uma categoria para a descrição informada.

        Retorna None se não conseguir sugerir.
        """
        if not _normalize(description):
            return None

        categories = self._get_valid_categories()
        if not categories:
            return None

        # 1. Histórico
        historical = self._find_in_history(description, categories)
        if historical:
            return historical

        # 2. IA
        return classify_category(description, categories)
