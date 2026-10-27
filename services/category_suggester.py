"""Serviço de sugestão automática de categoria para lançamentos de fatura.

Estratégia:
1. Buscar no histórico de despesas do usuário descrições similares já
   categorizadas.
2. Se não encontrar correspondência confiável, consultar a IA (OpenAI) para
   escolher uma das categorias existentes.
3. Nunca criar categorias novas; apenas sugerir entre as disponíveis.
"""
import sqlite3
from difflib import SequenceMatcher
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import settings


def _normalize(text: str) -> str:
    """Normaliza texto para comparação."""
    import re
    import unicodedata
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


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
        return sorted({row["name"] for row in rows})

    def _find_in_history(self, description: str) -> Optional[str]:
        """Busca despesas anteriores com descrição similar e retorna a categoria
        mais frequente entre as similares."""
        rows = self.conn.execute(
            """
            SELECT description, category
            FROM expenses
            WHERE user_id = ? AND deleted_at IS NULL AND category IS NOT NULL
            """,
            (self.user_id,),
        ).fetchall()

        if not rows:
            return None

        similar: list[tuple[str, float]] = []
        for row in rows:
            sim = _similarity(description, row["description"])
            if sim >= 0.65:
                similar.append((row["category"], sim))

        if not similar:
            return None

        # Escolhe a categoria com maior similaridade média
        from collections import defaultdict
        cat_scores: defaultdict[str, list[float]] = defaultdict(list)
        for cat, sim in similar:
            cat_scores[cat].append(sim)

        best_cat = max(
            cat_scores.keys(),
            key=lambda c: sum(cat_scores[c]) / len(cat_scores[c]),
        )
        return best_cat

    def _ask_ai(self, description: str, categories: list[str]) -> Optional[str]:
        """Consulta a IA para escolher uma categoria existente."""
        if not settings.openai_api_key:
            return None

        try:
            llm = ChatOpenAI(
                model=settings.openai_model,
                temperature=0,
                api_key=settings.openai_api_key,
            )
            system_msg = (
                "Você é um assistente de categorização de despesas pessoais. "
                "Dada uma descrição curta de uma despesa, escolha a categoria "
                "mais adequada entre as categorias disponíveis. "
                "Responda apenas com o nome exato da categoria escolhida, nada mais."
            )
            human_msg = (
                f"Descrição: '{description}'\n"
                f"Categorias disponíveis: {', '.join(categories)}\n"
                "Categoria:"
            )
            response = llm.invoke([SystemMessage(content=system_msg), HumanMessage(content=human_msg)])
            chosen = response.content.strip()
            # Normaliza para encontrar correspondência case-insensitive
            lower_chosen = chosen.lower()
            for cat in categories:
                if cat.lower() == lower_chosen:
                    return cat
            return None
        except Exception:
            return None

    def suggest_from_history(self, description: str) -> Optional[str]:
        """Sugere categoria apenas com base no histórico (rápido, sem IA)."""
        return self._find_in_history(description)

    def suggest(self, description: str) -> Optional[str]:
        """Sugere uma categoria para a descrição informada.

        Retorna None se não conseguir sugerir.
        """
        categories = self._get_valid_categories()
        if not categories:
            return None

        # 1. Histórico
        historical = self._find_in_history(description)
        if historical:
            return historical

        # 2. IA
        return self._ask_ai(description, categories)
