"""Parser de fatura PDF Bradesco.

Extrai metadados, titulares/cartões e lançamentos de faturas de cartão de
crédito Bradesco no formato observado nas amostras.

Regras principais:
- Cada página é processada como texto bruto.
- Titulares/cartões são identificados por padrões como
  "Número do Cartão 4066 XXXX XXXX 3006" ou
  "NOME COMPLETO Cartão 4066 XXXX XXXX 2470".
- Cada lançamento começa com uma data no formato DD/MM.
- Valores são convertidos para centavos (inteiros) para evitar problemas de
  ponto flutuante.
- Lançamentos de pagamento/crédito têm valor negativo.
- Lançamentos cuja titularidade não pode ser determinada com segurança são
  marcados como ambiguous=True para revisão manual.
"""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import pdfplumber


# Regex para identificar final do cartão (4 dígitos)
CARD_LAST_FOUR_RE = re.compile(r"\b(\d{4})\b")
# Regex para linha de cartão/titular
CARD_HEADER_RE = re.compile(
    r"(?:Número do Cartão\s+\d{4}\s+X{4}\s+X{4}\s+(\d{4})|"
    r"([A-Z][A-Z\s]+?)\s+Cartão\s+\d{4}\s+X{4}\s+X{4}\s+(\d{4}))"
)
# Regex para data DD/MM
DATE_RE = re.compile(r"\b(\d{2}/\d{2})\b")
# Regex para parcela (ex: 01/03, 02/05)
INSTALLMENT_RE = re.compile(r"\b(\d{2}/\d{2})\b")


@dataclass
class ParsedTransaction:
    id: int = 0
    transaction_date: date = date.today()
    description: str = ""
    amount_cents: int = 0
    card_holder: Optional[str] = None
    card_last_four: Optional[str] = None
    purchase_date: Optional[date] = None
    city: Optional[str] = None
    installment_info: Optional[str] = None
    ambiguous: bool = False
    is_credit: bool = False
    raw_line: str = ""


@dataclass
class CardHolder:
    name: str
    last_four: str


@dataclass
class ParsedStatement:
    holder_name: Optional[str] = None
    due_date: Optional[date] = None
    statement_date: Optional[date] = None
    total_cents: Optional[int] = None
    file_hash: str = ""
    file_name: str = ""
    card_holders: list[CardHolder] = field(default_factory=list)
    transactions: list[ParsedTransaction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _bradesco_month_year(due_date: date, dd_mm_str: str) -> date:
    """Converte 'DD/MM' em date usando o ano/mês de referência da fatura.

    A fatura lista apenas dia/mês. Usamos o mês/ano da data de vencimento
    como âncora; se a data convertida ficar muito no futuro (> 40 dias após
    vencimento), assumimos o mês anterior. Isso cobre lançamentos de ciclos
    anteriores que aparecem na fatura atual.
    """
    day, month = map(int, dd_mm_str.split("/"))
    year = due_date.year
    candidate = date(year, month, day)
    if (candidate - due_date).days > 40:
        # Retrocede um mês
        if month == 1:
            candidate = date(year - 1, 12, day)
        else:
            candidate = date(year, month - 1, day)
    return candidate


def _parse_amount(value_str: str) -> int:
    """Converte string monetária brasileira para centavos.

    Exemplos:
        'R$ 20.372,90' -> 2037290
        '18.133,47-'   -> -1813347
        '1,88'         -> 188
    """
    negative = value_str.endswith("-")
    clean = value_str.replace("R$", "").replace(".", "").replace(",", ".").replace("-", "").strip()
    if not clean:
        raise ValueError(f"Valor vazio: {value_str!r}")
    amount = Decimal(clean)
    cents = int(amount * 100)
    return -cents if negative else cents


def _extract_due_date(text: str) -> Optional[date]:
    """Extrai a data de vencimento da fatura.

    O layout Bradesco costuma colocar 'Total da fatura Vencimento' em uma
    linha e, na linha seguinte, o valor seguido da data de vencimento.
    """
    # Padrão 1: 'Total da fatura Vencimento' + linha com valor e data
    match = re.search(
        r"Total da fatura\s+Vencimento\s*\n.*?R\$\s*[\d.]+,\d{2}\s+(\d{2}/\d{2}/\d{4})",
        text,
        re.MULTILINE,
    )
    if match:
        return datetime.strptime(match.group(1), "%d/%m/%Y").date()

    # Padrão 2: 'Vencimento DD/MM/YYYY' direto
    match = re.search(r"Vencimento\s*(\d{2}/\d{2}/\d{4})", text)
    if match:
        return datetime.strptime(match.group(1), "%d/%m/%Y").date()
    return None


def _extract_total(text: str) -> Optional[int]:
    """Extrai 'Total da fatura R$ XX.XXX,XX' do cabeçalho."""
    match = re.search(
        r"Total da fatura\s+Vencimento\s*\n.*?R\$\s*([\d.]+,\d{2})\s+\d{2}/\d{2}/\d{4}",
        text,
        re.MULTILINE,
    )
    if match:
        try:
            return _parse_amount(match.group(1))
        except (ValueError, InvalidOperation):
            return None

    match = re.search(r"Total da fatura\s*R?\$?\s*([\d.,]+)", text)
    if match:
        try:
            return _parse_amount(match.group(1))
        except (ValueError, InvalidOperation):
            return None
    return None


def _extract_main_holder(text: str) -> Optional[str]:
    """Extrai o nome do titular principal do endereçamento da fatura."""
    # Após o endereço da agência aparece o nome em maiúsculas.
    match = re.search(
        r"CTC\s+[A-Z\s]+\d+\s+R\$[\s\d.,]+\s+\d{2}/\d{2}/\d{4}\s*\n"
        r"([A-Z][A-Z\s]+?)\s*\n",
        text,
    )
    if match:
        return match.group(1).strip()
    # Fallback: procura nome antes de "Cartão 4066..."
    match = re.search(r"\n([A-Z][A-Z\s]{5,}?)\s+Cartão\s+\d{4}", text)
    if match:
        return match.group(1).strip()
    return None


def _extract_card_holders(text: str) -> list[CardHolder]:
    """Extrai todos os titulares/cartões mencionados na fatura."""
    holders: list[CardHolder] = []
    seen = set()

    # Padrão 1: "Número do Cartão 4066 XXXX XXXX 3006"
    for match in re.finditer(r"Número do Cartão\s+\d{4}\s+X{4}\s+X{4}\s+(\d{4})", text):
        last_four = match.group(1)
        if last_four not in seen:
            seen.add(last_four)
            holders.append(CardHolder(name="", last_four=last_four))

    # Padrão 2: "NOME COMPLETO Cartão 4066 XXXX XXXX 2470"
    for match in re.finditer(r"([A-Z][A-Z\s]{5,}?)\s+Cartão\s+\d{4}\s+X{4}\s+X{4}\s+(\d{4})", text):
        name = match.group(1).strip()
        last_four = match.group(2)
        if last_four not in seen:
            seen.add(last_four)
            holders.append(CardHolder(name=name, last_four=last_four))
        else:
            # Atualiza nome se antes estava vazio
            for h in holders:
                if h.last_four == last_four and not h.name:
                    h.name = name

    return holders


def _build_holder_map(holders: list[CardHolder], main_holder_name: Optional[str]) -> dict[str, str]:
    """Associa cada final de cartão ao nome do titular."""
    holder_map: dict[str, str] = {}
    for h in holders:
        holder_map[h.last_four] = h.name or main_holder_name or ""
    return holder_map


def _parse_transaction_line(line: str, due_date: date) -> Optional[ParsedTransaction]:
    """Tenta interpretar uma linha de lançamento da fatura.

    Formato esperado:
        DD/MM DESCRIÇÃO [DD/MM CIDADE] VALOR

    Retorna None se a linha não corresponder a um lançamento.
    """
    line = line.strip()
    if not line:
        return None

    # Deve começar com data DD/MM no início da linha
    first_date_match = DATE_RE.match(line)
    if not first_date_match:
        return None

    first_date_str = first_date_match.group(1)
    try:
        transaction_date = _bradesco_month_year(due_date, first_date_str)
    except ValueError:
        return None

    # Extrai o valor monetário no final da linha, ignorando lixo de colunas
    # adjacentes (taxas, juros, etc). Pegamos o ÚLTIMO valor monetário
    # encontrado, pois o primeiro pode ser cotação em dólar (compras
    # internacionais) ou parcela.
    value_matches = list(re.finditer(r"(?:R\$\s*)?([\d.]+,\d{2}-?)(?:\s+|$)", line))
    if not value_matches:
        return None

    value_match = value_matches[-1]
    try:
        amount_cents = _parse_amount(value_match.group(1))
    except (ValueError, InvalidOperation):
        return None

    middle = line[first_date_match.end(): value_match.start()].strip()

    # Remove textos de colunas/taxas que possam ter sido concatenados
    middle = re.sub(r"\s+Taxa.*", "", middle, flags=re.IGNORECASE)
    middle = re.sub(r"\s+Parcelamento.*", "", middle, flags=re.IGNORECASE)
    middle = re.sub(r"\s+Compras Parceladas.*", "", middle, flags=re.IGNORECASE)
    middle = re.sub(r"\s+com Juros.*", "", middle, flags=re.IGNORECASE)
    middle = re.sub(r"\s+Crediário.*", "", middle, flags=re.IGNORECASE)
    middle = re.sub(r"\s+Rotativo.*", "", middle, flags=re.IGNORECASE)
    middle = re.sub(r"\s+Saque.*", "", middle, flags=re.IGNORECASE)
    middle = re.sub(r"\s+Válido para.*", "", middle, flags=re.IGNORECASE)
    middle = re.sub(r"\s+\* Sobre.*", "", middle, flags=re.IGNORECASE)
    middle = re.sub(r"\s+e IOF.*", "", middle, flags=re.IGNORECASE)
    middle = re.sub(r"\s+Novo teto.*", "", middle, flags=re.IGNORECASE)
    middle = re.sub(r"\s+Valor em R\$.*", "", middle, flags=re.IGNORECASE)

    # Tenta separar descrição e cidade. A cidade geralmente vem no final,
    # em maiúsculas, após uma segunda data opcional.
    description = middle
    purchase_date: Optional[date] = None
    city: Optional[str] = None
    installment_info: Optional[str] = None

    # Procura por segunda data no meio (data da compra ou parcela)
    remaining_dates = list(DATE_RE.finditer(middle))
    if remaining_dates:
        second = remaining_dates[-1]  # última data geralmente é a cidade/compra
        second_str = second.group(1)
        try:
            second_date = _bradesco_month_year(due_date, second_str)
        except ValueError:
            second_date = None

        before_second = middle[: second.start()].strip()
        after_second = middle[second.end():].strip()

        # Heurística para parcela: se a segunda data for anterior à data do
        # lançamento em mais de 30 dias, provavelmente indica parcela atual/total
        # (ex: 01/03, 02/05), não a data da compra.
        is_installment = (
            second_date is not None
            and (transaction_date - second_date).days > 30
        )

        if is_installment:
            installment_info = second_str
            description = before_second
            city = after_second
        elif second_date:
            purchase_date = second_date
            description = before_second
            city = after_second

    # Detecta parcelamento colado ao final da descrição sem separação de espaço
    # (ex: "MERCADOLIVRE*INFANTO01/03").
    inst_match = re.search(r"(\d{2}/\d{2})$", description.replace(" ", ""))
    if inst_match:
        # Só considera parcela se não tiver sido detectada acima
        if installment_info is None:
            installment_info = inst_match.group(1)
        description = description[: -len(inst_match.group(1))].strip()

    # Normaliza descrição
    description = re.sub(r"\s+", " ", description).strip()

    # Limita cidade a algo razoável
    if city and len(city) > 40:
        city = city[:40].strip()

    # Heurística: ignora linhas que claramente não são transações
    upper_desc = description.upper()
    if any(k in upper_desc for k in ["TOTAL PARA", "TOTAL DA FATURA", "LANÇAMENTOS", "HISTÓRICO DE LANÇAMENTOS"]):
        return None

    # Pagamentos/créditos/estornos não são despesas e não entram na conciliação.
    is_credit = amount_cents < 0 or any(
        k in upper_desc
        for k in ["PAGTO.", "PAGAMENTO", "CREDITO", "CRÉDITO", "ESTORNO", "DEB EM C/C"]
    )

    return ParsedTransaction(
        transaction_date=transaction_date,
        description=description,
        amount_cents=amount_cents,
        purchase_date=purchase_date,
        city=city,
        installment_info=installment_info,
        is_credit=is_credit,
        raw_line=line,
    )


def _split_lines(text: str) -> list[str]:
    """Divide o texto em linhas, preservando possíveis quebras."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _assign_holder_to_transactions(
    lines: list[str],
    transactions: list[ParsedTransaction],
    holder_map: dict[str, str],
    main_holder_name: Optional[str],
) -> None:
    """Atribui titular/cartão aos lançamentos com base na seção em que aparecem.

    A fatura alterna seções identificadas por cabeçalhos de cartão. Lançamentos
    entre um cabeçalho e o próximo cabeçalho/total pertencem àquele cartão.
    """
    current_last_four: Optional[str] = None
    tx_idx = 0

    for line in lines:
        # Detecta cabeçalho de cartão
        m = re.search(r"(?:Número do Cartão|[A-Z\s]+?)\s+Cartão\s+\d{4}\s+X{4}\s+X{4}\s+(\d{4})", line)
        if m:
            current_last_four = m.group(1)
            continue

        # Ignora totais e outras linhas
        if "Total para" in line or "Total da fatura" in line:
            continue

        # Se for um lançamento, atribui titular
        if tx_idx < len(transactions) and line == transactions[tx_idx].raw_line:
            tx = transactions[tx_idx]
            if current_last_four:
                tx.card_last_four = current_last_four
                tx.card_holder = holder_map.get(current_last_four, main_holder_name or "")
            else:
                tx.ambiguous = True
                tx.card_holder = main_holder_name or ""
            tx_idx += 1


def parse_bradesco_statement(pdf_path: Path | str) -> ParsedStatement:
    """Parseia uma fatura Bradesco em PDF.

    Args:
        pdf_path: caminho para o arquivo PDF.

    Returns:
        ParsedStatement com metadados, titulares/cartões e lançamentos.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF não encontrado: {pdf_path}")

    result = ParsedStatement(file_name=pdf_path.name)

    # Hash do arquivo (SHA-256) para idempotência
    result.file_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    result.due_date = _extract_due_date(full_text)
    result.total_cents = _extract_total(full_text)
    result.statement_date = result.due_date  # Melhor âncora disponível
    result.holder_name = _extract_main_holder(full_text)
    result.card_holders = _extract_card_holders(full_text)
    holder_map = _build_holder_map(result.card_holders, result.holder_name)

    if not result.due_date:
        result.warnings.append("Não foi possível identificar a data de vencimento da fatura.")
        return result

    lines = _split_lines(full_text)
    transactions: list[ParsedTransaction] = []
    for line in lines:
        tx = _parse_transaction_line(line, result.due_date)
        if tx:
            transactions.append(tx)

    _assign_holder_to_transactions(lines, transactions, holder_map, result.holder_name)

    # Marca como ambíguos lançamentos sem cartão/titular identificado
    for tx in transactions:
        if not tx.card_last_four or not tx.card_holder:
            tx.ambiguous = True

    result.transactions = transactions

    # Validação: total parseado vs total informado
    # O total da fatura é o saldo devedor do ciclo, aproximadamente a soma
    # das despesas (excluindo pagamentos/créditos/estornos).
    if result.total_cents is not None and transactions:
        parsed_total = sum(
            tx.amount_cents for tx in transactions if not tx.is_credit
        )
        if abs(parsed_total - result.total_cents) > 100:  # tolerância de R$ 1,00
            result.warnings.append(
                f"Total de despesas parseado ({parsed_total/100:.2f}) difere do "
                f"total da fatura ({result.total_cents/100:.2f}). Verifique "
                "lançamentos de pagamentos, estornos ou compras internacionais."
            )

    return result


def filter_transactions_by_holder(
    statement: ParsedStatement,
    card_last_four: Optional[str] = None,
    card_holder: Optional[str] = None,
) -> list[ParsedTransaction]:
    """Filtra lançamentos pelo titular/cartão selecionado.

    Se ambos os parâmetros forem None, retorna apenas lançamentos ambíguos
    para revisão.
    """
    selected: list[ParsedTransaction] = []
    for tx in statement.transactions:
        if tx.ambiguous:
            continue
        if card_last_four and tx.card_last_four != card_last_four:
            continue
        if card_holder and tx.card_holder and tx.card_holder != card_holder:
            continue
        selected.append(tx)
    return selected
