"""cameras: tipo de cámaras y cuántas hay de cada una (bala, PTZ) por DVR

Escrita a mano. Tres columnas NULLABLE sin default (tabla con datos en prod) y
sus CHECK; sin backfill.

Downgrade (CON PERDIDA de esos tres datos): quita constraints y columnas.

Revision ID: cam20261118a
Revises: cam20261113a
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa

revision = "cam20261118a"
down_revision = "cam20261113a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.add_column("cameras_dvrs", sa.Column("camera_type", sa.String(10), nullable=True))
    op.add_column("cameras_dvrs", sa.Column("cameras_bala", sa.Integer(), nullable=True))
    op.add_column("cameras_dvrs", sa.Column("cameras_ptz", sa.Integer(), nullable=True))
    op.create_check_constraint("ck_cameras_dvrs_camera_type", "cameras_dvrs",
                               "camera_type IN ('bala','ptz','mixtas')")
    op.create_check_constraint("ck_cameras_dvrs_cameras_bala", "cameras_dvrs",
                               "cameras_bala BETWEEN 0 AND 128")
    op.create_check_constraint("ck_cameras_dvrs_cameras_ptz", "cameras_dvrs",
                               "cameras_ptz BETWEEN 0 AND 128")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.drop_constraint("ck_cameras_dvrs_cameras_ptz", "cameras_dvrs", type_="check")
    op.drop_constraint("ck_cameras_dvrs_cameras_bala", "cameras_dvrs", type_="check")
    op.drop_constraint("ck_cameras_dvrs_camera_type", "cameras_dvrs", type_="check")
    op.drop_column("cameras_dvrs", "cameras_ptz")
    op.drop_column("cameras_dvrs", "cameras_bala")
    op.drop_column("cameras_dvrs", "camera_type")
