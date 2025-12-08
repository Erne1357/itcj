from itcj.core.extensions import db
class Permission(db.Model):
    __tablename__ = "core_permissions"
    id = db.Column(db.Integer, primary_key=True)
    app_id = db.Column(db.Integer, db.ForeignKey("core_apps.id", ondelete="CASCADE"), nullable=False, index=True)
    code = db.Column(db.String(100), nullable=False)  # p.ej. 'requests.view'
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)

    __table_args__ = (
        db.UniqueConstraint("app_id", "code", name="uq_permissions_app_code"),
    )