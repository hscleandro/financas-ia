from typing import Annotated

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage, trim_messages
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from agent.model_factory import create_chat_model
from agent.prompts_telegram import get_telegram_system_prompt
from config import settings

_BULK_DELETE_MSG = (
    "🚫 *Exclusões em massa não são permitidas*\n\n"
    "O sistema permite excluir apenas *um registro por vez*, "
    "com confirmação explícita."
)

DESTRUCTIVE_TOOLS = {"delete_expense", "update_expense"}

# Gastos acima deste valor exigem confirmação HITL ANTES de serem gravados.
HIGH_VALUE_THRESHOLD = 1000.0

_CONFIRM_WORDS = {"sim", "confirmo", "yes", "pode", "confirmar", "s", "ok"}


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def _needs_record_confirmation(tc: dict) -> bool:
    """record_expense precisa de HITL quando força duplicata ou tem valor alto."""
    if tc.get("name") != "record_expense":
        return False
    args = tc.get("args", {}) or {}
    if args.get("force"):
        return True
    try:
        return float(args.get("amount") or 0) > HIGH_VALUE_THRESHOLD
    except (TypeError, ValueError):
        return False


def _requires_confirmation(tc: dict) -> bool:
    return tc.get("name") in DESTRUCTIVE_TOOLS or _needs_record_confirmation(tc)


def _find_identical_expense(args: dict, user_id: int | None = None) -> dict | None:
    """Procura um gasto ativo idêntico (mesmo hash) para exibir na confirmação."""
    try:
        from database.setup import get_connection
        from models.schemas import ExpenseCreate
        from services._base import compute_hash

        expense = ExpenseCreate(
            amount=args["amount"],
            description=args["description"],
            category=args.get("category") or "Outros",
            method=args.get("method") or "dinheiro",
            expense_date=args.get("expense_date"),
        )
        expense_hash = compute_hash(expense.amount, expense.description, expense.expense_date)
        query = (
            "SELECT id, amount, description, category, method, expense_date "
            "FROM expenses WHERE hash = ? AND deleted_at IS NULL"
        )
        params: list = [expense_hash]
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        with get_connection() as conn:
            row = conn.execute(query + " ORDER BY id DESC", params).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def _format_record_confirmation(tc: dict, user_id: int | None = None) -> str:
    """Mensagem de confirmação para record_expense (valor alto ou duplicata forçada)."""
    args = tc.get("args", {}) or {}
    try:
        amount_str = f"R$ {float(args.get('amount')):.2f}"
    except (TypeError, ValueError):
        amount_str = f"R$ {args.get('amount')}"
    body = (
        f"📝 {args.get('description')}\n"
        f"💰 *{amount_str}*\n"
        f"🏷️ {args.get('category')} · {args.get('method')}\n"
        f"📅 {args.get('expense_date') or 'hoje'}\n"
    )
    if args.get("force"):
        existing = _find_identical_expense(args, user_id)
        existing_str = ""
        if existing:
            existing_str = (
                f"\n⚠️ Já existe o registro *ID #{existing['id']}* "
                f"(R$ {existing['amount']:.2f} · {existing['category']} · {existing['expense_date']}).\n"
                f"Para corrigir esse registro, cancele e peça a alteração.\n"
            )
        return (
            f"➕ *Cadastrar gasto DUPLICADO?*\n\n{body}{existing_str}\n"
            f"Criar um segundo registro mesmo assim?"
        )
    return f"💰 *Confirme o gasto de valor alto*\n\n{body}\nRegistrar?"


def _get_expense_for_confirm(expense_id: int, user_id: int | None = None) -> dict | None:
    """Lê detalhes do registro para exibir na mensagem de confirmação."""
    try:
        from database.setup import get_connection
        query = (
            "SELECT id, amount, description, category, method, expense_date "
            "FROM expenses WHERE id = ? AND deleted_at IS NULL"
        )
        params: list = [expense_id]
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        with get_connection() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def _format_confirmation(tc: dict, user_id: int | None = None) -> str:
    """Formata mensagem de confirmação otimizada para Telegram."""
    name = tc["name"]
    args = tc.get("args", {})
    if name == "record_expense":
        return _format_record_confirmation(tc, user_id)
    expense_id = args.get("expense_id")

    record = _get_expense_for_confirm(expense_id, user_id) if expense_id else None

    if name == "delete_expense":
        if record:
            return (
                f"🗑️ *Confirme a exclusão*\n\n"
                f"📝 {record['description']}\n"
                f"💰 *R$ {record['amount']:.2f}*\n"
                f"🏷️ {record['category']} · {record['method']}\n"
                f"📅 {record['expense_date']}\n"
                f"🔢 ID #{record['id']}\n\n"
                f"Tem certeza?"
            )
        return f"🗑️ *Confirme a exclusão*\n\nID #{expense_id}\n\nTem certeza?"

    elif name == "update_expense":
        changes = {
            k: v for k, v in args.items()
            if k not in {"expense_id", "confirmed"} and v is not None
        }

        if record:
            header = (
                f"✏️ *Atualizar registro*\n\n"
                f"📝 {record['description']}\n"
                f"📅 {record['expense_date']}\n"
                f"🔢 ID #{record['id']}\n"
            )
        else:
            header = f"✏️ *Atualizar registro #${expense_id}*\n\n"

        if changes:
            changes_lines = []
            for k, v in changes.items():
                emoji = {"amount": "💰", "description": "📝", "category": "🏷️",
                        "method": "💳", "expense_date": "📅"}.get(k, "•")
                changes_lines.append(f"{emoji} {k}: *{v}*")
            changes_str = "\n".join(changes_lines)
        else:
            changes_str = "_(sem alterações)_"

        return f"{header}{changes_str}\n\nConfirmar?"

    return f"⚠️ Confirmar operação '{name}' no registro ID #{expense_id}?"


def should_call_tools(state: AgentState) -> str:
    """Roteador condicional — determina o próximo nó após agent_node."""
    last = state["messages"][-1]
    if not (hasattr(last, "tool_calls") and last.tool_calls):
        return END

    # Bloqueia múltiplos delete_expense em paralelo (bulk delete)
    delete_calls = [tc for tc in last.tool_calls if tc["name"] == "delete_expense"]
    if len(delete_calls) > 1:
        return "guardrail_node"

    # Operações destrutivas, gastos de valor alto e duplicatas forçadas passam por HITL
    if any(_requires_confirmation(tc) for tc in last.tool_calls):
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


def build_graph(
    tools: list,
    checkpointer=None,
    user_id: int | None = None,
    categories: list[str] | None = None,
):
    """Build LangGraph com prompt otimizado para Telegram.

    Args:
        tools: Lista de tools do LangChain
        checkpointer: AsyncSqliteSaver para persistência
        user_id: usuário dono da conversa (escopo das consultas de confirmação)
        categories: categorias de gasto do usuário, injetadas no system prompt
    """
    llm = create_chat_model()
    llm_with_tools = llm.bind_tools(tools)

    system_prompt = get_telegram_system_prompt(categories=categories)

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

    def confirm_node(state: AgentState) -> Command:
        """HITL via interrupt(): pausa antes de delete/update e antes de gravar
        gastos de valor alto ou duplicatas forçadas (record_expense)."""
        last = state["messages"][-1]
        pending = [tc for tc in last.tool_calls if _requires_confirmation(tc)]

        # Pausa e aguarda resposta do usuário
        response = interrupt(
            "\n\n———\n\n".join(_format_confirmation(tc, user_id) for tc in pending)
        )

        if str(response).strip().lower().rstrip("!. ") in _CONFIRM_WORDS:
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
            cancel = AIMessage(content="❌ *Operação cancelada*\n\nNenhum registro foi alterado.")
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
