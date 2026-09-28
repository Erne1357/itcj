"""titulatec: el SII informa, Servicios Escolares decide -- estado y origen del NIP

`titulatec_eligibility_checks.nip_status` (String(20), nullable): solo se
llena cuando la persona consultada NO tiene cuenta en `core_users` en ese
momento (spec `2026-09-27-titulatec-sii-informa-se-decide-design.md` A2).
Dominio: `available|missing|invalid|unavailable|error|not_needed`; NULL = no
se reviso (tiene cuenta, o el veredicto fue `error` antes de llegar a pedir
el NIP). Lo escribe `EligibilityService.check`/`classify_sii_nip`; con eso la
bandeja de Solicitudes pinta desde el inicio el boton correcto (D6) sin tener
que reconsultar.

`titulatec_enrollment_requests.nip_source` (String(20), nullable):
`sii|center|form`; NULL = cuenta preexistente (aprobar con liga) o fila
anterior a esta migracion. Lo escriben `_create_account`/`grant_access`:
`sii` cuando el NIP nacio de la consulta al SII, `center` cuando lo dio
Centro de Computo a mano, `form` en el modo alterno (`school_services`/
`computer_center`, sin SII). "Con acceso" filtra
`nip_source IS DISTINCT FROM 'sii'` para no listar las cuentas que ya
mandaron su propio correo con NIP.

El relleno (UPDATE) es LEGADO desde el dia uno: ninguna solicitud existente
hoy pudo nacer con `nip_source='sii'`, porque esta es la primera revision que
declara la columna. Se deja para reconstruir `nip_source` desde el rastro
que SI existe desde antes (`ProcessEvent('enrollment_self_service')` con
`payload.request_id`) si algun ambiente llega a correr esta migracion sobre
datos que el codigo nuevo (`payload.nip_source`) ya escribio -- por ejemplo,
una restauracion de un volcado de BD tomado despues de desplegar el codigo
pero antes de correr esta migracion. Solo toca filas con `nip_source IS
NULL` para no pisar un valor ya resuelto.

Escrita a mano (no autogenerate: arrastra drift ajeno). Correr con
MIGRATE_DATABASE_URL (Postgres directo), nunca contra PgBouncer.

Revision ID: tt20260927a
Revises: tt20260925b
"""
from alembic import op
import sqlalchemy as sa

revision = "tt20260927a"
down_revision = "tt20260925b"
branch_labels = None
depends_on = None

_CHECKS = "titulatec_eligibility_checks"
_REQUESTS = "titulatec_enrollment_requests"
_EVENTS = "titulatec_process_events"


def upgrade() -> None:
    op.add_column(_CHECKS, sa.Column("nip_status", sa.String(20), nullable=True))
    op.add_column(_REQUESTS, sa.Column("nip_source", sa.String(20), nullable=True))

    op.execute(
        f"UPDATE {_REQUESTS} er "
        f"SET nip_source = 'sii' "
        f"WHERE er.nip_source IS NULL "
        f"AND er.converted_process_id IS NOT NULL "
        f"AND EXISTS ("
        f"SELECT 1 FROM {_EVENTS} pe "
        f"WHERE pe.process_id = er.converted_process_id "
        f"AND pe.event_type = 'enrollment_self_service' "
        f"AND pe.payload->>'request_id' = er.id::text "
        f"AND pe.payload->>'nip_source' = 'sii'"
        f")"
    )


def downgrade() -> None:
    op.drop_column(_REQUESTS, "nip_source")
    op.drop_column(_CHECKS, "nip_status")
