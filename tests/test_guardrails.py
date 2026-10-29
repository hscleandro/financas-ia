"""
DT-007 — Testes de guardrails de segurança.

Cobre:
  1. test_guardrail_blocks_parallel_delete
  2. test_single_delete_passes_guardrail
  3. test_bulk_delete_prompt_refusal
  4. test_delete_without_confirmed_blocked

Adicionais para cobrir confirm_node routing e operações não-destrutivas.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.graph import (
    DESTRUCTIVE_TOOLS,
    _BULK_DELETE_MSG,
    guardrail_node,
    should_call_tools,
)
from database.setup import get_connection
from services.expense_service import ExpenseService


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_state(*tool_calls: dict) -> dict:
    """Constrói um AgentState mínimo com uma AIMessage contendo as tool_calls fornecidas."""
    return {
        "messages": [
            AIMessage(content="", tool_calls=list(tool_calls))
        ]
    }


def _delete_call(expense_id: int, tc_id: str = "tc1") -> dict:
    return {"name": "delete_expense", "id": tc_id, "args": {"expense_id": expense_id, "confirmed": False}}


def _update_call(expense_id: int, tc_id: str = "tc1") -> dict:
    return {"name": "update_expense", "id": tc_id, "args": {"expense_id": expense_id, "confirmed": False, "amount": 60.0}}


def _safe_call(tc_id: str = "tc1") -> dict:
    return {"name": "query_expenses", "id": tc_id, "args": {"keyword": "uber"}}


@pytest.fixture
def service(test_db, test_user):
    """Fixture que retorna um ExpenseService com conexão aberta."""
    conn = get_connection()
    yield ExpenseService(conn, user_id=test_user["id"])
    conn.close()


# ─── DT-007 — Teste 1: guardrail bloqueia delete paralelo ─────────────────────

def test_guardrail_blocks_parallel_delete():
    """Dois delete_expense em paralelo → should_call_tools deve rotear para guardrail_node."""
    state = _make_state(
        _delete_call(1, "tc1"),
        _delete_call(2, "tc2"),
    )
    assert should_call_tools(state) == "guardrail_node"


def test_guardrail_blocks_three_parallel_deletes():
    """Três delete_expense em paralelo → mesma lógica de bloqueio."""
    state = _make_state(
        _delete_call(1, "tc1"),
        _delete_call(2, "tc2"),
        _delete_call(3, "tc3"),
    )
    assert should_call_tools(state) == "guardrail_node"


# ─── DT-007 — Teste 2: delete único passa pelo guardrail ─────────────────────

def test_single_delete_passes_guardrail():
    """Um único delete_expense → deve ir para confirm_node, não guardrail."""
    state = _make_state(_delete_call(1))
    assert should_call_tools(state) == "confirm_node"


def test_single_update_passes_guardrail():
    """Update único → confirm_node (não guardrail)."""
    state = _make_state(_update_call(1))
    assert should_call_tools(state) == "confirm_node"


# ─── DT-007 — Teste 3: guardrail_node injeta stubs e mensagem de segurança ────

def test_bulk_delete_prompt_refusal():
    """guardrail_node deve injetar ToolMessage stub para cada delete bloqueado
    e um AIMessage com a mensagem de segurança padrão."""
    state = _make_state(
        _delete_call(1, "tc1"),
        _delete_call(2, "tc2"),
    )
    result = asyncio.run(guardrail_node(state))

    messages = result["messages"]
    tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
    ai_msgs   = [m for m in messages if isinstance(m, AIMessage)]

    # Um stub por delete bloqueado
    assert len(tool_msgs) == 2
    assert {m.tool_call_id for m in tool_msgs} == {"tc1", "tc2"}

    # Cada stub contém o campo 'tipo': 'bloqueado'
    for tm in tool_msgs:
        payload = json.loads(tm.content)
        assert payload["tipo"] == "bloqueado"

    # AIMessage com a mensagem de segurança padrão
    assert len(ai_msgs) == 1
    assert ai_msgs[0].content == _BULK_DELETE_MSG


def test_guardrail_node_stubs_preserve_tool_call_ids():
    """Os IDs dos stubs devem corresponder exatamente aos IDs das tool_calls bloqueadas."""
    ids = {"id-alpha", "id-beta", "id-gamma"}
    calls = [
        {"name": "delete_expense", "id": i, "args": {"expense_id": k, "confirmed": False}}
        for k, i in enumerate(ids)
    ]
    state = {"messages": [AIMessage(content="", tool_calls=calls)]}
    result = asyncio.run(guardrail_node(state))

    stub_ids = {m.tool_call_id for m in result["messages"] if isinstance(m, ToolMessage)}
    assert stub_ids == ids


# ─── DT-007 — Teste 4: Service Layer rejeita confirmed=False ─────────────────

def test_delete_without_confirmed_blocked(service):
    """delete_expense(confirmed=False) deve retornar erro sem tocar no banco."""
    result = service.record_expense(55.0, "almoço", "Alimentação", "dinheiro", "2026-05-10")
    expense_id = result["id"]

    result = service.delete_expense(expense_id=expense_id, confirmed=False)
    assert result["tipo"] == "nao_confirmado"


def test_update_without_confirmed_blocked(service):
    """update_expense(confirmed=False) deve retornar erro sem tocar no banco."""
    result = service.record_expense(55.0, "almoço", "Alimentação", "dinheiro", "2026-05-10")
    expense_id = result["id"]

    result = service.update_expense(expense_id=expense_id, confirmed=False, amount=999.0)
    assert result["tipo"] == "nao_confirmado"


def test_create_category_without_confirmed_blocked(service):
    """create_category(confirmed=False) deve retornar erro."""
    result = service.create_category("Nova Categoria", confirmed=False)
    assert result["tipo"] == "nao_confirmado"


# ─── Roteamento adicional ─────────────────────────────────────────────────────

def test_no_tool_calls_routes_to_end():
    """Mensagem sem tool_calls → END."""
    state = {"messages": [AIMessage(content="Tudo certo!")]}
    assert should_call_tools(state) == END


def test_safe_tool_routes_to_tool_node():
    """Tool não-destrutiva → tool_node direto."""
    state = _make_state(_safe_call())
    assert should_call_tools(state) == "tool_node"


def test_multiple_safe_tools_route_to_tool_node():
    """Múltiplas tools seguras em paralelo → tool_node."""
    state = _make_state(_safe_call("tc1"), _safe_call("tc2"))
    assert should_call_tools(state) == "tool_node"


def test_destructive_tools_constant_contains_expected_tools():
    """Garante que DESTRUCTIVE_TOOLS não foi alterada acidentalmente."""
    assert "delete_expense" in DESTRUCTIVE_TOOLS
    assert "update_expense" in DESTRUCTIVE_TOOLS


def test_guardrail_only_triggers_on_multiple_deletes_not_updates():
    """Dois update_expense paralelos NÃO devem ir para guardrail (é só delete)."""
    state = _make_state(
        _update_call(1, "tc1"),
        _update_call(2, "tc2"),
    )
    # Dois updates: o primeiro é destrutivo → confirm_node, não guardrail
    assert should_call_tools(state) == "confirm_node"
