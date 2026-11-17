"""Avisos de Cámaras por la campana de la plataforma (sin correo).

Nada secreto viaja en title, body ni data: solo el nombre del DVR y de quien actuó.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TYPE_PASSWORD_CHANGED = "DVR_PASSWORD_CHANGED"


def notify_password_changed(db: Session, dvr, actor_id: int) -> None:
    """Avisa a todos los que ven `dvr`, menos a `actor_id`. No hace commit.

    Corre en un SAVEPOINT: si falla, se registra y el cambio de contraseña sigue.
    """
    try:
        with db.begin_nested():
            from sqlalchemy.orm import joinedload
            from itcj2.apps.cameras.services import dvr_service
            from itcj2.core.models.user import User
            from itcj2.core.services.authz_service import users_with_assignment_select
            from itcj2.core.services.notification_service import NotificationService

            actor = db.get(User, actor_id)
            actor_name = actor.full_name if actor else "Alguien"
            candidates = (db.query(User).options(joinedload(User.role))
                          .filter(User.is_active.is_(True), User.id != actor_id,
                                  User.id.in_(users_with_assignment_select(db, dvr_service.APP)))
                          .all())
            for u in candidates:
                viewer = dvr_service.viewer_for(
                    db, {"sub": str(u.id), "role": u.role.name if u.role else None})
                if dvr_service.get_visible(db, viewer, dvr.id) is None:
                    continue
                NotificationService.create(
                    db, u.id, app_name=dvr_service.APP, type=TYPE_PASSWORD_CHANGED,
                    title="Cambió la contraseña de un DVR",
                    body=f"{dvr.name}: {actor_name} la cambió. Revélala en Cámaras cuando la necesites.",
                    data={"url": "/cameras/", "dvr_id": dvr.id})
    except Exception as e:  # noqa: BLE001 - el aviso nunca debe tumbar el cambio
        logger.exception("No se pudo avisar el cambio de contraseña del DVR %s (%s)",
                         dvr.id, type(e).__name__)
