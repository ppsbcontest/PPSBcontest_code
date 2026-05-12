"""20260512_cancel_expire

Revision ID: 6c3d4e5f6071
Revises: 5b2c3d4e5f60
Create Date: 2026-05-12 17:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6c3d4e5f6071'
down_revision: Union[str, Sequence[str], None] = '5b2c3d4e5f60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'payment_intents',
        sa.Column(
            'expires_at',
            sa.DateTime(),
            nullable=True,
            server_default=sa.text("now() + interval '15 minutes'"),
        ),
    )
    op.execute(
        "UPDATE payment_intents SET expires_at = created_at + interval '15 minutes' "
        "WHERE expires_at IS NULL"
    )
    op.alter_column('payment_intents', 'expires_at', nullable=False)
    op.add_column(
        'payment_intents',
        sa.Column('canceled_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('payment_intents', 'canceled_at')
    op.drop_column('payment_intents', 'expires_at')
