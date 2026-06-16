"""titulatec cohort_review_days

Revision ID: a9f477ea220c
Revises: f972f1db2ee5
Create Date: 2026-06-04 11:19:01.958624

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a9f477ea220c'
down_revision = 'f972f1db2ee5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'titulatec_cohort_review_days',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cohort_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('created_by_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['cohort_id'], ['titulatec_cohorts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['core_users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cohort_id', 'date', name='uq_titulatec_cohort_review_days_cohort_date'),
    )
    op.create_index(
        'ix_titulatec_cohort_review_days_cohort_id',
        'titulatec_cohort_review_days',
        ['cohort_id'],
        unique=False,
    )


def downgrade():
    op.drop_index('ix_titulatec_cohort_review_days_cohort_id', table_name='titulatec_cohort_review_days')
    op.drop_table('titulatec_cohort_review_days')
