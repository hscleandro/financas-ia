import json
import sqlite3
from datetime import date

import pytest

from services._base import compute_hash
from services.expense_service import ExpenseService
from web.dashboard import build_dashboard_data


TODAY = date(2026, 10, 27)


@pytest.fixture
def service(test_db, test_user):
    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    try:
        yield ExpenseService(conn, user_id=test_user["id"])
    finally:
        conn.close()


@pytest.fixture
def add_expense(service, test_user):
    def insert(
        amount,
        expense_date,
        description="Despesa original",
        category="Lazer",
        method="pix",
        created_at="2026-10-27 12:00:00",
        deleted_at=None,
        user_id=None,
    ):
        cursor = service.conn.execute(
            "INSERT INTO expenses "
            "(user_id, amount, description, category, method, expense_date, hash, created_at, deleted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                test_user["id"] if user_id is None else user_id,
                amount,
                description,
                category,
                method,
                expense_date,
                compute_hash(amount, description, date.fromisoformat(expense_date)),
                created_at,
                deleted_at,
            ),
        )
        service.conn.commit()
        return cursor.lastrowid

    return insert


@pytest.fixture
def other_user(service):
    cursor = service.conn.execute(
        "INSERT INTO users (telegram_id, name) VALUES (?, ?)",
        (888888888, "Outro usuario"),
    )
    service.conn.commit()
    return cursor.lastrowid


def test_dashboard_contract_and_current_calendar_totals(service, add_expense):
    add_expense(20.10, "2026-09-01")
    add_expense(29.90, "2026-09-30", category="Transporte")
    first_id = add_expense(10.10, "2026-10-01", description="Mercado ABC / caixa 02")
    second_id = add_expense(
        20.20, "2026-10-26", description="UBER *Viagem",
        category="Transporte", method="cr\u00e9dito",
    )
    third_id = add_expense(69.70, "2026-10-27", description="Cinema 3D")
    add_expense(999, "2026-10-28")
    add_expense(999, "2026-11-01")

    data = build_dashboard_data(service, today=TODAY)

    assert set(data) == {
        "period", "period_label", "period_options", "evolution_category", "categories",
        "evolution_method", "payment_method_options", "total_cents", "expense_count",
        "comparison", "evolution", "category_parts", "payment_methods", "expenses",
    }
    assert data["period"] == "2026-10"
    assert data["period_label"] == "Outubro 2026"
    assert data["evolution_category"] == ""
    assert data["categories"] == service.list_categories()
    assert data["total_cents"] == 10000
    assert data["expense_count"] == 3
    assert data["comparison"] == {
        "percent": 100, "direction": "up", "previous_total_cents": 5000,
    }
    assert data["category_parts"] == [
        {"name": "Lazer", "total_cents": 7980, "percent": pytest.approx(79.8), "color": "#62e6ba"},
        {"name": "Transporte", "total_cents": 2020, "percent": pytest.approx(20.2), "color": "#7daeff"},
    ]
    assert data["payment_methods"] == [
        {"name": "Pix", "total_cents": 7980, "percent": pytest.approx(79.8)},
        {"name": "Cr\u00e9dito", "total_cents": 2020, "percent": pytest.approx(20.2)},
    ]
    assert data["expenses"] == [
        {
            "id": third_id, "description": "Cinema 3D", "date": "2026-10-27",
            "date_label": "27 out", "category": "Lazer", "method": "Pix", "amount_cents": 6970,
        },
        {
            "id": second_id, "description": "UBER *Viagem", "date": "2026-10-26",
            "date_label": "26 out", "category": "Transporte", "method": "Cr\u00e9dito",
            "amount_cents": 2020,
        },
        {
            "id": first_id, "description": "Mercado ABC / caixa 02", "date": "2026-10-01",
            "date_label": "1 out", "category": "Lazer", "method": "Pix", "amount_cents": 1010,
        },
    ]
    assert data["evolution"][-2] == {
        "period": "2026-10", "label": "Out", "full_label": "Outubro 2026",
        "total_cents": 10000, "height_percent": pytest.approx(10000 / 99900 * 100), "kind": "current",
    }
    assert data["evolution"][-1] == {
        "period": "2026-11", "label": "Nov", "full_label": "Novembro 2026",
        "total_cents": 99900, "height_percent": 100, "kind": "future",
    }
    assert json.loads(json.dumps(data, ensure_ascii=False, allow_nan=False)) == data


@pytest.mark.parametrize(
    "current,previous,percent,direction",
    [
        (150, 100, 50, "up"),
        (50, 100, -50, "down"),
        (100, 100, 0, "same"),
        (0, 100, -100, "down"),
        (0, 0, 0, "same"),
        (25, 0, None, "no_base"),
        (4, 3, 100 / 3, "up"),
    ],
)
def test_comparison(service, add_expense, current, previous, percent, direction):
    if previous:
        add_expense(previous, "2026-09-01")
    if current:
        add_expense(current, "2026-10-27")

    data = build_dashboard_data(service, today=TODAY)

    assert data["comparison"]["direction"] == direction
    assert data["comparison"]["previous_total_cents"] == previous * 100
    if percent is None:
        assert data["comparison"]["percent"] is None
    else:
        assert data["comparison"]["percent"] == pytest.approx(percent)


def test_historical_month_is_complete_and_compares_previous_calendar_month(service, add_expense):
    add_expense(100, "2026-08-01")
    add_expense(20, "2026-09-01")
    last_id = add_expense(30, "2026-09-30")
    add_expense(999, "2026-10-01")

    data = build_dashboard_data(service, period="2026-09", today=TODAY)

    assert data["total_cents"] == 5000
    assert data["expense_count"] == 2
    assert data["expenses"][0]["id"] == last_id
    assert data["comparison"] == {
        "percent": -50, "direction": "down", "previous_total_cents": 10000,
    }
    assert data["evolution"][-2] == {
        "period": "2026-09", "label": "Set", "full_label": "Setembro 2026",
        "total_cents": 5000, "height_percent": pytest.approx(5000 / 99900 * 100), "kind": "past",
    }
    assert data["evolution"][-1] == {
        "period": "2026-10", "label": "Out", "full_label": "Outubro 2026",
        "total_cents": 99900, "height_percent": 100, "kind": "current",
    }


def test_method_filters_only_evolution(service, add_expense):
    add_expense(20, "2026-09-01", category="Lazer", method="pix")
    add_expense(30, "2026-09-30", category="Lazer", method="crédito")
    add_expense(10, "2026-10-01", category="Transporte", method="pix")
    add_expense(90, "2026-10-27", category="Transporte", method="crédito")

    baseline = build_dashboard_data(service, today=TODAY)
    filtered = build_dashboard_data(service, evolution_method="pix", today=TODAY)

    assert filtered["evolution_method"] == "pix"
    assert [item["total_cents"] for item in baseline["evolution"]] == [0, 0, 0, 0, 5000, 10000]
    assert [item["total_cents"] for item in filtered["evolution"]] == [0, 0, 0, 0, 2000, 1000]
    assert [item["height_percent"] for item in filtered["evolution"]] == [0, 0, 0, 0, 100, 50]
    assert {
        key: value for key, value in filtered.items()
        if key not in {"evolution", "evolution_method"}
    } == {
        key: value for key, value in baseline.items()
        if key not in {"evolution", "evolution_method"}
    }
    assert build_dashboard_data(service, evolution_method="", today=TODAY) == baseline


def test_category_and_method_filters_combine(service, add_expense):
    add_expense(20, "2026-09-01", category="Lazer", method="pix")
    add_expense(30, "2026-09-30", category="Lazer", method="crédito")
    add_expense(10, "2026-10-01", category="Transporte", method="pix")
    add_expense(90, "2026-10-27", category="Transporte", method="crédito")

    category_only = build_dashboard_data(service, evolution_category="Lazer", today=TODAY)
    method_only = build_dashboard_data(service, evolution_method="pix", today=TODAY)
    combined = build_dashboard_data(
        service, evolution_category="Lazer", evolution_method="pix", today=TODAY,
    )

    assert combined["evolution_category"] == "Lazer"
    assert combined["evolution_method"] == "pix"
    assert [item["total_cents"] for item in category_only["evolution"]] == [0, 0, 0, 0, 5000, 0]
    assert [item["total_cents"] for item in method_only["evolution"]] == [0, 0, 0, 0, 2000, 1000]
    assert [item["total_cents"] for item in combined["evolution"]] == [0, 0, 0, 0, 2000, 0]


def test_global_and_user_payment_method_catalog(service, test_user, other_user, add_expense):
    service.conn.executemany(
        "INSERT INTO payment_methods (name, is_system, user_id) VALUES (?, 0, ?)",
        [("Global Método", None), ("Meu Método", test_user["id"]), ("Segredo", other_user)],
    )
    service.conn.commit()
    add_expense(10, "2026-10-01", method="Global Método")
    add_expense(20, "2026-10-02", method="Meu Método")

    for method, total in [("Global Método", 1000), ("Meu Método", 2000), ("pix", 0)]:
        data = build_dashboard_data(service, evolution_method=method, today=TODAY)
        assert data["evolution_method"] == method
        assert data["evolution"][-1]["total_cents"] == total
        assert {"Global Método", "Meu Método", "pix"} <= set(data["payment_method_options"])
        assert "Segredo" not in data["payment_method_options"]
        assert data["payment_method_options"] == sorted(set(data["payment_method_options"]))

    for method in ("Segredo", "Inexistente", " "):
        with pytest.raises(ValueError, match="Método.*inválido"):
            build_dashboard_data(service, evolution_method=method, today=TODAY)


def test_category_filters_only_evolution(service, add_expense):
    add_expense(20, "2026-09-01", category="Lazer")
    add_expense(30, "2026-09-30", category="Transporte")
    add_expense(10, "2026-10-01", category="Lazer")
    add_expense(90, "2026-10-27", category="Transporte")

    baseline = build_dashboard_data(service, today=TODAY)
    filtered = build_dashboard_data(service, evolution_category="Lazer", today=TODAY)

    assert filtered["evolution_category"] == "Lazer"
    assert [item["total_cents"] for item in baseline["evolution"]] == [0, 0, 0, 0, 5000, 10000]
    assert [item["total_cents"] for item in filtered["evolution"]] == [0, 0, 0, 0, 2000, 1000]
    assert [item["height_percent"] for item in filtered["evolution"]] == [0, 0, 0, 0, 100, 50]
    assert {
        key: value for key, value in filtered.items()
        if key not in {"evolution", "evolution_category"}
    } == {
        key: value for key, value in baseline.items()
        if key not in {"evolution", "evolution_category"}
    }
    assert build_dashboard_data(service, evolution_category="", today=TODAY) == baseline
    assert build_dashboard_data(service, evolution_category="Moradia", today=TODAY)["evolution"] == [
        {**item, "total_cents": 0, "height_percent": 0} for item in baseline["evolution"]
    ]


def test_global_and_user_category_catalog(service, test_user, other_user, add_expense):
    service.conn.executemany(
        "INSERT INTO categories (name, is_system, user_id) VALUES (?, 0, ?)",
        [("Global Extra", None), ("Projetos", test_user["id"]), ("Segredo", other_user)],
    )
    service.conn.commit()
    add_expense(10, "2026-10-01", category="Global Extra")
    add_expense(20, "2026-10-02", category="Projetos")

    for category, total in [("Global Extra", 1000), ("Projetos", 2000), ("Alimenta\u00e7\u00e3o", 0)]:
        data = build_dashboard_data(service, evolution_category=category, today=TODAY)
        assert data["evolution_category"] == category
        assert data["evolution"][-1]["total_cents"] == total
        assert {"Global Extra", "Projetos", "Alimenta\u00e7\u00e3o"} <= set(data["categories"])
        assert "Segredo" not in data["categories"]
        assert data["categories"] == sorted(set(data["categories"]))
        assert data["total_cents"] == 3000

    for category in ("Segredo", "Inexistente", " ", "lazer"):
        with pytest.raises(ValueError, match="Categoria.*inv\u00e1lida"):
            build_dashboard_data(service, evolution_category=category, today=TODAY)


def test_six_month_evolution_is_chronological_zero_filled_and_crosses_year(service, add_expense):
    add_expense(999, "2025-07-31")
    add_expense(0.10, "2025-08-01")
    add_expense(0.20, "2025-10-31")
    add_expense(0.30, "2025-12-31")
    add_expense(0.10, "2026-01-31")
    add_expense(999, "2026-02-01")

    data = build_dashboard_data(service, period="2026-01", today=TODAY)

    assert [item["period"] for item in data["evolution"]] == [
        "2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02",
    ]
    assert [item["label"] for item in data["evolution"]] == ["Set", "Out", "Nov", "Dez", "Jan", "Fev"]
    assert [item["total_cents"] for item in data["evolution"]] == [0, 20, 0, 30, 10, 99900]
    assert [item["height_percent"] for item in data["evolution"]] == pytest.approx(
        [0, 20 / 99900 * 100, 0, 30 / 99900 * 100, 10 / 99900 * 100, 100],
    )
    assert data["comparison"]["previous_total_cents"] == 30


def test_empty_dashboard(service):
    data = build_dashboard_data(service, today=TODAY)

    assert data["total_cents"] == data["expense_count"] == 0
    assert data["comparison"] == {"percent": 0, "direction": "same", "previous_total_cents": 0}
    assert data["category_parts"] == data["payment_methods"] == data["expenses"] == []
    assert [item["period"] for item in data["evolution"]] == [
        "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10",
    ]
    assert all(item["total_cents"] == item["height_percent"] == 0 for item in data["evolution"])
    assert data["evolution"][0]["label"] == "Mai"
    assert data["evolution"][0]["full_label"] == "Maio 2026"
    assert len(data["period_options"]) == 12
    assert data["period_options"][0] == {"value": "2026-10", "label": "Outubro 2026"}
    assert data["period_options"][-1] == {"value": "2025-11", "label": "Novembro 2025"}


def test_cents_remain_exact_across_rows_and_summaries(service, add_expense):
    for amount in (0.10, 0.20, 2.01, 19.99, 0.29, 4.06):
        add_expense(amount, "2026-10-01")
    add_expense(0.10, "2026-09-01")
    add_expense(0.20, "2026-09-01")

    data = build_dashboard_data(service, today=TODAY)

    assert data["total_cents"] == 2665
    assert sorted(item["amount_cents"] for item in data["expenses"]) == [10, 20, 29, 201, 406, 1999]
    assert sum(item["amount_cents"] for item in data["expenses"]) == 2665
    assert data["category_parts"][0]["total_cents"] == 2665
    assert data["payment_methods"][0]["total_cents"] == 2665
    assert data["evolution"][-1]["total_cents"] == 2665
    assert data["comparison"]["previous_total_cents"] == 30
    assert type(data["total_cents"]) is int
    assert all(type(item["amount_cents"]) is int for item in data["expenses"])


def test_palette_cycles_and_percentages_are_not_rounded_or_scaled_to_largest_method(service, add_expense):
    categories = service.list_categories()[:7]
    for index, category in enumerate(categories):
        add_expense(
            0.01, "2026-10-01", category=category,
            method="pix" if index % 2 == 0 else "cr\u00e9dito",
        )

    data = build_dashboard_data(service, today=TODAY)

    assert [item["color"] for item in data["category_parts"]] == [
        "#62e6ba", "#7daeff", "#c3a0ff", "#f7bb75", "#ff9caa", "#a8e6cf", "#62e6ba",
    ]
    assert {item["name"] for item in data["category_parts"]} == set(categories)
    assert all(item["percent"] == pytest.approx(100 / 7) for item in data["category_parts"])
    assert sum(item["percent"] for item in data["category_parts"]) == pytest.approx(100)
    assert data["payment_methods"] == [
        {"name": "Pix", "total_cents": 4, "percent": pytest.approx(4 / 7 * 100)},
        {"name": "Cr\u00e9dito", "total_cents": 3, "percent": pytest.approx(3 / 7 * 100)},
    ]


def test_payment_labels_only_capitalize_first_letter(service, test_user, add_expense):
    service.conn.execute(
        "INSERT INTO payment_methods (name, user_id) VALUES (?, ?)",
        ("vale ABC", test_user["id"]),
    )
    service.conn.commit()
    add_expense(10, "2026-10-01", method="vale ABC")

    data = build_dashboard_data(service, today=TODAY)

    assert data["payment_methods"] == [{"name": "Vale ABC", "total_cents": 1000, "percent": 100}]
    assert data["expenses"][0]["method"] == "Vale ABC"


def test_all_expenses_are_returned_in_deterministic_order(service, add_expense):
    older_date = add_expense(1, "2026-10-25", created_at="2026-10-27 20:00:00")
    tied_low_id = add_expense(
        2, "2026-10-26", description="Descricao ORIGINAL / 001", created_at="2026-10-26 10:00:00",
    )
    tied_high_id = add_expense(
        3, "2026-10-26", description="Outra ORIGINAL / 002", created_at="2026-10-26 10:00:00",
    )
    newer_created = add_expense(4, "2026-10-26", created_at="2026-10-26 11:00:00")
    newer_date = add_expense(5, "2026-10-27", created_at="2026-10-01 08:00:00")

    data = build_dashboard_data(service, today=TODAY)

    assert [item["id"] for item in data["expenses"]] == [
        newer_date, newer_created, tied_high_id, tied_low_id, older_date,
    ]
    assert data["expense_count"] == len(data["expenses"]) == 5
    assert data["total_cents"] == 1500
    assert data["expenses"][2]["description"] == "Outra ORIGINAL / 002"
    assert data["expenses"][3]["description"] == "Descricao ORIGINAL / 001"
    assert build_dashboard_data(service, today=TODAY) == data


def test_user_isolation_and_soft_delete_apply_to_every_read(service, other_user, add_expense):
    add_expense(10, "2026-09-30")
    add_expense(20, "2026-10-01")
    baseline = build_dashboard_data(service, today=TODAY)

    for expense_date in ("2020-01-01", "2026-09-30", "2026-10-01"):
        add_expense(999, expense_date, user_id=other_user)
    for expense_date in ("2019-01-01", "2026-09-30", "2026-10-01"):
        add_expense(999, expense_date, deleted_at="2026-10-27 12:00:00")

    assert build_dashboard_data(service, today=TODAY) == baseline


def test_period_options_include_recent_historical_and_selected_months_independent_of_category(
    service, add_expense,
):
    add_expense(10, "2024-02-29", category="Transporte")
    add_expense(10, "2023-12-31", category="Transporte")
    add_expense(10, "2026-11-01")

    data = build_dashboard_data(
        service, period="2022-06", evolution_category="Lazer", today=TODAY,
    )
    expected_values = ["2026-11"] + [f"2026-{month:02d}" for month in range(10, 0, -1)] + [
        "2025-12", "2025-11", "2024-02", "2023-12", "2022-06",
    ]

    assert [option["value"] for option in data["period_options"]] == expected_values
    assert data["period_options"][-3:] == [
        {"value": "2024-02", "label": "Fevereiro 2024"},
        {"value": "2023-12", "label": "Dezembro 2023"},
        {"value": "2022-06", "label": "Junho 2022"},
    ]
    assert data["total_cents"] == data["expense_count"] == 0
    assert data["period_options"] == build_dashboard_data(
        service, period="2022-06", today=TODAY,
    )["period_options"]


@pytest.mark.parametrize(
    "period,expected,label",
    [
        (None, "2026-10", "Outubro 2026"),
        ("", "2026-10", "Outubro 2026"),
        ("2026-10", "2026-10", "Outubro 2026"),
        ("2026-01", "2026-01", "Janeiro 2026"),
        ("2025-12", "2025-12", "Dezembro 2025"),
        ("2026-03", "2026-03", "Mar\u00e7o 2026"),
        ("2024-02", "2024-02", "Fevereiro 2024"),
        ("0001-06", "0001-06", "Junho 0001"),
    ],
)
def test_valid_periods(service, period, expected, label):
    data = build_dashboard_data(service, period=period, today=TODAY)

    assert data["period"] == expected
    assert data["period_label"] == label
    assert {"value": expected, "label": label} in data["period_options"]


@pytest.mark.parametrize(
    "period",
    [
        "2026-1", "2026-001", "26-10", "202610", "2026-10-01", "2026/10",
        " 2026-10", "2026-10 ", "2026-10\n", "2026-00", "2026-13", "0000-01",
        "10000-01", "-001-01", "2026-0a", "\u0662\u0660\u0662\u0666-\u0661\u0660", 123, 0,
    ],
)
def test_invalid_periods_raise_portuguese_value_error(service, period):
    with pytest.raises(ValueError, match="Per\u00edodo inv\u00e1lido"):
        build_dashboard_data(service, period=period, today=TODAY)


@pytest.mark.parametrize("period", ["2027-01", "9999-12"])
def test_future_months_beyond_latest_with_data_are_rejected(service, period):
    with pytest.raises(ValueError, match="\u00faltimo m\u00eas com lan\u00e7amentos"):
        build_dashboard_data(service, period=period, today=TODAY)


def test_future_months_up_to_latest_with_data_are_allowed(service, add_expense):
    add_expense(100, "2026-11-15")
    add_expense(200, "2026-12-20")

    data = build_dashboard_data(service, period="2026-12", today=TODAY)

    assert data["period"] == "2026-12"
    assert data["total_cents"] == 20000
    assert data["expense_count"] == 1
    assert data["evolution"][-1]["total_cents"] == 20000
    assert data["evolution"][-1]["kind"] == "future"


def test_evolution_marks_future_months_and_keeps_six_bars(service, add_expense):
    add_expense(100, "2026-11-01")
    add_expense(200, "2026-12-01")

    data = build_dashboard_data(service, period="2026-12", today=TODAY)

    assert len(data["evolution"]) == 6
    assert [month["period"] for month in data["evolution"]] == [
        "2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12",
    ]
    assert [month["kind"] for month in data["evolution"]] == [
        "past", "past", "past", "current", "future", "future",
    ]
    assert data["evolution"][-2]["total_cents"] == 10000
    assert data["evolution"][-1]["total_cents"] == 20000


def test_current_month_is_valid_before_its_last_day(service, add_expense):
    first_id = add_expense(10, "2026-10-01")
    add_expense(20, "2026-10-02")

    data = build_dashboard_data(service, period="2026-10", today=date(2026, 10, 1))

    assert data["total_cents"] == 1000
    assert [item["id"] for item in data["expenses"]] == [first_id]
    assert data["evolution"][-1]["total_cents"] == 1000


@pytest.mark.parametrize("period", ["0001-01", "0001-02", "0001-03", "0001-04", "0001-05"])
def test_calendar_underflow_raises_portuguese_value_error(service, period):
    with pytest.raises(ValueError, match="Per\u00edodo.*intervalo"):
        build_dashboard_data(service, period=period, today=TODAY)


@pytest.mark.parametrize(
    "period,today,previous_date,last_date,next_date,date_label",
    [
        ("2024-02", date(2024, 3, 15), "2024-01-31", "2024-02-29", "2024-03-01", "29 fev"),
        ("2025-02", date(2025, 3, 15), "2025-01-31", "2025-02-28", "2025-03-01", "28 fev"),
        ("2026-01", date(2026, 2, 15), "2025-12-31", "2026-01-31", "2026-02-01", "31 jan"),
        ("9999-12", date(9999, 12, 31), "9999-11-30", "9999-12-31", None, "31 dez"),
        ("0001-06", date(1, 6, 30), "0001-05-31", "0001-06-30", "0001-07-01", "30 jun"),
    ],
)
def test_calendar_boundaries_and_leap_years(
    service, add_expense, period, today, previous_date, last_date, next_date, date_label,
):
    add_expense(50, previous_date)
    selected_id = add_expense(100, last_date)
    if next_date:
        add_expense(999, next_date)

    data = build_dashboard_data(service, period=period, today=today)

    assert data["period"] == period
    assert data["total_cents"] == 10000
    assert data["expense_count"] == 1
    assert data["comparison"] == {
        "percent": 100, "direction": "up", "previous_total_cents": 5000,
    }
    assert len(data["evolution"]) == 6
    if next_date:
        assert data["evolution"][-2]["total_cents"] == 10000
        assert data["evolution"][-1]["total_cents"] == 99900
    else:
        assert data["evolution"][-2]["total_cents"] == 5000
        assert data["evolution"][-1]["total_cents"] == 10000
    assert data["expenses"][0]["id"] == selected_id
    assert data["expenses"][0]["date_label"] == date_label
    if today.year == 1:
        assert [option["value"] for option in data["period_options"]] == [
            "0001-07", "0001-06", "0001-05", "0001-04", "0001-03", "0001-02", "0001-01",
        ]
