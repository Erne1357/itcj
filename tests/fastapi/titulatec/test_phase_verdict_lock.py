"""Dictamen de fase serializado (Ruling R14, 2026-10-15, tras el PR #84).

Dos carreras que quedaban abiertas fuera de la fase de cotejo (R9 solo
bloqueaba la fila del proceso al liberar la fase 2):

* **Aprobar dos veces.** Dos revisores aprueban a la vez los últimos documentos
  de la fase 1: los dos pasan `can_transition` y el auto-avance de
  `pages/documents.py::_cuerpo_review` llama `approve_phase(1)` dos veces --
  eventos, avisos y correos duplicados.
* **Rechazar sobre una fase ya liberada.** `reject_phase` no bloqueaba: un
  rechazo concurrente con la aprobación de la misma fase fijaba
  `current_phase` con datos viejos y regresaba el proceso.

Arreglo: `approve_phase` y `reject_phase` bloquean SIEMPRE la fila del proceso
(`FOR NO KEY UPDATE` + `populate_existing`, un helper privado único) ANTES de
`assert_can_transition`, que así revalida sobre el estado ya bloqueado;
`approve_phase` además se niega sobre una `ProcessPhase` ya `approved`; y el
auto-avance de la bandeja atrapa el `ValueError` del perdedor.

Las carreras se reproducen de forma DETERMINISTA, sin hilos: tras una
aprobación real, `set_committed_value` devuelve al objeto en memoria la fase que
el perdedor había leído antes de que el ganador hiciera commit. Sin el bloqueo +
relectura, la guarda corre sobre ese dato viejo y pasa.

La base de dev es compartida y trae datos reales: todo se siembra con las
fábricas del conftest y nada afirma totales de una tabla.
"""
from __future__ import annotations

import unicodedata

import pytest
from sqlalchemy import event
from sqlalchemy.orm.attributes import set_committed_value

from itcj2.apps.titulatec.services.phase_service import PhaseService

_YA_APROBADA = "Esa fase ya fue aprobada."
_FASE_EN_CURSO = "Solo puedes actuar sobre la fase en curso"
REVIEW_PERMS = ("titulatec.document.api.approve", "titulatec.document.api.reject")


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture()
def espias(monkeypatch):
    """Aviso in-app y los dos correos de dictamen de fase, registrados en vez
    de escritos: si el perdedor llegara hasta ahí, aparecería aquí."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    avisos, correos = [], []
    monkeypatch.setattr("itcj2.apps.titulatec.services.notify.notify_student",
                        lambda db, student_id, **kw: avisos.append(kw["type"]))
    monkeypatch.setattr(StudentMail, "phase_approved",
                        staticmethod(lambda db, process, **kw:
                                     correos.append(("phase_approved", kw)) or True))
    monkeypatch.setattr(StudentMail, "phase_rejected",
                        staticmethod(lambda db, process, **kw:
                                     correos.append(("phase_rejected", kw)) or True))
    return {"avisos": avisos, "correos": correos}


@pytest.fixture()
def esc(db_session, seed_phase_defs, make_cohort, make_student, make_process, make_user,
        espias):
    """Proceso `active` en la fase que pida el test. La convocatoria no tiene
    requisitos de cotejo y el no adeudo nace `cleared`: la compuerta de la
    fase 2 deja pasar, así que lo único que puede negar es la guarda."""
    seed_phase_defs()
    cohort = make_cohort()
    revisor = make_user(first_name="REVISOR", last_name="GANADOR")
    otro = make_user(first_name="REVISOR", last_name="PERDEDOR")

    def _build(current_phase=1):
        return make_process(make_student(), cohort=cohort, current_phase=current_phase)

    return {"build": _build, "revisor": revisor, "otro": otro, **espias}


def _eventos(db, process_id, event_type):
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db.query(ProcessEvent)
            .filter_by(process_id=process_id, event_type=event_type).all())


def _releer(db, process_id):
    """`flush()` ANTES de expirar: un cambio que el service dejó en memoria
    antes de lanzar se vería aquí (expirar a secas lo descartaría y la negativa
    pasaría sin probar nada). Devuelve (proceso, {fase: estado})."""
    from itcj2.apps.titulatec.models import ProcessPhase, TitulationProcess
    db.flush()
    db.expire_all()
    proc = db.get(TitulationProcess, process_id)
    fases = {p.phase_number: p.status
             for p in db.query(ProcessPhase).filter_by(process_id=process_id).all()}
    return proc, fases


def _contar(db_session, fn):
    """Sentencias SQL que emite `fn`, en orden (sin las del espejo de bitácora)."""
    sentencias = []

    def _ver(_conn, _cursor, statement, *_a):
        sentencias.append(statement)

    db_session.flush()
    conn = db_session.connection()
    event.listen(conn, "before_cursor_execute", _ver)
    try:
        resultado = fn()
    finally:
        event.remove(conn, "before_cursor_execute", _ver)
    return resultado, [s for s in sentencias if "titulatec_audit_log" not in s]


def _primera(sentencias, pred):
    return next((i for i, s in enumerate(sentencias) if pred(s)), None)


def _lock_del_proceso(s):
    return "FROM titulatec_processes" in s and "FOR NO KEY UPDATE" in s


def _es_ascii(msg: str) -> bool:
    return msg == unicodedata.normalize("NFKD", msg).encode("ascii", "ignore").decode()


# ---------------------------------------------------------------------------
# El perdedor de la carrera: proceso viejo en memoria
# ---------------------------------------------------------------------------
class TestElPerdedorDeLaCarrera:
    @pytest.mark.parametrize("fase", [1, 2])
    def test_la_segunda_aprobacion_levanta_y_no_escribe_nada(self, db_session, esc, fase):
        """El ganador aprobó y avanzó; el perdedor todavía ve la fase vieja.
        Sin el bloqueo + relectura, su guarda pasa sobre ese dato y duplica
        evento, aviso y correo."""
        proc = esc["build"](current_phase=fase)
        PhaseService.approve_phase(db_session, proc, fase, reviewer_id=esc["revisor"].id)
        assert proc.current_phase == fase + 1
        assert (len(esc["avisos"]), len(esc["correos"])) == (1, 1)

        set_committed_value(proc, "current_phase", fase)     # lo que leyó el perdedor

        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, proc, fase, reviewer_id=esc["otro"].id)

        # La guarda de transición, ya sobre la fila releída -- no la defensa de
        # `_ensure_phase`: es el bloqueo el que lo detiene.
        assert str(exc.value).startswith(_FASE_EN_CURSO), str(exc.value)
        assert _es_ascii(str(exc.value))
        fresco, fases = _releer(db_session, proc.id)
        assert fresco.current_phase == fase + 1
        assert fases[fase] == "approved"
        assert len(_eventos(db_session, proc.id, "phase_approved")) == 1
        assert (len(esc["avisos"]), len(esc["correos"])) == (1, 1), (
            esc["avisos"], esc["correos"])

    @pytest.mark.parametrize("fase", [1, 2])
    def test_el_rechazo_tardio_no_regresa_una_fase_ya_liberada(self, db_session, esc, fase):
        """Antes `reject_phase` fijaba `current_phase` con el dato viejo: el
        proceso volvía a una fase ya aprobada, con evento, aviso y correo."""
        proc = esc["build"](current_phase=fase)
        PhaseService.approve_phase(db_session, proc, fase, reviewer_id=esc["revisor"].id)

        set_committed_value(proc, "current_phase", fase)

        with pytest.raises(ValueError) as exc:
            PhaseService.reject_phase(db_session, proc, fase, reviewer_id=esc["otro"].id,
                                      reason="Le falta la firma")

        assert str(exc.value).startswith(_FASE_EN_CURSO), str(exc.value)
        fresco, fases = _releer(db_session, proc.id)
        assert fresco.current_phase == fase + 1
        assert fases[fase] == "approved"
        assert fases[fase + 1] == "in_progress"
        assert _eventos(db_session, proc.id, "phase_rejected") == []
        assert esc["avisos"] == ["PHASE_APPROVED"]
        assert [k for k, _ in esc["correos"]] == ["phase_approved"]

    def test_control_sin_carrera_el_rechazo_si_pasa(self, db_session, esc):
        """Positivo del mismo actor: el bloqueo no puede ser un «no» universal."""
        proc = esc["build"](current_phase=1)

        PhaseService.reject_phase(db_session, proc, 1, reviewer_id=esc["otro"].id,
                                  reason="Le falta la firma")

        fresco, fases = _releer(db_session, proc.id)
        assert (fresco.current_phase, fases[1]) == (1, "rejected")
        assert esc["avisos"] == ["PHASE_REJECTED"]


# ---------------------------------------------------------------------------
# Defensa: la ProcessPhase ya aprobada (sin consulta extra)
# ---------------------------------------------------------------------------
class TestFaseYaAprobada:
    @pytest.mark.parametrize("fase", [1, 2])
    def test_aprobar_una_fase_ya_aprobada_levanta_sin_escribir(
            self, db_session, esc, make_appointment, fase):
        """Dato incoherente (la `ProcessPhase` de la fase en curso ya está
        `approved`): la guarda de transición pasa, pero aprobarla otra vez
        duplicaría el avance. Se niega antes de escribir -- en la fase 2,
        también antes del auto-cierre de la cita."""
        from itcj2.apps.titulatec.models import ProcessPhase

        proc = esc["build"](current_phase=fase)
        cita = make_appointment(proc, status="in_progress") if fase == 2 else None
        (db_session.query(ProcessPhase)
         .filter_by(process_id=proc.id, phase_number=fase)
         .update({"status": "approved"}))
        db_session.flush()

        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, proc, fase, reviewer_id=esc["revisor"].id)

        assert str(exc.value) == _YA_APROBADA
        assert _es_ascii(_YA_APROBADA)
        fresco, fases = _releer(db_session, proc.id)
        assert fresco.current_phase == fase
        assert fases[fase + 1] == "pending"
        assert _eventos(db_session, proc.id, "phase_approved") == []
        assert (esc["avisos"], esc["correos"]) == ([], [])
        if cita is not None:
            db_session.refresh(cita)
            assert cita.status == "in_progress"
            assert _eventos(db_session, proc.id, "appointment_attended") == []


# ---------------------------------------------------------------------------
# Orden del SQL: el bloqueo va primero
# ---------------------------------------------------------------------------
class TestOrdenDelBloqueo:
    @pytest.mark.parametrize("fase", [1, 2])
    @pytest.mark.parametrize("dictamen", ["approve", "reject"])
    def test_bloquea_el_proceso_antes_de_validar_y_de_leer_las_fases(
            self, db_session, esc, fase, dictamen):
        proc = esc["build"](current_phase=fase)
        revisor = esc["revisor"].id
        if dictamen == "approve":
            def fn():
                return PhaseService.approve_phase(db_session, proc, fase, reviewer_id=revisor)
        else:
            def fn():
                return PhaseService.reject_phase(db_session, proc, fase, reviewer_id=revisor,
                                                 reason="Le falta la firma")

        _, sql = _contar(db_session, fn)

        bloqueo = _primera(sql, _lock_del_proceso)
        catalogo = _primera(sql, lambda s: "FROM titulatec_phase_definitions" in s)
        fases = _primera(sql, lambda s: "FROM titulatec_process_phases" in s)
        assert bloqueo is not None, sql
        # Antes de `assert_can_transition` (que lee el catálogo de fases)...
        assert catalogo is not None and bloqueo < catalogo, sql
        # ...y antes de leer las fases del proceso.
        assert fases is not None and bloqueo < fases, sql
        # Un solo bloqueo por dictamen: el helper es único.
        assert sum(1 for s in sql if _lock_del_proceso(s)) == 1, sql


# ---------------------------------------------------------------------------
# El auto-avance 1->2 de la bandeja: perder la carrera no es un 500
# ---------------------------------------------------------------------------
def _bandeja(seed_document_types, make_cohort, make_student, make_process,
             make_document):
    """Fase 1 con dos documentos aprobados y el tercero por evaluar: aprobar
    ese tercero dispara el auto-avance."""
    seed_document_types()
    proc = make_process(make_student(), cohort=make_cohort(), current_phase=1)
    for code, st in zip(("birth_certificate", "high_school_cert", "curp"),
                        ("approved", "approved", "pending")):
        make_document(proc, type_code=code, review_status=st)
    return proc


def _estado_doc(db, process_id, code="curp"):
    from itcj2.apps.titulatec.models import Document
    db.flush()
    db.expire_all()
    return db.query(Document.review_status).filter_by(
        process_id=process_id, type_code=code).scalar()


class TestAutoAvanceDeLaBandeja:
    def test_si_otro_revisor_ya_avanzo_la_fase_responde_200_sin_duplicar(
            self, db_session, esc, seed_document_types, make_cohort, make_student,
            make_process, make_document, make_head, client_as, monkeypatch):
        """La carrera real, determinista: entre el `can_transition` de esta
        petición y su `approve_phase`, el auto-avance del otro revisor gana el
        bloqueo y hace commit. Esta petición ya guardó su dictamen; perder el
        avance = otro ya avanzó, no es error."""
        from tests.fastapi.titulatec.conftest import HEAD_PERMS

        proc = _bandeja(seed_document_types, make_cohort, make_student, make_process,
                        make_document)
        jefa = make_head(perm_codes=HEAD_PERMS + REVIEW_PERMS)
        real = PhaseService.approve_phase
        intentos = []

        def _carrera(db, process, n, reviewer_id):
            real(db, process, n, esc["otro"].id)                 # el ganador
            set_committed_value(process, "current_phase", n)     # lo que leyó esta petición
            intentos.append(n)
            return real(db, process, n, reviewer_id)

        monkeypatch.setattr(PhaseService, "approve_phase", staticmethod(_carrera))

        resp = client_as(jefa).post(
            "/titulatec/admin/documents/%d/document/review" % proc.id,
            data={"type_code": "curp", "action": "approve"})

        assert resp.status_code == 200, resp.text[:400]
        assert intentos == [1]
        assert _estado_doc(db_session, proc.id) == "approved"
        fresco, fases = _releer(db_session, proc.id)
        assert (fresco.current_phase, fases[1], fases[2]) == (2, "approved", "in_progress")
        assert len(_eventos(db_session, proc.id, "phase_approved")) == 1
        assert esc["avisos"].count("PHASE_APPROVED") == 1
        assert [k for k, _ in esc["correos"]] == ["phase_approved"]

    def test_un_approve_phase_que_levanta_no_tumba_el_dictamen(
            self, db_session, esc, seed_document_types, make_cohort, make_student,
            make_process, make_document, make_head, client_as, monkeypatch):
        from tests.fastapi.titulatec.conftest import HEAD_PERMS

        proc = _bandeja(seed_document_types, make_cohort, make_student, make_process,
                        make_document)
        jefa = make_head(perm_codes=HEAD_PERMS + REVIEW_PERMS)

        def _pierde(db, process, n, reviewer_id):
            raise ValueError(_YA_APROBADA)

        monkeypatch.setattr(PhaseService, "approve_phase", staticmethod(_pierde))

        resp = client_as(jefa).post(
            "/titulatec/admin/documents/%d/document/review" % proc.id,
            data={"type_code": "curp", "action": "approve"})

        assert resp.status_code == 200, resp.text[:400]
        assert "X-Tt-Error" not in resp.headers
        assert _estado_doc(db_session, proc.id) == "approved"

    def test_control_sin_carrera_auto_avanza(
            self, db_session, esc, seed_document_types, make_cohort, make_student,
            make_process, make_document, make_head, client_as):
        """Positivo del mismo actor sobre la misma ruta."""
        from tests.fastapi.titulatec.conftest import HEAD_PERMS

        proc = _bandeja(seed_document_types, make_cohort, make_student, make_process,
                        make_document)
        jefa = make_head(perm_codes=HEAD_PERMS + REVIEW_PERMS)

        resp = client_as(jefa).post(
            "/titulatec/admin/documents/%d/document/review" % proc.id,
            data={"type_code": "curp", "action": "approve"})

        assert resp.status_code == 200, resp.text[:400]
        fresco, fases = _releer(db_session, proc.id)
        assert (fresco.current_phase, fases[1]) == (2, "approved")
        assert len(_eventos(db_session, proc.id, "phase_approved")) == 1
