"""titulatec: Servicios Escolares deshace el rechazo de una solicitud

La persona va a ventanilla, aclara lo que motivo el rechazo y SE regresa la
solicitud a «por revisar» (`EnrollmentRequestService.reopen`). Escrita a mano
(sin autogenerate, ver la deriva de modelos de otras apps), junto con el
modelo: el CI arma el esquema con `create_all` y dev/prod con Alembic, asi
que las columnas y la FK se declaran AQUI y en `models/enrollment_request.py`
con el mismo nombre y tipo.

Que cambia
----------
* `reopened_by_id` BigInteger, FK a `core_users`, NULL: quien deshizo el
  rechazo. La FK lleva el nombre que Postgres le pone a la del `create_all`
  (`<tabla>_<columna>_fkey`), igual que `returned_by_id` en `tt20260924a`.
* `reopened_at` DateTime, NULL.
* `reopen_note` Text, NULL: que se aclaro en ventanilla.

`review_note`/`reviewed_*` no se tocan: siguen siendo del rechazo deshecho
hasta que SE vuelva a resolver la solicitud.

Tabla con filas vivas y sin backfill: `ADD COLUMN` nullable sin default es
solo catalogo.

Downgrade (CON PERDIDA, documentada)
-------------------------------------
Quita la FK y las tres columnas: se pierde quien y por que deshizo cada
rechazo. Las solicitudes reabiertas se quedan en `pending_review`, un estado
que el codigo viejo conoce.

ADVERTENCIA: no ejecutar este SQL a mano. Solo via `alembic upgrade head` /
`alembic downgrade`.

Revision ID: tt20261006a
Revises: tt20261005d
Create Date: 2026-10-06
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261006a"
down_revision = "tt20261005d"
branch_labels = None
depends_on = None

_TABLE = "titulatec_enrollment_requests"
_FK = "titulatec_enrollment_requests_reopened_by_id_fkey"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("reopened_by_id", sa.BigInteger(), nullable=True))
    op.add_column(_TABLE, sa.Column("reopened_at", sa.DateTime(), nullable=True))
    op.add_column(_TABLE, sa.Column("reopen_note", sa.Text(), nullable=True))
    op.create_foreign_key(_FK, _TABLE, "core_users", ["reopened_by_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    op.drop_column(_TABLE, "reopen_note")
    op.drop_column(_TABLE, "reopened_at")
    op.drop_column(_TABLE, "reopened_by_id")
