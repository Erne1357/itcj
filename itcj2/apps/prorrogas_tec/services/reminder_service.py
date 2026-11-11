"""Recordatorios automáticos de pago: 5, 1 y 0 días antes de cada vencimiento, una vez por umbral."""
import logging
from datetime import date, timedelta

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
from itcj2.apps.prorrogas_tec.services import account, notify
from itcj2.apps.prorrogas_tec.services.formatting import fecha_larga, pesos

logger = logging.getLogger(__name__)

UMBRALES = (5, 1, 0)


class ReminderService:
    @staticmethod
    def run(db, today: date) -> dict:
        """Manda los recordatorios que tocan hoy. Un fallo no detiene a los demás ni deshace los enviados."""
        fechas = {today + timedelta(days=d): d for d in UMBRALES}
        filas = (db.query(ProrrogaInstallment, ProrrogaRequest)
                 .join(ProrrogaRequest, ProrrogaRequest.id == ProrrogaInstallment.request_id)
                 .filter(ProrrogaInstallment.superseded_at.is_(None),
                         ProrrogaInstallment.due_date.in_(list(fechas)),
                         ProrrogaRequest.status == "aceptada",
                         ProrrogaRequest.period_id.isnot(None),
                         (ProrrogaRequest.student_id.isnot(None)) | (ProrrogaRequest.email.isnot(None)))
                 .order_by(ProrrogaInstallment.id).all())
        ids = [(i.id, r.id) for i, r in filas]
        enviados = fallidos = 0
        for inst_id, req_id in ids:
            try:
                inst, req = db.get(ProrrogaInstallment, inst_id), db.get(ProrrogaRequest, req_id)
                dias = fechas[inst.due_date]
                if inst.last_reminder_days is not None and inst.last_reminder_days <= dias:
                    continue
                c = account.load(db, req, today)
                p = next(x for x in c.parcialidades if x.number == inst.number)
                if p.estado == "pagada":
                    continue
                fecha, monto = fecha_larga(p.due_date), pesos(p.amount - p.cubierto)
                salio = notify.notify_student(
                    db, req, kind="recordatorio", link="/prorrogas/estudiante",
                    titulo=notify.titulo_recordatorio(p.due_date, False),
                    body=f"Saldo {pesos(c.saldo)}. Próximo pago: {fecha} por {monto}.",
                    context={"saldo": pesos(c.saldo), "proxima_fecha": fecha, "proxima_monto": monto,
                             "vencido": False})
                if salio:
                    inst.last_reminder_days = dias
                    enviados += 1
                else:
                    fallidos += 1
                db.commit()  # por parcialidad: un fallo posterior no pierde las marcas anteriores
            except Exception:
                logger.exception("Recordatorio de la parcialidad %s", inst_id)
                db.rollback()
                fallidos += 1
        return {"enviados": enviados, "fallidos": fallidos}
