from enum import Enum


class TipoAmortizacion(str, Enum):
    BULLET = "bullet"
    CUOTAS = "cuotas"


class TipoCashflow(str, Enum):
    CUPON = "cupon"
    AMORTIZACION = "amortizacion"


class FuenteDatos(str, Enum):
    RAVA = "rava"
