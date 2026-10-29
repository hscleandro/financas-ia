"""Integracao HTTP da web com SQLite temporario, sem PDF privado ou rede."""
from contextlib import closing
from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from agent import category_classifier
import config
from database.setup import get_connection
from database.user_setup import create_user
from services import category_suggester, statement_parser, statement_service
from services._base import compute_hash
from services.statement_parser import CardHolder, ParsedStatement, ParsedTransaction
from web import main as web


PASSWORD = "teste123"
PDF_BYTES = b"%PDF-1.4\n% synthetic upload; parsing is mocked\n%%EOF\n"


@pytest.fixture
def sample_pdf(tmp_path):
    pdf = tmp_path / "fatura-sintetica.pdf"
    pdf.write_bytes(PDF_BYTES)
    return pdf


@pytest.fixture
def parsed_statement():
    transactions = [
        ("2026-09-10", "RESTAURANTE AURORA 0001", 5599, "3006", None),
        ("2026-09-12", "FARMACIA HISTORICO", 1299, "3006", None),
        ("2026-09-13", "LIVRARIA NUVEM", 2345, "2470", "01/03"),
        ("2026-09-14", "COMPRA SEM CATEGORIA", 401, "2470", None),
    ]
    return ParsedStatement(
        holder_name="TEST WEB",
        statement_date=date(2026, 9, 30),
        due_date=date(2026, 10, 10),
        total_cents=sum(tx[2] for tx in transactions),
        file_hash=sha256(PDF_BYTES).hexdigest(),
        file_name="fatura-sintetica.pdf",
        card_holders=[CardHolder("TEST WEB", "3006"), CardHolder("SECOND CARD", "2470")],
        transactions=[
            ParsedTransaction(
                transaction_date=date.fromisoformat(day),
                description=name,
                amount_cents=cents,
                card_holder="TEST WEB" if card == "3006" else "SECOND CARD",
                card_last_four=card,
                installment_info=installment,
                raw_line=f"{day} {name} {cents}",
            )
            for day, name, cents, card, installment in transactions
        ],
    )


@pytest.fixture
def offline_classifier(monkeypatch):
    classifier = Mock(
        side_effect=lambda description, categories: (
            "Livros" if description == "LIVRARIA NUVEM" and "Livros" in categories else None
        )
    )
    monkeypatch.setattr(category_suggester, "classify_category", classifier)
    monkeypatch.setattr(category_classifier, "classify_category", classifier)
    monkeypatch.setattr(
        category_classifier, "create_chat_model",
        Mock(side_effect=AssertionError("Os testes web nao podem criar um modelo externo.")),
    )
    return classifier


@pytest.fixture
def client_factory(test_user, tmp_path, monkeypatch, parsed_statement, offline_classifier):
    monkeypatch.setattr(config.settings, "web_auth_password", PASSWORD)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(web, "UPLOADS_DIR", uploads)
    # test_db ja cria o schema atual; o startup nao deve executar Alembic relativo ao cwd.
    monkeypatch.setattr(web, "run_migrations", Mock())

    def parse_pdf(path):
        assert Path(path).parent == uploads
        assert Path(path).read_bytes() == PDF_BYTES
        return deepcopy(parsed_statement)

    parser = Mock(side_effect=parse_pdf)
    monkeypatch.setattr(statement_parser, "parse_bradesco_statement", parser)
    monkeypatch.setattr(statement_service, "parse_bradesco_statement", parser)
    return lambda: TestClient(web.app, follow_redirects=False)


@pytest.fixture
def client(client_factory):
    with client_factory() as test_client:
        yield test_client


@pytest.fixture
def logged_client(client):
    _login(client)
    return client


def _login(client):
    response = client.post("/login", data={"password": PASSWORD}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    assert "financas_session" in client.cookies


def _rows(query, parameters=()):
    with closing(get_connection()) as conn:
        return [dict(row) for row in conn.execute(query, parameters).fetchall()]


def _insert_expense(conn, user_id, name, cents, day, category, card="3006", method="crédito"):
    cursor = conn.execute(
        """INSERT INTO expenses
           (user_id, description, amount, expense_date, category, method, hash, card_last_four, card_holder)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, name, cents / 100, day, category, method,
         compute_hash(cents / 100, name, date.fromisoformat(day)), card, "TEST WEB"),
    )
    return cursor.lastrowid


def _import_statement(client, sample_pdf, cards=("3006", "2470")):
    response = client.post(
        "/importar-fatura",
        files={"file": ("fatura.pdf", sample_pdf.read_bytes(), "application/pdf")},
        follow_redirects=False,
    )
    assert response.status_code == 200, response.text
    assert set(re.findall(r'name="selected_cards" value="(\d{4})"', response.text)) == {"3006", "2470"}
    response = client.post(
        "/selecionar-cartoes", data={"selected_cards": list(cards)}, follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    match = re.fullmatch(r"/revisar-fatura/(\d+)", response.headers["location"])
    assert match is not None
    return int(match.group(1))


def _review_data(client, statement_id):
    response = client.get(f"/api/reconciliation/{statement_id}")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert set(data) == {"state", "categories"}
    return data


def _bootstrap(response):
    assert response.status_code == 200, response.text
    match = re.search(
        r'<script\b[^>]*\bid=[\'"]reconciliation-data[\'"][^>]*>(.*?)</script>',
        response.text, re.DOTALL,
    )
    assert match is not None
    assert re.search(r'type=[\'"]application/json[\'"]', match.group(0))
    return json.loads(match.group(1))


def _batch(client, statement_id, section, action, items, request_id):
    response = client.post(
        f"/api/reconciliation/{statement_id}/batch",
        json={"section": section, "action": action, "items": items, "request_id": request_id},
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert set(data) == {"success", "processed", "state"}
    assert data["success"] is True
    return data


@pytest.fixture
def reconciliation(logged_client, sample_pdf, test_user):
    with closing(get_connection()) as conn:
        conn.execute("INSERT INTO categories (name, user_id) VALUES ('Livros', ?)", (test_user["id"],))
        matched_id = _insert_expense(
            conn, test_user["id"], "almoco informado no Telegram", 5599,
            "2026-09-09", "Alimentação",
        )
        _insert_expense(
            conn, test_user["id"], "corrida informada no Telegram", 873,
            "2026-09-08", "Transporte", card="2470",
        )
        _insert_expense(
            conn, test_user["id"], "lanche informado no Telegram", 1657,
            "2026-09-11", "Alimentação",
        )
        _insert_expense(
            conn, test_user["id"], "farmacia historico", 550,
            "2026-01-10", "Saúde", method="pix",
        )
        conn.commit()

    statement_id = _import_statement(logged_client, sample_pdf)
    state = _review_data(logged_client, statement_id)["state"]
    by_name = {item["name"]: item for item in state["items"]}
    return {
        "statement_id": statement_id,
        "history": by_name["FARMACIA HISTORICO"],
        "agent": by_name["LIVRARIA NUVEM"],
        "uncategorized": by_name["COMPRA SEM CATEGORIA"],
        "matched": by_name["RESTAURANTE AURORA 0001"],
        "bank": [item for item in state["items"] if item["section"] == "bank"],
        "matched_expense_id": matched_id,
        "expenses": _rows("SELECT * FROM expenses ORDER BY id"),
    }


def test_login_success_and_logout(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert "account-menu" not in response.text
    _login(client)
    assert client.get("/").status_code == 200
    response = client.get("/logout", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    assert client.get("/").status_code == 401


def test_login_failure(client):
    response = client.post("/login", data={"password": "errado"}, follow_redirects=False)
    assert response.status_code == 401
    assert "Senha inválida" in response.text
    assert "financas_session" not in client.cookies


def test_dashboard_without_pending_reconciliation(logged_client):
    response = logged_client.get("/")
    assert response.status_code == 200
    assert 'href="/importar-fatura"' in response.text
    assert "Nenhuma conciliação pendente" in response.text
    assert 'href="/revisar-fatura/' not in response.text


@pytest.mark.parametrize("has_pending", [False, True], ids=["no-pending", "with-pending"])
def test_account_menu_is_shared_across_authenticated_pages(logged_client, sample_pdf, has_pending):
    statement_id = _import_statement(logged_client, sample_pdf) if has_pending else None
    responses = [logged_client.get(path) for path in ("/", "/importar-fatura", "/extrato-bancario")]
    if statement_id:
        responses.append(logged_client.get(f"/revisar-fatura/{statement_id}"))
    responses.append(logged_client.post(
        "/importar-fatura", files={"file": ("fatura.pdf", sample_pdf.read_bytes(), "application/pdf")},
    ))
    responses.append(logged_client.get("/selecionar-cartoes"))

    menus = []
    for response in responses:
        assert response.status_code == 200, response.text
        assert response.context["pending"]["has_pending"] is has_pending
        header = re.search(r"<header\b[^>]*>(.*?)</header>", response.text, re.DOTALL)
        assert header is not None
        menu = re.search(r'<details class="account-menu" id="account-menu">(.*?)</details>', header[1], re.DOTALL)
        assert menu is not None
        assert response.text.count('id="account-menu"') == 1
        assert 'class="account-indicator" aria-hidden="true"' in menu[1]
        assert response.text.count("/static/account-menu.css") == 1
        assert re.search(r'<script src="[^"]*/static/account-menu.js" defer></script>', response.text)
        links = re.findall(r'<a href="([^"]+)"', menu[1])
        if has_pending:
            assert links == ["/importar-fatura", f"/revisar-fatura/{statement_id}", "/extrato-bancario"]
            assert '<span class="pending-badge">4</span>' in menu[1]
            assert "menu-disabled" not in menu[1]
        else:
            assert links == ["/importar-fatura", "/extrato-bancario"]
            assert 'aria-disabled="true" title="Nenhuma concilia\u00e7\u00e3o pendente"' in menu[1]
            assert "pending-badge" not in menu[1]
        menus.append(menu[1])
    assert len(set(menus)) == 1


def test_basic_authentication(client):
    assert client.get("/", auth=("web", "errado")).status_code == 401
    assert client.get("/", auth=("web", PASSWORD)).status_code == 200


@pytest.mark.parametrize("cards", [("3006",), ("2470",), ("3006", "2470")])
def test_import_and_select_cards_flow(logged_client, sample_pdf, parsed_statement, cards):
    statement_id = _import_statement(logged_client, sample_pdf, cards)
    state = _review_data(logged_client, statement_id)["state"]
    expected = [tx for tx in parsed_statement.transactions if tx.card_last_four in cards]
    assert {item["name"] for item in state["items"]} == {tx.description for tx in expected}
    assert {item["card_last_four"] for item in state["items"]} == set(cards)
    assert state["counts"] == {"new": len(expected), "matched": 0, "bank": 0}
    assert _rows("SELECT card_last_four FROM card_statements") == [{"card_last_four": ",".join(sorted(cards))}]
    assert not _rows("SELECT id FROM expenses")
    assert not list(web.UPLOADS_DIR.iterdir())
    statement_parser.parse_bradesco_statement.assert_called()
    statement_service.parse_bradesco_statement.assert_called()
    web.run_migrations.assert_called_once()


def test_pending_upload_can_be_resumed_and_requires_card_selection(logged_client, sample_pdf):
    response = logged_client.post(
        "/importar-fatura", files={"file": ("fatura.pdf", sample_pdf.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 200
    assert len(list(web.UPLOADS_DIR.iterdir())) == 1
    assert "3006" in logged_client.get("/selecionar-cartoes").text
    response = logged_client.post("/selecionar-cartoes", data={})
    assert response.status_code == 400
    assert "Selecione" in response.json()["detail"]
    assert not _rows("SELECT id FROM card_statements")
    response = logged_client.post("/selecionar-cartoes", data={"selected_cards": ["3006", "2470"]})
    assert response.status_code == 302
    assert not list(web.UPLOADS_DIR.iterdir())
    assert logged_client.get("/selecionar-cartoes").headers["location"] == "/importar-fatura"


def test_upload_with_cards_selected_directly(logged_client, sample_pdf):
    response = logged_client.post(
        "/importar-fatura", data={"selected_cards": ["2470"]},
        files={"file": ("fatura.pdf", sample_pdf.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 302
    data = _bootstrap(logged_client.get(response.headers["location"]))
    assert {item["card_last_four"] for item in data["state"]["items"]} == {"2470"}
    assert not list(web.UPLOADS_DIR.iterdir())


@pytest.mark.parametrize("cards", [["9999"], ["3006", "3006"]], ids=["unknown", "duplicate"])
def test_invalid_card_selection_does_not_import(logged_client, sample_pdf, cards):
    logged_client.post(
        "/importar-fatura", files={"file": ("fatura.pdf", sample_pdf.read_bytes(), "application/pdf")},
    )
    response = logged_client.post("/selecionar-cartoes", data={"selected_cards": cards})
    assert response.status_code == 400
    assert "detail" in response.json()
    assert not _rows("SELECT id FROM card_statements")
    assert not _rows("SELECT id FROM statement_transactions")
    assert not list(web.UPLOADS_DIR.iterdir())


@pytest.mark.parametrize("method", ["get", "post"])
def test_select_cards_without_upload_redirects(logged_client, method):
    response = logged_client.request(method, "/selecionar-cartoes")
    assert response.status_code == 302
    assert response.headers["location"] == "/importar-fatura"


def test_upload_rejects_non_pdf(logged_client):
    response = logged_client.post(
        "/importar-fatura", files={"file": ("fatura.txt", PDF_BYTES, "text/plain")},
    )
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]
    statement_parser.parse_bradesco_statement.assert_not_called()
    assert not list(web.UPLOADS_DIR.iterdir())


def test_upload_parser_error_cleans_temporary_file(logged_client, monkeypatch):
    monkeypatch.setattr(
        statement_parser, "parse_bradesco_statement", Mock(side_effect=ValueError("PDF sintetico invalido")),
    )
    response = logged_client.post(
        "/importar-fatura", files={"file": ("fatura.pdf", PDF_BYTES, "application/pdf")},
    )
    assert response.status_code == 400
    assert "Erro ao ler fatura" in response.json()["detail"]
    assert not list(web.UPLOADS_DIR.iterdir())
    assert not _rows("SELECT id FROM card_statements")


def test_review_bootstrap_three_sections_and_static_assets(logged_client, reconciliation):
    statement_id = reconciliation["statement_id"]
    response = logged_client.get(f"/revisar-fatura/{statement_id}")
    data = _bootstrap(response)
    assert response.headers["cache-control"] == "no-store"
    assert data == _review_data(logged_client, statement_id)
    assert {"Alimentação", "Saúde", "Livros", "Outros"} <= set(data["categories"])
    assert data["state"]["counts"] == {"new": 3, "matched": 1, "bank": 2}
    assert data["state"]["progress"] == {
        "total": 6, "pending": 6, "approved": 0, "ignored": 0, "reviewed": 0, "percent": 0.0,
    }
    for section, count in data["state"]["counts"].items():
        assert f'data-section="{section}"' in response.text
        assert re.search(rf'id="count-{section}"[^>]*>\s*{count}\s*<', response.text)
    for suffix, content_type in [("css", "text/css"), ("js", "javascript")]:
        path = f"/static/reconciliation.{suffix}"
        assert path in response.text
        asset = logged_client.get(path)
        assert asset.status_code == 200
        assert content_type in asset.headers["content-type"]
        assert asset.content


def test_state_preserves_statement_and_telegram_details(logged_client, reconciliation):
    state = _review_data(logged_client, reconciliation["statement_id"])["state"]
    matched = next(item for item in state["items"] if item["section"] == "matched")
    assert matched["id"] == f"tx:{matched['tx_id']}"
    assert matched["expense_id"] == reconciliation["matched_expense_id"]
    assert matched["name"] == "RESTAURANTE AURORA 0001"
    assert matched["bank_name"] == "almoco informado no Telegram"
    assert matched["date"] == "2026-09-10"
    assert matched["bank_date"] == "2026-09-09"
    assert matched["amount_cents"] == matched["bank_amount_cents"] == 5599
    assert matched["category"] == matched["bank_category"] == "Alimentação"
    assert reconciliation["agent"]["amount_cents"] == 2345
    assert reconciliation["agent"]["installment_info"] == "01/03"
    for item in state["items"]:
        assert type(item["amount_cents"]) is int
        if item["section"] == "bank":
            assert item["id"] == f"expense:{item['expense_id']}"
            assert item["tx_id"] is None
            assert item["name"] == item["bank_name"]
    assert _rows("SELECT * FROM expenses ORDER BY id") == reconciliation["expenses"]


def test_suggestions_use_history_then_offline_agent(logged_client, reconciliation, offline_classifier):
    historical = reconciliation["history"]
    assert historical["category"] == "Saúde"
    assert historical["category_edited"] is False
    offline_classifier.assert_not_called()
    response = logged_client.get(f"/api/suggest-category/{historical['tx_id']}")
    assert response.status_code == 200
    assert response.json() == {"category": "Saúde"}
    offline_classifier.assert_not_called()

    agent = reconciliation["agent"]
    assert agent["category"] is None
    response = logged_client.get(f"/api/suggest-category/{agent['tx_id']}")
    assert response.status_code == 200
    assert response.json() == {"category": "Livros"}
    assert offline_classifier.call_count == 1
    assert offline_classifier.call_args.args[0] == agent["name"]
    assert "Livros" in offline_classifier.call_args.args[1]
    state = _review_data(logged_client, reconciliation["statement_id"])["state"]
    suggested = next(item for item in state["items"] if item["id"] == agent["id"])
    assert suggested["category"] == "Livros"
    assert suggested["category_edited"] is False
    assert logged_client.get(f"/api/suggest-category/{agent['tx_id']}").json() == {"category": "Livros"}
    assert offline_classifier.call_count == 1
    unknown = reconciliation["uncategorized"]
    assert logged_client.get(f"/api/suggest-category/{unknown['tx_id']}").json() == {"category": None}
    assert _rows("SELECT * FROM expenses ORDER BY id") == reconciliation["expenses"]


@pytest.mark.parametrize("category,expected", [("  sAúDe  ", "Saúde"), ("", None), ("   ", None)])
def test_manual_category_including_clear_blocks_suggestion(
    logged_client, reconciliation, offline_classifier, category, expected,
):
    statement_id = reconciliation["statement_id"]
    item = reconciliation["history"]
    response = logged_client.post(
        f"/api/reconciliation/{statement_id}/category", json={"id": item["id"], "category": category},
    )
    assert response.status_code == 200
    assert response.json() == {"success": True, "updated": True, "category": expected}
    assert logged_client.get(f"/api/suggest-category/{item['tx_id']}").json() == {"category": expected}
    offline_classifier.assert_not_called()
    state = _review_data(logged_client, statement_id)["state"]
    current = next(row for row in state["items"] if row["id"] == item["id"])
    assert current["category"] == expected
    assert current["category_edited"] is True
    assert _rows("SELECT selected_category FROM statement_transactions WHERE id = ?", (item["tx_id"],)) == [
        {"selected_category": expected},
    ]
    assert _rows("SELECT * FROM expenses ORDER BY id") == reconciliation["expenses"]


@pytest.mark.parametrize("choice", ["Saúde", "", "ignore"], ids=["manual", "clear", "terminal"])
def test_late_suggestion_does_not_overwrite_newer_decision(logged_client, reconciliation, monkeypatch, choice):
    statement_id = reconciliation["statement_id"]
    item = reconciliation["agent"]

    def delayed_suggestion(_suggester, _description):
        # Uma segunda requisicao salva a decisao enquanto a sugestao esta em andamento.
        if choice == "ignore":
            _batch(logged_client, statement_id, "new", "ignore", [{"id": item["id"]}], "late-ignore")
        else:
            response = logged_client.post(
                f"/api/reconciliation/{statement_id}/category", json={"id": item["id"], "category": choice},
            )
            assert response.status_code == 200
        return "Livros"

    monkeypatch.setattr(category_suggester.CategorySuggester, "suggest", delayed_suggestion)
    response = logged_client.get(f"/api/suggest-category/{item['tx_id']}")
    assert response.status_code == 200
    expected = "Saúde" if choice == "Saúde" else None
    assert response.json() == {"category": expected}
    state = _review_data(logged_client, statement_id)["state"]
    current = next(row for row in state["items"] + state["history"] if row["id"] == item["id"])
    assert current["category"] == expected
    if choice == "ignore":
        assert current["decision"] == "ignored"
        assert logged_client.get(f"/api/suggest-category/{item['tx_id']}").status_code == 409
    else:
        assert current["category_edited"] is True


def test_approve_new_uses_saved_category_and_inserts_exact_expense(logged_client, reconciliation, test_user):
    item = reconciliation["agent"]
    statement_id = reconciliation["statement_id"]
    response = logged_client.post(
        f"/api/reconciliation/{statement_id}/category", json={"id": item["id"], "category": "Livros"},
    )
    assert response.status_code == 200
    result = _batch(logged_client, statement_id, "new", "approve", [{"id": item["id"]}], "insert-saved")
    assert result["processed"] == 1
    assert result["state"]["counts"] == {"new": 2, "matched": 1, "bank": 2}
    reviewed = result["state"]["history"][0]
    assert reviewed["id"] == item["id"]
    assert reviewed["decision"] == "approved"
    expense = _rows("SELECT * FROM expenses WHERE id = ?", (reviewed["expense_id"],))[0]
    assert expense["user_id"] == test_user["id"]
    assert expense["description"] == item["name"]
    assert expense["expense_date"] == item["date"]
    assert expense["amount"] == 23.45
    assert expense["category"] == "Livros"
    assert expense["method"] == "crédito"
    assert expense["card_last_four"] == "2470"
    assert expense["statement_id"] == statement_id
    assert expense["deleted_at"] is None
    assert len(_rows("SELECT id FROM expenses")) == len(reconciliation["expenses"]) + 1
    assert logged_client.get(f"/api/suggest-category/{item['tx_id']}").status_code == 409
    assert logged_client.post(
        f"/api/reconciliation/{statement_id}/category", json={"id": item["id"], "category": "Outros"},
    ).status_code == 400


@pytest.mark.parametrize("section", ["matched", "bank"])
@pytest.mark.parametrize("edit_category", [False, True], ids=["preserve", "edit-category"])
def test_approve_existing_only_changes_explicit_category(logged_client, reconciliation, section, edit_category):
    item = reconciliation["matched"] if section == "matched" else reconciliation["bank"][0]
    statement_id = reconciliation["statement_id"]
    if edit_category:
        response = logged_client.post(
            f"/api/reconciliation/{statement_id}/category", json={"id": item["id"], "category": "Outros"},
        )
        assert response.status_code == 200
        assert _rows("SELECT * FROM expenses ORDER BY id") == reconciliation["expenses"]
    selection = {"id": item["id"]}
    if section == "matched":
        selection["expense_id"] = item["expense_id"]
    result = _batch(logged_client, statement_id, section, "approve", [selection], "approve-existing")
    assert result["processed"] == 1
    assert result["state"]["history"][0]["decision"] == "approved"
    expected = deepcopy(reconciliation["expenses"])
    if edit_category:
        next(row for row in expected if row["id"] == item["expense_id"])["category"] = "Outros"
    assert _rows("SELECT * FROM expenses ORDER BY id") == expected
    if section == "matched":
        reviewed = result["state"]["history"][0]
        assert reviewed["name"] == item["name"]
        assert reviewed["bank_name"] == item["bank_name"]
        assert reviewed["bank_date"] == item["bank_date"]
        assert reviewed["bank_category"] == item["bank_category"]


@pytest.mark.parametrize("section", ["new", "matched", "bank"])
def test_ignore_never_inserts_deletes_or_changes_expenses(logged_client, reconciliation, section):
    statement_id = reconciliation["statement_id"]
    state = _review_data(logged_client, statement_id)["state"]
    selections = [{"id": item["id"]} for item in state["items"] if item["section"] == section]
    result = _batch(logged_client, statement_id, section, "ignore", selections, f"ignore-{section}")
    assert result["processed"] == len(selections)
    assert result["state"]["counts"][section] == 0
    assert result["state"]["progress"]["ignored"] == len(selections)
    assert {item["id"] for item in result["state"]["history"]} == {item["id"] for item in selections}
    assert all(item["decision"] == "ignored" for item in result["state"]["history"])
    assert _rows("SELECT * FROM expenses ORDER BY id") == reconciliation["expenses"]
    assert not _rows("SELECT id FROM audit_log")


def test_batch_invalid_category_rolls_back_all_decisions(logged_client, reconciliation):
    statement_id = reconciliation["statement_id"]
    before = _review_data(logged_client, statement_id)
    payload = {
        "section": "new", "action": "approve", "request_id": "atomic-category",
        "items": [
            {"id": reconciliation["agent"]["id"], "category": "Livros"},
            {"id": reconciliation["uncategorized"]["id"], "category": "Nao cadastrada"},
        ],
    }
    response = logged_client.post(f"/api/reconciliation/{statement_id}/batch", json=payload)
    assert response.status_code == 400
    assert "Categoria inválida" in response.json()["detail"]
    assert _review_data(logged_client, statement_id) == before
    assert _rows("SELECT * FROM expenses ORDER BY id") == reconciliation["expenses"]
    assert not _rows("SELECT id FROM statement_review_batches")
    assert not _rows("SELECT id FROM statement_transactions WHERE status != 'pending'")

    payload["items"][1]["category"] = "Outros"
    response = logged_client.post(f"/api/reconciliation/{statement_id}/batch", json=payload)
    assert response.status_code == 200
    assert response.json()["processed"] == 2


def test_batch_retry_is_idempotent_and_request_id_cannot_be_reused(logged_client, reconciliation):
    statement_id = reconciliation["statement_id"]
    selections = [
        {"id": reconciliation["history"]["id"]},
        {"id": reconciliation["agent"]["id"], "category": "Livros"},
    ]
    first = _batch(logged_client, statement_id, "new", "approve", selections, "idempotent")
    expenses = _rows("SELECT * FROM expenses ORDER BY id")
    retry = _batch(logged_client, statement_id, "new", "approve", list(reversed(selections)), "idempotent")
    assert retry == first
    assert first["processed"] == 2
    assert len(expenses) == len(reconciliation["expenses"]) + 2
    assert _rows("SELECT * FROM expenses ORDER BY id") == expenses
    assert len(_rows("SELECT id FROM statement_review_batches")) == 1
    repeat = _batch(logged_client, statement_id, "new", "approve", selections, "same-decision")
    assert repeat["processed"] == 0
    assert repeat["state"] == first["state"]
    response = logged_client.post(
        f"/api/reconciliation/{statement_id}/batch",
        json={"section": "new", "action": "ignore", "items": selections, "request_id": "idempotent"},
    )
    assert response.status_code == 400
    assert "request_id" in response.json()["detail"]
    assert _review_data(logged_client, statement_id)["state"] == first["state"]
    assert _rows("SELECT * FROM expenses ORDER BY id") == expenses


def test_dashboard_resumes_when_only_bank_items_remain(logged_client, reconciliation):
    statement_id = reconciliation["statement_id"]
    initial = _review_data(logged_client, statement_id)["state"]
    dashboard = logged_client.get("/")
    assert dashboard.status_code == 200
    assert f'href="/revisar-fatura/{statement_id}"' in dashboard.text
    assert re.search(r'Revisar conciliação\s*<span[^>]*>6</span>', dashboard.text)
    for section in ("new", "matched"):
        items = [{"id": item["id"]} for item in initial["items"] if item["section"] == section]
        _batch(logged_client, statement_id, section, "ignore", items, f"finish-{section}")
    state = _review_data(logged_client, statement_id)["state"]
    assert state["counts"] == {"new": 0, "matched": 0, "bank": 2}
    assert not _rows("SELECT id FROM statement_transactions WHERE status = 'pending'")
    assert _rows("SELECT status FROM card_statements WHERE id = ?", (statement_id,)) == [{"status": "pending"}]
    dashboard = logged_client.get("/")
    assert f'href="/revisar-fatura/{statement_id}"' in dashboard.text
    assert re.search(r'Revisar conciliação\s*<span[^>]*>2</span>', dashboard.text)
    result = _batch(
        logged_client, statement_id, "bank", "ignore",
        [{"id": item["id"]} for item in state["items"]], "finish-bank",
    )
    assert result["state"]["progress"] == {
        "total": 6, "pending": 0, "approved": 0, "ignored": 6, "reviewed": 6, "percent": 100.0,
    }
    assert _rows("SELECT status FROM card_statements WHERE id = ?", (statement_id,)) == [{"status": "confirmed"}]
    assert f'href="/revisar-fatura/{statement_id}"' not in logged_client.get("/").text
    assert _rows("SELECT * FROM expenses ORDER BY id") == reconciliation["expenses"]


def test_refresh_and_new_client_relogin_preserve_decisions_and_drafts(
    logged_client, client_factory, reconciliation, sample_pdf, offline_classifier,
):
    statement_id = reconciliation["statement_id"]
    _batch(
        logged_client, statement_id, "new", "approve",
        [{"id": reconciliation["history"]["id"]}], "persist-approval",
    )
    _batch(
        logged_client, statement_id, "bank", "ignore",
        [{"id": reconciliation["bank"][0]["id"]}], "persist-ignore",
    )
    for key, category in [("agent", "Livros"), ("matched", "")]:
        response = logged_client.post(
            f"/api/reconciliation/{statement_id}/category",
            json={"id": reconciliation[key]["id"], "category": category},
        )
        assert response.status_code == 200
    expected = _review_data(logged_client, statement_id)
    expenses = _rows("SELECT * FROM expenses ORDER BY id")
    assert _bootstrap(logged_client.get(f"/revisar-fatura/{statement_id}")) == expected
    assert len(expected["state"]["history"]) == 2

    with client_factory() as refreshed:
        assert refreshed.get(f"/api/reconciliation/{statement_id}").status_code == 401
        _login(refreshed)
        assert _review_data(refreshed, statement_id) == expected
        assert _bootstrap(refreshed.get(f"/revisar-fatura/{statement_id}")) == expected
        assert refreshed.get(f"/api/suggest-category/{reconciliation['agent']['tx_id']}").json() == {"category": "Livros"}
        assert refreshed.get(f"/api/suggest-category/{reconciliation['matched']['tx_id']}").json() == {"category": None}
        assert _import_statement(refreshed, sample_pdf) == statement_id
        assert _review_data(refreshed, statement_id) == expected
    offline_classifier.assert_not_called()
    assert _rows("SELECT * FROM expenses ORDER BY id") == expenses
    assert len(_rows("SELECT id FROM card_statements")) == 1


@pytest.mark.parametrize("endpoint", ["page", "state", "batch", "category", "suggest"])
def test_reconciliation_requires_authentication(logged_client, reconciliation, endpoint):
    statement_id = reconciliation["statement_id"]
    item = reconciliation["agent"]
    before = _review_data(logged_client, statement_id)
    logged_client.cookies.clear()
    if endpoint == "batch":
        response = logged_client.post(
            f"/api/reconciliation/{statement_id}/batch",
            json={"section": "new", "action": "ignore", "items": [{"id": item["id"]}], "request_id": "anonymous"},
        )
    elif endpoint == "category":
        response = logged_client.post(
            f"/api/reconciliation/{statement_id}/category", json={"id": item["id"], "category": "Outros"},
        )
    else:
        path = {
            "page": f"/revisar-fatura/{statement_id}",
            "state": f"/api/reconciliation/{statement_id}",
            "suggest": f"/api/suggest-category/{item['tx_id']}",
        }[endpoint]
        response = logged_client.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"
    _login(logged_client)
    assert _review_data(logged_client, statement_id) == before
    assert _rows("SELECT * FROM expenses ORDER BY id") == reconciliation["expenses"]


def test_cross_user_statements_items_categories_and_history_are_isolated(
    logged_client, client_factory, reconciliation, sample_pdf, test_user,
):
    own_id = reconciliation["statement_id"]
    with closing(get_connection()) as conn:
        other_id = create_user(conn, telegram_id=888888888, name="Other Web User")
        conn.execute("INSERT INTO categories (name, user_id) VALUES ('Categoria Privada', ?)", (other_id,))
        _insert_expense(
            conn, other_id, "LIVRARIA NUVEM", 7701, "2026-01-10", "Categoria Privada", method="pix",
        )
        conn.commit()
    own_before = _review_data(logged_client, own_id)
    assert "Categoria Privada" not in own_before["categories"]
    assert reconciliation["agent"]["category"] is None

    # O login usa o primeiro usuario ativo; a sessao anterior continua vinculada ao dono.
    with closing(get_connection()) as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (test_user["id"],))
        conn.commit()
    with client_factory() as other:
        _login(other)
        with closing(get_connection()) as conn:
            conn.execute("UPDATE users SET is_active = 1 WHERE id = ?", (test_user["id"],))
            conn.commit()
        other_statement = _import_statement(other, sample_pdf)
        assert other_statement != own_id
        other_data = _review_data(other, other_statement)
        assert "Categoria Privada" in other_data["categories"]
        assert "Livros" not in other_data["categories"]
        other_item = next(item for item in other_data["state"]["items"] if item["name"] == "LIVRARIA NUVEM")
        assert other_item["category"] == "Categoria Privada"
        for actor, foreign_statement, foreign_item in [
            (logged_client, other_statement, other_item),
            (other, own_id, reconciliation["agent"]),
        ]:
            assert actor.get(f"/revisar-fatura/{foreign_statement}").status_code == 404
            assert actor.get(f"/api/reconciliation/{foreign_statement}").status_code == 404
            assert actor.get(f"/api/suggest-category/{foreign_item['tx_id']}").status_code == 404
            response = actor.post(
                f"/api/reconciliation/{foreign_statement}/category",
                json={"id": foreign_item["id"], "category": "Outros"},
            )
            assert response.status_code == 400
            response = actor.post(
                f"/api/reconciliation/{foreign_statement}/batch",
                json={"section": "new", "action": "ignore", "items": [{"id": foreign_item["id"]}], "request_id": "foreign"},
            )
            assert response.status_code == 400
        response = logged_client.post(
            f"/api/reconciliation/{own_id}/batch",
            json={"section": "new", "action": "ignore", "items": [{"id": other_item["id"]}], "request_id": "foreign-item"},
        )
        assert response.status_code == 400
        response = logged_client.post(
            f"/api/reconciliation/{own_id}/category",
            json={"id": reconciliation["agent"]["id"], "category": "Categoria Privada"},
        )
        assert response.status_code == 400
        assert _review_data(other, other_statement) == other_data
        assert f'href="/revisar-fatura/{own_id}"' not in other.get("/").text
    assert _review_data(logged_client, own_id) == own_before
    assert not _rows("SELECT id FROM statement_review_batches")


@pytest.mark.parametrize(
    "changes",
    [
        {"section": "statement"}, {"action": "delete"}, {"items": []},
        {"items": "tx:1"}, {"items": [{}]}, {"request_id": ""},
        {"request_id": "x" * 129}, {"unexpected": True},
        {"items": [{"id": "1"}]}, {"items": [{"id": "tx:0"}]},
        {"items": [{"id": "tx:-1"}]}, {"items": [{"id": "tx:01"}]},
        {"items": [{"id": "tx:1", "extra": "not allowed"}]},
        {"items": [{"id": "tx:1", "category": 123}]},
        {"items": [{"id": "tx:1", "category": "x" * 201}]},
        {"items": [{"id": "tx:1", "expense_id": True}]},
        {"items": [{"id": "tx:1", "expense_id": "1"}]},
        {"items": [{"id": "tx:1", "expense_id": 0}]},
    ],
    ids=[
        "section", "action", "empty-items", "non-list", "missing-id", "empty-request-id",
        "long-request-id", "extra-batch-field", "unprefixed-id", "zero-id", "negative-id",
        "leading-zero-id", "extra-item-field", "numeric-category", "long-category",
        "boolean-expense-id", "string-expense-id", "zero-expense-id",
    ],
)
def test_malformed_batch_is_rejected_without_changes(logged_client, reconciliation, changes):
    statement_id = reconciliation["statement_id"]
    before = _review_data(logged_client, statement_id)
    payload = {
        "section": "new", "action": "ignore",
        "items": [{"id": reconciliation["agent"]["id"]}], "request_id": "malformed",
        **changes,
    }
    response = logged_client.post(f"/api/reconciliation/{statement_id}/batch", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]
    assert _review_data(logged_client, statement_id) == before
    assert _rows("SELECT * FROM expenses ORDER BY id") == reconciliation["expenses"]
    assert not _rows("SELECT id FROM statement_review_batches")


@pytest.mark.parametrize(
    "case",
    ["unknown-tx", "unknown-expense", "duplicate", "wrong-prefix", "wrong-tab", "invalid-match", "null-category", "blank-request-id", "missing-category"],
)
def test_invalid_batch_items_return_errors_without_partial_decisions(logged_client, reconciliation, case):
    statement_id = reconciliation["statement_id"]
    before = _review_data(logged_client, statement_id)
    item_id = reconciliation["agent"]["id"]
    section, action = "new", "ignore"
    selections = [{"id": item_id}]
    request_id = "invalid-item"
    if case == "unknown-tx":
        selections.append({"id": "tx:999999999"})
    elif case == "unknown-expense":
        section, selections = "bank", [{"id": "expense:999999999"}]
    elif case == "duplicate":
        selections.append({"id": item_id})
    elif case == "wrong-prefix":
        selections = [{"id": reconciliation["bank"][0]["id"]}]
    elif case == "wrong-tab":
        selections = [{"id": reconciliation["matched"]["id"]}]
    elif case == "invalid-match":
        section, action = "matched", "approve"
        selections = [{"id": reconciliation["matched"]["id"], "expense_id": reconciliation["bank"][0]["expense_id"]}]
    elif case == "null-category":
        selections[0]["category"] = None
    elif case == "blank-request-id":
        request_id = "   "
    elif case == "missing-category":
        action = "approve"
    response = logged_client.post(
        f"/api/reconciliation/{statement_id}/batch",
        json={"section": section, "action": action, "items": selections, "request_id": request_id},
    )
    assert response.status_code == 400
    assert response.json()["detail"]
    assert _review_data(logged_client, statement_id) == before
    assert _rows("SELECT * FROM expenses ORDER BY id") == reconciliation["expenses"]
    assert not _rows("SELECT id FROM statement_review_batches")


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"id": "tx:999999999", "category": "Outros"}, 400),
        ({"id": "expense:999999999", "category": "Outros"}, 400),
        ({"id": "invalid", "category": "Outros"}, 422),
        ({"category": "Outros"}, 422),
        ({"id": "tx:1"}, 422),
        ({"id": "tx:1", "category": None}, 422),
        ({"id": "tx:1", "category": "Outros", "extra": True}, 422),
    ],
)
def test_category_endpoint_rejects_invalid_input(logged_client, reconciliation, payload, status):
    statement_id = reconciliation["statement_id"]
    before = _review_data(logged_client, statement_id)
    response = logged_client.post(f"/api/reconciliation/{statement_id}/category", json=payload)
    assert response.status_code == status
    assert response.json()["detail"]
    assert _review_data(logged_client, statement_id) == before
    assert _rows("SELECT * FROM expenses ORDER BY id") == reconciliation["expenses"]


def test_invalid_json_and_missing_statement_return_http_errors(logged_client):
    for endpoint in ("batch", "category"):
        response = logged_client.post(
            f"/api/reconciliation/999999999/{endpoint}",
            content=b"{not json", headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
    assert logged_client.get("/revisar-fatura/999999999").status_code == 404
    assert logged_client.get("/api/reconciliation/999999999").status_code == 404
    assert logged_client.get("/api/suggest-category/999999999").status_code == 404
    response = logged_client.post(
        "/api/reconciliation/999999999/batch",
        json={"section": "new", "action": "ignore", "items": [{"id": "tx:1"}], "request_id": "missing-statement"},
    )
    assert response.status_code == 400
    assert not _rows("SELECT id FROM statement_review_batches")


def test_review_bootstrap_escapes_script_breakout(logged_client, sample_pdf, parsed_statement):
    malicious = '</script><script id="injected">alert("xss")</script><img src=x onerror=alert(1)>'
    parsed_statement.transactions[0].description = malicious
    statement_id = _import_statement(logged_client, sample_pdf)
    response = logged_client.get(f"/revisar-fatura/{statement_id}")
    data = _bootstrap(response)
    assert any(item["name"] == malicious for item in data["state"]["items"])
    assert data == _review_data(logged_client, statement_id)
    assert malicious not in response.text
    assert '<script id="injected">' not in response.text
    assert "<img src=x" not in response.text
    assert r"\u003c/script\u003e\u003cscript" in response.text
