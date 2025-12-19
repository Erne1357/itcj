"""rename nip_hash to password_hash, add audit fields

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
    # Renombrar la columna nip_hash a password_hash y agregar campos de auditoría
    with op.batch_alter_table('core_users', schema=None) as batch_op:
        batch_op.alter_column('nip_hash',
                              new_column_name='password_hash',
                              existing_type=sa.Text(),
                              nullable=False)

        # Agregar campos de auditoría
        batch_op.add_column(sa.Column('created_by_id', sa.BigInteger(), nullable=True, server_default='10'))
        batch_op.add_column(sa.Column('updated_by_id', sa.BigInteger(), nullable=True, server_default='10'))

        # Agregar foreign keys para los campos de auditoría
        batch_op.create_foreign_key(
            'core_users_created_by_id_fkey',
            'core_users',
            ['created_by_id'],
            ['id'],
            onupdate='CASCADE',
            ondelete='SET NULL'
        )
        batch_op.create_foreign_key(
            'core_users_updated_by_id_fkey',
            'core_users',
            ['updated_by_id'],
            ['id'],
            onupdate='CASCADE',
            ondelete='SET NULL'
        )


def downgrade():
    # Revertir los cambios
    with op.batch_alter_table('core_users', schema=None) as batch_op:
        # Eliminar foreign keys de auditoría
        batch_op.drop_constraint('core_users_created_by_id_fkey', type_='foreignkey')
        batch_op.drop_constraint('core_users_updated_by_id_fkey', type_='foreignkey')

        # Eliminar columnas de auditoría
        batch_op.drop_column('created_by_id')
        batch_op.drop_column('updated_by_id')

        # Revertir el cambio: renombrar password_hash a nip_hash
        batch_op.alter_column('password_hash',
                              new_column_name='nip_hash',
                              existing_type=sa.Text(),
                              nullable=False)
