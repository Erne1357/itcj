from sqlalchemy import func
from . import db

class SurveyDispatch(db.Model):
    __tablename__ = "agendatec_survey_dispatches"
    id            = db.Column(db.BigInteger, primary_key=True)
    campaign_code = db.Column(db.Text, nullable=False)
    user_id       = db.Column(db.BigInteger, db.ForeignKey("core_users.id"), nullable=False)
    request_id    = db.Column(db.BigInteger, db.ForeignKey("agendatec_requests.id"))
    email         = db.Column(db.Text, nullable=False)
    sent_at       = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    message_id    = db.Column(db.Text)
    status        = db.Column(db.Text, default="SENT", nullable=False)   # SENT | FAILED
    error         = db.Column(db.Text)

    __table_args__ = (
        db.UniqueConstraint("campaign_code", "user_id", name="uq_survey_dispatches_campaign_user"),
    )
