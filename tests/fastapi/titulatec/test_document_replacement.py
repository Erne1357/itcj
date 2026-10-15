"""Reemplazo de un documento de la fase 1 durante la cita de cotejo (spec
2026-10-15-titulatec-reemplazo-cotejo-design.md, §3-§5 y §10, parte de service).

En el cotejo (fase 2) el egresado a veces presenta en físico un documento
DISTINTO del que subió en la fase 1. La jefatura de Servicios Escolares pide el
reemplazo por una vía APARTE de `review` -- que sigue congelando el dictamen de
una fase ya pasada (`PHASE_CLOSED_MSG`) --, el alumno lo vuelve a subir y queda
«por evaluar», y aprobarlo cierra el reemplazo.

Modelo: `titulatec_documents.replacement_requested_at` no NULL = reemplazo
ABIERTO. Lo escribe SOLO `request_replacement` (la primera vez) y lo limpia SOLO
`review(status="approved")`.

Ciclo: approved -> (pide) rejected+abierto -> (sube) pending+abierto ->
(aprueba) approved, cerrado.

Lo que se fija aquí:

* la matriz de `request_replacement` (fase 1/2/3, inactivo, sin documento, sin
  motivo, fuera del set del perfil, fase 2 ya aprobada, catálogo sin la fase de
  cotejo) -- todo error con mensaje ASCII y SIN escribir nada;
* pedirlo otra vez conserva la fecha original;
* `save` conserva la bandera y deja el documento «por evaluar»;
* `review` aprueba y limpia; el rechazo por la vía normal sigue negado;
* `student_can_replace`, `open_replacements`, `replacement_gate_error`;
* `initial_docs_approved_map(..., replacement_ok=True)` y la cola del encargado;
* `approve_phase(2)` bloqueado con un reemplazo abierto y libre al aprobarlo.

La base de dev es compartida y trae datos reales: todo se siembra con las
fábricas del conftest y nada afirma totales de una tabla.
"""
from __future__ import annotations

import unicodedata
from datetime import datetime

import pytest
from sqlalchemy import event

from tests.fastapi.titulatec._pdf_samples import small_pdf
from tests.fastapi.titulatec.conftest import INITIAL_DOC_TYPES, POSGRADO_DOC_TYPES

_BASE = ("birth_certificate", "high_school_cert", "curp")
_HACE_TIEMPO = datetime(2026, 10, 1, 9, 30)


# ---------------------------------------------------------------------------
# Andamiaje
# ---------------------------------------------------------------------------
@pytest.fixture()
def espias(monkeypatch):
    """Aviso in-app y correo, registrados en vez de enviados."""
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    avisos, correos = [], []
    monkeypatch.setattr("itcj2.apps.titulatec.services.notify.notify_student",
                        lambda db, student_id, **kw: avisos.append((student_id, kw)))
    monkeypatch.setattr(StudentMail, "doc_reviewed",
                        staticmethod(lambda db, process, **kw:
                                     correos.append((process.id, kw)) or True))
    return {"avisos": avisos, "correos": correos}


@pytest.fixture()
def esc(db_session, seed_phase_defs, seed_document_types, make_cohort, make_student,
        make_process, make_document, make_user, espias):
    """Proceso en la fase 2 (por omisión) con los 3 documentos base aprobados."""
    seed_phase_defs()
    seed_document_types(types=INITIAL_DOC_TYPES + POSGRADO_DOC_TYPES)
    cohort = make_cohort()
    jefa = make_user(first_name="JEFA", last_name="REEMPLAZO")

    def _build(current_phase=2, status="active", estados=("approved",) * 3,
               program=None, abiertos=()):
        student = make_student()
        proc = make_process(student, cohort=cohort, program=program,
                            current_phase=current_phase, status=status)
        docs = {}
        for code, st in zip(_BASE, estados):
            if st is None:
                continue
            docs[code] = make_document(
                proc, type_code=code, review_status=st,
                replacement_requested_at=(_HACE_TIEMPO if code in abiertos else None))
        return proc, docs, student

    return {"build": _build, "jefa": jefa, **espias}


def _pedir(db, proc, code="curp", note="El acta fisica es otra", actor=None, esc=None):
    from itcj2.apps.titulatec.services.document_service import DocumentService
    return DocumentService.request_replacement(
        db, proc.id, code, note=note, actor_id=(actor or esc["jefa"]).id)


def _doc(db, process_id, code="curp"):
    """Relee la fila. `flush()` ANTES de expirar: un cambio que el service dejó
    en memoria antes de lanzar se vería aquí (expirar a secas lo descartaría y
    la negativa pasaría sin probar nada)."""
    from itcj2.apps.titulatec.models import Document
    db.flush()
    db.expire_all()
    return db.query(Document).filter_by(process_id=process_id, type_code=code).one()


def _nombre(db, code):
    from itcj2.apps.titulatec.models import DocumentType
    return db.query(DocumentType.name).filter_by(code=code).scalar()


def _eventos(db, process_id, event_type):
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db.query(ProcessEvent)
            .filter_by(process_id=process_id, event_type=event_type)
            .order_by(ProcessEvent.id).all())


def _es_ascii(msg: str) -> bool:
    return msg == unicodedata.normalize("NFKD", msg).encode("ascii", "ignore").decode()


def _contar(db_session, fn):
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


# ---------------------------------------------------------------------------
# request_replacement: el camino feliz y sus efectos
# ---------------------------------------------------------------------------
class TestPedirReemplazo:
    def test_en_la_fase_2_rechaza_abre_y_deja_rastro(self, db_session, esc):
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        proc, _docs, student = esc["build"]()
        jefa = esc["jefa"]

        doc = _pedir(db_session, proc, "curp", note="  El acta fisica es otra  ", esc=esc)

        doc = _doc(db_session, proc.id)
        assert doc.review_status == "rejected"
        assert doc.review_note == "El acta fisica es otra"          # con strip()
        assert doc.reviewed_by_id == jefa.id
        assert doc.replacement_requested_at is not None

        fase_cotejo = PhaseService.phase_number_for_code(db_session, "review_appointment")
        eventos = _eventos(db_session, proc.id, "document_replacement_requested")
        assert [(e.actor_id, e.phase_number, e.payload) for e in eventos] == [
            (jefa.id, fase_cotejo, {"type_code": "curp", "note": "El acta fisica es otra"})]

        assert esc["avisos"] == [(student.id, {
            "type": "DOCUMENT_REPLACEMENT_REQUESTED",
            "title": "Servicios Escolares te pidió reemplazar un documento",
            "body": f"{_nombre(db_session, 'curp')}: El acta fisica es otra",
            "process_id": proc.id,
            "phase_number": fase_cotejo,
        })]
        assert esc["correos"] == [(proc.id, {
            "type_code": "curp", "doc_name": _nombre(db_session, "curp"),
            "status": "rejected", "note": "El acta fisica es otra",
        })]

    def test_pedirlo_otra_vez_conserva_la_fecha_original(self, db_session, esc,
                                                         make_user):
        proc, _docs, _ = esc["build"](estados=("approved", "approved", "rejected"),
                                      abiertos=("curp",))
        otra = make_user(first_name="OTRA", last_name="JEFA")

        _pedir(db_session, proc, "curp", note="Sigue sin sello", actor=otra)

        doc = _doc(db_session, proc.id)
        assert doc.replacement_requested_at == _HACE_TIEMPO
        assert (doc.review_status, doc.review_note, doc.reviewed_by_id) == (
            "rejected", "Sigue sin sello", otra.id)

    def test_desde_pendiente_abierto_se_puede_pedir_de_nuevo(self, db_session, esc):
        """El alumno subió el archivo equivocado: la jefa lo vuelve a pedir."""
        proc, _docs, _ = esc["build"](estados=("approved", "approved", "pending"),
                                      abiertos=("curp",))

        _pedir(db_session, proc, "curp", note="Subiste el de otra persona", esc=esc)

        doc = _doc(db_session, proc.id)
        assert doc.review_status == "rejected"
        assert doc.replacement_requested_at == _HACE_TIEMPO

    def test_tambien_un_extra_de_posgrado(self, db_session, esc, make_program,
                                          make_document):
        proc, _docs, _ = esc["build"](program=make_program("Maestria Reemplazo T1",
                                                           level="maestria"))
        make_document(proc, type_code="efirma_sat", review_status="approved")

        _pedir(db_session, proc, "efirma_sat", note="Cita del SAT vencida", esc=esc)

        assert _doc(db_session, proc.id, "efirma_sat").replacement_requested_at is not None

    def test_la_bitacora_lo_espeja_con_la_jefa_como_actor(self, audit_mark, db_session,
                                                           esc):
        from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog
        from tests.fastapi.titulatec.conftest import audit_query
        proc, _docs, _ = esc["build"]()

        _pedir(db_session, proc, "curp", esc=esc)

        espejo = [(r.action, r.actor_id) for r in audit_query(db_session).filter(
            TitulatecAuditLog.process_id == proc.id,
            TitulatecAuditLog.source == "process_event")]
        assert ("process.document_replacement_requested", esc["jefa"].id) in espejo


# ---------------------------------------------------------------------------
# request_replacement: la matriz de negativas (nada se escribe)
# ---------------------------------------------------------------------------
class TestPedirReemplazoNegativas:
    def _sin_cambios(self, db, proc, code="curp", estado="approved"):
        doc = _doc(db, proc.id, code)
        assert (doc.review_status, doc.replacement_requested_at) == (estado, None)
        assert _eventos(db, proc.id, "document_replacement_requested") == []

    @pytest.mark.parametrize("fase", [1, 3])
    def test_fuera_de_la_fase_de_cotejo(self, db_session, esc, fase):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"](current_phase=fase)

        with pytest.raises(ValueError) as exc:
            _pedir(db_session, proc, esc=esc)

        assert str(exc.value) == DocumentService.REPLACEMENT_NOT_COTEJO_MSG
        self._sin_cambios(db_session, proc)
        assert esc["avisos"] == [] and esc["correos"] == []

    @pytest.mark.parametrize("estado", ["on_hold", "completed", "cancelled"])
    def test_proceso_no_activo(self, db_session, esc, estado):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"](status=estado)

        with pytest.raises(ValueError) as exc:
            _pedir(db_session, proc, esc=esc)

        assert str(exc.value) == DocumentService.REPLACEMENT_INACTIVE_MSG
        self._sin_cambios(db_session, proc)

    def test_sin_documento(self, db_session, esc):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"](estados=("approved", "approved", None))

        with pytest.raises(ValueError) as exc:
            _pedir(db_session, proc, "curp", esc=esc)

        assert str(exc.value) == DocumentService.REPLACEMENT_NO_DOC_MSG
        assert _eventos(db_session, proc.id, "document_replacement_requested") == []

    @pytest.mark.parametrize("motivo", [None, "", "   \n\t "])
    def test_sin_motivo(self, db_session, esc, motivo):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"]()

        with pytest.raises(ValueError) as exc:
            _pedir(db_session, proc, note=motivo, esc=esc)

        assert str(exc.value) == DocumentService.REPLACEMENT_NOTE_REQUIRED_MSG
        self._sin_cambios(db_session, proc)

    def test_motivo_de_mas_de_1000(self, db_session, esc):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"]()

        with pytest.raises(ValueError) as exc:
            _pedir(db_session, proc, note="x" * 1001, esc=esc)
        assert str(exc.value) == DocumentService.REPLACEMENT_NOTE_TOO_LONG_MSG
        self._sin_cambios(db_session, proc)

        # 1000 exactos (tras el strip) sí entran.
        _pedir(db_session, proc, note="  " + "x" * 1000 + "  ", esc=esc)
        assert _doc(db_session, proc.id).review_note == "x" * 1000

    def test_fuera_del_set_del_perfil(self, db_session, esc, make_document):
        """Licenciatura: un extra de posgrado no es de SU fase 1."""
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"]()
        make_document(proc, type_code="efirma_sat", review_status="approved")

        with pytest.raises(ValueError) as exc:
            _pedir(db_session, proc, "efirma_sat", esc=esc)

        assert str(exc.value) == DocumentService.REPLACEMENT_NOT_INITIAL_MSG
        self._sin_cambios(db_session, proc, "efirma_sat")

    def test_tipo_desconocido(self, db_session, esc):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"]()

        with pytest.raises(ValueError) as exc:
            _pedir(db_session, proc, "no_existe_t1", esc=esc)

        assert str(exc.value) == DocumentService.REPLACEMENT_NOT_INITIAL_MSG

    def test_con_la_fase_2_ya_aprobada(self, db_session, esc):
        from itcj2.apps.titulatec.models import ProcessPhase
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"]()
        (db_session.query(ProcessPhase)
         .filter_by(process_id=proc.id, phase_number=2).one()).status = "approved"
        db_session.flush()

        with pytest.raises(ValueError) as exc:
            _pedir(db_session, proc, esc=esc)

        assert str(exc.value) == DocumentService.REPLACEMENT_COTEJO_CLOSED_MSG
        self._sin_cambios(db_session, proc)

    def test_sin_la_fase_de_cotejo_en_el_catalogo_falla_cerrado(self, db_session, esc,
                                                                monkeypatch):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        proc, _docs, _ = esc["build"]()
        original = PhaseService.phase_number_for_code
        monkeypatch.setattr(PhaseService, "phase_number_for_code", staticmethod(
            lambda db, code: None if code == "review_appointment" else original(db, code)))

        with pytest.raises(ValueError) as exc:
            _pedir(db_session, proc, esc=esc)

        assert str(exc.value) == DocumentService.REPLACEMENT_NOT_COTEJO_MSG
        self._sin_cambios(db_session, proc)

    def test_proceso_inexistente(self, db_session, esc):
        from itcj2.apps.titulatec.services.document_service import DocumentService

        with pytest.raises(ValueError) as exc:
            DocumentService.request_replacement(db_session, 987654321, "curp",
                                                note="x", actor_id=esc["jefa"].id)
        assert str(exc.value) == DocumentService.REPLACEMENT_NO_PROCESS_MSG

    def test_todos_los_mensajes_son_ascii(self):
        """Viajan por `X-Tt-Error` (latin-1 en Starlette, UTF-8 en el TestClient)."""
        from itcj2.apps.titulatec.services.document_service import DocumentService

        mensajes = {n: getattr(DocumentService, n) for n in dir(DocumentService)
                    if n.startswith("REPLACEMENT_") and n.endswith("_MSG")}
        assert len(mensajes) >= 7, sorted(mensajes)
        for nombre, msg in mensajes.items():
            msg.encode("latin-1")
            assert _es_ascii(msg), nombre


# ---------------------------------------------------------------------------
# save / review
# ---------------------------------------------------------------------------
class TestResubirYAprobar:
    def test_resubir_conserva_la_bandera_y_queda_por_evaluar(self, db_session, esc,
                                                             tmp_path, monkeypatch):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
        proc, _docs, student = esc["build"]()
        _pedir(db_session, proc, "curp", esc=esc)
        abierto_en = _doc(db_session, proc.id).replacement_requested_at

        DocumentService.save(db_session, proc, "curp", raw=small_pdf(),
                             original_name="curp-nueva.pdf",
                             content_type="application/pdf",
                             uploaded_by_id=student.id)

        doc = _doc(db_session, proc.id)
        assert doc.review_status == "pending"
        assert doc.replacement_requested_at == abierto_en
        assert doc.reviewed_by_id is None

    @pytest.mark.parametrize("estado", ["rejected", "pending"])
    def test_aprobar_cierra_el_reemplazo(self, db_session, esc, estado):
        """`rejected`+abierto aprobado sin resubida = «el original sí sirve»."""
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"](estados=("approved", "approved", estado),
                                      abiertos=("curp",))

        assert DocumentService.review(db_session, proc.id, "curp", status="approved",
                                      note=None, reviewer_id=esc["jefa"].id) is True

        doc = _doc(db_session, proc.id)
        assert (doc.review_status, doc.replacement_requested_at) == ("approved", None)
        [ev] = _eventos(db_session, proc.id, "document_approved")
        assert ev.payload == {"type_code": "curp", "note": None, "replacement": True}

    def test_aprobar_sin_reemplazo_no_marca_el_evento(self, db_session, esc):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"](current_phase=1,
                                      estados=("approved", "approved", "pending"))

        DocumentService.review(db_session, proc.id, "curp", status="approved",
                               note=None, reviewer_id=esc["jefa"].id)

        [ev] = _eventos(db_session, proc.id, "document_approved")
        assert ev.payload == {"type_code": "curp", "note": None}

    def test_rechazar_por_la_via_normal_sigue_negado_en_la_fase_2(self, db_session, esc):
        """La vía de la jefa es APARTE: `review` no cambia su congelado."""
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"](estados=("approved", "approved", "pending"),
                                      abiertos=("curp",))

        with pytest.raises(ValueError) as exc:
            DocumentService.review(db_session, proc.id, "curp", status="rejected",
                                   note="Ilegible", reviewer_id=esc["jefa"].id)

        assert str(exc.value) == DocumentService.PHASE_CLOSED_MSG
        doc = _doc(db_session, proc.id)
        assert (doc.review_status, doc.replacement_requested_at) == ("pending", _HACE_TIEMPO)


# ---------------------------------------------------------------------------
# student_can_replace / open_replacements / replacement_gate_error
# ---------------------------------------------------------------------------
class TestLecturas:
    @pytest.mark.parametrize("fase,estado,doc_estado,abierto,esperado", [
        (2, "active", "rejected", True, True),
        (2, "active", "pending", True, True),
        (2, "active", "approved", False, False),     # cerrado
        (2, "active", "rejected", False, False),     # rechazado sin reemplazo
        (1, "active", "rejected", True, False),      # fase 1: la vía normal
        (3, "active", "rejected", True, False),
        (2, "on_hold", "rejected", True, False),
        (2, "cancelled", "rejected", True, False),
    ])
    def test_student_can_replace(self, db_session, esc, fase, estado, doc_estado,
                                 abierto, esperado):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"](current_phase=fase, status=estado,
                                      estados=("approved", "approved", doc_estado),
                                      abiertos=("curp",) if abierto else ())

        assert DocumentService.student_can_replace(db_session, proc, "curp") is esperado

    def test_student_can_replace_sin_proceso_o_sin_documento(self, db_session, esc):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"](estados=("approved", "approved", None))

        assert DocumentService.student_can_replace(db_session, None, "curp") is False
        assert DocumentService.student_can_replace(db_session, proc, "curp") is False

    def test_open_replacements_en_orden_del_set_y_con_sus_datos(self, db_session, esc):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"](estados=("pending", "approved", "rejected"))
        # Se piden en desorden: la lista sale en el orden del set (acta antes que CURP).
        _pedir(db_session, proc, "curp", note="Sin sello", esc=esc)
        _pedir(db_session, proc, "birth_certificate", note="Es otra acta", esc=esc)

        filas, sentencias = _contar(
            db_session, lambda: DocumentService.open_replacements(db_session, proc.id))

        assert [(f["type_code"], f["name"], f["status"], f["note"]) for f in filas] == [
            ("birth_certificate", _nombre(db_session, "birth_certificate"), "rejected",
             "Es otra acta"),
            ("curp", _nombre(db_session, "curp"), "rejected", "Sin sello"),
        ]
        assert all(isinstance(f["requested_at"], datetime) for f in filas)
        assert len(sentencias) <= 2, sentencias

    def test_open_replacements_vacio_con_una_consulta(self, db_session, esc):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"]()

        filas, sentencias = _contar(
            db_session, lambda: DocumentService.open_replacements(db_session, proc.id))

        assert filas == []
        assert len(sentencias) == 1, sentencias

    def test_replacement_gate_error_nombra_los_documentos(self, db_session, esc):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"](estados=("rejected", "approved", "pending"),
                                      abiertos=("birth_certificate", "curp"))
        db_session.expire_all()

        assert DocumentService.replacement_gate_error(db_session, proc) == (
            "No se puede liberar la fase 02: falta aprobar el reemplazo de: "
            f"{_nombre(db_session, 'birth_certificate')}, {_nombre(db_session, 'curp')}.")

    def test_replacement_gate_error_sin_reemplazos(self, db_session, esc):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"]()

        assert DocumentService.replacement_gate_error(db_session, proc) is None


# ---------------------------------------------------------------------------
# initial_docs_approved_map(..., replacement_ok) y la cola del encargado
# ---------------------------------------------------------------------------
class TestMapaYCola:
    def test_replacement_ok_cuenta_el_abierto_como_aprobado(self, db_session, esc):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        abierto_rech, _, _ = esc["build"](estados=("approved", "approved", "rejected"),
                                          abiertos=("curp",))
        abierto_pend, _, _ = esc["build"](estados=("approved", "approved", "pending"),
                                          abiertos=("curp",))
        rechazado, _, _ = esc["build"](estados=("approved", "approved", "rejected"))
        completo, _, _ = esc["build"]()
        procs = [abierto_rech, abierto_pend, rechazado, completo]

        estricto, q_estricto = _contar(
            db_session, lambda: DocumentService.initial_docs_approved_map(db_session, procs))
        flexible, q_flexible = _contar(
            db_session, lambda: DocumentService.initial_docs_approved_map(
                db_session, procs, replacement_ok=True))

        assert [estricto[p.id] for p in procs] == [False, False, False, True]
        assert [flexible[p.id] for p in procs] == [True, True, False, True]
        assert len(q_estricto) == len(q_flexible)
        # La firma de un solo proceso sigue siendo la regla estricta.
        assert DocumentService.initial_docs_all_approved(db_session, abierto_rech.id) is False

    def test_la_cola_del_encargado_no_atrasa_por_un_reemplazo(
            self, db_session, esc, make_program, make_survey_review):
        """D2: agendar NO se bloquea por un reemplazo abierto."""
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService
        prog = make_program("Ingenieria Reemplazo Cola T1")
        con_reemplazo, _, _ = esc["build"](program=prog,
                                           estados=("approved", "approved", "rejected"),
                                           abiertos=("curp",))
        sin_reemplazo, _, _ = esc["build"](program=prog,
                                           estados=("approved", "approved", "rejected"))
        for p in (con_reemplazo, sin_reemplazo):
            make_survey_review(p, status="approved")
        db_session.flush()

        cola = AppointmentService.queue_candidates(db_session,
                                                   allowed_program_ids={prog.id})

        ids = [p.id for p in cola["pending"]]
        assert con_reemplazo.id in ids
        assert sin_reemplazo.id not in ids
        assert cola["docs_ok"][con_reemplazo.id] is True
        assert cola["docs_ok"][sin_reemplazo.id] is False


# ---------------------------------------------------------------------------
# approve_phase(2): la guarda de liberación
# ---------------------------------------------------------------------------
class TestLiberarFase2:
    def test_bloquea_con_un_reemplazo_abierto_y_lo_nombra(self, db_session, esc):
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        proc, _docs, _ = esc["build"]()
        _pedir(db_session, proc, "birth_certificate", esc=esc)

        with pytest.raises(ValueError) as exc:
            PhaseService.approve_phase(db_session, proc, 2, reviewer_id=esc["jefa"].id)

        assert str(exc.value) == (
            "No se puede liberar la fase 02: falta aprobar el reemplazo de: "
            f"{_nombre(db_session, 'birth_certificate')}.")
        db_session.expire_all()
        assert proc.current_phase == 2

    def test_el_reemplazo_se_nombra_antes_que_los_requisitos(self, db_session, esc):
        from itcj2.apps.titulatec.models import CotejoRequirement
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        proc, _docs, _ = esc["build"]()
        db_session.add(CotejoRequirement(cohort_id=proc.cohort_id, label="12 fotografias",
                                         icon="check2-square", is_required=True,
                                         is_active=True, order_index=0))
        db_session.flush()
        _pedir(db_session, proc, "curp", esc=esc)

        msg = PhaseService._cotejo_gate_error(db_session, proc)

        assert "falta aprobar el reemplazo" in msg and "12 fotografias" not in msg

    def test_aprobado_el_reemplazo_la_fase_se_libera(self, db_session, esc):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        proc, _docs, _ = esc["build"]()
        _pedir(db_session, proc, "curp", esc=esc)
        DocumentService.review(db_session, proc.id, "curp", status="approved", note=None,
                               reviewer_id=esc["jefa"].id)

        resultado = PhaseService.approve_phase(db_session, proc, 2,
                                               reviewer_id=esc["jefa"].id)

        assert resultado == {"next_phase": 3, "completed": False}


# ---------------------------------------------------------------------------
# R7 (revisión final): UN solo predicado de «reemplazo abierto»
# ---------------------------------------------------------------------------
# Abierto = bandera **y** `review_status != "approved"`. Un `approved` con la
# bandera vieja (reversa de la spec §9: el código viejo aprobó sin limpiarla)
# es CERRADO en todas partes; antes la compuerta lo contaba abierto y la fase 2
# quedaba trabada para siempre (aprobar de nuevo un aprobado de una fase pasada
# da `PHASE_CLOSED_MSG`).
_COMBOS = [(st, flag) for st in ("rejected", "pending", "approved") for flag in (True, False)]


class TestPredicadoUnico:
    @pytest.mark.parametrize("status,bandera,esperado", [
        ("rejected", _HACE_TIEMPO, True),
        ("pending", _HACE_TIEMPO, True),
        ("approved", _HACE_TIEMPO, False),
        ("rejected", None, False),
        ("pending", None, False),
        ("approved", None, False),
    ])
    def test_el_predicado_puro(self, status, bandera, esperado):
        from itcj2.apps.titulatec.services.document_service import DocumentService

        assert DocumentService.replacement_open(status, bandera) is esperado

    @pytest.mark.parametrize("status,con_bandera", _COMBOS)
    def test_todos_los_lectores_del_servicio_dicen_lo_mismo(self, db_session, esc,
                                                            status, con_bandera):
        """`open_replacements` (SQL), `student_can_replace`, la compuerta y el
        mapa de la cola contestan con el MISMO predicado, combinación por
        combinación."""
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"](estados=("approved", "approved", status),
                                      abiertos=("curp",) if con_bandera else ())
        db_session.expire_all()
        abierto = DocumentService.replacement_open(
            status, _HACE_TIEMPO if con_bandera else None)

        listados = {r["type_code"] for r in DocumentService.open_replacements(db_session, proc.id)}
        assert ("curp" in listados) is abierto
        assert DocumentService.student_can_replace(db_session, proc, "curp") is abierto
        assert (DocumentService.replacement_gate_error(db_session, proc) is not None) is abierto
        flexible = DocumentService.initial_docs_approved_map(
            db_session, [proc], replacement_ok=True)[proc.id]
        assert flexible is (abierto or status == "approved")

    def test_un_aprobado_con_bandera_vieja_no_traba_la_fase_2(self, db_session, esc):
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        proc, _docs, _ = esc["build"](abiertos=("curp",))     # los 3 `approved`

        assert PhaseService._cotejo_gate_error(db_session, proc) is None
        resultado = PhaseService.approve_phase(db_session, proc, 2,
                                               reviewer_id=esc["jefa"].id)

        assert resultado == {"next_phase": 3, "completed": False}

    def test_la_bandera_vieja_no_entra_en_open_replacements_con_una_consulta(
            self, db_session, esc):
        """El filtro va en SQL: sin abiertos de verdad, una consulta y lista vacía."""
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"](abiertos=("curp", "birth_certificate"))

        filas, sentencias = _contar(
            db_session, lambda: DocumentService.open_replacements(db_session, proc.id))

        assert filas == []
        assert len(sentencias) == 1, sentencias


# ---------------------------------------------------------------------------
# R8: la fila del documento se serializa (subida en vuelo vs. aprobación)
# ---------------------------------------------------------------------------
def _subir(db, proc, student, raw=None, nombre="curp-nueva.pdf"):
    from itcj2.apps.titulatec.services.document_service import DocumentService
    return DocumentService.save(db, proc, "curp", raw=raw or small_pdf(),
                                original_name=nombre, content_type="application/pdf",
                                uploaded_by_id=student.id)


def _es_lock_de(tabla, sentencia, modo="FOR UPDATE"):
    return f"FROM {tabla}" in sentencia and modo in sentencia


class TestCarreraSubirVsAprobar:
    def test_la_guarda_pasa_aprueban_y_la_subida_en_vuelo_no_pisa(
            self, db_session, esc, tmp_path, monkeypatch):
        """La carrera de R8, determinista: la ruta del alumno ya validó
        (`student_can_replace` = True) y, antes de que llegue su `save()`, la
        jefa aprueba el reemplazo en otra pestaña. La subida tiene que
        levantar en la MISMA transacción del `save()` -- sin pisar el
        dictamen, sin reabrir nada y sin tocar el archivo aprobado."""
        from itcj2.apps.titulatec.services.document_service import DocumentService
        from itcj2.apps.titulatec.utils import storage
        from tests.fastapi.titulatec._pdf_samples import merge_pdfs
        monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
        proc, _docs, student = esc["build"]()
        _pedir(db_session, proc, "curp", esc=esc)
        _subir(db_session, proc, student, nombre="curp-vista.pdf")
        doc = _doc(db_session, proc.id)
        archivo = storage.abs_path(doc.file_path)
        bytes_aprobados, version = archivo.read_bytes(), doc.version
        # La subida del reemplazo cuelga de la fase del TIPO (1), no de la del
        # proceso (2) -- antes lo fijaba `test_expediente_proceso.py` con un
        # `save()` en la fase 2 sin reemplazo, que R8 ya no admite.
        assert [e.phase_number for e in _eventos(db_session, proc.id,
                                                 "document_uploaded")] == [1]

        # 1) la guarda de la ruta pasa
        assert DocumentService.student_can_replace(db_session, proc, "curp") is True
        # 2) la jefa aprueba
        DocumentService.review(db_session, proc.id, "curp", status="approved", note=None,
                               reviewer_id=esc["jefa"].id)
        # 3) llega la subida en vuelo (otro archivo)
        with pytest.raises(ValueError) as exc:
            _subir(db_session, proc, student, raw=merge_pdfs(small_pdf(), small_pdf()),
                   nombre="curp-tarde.pdf")

        assert str(exc.value) == DocumentService.REPLACEMENT_CLOSED_MSG
        doc = _doc(db_session, proc.id)
        assert (doc.review_status, doc.replacement_requested_at, doc.version,
                doc.original_name) == ("approved", None, version, "curp-vista.pdf")
        assert archivo.read_bytes() == bytes_aprobados, "pisó el archivo aprobado"
        assert len(_eventos(db_session, proc.id, "document_uploaded")) == 1

    def test_tipo_de_una_fase_pasada_sin_reemplazo_no_se_sube(
            self, db_session, esc, tmp_path, monkeypatch):
        """Sin reemplazo abierto, un documento de la fase 1 con el proceso en la
        fase 2 no se escribe ni en BD ni en disco (antes solo lo paraba la
        guarda de la ruta)."""
        from itcj2.apps.titulatec.services.document_service import DocumentService
        monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
        proc, _docs, student = esc["build"]()

        with pytest.raises(ValueError) as exc:
            _subir(db_session, proc, student)

        assert str(exc.value) == DocumentService.REPLACEMENT_CLOSED_MSG
        assert _doc(db_session, proc.id).review_status == "approved"
        assert not any(p.is_file() for p in tmp_path.rglob("*")), "escribió en disco"

    def test_en_la_fase_1_la_subida_no_cambia(self, db_session, esc, tmp_path,
                                              monkeypatch):
        """Positivo del mismo `save()`: en su fase el documento se sube como siempre."""
        monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
        proc, _docs, student = esc["build"](current_phase=1,
                                            estados=("approved", "approved", "rejected"))

        _subir(db_session, proc, student)

        assert _doc(db_session, proc.id).review_status == "pending"

    def test_save_y_review_leen_la_fila_con_for_update(self, db_session, esc, tmp_path,
                                                      monkeypatch):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
        proc, _docs, student = esc["build"](estados=("approved", "approved", "rejected"),
                                            abiertos=("curp",))

        _, al_subir = _contar(db_session, lambda: _subir(db_session, proc, student))
        _, al_aprobar = _contar(db_session, lambda: DocumentService.review(
            db_session, proc.id, "curp", status="approved", note=None,
            reviewer_id=esc["jefa"].id))

        assert any(_es_lock_de("titulatec_documents", s) for s in al_subir), al_subir
        assert any(_es_lock_de("titulatec_documents", s) for s in al_aprobar), al_aprobar


# ---------------------------------------------------------------------------
# R9: pedir reemplazo y liberar la fase 2 bloquean la fila del proceso
# ---------------------------------------------------------------------------
def _primera(sentencias, pred):
    return next((i for i, s in enumerate(sentencias) if pred(s)), None)


def _lock_del_proceso(s):
    return _es_lock_de("titulatec_processes", s, "FOR NO KEY UPDATE")


class TestBloqueoDelProceso:
    def test_pedir_bloquea_el_proceso_antes_de_validar_la_fase(self, db_session, esc):
        proc, _docs, _ = esc["build"]()

        _, sql = _contar(db_session, lambda: _pedir(db_session, proc, "curp", esc=esc))

        bloqueo = _primera(sql, _lock_del_proceso)
        fase = _primera(sql, lambda s: "FROM titulatec_process_phases" in s)
        assert bloqueo is not None, sql
        assert fase is not None and bloqueo < fase, sql

    def test_liberar_la_fase_2_bloquea_el_proceso_antes_de_la_compuerta(
            self, db_session, esc):
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        proc, _docs, _ = esc["build"]()

        _, sql = _contar(db_session, lambda: PhaseService.approve_phase(
            db_session, proc, 2, reviewer_id=esc["jefa"].id))

        bloqueo = _primera(sql, _lock_del_proceso)
        compuerta = _primera(sql, lambda s: "FROM titulatec_documents" in s)
        assert bloqueo is not None, sql
        assert compuerta is not None and bloqueo < compuerta, sql

    def test_aprobar_otra_fase_tambien_toma_ese_bloqueo(self, db_session, esc):
        """Hasta R14 esto afirmaba lo contrario (R9 bloqueaba SOLO la fase de
        cotejo). Desde R14 (2026-10-15) `approve_phase` bloquea en TODAS las
        fases, una sola vez y antes de leer las fases del proceso; la matriz
        completa (aprobar/rechazar × fase 1/2) vive en
        `test_phase_verdict_lock.py`."""
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        proc, _docs, _ = esc["build"](current_phase=1)

        _, sql = _contar(db_session, lambda: PhaseService.approve_phase(
            db_session, proc, 1, reviewer_id=esc["jefa"].id))

        bloqueo = _primera(sql, _lock_del_proceso)
        fase = _primera(sql, lambda s: "FROM titulatec_process_phases" in s)
        assert bloqueo is not None, sql
        assert fase is not None and bloqueo < fase, sql
        assert sum(1 for s in sql if _lock_del_proceso(s)) == 1, sql


# ---------------------------------------------------------------------------
# R10 (parte de service): aprobar la versión que se vio
# ---------------------------------------------------------------------------
class TestAprobarLaVersionVista:
    def test_con_otra_version_levanta_sin_escribir(self, db_session, esc):
        from itcj2.apps.titulatec.services.document_service import (
            DocumentService, DocumentVersionChanged,
        )
        proc, docs, _ = esc["build"](estados=("approved", "approved", "pending"),
                                     abiertos=("curp",))
        version = _doc(db_session, proc.id).version

        with pytest.raises(DocumentVersionChanged):
            DocumentService.review(db_session, proc.id, "curp", status="approved",
                                   note=None, reviewer_id=esc["jefa"].id,
                                   expected_version=version + 1)

        doc = _doc(db_session, proc.id)
        assert (doc.review_status, doc.replacement_requested_at) == ("pending", _HACE_TIEMPO)
        assert _eventos(db_session, proc.id, "document_approved") == []
        assert issubclass(DocumentVersionChanged, ValueError)

    def test_con_la_version_vista_aprueba(self, db_session, esc):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, _docs, _ = esc["build"](estados=("approved", "approved", "pending"),
                                      abiertos=("curp",))
        version = _doc(db_session, proc.id).version

        assert DocumentService.review(db_session, proc.id, "curp", status="approved",
                                      note=None, reviewer_id=esc["jefa"].id,
                                      expected_version=version) is True

        assert _doc(db_session, proc.id).review_status == "approved"


# ---------------------------------------------------------------------------
# Vocabulario del evento
# ---------------------------------------------------------------------------
def test_el_evento_tiene_sus_dos_voces():
    from itcj2.apps.titulatec.models.process_event import EVENT_TYPES
    from itcj2.apps.titulatec.pages.admin import _EVENT_UI
    from itcj2.apps.titulatec.pages.student import _EVENT_LABELS

    assert "document_replacement_requested" in EVENT_TYPES
    assert _EVENT_LABELS["document_replacement_requested"] == (
        "Servicios Escolares te pidió reemplazar un documento")
    assert _EVENT_UI["document_replacement_requested"] == (
        "Reemplazo de documento solicitado", "arrow-repeat", "amber")
