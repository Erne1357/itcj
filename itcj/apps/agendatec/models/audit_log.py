from . import db

class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.BigInteger, primary_key=True)

    actor_id = db.Column(db.BigInteger, db.ForeignKey("users.id", onupdate="CASCADE", ondelete="SET NULL"))
    action = db.Column(db.Text, nullable=False)   # e.g. 'REQUEST_STATUS_CHANGED'
    entity = db.Column(db.Text, nullable=False)   # e.g. 'requests', 'appointments'
    entity_id = db.Column(db.BigInteger)          # affected row id
    payload_json = db.Column(db.JSON)

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))

    actor = db.relationship("User", back_populates="audit_logs")

    def __repr__(self) -> str:
        return f"<AuditLog {self.id} actor={self.actor_id} action={self.action} entity={self.entity}:{self.entity_id}>"
