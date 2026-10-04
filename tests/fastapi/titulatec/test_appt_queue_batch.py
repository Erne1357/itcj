"""La cola de «Citas de cotejo» sin consultas por candidato (spec 2026-10-04-
titulatec-paginacion-design.md §8, Tarea 7).

Sin paginar y sin cambiar listas, orden, contadores ni UI: solo mapas en lote
en vez de N+1. El criterio de aceptación es la EQUIVALENCIA, así que este
archivo lleva un ORÁCULO congelado -- la copia literal del algoritmo por fila
que existía antes de la Tarea 7 (`_viejo_*`) -- y compara contra él:

* `DocumentService.initial_docs_approved_map` contra el `initial_docs_all_
  approved` por código de siempre (licenciatura, posgrado completo, posgrado
  R-G con extras faltantes tras la fase 1, R-G con la fase 1 abierta, extra
  rechazado, documento base rechazado, sin carrera).
* `SelfBookingService.cancellations_map` / `blocked_map` contra el COUNT por
  proceso (las del encargado no cuentan).
* Los cinco cubos de `_shell_ctx` (ids, ORDEN, contadores, `cancelaciones`
  de «Requieren», `bloqueado` de «Fase 02 rechazada») contra el oráculo, y
  contra los `list_*` públicos llamados por separado.
* Presupuesto de consultas de `_shell_ctx` IGUAL con 3 y con 30 candidatos por
  clase (modo día y modo resultados, este con `_appt_rows`).
* `?selected=` sigue validándose contra las listas COMPLETAS.

Todas las consultas van acotadas a las carreras del escenario
(`allowed_program_ids`): la base de pruebas puede traer otros procesos.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from tests.fastapi.titulatec.conftest import INITIAL_DOC_TYPES, POSGRADO_DOC_TYPES

_BASE = ("birth_certificate", "high_school_cert", "curp")
_EXTRAS = ("professional_license", "degree_title", "postgrad_authorization", "efirma_sat")
_T0 = datetime(2020, 1, 1, 8, 0)


# ---------------------------------------------------------------------------
# Oráculo congelado: el algoritmo POR FILA de antes de la Tarea 7, copiado
# tal cual (no llama a nada que la Tarea 7 haya tocado).
# ---------------------------------------------------------------------------
def _viejo_docs_ok(db, proc) -> bool:
    from itcj2.apps.titulatec.models import Document
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    codes = DocumentService.initial_doc_types_for_id(db, proc.id)
    excused = None
    for code in codes:
        doc = db.query(Document).filter_by(process_id=proc.id, type_code=code).first()
        if doc is None and code in DocumentService.POSGRADO_EXTRA_DOCS:
            if excused is None:
                n = PhaseService.phase_number_for_code(db, "initial_docs")
                excused = DocumentService.excused_initial_docs(
                    proc, frozenset(), initial_docs_phase=n)
            if code in excused:
                continue
            return False
        if not doc or doc.review_status != "approved":
            return False
    return True


def _viejo_cancelaciones(db, proc) -> int:
    from itcj2.apps.titulatec.models import ReviewAppointment
    return (db.query(ReviewAppointment)
            .filter(ReviewAppointment.process_id == proc.id,
                    ReviewAppointment.status == "cancelled",
                    ReviewAppointment.cancelled_by_id == proc.student_id)
            .count())


def _viejo_cubos(db, allowed) -> dict:
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.clearance_gate import ClearanceGate
    from itcj2.config import get_settings

    tope = get_settings().TITULATEC_SELF_CANCEL_MAX
    base = AppointmentService._unscheduled_query(db, program_id=None,
                                                 allowed_program_ids=allowed)
    liberados = [p for p in base.filter(ClearanceGate.released_clause())
                 .order_by(TitulationProcess.created_at).all() if _viejo_docs_ok(db, p)]
    faltan = [p for p in base.filter(ClearanceGate.not_released_clause())
              .order_by(TitulationProcess.created_at).all() if _viejo_docs_ok(db, p)]
    rechazados = AppointmentService.list_rejected_cotejo_processes(
        db, allowed_program_ids=allowed)
    return {
        "pending": [p.id for p in liberados if _viejo_cancelaciones(db, p) < tope],
        "bloqueados": [p.id for p in liberados if _viejo_cancelaciones(db, p) >= tope],
        "cancelaciones": {p.id: _viejo_cancelaciones(db, p) for p in liberados
                          if _viejo_cancelaciones(db, p) >= tope},
        "liberaciones": [p.id for p in faltan],
        "reagendar": [p.id for p in AppointmentService.list_reschedule_processes(
            db, allowed_program_ids=allowed)],
        "rechazados": [p.id for p in rechazados],
        "rechazado_bloqueado": {p.id: _viejo_cancelaciones(db, p) >= tope
                                for p in rechazados},
    }


# ---------------------------------------------------------------------------
# Escenario
# ---------------------------------------------------------------------------
@pytest.fixture()
def fab(seed_phase_defs, seed_document_types, make_program, make_cohort,
        make_student, make_process, make_document, make_appointment,
        make_officer, make_survey_review, db_session):
    """Fábrica de procesos por CLASE, con `created_at` estrictamente creciente
    (el orden de los cubos es `created_at`: con empates el orden sería el que
    Postgres quiera y la equivalencia de ORDEN no probaría nada)."""
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.models import ProcessPhase

    seed_phase_defs()
    seed_document_types(types=INITIAL_DOC_TYPES + POSGRADO_DOC_TYPES)
    lic = make_program("Ing. Lote Cola T7")
    pos = make_program("Maestria Lote Cola T7", level="maestria")
    cohort = make_cohort()
    officer, _ = make_officer([lic, pos])
    reloj = {"t": _T0}

    def _docs(proc, codes, estado="approved"):
        for code in codes:
            make_document(proc, type_code=code, review_status=estado)

    def _cancelar(proc, n, por=None):
        for i in range(n):
            a = make_appointment(proc, status="cancelled", is_current=False,
                                 attempt_no=i + 1)
            a.cancelled_by_id = por if por is not None else proc.student_id
        db_session.flush()

    def _fase2(proc, estado):
        fila = (db_session.query(ProcessPhase)
                .filter_by(process_id=proc.id, phase_number=PhaseService.PHASE_COTEJO)
                .first())
        fila.status = estado
        db_session.flush()

    def make(clase):
        program = pos if clase.startswith("pos") else lic
        if clase == "sin_carrera":
            program = None
        fase = 1 if clase == "pos_rg_fase1" else 2
        student = make_student(first_name="T7", last_name=clase.upper())
        proc = make_process(student, cohort=cohort, program=program, current_phase=fase)
        reloj["t"] += timedelta(minutes=1)
        proc.created_at = reloj["t"]
        encuesta = "approved"
        if clase in ("lic_ok", "lic_bloq_por_encargado", "sin_carrera"):
            _docs(proc, _BASE)
        elif clase == "pos_completo":
            _docs(proc, _BASE + _EXTRAS)
        elif clase in ("pos_rg", "pos_rg_fase1"):
            _docs(proc, _BASE)
        elif clase == "pos_rg_sin_encuesta":
            _docs(proc, _BASE)
            encuesta = None
        elif clase == "pos_extra_rechazado":
            _docs(proc, _BASE + _EXTRAS[:2])
            make_document(proc, type_code=_EXTRAS[2], review_status="rejected")
        elif clase == "lic_doc_rechazado":
            _docs(proc, _BASE[:2])
            make_document(proc, type_code=_BASE[2], review_status="rejected")
        elif clase == "bloqueado":
            _docs(proc, _BASE)
            _cancelar(proc, 3)
        elif clase == "sin_encuesta":
            _docs(proc, _BASE)
            encuesta = None
        elif clase == "encuesta_en_revision":
            _docs(proc, _BASE)
            encuesta = "in_review"
        elif clase == "no_show":
            _docs(proc, _BASE)
            make_appointment(proc, status="no_show", is_current=True)
        elif clase == "rechazado":
            _docs(proc, _BASE)
            _fase2(proc, "rejected")
        elif clase == "rechazado_bloqueado":
            _docs(proc, _BASE)
            _cancelar(proc, 3)
            _fase2(proc, "rejected")
        elif clase == "sin_docs":
            pass
        else:  # pragma: no cover
            raise AssertionError(clase)
        if clase == "lic_bloq_por_encargado":
            _cancelar(proc, 3, por=officer.id)
        if encuesta is not None:
            make_survey_review(proc, status=encuesta)
        db_session.flush()
        return proc

    return {"make": make, "lic": lic, "pos": pos, "officer": officer,
            "allowed": {lic.id, pos.id}}


CLASES_MIXTAS = (
    "lic_ok", "pos_completo", "pos_rg", "pos_rg_fase1", "pos_extra_rechazado",
    "lic_doc_rechazado", "bloqueado", "lic_bloq_por_encargado", "sin_encuesta",
    "encuesta_en_revision", "pos_rg_sin_encuesta", "no_show", "rechazado",
    "rechazado_bloqueado", "sin_docs",
)


@pytest.fixture()
def mixto(fab):
    """Dos de cada clase, intercaladas (el orden por `created_at` cruza
    clases y carreras)."""
    procs = {}
    for _ in range(2):
        for clase in CLASES_MIXTAS:
            procs.setdefault(clase, []).append(fab["make"](clase))
    return {**fab, "procs": procs}


def _ids(filas):
    return [f["process_id"] for f in filas]


# ---------------------------------------------------------------------------
# 1. Los mapas equivalen al cálculo por fila
# ---------------------------------------------------------------------------
def test_mapa_docs_equivale_a_all_approved(db_session, fab):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    esperado = {
        "lic_ok": True, "pos_completo": True, "pos_rg": True,
        "pos_rg_fase1": False, "pos_extra_rechazado": False,
        "lic_doc_rechazado": False, "sin_carrera": True, "sin_docs": False,
    }
    procs = {clase: fab["make"](clase) for clase in esperado}
    mapa = DocumentService.initial_docs_approved_map(db_session, list(procs.values()))
    for clase, proc in procs.items():
        viejo = _viejo_docs_ok(db_session, proc)
        assert viejo is esperado[clase], (clase, "el escenario no prueba lo que dice")
        assert mapa[proc.id] is viejo, clase
        # La firma de siempre delega en el mapa y dice lo mismo.
        assert DocumentService.initial_docs_all_approved(db_session, proc.id) is viejo, clase
    # `codes` explícito se respeta: con solo los 3 base, el R-G de fase 1 pasa.
    p = procs["pos_rg_fase1"]
    assert DocumentService.initial_docs_all_approved(db_session, p.id, codes=_BASE) is True
    assert DocumentService.initial_docs_approved_map(db_session, []) == {}


def test_all_approved_proceso_inexistente_no_revienta(db_session, fab):
    from itcj2.apps.titulatec.services.document_service import DocumentService

    assert DocumentService.initial_docs_all_approved(db_session, 987654321) is False
    assert DocumentService.initial_docs_all_approved(db_session, 987654321, codes=()) is True


def test_cancellations_map_equivale(db_session, fab):
    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

    procs = [fab["make"](c) for c in ("bloqueado", "lic_bloq_por_encargado", "lic_ok",
                                      "rechazado_bloqueado")]
    cuentas = SelfBookingService.cancellations_map(db_session, procs)
    bloq = SelfBookingService.blocked_map(db_session, procs)
    assert [cuentas[p.id] for p in procs] == [3, 0, 0, 3]
    for p in procs:
        assert cuentas[p.id] == _viejo_cancelaciones(db_session, p)
        assert SelfBookingService.cancellations(db_session, p) == cuentas[p.id]
        assert bloq[p.id] is (cuentas[p.id] >= 3)
        assert SelfBookingService.is_blocked_by_cancellations(db_session, p) is bloq[p.id]
    assert SelfBookingService.cancellations(db_session, None) == 0
    assert SelfBookingService.cancellations_map(db_session, []) == {}


# ---------------------------------------------------------------------------
# 2. Los cinco cubos, idénticos
# ---------------------------------------------------------------------------
def test_cola_identica_antes_y_despues(db_session, mixto):
    from itcj2.apps.titulatec.pages.appointments import _shell_ctx
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    allowed = mixto["allowed"]
    viejo = _viejo_cubos(db_session, allowed)
    pr = mixto["procs"]

    # El escenario de verdad reparte: ningún cubo vacío por accidente.
    assert viejo["pending"] == [p.id for p in sorted(
        pr["lic_ok"] + pr["pos_completo"] + pr["pos_rg"] + pr["lic_bloq_por_encargado"],
        key=lambda p: p.created_at)]
    assert set(viejo["bloqueados"]) == {p.id for p in pr["bloqueado"]}
    assert set(viejo["liberaciones"]) == {p.id for p in pr["sin_encuesta"]
                                          + pr["encuesta_en_revision"]
                                          + pr["pos_rg_sin_encuesta"]}
    assert set(viejo["reagendar"]) == {p.id for p in pr["no_show"]}
    assert set(viejo["rechazados"]) == {p.id for p in pr["rechazado"]
                                        + pr["rechazado_bloqueado"]}

    ctx = _shell_ctx(db_session, user_id=mixto["officer"].id)
    assert _ids(ctx["pending"]) == viejo["pending"]
    assert ctx["pending_count"] == len(viejo["pending"])
    assert _ids(ctx["bloqueados"]) == viejo["bloqueados"]
    assert ctx["bloqueados_count"] == len(viejo["bloqueados"])
    assert {f["process_id"]: f["cancelaciones"] for f in ctx["bloqueados"]} == \
        viejo["cancelaciones"]
    assert _ids(ctx["liberaciones"]) == viejo["liberaciones"]
    assert ctx["liberaciones_count"] == len(viejo["liberaciones"])
    assert _ids(ctx["reagendar"]) == viejo["reagendar"]
    assert ctx["reagendar_count"] == len(viejo["reagendar"])
    assert _ids(ctx["rechazados"]) == viejo["rechazados"]
    assert ctx["rechazados_count"] == len(viejo["rechazados"])
    assert {f["process_id"]: f["bloqueado"] for f in ctx["rechazados"]} == \
        viejo["rechazado_bloqueado"]

    # Los `list_*` públicos (firmas intactas) dicen lo mismo, por separado.
    kw = {"allowed_program_ids": allowed}
    assert [p.id for p in AppointmentService.list_pending_processes(db_session, **kw)] \
        == viejo["pending"]
    assert [p.id for p in AppointmentService.list_self_blocked_processes(db_session, **kw)] \
        == viejo["bloqueados"]
    assert [p.id for p in AppointmentService.list_missing_clearance_processes(
        db_session, **kw)] == viejo["liberaciones"]

    # Y `queue_candidates` es el cálculo único del que salen los tres.
    cola = AppointmentService.queue_candidates(db_session, allowed_program_ids=allowed)
    assert [p.id for p in cola["pending"]] == viejo["pending"]
    assert [p.id for p in cola["blocked"]] == viejo["bloqueados"]
    assert [p.id for p in cola["missing_clearance"]] == viejo["liberaciones"]
    assert all(cola["docs_ok"][pid] for pid in viejo["pending"] + viejo["bloqueados"])
    assert all(cola["blocked_map"][pid] for pid in viejo["bloqueados"])
    assert not any(cola["blocked_map"][pid] for pid in viejo["pending"])

    # Filtro por carrera: el mismo reparto que el oráculo restringido.
    solo_pos = {mixto["pos"].id}
    viejo_pos = _viejo_cubos(db_session, solo_pos)
    assert [p.id for p in AppointmentService.list_pending_processes(
        db_session, allowed_program_ids=allowed, program_id=mixto["pos"].id)] == \
        viejo_pos["pending"]
    assert AppointmentService.queue_candidates(db_session, allowed_program_ids=set()) == {
        "pending": [], "blocked": [], "missing_clearance": [],
        "docs_ok": {}, "blocked_map": {}, "cancellations": {}}


def test_selected_sigue_validando_contra_listas_completas(db_session, mixto):
    from itcj2.apps.titulatec.pages.appointments import _shell_ctx

    uid = mixto["officer"].id
    pr = mixto["procs"]
    for clase in ("lic_ok", "pos_rg", "bloqueado", "rechazado", "rechazado_bloqueado"):
        pid = pr[clase][1].id
        ctx = _shell_ctx(db_session, user_id=uid, selected_id=pid)
        assert ctx["selected_id"] == pid, clase
        assert ctx["detail"] is not None, clase
    # Fuera de `visibles`: liberaciones pendientes, docs incompletos, R-G fase 1.
    for clase in ("sin_encuesta", "lic_doc_rechazado", "pos_rg_fase1", "sin_docs"):
        ctx = _shell_ctx(db_session, user_id=uid, selected_id=pr[clase][0].id)
        assert ctx["selected_id"] is None, clase
        assert ctx["detail"] is None, clase


# ---------------------------------------------------------------------------
# 3. Presupuesto de consultas fijo
# ---------------------------------------------------------------------------
CLASES_LOTE = ("lic_ok", "pos_rg", "pos_completo", "bloqueado", "sin_encuesta",
               "pos_rg_sin_encuesta", "no_show", "rechazado_bloqueado", "lic_doc_rechazado")


def _contar(db_session, fn):
    sentencias = []

    def _ver(_conn, _cursor, statement, *_a):
        sentencias.append(statement)

    conn = db_session.connection()
    event.listen(conn, "before_cursor_execute", _ver)
    try:
        fn()
    finally:
        event.remove(conn, "before_cursor_execute", _ver)
    return len(sentencias)


def _medir(db_session, fab, nuevos, total):
    from itcj2.apps.titulatec.pages.appointments import _shell_ctx

    for _ in range(nuevos):
        for clase in CLASES_LOTE:
            fab["make"](clase)
    uid = fab["officer"].id
    # Una pasada de calentamiento: lo que se cachea la primera vez (alcance
    # del encargado, catálogos) no es por candidato y no debe sesgar la cuenta.
    _shell_ctx(db_session, user_id=uid)
    db_session.expire_all()
    dia = _contar(db_session, lambda: _shell_ctx(db_session, user_id=uid))
    db_session.expire_all()
    res = _contar(db_session, lambda: _shell_ctx(db_session, user_id=uid,
                                                 estado="no_show"))
    ctx = _shell_ctx(db_session, user_id=uid, estado="no_show")
    assert len(ctx["rows"]) == total
    assert ctx["pending_count"] == 3 * total and ctx["bloqueados_count"] == total
    assert ctx["liberaciones_count"] == 2 * total and ctx["rechazados_count"] == total
    return dia, res


def test_consultas_de_la_cola_fijas_con_3_y_con_30(db_session, fab):
    tres = _medir(db_session, fab, 3, 3)
    # Segunda tanda en la MISMA base: 27 más de cada clase (30 en total).
    treinta = _medir(db_session, fab, 27, 30)
    print(f"\n[T7] consultas _shell_ctx (dia, resultados): 3 -> {tres}, 30 -> {treinta}")
    assert tres == treinta
