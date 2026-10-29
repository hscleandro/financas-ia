"""Contrato HTTP/HTML do dashboard com SQLite sintetico, sem executar JavaScript."""

from contextlib import closing
from dataclasses import dataclass
from datetime import date
from functools import partial
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

import config
from database.setup import get_connection
from database.user_setup import create_user
from services._base import compute_hash
from services.expense_service import ExpenseService
from services.statement_service import StatementService
from web import main as web
from web.dashboard import build_dashboard_data


TODAY = date(2026, 10, 27)
PASSWORD = "dashboard-offline-password"


@dataclass(eq=False)
class _Element:
    tag: str
    attrs: dict
    ancestors: tuple
    text: str = ""


class _HTML(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.stack = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        element = _Element(tag, dict(attrs), tuple(self.stack))
        self.elements.append(element)
        if tag not in {
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr",
        }:
            self.stack.append(element)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        for element in self.stack:
            element.text += data

    def find(self, tag=None, *, id=None, class_=None, within=None):
        return [
            element for element in self.elements
            if (tag is None or element.tag == tag)
            and (id is None or element.attrs.get("id") == id)
            and (class_ is None or class_ in element.attrs.get("class", "").split())
            and (within is None or within in element.ancestors)
        ]

    def one(self, tag=None, **filters):
        elements = self.find(tag, **filters)
        assert len(elements) == 1, (tag, filters, len(elements))
        return elements[0]


def _dashboard(response):
    assert response.status_code == 200, response.text
    page = _HTML(response.text)
    bootstrap = page.one("script", id="dashboard-data")
    assert bootstrap.attrs.get("type") == "application/json"
    return page, json.loads(bootstrap.text)


@pytest.fixture
def client(test_user, monkeypatch):
    monkeypatch.setattr(config.settings, "web_auth_password", PASSWORD)
    monkeypatch.setattr(web, "run_migrations", lambda: None)
    monkeypatch.setattr(web, "build_dashboard_data", partial(build_dashboard_data, today=TODAY))
    with TestClient(web.app, follow_redirects=False) as test_client:
        yield test_client


@pytest.fixture
def logged_client(client):
    response = client.post("/login", data={"password": PASSWORD})
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    return client


@pytest.fixture
def expense_service(test_user):
    with closing(get_connection()) as conn:
        yield ExpenseService(conn, user_id=test_user["id"])


@pytest.fixture
def add_expense(expense_service):
    def insert(
        amount, day="2026-10-27", description="Despesa ORIGINAL / 001",
        category="Lazer", method="pix", *, user_id=None, deleted_at=None,
    ):
        cursor = expense_service.conn.execute(
            """INSERT INTO expenses
               (user_id, amount, description, category, method, expense_date,
                hash, created_at, deleted_at, card_last_four)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                expense_service.user_id if user_id is None else user_id,
                amount, description, category, method, day,
                compute_hash(amount, description, date.fromisoformat(day)),
                "2026-10-27 12:00:00", deleted_at, "3006",
            ),
        )
        expense_service.conn.commit()
        return cursor.lastrowid

    return insert


@pytest.fixture
def category_catalog(expense_service):
    other_id = create_user(expense_service.conn, 888888888, "Outro usuario")
    expense_service.conn.executemany(
        "INSERT INTO categories (name, user_id) VALUES (?, ?)",
        [("Global Extra", None), ("Projetos", expense_service.user_id), ("Segredo", other_id)],
    )
    expense_service.conn.commit()
    return other_id


@pytest.fixture
def pending_statement(expense_service, add_expense):
    add_expense(8.74, "2026-09-10", method="cr\u00e9dito")
    cursor = expense_service.conn.execute(
        """INSERT INTO card_statements
           (user_id, file_hash, file_name, statement_date, due_date, card_last_four)
           VALUES (?, 'dashboard-synthetic-hash', 'fatura-sintetica.pdf',
                   '2026-09-30', '2026-10-10', '3006')""",
        (expense_service.user_id,),
    )
    statement_id = cursor.lastrowid
    cursor = expense_service.conn.execute(
        """INSERT INTO statement_transactions
           (statement_id, transaction_date, description, amount_cents, card_last_four)
           VALUES (?, '2026-09-11', 'COMPRA SINTETICA', 1250, '3006')""",
        (statement_id,),
    )
    expense_service.conn.commit()
    return statement_id, cursor.lastrowid


def test_dashboard_requires_authentication(client):
    response = client.get("/", params={"period": "2026-09", "evolution_category": "Lazer"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"
    assert not _HTML(response.text).find(id="dashboard-data")


def test_dashboard_serializes_full_contract_and_renders_real_metrics(
    logged_client, expense_service, add_expense, test_user,
):
    add_expense(100, "2026-09-30")
    add_expense(1234.56, "2026-10-01", description="Mercado ABC / caixa 02")
    add_expense(
        78.90, description="UBER *Viagem", category="Transporte", method="cr\u00e9dito",
    )
    add_expense(999, "2026-10-28")
    add_expense(999, "2026-11-01")

    response = logged_client.get("/")
    page, data = _dashboard(response)

    assert response.template.name == "dashboard.html"
    assert response.context["user"]["id"] == test_user["id"]
    assert response.headers["cache-control"] == "no-store"
    assert "text/html" in response.headers["content-type"]
    assert data == response.context["dashboard_data"] == build_dashboard_data(
        expense_service, today=TODAY,
    )
    assert set(data) == {
        "period", "period_label", "period_options", "evolution_category", "categories",
        "total_cents", "expense_count", "comparison", "evolution", "category_parts",
        "payment_methods", "expenses",
    }
    assert data["period"] == "2026-10"
    assert (data["total_cents"], data["expense_count"]) == (131346, 2)

    metrics = page.one(class_="metrics")
    assert [card.attrs["aria-label"] for card in page.find("section", within=metrics)] == [
        "Despesas do m\u00eas", "Lan\u00e7amentos do m\u00eas",
    ]
    assert len(page.find(class_="metric-card")) == 2
    assert page.one(id="monthly-total", within=metrics).text.strip() == "R$ 1.313,46"
    assert page.one(id="monthly-count", within=metrics).text.strip() == "2"

    layout = page.one(class_="dashboard-layout")
    sections = page.find("section", within=layout)
    assert [section.attrs["aria-labelledby"] for section in sections] == [
        "evolution-title", "category-title", "payment-title", "recent-title",
    ]
    for section in sections:
        page.one("h2", id=section.attrs["aria-labelledby"], within=section)
    assert [page.one("span", within=entry).text for entry in page.find(class_="legend-entry")] == [
        part["name"] for part in data["category_parts"]
    ]
    assert [
        (page.one("span", within=row).text, page.one("strong", within=row).text.strip())
        for row in page.find(class_="payment-method", within=page.one(id="payments"))
    ] == [("Pix", "R$ 1.234,56"), ("Cr\u00e9dito", "R$ 78,90")]


@pytest.mark.parametrize(
    "current,previous,direction,color,percentage,arrow",
    [
        (150, 100, "up", "negative", "50,0%", "\u2191"),
        (50, 100, "down", "positive", "50,0%", "\u2193"),
        (25, 0, "no_base", "muted", None, None),
        (0, 0, "same", "muted", "0,0%", None),
    ],
    ids=["increase-red", "decrease-green", "no-previous-base", "both-zero"],
)
def test_comparison_presentation(
    logged_client, add_expense, current, previous, direction, color, percentage, arrow,
):
    if previous:
        add_expense(previous, "2026-09-30")
    if current:
        add_expense(current)
    page, data = _dashboard(logged_client.get("/"))
    comparison = page.one(id="monthly-comparison")
    assert data["comparison"]["direction"] == direction
    assert set(comparison.attrs["class"].split()) == {"comparison", color}
    if percentage is None:
        assert data["comparison"]["percent"] is None
        assert comparison.text.strip() == "Sem gastos no m\u00eas anterior"
        assert "%" not in comparison.text
    else:
        assert percentage in comparison.text
    if arrow:
        assert arrow in comparison.text
    else:
        assert not any(symbol in comparison.text for symbol in ("\u2191", "\u2193"))
    if not current:
        assert page.one(id="monthly-total").text.strip() == "R$ 0,00"
        assert page.one(id="monthly-count").text.strip() == "0"


@pytest.mark.parametrize("period", ["2024-02", "2022-06"], ids=["historical", "empty-selected-month"])
def test_month_options_and_get_forms_preserve_both_selections(logged_client, add_expense, period):
    add_expense(10, "2024-02-29", category="Transporte")
    page, data = _dashboard(logged_client.get(
        "/", params={"period": period, "evolution_category": "Transporte"},
    ))
    period_form = page.one("form", class_="period-form")
    category_form = page.one("form", class_="category-form")
    period_select = page.one("select", id="period", within=period_form)
    category_select = page.one("select", id="evolution-category", within=category_form)
    assert period_select.attrs["name"] == "period"
    assert category_select.attrs["name"] == "evolution_category"
    assert len(page.find("select")) == 2
    for form in (period_form, category_form):
        assert form.attrs["method"].lower() == "get"
        assert urlsplit(form.attrs["action"]).path == "/"
        assert "data-auto-submit" in form.attrs
        fallback = page.one("noscript", within=form)
        assert page.one("button", within=fallback).attrs["type"] == "submit"
    assert urlsplit(category_form.attrs["action"]).fragment == "evolucao-mensal"
    for form, expected in (
        (period_form, {"evolution_category": "Transporte"}),
        (category_form, {"period": period}),
    ):
        assert {
            control.attrs["name"]: control.attrs["value"]
            for control in page.find("input", within=form)
            if control.attrs.get("type") == "hidden"
        } == expected

    options = page.find("option", within=period_select)
    assert [
        {"value": option.attrs["value"], "label": option.text} for option in options
    ] == data["period_options"]
    values = [option.attrs["value"] for option in options]
    assert values == sorted(set(values), reverse=True)
    assert values[0] == "2026-10"
    assert {"2025-11", "2024-02", period} <= set(values)
    assert len(values) == 12 + len({"2024-02", period})
    assert [option.attrs["value"] for option in options if "selected" in option.attrs] == [period]
    category_options = page.find("option", within=category_select)
    assert [option.attrs["value"] for option in category_options] == ["", *data["categories"]]
    assert [
        option.attrs["value"] for option in category_options if "selected" in option.attrs
    ] == ["Transporte"]
    assert data["period"] == period
    assert data["evolution_category"] == "Transporte"


def test_category_selection_only_changes_evolution_and_can_be_cleared(logged_client, add_expense):
    add_expense(20, "2026-09-01", category="Lazer")
    add_expense(30, "2026-09-30", category="Transporte")
    add_expense(10, "2026-10-01", category="Lazer")
    add_expense(90, category="Transporte")
    baseline_page, baseline = _dashboard(logged_client.get("/"))
    page, filtered = _dashboard(logged_client.get(
        "/", params={"period": "2026-10", "evolution_category": "Lazer"},
    ))
    assert filtered["evolution_category"] == "Lazer"
    assert [month["total_cents"] for month in filtered["evolution"]][-2:] == [2000, 1000]
    assert {
        key: value for key, value in filtered.items()
        if key not in {"evolution", "evolution_category"}
    } == {
        key: value for key, value in baseline.items()
        if key not in {"evolution", "evolution_category"}
    }
    for id in ("monthly-total", "monthly-count", "payments", "recent-expenses"):
        assert page.one(id=id).text == baseline_page.one(id=id).text
    cleared_page, cleared = _dashboard(logged_client.get(
        "/", params={"period": "2026-10", "evolution_category": ""},
    ))
    assert cleared == baseline
    assert not cleared_page.find("input", within=cleared_page.one("form", class_="period-form"))


def test_evolution_renders_six_chronological_months_including_zeros(logged_client, add_expense):
    add_expense(12.34, "2026-05-01")
    add_expense(2, "2026-08-01")
    add_expense(4)
    page, data = _dashboard(logged_client.get("/"))
    assert [month["period"] for month in data["evolution"]] == [
        "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10",
    ]
    assert [month["total_cents"] for month in data["evolution"]] == [1234, 0, 0, 200, 0, 400]
    chart = page.one("section", id="evolucao-mensal")
    bars = page.find("button", class_="bar", within=chart)
    assert len(bars) == 6
    assert [label.text for label in page.find(class_="bar-label", within=chart)] == [
        month["label"] for month in data["evolution"]
    ]
    for bar, month in zip(bars, data["evolution"]):
        assert bar.attrs["data-month"] == month["full_label"]
        assert int(bar.attrs["data-total"]) == month["total_cents"]
        assert bar.attrs["aria-describedby"] == "evolution-value"
        assert month["full_label"] in bar.attrs["aria-label"]
        assert ("zero" in bar.attrs["class"].split()) == (month["total_cents"] == 0)
        height = re.fullmatch(r"height:\s*([0-9.]+)%", bar.attrs["style"])
        assert height is not None
        assert float(height.group(1)) == pytest.approx(month["height_percent"])


def test_user_scope_soft_deletes_and_category_catalog_reach_html(
    logged_client, expense_service, add_expense, category_catalog,
):
    add_expense(10, "2026-09-30", category="Global Extra")
    own_id = add_expense(20, category="Projetos")
    _, baseline = _dashboard(logged_client.get("/"))
    for day in ("2020-01-01", "2026-09-30", "2026-10-27"):
        add_expense(
            999, day, description="DESPESA DE OUTRO USUARIO",
            user_id=category_catalog, category="Segredo",
        )
        add_expense(999, day, description="DESPESA EXCLUIDA", deleted_at="2026-10-27 13:00:00")

    response = logged_client.get("/")
    page, data = _dashboard(response)
    assert data == baseline
    assert [expense["id"] for expense in data["expenses"]] == [own_id]
    category_select = page.one("select", id="evolution-category")
    categories = [option.attrs["value"] for option in page.find("option", within=category_select)]
    assert {"Global Extra", "Projetos", "Alimenta\u00e7\u00e3o"} <= set(categories)
    assert "Segredo" not in categories
    assert "DESPESA DE OUTRO USUARIO" not in response.text
    assert "DESPESA EXCLUIDA" not in response.text


@pytest.mark.parametrize("count", [0, 3, 5], ids=["empty", "initial-limit", "show-more"])
def test_recent_expenses_keep_all_original_rows_for_progressive_enhancement(
    logged_client, add_expense, count,
):
    ids = [
        add_expense((index + 1) / 100, description=f"LOJA Original / caixa {index:02d}")
        for index in range(count)
    ]
    page, data = _dashboard(logged_client.get("/"))
    recent = page.one(id="recent-expenses")
    rows = page.find(class_="item", within=recent)
    assert [expense["id"] for expense in data["expenses"]] == ids[::-1]
    assert [expense["description"] for expense in data["expenses"]] == [
        f"LOJA Original / caixa {index:02d}" for index in reversed(range(count))
    ]
    assert [int(row.attrs["data-expense-id"]) for row in rows] == ids[::-1]
    for index, (row, expense) in enumerate(zip(rows, data["expenses"])):
        name = page.one("strong", within=row)
        assert name.text == name.attrs["title"] == expense["description"]
        assert page.one("time", within=row).attrs["datetime"] == expense["date"]
        assert ("recent-extra" in row.attrs["class"].split()) == (index >= 3)
        assert not any("hidden" in element.attrs for element in (row, *row.ancestors))
        assert not page.find("button", within=row)
    if count > 3:
        show_more = page.one("button", id="show-all-expenses")
        assert show_more.attrs["type"] == "button"
        assert show_more.attrs["aria-controls"] == "recent-expenses"
        assert show_more.attrs["aria-expanded"] == "false"
        assert "hidden" in show_more.attrs
    else:
        assert not page.find(id="show-all-expenses")
    if not count:
        page.one(class_="empty-state", within=recent)


def test_account_actions_only_appear_inside_the_header_menu(logged_client):
    page, _ = _dashboard(logged_client.get("/"))
    header = page.one("header")
    menu = page.one("details", id="account-menu", class_="account-menu", within=header)
    trigger = page.one("summary", class_="account-trigger", within=menu)
    assert trigger.text.strip() == "Minha Conta"
    assert page.one("span", class_="account-indicator", within=trigger).attrs["aria-hidden"] == "true"
    assert not page.find("svg", within=trigger)
    assert "open" not in menu.attrs
    assert [link.attrs["href"] for link in page.find("a", within=menu)] == [
        "/importar-fatura", "/extrato-bancario",
    ]
    disabled = page.one(class_="menu-disabled", within=menu)
    assert disabled.attrs["aria-disabled"] == "true"
    assert disabled.text.strip() == "Revisar concilia\u00e7\u00e3o"
    for link in page.find("a"):
        if link.attrs.get("href") != "/":
            assert menu in link.ancestors
    assert not page.find(class_="pending-badge")
    assert not page.find(class_="actions")
    assert not page.find("button", within=header)


def test_menu_badge_uses_real_statement_summary_even_with_only_bank_items(
    logged_client, expense_service, pending_statement,
):
    statement_id, tx_id = pending_statement
    statements = StatementService(expense_service.conn, expense_service.user_id)
    for bank_only, count in ((False, 2), (True, 1)):
        if bank_only:
            state = statements.review_batch(
                statement_id, "new", "ignore", [{"id": f"tx:{tx_id}"}], "dashboard-ignore-new",
            )["state"]
            assert state["counts"] == {"new": 0, "matched": 0, "bank": 1}
        pending = statements.get_pending_summary()
        assert pending["pending_count"] == count
        response = logged_client.get("/")
        page, _ = _dashboard(response)
        assert response.context["pending"] == pending
        menu = page.one("details", id="account-menu", within=page.one("header"))
        links = page.find("a", within=menu)
        assert [link.attrs["href"] for link in links] == [
            "/importar-fatura", f"/revisar-fatura/{statement_id}", "/extrato-bancario",
        ]
        assert page.one(class_="pending-badge", within=links[1]).text == str(count)
        assert not page.find(class_="menu-disabled")
        for link in page.find("a"):
            if link.attrs.get("href") != "/":
                assert menu in link.ancestors
        assert not page.find(class_="actions")


def test_dashboard_css_and_javascript_are_served_locally_without_cdn(logged_client):
    response = logged_client.get("/")
    page, _ = _dashboard(response)
    stylesheets = [node for node in page.find("link") if node.attrs.get("rel") == "stylesheet"]
    scripts = [node for node in page.find("script") if "src" in node.attrs]
    assert len(stylesheets) == len(scripts) == 2
    assert all("defer" in script.attrs for script in scripts)
    for node, attribute, path, content_type in (
        (stylesheets[0], "href", "/static/dashboard.css", "text/css"),
        (stylesheets[1], "href", "/static/account-menu.css", "text/css"),
        (scripts[0], "src", "/static/account-menu.js", "javascript"),
        (scripts[1], "src", "/static/dashboard.js", "javascript"),
    ):
        url = urlsplit(node.attrs[attribute])
        assert url.netloc in ("", urlsplit(str(response.url)).netloc)
        assert url.path == path
        asset = logged_client.get(node.attrs[attribute])
        assert asset.status_code == 200
        assert content_type in asset.headers["content-type"]
        assert asset.content
        assert not re.search(r"(?:@import\s+|url\()\s*['\"]?(?:https?:)?//", asset.text)


def test_bootstrap_and_html_escape_original_descriptions_and_selected_category(
    logged_client, expense_service, add_expense,
):
    description = '</script><script id="injected">alert("xss")</script><img src=x onerror=alert(1)> & original'
    category = '</option><script id="category-injected">alert(1)</script> & "Projeto"'
    expense_service.conn.execute(
        "INSERT INTO categories (name, user_id) VALUES (?, ?)",
        (category, expense_service.user_id),
    )
    expense_service.conn.commit()
    add_expense(12.34, description=description, category=category)
    response = logged_client.get("/", params={"evolution_category": category})
    page, data = _dashboard(response)
    assert data == response.context["dashboard_data"]
    assert data["expenses"][0]["description"] == description
    assert data["expenses"][0]["category"] == data["evolution_category"] == category
    assert "<" not in page.one("script", id="dashboard-data").text
    assert description not in response.text
    assert category not in response.text
    assert "&lt;/script&gt;" in response.text
    assert not page.find("img")
    assert not page.find(id="injected")
    assert not page.find(id="category-injected")
    assert not any("onerror" in element.attrs for element in page.elements)
    name = page.one("strong", within=page.one(id="recent-expenses"))
    assert name.text == name.attrs["title"] == description
    options = page.find("option", within=page.one("select", id="evolution-category"))
    selected = [option for option in options if "selected" in option.attrs]
    assert len(selected) == 1
    assert selected[0].attrs["value"] == selected[0].text == category
    hidden = page.one("input", within=page.one("form", class_="period-form"))
    assert hidden.attrs["value"] == category


@pytest.mark.parametrize(
    "params",
    [
        {"period": "2026/10"},
        {"period": "2026-11"},
        {"period": "2026-09", "evolution_category": "Inexistente"},
        {"evolution_category": "Segredo"},
    ],
    ids=["malformed-period", "future-period", "unknown-category", "foreign-category"],
)
def test_invalid_filters_return_400_without_database_changes(
    logged_client, expense_service, category_catalog, pending_statement, params,
):
    before = expense_service.conn.serialize()
    response = logged_client.get("/", params=params)
    assert response.status_code == 400
    assert response.json()["detail"]
    assert expense_service.conn.serialize() == before
