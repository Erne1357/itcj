# itcj/core/models/authz.py
from itcj.core.extensions import db

class App(db.Model):
    __tablename__ = "core_apps"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False, index=True)  # p.ej. 'agendatec'
    name = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now(), nullable=False)

    # Campos mobile
    visible_to_students = db.Column(db.Boolean, nullable=False, default=False)
    mobile_icon = db.Column(db.String(100), nullable=True)
    mobile_url = db.Column(db.String(255), nullable=True)
    mobile_enabled = db.Column(db.Boolean, nullable=False, default=True)

    # Relaciones útiles
    permissions = db.relationship("Permission", backref="app", cascade="all, delete-orphan", lazy="dynamic")

    def to_dict(self, include_mobile=False):
        data = {
            "id": self.id,
            "key": self.key,
            "name": self.name,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_mobile:
            data.update({
                "visible_to_students": self.visible_to_students,
                "mobile_icon": self.mobile_icon,
                "mobile_url": self.mobile_url,
                "mobile_enabled": self.mobile_enabled,
            })
        return data

