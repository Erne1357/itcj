"""core hardening: BigInt user FKs, safe cascades, indexes, partial unique, updated_at

Revision ID: o1s2c3p4e002
Revises: o1s2c3p4e001
Create Date: 2026-07-02

Todo aditivo/widening y prod-safe:
- Ensancha user_id INT→BIGINT en core_user_app_roles/perms (users id>2^31 fallaban).
- Recrea FKs de core_notifications.user_id (→CASCADE) y
  core_academic_periods.created_by_id (→SET NULL) para no bloquear el borrado de users.
- Índices en FKs calientes.
- Índice único PARCIAL "un activo por (user, position)"; quita el unique de 3 columnas
  que rompía asignar/quitar/reasignar.
- updated_at en core_departments y core_user_positions.
"""
from alembic import op

revision = "o1s2c3p4e002"
down_revision = "o1s2c3p4e001"
branch_labels = None
depends_on = None


def upgrade():
    # 1) Ensanchar user_id INT→BIGINT en tablas RBAC
    op.execute("ALTER TABLE core_user_app_roles ALTER COLUMN user_id TYPE BIGINT")
    op.execute("ALTER TABLE core_user_app_perms ALTER COLUMN user_id TYPE BIGINT")

    # 2) core_notifications.user_id → ON DELETE CASCADE (drop dinámico del FK actual)
    op.execute("""
    DO $$
    DECLARE cname text;
    BEGIN
        SELECT con.conname INTO cname
        FROM pg_constraint con
        WHERE con.conrelid = 'core_notifications'::regclass AND con.contype = 'f'
          AND con.conkey = (SELECT array_agg(a.attnum ORDER BY a.attnum)
                            FROM pg_attribute a
                            WHERE a.attrelid = 'core_notifications'::regclass AND a.attname = 'user_id');
        IF cname IS NOT NULL THEN
            EXECUTE 'ALTER TABLE core_notifications DROP CONSTRAINT ' || quote_ident(cname);
        END IF;
        ALTER TABLE core_notifications
            ADD CONSTRAINT core_notifications_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES core_users(id) ON DELETE CASCADE;
    END $$;
    """)

    # 3) core_academic_periods.created_by_id → ON DELETE SET NULL + índice
    op.execute("""
    DO $$
    DECLARE cname text;
    BEGIN
        SELECT con.conname INTO cname
        FROM pg_constraint con
        WHERE con.conrelid = 'core_academic_periods'::regclass AND con.contype = 'f'
          AND con.conkey = (SELECT array_agg(a.attnum ORDER BY a.attnum)
                            FROM pg_attribute a
                            WHERE a.attrelid = 'core_academic_periods'::regclass AND a.attname = 'created_by_id');
        IF cname IS NOT NULL THEN
            EXECUTE 'ALTER TABLE core_academic_periods DROP CONSTRAINT ' || quote_ident(cname);
        END IF;
        ALTER TABLE core_academic_periods
            ADD CONSTRAINT core_academic_periods_created_by_id_fkey
            FOREIGN KEY (created_by_id) REFERENCES core_users(id) ON DELETE SET NULL;
    END $$;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_academic_periods_created_by ON core_academic_periods(created_by_id)")

    # 4) Índices en FKs / columnas de filtro calientes
    op.execute("CREATE INDEX IF NOT EXISTS ix_positions_department_id ON core_positions(department_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_role_id ON core_users(role_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notifications_program_id ON core_notifications(program_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notifications_source_request_id ON core_notifications(source_request_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notifications_source_appointment_id ON core_notifications(source_appointment_id)")

    # 5) Índice único parcial "un activo por (user, position)"; quitar unique de 3 columnas
    op.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS uq_active_user_position_new
        ON core_user_positions (user_id, position_id) WHERE is_active
    """)
    op.execute("ALTER TABLE core_user_positions DROP CONSTRAINT IF EXISTS uq_active_user_position")

    # 6) updated_at en entidades mutables
    op.execute("ALTER TABLE core_departments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()")
    op.execute("ALTER TABLE core_user_positions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()")


def downgrade():
    op.execute("ALTER TABLE core_departments DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE core_user_positions DROP COLUMN IF EXISTS updated_at")
    op.execute("DROP INDEX IF EXISTS uq_active_user_position_new")
    op.execute("""
    ALTER TABLE core_user_positions
        ADD CONSTRAINT uq_active_user_position UNIQUE (user_id, position_id, is_active)
    """)
    op.execute("DROP INDEX IF EXISTS ix_positions_department_id")
    op.execute("DROP INDEX IF EXISTS ix_users_role_id")
    op.execute("DROP INDEX IF EXISTS ix_notifications_program_id")
    op.execute("DROP INDEX IF EXISTS ix_notifications_source_request_id")
    op.execute("DROP INDEX IF EXISTS ix_notifications_source_appointment_id")
    op.execute("DROP INDEX IF EXISTS ix_academic_periods_created_by")
    # (FKs y tipos BIGINT no se revierten: widening/cascades son seguros y no destructivos)
