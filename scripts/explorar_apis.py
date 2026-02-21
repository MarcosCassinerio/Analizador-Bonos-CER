"""
Script de exploración de APIs.
Muestra los datos crudos que devuelven Rava, Docta y BCRA para un bono de ejemplo.

Uso:
    python scripts/explorar_apis.py

Requiere en .env:
    DOCTA_CLIENT_ID=...
    DOCTA_TOKEN_SECRET=...
"""

import os
import warnings
import requests
import pandas as pd
from datetime import date, timedelta
from dotenv import load_dotenv

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

load_dotenv()

DOCTA_CLIENT_ID = os.environ["DOCTA_CLIENT_ID"]
DOCTA_TOKEN_SECRET = os.environ["DOCTA_TOKEN_SECRET"]
DOCTA_BASE = "https://api.doctacapital.com.ar/api/v1"
RAVA_BASE = "https://admin.rava.com/api/v3/publico/cotizaciones/historicos"
BCRA_CER_ID = 30

BONO_EJEMPLO = "TX26"


def ultimo_dia_habil() -> date:
    dia = date.today() - timedelta(days=1)
    while dia.weekday() >= 5:
        dia -= timedelta(days=1)
    return dia


def get_docta_token() -> str:
    url = f"{DOCTA_BASE}/auth/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": DOCTA_CLIENT_ID,
        "client_secret": DOCTA_TOKEN_SECRET,
        "scope": "bonds:read cedears:read stocks:read",
    }
    r = requests.post(url, json=payload)
    r.raise_for_status()
    return r.json()["access_token"]


def docta_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Rava: precios OHLCV históricos
# ---------------------------------------------------------------------------
def fetch_ohlcv(ticker: str, desde: date, hasta: date) -> pd.DataFrame:
    data = {
        "especie": ticker,
        "fecha_inicio": desde.strftime("%Y-%m-%d"),
        "fecha_fin": hasta.strftime("%Y-%m-%d"),
        "orden": "asc",
    }
    r = requests.post(RAVA_BASE, data=data)
    r.raise_for_status()
    filas = r.json().get("body", [])
    df = pd.DataFrame(filas)[["fecha", "apertura", "maximo", "minimo", "cierre", "volumen"]]
    df.insert(0, "ticker", ticker)
    return df


# ---------------------------------------------------------------------------
# Docta: cashflows
# ---------------------------------------------------------------------------
def fetch_cashflows(ticker: str, token: str) -> pd.DataFrame:
    url = f"{DOCTA_BASE}/bonds/analytics/{ticker}/cashflow"
    r = requests.get(url, headers=docta_headers(token), params={"nominal_units": 100})
    r.raise_for_status()
    data = r.json().get("data", [])
    df = pd.DataFrame(data)
    df.insert(0, "ticker", ticker)
    return df


# ---------------------------------------------------------------------------
# BCRA: coeficiente CER
# ---------------------------------------------------------------------------
def fetch_cer(desde: date, hasta: date) -> pd.DataFrame:
    url = f"https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/{BCRA_CER_ID}"
    params = {"desde": desde.strftime("%Y-%m-%d"), "hasta": hasta.strftime("%Y-%m-%d")}
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, params=params, verify=False)
    r.raise_for_status()
    results = r.json().get("results", [])
    filas = []
    for item in results:
        for punto in item.get("detalle", []):
            filas.append({"fecha": punto["fecha"], "valor": punto["valor"]})
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    dia = ultimo_dia_habil()
    print(f"\nFecha consultada: {dia}\n")

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 120)

    print("=" * 60)
    print(f"RAVA — OHLCV: {BONO_EJEMPLO}")
    print("=" * 60)
    try:
        df_ohlcv = fetch_ohlcv(BONO_EJEMPLO, dia, dia)
        print(df_ohlcv.to_string(index=False))
    except Exception as e:
        print(f"Error: {e}")

    print("\n" + "=" * 60)
    print(f"DOCTA — Cashflows: {BONO_EJEMPLO}")
    print("=" * 60)
    try:
        print("Obteniendo token de Docta...")
        token = get_docta_token()
        df_cf = fetch_cashflows(BONO_EJEMPLO, token)
        print(df_cf.to_string(index=False))
    except Exception as e:
        print(f"Error: {e}")

    print("\n" + "=" * 60)
    print("BCRA — Coeficiente CER")
    print("=" * 60)
    try:
        df_cer = fetch_cer(dia, dia)
        print(df_cer.to_string(index=False))
    except Exception as e:
        print(f"Error: {e}")
