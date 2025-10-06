# itcj/core/models/department.py
from itcj.core.extensions import db
from datetime import datetime

class Department(db.Model):
    __tablename__ = 'departments'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relaciones
    positions = db.relationship('Position', back_populates='department', lazy='dynamic')
    
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
    
    def to_dict(self):
        head_user = self.get_head_user()
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'is_active': self.is_active,
            'positions_count': self.positions.filter_by(is_active=True).count(),
            'head': {
                'full_name': head_user.full_name,
                'email': head_user.email
            } if head_user else None
        }