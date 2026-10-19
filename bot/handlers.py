"""Handlers compartilhados para processar mensagens do Telegram.

Lógica de negócio usada tanto em webhook (FastAPI) quanto polling.
"""
import logging

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from telegram import Bot

from agent.graph import build_graph
from agent.tools import build_tools
from database.setup import get_connection
from database.user_setup import get_user_by_telegram_id
from services.expense_service import ExpenseService
from services.income_service import IncomeService
from bot.keyboards import get_confirmation_keyboard

logger = logging.getLogger(__name__)


async def process_telegram_message(
    bot: Bot,
    chat_id: int,
    text: str,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Processa mensagem do Telegram e responde via bot.

    Fluxo:
    1. Whitelist: valida telegram_id (chat_id) na tabela users
    2. Service Layer: instancia ExpenseService e IncomeService com user_id
    3. LangGraph: constrói tools + graph
    4. Executa: verifica state.next (interrupt pendente) ou nova mensagem
    5. Responde: envia mensagem final (com keyboard se HITL)

    Args:
        bot: Instância do Bot do Telegram
        chat_id: ID do chat (telegram_id do usuário)
        text: Texto da mensagem ou callback_data
        checkpointer: AsyncSqliteSaver para persistência de estado
    """
    try:
        # 1. Whitelist — apenas usuários autorizados
        conn = get_connection()
        user = get_user_by_telegram_id(conn, telegram_id=chat_id)

        if not user or not user.get("is_active"):
            await bot.send_message(
                chat_id=chat_id,
                text="🚫 Acesso não autorizado. Entre em contato com o administrador.",
            )
            conn.close()
            return

        user_id = user["id"]
        logger.info(f"Processando mensagem de user_id={user_id} (telegram_id={chat_id})")

        # 2. Service Layer + Tools
        expense_service = ExpenseService(conn, user_id=user_id)
        income_service = IncomeService(conn, user_id=user_id)
        tools = build_tools(expense_service, income_service)

        # 3. LangGraph
        graph = build_graph(tools, checkpointer=checkpointer)

        thread_id = f"user_{user_id}"
        config = {"configurable": {"thread_id": thread_id}}

        # 4. Verificar se há interrupt pendente (HITL)
        state = await graph.aget_state(config)
        logger.info(f"Estado do grafo - next: {state.next}, tasks: {state.tasks}")

        if state.next:
            # Interrupt pendente → usuário está respondendo confirmação
            logger.info(f"Resumindo interrupt com resposta: {text}")
            result = await graph.ainvoke(Command(resume=text), config)
        else:
            # Nova mensagem
            logger.info(f"Nova mensagem: {text}")
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content=text)]}, config
            )

        # 5. Verificar se há interrupt (HITL) e extrair mensagem correta
        keyboard = None
        response_text = None

        if "__interrupt__" in result and result["__interrupt__"]:
            # Interrupt disparado — mensagem vem do interrupt, não do AIMessage
            keyboard = get_confirmation_keyboard()
            interrupts = result["__interrupt__"]

            # Pegar a mensagem de confirmação do interrupt
            if interrupts and len(interrupts) > 0:
                interrupt_obj = interrupts[0]

                # Interrupt pode ser um objeto com atributo .value ou um dict
                if hasattr(interrupt_obj, "value"):
                    response_text = interrupt_obj.value
                elif isinstance(interrupt_obj, dict) and "value" in interrupt_obj:
                    response_text = interrupt_obj["value"]
                else:
                    # Fallback
                    response_text = str(interrupt_obj)

        # 6. Se não houver interrupt, pegar resposta normal do agente
        if not response_text:
            last_message = result["messages"][-1]
            response_text = last_message.content

        # 7. Validar que a resposta não está vazia
        if not response_text or not response_text.strip():
            logger.warning(f"Resposta vazia. Result: {result.keys()}, interrupt: {result.get('__interrupt__')}")
            response_text = "✅ Operação concluída."

        # 8. Enviar resposta
        await bot.send_message(
            chat_id=chat_id,
            text=response_text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

        conn.close()
        logger.info(f"Mensagem processada com sucesso para user_id={user_id}")

    except Exception as e:
        logger.error(f"Erro processando mensagem de chat_id={chat_id}: {e}", exc_info=True)
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="❌ Ocorreu um erro ao processar sua mensagem. Tente novamente.",
            )
        except Exception as send_error:
            logger.error(f"Erro enviando mensagem de erro: {send_error}")


async def process_telegram_callback(
    bot: Bot,
    chat_id: int,
    callback_query_id: str,
    callback_data: str,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Processa callback de botão inline (confirmação HITL).

    Args:
        bot: Instância do Bot do Telegram
        chat_id: ID do chat
        callback_query_id: ID do callback query (para answer_callback_query)
        callback_data: "confirm" ou "cancel"
        checkpointer: AsyncSqliteSaver
    """
    try:
        # Acknowledge callback query (remove loading spinner)
        await bot.answer_callback_query(callback_query_id)

        # Processar como mensagem normal
        # O confirm_node do LangGraph já trata "confirm"/"cancel"
        # Mas vamos mapear para português para melhor UX
        text_mapping = {
            "confirm": "sim",
            "cancel": "não",
        }
        text = text_mapping.get(callback_data, callback_data)

        await process_telegram_message(bot, chat_id, text, checkpointer)

    except Exception as e:
        logger.error(f"Erro processando callback de chat_id={chat_id}: {e}", exc_info=True)
