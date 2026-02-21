from datetime import date
from decimal import Decimal
from pydantic import BaseModel
from src.enums import TipoCashflow


class CashflowCreate(BaseModel):
    ticker: str
    fecha_pago: date
    tipo: TipoCashflow
    monto_base: Decimal


class Cashflow(CashflowCreate):
    id: int

    model_config = {"from_attributes": True}
