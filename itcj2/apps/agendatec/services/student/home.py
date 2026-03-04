from sqlalchemy import desc
from sqlalchemy.orm import Session


def has_request(db: Session, user_id: int) -> bool:
    """
    Check if the user has a request in the active period.
    """
    from itcj2.apps.agendatec.models.request import Request
    from itcj2.core.models.user import User
    from itcj2.core.services import period_service

    user = db.get(User, user_id)
    if not user:
        return False

    period = period_service.get_active_period(db)
    if not period:
        return False

    request = (
        db.query(Request)
        .filter_by(student_id=user.id, period_id=period.id)
        .filter(Request.status != "CANCELED")
        .order_by(desc(Request.created_at))
        .first()
    )

    return request is not None
