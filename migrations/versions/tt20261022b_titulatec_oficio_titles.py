"""titulatec fase 4: titulos personalizados del destinatario y del At'n. del oficio

Escrita a mano (sin autogenerate: arrastra deriva de otras apps), junto con
`models/program_department.py`: el CI arma el esquema con `create_all` y
dev/prod con Alembic, asi que las columnas se declaran AQUI y en el modelo con
el mismo nombre y tipo.

Spec: docs/superpowers/specs/2026-10-21-titulatec-fase4-sinodales-design.md
(revision final de la rama, hallazgo 17 / ruling R6).

Que agrega a `titulatec_department_settings`
--------------------------------------------
- `addressee_title` String(200) NULL: titulo con que el oficio nombra al
  destinatario (p. ej. «JEFA DE LA DIVISION DE ESTUDIOS PROFESIONALES»).
- `attn_title` String(200) NULL: titulo del «At'n.».
NULL = el titulo del puesto en el organigrama (comportamiento anterior). Sin
backfill: los valores del oficio real los siembra
`database/DML/titulatec/fase_2/02_sinodales.sql` (solo donde siguen NULL) via
`titulatec init-titulatec-fase-2`.

Compatibilidad: columnas NULL; el codigo anterior las ignora (rollback.sh basta).
Downgrade: quita las dos columnas; se pierden los titulos editados en
«Carreras por departamento» (la bitacora conserva el antes/despues).

Revision ID: tt20261022b
Revises: tt20261022a
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261022b"
down_revision = "tt20261022a"
branch_labels = None
depends_on = None

_TABLE = "titulatec_department_settings"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.add_column(_TABLE, sa.Column("addressee_title", sa.String(200), nullable=True))
    op.add_column(_TABLE, sa.Column("attn_title", sa.String(200), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.drop_column(_TABLE, "attn_title")
    op.drop_column(_TABLE, "addressee_title")
