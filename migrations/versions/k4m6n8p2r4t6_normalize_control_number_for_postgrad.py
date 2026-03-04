"""Normalize control_number: expand to 10 chars and migrate postgrad students

Revision ID: k4m6n8p2r4t6
Revises: j3k5m7p9r1t3
Create Date: 2026-02-26

Changes:
- Alter core_users.control_number from CHAR(8) to VARCHAR(10)
  to support postgrad/transfer students (e.g. M21111182, B211111820).
- Migrate students who currently have their control number stored in
  the 'username' field: find users without control_number who have the
  'student' role in the 'agendatec' app (via core_user_app_roles +
  core_apps + core_roles), and move username → control_number.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'k4m6n8p2r4t6'
down_revision = 'j3k5m7p9r1t3'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Alter the column type from CHAR(8) to VARCHAR(10)
    op.alter_column(
        'core_users',
        'control_number',
        existing_type=sa.CHAR(8),
        type_=sa.String(10),
        existing_nullable=True,
    )

    # 2. Data migration: move username → control_number for postgrad/transfer students
    #    These are users who:
    #    - Have NO control_number (IS NULL)
    #    - Have the "student" role in the "agendatec" app (via core_user_app_roles)
    #    - Their username looks like a postgrad control number (letter + digits)
    conn = op.get_bind()

    # Find the agendatec app id
    app_row = conn.execute(
        sa.text("SELECT id FROM core_apps WHERE key = 'agendatec'")
    ).fetchone()

    if not app_row:
        # No agendatec app found, skip data migration
        return

    agendatec_app_id = app_row[0]

    # Find the student role id
    role_row = conn.execute(
        sa.text("SELECT id FROM core_roles WHERE name = 'student'")
    ).fetchone()

    if not role_row:
        # No student role found, skip data migration
        return

    student_role_id = role_row[0]

    # Find users who have student role in agendatec, have no control_number,
    # and have a username that looks like a postgrad control number
    # Pattern: starts with a letter followed by 7-9 digits (e.g. M21111182)
    result = conn.execute(
        sa.text("""
            SELECT DISTINCT u.id, u.username
            FROM core_users u
            INNER JOIN core_user_app_roles uar
                ON uar.user_id = u.id
                AND uar.app_id = :app_id
                AND uar.role_id = :role_id
            WHERE u.control_number IS NULL
              AND u.username IS NOT NULL
              AND u.username ~ '^[A-Za-z][0-9]{7,9}$'
        """),
        {"app_id": agendatec_app_id, "role_id": student_role_id}
    )

    rows = result.fetchall()

    if rows:
        for row in rows:
            user_id = row[0]
            username_val = row[1].upper()  # Normalize to uppercase

            # Move username to control_number, clear username
            conn.execute(
                sa.text("""
                    UPDATE core_users
                    SET control_number = :cn,
                        username = NULL,
                        updated_at = NOW()
                    WHERE id = :uid
                """),
                {"cn": username_val, "uid": user_id}
            )

        print(f"  [migrate] Moved {len(rows)} postgrad/transfer student(s) from username → control_number")
    else:
        print("  [migrate] No postgrad/transfer students found to migrate")


def downgrade():
    # 1. Reverse data migration: move control_number back to username
    #    for records with alphanumeric control numbers (letter + digits)
    conn = op.get_bind()

    result = conn.execute(
        sa.text("""
            SELECT id, control_number
            FROM core_users
            WHERE control_number IS NOT NULL
              AND control_number ~ '^[A-Za-z][0-9]{7,9}$'
        """)
    )

    rows = result.fetchall()

    if rows:
        for row in rows:
            user_id = row[0]
            cn_val = row[1]

            conn.execute(
                sa.text("""
                    UPDATE core_users
                    SET username = :uname,
                        control_number = NULL,
                        updated_at = NOW()
                    WHERE id = :uid
                """),
                {"uname": cn_val, "uid": user_id}
            )

        print(f"  [downgrade] Moved {len(rows)} postgrad/transfer student(s) back from control_number → username")

    # 2. Revert column type from VARCHAR(10) back to CHAR(8)
    op.alter_column(
        'core_users',
        'control_number',
        existing_type=sa.String(10),
        type_=sa.CHAR(8),
        existing_nullable=True,
    )
