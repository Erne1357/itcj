"""
Modelo para el historial de verificaciones físicas de equipos del inventario.
Cada registro indica que alguien verificó presencialmente que un equipo existe,
está en el lugar correcto y con los datos correctos.
"""
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from itcj2.models.base import Base


class InventoryVerification(Base):
    """
    Registro de verificaciones físicas de equipos del inventario.
    Proporciona trazabilidad de quién verificó qué, cuándo y qué encontró/cambió.
    """
    __tablename__ = "helpdesk_inventory_verifications"

    id = Column(Integer, primary_key=True)

    # Equipo verificado
    inventory_item_id = Column(
        Integer,
        ForeignKey("helpdesk_inventory_items.id"),
        nullable=False,
        index=True,
    )

    # Quién verificó
    verified_by_id = Column(
        BigInteger,
        ForeignKey("core_users.id"),
        nullable=False,
        index=True,
    )

    # Cuándo se verificó
    verified_at = Column(
        DateTime,
        default=datetime.now(),
        nullable=False,
        index=True,
    )

    # Ubicación confirmada en el momento de la verificación
    # Ej.: "Aula 201", "Lab 3 - Estación 5"
    location_confirmed = Column(String(200), nullable=True)

    # Estado físico encontrado durante la verificación
    # Uno de: ACTIVE, MAINTENANCE, DAMAGED, LOST, RETIRED
    status_found = Column(String(30), nullable=True)

    # Observaciones libres del verificador
    observations = Column(Text, nullable=True)

    # Cambios aplicados al equipo durante la verificación (JSON)
    # Ejemplo: {"location_detail": {"old": "Aula 201", "new": "Aula 202"}}
    # None / {} si no se realizó ningún cambio
    changes_applied = Column(JSON, nullable=True)

    # --- Relaciones ---
    inventory_item = relationship(
        "InventoryItem",
        back_populates="verifications",
    )

    verified_by = relationship(
        "User",
        foreign_keys=[verified_by_id],
        backref="inventory_verifications",
    )

    # --- Índices compuestos ---
    __table_args__ = (
        Index("ix_inv_verif_item_at", "inventory_item_id", "verified_at"),
        Index("ix_inv_verif_user_at", "verified_by_id", "verified_at"),
    )

    def __repr__(self):
        return (
            f"<InventoryVerification item={self.inventory_item_id} "
            f"by={self.verified_by_id} at={self.verified_at}>"
        )

    def to_dict(self, include_relations: bool = False) -> dict:
        """Serialización para API."""
        data = {
            "id": self.id,
            "inventory_item_id": self.inventory_item_id,
            "verified_by_id": self.verified_by_id,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "location_confirmed": self.location_confirmed,
            "status_found": self.status_found,
            "observations": self.observations,
            "changes_applied": self.changes_applied,
        }

        if include_relations:
            data["verified_by"] = {
                "id": self.verified_by.id,
                "full_name": self.verified_by.full_name,
                "email": self.verified_by.email,
            } if self.verified_by else None

            if self.inventory_item:
                item = self.inventory_item
                data["inventory_item"] = {
                    "id": item.id,
                    "inventory_number": item.inventory_number,
                    "display_name": item.display_name,
                }
            else:
                data["inventory_item"] = None

        return data
