"""Teclados inline para HITL — MVP 3 (otimizado para UX).

Botões Telegram substituem parsing de texto livre no confirm_node.
Versão otimizada com feedback visual aprimorado.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Retorna teclado inline para confirmação de operações destrutivas.

    Usado em delete_expense e update_expense via HITL.
    Botões otimizados com emojis e texto claro.
    """
    keyboard = [
        [
            InlineKeyboardButton("✅ Sim, confirmar", callback_data="confirm"),
            InlineKeyboardButton("❌ Não, cancelar", callback_data="cancel"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_yes_no_keyboard() -> InlineKeyboardMarkup:
    """Retorna teclado inline simples sim/não para perguntas gerais.

    Usado para confirmações de criação de categoria, método de pagamento, etc.
    """
    keyboard = [
        [
            InlineKeyboardButton("👍 Sim", callback_data="sim"),
            InlineKeyboardButton("👎 Não", callback_data="não"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def format_expense_for_confirmation(expense: dict, operation: str = "delete") -> str:
    """Formata detalhes do gasto para mensagem de confirmação.

    Args:
        expense: dict com id, description, amount, category, method, expense_date
        operation: "delete" ou "update"

    Returns:
        Mensagem formatada em Markdown otimizada para Telegram
    """
    emoji = "🗑️" if operation == "delete" else "✏️"
    action = "Excluir gasto" if operation == "delete" else "Atualizar gasto"

    return (
        f"{emoji} *{action}*\n\n"
        f"📝 {expense.get('description', 'N/A')}\n"
        f"💰 *R$ {expense.get('amount', 0):.2f}*\n"
        f"📅 {expense.get('expense_date', 'N/A')}\n"
        f"🏷️ {expense.get('category', 'N/A')} · {expense.get('method', 'N/A')}\n"
        f"🔢 ID #{expense.get('id', 'N/A')}"
    )


def format_expense_list(expenses: list[dict], max_items: int = 10) -> str:
    """Formata lista de gastos de forma concisa e visual.

    Args:
        expenses: Lista de dicts com gastos
        max_items: Número máximo de itens a exibir (padrão: 10)

    Returns:
        String formatada com Markdown otimizada para Telegram
    """
    if not expenses:
        return "❌ Nenhum gasto encontrado."

    total = sum(e.get("amount", 0) for e in expenses)
    count = len(expenses)

    # Mostrar apenas primeiros max_items
    visible = expenses[:max_items]
    hidden_count = count - len(visible)

    lines = []
    for i, exp in enumerate(visible, 1):
        lines.append(
            f"{i}. *R$ {exp.get('amount', 0):.2f}* · "
            f"{exp.get('description', 'N/A')} · "
            f"{exp.get('category', 'N/A')}"
        )

    result = "\n".join(lines)

    # Adicionar resumo se houver itens ocultos
    if hidden_count > 0:
        result += f"\n\n_...e mais {hidden_count} {'item' if hidden_count == 1 else 'itens'}_"

    result += f"\n\n💰 *Total:* R$ {total:.2f}"

    return result


def format_summary(summary_data: dict, period: str = "") -> str:
    """Formata resumo financeiro com emojis e estrutura visual.

    Args:
        summary_data: Dict com dados do resumo (category → total)
        period: Período do resumo (ex: "Janeiro 2026", "Últimos 7 dias")

    Returns:
        String formatada com Markdown
    """
    if not summary_data:
        return "❌ Nenhum dado encontrado para o período."

    # Emojis por categoria (alguns exemplos)
    category_emojis = {
        "Alimentação": "🍔",
        "Transporte": "🚗",
        "Moradia": "🏠",
        "Saúde": "🏥",
        "Lazer": "🎮",
        "Educação": "📚",
        "Vestuário": "👕",
        "Tecnologia": "💻",
        "Serviços": "🔧",
        "Outros": "📦",
    }

    header = f"📊 *Resumo{' - ' + period if period else ''}*\n\n"

    # Ordenar por valor (maior → menor)
    sorted_items = sorted(summary_data.items(), key=lambda x: x[1], reverse=True)

    lines = []
    total = 0
    for category, amount in sorted_items:
        emoji = category_emojis.get(category, "•")
        lines.append(f"{emoji} {category}: *R$ {amount:.2f}*")
        total += amount

    result = header + "\n".join(lines)
    result += f"\n\n💰 *Total geral:* R$ {total:.2f}"

    return result
