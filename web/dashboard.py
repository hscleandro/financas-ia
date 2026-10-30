"""Dados serializaveis do dashboard, sem dependencias de apresentacao."""

import re
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from services.expense_service import ExpenseService


_MONTH_NAMES = (
    "Janeiro", "Fevereiro", "Mar\u00e7o", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)
_CATEGORY_COLORS = (
    "#62e6ba", "#7daeff", "#c3a0ff", "#f7bb75", "#ff9caa", "#a8e6cf",
)


def _month_start(value: date, offset: int) -> date:
    year, month = divmod((value.year - 1) * 12 + value.month - 1 + offset, 12)
    try:
        return date(year + 1, month + 1, 1)
    except ValueError:
        raise ValueError("Per\u00edodo fora do intervalo de datas suportado.") from None


def _period_label(value: date) -> str:
    return f"{_MONTH_NAMES[value.month - 1]} {value.year:04d}"


def _to_cents(value: float) -> int:
    return int((Decimal(str(value)) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def build_dashboard_data(
    service: ExpenseService,
    period: str | None = None,
    evolution_category: str | None = None,
    today: date | None = None,
) -> dict:
    """Monta o mes selecionado; a categoria filtra somente a evolucao."""
    if today is None:
        today = date.today()
    if period is None or period == "":
        period = today.isoformat()[:7]
    if not isinstance(period, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}", period) is None:
        raise ValueError("Per\u00edodo inv\u00e1lido. Use YYYY-MM.")
    try:
        selected = date(int(period[:4]), int(period[5:]), 1)
    except ValueError:
        raise ValueError("Per\u00edodo inv\u00e1lido. Use YYYY-MM com um m\u00eas v\u00e1lido.") from None

    start_date = selected.isoformat()
    current_month_start = date(today.year, today.month, 1)
    end_of_month = date(
        selected.year,
        selected.month,
        monthrange(selected.year, selected.month)[1],
    )
    # Para o mês corrente e meses passados, limita ao dia de hoje;
    # para meses futuros, usa o último dia do mês selecionado.
    end_date = (
        min(today, end_of_month) if selected <= current_month_start else end_of_month
    ).isoformat()

    categories = service.list_categories()
    evolution_category = evolution_category or ""
    if evolution_category and evolution_category not in categories:
        raise ValueError("Categoria de evolu\u00e7\u00e3o inv\u00e1lida.")

    summary = service.get_summary(start_date, end_date, group_by="category")
    methods_summary = service.get_summary(start_date, end_date, group_by="method")
    history = service.get_summary("0001-01-01", "9999-12-31", group_by="month")
    history_totals = {
        item["dimension"]: _to_cents(item["total"]) for item in history["items"]
    }

    # Permite selecionar até o último mês com lançamentos registrados.
    latest_with_data = max(history_totals.keys()) if history_totals else today.isoformat()[:7]
    max_allowed = max(today.isoformat()[:7], latest_with_data)
    if selected.isoformat()[:7] > max_allowed:
        raise ValueError("O per\u00edodo n\u00e3o pode ser al\u00e9m do \u00faltimo m\u00eas com lan\u00e7amentos.")

    # O gráfico de evolução estica até 2 meses futuros consecutivos com lançamentos.
    future_months_count = 0
    for offset in range(1, 3):
        try:
            future_month = _month_start(selected, offset)
        except ValueError:
            break
        future_period = future_month.isoformat()[:7]
        if history_totals.get(future_period, 0) > 0:
            future_months_count += 1
        else:
            break
    evolution_months = [
        _month_start(selected, offset)
        for offset in range(-5 + future_months_count, 1 + future_months_count)
    ]
    evolution_end_of_month = date(
        evolution_months[-1].year,
        evolution_months[-1].month,
        monthrange(evolution_months[-1].year, evolution_months[-1].month)[1],
    )
    evolution_end_date = (
        min(today, evolution_end_of_month)
        if evolution_months[-1] <= current_month_start
        else evolution_end_of_month
    ).isoformat()

    total_cents = _to_cents(summary["total_geral"])
    previous_period = _month_start(selected, -1).isoformat()[:7]
    previous_total_cents = history_totals.get(previous_period, 0)
    if previous_total_cents:
        percent = (total_cents - previous_total_cents) / previous_total_cents * 100
        direction = "up" if total_cents > previous_total_cents else (
            "down" if total_cents < previous_total_cents else "same"
        )
    else:
        percent = None if total_cents else 0
        direction = "no_base" if total_cents else "same"

    option_values = set(history_totals) | {period}
    available_months = (today.year - 1) * 12 + today.month
    option_values.update(
        _month_start(today, -offset).isoformat()[:7]
        for offset in range(min(12, available_months))
    )
    period_options = [
        {"value": value, "label": _period_label(date.fromisoformat(f"{value}-01"))}
        for value in sorted(option_values, reverse=True)
    ]

    evolution_totals = {month.isoformat()[:7]: 0 for month in evolution_months}
    for row in service.query_expenses(
        start_date=evolution_months[0].isoformat(),
        end_date=evolution_end_date,
        category=evolution_category or None,
    ):
        expense_month = row["expense_date"][:7]
        expense_day = date.fromisoformat(row["expense_date"])
        # Meses passados/atuais só contam até hoje; meses futuros contam integralmente.
        month_start = date(expense_day.year, expense_day.month, 1)
        if month_start <= current_month_start and expense_day > today:
            continue
        evolution_totals[expense_month] += _to_cents(row["amount"])
    maximum = max(evolution_totals.values())
    evolution = []
    for month in evolution_months:
        month_period = month.isoformat()[:7]
        month_total = evolution_totals[month_period]
        if month > current_month_start:
            kind = "future"
        elif month == current_month_start:
            kind = "current"
        else:
            kind = "past"
        evolution.append({
            "period": month_period,
            "label": _MONTH_NAMES[month.month - 1][:3],
            "full_label": _period_label(month),
            "total_cents": month_total,
            "height_percent": month_total / maximum * 100 if maximum else 0,
            "kind": kind,
        })

    category_parts = []
    for index, item in enumerate(summary["items"]):
        cents = _to_cents(item["total"])
        category_parts.append({
            "name": item["dimension"],
            "total_cents": cents,
            "percent": cents / total_cents * 100 if total_cents else 0,
            "color": _CATEGORY_COLORS[index % len(_CATEGORY_COLORS)],
        })

    payment_methods = []
    for item in methods_summary["items"]:
        cents = _to_cents(item["total"])
        name = item["dimension"]
        payment_methods.append({
            "name": name[:1].upper() + name[1:],
            "total_cents": cents,
            "percent": cents / total_cents * 100 if total_cents else 0,
        })

    rows = service.query_expenses(start_date=start_date, end_date=end_date)
    rows.sort(
        key=lambda row: (row["expense_date"], row["created_at"] or "", row["id"]),
        reverse=True,
    )
    expenses = []
    for row in rows:
        expense_date = date.fromisoformat(row["expense_date"])
        method = row["method"]
        expenses.append({
            "id": row["id"],
            "description": row["description"],
            "date": expense_date.isoformat(),
            "date_label": f"{expense_date.day} {_MONTH_NAMES[expense_date.month - 1][:3].lower()}",
            "category": row["category"],
            "method": method[:1].upper() + method[1:],
            "amount_cents": _to_cents(row["amount"]),
        })

    return {
        "period": period,
        "period_label": _period_label(selected),
        "period_options": period_options,
        "evolution_category": evolution_category,
        "categories": categories,
        "total_cents": total_cents,
        "expense_count": sum(item["count"] for item in summary["items"]),
        "comparison": {
            "percent": percent,
            "direction": direction,
            "previous_total_cents": previous_total_cents,
        },
        "evolution": evolution,
        "category_parts": category_parts,
        "payment_methods": payment_methods,
        "expenses": expenses,
    }
