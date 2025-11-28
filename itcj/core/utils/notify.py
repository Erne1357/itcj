# utils/notify.py
"""
DEPRECATED: Este módulo está deprecado.
Use itcj.core.services.notification_service.NotificationService en su lugar.

Esta función se mantiene solo para backwards compatibility con AgendaTec.
"""
import warnings
from datetime import datetime
from itcj.apps.agendatec.models import db
from itcj.core.models.notification import Notification


def create_notification(*, user_id: int, type: str, title: str, body: str|None, data: dict|None,
                        source_request_id: int|None = None, source_appointment_id: int|None = None,
                        program_id: int|None = None) -> Notification:
    """
    DEPRECATED: Use NotificationService.create() instead.

    Esta función se mantiene para backwards compatibility con AgendaTec.
    Automáticamente asigna app_name='agendatec' y difunde vía SSE + WebSocket.
    """
    warnings.warn(
        "create_notification() is deprecated. Use NotificationService.create() instead.",
        DeprecationWarning,
        stacklevel=2
    )

    # Importar aquí para evitar dependencias circulares
    from itcj.core.services.notification_service import NotificationService

    # Llamar al nuevo servicio con app_name='agendatec' para backwards compatibility
    return NotificationService.create(
        user_id=user_id,
        app_name='agendatec',  # Default para AgendaTec
        type=type,
        title=title,
        body=body,
        data=data,
        source_request_id=source_request_id,
        source_appointment_id=source_appointment_id,
        program_id=program_id
    )
