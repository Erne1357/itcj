from itcj.core.extensions import db

class UserAppPerm(db.Model):
    __tablename__ = "user_app_perms"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    app_id  = db.Column(db.Integer, db.ForeignKey("apps.id",  ondelete="CASCADE"), primary_key=True)
    perm_id = db.Column(db.Integer, db.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)
    allow   = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (
        db.Index("ix_user_app_perms_user_app", "user_id", "app_id"),
    )