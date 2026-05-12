from typing import Annotated

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage, trim_messages
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from agent.prompts import get_system_prompt
from config import settings

_BULK_DELETE_MSG = (
    "Por segurança, exclusões em massa não são permitidas.\n\n"
    "O sistema permite excluir apenas um registro por vez, "
    "mediante identificação e confirmação explícita do registro específico."
)


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def build_graph(tools: list, checkpointer=None):
    llm = ChatOpenAI(
        model=settings.openai_model,
        temperature=0,
        api_key=settings.openai_api_key,
    )
    llm_with_tools = llm.bind_tools(tools)
    system_prompt = get_system_prompt()

    async def agent_node(state: AgentState) -> dict:
        # Trim history before sending to the LLM — full history stays in the checkpointer
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

        # Block parallel bulk delete: multiple delete_expense in a single turn
        delete_calls = [tc for tc in last.tool_calls if tc["name"] == "delete_expense"]
        if len(delete_calls) > 1:
            return "guardrail_node"

        return "tool_node"

    async def guardrail_node(state: AgentState) -> dict:
        """Intercepts unsafe multi-delete tool calls before they reach tool_node."""
        last = state["messages"][-1]
        # ToolMessage stubs are required so future turns don't see dangling tool_calls
        stubs = [
            ToolMessage(
                content='{"error": "Bloqueado: exclusão em massa não é permitida.", "tipo": "bloqueado"}',
                tool_call_id=tc["id"],
            )
            for tc in last.tool_calls
        ]
        return {"messages": stubs + [AIMessage(content=_BULK_DELETE_MSG)]}

    graph = StateGraph(AgentState)
    graph.add_node("agent_node", agent_node)
    graph.add_node("tool_node", ToolNode(tools=tools))
    graph.add_node("guardrail_node", guardrail_node)

    graph.add_edge(START, "agent_node")
    graph.add_conditional_edges("agent_node", should_call_tools)
    graph.add_edge("tool_node", "agent_node")
    graph.add_edge("guardrail_node", END)

    return graph.compile(checkpointer=checkpointer)
