from sqlalchemy import (
    Column, String, Boolean, Date, Numeric,
    Integer, DateTime, ForeignKey, UniqueConstraint, Enum,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func
from src.enums import TipoAmortizacion, TipoCashflow


class Base(DeclarativeBase):
    pass


class Grupo(Base):
    __tablename__ = "grupos"

    nombre = Column(String, primary_key=True)
    descripcion = Column(String, nullable=True)

    bonos = relationship("Bono", back_populates="grupo_rel")


class Bono(Base):
    __tablename__ = "bonos"

    ticker = Column(String, primary_key=True)
    nombre = Column(String, nullable=False)
    grupo = Column(String, ForeignKey("grupos.nombre"), nullable=False)
    tipo_amortizacion = Column(Enum(TipoAmortizacion, name="tipo_amortizacion_enum", values_callable=lambda x: [e.value for e in x]), nullable=False)
    fecha_vencimiento = Column(Date, nullable=False)
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    grupo_rel = relationship("Grupo", back_populates="bonos")
    cashflows = relationship("Cashflow", back_populates="bono")
    precios = relationship("PrecioRaw", back_populates="bono")


class Cashflow(Base):
    __tablename__ = "cashflows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String, ForeignKey("bonos.ticker"), nullable=False)
    fecha_pago = Column(Date, nullable=False)
    tipo = Column(Enum(TipoCashflow, name="tipo_cashflow_enum", values_callable=lambda x: [e.value for e in x]), nullable=False)
    monto_base = Column(Numeric, nullable=False)
    capital_pct = Column(Numeric, nullable=True)
    residual_pct = Column(Numeric, nullable=True)

    bono = relationship("Bono", back_populates="cashflows")


class PrecioRaw(Base):
    __tablename__ = "precios_raw"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String, ForeignKey("bonos.ticker"), nullable=False)
    fecha = Column(Date, nullable=False)
    apertura = Column(Numeric)
    maximo = Column(Numeric)
    minimo = Column(Numeric)
    cierre = Column(Numeric)
    volumen = Column(Numeric)
    fuente = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("ticker", "fecha", name="uq_precio_ticker_fecha"),
    )

    bono = relationship("Bono", back_populates="precios")
    metrica = relationship("MetricaDiaria", back_populates="precio", uselist=False)


class CoeficienteCer(Base):
    __tablename__ = "coeficientes_cer"

    fecha = Column(Date, primary_key=True)
    valor = Column(Numeric, nullable=False)


class MetricaDiaria(Base):
    __tablename__ = "metricas_diarias"

    precio_id = Column(Integer, ForeignKey("precios_raw.id"), primary_key=True)
    tir = Column(Numeric, nullable=False)
    duration_modificada = Column(Numeric, nullable=False)
    paridad = Column(Numeric, nullable=False)
    valor_tecnico = Column(Numeric, nullable=False)
    intereses_corridos = Column(Numeric, nullable=False)
    valor_residual = Column(Numeric, nullable=False)

    precio = relationship("PrecioRaw", back_populates="metrica")
