"""rename serial_number add itcj_serial id_tecnm

Revision ID: a2b4c6d8e0f2
Revises: cebd1b61e623
Create Date: 2026-03-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a2b4c6d8e0f2'
down_revision = 'cebd1b61e623'
branch_labels = None
depends_on = None


def upgrade():
    # Renombrar serial_number → supplier_serial
    op.alter_column(
        'helpdesk_inventory_items',
        'serial_number',
        new_column_name='supplier_serial',
        existing_type=sa.String(100),
        existing_nullable=True,
    )

    # Ampliar longitud de supplier_serial a 150 (era 100)
    op.alter_column(
        'helpdesk_inventory_items',
        'supplier_serial',
        type_=sa.String(150),
        existing_nullable=True,
    )

    # Renombrar índice antiguo si existe
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'helpdesk_inventory_items'
                AND indexname = 'ix_helpdesk_inventory_items_serial_number'
            ) THEN
                ALTER INDEX ix_helpdesk_inventory_items_serial_number
                    RENAME TO ix_helpdesk_inventory_items_supplier_serial;
            END IF;
        END $$;
    """)

    # Agregar columna itcj_serial
    op.add_column(
        'helpdesk_inventory_items',
        sa.Column('itcj_serial', sa.String(150), nullable=True),
    )
    op.create_unique_constraint(
        'uq_helpdesk_inventory_items_itcj_serial',
        'helpdesk_inventory_items',
        ['itcj_serial'],
    )
    op.create_index(
        'ix_helpdesk_inventory_items_itcj_serial',
        'helpdesk_inventory_items',
        ['itcj_serial'],
    )

    # Agregar columna id_tecnm
    op.add_column(
        'helpdesk_inventory_items',
        sa.Column('id_tecnm', sa.String(100), nullable=True),
    )
    op.create_unique_constraint(
        'uq_helpdesk_inventory_items_id_tecnm',
        'helpdesk_inventory_items',
        ['id_tecnm'],
    )
    op.create_index(
        'ix_helpdesk_inventory_items_id_tecnm',
        'helpdesk_inventory_items',
        ['id_tecnm'],
    )


def downgrade():
    # Eliminar columnas nuevas
    op.drop_index('ix_helpdesk_inventory_items_id_tecnm', table_name='helpdesk_inventory_items')
    op.drop_constraint('uq_helpdesk_inventory_items_id_tecnm', 'helpdesk_inventory_items', type_='unique')
    op.drop_column('helpdesk_inventory_items', 'id_tecnm')

    op.drop_index('ix_helpdesk_inventory_items_itcj_serial', table_name='helpdesk_inventory_items')
    op.drop_constraint('uq_helpdesk_inventory_items_itcj_serial', 'helpdesk_inventory_items', type_='unique')
    op.drop_column('helpdesk_inventory_items', 'itcj_serial')

    # Revertir supplier_serial → serial_number
    op.alter_column(
        'helpdesk_inventory_items',
        'supplier_serial',
        new_column_name='serial_number',
        existing_type=sa.String(150),
        existing_nullable=True,
    )
    op.alter_column(
        'helpdesk_inventory_items',
        'serial_number',
        type_=sa.String(100),
        existing_nullable=True,
    )
