"""refactor names to add sufix core_

Revision ID: 757969626448
Revises: 5f96ae18f522
Create Date: 2025-10-29 12:12:23.381344

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '757969626448'
down_revision = '5f96ae18f522'
branch_labels = None
depends_on = None


def upgrade():
    # Renombrar tablas
    op.rename_table('users', 'core_users')
    op.rename_table('roles', 'core_roles')
    op.rename_table('apps', 'core_apps')
    op.rename_table('permissions', 'core_permissions')
    op.rename_table('departments', 'core_departments')
    op.rename_table('positions', 'core_positions')
    op.rename_table('user_positions', 'core_user_positions')
    op.rename_table('position_app_roles', 'core_position_app_roles')
    op.rename_table('position_app_perms', 'core_position_app_perms')
    op.rename_table('coordinators', 'core_coordinators')
    op.rename_table('programs', 'core_programs')
    op.rename_table('program_coordinator', 'core_program_coordinator')
    op.rename_table('role_permissions', 'core_role_permissions')
    op.rename_table('user_app_roles', 'core_user_app_roles')
    op.rename_table('user_app_perms', 'core_user_app_perms')
    op.rename_table('program_positions', 'core_program_positions')
    
    # Función helper para verificar y renombrar secuencias
    def rename_sequence_if_exists(old_name, new_name):
        connection = op.get_bind()
        result = connection.execute(
            sa.text("SELECT 1 FROM pg_class WHERE relname = :seq_name AND relkind = 'S'"),
            {"seq_name": old_name}
        )
        if result.fetchone():
            op.execute(f'ALTER SEQUENCE {old_name} RENAME TO {new_name}')
        else:
            print(f"Warning: Sequence {old_name} does not exist, skipping rename")
    
    # Renombrar secuencias
    rename_sequence_if_exists('apps_id_seq', 'core_apps_id_seq')
    rename_sequence_if_exists('coordinators_id_seq', 'core_coordinators_id_seq')
    rename_sequence_if_exists('departments_id_seq', 'core_departments_id_seq')
    rename_sequence_if_exists('permissions_id_seq', 'core_permissions_id_seq')
    rename_sequence_if_exists('positions_id_seq', 'core_positions_id_seq')
    rename_sequence_if_exists('programs_id_seq', 'core_programs_id_seq')
    rename_sequence_if_exists('roles_id_seq', 'core_roles_id_seq')
    rename_sequence_if_exists('users_id_seq', 'core_users_id_seq')
    rename_sequence_if_exists('user_positions_id_seq', 'core_user_positions_id_seq')
    rename_sequence_if_exists('program_positions_id_seq', 'core_program_positions_id_seq')
    rename_sequence_if_exists('agendatec_notifications_id_seq', 'core_notifications_id_seq')
    
    # Función helper para verificar y renombrar índices
    def rename_index_if_exists(old_name, new_name):
        connection = op.get_bind()
        result = connection.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :index_name"),
            {"index_name": old_name}
        )
        if result.fetchone():
            op.execute(f'ALTER INDEX {old_name} RENAME TO {new_name}')
        else:
            print(f"Warning: Index {old_name} does not exist, skipping rename")
    
    # Función helper para crear índices si no existen
    def create_index_if_not_exists(index_name, table_name, columns):
        connection = op.get_bind()
        result = connection.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :index_name"),
            {"index_name": index_name}
        )
        if not result.fetchone():
            op.create_index(index_name, table_name, columns)
    
    # Renombrar índices existentes o crear nuevos
    rename_index_if_exists('ix_users_username', 'ix_core_users_username')
    rename_index_if_exists('ix_users_control_number', 'ix_core_users_control_number')
    rename_index_if_exists('ix_permissions_app_id', 'ix_core_permissions_app_id')
    rename_index_if_exists('ix_user_positions_active', 'ix_core_user_positions_active')
    rename_index_if_exists('ix_position_app_roles_position_app', 'ix_core_position_app_roles_position_app')
    rename_index_if_exists('ix_position_app_perms_position_app', 'ix_core_position_app_perms_position_app')
    rename_index_if_exists('ix_user_app_roles_user_app', 'ix_core_user_app_roles_user_app')
    rename_index_if_exists('ix_user_app_perms_user_app', 'ix_core_user_app_perms_user_app')
    
    # Crear índices importantes si no existen
    create_index_if_not_exists('ix_core_users_username', 'core_users', ['username'])
    create_index_if_not_exists('ix_core_users_control_number', 'core_users', ['control_number'])
    create_index_if_not_exists('ix_core_permissions_app_id', 'core_permissions', ['app_id'])
    create_index_if_not_exists('ix_core_user_positions_active', 'core_user_positions', ['active'])
    
    
    # Manejar notificaciones
    op.rename_table('agendatec_notifications', 'core_notifications')
    op.add_column('core_notifications', sa.Column('app_name', sa.String(50), nullable=True))
    op.execute("UPDATE core_notifications SET app_name = 'agendatec' WHERE app_name IS NULL")
    op.alter_column('core_notifications', 'app_name', nullable=False)
    
    # Crear índices para notificaciones
    op.create_index('ix_core_notifications_user_app', 'core_notifications', ['user_id', 'app_name'])
    op.create_index('ix_core_notifications_app_type', 'core_notifications', ['app_name', 'type'])
    op.create_index('ix_core_notifications_user_unread', 'core_notifications', ['user_id', 'is_read'])
    
    op.add_column('core_notifications', sa.Column('ticket_id', sa.Integer, nullable=True))
    op.create_foreign_key('fk_core_notifications_ticket', 'core_notifications', 'helpdesk_ticket', ['ticket_id'], ['id'], ondelete='CASCADE')


def downgrade():
    # Función helper para verificar y renombrar índices en downgrade
    def rename_index_if_exists(old_name, new_name):
        connection = op.get_bind()
        result = connection.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :index_name"),
            {"index_name": old_name}
        )
        if result.fetchone():
            op.execute(f'ALTER INDEX {old_name} RENAME TO {new_name}')
    
    op.drop_constraint('fk_core_notifications_ticket', 'core_notifications', type_='foreignkey')
    op.drop_column('core_notifications', 'ticket_id')
    
    op.drop_index('ix_core_notifications_user_unread', 'core_notifications')
    op.drop_index('ix_core_notifications_app_type', 'core_notifications')
    op.drop_index('ix_core_notifications_user_app', 'core_notifications')
    op.drop_column('core_notifications', 'app_name')
    op.rename_table('core_notifications', 'agendatec_notifications')
    
    # Renombrar índices de vuelta
    rename_index_if_exists('ix_core_user_app_perms_user_app', 'ix_user_app_perms_user_app')
    rename_index_if_exists('ix_core_user_app_roles_user_app', 'ix_user_app_roles_user_app')
    rename_index_if_exists('ix_core_position_app_perms_position_app', 'ix_position_app_perms_position_app')
    rename_index_if_exists('ix_core_position_app_roles_position_app', 'ix_position_app_roles_position_app')
    rename_index_if_exists('ix_core_user_positions_active', 'ix_user_positions_active')
    rename_index_if_exists('ix_core_permissions_app_id', 'ix_permissions_app_id')
    rename_index_if_exists('ix_core_users_control_number', 'ix_users_control_number')
    rename_index_if_exists('ix_core_users_username', 'ix_users_username')
    
    # Función helper para verificar y renombrar secuencias en downgrade
    def rename_sequence_if_exists(old_name, new_name):
        connection = op.get_bind()
        result = connection.execute(
            sa.text("SELECT 1 FROM pg_class WHERE relname = :seq_name AND relkind = 'S'"),
            {"seq_name": old_name}
        )
        if result.fetchone():
            op.execute(f'ALTER SEQUENCE {old_name} RENAME TO {new_name}')
    
    # Renombrar secuencias de vuelta
    rename_sequence_if_exists('core_notifications_id_seq', 'agendatec_notifications_id_seq')
    rename_sequence_if_exists('core_program_positions_id_seq', 'program_positions_id_seq')
    rename_sequence_if_exists('core_user_positions_id_seq', 'user_positions_id_seq')
    rename_sequence_if_exists('core_users_id_seq', 'users_id_seq')
    rename_sequence_if_exists('core_roles_id_seq', 'roles_id_seq')
    rename_sequence_if_exists('core_programs_id_seq', 'programs_id_seq')
    rename_sequence_if_exists('core_positions_id_seq', 'positions_id_seq')
    rename_sequence_if_exists('core_permissions_id_seq', 'permissions_id_seq')
    rename_sequence_if_exists('core_departments_id_seq', 'departments_id_seq')
    rename_sequence_if_exists('core_coordinators_id_seq', 'coordinators_id_seq')
    rename_sequence_if_exists('core_apps_id_seq', 'apps_id_seq')
    
    # Renombrar tablas de vuelta
    op.rename_table('core_user_app_perms', 'user_app_perms')
    op.rename_table('core_user_app_roles', 'user_app_roles')
    op.rename_table('core_role_permissions', 'role_permissions')
    op.rename_table('core_program_coordinator', 'program_coordinator')
    op.rename_table('core_program_positions', 'program_positions')
    op.rename_table('core_programs', 'programs')
    op.rename_table('core_coordinators', 'coordinators')
    op.rename_table('core_position_app_perms', 'position_app_perms')
    op.rename_table('core_position_app_roles', 'position_app_roles')
    op.rename_table('core_user_positions', 'user_positions')
    op.rename_table('core_positions', 'positions')
    op.rename_table('core_departments', 'departments')
    op.rename_table('core_permissions', 'permissions')
    op.rename_table('core_apps', 'apps')
    op.rename_table('core_roles', 'roles')
    op.rename_table('core_users', 'users')
    
