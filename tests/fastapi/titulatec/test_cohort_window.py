"""La ventana de la convocatoria: predicado, resolver y el flip de pausa/reanudación.

Contexto
--------
`titulatec_cohorts` tiene `opens_at`, `closes_at` y `status` desde su primera
migración y hasta hoy NADIE los escribía: `pages/admin.py:387` clavaba `"open"`
al crear y las dos fechas quedaban NULL para siempre. Consecuencia directa: el
predicado de apertura es verdadero para TODAS las convocatorias existentes, y
por eso el resolver falla cerrado con >1 en vez de desempatar por id — un
desempate silencioso mandaría al solicitante a otro periodo, y el folio y su
carpeta en disco llevan el periodo dentro.

Aislamiento
-----------
La suite corre contra la BD de dev dentro de un SAVEPOINT, así que las
convocatorias REALES son visibles para un `db.query(Cohort)` sin filtro — que es
justo lo que hace el resolver. `sin_convocatorias_previas` las pasa a `draft`
DENTRO de la transacción del test (`draft` no entra ni en el predicado de
apertura ni en el de reanudación) y el rollback del fixture `db_session` las deja
intactas. Contra la BD vacía de CI el fixture es un no-op.
"""
from datetime import date, timedelta

import pytest


@pytest.fixture()
def sin_convocatorias_previas(db_session):
    """Saca del radar las convocatorias ya commiteadas en la BD compartida."""
    from itcj2.apps.titulatec.models import Cohort

    db_session.query(Cohort).update({Cohort.status: "draft"},
                                    synchronize_session=False)
    db_session.flush()
    db_session.expire_all()
    return db_session


@pytest.fixture()
def sin_fechas():
    """`make_cohort` hace `opens_at or date.today()`: no sabe crear fechas NULL.

    Las convocatorias de producción SÍ las tienen NULL, que es el caso que hace
    verdadero el predicado para todas. Este helper las borra tras crear la fila.
    """
    def _quitar(db, cohort):
        cohort.opens_at = None
        cohort.closes_at = None
        db.flush()
        return cohort

    return _quitar


# ---------------------------------------------------------------------------
# is_public_enrollment_open
# ---------------------------------------------------------------------------
def test_el_predicado_exige_open_y_la_fecha_dentro(db_session, make_cohort, sin_fechas):
    from itcj2.apps.titulatec.services.cohort_service import CohortService
    hoy = date.today()

    abierta = make_cohort(status="open", opens_at=hoy - timedelta(days=1),
                          closes_at=hoy + timedelta(days=1))
    borrador = make_cohort(status="draft")
    cerrada = make_cohort(status="closed")
    futura = make_cohort(status="open", opens_at=hoy + timedelta(days=1),
                         closes_at=hoy + timedelta(days=5))
    vencida = make_cohort(status="open", opens_at=hoy - timedelta(days=10),
                          closes_at=hoy - timedelta(days=1))
    perpetua = sin_fechas(db_session, make_cohort(status="open"))

    assert CohortService.is_public_enrollment_open(abierta) is True
    assert CohortService.is_public_enrollment_open(borrador) is False
    assert CohortService.is_public_enrollment_open(cerrada) is False
    assert CohortService.is_public_enrollment_open(futura) is False
    assert CohortService.is_public_enrollment_open(vencida) is False
    assert CohortService.is_public_enrollment_open(perpetua) is True, (
        "Fechas NULL = sin tope. Es el estado de TODA convocatoria real hoy."
    )
    assert CohortService.is_public_enrollment_open(None) is False


# ---------------------------------------------------------------------------
# accepts_enrollment_followup — D5 (spec 2026-09-24)
# ---------------------------------------------------------------------------
def test_el_seguimiento_de_una_solicitud_solo_exige_status_open(
    db_session, make_cohort, sin_fechas,
):
    """Aprobar, dar acceso, abrir la liga y reenviarla ignoran las fechas: la
    ventana solo filtra el formulario público. Solo `closed` (pausa) y `draft`
    lo detienen."""
    from itcj2.apps.titulatec.services.cohort_service import CohortService
    hoy = date.today()

    abierta = make_cohort(status="open", opens_at=hoy - timedelta(days=1),
                          closes_at=hoy + timedelta(days=1))
    vencida = make_cohort(status="open", opens_at=hoy - timedelta(days=10),
                          closes_at=hoy - timedelta(days=1))
    futura = make_cohort(status="open", opens_at=hoy + timedelta(days=1),
                         closes_at=hoy + timedelta(days=5))
    perpetua = sin_fechas(db_session, make_cohort(status="open"))
    cerrada = make_cohort(status="closed")
    borrador = make_cohort(status="draft")

    for c in (abierta, vencida, futura, perpetua):
        assert CohortService.accepts_enrollment_followup(c) is True, c.opens_at
    assert CohortService.accepts_enrollment_followup(cerrada) is False
    assert CohortService.accepts_enrollment_followup(borrador) is False
    assert CohortService.accepts_enrollment_followup(None) is False
    # El formulario, en cambio, sigue cerrado fuera de fechas.
    assert CohortService.is_public_enrollment_open(vencida) is False


# ---------------------------------------------------------------------------
# public_enrollment_cohort — 0 / 1 / >1
# ---------------------------------------------------------------------------
def test_resolver_sin_ninguna_abierta_devuelve_closed(sin_convocatorias_previas,
                                                      make_cohort, db_session):
    from itcj2.apps.titulatec.services.cohort_service import CohortService
    make_cohort(status="draft")
    make_cohort(status="closed")

    cohort, error = CohortService.public_enrollment_cohort(db_session)

    assert cohort is None
    assert error == "closed"


def test_resolver_con_una_abierta_la_devuelve(sin_convocatorias_previas,
                                              make_cohort, db_session):
    from itcj2.apps.titulatec.services.cohort_service import CohortService
    make_cohort(status="draft")
    unica = make_cohort(status="open")

    cohort, error = CohortService.public_enrollment_cohort(db_session)

    assert error is None
    assert cohort is not None and cohort.id == unica.id


def test_resolver_con_dos_abiertas_falla_cerrado(sin_convocatorias_previas,
                                                 make_cohort, db_session):
    """NUNCA un desempate por id: el folio y la carpeta en disco llevan el
    periodo dentro, y elegir mal es irreversible en silencio."""
    from itcj2.apps.titulatec.services.cohort_service import CohortService
    make_cohort(status="open")
    make_cohort(status="open")

    cohort, error = CohortService.public_enrollment_cohort(db_session)

    assert cohort is None, "Con dos abiertas NO puede elegir una."
    assert error == "ambiguous"


# ---------------------------------------------------------------------------
# set_window — la tabla de transiciones de §6.7, una prueba por fila
# ---------------------------------------------------------------------------
def test_draft_a_open_reanuda_los_pausados_de_convocatorias_cerradas(
        sin_convocatorias_previas, make_cohort, make_student, make_process,
        make_head, db_session):
    from itcj2.apps.titulatec.models import ProcessEvent
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    jefa = make_head()
    vieja = make_cohort(status="closed")
    pausado = make_process(make_student(), cohort=vieja, status="on_hold")
    nueva = make_cohort(status="draft")

    res = CohortService.set_window(db_session, nueva.id, opens_at=date.today(),
                                   closes_at=date.today() + timedelta(days=30),
                                   status="open", actor_id=jefa.id)

    db_session.refresh(pausado)
    assert res == {"paused": 0, "resumed": 1}
    assert pausado.status == "active"
    assert pausado.cohort_id == vieja.id, "Reanudar NO cambia de convocatoria."
    eventos = (db_session.query(ProcessEvent)
               .filter_by(process_id=pausado.id, event_type="process_resumed").all())
    assert len(eventos) == 1


def test_closed_a_open_reanuda_tambien_los_suyos(sin_convocatorias_previas,
                                                 make_cohort, make_student,
                                                 make_process, make_head, db_session):
    """El conjunto de cerradas se calcula ANTES de escribir el nuevo status.

    Si se calculara después, esta convocatoria ya sería 'open' y sus propios
    procesos quedarían en `on_hold` para siempre.
    """
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    jefa = make_head()
    cohort = make_cohort(status="closed")
    propio = make_process(make_student(), cohort=cohort, status="on_hold")

    res = CohortService.set_window(db_session, cohort.id, opens_at=None,
                                   closes_at=None, status="open", actor_id=jefa.id)

    db_session.refresh(propio)
    assert res["resumed"] == 1
    assert propio.status == "active"


def test_open_a_closed_pausa_solo_los_activos_de_esa_convocatoria(
        sin_convocatorias_previas, make_cohort, make_student, make_process,
        make_head, db_session):
    from itcj2.apps.titulatec.models import ProcessEvent
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    jefa = make_head()
    cohort = make_cohort(status="open")
    otra = make_cohort(status="open")

    activo = make_process(make_student(), cohort=cohort, status="active")
    terminado = make_process(make_student(), cohort=cohort, status="completed")
    cancelado = make_process(make_student(), cohort=cohort, status="cancelled")
    ajeno = make_process(make_student(), cohort=otra, status="active")

    res = CohortService.set_window(db_session, cohort.id, opens_at=None,
                                   closes_at=None, status="closed", actor_id=jefa.id)

    for p in (activo, terminado, cancelado, ajeno):
        db_session.refresh(p)
    assert res == {"paused": 1, "resumed": 0}
    assert activo.status == "on_hold"
    assert terminado.status == "completed"
    assert cancelado.status == "cancelled"
    assert ajeno.status == "active", "La pausa se acota a ESA convocatoria."
    assert (db_session.query(ProcessEvent)
            .filter_by(process_id=activo.id, event_type="process_paused").count()) == 1


def test_cerrar_dos_veces_no_pausa_de_nuevo(sin_convocatorias_previas, make_cohort,
                                            make_student, make_process, make_head,
                                            db_session):
    """`closed→closed` es un no-op: idempotente y sin eventos duplicados."""
    from itcj2.apps.titulatec.models import ProcessEvent
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    jefa = make_head()
    cohort = make_cohort(status="open")
    proc = make_process(make_student(), cohort=cohort, status="active")

    CohortService.set_window(db_session, cohort.id, opens_at=None, closes_at=None,
                             status="closed", actor_id=jefa.id)
    res = CohortService.set_window(db_session, cohort.id, opens_at=None,
                                   closes_at=None, status="closed", actor_id=jefa.id)

    assert res == {"paused": 0, "resumed": 0}
    assert (db_session.query(ProcessEvent)
            .filter_by(process_id=proc.id, event_type="process_paused").count()) == 1


def test_draft_a_closed_tambien_pausa(sin_convocatorias_previas, make_cohort,
                                      make_student, make_process, make_head, db_session):
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    jefa = make_head()
    cohort = make_cohort(status="draft")
    proc = make_process(make_student(), cohort=cohort, status="active")

    res = CohortService.set_window(db_session, cohort.id, opens_at=None,
                                   closes_at=None, status="closed", actor_id=jefa.id)

    db_session.refresh(proc)
    assert res["paused"] == 1
    assert proc.status == "on_hold"


def test_pasar_a_draft_no_toca_ningun_proceso(sin_convocatorias_previas, make_cohort,
                                              make_student, make_process, make_head,
                                              db_session):
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    jefa = make_head()
    cerrada = make_cohort(status="closed")
    pausado = make_process(make_student(), cohort=cerrada, status="on_hold")
    cohort = make_cohort(status="open")
    activo = make_process(make_student(), cohort=cohort, status="active")

    res = CohortService.set_window(db_session, cohort.id, opens_at=None,
                                   closes_at=None, status="draft", actor_id=jefa.id)

    db_session.refresh(activo)
    db_session.refresh(pausado)
    assert res == {"paused": 0, "resumed": 0}
    assert activo.status == "active"
    assert pausado.status == "on_hold"


def test_abrir_lo_ya_abierto_solo_mueve_fechas(sin_convocatorias_previas, make_cohort,
                                               make_student, make_process, make_head,
                                               db_session):
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    jefa = make_head()
    cerrada = make_cohort(status="closed")
    pausado = make_process(make_student(), cohort=cerrada, status="on_hold")
    cohort = make_cohort(status="open")
    nuevo_cierre = date.today() + timedelta(days=60)

    res = CohortService.set_window(db_session, cohort.id, opens_at=date.today(),
                                   closes_at=nuevo_cierre, status="open",
                                   actor_id=jefa.id)

    db_session.refresh(cohort)
    db_session.refresh(pausado)
    assert res == {"paused": 0, "resumed": 0}, "open→open es un no-op para procesos."
    assert cohort.closes_at == nuevo_cierre
    assert pausado.status == "on_hold"


def test_rechaza_estado_desconocido_y_convocatoria_inexistente(make_cohort, make_head,
                                                               db_session):
    from itcj2.apps.titulatec.services.cohort_service import CohortService
    jefa = make_head()
    cohort = make_cohort(status="draft")

    with pytest.raises(ValueError):
        CohortService.set_window(db_session, cohort.id, opens_at=None, closes_at=None,
                                 status="abierta", actor_id=jefa.id)
    with pytest.raises(ValueError):
        CohortService.set_window(db_session, 10**9, opens_at=None, closes_at=None,
                                 status="open", actor_id=jefa.id)


def test_rechaza_cierre_anterior_a_la_apertura(make_cohort, make_head, db_session):
    from itcj2.apps.titulatec.services.cohort_service import CohortService
    jefa = make_head()
    cohort = make_cohort(status="draft")
    hoy = date.today()

    with pytest.raises(ValueError):
        CohortService.set_window(db_session, cohort.id, opens_at=hoy,
                                 closes_at=hoy - timedelta(days=1),
                                 status="open", actor_id=jefa.id)


# ---------------------------------------------------------------------------
# _active_cohort_id — la agenda de citas NUNCA debe caer en un borrador
# ---------------------------------------------------------------------------
def test_la_agenda_prefiere_open_y_nunca_elige_draft(sin_convocatorias_previas,
                                                     make_cohort, db_session):
    """`pages/appointments.py:114-118` hacía `filter_by(status="open") or la más
    nueva SEA CUAL SEA`. Con `cohort_create` naciendo en `draft`, ese respaldo
    aterrizaba en una convocatoria que todavía no existe para nadie."""
    from itcj2.apps.titulatec.pages.appointments import _active_cohort_id

    cerrada = make_cohort(status="closed")
    abierta = make_cohort(status="open")
    make_cohort(status="draft")          # la más NUEVA por id

    assert _active_cohort_id(db_session) == abierta.id

    abierta.status = "closed"
    db_session.flush()
    assert _active_cohort_id(db_session) == abierta.id, (
        "Sin ninguna abierta, la `closed` más nueva; jamás el borrador."
    )

    for c in (cerrada, abierta):
        c.status = "draft"
    db_session.flush()
    assert _active_cohort_id(db_session) is None, (
        "Solo borradores = no hay convocatoria de agenda."
    )
