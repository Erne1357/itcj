# models/notification.py
from sqlalchemy.dialects.postgresql import JSONB, ENUM
from . import db

notif_type_pg_enum = ENUM("APPOINTMENT_CREATED","APPOINTMENT_CANCELED", "REQUEST_STATUS_CHANGED", "DROP_CREATED", "SYSTEM",name="notif_type_enum", create_type=False)

class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    type = db.Column(notif_type_pg_enum, nullable=False)
    title = db.Column(db.Text, nullable=False)
    body = db.Column(db.Text)
    data = db.Column(JSONB, nullable=False, default=dict)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    read_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())

    source_request_id = db.Column(db.BigInteger, db.ForeignKey("requests.id", onupdate="CASCADE", ondelete="SET NULL"))
    source_appointment_id = db.Column(db.BigInteger, db.ForeignKey("appointments.id", onupdate="CASCADE", ondelete="SET NULL"))
    program_id = db.Column(db.Integer, db.ForeignKey("programs.id", onupdate="CASCADE", ondelete="SET NULL"))

    user = db.relationship("User", back_populates="notifications")

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "body": self.body,
            "data": self.data or {},
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "read_at": self.read_at.isoformat() if self.read_at else None,
        }
