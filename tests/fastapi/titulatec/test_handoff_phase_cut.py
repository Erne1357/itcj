"""Corte a T-soft: `TITULATEC_HANDOFF_PHASE` (Tarea 2 del plan de deslinde).

A partir de esa fase (3 = Formato B por defecto) el proceso ya NO se opera en
esta app: lo atiende el Departamento de Titulacion en su propio sistema
(T-soft). Las dos guardas existentes (`_student_action_error` para el alumno,
`_transition_error` para el dictamen del admin) ganan una tercera regla que
bloquea cualquier accion sobre `phase_number >= _handoff_phase()`.

`approve_phase(2)` es el acto de LIBERACION sobre el que se apoya toda la
feature (mueve `current_phase` de 2 a 3) y tiene que seguir funcionando: el
corte protege la fase 3 en si, no el salto hacia ella.

Ver `docs/superpowers/specs/2026-09-21-titulatec-dpto-titulacion-design.md` §4.
"""
from __future__ import annotations

import unicodedata
from unittest.mock import patch

import pytest

from itcj2.apps.titulatec.services.phase_service import PhaseService


@pytest.fixture()
def revisor(make_user):
    """Un revisor que EXISTE en `core_users` (FK de `reviewed_by_id`/`actor_id`).

    Mismo patron que `test_phase_service.py::revisor`: un id inventado solo
    prueba que la base de quien corre el test tiene a alguien con ese numero.
    """
    return make_user(first_name="REVISOR", last_name="DE PRUEBA")


# ─────────────────────────── guarda del ALUMNO ────────────────────────────

class TestCorteDelAlumno:
    def test_el_alumno_no_puede_actuar_en_la_fase_3_con_el_corte_puesto(
        self, db_session, seed_phase_defs, make_student, make_process,
    ):
        seed_phase_defs()
        process = make_process(make_student(), current_phase=3)

        with pytest.raises(ValueError) as exc:
            PhaseService.assert_student_can_act(db_session, process, 3)

        assert str(exc.value) == PhaseService.HANDOFF_MSG

    def test_el_alumno_si_puede_actuar_en_la_fase_2_con_el_corte_puesto(
        self, db_session, seed_phase_defs, make_student, make_process,
    ):
        seed_phase_defs()
        process = make_process(make_student(), current_phase=2)

        assert PhaseService.assert_student_can_act(db_session, process, 2) == 2
        assert PhaseService.can_student_act(db_session, process, 2) is True

    def test_con_el_corte_en_9_la_fase_3_vuelve_a_ser_operable(
        self, db_session, seed_phase_defs, make_student, make_process, monkeypatch,
    ):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 9))
        seed_phase_defs()
        process = make_process(make_student(), current_phase=3)

        assert PhaseService.assert_student_can_act(db_session, process, 3) == 3


# ──────────────────────────── guarda del ADMIN ────────────────────────────

class TestCorteDelAdmin:
    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_el_admin_no_puede_aprobar_la_fase_3_con_el_corte_puesto(
        self, mock_notify, db_session, seed_phase_defs, make_student, make_process,
        revisor,
    ):
        seed_phase_defs()
        process = make_process(make_student(), current_phase=3)

        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, process, 3, reviewer_id=revisor.id)

        assert str(exc.value) == PhaseService.HANDOFF_MSG
        assert process.current_phase == 3
        mock_notify.assert_not_called()

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_el_admin_si_puede_aprobar_la_fase_2_con_el_corte_puesto(
        self, mock_notify, db_session, seed_phase_defs, make_student, make_process,
        revisor,
    ):
        """Es la liberacion: manda `current_phase` de 2 a 3 (T-soft) y tiene que
        seguir funcionando pese al corte -- es el acto sobre el que se apoya
        toda la feature (ver docstring del modulo)."""
        seed_phase_defs()
        process = make_process(make_student(), current_phase=2)

        result = PhaseService.approve_phase(db_session, process, 2, reviewer_id=revisor.id)

        assert result == {"next_phase": 3, "completed": False}
        assert process.current_phase == 3


# ─────────────────────────── mensaje del corte ────────────────────────────

class TestMensajeDelCorte:
    def test_el_mensaje_del_corte_es_ascii_puro(self):
        """Viaja por `X-Tt-Error`: Starlette lo escribe en latin-1 pero su
        TestClient lo lee en UTF-8 -- un solo byte >127 revienta el request
        (mismo motivo que `_transition_error`/`_student_action_error`)."""
        msg = PhaseService.HANDOFF_MSG

        msg.encode("latin-1")  # no debe levantar
        assert msg == unicodedata.normalize("NFKD", msg).encode("ascii", "ignore").decode()
