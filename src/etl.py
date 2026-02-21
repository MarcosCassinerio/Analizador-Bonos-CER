"""
ETL principal para bonos CER.

Uso:
    python -m src.etl

Pasos:
  1. seed_initial_data: inserta grupos y bonos si no existen
  2. run_etl: carga CER, cashflows (si faltan) y precios + métricas
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterator

import requests
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.apis import fetch_cashflows_docta, fetch_cer, fetch_ohlcv, get_docta_token
from src.db.models import Bono, Cashflow, CoeficienteCer, Grupo, MetricaDiaria, PrecioRaw
from src.db.session import SessionLocal
from src.enums import FuenteDatos, TipoAmortizacion
from src.pricing import calcular_metricas

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Datos estáticos
# ---------------------------------------------------------------------------

GRUPOS = {
    "corto": "Bonos CER corto plazo (venc. < 2 años)",
    "medio": "Bonos CER mediano plazo (2-5 años)",
    "largo": "Bonos CER largo plazo (> 5 años)",
}

# ticker -> (nombre, grupo, tipo_amortizacion)
BONOS: dict[str, tuple[str, str, TipoAmortizacion]] = {
    # Corto plazo
    "TZXM6": ("BONCER Mar 2026", "corto", TipoAmortizacion.BULLET),
    "TZXO6": ("BONCER Oct 2026", "corto", TipoAmortizacion.BULLET),
    "X29Y6": ("BONCER Ene 2026", "corto", TipoAmortizacion.BULLET),
    "X30N6": ("BONCER Nov 2026", "corto", TipoAmortizacion.BULLET),
    "X31L6": ("BONCER Jul 2026", "corto", TipoAmortizacion.BULLET),
    "TZXD6": ("BONCER Dic 2026", "corto", TipoAmortizacion.BULLET),
    "TZX26": ("BONCER 2026", "corto", TipoAmortizacion.BULLET),
    "TX26": ("BONCER TX26", "corto", TipoAmortizacion.CUOTAS),
    # Medio plazo
    "TZXM7": ("BONCER Mar 2027", "medio", TipoAmortizacion.BULLET),
    "TZXA7": ("BONCER Abr 2027", "medio", TipoAmortizacion.BULLET),
    "TZXY7": ("BONCER May 2027", "medio", TipoAmortizacion.BULLET),
    "TZX27": ("BONCER 2027", "medio", TipoAmortizacion.BULLET),
    "TZXD7": ("BONCER Dic 2027", "medio", TipoAmortizacion.BULLET),
    "TZX28": ("BONCER 2028", "medio", TipoAmortizacion.BULLET),
    "TX28": ("BONCER TX28", "medio", TipoAmortizacion.CUOTAS),
    # Largo plazo
    "TX31": ("BONCER TX31", "largo", TipoAmortizacion.CUOTAS),
    "DICP": ("DISCOUNT CER", "largo", TipoAmortizacion.BULLET),
    "DIP0": ("DISCOUNT CER 0", "largo", TipoAmortizacion.BULLET),
    "PARP": ("PAR CER", "largo", TipoAmortizacion.BULLET),
    "PAP0": ("PAR CER 0", "largo", TipoAmortizacion.BULLET),
    "CUAP": ("CUASI PAR CER", "largo", TipoAmortizacion.BULLET),
}

# Fecha de vencimiento placeholder (se actualiza con los cashflows de Docta)
FECHA_PLACEHOLDER = date(2099, 12, 31)

# Cache de feriados por año: {año: set[date]}
_feriados_cache: dict[int, set[date]] = {}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _feriados_ar(anio: int) -> set[date]:
    if anio in _feriados_cache:
        return _feriados_cache[anio]
    try:
        url = f"https://date.nager.at/api/v3/PublicHolidays/{anio}/AR"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        feriados = {date.fromisoformat(h["date"]) for h in r.json()}
    except Exception as e:
        log.warning(f"No se pudo obtener feriados {anio}: {e}")
        feriados = set()
    _feriados_cache[anio] = feriados
    return feriados


def dias_habiles_ar(desde: date, hasta: date) -> Iterator[date]:
    """Itera sobre los días hábiles argentinos en el rango [desde, hasta]."""
    # Pre-cargar feriados para los años en el rango
    for anio in range(desde.year, hasta.year + 1):
        _feriados_ar(anio)

    dia = desde
    while dia <= hasta:
        if dia.weekday() < 5 and dia not in _feriados_cache.get(dia.year, set()):
            yield dia
        dia += timedelta(days=1)


# ---------------------------------------------------------------------------
# Paso 1: Seed inicial
# ---------------------------------------------------------------------------

def seed_initial_data(session: Session) -> None:
    """Inserta grupos y bonos si no existen todavía."""
    # Grupos
    for nombre, descripcion in GRUPOS.items():
        existe = session.get(Grupo, nombre)
        if not existe:
            session.add(Grupo(nombre=nombre, descripcion=descripcion))
            log.info(f"Grupo insertado: {nombre}")
    session.flush()

    # Bonos
    for ticker, (nombre, grupo, tipo_amort) in BONOS.items():
        existe = session.get(Bono, ticker)
        if not existe:
            session.add(
                Bono(
                    ticker=ticker,
                    nombre=nombre,
                    grupo=grupo,
                    tipo_amortizacion=tipo_amort,
                    fecha_vencimiento=FECHA_PLACEHOLDER,
                    activo=True,
                )
            )
            log.info(f"Bono insertado: {ticker}")
    session.commit()
    log.info("Seed completado.")


# ---------------------------------------------------------------------------
# Helpers de DB
# ---------------------------------------------------------------------------

def _max_fecha_cer(session: Session) -> date | None:
    result = session.execute(select(func.max(CoeficienteCer.fecha))).scalar()
    return result


def _max_fecha_precio(session: Session, ticker: str) -> date | None:
    result = session.execute(
        select(func.max(PrecioRaw.fecha)).where(PrecioRaw.ticker == ticker)
    ).scalar()
    return result


def _tiene_cashflows(session: Session, ticker: str) -> bool:
    count = session.execute(
        select(func.count()).select_from(Cashflow).where(Cashflow.ticker == ticker)
    ).scalar()
    return (count or 0) > 0


def _get_cer_para_fecha(session: Session, fecha: date) -> Decimal | None:
    row = session.get(CoeficienteCer, fecha)
    return Decimal(str(row.valor)) if row else None


def _get_cashflows_para_bono(session: Session, ticker: str) -> list[dict]:
    rows = session.execute(
        select(Cashflow).where(Cashflow.ticker == ticker).order_by(Cashflow.fecha_pago)
    ).scalars().all()
    return [
        {
            "fecha_pago": r.fecha_pago,
            "adj_capital": float(r.monto_base) if r.tipo.value == "amortizacion" else 0.0,
            "adj_interest_amount": float(r.monto_base) if r.tipo.value == "cupon" else 0.0,
            "capital": float(r.monto_base) if r.tipo.value == "amortizacion" else 0.0,
            "residual_value": 0.0,  # se actualiza más abajo
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Carga de cashflows de Docta → DB
# ---------------------------------------------------------------------------

def _guardar_cashflows_docta(session: Session, ticker: str, df) -> date | None:
    """
    Parsea el DataFrame de Docta y guarda los cashflows en DB.
    Retorna la fecha de vencimiento (max payment_date), o None si df está vacío.
    """
    if df.empty:
        return None

    from src.enums import TipoCashflow

    # Detectar columnas disponibles
    cols = set(df.columns)

    max_fecha = None
    for _, row in df.iterrows():
        fecha_pago = date.fromisoformat(str(row["payment_date"])[:10])
        if max_fecha is None or fecha_pago > max_fecha:
            max_fecha = fecha_pago

        # Capital ajustado
        adj_cap = float(row.get("adj_capital", row.get("capital", 0)) or 0)
        # Interés ajustado
        adj_int = float(row.get("adj_interest_amount", row.get("interest_amount", 0)) or 0)

        capital_pct = float(row.get("capital", 0) or 0)
        residual_pct = float(row.get("residual_value", 0) or 0)

        if adj_cap and adj_cap != 0:
            session.add(Cashflow(
                ticker=ticker,
                fecha_pago=fecha_pago,
                tipo=TipoCashflow.AMORTIZACION,
                monto_base=Decimal(str(adj_cap)),
                capital_pct=Decimal(str(capital_pct)),
                residual_pct=Decimal(str(residual_pct)),
            ))
        if adj_int and adj_int != 0:
            session.add(Cashflow(
                ticker=ticker,
                fecha_pago=fecha_pago,
                tipo=TipoCashflow.CUPON,
                monto_base=Decimal(str(adj_int)),
                capital_pct=Decimal(str(capital_pct)),
                residual_pct=Decimal(str(residual_pct)),
            ))

    session.flush()
    return max_fecha


def _cashflows_para_metricas(session: Session, ticker: str) -> list[dict]:
    """
    Construye lista de dicts con todos los campos necesarios para pricing.
    Como los cashflows se guardan separados (capital y cupon), los juntamos por fecha.
    """
    rows = session.execute(
        select(Cashflow).where(Cashflow.ticker == ticker).order_by(Cashflow.fecha_pago)
    ).scalars().all()

    # Agrupar por fecha_pago
    por_fecha: dict[date, dict] = {}
    for r in rows:
        fp = r.fecha_pago
        if fp not in por_fecha:
            por_fecha[fp] = {
                "fecha_pago": fp,
                "adj_capital": 0.0,
                "adj_interest_amount": 0.0,
                "capital": 0.0,
                "residual_value": 0.0,
            }
        if r.tipo.value == "amortizacion":
            por_fecha[fp]["adj_capital"] += float(r.monto_base)
            por_fecha[fp]["capital"] += float(r.monto_base)
            if r.capital_pct is not None:
                por_fecha[fp]["capital_pct"] = float(r.capital_pct)
                por_fecha[fp]["residual_value"] = float(r.residual_pct or 0)
        else:
            por_fecha[fp]["adj_interest_amount"] += float(r.monto_base)
            # Para fechas solo con cupón (sin amortización), guardar residual del cupón
            if r.capital_pct is not None and "capital_pct" not in por_fecha[fp]:
                por_fecha[fp]["capital_pct"] = float(r.capital_pct)
                por_fecha[fp]["residual_value"] = float(r.residual_pct or 0)

    return sorted(por_fecha.values(), key=lambda x: x["fecha_pago"])


# ---------------------------------------------------------------------------
# ETL principal
# ---------------------------------------------------------------------------

def run_etl(session: Session) -> None:
    ayer = date.today() - timedelta(days=1)
    inicio = date(2025, 1, 1)

    # 1. Token Docta
    log.info("Obteniendo token de Docta...")
    try:
        token = get_docta_token()
    except Exception as e:
        log.error(f"No se pudo obtener token de Docta: {e}")
        token = None

    # 2. Cargar CER desde BCRA
    log.info("Cargando coeficientes CER...")
    max_cer = _max_fecha_cer(session)
    desde_cer = (max_cer + timedelta(days=1)) if max_cer else inicio
    if desde_cer <= ayer:
        try:
            df_cer = fetch_cer(desde_cer, ayer)
            nuevos_cer = 0
            for _, row in df_cer.iterrows():
                fecha_cer = date.fromisoformat(str(row["fecha"])[:10])
                existe = session.get(CoeficienteCer, fecha_cer)
                if not existe:
                    session.add(CoeficienteCer(fecha=fecha_cer, valor=Decimal(str(row["valor"]))))
                    nuevos_cer += 1
            session.commit()
            log.info(f"CER: {nuevos_cer} nuevas filas insertadas.")
        except Exception as e:
            log.error(f"Error cargando CER: {e}")
            session.rollback()
    else:
        log.info("CER ya está actualizado.")

    # 3. Procesar cada bono
    bonos = session.execute(select(Bono).where(Bono.activo == True)).scalars().all()

    for bono in bonos:
        ticker = bono.ticker
        log.info(f"Procesando {ticker}...")

        # 3a. Cashflows: intentar cargar si no existen
        if not _tiene_cashflows(session, ticker) and token:
            log.info(f"  {ticker}: fetcheando cashflows de Docta...")
            try:
                df_cf = fetch_cashflows_docta(ticker, token)
                max_fecha = _guardar_cashflows_docta(session, ticker, df_cf)
                if max_fecha:
                    bono.fecha_vencimiento = max_fecha
                session.commit()
                log.info(f"  {ticker}: {len(df_cf)} filas de cashflows cargadas.")
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else "?"
                log.warning(f"  {ticker}: Docta devolvió {status} — sin cashflows.")
                session.rollback()
            except Exception as e:
                log.warning(f"  {ticker}: error en Docta — {e}")
                session.rollback()

        # 3b. Precios: rango desde último precio + 1 hasta ayer
        max_precio = _max_fecha_precio(session, ticker)
        desde_precio = (max_precio + timedelta(days=1)) if max_precio else inicio

        if desde_precio > ayer:
            log.info(f"  {ticker}: precios ya actualizados.")
            continue

        # 3c. Fetch OHLCV de Rava (un solo request para todo el rango)
        try:
            df_ohlcv = fetch_ohlcv(ticker, desde_precio, ayer)
        except Exception as e:
            log.error(f"  {ticker}: error en Rava — {e}")
            continue

        if df_ohlcv.empty:
            log.info(f"  {ticker}: sin datos de Rava en el rango.")
            continue

        tiene_cfs = _tiene_cashflows(session, ticker)
        cashflows_metricas = _cashflows_para_metricas(session, ticker) if tiene_cfs else []

        # 3d. Insertar precios + calcular métricas por cada fila
        nuevos_precios = 0
        nuevas_metricas = 0

        for _, row in df_ohlcv.iterrows():
            fecha_precio = date.fromisoformat(str(row["fecha"])[:10])

            # INSERT precio (ignorar si ya existe por unique constraint)
            stmt = pg_insert(PrecioRaw).values(
                ticker=ticker,
                fecha=fecha_precio,
                apertura=_decimal_or_none(row.get("apertura")),
                maximo=_decimal_or_none(row.get("maximo")),
                minimo=_decimal_or_none(row.get("minimo")),
                cierre=_decimal_or_none(row.get("cierre")),
                volumen=_decimal_or_none(row.get("volumen")),
                fuente=FuenteDatos.RAVA.value,
            ).on_conflict_do_nothing(constraint="uq_precio_ticker_fecha")
            session.execute(stmt)
            session.flush()

            # Obtener el id del precio recién insertado (o existente)
            precio_row = session.execute(
                select(PrecioRaw).where(
                    PrecioRaw.ticker == ticker,
                    PrecioRaw.fecha == fecha_precio,
                )
            ).scalar_one_or_none()

            if precio_row is None:
                continue
            nuevos_precios += 1

            # Métricas: solo si tiene cashflows y CER para esa fecha
            cierre = _decimal_or_none(row.get("cierre"))
            if not (tiene_cfs and cierre and cashflows_metricas):
                continue

            cer_fecha = _get_cer_para_fecha(session, fecha_precio)
            if cer_fecha is None:
                continue

            # No calcular si ya existe la métrica
            existente = session.get(MetricaDiaria, precio_row.id)
            if existente:
                continue

            try:
                metricas = calcular_metricas(
                    cierre=cierre,
                    cashflows=cashflows_metricas,
                    cer_hoy=cer_fecha,
                    fecha_hoy=fecha_precio,
                )
                import math
                if any(math.isnan(v) for v in metricas.values()):
                    log.warning(f"  {ticker} {fecha_precio}: métricas con NaN, omitiendo.")
                    continue

                session.add(MetricaDiaria(
                    precio_id=precio_row.id,
                    tir=Decimal(str(round(metricas["tir"], 8))),
                    duration_modificada=Decimal(str(round(metricas["duration_modificada"], 6))),
                    paridad=Decimal(str(round(metricas["paridad"], 4))),
                    valor_tecnico=Decimal(str(round(metricas["valor_tecnico"], 4))),
                    intereses_corridos=Decimal(str(round(metricas["intereses_corridos"], 4))),
                    valor_residual=Decimal(str(round(metricas["valor_residual"], 4))),
                ))
                nuevas_metricas += 1
            except Exception as e:
                log.warning(f"  {ticker} {fecha_precio}: error calculando métricas — {e}")

        session.commit()
        log.info(f"  {ticker}: {nuevos_precios} precios, {nuevas_metricas} métricas insertadas.")

    log.info("ETL completado.")


# ---------------------------------------------------------------------------
# Backfill de métricas faltantes
# ---------------------------------------------------------------------------

def backfill_metricas(session: Session) -> None:
    """
    Calcula métricas para todos los precios que no las tienen aún,
    siempre que el bono tenga cashflows y exista CER para esa fecha.
    """
    import math
    from sqlalchemy import outerjoin

    log.info("=== Backfill de métricas faltantes ===")

    # Bonos con cashflows
    bonos_con_cfs = session.execute(
        select(Bono).where(Bono.activo == True)
    ).scalars().all()

    total = 0
    for bono in bonos_con_cfs:
        ticker = bono.ticker
        if not _tiene_cashflows(session, ticker):
            continue

        cashflows_metricas = _cashflows_para_metricas(session, ticker)
        if not cashflows_metricas:
            continue

        # Precios sin métrica para este ticker
        precios_sin_metrica = session.execute(
            select(PrecioRaw)
            .outerjoin(MetricaDiaria, PrecioRaw.id == MetricaDiaria.precio_id)
            .where(PrecioRaw.ticker == ticker)
            .where(MetricaDiaria.precio_id == None)
            .order_by(PrecioRaw.fecha)
        ).scalars().all()

        if not precios_sin_metrica:
            continue

        log.info(f"  {ticker}: {len(precios_sin_metrica)} precios sin métricas...")
        nuevas = 0

        for precio_row in precios_sin_metrica:
            if precio_row.cierre is None:
                continue

            cer_fecha = _get_cer_para_fecha(session, precio_row.fecha)
            if cer_fecha is None:
                continue

            try:
                metricas = calcular_metricas(
                    cierre=precio_row.cierre,
                    cashflows=cashflows_metricas,
                    cer_hoy=cer_fecha,
                    fecha_hoy=precio_row.fecha,
                )
                if any(math.isnan(v) for v in metricas.values()):
                    continue

                session.add(MetricaDiaria(
                    precio_id=precio_row.id,
                    tir=Decimal(str(round(metricas["tir"], 8))),
                    duration_modificada=Decimal(str(round(metricas["duration_modificada"], 6))),
                    paridad=Decimal(str(round(metricas["paridad"], 4))),
                    valor_tecnico=Decimal(str(round(metricas["valor_tecnico"], 4))),
                    intereses_corridos=Decimal(str(round(metricas["intereses_corridos"], 4))),
                    valor_residual=Decimal(str(round(metricas["valor_residual"], 4))),
                ))
                nuevas += 1
            except Exception as e:
                log.warning(f"  {ticker} {precio_row.fecha}: error — {e}")

        session.commit()
        log.info(f"  {ticker}: {nuevas} métricas insertadas.")
        total += nuevas

    log.info(f"Backfill completado: {total} métricas en total.")


def _decimal_or_none(val) -> Decimal | None:
    try:
        if val is None or (isinstance(val, float) and val != val):
            return None
        return Decimal(str(val))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    session = SessionLocal()
    try:
        log.info("=== Seed inicial ===")
        seed_initial_data(session)
        log.info("=== ETL ===")
        run_etl(session)
        backfill_metricas(session)
    finally:
        session.close()
