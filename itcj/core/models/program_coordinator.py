from . import db

class ProgramCoordinator(db.Model):
    __tablename__ = "program_coordinator"

    program_id = db.Column(db.Integer, db.ForeignKey("programs.id", onupdate="CASCADE", ondelete="CASCADE"), primary_key=True)
    coordinator_id = db.Column(db.Integer, db.ForeignKey("coordinators.id", onupdate="CASCADE", ondelete="CASCADE"), primary_key=True)

    program = db.relationship("Program", back_populates="program_coordinators")
    coordinator = db.relationship("Coordinator", back_populates="program_coordinators")

    def __repr__(self) -> str:
        return f"<ProgramCoordinator program={self.program_id} coord={self.coordinator_id}>"
