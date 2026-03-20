"""add inventory retirement requests tables

Revision ID: b3c5d7e9f1a3
Revises: a2b4c6d8e0f2
Create Date: 2026-03-06 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b3c5d7e9f1a3'
down_revision = 'a2b4c6d8e0f2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'helpdesk_inventory_retirement_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('folio', sa.String(20), nullable=False, unique=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='DRAFT'),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('requested_by_id', sa.BigInteger(), sa.ForeignKey('core_users.id'), nullable=False),
        sa.Column('reviewed_by_id',  sa.BigInteger(), sa.ForeignKey('core_users.id'), nullable=True),
        sa.Column('reviewed_at',     sa.DateTime(), nullable=True),
        sa.Column('review_notes',    sa.Text(), nullable=True),
        sa.Column('document_path',          sa.String(500), nullable=True),
        sa.Column('document_original_name', sa.String(255), nullable=True),
        sa.Column('format_generated_at',    sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_retirement_requests_folio',  'helpdesk_inventory_retirement_requests', ['folio'])
    op.create_index('ix_retirement_requests_status', 'helpdesk_inventory_retirement_requests', ['status'])
    op.create_index('ix_retirement_requests_by',     'helpdesk_inventory_retirement_requests', ['requested_by_id'])

    op.create_table(
        'helpdesk_inventory_retirement_request_items',
        sa.Column('id',         sa.Integer(), primary_key=True),
        sa.Column('request_id', sa.Integer(), sa.ForeignKey('helpdesk_inventory_retirement_requests.id', ondelete='CASCADE'), nullable=False),
        sa.Column('item_id',    sa.Integer(), sa.ForeignKey('helpdesk_inventory_items.id'), nullable=False),
        sa.Column('item_notes', sa.Text(), nullable=True),
        sa.UniqueConstraint('request_id', 'item_id', name='uq_retirement_request_item'),
    )
    op.create_index('ix_retirement_request_items_request', 'helpdesk_inventory_retirement_request_items', ['request_id'])
    op.create_index('ix_retirement_request_items_item',    'helpdesk_inventory_retirement_request_items', ['item_id'])


def downgrade():
    op.drop_table('helpdesk_inventory_retirement_request_items')
    op.drop_table('helpdesk_inventory_retirement_requests')
