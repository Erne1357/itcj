from . import db

class AvailabilityWindow(db.Model):
    __tablename__ = "agendatec_availability_windows"

    id = db.Column(db.Integer, primary_key=True)
    coordinator_id = db.Column(db.Integer, db.ForeignKey("core_coordinators.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)

    day = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    slot_minutes = db.Column(db.Integer, nullable=False, server_default=db.text("10"))

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))

    coordinator = db.relationship("Coordinator", back_populates="availability_windows")

    def __repr__(self) -> str:
        return f"<AvailabilityWindow coord={self.coordinator_id} {self.day} {self.start_time}-{self.end_time}>"
