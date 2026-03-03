"""
Modelo para el historial de verificaciones físicas de equipos del inventario.
Cada registro indica que alguien verificó presencialmente que un equipo existe,
está en el lugar correcto y con los datos correctos.
"""
from itcj.core.extensions import db
from datetime import datetime


class InventoryVerification(db.Model):
    """
    Registro de verificaciones físicas de equipos del inventario.
    Proporciona trazabilidad de quién verificó qué, cuándo y qué encontró/cambió.
    """
    __tablename__ = "helpdesk_inventory_verifications"

    id = db.Column(db.Integer, primary_key=True)

    # Equipo verificado
    inventory_item_id = db.Column(
        db.Integer,
        db.ForeignKey("helpdesk_inventory_items.id"),
        nullable=False,
        index=True
    )

    # Quién verificó
    verified_by_id = db.Column(
        db.BigInteger,
        db.ForeignKey("core_users.id"),
        nullable=False,
        index=True
    )

    # Cuándo se verificó
    verified_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True
    )

    # Ubicación confirmada en el momento de la verificación
    location_confirmed = db.Column(db.String(200), nullable=True)
    # Ej.: "Aula 201", "Lab 3 - Estación 5"

    # Estado físico encontrado durante la verificación
    status_found = db.Column(db.String(30), nullable=True)
    # Uno de: ACTIVE, MAINTENANCE, DAMAGED, LOST, RETIRED

    # Observaciones libres del verificador
    observations = db.Column(db.Text, nullable=True)

    # Cambios aplicados al equipo durante la verificación (JSON con los campos y valores)
    changes_applied = db.Column(db.JSON, nullable=True)
    # Ejemplo:
    # {
    #   "location_detail": {"old": "Aula 201", "new": "Aula 202"},
    #   "status": {"old": "ACTIVE", "new": "MAINTENANCE"}
    # }
    # None / {} si no se realizó ningún cambio

    # Relaciones
    inventory_item = db.relationship(
        "InventoryItem",
        back_populates="verifications"
    )

    verified_by = db.relationship(
        "User",
        foreign_keys=[verified_by_id],
        backref="inventory_verifications"
    )

    # Índices compuestos
    __table_args__ = (
        db.Index("ix_inv_verif_item_at", "inventory_item_id", "verified_at"),
        db.Index("ix_inv_verif_user_at", "verified_by_id", "verified_at"),
    )

    def __repr__(self):
        return (
            f"<InventoryVerification item={self.inventory_item_id} "
            f"by={self.verified_by_id} at={self.verified_at}>"
        )

    def to_dict(self, include_relations=False):
        """Serialización para API"""
        data = {
            'id': self.id,
            'inventory_item_id': self.inventory_item_id,
            'verified_by_id': self.verified_by_id,
            'verified_at': self.verified_at.isoformat() if self.verified_at else None,
            'location_confirmed': self.location_confirmed,
            'status_found': self.status_found,
            'observations': self.observations,
            'changes_applied': self.changes_applied,
        }

        if include_relations:
            data['verified_by'] = {
                'id': self.verified_by.id,
                'full_name': self.verified_by.full_name,
                'email': self.verified_by.email,
            } if self.verified_by else None

            if self.inventory_item:
                item = self.inventory_item
                data['inventory_item'] = {
                    'id': item.id,
                    'inventory_number': item.inventory_number,
                    'display_name': item.display_name,
                }
            else:
                data['inventory_item'] = None

        return data
