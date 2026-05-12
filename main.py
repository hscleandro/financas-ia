import asyncio
import logging
import sys

# Garante que stdin/stdout usam UTF-8, necessário para acentos e caracteres especiais
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from alembic import command
from alembic.config import Config
from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from agent.graph import build_graph
from config import settings

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

MCP_CONFIG = {
    "financas": {
        "command": "python",
        "args": ["mcp_server/server.py"],
        "transport": "stdio",
    }
}

# Sessão única: mesmo thread_id a cada execução mantém o histórico
THREAD_ID = "default"


def run_migrations() -> None:
    """Aplica todas as migrations pendentes. Autoridade final sobre o schema."""
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


async def _invoke(graph, input_, config: dict) -> dict:
    """Invoca o grafo e trata interrupt() de confirmação em loop."""
    result = await graph.ainvoke(input_, config=config)

    while "__interrupt__" in result:
        interrupts = result["__interrupt__"]
        interrupt_msg = interrupts[0].value
        print(f"\nAssistente: {interrupt_msg}\n")

        try:
            confirm_input = input("Você: ").strip()
        except (KeyboardInterrupt, EOFError):
            raise

        if not confirm_input or confirm_input.lower() in ("sair", "exit", "quit"):
            raise SystemExit

        result = await graph.ainvoke(Command(resume=confirm_input), config=config)

    return result


async def run_chat() -> None:
    run_migrations()

    config = {"configurable": {"thread_id": THREAD_ID}}

    client = MultiServerMCPClient(MCP_CONFIG)
    tools = await client.get_tools()

    async with AsyncSqliteSaver.from_conn_string(settings.checkpoints_path) as checkpointer:
        graph = build_graph(tools, checkpointer=checkpointer)

        state = await graph.aget_state(config)
        msg_count = len(state.values.get("messages", [])) if state.values else 0

        print("=" * 50)
        print("  Assistente Financeiro Pessoal — MVP 2")
        if msg_count:
            print(f"  Sessão anterior carregada ({msg_count} mensagens).")
        else:
            print("  Nova sessão iniciada.")
        print("  Digite 'sair' para encerrar.")
        print("=" * 50)
        print()

        while True:
            try:
                user_input = input("Você: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nEncerrando...")
                break

            if not user_input:
                continue
            if user_input.lower() in ("sair", "exit", "quit"):
                print("Até logo!")
                break

            try:
                result = await _invoke(
                    graph,
                    {"messages": [HumanMessage(content=user_input)]},
                    config=config,
                )
                last = result["messages"][-1]
                print(f"\nAssistente: {last.content}\n")
            except SystemExit:
                print("Até logo!")
                break
            except Exception as e:
                print(f"\nErro: {e}\n")


if __name__ == "__main__":
    asyncio.run(run_chat())
