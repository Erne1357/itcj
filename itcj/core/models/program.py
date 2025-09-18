from . import db

class Program(db.Model):
    __tablename__ = "programs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, unique=True, nullable=False)

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))

    # association objects
    program_coordinators = db.relationship("ProgramCoordinator", back_populates="program", cascade="all, delete-orphan", passive_deletes=True)

    # convenient many-to-many via association table
    coordinators = db.relationship(
        "Coordinator",
        secondary="program_coordinator",
        back_populates="programs",
        viewonly=True,
    )

    # one-to-many
    requests = db.relationship("Request", back_populates="program", cascade="all, delete", passive_deletes=True)
    appointments = db.relationship("Appointment", back_populates="program", cascade="all, delete", passive_deletes=True)

    def __repr__(self) -> str:
        return f"<Program {self.name}>"
