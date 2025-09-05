from sqlalchemy import desc

def has_request(user_id) -> bool:
    """
    Check if the user has an request.
    """
    from models.user import User
    from models.request import Request

    user = User.query.get(user_id)
    if not user:
        return False
    request = Request.query.filter_by(student_id=user.id).order_by(desc(Request.created_at)).first()
    if not request:
        return False
    return request.status != "CANCELED"