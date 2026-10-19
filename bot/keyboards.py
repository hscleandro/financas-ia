"""Teclados inline para HITL — MVP 3."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Retorna teclado inline para confirmação de operações destrutivas."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Sim, confirmar", callback_data="confirm"),
            InlineKeyboardButton("❌ Não, cancelar", callback_data="cancel"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)
