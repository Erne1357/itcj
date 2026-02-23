"""add_maintenance_fields_to_ticket

Revision ID: h7k9m2p4q6s8
Revises: n8ftm6r2geem
Create Date: 2026-02-19

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'h7k9m2p4q6s8'
down_revision = 'n8ftm6r2geem'
branch_labels = None
depends_on = None


def upgrade():
    # Agregar campos de mantenimiento al ticket
    op.add_column('helpdesk_ticket', sa.Column('maintenance_type', sa.String(length=20), nullable=True))
    op.add_column('helpdesk_ticket', sa.Column('service_origin', sa.String(length=20), nullable=True))
    op.add_column('helpdesk_ticket', sa.Column('observations', sa.Text(), nullable=True))

    # Asignar valores por defecto a tickets existentes
    op.execute("UPDATE helpdesk_ticket SET maintenance_type = 'CORRECTIVO' WHERE maintenance_type IS NULL")
    op.execute("UPDATE helpdesk_ticket SET service_origin = 'INTERNO' WHERE service_origin IS NULL")


def downgrade():
    op.drop_column('helpdesk_ticket', 'observations')
    op.drop_column('helpdesk_ticket', 'service_origin')
    op.drop_column('helpdesk_ticket', 'maintenance_type')
