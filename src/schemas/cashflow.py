from datetime import date
from decimal import Decimal
from pydantic import BaseModel
from src.enums import TipoCashflow


class CashflowCreate(BaseModel):
    ticker: str
    fecha_pago: date
    tipo: TipoCashflow
    monto_base: Decimal
    capital_pct: Decimal | None = None
    residual_pct: Decimal | None = None
    interest_nominal: Decimal | None = None
    cer_al_fetch: Decimal | None = None


class Cashflow(CashflowCreate):
    id: int

    model_config = {"from_attributes": True}
