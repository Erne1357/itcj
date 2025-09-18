from sqlalchemy.dialects.postgresql import ENUM
from . import db

# Map to existing PostgreSQL enum types created in DDL
request_type_pg_enum = ENUM("DROP", "APPOINTMENT", name="request_type_enum", create_type=False)
request_status_pg_enum = ENUM(
    "PENDING", "RESOLVED_SUCCESS", "RESOLVED_NOT_COMPLETED", "NO_SHOW", "ATTENDED_OTHER_SLOT", "CANCELED",
    name="request_status_enum", create_type=False
)

class Request(db.Model):
    __tablename__ = "agendatec_requests"

    id = db.Column(db.BigInteger, primary_key=True)

    student_id = db.Column(db.BigInteger, db.ForeignKey("users.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    program_id = db.Column(db.Integer, db.ForeignKey("programs.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)

    type = db.Column(request_type_pg_enum, nullable=False)
    description = db.Column(db.Text)
    status = db.Column(request_status_pg_enum, nullable=False, server_default="PENDING")
    coordinator_comment = db.Column(db.Text)

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))

    student = db.relationship("User", back_populates="requests")
    program = db.relationship("Program", back_populates="requests")
    # 1:1 with Appointment (appointments.request_id is UNIQUE)
    appointment = db.relationship("Appointment", back_populates="request", uselist=False, cascade="all, delete", passive_deletes=True)

    def __repr__(self) -> str:
        return f"<Request {self.id} student={self.student_id} type={self.type} status={self.status}>"
