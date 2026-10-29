"""Solicitud de prórroga del estudiante: una abierta por semestre y solo tras unirse (QR o invitación)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from itcj2.apps.prorrogas_tec.documents.catalog import DOC_TYPES
from itcj2.apps.prorrogas_tec.documents.values import SignatureInfo
from itcj2.apps.prorrogas_tec.models.invitation import ProrrogaJoin
from itcj2.apps.prorrogas_tec.models.request import OPEN_STATUSES, ProrrogaRequest
from itcj2.apps.prorrogas_tec.services.document_service import DocumentService
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.events import log_event
from itcj2.apps.prorrogas_tec.services.formatting import nombre_oficial
from itcj2.apps.prorrogas_tec.services.identity import folio, institutional_email
from itcj2.apps.prorrogas_tec.services import notify
from itcj2.apps.prorrogas_tec.services.periods import period_for, period_label
from itcj2.core.models.academic_period import AcademicPeriod
from itcj2.core.models.program import Program
from itcj2.core.models.user import User
from itcj2.core.utils.timezone import db_now

logger = logging.getLogger(__name__)

_ABIERTA = ("solicitud_abierta", "Ya tienes una solicitud abierta en este semestre.")


class RequestService:
    MOTIVO_MIN = 20
    MOTIVO_MAX = 1000
    COMENTARIO_MAX = 1000

    @staticmethod
    def access(db, user_id: int, *, now: datetime | None = None) -> tuple[AcademicPeriod | None, str | None]:
        """Semestre actual y, si no puede solicitar, el código que lo impide."""
        now = now or db_now()
        period = period_for(db, now.date())
        if period is None:
            return None, "no_hay_semestre"
        mias = db.query(ProrrogaRequest).filter_by(student_id=user_id, period_id=period.id)
        if mias.filter(ProrrogaRequest.origin == "app", ProrrogaRequest.status.in_(OPEN_STATUSES)).first():
            return period, "solicitud_abierta"
        ultima = mias.order_by(ProrrogaRequest.created_at.desc(), ProrrogaRequest.id.desc()).first()
        uniones = db.query(ProrrogaJoin.id).filter(
            ProrrogaJoin.user_id == user_id,
            ProrrogaJoin.joined_at >= period.start_date,
            ProrrogaJoin.joined_at < period.end_date + timedelta(days=1))
        if ultima is not None:
            uniones = uniones.filter(ProrrogaJoin.joined_at > ultima.created_at)
        return period, (None if uniones.first() else "sin_acceso")

    @staticmethod
    def create(db, student: User, *, plazos: int, motivo: str, program_id: int, firma: bytes,
               ip: str | None, user_agent: str | None, now: datetime | None = None) -> ProrrogaRequest:
        now = now or db_now()
        if not isinstance(plazos, int) or isinstance(plazos, bool) or not 1 <= plazos <= 3:
            raise ServiceError("plazos_invalidos", "Elige de 1 a 3 plazos.")
        motivo = (motivo or "").strip()
        if not RequestService.MOTIVO_MIN <= len(motivo) <= RequestService.MOTIVO_MAX:
            raise ServiceError(
                "motivo_invalido",
                f"El motivo debe tener de {RequestService.MOTIVO_MIN} a {RequestService.MOTIVO_MAX} caracteres.")
        program = db.get(Program, program_id)
        if program is None:
            raise ServiceError("carrera_invalida", "Elige una carrera de la lista.")
        period, code = RequestService.access(db, student.id, now=now)
        if code == "sin_acceso":
            raise ServiceError(code, "Pide en persona a la secretaría que te dé acceso (QR o invitación).",
                               status=403)
        if code == "solicitud_abierta":
            raise ServiceError(*_ABIERTA, status=409)
        if code:
            raise ServiceError(code, "No hay un semestre vigente para solicitar.", status=409)

        email = student.email or institutional_email(student.control_number)
        req = ProrrogaRequest(
            origin="app", student_id=student.id, period_id=period.id, period_label=period_label(period),
            status="pendiente", requested_terms=plazos, reason=motivo, control_number=student.control_number,
            student_name=nombre_oficial(student.first_name, student.last_name, student.middle_name),
            program_name=program.name, program_level=program.level, email=email,
            created_at=now, updated_at=now)
        try:
            db.add(req)
            db.flush()
            db.refresh(req)
            DocumentService.generate(
                db, req, "formato_solicitud", actor_id=student.id, today=now.date(),
                signature=SignatureInfo(png=firma, signer_id=student.id, signed_at=now, ip=ip,
                                        user_agent=user_agent))
            log_event(db, event_type="solicitud_creada", request_id=req.id, actor_id=student.id,
                      payload={"plazos": plazos, "periodo": req.period_label})
            db.commit()
        except IntegrityError as e:  # doble envío: gana el índice único de solicitudes abiertas
            db.rollback()
            if getattr(getattr(e.orig, "diag", None), "constraint_name", None) != "uq_prorrogas_requests_abierta":
                raise
            raise ServiceError(*_ABIERTA, status=409)
        except ServiceError:  # p. ej. pdf_no_disponible: no queda solicitud y puede reintentar
            db.rollback()
            raise
        db.refresh(req)
        return req

    @staticmethod
    def cancel(db, request_id: int, student_id: int, *, now: datetime | None = None) -> ProrrogaRequest:
        req = db.query(ProrrogaRequest).filter_by(id=request_id, student_id=student_id).first()
        if req is None:
            raise ServiceError("no_encontrada", "No se encontró la solicitud.", status=404)
        if req.status != "pendiente":
            raise ServiceError("no_cancelable", "Solo se puede cancelar una solicitud pendiente.", status=409)
        req.status = "cancelada"
        req.updated_at = now or db_now()
        log_event(db, event_type="solicitud_cancelada", request_id=req.id, actor_id=student_id)
        db.commit()
        return req

    @staticmethod
    def mine(db, student_id: int) -> list[ProrrogaRequest]:
        return (db.query(ProrrogaRequest).filter_by(student_id=student_id)
                .order_by(ProrrogaRequest.created_at.desc(), ProrrogaRequest.id.desc()).all())

    @staticmethod
    def pending(db) -> list[ProrrogaRequest]:
        return (db.query(ProrrogaRequest).filter_by(status="pendiente")
                .order_by(ProrrogaRequest.created_at.desc(), ProrrogaRequest.id.desc()).all())

    @staticmethod
    def decide(db, request_id: int, actor_id: int, *, aceptar: bool, comentario: str | None,
               now: datetime | None = None) -> ProrrogaRequest:
        """La secretaria acepta o rechaza; genera la carta y avisa al estudiante."""
        comentario = (comentario or "").strip()
        if len(comentario) > RequestService.COMENTARIO_MAX:
            raise ServiceError("comentario_muy_largo",
                               f"El comentario no puede pasar de {RequestService.COMENTARIO_MAX} caracteres.")
        if not aceptar and not comentario:
            raise ServiceError("motivo_requerido", "Escribe el motivo del rechazo.")
        now = now or db_now()
        req = (db.query(ProrrogaRequest).filter_by(id=request_id)
               .populate_existing().with_for_update().first())
        if req is None:
            raise ServiceError("no_encontrada", "No se encontró la solicitud.", status=404)
        if req.status != "pendiente":
            db.rollback()  # suelta el candado
            raise ServiceError("ya_resuelta", "Esta solicitud ya fue resuelta.", status=409)
        try:
            req.status = "aceptada" if aceptar else "rechazada"
            req.decided_by_id = actor_id
            req.decided_at = now
            req.decision_comment = comentario or None
            req.updated_at = now
            DocumentService.generate(
                db, req, "carta_aceptacion" if aceptar else "carta_rechazo", actor_id=actor_id,
                today=now.date(),
                extra={"comentario": comentario} if aceptar else {"motivo_rechazo": comentario})
            log_event(db, event_type="solicitud_aceptada" if aceptar else "solicitud_rechazada",
                      request_id=req.id, actor_id=actor_id, payload={"comentario": comentario or None})
            db.commit()
        except Exception:  # p. ej. pdf_no_disponible: sigue pendiente y puede reintentar
            db.rollback()
            raise
        db.refresh(req)
        notify.notify_student(db, req, kind="aceptada" if aceptar else "rechazada",
                              link="/prorrogas/estudiante")
        try:  # el aviso en la plataforma sale con este commit; si falla, la decisión ya está firme
            db.commit()
        except Exception:
            logger.exception("No se pudo guardar el aviso de la solicitud %s", req.id)
            db.rollback()
        return req

    @staticmethod
    def request_out(db, req: ProrrogaRequest) -> dict:
        return {
            "id": req.id, "folio": folio(req.id), "estado": req.status, "plazos": req.requested_terms,
            "motivo": req.reason, "semestre": req.period_label, "creada": req.created_at.isoformat(),
            "decidida": req.decided_at.isoformat() if req.decided_at else None,
            "comentario": req.decision_comment,
            "documentos": [
                {"id": d.id, "tipo": d.doc_type, "label": DOC_TYPES[d.doc_type].label, "version": d.version,
                 "firmado": d.signed_at is not None}
                for d in DocumentService.current(db, req)],
        }
