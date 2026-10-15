"""titulatec: reemplazo de documento en el cotejo + version que no se reinicia

Escrita a mano (sin autogenerate: la deriva de modelos de otras apps borraria
cosas que no son de esta entrega), junto con `models/document.py`: el CI arma el
esquema con `create_all` y dev/prod con Alembic, asi que la columna se declara
AQUI y en el modelo con el mismo nombre y tipo.

Spec: docs/superpowers/specs/2026-10-15-titulatec-reemplazo-cotejo-design.md
(§3, §4.6, §6 y §9).

Que agrega
----------
`titulatec_documents.replacement_requested_at` DateTime NULL. No NULL =
REEMPLAZO ABIERTO: la jefatura de Servicios Escolares pidio en la cita de cotejo
(fase 2) que el egresado vuelva a subir ese documento de la fase 1. La escribe
SOLO `DocumentService.request_replacement` y la limpia SOLO
`DocumentService.review(status="approved")`. Nace NULL para todos: el codigo
viejo la ignora.

Que corrige (datos)
-------------------
`VERSION_FIX_SQL`: antes, borrar un documento y volverlo a subir creaba una fila
NUEVA con `version = 1` aunque fuera la quinta subida (en dev, 120 documentos
`version = 1` con un `document_deleted` previo). Cada subida real deja un
`ProcessEvent(document_uploaded)` con `type_code` en el payload, asi que la
version correcta es, como minimo, cuantas subidas tiene ese (proceso, tipo):
`version = GREATEST(version, n de document_uploaded)`. Nunca baja una version.
`payload` es `json` (no `jsonb`): `->>` funciona igual. Idempotente. El SQL vive
en una constante del modulo para que `tests/fastapi/titulatec/test_document_
version.py` ejecute ESTE mismo texto sobre filas sembradas.

Downgrade (CON PERDIDA)
-----------------------
Quita la columna: se pierden los reemplazos ABIERTOS. La correccion de version
NO se revierte (no hay forma de saber cual era el numero equivocado, y el
codigo viejo lo trata como un contador informativo).

Reversa (spec §9): `rollback.sh` PRIMERO (el codigo viejo ignora la columna);
este downgrade es opcional. Antes de bajarla, aprobar o listar los reemplazos
abiertos:

    SELECT process_id, type_code FROM titulatec_documents
     WHERE replacement_requested_at IS NOT NULL;

(con el codigo viejo, un documento `rejected` en fase 2 vuelve a dejar al
alumno sin poder subirlo).

ADVERTENCIA: no ejecutar este SQL a mano. Solo via `alembic upgrade head` /
`alembic downgrade`.

Revision ID: tt20261015a
Revises: tt20261013b
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20261015a"
down_revision = "tt20261013b"
branch_labels = None
depends_on = None

_TABLE = "titulatec_documents"

# Solo toca las filas que de verdad quedaron cortas (`s.subidas > d.version`):
# las demas ni se reescriben ni se bloquean.
VERSION_FIX_SQL = """
UPDATE titulatec_documents AS d
   SET version = GREATEST(d.version, s.subidas)
  FROM (
        SELECT e.process_id,
               e.payload->>'type_code' AS type_code,
               COUNT(*) AS subidas
          FROM titulatec_process_events AS e
         WHERE e.event_type = 'document_uploaded'
           AND e.payload IS NOT NULL
         GROUP BY e.process_id, e.payload->>'type_code'
       ) AS s
 WHERE s.process_id = d.process_id
   AND s.type_code = d.type_code
   AND s.subidas > d.version
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.add_column(_TABLE, sa.Column("replacement_requested_at", sa.DateTime(), nullable=True))
    op.execute(VERSION_FIX_SQL)


def downgrade() -> None:
    op.drop_column(_TABLE, "replacement_requested_at")
