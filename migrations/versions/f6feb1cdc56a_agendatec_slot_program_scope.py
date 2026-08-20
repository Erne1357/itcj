"""agendatec slot program scope

Tablas puente que permiten limitar un rango horario a carreras específicas.

`agendatec_availability_window_programs` es la config que guardó el
coordinador; `agendatec_time_slot_programs` es la proyección que consulta la
query del alumno.

NOTA SOBRE EL AUTOGENERATE: la ejecución de `alembic revision --autogenerate`
detectó ~110 líneas de drift ajeno a este cambio (índices y constraints de
helpdesk que existen en los modelos pero no en la BD, y viceversa). Ese drift
se eliminó a mano: esta migración contiene EXCLUSIVAMENTE las dos tablas
nuevas. Aplicar el drift de helpdesk aquí habría mezclado dos cambios sin
relación y sin haberlo pedido nadie.

Revision ID: f6feb1cdc56a
Revises: o1s2c3p4e004
Create Date: 2026-08-20 09:30:58.090421

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f6feb1cdc56a'
down_revision = 'o1s2c3p4e004'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'agendatec_availability_window_programs',
        sa.Column('window_id', sa.Integer(), nullable=False),
        sa.Column('program_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['program_id'], ['core_programs.id'], onupdate='CASCADE', ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['window_id'], ['agendatec_availability_windows.id'],
            onupdate='CASCADE', ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('window_id', 'program_id'),
    )
    op.create_index(
        op.f('ix_agendatec_availability_window_programs_program_id'),
        'agendatec_availability_window_programs', ['program_id'], unique=False,
    )

    op.create_table(
        'agendatec_time_slot_programs',
        sa.Column('slot_id', sa.BigInteger(), nullable=False),
        sa.Column('program_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['program_id'], ['core_programs.id'], onupdate='CASCADE', ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['slot_id'], ['agendatec_time_slots.id'], onupdate='CASCADE', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('slot_id', 'program_id'),
    )
    op.create_index(
        op.f('ix_agendatec_time_slot_programs_program_id'),
        'agendatec_time_slot_programs', ['program_id'], unique=False,
    )

    # --- Backfill -----------------------------------------------------------
    # El default del feature es "todas las carreras del coordinador", y se
    # materializa como filas EXPLÍCITAS (no como ausencia de filas) para que la
    # query del alumno sea un INNER JOIN sin OR NOT EXISTS. Sembrando así, el
    # comportamiento visible no cambia hasta que alguien limite un rango.
    op.execute("""
        INSERT INTO agendatec_time_slot_programs (slot_id, program_id)
        SELECT ts.id, pc.program_id
        FROM agendatec_time_slots ts
        JOIN core_program_coordinator pc ON pc.coordinator_id = ts.coordinator_id
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        INSERT INTO agendatec_availability_window_programs (window_id, program_id)
        SELECT aw.id, pc.program_id
        FROM agendatec_availability_windows aw
        JOIN core_program_coordinator pc ON pc.coordinator_id = aw.coordinator_id
        ON CONFLICT DO NOTHING
    """)

    # --- Guarda -------------------------------------------------------------
    # Un coordinador sin filas en core_program_coordinator dejaría sus slots sin
    # proyección: invisibles para todos y sin ningún error. Abortar antes de
    # dejar la BD en ese estado es preferible a descubrirlo en producción.
    orphans = op.get_bind().execute(sa.text("""
        SELECT count(*) FROM agendatec_time_slots ts
        WHERE NOT EXISTS (
            SELECT 1 FROM agendatec_time_slot_programs p WHERE p.slot_id = ts.id
        )
    """)).scalar()
    if orphans:
        raise RuntimeError(
            f"{orphans} slots quedaron sin carrera asignada tras el backfill. "
            "Revisa que todo coordinador con slots tenga fila en "
            "core_program_coordinator antes de aplicar esta migración."
        )


def downgrade():
    op.drop_index(
        op.f('ix_agendatec_time_slot_programs_program_id'),
        table_name='agendatec_time_slot_programs',
    )
    op.drop_table('agendatec_time_slot_programs')
    op.drop_index(
        op.f('ix_agendatec_availability_window_programs_program_id'),
        table_name='agendatec_availability_window_programs',
    )
    op.drop_table('agendatec_availability_window_programs')
