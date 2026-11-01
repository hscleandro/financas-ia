"""Regressões dos problemas reportados no bot do Telegram (logs de 31/10 e 01/11/2026).

Cenários:
  1. Alterar categoria/valor deve ATUALIZAR o registro original, nunca duplicar
     (caso real: "4849 reais gasto com filhos" → #135 e #136 duplicados).
  2. Consultas de gastos vêm do banco (caso real: R$ 158,77 no açougue sumiu
     dos "10 últimos gastos no cartão de crédito").
  3. "Últimos gastos" excluem gastos com data futura e vêm em ordem decrescente.
  4. Compras parceladas aparecem uma vez, na data original da compra; parcelas
     individuais só quando solicitado.

As datas são relativas a date.today() para que os testes não dependam do dia
em que rodam.
"""
import asyncio
import json
from datetime import date, timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from database.setup import get_connection
from services._base import compute_hash
from services.expense_service import ExpenseService

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


def _month_start(offset: int) -> date:
    """Primeiro dia do mês deslocado `offset` meses em relação ao mês atual."""
    month_index = TODAY.year * 12 + (TODAY.month - 1) + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def conn(test_db):
    connection = get_connection()
    yield connection
    connection.close()


@pytest.fixture
def service(conn, test_user):
    svc = ExpenseService(conn, user_id=test_user["id"])
    assert svc.create_category("Filhos", confirmed=True).get("created")
    assert svc.create_category("Parentes", confirmed=True).get("created")
    return svc


def _insert_expense(conn, user_id, amount, description, category, method, expense_date,
                    created_at):
    cursor = conn.execute(
        "INSERT INTO expenses (user_id, amount, description, category, method, expense_date, "
        "hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, amount, description, category, method, expense_date.isoformat(),
         compute_hash(amount, description, expense_date), created_at),
    )
    return cursor.lastrowid


def _insert_installment_group(conn, user_id, description, category, amount, total,
                              purchase_date, parcels: dict[int, date]):
    """Cria um grupo de parcelas como o import de fatura faz (uma despesa por parcela)."""
    group_id = conn.execute(
        "INSERT INTO installment_groups (user_id, description, card_last_four, total_parcels, "
        "original_purchase_date, amount_cents) VALUES (?, ?, '3006', ?, ?, ?)",
        (user_id, description, total, purchase_date.isoformat(), round(amount * 100)),
    ).lastrowid
    expense_ids = {}
    for number, ref_date in parcels.items():
        expense_id = _insert_expense(
            conn, user_id, amount, description, category, "crédito", ref_date,
            "2000-01-01 00:00:00",
        )
        conn.execute(
            "INSERT INTO installment_parcels (group_id, parcel_number, reference_date, expense_id) "
            "VALUES (?, ?, ?, ?)",
            (group_id, number, ref_date.isoformat(), expense_id),
        )
        expense_ids[number] = expense_id
    return group_id, expense_ids


@pytest.fixture
def real_case(conn, service, test_user):
    """Reproduz o banco do log: lançamentos manuais + parcelas importadas da fatura."""
    uid = test_user["id"]
    ids = {}
    # Compras manuais (ordem de created_at igual à do log de 31/10).
    ids["acougue_158"] = _insert_expense(conn, uid, 158.77, "Açougue", "Alimentação", "crédito",
                                         YESTERDAY, "2026-01-01 18:33:05")
    ids["frigideira"] = _insert_expense(conn, uid, 99.99, "Frigideira", "Outros", "crédito",
                                        YESTERDAY, "2026-01-01 18:33:34")
    ids["hortifruti"] = _insert_expense(conn, uid, 18.09, "Hortifruti", "Alimentação", "crédito",
                                        YESTERDAY, "2026-01-01 18:34:10")
    ids["acougue_20"] = _insert_expense(conn, uid, 20.70, "Açougue", "Alimentação", "crédito",
                                        YESTERDAY, "2026-01-01 18:36:18")
    ids["diarista"] = _insert_expense(conn, uid, 200.0, "Diarista", "Serviços", "pix",
                                      YESTERDAY, "2026-01-01 18:41:17")
    ids["almoco"] = _insert_expense(conn, uid, 160.0, "Almoço", "Alimentação", "crédito",
                                    TODAY, "2026-01-02 14:27:25")
    ids["feira"] = _insert_expense(conn, uid, 12.0, "Feira", "Alimentação", "crédito",
                                   TODAY, "2026-01-02 14:39:50")
    ids["mercado_antigo"] = _insert_expense(conn, uid, 12.03, "Mercado", "Alimentação", "crédito",
                                            TODAY - timedelta(days=6), "2025-12-26 22:12:47")

    # Parcelas importadas: duas parcelas passadas e três futuras por grupo.
    ids["elaza_group"], ids["elaza"] = _insert_installment_group(
        conn, uid, "ELAZA COMERCIAL VARE", "Outros", 499.99, 10,
        TODAY - timedelta(days=170),
        {5: _month_start(-1), 6: _month_start(0), 7: _month_start(1), 8: _month_start(2),
         9: _month_start(3)},
    )
    ids["dsa_group"], ids["dsa"] = _insert_installment_group(
        conn, uid, "PAYPAL *DSA ACADEMY", "Educação", 154.45, 11,
        TODAY - timedelta(days=230),
        {7: _month_start(-1), 8: _month_start(0), 9: _month_start(1), 10: _month_start(2),
         11: _month_start(3)},
    )
    # Compra parcelada recente cujas parcelas ainda vão vencer.
    ids["geladeira_group"], ids["geladeira"] = _insert_installment_group(
        conn, uid, "Geladeira", "Outros", 1000.0, 3,
        TODAY - timedelta(days=2),
        {1: _month_start(1), 2: _month_start(2), 3: _month_start(3)},
    )
    conn.commit()
    return ids


def _active_count(conn, **filters) -> int:
    where = " AND ".join(f"{k} = ?" for k in filters)
    sql = "SELECT COUNT(*) FROM expenses WHERE deleted_at IS NULL"
    if where:
        sql += " AND " + where
    return conn.execute(sql, tuple(filters.values())).fetchone()[0]


# ─── Grafo com LLM roteirizado (sem chamadas à OpenAI) ───────────────────────

class _ScriptedLLM:
    """Substitui o chat model: devolve respostas pré-definidas em sequência."""

    def __init__(self, responses: list[AIMessage]):
        self.responses = list(responses)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        assert self.responses, "LLM roteirizado sem respostas restantes"
        return self.responses.pop(0)


def _tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def _build_scripted_graph(monkeypatch, service, user_id, responses):
    import agent.graph as graph_module
    from agent.tools import build_tools

    llm = _ScriptedLLM(responses)
    monkeypatch.setattr(graph_module, "create_chat_model", lambda: llm)
    graph = graph_module.build_graph(
        build_tools(service), checkpointer=MemorySaver(), user_id=user_id,
        categories=service.list_categories(),
    )
    return graph, llm


def _run(graph, payload, config):
    return asyncio.run(graph.ainvoke(payload, config))


def _pending(graph, config):
    return asyncio.run(graph.aget_state(config)).next


def _tool_result(result, tool_name):
    for message in reversed(result["messages"]):
        if getattr(message, "name", None) == tool_name:
            return json.loads(message.content)
    raise AssertionError(f"ToolMessage de {tool_name} não encontrado")


# ═════════════════════════════════════════════════════════════════════════════
# Cenário 1 — alteração de categoria/valor não duplica
# ═════════════════════════════════════════════════════════════════════════════

class TestScenario1NoDuplicationOnUpdate:

    def test_log_flow_high_value_confirm_then_category_change(self, monkeypatch, service, conn,
                                                              test_user):
        """Reproduz o fluxo do log: valor alto → "Sim" → "Mudei para categoria X".

        Antes: o LLM gravava (#135), perguntava "Confirmar?" e, no "Sim", gravava de
        novo com force=True (#136). Agora a confirmação acontece ANTES de gravar e
        a duplicata forçada também passa por HITL.
        """
        args = {"amount": 4849, "description": "Gasto com filhos", "category": "Parentes",
                "method": "pix"}
        graph, llm = _build_scripted_graph(monkeypatch, service, test_user["id"], [
            # Turno 1: registro de valor alto.
            _tool_call("record_expense", args, "c1"),
            AIMessage(content="✅ registrado"),
            # Turno 2: LLM tenta gravar de novo (como no log) — primeiro sem force…
            _tool_call("record_expense", args, "c2"),
            # …e depois com force=True.
            _tool_call("record_expense", {**args, "force": True}, "c3"),
            # Turno 3: correção de categoria pelo caminho correto.
            _tool_call("find_expense_candidates", {"amount": 4849}, "c4"),
            AIMessage(content="", tool_calls=[{
                "name": "update_expense", "id": "c5",
                "args": {"expense_id": None, "confirmed": False, "category": "Filhos"},
            }]),
            AIMessage(content="✅ categoria alterada"),
        ])
        config = {"configurable": {"thread_id": "t1"}}

        # Turno 1 — HITL dispara ANTES de gravar.
        result = _run(graph, {"messages": [HumanMessage("4849 reais gasto com filhos no Pix")]},
                      config)
        assert _pending(graph, config) == ("confirm_node",)
        assert "valor alto" in result["__interrupt__"][0].value
        assert _active_count(conn, amount=4849.0) == 0

        _run(graph, Command(resume="sim"), config)
        assert _active_count(conn, amount=4849.0) == 1
        original_id = conn.execute("SELECT id FROM expenses WHERE amount = 4849").fetchone()[0]

        # Turno 2 — tentativa de regravar: duplicata é barrada.
        _run(graph, {"messages": [HumanMessage("Sim")]}, config)
        result = _run(graph, Command(resume="sim"), config)  # confirma valor alto
        assert _tool_result(result, "record_expense")["tipo"] == "duplicata"
        assert _active_count(conn, amount=4849.0) == 1

        # force=True também passa por HITL e mostra o registro existente.
        interrupt_text = result["__interrupt__"][0].value
        assert "DUPLICADO" in interrupt_text
        assert f"ID #{original_id}" in interrupt_text
        _run(graph, Command(resume="não"), config)
        assert _active_count(conn, amount=4849.0) == 1

        # Turno 3 — "Mudei o gasto de 4849 para categoria filhos".
        llm.responses[1].tool_calls[0]["args"]["expense_id"] = original_id
        _run(graph, {"messages": [HumanMessage("Mudei o gasto de 4849 para categoria filhos")]},
             config)
        assert _pending(graph, config) == ("confirm_node",)
        _run(graph, Command(resume="sim"), config)

        rows = conn.execute(
            "SELECT id, category FROM expenses WHERE amount = 4849 AND deleted_at IS NULL"
        ).fetchall()
        assert [(r["id"], r["category"]) for r in rows] == [(original_id, "Filhos")]

    @pytest.mark.parametrize("changes", [
        {"category": "Filhos"},
        {"amount": 48.49},
        {"method": "crédito"},
        {"description": "Material escolar"},
        {"expense_date": YESTERDAY.isoformat()},
    ])
    def test_update_changes_original_record_in_place(self, service, conn, changes):
        created = service.record_expense(4849.0, "Gasto com filhos", "Parentes", "pix")
        before = _active_count(conn)

        result = service.update_expense(created["id"], confirmed=True, **changes)

        assert result["updated"] is True
        assert result["expense_id"] == created["id"]
        assert _active_count(conn) == before
        row = dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (created["id"],)).fetchone())
        for field, value in changes.items():
            assert row[field] == value
        audit = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE expense_id = ? AND operation = 'update'",
            (created["id"],),
        ).fetchone()[0]
        assert audit == 1

    def test_duplicate_record_points_to_update(self, service, conn):
        created = service.record_expense(4849.0, "Gasto com filhos", "Parentes", "pix")
        result = service.record_expense(4849.0, "Gasto com filhos", "Filhos", "pix")

        assert result["tipo"] == "duplicata"
        assert result["record"]["id"] == created["id"]
        assert "update_expense" in result["warning"]
        assert _active_count(conn, amount=4849.0) == 1

    def test_find_candidates_by_amount(self, service):
        created = service.record_expense(4849.0, "Gasto com filhos", "Parentes", "pix")
        service.record_expense(12.0, "Feira", "Alimentação", "crédito")

        found = service.find_expense_candidates(amount=4849)

        assert [r["id"] for r in found["records"]] == [created["id"]]

    def test_force_and_high_value_require_confirmation_routing(self):
        from agent.graph import should_call_tools

        def state(args):
            return {"messages": [_tool_call("record_expense", args, "x")]}

        base = {"amount": 50.0, "description": "x", "category": "Outros", "method": "pix"}
        assert should_call_tools(state(base)) == "tool_node"
        assert should_call_tools(state({**base, "force": True})) == "confirm_node"
        assert should_call_tools(state({**base, "amount": 1500.0})) == "confirm_node"


# ═════════════════════════════════════════════════════════════════════════════
# Cenário 2 — consultas sempre pelo banco (caso R$ 158,77)
# ═════════════════════════════════════════════════════════════════════════════

class TestScenario2QueriesFromDatabase:

    def test_root_cause_old_query_hid_the_purchase(self, service, real_case):
        """Documenta a causa: sem corte de data, parcelas futuras ocupavam o topo."""
        old_top10 = service.query_expenses(method="crédito")[:10]
        assert real_case["acougue_158"] not in [r["id"] for r in old_top10]

    def test_last_10_credit_card_includes_butcher_purchase(self, service, real_case):
        result = service.list_recent_expenses(limit=10, method="crédito")

        ids = [g["id"] for g in result["gastos"]]
        assert len(ids) == 10
        assert real_case["acougue_158"] in ids
        assert all(g["method"] == "crédito" for g in result["gastos"])

    def test_tool_reads_from_database_not_from_context(self, service, real_case, conn,
                                                       test_user):
        """A tool reflete o banco no momento da chamada (inclusive inserções recentes)."""
        from agent.tools import build_tools
        tools = {t.name: t for t in build_tools(service)}

        first = tools["list_recent_expenses"].invoke({"limit": 10, "method": "crédito"})
        new_id = _insert_expense(conn, test_user["id"], 33.33, "Padaria", "Alimentação",
                                 "crédito", TODAY, "2099-01-01 00:00:00")
        conn.commit()
        second = tools["list_recent_expenses"].invoke({"limit": 10, "method": "crédito"})

        assert new_id not in [g["id"] for g in first["gastos"]]
        assert second["gastos"][0]["id"] == new_id

    def test_search_by_amount(self, service, real_case):
        from agent.tools import build_tools
        tools = {t.name: t for t in build_tools(service)}

        found = tools["query_expenses"].invoke({"method": "crédito", "amount": 158.77})

        assert [r["id"] for r in found] == [real_case["acougue_158"]]

    def test_filter_by_category(self, service, real_case):
        result = service.list_recent_expenses(limit=10, category="Alimentação")

        assert result["gastos"]
        assert all(g["category"] == "Alimentação" for g in result["gastos"])
        assert real_case["acougue_158"] in [g["id"] for g in result["gastos"]]

    def test_filter_by_payment_method(self, service, real_case):
        result = service.list_recent_expenses(limit=10, method="pix")

        assert [g["id"] for g in result["gastos"]] == [real_case["diarista"]]


# ═════════════════════════════════════════════════════════════════════════════
# Cenário 3 — sem gastos futuros nos "últimos gastos"
# ═════════════════════════════════════════════════════════════════════════════

class TestScenario3NoFutureExpenses:

    def test_recent_excludes_future_and_is_sorted_desc(self, service, real_case):
        result = service.list_recent_expenses(limit=50, include_installments=True)

        dates = [g["expense_date"] for g in result["gastos"]]
        assert dates
        assert max(dates) <= TODAY.isoformat()
        assert dates == sorted(dates, reverse=True)

    def test_most_recent_first(self, service, real_case):
        result = service.list_recent_expenses(limit=3, method="crédito")

        assert [g["id"] for g in result["gastos"]][:2] == [real_case["feira"], real_case["almoco"]]

    def test_future_only_when_explicitly_requested(self, service, real_case):
        future_ids = {real_case["elaza"][9], real_case["dsa"][11]}

        default = service.list_recent_expenses(limit=100, include_installments=True)
        explicit = service.list_recent_expenses(limit=100, include_installments=True,
                                                include_future=True)

        assert not future_ids & {g["id"] for g in default["gastos"]}
        assert future_ids <= {g["id"] for g in explicit["gastos"]}

    def test_query_tool_defaults_to_today(self, service, real_case):
        from agent.tools import build_tools
        tools = {t.name: t for t in build_tools(service)}

        default = tools["query_expenses"].invoke({"method": "crédito"})
        explicit = tools["query_expenses"].invoke({"method": "crédito", "include_future": True})
        next_month = tools["query_expenses"].invoke({
            "start_date": _month_start(1).isoformat(),
        })

        assert max(r["expense_date"] for r in default) <= TODAY.isoformat()
        assert max(r["expense_date"] for r in explicit) > TODAY.isoformat()
        assert next_month and all(r["expense_date"] >= _month_start(1).isoformat()
                                  for r in next_month)

    def test_dashboard_service_behaviour_unchanged(self, service, real_case):
        """O dashboard web continua recebendo o período completo pedido."""
        rows = service.query_expenses(start_date=_month_start(1).isoformat(),
                                      end_date=_month_start(3).isoformat())
        assert len(rows) == 9  # 3 meses futuros × 3 grupos
        assert "parcela" not in rows[0]


# ═════════════════════════════════════════════════════════════════════════════
# Cenário 4 — compras parceladas
# ═════════════════════════════════════════════════════════════════════════════

class TestScenario4Installments:

    def test_default_shows_each_purchase_once_on_original_date(self, service, real_case):
        result = service.list_recent_expenses(limit=100, method="crédito")
        parceladas = [g for g in result["gastos"] if g.get("tipo") == "compra_parcelada"]

        by_desc = {g["description"]: g for g in parceladas}
        assert len(parceladas) == 3 == len(by_desc)
        elaza = by_desc["ELAZA COMERCIAL VARE"]
        assert elaza["expense_date"] == (TODAY - timedelta(days=170)).isoformat()
        assert elaza["parcelas"] == "10x"
        assert elaza["valor_parcela"] == 499.99
        assert elaza["valor_total"] == 4999.90
        assert elaza["parcela_atual"] == "6/10"
        # Nenhum lançamento mensal aparece como compra nova.
        parcel_ids = set(real_case["elaza"].values()) | set(real_case["dsa"].values())
        assert not parcel_ids & {g["id"] for g in result["gastos"] if g.get("tipo") != "compra_parcelada"}
        assert all(g.get("tipo") != "parcela" for g in result["gastos"])

    def test_monthly_parcels_do_not_crowd_recent_list(self, service, real_case):
        result = service.list_recent_expenses(limit=10, method="crédito")
        ids = [g["id"] for g in result["gastos"]]

        assert ids[:2] == [real_case["feira"], real_case["almoco"]]
        # Compra parcelada recente (há 2 dias) aparece na data da compra.
        geladeira = next(g for g in result["gastos"] if g["description"] == "Geladeira")
        assert geladeira["expense_date"] == (TODAY - timedelta(days=2)).isoformat()
        assert geladeira["parcelas"] == "3x"

    def test_parcels_listed_individually_when_requested(self, service, real_case):
        result = service.list_recent_expenses(limit=100, method="crédito",
                                              include_installments=True)
        parcels = [g for g in result["gastos"] if g.get("tipo") == "parcela"]

        elaza = sorted(g["parcela"] for g in parcels if g["description"] == "ELAZA COMERCIAL VARE")
        assert elaza == ["5/10", "6/10"]  # somente parcelas já lançadas até hoje
        assert all(g["expense_date"] <= TODAY.isoformat() for g in parcels)
        assert all(g.get("data_compra_original") for g in parcels)
        # Geladeira só tem parcelas futuras → não aparece sem include_future.
        assert not any(g["description"] == "Geladeira" for g in parcels)
        assert not any(g.get("tipo") == "compra_parcelada" for g in result["gastos"])

    def test_parcels_with_future_when_both_requested(self, service, real_case):
        result = service.list_recent_expenses(limit=100, include_installments=True,
                                              include_future=True)
        geladeira = sorted(g["parcela"] for g in result["gastos"] if g["description"] == "Geladeira")
        assert geladeira == ["1/3", "2/3", "3/3"]

    def test_query_tool_annotates_parcels(self, service, real_case):
        from agent.tools import build_tools
        tools = {t.name: t for t in build_tools(service)}

        rows = tools["query_expenses"].invoke({"keyword": "ELAZA"})

        assert rows and all(r["parcela"].endswith("/10") for r in rows)
