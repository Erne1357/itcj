"""Notificaciones in-app de TitulaTec.

Enruta los eventos clave por el ``NotificationService`` del core para que aparezcan
en el tab **Avisos** del shell mobile (superficie única en móvil) y en el FAB por-app
(standalone/desktop). El click abre la app en el iframe vía ``data['url']``.

Convención: ``app_name='titulatec'`` · ``data={'url', 'process_id', 'phase_number'}``.
No hace commit: el service que llama es dueño de la transacción.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("itcj2.apps.titulatec.notify")


def notify_student(
    db: Session,
    student_id: int,
    *,
    type: str,
    title: str,
    body: Optional[str] = None,
    process_id: Optional[int] = None,
    phase_number: Optional[int] = None,
) -> None:
    """Crea una notificación para el alumno (best-effort; nunca rompe el flujo)."""
    url = "/titulatec/student/dashboard"
    if phase_number is not None:
        url = f"/titulatec/student/fase/{phase_number}"
    try:
        from itcj2.core.services.notification_service import NotificationService

        NotificationService.create(
            db,
            user_id=student_id,
            app_name="titulatec",
            type=type,
            title=title,
            body=body,
            data={"url": url, "process_id": process_id, "phase_number": phase_number},
        )
    except Exception as exc:  # pragma: no cover - notificación no debe tumbar la acción
        logger.warning("No se pudo crear notificación titulatec (%s): %s", type, exc)
