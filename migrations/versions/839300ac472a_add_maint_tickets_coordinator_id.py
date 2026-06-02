"""add_maint_tickets_coordinator_id

Revision ID: 839300ac472a
Revises: f387d87239ec
Create Date: 2026-06-02 08:16:02.314172

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '839300ac472a'
down_revision = 'f387d87239ec'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('maint_tickets', sa.Column('coordinator_id', sa.BigInteger(), nullable=True))
    op.create_index(op.f('ix_maint_tickets_coordinator_id'), 'maint_tickets', ['coordinator_id'], unique=False)
    op.create_foreign_key(
        'fk_maint_tickets_coordinator_id',
        'maint_tickets', 'core_users',
        ['coordinator_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_maint_tickets_coordinator_id', 'maint_tickets', type_='foreignkey')
    op.drop_index(op.f('ix_maint_tickets_coordinator_id'), table_name='maint_tickets')
    op.drop_column('maint_tickets', 'coordinator_id')
