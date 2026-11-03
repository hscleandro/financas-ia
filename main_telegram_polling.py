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

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from telegram import Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from config import settings
from bot.handlers import process_telegram_message, process_telegram_callback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# httpx registra a URL completa (com o token do bot) em nível INFO — silenciar.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def _init_app_with_retry(app: Application, max_retries: int = 5, base_delay: float = 5.0) -> None:
    """Inicializa a aplicação com retentativas em caso de timeout de rede.

    get_me() na inicialização pode falhar por instabilidade com a API do
    Telegram (ex.: TimedOut). Sem retry o processo morre e o servidor para.
    """
    for attempt in range(1, max_retries + 1):
        try:
            await app.initialize()
            return
        except (TimedOut, NetworkError) as e:
            if attempt == max_retries:
                raise
            wait = base_delay * attempt
            logger.warning(
                f"Timeout/erro de rede na inicialização do Telegram (tentativa {attempt}/{max_retries}): {e}. "
                f"Tentando novamente em {wait}s..."
            )
            await asyncio.sleep(wait)


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

        # Criar aplicação do Telegram com timeouts mais generosos
        app = (
            Application.builder()
            .token(settings.telegram_bot_token)
            .connect_timeout(30)
            .read_timeout(30)
            .write_timeout(30)
            .get_updates_connect_timeout(60)
            .get_updates_read_timeout(60)
            .build()
        )

        # Armazenar checkpointer no bot_data para acesso nos handlers
        app.bot_data["checkpointer"] = checkpointer

        # Registrar handlers
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))

        logger.info("✅ Bot iniciado! Aguardando mensagens...")
        logger.info("Pressione Ctrl+C para parar.")

        # Iniciar polling
        await _init_app_with_retry(app)
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
