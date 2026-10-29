"""Bitácora de solicitudes. Solo hace `db.add`; quien llama hace commit."""
from __future__ import annotations

from itcj2.apps.prorrogas_tec.models.event import ProrrogaEvent

EVENT_TYPES = frozenset({
    "solicitud_creada", "solicitud_cancelada", "solicitud_aceptada",
    "solicitud_rechazada", "documento_generado", "invitacion_enviada",
})


def log_event(db, *, event_type: str, request_id: int | None = None,
              actor_id: int | None = None, payload: dict | None = None) -> ProrrogaEvent:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Tipo de evento desconocido: {event_type}")
    ev = ProrrogaEvent(request_id=request_id, actor_id=actor_id,
                       event_type=event_type, payload=payload or {})
    db.add(ev)
    return ev
