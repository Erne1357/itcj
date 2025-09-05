from . import db

class TimeSlot(db.Model):
    __tablename__ = "time_slots"

    id = db.Column(db.BigInteger, primary_key=True)
    coordinator_id = db.Column(db.Integer, db.ForeignKey("coordinators.id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False)

    day = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    is_booked = db.Column(db.Boolean, nullable=False, server_default=db.text("FALSE"))

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))

    coordinator = db.relationship("Coordinator", back_populates="time_slots")
    appointments = db.relationship("Appointment", back_populates="slot", cascade="all, delete", passive_deletes=True)

    def __repr__(self) -> str:
        return f"<TimeSlot {self.id} coord={self.coordinator_id} {self.start_time}-{self.end_time} booked={self.is_booked}>"
