"""
Servicio para gestión de solicitudes de baja de inventario.
"""
import os
import logging
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
from itcj2.apps.helpdesk.models.inventory_retirement_request import (
    InventoryRetirementRequest,
    InventoryRetirementRequestItem,
)

logger = logging.getLogger(__name__)

from itcj2.config import get_settings
UPLOAD_BASE = get_settings().HELPDESK_RETIREMENT_PATH
ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "png", "jpg", "jpeg"}


class InventoryRetirementService:
    """Lógica de negocio para solicitudes de baja de inventario."""

    # ── Generación de folio ───────────────────────────────────────────────────

    @staticmethod
    def generate_folio(db: Session) -> str:
        """Genera folio único: BAJA-{YEAR}-{SEQ:03d}"""
        year = datetime.now().year
        last = (
            db.query(InventoryRetirementRequest)
            .filter(InventoryRetirementRequest.folio.like(f"BAJA-{year}-%"))
            .order_by(InventoryRetirementRequest.id.desc())
            .first()
        )
        if last:
            try:
                seq = int(last.folio.split("-")[-1]) + 1
            except Exception:
                seq = 1
        else:
            seq = 1
        return f"BAJA-{year}-{seq:03d}"

    # ── Validaciones ──────────────────────────────────────────────────────────

    @staticmethod
    def validate_items_not_in_pending(db: Session, item_ids: list[int]) -> list[int]:
        """
        Retorna la lista de item_ids que ya están en una solicitud DRAFT o PENDING.
        """
        occupied = (
            db.query(InventoryRetirementRequestItem.item_id)
            .join(
                InventoryRetirementRequest,
                InventoryRetirementRequest.id == InventoryRetirementRequestItem.request_id,
            )
            .filter(
                InventoryRetirementRequestItem.item_id.in_(item_ids),
                InventoryRetirementRequest.status.in_(["DRAFT", "PENDING"]),
            )
            .all()
        )
        return [row[0] for row in occupied]

    # ── CRUD de solicitudes ───────────────────────────────────────────────────

    @staticmethod
    def create_request(db: Session, reason: str, requested_by_id: int) -> InventoryRetirementRequest:
        if not reason or len(reason.strip()) < 10:
            raise ValueError("La razón debe tener al menos 10 caracteres")

        folio = InventoryRetirementService.generate_folio(db)
        req = InventoryRetirementRequest(
            folio=folio,
            status="DRAFT",
            reason=reason.strip(),
            requested_by_id=requested_by_id,
        )
        db.add(req)
        db.commit()
        db.refresh(req)
        return req

    @staticmethod
    def add_items(db: Session, request_id: int, item_ids: list[int], notes_map: dict = None, user_id: int = None) -> InventoryRetirementRequest:
        """
        Agrega equipos a una solicitud en estado DRAFT.
        notes_map: {item_id: "nota específica"}
        """
        req = db.get(InventoryRetirementRequest, request_id)
        if not req:
            raise ValueError("Solicitud no encontrada")
        if req.status != "DRAFT":
            raise ValueError("Solo se pueden agregar equipos a solicitudes en estado DRAFT")
        if user_id and req.requested_by_id != user_id:
            raise ValueError("No puede modificar una solicitud de otro usuario")

        # Verificar que no estén en otras solicitudes activas
        occupied = InventoryRetirementService.validate_items_not_in_pending(db, item_ids)
        # Excluir los que ya son de esta misma solicitud
        already_in_this = {ri.item_id for ri in req.items}
        truly_occupied = [iid for iid in occupied if iid not in already_in_this]
        if truly_occupied:
            items_str = ", ".join(str(i) for i in truly_occupied)
            raise ValueError(f"Los siguientes equipos ya están en otra solicitud activa: {items_str}")

        notes_map = notes_map or {}
        for item_id in item_ids:
            if item_id in already_in_this:
                continue
            item = db.get(InventoryItem, item_id)
            if not item:
                raise ValueError(f"Equipo {item_id} no encontrado")
            if not item.is_active:
                raise ValueError(f"El equipo {item.inventory_number} ya está dado de baja")

            ri = InventoryRetirementRequestItem(
                request_id=request_id,
                item_id=item_id,
                item_notes=notes_map.get(item_id),
            )
            db.add(ri)

        db.commit()
        db.refresh(req)
        return req

    @staticmethod
    def remove_item(db: Session, request_id: int, item_id: int, user_id: int) -> InventoryRetirementRequest:
        req = db.get(InventoryRetirementRequest, request_id)
        if not req:
            raise ValueError("Solicitud no encontrada")
        if req.status != "DRAFT":
            raise ValueError("Solo se puede modificar una solicitud en estado DRAFT")
        if req.requested_by_id != user_id:
            raise ValueError("No puede modificar una solicitud de otro usuario")

        ri = (
            db.query(InventoryRetirementRequestItem)
            .filter_by(request_id=request_id, item_id=item_id)
            .first()
        )
        if ri:
            db.delete(ri)
            db.commit()

        db.refresh(req)
        return req

    @staticmethod
    def submit_request(db: Session, request_id: int, user_id: int) -> InventoryRetirementRequest:
        """Cambia estado DRAFT → PENDING (enviar para revisión)."""
        req = db.get(InventoryRetirementRequest, request_id)
        if not req:
            raise ValueError("Solicitud no encontrada")
        if req.requested_by_id != user_id:
            raise ValueError("No puede enviar una solicitud de otro usuario")
        if req.status != "DRAFT":
            raise ValueError(f"Solo se puede enviar una solicitud en estado DRAFT (actual: {req.status})")
        if req.items.count() == 0:
            raise ValueError("La solicitud debe tener al menos un equipo antes de enviarse")

        req.status = "PENDING"
        req.updated_at = datetime.now()
        db.commit()
        db.refresh(req)
        return req

    @staticmethod
    def approve_request(db: Session, request_id: int, admin_id: int, review_notes: str = None, ip_address: str = None) -> InventoryRetirementRequest:
        """Aprueba la solicitud y ejecuta la baja de todos los equipos."""
        from itcj2.apps.helpdesk.services.inventory_service import InventoryService

        req = db.get(InventoryRetirementRequest, request_id)
        if not req:
            raise ValueError("Solicitud no encontrada")
        if req.status != "PENDING":
            raise ValueError(f"Solo se puede aprobar una solicitud en estado PENDING (actual: {req.status})")

        req.status = "APPROVED"
        req.reviewed_by_id = admin_id
        req.reviewed_at = datetime.now()
        req.review_notes = review_notes
        req.updated_at = datetime.now()

        reason_base = f"Solicitud de baja aprobada. Folio: {req.folio}."
        if review_notes:
            reason_base += f" {review_notes}"

        for ri in req.items:
            try:
                item = db.get(InventoryItem, ri.item_id)
                was_locked = item.is_locked if item else False
                reason = reason_base
                if was_locked:
                    reason += " El equipo estaba bloqueado por campaña de inventario al momento de la baja."
                InventoryService.deactivate_item(
                    db,
                    item_id=ri.item_id,
                    deactivated_by_id=admin_id,
                    reason=reason,
                    ip_address=ip_address,
                )
            except ValueError as e:
                logger.warning(f"approve_request: no se pudo dar de baja item {ri.item_id}: {e}")

        db.commit()
        db.refresh(req)
        return req

    @staticmethod
    def reject_request(db: Session, request_id: int, admin_id: int, review_notes: str) -> InventoryRetirementRequest:
        req = db.get(InventoryRetirementRequest, request_id)
        if not req:
            raise ValueError("Solicitud no encontrada")
        if req.status != "PENDING":
            raise ValueError(f"Solo se puede rechazar una solicitud en estado PENDING (actual: {req.status})")
        if not review_notes or len(review_notes.strip()) < 5:
            raise ValueError("Debe indicar el motivo del rechazo (mínimo 5 caracteres)")

        req.status = "REJECTED"
        req.reviewed_by_id = admin_id
        req.reviewed_at = datetime.now()
        req.review_notes = review_notes.strip()
        req.updated_at = datetime.now()
        db.commit()
        db.refresh(req)
        return req

    @staticmethod
    def cancel_request(db: Session, request_id: int, user_id: int) -> InventoryRetirementRequest:
        req = db.get(InventoryRetirementRequest, request_id)
        if not req:
            raise ValueError("Solicitud no encontrada")
        if req.requested_by_id != user_id:
            raise ValueError("No puede cancelar una solicitud de otro usuario")
        if req.status not in ("DRAFT", "PENDING"):
            raise ValueError(f"No se puede cancelar una solicitud en estado {req.status}")

        req.status = "CANCELLED"
        req.updated_at = datetime.now()
        db.commit()
        db.refresh(req)
        return req

    @staticmethod
    def attach_document(db: Session, request_id: int, file, filename: str, user_id: int) -> InventoryRetirementRequest:
        """Guarda un archivo adjunto a la solicitud."""
        import shutil

        req = db.get(InventoryRetirementRequest, request_id)
        if not req:
            raise ValueError("Solicitud no encontrada")
        if req.requested_by_id != user_id:
            raise ValueError("No puede adjuntar documentos a una solicitud de otro usuario")
        if req.status not in ("DRAFT", "PENDING"):
            raise ValueError("Solo se puede adjuntar documentos a solicitudes en estado DRAFT o PENDING")

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Tipo de archivo no permitido. Permitidos: {', '.join(ALLOWED_EXTENSIONS)}")

        os.makedirs(UPLOAD_BASE, exist_ok=True)
        dest_path = os.path.join(UPLOAD_BASE, f"{req.folio}.{ext}")

        with open(dest_path, "wb") as f:
            shutil.copyfileobj(file, f)

        req.document_path = dest_path
        req.document_original_name = filename
        req.updated_at = datetime.now()
        db.commit()
        db.refresh(req)
        return req

    @staticmethod
    def generate_format(db: Session, request_id: int):
        """
        Genera el PDF del formato oficial de baja.
        PLACEHOLDER — implementar cuando se comparta el formato oficial.
        """
        raise NotImplementedError("Generación de formato pendiente. Adjunta el documento manualmente.")

    # ── Consultas ─────────────────────────────────────────────────────────────

    @staticmethod
    def get_requests(db: Session, user_id: int, is_admin: bool, filters: dict = None) -> dict:
        """Lista solicitudes. Admin ve todas, otros solo las suyas."""
        filters = filters or {}
        query = db.query(InventoryRetirementRequest)

        if not is_admin:
            query = query.filter(InventoryRetirementRequest.requested_by_id == user_id)

        if filters.get("status"):
            query = query.filter(InventoryRetirementRequest.status == filters["status"].upper())

        if filters.get("folio"):
            query = query.filter(InventoryRetirementRequest.folio.ilike(f"%{filters['folio']}%"))

        query = query.order_by(InventoryRetirementRequest.created_at.desc())

        page = max(1, int(filters.get("page", 1)))
        per_page = min(100, int(filters.get("per_page", 20)))
        total = query.count()
        items = query.offset((page - 1) * per_page).limit(per_page).all()

        return {
            "requests": [r.to_dict() for r in items],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page,
        }
