"""Anexo III (fase 6): folio, firmas requeridas, PDF al vuelo y dictamen -- spec fase 6 §5-§10.

El PDF se regenera cada vez que se pide (como el oficio de sinodales); lo unico
que se guarda es el folio y la fecha de liberacion en `titulatec_anexos`, para
que reimprimir no cambie el documento. Todo lo que pinta la plantilla
(`oficios/anexo_iii.html`) llega precalculado en `context`: no decide nada.

Las firmas requeridas salen SOLO de `ReviewService.counting_roles` (el unico
traductor de `Modality.signature_rule`).

`AnexoService` es la UNICA puerta de la fase 6 (`PhaseService._DOOR_PHASES`):
el escaneo firmado es un `Document` de tipo `DOC_TYPE`; subirlo o borrarlo
sincroniza la fase (`sync_phase`, desde `DocumentService.save`/`delete`) y
solo `approve`/`observe` lo dictaminan, junto con la fase, en UNA transaccion.
Invariante: fase 6 `approved` <=> escaneo `approved`.
"""
from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.oficio_service import (
    FOOTER_ADDRESS, FOOTER_CONTACT, NO_SYNODALS_MSG,
    OficioService, _date_label,
)
from itcj2.core.utils.timezone import db_now

logger = logging.getLogger(__name__)

PHASE_CODE = "anexo_iii"
# Tipo de documento del escaneo firmado (`titulatec_document_types`, fase 6).
DOC_TYPE = "anexo_iii"
REVIEW_PHASE_CODE = "synodal_review"
SYNODALS_REQUIRED = 4
REASON_MAX = 500

NOT_OPERABLE_MSG = "El Anexo III todavia no se opera en esta app."
NOT_REACHED_MSG = "El proceso todavia no llega al Anexo III."
NO_DEPARTMENT_MSG = "La carrera del proceso no esta ligada a un departamento academico."
NO_MODALITY_MSG = "El proceso no tiene una modalidad con producto definido."
NOT_IN_REVIEW_MSG = ("Este Anexo III no esta por revisar: el alumno aun no sube el "
                     "escaneo firmado o ya fue dictaminado.")
REASON_REQUIRED_MSG = "Escribe el motivo de la observacion."
REASON_TOO_LONG_MSG = "El motivo de la observacion admite hasta 500 caracteres."

# Estados de la fase 6 desde los que una subida la pone «Por revisar» (C6).
_SYNC_TO_REVIEW = ("in_progress", "rejected", "in_review")

_TEMPLATE_NAME = "titulatec/oficios/anexo_iii.html"


class AnexoService:

    # ------------------------------------------------------------------
    # Corte y alcance
    # ------------------------------------------------------------------
    @staticmethod
    def phase_number(db: Session) -> int | None:
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        return PhaseService.phase_number_for_code(db, PHASE_CODE)

    @staticmethod
    def operable(db: Session) -> bool:
        """¿La fase 6 se opera en esta app? Falla cerrado (corte o sin catalogo)."""
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        return PHASE_CODE in PhaseService.operable_codes(db, [PHASE_CODE])

    @staticmethod
    def reached(db: Session, process) -> bool:
        """Fase 6 en el catalogo, proceso no cancelado, `current_phase >= n6` y
        su `ProcessPhase` no `skipped`."""
        from itcj2.apps.titulatec.models import ProcessPhase

        n = AnexoService.phase_number(db)
        if n is None or process is None or process.status == "cancelled":
            return False
        if (process.current_phase or 0) < n:
            return False
        estado = (db.query(ProcessPhase.status)
                  .filter(ProcessPhase.process_id == process.id,
                          ProcessPhase.phase_number == n).scalar())
        return estado != "skipped"

    # ------------------------------------------------------------------
    # Firmas
    # ------------------------------------------------------------------
    @staticmethod
    def required_signers(process) -> list[str]:
        """`["department_head", *roles que cuentan]`. `ValueError` si la regla
        de firma es desconocida (falla cerrado)."""
        from itcj2.apps.titulatec.services.review_service import ReviewService
        return ["department_head",
                *ReviewService.counting_roles(ReviewService.rule_for(process))]

    @staticmethod
    def signers_text(process) -> str:
        """Quien firma, en lenguaje llano (alumno y Titulacion)."""
        from itcj2.apps.titulatec.services.synodal_service import ROLE_LABELS

        roles = [r for r in AnexoService.required_signers(process) if r != "department_head"]
        if len(roles) == 1:
            sinodales = f"el {ROLE_LABELS.get(roles[0], roles[0])}"
        else:
            sinodales = f"tus {len(roles)} sinodales"
        return (f"Firman el jefe del departamento académico y {sinodales}. La firma del "
                "jefe del departamento la gestiona tu jefe de proyecto de vinculación.")

    # ------------------------------------------------------------------
    # Folio
    # ------------------------------------------------------------------
    @staticmethod
    def get(db: Session, process_id: int):
        from itcj2.apps.titulatec.models import Anexo
        return db.query(Anexo).filter(Anexo.process_id == process_id).first()

    @staticmethod
    def _released_at(db: Session, process):
        """Fin de la fase 5: `completed_at` de su `ProcessPhase`, respaldo el
        evento `phase_approved` de esa fase, ultimo recurso `db_now()`."""
        from itcj2.apps.titulatec.models import ProcessEvent, ProcessPhase
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        n5 = PhaseService.phase_number_for_code(db, REVIEW_PHASE_CODE)
        if n5 is not None:
            cuando = (db.query(ProcessPhase.completed_at)
                      .filter(ProcessPhase.process_id == process.id,
                              ProcessPhase.phase_number == n5).scalar())
            if cuando is not None:
                return cuando
            cuando = (db.query(ProcessEvent.created_at)
                      .filter(ProcessEvent.process_id == process.id,
                              ProcessEvent.event_type == "phase_approved",
                              ProcessEvent.phase_number == n5)
                      .order_by(ProcessEvent.id.desc()).limit(1).scalar())
            if cuando is not None:
                return cuando
        return db_now()

    @staticmethod
    def _next_number(db: Session, semester: str) -> int:
        """Contador atomico por semestre: UNA sentencia, nace en 1."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from itcj2.apps.titulatec.models import AnexoCounter

        tabla = AnexoCounter.__table__
        stmt = (pg_insert(tabla)
                .values(semester=semester, last_value=1)
                .on_conflict_do_update(
                    index_elements=["semester"],
                    set_={"last_value": tabla.c.last_value + 1})
                .returning(tabla.c.last_value))
        return db.execute(stmt).scalar_one()

    @staticmethod
    def ensure_folio(db: Session, process, actor_id: int | None):
        """El `Anexo` del proceso; lo crea (folio + fecha congelada) la primera
        vez. Sin commit. `ValueError` si la fase no se opera, no se alcanzo o los
        datos del documento estan incompletos: ANTES de numerar valida con
        `context` (4 sinodales, departamento, modalidad con producto), asi que
        un folio nunca se quema por datos invalidos sin importar el llamador."""
        from itcj2.apps.titulatec.models import Anexo
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.certificate_service import semester_key
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        if not AnexoService.operable(db):
            raise ValueError(NOT_OPERABLE_MSG)
        PhaseService._lock_process_row(db, process)
        if not AnexoService.reached(db, process):
            raise ValueError(NOT_REACHED_MSG)
        existente = AnexoService.get(db, process.id)
        if existente is not None:
            return existente

        AnexoService.context(db, process)           # falla cerrado antes de numerar
        ahora = db_now()
        semestre = semester_key(ahora)
        liberado = AnexoService._released_at(db, process)
        try:
            with db.begin_nested():
                n = AnexoService._next_number(db, semestre)
                anexo = Anexo(process_id=process.id, folio=f"AIII-{semestre}-{n:04d}",
                              semester=semestre, released_at=liberado,
                              issued_at=ahora, issued_by_id=actor_id)
                db.add(anexo)
                db.flush()
        except IntegrityError:
            # Otro proceso gano la carrera: se relee su fila.
            existente = AnexoService.get(db, process.id)
            if existente is None:
                raise
            return existente

        datos = {"folio": anexo.folio, "semester": semestre}
        PhaseService._log(db, process.id, actor_id, "anexo_iii_issued",
                          AnexoService.phase_number(db), dict(datos))
        AuditService.record(
            db, "anexo_iii.issued",
            entity_type="anexo", entity_id=anexo.id,
            process_id=process.id, subject=process.folio,
            payload=dict(datos), actor_id=actor_id)
        return anexo

    # ------------------------------------------------------------------
    # Sincronia de la subida (C6)
    # ------------------------------------------------------------------
    @staticmethod
    def sync_phase(db: Session, process) -> str | None:
        """Sincroniza la `ProcessPhase` de la fase 6 con el escaneo firmado.

        Molde de `DocumentService.sync_initial_phase`: es un efecto secundario
        de `DocumentService.save`/`delete` del tipo de la fase 6, no una guarda
        (nunca lanza). Solo actua con el Anexo operable y el proceso `active`
        parado en la fase 6:

        - escaneo presente -> `in_review` si estaba `in_progress`, `rejected`
          o `in_review`, y SIEMPRE `updated_at = db_now()`: es la clave FIFO de
          la bandeja de Titulacion, asi que cada subida (tambien un reemplazo
          sin dictamen) manda el escaneo al final de la cola;
        - escaneo ausente -> `in_progress` si estaba `in_review`;
        - nunca toca `approved`, `skipped` ni `pending` (ni crea la fila).

        Devuelve el estado escrito o None. Sin commit ni flush: lo hace el
        llamador, que ademas tiene la fila del proceso bloqueada y releida (asi
        `current_phase` no es el que se leyo antes de comprimir el PDF). La
        fase se relee (`populate_existing`) por lo mismo: un objeto viejo de la
        sesion escribiria encima del dictamen de otro.
        """
        from itcj2.apps.titulatec.models import Document, ProcessPhase

        if process.status != "active":
            return None
        n = AnexoService.phase_number(db)
        if n is None or process.current_phase != n or not AnexoService.operable(db):
            return None

        presente = (db.query(Document.id)
                    .filter(Document.process_id == process.id,
                            Document.type_code == DOC_TYPE)
                    .first()) is not None
        fase = (db.query(ProcessPhase)
                .filter_by(process_id=process.id, phase_number=n)
                .populate_existing().first())
        if fase is None:
            return None
        if presente:
            if fase.status not in _SYNC_TO_REVIEW:
                return None
            nuevo = "in_review"
        else:
            if fase.status != "in_review":
                return None
            nuevo = "in_progress"
        fase.status = nuevo
        fase.updated_at = db_now()
        return nuevo

    # ------------------------------------------------------------------
    # Dictamen de Titulacion (puerta unica, spec §10)
    # ------------------------------------------------------------------
    @staticmethod
    def _state(db: Session, process, n, *, locked: bool):
        """`(escaneo, estado de la fase 6)`. Sin `locked`: lo que ya hay en la
        sesion (pre-chequeo). Con `locked` (bajo el bloqueo del proceso): el
        escaneo `FOR UPDATE` y los dos releidos con `populate_existing`, asi la
        verificacion ve lo que dejo quien llego antes."""
        from itcj2.apps.titulatec.models import Document, ProcessPhase
        from itcj2.apps.titulatec.services.document_service import DocumentService

        if locked:
            doc = DocumentService._locked_document(db, process.id, DOC_TYPE)
        else:
            doc = (db.query(Document)
                   .filter_by(process_id=process.id, type_code=DOC_TYPE).first())
        consulta = db.query(ProcessPhase).filter_by(process_id=process.id, phase_number=n)
        if locked:
            consulta = consulta.populate_existing()
        fase = consulta.first()
        return doc, (fase.status if fase is not None else None)

    @staticmethod
    def _assert_in_review(db: Session, process, n, *, locked: bool):
        """«Por revisar» + guarda del motor, sin escribir. Devuelve el escaneo.

        Se corre DOS veces (molde de `FormatBService._assert_in_review`): sin
        bloqueo sobre lo cargado (lo comun falla sin tomar candado ni deshacer
        nada) y bajo el bloqueo sobre lo releido. Orden: Anexo operable
        (`NOT_OPERABLE_MSG`), fase 6 `in_review` con el escaneo presente y
        `pending` (`NOT_IN_REVIEW_MSG`) y `assert_can_transition` (proceso
        `active`, fase en curso, corte).
        """
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        if not AnexoService.operable(db):
            raise ValueError(NOT_OPERABLE_MSG)
        doc, estado = AnexoService._state(db, process, n, locked=locked)
        if estado != "in_review" or doc is None or doc.review_status != "pending":
            raise ValueError(NOT_IN_REVIEW_MSG)
        PhaseService.assert_can_transition(db, process, n)
        return doc

    @staticmethod
    def approve(db: Session, process, reviewer_id: int) -> dict:
        """Titulacion aprueba el escaneo y, en la MISMA transaccion, la fase 6.

        Escaneo `approved` (sin nota) + `approve_phase` con la puerta abierta:
        el proceso pasa a la siguiente fase aplicable (la 7). Cualquier error
        bajo el bloqueo: `rollback` y se re-lanza. Devuelve lo de
        `approve_phase`.
        """
        n = AnexoService.phase_number(db)
        AnexoService._assert_in_review(db, process, n, locked=False)
        return AnexoService._dictaminar(db, process, n, reviewer_id, "approved", None)

    @staticmethod
    def observe(db: Session, process, reviewer_id: int, *, reason: str) -> None:
        """Titulacion observa el escaneo: escaneo `rejected` con el motivo y
        `reject_phase` (el alumno lo ve y vuelve a subir, C6). Motivo
        obligatorio (`REASON_REQUIRED_MSG`) y de a lo mas `REASON_MAX`
        caracteres tras `strip()` (`REASON_TOO_LONG_MSG`); se valida antes de
        tomar el bloqueo, asi que un motivo invalido no escribe nada."""
        n = AnexoService.phase_number(db)
        AnexoService._assert_in_review(db, process, n, locked=False)
        motivo = (reason or "").strip()
        if not motivo:
            raise ValueError(REASON_REQUIRED_MSG)
        if len(motivo) > REASON_MAX:
            raise ValueError(REASON_TOO_LONG_MSG)
        AnexoService._dictaminar(db, process, n, reviewer_id, "rejected", motivo)

    @staticmethod
    def _dictaminar(db: Session, process, n: int, reviewer_id: int, veredicto: str,
                    motivo: str | None):
        """Bloqueo -> re-chequeo -> escaneo + bitacora -> puerta -> motor.

        El escaneo se escribe y se hace `flush` ANTES del motor: `_door_guard`
        lo lee de la BD (`_door_state_ok`) y `approve_phase`/`reject_phase`
        releen el proceso con `populate_existing`. La ronda es la `version` del
        documento; el evento del motor lleva `{"anexo_iii": {folio, round}}`
        (un evento por dictamen, sin duplicar). La puerta se cierra pase lo que
        pase; cualquier error bajo el bloqueo hace `rollback`.
        """
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        try:
            PhaseService._lock_process_row(db, process)
            doc = AnexoService._assert_in_review(db, process, n, locked=True)
            doc.review_status = veredicto
            doc.review_note = motivo
            doc.reviewed_by_id = reviewer_id
            ronda = doc.version
            anexo = AnexoService.get(db, process.id)
            AuditService.record(
                db, "anexo_iii.reviewed",
                entity_type="anexo", entity_id=anexo.id if anexo else None,
                process_id=process.id, subject=process.folio, reason=motivo,
                payload={"status": veredicto, "round": ronda},
                actor_id=reviewer_id)
            db.flush()
            evento = {"anexo_iii": {"folio": anexo.folio if anexo else None, "round": ronda}}
            PhaseService.open_door(db, PHASE_CODE, process.id, veredicto)
            if veredicto == "approved":
                return PhaseService.approve_phase(db, process, n, reviewer_id,
                                                  event_payload=evento)
            PhaseService.reject_phase(db, process, n, reviewer_id, motivo,
                                      event_payload=evento)
            return None
        except Exception:
            db.rollback()
            raise
        finally:
            PhaseService.close_door(db)

    # ------------------------------------------------------------------
    # Documento
    # ------------------------------------------------------------------
    @staticmethod
    def context(db: Session, process) -> dict:
        """Todas las piezas del Anexo (spec §7). `ValueError` sin los 4
        sinodales vigentes, sin departamento o sin modalidad/producto."""
        from itcj2.apps.titulatec.models import Modality
        from itcj2.apps.titulatec.services.synodal_service import SynodalService

        sinodales = SynodalService.active_for_process(db, process.id)
        if len(sinodales) != SYNODALS_REQUIRED:
            raise ValueError(NO_SYNODALS_MSG)
        marco = OficioService.department_frame(db, process)
        depto = marco["department"]
        if depto is None:
            raise ValueError(NO_DEPARTMENT_MSG)
        modalidad = db.get(Modality, process.modality_id) if process.modality_id else None
        producto = " ".join(str(getattr(modalidad, "product_label", None) or "").split())
        if modalidad is None or not producto:
            raise ValueError(NO_MODALITY_MSG)

        base = SynodalService._notice_base(db, process)
        anexo = AnexoService.get(db, process.id)
        liberado = anexo.released_at if anexo else AnexoService._released_at(db, process)
        egresado = (base["alumno"] or "").title()
        carrera = base["carrera"] or ""
        control = base["control"] or ""
        proyecto = (base["titulo"] or "").upper()
        return {
            "header": marco["header"],
            "folio": anexo.folio if anexo else None,
            "date_label": _date_label(liberado),
            "addressee": marco["addressee"],
            "signer": marco["signer"],
            "student_name": egresado,
            "control_number": control,
            "program_name": carrera,
            "project_title": proyecto,
            "product_label": producto,
            "items": [
                {"letter": "a", "label": "Nombre del egresado", "value": egresado},
                {"letter": "b", "label": "Carrera", "value": carrera},
                {"letter": "c", "label": "No. de control", "value": control},
                {"letter": "d", "label": "Nombre del proyecto", "value": proyecto},
                {"letter": "e", "label": "Producto", "value": producto},
            ],
            "synodals": [{
                "role_label": s["role_label"],
                "name": (s["name"] or "").upper(),
                "academic_degree": (s["academic_degree"] or "").upper(),
                "license": s["professional_license"] or "",
            } for s in sinodales],
            "footer_address": FOOTER_ADDRESS,
            "footer_contact": FOOTER_CONTACT,
        }

    @staticmethod
    def render_pdf(db: Session, process, actor_id: int | None) -> bytes:
        """PDF del Anexo. `ensure_folio` valida antes de numerar; luego pinta. Sin commit."""
        from weasyprint import HTML

        from itcj2.apps.titulatec.pages.nav import titulatec_templates
        from itcj2.apps.titulatec.utils.certificate_pdf import CORE_STATIC_DIR

        AnexoService.ensure_folio(db, process, actor_id)
        ctx = AnexoService.context(db, process)
        html = titulatec_templates.get_template(_TEMPLATE_NAME).render(**ctx)
        return HTML(string=html, base_url=str(CORE_STATIC_DIR)).write_pdf()

    @staticmethod
    def filename(db: Session, process) -> str:
        from itcj2.core.models.user import User

        alumno = db.get(User, process.student_id)
        control = (alumno.control_number if alumno and alumno.control_number
                   else f"proceso{process.id}")
        return f"{control}_ANEXO_III.pdf"
