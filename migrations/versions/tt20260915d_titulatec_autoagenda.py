"""titulatec_autoagenda

Auto-agendado de la cita de cotejo por el egresado (Tarea 1: solo esquema).

- `ReviewWindow.visibility` (private|bookable|walkin): el modo del espacio,
  con CheckConstraint. `private` es el default, asi que las 5 ventanas
  existentes no cambian de comportamiento.
- Historial de intentos de `ReviewAppointment`: `is_current`, `attempt_no`,
  `booked_by`, mas la auditoria de cancelacion (`cancelled_at`,
  `cancelled_by_id`, `cancel_reason`). Indice UNICO PARCIAL
  `uq_titulatec_review_appt_current` (process_id) WHERE is_current: como
  mucho una cita vigente por proceso. `autogenerate` no produce indices
  parciales, asi que el CREATE/DROP van a mano con `op.execute`.

Nota: el `autogenerate` de esta revision tambien detecto drift preexistente
y NO relacionado con esta tarea en tablas de helpdesk/core/agendatec (indices
renombrados, constraints con otro nombre al que generaria la convencion
actual de SQLAlchemy). Se omite a proposito: no es parte de esta tarea y
tocarlo aqui seria un DROP/CREATE de constraints en produccion sin pedirlo.

Revision ID: tt20260915d
Revises: tt20260915c
Create Date: 2026-09-15 23:28:32.604060

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'tt20260915d'
down_revision = 'tt20260915c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- ReviewWindow.visibility ---
    op.add_column(
        'titulatec_review_windows',
        sa.Column('visibility', sa.String(length=20), nullable=False,
                  server_default=sa.text("'private'")),
    )
    op.create_check_constraint(
        'ck_titulatec_review_windows_visibility', 'titulatec_review_windows',
        "visibility IN ('private','bookable','walkin')",
    )

    # --- ReviewAppointment: historial de intentos + auditoria de cancelacion ---
    op.add_column(
        'titulatec_review_appointments',
        sa.Column('is_current', sa.Boolean(), nullable=False,
                  server_default=sa.text('TRUE')),
    )
    op.add_column(
        'titulatec_review_appointments',
        sa.Column('attempt_no', sa.Integer(), nullable=False,
                  server_default=sa.text('1')),
    )
    op.add_column(
        'titulatec_review_appointments',
        sa.Column('booked_by', sa.String(length=20), nullable=False,
                  server_default=sa.text("'officer'")),
    )
    op.add_column(
        'titulatec_review_appointments',
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
    )
    op.add_column(
        'titulatec_review_appointments',
        sa.Column('cancelled_by_id', sa.BigInteger(), nullable=True),
    )
    op.add_column(
        'titulatec_review_appointments',
        sa.Column('cancel_reason', sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        None, 'titulatec_review_appointments', 'core_users',
        ['cancelled_by_id'], ['id'],
    )

    # Indice UNICO PARCIAL: autogenerate no los produce, se escribe a mano.
    op.execute(
        "CREATE UNIQUE INDEX uq_titulatec_review_appt_current "
        "ON titulatec_review_appointments (process_id) WHERE is_current"
    )

    # Guard: aborta si algun proceso quedo con mas de una cita vigente. Hoy
    # (13 citas vivas) son 0 filas y el guard pasa; esto es para el dia que
    # no sea asi — el propio CREATE UNIQUE INDEX de arriba ya habria fallado
    # primero, pero este guard deja un mensaje explicito en vez de un error
    # crudo de Postgres.
    conn = op.get_bind()
    dupes = conn.execute(sa.text(
        "SELECT count(*) FROM ("
        "  SELECT process_id FROM titulatec_review_appointments"
        "  WHERE is_current GROUP BY process_id HAVING count(*) > 1"
        ") dup"
    )).scalar()
    if dupes:
        raise RuntimeError(
            f"{dupes} proceso(s) quedaron con mas de una cita vigente "
            "(is_current) tras la migracion. Revisa antes de continuar."
        )


def downgrade() -> None:
    op.execute("DROP INDEX uq_titulatec_review_appt_current")
    op.drop_constraint(
        'titulatec_review_appointments_cancelled_by_id_fkey',
        'titulatec_review_appointments', type_='foreignkey',
    )
    op.drop_column('titulatec_review_appointments', 'cancel_reason')
    op.drop_column('titulatec_review_appointments', 'cancelled_by_id')
    op.drop_column('titulatec_review_appointments', 'cancelled_at')
    op.drop_column('titulatec_review_appointments', 'booked_by')
    op.drop_column('titulatec_review_appointments', 'attempt_no')
    op.drop_column('titulatec_review_appointments', 'is_current')

    op.drop_constraint('ck_titulatec_review_windows_visibility',
                       'titulatec_review_windows', type_='check')
    op.drop_column('titulatec_review_windows', 'visibility')
