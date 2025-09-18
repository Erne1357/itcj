"""Cambio en los nombres de las tablas y secuencias en la base de datos

Revision ID: 1f91a6f1f3c6
Revises: 4fc261c4f603
Create Date: 2025-09-18 12:34:13.030187

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '1f91a6f1f3c6'
down_revision = '4fc261c4f603'
branch_labels = None
depends_on = None

def upgrade():
    # Deshabilitar temporalmente la revisión de claves foráneas para evitar errores
    op.execute('SET session_replication_role = replica;')

    # Renombrar tablas
    op.rename_table('audit_logs', 'agendatec_audit_logs')
    op.rename_table('requests', 'agendatec_requests')
    op.rename_table('availability_windows', 'agendatec_availability_windows')
    op.rename_table('survey_dispatches', 'agendatec_survey_dispatches')
    op.rename_table('time_slots', 'agendatec_time_slots')
    op.rename_table('appointments', 'agendatec_appointments')
    op.rename_table('notifications', 'agendatec_notifications')

    # Renombrar secuencias asociadas a las tablas
    op.execute("ALTER SEQUENCE audit_logs_id_seq RENAME TO agendatec_audit_logs_id_seq;")
    op.execute("ALTER SEQUENCE requests_id_seq RENAME TO agendatec_requests_id_seq;")
    op.execute("ALTER SEQUENCE availability_windows_id_seq RENAME TO agendatec_availability_windows_id_seq;")
    op.execute("ALTER SEQUENCE survey_dispatches_id_seq RENAME TO agendatec_survey_dispatches_id_seq;")
    op.execute("ALTER SEQUENCE time_slots_id_seq RENAME TO agendatec_time_slots_id_seq;")
    op.execute("ALTER SEQUENCE appointments_id_seq RENAME TO agendatec_appointments_id_seq;")
    op.execute("ALTER SEQUENCE notifications_id_seq RENAME TO agendatec_notifications_id_seq;")

    # Habilitar nuevamente la revisión de claves foráneas
    op.execute('SET session_replication_role = DEFAULT;')

def downgrade():
    # Deshabilitar temporalmente la revisión de claves foráneas
    op.execute('SET session_replication_role = replica;')
    
    # Revertir el nombre de las secuencias
    op.execute("ALTER SEQUENCE agendatec_audit_logs_id_seq RENAME TO audit_logs_id_seq;")
    op.execute("ALTER SEQUENCE agendatec_requests_id_seq RENAME TO requests_id_seq;")
    op.execute("ALTER SEQUENCE agendatec_availability_windows_id_seq RENAME TO availability_windows_id_seq;")
    op.execute("ALTER SEQUENCE agendatec_survey_dispatches_id_seq RENAME TO survey_dispatches_id_seq;")
    op.execute("ALTER SEQUENCE agendatec_time_slots_id_seq RENAME TO time_slots_id_seq;")
    op.execute("ALTER SEQUENCE agendatec_appointments_id_seq RENAME TO appointments_id_seq;")
    op.execute("ALTER SEQUENCE agendatec_notifications_id_seq RENAME TO notifications_id_seq;")

    # Revertir el nombre de las tablas
    op.rename_table('agendatec_audit_logs', 'audit_logs')
    op.rename_table('agendatec_requests', 'requests')
    op.rename_table('agendatec_availability_windows', 'availability_windows')
    op.rename_table('agendatec_survey_dispatches', 'survey_dispatches')
    op.rename_table('agendatec_time_slots', 'time_slots')
    op.rename_table('agendatec_appointments', 'appointments')
    op.rename_table('agendatec_notifications', 'notifications')

    # Habilitar nuevamente la revisión de claves foráneas
    op.execute('SET session_replication_role = DEFAULT;')