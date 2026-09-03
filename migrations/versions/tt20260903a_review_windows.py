"""titulatec: ventanas de cotejo, defaults de franja y solicitud de cambio propia

Revision ID: tt20260903a
Revises: s1e2s3s4v001
Create Date: 2026-09-03

Que hace, y por que en este orden
---------------------------------
1. `titulatec_review_windows`: la ventana de atencion que cada encargado abre
   dentro de un dia de cotejo. El dueno es el USUARIO y no el puesto porque
   `core_positions.aux_school_services` tiene `allows_multiple = TRUE` con nueve
   ocupantes: con dueno = puesto esas nueve personas compartirian una ventana.

2. Defaults de franja en `titulatec_cohorts` (NOT NULL CON server_default, o la
   migracion falla sobre la convocatoria que ya existe) y overrides NULLABLE por
   dia en `titulatec_cohort_review_days` (NULL = hereda, asi que los seis dias
   que ya existen quedan validos sin backfill).

3. `is_closed` en el dia. Sustituye al DELETE de `ReviewDayService.toggle()`:
   con ventanas y citas colgando, borrar un dia es destructivo.

4. La solicitud de cambio del alumno sale del prefijo magico `"[CAMBIO] "`
   dentro de `note` y pasa a columna propia. `change_requested_at` queda en NULL
   a proposito: `updated_at` es la fecha de alta de la cita, no la de la
   solicitud, y escribir un dato falso es peor que dejarlo vacio.

5. Ventanas de compatibilidad para las citas que YA existen. Dejarlas con
   `window_id IS NULL` no es neutro: sus horas volverian a ofrecerse como libres
   y se podria sentar a otro alumno encima. Se crea una ventana por dia con
   citas, con los defaults de su convocatoria, y se casan por horario. Lo que no
   case se queda en NULL y la UI lo muestra en una banda «Otras citas de este
   dia»: visible, no escondido.
"""
from alembic import op
import sqlalchemy as sa


revision = "tt20260903a"
down_revision = "s1e2s3s4v001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 2a. Defaults de franja de la convocatoria --------------------------
    op.add_column("titulatec_cohorts", sa.Column(
        "default_start_time", sa.Time(), nullable=False, server_default=sa.text("'09:00'")))
    op.add_column("titulatec_cohorts", sa.Column(
        "default_end_time", sa.Time(), nullable=False, server_default=sa.text("'14:00'")))
    op.add_column("titulatec_cohorts", sa.Column(
        "default_slot_minutes", sa.Integer(), nullable=False, server_default=sa.text("30")))
    op.add_column("titulatec_cohorts", sa.Column(
        "default_capacity", sa.Integer(), nullable=False, server_default=sa.text("1")))
    op.add_column("titulatec_cohorts", sa.Column(
        "default_location", sa.String(length=120), nullable=True))
    op.create_check_constraint(
        "ck_titulatec_cohorts_default_time_order", "titulatec_cohorts",
        "default_end_time > default_start_time")

    # --- 2b. Override por dia (NULL = hereda) + 3. is_closed ----------------
    for nombre, tipo in (("start_time", sa.Time()), ("end_time", sa.Time()),
                         ("slot_minutes", sa.Integer()), ("capacity", sa.Integer()),
                         ("location", sa.String(length=120))):
        op.add_column("titulatec_cohort_review_days", sa.Column(nombre, tipo, nullable=True))
    op.add_column("titulatec_cohort_review_days", sa.Column(
        "is_closed", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")))
    op.create_index("ix_titulatec_cohort_review_days_is_closed",
                    "titulatec_cohort_review_days", ["is_closed"])
    # Tolerantes a NULL: un CHECK solo falla con FALSE, y `NULL > NULL` es NULL.
    op.create_check_constraint(
        "ck_titulatec_cohort_review_days_time_order", "titulatec_cohort_review_days",
        "end_time IS NULL OR start_time IS NULL OR end_time > start_time")
    op.create_check_constraint(
        "ck_titulatec_cohort_review_days_slot_minutes", "titulatec_cohort_review_days",
        "slot_minutes IS NULL OR slot_minutes BETWEEN 5 AND 480")
    op.create_check_constraint(
        "ck_titulatec_cohort_review_days_capacity", "titulatec_cohort_review_days",
        "capacity IS NULL OR capacity >= 1")

    # --- 1. La tabla nueva --------------------------------------------------
    op.create_table(
        "titulatec_review_windows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_day_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_position_id", sa.Integer(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("slot_minutes", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("location", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default=sa.text("'open'")),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_by_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        # RESTRICT y no CASCADE: borrar un dia no puede borrar la cita de un alumno.
        sa.ForeignKeyConstraint(["review_day_id"], ["titulatec_cohort_review_days.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["core_users.id"]),
        sa.ForeignKeyConstraint(["owner_position_id"], ["core_positions.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["core_users.id"]),
        sa.UniqueConstraint("review_day_id", "owner_user_id", "start_time",
                            name="uq_titulatec_review_windows_day_user_start"),
        sa.CheckConstraint("end_time > start_time",
                           name="ck_titulatec_review_windows_time_order"),
        sa.CheckConstraint("slot_minutes BETWEEN 5 AND 480",
                           name="ck_titulatec_review_windows_slot_minutes"),
        sa.CheckConstraint("capacity >= 1",
                           name="ck_titulatec_review_windows_capacity"),
    )
    op.create_index("ix_titulatec_review_windows_review_day_id",
                    "titulatec_review_windows", ["review_day_id"])
    op.create_index("ix_titulatec_review_windows_owner_user_id",
                    "titulatec_review_windows", ["owner_user_id"])
    op.create_index("ix_titulatec_review_windows_day_user",
                    "titulatec_review_windows", ["review_day_id", "owner_user_id"])

    # --- 4. La cita conoce su ventana y su solicitud de cambio --------------
    op.add_column("titulatec_review_appointments",
                  sa.Column("window_id", sa.Integer(), nullable=True))
    op.add_column("titulatec_review_appointments",
                  sa.Column("change_request", sa.Text(), nullable=True))
    op.add_column("titulatec_review_appointments",
                  sa.Column("change_requested_at", sa.DateTime(), nullable=True))
    op.create_index("ix_titulatec_review_appointments_window_id",
                    "titulatec_review_appointments", ["window_id"])
    op.create_foreign_key("fk_titulatec_review_appointments_window",
                          "titulatec_review_appointments", "titulatec_review_windows",
                          ["window_id"], ["id"], ondelete="RESTRICT")

    # Backfill del prefijo magico. `substring(note from 10)` corta "[CAMBIO] "
    # (nueve caracteres). `change_requested_at` se queda NULL: el dato no existe.
    op.execute("""
        UPDATE titulatec_review_appointments
           SET change_request = substring(note from 10),
               note = NULL
         WHERE note LIKE '[CAMBIO] %'
    """)

    # --- 5. Ventanas de compatibilidad + casado de las citas vivas ----------
    op.execute("""
        INSERT INTO titulatec_review_windows
            (review_day_id, owner_user_id, start_time, end_time, slot_minutes,
             capacity, location, status, created_by_id)
        SELECT d.id,
               COALESCE(d.created_by_id, c.created_by_id,
                        (SELECT id FROM core_users ORDER BY id LIMIT 1)),
               c.default_start_time, c.default_end_time, c.default_slot_minutes,
               c.default_capacity, c.default_location, 'open',
               COALESCE(d.created_by_id, c.created_by_id,
                        (SELECT id FROM core_users ORDER BY id LIMIT 1))
          FROM titulatec_cohort_review_days d
          JOIN titulatec_cohorts c ON c.id = d.cohort_id
         WHERE EXISTS (SELECT 1
                         FROM titulatec_review_appointments a
                        WHERE a.scheduled_at::date = d.date)
    """)
    op.execute("""
        UPDATE titulatec_review_appointments a
           SET window_id = w.id
          FROM titulatec_review_windows w
          JOIN titulatec_cohort_review_days d ON d.id = w.review_day_id
         WHERE a.window_id IS NULL
           AND a.scheduled_at::date = d.date
           AND a.scheduled_at::time >= w.start_time
           AND a.scheduled_at::time <  w.end_time
    """)


def downgrade() -> None:
    # Restaurar el prefijo ANTES de tirar la columna, o se pierde el dato.
    op.execute("""
        UPDATE titulatec_review_appointments
           SET note = '[CAMBIO] ' || change_request
         WHERE change_request IS NOT NULL
    """)
    op.drop_constraint("fk_titulatec_review_appointments_window",
                       "titulatec_review_appointments", type_="foreignkey")
    op.drop_index("ix_titulatec_review_appointments_window_id",
                  table_name="titulatec_review_appointments")
    op.drop_column("titulatec_review_appointments", "change_requested_at")
    op.drop_column("titulatec_review_appointments", "change_request")
    op.drop_column("titulatec_review_appointments", "window_id")

    op.drop_index("ix_titulatec_review_windows_day_user",
                  table_name="titulatec_review_windows")
    op.drop_index("ix_titulatec_review_windows_owner_user_id",
                  table_name="titulatec_review_windows")
    op.drop_index("ix_titulatec_review_windows_review_day_id",
                  table_name="titulatec_review_windows")
    op.drop_table("titulatec_review_windows")

    op.drop_constraint("ck_titulatec_cohort_review_days_capacity",
                       "titulatec_cohort_review_days", type_="check")
    op.drop_constraint("ck_titulatec_cohort_review_days_slot_minutes",
                       "titulatec_cohort_review_days", type_="check")
    op.drop_constraint("ck_titulatec_cohort_review_days_time_order",
                       "titulatec_cohort_review_days", type_="check")
    op.drop_index("ix_titulatec_cohort_review_days_is_closed",
                  table_name="titulatec_cohort_review_days")
    for nombre in ("is_closed", "location", "capacity", "slot_minutes",
                   "end_time", "start_time"):
        op.drop_column("titulatec_cohort_review_days", nombre)

    op.drop_constraint("ck_titulatec_cohorts_default_time_order",
                       "titulatec_cohorts", type_="check")
    for nombre in ("default_location", "default_capacity", "default_slot_minutes",
                   "default_end_time", "default_start_time"):
        op.drop_column("titulatec_cohorts", nombre)
