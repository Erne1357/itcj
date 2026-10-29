"""Pestaña Estudiantes de la secretaria: lista por semestre con su cuenta y expediente de una solicitud."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from itcj2.apps.prorrogas_tec.documents.catalog import DOC_TYPES
from itcj2.apps.prorrogas_tec.models.event import ProrrogaEvent
from itcj2.apps.prorrogas_tec.models.plan import ProrrogaPayment
from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
from itcj2.apps.prorrogas_tec.services import account
from itcj2.apps.prorrogas_tec.services.document_service import DocumentService
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.identity import folio
from itcj2.apps.prorrogas_tec.services.periods import period_for, period_label
from itcj2.apps.prorrogas_tec.services.request_service import RequestService
from itcj2.core.models.academic_period import AcademicPeriod
from itcj2.core.utils.timezone import db_now

FILTROS = ("todos", "con_adeudo", "al_corriente", "sin_plan", "liquidada")
_SITUACION = {"con_adeudo": "atrasada", "al_corriente": "al_corriente", "sin_plan": "sin_plan",
              "liquidada": "liquidada"}
_ENTRE_RECORDATORIOS = timedelta(hours=24)


def _puede_recordar(req, c, ahora: datetime) -> bool:
    return (c.total is not None and c.saldo > 0
            and (req.last_reminded_at is None or ahora - req.last_reminded_at > _ENTRE_RECORDATORIOS))


def _avisar_desbloqueo(req, c) -> bool:
    return req.block_exported_at is not None and c.situacion == "liquidada" and req.unblock_notified_at is None


class StudentsService:
    @staticmethod
    def periodos(db, today: date) -> dict:
        ps = (db.query(AcademicPeriod)
              .filter(AcademicPeriod.id.in_(
                  db.query(ProrrogaRequest.period_id).filter(ProrrogaRequest.status == "aceptada")))
              .order_by(AcademicPeriod.start_date.desc()).all())
        items = [{"id": p.id, "label": period_label(p)} for p in ps]
        hoy = period_for(db, today)
        ids = [i["id"] for i in items]
        actual = hoy.id if hoy and hoy.id in ids else (ids[0] if ids else None)
        return {"items": items, "actual": actual}

    @staticmethod
    def listar(db, period_id: int, *, q: str | None = None, filtro: str = "todos", page: int = 1,
               per_page: int = 25, today: date) -> dict:
        if filtro not in FILTROS:
            raise ServiceError("filtro_invalido", "Filtro no válido.", 400)
        page = max(page, 1)
        per_page = min(max(per_page, 1), 100)
        qry = db.query(ProrrogaRequest).filter(ProrrogaRequest.period_id == period_id,
                                               ProrrogaRequest.status == "aceptada")
        if q and q.strip():
            like = f"%{q.strip()}%"
            qry = qry.filter(ProrrogaRequest.control_number.ilike(like) | ProrrogaRequest.student_name.ilike(like))
        reqs = qry.all()
        # shortcut: situación calculada en Python por semestre; pasar a SQL si un semestre supera ~2000 solicitudes
        cuentas = account.load_many(db, reqs, today)
        conteos = {"todos": len(reqs)} | {k: sum(1 for c in cuentas.values() if c.situacion == s)
                                          for k, s in _SITUACION.items()}
        if filtro != "todos":
            reqs = [r for r in reqs if cuentas[r.id].situacion == _SITUACION[filtro]]
        reqs.sort(key=lambda r: ((r.student_name or "").lower(), r.id))
        pagina = reqs[(page - 1) * per_page: page * per_page]
        ahora = db_now()
        items = []
        for r in pagina:
            c = cuentas[r.id]
            items.append({
                "id": r.id, "folio": folio(r.id), "control": r.control_number, "nombre": r.student_name,
                "situacion": c.situacion, "faltantes": c.faltantes,
                "vencida_desde": c.vencida_desde.isoformat() if c.vencida_desde else None,
                "pagos": [p.estado for p in c.parcialidades],
                "pagados": sum(1 for p in c.parcialidades if p.estado == "pagada"),
                "puede_recordar": _puede_recordar(r, c, ahora),
                "avisar_desbloqueo": _avisar_desbloqueo(r, c)})
        return {"items": items, "total": len(reqs), "page": page, "per_page": per_page, "conteos": conteos}

    @staticmethod
    def expediente(db, request_id: int, today: date) -> dict:
        req = db.get(ProrrogaRequest, request_id)
        if req is None or req.status != "aceptada":
            raise ServiceError("no_encontrada", "No se encontró la solicitud.", 404)
        c = account.load(db, req, today)
        period = db.get(AcademicPeriod, req.period_id)
        conservadas = [p for p in c.parcialidades if p.estado == "pagada"]
        suma = sum((p.amount for p in conservadas), Decimal("0"))
        carta = next((d for d in DocumentService.current(db, req) if d.doc_type.startswith("carta_compromiso")), None)
        recibos = (db.query(ProrrogaPayment).filter(ProrrogaPayment.request_id == req.id)
                   .order_by(ProrrogaPayment.recorded_at.desc(), ProrrogaPayment.id.desc()).all())
        eventos = (db.query(ProrrogaEvent).filter(ProrrogaEvent.request_id == req.id)
                   .order_by(ProrrogaEvent.created_at.desc(), ProrrogaEvent.id.desc()).all())
        return {
            "solicitud": RequestService.request_out(db, req),
            "estudiante": {"nombre": req.student_name, "control": req.control_number, "correo": req.email,
                           "carrera": req.program_name},
            "cuenta": account.cuenta_json(c),
            "recibos": [{"id": p.id, "folio": p.folio, "fecha": p.paid_on.isoformat(), "monto": account.money(p.amount),
                         "registrado": p.recorded_at.isoformat(),
                         "anulado": p.voided_at.isoformat() if p.voided_at else None,
                         "motivo_anulacion": p.void_reason} for p in recibos],
            "carta": ({"doc_id": carta.id, "tipo": carta.doc_type, "version": carta.version,
                       "firmada": carta.signed_at is not None} if carta else None),
            "plan": {
                "confirmado": req.plan_confirmed_at.isoformat() if req.plan_confirmed_at else None,
                "puede_replantear": c.situacion != "liquidada" and today <= period.end_date,
                "conservadas": [p.number for p in conservadas],
                "suma_conservadas": account.money(suma),
                "max_nuevas": 3 - len(conservadas),
                "fecha_limite": period.end_date.isoformat()},
            "bloqueo": {"exportada": req.block_exported_at.isoformat() if req.block_exported_at else None,
                        "avisar_desbloqueo": _avisar_desbloqueo(req, c),
                        "avisado": req.unblock_notified_at.isoformat() if req.unblock_notified_at else None},
            "recordatorio": {"ultimo": req.last_reminded_at.isoformat() if req.last_reminded_at else None,
                             "puede": _puede_recordar(req, c, db_now())},
            "historial": [{"tipo": e.event_type, "fecha": e.created_at.isoformat(), "datos": e.payload}
                          for e in eventos],
        }
