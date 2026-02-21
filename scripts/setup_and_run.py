"""
Script de arranque completo.

Corre todo desde cero:
  1. Migraciones Alembic (idempotente)
  2. Seed de grupos y bonos
  3. ETL: CER, cashflows, precios, métricas
  4. Backfill de métricas faltantes

Uso:
    python scripts/setup_and_run.py

También acepta --check para solo verificar el estado sin cargar datos.
"""

import sys
import logging
import argparse
from pathlib import Path

# Asegurar que src/ sea importable desde cualquier directorio
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paso 1: Migraciones
# ---------------------------------------------------------------------------

def run_migrations() -> None:
    log.info("=== Paso 1: Migraciones Alembic ===")
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(alembic_cfg, "head")
    log.info("Migraciones aplicadas.")


# ---------------------------------------------------------------------------
# Paso 2: Seed + ETL + Backfill
# ---------------------------------------------------------------------------

def run_pipeline() -> None:
    from src.db.session import SessionLocal
    from src.etl import seed_initial_data, run_etl, backfill_metricas

    session = SessionLocal()
    try:
        log.info("=== Paso 2: Seed inicial ===")
        seed_initial_data(session)

        log.info("=== Paso 3: ETL ===")
        run_etl(session)

        log.info("=== Paso 4: Backfill de métricas ===")
        backfill_metricas(session)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# --check: resumen del estado actual sin cargar datos
# ---------------------------------------------------------------------------

def check_status() -> None:
    from sqlalchemy import text
    from src.db.session import SessionLocal

    session = SessionLocal()
    try:
        def count(table: str, where: str = "") -> int:
            q = f"SELECT COUNT(*) FROM {table}"
            if where:
                q += f" WHERE {where}"
            return session.execute(text(q)).scalar() or 0

        bonos_total     = count("bonos")
        bonos_con_cfs   = session.execute(text(
            "SELECT COUNT(DISTINCT ticker) FROM cashflows"
        )).scalar() or 0
        bonos_sin_vcto  = count("bonos", "fecha_vencimiento = '2099-12-31'")
        grupos          = count("grupos")
        cashflows       = count("cashflows")
        precios         = count("precios_raw")
        cer             = count("coeficientes_cer")
        metricas        = count("metricas_diarias")
        sin_metricas    = session.execute(text("""
            SELECT COUNT(*) FROM precios_raw p
            LEFT JOIN metricas_diarias m ON m.precio_id = p.id
            JOIN (SELECT DISTINCT ticker FROM cashflows) cf ON cf.ticker = p.ticker
            WHERE m.precio_id IS NULL
        """)).scalar() or 0

        max_cer = session.execute(text("SELECT MAX(fecha) FROM coeficientes_cer")).scalar()
        max_precio = session.execute(text("SELECT MAX(fecha) FROM precios_raw")).scalar()

        print()
        print("=" * 50)
        print("  Estado del proyecto")
        print("=" * 50)
        print(f"  Grupos:           {grupos}")
        print(f"  Bonos:            {bonos_total} ({bonos_con_cfs} con cashflows, {bonos_sin_vcto} sin vencimiento real)")
        print(f"  Cashflows:        {cashflows}")
        print(f"  Precios:          {precios}  (hasta {max_precio})")
        print(f"  CER:              {cer}  (hasta {max_cer})")
        print(f"  Métricas:         {metricas}  ({sin_metricas} precios con cashflows sin métrica)")
        print("=" * 50)
        print()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup y ETL completo de bonos CER")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Solo muestra el estado actual, sin cargar datos",
    )
    args = parser.parse_args()

    if args.check:
        check_status()
    else:
        run_migrations()
        run_pipeline()
        check_status()
