"""Bitácora de solicitudes. Solo hace `db.add`; quien llama hace commit."""
from __future__ import annotations

from itcj2.apps.prorrogas_tec.models.event import ProrrogaEvent

EVENT_TYPES = frozenset({
    "solicitud_creada", "solicitud_cancelada", "solicitud_aceptada",
    "solicitud_rechazada", "documento_generado", "invitacion_enviada",
    "plan_confirmado", "plan_modificado", "recibo_registrado", "recibo_anulado", "documento_firmado",
    "recordatorio_enviado", "lista_bloqueo_exportada", "desbloqueo_avisado",
    "correo_no_enviado", "recordatorio_pendiente",
    "referencia_subida", "cerrada_sin_plan", "recibo_subido", "recibo_inconsistente",
})


def log_event(db, *, event_type: str, request_id: int | None = None,
              actor_id: int | None = None, payload: dict | None = None) -> ProrrogaEvent:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Tipo de evento desconocido: {event_type}")
    ev = ProrrogaEvent(request_id=request_id, actor_id=actor_id,
                       event_type=event_type, payload=payload or {})
    db.add(ev)
    return ev


def last_mail_failed(db, request_id: int) -> bool:
    """El evento más nuevo de la solicitud es `correo_no_enviado`."""
    ultimo = (db.query(ProrrogaEvent.event_type)
              .filter(ProrrogaEvent.request_id == request_id,
                      ProrrogaEvent.event_type.notin_(("recibo_registrado", "recibo_anulado", "recibo_subido")))
              .order_by(ProrrogaEvent.created_at.desc(), ProrrogaEvent.id.desc()).first())
    return ultimo is not None and ultimo[0] == "correo_no_enviado"
