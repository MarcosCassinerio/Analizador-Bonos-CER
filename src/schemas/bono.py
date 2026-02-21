from datetime import date, datetime
from pydantic import BaseModel
from src.enums import TipoAmortizacion


class GrupoCreate(BaseModel):
    nombre: str
    descripcion: str | None = None


class Grupo(GrupoCreate):
    model_config = {"from_attributes": True}


class BonoCreate(BaseModel):
    ticker: str
    nombre: str
    grupo: str
    tipo_amortizacion: TipoAmortizacion
    fecha_vencimiento: date
    activo: bool = True


class Bono(BonoCreate):
    created_at: datetime

    model_config = {"from_attributes": True}
