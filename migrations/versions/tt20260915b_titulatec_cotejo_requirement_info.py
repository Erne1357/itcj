"""titulatec: informacion enriquecida (info_html) en los requisitos de cotejo

Servicios Escolares escribe, por requisito, una «Informacion para el alumno»
con formato (negritas, listas, ligas) en un editor visual; el alumno la abre con
el boton «i» de su pagina de cita.

La columna guarda HTML YA SANITIZADO (`utils/rich_text.sanitize_info_html`,
lista blanca con nh3), y las vistas lo vuelven a sanitizar al pintar: una fila
escrita por fuera del editor tampoco inyecta.

`Text` y NULL-able, sin `server_default`: NULL = sin informacion = sin boton,
que es el estado correcto para toda fila existente. Los textos por defecto de
acta y CURP los ponen `CotejoRequirementService.DEFAULTS` (convocatorias nuevas)
y `database/DML/titulatec/survey_2026_09/12_seed_cotejo_codes.sql` (las que ya
existen).

Correr con MIGRATE_DATABASE_URL (Postgres directo), nunca contra PgBouncer
(gotcha 1).

Revision ID: tt20260915b
Revises: tt20260915a
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20260915b"
down_revision = "tt20260915a"
branch_labels = None
depends_on = None

_TABLE = "titulatec_cotejo_requirements"


def upgrade():
    op.add_column(_TABLE, sa.Column("info_html", sa.Text(), nullable=True))


def downgrade():
    op.drop_column(_TABLE, "info_html")
