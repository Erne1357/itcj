from sqlalchemy.dialects.postgresql import ENUM
from . import db

appointment_status_pg_enum = ENUM("SCHEDULED", "DONE", "NO_SHOW", "CANCELED", name="appointment_status_enum", create_type=False)

class Appointment(db.Model):
    __tablename__ = "agendatec_appointments"

    id = db.Column(db.BigInteger, primary_key=True)

    request_id = db.Column(db.BigInteger, db.ForeignKey("agendatec_requests.id", onupdate="CASCADE", ondelete="CASCADE"), unique=True)
    student_id = db.Column(db.BigInteger, db.ForeignKey("core_users.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    coordinator_id = db.Column(db.Integer, db.ForeignKey("core_coordinators.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    program_id = db.Column(db.Integer, db.ForeignKey("core_programs.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)
    slot_id = db.Column(db.BigInteger, db.ForeignKey("agendatec_time_slots.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)

    status = db.Column(appointment_status_pg_enum, nullable=False, server_default="SCHEDULED")
    booked_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))

    # relationships
    request = db.relationship("Request", back_populates="appointment")
    student = db.relationship("User", back_populates="appointments")
    coordinator = db.relationship("Coordinator", back_populates="appointments")
    program = db.relationship("Program", back_populates="appointments")
    slot = db.relationship("TimeSlot", back_populates="appointments")

    def __repr__(self) -> str:
        return f"<Appointment {self.id} student={self.student_id} slot={self.slot_id} status={self.status}>"
