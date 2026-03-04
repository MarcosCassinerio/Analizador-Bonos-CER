"""
Cálculo de métricas de bonos CER:
  - TIR (tasa interna de retorno real, convención argentina CER constante)
  - Duration modificada
  - Valor técnico (VT)
  - Paridad
  - Intereses corridos
  - Valor residual
"""

from datetime import date
from decimal import Decimal

from scipy.optimize import brentq


def calcular_metricas(
    cierre: Decimal,
    cashflows: list[dict],
    cer_hoy: Decimal,
    fecha_hoy: date,
    cotiza_por_residual: bool = False,
) -> dict:
    """
    Calcula las métricas para un bono CER dado el precio de cierre,
    los cashflows futuros (ya ajustados por CER desde Docta) y el CER del día.

    Args:
        cierre: precio de cierre del bono (% del nominal, e.g. 150.5)
        cashflows: lista de dicts con campos:
            - fecha_pago (date)
            - adj_capital (float): capital ajustado por CER
            - adj_interest_amount (float): cupón ajustado por CER
            - capital (float): capital sin ajustar (nominal base)
            - residual_value (float): valor residual % del nominal
        cer_hoy: valor del CER para fecha_hoy
        fecha_hoy: fecha de valuación
        cotiza_por_residual: True si Rava cotiza el bono en ARS por VN 100 RESIDUAL
            (ej. DICP, DIP0). False (default) si cotiza por VN 100 ORIGINAL.

    Returns:
        dict con tir, duration_modificada, paridad, valor_tecnico,
        intereses_corridos, valor_residual
    """
    # Ordenar por fecha de pago
    cfs = sorted(cashflows, key=lambda x: x["fecha_pago"])

    # -------------------------------------------------------------------------
    # Escala CER: ajustar monto_base al CER de la fecha de valuación.
    # adj(d) = monto_base_stored * CER(d) / CER_al_fetch
    # Si cer_al_fetch es None (cashflows sin la nueva columna), factor = 1.0.
    # -------------------------------------------------------------------------
    cer_hoy_f = float(cer_hoy)
    cfs = [
        {
            **cf,
            "adj_capital": float(cf.get("adj_capital", 0)) * (
                cer_hoy_f / float(cf["cer_al_fetch"])
                if cf.get("cer_al_fetch") and float(cf.get("cer_al_fetch", 0)) > 0
                else 1.0
            ),
            "adj_interest_amount": float(cf.get("adj_interest_amount", 0)) * (
                cer_hoy_f / float(cf["cer_al_fetch"])
                if cf.get("cer_al_fetch") and float(cf.get("cer_al_fetch", 0)) > 0
                else 1.0
            ),
        }
        for cf in cfs
    ]

    # Filtrar solo cashflows futuros (fecha_pago > fecha_hoy)
    futuros = [cf for cf in cfs if cf["fecha_pago"] > fecha_hoy]

    if not futuros:
        raise ValueError("No hay cashflows futuros para calcular métricas")

    cierre_f = float(cierre)

    # -------------------------------------------------------------------------
    # Valor residual: % del nominal original aún no pagado hoy
    # = residual_after_next_payment + capital_pct_of_next_payment
    # -------------------------------------------------------------------------
    proximo = futuros[0]
    capital_pct_prox = float(proximo.get("capital_pct", 0))
    residual_after = float(proximo.get("residual_value", 0))
    valor_residual = residual_after + capital_pct_prox

    # -------------------------------------------------------------------------
    # Normalización de precio (solo cuando cotiza_por_residual=True):
    # Algunos bonos (ej. DICP, DIP0) se cotizan en ARS por VN 100 RESIDUAL,
    # pero los cashflows de Docta están en ARS por VN 100 ORIGINAL.
    # precio_normalizado convierte ambas magnitudes a la misma base.
    # Para todos los demás bonos, cotiza_por_residual=False → sin ajuste.
    # -------------------------------------------------------------------------
    if cotiza_por_residual and valor_residual:
        precio_normalizado = cierre_f * (valor_residual / 100.0)
    else:
        precio_normalizado = cierre_f

    # -------------------------------------------------------------------------
    # Valor técnico (VT)
    # VT = suma de adj_capital futuros = capital residual ajustado por CER
    # Equivalente a: residual_pct * CER_factor para cualquier estructura
    # -------------------------------------------------------------------------
    valor_tecnico = sum(float(cf.get("adj_capital", 0)) for cf in futuros)

    # -------------------------------------------------------------------------
    # Intereses corridos: accrual desde último pago hasta hoy
    # -------------------------------------------------------------------------
    pagados = [cf for cf in cfs if cf["fecha_pago"] <= fecha_hoy]
    if pagados:
        ultimo_pago = pagados[-1]["fecha_pago"]
    else:
        # Si no hay pagos anteriores, usar inicio del primer período
        # (asumimos que la fecha de inicio del período es 180 días antes)
        ultimo_pago = date(
            proximo["fecha_pago"].year,
            proximo["fecha_pago"].month,
            proximo["fecha_pago"].day,
        )
        # Retrocedemos un período estimado
        from dateutil.relativedelta import relativedelta
        ultimo_pago = proximo["fecha_pago"] - relativedelta(months=6)

    dias_desde_ultimo = (fecha_hoy - ultimo_pago).days
    dias_del_periodo = (proximo["fecha_pago"] - ultimo_pago).days

    adj_interest_prox = float(proximo.get("adj_interest_amount", 0))

    if dias_del_periodo > 0:
        intereses_corridos = adj_interest_prox * (dias_desde_ultimo / dias_del_periodo)
    else:
        intereses_corridos = 0.0

    # -------------------------------------------------------------------------
    # TIR: scipy brentq resolviendo NPV = 0
    # CF_i = adj_capital_i + adj_interest_i
    # t_i  = (fecha_pago_i - fecha_hoy).days / 365
    # f(r) = sum(CF_i / (1+r)^t_i) - cierre = 0
    # -------------------------------------------------------------------------
    tiempos = []
    flujos = []
    for cf in futuros:
        t = (cf["fecha_pago"] - fecha_hoy).days / 365.0
        cf_total = float(cf.get("adj_capital", 0)) + float(cf.get("adj_interest_amount", 0))
        tiempos.append(t)
        flujos.append(cf_total)

    def npv(r):
        return sum(cf / (1 + r) ** t for cf, t in zip(flujos, tiempos)) - precio_normalizado

    try:
        tir = brentq(npv, -0.9999, 50.0, maxiter=1000)
    except ValueError:
        # Si brentq no converge (e.g. bono muy corto o flujos inusuales)
        tir = float("nan")

    # -------------------------------------------------------------------------
    # Duration modificada
    # D = sum(t_i * CF_i / (1+r)^t_i) / cierre
    # MD = D / (1 + r)
    # -------------------------------------------------------------------------
    if not (tir != tir):  # not NaN
        duration = sum(
            t * cf / (1 + tir) ** t for cf, t in zip(flujos, tiempos)
        ) / precio_normalizado
        duration_modificada = duration / (1 + tir)
    else:
        duration_modificada = float("nan")

    # -------------------------------------------------------------------------
    # Paridad
    # -------------------------------------------------------------------------
    if valor_tecnico and valor_tecnico != 0:
        paridad = precio_normalizado / valor_tecnico * 100
    else:
        paridad = float("nan")

    return {
        "tir": tir,
        "duration_modificada": duration_modificada,
        "paridad": paridad,
        "valor_tecnico": valor_tecnico,
        "intereses_corridos": intereses_corridos,
        "valor_residual": valor_residual,
    }
