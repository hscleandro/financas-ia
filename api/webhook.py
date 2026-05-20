"""FastAPI webhook receiver para Telegram Bot — MVP 3.

Modo webhook (produção):
- Requer URL pública com HTTPS
- Telegram envia updates via POST
- Responde 200 imediatamente + processa em background

Para desenvolvimento local com webhook:
    1. Rodar FastAPI: uvicorn api.webhook:app --port 8000
    2. Expor com ngrok: ngrok http 8000
    3. Registrar webhook:
       curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
         -d "url=https://abc123.ngrok.io/webhook/telegram?secret=SEU_SECRET"

Para desenvolvimento sem URL pública, use: python main_telegram_polling.py
"""
import logging
from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from telegram import Bot, Update

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


# Global state para checkpointer (compartilhado entre requests)
checkpointer_instance = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager — inicializa checkpointer ao startar."""
    global checkpointer_instance

    run_migrations()
    logger.info("Migrations aplicadas")

    # Inicializar checkpointer
    checkpointer_instance = AsyncSqliteSaver.from_conn_string(settings.checkpoints_path)
    await checkpointer_instance.__aenter__()
    logger.info(f"Checkpointer inicializado: {settings.checkpoints_path}")

    logger.info("✅ FastAPI webhook pronto!")
    logger.info(f"Database: {settings.db_path}")
    logger.info(f"Webhook URL esperada: {settings.telegram_webhook_url}")

    yield

    # Cleanup ao encerrar
    if checkpointer_instance:
        await checkpointer_instance.__aexit__(None, None, None)
        logger.info("Checkpointer fechado")


app = FastAPI(title="Financas-IA Telegram Bot", lifespan=lifespan)


@app.get("/health")
async def health():
    """Healthcheck endpoint."""
    return {"status": "ok", "service": "financas-ia-telegram-bot"}


@app.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    secret: str = "",
):
    """Webhook receiver para updates do Telegram.

    Query param 'secret' é usado para autenticação simples.
    Telegram não valida isso, mas previne requisições falsas.

    Args:
        request: FastAPI Request
        background_tasks: FastAPI BackgroundTasks
        secret: Query param para validação (deve ser settings.telegram_webhook_secret)

    Returns:
        {"status": "ok"} imediatamente (200 OK)
    """
    # 1. Validar secret token
    if secret != settings.telegram_webhook_secret:
        logger.warning(f"Webhook chamado com secret inválido: {secret}")
        raise HTTPException(status_code=403, detail="Invalid secret")

    # 2. Parse update do Telegram
    try:
        data = await request.json()
        bot = Bot(token=settings.telegram_bot_token)
        update = Update.de_json(data, bot)
    except Exception as e:
        logger.error(f"Erro ao parsear update: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid update format")

    # 3. Extrair chat_id e texto
    chat_id = None
    text = None
    callback_query_id = None
    callback_data = None

    if update.message:
        # Mensagem de texto normal
        chat_id = update.message.chat_id
        text = update.message.text or ""
        update_id = update.update_id
        logger.info(f"Update #{update_id} — Mensagem de {chat_id}")

    elif update.callback_query:
        # Usuário tocou em botão inline (HITL)
        chat_id = update.callback_query.message.chat_id
        callback_query_id = update.callback_query.id
        callback_data = update.callback_query.data
        update_id = update.update_id
        logger.info(f"Update #{update_id} — Callback de {chat_id}: {callback_data}")

    else:
        # Update type não suportado (ignora)
        logger.warning(f"Update type não suportado: {update}")
        return {"status": "ok"}

    # 4. Responder 200 OK IMEDIATAMENTE
    # Telegram retenta se não receber 200 em ~10s
    # LangGraph pode demorar 5-20s, então processamos em background

    if callback_query_id and callback_data:
        # Callback de botão
        background_tasks.add_task(
            process_telegram_callback,
            bot=bot,
            chat_id=chat_id,
            callback_query_id=callback_query_id,
            callback_data=callback_data,
            checkpointer=checkpointer_instance,
        )
    else:
        # Mensagem de texto
        background_tasks.add_task(
            process_telegram_message,
            bot=bot,
            chat_id=chat_id,
            text=text,
            checkpointer=checkpointer_instance,
        )

    return {"status": "ok"}


@app.post("/webhook/register")
async def register_webhook():
    """Helper endpoint para registrar webhook no Telegram.

    Chame este endpoint uma vez após deploy para configurar o webhook.

    Exemplo:
        curl -X POST http://localhost:8000/webhook/register

    Returns:
        Resultado do setWebhook do Telegram
    """
    if not settings.telegram_webhook_url:
        raise HTTPException(
            status_code=400,
            detail="telegram_webhook_url não configurado no .env",
        )

    bot = Bot(token=settings.telegram_bot_token)

    webhook_url = f"{settings.telegram_webhook_url}?secret={settings.telegram_webhook_secret}"

    try:
        result = await bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook registrado: {webhook_url}")
        return {"success": result, "webhook_url": webhook_url}
    except Exception as e:
        logger.error(f"Erro ao registrar webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/webhook/unregister")
async def unregister_webhook():
    """Helper endpoint para remover webhook (útil ao trocar para polling).

    Exemplo:
        curl -X DELETE http://localhost:8000/webhook/unregister
    """
    bot = Bot(token=settings.telegram_bot_token)

    try:
        result = await bot.delete_webhook()
        logger.info("Webhook removido")
        return {"success": result}
    except Exception as e:
        logger.error(f"Erro ao remover webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
