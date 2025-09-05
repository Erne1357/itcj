from . import db

class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, unique=True, nullable=False)  # 'student','social_service','coordinator','admin'

    users = db.relationship("User", back_populates="role", cascade="all, delete", passive_deletes=True)

    def __repr__(self) -> str:
        return f"<Role {self.name}>"
