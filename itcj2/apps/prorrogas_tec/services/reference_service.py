"""Referencia bancaria del alumno: un PDF por solicitud, que la secretaria consulta para armar el plan."""
from __future__ import annotations

from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
from itcj2.apps.prorrogas_tec.services import storage
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.events import log_event
from itcj2.core.utils.timezone import db_now


MAX_BYTES = 5 * 1024 * 1024


def validar_pdf(data: bytes, invalido: str, muy_grande: str, nombre: str) -> None:
    if not data.startswith(b"%PDF-"):
        raise ServiceError(invalido, f"{nombre} debe ser un PDF.")
    if len(data) > MAX_BYTES:
        raise ServiceError(muy_grande, f"{nombre} no puede pasar de 5 MB.")


class ReferenceService:
    MAX_BYTES = MAX_BYTES

    @staticmethod
    def save(db, req: ProrrogaRequest, data: bytes, actor_id: int, *, now=None) -> ProrrogaRequest:
        validar_pdf(data, "referencia_invalida", "referencia_muy_grande", "La referencia")
        if req.status not in ("pendiente", "aceptada"):
            raise ServiceError("referencia_no_aplica", "Esta solicitud ya no admite referencia.", status=409)
        if req.total_amount is not None:
            raise ServiceError("referencia_fija",
                               "Tu plan ya está armado: la referencia ya no se puede cambiar.", status=409)
        # la ruta sale solo de ids (una por solicitud, se sobrescribe): nunca del nombre que mandó el alumno
        rel = f"referencias/{req.period_id}/{req.id}.pdf"
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
        try:
            return storage.abs_path(req.reference_path).read_bytes()
        except FileNotFoundError:
            raise ServiceError("no_encontrada", "No se encontró la referencia.", status=404) from None
