"""Anexo III (fase 6): folio, firmas requeridas y PDF al vuelo -- spec fase 6 §7, §8, §10.

El PDF se regenera cada vez que se pide (como el oficio de sinodales); lo unico
que se guarda es el folio y la fecha de liberacion en `titulatec_anexos`, para
que reimprimir no cambie el documento. Todo lo que pinta la plantilla
(`oficios/anexo_iii.html`) llega precalculado en `context`: no decide nada.

Las firmas requeridas salen SOLO de `ReviewService.counting_roles` (el unico
traductor de `Modality.signature_rule`).
"""
from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.oficio_service import (
    DEFAULT_ADDRESSEE_CODE, FOOTER_ADDRESS, FOOTER_CONTACT, NO_SYNODALS_MSG,
    OficioService, _date_label,
)
from itcj2.core.utils.timezone import db_now

logger = logging.getLogger(__name__)

PHASE_CODE = "anexo_iii"
REVIEW_PHASE_CODE = "synodal_review"
SYNODALS_REQUIRED = 4

NOT_OPERABLE_MSG = "El Anexo III todavia no se opera en esta app."
NOT_REACHED_MSG = "El proceso todavia no llega al Anexo III."
NO_DEPARTMENT_MSG = "La carrera del proceso no esta ligada a un departamento academico."
NO_MODALITY_MSG = "El proceso no tiene una modalidad con producto definido."

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
        vez. Sin commit. `ValueError` si la fase no se opera o no se alcanzo."""
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
    # Documento
    # ------------------------------------------------------------------
    @staticmethod
    def context(db: Session, process) -> dict:
        """Todas las piezas del Anexo (spec §7). `ValueError` sin los 4
        sinodales vigentes, sin departamento o sin modalidad/producto."""
        from itcj2.apps.titulatec.models import DepartmentSettings, Modality, ProgramDepartment
        from itcj2.apps.titulatec.services.synodal_service import SynodalService
        from itcj2.core.models.department import Department

        sinodales = SynodalService.active_for_process(db, process.id)
        if len(sinodales) != SYNODALS_REQUIRED:
            raise ValueError(NO_SYNODALS_MSG)
        mapeo = db.get(ProgramDepartment, process.program_id) if process.program_id else None
        depto = db.get(Department, mapeo.department_id) if mapeo else None
        if depto is None:
            raise ValueError(NO_DEPARTMENT_MSG)
        modalidad = db.get(Modality, process.modality_id) if process.modality_id else None
        producto = " ".join(str(getattr(modalidad, "product_label", None) or "").split())
        if modalidad is None or not producto:
            raise ValueError(NO_MODALITY_MSG)

        base = SynodalService._notice_base(db, process)
        ajustes = db.get(DepartmentSettings, depto.id)
        encabezado = (ajustes.oficio_header if ajustes and ajustes.oficio_header
                      else f"Departamento de {depto.name}")
        destinatario = OficioService.holder(
            db, ajustes.addressee_position_code if ajustes else DEFAULT_ADDRESSEE_CODE,
            title=ajustes.addressee_title if ajustes else None)
        firmante = OficioService.holder(db, f"head_{depto.code}")

        anexo = AnexoService.get(db, process.id)
        liberado = anexo.released_at if anexo else AnexoService._released_at(db, process)
        egresado = (base["alumno"] or "").title()
        carrera = base["carrera"] or ""
        control = base["control"] or ""
        proyecto = (base["titulo"] or "").upper()
        return {
            "header": encabezado,
            "folio": anexo.folio if anexo else None,
            "date_label": _date_label(liberado),
            "addressee": destinatario,
            "signer": firmante,
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
        """PDF del Anexo. Valida primero (no quema folio si los datos estan
        incompletos), luego emite/relee el folio y pinta. Sin commit."""
        from weasyprint import HTML

        from itcj2.apps.titulatec.pages.nav import titulatec_templates
        from itcj2.apps.titulatec.utils.certificate_pdf import CORE_STATIC_DIR

        AnexoService.context(db, process)           # falla cerrado antes del folio
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
