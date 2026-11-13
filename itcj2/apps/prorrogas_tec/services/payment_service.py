"""Recibos de Caja de una solicitud con plan: registrar y anular (nunca se borran)."""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaPayment
from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
from itcj2.apps.prorrogas_tec.services import account, notify
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.events import log_event
from itcj2.apps.prorrogas_tec.services.formatting import fecha_larga, parse_monto, pesos
from itcj2.core.utils.timezone import db_now

logger = logging.getLogger(__name__)

_UQ_FOLIO = "uq_prorrogas_payments_folio_vigente"


def _folio_duplicado() -> ServiceError:
    return ServiceError("folio_duplicado", "Ese folio ya está registrado.", status=409)


def _tiempos(now):
    now = now or db_now()
    return (now.date(), now) if isinstance(now, datetime) else (now, datetime.combine(now, time()))


def _exigir_semestre(req) -> None:
    """Las del Excel sin semestre de core son de solo lectura (§17.3)."""
    if req.period_id is None:
        raise ServiceError("sin_semestre", "Esta prórroga es del histórico sin semestre: solo cuenta para Estadísticas.",
                           status=409)


class PaymentService:

    @staticmethod
    def record(db, request_id: int, actor_id: int, *, folio: str, paid_on: date, amount: Decimal,
               now: date | datetime | None = None) -> ProrrogaPayment:
        today, ts = _tiempos(now)
        # El candado va antes de leer el saldo: dos recibos a la vez se serializan (no hay sobrepago por carrera).
        req = (db.query(ProrrogaRequest).filter_by(id=request_id)
               .populate_existing().with_for_update().first())
        if req is None:
            raise ServiceError("no_encontrada", "No se encontró la solicitud.", status=404)
        try:
            if req.status != "aceptada":
                raise ServiceError("no_aceptada", "Solo una solicitud aceptada lleva recibos.", status=409)
            _exigir_semestre(req)
            if req.total_amount is None:
                raise ServiceError("sin_plan", "Primero hay que confirmar el plan de pagos.", status=409)
            folio = (folio or "").strip().upper()
            if not 1 <= len(folio) <= 40:
                raise ServiceError("folio_invalido", "El folio de Caja debe tener de 1 a 40 caracteres.")
            amount = parse_monto(amount)
            if paid_on > today or paid_on < req.created_at.date():
                raise ServiceError("fecha_invalida",
                                   "La fecha de pago no puede ser futura ni anterior a la solicitud.")
            saldo = account.load(db, req, today).saldo
            if amount > saldo:
                raise ServiceError("sobrepago", f"El monto excede el saldo pendiente ({pesos(saldo)}).")
            if (db.query(ProrrogaPayment.id)
                    .filter(func.upper(ProrrogaPayment.folio) == folio, ProrrogaPayment.voided_at.is_(None)).first()):
                raise _folio_duplicado()
            pago = ProrrogaPayment(request_id=req.id, folio=folio, paid_on=paid_on, amount=amount,
                                   recorded_by_id=actor_id)
            db.add(pago)
            db.flush()
            req.updated_at = ts
            log_event(db, event_type="recibo_registrado", request_id=req.id, actor_id=actor_id,
                      payload={"folio": folio, "monto": account.money(amount), "fecha": paid_on.isoformat()})
            db.commit()
        except IntegrityError as e:  # carrera de folio: gana el índice único parcial
            db.rollback()
            if getattr(getattr(e.orig, "diag", None), "constraint_name", None) != _UQ_FOLIO:
                raise
            raise _folio_duplicado()
        except Exception:
            db.rollback()
            raise
        PaymentService._avisar(db, request_id, req, pago, today)
        return pago

    @staticmethod
    def _avisar(db, request_id: int, req, pago, today: date) -> None:
        """Aviso y correo del recibo; el que liquida manda el de prórroga pagada. Va tras el commit: sin candados
        durante Graph, y nunca lanza: el recibo ya está firme y Caja no debe ver un error."""
        try:
            c = account.load(db, req, today)
            datos = {"monto": pesos(pago.amount), "fecha": fecha_larga(pago.paid_on), "folio_caja": pago.folio,
                     "total": pesos(c.total), "saldo": pesos(c.saldo)}
            if c.situacion == "liquidada":
                kind, body = "liquidada", f"Pagaste {datos['total']} en total. Sube el recibo de tu último pago en Mi prórroga."
            else:
                datos.update(proxima_fecha=fecha_larga(c.proxima.due_date),
                             proxima_monto=pesos(c.proxima.amount - c.proxima.cubierto))
                kind, body = "pago_registrado", (f"{datos['monto']} con folio {pago.folio}. Saldo {datos['saldo']}. "
                                                 "Sube tu recibo en Mi prórroga.")
            notify.notify_student(db, req, kind=kind, link="/prorrogas/estudiante", body=body, context=datos)
            db.commit()  # el aviso en la plataforma sale con este commit
        except Exception:
            logger.exception("No se pudo guardar el aviso del recibo de la solicitud %s", request_id)
            db.rollback()

    @staticmethod
    def settle_next(db, request_id: int, actor_id: int, *, numero: int, monto: str, folio: str,
                    paid_on: date, now: date | datetime | None = None) -> ProrrogaPayment:
        """Caja cobra completo el pago más próximo (lo que falte si ya venía cubierto en parte)."""
        today, _ = _tiempos(now)
        # Mismo candado que `record`; la transacción lo conserva hasta el commit de `record`.
        req = (db.query(ProrrogaRequest).filter_by(id=request_id)
               .populate_existing().with_for_update().first())
        if req is None:
            raise ServiceError("no_encontrada", "No se encontró la solicitud.", status=404)
        try:
            if req.status != "aceptada":
                raise ServiceError("no_aceptada", "Solo una solicitud aceptada lleva recibos.", status=409)
            _exigir_semestre(req)
            c = account.load(db, req, today)
            if c.total is None:
                raise ServiceError("sin_plan", "Primero hay que confirmar el plan de pagos.", status=409)
            if c.proxima is None or c.proxima.number != numero:
                raise ServiceError("pago_cambio", "Ese pago ya no es el siguiente por cobrar. Revisa el detalle.",
                                   status=409)
            a_cobrar = c.proxima.amount - c.proxima.cubierto
            if parse_monto(monto) != a_cobrar:  # el plan cambió mientras Caja tenía el formulario abierto
                raise ServiceError("pago_cambio", "Ese pago ya no es el siguiente por cobrar. Revisa el detalle.",
                                   status=409)
            if (db.query(ProrrogaPayment.id).filter(ProrrogaPayment.request_id == req.id,
                                                    ProrrogaPayment.voided_at.is_(None),
                                                    ProrrogaPayment.paid_on > paid_on).first()):
                raise ServiceError("fecha_invalida", "La fecha no puede ser anterior a la del último pago registrado.")
            return PaymentService.record(db, request_id, actor_id, folio=folio, paid_on=paid_on,
                                         amount=a_cobrar, now=now)
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def void(db, payment_id: int, actor_id: int, *, motivo: str, request_id: int | None = None,
             now: date | datetime | None = None) -> ProrrogaPayment:
        """Anula un recibo. `request_id` (opcional) exige que sea de esa solicitud."""
        _, ts = _tiempos(now)
        pago = (db.query(ProrrogaPayment).filter_by(id=payment_id)
                .populate_existing().with_for_update().first())
        if pago is None or (request_id is not None and pago.request_id != request_id):
            db.rollback()
            raise ServiceError("recibo_no_encontrado", "No se encontró el recibo.", status=404)
        try:
            req = (db.query(ProrrogaRequest).filter_by(id=pago.request_id)
                   .populate_existing().with_for_update().first())
            db.refresh(pago)  # releer tras el candado de la solicitud
            _exigir_semestre(req)
            if pago.voided_at is not None:
                raise ServiceError("ya_anulado", "El recibo ya estaba anulado.", status=409)
            ultimo = (db.query(ProrrogaPayment.id).filter(ProrrogaPayment.request_id == req.id,
                                                          ProrrogaPayment.voided_at.is_(None))
                      .order_by(ProrrogaPayment.paid_on.desc(), ProrrogaPayment.id.desc()).first())
            if ultimo.id != pago.id:
                raise ServiceError("no_es_el_ultimo", "Solo se puede anular el último recibo vigente.", status=409)
            motivo = (motivo or "").strip()
            if not 5 <= len(motivo) <= 500:
                raise ServiceError("motivo_requerido", "El motivo debe tener de 5 a 500 caracteres.")
            pago.voided_at = ts
            pago.voided_by_id = actor_id
            pago.void_reason = motivo
            req.updated_at = ts
            log_event(db, event_type="recibo_anulado", request_id=req.id, actor_id=actor_id,
                      payload={"folio": pago.folio, "monto": account.money(pago.amount), "motivo": motivo})
            db.commit()
        except Exception:
            db.rollback()
            raise
        return pago
