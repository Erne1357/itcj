# utils/notify.py
from datetime import datetime
from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.notification import Notification

def create_notification(*, user_id: int, type: str, title: str, body: str|None, data: dict|None,
                        source_request_id: int|None = None, source_appointment_id: int|None = None,
                        program_id: int|None = None) -> Notification:
    n = Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        data=(data or {}),
        source_request_id=source_request_id,
        source_appointment_id=source_appointment_id,
        program_id=program_id
    )
    db.session.add(n)
    db.session.flush()
    return n
