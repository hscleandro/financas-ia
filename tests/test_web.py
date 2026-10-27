"""Testes de integração das rotas web."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.setup import get_connection
from database.user_setup import create_or_update_user
from web.main import app


@pytest.fixture
def client(test_db, monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PASSWORD", "teste123")
    import config
    monkeypatch.setattr(config.settings, "web_auth_password", "teste123")
    with TestClient(app) as c:
        yield c


def _create_user():
    conn = get_connection()
    user = create_or_update_user(conn, telegram_id=999999999, name="Test Web")
    conn.close()
    return user


def _login(client: TestClient):
    r = client.post("/login", data={"password": "teste123"}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/"


def test_login_success(client):
    _create_user()
    _login(client)


def test_login_failure(client):
    r = client.post("/login", data={"password": "errado"}, follow_redirects=False)
    assert r.status_code == 401


def _import_statement(client, sample_pdf):
    """Faz upload e, se necessário, seleciona cartões. Retorna statement_id."""
    with open(sample_pdf, "rb") as f:
        r = client.post("/importar-fatura", files={"file": ("fatura.pdf", f, "application/pdf")})

    if r.status_code == 200:
        cards = re.findall(r'name="selected_cards" value="(\d{4})"', r.text)
        assert cards, "Nenhum cartão encontrado na página de seleção"
        r = client.post("/selecionar-cartoes", data={"selected_cards": cards}, follow_redirects=False)
        assert r.status_code == 302, f"Esperado redirect após seleção, obtido {r.status_code}"

    assert r.status_code == 302 and "/revisar-fatura/" in r.headers.get("location", "")
    match = re.search(r"/revisar-fatura/(\d+)", r.headers["location"])
    return int(match.group(1))


def test_dashboard_shows_review_button_with_pending_count(client, sample_pdf):
    _create_user()
    _login(client)
    _import_statement(client, sample_pdf)

    r = client.get("/", follow_redirects=False)
    assert r.status_code == 200
    assert "Revisar conciliação" in r.text
    match = re.search(r'Revisar conciliação\s*<span[^>]*>(\d+)</span>', r.text)
    assert match is not None
    assert int(match.group(1)) > 0


def test_import_and_select_cards_flow(client, sample_pdf):
    _create_user()
    _login(client)
    statement_id = _import_statement(client, sample_pdf)
    assert statement_id > 0


def test_review_page_lists_transactions(client, sample_pdf):
    _create_user()
    _login(client)
    statement_id = _import_statement(client, sample_pdf)

    r = client.get(f"/revisar-fatura/{statement_id}")
    assert r.status_code == 200
    assert "Só na fatura" in r.text or "Na fatura e no banco" in r.text


def test_api_approve_insert_and_reject(client, sample_pdf):
    _create_user()
    _login(client)
    statement_id = _import_statement(client, sample_pdf)

    r = client.get(f"/revisar-fatura/{statement_id}")
    tx_ids = re.findall(r'<div class="expense" data-tx-id="(\d+)" data-type="insert"', r.text)
    assert tx_ids

    # Aprova inserção
    r = client.post(f"/api/approve-insert/{tx_ids[0]}", data={"category": "Outros"})
    assert r.status_code == 200
    assert r.json()["success"] is True

    # Rejeita outra
    r = client.post(f"/api/reject/{tx_ids[1]}")
    assert r.status_code == 200
    assert r.json()["success"] is True


@pytest.fixture
def sample_pdf():
    pdf = Path("docs/Bradesco_Fatura-Tue Oct 27 2026 082503 GMT-0300 (Horário Padrão de Brasília).pdf")
    if pdf.exists():
        return pdf
    pytest.skip("PDF de fatura de exemplo não encontrado")
