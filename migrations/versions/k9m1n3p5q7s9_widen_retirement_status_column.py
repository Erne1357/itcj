"""widen retirement request status column to varchar(40)

Revision ID: k9m1n3p5q7s9
Revises: h2j4l6n8p0r2
Create Date: 2026-05-25 10:00:00

Necesario porque los nuevos estados de firma multi-paso
'AWAITING_RECURSOS_MATERIALES' (30 chars) no caben en varchar(20).
"""
from alembic import op
import sqlalchemy as sa


revision = 'k9m1n3p5q7s9'
down_revision = 'h2j4l6n8p0r2'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'helpdesk_inventory_retirement_requests',
        'status',
        existing_type=sa.String(length=20),
        type_=sa.String(length=40),
        existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        'helpdesk_inventory_retirement_requests',
        'status',
        existing_type=sa.String(length=40),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
