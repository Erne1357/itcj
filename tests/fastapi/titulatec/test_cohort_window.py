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

Desde `tt20260927b` (spec 2026-09-27 §B) las dos columnas son `DateTime` NOT
NULL y los predicados comparan al minuto contra `db_now()`: ya no hay «fechas
NULL = sin tope», y `set_window` exige los dos extremos.

Aislamiento
-----------
La suite corre contra la BD de dev dentro de un SAVEPOINT, así que las
convocatorias REALES son visibles para un `db.query(Cohort)` sin filtro — que es
justo lo que hace el resolver. `sin_convocatorias_previas` las pasa a `draft`
DENTRO de la transacción del test (`draft` no entra ni en el predicado de
apertura ni en el de reanudación) y el rollback del fixture `db_session` las deja
intactas. Contra la BD vacía de CI el fixture es un no-op.
"""
from datetime import datetime, timedelta

import pytest

from itcj2.core.utils.timezone import db_now


def _hoy() -> datetime:
    """Hoy a las 00:00 en el reloj de la ventana (`db_now`, hora local)."""
    return db_now().replace(hour=0, minute=0, second=0, microsecond=0)


def _cierre(dias: int) -> datetime:
    """El cierre por omisión: `dias` desde hoy, a las 23:59:59."""
    return _hoy() + timedelta(days=dias, hours=23, minutes=59, seconds=59)


@pytest.fixture()
def sin_convocatorias_previas(db_session):
    """Saca del radar las convocatorias ya commiteadas en la BD compartida."""
    from itcj2.apps.titulatec.models import Cohort

    db_session.query(Cohort).update({Cohort.status: "draft"},
                                    synchronize_session=False)
    db_session.flush()
    db_session.expire_all()
    return db_session


# ---------------------------------------------------------------------------
# is_public_enrollment_open
# ---------------------------------------------------------------------------
def test_el_predicado_exige_open_y_la_fecha_dentro(db_session, make_cohort):
    from itcj2.apps.titulatec.services.cohort_service import CohortService
    hoy = _hoy()

    abierta = make_cohort(status="open", opens_at=hoy - timedelta(days=1),
                          closes_at=_cierre(1))
    borrador = make_cohort(status="draft")
    cerrada = make_cohort(status="closed")
    futura = make_cohort(status="open", opens_at=hoy + timedelta(days=1),
                         closes_at=_cierre(5))
    vencida = make_cohort(status="open", opens_at=hoy - timedelta(days=10),
                          closes_at=_cierre(-1))

    assert CohortService.is_public_enrollment_open(abierta) is True
    assert CohortService.is_public_enrollment_open(borrador) is False
    assert CohortService.is_public_enrollment_open(cerrada) is False
    assert CohortService.is_public_enrollment_open(futura) is False
    assert CohortService.is_public_enrollment_open(vencida) is False
    assert CohortService.is_public_enrollment_open(None) is False


def test_el_ultimo_minuto_del_cierre_sigue_abierto(make_cohort):
    """Review Focus 3: con el cierre POR OMISIÓN (solo fecha → 23:59:59), quien
    envía a las 23:59:30 del último día sigue dentro; a las 00:00:00 del día
    siguiente ya no. El cierre sale del mismo `_parse_window_dt` que usa la
    ruta, no de un literal del test."""
    from itcj2.apps.titulatec.pages.admin import (
        _CLOSES_DEFAULT_TIME, _OPENS_DEFAULT_TIME, _parse_window_dt,
    )
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    apertura = _parse_window_dt("2031-03-10", "", default=_OPENS_DEFAULT_TIME)
    cierre = _parse_window_dt("2031-03-20", "", default=_CLOSES_DEFAULT_TIME)
    assert cierre == datetime(2031, 3, 20, 23, 59, 59)
    cohort = make_cohort(status="open", opens_at=apertura, closes_at=cierre)

    assert CohortService.is_public_enrollment_open(
        cohort, now=datetime(2031, 3, 20, 23, 59, 30)) is True
    assert CohortService.is_public_enrollment_open(
        cohort, now=datetime(2031, 3, 20, 23, 59, 59)) is True
    assert CohortService.is_public_enrollment_open(
        cohort, now=datetime(2031, 3, 21, 0, 0, 0)) is False


def test_la_apertura_respeta_la_hora(make_cohort):
    """Al minuto: una apertura a las 09:00 está cerrada a las 08:59."""
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    cohort = make_cohort(status="open", opens_at=datetime(2031, 3, 10, 9, 0),
                         closes_at=datetime(2031, 3, 20, 23, 59, 59))

    assert CohortService.is_public_enrollment_open(
        cohort, now=datetime(2031, 3, 10, 8, 59)) is False
    assert CohortService.is_public_enrollment_open(
        cohort, now=datetime(2031, 3, 10, 9, 0)) is True


def test_un_cierre_tecleado_23_59_conserva_su_ultimo_minuto(make_cohort):
    """Revisión final (F10): la hora tecleada se guarda HH:MM:00, así que un
    cierre escrito «23:59» es 23:59:00. «Al minuto» de verdad: a las 23:59:30
    sigue abierto, igual que con el cierre por omisión (23:59:59); a las
    00:00:00 del día siguiente, cerrado. El cierre sale del mismo
    `_parse_window_dt` que usa la ruta."""
    from itcj2.apps.titulatec.pages.admin import _CLOSES_DEFAULT_TIME, _parse_window_dt
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    cierre = _parse_window_dt("2031-03-20", "23:59", default=_CLOSES_DEFAULT_TIME)
    assert cierre == datetime(2031, 3, 20, 23, 59, 0)
    cohort = make_cohort(status="open", opens_at=datetime(2031, 3, 10),
                         closes_at=cierre)

    assert CohortService.is_public_enrollment_open(
        cohort, now=datetime(2031, 3, 20, 23, 59, 30)) is True
    assert CohortService.is_public_enrollment_open(
        cohort, now=datetime(2031, 3, 20, 23, 59, 59, 999999)) is True
    assert CohortService.is_public_enrollment_open(
        cohort, now=datetime(2031, 3, 21, 0, 0, 0)) is False


def test_la_apertura_es_al_minuto(make_cohort):
    """F10: una apertura a las 09:00 sigue cerrada a las 08:59:59 y ya está
    abierta a las 09:00:30 (el minuto de las 09:00 cuenta entero)."""
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    cohort = make_cohort(status="open", opens_at=datetime(2031, 3, 10, 9, 0),
                         closes_at=datetime(2031, 3, 20, 23, 59, 59))

    assert CohortService.is_public_enrollment_open(
        cohort, now=datetime(2031, 3, 10, 8, 59, 59)) is False
    assert CohortService.is_public_enrollment_open(
        cohort, now=datetime(2031, 3, 10, 9, 0, 30)) is True


def test_la_proxima_ventana_y_el_predicado_comparan_igual(sin_convocatorias_previas,
                                                        make_cohort, db_session):
    """F10: `next_public_enrollment_window` trunca al minuto como
    `is_public_enrollment_open`, así los dos nunca se contradicen: una
    convocatoria cerrada porque su apertura aún no llega se anuncia como la
    próxima, aunque la apertura traiga segundos (09:00:30 con el reloj en
    09:00:45 → el minuto de las 09:00 todavía no la alcanza)."""
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    cohort = make_cohort(status="open", opens_at=datetime(2031, 3, 10, 9, 0, 30),
                         closes_at=datetime(2031, 3, 20, 23, 59, 59))
    ahora = datetime(2031, 3, 10, 9, 0, 45)

    assert CohortService.is_public_enrollment_open(cohort, now=ahora) is False
    prox = CohortService.next_public_enrollment_window(db_session, now=ahora)
    assert prox is not None and prox.id == cohort.id, (
        "cerrada por no haber abierto: tiene que anunciarse como la próxima")


def test_los_predicados_usan_db_now(sin_convocatorias_previas, make_cohort,
                                    db_session, monkeypatch):
    """Review Focus 5: el reloj del proceso puede no estar en APP_TZ. Con
    `db_now` fijado a un instante y el `datetime`/`date` del módulo a otro,
    manda `db_now` — en los dos predicados."""
    from datetime import date as date_real

    import itcj2.apps.titulatec.services.cohort_service as mod
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    cohort = make_cohort(status="open", opens_at=datetime(2031, 3, 10, 9, 0),
                         closes_at=datetime(2031, 3, 20, 23, 59, 59))
    antes = datetime(2031, 3, 1, 12, 0)
    dentro = datetime(2031, 3, 15, 12, 0)

    class _RelojDelProceso(datetime):
        """El reloj del proceso: se mueve SIEMPRE al lado contrario de `db_now`."""
        instante = antes

        @classmethod
        def now(cls, tz=None):
            return cls.instante

        @classmethod
        def today(cls):
            return cls.instante

    class _HoyDelProceso(date_real):
        @classmethod
        def today(cls):
            return _RelojDelProceso.instante.date()

    monkeypatch.setattr(mod, "datetime", _RelojDelProceso, raising=False)
    monkeypatch.setattr(mod, "date", _HoyDelProceso, raising=False)

    # db_now DENTRO de la ventana, el proceso ANTES de la apertura.
    monkeypatch.setattr(mod, "db_now", lambda: dentro)
    _RelojDelProceso.instante = antes
    assert CohortService.is_public_enrollment_open(cohort) is True
    assert CohortService.next_public_enrollment_window(db_session) is None, (
        "según db_now ya abrió: no es la PRÓXIMA")

    # Al revés: db_now ANTES de la apertura, el proceso DENTRO.
    monkeypatch.setattr(mod, "db_now", lambda: antes)
    _RelojDelProceso.instante = dentro
    assert CohortService.is_public_enrollment_open(cohort) is False
    prox = CohortService.next_public_enrollment_window(db_session)
    assert prox is not None and prox.id == cohort.id


# ---------------------------------------------------------------------------
# accepts_enrollment_followup — D5 (spec 2026-09-24)
# ---------------------------------------------------------------------------
def test_el_seguimiento_de_una_solicitud_solo_exige_status_open(
    db_session, make_cohort,
):
    """Aprobar, dar acceso, abrir la liga y reenviarla ignoran las fechas: la
    ventana solo filtra el formulario público. Solo `closed` (pausa) y `draft`
    lo detienen."""
    from itcj2.apps.titulatec.services.cohort_service import CohortService
    hoy = _hoy()

    abierta = make_cohort(status="open", opens_at=hoy - timedelta(days=1),
                          closes_at=_cierre(1))
    vencida = make_cohort(status="open", opens_at=hoy - timedelta(days=10),
                          closes_at=_cierre(-1))
    futura = make_cohort(status="open", opens_at=hoy + timedelta(days=1),
                         closes_at=_cierre(5))
    cerrada = make_cohort(status="closed")
    borrador = make_cohort(status="draft")

    for c in (abierta, vencida, futura):
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

    res = CohortService.set_window(db_session, nueva.id, opens_at=_hoy(),
                                   closes_at=_cierre(30),
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

    res = CohortService.set_window(db_session, cohort.id, opens_at=cohort.opens_at,
                                   closes_at=cohort.closes_at, status="open", actor_id=jefa.id)

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

    res = CohortService.set_window(db_session, cohort.id, opens_at=cohort.opens_at,
                                   closes_at=cohort.closes_at, status="closed", actor_id=jefa.id)

    for p in (activo, terminado, cancelado, ajeno):
        db_session.refresh(p)
    assert res == {"paused": 1, "resumed": 0}
    assert activo.status == "on_hold"
    assert terminado.status == "completed"
    assert cancelado.status == "cancelled"
    assert ajeno.status == "active", "La pausa se acota a ESA convocatoria."
    assert (db_session.query(ProcessEvent)
            .filter_by(process_id=activo.id, event_type="process_paused").count()) == 1


@pytest.mark.parametrize("anterior,nuevo,estado_proc", [
    ("open", "closed", "active"),       # pausa
    ("closed", "open", "on_hold"),      # reanuda
])
def test_pausar_y_reanudar_bloquean_los_procesos_que_mueven(
        sin_convocatorias_previas, make_cohort, make_student, make_process,
        make_head, db_session, anterior, nuevo, estado_proc):
    """Revisión final (F2): sin `FOR UPDATE`, una revocación que hace commit
    entre la lectura y el flush se pisa (`cancelled` -> `on_hold`/`active`).
    Con el bloqueo, Postgres re-evalúa el filtro de estado tras la espera y la
    revocada queda fuera."""
    from sqlalchemy import event
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    jefa = make_head()
    cohort = make_cohort(status=anterior)
    make_process(make_student(), cohort=cohort, status=estado_proc)
    sentencias: list[str] = []

    def _captura(conn, cursor, statement, parameters, context, executemany):
        sentencias.append(" ".join(statement.split()))

    conn = db_session.connection()
    event.listen(conn, "before_cursor_execute", _captura)
    try:
        res = CohortService.set_window(db_session, cohort.id, opens_at=cohort.opens_at,
                                       closes_at=cohort.closes_at, status=nuevo, actor_id=jefa.id)
    finally:
        event.remove(conn, "before_cursor_execute", _captura)

    assert res["paused"] + res["resumed"] == 1
    lecturas = [s for s in sentencias
                if s.startswith("SELECT") and "FROM titulatec_processes" in s]
    assert lecturas, sentencias
    assert all(s.endswith("FOR NO KEY UPDATE") for s in lecturas), lecturas


def test_cerrar_dos_veces_no_pausa_de_nuevo(sin_convocatorias_previas, make_cohort,
                                            make_student, make_process, make_head,
                                            db_session):
    """`closed→closed` es un no-op: idempotente y sin eventos duplicados."""
    from itcj2.apps.titulatec.models import ProcessEvent
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    jefa = make_head()
    cohort = make_cohort(status="open")
    proc = make_process(make_student(), cohort=cohort, status="active")

    CohortService.set_window(db_session, cohort.id, opens_at=cohort.opens_at,
                             closes_at=cohort.closes_at,
                             status="closed", actor_id=jefa.id)
    res = CohortService.set_window(db_session, cohort.id, opens_at=cohort.opens_at,
                                   closes_at=cohort.closes_at, status="closed", actor_id=jefa.id)

    assert res == {"paused": 0, "resumed": 0}
    assert (db_session.query(ProcessEvent)
            .filter_by(process_id=proc.id, event_type="process_paused").count()) == 1


def test_draft_a_closed_tambien_pausa(sin_convocatorias_previas, make_cohort,
                                      make_student, make_process, make_head, db_session):
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    jefa = make_head()
    cohort = make_cohort(status="draft")
    proc = make_process(make_student(), cohort=cohort, status="active")

    res = CohortService.set_window(db_session, cohort.id, opens_at=cohort.opens_at,
                                   closes_at=cohort.closes_at, status="closed", actor_id=jefa.id)

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

    res = CohortService.set_window(db_session, cohort.id, opens_at=cohort.opens_at,
                                   closes_at=cohort.closes_at, status="draft", actor_id=jefa.id)

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
    nuevo_cierre = _cierre(60)

    res = CohortService.set_window(db_session, cohort.id, opens_at=_hoy(),
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

    with pytest.raises(ValueError, match="borrador, abierta o cerrada"):
        CohortService.set_window(db_session, cohort.id, opens_at=cohort.opens_at,
                                 closes_at=cohort.closes_at,
                                 status="abierta", actor_id=jefa.id)
    with pytest.raises(ValueError, match="no existe"):
        CohortService.set_window(db_session, 10**9, opens_at=cohort.opens_at,
                                 closes_at=cohort.closes_at,
                                 status="open", actor_id=jefa.id)


@pytest.mark.parametrize("falta", ["opens_at", "closes_at", "ambas"])
def test_la_apertura_y_el_cierre_son_obligatorios(make_cohort, make_head, db_session,
                                                  falta):
    """D9: las dos columnas son NOT NULL. Se rechaza ANTES de escribir, con el
    texto que lee la jefa, y la convocatoria queda como estaba."""
    from itcj2.apps.titulatec.services.cohort_service import CohortService
    jefa = make_head()
    cohort = make_cohort(status="draft")
    antes = (cohort.opens_at, cohort.closes_at, cohort.status)
    ventana = {"opens_at": cohort.opens_at, "closes_at": cohort.closes_at}
    for k in (("opens_at", "closes_at") if falta == "ambas" else (falta,)):
        ventana[k] = None

    with pytest.raises(ValueError) as exc:
        CohortService.set_window(db_session, cohort.id, status="open",
                                 actor_id=jefa.id, **ventana)

    assert str(exc.value) == "La apertura y el cierre son obligatorios."
    db_session.refresh(cohort)
    assert (cohort.opens_at, cohort.closes_at, cohort.status) == antes


@pytest.mark.parametrize("cierre_menos_apertura", [
    timedelta(0),                  # igualdad: rechazada (spec B2)
    -timedelta(minutes=1),
    -timedelta(days=1),
])
def test_el_cierre_tiene_que_ser_posterior_a_la_apertura(make_cohort, make_head,
                                                         db_session, cierre_menos_apertura):
    from itcj2.apps.titulatec.services.cohort_service import CohortService
    jefa = make_head()
    cohort = make_cohort(status="draft")
    apertura = datetime(2031, 3, 10, 9, 0)

    with pytest.raises(ValueError) as exc:
        CohortService.set_window(db_session, cohort.id, opens_at=apertura,
                                 closes_at=apertura + cierre_menos_apertura,
                                 status="open", actor_id=jefa.id)

    assert str(exc.value) == "El cierre tiene que ser posterior a la apertura."
    db_session.refresh(cohort)
    assert cohort.status == "draft"


def test_set_window_guarda_la_hora_exacta(make_cohort, make_head, db_session):
    """Una apertura a las 09:30 y un cierre a las 18:00 salen de la BD tal cual."""
    from itcj2.apps.titulatec.services.cohort_service import CohortService
    jefa = make_head()
    cohort = make_cohort(status="draft")

    CohortService.set_window(db_session, cohort.id,
                             opens_at=datetime(2031, 3, 10, 9, 30),
                             closes_at=datetime(2031, 3, 20, 18, 0),
                             status="draft", actor_id=jefa.id)

    db_session.expire(cohort)
    assert cohort.opens_at == datetime(2031, 3, 10, 9, 30)
    assert cohort.closes_at == datetime(2031, 3, 20, 18, 0)


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
