"""rename nip_hash to password_hash in core_users

Revision ID: f1a2b3c4d5e6
Revises: split_fullname_to_parts
Create Date: 2025-12-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = 'split_fullname_to_parts'
branch_labels = None
depends_on = None


def upgrade():
    # Renombrar la columna nip_hash a password_hash
    with op.batch_alter_table('core_users', schema=None) as batch_op:
        batch_op.alter_column('nip_hash',
                              new_column_name='password_hash',
                              existing_type=sa.Text(),
                              nullable=False)


def downgrade():
    # Revertir el cambio: renombrar password_hash a nip_hash
    with op.batch_alter_table('core_users', schema=None) as batch_op:
        batch_op.alter_column('password_hash',
                              new_column_name='nip_hash',
                              existing_type=sa.Text(),
                              nullable=False)
