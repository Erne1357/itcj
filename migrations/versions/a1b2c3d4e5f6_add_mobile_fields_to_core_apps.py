"""Add mobile fields to core_apps

Revision ID: a1b2c3d4e5f6
Revises: 955c64adde31
Create Date: 2026-02-04

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '955c64adde31'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('core_apps', schema=None) as batch_op:
        batch_op.add_column(sa.Column('visible_to_students', sa.Boolean(),
                                       nullable=False, server_default=sa.text('FALSE')))
        batch_op.add_column(sa.Column('mobile_icon', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('mobile_url', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('mobile_enabled', sa.Boolean(),
                                       nullable=False, server_default=sa.text('TRUE')))

    # Configurar URLs mobile para apps existentes
    op.execute("UPDATE core_apps SET mobile_url = '/agendatec/' WHERE key = 'agendatec'")
    op.execute("UPDATE core_apps SET mobile_url = '/help-desk/' WHERE key = 'helpdesk'")
    # AgendaTec visible para estudiantes por defecto
    op.execute("UPDATE core_apps SET visible_to_students = TRUE WHERE key = 'agendatec'")

    # Copiar rol 'student' de agendatec a vistetec para todos los usuarios que lo tengan
    # Esto se hace con una sola consulta INSERT...SELECT eficiente
    op.execute("""
        INSERT INTO core_user_app_roles (user_id, app_id, role_id)
        SELECT 
            uar.user_id,
            (SELECT id FROM core_apps WHERE key = 'vistetec'),
            uar.role_id
        FROM core_user_app_roles uar
        INNER JOIN core_apps a ON uar.app_id = a.id
        INNER JOIN core_roles r ON uar.role_id = r.id
        WHERE a.key = 'agendatec' 
          AND r.name = 'student'
          AND (SELECT id FROM core_apps WHERE key = 'vistetec') IS NOT NULL
        ON CONFLICT (user_id, app_id, role_id) DO NOTHING
    """)


def downgrade():
    # Eliminar roles de student en vistetec que fueron copiados de agendatec
    op.execute("""
        DELETE FROM core_user_app_roles
        WHERE app_id = (SELECT id FROM core_apps WHERE key = 'vistetec')
          AND role_id = (SELECT id FROM core_roles WHERE name = 'student')
    """)

    with op.batch_alter_table('core_apps', schema=None) as batch_op:
        batch_op.drop_column('mobile_enabled')
        batch_op.drop_column('mobile_url')
        batch_op.drop_column('mobile_icon')
        batch_op.drop_column('visible_to_students')
