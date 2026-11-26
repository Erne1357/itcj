"""`AverageQueueService`: bandeja «Promedios» (spec 2026-11-26-titulatec-promedios-
pendientes-design.md §5 y §8, parte servicio).

Centro de Cómputo (vista `cc`) ve todo expediente sin promedio en dos pestañas;
Servicios Escolares (vista `se`) solo lo que CC le pasó, por carrera. Las páginas
(`test_averages_pages.py`) ponen la plomería encima.

La base de dev comparte filas reales: toda consulta de la vista `cc` se acota con
`q=TAG` (apellido propio de esta corrida) y la de `se` con carreras sembradas aquí.
"""
from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal

import pytest

import itcj2.models  # noqa: F401
from itcj2.apps.titulatec.services.average_queue_service import (
    LOAD_BUCKETS,
    LOAD_LABELS,
    TABS,
    AverageRow,
)
from itcj2.apps.titulatec.services.average_queue_service import (
    AverageQueueService as Svc,
)
from tests.fastapi.titulatec.conftest import audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")

D = Decimal
TAG = f"PROMQ{os.getpid()}"
LIST = "titulatec.average.page.list"
CAPTURE = "titulatec.average.api.capture"
REQUEST = "titulatec.average.api.request"


@pytest.fixture(autouse=True)
def _catalogo(seed_phase_defs):
    seed_phase_defs()


@pytest.fixture()
def carrera(make_program):
    return make_program(f"Ingenieria Promedios {TAG}")


@pytest.fixture()
def otra_carrera(make_program):
    return make_program(f"Ingenieria Otra {TAG}")


@pytest.fixture()
def cc(make_user, make_role, grant_user_role):
    user = make_user(first_name="CENTRO", last_name="COMPUTO")
    grant_user_role(user, make_role(f"tt_test_avg_cc_{os.getpid()}", (LIST, CAPTURE, REQUEST)))
    return user


@pytest.fixture()
def expediente(db_session, make_student, make_process, make_cohort, carrera):
    """Proceso SIN promedio de un alumno con apellido `TAG`. `fase=3` = ya liberado
    (fase 2 aprobada); `creado` fija `created_at` (todo lo sembrado en una
    transacción comparte `NOW()`)."""
    def _make(*, program=carrera, fase=1, status="active", control=None, creado=None,
              cohort=None):
        alumno = make_student(control_number=control, last_name=TAG)
        proc = make_process(alumno, cohort=cohort or make_cohort(), program=program,
                            current_phase=fase, status=status)
        if creado is not None:
            proc.created_at = creado
            db_session.flush()
        return proc

    return _make


def _ids(page):
    return [r.process_id for r in page.items]


def _cc_tray(db, tab="pending"):
    return Svc.tray(db, view="cc", tab=tab, allowed_program_ids="ALL", q=TAG, page=1)


def _control(db, proc):
    from itcj2.core.models.user import User
    return db.get(User, proc.student_id).control_number


def _audits(db, action):
    return audit_query(db).filter_by(action=action).all()


# ---------------------------------------------------------------------------
# view_for
# ---------------------------------------------------------------------------
def test_view_for_cc_con_el_permiso_de_pasar(db_session, cc):
    assert Svc.view_for(db_session, cc.id) == ("cc", "ALL")


def test_view_for_encargado_es_se_con_sus_carreras(db_session, make_officer, carrera):
    officer, _pos = make_officer([carrera], perm_codes=(LIST, CAPTURE))
    assert Svc.view_for(db_session, officer.id) == ("se", {carrera.id})


def test_view_for_jefa_con_read_all_es_se_todas(db_session, make_head):
    jefa = make_head(perm_codes=(LIST, CAPTURE, "titulatec.process.api.read.all"))
    assert Svc.view_for(db_session, jefa.id) == ("se", "ALL")


# ---------------------------------------------------------------------------
# tray / tab_counts
# ---------------------------------------------------------------------------
def test_por_capturar_solo_expedientes_sin_promedio(
        db_session, expediente, make_user, make_process, make_cohort, carrera):
    vivo = expediente()
    con_promedio = expediente()
    con_promedio.final_average = D("88.00")
    expediente(status="cancelled")
    pausado = expediente(status="on_hold")
    sin_control = make_process(make_user(last_name=TAG), cohort=make_cohort(), program=carrera)
    db_session.flush()

    ids = _ids(_cc_tray(db_session))

    assert set(ids) == {vivo.id, pausado.id}
    assert sin_control.id not in ids


def test_orden_liberados_primero_luego_fifo_por_creacion(db_session, expediente):
    viejo = expediente(creado=datetime(2026, 1, 1))
    nuevo = expediente(creado=datetime(2026, 3, 1))
    liberado = expediente(fase=3, creado=datetime(2026, 5, 1))

    page = _cc_tray(db_session)

    assert _ids(page) == [liberado.id, viejo.id, nuevo.id]
    assert [r.released for r in page.items] == [True, False, False]


def test_la_fila_trae_lo_que_pinta_la_bandeja(db_session, expediente, carrera):
    proc = expediente(fase=1)

    (row,) = _cc_tray(db_session).items

    assert isinstance(row, AverageRow)
    assert row.process_id == proc.id and row.folio == proc.folio
    assert row.control == _control(db_session, proc)
    assert TAG in row.name
    assert row.program == carrera.name
    assert row.cohort and row.phase_number == 1 and row.phase_name == "Documentos iniciales"
    assert row.released is False
    assert row.requested_at is None and row.requested_by_name is None


def test_pasar_a_escolares_mueve_de_pestana_en_orden_fifo(db_session, expediente, cc):
    primero = expediente()
    segundo = expediente()
    Svc.request_school_services(db_session, segundo.id, actor_id=cc.id)
    Svc.request_school_services(db_session, primero.id, actor_id=cc.id)
    # Mismo NOW() en la transacción: la FIFO la fija la fecha de paso.
    primero.average_requested_at = datetime(2026, 11, 26, 10, 0)
    segundo.average_requested_at = datetime(2026, 11, 25, 10, 0)
    db_session.flush()

    assert _ids(_cc_tray(db_session, "pending")) == []
    page = _cc_tray(db_session, "requested")
    assert _ids(page) == [segundo.id, primero.id]
    assert page.items[0].requested_by_name == "COMPUTO CENTRO"
    assert page.items[0].requested_at == datetime(2026, 11, 25, 10, 0)


def test_tab_counts_cc(db_session, expediente, cc):
    expediente()
    expediente()
    pasado = expediente()
    Svc.request_school_services(db_session, pasado.id, actor_id=cc.id)

    assert Svc.tab_counts(db_session, view="cc", allowed_program_ids="ALL", q=TAG) == {
        "pending": 2, "requested": 1}
    assert TABS == ("pending", "requested")


def test_se_solo_ve_lo_pasado_y_de_sus_carreras(
        db_session, expediente, cc, carrera, otra_carrera):
    expediente(program=carrera)                       # por capturar en CC: invisible
    pasado = expediente(program=carrera)
    ajeno = expediente(program=otra_carrera)
    for p in (pasado, ajeno):
        Svc.request_school_services(db_session, p.id, actor_id=cc.id)

    def se(allowed, tab="requested"):
        return _ids(Svc.tray(db_session, view="se", tab=tab, allowed_program_ids=allowed,
                             q=TAG, page=1))

    assert se({carrera.id}) == [pasado.id]
    assert se({carrera.id}, tab="pending") == [pasado.id]   # SE no tiene «Por capturar»
    assert set(se("ALL")) == {pasado.id, ajeno.id}
    assert se(set()) == []                                  # sin carreras: fail-closed
    assert Svc.tab_counts(db_session, view="se", allowed_program_ids={carrera.id},
                          q=TAG) == {"pending": 0, "requested": 1}
    assert Svc.tab_counts(db_session, view="se", allowed_program_ids=set(),
                          q=TAG) == {"pending": 0, "requested": 0}


def test_busqueda_por_control(db_session, expediente):
    uno = expediente()
    expediente()

    page = Svc.tray(db_session, view="cc", tab="pending", allowed_program_ids="ALL",
                    q=_control(db_session, uno), page=1)

    assert _ids(page) == [uno.id]


# ---------------------------------------------------------------------------
# pasar / regresar
# ---------------------------------------------------------------------------
def test_pasar_escribe_quien_y_cuando_y_la_bitacora(db_session, expediente, cc):
    proc = expediente()

    Svc.request_school_services(db_session, proc.id, actor_id=cc.id)

    db_session.refresh(proc)
    assert proc.average_requested_at is not None
    assert proc.average_requested_by_id == cc.id
    (fila,) = _audits(db_session, "average.requested")
    assert fila.process_id == proc.id and fila.actor_id == cc.id


def test_pasar_es_idempotente(db_session, expediente, cc, make_user):
    proc = expediente()
    Svc.request_school_services(db_session, proc.id, actor_id=cc.id)
    db_session.refresh(proc)
    antes = proc.average_requested_at

    Svc.request_school_services(db_session, proc.id, actor_id=make_user().id)

    db_session.refresh(proc)
    assert proc.average_requested_at == antes and proc.average_requested_by_id == cc.id
    assert len(_audits(db_session, "average.requested")) == 1


def test_pasar_o_regresar_con_promedio_es_value_error(db_session, expediente, cc):
    proc = expediente()
    proc.final_average = D("90.00")
    db_session.flush()

    with pytest.raises(ValueError, match="Ya tiene promedio"):
        Svc.request_school_services(db_session, proc.id, actor_id=cc.id)
    with pytest.raises(ValueError, match="Ya tiene promedio"):
        Svc.withdraw_request(db_session, proc.id, actor_id=cc.id)


def test_pasar_cancelado_o_inexistente_es_lookup_error(db_session, expediente, cc):
    cancelado = expediente(status="cancelled")

    for pid in (cancelado.id, 0):
        with pytest.raises(LookupError):
            Svc.request_school_services(db_session, pid, actor_id=cc.id)


def test_regresar_limpia_y_registra(db_session, expediente, cc):
    proc = expediente()
    Svc.request_school_services(db_session, proc.id, actor_id=cc.id)

    Svc.withdraw_request(db_session, proc.id, actor_id=cc.id)

    db_session.refresh(proc)
    assert proc.average_requested_at is None and proc.average_requested_by_id is None
    assert _ids(_cc_tray(db_session, "pending")) == [proc.id]
    assert len(_audits(db_session, "average.request_withdrawn")) == 1

    Svc.withdraw_request(db_session, proc.id, actor_id=cc.id)   # idempotente
    assert len(_audits(db_session, "average.request_withdrawn")) == 1


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------
def _captura(db, proc, raw, actor, *, view="cc", allowed="ALL"):
    return Svc.capture(db, proc.id, raw, actor_id=actor.id, view=view,
                       allowed_program_ids=allowed)


def test_capturar_escribe_tabla_proceso_y_bitacora(db_session, expediente, cc):
    from itcj2.apps.titulatec.models import OfficialAverage

    proc = expediente()

    assert _captura(db_session, proc, " 85,5 ", cc) == D("85.50")

    db_session.refresh(proc)
    assert proc.final_average == D("85.50")
    fila = db_session.get(OfficialAverage, _control(db_session, proc))
    assert fila.average == D("85.50") and fila.loaded_by_id == cc.id
    (aud,) = _audits(db_session, "average.final_set")
    assert aud.process_id == proc.id and aud.actor_id == cc.id
    assert _ids(_cc_tray(db_session)) == []                  # sale de la bandeja


def test_capturar_tambien_desde_con_escolares(db_session, expediente, cc):
    proc = expediente()
    Svc.request_school_services(db_session, proc.id, actor_id=cc.id)

    assert _captura(db_session, proc, "91", cc) == D("91.00")
    assert _ids(_cc_tray(db_session, "requested")) == []


@pytest.mark.parametrize("raw, texto", [
    ("69.99", "entre 70 y 100"),
    ("100.5", "entre 70 y 100"),
    ("ochenta", "Formato inválido"),
    ("", "Formato inválido"),
    ("85,5,1", "Formato inválido"),
])
def test_capturar_valor_invalido_es_value_error_sin_escribir(
        db_session, expediente, cc, raw, texto):
    proc = expediente()

    with pytest.raises(ValueError, match=texto):
        _captura(db_session, proc, raw, cc)

    db_session.refresh(proc)
    assert proc.final_average is None


def test_capturar_con_promedio_no_lo_pisa(db_session, expediente, cc):
    proc = expediente()
    proc.final_average = D("88.00")
    db_session.flush()

    with pytest.raises(ValueError, match="Ya tiene promedio"):
        _captura(db_session, proc, "90", cc)
    db_session.refresh(proc)
    assert proc.final_average == D("88.00")


def test_capturar_fuera_de_la_bandeja_es_lookup_error(
        db_session, expediente, cc, carrera, otra_carrera, make_officer):
    officer, _pos = make_officer([carrera], perm_codes=(LIST, CAPTURE))
    sin_pasar = expediente(program=carrera)
    ajeno = expediente(program=otra_carrera)
    Svc.request_school_services(db_session, ajeno.id, actor_id=cc.id)
    cancelado = expediente(status="cancelled")

    for proc in (sin_pasar, ajeno):                          # SE: no pasado / otra carrera
        with pytest.raises(LookupError):
            _captura(db_session, proc, "90", officer, view="se", allowed={carrera.id})
    with pytest.raises(LookupError):
        _captura(db_session, cancelado, "90", cc)
    with pytest.raises(LookupError):
        Svc.capture(db_session, 0, "90", actor_id=cc.id, view="cc", allowed_program_ids="ALL")


def test_se_captura_lo_pasado_de_su_carrera(db_session, expediente, cc, carrera, make_officer):
    officer, _pos = make_officer([carrera], perm_codes=(LIST, CAPTURE))
    proc = expediente(program=carrera)
    Svc.request_school_services(db_session, proc.id, actor_id=cc.id)

    assert _captura(db_session, proc, "77.255", officer, view="se",
                    allowed={carrera.id}) == D("77.26")
    db_session.refresh(proc)
    assert proc.final_average == D("77.26")
    assert proc.average_requested_by_id == cc.id             # la historia se queda


# ---------------------------------------------------------------------------
# load_rows (archivo)
# ---------------------------------------------------------------------------
def _carga(db, rows, actor, *, view="cc", allowed="ALL", dry_run=False):
    return Svc.load_rows(db, rows, actor_id=actor.id, view=view,
                         allowed_program_ids=allowed, dry_run=dry_run)


def _controles(res, bucket):
    return [c for c, _ in res[bucket]]


def test_buckets_fijos_y_con_etiqueta(db_session, cc):
    res = _carga(db_session, [], cc)
    assert tuple(res) == LOAD_BUCKETS == (
        "applied", "not_in_tray", "out_of_range", "invalid", "duplicate")
    assert set(LOAD_LABELS) == set(LOAD_BUCKETS)
    assert LOAD_LABELS["not_in_tray"] == "No está en tu bandeja"


def test_archivo_aplica_y_clasifica(db_session, expediente, cc):
    ok = expediente()
    coma = expediente()
    rango = expediente()
    dup = expediente()
    con_promedio = expediente()
    con_promedio.final_average = D("80.00")
    db_session.flush()
    c = {p: _control(db_session, p) for p in (ok, coma, rango, dup, con_promedio)}

    res = _carga(db_session, [
        (c[ok], "85.5"), ("L" + c[coma], "90,25"), (c[rango], "9.5"),
        (c[dup], "80"), (c[dup], "81"), (c[con_promedio], "95"),
        ("99999999", "80"), ("ABC", "80"), (c[ok][:-1] + "X", "80"), ("", ""),
    ], cc)

    assert sorted(_controles(res, "applied")) == sorted([c[ok], c[coma]])
    assert _controles(res, "out_of_range") == [c[rango]]
    assert _controles(res, "duplicate") == [c[dup]]
    assert sorted(_controles(res, "not_in_tray")) == sorted([c[con_promedio], "99999999"])
    assert len(res["invalid"]) == 2
    for p, v in ((ok, "85.50"), (coma, "90.25"), (con_promedio, "80.00")):
        db_session.refresh(p)
        assert p.final_average == D(v)                       # nunca pisa
    db_session.refresh(dup)
    assert dup.final_average is None
    assert len(_audits(db_session, "average.final_set")) == 2


def test_archivo_se_solo_su_bandeja(db_session, expediente, cc, carrera, otra_carrera,
                                    make_officer):
    officer, _pos = make_officer([carrera], perm_codes=(LIST, CAPTURE))
    pasado = expediente(program=carrera)
    sin_pasar = expediente(program=carrera)
    ajeno = expediente(program=otra_carrera)
    for p in (pasado, ajeno):
        Svc.request_school_services(db_session, p.id, actor_id=cc.id)

    res = _carga(db_session, [(_control(db_session, p), "88") for p in (pasado, sin_pasar, ajeno)],
                 officer, view="se", allowed={carrera.id})

    assert _controles(res, "applied") == [_control(db_session, pasado)]
    assert sorted(_controles(res, "not_in_tray")) == sorted(
        [_control(db_session, sin_pasar), _control(db_session, ajeno)])
    for p in (sin_pasar, ajeno):
        db_session.refresh(p)
        assert p.final_average is None


def test_archivo_dry_run_no_escribe(db_session, expediente, cc):
    from itcj2.apps.titulatec.models import OfficialAverage

    proc = expediente()
    control = _control(db_session, proc)

    res = _carga(db_session, [(control, "85")], cc, dry_run=True)

    assert _controles(res, "applied") == [control]
    db_session.refresh(proc)
    assert proc.final_average is None
    assert db_session.get(OfficialAverage, control) is None
