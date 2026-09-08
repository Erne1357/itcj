"""La fase 2 no se libera si al alumno le faltan requisitos de cotejo (D9).

Espejo de `DocumentService.initial_docs_all_approved`, que ya hace lo mismo para
la fase 1. El alumno SI puede agendar y presentarse: lo que se bloquea es el
DICTAMEN del oficial, nada mas.

Tres cosas que estos tests fijan y que alguien podria 'arreglar' por error:

* `waived` (dispensa con nota) satisface el requisito. Sin eso un caso legitimo
  dejaria la fase trabada para siempre.
* SOLO la fase 2. Ni la 1 ni la 3 miran el checklist.
* Un proceso creado ANTES de que existiera el requisito queda igualmente sujeto
  a el: la guarda lee el estado ACTUAL de la convocatoria, porque el requisito
  es del tramite, no del momento del alta.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.apps.titulatec.services.requirement_service import RequirementService


def _req(db, cohort, *, label, is_required=True, is_active=True, order_index=0):
    from itcj2.apps.titulatec.models import CotejoRequirement
    row = CotejoRequirement(cohort_id=cohort.id, label=label, icon="check2-square",
                            is_required=is_required, is_active=is_active,
                            order_index=order_index)
    db.add(row)
    db.flush()
    return row


def _estado(db, process_id, n):
    from itcj2.apps.titulatec.models import ProcessPhase
    return (db.query(ProcessPhase)
            .filter_by(process_id=process_id, phase_number=n).one().status)


@pytest.fixture()
def revisor(make_user):
    """Un revisor que EXISTE en core_users: hay FK en process_phases y events."""
    return make_user(first_name="REVISOR", last_name="DE PRUEBA")


@pytest.fixture()
def esc(db_session, seed_phase_defs, make_student, make_cohort, make_process):
    seed_phase_defs()
    cohort = make_cohort()

    def _build(current_phase=2, program=None):
        return cohort, make_process(make_student(), cohort=cohort, program=program,
                                    current_phase=current_phase)

    return _build


class TestBloqueo:
    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_no_aprueba_y_nombra_lo_que_falta(self, _n, db_session, esc, revisor):
        cohort, process = esc(current_phase=2)
        _req(db_session, cohort, label="Vigencia de derechos IMSS", order_index=0)
        _req(db_session, cohort, label="12 fotografias", order_index=1)

        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, process, 2, reviewer_id=revisor.id)

        assert "Vigencia de derechos IMSS" in str(exc.value)
        assert "12 fotografias" in str(exc.value)
        assert process.current_phase == 2
        assert _estado(db_session, process.id, 2) == "in_progress"

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_un_proceso_anterior_al_requisito_queda_sujeto(self, _n, db_session, esc,
                                                           revisor):
        """El requisito es del tramite, no del momento del alta."""
        cohort, process = esc(current_phase=2)          # primero el proceso
        _req(db_session, cohort, label="Requisito nuevo")   # despues el requisito

        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, process, 2, reviewer_id=revisor.id)

        assert "Requisito nuevo" in str(exc.value)


class TestPaso:
    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_fulfilled_deja_pasar(self, _n, db_session, esc, revisor):
        cohort, process = esc(current_phase=2)
        req = _req(db_session, cohort, label="Actas de nacimiento")
        RequirementService.fulfill(db_session, process.id, req.id,
                                   source="officer", commit=False)

        result = PhaseService.approve_phase(db_session, process, 2, reviewer_id=revisor.id)

        assert result == {"next_phase": 3, "completed": False}
        assert _estado(db_session, process.id, 2) == "approved"

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_waived_deja_pasar(self, _n, db_session, esc, revisor):
        """La dispensa con nota existe para que un caso legitimo no trabe la fase."""
        cohort, process = esc(current_phase=2)
        req = _req(db_session, cohort, label="e.Firma (SAT)")
        RequirementService.fulfill(db_session, process.id, req.id, source="officer",
                                   status="waived", note="Tramite del SAT caido",
                                   commit=False)

        result = PhaseService.approve_phase(db_session, process, 2, reviewer_id=revisor.id)

        assert result == {"next_phase": 3, "completed": False}

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_opcionales_e_inactivos_no_traban(self, _n, db_session, esc, revisor):
        cohort, process = esc(current_phase=2)
        _req(db_session, cohort, label="Opcional", is_required=False, order_index=0)
        _req(db_session, cohort, label="Retirado", is_active=False, order_index=1)

        result = PhaseService.approve_phase(db_session, process, 2, reviewer_id=revisor.id)

        assert result == {"next_phase": 3, "completed": False}

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_sin_requisitos_configurados_no_traba(self, _n, db_session, esc, revisor):
        """La guarda NO siembra: una convocatoria sin lista no bloquea a nadie."""
        _cohort, process = esc(current_phase=2)

        result = PhaseService.approve_phase(db_session, process, 2, reviewer_id=revisor.id)

        assert result == {"next_phase": 3, "completed": False}


class TestSoloLaFase2:
    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_la_fase_1_no_mira_el_checklist(self, _n, db_session, esc, revisor):
        cohort, process = esc(current_phase=1)
        _req(db_session, cohort, label="Requisito pendiente")

        result = PhaseService.approve_phase(db_session, process, 1, reviewer_id=revisor.id)

        assert result == {"next_phase": 2, "completed": False}

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_la_fase_3_no_mira_el_checklist(self, _n, db_session, esc, revisor):
        cohort, process = esc(current_phase=3)
        _req(db_session, cohort, label="Requisito pendiente")

        result = PhaseService.approve_phase(db_session, process, 3, reviewer_id=revisor.id)

        assert result == {"next_phase": 4, "completed": False}

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_rechazar_la_fase_2_sigue_siendo_posible(self, _n, db_session, esc, revisor):
        """Rechazar no es aprobar: la guarda no puede atrapar tambien esa via."""
        cohort, process = esc(current_phase=2)
        _req(db_session, cohort, label="Requisito pendiente")

        PhaseService.reject_phase(db_session, process, 2, reviewer_id=revisor.id,
                                  reason="Faltan documentos fisicos")

        assert _estado(db_session, process.id, 2) == "rejected"


class TestDesdeLaRuta:
    def test_el_boton_del_expediente_contesta_400_con_el_motivo(
            self, db_session, esc, client_as, make_head, make_program):
        """El mensaje llega percent-codificado en X-Tt-Error (`phase_approve`).

        El proceso lleva CARRERA a proposito. Sin ella `process_in_scope` lo manda
        al cubo "Sin carrera" —la cola de reparacion, que abre
        `titulatec.officers.api.manage`— y la ruta contesta 404 antes de llegar a
        la guarda: el 404 taparia justo el 400 que este test mide.
        """
        from urllib.parse import unquote

        cohort, process = esc(current_phase=2,
                              program=make_program("Ingenieria de la Puerta"))
        _req(db_session, cohort, label="12 fotografias")
        jefa = make_head(perm_codes=("titulatec.process.api.read.all",
                                     "titulatec.process.api.approve_phase"))

        resp = client_as(jefa).post(
            f"/titulatec/admin/processes/{process.id}/phase/2/approve",
            follow_redirects=False)

        assert resp.status_code == 400, resp.text[:300]
        assert "12 fotografias" in unquote(resp.headers.get("X-Tt-Error", ""))
