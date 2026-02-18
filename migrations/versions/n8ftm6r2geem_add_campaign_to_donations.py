"""add_campaign_to_donations

Revision ID: n8ftm6r2geem
Revises: b3c4d5e6f7a8
Create Date: 2026-02-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'n8ftm6r2geem'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    # Agregar campaign_id a vistetec_donations
    with op.batch_alter_table('vistetec_donations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('campaign_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_vistetec_donations_campaign',
            'vistetec_pantry_campaigns',
            ['campaign_id'],
            ['id']
        )


def downgrade():
    # Eliminar campaign_id
    with op.batch_alter_table('vistetec_donations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_vistetec_donations_campaign', type_='foreignkey')
        batch_op.drop_column('campaign_id')
