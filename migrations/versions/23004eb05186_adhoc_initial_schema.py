"""adhoc initial schema

Las 22 tablas de la app Adhoc (Calidad): 14 de entidad mutable, 5 de
catálogo/singleton y 3 de asociación. Ver `docs/adhoc/PLAN_MIGRACION_ADHOC.md`
§2 para la especificación completa.

NOTA SOBRE EL AUTOGENERATE: la ejecución de `alembic revision --autogenerate`
detectó ~110 líneas de drift ajeno a este cambio (un `DROP TABLE
titulatec_cotejo_requirements` y renombrados de índices de agendatec/core/
helpdesk que existen en la BD real pero no en los modelos actuales, y
viceversa — igual que documentó `f6feb1cdc56a_agendatec_slot_program_scope.py`
para su propio autogenerate). Ese drift se eliminó a mano: esta migración
contiene EXCLUSIVAMENTE las 22 tablas nuevas de `adhoc`.

Revision ID: 23004eb05186
Revises: f6feb1cdc56a
Create Date: 2026-08-25 10:33:24.356470

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '23004eb05186'
down_revision = 'f6feb1cdc56a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('adhoc_approval_flows',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('adhoc_areas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('color', sa.String(length=7), server_default=sa.text("'#4834d4'"), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_adhoc_areas_is_active'), 'adhoc_areas', ['is_active'], unique=False)
    op.create_table('adhoc_document_categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('adhoc_document_classifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('adhoc_incident_categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('adhoc_indicator_years',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('year')
    )
    op.create_table('adhoc_mail_config',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('id = 1', name='ck_adhoc_mail_config_singleton'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('adhoc_processes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('color', sa.String(length=7), server_default=sa.text("'#b2bec3'"), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('adhoc_program_categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('adhoc_approval_flow_steps',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('flow_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('days_limit', sa.Integer(), server_default=sa.text('3'), nullable=False),
    sa.Column('step_order', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['flow_id'], ['adhoc_approval_flows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('flow_id', 'step_order', name='uq_adhoc_approval_flow_steps_flow_order')
    )
    op.create_index(op.f('ix_adhoc_approval_flow_steps_flow_id'), 'adhoc_approval_flow_steps', ['flow_id'], unique=False)
    op.create_table('adhoc_indicators',
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
    sa.CheckConstraint("frequency IN ('Semanal','Mensual','Anual')", name='ck_adhoc_indicators_frequency'),
    sa.ForeignKeyConstraint(['process_id'], ['adhoc_processes.id'], ),
    sa.ForeignKeyConstraint(['year_id'], ['adhoc_indicator_years.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_adhoc_indicators_process_id'), 'adhoc_indicators', ['process_id'], unique=False)
    op.create_index(op.f('ix_adhoc_indicators_year_id'), 'adhoc_indicators', ['year_id'], unique=False)
    op.create_table('adhoc_documents',
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
    sa.CheckConstraint("status IN ('Borrador','En Revisión','Aprobado','Rechazado')", name='ck_adhoc_documents_status'),
    sa.ForeignKeyConstraint(['area_id'], ['adhoc_areas.id'], ),
    sa.ForeignKeyConstraint(['author_id'], ['core_users.id'], ),
    sa.ForeignKeyConstraint(['category_id'], ['adhoc_document_categories.id'], ),
    sa.ForeignKeyConstraint(['classification_id'], ['adhoc_document_classifications.id'], ),
    sa.ForeignKeyConstraint(['current_step_id'], ['adhoc_approval_flow_steps.id'], ),
    sa.ForeignKeyConstraint(['flow_id'], ['adhoc_approval_flows.id'], ),
    sa.ForeignKeyConstraint(['process_id'], ['adhoc_processes.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_adhoc_documents_area_id'), 'adhoc_documents', ['area_id'], unique=False)
    op.create_index(op.f('ix_adhoc_documents_author_id'), 'adhoc_documents', ['author_id'], unique=False)
    op.create_index(op.f('ix_adhoc_documents_category_id'), 'adhoc_documents', ['category_id'], unique=False)
    op.create_index(op.f('ix_adhoc_documents_classification_id'), 'adhoc_documents', ['classification_id'], unique=False)
    op.create_index(op.f('ix_adhoc_documents_code'), 'adhoc_documents', ['code'], unique=False)
    op.create_index(op.f('ix_adhoc_documents_current_step_id'), 'adhoc_documents', ['current_step_id'], unique=False)
    op.create_index(op.f('ix_adhoc_documents_flow_id'), 'adhoc_documents', ['flow_id'], unique=False)
    op.create_index(op.f('ix_adhoc_documents_process_id'), 'adhoc_documents', ['process_id'], unique=False)
    op.create_table('adhoc_flow_step_assignees',
    sa.Column('step_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('notify_on_overdue', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.ForeignKeyConstraint(['step_id'], ['adhoc_approval_flow_steps.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['core_users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('step_id', 'user_id')
    )
    op.create_index('ix_adhoc_flow_step_assignees_user_id', 'adhoc_flow_step_assignees', ['user_id'], unique=False)
    op.create_table('adhoc_incidents',
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
    sa.CheckConstraint("priority IN ('Baja','Media','Alta','Urgente')", name='ck_adhoc_incidents_priority'),
    sa.CheckConstraint("status IN ('No Iniciada','Iniciada','Cerrada')", name='ck_adhoc_incidents_status'),
    sa.ForeignKeyConstraint(['area_id'], ['adhoc_areas.id'], ),
    sa.ForeignKeyConstraint(['category_id'], ['adhoc_incident_categories.id'], ),
    sa.ForeignKeyConstraint(['process_id'], ['adhoc_processes.id'], ),
    sa.ForeignKeyConstraint(['responsible_id'], ['core_users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_adhoc_incidents_area_id'), 'adhoc_incidents', ['area_id'], unique=False)
    op.create_index(op.f('ix_adhoc_incidents_category_id'), 'adhoc_incidents', ['category_id'], unique=False)
    op.create_index(op.f('ix_adhoc_incidents_folio'), 'adhoc_incidents', ['folio'], unique=False)
    op.create_index(op.f('ix_adhoc_incidents_process_id'), 'adhoc_incidents', ['process_id'], unique=False)
    op.create_index(op.f('ix_adhoc_incidents_responsible_id'), 'adhoc_incidents', ['responsible_id'], unique=False)
    op.create_table('adhoc_indicator_trackings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('indicator_id', sa.Integer(), nullable=False),
    sa.Column('period_index', sa.Integer(), nullable=False),
    sa.Column('real_value', sa.String(length=100), nullable=True),
    sa.Column('color', sa.String(length=50), server_default=sa.text("'blanco'"), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("color IN ('blanco','rojo','amarillo','verde')", name='ck_adhoc_indicator_trackings_color'),
    sa.ForeignKeyConstraint(['indicator_id'], ['adhoc_indicators.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('indicator_id', 'period_index', name='uq_adhoc_indicator_trackings_indicator_period')
    )
    op.create_index(op.f('ix_adhoc_indicator_trackings_indicator_id'), 'adhoc_indicator_trackings', ['indicator_id'], unique=False)
    op.create_table('adhoc_program_events',
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
    sa.CheckConstraint("priority IN ('Baja','Media','Alta','Urgente')", name='ck_adhoc_program_events_priority'),
    sa.CheckConstraint("status IN ('Planeado','En Proceso','Completado')", name='ck_adhoc_program_events_status'),
    sa.ForeignKeyConstraint(['area_id'], ['adhoc_areas.id'], ),
    sa.ForeignKeyConstraint(['category_id'], ['adhoc_program_categories.id'], ),
    sa.ForeignKeyConstraint(['process_id'], ['adhoc_processes.id'], ),
    sa.ForeignKeyConstraint(['responsible_id'], ['core_users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_adhoc_program_events_area_id'), 'adhoc_program_events', ['area_id'], unique=False)
    op.create_index(op.f('ix_adhoc_program_events_category_id'), 'adhoc_program_events', ['category_id'], unique=False)
    op.create_index(op.f('ix_adhoc_program_events_folio'), 'adhoc_program_events', ['folio'], unique=False)
    op.create_index(op.f('ix_adhoc_program_events_process_id'), 'adhoc_program_events', ['process_id'], unique=False)
    op.create_index(op.f('ix_adhoc_program_events_responsible_id'), 'adhoc_program_events', ['responsible_id'], unique=False)
    op.create_table('adhoc_user_areas',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('area_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['area_id'], ['adhoc_areas.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['core_users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'area_id')
    )
    op.create_index('ix_adhoc_user_areas_area_id', 'adhoc_user_areas', ['area_id'], unique=False)
    op.create_table('adhoc_program_event_files',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=False),
    sa.Column('file_path', sa.String(length=255), nullable=False),
    sa.Column('original_name', sa.String(length=255), nullable=False),
    sa.Column('mime_type', sa.String(length=100), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=True),
    sa.Column('uploaded_by_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['adhoc_program_events.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by_id'], ['core_users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_adhoc_program_event_files_event_id'), 'adhoc_program_event_files', ['event_id'], unique=False)
    op.create_index(op.f('ix_adhoc_program_event_files_uploaded_by_id'), 'adhoc_program_event_files', ['uploaded_by_id'], unique=False)
    op.create_table('adhoc_tasks',
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
    sa.CheckConstraint("priority IN ('Baja','Media','Alta','Urgente')", name='ck_adhoc_tasks_priority'),
    sa.CheckConstraint("status IN ('Pendiente','En Proceso','En Revisión','En Espera','Completada','Rechazada')", name='ck_adhoc_tasks_status'),
    sa.CheckConstraint('(incident_id IS NOT NULL)::int + (program_id IS NOT NULL)::int + (document_id IS NOT NULL)::int = 1', name='ck_adhoc_tasks_single_parent'),
    sa.ForeignKeyConstraint(['created_by_id'], ['core_users.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['adhoc_documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['flow_step_id'], ['adhoc_approval_flow_steps.id'], ),
    sa.ForeignKeyConstraint(['incident_id'], ['adhoc_incidents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['program_id'], ['adhoc_program_events.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_adhoc_tasks_created_by_id'), 'adhoc_tasks', ['created_by_id'], unique=False)
    op.create_index(op.f('ix_adhoc_tasks_document_id'), 'adhoc_tasks', ['document_id'], unique=False)
    op.create_index(op.f('ix_adhoc_tasks_flow_step_id'), 'adhoc_tasks', ['flow_step_id'], unique=False)
    op.create_index(op.f('ix_adhoc_tasks_incident_id'), 'adhoc_tasks', ['incident_id'], unique=False)
    op.create_index(op.f('ix_adhoc_tasks_program_id'), 'adhoc_tasks', ['program_id'], unique=False)
    op.create_table('adhoc_task_assignees',
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('notified_overdue', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['adhoc_tasks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['core_users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('task_id', 'user_id')
    )
    op.create_index('ix_adhoc_task_assignees_user_id', 'adhoc_task_assignees', ['user_id'], unique=False)
    op.create_table('adhoc_task_comments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('comment', sa.Text(), nullable=False),
    sa.Column('file_path', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['adhoc_tasks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['core_users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_adhoc_task_comments_task_id'), 'adhoc_task_comments', ['task_id'], unique=False)
    op.create_index(op.f('ix_adhoc_task_comments_user_id'), 'adhoc_task_comments', ['user_id'], unique=False)
    op.create_table('adhoc_task_approvals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('decision', sa.String(length=20), nullable=False),
    sa.Column('comment_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("decision IN ('aprobado','rechazado')", name='ck_adhoc_task_approvals_decision'),
    sa.ForeignKeyConstraint(['comment_id'], ['adhoc_task_comments.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['adhoc_tasks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['core_users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('task_id', 'user_id', name='uq_adhoc_task_approvals_task_user')
    )
    op.create_index(op.f('ix_adhoc_task_approvals_comment_id'), 'adhoc_task_approvals', ['comment_id'], unique=False)
    op.create_index(op.f('ix_adhoc_task_approvals_task_id'), 'adhoc_task_approvals', ['task_id'], unique=False)
    op.create_index(op.f('ix_adhoc_task_approvals_user_id'), 'adhoc_task_approvals', ['user_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_adhoc_task_approvals_user_id'), table_name='adhoc_task_approvals')
    op.drop_index(op.f('ix_adhoc_task_approvals_task_id'), table_name='adhoc_task_approvals')
    op.drop_index(op.f('ix_adhoc_task_approvals_comment_id'), table_name='adhoc_task_approvals')
    op.drop_table('adhoc_task_approvals')
    op.drop_index(op.f('ix_adhoc_task_comments_user_id'), table_name='adhoc_task_comments')
    op.drop_index(op.f('ix_adhoc_task_comments_task_id'), table_name='adhoc_task_comments')
    op.drop_table('adhoc_task_comments')
    op.drop_index('ix_adhoc_task_assignees_user_id', table_name='adhoc_task_assignees')
    op.drop_table('adhoc_task_assignees')
    op.drop_index(op.f('ix_adhoc_tasks_program_id'), table_name='adhoc_tasks')
    op.drop_index(op.f('ix_adhoc_tasks_incident_id'), table_name='adhoc_tasks')
    op.drop_index(op.f('ix_adhoc_tasks_flow_step_id'), table_name='adhoc_tasks')
    op.drop_index(op.f('ix_adhoc_tasks_document_id'), table_name='adhoc_tasks')
    op.drop_index(op.f('ix_adhoc_tasks_created_by_id'), table_name='adhoc_tasks')
    op.drop_table('adhoc_tasks')
    op.drop_index(op.f('ix_adhoc_program_event_files_uploaded_by_id'), table_name='adhoc_program_event_files')
    op.drop_index(op.f('ix_adhoc_program_event_files_event_id'), table_name='adhoc_program_event_files')
    op.drop_table('adhoc_program_event_files')
    op.drop_index('ix_adhoc_user_areas_area_id', table_name='adhoc_user_areas')
    op.drop_table('adhoc_user_areas')
    op.drop_index(op.f('ix_adhoc_program_events_responsible_id'), table_name='adhoc_program_events')
    op.drop_index(op.f('ix_adhoc_program_events_process_id'), table_name='adhoc_program_events')
    op.drop_index(op.f('ix_adhoc_program_events_folio'), table_name='adhoc_program_events')
    op.drop_index(op.f('ix_adhoc_program_events_category_id'), table_name='adhoc_program_events')
    op.drop_index(op.f('ix_adhoc_program_events_area_id'), table_name='adhoc_program_events')
    op.drop_table('adhoc_program_events')
    op.drop_index(op.f('ix_adhoc_indicator_trackings_indicator_id'), table_name='adhoc_indicator_trackings')
    op.drop_table('adhoc_indicator_trackings')
    op.drop_index(op.f('ix_adhoc_incidents_responsible_id'), table_name='adhoc_incidents')
    op.drop_index(op.f('ix_adhoc_incidents_process_id'), table_name='adhoc_incidents')
    op.drop_index(op.f('ix_adhoc_incidents_folio'), table_name='adhoc_incidents')
    op.drop_index(op.f('ix_adhoc_incidents_category_id'), table_name='adhoc_incidents')
    op.drop_index(op.f('ix_adhoc_incidents_area_id'), table_name='adhoc_incidents')
    op.drop_table('adhoc_incidents')
    op.drop_index('ix_adhoc_flow_step_assignees_user_id', table_name='adhoc_flow_step_assignees')
    op.drop_table('adhoc_flow_step_assignees')
    op.drop_index(op.f('ix_adhoc_documents_process_id'), table_name='adhoc_documents')
    op.drop_index(op.f('ix_adhoc_documents_flow_id'), table_name='adhoc_documents')
    op.drop_index(op.f('ix_adhoc_documents_current_step_id'), table_name='adhoc_documents')
    op.drop_index(op.f('ix_adhoc_documents_code'), table_name='adhoc_documents')
    op.drop_index(op.f('ix_adhoc_documents_classification_id'), table_name='adhoc_documents')
    op.drop_index(op.f('ix_adhoc_documents_category_id'), table_name='adhoc_documents')
    op.drop_index(op.f('ix_adhoc_documents_author_id'), table_name='adhoc_documents')
    op.drop_index(op.f('ix_adhoc_documents_area_id'), table_name='adhoc_documents')
    op.drop_table('adhoc_documents')
    op.drop_index(op.f('ix_adhoc_indicators_year_id'), table_name='adhoc_indicators')
    op.drop_index(op.f('ix_adhoc_indicators_process_id'), table_name='adhoc_indicators')
    op.drop_table('adhoc_indicators')
    op.drop_index(op.f('ix_adhoc_approval_flow_steps_flow_id'), table_name='adhoc_approval_flow_steps')
    op.drop_table('adhoc_approval_flow_steps')
    op.drop_table('adhoc_program_categories')
    op.drop_table('adhoc_processes')
    op.drop_table('adhoc_mail_config')
    op.drop_table('adhoc_indicator_years')
    op.drop_table('adhoc_incident_categories')
    op.drop_table('adhoc_document_classifications')
    op.drop_table('adhoc_document_categories')
    op.drop_index(op.f('ix_adhoc_areas_is_active'), table_name='adhoc_areas')
    op.drop_table('adhoc_areas')
    op.drop_table('adhoc_approval_flows')
