# itcj/core/models/department.py
from itcj.core.extensions import db

class Department(db.Model):
    __tablename__ = 'departments'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    icon_class = db.Column(db.String(50), nullable=True)  # ⭐ NUEVO
    parent_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.text("NOW()"), nullable=False)
    
    # Relaciones
    positions = db.relationship('Position', back_populates='department', lazy='dynamic')
    parent = db.relationship('Department', remote_side=[id], backref='subdepartments')

    def is_subdirection(self):
        """Verifica si es una subdirección (no tiene padre)"""
        return self.parent_id is None
    
    def get_children_count(self):
        """Obtiene cantidad de departamentos hijos"""
        return Department.query.filter_by(parent_id=self.id, is_active=True).count()

    def get_head_position(self):
        """Obtiene el puesto de jefe del departamento"""
        return self.positions.filter_by(
            code=f'jefe_{self.code}',
            is_active=True
        ).first()
    
    def get_head_user(self):
        """Obtiene el usuario que es jefe del departamento"""
        head_position = self.get_head_position()
        if not head_position:
            return None
        
        from itcj.core.models.position import UserPosition
        assignment = UserPosition.query.filter_by(
            position_id=head_position.id,
            is_active=True
        ).first()
        
        return assignment.user if assignment else None
    
    def to_dict(self, include_children=False):
        head_user = self.get_head_user()
        data = {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'icon_class': self.icon_class or 'bi-building',  # ⭐ NUEVO
            'is_active': self.is_active,
            'is_subdirection': self.is_subdirection(),  # ⭐ NUEVO
            'parent_id': self.parent_id,  # ⭐ NUEVO
            'positions_count': self.positions.filter_by(is_active=True).count(),
            'children_count': self.get_children_count() if self.is_subdirection() else 0,  # ⭐ NUEVO
            'head': {
                'full_name': head_user.full_name,
                'email': head_user.email
            } if head_user else None
        }
        
        if include_children and self.is_subdirection():
            data['children'] = [
                child.to_dict() for child in 
                Department.query.filter_by(parent_id=self.id, is_active=True).all()
            ]
        
        return data