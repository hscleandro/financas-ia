"""Teclados inline para HITL — MVP 3.

Botões Telegram substituem parsing de texto livre no confirm_node.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Retorna teclado inline para confirmação de operações destrutivas.

    Usado em delete_expense e update_expense via HITL.
    """
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirmar", callback_data="confirm"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def format_expense_for_confirmation(expense: dict, operation: str = "delete") -> str:
    """Formata detalhes do gasto para mensagem de confirmação.

    Args:
        expense: dict com id, description, amount, category, method, expense_date
        operation: "delete" ou "update"

    Returns:
        Mensagem formatada em Markdown
    """
    emoji = "🗑" if operation == "delete" else "✏️"
    action = "Excluir" if operation == "delete" else "Atualizar"

    return (
        f"{emoji} *{action} gasto?*\n\n"
        f"📝 {expense.get('description', 'N/A')}\n"
        f"💰 R$ {expense.get('amount', 0):.2f}\n"
        f"📅 {expense.get('expense_date', 'N/A')}\n"
        f"🏷 {expense.get('category', 'N/A')} · {expense.get('method', 'N/A')}"
    )
