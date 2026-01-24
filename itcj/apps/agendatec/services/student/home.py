from sqlalchemy import desc

def has_request(user_id) -> bool:
    """
    Check if the user has a request in the active period.
    """
    from itcj.core.models.user import User
    from itcj.apps.agendatec.models.request import Request
    from itcj.core.services import period_service

    user = User.query.get(user_id)
    if not user:
        return False

    # Get active period
    period = period_service.get_active_period()
    if not period:
        return False

    # Check if user has a non-canceled request in the active period
    request = (Request.query
               .filter_by(student_id=user.id, period_id=period.id)
               .filter(Request.status != "CANCELED")
               .order_by(desc(Request.created_at))
               .first())

    return request is not None