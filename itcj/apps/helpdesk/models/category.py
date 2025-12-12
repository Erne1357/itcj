from itcj.core.extensions import db

class Category(db.Model):
    """
    Categorías para clasificar tickets (dinámicas, configurables por admin)
    Ejemplos:
    - Desarrollo: SII, SIILE, SIISAE, Moodle, Correo, AgendaTec, Tickets
    - Soporte: Hardware, Cableado, Proyectores, Impresoras, Red
    """
    __tablename__ = 'helpdesk_category'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Clasificación
    area = db.Column(db.String(20), nullable=False)  # 'DESARROLLO' | 'SOPORTE'
    code = db.Column(db.String(50), nullable=False, unique=True, index=True)  # 'dev_sii', 'sop_hardware'
    name = db.Column(db.String(100), nullable=False)  # 'SII', 'Hardware'
    description = db.Column(db.Text)

    # Campos personalizados
    field_template = db.Column(db.JSON, nullable=True)  # Plantilla de campos personalizados para esta categoría

    # Estado y orden
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    display_order = db.Column(db.Integer, default=0)  # Para ordenar en dropdowns
    
    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, server_default=db.text("NOW()"))
    
    # Relaciones
    tickets = db.relationship('Ticket', back_populates='category', lazy='dynamic')
    
    # Índices
    __table_args__ = (
        db.Index('ix_helpdesk_category_area_active', 'area', 'is_active'),
    )
    
    def __repr__(self):
        return f'<Category {self.area}:{self.name}>'
    
    def to_dict(self, include_field_template=False):
        data = {
            'id': self.id,
            'area': self.area,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'is_active': self.is_active,
            'display_order': self.display_order
        }

        if include_field_template:
            data['field_template'] = self.field_template

        return data