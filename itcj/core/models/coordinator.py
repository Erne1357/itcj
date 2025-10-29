from . import db

class Coordinator(db.Model):
    __tablename__ = "core_coordinators"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("core_users.id", onupdate="CASCADE", ondelete="CASCADE"), unique=True, nullable=False)

    contact_email = db.Column(db.Text)
    office_hours = db.Column(db.Text)
    must_change_pw = db.Column(db.Boolean, nullable=False, server_default=db.text("TRUE"))

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))

    user = db.relationship("User", back_populates="coordinator")

    # association objects
    program_coordinators = db.relationship("ProgramCoordinator", back_populates="coordinator", cascade="all, delete-orphan", passive_deletes=True)

    # convenient many-to-many
    programs = db.relationship(
        "Program",
        secondary="core_program_coordinator",
        back_populates="coordinators",
        viewonly=True,
    )

    # one-to-many
    availability_windows = db.relationship("AvailabilityWindow", back_populates="coordinator", cascade="all, delete", passive_deletes=True)
    time_slots = db.relationship("TimeSlot", back_populates="coordinator", cascade="all, delete", passive_deletes=True)
    appointments = db.relationship("Appointment", back_populates="coordinator", cascade="all, delete", passive_deletes=True)

    def __repr__(self) -> str:
        return f"<Coordinator {self.id} user={self.user_id}>"
