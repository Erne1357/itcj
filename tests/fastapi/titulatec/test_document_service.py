"""Tests de DocumentService.review — notificación al alumno cuando se rechaza."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.document_service import DocumentService


class TestReview:
    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_rechazo_notifica_al_alumno(self, mock_notify):
        db = MagicMock()
        db.get.return_value = SimpleNamespace(student_id=7)
        # `review()` ahora TAMBIEN consulta `DocumentType` para la guarda angosta
        # del corte a T-soft (Tarea 2, Ronda 3): sin configurar esto, el
        # `MagicMock` sin resolver revienta `dtype.phase_number >= _handoff_phase()`
        # (`>=` entre MagicMock e int). `curp` es fase 1 de verdad en el catalogo
        # real, asi que esto no cambia lo que el test prueba (notificacion).
        db.query.return_value.filter_by.return_value.first.return_value = \
            SimpleNamespace(phase_number=1)

        ok = DocumentService.review(db, process_id=1, type_code="curp",
                                    status="rejected", note="Ilegible", reviewer_id=200)

        assert ok is True
        db.commit.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["type"] == "DOCUMENT_REJECTED"
        assert kwargs["phase_number"] == 1
        assert kwargs["body"] == "Ilegible"

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_aprobacion_no_notifica(self, mock_notify):
        db = MagicMock()
        # Mismo motivo que en `test_rechazo_notifica_al_alumno`: la guarda angosta
        # del corte a T-soft consulta `DocumentType.phase_number`.
        db.query.return_value.filter_by.return_value.first.return_value = \
            SimpleNamespace(phase_number=1)

        ok = DocumentService.review(db, process_id=1, type_code="curp",
                                    status="approved", note=None, reviewer_id=200)
        assert ok is True
        mock_notify.assert_not_called()

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_documento_inexistente_devuelve_false(self, mock_notify):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None
        ok = DocumentService.review(db, process_id=1, type_code="curp",
                                    status="rejected", note="x", reviewer_id=200)
        assert ok is False
        mock_notify.assert_not_called()

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_tipo_de_documento_desconocido_cae_en_la_fase_de_la_fila(self, mock_notify):
        """Arreglo A4 (revision final 2026-09-21): si `dtype` es None (el tipo
        ya no existe en el catalogo -- borrado o nunca sembrado), la guarda
        del corte NO debe abrirse por default. Antes, `dtype is None` dejaba
        pasar el dictamen SIN mirar nada mas, aunque el documento fuera de una
        fase ya congelada -- justo lo contrario del principio que el propio
        repo fija en `phase_service.py:158-161` ("None es una respuesta
        legitima... FALLA CERRADO"). El respaldo es `doc.phase_number`
        (columna real de la fila, `nullable=False`: SIEMPRE esta a mano).
        """
        from itcj2.apps.titulatec.models import Document

        doc = SimpleNamespace(phase_number=6, review_status="pending",
                              review_note=None, reviewed_by_id=None)

        def _query(model):
            q = MagicMock()
            q.filter_by.return_value.first.return_value = (
                doc if model is Document else None)
            return q

        db = MagicMock()
        db.query.side_effect = _query

        from itcj2.apps.titulatec.services.phase_service import PhaseService
        with pytest.raises(ValueError) as exc:
            DocumentService.review(db, process_id=1, type_code="tipo_borrado",
                                   status="approved", note=None, reviewer_id=200)

        assert str(exc.value) == PhaseService.HANDOFF_MSG
        assert doc.review_status == "pending", "debe bloquear ANTES de escribir"
        mock_notify.assert_not_called()

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_tipo_de_documento_desconocido_de_fase_temprana_si_se_dictamina(
        self, mock_notify,
    ):
        """Simetrico del anterior: el respaldo usa el VALOR de
        `doc.phase_number`, no bloquea por el simple hecho de que `dtype` sea
        None (regla de oro: ninguna negativa sola)."""
        from itcj2.apps.titulatec.models import Document

        doc = SimpleNamespace(phase_number=1, review_status="pending",
                              review_note=None, reviewed_by_id=None)

        def _query(model):
            q = MagicMock()
            q.filter_by.return_value.first.return_value = (
                doc if model is Document else None)
            return q

        db = MagicMock()
        db.query.side_effect = _query

        ok = DocumentService.review(db, process_id=1, type_code="tipo_borrado",
                                    status="approved", note=None, reviewer_id=200)

        assert ok is True
        assert doc.review_status == "approved"
