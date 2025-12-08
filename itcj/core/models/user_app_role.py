from itcj.core.extensions import db

class UserAppRole(db.Model):
    __tablename__ = "core_user_app_roles"
    user_id = db.Column(db.Integer, db.ForeignKey("core_users.id", ondelete="CASCADE"), primary_key=True)
    app_id  = db.Column(db.Integer, db.ForeignKey("core_apps.id",  ondelete="CASCADE"), primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("core_roles.id", ondelete="CASCADE"), primary_key=True)

    __table_args__ = (
        db.Index("ix_user_app_roles_user_app", "user_id", "app_id"),
    )