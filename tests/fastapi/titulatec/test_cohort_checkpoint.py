"""Cerrar una convocatoria solo pausa a quien no pasó el primer checkpoint (D12).

Checkpoint 1 = el pago en Caja durante la cita de cotejo = fase
`review_appointment` (2) aprobada. Spec 2026-10-22 fase 5, §4 (D12) y §6.5.
"""
import pytest

from tests.fastapi.titulatec.conftest import audit_query

from itcj2.apps.titulatec.models import ProcessEvent, ProcessPhase
from itcj2.apps.titulatec.services.cohort_service import CohortService
from itcj2.apps.titulatec.services.process_service import ProcessService

pytestmark = pytest.mark.usefixtures("audit_mark")


def _cerrar(db, cohort, jefa):
    return CohortService.set_window(db, cohort.id, opens_at=cohort.opens_at,
                                    closes_at=cohort.closes_at, status="closed",
                                    actor_id=jefa.id)


@pytest.fixture()
def escenario(db_session, seed_phase_defs, make_cohort, make_student, make_process,
              make_head):
    seed_phase_defs()
    jefa = make_head()
    cohort = make_cohort(status="open")
    p1 = make_process(make_student(), cohort=cohort, current_phase=1)
    p2 = make_process(make_student(), cohort=cohort, current_phase=2)  # sin aprobar
    p3 = make_process(make_student(), cohort=cohort, current_phase=3)
    p5 = make_process(make_student(), cohort=cohort, current_phase=5)
    revocado = make_process(make_student(), cohort=cohort, current_phase=1,
                            status="cancelled")
    return jefa, cohort, p1, p2, p3, p5, revocado


def test_cerrar_solo_pausa_a_quien_no_paso_el_primer_checkpoint(db_session, escenario):
    jefa, cohort, p1, p2, p3, p5, revocado = escenario

    res = _cerrar(db_session, cohort, jefa)

    for p in (p1, p2, p3, p5, revocado):
        db_session.refresh(p)
    assert res == {"paused": 2, "resumed": 0}
    assert (p1.status, p2.status) == ("on_hold", "on_hold")
    assert (p3.status, p5.status) == ("active", "active")
    assert revocado.status == "cancelled"

    pausados = {e.process_id for e in db_session.query(ProcessEvent)
                .filter(ProcessEvent.process_id.in_([p.id for p in
                        (p1, p2, p3, p5, revocado)]),
                        ProcessEvent.event_type == "process_paused")}
    assert pausados == {p1.id, p2.id}

    fila = (audit_query(db_session)
            .filter_by(action="cohort.window_changed", entity_id=cohort.id).one())
    assert fila.payload["paused"] == 2


def test_reabrir_reanuda_solo_los_pausados(db_session, escenario):
    jefa, cohort, p1, p2, p3, p5, revocado = escenario
    _cerrar(db_session, cohort, jefa)

    res = CohortService.set_window(db_session, cohort.id, opens_at=cohort.opens_at,
                                   closes_at=cohort.closes_at, status="open",
                                   actor_id=jefa.id)

    for p in (p1, p2, p3, p5, revocado):
        db_session.refresh(p)
    assert res["resumed"] >= 2
    assert (p1.status, p2.status, p3.status, p5.status) == ("active",) * 4
    assert revocado.status == "cancelled"
    reanudados = {e.process_id for e in db_session.query(ProcessEvent)
                  .filter(ProcessEvent.process_id.in_([p.id for p in
                          (p1, p2, p3, p5, revocado)]),
                          ProcessEvent.event_type == "process_resumed")}
    assert reanudados == {p1.id, p2.id}


def test_el_predicado_y_su_gemela_en_python(db_session, escenario):
    _, _, p1, p2, p3, p5, _ = escenario
    assert [ProcessService.passed_first_checkpoint(db_session, p)
            for p in (p1, p2, p3, p5)] == [False, False, True, True]


def test_sin_la_fase_en_el_catalogo_falla_cerrado(db_session, monkeypatch, escenario):
    """Fase ausente del catalogo -> predicado falso -> se pausa a todos como antes."""
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    jefa, cohort, p1, p2, p3, p5, _ = escenario
    monkeypatch.setattr(PhaseService, "phase_number_for_code",
                        staticmethod(lambda db, code: None))

    res = _cerrar(db_session, cohort, jefa)

    assert res["paused"] == 4
    assert not ProcessService.passed_first_checkpoint(db_session, p5)


def test_aprobada_la_fase_de_cotejo_el_proceso_ya_no_se_pausa(db_session, escenario):
    """El predicado mira ProcessPhase.approved, no current_phase."""
    jefa, cohort, p1, p2, *_ = escenario
    fase = db_session.query(ProcessPhase).filter_by(process_id=p2.id,
                                                    phase_number=2).one()
    fase.status = "approved"
    db_session.flush()

    res = _cerrar(db_session, cohort, jefa)

    db_session.refresh(p2)
    assert res["paused"] == 1
    assert p2.status == "active"
