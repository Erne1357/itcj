"""Pestaña Estudiantes de la secretaria: lista por semestre con su cuenta y expediente de una solicitud."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font

from itcj2.apps.prorrogas_tec.documents.catalog import DOC_TYPES
from itcj2.apps.prorrogas_tec.models.document import ProrrogaDocument
from itcj2.apps.prorrogas_tec.models.event import ProrrogaEvent
from itcj2.apps.prorrogas_tec.models.period import ProrrogaPeriod
from itcj2.apps.prorrogas_tec.models.plan import ProrrogaPayment
from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
from itcj2.apps.prorrogas_tec.services import account, notify
from itcj2.apps.prorrogas_tec.services.document_service import DocumentService
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.events import last_mail_failed, log_event
from itcj2.apps.prorrogas_tec.services.formatting import fecha_larga, pesos
from itcj2.apps.prorrogas_tec.services.identity import folio
from itcj2.apps.prorrogas_tec.services.periods import period_for, period_label
from itcj2.apps.prorrogas_tec.services.request_service import RequestService
from itcj2.core.models.academic_period import AcademicPeriod
from itcj2.core.utils.timezone import db_now

FILTROS = ("todos", "con_adeudo", "al_corriente", "sin_plan", "liquidada", "por_firmar",
           "pendiente_cierre")
_PENDIENTES = {"firma": "firma_pendiente", "referencia": "referencia_pendiente"}
_SITUACION = {"con_adeudo": "atrasada", "al_corriente": "al_corriente", "sin_plan": "sin_plan",
              "liquidada": "liquidada"}
_ENTRE_RECORDATORIOS = timedelta(hours=24)
logger = logging.getLogger(__name__)
_COLUMNAS = [("No. de control", 16), ("Nombre", 36), ("Carrera", 36), ("Monto debido", 16)]
_DINERO = '"$"#,##0.00'


def _tiempos(now):
    now = now or db_now()
    if isinstance(now, datetime):
        return now, now.date(), now
    return now, now, datetime.combine(now, time())


def _puede_recordar(req, c, ahora: datetime) -> bool:
    return (bool(req.student_id or req.email) and req.period_id is not None and c.total is not None and c.saldo > 0
            and (req.last_reminded_at is None or ahora - req.last_reminded_at >= _ENTRE_RECORDATORIOS))


def _avisar_desbloqueo(req, c) -> bool:
    return req.block_exported_at is not None and c.situacion == "liquidada" and req.unblock_notified_at is None


def _sin_firmar(db, ids: list[int]) -> set[int]:
    """Solicitudes con carta compromiso vigente (no reemplazada) sin firmar; mismo criterio que el expediente."""
    if not ids:
        return set()
    rows = (db.query(ProrrogaDocument.request_id)
            .filter(ProrrogaDocument.request_id.in_(ids), ProrrogaDocument.superseded_at.is_(None),
                    ProrrogaDocument.doc_type.like("carta_compromiso%"), ProrrogaDocument.signed_at.is_(None)))
    return {r[0] for r in rows}


def _datos(payload: dict) -> dict:
    """Datos del evento para el historial; un documento lleva también su nombre."""
    t = payload.get("doc_type")
    return payload | {"documento": DOC_TYPES[t].label} if t in DOC_TYPES else payload


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
        fin = db.get(AcademicPeriod, period_id).end_date
        # shortcut: situación calculada en Python por semestre; pasar a SQL si un semestre supera ~2000 solicitudes
        cuentas = account.load_many(db, reqs, today)
        conteos = {"todos": len(reqs)} | {k: sum(1 for c in cuentas.values() if c.situacion == s)
                                          for k, s in _SITUACION.items()}
        por_firmar = _sin_firmar(db, [r.id for r in reqs])
        conteos["por_firmar"] = len(por_firmar)
        por_cerrar = {r.id for r in reqs if cuentas[r.id].situacion == "sin_plan" and today > fin}
        conteos["pendiente_cierre"] = len(por_cerrar)
        if filtro == "por_firmar":
            reqs = [r for r in reqs if r.id in por_firmar]
        elif filtro == "pendiente_cierre":
            reqs = [r for r in reqs if r.id in por_cerrar]
        elif filtro != "todos":
            reqs = [r for r in reqs if cuentas[r.id].situacion == _SITUACION[filtro]]
        reqs.sort(key=lambda r: ((r.student_name or "").lower(), r.id))
        pagina = reqs[(page - 1) * per_page: page * per_page]
        ahora = db_now()
        items = []
        for r in pagina:
            c = cuentas[r.id]
            items.append({
                "id": r.id, "folio": folio(r), "control": r.control_number, "nombre": r.student_name,
                "situacion": c.situacion, "faltantes": c.faltantes,
                "vencida_desde": c.vencida_desde.isoformat() if c.vencida_desde else None,
                "pagos": [p.estado for p in c.parcialidades],
                "pagados": sum(1 for p in c.parcialidades if p.estado == "pagada"),
                "puede_recordar": _puede_recordar(r, c, ahora), "por_firmar": r.id in por_firmar,
                "pendiente_cierre": r.id in por_cerrar,
                "avisar_desbloqueo": _avisar_desbloqueo(r, c)})
        return {"items": items, "total": len(reqs), "page": page, "per_page": per_page, "conteos": conteos}

    @staticmethod
    def expediente(db, request_id: int, today: date) -> dict:
        req = db.get(ProrrogaRequest, request_id)
        if req is None or req.status != "aceptada":
            raise ServiceError("no_encontrada", "No se encontró la solicitud.", 404)
        c = account.load(db, req, today)
        period = db.get(AcademicPeriod, req.period_id) if req.period_id else None  # histórica sin semestre: solo lectura
        comun = db.query(ProrrogaPeriod).filter_by(period_id=req.period_id).first()  # fechas de Configuración
        carta = next((d for d in DocumentService.current(db, req) if d.doc_type.startswith("carta_compromiso")), None)
        recibos = (db.query(ProrrogaPayment).filter(ProrrogaPayment.request_id == req.id)
                   .order_by(ProrrogaPayment.recorded_at.desc(), ProrrogaPayment.id.desc()).all())
        cuenta = account.cuenta_json(c)
        vivos = [(p.paid_on, p.amount, p.folio) for p in sorted(recibos, key=lambda p: p.id) if p.voided_at is None]
        plan = [(p.number, p.amount, p.due_date) for p in c.parcialidades]
        for parc, r in zip(cuenta["parcialidades"], account.cobertura(plan, vivos)):  # recibo de Caja de cada pago
            parc["recibo"], parc["pagado_el"] = (r[2], r[0].isoformat()) if r else (None, None)
        return {
            "solo_lectura": req.period_id is None,  # del Excel sin semestre de core: solo cuenta para Estadísticas
            "solicitud": RequestService.request_out(db, req),
            "estudiante": {"nombre": req.student_name, "control": req.control_number, "correo": req.email,
                           "carrera": req.program_name},
            "cuenta": cuenta,
            "recibos": [{"id": p.id, "folio": p.folio, "fecha": p.paid_on.isoformat(), "monto": account.money(p.amount),
                         "registrado": p.recorded_at.isoformat(),
                         "anulado": p.voided_at.isoformat() if p.voided_at else None,
                         "motivo_anulacion": p.void_reason} for p in recibos],
            "carta": ({"doc_id": carta.id, "tipo": carta.doc_type, "version": carta.version,
                       "firmada": carta.signed_at is not None} if carta else None),
            "plan": {
                "confirmado": req.plan_confirmed_at.isoformat() if req.plan_confirmed_at else None,
                "editable": period is not None and c.pagado == 0 and c.situacion != "atrasada" and today <= period.end_date,  # rehacer solo sin pagos
                "cerrable": c.situacion == "sin_plan" and period is not None and today > period.end_date,
                "fecha_limite": period.end_date.isoformat() if period else None,
                "fechas_sugeridas": [comun.payment_1_on.isoformat(), comun.payment_2_on.isoformat()] if comun else []},
            "bloqueo": {"exportada": req.block_exported_at.isoformat() if req.block_exported_at else None,
                        "avisar_desbloqueo": _avisar_desbloqueo(req, c),
                        "avisado": req.unblock_notified_at.isoformat() if req.unblock_notified_at else None},
            "recordatorio": {"ultimo": req.last_reminded_at.isoformat() if req.last_reminded_at else None,
                             "puede": _puede_recordar(req, c, db_now())},
            "correo_enviado": not last_mail_failed(db, req.id),
            "historial": StudentsService.historial(db, req.id),
        }

    @staticmethod
    def historial(db, request_id: int) -> list[dict]:
        eventos = (db.query(ProrrogaEvent).filter(ProrrogaEvent.request_id == request_id)
                   .order_by(ProrrogaEvent.created_at.desc(), ProrrogaEvent.id.desc()).all())
        return [{"tipo": e.event_type, "fecha": e.created_at.isoformat(), "datos": _datos(e.payload)}
                for e in eventos]

    @staticmethod
    def _bloquear(db, request_id: int) -> ProrrogaRequest:
        req = (db.query(ProrrogaRequest).filter_by(id=request_id)
               .populate_existing().with_for_update().first())
        if req is None or req.status != "aceptada":
            db.rollback()
            raise ServiceError("no_encontrada", "No se encontró la solicitud.", status=404)
        return req

    @staticmethod
    def close_without_plan(db, request_id: int, actor_id: int, motivo: str, *,
                           now: date | datetime | None = None) -> ProrrogaRequest:
        """Cierra con motivo una aceptada que terminó el semestre sin plan; no se avisa al alumno."""
        _, today, _ = _tiempos(now)
        motivo = (motivo or "").strip()
        if not 10 <= len(motivo) <= 1000:
            raise ServiceError("motivo_invalido", "El motivo debe tener entre 10 y 1000 caracteres.", 400)
        req = StudentsService._bloquear(db, request_id)
        try:
            if account.load(db, req, today).total is not None:
                raise ServiceError("con_plan", "La solicitud ya tiene plan de pagos.", status=409)
            period = db.get(AcademicPeriod, req.period_id) if req.period_id else None
            if period is None or today <= period.end_date:
                raise ServiceError("semestre_en_curso", "El semestre aún no termina.", status=409)
            req.status = "cerrada_sin_plan"
            log_event(db, event_type="cerrada_sin_plan", request_id=req.id, actor_id=actor_id,
                      payload={"motivo": motivo})
            db.commit()
        except Exception:
            db.rollback()
            raise
        return req

    @staticmethod
    def remind(db, request_id: int, actor_id: int, *, now: date | datetime | None = None) -> ProrrogaRequest:
        """Recordatorio de pago por correo y aviso; como máximo uno cada 24 h por solicitud."""
        _, today, ts = _tiempos(now)
        req = StudentsService._bloquear(db, request_id)
        try:
            c = account.load(db, req, today)
            if c.total is None:
                raise ServiceError("sin_plan", "La solicitud aún no tiene plan de pagos.", status=409)
            if c.saldo <= 0:
                raise ServiceError("sin_saldo", "La solicitud no tiene saldo pendiente.", status=409)
            if not (req.student_id or req.email):  # importada del Excel sin cuenta: no llegaría a nadie
                raise ServiceError("sin_destinatario", "Esta prórroga no tiene cuenta ni correo para avisar.",
                                   status=409)
            if req.period_id is None:
                raise ServiceError("sin_semestre", "Esta prórroga histórica no tiene semestre en el sistema.",
                                   status=409)
            if req.last_reminded_at and ts - req.last_reminded_at < _ENTRE_RECORDATORIOS:
                raise ServiceError("ya_recordado", "Ya se le recordó en las últimas 24 horas.", status=409,
                                   siguiente=(req.last_reminded_at + _ENTRE_RECORDATORIOS).isoformat())
            p = c.proxima
            fecha, monto, vencido = fecha_larga(p.due_date), pesos(p.amount - p.cubierto), p.due_date < today
            previo, req.last_reminded_at = req.last_reminded_at, ts
            db.commit()  # sin candados durante Graph
        except Exception:
            db.rollback()
            raise
        db.refresh(req)
        body = (f"Saldo {pesos(c.saldo)}. Tienes un pago vencido desde el {fecha} por {monto}." if vencido
                else f"Saldo {pesos(c.saldo)}. Próximo pago: {fecha} por {monto}.")
        salio = notify.notify_student(db, req, kind="recordatorio", link="/prorrogas/estudiante", body=body,
                                      context={"saldo": pesos(c.saldo), "proxima_fecha": fecha,
                                               "proxima_monto": monto, "vencido": vencido})
        if salio:
            log_event(db, event_type="recordatorio_enviado", request_id=req.id, actor_id=actor_id,
                      payload={"saldo": account.money(c.saldo)})
        else:  # no cuenta: que se pueda reintentar sin esperar 24 h
            req.last_reminded_at = previo
        try:
            db.commit()
        except Exception:
            logger.exception("No se pudo guardar el aviso de la solicitud %s", req.id)
            db.rollback()
        if not salio:
            raise ServiceError("correo_no_salio",
                               "El recordatorio no salió: revisa la conexión del correo en /itcj/config/email.",
                               status=502)
        return req

    @staticmethod
    def remind_pending(db, request_id: int, actor_id: int, que: str, *,
                       now: date | datetime | None = None) -> ProrrogaRequest:
        """Recordatorio de un pendiente del alumno (hoy, la firma); como máximo uno cada 24 h por pendiente."""
        if que not in _PENDIENTES:
            raise ServiceError("que_invalido", "Pendiente no válido.", 400)
        kind = _PENDIENTES[que]
        _, _, ts = _tiempos(now)
        req = StudentsService._bloquear(db, request_id)
        try:
            pendiente = req.id in _sin_firmar(db, [req.id]) if que == "firma" else not req.reference_path
            if not pendiente:
                raise ServiceError("no_aplica", f"El estudiante no tiene {que} pendiente.", status=409)
            if not (req.student_id or req.email):
                raise ServiceError("sin_destinatario", "Esta prórroga no tiene cuenta ni correo para avisar.",
                                   status=409)
            previos = (db.query(ProrrogaEvent).filter_by(request_id=req.id, event_type="recordatorio_pendiente")
                       .order_by(ProrrogaEvent.created_at.desc(), ProrrogaEvent.id.desc()).all())
            ultimo = next((e.created_at for e in previos if e.payload.get("que") == que), None)
            if ultimo and ts - ultimo < _ENTRE_RECORDATORIOS:
                raise ServiceError("ya_recordado", "Ya se le recordó en las últimas 24 horas.", status=409,
                                   siguiente=(ultimo + _ENTRE_RECORDATORIOS).isoformat())
            db.commit()  # sin candados durante Graph
        except Exception:
            db.rollback()
            raise
        db.refresh(req)
        salio = notify.notify_student(db, req, kind=kind, link="/prorrogas/estudiante")
        if salio:
            log_event(db, event_type="recordatorio_pendiente", request_id=req.id, actor_id=actor_id,
                      payload={"que": que}).created_at = ts
        try:
            db.commit()
        except Exception:
            logger.exception("No se pudo guardar el aviso de la solicitud %s", req.id)
            db.rollback()
        if not salio:
            raise ServiceError("correo_no_salio",
                               "El recordatorio no salió: revisa la conexión del correo en /itcj/config/email.",
                               status=502)
        return req

    @staticmethod
    def export_adeudos(db, period_id: int, actor_id: int, *, now: date | datetime | None = None) -> tuple[bytes, str]:
        """Lista de estudiantes con parcialidad vencida (§16.1) para el centro de cómputo."""
        now, today, ts = _tiempos(now)
        period = db.get(AcademicPeriod, period_id)
        if period is None:
            raise ServiceError("periodo_no_encontrado", "No se encontró el semestre.", status=404)
        reqs = (db.query(ProrrogaRequest).filter(ProrrogaRequest.period_id == period_id,
                                                 ProrrogaRequest.status == "aceptada")
                .order_by(ProrrogaRequest.student_name, ProrrogaRequest.id).all())
        cuentas = account.load_many(db, reqs, today)
        filas = [(r, cuentas[r.id]) for r in reqs if cuentas[r.id].situacion == "atrasada"]

        ws = Workbook().active
        ws.title = "Adeudos"
        ws["A1"], ws["A2"] = "Lista de adeudos de prórrogas", f"Semestre: {period_label(period)}"
        ws["A3"] = f"Exportado el {ts:%d/%m/%Y %H:%M}"
        ws["A4"] = f"Criterio: estudiantes con al menos una parcialidad vencida y no cubierta al {today:%d/%m/%Y}."
        ws["A5"] = f"Total de estudiantes: {len(filas)}"
        ws["A1"].font = Font(bold=True, size=14)
        for i, (titulo, ancho) in enumerate(_COLUMNAS, start=1):
            celda = ws.cell(row=7, column=i, value=titulo)
            celda.font = Font(bold=True)
            ws.column_dimensions[celda.column_letter].width = ancho
        for r, c in filas:
            ws.append([r.control_number, r.student_name, r.program_name, c.saldo])
            fila = ws.max_row
            for col in range(1, 4):  # texto: openpyxl haría fórmula de un nombre que empiece con "="
                celda = ws.cell(row=fila, column=col)
                if isinstance(celda.value, str):
                    celda.data_type = "s"
            ws.cell(row=fila, column=4).number_format = _DINERO
            # Se conserva la primera exportación; si ya se avisó su desbloqueo, empieza un ciclo nuevo.
            if r.block_exported_at is None or r.unblock_notified_at is not None:
                r.block_exported_at, r.unblock_notified_at = ts, None
        if not filas:
            ws.append(["Sin estudiantes con adeudo"])
        ws.freeze_panes = "A8"
        ws.auto_filter.ref = f"A7:D{max(ws.max_row, 8)}"
        log_event(db, event_type="lista_bloqueo_exportada", request_id=None, actor_id=actor_id,
                  payload={"period_id": period_id, "estudiantes": len(filas), "solicitudes": [r.id for r, _ in filas]})
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        buf = BytesIO()
        ws.parent.save(buf)
        return buf.getvalue(), f"adeudos-prorrogas-{ts:%Y%m%d-%H%M}.xlsx"

    @staticmethod
    def mark_unblock(db, request_id: int, actor_id: int, *, now: date | datetime | None = None) -> ProrrogaRequest:
        """Marca que el estudiante, ya liquidado, fue reportado para desbloqueo (§16.2)."""
        _, today, ts = _tiempos(now)
        req = StudentsService._bloquear(db, request_id)
        try:
            if not _avisar_desbloqueo(req, account.load(db, req, today)):
                raise ServiceError("no_aplica", "No hay un desbloqueo pendiente de avisar.", status=409)
            req.unblock_notified_at = ts
            log_event(db, event_type="desbloqueo_avisado", request_id=req.id, actor_id=actor_id, payload={})
            db.commit()
        except Exception:
            db.rollback()
            raise
        return req
