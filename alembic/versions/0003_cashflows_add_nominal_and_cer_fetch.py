"""cashflows: add interest_nominal and cer_al_fetch

Revision ID: 0003
Revises: 0002
Create Date: 2026-02-27

interest_nominal: monto del cupón en términos nominales (sin ajuste CER),
                  equivale al campo interest_amount de la API de Docta.
cer_al_fetch:     valor del CER vigente en el momento en que se guardaron
                  los cashflows desde Docta. Permite escalar monto_base a
                  cualquier fecha de valuación: adj(d) = monto_base * CER(d) / cer_al_fetch.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cashflows", sa.Column("interest_nominal", sa.Numeric(), nullable=True))
    op.add_column("cashflows", sa.Column("cer_al_fetch", sa.Numeric(), nullable=True))


def downgrade() -> None:
    op.drop_column("cashflows", "cer_al_fetch")
    op.drop_column("cashflows", "interest_nominal")
