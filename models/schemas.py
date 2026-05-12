from pydantic import BaseModel, field_validator
from datetime import date
from typing import Literal, Optional

PaymentMethod = Literal["dinheiro", "crédito", "débito", "pix", "transferência"]


class ExpenseCreate(BaseModel):
    amount: float
    description: str
    category: str
    method: PaymentMethod = "dinheiro"
    expense_date: Optional[date] = None

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: float) -> float:
        if v <= 0 or v >= 100_000:
            raise ValueError(f"Valor deve ser entre 0 e 100.000, recebido: {v}")
        return round(v, 2)

    @field_validator("expense_date", mode="before")
    @classmethod
    def validate_date(cls, v) -> date:
        if v is None:
            return date.today()
        if isinstance(v, str):
            v = date.fromisoformat(v)
        today = date.today()
        if v > today:
            raise ValueError("Data de gasto não pode ser futura")
        if (today - v).days > 365:
            raise ValueError("Data de gasto não pode ser mais de 365 dias no passado")
        return v


class ExpenseRecord(BaseModel):
    id: int
    amount: float
    description: str
    category: str
    method: str
    expense_date: date
    created_at: str
    hash: str


class SummaryItem(BaseModel):
    dimension: str
    total: float
    count: int


class Summary(BaseModel):
    group_by: str
    start_date: date
    end_date: date
    items: list[SummaryItem]
    total_geral: float
