"""cashflows: add capital_pct and residual_pct

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-21

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cashflows", sa.Column("capital_pct", sa.Numeric(), nullable=True))
    op.add_column("cashflows", sa.Column("residual_pct", sa.Numeric(), nullable=True))


def downgrade() -> None:
    op.drop_column("cashflows", "residual_pct")
    op.drop_column("cashflows", "capital_pct")
