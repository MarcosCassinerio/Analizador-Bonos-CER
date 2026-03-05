"""grupos: reemplazar corto/medio/largo por cer/lecer; agregar X15Y6

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-04

Cambios:
  - Grupos nuevos: 'lecer' y 'cer' (reemplazan corto/medio/largo)
  - LECERs: X15Y6, X29Y6, X31L6, X30N6, TZXA7, TZXY7
  - CER: los 16 restantes (TZX*, TX*, DICP, DIP0, PARP, PAP0, CUAP)
  - Nuevo bono: X15Y6 (LECER May 2026, venc. 2026-05-15)
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from datetime import date

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LECER_TICKERS = ("X29Y6", "X31L6", "X30N6", "TZXA7", "TZXY7")


def upgrade() -> None:
    # 1. Insertar nuevos grupos
    op.execute("INSERT INTO grupos (nombre, descripcion) VALUES ('lecer', 'Letras del Tesoro ajustadas por CER (zero coupon, bullet)')")
    op.execute("INSERT INTO grupos (nombre, descripcion) VALUES ('cer', 'Bonos CER del Tesoro y reestructurados soberanos')")

    # 2. Mover LECERs existentes al grupo lecer
    tickers_sql = ", ".join(f"'{t}'" for t in LECER_TICKERS)
    op.execute(f"UPDATE bonos SET grupo = 'lecer' WHERE ticker IN ({tickers_sql})")

    # 3. Mover todo lo que quede en corto/medio/largo → cer
    op.execute("UPDATE bonos SET grupo = 'cer' WHERE grupo IN ('corto', 'medio', 'largo')")

    # 4. Insertar X15Y6
    op.execute("""
        INSERT INTO bonos (ticker, nombre, grupo, tipo_amortizacion, fecha_vencimiento, activo, created_at)
        VALUES ('X15Y6', 'LECER May 2026', 'lecer', 'bullet', '2026-05-15', true, now())
    """)

    # 5. Eliminar grupos viejos (ya sin bonos apuntando)
    op.execute("DELETE FROM grupos WHERE nombre IN ('corto', 'medio', 'largo')")


def downgrade() -> None:
    # Restaurar grupos viejos
    op.execute("INSERT INTO grupos (nombre, descripcion) VALUES ('corto', 'Bonos CER corto plazo (venc. < 2 años)')")
    op.execute("INSERT INTO grupos (nombre, descripcion) VALUES ('medio', 'Bonos CER mediano plazo (2-5 años)')")
    op.execute("INSERT INTO grupos (nombre, descripcion) VALUES ('largo', 'Bonos CER largo plazo (> 5 años)')")

    # Eliminar X15Y6
    op.execute("DELETE FROM bonos WHERE ticker = 'X15Y6'")

    # Restaurar grupos por duration (aproximado)
    op.execute("""
        UPDATE bonos SET grupo = 'corto'
        WHERE ticker IN ('TZXM6','TZXO6','X29Y6','X30N6','X31L6','TZXD6','TZX26','TX26')
    """)
    op.execute("""
        UPDATE bonos SET grupo = 'medio'
        WHERE ticker IN ('TZXM7','TZXA7','TZXY7','TZX27','TZXD7','TZX28','TX28')
    """)
    op.execute("""
        UPDATE bonos SET grupo = 'largo'
        WHERE ticker IN ('TX31','DICP','DIP0','PARP','PAP0','CUAP')
    """)

    # Eliminar grupos nuevos
    op.execute("DELETE FROM grupos WHERE nombre IN ('lecer', 'cer')")
