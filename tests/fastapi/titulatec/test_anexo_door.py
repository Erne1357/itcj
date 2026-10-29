"""Fase 6, tarea 3: motor del Anexo III -- puerta única, sincronía de la
subida y dictamen (spec fase 6 §5 C6/C9, §6 paso 5, §8, §10).

- Subir el escaneo (`DocumentService.save`) pone la fase 6 `in_review` sola y
  escribe `ProcessPhase.updated_at` (la clave FIFO de la bandeja); borrarlo la
  regresa a `in_progress`; resubir tras «Observar» la regresa a `in_review`.
- `AnexoService.approve` / `.observe` son la ÚNICA puerta de la fase 6:
  `approve_phase(6)`/`reject_phase(6)` por otra vía dan `ANEXO_ONLY_MSG`.
  Invariante: fase 6 `approved` <=> documento `anexo_iii` `approved`.
- Carreras (Review Focus 4): la subida o el borrado en vuelo contra un dictamen
  ya hecho releen el proceso bajo su bloqueo y no pisan el escaneo aprobado.
- `on_hold` y el corte en 3 dejan todo inerte.

Todo test que opera la fase 6 fija el corte en 9 (el contenedor de dev trae
10; CI y producción, 3).
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.orm.attributes import set_committed_value

from itcj2.apps.titulatec.models import Document, ProcessEvent, ProcessPhase
from itcj2.apps.titulatec.services import anexo_service
from itcj2.apps.titulatec.services.anexo_service import AnexoService
from itcj2.apps.titulatec.services.document_service import DocumentService
from itcj2.apps.titulatec.services.phase_service import PhaseService
from tests.fastapi.titulatec.conftest import audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")

# Un PDF estructuralmente válido (catálogo, páginas y trailer): pasa la
# validación y la compresión de `storage` como lo haría un escaneo real.
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
       b"trailer<</Root 1 0 R>>\n%%EOF\n")
TIPO = "anexo_iii"


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture()
def corte(monkeypatch):
    """`corte(9)` opera la fase 6; `corte(3)` es producción."""
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture()
def caso(db_session, corte, make_anexo_case, seed_document_types, make_user, tmp_path,
         monkeypatch):
    """Proceso en la fase 6 (`in_progress`) con el tipo `anexo_iii` sembrado,
    los archivos en `tmp_path` y un revisor de Titulación. Con `folio`, el
    Anexo además queda «Listo para recoger» (fase 6 v2: sin eso el alumno no
    sube el escaneo; `mark_ready` se prueba en `test_anexo_entrega.py`)."""
    def _build(*, modality_code="integral_residencias", phase_status="in_progress",
               cut=9, folio=True):
        corte(9)
        monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
        seed_document_types([(TIPO, "Anexo III firmado", 6)])
        c = make_anexo_case(modality_code=modality_code, phase_status=phase_status)
        if folio:
            anexo = AnexoService.ensure_folio(db_session, c.process, c.coordinator.id)
            anexo.ready_at = datetime(2026, 3, 20, 9, 0)
            anexo.pickup_note = "Oficina de vinculación"
            db_session.flush()
        revisor = make_user(first_name="TERE", last_name="TITULACION")
        corte(cut)
        return SimpleNamespace(**vars(c), revisor=revisor)
    return _build


@pytest.fixture()
def rollbacks(db_session, monkeypatch):
    """Cuenta los `db.rollback()` del servicio (y los deja ocurrir)."""
    llamadas = []
    original = db_session.rollback

    def _contado():
        llamadas.append(1)
        return original()
    monkeypatch.setattr(db_session, "rollback", _contado)
    return llamadas


def _subir(db, c, contenido=PDF):
    return DocumentService.save(db, c.process, TIPO, raw=contenido,
                                original_name="anexo_firmado.pdf",
                                content_type="application/pdf",
                                uploaded_by_id=c.student.id)


def _fase(db, c):
    db.expire_all()
    return (db.query(ProcessPhase)
            .filter_by(process_id=c.process.id, phase_number=c.anexo_phase).one())


def _doc(db, c):
    db.expire_all()
    return db.query(Document).filter_by(process_id=c.process.id, type_code=TIPO).first()


def _eventos(db, c, tipo):
    return (db.query(ProcessEvent).filter_by(process_id=c.process.id, event_type=tipo)
            .order_by(ProcessEvent.id).all())


def _acciones(db, action):
    from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog
    db.flush()
    return (audit_query(db).filter_by(source="action", action=action)
            .order_by(TitulatecAuditLog.id).all())


def _en_revision(db, c):
    """Sube el escaneo: fase 6 `in_review`, documento `pending` (commit)."""
    _subir(db, c)
    assert _fase(db, c).status == "in_review"
    return _doc(db, c)


def _contar(db, fn):
    sentencias = []

    def _ver(_conn, _cursor, statement, *_a):
        sentencias.append(statement)

    db.flush()
    conn = db.connection()
    event.listen(conn, "before_cursor_execute", _ver)
    try:
        resultado = fn()
    finally:
        event.remove(conn, "before_cursor_execute", _ver)
    return resultado, sentencias


def _lock(tabla, sentencia, modo):
    return f"FROM {tabla}" in sentencia and modo in sentencia


# ---------------------------------------------------------------------------
# 1. Sincronía de la subida (C6)
# ---------------------------------------------------------------------------
class TestSincronia:
    def test_subir_pone_la_fase_en_revision_y_escribe_la_clave_fifo(self, db_session, caso):
        c = caso()
        viejo = datetime(2026, 1, 1, 8, 0)
        _fase(db_session, c).updated_at = viejo
        db_session.flush()

        _subir(db_session, c)

        fase = _fase(db_session, c)
        assert fase.status == "in_review"
        assert fase.updated_at > viejo
        doc = _doc(db_session, c)
        assert doc.review_status == "pending" and doc.version == 1

    def test_resubir_sin_dictamen_sigue_en_revision_y_va_al_final(self, db_session, caso):
        # Fase 6 v2: el reemplazo sin dictamen (etapa `in_review`) sigue
        # permitido (C6 del v1, Ruling del controlador 2026-10-29).
        c = caso()
        _en_revision(db_session, c)
        viejo = datetime(2026, 1, 1, 8, 0)
        _fase(db_session, c).updated_at = viejo
        db_session.flush()

        _subir(db_session, c)

        fase = _fase(db_session, c)
        assert fase.status == "in_review"
        assert fase.updated_at > viejo, "cada subida manda el escaneo al final de la cola"
        assert _doc(db_session, c).version == 2

    def test_borrar_regresa_a_en_curso(self, db_session, caso):
        c = caso()
        _en_revision(db_session, c)

        assert DocumentService.delete(db_session, c.process.id, TIPO,
                                      actor_id=c.student.id) is True

        assert _fase(db_session, c).status == "in_progress"
        assert _doc(db_session, c) is None

    def test_resubir_tras_observar_vuelve_a_revision(self, db_session, caso):
        c = caso()
        _en_revision(db_session, c)
        AnexoService.observe(db_session, c.process, c.revisor.id,
                             reason="Falta la firma del Presidente.")
        assert _fase(db_session, c).status == "rejected"

        _subir(db_session, c)

        assert _fase(db_session, c).status == "in_review"
        doc = _doc(db_session, c)
        assert doc.review_status == "pending" and doc.review_note is None
        assert doc.version == 2

    def test_borrar_el_observado_se_niega_bajo_el_bloqueo(self, db_session, caso, tmp_path):
        """Revision final, punto 7: el escaneo solo se borra `pending`, y lo
        decide `DocumentService.delete` bajo el bloqueo (no solo la ruta)."""
        c = caso()
        _en_revision(db_session, c)
        AnexoService.observe(db_session, c.process, c.revisor.id, reason="Ilegible.")

        with pytest.raises(ValueError) as exc:
            DocumentService.delete(db_session, c.process.id, TIPO, actor_id=c.student.id)

        assert str(exc.value) == DocumentService.ANEXO_SCAN_REVIEWED_MSG
        str(exc.value).encode("ascii")              # viaja por X-Tt-Error
        doc = _doc(db_session, c)
        assert doc is not None and doc.review_status == "rejected"
        assert (tmp_path / doc.file_path).exists()
        assert _fase(db_session, c).status == "rejected"
        assert _eventos(db_session, c, "document_deleted") == []

    def test_ausente_solo_regresa_lo_que_estaba_en_revision(self, db_session, caso):
        """Sin escaneo, `sync_phase` no toca una fase observada."""
        c = caso()
        _en_revision(db_session, c)
        AnexoService.observe(db_session, c.process, c.revisor.id, reason="Ilegible.")
        db_session.delete(_doc(db_session, c))
        db_session.flush()

        assert AnexoService.sync_phase(db_session, c.process) is None
        assert _fase(db_session, c).status == "rejected"

    @pytest.mark.parametrize("estado", ["approved", "skipped", "pending"])
    def test_nunca_toca_aprobada_saltada_ni_pendiente(self, db_session, caso, make_document,
                                                     estado):
        c = caso(phase_status=estado, folio=False)      # `skipped` no alcanza el folio
        make_document(c.process, type_code=TIPO, phase_number=c.anexo_phase)
        viejo = _fase(db_session, c).updated_at

        assert AnexoService.sync_phase(db_session, c.process) is None

        fase = _fase(db_session, c)
        assert fase.status == estado and fase.updated_at == viejo

    def test_proceso_en_pausa_no_sincroniza(self, db_session, caso, make_document):
        c = caso()
        c.process.status = "on_hold"
        make_document(c.process, type_code=TIPO, phase_number=c.anexo_phase)

        assert AnexoService.sync_phase(db_session, c.process) is None
        assert _fase(db_session, c).status == "in_progress"

    def test_proceso_en_otra_fase_no_sincroniza(self, db_session, caso, make_document):
        c = caso()
        c.process.current_phase = c.review_phase
        make_document(c.process, type_code=TIPO, phase_number=c.anexo_phase)

        assert AnexoService.sync_phase(db_session, c.process) is None
        assert _fase(db_session, c).status == "in_progress"

    def test_corte_en_3_sync_no_toca_nada(self, db_session, caso, make_document):
        c = caso(cut=3)
        make_document(c.process, type_code=TIPO, phase_number=c.anexo_phase)
        viejo = _fase(db_session, c).updated_at

        assert AnexoService.operable(db_session) is False
        assert AnexoService.sync_phase(db_session, c.process) is None

        fase = _fase(db_session, c)
        assert fase.status == "in_progress" and fase.updated_at == viejo

    def test_subir_un_documento_de_la_fase_1_no_consulta_el_anexo(
            self, db_session, caso, seed_document_types, monkeypatch):
        """El gancho del Anexo no agrega consultas a la subida de la fase 1."""
        c = caso()
        seed_document_types()
        llamadas = []
        monkeypatch.setattr(AnexoService, "phase_number",
                            staticmethod(lambda db: llamadas.append(1) or 6))
        monkeypatch.setattr(AnexoService, "sync_phase",
                            staticmethod(lambda db, p: llamadas.append(2)))
        c.process.current_phase = 1
        DocumentService.save(db_session, c.process, "curp", raw=PDF,
                             original_name="curp.pdf", content_type="application/pdf",
                             uploaded_by_id=c.student.id)
        DocumentService.delete(db_session, c.process.id, "curp", actor_id=c.student.id)

        assert llamadas == []


# ---------------------------------------------------------------------------
# 2. Dictamen: aprobar
# ---------------------------------------------------------------------------
class TestAprobar:
    def test_aprobar_pasa_a_la_fase_7_en_una_transaccion(self, db_session, caso):
        c = caso()
        _en_revision(db_session, c)
        folio = AnexoService.get(db_session, c.process.id).folio

        out = AnexoService.approve(db_session, c.process, c.revisor.id)

        assert out["next_phase"] == c.anexo_phase + 1
        doc = _doc(db_session, c)
        assert doc.review_status == "approved" and doc.reviewed_by_id == c.revisor.id
        assert _fase(db_session, c).status == "approved"
        assert c.process.current_phase == c.anexo_phase + 1
        siguiente = (db_session.query(ProcessPhase)
                     .filter_by(process_id=c.process.id,
                                phase_number=c.anexo_phase + 1).one())
        assert siguiente.status == "in_progress"
        (ev,) = _eventos(db_session, c, "phase_approved")
        assert ev.phase_number == c.anexo_phase
        assert ev.payload == {"anexo_iii": {"folio": folio, "round": 1}}
        (acc,) = _acciones(db_session, "anexo_iii.reviewed")
        assert acc.payload["status"] == "approved" and acc.payload["round"] == 1
        assert acc.process_id == c.process.id
        assert PhaseService.DOOR_KEY not in db_session.info

    def test_la_ronda_es_la_version_del_documento(self, db_session, caso):
        c = caso()
        _en_revision(db_session, c)
        AnexoService.observe(db_session, c.process, c.revisor.id, reason="Sin sello.")
        _subir(db_session, c)

        AnexoService.approve(db_session, c.process, c.revisor.id)

        (ev,) = _eventos(db_session, c, "phase_approved")
        assert ev.payload["anexo_iii"]["round"] == 2

    def test_sin_folio_el_payload_lo_dice(self, db_session, caso, make_document):
        # Dato heredado de la v1 (escaneo sin «listo» ni folio): la v2 ya no
        # deja subir así, pero el dictamen no truena.
        c = caso(folio=False, phase_status="in_review")
        make_document(c.process, type_code=TIPO, phase_number=c.anexo_phase)

        AnexoService.approve(db_session, c.process, c.revisor.id)

        (ev,) = _eventos(db_session, c, "phase_approved")
        assert ev.payload == {"anexo_iii": {"folio": None, "round": 1}}

    def test_documento_pendiente_con_la_fase_en_curso(self, db_session, caso, make_document,
                                                     rollbacks):
        c = caso()
        make_document(c.process, type_code=TIPO, phase_number=c.anexo_phase)

        with pytest.raises(ValueError) as exc:
            AnexoService.approve(db_session, c.process, c.revisor.id)

        assert str(exc.value) == anexo_service.NOT_IN_REVIEW_MSG
        assert rollbacks == [], "falla antes del bloqueo"
        assert _fase(db_session, c).status == "in_progress"
        assert _doc(db_session, c).review_status == "pending"
        assert _eventos(db_session, c, "phase_approved") == []

    def test_sin_escaneo_no_se_aprueba(self, db_session, caso):
        c = caso(phase_status="in_review")
        with pytest.raises(ValueError) as exc:
            AnexoService.approve(db_session, c.process, c.revisor.id)
        assert str(exc.value) == anexo_service.NOT_IN_REVIEW_MSG
        assert _fase(db_session, c).status == "in_review"

    def test_proceso_en_pausa_rechaza_el_dictamen(self, db_session, caso):
        """Review Focus 5: `on_hold` en la fase 6 -> ni aprobar ni observar."""
        c = caso()
        _en_revision(db_session, c)
        c.process.status = "on_hold"
        db_session.flush()

        with pytest.raises(ValueError, match="on_hold"):
            AnexoService.approve(db_session, c.process, c.revisor.id)
        with pytest.raises(ValueError, match="on_hold"):
            AnexoService.observe(db_session, c.process, c.revisor.id, reason="x")

        assert _fase(db_session, c).status == "in_review"
        assert _doc(db_session, c).review_status == "pending"
        assert _acciones(db_session, "anexo_iii.reviewed") == []

    def test_corte_en_3_rechaza_aprobar_y_observar(self, db_session, caso, make_document):
        c = caso(phase_status="in_review", cut=3)
        make_document(c.process, type_code=TIPO, phase_number=c.anexo_phase)

        with pytest.raises(ValueError) as exc:
            AnexoService.approve(db_session, c.process, c.revisor.id)
        assert str(exc.value) == anexo_service.NOT_OPERABLE_MSG
        with pytest.raises(ValueError) as exc:
            AnexoService.observe(db_session, c.process, c.revisor.id, reason="x")
        assert str(exc.value) == anexo_service.NOT_OPERABLE_MSG

        assert _fase(db_session, c).status == "in_review"
        assert _doc(db_session, c).review_status == "pending"
        assert _eventos(db_session, c, "phase_approved") == []
        assert _acciones(db_session, "anexo_iii.reviewed") == []

    def test_dos_revisores_a_la_vez_el_segundo_ve_el_dictamen(self, db_session, caso,
                                                             rollbacks):
        """Carrera determinista: B leyó el escaneo pendiente y la fase en
        revisión ANTES de que A aprobara. Bajo el bloqueo B relee y se detiene."""
        c = caso()
        doc = _en_revision(db_session, c)
        fase = _fase(db_session, c)
        AnexoService.approve(db_session, c.process, c.revisor.id)       # A gana
        set_committed_value(doc, "review_status", "pending")             # lo que leyó B
        set_committed_value(fase, "status", "in_review")
        set_committed_value(c.process, "current_phase", c.anexo_phase)

        with pytest.raises(ValueError) as exc:
            AnexoService.observe(db_session, c.process, c.revisor.id, reason="Tarde.")

        assert str(exc.value) == anexo_service.NOT_IN_REVIEW_MSG, "lo para la relectura"
        assert rollbacks == [1], "falla bajo el bloqueo: deshace antes de re-lanzar"
        assert _doc(db_session, c).review_status == "approved"
        assert _fase(db_session, c).status == "approved"
        assert _eventos(db_session, c, "phase_rejected") == []
        assert PhaseService.DOOR_KEY not in db_session.info


# ---------------------------------------------------------------------------
# 3. Dictamen: observar
# ---------------------------------------------------------------------------
class TestObservar:
    def test_observar_regresa_la_fase_con_motivo(self, db_session, caso):
        c = caso()
        _en_revision(db_session, c)
        folio = AnexoService.get(db_session, c.process.id).folio

        AnexoService.observe(db_session, c.process, c.revisor.id,
                             reason="  Falta la firma del Vocal.  ")

        doc = _doc(db_session, c)
        assert doc.review_status == "rejected"
        assert doc.review_note == "Falta la firma del Vocal."
        assert doc.reviewed_by_id == c.revisor.id
        fase = _fase(db_session, c)
        assert fase.status == "rejected"
        assert fase.rejection_reason == "Falta la firma del Vocal."
        assert c.process.current_phase == c.anexo_phase
        (ev,) = _eventos(db_session, c, "phase_rejected")
        assert ev.payload == {"anexo_iii": {"folio": folio, "round": 1},
                              "reason": "Falta la firma del Vocal."}
        (acc,) = _acciones(db_session, "anexo_iii.reviewed")
        assert acc.payload["status"] == "rejected" and acc.payload["round"] == 1
        assert acc.reason == "Falta la firma del Vocal."
        assert PhaseService.DOOR_KEY not in db_session.info

    @pytest.mark.parametrize("motivo", [None, "", "   \n  "])
    def test_observar_sin_motivo_no_escribe_nada(self, db_session, caso, motivo, rollbacks):
        c = caso()
        _en_revision(db_session, c)

        with pytest.raises(ValueError) as exc:
            AnexoService.observe(db_session, c.process, c.revisor.id, reason=motivo)

        assert str(exc.value) == anexo_service.REASON_REQUIRED_MSG
        assert rollbacks == []
        assert _fase(db_session, c).status == "in_review"
        assert _doc(db_session, c).review_status == "pending"
        assert _eventos(db_session, c, "phase_rejected") == []
        assert _acciones(db_session, "anexo_iii.reviewed") == []

    def test_motivo_de_mas_de_500(self, db_session, caso):
        c = caso()
        _en_revision(db_session, c)

        with pytest.raises(ValueError) as exc:
            AnexoService.observe(db_session, c.process, c.revisor.id, reason="x" * 501)
        assert str(exc.value) == anexo_service.REASON_TOO_LONG_MSG

        AnexoService.observe(db_session, c.process, c.revisor.id, reason="x" * 500)
        assert _fase(db_session, c).status == "rejected"

    def test_observar_una_fase_ya_observada(self, db_session, caso):
        c = caso()
        _en_revision(db_session, c)
        AnexoService.observe(db_session, c.process, c.revisor.id, reason="Uno.")

        with pytest.raises(ValueError) as exc:
            AnexoService.observe(db_session, c.process, c.revisor.id, reason="Dos.")
        assert str(exc.value) == anexo_service.NOT_IN_REVIEW_MSG
        assert len(_eventos(db_session, c, "phase_rejected")) == 1


# ---------------------------------------------------------------------------
# 4. Una sola puerta
# ---------------------------------------------------------------------------
class TestUnaSolaPuerta:
    def test_registro_de_la_puerta(self):
        assert PhaseService._DOOR_PHASES["anexo_iii"] == PhaseService.ANEXO_ONLY_MSG
        assert PhaseService.ANEXO_ONLY_MSG == (
            "El Anexo III se dictamina desde la pestaña Titulación.")

    def test_aprobar_o_rechazar_la_fase_6_directo(self, db_session, caso):
        c = caso()
        _en_revision(db_session, c)

        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, c.process, c.anexo_phase, c.revisor.id)
        assert str(exc.value) == PhaseService.ANEXO_ONLY_MSG
        with pytest.raises(ValueError) as exc:
            PhaseService.reject_phase(db_session, c.process, c.anexo_phase, c.revisor.id,
                                      "por la otra puerta")
        assert str(exc.value) == PhaseService.ANEXO_ONLY_MSG

        assert _fase(db_session, c).status == "in_review"
        assert c.process.current_phase == c.anexo_phase

    def test_la_marca_sin_el_documento_dictaminado_no_abre(self, db_session, caso):
        """La guarda mira el estado: con el escaneo `pending` la marca no basta."""
        c = caso()
        _en_revision(db_session, c)
        for veredicto in ("approved", "rejected"):
            PhaseService.open_door(db_session, "anexo_iii", c.process.id, veredicto)
            with pytest.raises(ValueError) as exc:
                if veredicto == "approved":
                    PhaseService.approve_phase(db_session, c.process, c.anexo_phase,
                                               c.revisor.id)
                else:
                    PhaseService.reject_phase(db_session, c.process, c.anexo_phase,
                                              c.revisor.id, "x")
            assert str(exc.value) == PhaseService.ANEXO_ONLY_MSG
            assert PhaseService.DOOR_KEY not in db_session.info, "se consume"
        assert _fase(db_session, c).status == "in_review"

    def test_door_state_ok_espeja_el_documento(self, db_session, caso):
        c = caso()
        doc = _en_revision(db_session, c)
        ok = PhaseService._door_state_ok
        assert not ok(db_session, "anexo_iii", c.process, "approved")
        assert not ok(db_session, "anexo_iii", c.process, "rejected")
        doc.review_status = "approved"
        db_session.flush()
        assert ok(db_session, "anexo_iii", c.process, "approved")
        assert not ok(db_session, "anexo_iii", c.process, "rejected")
        doc.review_status = "rejected"
        db_session.flush()
        assert ok(db_session, "anexo_iii", c.process, "rejected")
        assert not ok(db_session, "anexo_iii", c.process, "approved")

    def test_la_bandeja_documentos_no_dictamina_el_escaneo(self, db_session, caso):
        """`DocumentService.review` (bandeja de Documentos) no aprueba ni
        rechaza el `anexo_iii`: rompería fase 6 `approved` <=> documento."""
        c = caso()
        _en_revision(db_session, c)
        for estado in ("approved", "rejected"):
            with pytest.raises(ValueError) as exc:
                DocumentService.review(db_session, c.process.id, TIPO, status=estado,
                                       note="x", reviewer_id=c.revisor.id)
            assert str(exc.value) == DocumentService.ANEXO_REVIEW_MSG
            str(exc.value).encode("ascii")          # viaja por X-Tt-Error sin _hdr
        assert _doc(db_session, c).review_status == "pending"


# ---------------------------------------------------------------------------
# 5. Review Focus 4: resubir o borrar contra un dictamen ya hecho
# ---------------------------------------------------------------------------
class TestCarreraContraElDictamen:
    def test_resubir_tras_aprobar_falla(self, db_session, caso):
        c = caso()
        _en_revision(db_session, c)
        AnexoService.approve(db_session, c.process, c.revisor.id)

        with pytest.raises(ValueError) as exc:
            _subir(db_session, c)

        assert str(exc.value) == DocumentService.REPLACEMENT_CLOSED_MSG
        doc = _doc(db_session, c)
        assert doc.review_status == "approved" and doc.version == 1

    def test_subida_en_vuelo_con_el_proceso_viejo_en_memoria(self, db_session, caso):
        """La ruta del alumno cargó el proceso (fase 6) y comprimió el PDF; entre
        tanto Titulación aprobó. `save` relee el proceso bajo su bloqueo: no
        pisa el escaneo aprobado ni regresa la fase."""
        c = caso()
        _en_revision(db_session, c)
        AnexoService.approve(db_session, c.process, c.revisor.id)
        set_committed_value(c.process, "current_phase", c.anexo_phase)   # lo que leyó

        with pytest.raises(ValueError) as exc:
            _subir(db_session, c)

        assert str(exc.value) == DocumentService.REPLACEMENT_CLOSED_MSG
        assert _doc(db_session, c).review_status == "approved"
        assert _fase(db_session, c).status == "approved"

    def test_borrado_en_vuelo_con_el_proceso_viejo_en_memoria(self, db_session, caso,
                                                             tmp_path):
        c = caso()
        _en_revision(db_session, c)
        AnexoService.approve(db_session, c.process, c.revisor.id)
        set_committed_value(c.process, "current_phase", c.anexo_phase)

        with pytest.raises(ValueError) as exc:
            DocumentService.delete(db_session, c.process.id, TIPO, actor_id=c.student.id)

        assert str(exc.value) == DocumentService.REPLACEMENT_CLOSED_MSG
        doc = _doc(db_session, c)
        assert doc is not None and doc.review_status == "approved"
        assert (tmp_path / doc.file_path).exists(), "el archivo aprobado sigue en disco"

    def test_subir_el_escaneo_bloquea_el_proceso_antes_que_el_documento(self, db_session,
                                                                        caso):
        """Mismo orden de candados que el dictamen (proceso -> documento)."""
        c = caso()
        _, sql = _contar(db_session, lambda: _subir(db_session, c))

        proceso = next(i for i, s in enumerate(sql)
                       if _lock("titulatec_processes", s, "FOR NO KEY UPDATE"))
        documento = next(i for i, s in enumerate(sql)
                         if _lock("titulatec_documents", s, "FOR UPDATE"))
        assert proceso < documento
