from typing import Annotated

from langchain_core.messages import AnyMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from agent.prompts import get_system_prompt
from config import settings


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def build_graph(tools: list):
    llm = ChatOpenAI(
        model=settings.openai_model,
        temperature=0,
        api_key=settings.openai_api_key,
    )
    llm_with_tools = llm.bind_tools(tools)
    system_prompt = get_system_prompt()

    async def agent_node(state: AgentState) -> dict:
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    def should_call_tools(state: AgentState) -> str:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tool_node"
        return END

    tool_node = ToolNode(tools=tools)

    graph = StateGraph(AgentState)
    graph.add_node("agent_node", agent_node)
    graph.add_node("tool_node", tool_node)

    graph.add_edge(START, "agent_node")
    graph.add_conditional_edges("agent_node", should_call_tools)
    graph.add_edge("tool_node", "agent_node")

    return graph.compile(checkpointer=MemorySaver())
