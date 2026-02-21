"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-02-21

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

tipo_amortizacion_enum = sa.Enum("bullet", "cuotas", name="tipo_amortizacion_enum")
tipo_cashflow_enum = sa.Enum("cupon", "amortizacion", name="tipo_cashflow_enum")


def upgrade() -> None:
    op.create_table(
        "grupos",
        sa.Column("nombre", sa.String(), nullable=False),
        sa.Column("descripcion", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("nombre"),
    )

    op.create_table(
        "bonos",
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("nombre", sa.String(), nullable=False),
        sa.Column("grupo", sa.String(), sa.ForeignKey("grupos.nombre"), nullable=False),
        sa.Column("tipo_amortizacion", tipo_amortizacion_enum, nullable=False),
        sa.Column("fecha_vencimiento", sa.Date(), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("ticker"),
    )

    op.create_table(
        "cashflows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("fecha_pago", sa.Date(), nullable=False),
        sa.Column("tipo", tipo_cashflow_enum, nullable=False),
        sa.Column("monto_base", sa.Numeric(), nullable=False),
        sa.ForeignKeyConstraint(["ticker"], ["bonos.ticker"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "precios_raw",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("apertura", sa.Numeric(), nullable=True),
        sa.Column("maximo", sa.Numeric(), nullable=True),
        sa.Column("minimo", sa.Numeric(), nullable=True),
        sa.Column("cierre", sa.Numeric(), nullable=True),
        sa.Column("volumen", sa.Numeric(), nullable=True),
        sa.Column("fuente", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["ticker"], ["bonos.ticker"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "fecha", name="uq_precio_ticker_fecha"),
    )


    op.create_table(
        "coeficientes_cer",
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("valor", sa.Numeric(), nullable=False),
        sa.PrimaryKeyConstraint("fecha"),
    )

    op.create_table(
        "metricas_diarias",
        sa.Column("precio_id", sa.Integer(), nullable=False),
        sa.Column("tir", sa.Numeric(), nullable=False),
        sa.Column("duration_modificada", sa.Numeric(), nullable=False),
        sa.Column("paridad", sa.Numeric(), nullable=False),
        sa.Column("valor_tecnico", sa.Numeric(), nullable=False),
        sa.Column("intereses_corridos", sa.Numeric(), nullable=False),
        sa.Column("valor_residual", sa.Numeric(), nullable=False),
        sa.ForeignKeyConstraint(["precio_id"], ["precios_raw.id"]),
        sa.PrimaryKeyConstraint("precio_id"),
    )


def downgrade() -> None:
    op.drop_table("metricas_diarias")
    op.drop_table("coeficientes_cer")
    op.drop_table("precios_raw")
    op.drop_table("cashflows")
    op.drop_table("bonos")
    op.drop_table("grupos")
    tipo_cashflow_enum.drop(op.get_bind())
    tipo_amortizacion_enum.drop(op.get_bind())
