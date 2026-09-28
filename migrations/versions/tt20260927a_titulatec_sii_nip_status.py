"""titulatec: el SII informa, Servicios Escolares decide -- estado y origen del NIP

`titulatec_eligibility_checks.nip_status` (String(20), nullable): lo que la
consulta al SII vio del NIP (spec `2026-09-27-titulatec-sii-informa-se-decide-design.md`
A2). Dominio: `available|missing|invalid|unavailable|error` (la persona NO
tenia cuenta en `core_users` al consultar: se le pidio el NIP al SII y se
clasifico) o `not_needed` (la persona SI tenia cuenta: sale la liga y el NIP
del SII no importa). NULL = no se reviso: la consulta termino en `error` o
sigue `pending` antes de llegar a pedir el NIP, o es una fila anterior a esta
migracion. NULL NO significa "tiene cuenta". Lo escriben
`EligibilityService.check` (via `classify_sii_nip`) y `record_nip_status`
(una aprobacion que vio al SII sin NIP valido); con eso la bandeja de
Solicitudes pinta desde el inicio el boton correcto (D6) sin reconsultar.
Nunca guarda el NIP, solo su estado.

`titulatec_enrollment_requests.nip_source` (String(20), nullable): de donde
salio el NIP de la cuenta que esta solicitud CREO. Lo escribe SOLO
`_create_account`: `sii` = la cuenta nacio con el NIP del SII («Aprobar y
dar acceso», modo `sii`); `center` = lo capturo Centro de Computo en Accesos
(`grant_access`, modo oficial `school_services` o modo `sii` pasando por
Accesos); `form` = lo tecleo quien aprobo en el modo ALTERNO
(`computer_center`), y solo ahi. NULL = no creo cuenta (cuenta preexistente:
se aprobo con liga) o fila anterior a esta migracion. «Con acceso» filtra
`nip_source IS DISTINCT FROM 'sii'`: Centro de Computo no intervino en esas
cuentas.

El relleno (UPDATE) NO es codigo muerto: desde `0b72d5f7` (ya en `main` y
desplegado) el codigo escribe `payload.nip_source = 'sii'` en el
`ProcessEvent('enrollment_self_service')` de cada cuenta creada con el NIP del
SII, asi que CUALQUIER ambiente que corrio el modo `sii` antes de esta
revision tiene solicitudes `converted` con esa marca y la columna todavia
vacia. Sin el relleno esas cuentas aparecerian en «Con acceso» de Accesos como
si Centro de Computo les hubiera dado el NIP. Se une por
`converted_process_id` Y `payload.request_id` (nunca marca la solicitud de
otra persona) y solo toca filas con `nip_source IS NULL` (no pisa un valor ya
resuelto). En produccion hoy no rellena nada (nunca corrio en modo `sii`); en
dev si.

`upgrade()` fija primero `SET LOCAL lock_timeout = '10s'`: ver el comentario
ahi.

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
    # Alembic corre esta revision y `tt20260927b` en UNA sola transaccion
    # (`migrations/env.py` no usa `transaction_per_migration`): los ADD COLUMN
    # de aqui retienen ACCESS EXCLUSIVE sobre solicitudes y consultas hasta el
    # COMMIT, y el `ALTER ... TYPE` de la b pide el de `titulatec_cohorts`. Un
    # lock ajeno sobre convocatorias (el backend viejo sirviendo, un export
    # largo, un psql «idle in transaction») lo haria esperar sin tope, y detras
    # se formaria toda consulta a las solicitudes: la inscripcion congelada
    # hasta el timeout del deploy en vez de fallar rapido. `SET LOCAL` vale para
    # el resto de la transaccion (las dos revisiones); si salta, el deploy
    # aborta limpio (nada queda a medias) y se reintenta.
    op.execute("SET LOCAL lock_timeout = '10s'")
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
