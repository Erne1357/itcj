"""Redesign time slots: general slots with volunteer signup

Revision ID: b3c4d5e6f7a8
Revises: 22cfcc00d729
Create Date: 2026-02-11

Changes:
- Create vistetec_slot_volunteers junction table (N:N slots-volunteers)
- Replace volunteer_id with created_by_id in vistetec_time_slots
- Add will_bring_donation to vistetec_appointments
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3c4d5e6f7a8'
down_revision = '22cfcc00d729'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create junction table vistetec_slot_volunteers
    op.create_table('vistetec_slot_volunteers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slot_id', sa.Integer(), nullable=False),
        sa.Column('volunteer_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['slot_id'], ['vistetec_time_slots.id']),
        sa.ForeignKeyConstraint(['volunteer_id'], ['core_users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slot_id', 'volunteer_id', name='uq_slot_volunteer'),
    )
    with op.batch_alter_table('vistetec_slot_volunteers', schema=None) as batch_op:
        batch_op.create_index('ix_vistetec_slot_volunteers_slot_id', ['slot_id'], unique=False)
        batch_op.create_index('ix_vistetec_slot_volunteers_volunteer_id', ['volunteer_id'], unique=False)

    # 2. Add created_by_id to time_slots (nullable temporarily for data migration)
    with op.batch_alter_table('vistetec_time_slots', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_by_id', sa.BigInteger(), nullable=True))

    # 3. Migrate data: copy volunteer_id → created_by_id
    op.execute('UPDATE vistetec_time_slots SET created_by_id = volunteer_id')

    # 4. Preserve volunteer relationships in junction table
    op.execute(
        'INSERT INTO vistetec_slot_volunteers (slot_id, volunteer_id) '
        'SELECT id, volunteer_id FROM vistetec_time_slots WHERE volunteer_id IS NOT NULL'
    )

    # 5. Make created_by_id NOT NULL + FK, drop old volunteer columns/indexes
    with op.batch_alter_table('vistetec_time_slots', schema=None) as batch_op:
        batch_op.alter_column('created_by_id', nullable=False)
        batch_op.create_foreign_key('fk_timeslot_created_by', 'core_users', ['created_by_id'], ['id'])
        batch_op.create_index('ix_vistetec_slot_created_by_date', ['created_by_id', 'date'], unique=False)
        batch_op.create_index('ix_vistetec_time_slots_created_by_id', ['created_by_id'], unique=False)
        # Drop old volunteer-based indexes
        batch_op.drop_index('ix_vistetec_slot_volunteer_date')
        batch_op.drop_index('ix_vistetec_time_slots_volunteer_id')
        # Drop volunteer_id column
        batch_op.drop_column('volunteer_id')

    # 6. Add will_bring_donation to appointments
    with op.batch_alter_table('vistetec_appointments', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('will_bring_donation', sa.Boolean(), server_default=sa.text('FALSE'), nullable=True)
        )


def downgrade():
    # Remove will_bring_donation from appointments
    with op.batch_alter_table('vistetec_appointments', schema=None) as batch_op:
        batch_op.drop_column('will_bring_donation')

    # Restore volunteer_id to time_slots
    with op.batch_alter_table('vistetec_time_slots', schema=None) as batch_op:
        batch_op.add_column(sa.Column('volunteer_id', sa.BigInteger(), nullable=True))

    # Migrate data back: copy created_by_id → volunteer_id
    op.execute('UPDATE vistetec_time_slots SET volunteer_id = created_by_id')

    with op.batch_alter_table('vistetec_time_slots', schema=None) as batch_op:
        batch_op.alter_column('volunteer_id', nullable=False)
        batch_op.create_foreign_key('fk_timeslot_volunteer', 'core_users', ['volunteer_id'], ['id'])
        batch_op.create_index('ix_vistetec_slot_volunteer_date', ['volunteer_id', 'date'], unique=False)
        batch_op.create_index('ix_vistetec_time_slots_volunteer_id', ['volunteer_id'], unique=False)
        # Drop new columns/indexes
        batch_op.drop_index('ix_vistetec_slot_created_by_date')
        batch_op.drop_index('ix_vistetec_time_slots_created_by_id')
        batch_op.drop_constraint('fk_timeslot_created_by', type_='foreignkey')
        batch_op.drop_column('created_by_id')

    # Drop junction table
    with op.batch_alter_table('vistetec_slot_volunteers', schema=None) as batch_op:
        batch_op.drop_index('ix_vistetec_slot_volunteers_volunteer_id')
        batch_op.drop_index('ix_vistetec_slot_volunteers_slot_id')

    op.drop_table('vistetec_slot_volunteers')
