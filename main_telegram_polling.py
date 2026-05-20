"""Telegram Bot — Polling Mode (desenvolvimento).

Modo mais simples para testes locais:
- Não precisa de URL pública
- Não precisa de ngrok
- Bot busca updates do Telegram a cada 1-2 segundos

Para produção, use api/webhook.py (modo webhook).

Usage:
    python main_telegram_polling.py
"""
import asyncio
import logging

from alembic import command
from alembic.config import Config
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from config import settings
from bot.handlers import process_telegram_message, process_telegram_callback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def run_migrations() -> None:
    """Aplica todas as migrations pendentes."""
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


async def handle_message(update: Update, context) -> None:
    """Handler para mensagens de texto."""
    if not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    text = update.message.text

    logger.info(f"Mensagem recebida de {chat_id}: {text}")

    # Acessar checkpointer do contexto da aplicação
    checkpointer = context.application.bot_data["checkpointer"]

    await process_telegram_message(
        bot=context.bot,
        chat_id=chat_id,
        text=text,
        checkpointer=checkpointer,
    )


async def handle_callback(update: Update, context) -> None:
    """Handler para callbacks de botões inline."""
    if not update.callback_query:
        return

    query = update.callback_query
    chat_id = query.message.chat_id
    callback_data = query.data

    logger.info(f"Callback recebido de {chat_id}: {callback_data}")

    # Acessar checkpointer do contexto da aplicação
    checkpointer = context.application.bot_data["checkpointer"]

    await process_telegram_callback(
        bot=context.bot,
        chat_id=chat_id,
        callback_query_id=query.id,
        callback_data=callback_data,
        checkpointer=checkpointer,
    )


async def main() -> None:
    """Inicializa bot em modo polling."""
    # Migrations já devem ter sido rodadas pelo setup_telegram_user.py
    # run_migrations() pode travar em background, então comentamos
    # Se precisar rodar migrations, use: python setup_telegram_user.py <telegram_id>

    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN não configurado no .env")
        return

    logger.info("Iniciando bot em modo POLLING...")
    logger.info(f"Database: {settings.db_path}")
    logger.info(f"Checkpoints: {settings.checkpoints_path}")

    # Criar checkpointer (compartilhado entre todas as mensagens)
    logger.info("Criando checkpointer...")
    async with AsyncSqliteSaver.from_conn_string(settings.checkpoints_path) as checkpointer:
        logger.info("✅ Checkpointer criado!")

        # Criar aplicação do Telegram
        app = Application.builder().token(settings.telegram_bot_token).build()

        # Armazenar checkpointer no bot_data para acesso nos handlers
        app.bot_data["checkpointer"] = checkpointer

        # Registrar handlers
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))

        logger.info("✅ Bot iniciado! Aguardando mensagens...")
        logger.info("Pressione Ctrl+C para parar.")

        # Iniciar polling
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        # Manter rodando até Ctrl+C
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Encerrando bot...")
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
