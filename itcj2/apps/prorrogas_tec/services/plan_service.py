"""Plan de pagos de una solicitud aceptada: confirmarlo y replantear solo lo que falta (spec §16.3)."""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from decimal import Decimal

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
from itcj2.apps.prorrogas_tec.services import account, notify
from itcj2.apps.prorrogas_tec.services.document_service import DocumentService
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.events import log_event
from itcj2.apps.prorrogas_tec.services.formatting import (
    MAX_PAGOS, fecha_larga, parse_monto, pesos, split_amount,
)
from itcj2.core.models.academic_period import AcademicPeriod
from itcj2.core.utils.timezone import db_now

logger = logging.getLogger(__name__)


def _plazos_invalidos() -> ServiceError:
    return ServiceError("plazos_invalidos", f"El plan debe tener de 1 a {MAX_PAGOS} parcialidades.")


class PlanService:

    @staticmethod
    def reparto(total, n: int) -> list[Decimal]:
        """Montos sugeridos: `total` en `n` parcialidades de pesos enteros."""
        total = parse_monto(total)
        if not 1 <= n <= MAX_PAGOS:
            raise _plazos_invalidos()
        return split_amount(total, n)

    @staticmethod
    def confirm(db, request_id: int, actor_id: int, *, total: Decimal,
                parcialidades: list[tuple[Decimal, date]], now: date | datetime | None = None) -> ProrrogaRequest:
        """Confirma el plan o lo replantea: conserva las pagadas y sustituye lo demás; genera la carta y avisa."""
        now = now or db_now()
        today = now.date() if isinstance(now, datetime) else now
        ts = now if isinstance(now, datetime) else datetime.combine(now, time())
        req = (db.query(ProrrogaRequest).filter_by(id=request_id)
               .populate_existing().with_for_update().first())
        if req is None:
            raise ServiceError("no_encontrada", "No se encontró la solicitud.", status=404)
        try:  # cualquier error (validación o pdf_no_disponible) suelta el candado y no deja nada a medias
            if req.status != "aceptada":
                raise ServiceError("no_aceptada", "Solo una solicitud aceptada lleva plan de pagos.", status=409)
            if req.period_id is None:
                raise ServiceError("sin_semestre", "Esta prórroga histórica no tiene semestre en el sistema.", status=409)
            cuenta = account.load(db, req, today)
            if cuenta.situacion == "liquidada":
                raise ServiceError("ya_liquidada", "La prórroga ya está liquidada.", status=409)
            total = parse_monto(total)
            nuevas = [(parse_monto(m), f) for m, f in parcialidades]
            if total < cuenta.pagado:
                raise ServiceError("total_menor_que_pagado",
                                   f"El total no puede ser menor a lo ya pagado ({pesos(cuenta.pagado)}).")
            conservadas = [p for p in cuenta.parcialidades if p.estado == "pagada"]
            if not nuevas or len(conservadas) + len(nuevas) > MAX_PAGOS:
                raise _plazos_invalidos()
            if sum(p.amount for p in conservadas) + sum(m for m, _ in nuevas) != total:
                raise ServiceError("suma_no_cuadra", "Las parcialidades deben sumar el total.")
            fechas = [f for _, f in nuevas]
            desde = conservadas[-1].due_date if conservadas else None
            fin = db.get(AcademicPeriod, req.period_id).end_date
            if (any(a >= b for a, b in zip(fechas, fechas[1:])) or (desde and fechas[0] <= desde)
                    or fechas[0] < today or fechas[-1] > fin):
                raise ServiceError("fechas_invalidas",
                                   f"Las fechas deben ir en orden, desde hoy y hasta el {fecha_larga(fin)}, "
                                   "y después de la última parcialidad pagada.")

            numeros = {p.number for p in conservadas}
            for inst in db.query(ProrrogaInstallment).filter_by(request_id=req.id, superseded_at=None):
                if inst.number not in numeros:
                    inst.superseded_at = ts
            db.flush()  # libera los números en el índice único parcial antes de insertar las nuevas
            base = conservadas[-1].number if conservadas else 0
            for i, (monto, fecha) in enumerate(nuevas, start=1):
                db.add(ProrrogaInstallment(request_id=req.id, number=base + i, amount=monto, due_date=fecha))
            req.total_amount = total
            req.plan_confirmed_at = ts
            req.plan_confirmed_by_id = actor_id
            req.updated_at = ts

            plan = [(p.number, p.amount, p.due_date) for p in conservadas] + [
                (base + i, m, f) for i, (m, f) in enumerate(nuevas, start=1)]
            extra = {"monto_total": pesos(total)}
            for i, (_, monto, fecha) in enumerate(plan, start=1):
                extra[f"pago{i}_monto"] = pesos(monto)
                extra[f"pago{i}_fecha"] = fecha_larga(fecha)
            tipo = f"carta_compromiso_{len(plan)}"
            DocumentService.generate(db, req, tipo, actor_id=actor_id, today=today, extra=extra)
            for d in DocumentService.current(db, req):  # generate solo sustituye las del mismo N
                if d.doc_type.startswith("carta_compromiso_") and d.doc_type != tipo:
                    d.superseded_at = ts
            log_event(db, event_type="plan_confirmado", request_id=req.id, actor_id=actor_id, payload={
                "total": account.money(total), "conservadas": sorted(numeros),
                "parcialidades": [{"numero": n, "monto": account.money(m), "fecha": f.isoformat()}
                                  for n, m, f in plan]})
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(req)
        notify.notify_student(db, req, kind="carta_lista", link="/prorrogas/estudiante")
        try:  # el aviso en la plataforma sale con este commit; si falla, el plan ya está firme
            db.commit()
        except Exception:
            logger.exception("No se pudo guardar el aviso de la solicitud %s", req.id)
            db.rollback()
        return req
