"""helpdesk config: ticket_status and status_transition

Revision ID: b2d4f6h8j0l2
Revises: a1c3e5g7i9k1
Create Date: 2026-05-11

Agrega tablas para Fase 4 (catálogo de estados editables y grafo de
transiciones) del plan de Configuración del módulo Helpdesk.

Tablas creadas:
  - helpdesk_ticket_status
  - helpdesk_status_transition
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2d4f6h8j0l2'
down_revision = 'a1c3e5g7i9k1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # helpdesk_ticket_status — catálogo de estados con metadatos
    # ------------------------------------------------------------------
    op.create_table(
        'helpdesk_ticket_status',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(30), nullable=False),
        sa.Column('label', sa.String(60), nullable=False),
        sa.Column('color', sa.String(20), nullable=True),
        sa.Column('badge_class', sa.String(80), nullable=True),
        sa.Column('icon', sa.String(60), nullable=True),
        sa.Column('progress_pct', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('stage', sa.String(20), nullable=False),
        sa.Column('is_open', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_resolved', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_terminal', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('display_order', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True,
                  server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_helpdesk_ticket_status_code'),
    )
    op.create_index('ix_helpdesk_ticket_status_code',
                    'helpdesk_ticket_status', ['code'], unique=True)
    op.create_index('ix_helpdesk_ticket_status_is_active',
                    'helpdesk_ticket_status', ['is_active'])

    # ------------------------------------------------------------------
    # helpdesk_status_transition — arcos del grafo de transiciones
    # ------------------------------------------------------------------
    op.create_table(
        'helpdesk_status_transition',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('from_status_id', sa.Integer(), nullable=False),
        sa.Column('to_status_id', sa.Integer(), nullable=False),
        sa.Column('required_perm', sa.String(100), nullable=True),
        sa.Column('required_fields', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True,
                  server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(
            ['from_status_id'], ['helpdesk_ticket_status.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['to_status_id'], ['helpdesk_ticket_status.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('from_status_id', 'to_status_id',
                            name='uq_status_transition'),
    )
    op.create_index('ix_status_transition_from',
                    'helpdesk_status_transition',
                    ['from_status_id', 'is_active'])


def downgrade() -> None:
    op.drop_index('ix_status_transition_from',
                  table_name='helpdesk_status_transition')
    op.drop_table('helpdesk_status_transition')

    op.drop_index('ix_helpdesk_ticket_status_is_active',
                  table_name='helpdesk_ticket_status')
    op.drop_index('ix_helpdesk_ticket_status_code',
                  table_name='helpdesk_ticket_status')
    op.drop_table('helpdesk_ticket_status')
