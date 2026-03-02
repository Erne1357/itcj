from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base

request_type_pg_enum = ENUM(
    "DROP", "APPOINTMENT",
    name="request_type_enum",
    create_type=False,
)
request_status_pg_enum = ENUM(
    "PENDING", "RESOLVED_SUCCESS", "RESOLVED_NOT_COMPLETED",
    "NO_SHOW", "ATTENDED_OTHER_SLOT", "CANCELED",
    name="request_status_enum",
    create_type=False,
)


class Request(Base):
    __tablename__ = "agendatec_requests"

    id = Column(BigInteger, primary_key=True)

    student_id = Column(
        BigInteger,
        ForeignKey("core_users.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    program_id = Column(
        Integer,
        ForeignKey("core_programs.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    period_id = Column(
        Integer,
        ForeignKey("core_academic_periods.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    type = Column(request_type_pg_enum, nullable=False)
    description = Column(Text)
    status = Column(request_status_pg_enum, nullable=False, server_default="PENDING")
    coordinator_comment = Column(Text)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    # Relaciones
    student = relationship("User", back_populates="requests")
    program = relationship("Program", back_populates="requests")
    period = relationship("AcademicPeriod", back_populates="requests")
    appointment = relationship(
        "Appointment",
        back_populates="request",
        uselist=False,
        cascade="all, delete",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Request {self.id} student={self.student_id} type={self.type} status={self.status}>"
