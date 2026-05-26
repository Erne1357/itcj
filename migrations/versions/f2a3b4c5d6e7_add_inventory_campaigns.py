"""add inventory campaigns and versioning

Revision ID: f2a3b4c5d6e7
Revises: d50f3d9281f2
Create Date: 2026-04-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f2a3b4c5d6e7'
down_revision = 'd50f3d9281f2'
branch_labels = None
depends_on = None


def upgrade():
    # -------------------------------------------------------------------------
    # 1. Tabla principal de campañas de inventario
    # -------------------------------------------------------------------------
    op.create_table(
        'helpdesk_inventory_campaigns',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('folio', sa.String(20), unique=True, nullable=False),
        sa.Column('department_id', sa.Integer(), sa.ForeignKey('core_departments.id'), nullable=False),
        sa.Column('academic_period_id', sa.Integer(), sa.ForeignKey('core_academic_periods.id'), nullable=True),
        sa.Column('status', sa.String(25), nullable=False, server_default='OPEN'),
        # OPEN | PENDING_VALIDATION | VALIDATED | REJECTED
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        # Fechas del ciclo de vida
        sa.Column('started_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('validated_at', sa.DateTime(), nullable=True),
        # Usuarios
        sa.Column('created_by_id', sa.BigInteger(), sa.ForeignKey('core_users.id'), nullable=False),
        sa.Column('closed_by_id', sa.BigInteger(), sa.ForeignKey('core_users.id'), nullable=True),
        sa.Column('validated_by_id', sa.BigInteger(), sa.ForeignKey('core_users.id'), nullable=True),
        # Resultado de validación
        sa.Column('validation_notes', sa.Text(), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        # Auditoría
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    with op.batch_alter_table('helpdesk_inventory_campaigns') as batch_op:
        batch_op.create_index('ix_inv_campaigns_department_id', ['department_id'])
        batch_op.create_index('ix_inv_campaigns_status', ['status'])
        batch_op.create_index('ix_inv_campaigns_academic_period_id', ['academic_period_id'])
        batch_op.create_index('ix_inv_campaigns_dept_status', ['department_id', 'status'])

    # -------------------------------------------------------------------------
    # 2. Tabla de historial de validaciones (registro formal por acción)
    # -------------------------------------------------------------------------
    op.create_table(
        'helpdesk_inventory_campaign_validations',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('campaign_id', sa.BigInteger(), sa.ForeignKey('helpdesk_inventory_campaigns.id'), nullable=False),
        sa.Column('action', sa.String(10), nullable=False),  # APPROVED | REJECTED
        sa.Column('performed_by_id', sa.BigInteger(), sa.ForeignKey('core_users.id'), nullable=False),
        sa.Column('performed_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('items_snapshot', sa.JSON(), nullable=True),
        # {"total": 45, "new_items": [id1, id2...], "existing_items": [...]}
    )
    with op.batch_alter_table('helpdesk_inventory_campaign_validations') as batch_op:
        batch_op.create_index('ix_inv_campaign_validations_campaign_id', ['campaign_id'])
        batch_op.create_index('ix_inv_campaign_validations_performed_by_id', ['performed_by_id'])

    # -------------------------------------------------------------------------
    # 3. Nuevos campos en helpdesk_inventory_items
    # -------------------------------------------------------------------------
    with op.batch_alter_table('helpdesk_inventory_items') as batch_op:
        # Versionado (cadena lineal de sucesión)
        batch_op.add_column(sa.Column(
            'predecessor_item_id',
            sa.BigInteger(),
            sa.ForeignKey('helpdesk_inventory_items.id', ondelete='SET NULL'),
            nullable=True,
        ))
        batch_op.create_index('ix_inventory_items_predecessor', ['predecessor_item_id'])

        # Campaña de inventario a la que pertenece este item
        batch_op.add_column(sa.Column(
            'campaign_id',
            sa.BigInteger(),
            sa.ForeignKey('helpdesk_inventory_campaigns.id', ondelete='SET NULL'),
            nullable=True,
        ))
        batch_op.create_index('ix_inventory_items_campaign_id', ['campaign_id'])

        # Bloqueo tras validación
        batch_op.add_column(sa.Column('is_locked', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('validated_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column(
            'validated_by_id',
            sa.BigInteger(),
            sa.ForeignKey('core_users.id', ondelete='SET NULL'),
            nullable=True,
        ))
        batch_op.add_column(sa.Column(
            'locked_campaign_id',
            sa.BigInteger(),
            sa.ForeignKey('helpdesk_inventory_campaigns.id', ondelete='SET NULL'),
            nullable=True,
        ))


def downgrade():
    with op.batch_alter_table('helpdesk_inventory_items') as batch_op:
        batch_op.drop_index('ix_inventory_items_campaign_id')
        batch_op.drop_index('ix_inventory_items_predecessor')
        batch_op.drop_column('locked_campaign_id')
        batch_op.drop_column('validated_by_id')
        batch_op.drop_column('validated_at')
        batch_op.drop_column('is_locked')
        batch_op.drop_column('campaign_id')
        batch_op.drop_column('predecessor_item_id')

    with op.batch_alter_table('helpdesk_inventory_campaign_validations') as batch_op:
        batch_op.drop_index('ix_inv_campaign_validations_performed_by_id')
        batch_op.drop_index('ix_inv_campaign_validations_campaign_id')
    op.drop_table('helpdesk_inventory_campaign_validations')

    with op.batch_alter_table('helpdesk_inventory_campaigns') as batch_op:
        batch_op.drop_index('ix_inv_campaigns_dept_status')
        batch_op.drop_index('ix_inv_campaigns_academic_period_id')
        batch_op.drop_index('ix_inv_campaigns_status')
        batch_op.drop_index('ix_inv_campaigns_department_id')
    op.drop_table('helpdesk_inventory_campaigns')
