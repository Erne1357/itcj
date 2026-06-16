"""Tests del motor de fases (PhaseService) — avance, salto y notificaciones."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.phase_service import PhaseService


# ───────────────────────────── helpers puros ─────────────────────────────

def _proc(skips=None, current_phase=1):
    modality = SimpleNamespace(skips_phases=skips)
    return SimpleNamespace(id=1, student_id=7, modality=modality,
                           current_phase=current_phase, status="active",
                           completed_at=None)


class TestSkipsYSiguiente:
    def test_skips_desde_json(self):
        assert PhaseService._skips(_proc(skips=[4, 5])) == {4, 5}

    def test_skips_vacio_si_none(self):
        assert PhaseService._skips(_proc(skips=None)) == set()

    def test_skips_vacio_si_invalido(self):
        assert PhaseService._skips(_proc(skips=["x"])) == set()

    def test_siguiente_salta_las_fases_de_la_modalidad(self):
        # tras la fase 3, con 4 y 5 saltadas → 6
        assert PhaseService._next_applicable(_proc(skips=[4, 5]), 3) == 6

    def test_siguiente_none_al_final(self):
        assert PhaseService._next_applicable(_proc(skips=None), 8) is None


# ───────────────────────────── approve_phase ─────────────────────────────

class TestApprovePhase:
    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_avanza_a_la_siguiente_fase(self, mock_notify):
        db = MagicMock()
        process = _proc(skips=None, current_phase=1)

        result = PhaseService.approve_phase(db, process, 1, reviewer_id=200)

        assert result == {"next_phase": 2, "completed": False}
        assert process.current_phase == 2
        assert process.status == "active"
        db.commit.assert_called_once()
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["type"] == "PHASE_APPROVED"

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_ultima_fase_completa_el_proceso(self, mock_notify):
        db = MagicMock()
        process = _proc(skips=None, current_phase=8)

        result = PhaseService.approve_phase(db, process, 8, reviewer_id=200)

        assert result == {"next_phase": None, "completed": True}
        assert process.status == "completed"
        assert process.completed_at is not None
        assert mock_notify.call_args.kwargs["type"] == "PROCESS_COMPLETED"


# ───────────────────────────── reject_phase ──────────────────────────────

class TestRejectPhase:
    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_rechaza_y_notifica_con_motivo(self, mock_notify):
        db = MagicMock()
        process = _proc(skips=None, current_phase=3)

        PhaseService.reject_phase(db, process, 2, reviewer_id=200, reason="Faltan firmas")

        assert process.current_phase == 2
        db.commit.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["type"] == "PHASE_REJECTED"
        assert kwargs["phase_number"] == 2
        assert "Faltan firmas" in kwargs["body"]
