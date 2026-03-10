"""
ETL principal para bonos CER.

Uso:
    python -m src.etl

Pasos:
  1. seed_initial_data: inserta grupos y bonos si no existen
  2. run_etl: carga CER, cashflows (si faltan) y precios + métricas
"""

import logging
import math
import time
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterator

import requests
from sqlalchemy import delete, func, outerjoin, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.apis import fetch_cashflows_docta, fetch_cer, fetch_ohlcv, get_docta_token
from src.db.models import Bono, Cashflow, CoeficienteCer, Grupo, MetricaDiaria, PrecioRaw
from src.db.session import SessionLocal
from src.enums import FuenteDatos, TipoAmortizacion, TipoCashflow
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
    "lecer": "Letras del Tesoro ajustadas por CER (zero coupon, bullet)",
    "cer": "Bonos CER del Tesoro y reestructurados soberanos",
}

# ticker -> (nombre, grupo, tipo_amortizacion)
BONOS: dict[str, tuple[str, str, TipoAmortizacion]] = {
    # LECERs (Letras del Tesoro CER, zero coupon)
    "X15Y6": ("LECER May 2026", "lecer", TipoAmortizacion.BULLET),
    "X29Y6": ("LECER May 2026 (29)", "lecer", TipoAmortizacion.BULLET),
    "X30N6": ("LECER Nov 2026", "lecer", TipoAmortizacion.BULLET),
    "X31L6": ("LECER Jul 2026", "lecer", TipoAmortizacion.BULLET),
    "TZXA7": ("LECER Abr 2027", "lecer", TipoAmortizacion.BULLET),
    "TZXY7": ("LECER May 2027", "lecer", TipoAmortizacion.BULLET),
    # BONCERs del Tesoro (zero coupon y con amortización)
    "TZXM6": ("BONCER Mar 2026", "cer", TipoAmortizacion.BULLET),
    "TZXO6": ("BONCER Oct 2026", "cer", TipoAmortizacion.BULLET),
    "TZXD6": ("BONCER Dic 2026", "cer", TipoAmortizacion.BULLET),
    "TZX26": ("BONCER 2026", "cer", TipoAmortizacion.BULLET),
    "TX26": ("BONCER TX26", "cer", TipoAmortizacion.CUOTAS),
    "TZXM7": ("BONCER Mar 2027", "cer", TipoAmortizacion.BULLET),
    "TZX27": ("BONCER 2027", "cer", TipoAmortizacion.BULLET),
    "TZXD7": ("BONCER Dic 2027", "cer", TipoAmortizacion.BULLET),
    "TZX28": ("BONCER 2028", "cer", TipoAmortizacion.BULLET),
    "TX28": ("BONCER TX28", "cer", TipoAmortizacion.CUOTAS),
    # BONCERs largos y reestructurados
    "TX31": ("BONCER TX31", "cer", TipoAmortizacion.CUOTAS),
    "DICP": ("DISCOUNT CER", "cer", TipoAmortizacion.BULLET),
    "DIP0": ("DISCOUNT CER 0", "cer", TipoAmortizacion.BULLET),
    "PARP": ("PAR CER", "cer", TipoAmortizacion.BULLET),
    "PAP0": ("PAR CER 0", "cer", TipoAmortizacion.BULLET),
    "CUAP": ("CUASI PAR CER", "cer", TipoAmortizacion.BULLET),
}

# Fecha de vencimiento placeholder (se actualiza con los cashflows de Docta)
FECHA_PLACEHOLDER = date(2099, 12, 31)

# Bonos que Rava cotiza en ARS por VN 100 RESIDUAL (no original).
# El precio debe normalizarse multiplicando por (valor_residual / 100) antes
# de calcular TIR, duration y paridad, para que esté en la misma base que
# los cashflows de Docta (siempre per VN 100 original con nominal_units=100).
COTIZA_POR_RESIDUAL: set[str] = {"DICP", "DIP0"}

# Volumen mínimo (en ARS) para considerar que el precio de un día es representativo.
# Por debajo de este umbral, Rava reporta precios de una o pocas operaciones marginales
# que no reflejan el precio de mercado real. Bonistas y otras fuentes ignoran esos días.
VOLUMEN_MINIMO_ARS: int = 1_000_000

# Bonos cuya API de Docta devuelve cashflows con una base CER diferente a la del prospecto.
# Factores calibrados comparando VT (Bonistas vs nuestro) al mismo CER — 2026-03-08.
# Grupos de error:
#   CUAP  (~41%): Docta usa CER_base 2005, prospecto referencia 2002
#   DICP/DIP0 (~3.3%): Docta usa CER_base ligeramente más alta que el prospecto
#   PAP0/PARP (~1.4%): ídem, menor magnitud
#   TX26/TX28/TX31 (~1.0%): ídem, menor magnitud
#   Resto zero-coupon (~0.27%): offset sistemático menor en CER_base de Docta
ESCALA_CASHFLOWS: dict[str, float] = {
    "CUAP":  1.4072,   # ajustado de 1.4143 → VT_nuestro/VT_bonistas = 0.9950
    "DICP":  1.0335,
    "DIP0":  1.0335,
    "PAP0":  1.0139,
    "PARP":  1.0139,
    "TX26":  1.0092,
    "TX28":  1.0100,
    "TX31":  1.0095,
    "TZX26": 1.0027,
    "TZX27": 1.0027,
    "TZX28": 1.0027,
    "TZXA7": 1.0027,
    "TZXD6": 1.0027,
    "TZXD7": 1.0027,
    "TZXM6": 1.0026,
    "TZXM7": 1.0027,
    "TZXO6": 1.0027,
    "TZXY7": 1.0027,
    "X29Y6": 1.0027,
    "X30N6": 1.0027,
    "X31L6": 1.0027,
    # X15Y6: sin corrección (cer_al_fetch reciente coincide con CER_base de Bonistas)
}

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


def _cashflows_necesitan_fetch(session: Session, ticker: str) -> bool:
    """True si el ticker no tiene cashflows O si alguno tiene cer_al_fetch NULL."""
    total = session.execute(
        select(func.count()).select_from(Cashflow).where(Cashflow.ticker == ticker)
    ).scalar() or 0
    if total == 0:
        return True
    sin_cer = session.execute(
        select(func.count()).select_from(Cashflow)
        .where(Cashflow.ticker == ticker)
        .where(Cashflow.cer_al_fetch == None)
    ).scalar() or 0
    return sin_cer > 0


def _borrar_cashflows_y_metricas(session: Session, ticker: str) -> None:
    """Elimina cashflows y métricas del ticker para forzar re-fetch y recálculo."""
    # Metricas vinculadas a precios del ticker
    precio_ids = session.execute(
        select(PrecioRaw.id).where(PrecioRaw.ticker == ticker)
    ).scalars().all()
    if precio_ids:
        session.execute(
            delete(MetricaDiaria).where(MetricaDiaria.precio_id.in_(precio_ids))
        )

    # Cashflows del ticker
    session.execute(
        delete(Cashflow).where(Cashflow.ticker == ticker)
    )
    session.flush()
    log.info(f"  {ticker}: cashflows y métricas eliminados para re-fetch.")


def _get_cer_para_fecha(session: Session, fecha: date) -> Decimal | None:
    row = session.get(CoeficienteCer, fecha)
    return Decimal(str(row.valor)) if row else None


# ---------------------------------------------------------------------------
# Carga de cashflows de Docta → DB
# ---------------------------------------------------------------------------

def _guardar_cashflows_docta(
    session: Session, ticker: str, df, cer_hoy: Decimal
) -> date | None:
    """
    Parsea el DataFrame de Docta y guarda los cashflows en DB.
    Almacena interest_nominal (cupón sin CER) y cer_al_fetch (CER del día de fetch)
    para permitir escalar monto_base a cualquier fecha de valuación futura.
    Retorna la fecha de vencimiento (max payment_date), o None si df está vacío.
    """
    if df.empty:
        return None

    max_fecha = None
    for _, row in df.iterrows():
        fecha_pago = date.fromisoformat(str(row["payment_date"])[:10])
        if max_fecha is None or fecha_pago > max_fecha:
            max_fecha = fecha_pago

        adj_cap = float(row.get("adj_capital", row.get("capital", 0)) or 0)
        adj_int = float(row.get("adj_interest_amount", row.get("interest_amount", 0)) or 0)
        interest_nominal = float(row.get("interest_amount", 0) or 0)
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
                interest_nominal=None,
                cer_al_fetch=cer_hoy,
            ))
        if adj_int and adj_int != 0:
            session.add(Cashflow(
                ticker=ticker,
                fecha_pago=fecha_pago,
                tipo=TipoCashflow.CUPON,
                monto_base=Decimal(str(adj_int)),
                capital_pct=Decimal(str(capital_pct)),
                residual_pct=Decimal(str(residual_pct)),
                interest_nominal=Decimal(str(interest_nominal)) if interest_nominal else None,
                cer_al_fetch=cer_hoy,
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

    # Factor corrector para bonos cuyo API de Docta usa base CER incorrecta (ver ESCALA_CASHFLOWS)
    escala = ESCALA_CASHFLOWS.get(ticker, 1.0)

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
                "cer_al_fetch": float(r.cer_al_fetch) if r.cer_al_fetch else None,
            }
        if r.tipo.value == "amortizacion":
            por_fecha[fp]["adj_capital"] += float(r.monto_base) * escala
            por_fecha[fp]["capital"] += float(r.monto_base) * escala
            if r.capital_pct is not None:
                por_fecha[fp]["capital_pct"] = float(r.capital_pct)
                por_fecha[fp]["residual_value"] = float(r.residual_pct or 0)
        else:
            por_fecha[fp]["adj_interest_amount"] += float(r.monto_base) * escala
            # Para fechas solo con cupón (sin amortización), guardar residual del cupón
            if r.capital_pct is not None and "capital_pct" not in por_fecha[fp]:
                por_fecha[fp]["capital_pct"] = float(r.capital_pct)
                por_fecha[fp]["residual_value"] = float(r.residual_pct or 0)
        # cer_al_fetch: usar el primero disponible del grupo (todos deberían ser iguales)
        if por_fecha[fp]["cer_al_fetch"] is None and r.cer_al_fetch is not None:
            por_fecha[fp]["cer_al_fetch"] = float(r.cer_al_fetch)

    return sorted(por_fecha.values(), key=lambda x: x["fecha_pago"])


# ---------------------------------------------------------------------------
# ETL principal
# ---------------------------------------------------------------------------

def run_etl(session: Session) -> None:
    ayer = date.today() - timedelta(days=1)
    inicio = date(2015, 1, 1)

    # 1. Token Docta
    log.info("Obteniendo token de Docta...")
    try:
        token = get_docta_token()
    except Exception as e:
        log.error(f"No se pudo obtener token de Docta: {e}")
        token = None

    # 2. Cargar CER desde BCRA (en chunks anuales para evitar límite de 1000 registros)
    log.info("Cargando coeficientes CER...")
    max_cer = _max_fecha_cer(session)
    desde_cer = (max_cer + timedelta(days=1)) if max_cer else inicio
    if desde_cer <= ayer:
        total_cer = 0
        chunk_inicio = desde_cer
        while chunk_inicio <= ayer:
            chunk_fin = min(date(chunk_inicio.year + 1, chunk_inicio.month, chunk_inicio.day) - timedelta(days=1), ayer)
            try:
                df_cer = fetch_cer(chunk_inicio, chunk_fin)
                for _, row in df_cer.iterrows():
                    fecha_cer = date.fromisoformat(str(row["fecha"])[:10])
                    existe = session.get(CoeficienteCer, fecha_cer)
                    if not existe:
                        session.add(CoeficienteCer(fecha=fecha_cer, valor=Decimal(str(row["valor"]))))
                        total_cer += 1
                session.commit()
                log.info(f"CER: chunk {chunk_inicio} → {chunk_fin} cargado ({len(df_cer)} registros).")
            except Exception as e:
                log.error(f"Error cargando CER {chunk_inicio}→{chunk_fin}: {e}")
                session.rollback()
            chunk_inicio = chunk_fin + timedelta(days=1)
        log.info(f"CER: {total_cer} nuevas filas insertadas en total.")
    else:
        log.info("CER ya está actualizado.")

    # 3. Procesar cada bono
    bonos = session.execute(select(Bono).where(Bono.activo == True)).scalars().all()

    for bono in bonos:
        ticker = bono.ticker
        log.info(f"Procesando {ticker}...")

        # 3a. Cashflows: cargar si no existen o si cer_al_fetch es NULL (datos sin escala CER)
        if _cashflows_necesitan_fetch(session, ticker) and token:
            log.info(f"  {ticker}: fetcheando cashflows de Docta...")
            try:
                # Obtener CER del día para guardarlo junto a los cashflows
                cer_hoy_cf = _get_cer_para_fecha(session, ayer)
                if cer_hoy_cf is None:
                    log.warning(f"  {ticker}: sin CER para {ayer}, usando CER más reciente.")
                    cer_hoy_cf = session.execute(
                        select(CoeficienteCer.valor).order_by(CoeficienteCer.fecha.desc()).limit(1)
                    ).scalar()
                    cer_hoy_cf = Decimal(str(cer_hoy_cf)) if cer_hoy_cf else Decimal("1")

                # Borrar cashflows viejos (y métricas asociadas) antes de re-insertar
                if _tiene_cashflows(session, ticker):
                    _borrar_cashflows_y_metricas(session, ticker)

                time.sleep(2)  # evitar rate-limit de Docta entre requests
                df_cf = fetch_cashflows_docta(ticker, token)
                max_fecha = _guardar_cashflows_docta(session, ticker, df_cf, cer_hoy_cf)
                if max_fecha:
                    bono.fecha_vencimiento = max_fecha
                session.commit()
                log.info(f"  {ticker}: {len(df_cf)} filas de cashflows cargadas (cer_al_fetch={cer_hoy_cf}).")
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
        prev_cierre_etl: Decimal | None = None
        prev_volumen_etl: Decimal | None = None

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
            volumen_actual = _decimal_or_none(row.get("volumen"))

            # Actualizar referencia del precio anterior (siempre, para próxima iteración)
            cierre_anterior, volumen_anterior = prev_cierre_etl, prev_volumen_etl
            prev_cierre_etl, prev_volumen_etl = cierre, volumen_actual

            if not (tiene_cfs and cierre and cashflows_metricas):
                continue
            if cierre < Decimal("1"):
                continue

            # Saltar si el precio es idéntico al del día anterior (precio repetido de Rava)
            if cierre == cierre_anterior and volumen_actual == volumen_anterior:
                log.debug(f"  {ticker} {fecha_precio}: precio repetido del día anterior, omitiendo métricas.")
                continue

            # Saltar si el volumen es demasiado bajo (absoluto o relativo al día anterior).
            if volumen_actual is None or volumen_actual < VOLUMEN_MINIMO_ARS:
                log.debug(f"  {ticker} {fecha_precio}: volumen insuficiente ({volumen_actual}), omitiendo métricas.")
                continue
            if volumen_anterior and float(volumen_anterior) > 0:
                ratio = float(volumen_actual) / float(volumen_anterior)
                if ratio < 0.30:
                    log.debug(f"  {ticker} {fecha_precio}: volumen {ratio:.1%} del día anterior, omitiendo métricas.")
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
                    cotiza_por_residual=(ticker in COTIZA_POR_RESIDUAL),
                )
                if any(math.isnan(v) for v in metricas.values()):
                    log.warning(f"  {ticker} {fecha_precio}: métricas con NaN, omitiendo.")
                    continue
                if abs(metricas["tir"]) > 1.0:
                    log.warning(f"  {ticker} {fecha_precio}: TIR={metricas['tir']:.2%} fuera de rango (probable día ex-div), omitiendo.")
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

        # Mapa de todos los precios del ticker para detectar precios repetidos
        todos_precios = session.execute(
            select(PrecioRaw.fecha, PrecioRaw.cierre, PrecioRaw.volumen)
            .where(PrecioRaw.ticker == ticker)
            .order_by(PrecioRaw.fecha)
        ).all()
        prev_precio: dict[date, tuple] = {}
        fechas_ordenadas = sorted(r[0] for r in todos_precios)
        precios_map = {r[0]: (r[1], r[2]) for r in todos_precios}
        for i, f in enumerate(fechas_ordenadas):
            if i > 0:
                prev_precio[f] = precios_map[fechas_ordenadas[i - 1]]

        log.info(f"  {ticker}: {len(precios_sin_metrica)} precios sin métricas...")
        nuevas = 0

        for precio_row in precios_sin_metrica:
            if precio_row.cierre is None or precio_row.cierre < Decimal("1"):
                continue

            # Saltar si el precio (cierre + volumen) es idéntico al del día anterior:
            # Rava repite el último cierre cuando el bono no operó ese día.
            prev = prev_precio.get(precio_row.fecha)
            if prev is not None and prev[0] == precio_row.cierre and prev[1] == precio_row.volumen:
                log.debug(f"  {ticker} {precio_row.fecha}: precio repetido del día anterior, omitiendo.")
                continue

            # Saltar si el volumen es demasiado bajo (absoluto o relativo al día anterior).
            # Un volumen muy bajo indica que el precio viene de una sola operación marginal
            # que no refleja el mercado real (equivalente a lo que hace Bonistas con el
            # precio oficial de BYMA vs el último precio operado de Rava).
            volumen = precio_row.volumen
            if volumen is None or volumen < VOLUMEN_MINIMO_ARS:
                log.debug(f"  {ticker} {precio_row.fecha}: volumen insuficiente ({volumen}), omitiendo.")
                continue
            if prev is not None and prev[1] and float(prev[1]) > 0:
                ratio = float(volumen) / float(prev[1])
                if ratio < 0.30:
                    log.debug(f"  {ticker} {precio_row.fecha}: volumen {ratio:.1%} del día anterior, omitiendo.")
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
                    cotiza_por_residual=(ticker in COTIZA_POR_RESIDUAL),
                )
                if any(math.isnan(v) for v in metricas.values()):
                    continue
                if abs(metricas["tir"]) > 1.0:
                    log.warning(f"  {ticker} {precio_row.fecha}: TIR={metricas['tir']:.2%} fuera de rango (probable día ex-div), omitiendo.")
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
