from datetime import date
from decimal import Decimal
from pydantic import BaseModel


class CoeficienteCerCreate(BaseModel):
    fecha: date
    valor: Decimal


class CoeficienteCer(CoeficienteCerCreate):
    model_config = {"from_attributes": True}


class MetricaDiariaCreate(BaseModel):
    precio_id: int
    tir: Decimal
    duration_modificada: Decimal
    paridad: Decimal
    valor_tecnico: Decimal
    intereses_corridos: Decimal
    valor_residual: Decimal


class MetricaDiaria(MetricaDiariaCreate):
    model_config = {"from_attributes": True}
