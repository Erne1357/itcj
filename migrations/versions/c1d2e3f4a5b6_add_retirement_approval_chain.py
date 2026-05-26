"""add retirement approval chain

Revision ID: c1d2e3f4a5b6
Revises: b3c5d7e9f1a3
Create Date: 2026-04-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c1d2e3f4a5b6'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- helpdesk_inventory_retirement_requests: agregar oficio_data ---
    op.add_column(
        'helpdesk_inventory_retirement_requests',
        sa.Column('oficio_data', sa.JSON(), nullable=True),
    )

    # --- helpdesk_inventory_retirement_request_items: agregar campos de disposición ---
    op.add_column(
        'helpdesk_inventory_retirement_request_items',
        sa.Column('valor_unitario', sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        'helpdesk_inventory_retirement_request_items',
        sa.Column('desalojo', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.add_column(
        'helpdesk_inventory_retirement_request_items',
        sa.Column('bodega', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.add_column(
        'helpdesk_inventory_retirement_request_items',
        sa.Column('afectacion', sa.Boolean(), nullable=False, server_default='false'),
    )

    # --- helpdesk_inventory_retirement_signatures: tabla nueva ---
    op.create_table(
        'helpdesk_inventory_retirement_signatures',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('step', sa.Integer(), nullable=False),
        sa.Column('position_code', sa.String(50), nullable=False),
        sa.Column('position_title', sa.String(120), nullable=False),
        sa.Column('signed_by_id', sa.BigInteger(), nullable=True),
        sa.Column('signed_at', sa.DateTime(), nullable=True),
        sa.Column('action', sa.String(10), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['request_id'],
            ['helpdesk_inventory_retirement_requests.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['signed_by_id'],
            ['core_users.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_helpdesk_retirement_signatures_request',
        'helpdesk_inventory_retirement_signatures',
        ['request_id'],
    )

    # Permisos de firma: ejecutar database/DML/helpdesk/inventory/06_add_retirement_sign_permissions.sql
    # Comando: python -m itcj2.cli init-retirement-permissions


def downgrade() -> None:
    # Eliminar tabla de firmas
    op.drop_index(
        'ix_helpdesk_retirement_signatures_request',
        table_name='helpdesk_inventory_retirement_signatures',
    )
    op.drop_table('helpdesk_inventory_retirement_signatures')

    # Revertir columnas de items
    op.drop_column('helpdesk_inventory_retirement_request_items', 'afectacion')
    op.drop_column('helpdesk_inventory_retirement_request_items', 'bodega')
    op.drop_column('helpdesk_inventory_retirement_request_items', 'desalojo')
    op.drop_column('helpdesk_inventory_retirement_request_items', 'valor_unitario')

    # Revertir columna de requests
    op.drop_column('helpdesk_inventory_retirement_requests', 'oficio_data')
