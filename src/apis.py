"""
Funciones de acceso a las APIs externas: Rava, Docta, BCRA.
"""

import os
import warnings
import requests
import pandas as pd
from datetime import date
from dotenv import load_dotenv

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

load_dotenv()

DOCTA_BASE = "https://api.doctacapital.com.ar/api/v1"
RAVA_BASE = "https://admin.rava.com/api/v3/publico/cotizaciones/historicos"
BCRA_CER_ID = 30


def get_docta_token() -> str:
    client_id = os.environ["DOCTA_CLIENT_ID"]
    client_secret = os.environ["DOCTA_TOKEN_SECRET"]
    url = f"{DOCTA_BASE}/auth/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "bonds:read cedears:read stocks:read",
    }
    r = requests.post(url, json=payload)
    r.raise_for_status()
    return r.json()["access_token"]


def fetch_ohlcv(ticker: str, desde: date, hasta: date) -> pd.DataFrame:
    """Retorna OHLCV histórico de Rava para el ticker en el rango dado."""
    data = {
        "especie": ticker,
        "fecha_inicio": desde.strftime("%Y-%m-%d"),
        "fecha_fin": hasta.strftime("%Y-%m-%d"),
        "orden": "asc",
    }
    r = requests.post(RAVA_BASE, data=data)
    r.raise_for_status()
    filas = r.json().get("body", [])
    if not filas:
        return pd.DataFrame(columns=["ticker", "fecha", "apertura", "maximo", "minimo", "cierre", "volumen"])
    df = pd.DataFrame(filas)[["fecha", "apertura", "maximo", "minimo", "cierre", "volumen"]]
    df.insert(0, "ticker", ticker)
    return df


def fetch_cashflows_docta(ticker: str, token: str) -> pd.DataFrame:
    """
    Retorna los cashflows futuros de Docta para el ticker.
    Columnas relevantes: payment_date, adj_capital, adj_interest_amount,
                         residual_value, capital, interest_amount.
    Raises requests.HTTPError si la respuesta no es 2xx.
    """
    url = f"{DOCTA_BASE}/bonds/analytics/{ticker}/cashflow"
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, params={"nominal_units": 100})
    r.raise_for_status()
    data = r.json().get("data", [])
    df = pd.DataFrame(data)
    df.insert(0, "ticker", ticker)
    return df


def fetch_cer(desde: date, hasta: date) -> pd.DataFrame:
    """Retorna el coeficiente CER del BCRA en el rango dado."""
    url = f"https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/{BCRA_CER_ID}"
    params = {"desde": desde.strftime("%Y-%m-%d"), "hasta": hasta.strftime("%Y-%m-%d")}
    r = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        params=params,
        verify=False,
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    filas = []
    for item in results:
        for punto in item.get("detalle", []):
            filas.append({"fecha": punto["fecha"], "valor": punto["valor"]})
    return pd.DataFrame(filas)
