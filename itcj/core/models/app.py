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

    # Relaciones útiles
    permissions = db.relationship("Permission", backref="app", cascade="all, delete-orphan", lazy="dynamic")

