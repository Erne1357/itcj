"""titulatec: sella si el correo de rechazo salio (rejection_sent_at)

La bandeja de Solicitudes necesita distinguir una solicitud `rejected` cuyo
correo con el motivo SI salio de una donde `send_enrollment_rejected` fallo
(buzon de titulatec desconectado, plantilla rota, Graph caido). Mismo patron
que `verify_sent_at` para la liga de activacion: `EnrollmentRequestService
.reject()` sella esta columna en un commit PROPIO, despues de mandar el
correo, solo si el envio devolvio `True`. `NULL` en una fila `rejected` es lo
que la bandeja pinta como pildora ambar "correo no enviado".

Nullable, sin `server_default`: toda fila existente (rechazada antes de esta
revision) queda en NULL, que es honesto — no sabemos si su correo salio.

Correr con MIGRATE_DATABASE_URL (Postgres directo), nunca contra PgBouncer
(gotcha 1). ORDEN OBLIGATORIO: esta migracion se aplica ANTES de que el
modelo declare la columna (ver `models/enrollment_request.py`) para que otros
agentes con tests que insertan `EnrollmentRequest` en la BD de dev no truenen
por una columna que el modelo espera y la tabla no tiene todavia.

Revision ID: tt20260917a
Revises: tt20260915d
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20260917a"
down_revision = "tt20260915d"
branch_labels = None
depends_on = None

_TABLE = "titulatec_enrollment_requests"


def upgrade():
    op.add_column(_TABLE, sa.Column("rejection_sent_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column(_TABLE, "rejection_sent_at")
