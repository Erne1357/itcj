"""titulatec: outbox para los correos de inscripcion sin secreto

Spec `2026-10-05-titulatec-rendimiento-design.md` §3.7 (decision P-D1).
Escrita a mano (sin autogenerate), junto con el modelo: el CI arma el esquema
con `create_all` (sin Alembic) y dev/prod con Alembic -- la columna, su FK y
su indice estan declarados AQUI y en `models/email_outbox.py` con el mismo
nombre y tipo.

Que cambia
----------
* `titulatec_email_outbox.enrollment_request_id` BigInteger (el tipo de
  `titulatec_enrollment_requests.id`, igual que `titulatec_eligibility_checks.
  request_id`), FK a la solicitud, NULL, con indice
  `ix_titulatec_email_outbox_enrollment_request_id`. La FK lleva el nombre que
  Postgres le pone a la del `create_all` (`<tabla>_<columna>_fkey`), asi las
  dos bases quedan iguales.
* `user_id` pasa a NULLABLE: el rechazo de una solicitud se encola contra la
  SOLICITUD, que puede no tener usuario. La regla «toda fila tiene `user_id`
  o `enrollment_request_id`» es de la aplicacion (`StudentMail.enqueue` y el
  `before_insert` del modelo), no un CHECK de la BD.

Tabla con filas vivas y sin backfill: `ADD COLUMN` nullable sin default y
`DROP NOT NULL` son solo catalogo. El `lock_timeout` va primero, como en
`tt20260928a`.

Downgrade (CON PERDIDA, documentada)
-------------------------------------
1. BORRA las filas con `user_id IS NULL` (rechazos de solicitud encolados):
   el esquema viejo no las admite. Si alguna seguia `pending`, ese correo de
   rechazo ya no sale y la bandeja vuelve a pintar «correo no enviado».
2. Quita el indice, la FK y la columna.
3. Devuelve `user_id` a NOT NULL.
Las filas de los otros tres kinds nuevos (`enrollment_verified`,
`already_enrolled`, `process_cancelled`) traen `user_id` y se quedan: el
codigo viejo no las sabe componer y las cierra `obsolete` («sin composicion»)
en su primera corrida.

ADVERTENCIA: no ejecutar este SQL a mano. Solo via `alembic upgrade head` /
`alembic downgrade`.

Revision ID: tt20261005d
Revises: tt20261005c
Create Date: 2026-10-05
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261005d"
down_revision = "tt20261005c"
branch_labels = None
depends_on = None

_TABLE = "titulatec_email_outbox"
_REQUESTS = "titulatec_enrollment_requests"
_COLUMN = "enrollment_request_id"
_FK = "titulatec_email_outbox_enrollment_request_id_fkey"
_INDEX = "ix_titulatec_email_outbox_enrollment_request_id"


def upgrade():
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.BigInteger(), nullable=True))
    op.create_foreign_key(_FK, _TABLE, _REQUESTS, [_COLUMN], ["id"])
    op.create_index(_INDEX, _TABLE, [_COLUMN], unique=False)
    op.alter_column(_TABLE, "user_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade():
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"DELETE FROM {_TABLE} WHERE user_id IS NULL")
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    op.drop_column(_TABLE, _COLUMN)
    op.alter_column(_TABLE, "user_id", existing_type=sa.BigInteger(), nullable=False)
