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

from itcj2.apps.titulatec.services.document_service import DocumentService
from itcj2.apps.titulatec.services.format_b_service import FormatBService
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


# ──────────────── guarda del ADMIN en FormatBService.review ───────────────
# Ronda de fix 2 (2026-09-21): `review` no pasaba por NINGUNA guarda -ni la
# generica del admin-, solo por permiso y alcance por carrera. El hueco es
# real por el mecanismo de REVERSION que esta misma feature documenta: subir
# `TITULATEC_HANDOFF_PHASE` a 9, dejar pasar un envio a `submitted`, y volver
# a bajarlo a 3 dejaba ese Formato B aprobable/rechazable para siempre pese
# al corte -el corte dejaba de ser cierto justo por el camino que
# documentamos para desactivarlo-.

class TestCorteEnFormatBReview:
    @staticmethod
    def _fb_submitted(db, process):
        from itcj2.apps.titulatec.models import FormatB
        fb = FormatB(process_id=process.id, status="submitted")
        db.add(fb)
        db.flush()
        return fb

    def test_el_admin_no_puede_dictaminar_el_formato_b_con_el_corte_puesto(
        self, db_session, seed_phase_defs, make_student, make_process, revisor,
    ):
        seed_phase_defs()
        process = make_process(make_student(), current_phase=3)
        fb = self._fb_submitted(db_session, process)

        with pytest.raises(ValueError) as exc:
            FormatBService.review(db_session, fb, process, status="approved",
                                  note=None, reviewer_id=revisor.id)

        assert str(exc.value) == PhaseService.HANDOFF_MSG
        assert fb.status == "submitted", "el corte debe bloquear ANTES de escribir"

    def test_con_el_corte_en_9_el_dictamen_del_formato_b_si_pasa(
        self, db_session, seed_phase_defs, make_student, make_process, revisor,
        monkeypatch,
    ):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 9))
        seed_phase_defs()
        process = make_process(make_student(), current_phase=3)
        fb = self._fb_submitted(db_session, process)

        FormatBService.review(db_session, fb, process, status="approved",
                              note=None, reviewer_id=revisor.id)

        assert fb.status == "approved"
        assert fb.approved_by_id == revisor.id


# ────────────── guarda ANGOSTA en DocumentService.review ──────────────────
# Ronda de fix 3 (2026-09-21): mismo hueco que `FormatBService.review` tenia
# (cero guarda; `pages/documents.py::review` solo validaba permiso y alcance
# por carrera), pero el arreglo NO es la misma guarda. `assert_can_transition`
# exige `phase_number == process.current_phase`, y en documentos eso
# ROMPERIA el dictamen TARDIO -revisar hoy un documento de una fase que el
# proceso ya dejo atras es el uso normal de esta bandeja, no una excepcion
# ("`DocumentService.save` ya trata la fase del documento como la del TIPO,
# no la del proceso"). La guarda aqui es minima: solo mira si el TIPO del
# documento (`dtype.phase_number`) cayo dentro del corte, sin importar en
# que fase vaya el proceso.

class TestCorteEnDocumentServiceReview:
    def test_no_se_dictamina_un_documento_de_tipo_congelado_con_el_corte_puesto(
        self, db_session, seed_phase_defs, seed_document_types, make_student,
        make_process, make_document, revisor,
    ):
        """`anexo_iii` es de la fase 6 (>= corte=3): bloqueado.

        `current_phase=1` aqui es DELIBERADO, no un descuido: esta guarda no
        mira `current_phase` en absoluto, solo el tipo del documento -- por
        eso bloquea igual aunque el proceso ni siquiera haya llegado ahi.
        """
        seed_phase_defs()
        seed_document_types([("anexo_iii", "Anexo III firmado", 6)])
        process = make_process(make_student(), current_phase=1)
        doc = make_document(process, type_code="anexo_iii", phase_number=6,
                            review_status="pending")

        with pytest.raises(ValueError) as exc:
            DocumentService.review(db_session, process.id, "anexo_iii",
                                   status="approved", note=None,
                                   reviewer_id=revisor.id)

        assert str(exc.value) == PhaseService.HANDOFF_MSG
        assert doc.review_status == "pending", "el corte debe bloquear ANTES de escribir"

    def test_un_documento_de_fase_1_se_dictamina_tarde_con_el_corte_puesto(
        self, db_session, seed_phase_defs, seed_document_types, make_student,
        make_process, make_document, revisor,
    ):
        """EL TEST IMPORTANTE: fija el dictamen TARDIO como comportamiento

        deseado, no un hueco a cerrar. El documento es de la fase 1 pero el
        proceso YA avanzo a la fase 2 -- exactamente el caso real de la
        bandeja de Documentos (rezagados) que `DocumentService.review` tiene
        que seguir sirviendo sin condicion, con el corte puesto o no.

        Si alguien mas adelante "endurece" esta guarda para que tambien exija
        `phase_number == process.current_phase` (como
        `FormatBService.review`), ESTE test se pone en rojo y avisa: seria
        romper el dictamen tardio, no una mejora de seguridad.
        """
        seed_phase_defs()
        seed_document_types()  # los 3 de la fase 1 por defecto
        process = make_process(make_student(), current_phase=2)  # YA avanzo
        doc = make_document(process, type_code="curp", phase_number=1,
                            review_status="pending")

        ok = DocumentService.review(db_session, process.id, "curp",
                                    status="approved", note=None,
                                    reviewer_id=revisor.id)

        assert ok is True
        assert doc.review_status == "approved"


# ─────────────────────────── mensaje del corte ────────────────────────────

class TestMensajeDelCorte:
    def test_el_mensaje_del_corte_es_ascii_puro(self):
        """Viaja por `X-Tt-Error`: Starlette lo escribe en latin-1 pero su
        TestClient lo lee en UTF-8 -- un solo byte >127 revienta el request
        (mismo motivo que `_transition_error`/`_student_action_error`)."""
        msg = PhaseService.HANDOFF_MSG

        msg.encode("latin-1")  # no debe levantar
        assert msg == unicodedata.normalize("NFKD", msg).encode("ascii", "ignore").decode()
