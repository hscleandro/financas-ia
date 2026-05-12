import asyncio
import logging
import sys
import uuid

# Garante que stdin/stdout usam UTF-8, necessário para acentos e caracteres especiais
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

from agent.graph import build_graph
from database.setup import setup_database

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

MCP_CONFIG = {
    "financas": {
        "command": "python",
        "args": ["mcp_server/server.py"],
        "transport": "stdio",
    }
}


async def run_chat() -> None:
    setup_database()

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print("=" * 50)
    print("  Assistente Financeiro Pessoal — MVP 1")
    print("  Digite 'sair' para encerrar.")
    print("=" * 50)
    print()

    client = MultiServerMCPClient(MCP_CONFIG)
    tools = await client.get_tools()
    graph = build_graph(tools)

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
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content=user_input)]},
                config=config,
            )
            last = result["messages"][-1]
            print(f"\nAssistente: {last.content}\n")
        except Exception as e:
            print(f"\nErro: {e}\n")


if __name__ == "__main__":
    asyncio.run(run_chat())
