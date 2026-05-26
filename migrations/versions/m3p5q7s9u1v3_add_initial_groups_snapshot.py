"""add initial_groups_snapshot to InventoryCampaign

Revision ID: m3p5q7s9u1v3
Revises: k9m1n3p5q7s9
Create Date: 2026-05-25 11:00:00

Permite capturar el estado de grupos al cerrar la campaña, para que el jefe
pueda ver al validar qué items entraron/salieron de cada grupo durante el
levantamiento.
"""
from alembic import op
import sqlalchemy as sa


revision = 'm3p5q7s9u1v3'
down_revision = 'k9m1n3p5q7s9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'helpdesk_inventory_campaigns',
        sa.Column('initial_groups_snapshot', sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column('helpdesk_inventory_campaigns', 'initial_groups_snapshot')
