from typing import Annotated

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage, trim_messages
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from agent.prompts import get_system_prompt
from config import settings

_BULK_DELETE_MSG = (
    "Por segurança, exclusões em massa não são permitidas.\n\n"
    "O sistema permite excluir apenas um registro por vez, "
    "mediante identificação e confirmação explícita do registro específico."
)

DESTRUCTIVE_TOOLS = {"delete_expense", "update_expense"}


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def _get_expense_for_confirm(expense_id: int) -> dict | None:
    """Lê detalhes do registro para exibir na mensagem de confirmação."""
    try:
        from database.setup import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id, amount, description, category, method, expense_date "
                "FROM expenses WHERE id = ? AND deleted_at IS NULL",
                (expense_id,),
            ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def _format_confirmation(tc: dict) -> str:
    name = tc["name"]
    args = tc.get("args", {})
    expense_id = args.get("expense_id")

    record = _get_expense_for_confirm(expense_id) if expense_id else None

    if name == "delete_expense":
        if record:
            return (
                f"Confirme a exclusão do registro:\n"
                f"  ID #{record['id']} · R$ {record['amount']:.2f} · "
                f"{record['description']} · {record['category']} · "
                f"{record['method']} · {record['expense_date']}\n\n"
                f"Tem certeza? (sim/não)"
            )
        return f"Confirme a exclusão do registro ID #{expense_id}.\n\nTem certeza? (sim/não)"

    elif name == "update_expense":
        changes = {
            k: v for k, v in args.items()
            if k not in {"expense_id", "confirmed"} and v is not None
        }
        changes_str = "\n".join(f"  {k}: → {v}" for k, v in changes.items()) if changes else "  (sem alterações)"
        header = (
            f"ID #{record['id']} · {record['description']} · {record['expense_date']}"
            if record else f"ID #{expense_id}"
        )
        return (
            f"Confirme a atualização do registro {header}:\n"
            f"{changes_str}\n\n"
            f"Confirmar? (sim/não)"
        )

    return f"Confirme a operação '{name}' no registro ID #{expense_id}. (sim/não)"


def build_graph(tools: list, checkpointer=None):
    llm = ChatOpenAI(
        model=settings.openai_model,
        temperature=0,
        api_key=settings.openai_api_key,
    )
    llm_with_tools = llm.bind_tools(tools)
    system_prompt = get_system_prompt()

    async def agent_node(state: AgentState) -> dict:
        trimmed = trim_messages(
            state["messages"],
            max_tokens=settings.max_context_messages,
            token_counter=lambda msgs: len(msgs),
            strategy="last",
            include_system=False,
            start_on="human",
        )
        messages = [SystemMessage(content=system_prompt)] + trimmed
        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    def should_call_tools(state: AgentState) -> str:
        last = state["messages"][-1]
        if not (hasattr(last, "tool_calls") and last.tool_calls):
            return END

        # Block parallel bulk delete
        delete_calls = [tc for tc in last.tool_calls if tc["name"] == "delete_expense"]
        if len(delete_calls) > 1:
            return "guardrail_node"

        # Route destructive ops through HITL interrupt
        if any(tc["name"] in DESTRUCTIVE_TOOLS for tc in last.tool_calls):
            return "confirm_node"

        return "tool_node"

    async def guardrail_node(state: AgentState) -> dict:
        """Intercepta multi-delete paralelo antes do tool_node."""
        last = state["messages"][-1]
        stubs = [
            ToolMessage(
                content='{"error": "Bloqueado: exclusão em massa não é permitida.", "tipo": "bloqueado"}',
                tool_call_id=tc["id"],
            )
            for tc in last.tool_calls
        ]
        return {"messages": stubs + [AIMessage(content=_BULK_DELETE_MSG)]}

    def confirm_node(state: AgentState) -> Command:
        """HITL via interrupt(): pausa antes de executar delete/update."""
        last = state["messages"][-1]
        destructive = [tc for tc in last.tool_calls if tc["name"] in DESTRUCTIVE_TOOLS]
        tc = destructive[0]

        # Pausa e aguarda resposta do usuário
        response = interrupt(_format_confirmation(tc))

        if response.strip().lower() in {"sim", "confirmo", "yes", "pode", "confirmar"}:
            # Substitui o AIMessage original (mesmo id → add_messages faz replace)
            patched_calls = [
                {**t, "args": {**t["args"], "confirmed": True}}
                if t["name"] in DESTRUCTIVE_TOOLS else t
                for t in last.tool_calls
            ]
            new_ai = AIMessage(content=last.content, tool_calls=patched_calls, id=last.id)
            return Command(update={"messages": [new_ai]}, goto="tool_node")
        else:
            stubs = [
                ToolMessage(
                    content='{"error": "Operação cancelada pelo usuário.", "tipo": "cancelado"}',
                    tool_call_id=t["id"],
                )
                for t in last.tool_calls
            ]
            cancel = AIMessage(content="Operação cancelada. Nenhum registro foi alterado.")
            return Command(update={"messages": stubs + [cancel]}, goto=END)

    graph = StateGraph(AgentState)
    graph.add_node("agent_node", agent_node)
    graph.add_node("tool_node", ToolNode(tools=tools))
    graph.add_node("guardrail_node", guardrail_node)
    graph.add_node("confirm_node", confirm_node)

    graph.add_edge(START, "agent_node")
    graph.add_conditional_edges("agent_node", should_call_tools)
    graph.add_edge("tool_node", "agent_node")
    graph.add_edge("guardrail_node", END)
    # confirm_node usa Command para rotear dinamicamente — sem edges fixas

    return graph.compile(checkpointer=checkpointer)
