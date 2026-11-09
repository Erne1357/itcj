"""Referencia bancaria del alumno: un PDF por solicitud, que la secretaria consulta para armar el plan."""
from __future__ import annotations

import hashlib

from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
from itcj2.apps.prorrogas_tec.services import storage
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.events import log_event
from itcj2.core.utils.timezone import db_now


class ReferenceService:
    MAX_BYTES = 5 * 1024 * 1024

    @staticmethod
    def save(db, req: ProrrogaRequest, data: bytes, actor_id: int, *, now=None) -> ProrrogaRequest:
        if not data.startswith(b"%PDF-"):
            raise ServiceError("referencia_invalida", "La referencia debe ser un PDF.")
        if len(data) > ReferenceService.MAX_BYTES:
            raise ServiceError("referencia_muy_grande", "La referencia no puede pasar de 5 MB.")
        if req.status not in ("pendiente", "aceptada"):
            raise ServiceError("referencia_no_aplica", "Esta solicitud ya no admite referencia.", status=409)
        if req.plan_confirmed_at is not None:
            raise ServiceError("referencia_fija",
                               "Tu plan ya está armado: la referencia ya no se puede cambiar.", status=409)
        # la ruta sale solo de ids y del hash: nunca del nombre que mandó el alumno
        rel = f"referencias/{req.period_id}/{req.id}-{hashlib.sha256(data).hexdigest()[:12]}.pdf"
        storage.write_atomic(rel, data)
        req.reference_path = rel
        req.reference_uploaded_at = now or db_now()
        log_event(db, event_type="referencia_subida", request_id=req.id, actor_id=actor_id)
        db.flush()
        return req

    @staticmethod
    def read(req: ProrrogaRequest) -> bytes:
        if not req.reference_path:
            raise ServiceError("sin_referencia", "Aún no subes tu referencia.", status=404)
        return storage.abs_path(req.reference_path).read_bytes()
