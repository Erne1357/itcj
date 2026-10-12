"""titulatec: promedio oficial en el expediente (bandeja Liberados)

Escrita a mano (sin autogenerate: la deriva de modelos de otras apps borraria
cosas que no son de esta entrega), junto con `models/process.py`: el CI arma el
esquema con `create_all` y dev/prod con Alembic, asi que la columna y el CHECK
se declaran AQUI y en el modelo con el mismo nombre y tipo.

Que agrega
----------
`titulatec_processes.final_average` Numeric(5,2) NULL: el promedio OFICIAL de la
carrera del egresado, que la bandeja «Liberados» muestra al Departamento de
Titulacion. Todavia no hay fuente (SII, CSV de Servicios Escolares o captura):
nace NULL para todos y la bandeja pinta «—». Nunca se rellena con el «Promedio
final» que el alumno autodeclaro en la encuesta de egresados.

CHECK `ck_titulatec_processes_final_average_range` (0 a 100, NULL permitido):
la captura que llegue despues no puede colar un 910 por un punto perdido.

Sin backfill, sin DML, sin permisos nuevos.

Downgrade (CON PERDIDA si ya se capturo algo)
---------------------------------------------
Quita el CHECK y la columna: se pierden los promedios capturados. El codigo
viejo no lee la columna.

ADVERTENCIA: no ejecutar este SQL a mano. Solo via `alembic upgrade head` /
`alembic downgrade`.

Revision ID: tt20261012a
Revises: tt20261007c
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261012a"
down_revision = "tt20261007c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("titulatec_processes",
                  sa.Column("final_average", sa.Numeric(precision=5, scale=2), nullable=True))
    op.create_check_constraint(
        "ck_titulatec_processes_final_average_range", "titulatec_processes",
        "final_average BETWEEN 0 AND 100")


def downgrade() -> None:
    op.drop_constraint("ck_titulatec_processes_final_average_range", "titulatec_processes",
                       type_="check")
    op.drop_column("titulatec_processes", "final_average")
