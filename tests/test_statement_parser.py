"""Testes do parser de fatura Bradesco.

Usam amostras de texto construídas manualmente para não depender de PDFs
reais nos testes automatizados.
"""
from datetime import date
from pathlib import Path

import pytest

from services.statement_parser import (
    ParsedTransaction,
    _bradesco_month_year,
    _parse_amount,
    _parse_transaction_line,
)


def test_bradesco_month_year_uses_due_year():
    due = date(2026, 10, 10)
    assert _bradesco_month_year(due, "10/09") == date(2026, 9, 10)


def test_bradesco_month_year_retrocedes_when_far_future():
    due = date(2026, 10, 10)
    # 13/03 com vencimento em outubro -> ano anterior (março)
    assert _bradesco_month_year(due, "13/03") == date(2026, 3, 13)


def test_parse_amount_positive():
    assert _parse_amount("R$ 20.372,90") == 2037290
    assert _parse_amount("18.133,47-") == -1813347
    assert _parse_amount("1,88") == 188


def test_parse_transaction_line_basic():
    due = date(2026, 10, 10)
    tx = _parse_transaction_line("28/08 DL*UberRides SAO PAULO 1,00", due)
    assert tx is not None
    assert tx.transaction_date == date(2026, 8, 28)
    # Sem segunda data, cidade não é separada automaticamente
    assert "DL*UberRides" in tx.description
    assert tx.amount_cents == 100
    assert tx.installment_info is None
    assert tx.is_credit is False


def test_parse_transaction_line_with_purchase_date():
    due = date(2026, 10, 10)
    tx = _parse_transaction_line("13/03 PAYPAL *DSA ACADEMY 07/11 SAO PAULO 154,45", due)
    assert tx is not None
    assert tx.transaction_date == date(2026, 3, 13)
    # Formato Bradesco é DD/MM, portanto 07/11 = 7 de novembro
    assert tx.purchase_date == date(2026, 11, 7)
    assert tx.city == "SAO PAULO"
    assert tx.amount_cents == 15445


def test_parse_transaction_line_installment():
    due = date(2026, 10, 10)
    tx = _parse_transaction_line("30/08 GOL LINHAS A*NDNO 01/03 SAO PAULO 459,28", due)
    assert tx is not None
    assert tx.transaction_date == date(2026, 8, 30)
    # 01/03 está a mais de 30 dias antes do lançamento -> parcela
    assert tx.installment_info == "01/03"
    assert tx.amount_cents == 45928


def test_parse_transaction_line_credit_payment():
    due = date(2026, 10, 10)
    tx = _parse_transaction_line("10/09 PAGTO. POR DEB EM C/C 18.133,47-", due)
    assert tx is not None
    assert tx.amount_cents == -1813347
    assert tx.is_credit is True


def test_parse_transaction_line_ignores_non_transaction():
    due = date(2026, 10, 10)
    assert _parse_transaction_line("Total paraLEANDRO HENRIQUE SANTOS CORREA 5.202,56", due) is None
    assert _parse_transaction_line("Data Histórico de Lançamentos Cidade US$ R$", due) is None


def test_parse_transaction_line_international_purchase():
    due = date(2026, 10, 10)
    tx = _parse_transaction_line("11/09 ANTHROPIC USD 10,00ANTHROPIC.C 10,00 5,3600 53,60", due)
    assert tx is not None
    assert tx.amount_cents == 5360
    assert "ANTHROPIC" in tx.description
