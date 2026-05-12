from datetime import date


def validate_expense_intent(
    amount: float,
    description: str,
    expense_date: date | None = None,
) -> list[str]:
    """Retorna lista de erros encontrados antes de chamar a tool de registro."""
    errors: list[str] = []

    if amount <= 0:
        errors.append(f"Valor deve ser positivo, recebido: {amount}")
    elif amount >= 100_000:
        errors.append(f"Valor R$ {amount:,.2f} excede o limite de R$ 100.000")

    if not description or not description.strip():
        errors.append("Descrição não pode ser vazia")

    if expense_date is not None:
        today = date.today()
        if expense_date > today:
            errors.append("Data de gasto não pode ser futura")
        elif (today - expense_date).days > 365:
            errors.append("Data de gasto não pode ser mais de 365 dias no passado")

    return errors


def requires_confirmation(amount: float) -> bool:
    """True se o valor exige confirmação do usuário antes de registrar."""
    return amount > 1_000
