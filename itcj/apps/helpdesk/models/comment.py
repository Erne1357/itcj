from itcj.core.extensions import db

class Comment(db.Model):
    """
    Comentarios en tickets.
    Pueden ser públicos (visibles para el usuario) o internos (solo staff).
    """
    __tablename__ = 'helpdesk_comment'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('helpdesk_ticket.id'), nullable=False, index=True)
    author_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=False)
    
    # Contenido
    content = db.Column(db.Text, nullable=False)
    
    # Visibilidad
    is_internal = db.Column(db.Boolean, default=False, nullable=False)
    # True = Solo visible para staff (secretary, técnicos, admin)
    # False = Visible para todos (incluido requester)
    
    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, server_default=db.text("NOW()"))
    
    # Relaciones
    ticket = db.relationship('Ticket', back_populates='comments')
    author = db.relationship('User', foreign_keys=[author_id])
    
    # Índice
    __table_args__ = (
        db.Index('ix_helpdesk_comment_ticket_created', 'ticket_id', 'created_at'),
    )
    
    def __repr__(self):
        return f'<Comment on Ticket#{self.ticket_id} by {self.author.username}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'content': self.content,
            'is_internal': self.is_internal,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'author': {
                'id': self.author.id,
                'name': self.author.full_name,
                'username': self.author.username
            } if self.author else None
        }