"""
DEPRECATED: Este módulo está deprecado.
Use itcj2.core.services.notification_service.NotificationService en su lugar.

Esta función se mantiene solo para backwards compatibility con AgendaTec.
"""
import warnings


def create_notification(
    *,
    user_id: int,
    type: str,
    title: str,
    body: str | None,
    data: dict | None,
    source_request_id: int | None = None,
    source_appointment_id: int | None = None,
    program_id: int | None = None,
    db=None,
):
    """
    DEPRECATED: Use NotificationService.create() instead.
    """
    warnings.warn(
        "create_notification() is deprecated. Use NotificationService.create() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from itcj2.core.services.notification_service import NotificationService

    return NotificationService.create(
        db=db,
        user_id=user_id,
        app_name='agendatec',
        type=type,
        title=title,
        body=body,
        data=data,
        source_request_id=source_request_id,
        source_appointment_id=source_appointment_id,
        program_id=program_id,
    )
