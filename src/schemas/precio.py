from datetime import date
from decimal import Decimal
from pydantic import BaseModel
from src.enums import FuenteDatos


class PrecioDiarioCreate(BaseModel):
    ticker: str
    fecha: date
    apertura: Decimal | None = None
    maximo: Decimal | None = None
    minimo: Decimal | None = None
    cierre: Decimal | None = None
    volumen: Decimal | None = None
    fuente: FuenteDatos


class PrecioDiario(PrecioDiarioCreate):
    id: int

    model_config = {"from_attributes": True}
