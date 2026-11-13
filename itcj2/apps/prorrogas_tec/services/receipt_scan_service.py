"""Recibo escaneado que sube el alumno por cada parcialidad ya cubierta (un PDF por parcialidad)."""
from __future__ import annotations

import hashlib
from datetime import datetime

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
from itcj2.apps.prorrogas_tec.services import account, storage
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.events import log_event
from itcj2.apps.prorrogas_tec.services.reference_service import validar_pdf
from itcj2.core.utils.timezone import db_now


def _vigente(db, request_id: int, numero: int):
    return db.query(ProrrogaInstallment).filter(
        ProrrogaInstallment.request_id == request_id, ProrrogaInstallment.number == numero,
        ProrrogaInstallment.superseded_at.is_(None)).first()


class ReceiptScanService:
    @staticmethod
    def save(db, req: ProrrogaRequest, numero: int, data: bytes, actor_id: int, *,
             now: datetime | None = None) -> ProrrogaInstallment:
        validar_pdf(data, "recibo_invalido", "recibo_muy_grande", "El recibo")
        now = now or db_now()
        cuenta = account.load(db, req, now.date())
        parte = next((p for p in cuenta.parcialidades if p.number == numero), None)
        if req.period_id is None or parte is None or parte.estado != "pagada":
            raise ServiceError("recibo_no_aplica", "Ese pago aún no está cubierto: no lleva recibo.", status=409)
        inst = _vigente(db, req.id, numero)
        # el hash en el nombre: un reemplazo no pisa el archivo que Caja pudo haber abierto
        rel = f"recibos/{req.period_id}/{req.id}-{numero}-{hashlib.sha256(data).hexdigest()[:12]}.pdf"
        storage.write_atomic(rel, data)
        inst.receipt_path = rel
        inst.receipt_uploaded_at = now
        log_event(db, event_type="recibo_subido", request_id=req.id, actor_id=actor_id,
                  payload={"numero": numero})
        db.flush()
        return inst

    @staticmethod
    def read(db, req: ProrrogaRequest, numero: int) -> bytes:
        inst = _vigente(db, req.id, numero)
        if inst is None or not inst.receipt_path:
            raise ServiceError("sin_recibo", "Aún no hay recibo escaneado de ese pago.", status=404)
        try:
            return storage.abs_path(inst.receipt_path).read_bytes()
        except FileNotFoundError:
            raise ServiceError("sin_recibo", "No se encontró el recibo.", status=404) from None

    @staticmethod
    def subidos(db, request_id: int) -> dict[int, str]:
        rows = db.query(ProrrogaInstallment.number, ProrrogaInstallment.receipt_uploaded_at).filter(
            ProrrogaInstallment.request_id == request_id, ProrrogaInstallment.superseded_at.is_(None),
            ProrrogaInstallment.receipt_uploaded_at.isnot(None))
        return {n: t.isoformat() for n, t in rows}
