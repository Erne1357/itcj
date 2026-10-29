"""Fase 6 v2 (spec 2026-10-29-titulatec-fase6-anexo-entrega): el Anexo III lo
prepara vinculacion.

Nucleo de `AnexoService`: etapas (`stage`/`stage_map`, orden EXACTO de §4),
«Listo para recoger» (`mark_ready`), reimpresion (`observe(reprint=True)`),
vista previa del alumno (`preview_pdf`, nunca escribe), guarda de subida del
escaneo (`DocumentService.save`, las dos rutas del alumno), precarga de la nota
(`default_pickup_note`) y avisos (`notify_ready`/`notify_reprint`).
Review Focus 1, 2, 4 y 5 del plan.

Todo test que opera la fase 6 fija el corte en 9; la inercia se prueba con 3.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from sqlalchemy import event

from itcj2.apps.titulatec.models import Anexo, Document, ProcessEvent, ProcessPhase
from itcj2.apps.titulatec.services import anexo_service
from itcj2.apps.titulatec.services.anexo_service import AnexoService
from itcj2.apps.titulatec.services.document_service import DocumentService
from itcj2.apps.titulatec.services.phase_service import PhaseService
from tests.fastapi.titulatec.conftest import ROLE_STUDENT, STUDENT_PERMS, audit_query

pytestmark = pytest.mark.usefixtures("audit_mark")

PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
       b"trailer<</Root 1 0 R>>\n%%EOF\n")
TIPO = "anexo_iii"
NOTA = "Oficina de vinculacion de Sistemas, edificio A, de 9:00 a 14:00"
PERMS_ALUMNO = STUDENT_PERMS + ("titulatec.document.api.delete.own",
                                "titulatec.anexo_iii.api.preview.own")


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture()
def corte(monkeypatch):
    def _fijar(fase):
        monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: fase))
    return _fijar


@pytest.fixture()
def correos(monkeypatch):
    """`StudentMail.anexo_ready` (T1b) espiado: lo que `mark_ready` encola."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    llamadas = []

    def _espia(db, process, *, folio, note):
        llamadas.append({"process_id": process.id, "folio": folio, "note": note})
        return True
    monkeypatch.setattr(StudentMail, "anexo_ready", staticmethod(_espia))
    return llamadas


@pytest.fixture()
def caso(db_session, corte, make_anexo_case, seed_document_types, make_user, tmp_path,
         monkeypatch, correos):
    """Proceso en la fase 6 sin folio (`folio=True` lo emite; `listo=True` lo
    marca listo como vinculacion)."""
    def _build(*, modality_code="integral_residencias", phase_status="in_progress",
               folio=False, listo=False, cut=9):
        corte(9)
        monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
        seed_document_types([(TIPO, "Anexo III firmado", 6)])
        c = make_anexo_case(modality_code=modality_code, phase_status=phase_status)
        if folio:
            AnexoService.ensure_folio(db_session, c.process, c.coordinator.id)
        if listo:
            AnexoService.mark_ready(db_session, c.process, c.coordinator.id, NOTA)
        revisor = make_user(first_name="TERE", last_name="TITULACION")
        corte(cut)
        return SimpleNamespace(**vars(c), revisor=revisor, base=tmp_path)
    return _build


@pytest.fixture()
def rollbacks(db_session, monkeypatch):
    llamadas = []
    original = db_session.rollback

    def _contado():
        llamadas.append(1)
        return original()
    monkeypatch.setattr(db_session, "rollback", _contado)
    return llamadas


def _subir(db, c):
    return DocumentService.save(db, c.process, TIPO, raw=PDF, original_name="anexo.pdf",
                                content_type="application/pdf", uploaded_by_id=c.student.id)


def _fase(db, c):
    db.expire_all()
    return (db.query(ProcessPhase)
            .filter_by(process_id=c.process.id, phase_number=c.anexo_phase).one())


def _doc(db, c):
    db.expire_all()
    return db.query(Document).filter_by(process_id=c.process.id, type_code=TIPO).first()


def _anexo(db, c):
    db.expire_all()
    return db.query(Anexo).filter_by(process_id=c.process.id).first()


def _contador(db):
    from itcj2.apps.titulatec.models import AnexoCounter
    db.expire_all()
    return {x.semester: x.last_value for x in db.query(AnexoCounter).all()}


def _eventos(db, c, tipo):
    return (db.query(ProcessEvent).filter_by(process_id=c.process.id, event_type=tipo)
            .order_by(ProcessEvent.id).all())


def _acciones(db, action, c=None):
    from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog
    db.flush()
    q = audit_query(db).filter_by(source="action", action=action)
    if c is not None:
        q = q.filter_by(process_id=c.process.id)
    return q.order_by(TitulatecAuditLog.id).all()


def _archivos(base):
    return {p for p in base.rglob("*") if p.is_file()}


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


def _forzar(db, c, *, listo=False, reimpresion=False):
    """Escribe las columnas de entrega a mano (tabla de etapas)."""
    a = AnexoService.get(db, c.process.id)
    a.ready_at = datetime(2026, 10, 1, 9, 0) if listo else None
    a.reprint_requested_at = datetime(2026, 10, 2, 9, 0) if reimpresion else None
    a.reprint_reason = "Sello ilegible" if reimpresion else None
    db.flush()


def _reimpresion(db, c, motivo="  Sello ilegible  "):
    """listo -> sube -> Titulacion observa con reimpresion."""
    _subir(db, c)
    AnexoService.observe(db, c.process, c.revisor.id, reason=motivo, reprint=True)


# ---------------------------------------------------------------------------
# 1. Etapas (spec §4)
# ---------------------------------------------------------------------------
class TestEtapas:
    @pytest.mark.parametrize("estado,listo,reimpresion,esperada", [
        ("in_progress", False, False, "preparing"),
        ("in_progress", True, False, "ready"),
        ("in_review", True, False, "in_review"),
        ("rejected", True, False, "observed"),
        ("rejected", False, True, "reprint"),        # traslape: reimpresion gana a rejected
        ("in_progress", False, True, "reprint"),
        ("in_review", False, True, "reprint"),       # regla 2 antes que la 3
        ("approved", True, False, "approved"),
        ("approved", False, True, "approved"),       # aprobado gana a todo
    ])
    def test_tabla(self, db_session, caso, estado, listo, reimpresion, esperada):
        c = caso(phase_status=estado, folio=True)
        _forzar(db_session, c, listo=listo, reimpresion=reimpresion)

        assert AnexoService.stage(db_session, c.process) == esperada
        assert AnexoService.stage_map(db_session, [c.process.id]) == {c.process.id: esperada}
        assert esperada in anexo_service.STAGES and esperada in anexo_service.STAGE_LABELS

    def test_sin_fila_esta_en_preparacion(self, db_session, caso):
        c = caso()
        assert AnexoService.get(db_session, c.process.id) is None
        assert AnexoService.stage(db_session, c.process) == "preparing"

    def test_etiquetas(self):
        assert anexo_service.STAGES == ("preparing", "reprint", "ready", "in_review",
                                        "observed", "approved")
        assert anexo_service.STAGE_LABELS == {
            "preparing": "En preparación", "reprint": "Reimpresión", "ready": "Por recoger",
            "in_review": "En revisión", "observed": "Con observaciones",
            "approved": "Aprobado"}

    def test_none_si_no_aplica(self, db_session, caso, corte):
        a = caso()
        b = caso()
        b.process.current_phase = b.review_phase           # no alcanzado
        s = caso(phase_status="skipped")                   # EGEL / saltada
        db_session.flush()
        ids = [a.process.id, b.process.id, s.process.id]

        assert AnexoService.stage(db_session, b.process) is None
        assert AnexoService.stage(db_session, s.process) is None
        assert AnexoService.stage(db_session, None) is None
        assert AnexoService.stage_map(db_session, ids) == {a.process.id: "preparing"}
        corte(3)
        assert AnexoService.stage(db_session, a.process) is None
        assert AnexoService.stage_map(db_session, ids) == {}

    def test_stage_map_es_stage_por_proceso_sin_n_mas_1(self, db_session, caso):
        casos = [caso(), caso(listo=True), caso(listo=True), caso(phase_status="approved")]
        _subir(db_session, casos[2])                       # in_review
        ids = [x.process.id for x in casos]

        uno, sql_uno = _contar(db_session, lambda: AnexoService.stage_map(db_session, ids[:1]))
        todos, sql_todos = _contar(db_session, lambda: AnexoService.stage_map(db_session, ids))

        assert len(sql_todos) <= 3 and len(sql_todos) == len(sql_uno)
        assert todos == {x.process.id: AnexoService.stage(db_session, x.process) for x in casos}
        assert list(todos.values()) == ["preparing", "ready", "in_review", "approved"]
        assert uno == {ids[0]: "preparing"}
        vacio, sql_vacio = _contar(db_session, lambda: AnexoService.stage_map(db_session, []))
        assert vacio == {} and sql_vacio == []

    def test_recorrido_completo(self, db_session, caso):
        c = caso()

        def etapa():
            return AnexoService.stage(db_session, c.process)

        assert etapa() == "preparing"
        AnexoService.mark_ready(db_session, c.process, c.coordinator.id, NOTA)
        assert etapa() == "ready"
        _subir(db_session, c)
        assert etapa() == "in_review"
        AnexoService.observe(db_session, c.process, c.revisor.id, reason="Sello", reprint=True)
        assert etapa() == "reprint"
        AnexoService.mark_ready(db_session, c.process, c.coordinator.id, NOTA)
        assert etapa() == "ready"
        _subir(db_session, c)
        assert etapa() == "in_review"
        AnexoService.observe(db_session, c.process, c.revisor.id, reason="Falta una firma")
        assert etapa() == "observed"
        _subir(db_session, c)
        assert etapa() == "in_review"
        AnexoService.approve(db_session, c.process, c.revisor.id)
        assert etapa() == "approved"


# ---------------------------------------------------------------------------
# 2. Marcar listo para recoger
# ---------------------------------------------------------------------------
class TestMarcarListo:
    def test_emite_el_folio_y_queda_listo(self, db_session, caso, correos):
        c = caso()

        out = AnexoService.mark_ready(db_session, c.process, c.coordinator.id,
                                      f"  {NOTA}  ")

        assert out["first"] is True and out["changed"] is True
        a = _anexo(db_session, c)
        assert out["anexo"].id == a.id and a.folio.startswith("AIII-")
        assert a.ready_at is not None and a.ready_by_id == c.coordinator.id
        assert a.pickup_note == NOTA
        assert AnexoService.stage(db_session, c.process) == "ready"
        assert len(_eventos(db_session, c, "anexo_iii_issued")) == 1
        (ev,) = _eventos(db_session, c, "anexo_iii_ready")
        assert ev.payload == {"folio": a.folio, "note": NOTA, "first": True}
        assert ev.phase_number == c.anexo_phase and ev.actor_id == c.coordinator.id
        (acc,) = _acciones(db_session, "anexo_iii.ready", c)
        assert acc.payload["folio"] == a.folio and acc.payload["first"] is True
        assert correos == [{"process_id": c.process.id, "folio": a.folio, "note": NOTA}]

    @pytest.mark.parametrize("nota", [None, "", "   \n "])
    def test_nota_obligatoria(self, db_session, caso, correos, nota):
        c = caso()
        antes = _contador(db_session)
        with pytest.raises(ValueError) as exc:
            AnexoService.mark_ready(db_session, c.process, c.coordinator.id, nota)
        assert str(exc.value) == anexo_service.NOTE_REQUIRED_MSG
        assert _anexo(db_session, c) is None and _contador(db_session) == antes
        assert _eventos(db_session, c, "anexo_iii_ready") == [] and correos == []

    def test_nota_hasta_300(self, db_session, caso):
        c = caso()
        with pytest.raises(ValueError) as exc:
            AnexoService.mark_ready(db_session, c.process, c.coordinator.id, "x" * 301)
        assert str(exc.value) == anexo_service.NOTE_TOO_LONG_MSG
        assert _anexo(db_session, c) is None
        AnexoService.mark_ready(db_session, c.process, c.coordinator.id, "x" * 300)
        assert _anexo(db_session, c).pickup_note == "x" * 300

    def test_remarcar_solo_cambia_la_nota_review_focus_2(self, db_session, caso, correos):
        """Doble clic: un solo correo y una sola fila de evento «primera vez»."""
        c = caso()
        AnexoService.mark_ready(db_session, c.process, c.coordinator.id, NOTA)
        listo_desde = _anexo(db_session, c).ready_at

        out = AnexoService.mark_ready(db_session, c.process, c.coordinator.id, "Sala 2")

        assert out["first"] is False and out["changed"] is True
        a = _anexo(db_session, c)
        assert a.pickup_note == "Sala 2" and a.ready_at == listo_desde
        assert len(correos) == 1
        eventos = _eventos(db_session, c, "anexo_iii_ready")
        assert [e.payload["first"] for e in eventos] == [True, False]
        assert eventos[1].payload["note"] == "Sala 2"
        assert len(_eventos(db_session, c, "anexo_iii_issued")) == 1

    def test_remarcar_con_la_misma_nota_no_escribe(self, db_session, caso, correos):
        c = caso()
        AnexoService.mark_ready(db_session, c.process, c.coordinator.id, NOTA)
        db_session.commit()

        out, sql = _contar(db_session, lambda: AnexoService.mark_ready(
            db_session, c.process, c.coordinator.id, f"  {NOTA} "))

        assert out == {"anexo": out["anexo"], "first": False, "changed": False}
        assert not [s for s in sql if s.lstrip().upper().startswith(("INSERT", "UPDATE"))]
        assert len(_eventos(db_session, c, "anexo_iii_ready")) == 1
        assert len(_acciones(db_session, "anexo_iii.ready", c)) == 1
        assert len(correos) == 1

    @pytest.mark.parametrize("vista,real", [("preparing", "ready"), ("ready", "in_review"),
                                            ("reprint", "preparing")])
    def test_formulario_viejo_no_escribe(self, db_session, caso, correos, rollbacks,
                                         vista, real):
        c = caso(listo=real != "preparing")
        if real == "in_review":
            _subir(db_session, c)
        db_session.commit()
        assert AnexoService.stage(db_session, c.process) == real
        antes = _anexo(db_session, c)
        nota_antes = antes.pickup_note if antes else None

        with pytest.raises(anexo_service.AnexoStageChanged) as exc:
            AnexoService.mark_ready(db_session, c.process, c.coordinator.id, "Otra sala",
                                    expected_stage=vista)

        assert isinstance(exc.value, ValueError)
        assert str(exc.value) == anexo_service.STAGE_CHANGED_MSG
        str(exc.value).encode("ascii")
        assert rollbacks == [1]
        despues = _anexo(db_session, c)
        assert (despues.pickup_note if despues else None) == nota_antes
        assert len(correos) == (0 if real == "preparing" else 1)

    def test_formulario_al_dia_si_marca(self, db_session, caso):
        c = caso()
        out = AnexoService.mark_ready(db_session, c.process, c.coordinator.id, NOTA,
                                      expected_stage="preparing")
        assert out["first"] is True
        out = AnexoService.mark_ready(db_session, c.process, c.coordinator.id, "Sala 9",
                                      expected_stage="ready")
        assert out["changed"] is True and _anexo(db_session, c).pickup_note == "Sala 9"

    @pytest.mark.parametrize("etapa", ["in_review", "observed", "approved"])
    def test_rechaza_otras_etapas(self, db_session, caso, correos, etapa):
        c = caso(listo=True)
        _subir(db_session, c)
        if etapa == "observed":
            AnexoService.observe(db_session, c.process, c.revisor.id, reason="Falta firma")
        elif etapa == "approved":
            AnexoService.approve(db_session, c.process, c.revisor.id)
        assert AnexoService.stage(db_session, c.process) == etapa

        with pytest.raises(ValueError) as exc:
            AnexoService.mark_ready(db_session, c.process, c.coordinator.id, "Otra")

        assert str(exc.value) == anexo_service.NOT_PREPARABLE_MSG
        assert _anexo(db_session, c).pickup_note == NOTA
        assert len(correos) == 1
        assert len(_eventos(db_session, c, "anexo_iii_ready")) == 1

    def test_corte_3_inerte(self, db_session, caso, correos):
        c = caso(cut=3)
        antes = _contador(db_session)
        with pytest.raises(ValueError) as exc:
            AnexoService.mark_ready(db_session, c.process, c.coordinator.id, NOTA)
        assert str(exc.value) == anexo_service.NOT_OPERABLE_MSG
        assert _anexo(db_session, c) is None and _contador(db_session) == antes
        assert correos == []

    def test_no_alcanzado(self, db_session, caso, rollbacks):
        c = caso()
        c.process.current_phase = c.review_phase
        db_session.commit()
        with pytest.raises(ValueError) as exc:
            AnexoService.mark_ready(db_session, c.process, c.coordinator.id, NOTA)
        assert str(exc.value) == anexo_service.NOT_REACHED_MSG
        assert rollbacks == [1], "falla bajo el bloqueo: deshace"
        assert _anexo(db_session, c) is None and _fase(db_session, c).status == "in_progress"

    def test_proceso_en_pausa(self, db_session, caso):
        c = caso()
        c.process.status = "on_hold"
        db_session.flush()
        with pytest.raises(ValueError, match="on_hold"):
            AnexoService.mark_ready(db_session, c.process, c.coordinator.id, NOTA)
        assert _anexo(db_session, c) is None

    def test_datos_incompletos_falla_cerrado_sin_folio(self, db_session, caso, correos,
                                                       rollbacks):
        from itcj2.apps.titulatec.models import SynodalAssignment
        c = caso()
        fila = (db_session.query(SynodalAssignment)
                .filter_by(process_id=c.process.id, role="vocal").one())
        fila.is_active = False
        db_session.commit()
        antes = _contador(db_session)

        with pytest.raises(ValueError) as exc:
            AnexoService.mark_ready(db_session, c.process, c.coordinator.id, NOTA)

        assert str(exc.value) == anexo_service.NO_SYNODALS_MSG
        assert rollbacks == [1]
        assert _fase(db_session, c).status == "in_progress"
        assert _anexo(db_session, c) is None and _contador(db_session) == antes
        assert correos == []

    def test_mensajes_ascii(self):
        for msg in (anexo_service.NOTE_REQUIRED_MSG, anexo_service.NOTE_TOO_LONG_MSG,
                    anexo_service.NOT_PREPARABLE_MSG, anexo_service.ANEXO_NOT_READY_MSG,
                    anexo_service.STAGE_CHANGED_MSG):
            msg.encode("ascii")
        assert anexo_service.ANEXO_NOT_READY_MSG == (
            "Tu Anexo III todavia no esta listo para recoger: aun no puedes subir el escaneo.")


# ---------------------------------------------------------------------------
# 3. Reimpresion (E4)
# ---------------------------------------------------------------------------
class TestReimpresion:
    def test_observar_con_reimpresion_regresa_a_vinculacion(self, db_session, caso):
        c = caso(listo=True)
        antes = _anexo(db_session, c)
        folio, semestre, liberado = antes.folio, antes.semester, antes.released_at

        _reimpresion(db_session, c)

        assert _doc(db_session, c).review_status == "rejected"
        assert _fase(db_session, c).status == "rejected"
        assert AnexoService.stage(db_session, c.process) == "reprint"
        a = _anexo(db_session, c)
        assert (a.folio, a.semester, a.released_at) == (folio, semestre, liberado)
        assert a.ready_at is None and a.ready_by_id is None
        assert a.reprint_reason == "Sello ilegible" and a.reprint_requested_at is not None
        assert a.pickup_note == NOTA, "se conserva para precargar la siguiente"
        (ev,) = _eventos(db_session, c, "anexo_iii_reprint_requested")
        assert ev.payload == {"folio": folio, "reason": "Sello ilegible"}
        assert ev.actor_id == c.revisor.id
        assert len(_eventos(db_session, c, "phase_rejected")) == 1
        (acc,) = _acciones(db_session, "anexo_iii.reprint_requested", c)
        assert acc.reason == "Sello ilegible" and acc.payload["folio"] == folio
        (rev,) = _acciones(db_session, "anexo_iii.reviewed", c)
        assert rev.payload["status"] == "rejected"

    def test_el_correo_de_la_observacion_dice_que_se_reimprime(self, db_session, caso):
        """Revisor: con reimpresion el alumno no corrige ni sube; el correo de
        fase observada lo dice (bandera `reprint` del evento `phase_rejected`)."""
        c = caso(listo=True)
        _reimpresion(db_session, c)
        (ev,) = _eventos(db_session, c, "phase_rejected")
        assert ev.payload["anexo_iii"]["reprint"] is True

        correo = _correo_fase_observada(db_session, c)

        assert correo.subject.endswith("Titulación pidió reimprimir tu Anexo III")
        assert correo.context["reprint"] is True and correo.context["reason"] == "Sello ilegible"
        html = _html_correo(correo)
        assert "no tienes que subir nada" in html and "Sello ilegible" in html
        assert "necesita correcciones" not in html

    def test_la_observacion_normal_conserva_su_correo(self, db_session, caso):
        c = caso(listo=True)
        _subir(db_session, c)
        AnexoService.observe(db_session, c.process, c.revisor.id, reason="Falta firma")
        (ev,) = _eventos(db_session, c, "phase_rejected")
        assert "reprint" not in ev.payload["anexo_iii"]

        correo = _correo_fase_observada(db_session, c)

        assert "Una fase necesita correcciones" in correo.subject
        assert correo.context["reprint"] is False
        assert "Qué hacer" in _html_correo(correo)

    def test_luego_marcar_listo_vuelve_a_por_recoger(self, db_session, caso, correos):
        c = caso(listo=True)
        folio = _anexo(db_session, c).folio
        _reimpresion(db_session, c)
        antes = _fase(db_session, c).updated_at

        out = AnexoService.mark_ready(db_session, c.process, c.coordinator.id, "Sala 3")

        assert out["first"] is True
        assert _fase(db_session, c).updated_at > antes, "clave FIFO de «Sin enviar»"
        assert AnexoService.stage(db_session, c.process) == "ready"
        a = _anexo(db_session, c)
        assert a.folio == folio and a.ready_at is not None and a.pickup_note == "Sala 3"
        assert a.reprint_reason is None and a.reprint_requested_at is None
        assert _fase(db_session, c).status == "in_progress"
        assert [x["note"] for x in correos] == [NOTA, "Sala 3"]
        _subir(db_session, c)
        assert AnexoService.stage(db_session, c.process) == "in_review"

    def test_observar_sin_reimpresion_no_toca_la_entrega(self, db_session, caso):
        c = caso(listo=True)
        _subir(db_session, c)
        AnexoService.observe(db_session, c.process, c.revisor.id, reason="Falta firma")
        a = _anexo(db_session, c)
        assert a.ready_at is not None and a.reprint_requested_at is None
        assert AnexoService.stage(db_session, c.process) == "observed"
        assert _eventos(db_session, c, "anexo_iii_reprint_requested") == []

    def test_review_focus_5_version_cambiada_no_escribe(self, db_session, caso):
        """El alumno reemplazo el escaneo (borrar + subir) mientras Titulacion
        lo veia: observar con reimpresion sobre la version vieja no escribe."""
        c = caso(listo=True)
        _subir(db_session, c)
        DocumentService.delete(db_session, c.process.id, TIPO, actor_id=c.student.id)
        _subir(db_session, c)
        assert _doc(db_session, c).version == 2

        with pytest.raises(anexo_service.AnexoVersionChanged):
            AnexoService.observe(db_session, c.process, c.revisor.id, reason="Sello",
                                 expected_version=1, reprint=True)

        doc = _doc(db_session, c)
        assert doc.review_status == "pending" and doc.version == 2
        assert _fase(db_session, c).status == "in_review"
        a = _anexo(db_session, c)
        assert a.ready_at is not None and a.reprint_requested_at is None
        assert _eventos(db_session, c, "anexo_iii_reprint_requested") == []
        assert _acciones(db_session, "anexo_iii.reprint_requested", c) == []

    def test_reimpresion_sin_folio_falla_cerrado(self, db_session, caso, make_document,
                                                 rollbacks):
        """Dato heredado de la v1 (escaneo sin folio): no hay que reimprimir."""
        c = caso(phase_status="in_review")
        make_document(c.process, type_code=TIPO, phase_number=c.anexo_phase)
        db_session.commit()
        with pytest.raises(ValueError) as exc:
            AnexoService.observe(db_session, c.process, c.revisor.id, reason="Sello",
                                 reprint=True)
        assert str(exc.value) == anexo_service.NO_FOLIO_REPRINT_MSG
        str(exc.value).encode("ascii")
        assert rollbacks == [1]
        assert _doc(db_session, c).review_status == "pending"
        assert _fase(db_session, c).status == "in_review"

    def test_reimpresion_sin_motivo_no_escribe(self, db_session, caso):
        c = caso(listo=True)
        _subir(db_session, c)
        with pytest.raises(ValueError) as exc:
            AnexoService.observe(db_session, c.process, c.revisor.id, reason="  ",
                                 reprint=True)
        assert str(exc.value) == anexo_service.REASON_REQUIRED_MSG
        assert _anexo(db_session, c).reprint_requested_at is None
        assert _fase(db_session, c).status == "in_review"


def _correo_fase_observada(db, c):
    from itcj2.apps.titulatec.models.email_outbox import EmailOutbox
    from itcj2.apps.titulatec.services.mail_compose import MailComposer
    from itcj2.core.models.user import User

    filas = (db.query(EmailOutbox)
             .filter_by(process_id=c.process.id, kind="phase_rejected")
             .order_by(EmailOutbox.id).all())
    assert filas, "reject_phase no encolo el correo"
    return MailComposer.compose(db, filas[-1:], c.process, db.get(User, c.student.id))


def _html_correo(correo):
    from jinja2 import StrictUndefined

    from itcj2.apps.titulatec.pages.nav import titulatec_templates
    env = titulatec_templates.env.overlay(undefined=StrictUndefined)
    return env.get_template(f"titulatec/email/{correo.template}").render(**correo.context)


# ---------------------------------------------------------------------------
# 4. Guarda de subida (anti-objetivo 2): servicio y las dos rutas del alumno
# ---------------------------------------------------------------------------
class TestGuardaDeSubida:
    @pytest.mark.parametrize("etapa", ["preparing", "reprint"])
    def test_el_servicio_rechaza_bajo_el_bloqueo(self, db_session, caso, etapa):
        c = caso(listo=etapa != "preparing")
        if etapa == "reprint":
            _reimpresion(db_session, c)
        assert AnexoService.stage(db_session, c.process) == etapa
        antes_doc = _doc(db_session, c)
        antes = ((antes_doc.version, antes_doc.review_status) if antes_doc else None)
        archivos = _archivos(c.base)

        with pytest.raises(ValueError) as exc:
            _subir(db_session, c)

        assert str(exc.value) == anexo_service.ANEXO_NOT_READY_MSG
        despues = _doc(db_session, c)
        assert ((despues.version, despues.review_status) if despues else None) == antes
        assert _archivos(c.base) == archivos

    def test_en_revision_si_se_reemplaza_y_va_al_final(self, db_session, caso):
        """Ruling 2026-10-29: reemplazar el escaneo sin dictamen sigue
        permitido (C6 del v1); `sync_phase` lo manda al final de la cola."""
        c = caso(listo=True)
        _subir(db_session, c)
        assert AnexoService.stage(db_session, c.process) == "in_review"
        viejo = datetime(2026, 1, 1, 8, 0)
        _fase(db_session, c).updated_at = viejo
        db_session.flush()

        _subir(db_session, c)

        assert _doc(db_session, c).version == 2
        fase = _fase(db_session, c)
        assert fase.status == "in_review" and fase.updated_at > viejo
        assert anexo_service.UPLOAD_STAGES == ("ready", "observed", "in_review")

    def test_review_focus_1_reimpresion_por_las_dos_rutas(self, db_session, caso, client_as,
                                                          make_role, patched_session_local):
        c = caso(listo=True)
        _reimpresion(db_session, c)
        make_role(ROLE_STUDENT, PERMS_ALUMNO)
        db_session.commit()
        archivos = _archivos(c.base)
        cli = client_as(c.student)
        archivo = {"archivo": ("anexo.pdf", PDF, "application/pdf")}

        generica = cli.post("/titulatec/student/documents/" + TIPO, files=archivo)
        dedicada = cli.post("/titulatec/student/anexo/escaneo", files=archivo)

        # La generica contesta como con todo `ValueError` del servicio (200 +
        # X-Tt-Error, slot re-pintado); la dedicada, 400.
        assert generica.status_code == 200
        assert dedicada.status_code == 400
        for resp in (generica, dedicada):
            assert unquote(resp.headers["X-Tt-Error"]) == anexo_service.ANEXO_NOT_READY_MSG
        doc = _doc(db_session, c)
        assert doc.review_status == "rejected" and doc.version == 1
        assert _archivos(c.base) == archivos
        assert len(_eventos(db_session, c, "document_uploaded")) == 1

    def test_en_preparacion_ninguna_ruta_sube(self, db_session, caso, client_as, make_role,
                                              patched_session_local):
        c = caso()
        make_role(ROLE_STUDENT, PERMS_ALUMNO)
        db_session.commit()
        cli = client_as(c.student)
        archivo = {"archivo": ("anexo.pdf", PDF, "application/pdf")}
        for url in ("/titulatec/student/documents/" + TIPO, "/titulatec/student/anexo/escaneo"):
            resp = cli.post(url, files=archivo)
            assert unquote(resp.headers["X-Tt-Error"]) == anexo_service.ANEXO_NOT_READY_MSG
        assert _doc(db_session, c) is None and _archivos(c.base) == set()

    def test_listo_si_sube_por_la_ruta_dedicada(self, db_session, caso, client_as, make_role,
                                                patched_session_local):
        c = caso(listo=True)
        make_role(ROLE_STUDENT, PERMS_ALUMNO)
        db_session.commit()
        resp = client_as(c.student).post("/titulatec/student/anexo/escaneo",
                                         files={"archivo": ("a.pdf", PDF, "application/pdf")})
        assert resp.status_code == 200, resp.text[:300]
        assert _doc(db_session, c).review_status == "pending"
        assert AnexoService.stage(db_session, c.process) == "in_review"


# ---------------------------------------------------------------------------
# 5. Vista previa del alumno (E2)
# ---------------------------------------------------------------------------
def _html(ctx):
    from itcj2.apps.titulatec.pages.nav import titulatec_templates
    return titulatec_templates.get_template(anexo_service._TEMPLATE_NAME).render(**ctx)


class TestVistaPrevia:
    def test_review_focus_4_sin_folio_no_escribe_ni_bloquea(self, db_session, caso):
        c = caso()
        antes = _contador(db_session)

        ctx, sql = _contar(db_session, lambda: AnexoService.preview_pdf(db_session, c.process))

        assert ctx["preview"] is True and ctx["folio"] is None
        assert ctx["date_label"] == "17/Marzo/2026"
        assert not [s for s in sql if "FOR UPDATE" in s or "FOR NO KEY UPDATE" in s]
        assert not [s for s in sql if s.lstrip().upper().startswith(("INSERT", "UPDATE"))]
        assert _anexo(db_session, c) is None and _contador(db_session) == antes
        assert _eventos(db_session, c, "anexo_iii_issued") == []

    def test_con_folio_lo_muestra(self, db_session, caso):
        c = caso(folio=True)
        ctx = AnexoService.preview_pdf(db_session, c.process)
        assert ctx["preview"] is True
        assert ctx["folio"] == AnexoService.get(db_session, c.process.id).folio
        assert AnexoService.context(db_session, c.process)["preview"] is False

    def test_el_html_lleva_la_marca_de_agua(self, db_session, caso):
        c = caso()
        vista = AnexoService.preview_pdf(db_session, c.process)
        html = _html(vista)
        assert "VISTA PREVIA" in html and "Se asigna al imprimirse" in html
        assert AnexoService.render(vista).startswith(b"%PDF")     # mismo `render`
        oficial = _html(AnexoService.prepare_pdf(db_session, c.process, c.coordinator.id))
        assert "VISTA PREVIA" not in oficial

    def test_falla_cerrado(self, db_session, caso, corte):
        c = caso()
        c.process.current_phase = c.review_phase
        db_session.flush()
        with pytest.raises(ValueError) as exc:
            AnexoService.preview_pdf(db_session, c.process)
        assert str(exc.value) == anexo_service.NOT_REACHED_MSG
        corte(3)
        with pytest.raises(ValueError) as exc:
            AnexoService.preview_pdf(db_session, c.process)
        assert str(exc.value) == anexo_service.NOT_OPERABLE_MSG

    def test_nombre_de_archivo(self, db_session, caso):
        c = caso()
        nombre = AnexoService.preview_filename(db_session, c.process)
        assert nombre == f"{c.student.control_number}_ANEXO_III_VISTA_PREVIA.pdf"

    def test_la_ruta_del_alumno_sirve_la_vista_previa(self, db_session, caso, client_as,
                                                      make_role, monkeypatch,
                                                      patched_session_local):
        c = caso()
        make_role(ROLE_STUDENT, PERMS_ALUMNO)
        db_session.commit()
        pintados = []
        monkeypatch.setattr(AnexoService, "render",
                            staticmethod(lambda ctx: pintados.append(ctx) or b"%PDF-vista"))

        resp = client_as(c.student).get("/titulatec/student/anexo/pdf")

        assert resp.status_code == 200, resp.text[:300]
        assert resp.content == b"%PDF-vista"
        disp = resp.headers["content-disposition"]
        assert disp.startswith("inline") and "_ANEXO_III_VISTA_PREVIA.pdf" in disp
        assert pintados[0]["preview"] is True and pintados[0]["folio"] is None
        assert _anexo(db_session, c) is None, "la vista previa no emite folio"

    def test_sin_preview_own_no_entra(self, db_session, caso, client_as, make_role,
                                      patched_session_local):
        c = caso()
        make_role(ROLE_STUDENT, STUDENT_PERMS + ("titulatec.anexo_iii.api.generate.own",))
        db_session.commit()
        resp = client_as(c.student).get("/titulatec/student/anexo/pdf", follow_redirects=False)
        assert resp.status_code in (302, 303, 401, 403)
        assert _anexo(db_session, c) is None


# ---------------------------------------------------------------------------
# 6. Precarga de la nota (E3) e info de entrega
# ---------------------------------------------------------------------------
def _mismo_depto(db, origen, destino):
    from itcj2.apps.titulatec.models import ProgramDepartment
    db.get(ProgramDepartment, destino.process.program_id).department_id = origen.department.id
    db.flush()


class TestPrecarga:
    def test_sin_antecedente(self, db_session, caso):
        assert AnexoService.default_pickup_note(db_session, caso().process) is None

    def test_la_ultima_del_mismo_departamento(self, db_session, caso):
        a = caso(listo=True)
        b = caso(listo=True)
        _mismo_depto(db_session, a, b)
        AnexoService.mark_ready(db_session, b.process, b.coordinator.id, "Sala nueva")
        _anexo(db_session, a).ready_at = datetime(2026, 1, 1, 9, 0)
        db_session.flush()
        nuevo = caso()
        _mismo_depto(db_session, a, nuevo)
        otro = caso()

        assert AnexoService.default_pickup_note(db_session, nuevo.process) == "Sala nueva"
        assert AnexoService.default_pickup_note(db_session, otro.process) is None

    def test_la_propia_gana_tras_la_reimpresion(self, db_session, caso):
        a = caso(listo=True)
        _reimpresion(db_session, a)
        b = caso()
        _mismo_depto(db_session, a, b)
        AnexoService.mark_ready(db_session, b.process, b.coordinator.id, "Sala de b")

        assert AnexoService.default_pickup_note(db_session, a.process) == NOTA

    def test_ready_info(self, db_session, caso):
        c = caso()
        assert AnexoService.ready_info(db_session, c.process) is None
        AnexoService.mark_ready(db_session, c.process, c.coordinator.id, NOTA)
        info = AnexoService.ready_info(db_session, c.process)
        assert set(info) == {"ready_at", "ready_label", "pickup_note", "reprint_reason",
                             "reprint_requested_at", "folio"}
        assert isinstance(info["ready_at"], datetime) and isinstance(info["ready_label"], str)
        assert info["pickup_note"] == NOTA and info["folio"].startswith("AIII-")
        assert info["reprint_reason"] is None and info["reprint_requested_at"] is None


# ---------------------------------------------------------------------------
# 7. Avisos (campanas, best-effort con sesion propia)
# ---------------------------------------------------------------------------
def _avisos(db, user):
    from itcj2.core.models.notification import Notification
    db.expire_all()
    return (db.query(Notification).filter_by(user_id=user.id, app_name="titulatec")
            .order_by(Notification.id).all())


class TestAvisos:
    def test_listo_avisa_al_alumno(self, db_session, caso, patched_session_local):
        c = caso(listo=True)
        AnexoService.notify_ready(c.process.id)
        (aviso,) = [n for n in _avisos(db_session, c.student) if n.type == "ANEXO_PICKUP"]
        assert aviso.body == NOTA
        assert aviso.data["url"] == "/titulatec/student/anexo"
        assert aviso.data["process_id"] == c.process.id

    def test_sin_listo_no_avisa(self, db_session, caso, patched_session_local):
        c = caso()
        AnexoService.notify_ready(c.process.id)
        assert [n for n in _avisos(db_session, c.student) if n.type == "ANEXO_PICKUP"] == []

    def test_reimpresion_avisa_a_vinculacion(self, db_session, caso, patched_session_local):
        c = caso(listo=True)
        _reimpresion(db_session, c)
        AnexoService.notify_reprint(c.process.id)
        (aviso,) = _avisos(db_session, c.coordinator)
        assert aviso.title == "Reimprimir Anexo III"
        assert aviso.body.startswith("Reimprime el Anexo III de ")
        assert aviso.data["url"] == (
            f"/titulatec/admin/sinodales?tab=anexo&etapa=preparar&selected={c.process.id}")
        assert c.student.control_number in aviso.body
        assert _avisos(db_session, c.head) == []

    def test_liberacion_dice_prepara_el_anexo(self, db_session, caso, patched_session_local):
        c = caso()
        AnexoService.notify_release(c.process.id)
        (aviso,) = _avisos(db_session, c.coordinator)
        assert aviso.title == "Prepara el Anexo III"
        assert aviso.body.startswith("Prepara el Anexo III de ")
        assert c.student.control_number in aviso.body
        assert aviso.data["url"] == f"/titulatec/admin/sinodales?tab=anexo&selected={c.process.id}"

    def test_corte_3_no_avisa(self, db_session, caso, corte, patched_session_local):
        c = caso(listo=True)
        corte(3)
        AnexoService.notify_ready(c.process.id)
        AnexoService.notify_reprint(c.process.id)
        assert [n for n in _avisos(db_session, c.student) if n.type == "ANEXO_PICKUP"] == []
        assert _avisos(db_session, c.coordinator) == []


# ---------------------------------------------------------------------------
# 8. Textos v2 y una sola duena de la etapa
# ---------------------------------------------------------------------------
def test_quien_firma_ya_no_dice_que_el_alumno_gestiona_al_jefe(caso):
    from itcj2.apps.titulatec.services.review_service import RELEASED_TEXT

    c = caso()
    tesis = caso(modality_code="thesis")
    textos = [AnexoService.signers_text(c.process), AnexoService.signers_text(tesis.process),
              anexo_service.SIGNERS_FALLBACK_TEXT]
    assert "Presidente" in textos[0] and "4 sinodales" in textos[1]
    for t in textos:
        assert "gestiona" not in t and "ya vienen en el original" in t
    assert "Ya puedes pasar" not in RELEASED_TEXT and "vinculación preparará" in RELEASED_TEXT


_COLUMNAS_ENTREGA = {"ready_at", "ready_by_id", "reprint_reason", "reprint_requested_at"}


def _decisiones_con_columnas_de_entrega(arbol) -> list[int]:
    """Lineas donde una columna de entrega se usa para DECIDIR: en la prueba
    de un if/ternario/while/assert/comprension, como operando de una
    comparacion o un and/or, dentro de un filter/where/having, o con
    `.is_()`/`.isnot()` encima. Leerla para pintar u ordenar no cuenta."""
    import ast

    def _toca(nodo):
        return any(isinstance(n, ast.Attribute) and n.attr in _COLUMNAS_ENTREGA
                   for n in ast.walk(nodo))

    lineas = set()
    for nodo in ast.walk(arbol):
        pruebas = []
        if isinstance(nodo, (ast.If, ast.IfExp, ast.While, ast.Assert)):
            pruebas.append(nodo.test)
        elif isinstance(nodo, ast.comprehension):
            pruebas.extend(nodo.ifs)
        elif isinstance(nodo, (ast.Compare, ast.BoolOp)):
            pruebas.append(nodo)
        elif isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute):
            if nodo.func.attr in ("filter", "where", "having", "filter_by"):
                pruebas.extend(nodo.args)
                pruebas.extend(k.value for k in nodo.keywords)
            elif (nodo.func.attr in ("is_", "isnot", "is_not", "in_", "between")
                  and isinstance(nodo.func.value, ast.Attribute)
                  and nodo.func.value.attr in _COLUMNAS_ENTREGA):
                pruebas.append(nodo.func.value)
        for p in pruebas:
            if _toca(p):
                lineas.add(p.lineno)
    return sorted(lineas)


def test_nadie_fuera_de_anexo_service_decide_con_las_columnas_de_entrega():
    """Una sola duena de la etapa (spec §10, globals): fuera de
    `services/anexo_service.py` (y del modelo/migracion) ningun archivo que
    trate con el Anexo usa `ready_at`/`ready_by_id`/`reprint_*` para decidir;
    pide `AnexoService.stage`/`stage_map`/`ready_info`. Molde: el detector de
    `test_clearance_gate.py`. Solo se revisan los archivos que nombran
    `Anexo`/`AnexoService` (la biblioteca tiene su propio `ready_at`)."""
    import ast
    from pathlib import Path

    import itcj2

    raiz = Path(itcj2.__file__).resolve().parent
    permitidos = {raiz / "apps/titulatec/services/anexo_service.py",
                  raiz / "apps/titulatec/models/anexo.py"}
    archivos = [*(raiz / "apps/titulatec").rglob("*.py"), *(raiz / "cli/titulatec").rglob("*.py")]
    hallazgos = []
    for ruta in archivos:
        if ruta in permitidos:
            continue
        texto = ruta.read_text(encoding="utf-8")
        arbol = ast.parse(texto)
        nombres = {n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)}
        nombres |= {a.asname or a.name for n in ast.walk(arbol)
                    if isinstance(n, ast.ImportFrom) for a in n.names}
        if not nombres & {"Anexo", "AnexoService"}:
            continue
        for linea in _decisiones_con_columnas_de_entrega(arbol):
            hallazgos.append(f"{ruta.relative_to(raiz.parent).as_posix()}:{linea}")
    assert not hallazgos, (
        "deciden con las columnas de entrega fuera de AnexoService "
        "(usa stage/stage_map/ready_info):\n  " + "\n  ".join(hallazgos))


def test_el_detector_de_columnas_de_entrega_si_detecta():
    import ast

    malos = [
        "x = 1 if a.ready_at else 2",
        "if r.reprint_requested_at is not None: pass",
        "q.filter(Anexo.ready_at.isnot(None))",
        "ok = r.ready_by_id == 3",
        "y = [r for r in filas if r.reprint_reason]",
    ]
    buenos = [
        "q.order_by(Anexo.ready_at.asc())",
        "x = dia(r.ready_at) if etapa == 'ready' else None",
        "cols = (Anexo.ready_at.label('ready_at'),)",
    ]
    for src in malos:
        assert _decisiones_con_columnas_de_entrega(ast.parse(src)), src
    for src in buenos:
        assert not _decisiones_con_columnas_de_entrega(ast.parse(src)), src
