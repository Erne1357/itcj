"""titulatec cotejo requirements

Revision ID: e8368b899ed1
Revises: a9f477ea220c
Create Date: 2026-06-08 09:50:12.360492

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e8368b899ed1'
down_revision = 'a9f477ea220c'
branch_labels = None
depends_on = None


def upgrade():
    # Solo la tabla nueva de TitulaTec. El autogenerate detectó drift de otras
    # apps (helpdesk/inventory) que NO pertenece a esta migración y se omite.
    op.create_table('titulatec_cotejo_requirements',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cohort_id', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('hint', sa.String(length=255), nullable=True),
    sa.Column('icon', sa.String(length=40), server_default=sa.text("'check2-square'"), nullable=False),
    sa.Column('order_index', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_required', sa.Boolean(), server_default=sa.text('TRUE'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('TRUE'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
    sa.ForeignKeyConstraint(['cohort_id'], ['titulatec_cohorts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_titulatec_cotejo_requirements_cohort_id'), 'titulatec_cotejo_requirements', ['cohort_id'], unique=False)
    op.create_index(op.f('ix_titulatec_cotejo_requirements_is_active'), 'titulatec_cotejo_requirements', ['is_active'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_titulatec_cotejo_requirements_is_active'), table_name='titulatec_cotejo_requirements')
    op.drop_index(op.f('ix_titulatec_cotejo_requirements_cohort_id'), table_name='titulatec_cotejo_requirements')
    op.drop_table('titulatec_cotejo_requirements')
