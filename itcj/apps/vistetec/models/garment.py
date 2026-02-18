from itcj.core.extensions import db


class Garment(db.Model):
    """Prenda de vestir registrada en VisteTec."""
    __tablename__ = 'vistetec_garments'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)  # PRD-2025-0001

    # Descripción
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50), nullable=False, index=True)  # camisa, pantalon, vestido, zapatos
    gender = db.Column(db.String(20))  # masculino, femenino, unisex

    # Detalles
    size = db.Column(db.String(20))   # S, M, L, XL, 28, 30
    brand = db.Column(db.String(50))
    color = db.Column(db.String(30))
    material = db.Column(db.String(50))
    condition = db.Column(db.String(20), nullable=False)  # nuevo, como_nuevo, buen_estado, usado

    # Estado
    status = db.Column(db.String(20), nullable=False, server_default=db.text("'available'"), index=True)
    # available, reserved, delivered, withdrawn

    # Imagen (una sola por prenda)
    image_path = db.Column(db.String(255))

    # Trazabilidad
    donated_by_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)
    received_by_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)
    registered_by_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)

    delivered_to_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    delivered_by_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, server_default=db.text("NOW()"), onupdate=db.func.now())

    # Relaciones
    donated_by = db.relationship('User', foreign_keys=[donated_by_id], lazy='joined')
    received_by = db.relationship('User', foreign_keys=[received_by_id], lazy='joined')
    registered_by = db.relationship('User', foreign_keys=[registered_by_id], lazy='joined')
    delivered_to = db.relationship('User', foreign_keys=[delivered_to_id], lazy='joined')
    delivered_by = db.relationship('User', foreign_keys=[delivered_by_id], lazy='joined')

    appointments = db.relationship('itcj.apps.vistetec.models.appointment.Appointment', back_populates='garment', lazy='dynamic')
    donation = db.relationship('Donation', back_populates='garment', uselist=False, lazy='joined')

    __table_args__ = (
        db.Index('ix_vistetec_garment_status_category', 'status', 'category'),
        db.Index('ix_vistetec_garment_gender_size', 'gender', 'size'),
    )

    def __repr__(self):
        return f'<Garment {self.code} - {self.name}>'

    def to_dict(self, include_relations=False):
        data = {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'category': self.category,
            'gender': self.gender,
            'size': self.size,
            'brand': self.brand,
            'color': self.color,
            'material': self.material,
            'condition': self.condition,
            'status': self.status,
            'image_path': self.image_path,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_relations:
            data['donated_by'] = self.donated_by.to_dict() if self.donated_by else None
            data['received_by'] = self.received_by.to_dict() if self.received_by else None
            data['registered_by'] = self.registered_by.to_dict() if self.registered_by else None
            data['delivered_to'] = self.delivered_to.to_dict() if self.delivered_to else None
            data['delivered_by'] = self.delivered_by.to_dict() if self.delivered_by else None
        return data
