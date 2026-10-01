"""sgc initial schema

Las 22 tablas de la app Sgc (Calidad): 14 de entidad mutable, 5 de
catálogo/singleton y 3 de asociación. Ver `docs/sgi/sgc/PLAN_MIGRACION_SGC.md`
§2 para la especificación completa.

NOTA SOBRE EL AUTOGENERATE: la ejecución de `alembic revision --autogenerate`
detectó ~110 líneas de drift ajeno a este cambio (un `DROP TABLE
titulatec_cotejo_requirements` y renombrados de índices de agendatec/core/
helpdesk que existen en la BD real pero no en los modelos actuales, y
viceversa — igual que documentó `f6feb1cdc56a_agendatec_slot_program_scope.py`
para su propio autogenerate). Ese drift se eliminó a mano: esta migración
contiene EXCLUSIVAMENTE las 22 tablas nuevas de `sgc`.

Revision ID: 23004eb05186
Revises: tt20260929a
Create Date: 2026-08-25 10:33:24.356470

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '23004eb05186'
# Repunteada al integrar la rama de sgc en main (2026-09-30): la revision
# original (f6feb1cdc56a) sigue siendo ancestro, pero colgar de ella dejaba DOS
# cabezas de Alembic. Ninguna base tenia estas tablas aplicadas, asi que el
# repunte es seguro y no necesita un merge de revisiones.
down_revision = 'tt20260929a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sgc_approval_flows',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('sgc_areas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('color', sa.String(length=7), server_default=sa.text("'#4834d4'"), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_sgc_areas_is_active'), 'sgc_areas', ['is_active'], unique=False)
    op.create_table('sgc_document_categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('sgc_document_classifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('sgc_incident_categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('sgc_indicator_years',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('year')
    )
    op.create_table('sgc_mail_config',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('id = 1', name='ck_sgc_mail_config_singleton'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('sgc_processes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('color', sa.String(length=7), server_default=sa.text("'#b2bec3'"), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('sgc_program_categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('sgc_approval_flow_steps',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('flow_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('days_limit', sa.Integer(), server_default=sa.text('3'), nullable=False),
    sa.Column('step_order', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['flow_id'], ['sgc_approval_flows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('flow_id', 'step_order', name='uq_sgc_approval_flow_steps_flow_order')
    )
    op.create_index(op.f('ix_sgc_approval_flow_steps_flow_id'), 'sgc_approval_flow_steps', ['flow_id'], unique=False)
    op.create_table('sgc_indicators',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('year_id', sa.Integer(), nullable=False),
    sa.Column('process_id', sa.Integer(), nullable=False),
    sa.Column('objective', sa.String(length=255), nullable=True),
    sa.Column('prev_results', sa.String(length=255), nullable=True),
    sa.Column('unit_calc', sa.String(length=255), nullable=True),
    sa.Column('responsible', sa.String(length=255), nullable=True),
    sa.Column('facilitator', sa.String(length=255), nullable=True),
    sa.Column('source', sa.String(length=255), nullable=True),
    sa.Column('strategic_rel', sa.Text(), nullable=True),
    sa.Column('criteria', sa.Text(), nullable=True),
    sa.Column('plan_b', sa.Text(), nullable=True),
    sa.Column('document_url', sa.String(length=255), nullable=True),
    sa.Column('frequency', sa.String(length=50), nullable=True),
    sa.Column('planned_white', sa.String(length=50), nullable=True),
    sa.Column('planned_red', sa.String(length=50), nullable=True),
    sa.Column('planned_yellow', sa.String(length=50), nullable=True),
    sa.Column('planned_green', sa.String(length=50), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("frequency IN ('Semanal','Mensual','Anual')", name='ck_sgc_indicators_frequency'),
    sa.ForeignKeyConstraint(['process_id'], ['sgc_processes.id'], ),
    sa.ForeignKeyConstraint(['year_id'], ['sgc_indicator_years.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sgc_indicators_process_id'), 'sgc_indicators', ['process_id'], unique=False)
    op.create_index(op.f('ix_sgc_indicators_year_id'), 'sgc_indicators', ['year_id'], unique=False)
    op.create_table('sgc_documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('version', sa.String(length=10), server_default=sa.text("'1.0'"), nullable=False),
    sa.Column('status', sa.String(length=50), server_default=sa.text("'Borrador'"), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('approval_date', sa.DateTime(), nullable=True),
    sa.Column('file_url', sa.String(length=255), nullable=True),
    sa.Column('category_id', sa.Integer(), nullable=True),
    sa.Column('area_id', sa.Integer(), nullable=True),
    sa.Column('process_id', sa.Integer(), nullable=True),
    sa.Column('classification_id', sa.Integer(), nullable=True),
    sa.Column('flow_id', sa.Integer(), nullable=True),
    sa.Column('current_step_id', sa.Integer(), nullable=True),
    sa.Column('author_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('Borrador','En Revisión','Aprobado','Rechazado')", name='ck_sgc_documents_status'),
    sa.ForeignKeyConstraint(['area_id'], ['sgc_areas.id'], ),
    sa.ForeignKeyConstraint(['author_id'], ['core_users.id'], ),
    sa.ForeignKeyConstraint(['category_id'], ['sgc_document_categories.id'], ),
    sa.ForeignKeyConstraint(['classification_id'], ['sgc_document_classifications.id'], ),
    sa.ForeignKeyConstraint(['current_step_id'], ['sgc_approval_flow_steps.id'], ),
    sa.ForeignKeyConstraint(['flow_id'], ['sgc_approval_flows.id'], ),
    sa.ForeignKeyConstraint(['process_id'], ['sgc_processes.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sgc_documents_area_id'), 'sgc_documents', ['area_id'], unique=False)
    op.create_index(op.f('ix_sgc_documents_author_id'), 'sgc_documents', ['author_id'], unique=False)
    op.create_index(op.f('ix_sgc_documents_category_id'), 'sgc_documents', ['category_id'], unique=False)
    op.create_index(op.f('ix_sgc_documents_classification_id'), 'sgc_documents', ['classification_id'], unique=False)
    op.create_index(op.f('ix_sgc_documents_code'), 'sgc_documents', ['code'], unique=False)
    op.create_index(op.f('ix_sgc_documents_current_step_id'), 'sgc_documents', ['current_step_id'], unique=False)
    op.create_index(op.f('ix_sgc_documents_flow_id'), 'sgc_documents', ['flow_id'], unique=False)
    op.create_index(op.f('ix_sgc_documents_process_id'), 'sgc_documents', ['process_id'], unique=False)
    op.create_table('sgc_flow_step_assignees',
    sa.Column('step_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('notify_on_overdue', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.ForeignKeyConstraint(['step_id'], ['sgc_approval_flow_steps.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['core_users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('step_id', 'user_id')
    )
    op.create_index('ix_sgc_flow_step_assignees_user_id', 'sgc_flow_step_assignees', ['user_id'], unique=False)
    op.create_table('sgc_incidents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('folio', sa.String(length=50), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('commitment_date', sa.Date(), nullable=True),
    sa.Column('real_date', sa.Date(), nullable=True),
    sa.Column('priority', sa.String(length=20), server_default=sa.text("'Media'"), nullable=False),
    sa.Column('status', sa.String(length=50), server_default=sa.text("'No Iniciada'"), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=True),
    sa.Column('area_id', sa.Integer(), nullable=True),
    sa.Column('process_id', sa.Integer(), nullable=True),
    sa.Column('responsible_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("priority IN ('Baja','Media','Alta','Urgente')", name='ck_sgc_incidents_priority'),
    sa.CheckConstraint("status IN ('No Iniciada','Iniciada','Cerrada')", name='ck_sgc_incidents_status'),
    sa.ForeignKeyConstraint(['area_id'], ['sgc_areas.id'], ),
    sa.ForeignKeyConstraint(['category_id'], ['sgc_incident_categories.id'], ),
    sa.ForeignKeyConstraint(['process_id'], ['sgc_processes.id'], ),
    sa.ForeignKeyConstraint(['responsible_id'], ['core_users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sgc_incidents_area_id'), 'sgc_incidents', ['area_id'], unique=False)
    op.create_index(op.f('ix_sgc_incidents_category_id'), 'sgc_incidents', ['category_id'], unique=False)
    op.create_index(op.f('ix_sgc_incidents_folio'), 'sgc_incidents', ['folio'], unique=False)
    op.create_index(op.f('ix_sgc_incidents_process_id'), 'sgc_incidents', ['process_id'], unique=False)
    op.create_index(op.f('ix_sgc_incidents_responsible_id'), 'sgc_incidents', ['responsible_id'], unique=False)
    op.create_table('sgc_indicator_trackings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('indicator_id', sa.Integer(), nullable=False),
    sa.Column('period_index', sa.Integer(), nullable=False),
    sa.Column('real_value', sa.String(length=100), nullable=True),
    sa.Column('color', sa.String(length=50), server_default=sa.text("'blanco'"), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("color IN ('blanco','rojo','amarillo','verde')", name='ck_sgc_indicator_trackings_color'),
    sa.ForeignKeyConstraint(['indicator_id'], ['sgc_indicators.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('indicator_id', 'period_index', name='uq_sgc_indicator_trackings_indicator_period')
    )
    op.create_index(op.f('ix_sgc_indicator_trackings_indicator_id'), 'sgc_indicator_trackings', ['indicator_id'], unique=False)
    op.create_table('sgc_program_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('folio', sa.String(length=50), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('commitment_date', sa.Date(), nullable=True),
    sa.Column('real_date', sa.Date(), nullable=True),
    sa.Column('priority', sa.String(length=20), server_default=sa.text("'Media'"), nullable=False),
    sa.Column('status', sa.String(length=50), server_default=sa.text("'Planeado'"), nullable=False),
    sa.Column('location', sa.String(length=100), nullable=True),
    sa.Column('category_id', sa.Integer(), nullable=True),
    sa.Column('area_id', sa.Integer(), nullable=True),
    sa.Column('process_id', sa.Integer(), nullable=True),
    sa.Column('responsible_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("priority IN ('Baja','Media','Alta','Urgente')", name='ck_sgc_program_events_priority'),
    sa.CheckConstraint("status IN ('Planeado','En Proceso','Completado')", name='ck_sgc_program_events_status'),
    sa.ForeignKeyConstraint(['area_id'], ['sgc_areas.id'], ),
    sa.ForeignKeyConstraint(['category_id'], ['sgc_program_categories.id'], ),
    sa.ForeignKeyConstraint(['process_id'], ['sgc_processes.id'], ),
    sa.ForeignKeyConstraint(['responsible_id'], ['core_users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sgc_program_events_area_id'), 'sgc_program_events', ['area_id'], unique=False)
    op.create_index(op.f('ix_sgc_program_events_category_id'), 'sgc_program_events', ['category_id'], unique=False)
    op.create_index(op.f('ix_sgc_program_events_folio'), 'sgc_program_events', ['folio'], unique=False)
    op.create_index(op.f('ix_sgc_program_events_process_id'), 'sgc_program_events', ['process_id'], unique=False)
    op.create_index(op.f('ix_sgc_program_events_responsible_id'), 'sgc_program_events', ['responsible_id'], unique=False)
    op.create_table('sgc_user_areas',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('area_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['area_id'], ['sgc_areas.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['core_users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'area_id')
    )
    op.create_index('ix_sgc_user_areas_area_id', 'sgc_user_areas', ['area_id'], unique=False)
    op.create_table('sgc_program_event_files',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=False),
    sa.Column('file_path', sa.String(length=255), nullable=False),
    sa.Column('original_name', sa.String(length=255), nullable=False),
    sa.Column('mime_type', sa.String(length=100), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=True),
    sa.Column('uploaded_by_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['sgc_program_events.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by_id'], ['core_users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sgc_program_event_files_event_id'), 'sgc_program_event_files', ['event_id'], unique=False)
    op.create_index(op.f('ix_sgc_program_event_files_uploaded_by_id'), 'sgc_program_event_files', ['uploaded_by_id'], unique=False)
    op.create_table('sgc_tasks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=50), server_default=sa.text("'Pendiente'"), nullable=False),
    sa.Column('priority', sa.String(length=20), server_default=sa.text("'Media'"), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('created_by_id', sa.BigInteger(), nullable=True),
    sa.Column('incident_id', sa.Integer(), nullable=True),
    sa.Column('program_id', sa.Integer(), nullable=True),
    sa.Column('document_id', sa.Integer(), nullable=True),
    sa.Column('flow_step_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("priority IN ('Baja','Media','Alta','Urgente')", name='ck_sgc_tasks_priority'),
    sa.CheckConstraint("status IN ('Pendiente','En Proceso','En Revisión','En Espera','Completada','Rechazada')", name='ck_sgc_tasks_status'),
    sa.CheckConstraint('(incident_id IS NOT NULL)::int + (program_id IS NOT NULL)::int + (document_id IS NOT NULL)::int = 1', name='ck_sgc_tasks_single_parent'),
    sa.ForeignKeyConstraint(['created_by_id'], ['core_users.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['sgc_documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['flow_step_id'], ['sgc_approval_flow_steps.id'], ),
    sa.ForeignKeyConstraint(['incident_id'], ['sgc_incidents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['program_id'], ['sgc_program_events.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sgc_tasks_created_by_id'), 'sgc_tasks', ['created_by_id'], unique=False)
    op.create_index(op.f('ix_sgc_tasks_document_id'), 'sgc_tasks', ['document_id'], unique=False)
    op.create_index(op.f('ix_sgc_tasks_flow_step_id'), 'sgc_tasks', ['flow_step_id'], unique=False)
    op.create_index(op.f('ix_sgc_tasks_incident_id'), 'sgc_tasks', ['incident_id'], unique=False)
    op.create_index(op.f('ix_sgc_tasks_program_id'), 'sgc_tasks', ['program_id'], unique=False)
    op.create_table('sgc_task_assignees',
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('notified_overdue', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['sgc_tasks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['core_users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('task_id', 'user_id')
    )
    op.create_index('ix_sgc_task_assignees_user_id', 'sgc_task_assignees', ['user_id'], unique=False)
    op.create_table('sgc_task_comments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('comment', sa.Text(), nullable=False),
    sa.Column('file_path', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['sgc_tasks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['core_users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sgc_task_comments_task_id'), 'sgc_task_comments', ['task_id'], unique=False)
    op.create_index(op.f('ix_sgc_task_comments_user_id'), 'sgc_task_comments', ['user_id'], unique=False)
    op.create_table('sgc_task_approvals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('decision', sa.String(length=20), nullable=False),
    sa.Column('comment_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("decision IN ('aprobado','rechazado')", name='ck_sgc_task_approvals_decision'),
    sa.ForeignKeyConstraint(['comment_id'], ['sgc_task_comments.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['sgc_tasks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['core_users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('task_id', 'user_id', name='uq_sgc_task_approvals_task_user')
    )
    op.create_index(op.f('ix_sgc_task_approvals_comment_id'), 'sgc_task_approvals', ['comment_id'], unique=False)
    op.create_index(op.f('ix_sgc_task_approvals_task_id'), 'sgc_task_approvals', ['task_id'], unique=False)
    op.create_index(op.f('ix_sgc_task_approvals_user_id'), 'sgc_task_approvals', ['user_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_sgc_task_approvals_user_id'), table_name='sgc_task_approvals')
    op.drop_index(op.f('ix_sgc_task_approvals_task_id'), table_name='sgc_task_approvals')
    op.drop_index(op.f('ix_sgc_task_approvals_comment_id'), table_name='sgc_task_approvals')
    op.drop_table('sgc_task_approvals')
    op.drop_index(op.f('ix_sgc_task_comments_user_id'), table_name='sgc_task_comments')
    op.drop_index(op.f('ix_sgc_task_comments_task_id'), table_name='sgc_task_comments')
    op.drop_table('sgc_task_comments')
    op.drop_index('ix_sgc_task_assignees_user_id', table_name='sgc_task_assignees')
    op.drop_table('sgc_task_assignees')
    op.drop_index(op.f('ix_sgc_tasks_program_id'), table_name='sgc_tasks')
    op.drop_index(op.f('ix_sgc_tasks_incident_id'), table_name='sgc_tasks')
    op.drop_index(op.f('ix_sgc_tasks_flow_step_id'), table_name='sgc_tasks')
    op.drop_index(op.f('ix_sgc_tasks_document_id'), table_name='sgc_tasks')
    op.drop_index(op.f('ix_sgc_tasks_created_by_id'), table_name='sgc_tasks')
    op.drop_table('sgc_tasks')
    op.drop_index(op.f('ix_sgc_program_event_files_uploaded_by_id'), table_name='sgc_program_event_files')
    op.drop_index(op.f('ix_sgc_program_event_files_event_id'), table_name='sgc_program_event_files')
    op.drop_table('sgc_program_event_files')
    op.drop_index('ix_sgc_user_areas_area_id', table_name='sgc_user_areas')
    op.drop_table('sgc_user_areas')
    op.drop_index(op.f('ix_sgc_program_events_responsible_id'), table_name='sgc_program_events')
    op.drop_index(op.f('ix_sgc_program_events_process_id'), table_name='sgc_program_events')
    op.drop_index(op.f('ix_sgc_program_events_folio'), table_name='sgc_program_events')
    op.drop_index(op.f('ix_sgc_program_events_category_id'), table_name='sgc_program_events')
    op.drop_index(op.f('ix_sgc_program_events_area_id'), table_name='sgc_program_events')
    op.drop_table('sgc_program_events')
    op.drop_index(op.f('ix_sgc_indicator_trackings_indicator_id'), table_name='sgc_indicator_trackings')
    op.drop_table('sgc_indicator_trackings')
    op.drop_index(op.f('ix_sgc_incidents_responsible_id'), table_name='sgc_incidents')
    op.drop_index(op.f('ix_sgc_incidents_process_id'), table_name='sgc_incidents')
    op.drop_index(op.f('ix_sgc_incidents_folio'), table_name='sgc_incidents')
    op.drop_index(op.f('ix_sgc_incidents_category_id'), table_name='sgc_incidents')
    op.drop_index(op.f('ix_sgc_incidents_area_id'), table_name='sgc_incidents')
    op.drop_table('sgc_incidents')
    op.drop_index('ix_sgc_flow_step_assignees_user_id', table_name='sgc_flow_step_assignees')
    op.drop_table('sgc_flow_step_assignees')
    op.drop_index(op.f('ix_sgc_documents_process_id'), table_name='sgc_documents')
    op.drop_index(op.f('ix_sgc_documents_flow_id'), table_name='sgc_documents')
    op.drop_index(op.f('ix_sgc_documents_current_step_id'), table_name='sgc_documents')
    op.drop_index(op.f('ix_sgc_documents_code'), table_name='sgc_documents')
    op.drop_index(op.f('ix_sgc_documents_classification_id'), table_name='sgc_documents')
    op.drop_index(op.f('ix_sgc_documents_category_id'), table_name='sgc_documents')
    op.drop_index(op.f('ix_sgc_documents_author_id'), table_name='sgc_documents')
    op.drop_index(op.f('ix_sgc_documents_area_id'), table_name='sgc_documents')
    op.drop_table('sgc_documents')
    op.drop_index(op.f('ix_sgc_indicators_year_id'), table_name='sgc_indicators')
    op.drop_index(op.f('ix_sgc_indicators_process_id'), table_name='sgc_indicators')
    op.drop_table('sgc_indicators')
    op.drop_index(op.f('ix_sgc_approval_flow_steps_flow_id'), table_name='sgc_approval_flow_steps')
    op.drop_table('sgc_approval_flow_steps')
    op.drop_table('sgc_program_categories')
    op.drop_table('sgc_processes')
    op.drop_table('sgc_mail_config')
    op.drop_table('sgc_indicator_years')
    op.drop_table('sgc_incident_categories')
    op.drop_table('sgc_document_classifications')
    op.drop_table('sgc_document_categories')
    op.drop_index(op.f('ix_sgc_areas_is_active'), table_name='sgc_areas')
    op.drop_table('sgc_areas')
    op.drop_table('sgc_approval_flows')
