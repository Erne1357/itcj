from . import db

class Role(db.Model):
    __tablename__ = "core_roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, unique=True, nullable=False)  

    users = db.relationship("User", back_populates="role", cascade="all, delete", passive_deletes=True)

    def __repr__(self) -> str:
        return f"<Role {self.name}>"
