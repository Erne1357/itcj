"""
Servicio de Campañas de Inventario.

Flujo principal:
  CC crea campaña (OPEN)
    → registra / asigna items
    → cierra campaña → notifica jefe de dpto (PENDING_VALIDATION)
      → jefe aprueba → bloquea items, notifica CC (VALIDATED)
      → jefe rechaza → notifica CC (REJECTED)
        → CC puede reabrir (OPEN) y corregir

Funciones de consulta:
  - get_campaign_comparison: diferencia items nuevos vs pre-existentes del dpto
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.inventory_campaign import InventoryCampaign
from itcj2.apps.helpdesk.models.inventory_campaign_validation import InventoryCampaignValidation
from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
from itcj2.apps.helpdesk.services.inventory_history_service import InventoryHistoryService

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────────

def _get_department_head_ids(db: Session, department_id: int) -> list[int]:
    """
    Retorna los user_id de todos los jefes de departamento activos
    cuya posición pertenece al departamento indicado.

    Busca usuarios que:
      1. Tengan rol 'department_head' en la app 'helpdesk'.
      2. Tengan una UserPosition activa en una posición de ese departamento.
    """
    from itcj2.core.models.position import Position, UserPosition
    from itcj2.core.models.user_app_role import UserAppRole
    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role

    dept_head_user_ids = (
        db.query(UserAppRole.user_id)
        .join(Role, Role.id == UserAppRole.role_id)
        .join(App, App.id == UserAppRole.app_id)
        .filter(Role.name == 'department_head', App.key == 'helpdesk')
        .subquery()
    )

    rows = (
        db.query(UserPosition.user_id)
        .join(Position, Position.id == UserPosition.position_id)
        .filter(
            UserPosition.user_id.in_(dept_head_user_ids),
            Position.department_id == department_id,
            UserPosition.is_active.is_(True),
        )
        .distinct()
        .all()
    )
    return [r[0] for r in rows]


def _get_comp_center_ids(db: Session) -> list[int]:
    """
    Retorna los user_id del personal del Centro de Cómputo:
      - Usuarios con posición 'secretary_comp_center'
      - Usuarios con rol 'tech_desarrollo' o 'tech_soporte' en helpdesk
    """
    from itcj2.core.services.authz_service import _get_users_with_position
    from itcj2.core.models.user_app_role import UserAppRole
    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role

    # Por posición
    secretary_ids = [
        u if isinstance(u, int) else u.id
        for u in (_get_users_with_position(db, ['secretary_comp_center']) or [])
    ]

    # Por rol
    tech_ids = (
        db.query(UserAppRole.user_id)
        .join(Role, Role.id == UserAppRole.role_id)
        .join(App, App.id == UserAppRole.app_id)
        .filter(
            Role.name.in_(['tech_desarrollo', 'tech_soporte']),
            App.key == 'helpdesk',
        )
        .all()
    )
    tech_ids = [r[0] for r in tech_ids]

    return list(set(secretary_ids + tech_ids))


def _notify_users(
    db: Session,
    user_ids: list[int],
    notification_type: str,
    title: str,
    body: str,
    campaign_url: str,
) -> None:
    """Envía notificación a una lista de usuarios usando NotificationService."""
    from itcj2.core.services.notification_service import NotificationService

    for uid in user_ids:
        try:
            NotificationService.create(
                db=db,
                user_id=uid,
                app_name='helpdesk',
                type=notification_type,
                title=title,
                body=body,
                data={'url': campaign_url},
            )
        except Exception as exc:
            logger.error(f"_notify_users: error notificando user_id={uid}: {exc}", exc_info=True)


# ──────────────────────────────────────────────────────────────────────────────
# Servicio principal
# ──────────────────────────────────────────────────────────────────────────────

class CampaignService:
    """Lógica de negocio para campañas de inventario."""

    # ── Folio ─────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_folio(db: Session) -> str:
        """Genera folio único global por año: CAM-{YEAR}-{SEQ:03d}."""
        year = datetime.now().year
        last = (
            db.query(InventoryCampaign)
            .filter(InventoryCampaign.folio.like(f"CAM-{year}-%"))
            .order_by(InventoryCampaign.id.desc())
            .first()
        )
        if last:
            try:
                seq = int(last.folio.split("-")[-1]) + 1
            except Exception:
                seq = 1
        else:
            seq = 1
        return f"CAM-{year}-{seq:03d}"

    # ── Crear campaña ─────────────────────────────────────────────────────────

    @staticmethod
    def create_campaign(
        db: Session,
        department_id: int,
        title: str,
        created_by_id: int,
        ip: Optional[str] = None,
        notes: Optional[str] = None,
        academic_period_id: Optional[int] = None,
    ) -> InventoryCampaign:
        """
        Crea una nueva campaña en estado OPEN.

        Valida que no exista otra campaña OPEN o PENDING_VALIDATION
        para el mismo departamento.
        """
        if not title or len(title.strip()) < 5:
            raise ValueError("El título debe tener al menos 5 caracteres.")

        existing = (
            db.query(InventoryCampaign)
            .filter(
                InventoryCampaign.department_id == department_id,
                InventoryCampaign.status.in_(['OPEN', 'PENDING_VALIDATION']),
            )
            .first()
        )
        if existing:
            raise ValueError(
                f"Ya existe una campaña activa para este departamento "
                f"(Folio: {existing.folio}, Estado: {existing.status}). "
                f"Debe cerrarla o esperar su validación antes de crear una nueva."
            )

        folio = CampaignService.generate_folio(db)
        campaign = InventoryCampaign(
            folio=folio,
            department_id=department_id,
            academic_period_id=academic_period_id,
            status='OPEN',
            title=title.strip(),
            notes=notes.strip() if notes else None,
            created_by_id=created_by_id,
            started_at=datetime.now(),
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        logger.info(f"Campaña creada: {folio} para dept_id={department_id} por user_id={created_by_id}")
        return campaign

    # ── Asignación de items ───────────────────────────────────────────────────

    @staticmethod
    def assign_item(
        db: Session,
        campaign_id: int,
        item_id: int,
        assigned_by_id: int,
        ip: Optional[str] = None,
    ) -> InventoryItem:
        """
        Asocia un item individual a la campaña.
        El item debe pertenecer al mismo departamento.
        """
        campaign = db.get(InventoryCampaign, campaign_id)
        if not campaign:
            raise ValueError("Campaña no encontrada.")
        if not campaign.is_open:
            raise ValueError(f"Solo se pueden asignar items a campañas en estado OPEN (actual: {campaign.status}).")

        item = db.get(InventoryItem, item_id)
        if not item or not item.is_active:
            raise ValueError("Equipo no encontrado o dado de baja.")
        if item.department_id != campaign.department_id:
            raise ValueError("El equipo no pertenece al departamento de esta campaña.")
        if item.campaign_id == campaign_id:
            return item  # ya asignado, no hacer nada
        if item.campaign_id is not None:
            raise ValueError(
                f"El equipo ya está asignado a otra campaña (ID: {item.campaign_id})."
            )

        item.campaign_id = campaign_id
        InventoryHistoryService.log_event(
            db=db,
            item_id=item_id,
            event_type='CAMPAIGN_ASSIGNED',
            performed_by_id=assigned_by_id,
            new_value={'campaign_id': campaign_id, 'folio': campaign.folio},
            ip_address=ip,
        )
        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def bulk_assign_items(
        db: Session,
        campaign_id: int,
        item_ids: list[int],
        assigned_by_id: int,
        ip: Optional[str] = None,
    ) -> dict:
        """
        Asigna en masa una lista de items a la campaña.

        Pensado para la ronda activa: items ya registrados antes de que
        existiera el sistema de campañas (campaign_id = NULL).

        Retorna un resumen con los resultados por item.
        """
        campaign = db.get(InventoryCampaign, campaign_id)
        if not campaign:
            raise ValueError("Campaña no encontrada.")
        if not campaign.is_open:
            raise ValueError(f"Solo se pueden asignar items a campañas OPEN (actual: {campaign.status}).")

        result = {'assigned': [], 'skipped': [], 'errors': []}

        items = (
            db.query(InventoryItem)
            .filter(
                InventoryItem.id.in_(item_ids),
                InventoryItem.is_active.is_(True),
            )
            .all()
        )
        found_ids = {i.id for i in items}

        for item_id in item_ids:
            if item_id not in found_ids:
                result['errors'].append({'id': item_id, 'reason': 'Equipo no encontrado o dado de baja.'})
                continue

            item = next(i for i in items if i.id == item_id)

            if item.department_id != campaign.department_id:
                result['errors'].append({'id': item_id, 'reason': 'No pertenece al departamento de la campaña.'})
                continue
            if item.campaign_id == campaign_id:
                result['skipped'].append(item_id)
                continue
            if item.campaign_id is not None:
                result['errors'].append({
                    'id': item_id,
                    'reason': f'Ya asignado a campaña ID={item.campaign_id}.',
                })
                continue

            item.campaign_id = campaign_id
            InventoryHistoryService.log_event(
                db=db,
                item_id=item_id,
                event_type='CAMPAIGN_ASSIGNED',
                performed_by_id=assigned_by_id,
                new_value={'campaign_id': campaign_id, 'folio': campaign.folio},
                ip_address=ip,
            )
            result['assigned'].append(item_id)

        db.commit()
        logger.info(
            f"bulk_assign_items campaña {campaign.folio}: "
            f"asignados={len(result['assigned'])}, "
            f"saltados={len(result['skipped'])}, "
            f"errores={len(result['errors'])}"
        )
        return result

    @staticmethod
    def unassign_item(
        db: Session,
        campaign_id: int,
        item_id: int,
        unassigned_by_id: int,
        ip: Optional[str] = None,
    ) -> InventoryItem:
        """Desvincula un item de la campaña. Solo mientras esté OPEN."""
        campaign = db.get(InventoryCampaign, campaign_id)
        if not campaign:
            raise ValueError("Campaña no encontrada.")
        if not campaign.is_open:
            raise ValueError("Solo se puede desvincular items de campañas en estado OPEN.")

        item = db.get(InventoryItem, item_id)
        if not item or item.campaign_id != campaign_id:
            raise ValueError("El equipo no pertenece a esta campaña.")

        item.campaign_id = None
        InventoryHistoryService.log_event(
            db=db,
            item_id=item_id,
            event_type='CAMPAIGN_UNASSIGNED',
            performed_by_id=unassigned_by_id,
            old_value={'campaign_id': campaign_id, 'folio': campaign.folio},
            ip_address=ip,
        )
        db.commit()
        db.refresh(item)
        return item

    # ── Cerrar campaña (CC → jefe) ────────────────────────────────────────────

    @staticmethod
    def close_campaign(
        db: Session,
        campaign_id: int,
        closed_by_id: int,
        ip: Optional[str] = None,
    ) -> InventoryCampaign:
        """
        Cierra la campaña para enviarla a validación del jefe de departamento.
        OPEN → PENDING_VALIDATION.
        Notifica a todos los jefes de departamento del dpto de la campaña.
        """
        campaign = db.get(InventoryCampaign, campaign_id)
        if not campaign:
            raise ValueError("Campaña no encontrada.")
        if not campaign.is_open:
            raise ValueError(f"Solo se puede cerrar una campaña en estado OPEN (actual: {campaign.status}).")
        if campaign.items_count == 0:
            raise ValueError("La campaña debe tener al menos un item antes de cerrarla.")

        campaign.status = 'PENDING_VALIDATION'
        campaign.closed_at = datetime.now()
        campaign.closed_by_id = closed_by_id
        db.commit()
        db.refresh(campaign)

        # Notificar a jefes de departamento
        try:
            head_ids = _get_department_head_ids(db, campaign.department_id)
            if head_ids:
                _notify_users(
                    db=db,
                    user_ids=head_ids,
                    notification_type='CAMPAIGN_PENDING_VALIDATION',
                    title=f'Inventario pendiente de validación — {campaign.folio}',
                    body=(
                        f'El Centro de Cómputo ha cerrado la campaña "{campaign.title}" '
                        f'y requiere tu validación.'
                    ),
                    campaign_url=f'/help-desk/inventory/campaigns/{campaign.id}/validate',
                )
        except Exception as exc:
            logger.error(f"close_campaign: error enviando notificaciones: {exc}", exc_info=True)

        logger.info(f"Campaña {campaign.folio} cerrada por user_id={closed_by_id}")
        return campaign

    # ── Validar campaña (jefe de dpto) ────────────────────────────────────────

    @staticmethod
    def validate_campaign(
        db: Session,
        campaign_id: int,
        action: str,
        performed_by_id: int,
        notes: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> InventoryCampaign:
        """
        El jefe de departamento aprueba o rechaza la campaña.

        action: 'approve' | 'reject'

        Si aprueba (VALIDATED):
          - Bloquea todos los items de la campaña (is_locked=True).
          - Registra validated_at y validated_by_id en cada item.
          - Registra InventoryCampaignValidation con snapshot.
          - Notifica al CC.

        Si rechaza (REJECTED):
          - Los items NO se bloquean.
          - Guarda rejection_reason.
          - Registra InventoryCampaignValidation.
          - Notifica al CC.
        """
        if action not in ('approve', 'reject'):
            raise ValueError("El parámetro 'action' debe ser 'approve' o 'reject'.")

        campaign = db.get(InventoryCampaign, campaign_id)
        if not campaign:
            raise ValueError("Campaña no encontrada.")
        if not campaign.is_pending_validation:
            raise ValueError(
                f"Solo se puede validar una campaña en estado PENDING_VALIDATION "
                f"(actual: {campaign.status})."
            )

        if action == 'reject' and (not notes or len(notes.strip()) < 5):
            raise ValueError("Debe indicar el motivo del rechazo (mínimo 5 caracteres).")

        now = datetime.now()

        # Snapshot de los items en este momento
        campaign_item_ids = [i.id for i in campaign.items.all()]
        dept_existing_ids = (
            db.query(InventoryItem.id)
            .filter(
                InventoryItem.department_id == campaign.department_id,
                InventoryItem.is_active.is_(True),
                InventoryItem.campaign_id.is_(None),
            )
            .all()
        )
        dept_existing_ids = [r[0] for r in dept_existing_ids]

        snapshot = {
            'total': len(campaign_item_ids) + len(dept_existing_ids),
            'new_items': campaign_item_ids,
            'existing_items': dept_existing_ids,
        }

        # Actualizar campaña
        if action == 'approve':
            campaign.status = 'VALIDATED'
            campaign.validated_at = now
            campaign.validated_by_id = performed_by_id
            campaign.validation_notes = notes.strip() if notes else None

            # Bloquear y verificar todos los items de la campaña
            from itcj2.apps.helpdesk.models.inventory_verification import InventoryVerification
            from itcj2.apps.helpdesk.models.inventory_history import InventoryHistory

            items = campaign.items.all()
            for item in items:
                item.is_locked = True
                item.validated_at = now
                item.validated_by_id = performed_by_id
                item.locked_campaign_id = campaign_id

                # Marcar como verificado por el jefe de departamento
                item.last_verified_at = now
                item.last_verified_by_id = performed_by_id

                # Registro formal de verificación (visible en pestaña de verificación)
                verification = InventoryVerification(
                    inventory_item_id=item.id,
                    verified_by_id=performed_by_id,
                    verified_at=now,
                    location_confirmed=item.location_detail,
                    status_found=item.status,
                    observations=f"Verificado automáticamente al aprobar campaña {campaign.folio}.",
                    changes_applied=None,
                )
                db.add(verification)

                # Historial del item
                InventoryHistoryService.log_event(
                    db=db,
                    item_id=item.id,
                    event_type='CAMPAIGN_VALIDATED',
                    performed_by_id=performed_by_id,
                    new_value={
                        'is_locked': True,
                        'campaign_id': campaign_id,
                        'folio': campaign.folio,
                    },
                    ip_address=ip,
                )
                db.add(InventoryHistory(
                    item_id=item.id,
                    event_type='VERIFIED',
                    old_value=None,
                    new_value={
                        'location_confirmed': item.location_detail,
                        'status_found': item.status,
                        'source': 'campaign_approval',
                        'folio': campaign.folio,
                    },
                    notes=f"Verificado por aprobación de campaña {campaign.folio}.",
                    performed_by_id=performed_by_id,
                    ip_address=ip,
                ))

            notification_type = 'CAMPAIGN_VALIDATED'
            notif_title = f'Inventario aprobado — {campaign.folio}'
            notif_body = (
                f'El jefe de departamento aprobó la campaña "{campaign.title}". '
                f'{len(items)} equipos han quedado bloqueados.'
            )

        else:  # reject
            campaign.status = 'REJECTED'
            campaign.validated_at = now
            campaign.validated_by_id = performed_by_id
            campaign.rejection_reason = notes.strip()

            notification_type = 'CAMPAIGN_REJECTED'
            notif_title = f'Inventario rechazado — {campaign.folio}'
            notif_body = f'El jefe de departamento rechazó la campaña "{campaign.title}": {notes.strip()}'

        # Registrar validación formal
        validation_record = InventoryCampaignValidation(
            campaign_id=campaign_id,
            action='APPROVED' if action == 'approve' else 'REJECTED',
            performed_by_id=performed_by_id,
            performed_at=now,
            notes=notes.strip() if notes else None,
            ip_address=ip,
            items_snapshot=snapshot,
        )
        db.add(validation_record)
        db.commit()
        db.refresh(campaign)

        # Notificar al CC
        try:
            cc_ids = _get_comp_center_ids(db)
            if cc_ids:
                _notify_users(
                    db=db,
                    user_ids=cc_ids,
                    notification_type=notification_type,
                    title=notif_title,
                    body=notif_body,
                    campaign_url=f'/help-desk/inventory/campaigns/{campaign.id}',
                )
        except Exception as exc:
            logger.error(f"validate_campaign: error enviando notificaciones: {exc}", exc_info=True)

        logger.info(
            f"Campaña {campaign.folio} {action}d por user_id={performed_by_id} "
            f"(nuevo status: {campaign.status})"
        )
        return campaign

    # ── Reabrir campaña (admin, tras rechazo) ─────────────────────────────────

    @staticmethod
    def reopen_campaign(
        db: Session,
        campaign_id: int,
        reopened_by_id: int,
        ip: Optional[str] = None,
    ) -> InventoryCampaign:
        """
        Reabre una campaña rechazada para que el CC pueda corregirla.
        REJECTED → OPEN.
        Solo permitido para admin (la validación de permiso se hace en la API).
        """
        campaign = db.get(InventoryCampaign, campaign_id)
        if not campaign:
            raise ValueError("Campaña no encontrada.")
        if not campaign.is_rejected:
            raise ValueError(
                f"Solo se puede reabrir una campaña en estado REJECTED (actual: {campaign.status})."
            )

        campaign.status = 'OPEN'
        campaign.rejection_reason = None
        campaign.validated_at = None
        campaign.validated_by_id = None
        campaign.closed_at = None
        campaign.closed_by_id = None
        db.commit()
        db.refresh(campaign)
        logger.info(f"Campaña {campaign.folio} reabierta por user_id={reopened_by_id}")
        return campaign

    # ── Consultas ─────────────────────────────────────────────────────────────

    @staticmethod
    def get_campaigns(
        db: Session,
        filters: dict = None,
        department_id: Optional[int] = None,
    ) -> dict:
        """
        Lista campañas con paginación y filtros.
        Si department_id está dado, filtra solo ese departamento (para jefes).
        """
        filters = filters or {}
        query = db.query(InventoryCampaign)

        if department_id is not None:
            query = query.filter(InventoryCampaign.department_id == department_id)
        elif filters.get('department_id'):
            query = query.filter(InventoryCampaign.department_id == int(filters['department_id']))

        if filters.get('status'):
            query = query.filter(InventoryCampaign.status == filters['status'].upper())

        if filters.get('academic_period_id'):
            query = query.filter(
                InventoryCampaign.academic_period_id == int(filters['academic_period_id'])
            )

        if filters.get('folio'):
            query = query.filter(InventoryCampaign.folio.ilike(f"%{filters['folio']}%"))

        query = query.order_by(InventoryCampaign.created_at.desc())

        page = max(1, int(filters.get('page', 1)))
        per_page = min(100, int(filters.get('per_page', 20)))
        total = query.count()
        items = query.offset((page - 1) * per_page).limit(per_page).all()

        return {
            'campaigns': [c.to_dict(include_relations=True) for c in items],
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page,
        }

    @staticmethod
    def get_campaign_comparison(db: Session, campaign_id: int) -> dict:
        """
        Calcula la comparación de items para la vista de validación del jefe.

        Retorna:
          new_items      — items registrados en esta campaña
          existing_items — items del departamento sin campaña (inventario histórico)
          summary        — conteos por estado
        """
        campaign = db.get(InventoryCampaign, campaign_id)
        if not campaign:
            raise ValueError("Campaña no encontrada.")

        # Items nuevos (en esta campaña)
        new_items_raw = campaign.items.all()

        # Items pre-existentes del departamento (sin campaña asociada o de otra campaña)
        existing_items_raw = (
            db.query(InventoryItem)
            .filter(
                InventoryItem.department_id == campaign.department_id,
                InventoryItem.is_active.is_(True),
                InventoryItem.campaign_id.is_(None),
            )
            .all()
        )

        # Serializar items nuevos con info de predecesor
        def _serialize_new(item: InventoryItem) -> dict:
            d = item.to_dict(include_relations=True)
            d['predecessor'] = None
            if item.has_predecessor and item.predecessor:
                pred = item.predecessor
                d['predecessor'] = {
                    'id': pred.id,
                    'inventory_number': pred.inventory_number,
                    'brand': pred.brand,
                    'model': pred.model,
                    'itcj_serial': pred.itcj_serial,
                    'supplier_serial': pred.supplier_serial,
                    'status': pred.status,
                    'is_locked': pred.is_locked,
                }
                # Diferencias campo a campo respecto al predecesor
                diff = {}
                for field in ('brand', 'model', 'supplier_serial', 'itcj_serial', 'id_tecnm', 'category_id'):
                    old_val = getattr(pred, field, None)
                    new_val = getattr(item, field, None)
                    if old_val != new_val:
                        diff[field] = {'old': old_val, 'new': new_val}
                d['changes_vs_predecessor'] = diff
            return d

        def _serialize_existing(item: InventoryItem) -> dict:
            d = item.to_dict(include_relations=True)
            # Indicar si este item fue reemplazado por alguno en la campaña
            successor = item.successor
            d['replaced_by'] = None
            if successor and successor.campaign_id == campaign_id:
                d['replaced_by'] = {
                    'id': successor.id,
                    'inventory_number': successor.inventory_number,
                    'brand': successor.brand,
                    'model': successor.model,
                }
            return d

        new_serialized = [_serialize_new(i) for i in new_items_raw]
        existing_serialized = [_serialize_existing(i) for i in existing_items_raw]

        # Conteos para el resumen
        replaced_count = sum(1 for i in existing_serialized if i['replaced_by'] is not None)
        new_with_predecessor = sum(1 for i in new_serialized if i['predecessor'] is not None)

        return {
            'campaign': campaign.to_dict(include_relations=True),
            'new_items': new_serialized,
            'existing_items': existing_serialized,
            'summary': {
                'new_items_count': len(new_serialized),
                'existing_items_count': len(existing_serialized),
                'new_with_predecessor': new_with_predecessor,
                'existing_replaced': replaced_count,
                'existing_unchanged': len(existing_serialized) - replaced_count,
            },
        }

    @staticmethod
    def get_open_campaign_for_department(
        db: Session,
        department_id: int,
    ) -> Optional[InventoryCampaign]:
        """
        Retorna la campaña OPEN activa de un departamento, si existe.
        Útil para el formulario de creación de items (pre-seleccionar campaña).
        """
        return (
            db.query(InventoryCampaign)
            .filter(
                InventoryCampaign.department_id == department_id,
                InventoryCampaign.status == 'OPEN',
            )
            .first()
        )
