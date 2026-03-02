from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.sql import func

from itcj2.models.base import Base


class SurveyDispatch(Base):
    __tablename__ = "agendatec_survey_dispatches"

    id = Column(BigInteger, primary_key=True)
    campaign_code = Column(Text, nullable=False)
    user_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)
    request_id = Column(BigInteger, ForeignKey("agendatec_requests.id"))
    email = Column(Text, nullable=False)
    sent_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    message_id = Column(Text)
    status = Column(Text, default="SENT", nullable=False)  # SENT | FAILED
    error = Column(Text)

    __table_args__ = (
        UniqueConstraint("campaign_code", "user_id", name="uq_survey_dispatches_campaign_user"),
    )
