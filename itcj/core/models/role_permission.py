from itcj.core.extensions import db

class RolePermission(db.Model):
    __tablename__ = "role_permissions"
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    perm_id = db.Column(db.Integer, db.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)

    # Relaciones opcionales (no obligatorias)
    permission = db.relationship("Permission", lazy="joined")