# routes/api/notifications.py
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from itcj.core.utils.decorators import api_auth_required
from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.notification import Notification

api_notifications_bp = Blueprint("api_notifications", __name__)

def _current_uid() -> int:
    return int(g.current_user["sub"])

@api_notifications_bp.get("")
@api_auth_required
def list_notifications():
    """
    Query params:
      - unread: "1" para solo no leídas (default: todas)
      - limit: máx 50 (default 20)
      - before_id: paginación hacia atrás (opcional)
    """
    uid = _current_uid()
    unread = (request.args.get("unread") or "0") in ("1", "true", "True")
    limit = min(max(int(request.args.get("limit", 20)), 1), 50)
    before_id = request.args.get("before_id")

    q = Notification.query.filter_by(user_id=uid)
    if unread:
      q = q.filter_by(is_read=False)
    if before_id:
      try:
        bid = int(before_id)
        q = q.filter(Notification.id < bid)
      except:
        pass

    items = (q.order_by(Notification.id.desc())
               .limit(limit).all())
    return jsonify({"items": [n.to_dict() for n in items]})

@api_notifications_bp.patch("/<int:notif_id>/read")
@api_auth_required
def mark_read(notif_id: int):
    uid = _current_uid()
    n = Notification.query.filter_by(id=notif_id, user_id=uid).first()
    if not n:
        return jsonify({"error":"not_found"}), 404
    if not n.is_read:
        n.is_read = True
        n.read_at = datetime.now()
        db.session.commit()
    return jsonify({"ok": True})

@api_notifications_bp.patch("/read-all")
@api_auth_required
def mark_all_read():
    uid = _current_uid()
    db.session.query(Notification).filter_by(user_id=uid, is_read=False)\
        .update({"is_read": True, "read_at": datetime.now()}, synchronize_session=False)
    db.session.commit()
    return jsonify({"ok": True})
