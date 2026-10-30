"""Escribe en la base las solicitudes del archivo limpio (histórico del Excel). Idempotente por `import_ref`."""
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import select

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment, ProrrogaPayment
from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
from itcj2.apps.prorrogas_tec.services.periods import period_label
from itcj2.core.models.academic_period import AcademicPeriod
from itcj2.core.models.program import Program
from itcj2.core.models.user import User


def importar(db, solicitudes, *, dry_run: bool) -> dict:
    """Crea las solicitudes nuevas; con `dry_run` hace todo y deshace. Un error de una solicitud no frena el resto."""
    res = {"creadas": 0, "ya_existian": 0, "con_error": [], "sin_semestre_core": 0, "sin_cuenta": 0,
           "por_semestre": {}}
    try:
        existentes = set(db.scalars(select(ProrrogaRequest.import_ref).where(
            ProrrogaRequest.import_ref.in_([s.ref for s in solicitudes]))))
        # Con etiqueta repetida gana el id menor (el dict se sobrescribe, así que va en orden inverso).
        periodos = {period_label(p): p.id for p in db.scalars(select(AcademicPeriod).order_by(AcademicPeriod.id.desc()))}
        programas = {p.name: p for p in db.scalars(select(Program))}
        cuentas = {u.control_number: u.id for u in db.scalars(
            select(User).where(User.control_number.in_([s.no_control for s in solicitudes])))}
        vistos = set()
        for s in solicitudes:
            if s.ref in existentes:
                res["ya_existian"] += 1
                continue
            if s.ref in vistos:
                res["con_error"].append((s.ref, "ref repetido en el archivo"))
                continue
            vistos.add(s.ref)
            if s.carrera not in programas:
                res["con_error"].append((s.ref, "carrera no existe en core"))
                continue
            if not s.parcialidades:
                res["con_error"].append((s.ref, "parcialidades vacías"))
                continue
            if len(s.parcialidades) > 6:
                res["con_error"].append((s.ref, "más de 6 parcialidades"))
                continue
            prog = programas[s.carrera]
            momento = datetime.combine(s.fecha_solicitud, time())
            req = ProrrogaRequest(
                origin="excel", import_ref=s.ref, student_id=cuentas.get(s.no_control),
                period_id=periodos.get(s.semestre), period_label=s.semestre, status="aceptada",
                requested_terms=None, reason=None, control_number=s.no_control, student_name=s.nombre,
                program_name=prog.name, program_level=prog.level, email=None,
                total_amount=sum((m for _, _, m, _ in s.parcialidades), Decimal("0")),
                created_at=momento, updated_at=momento)
            db.add(req)
            db.flush()
            for n, venc, monto, pagado in s.parcialidades:
                db.add(ProrrogaInstallment(request_id=req.id, number=n, amount=monto, due_date=venc))
                if pagado:
                    db.add(ProrrogaPayment(request_id=req.id, origin="excel", folio=None, paid_on=venc,
                                           amount=monto, recorded_by_id=None))
            res["creadas"] += 1
            sem = res["por_semestre"].setdefault(s.semestre, {"creadas": 0, "ligado": req.period_id is not None})
            sem["creadas"] += 1
            res["sin_semestre_core"] += req.period_id is None
            res["sin_cuenta"] += req.student_id is None
        db.flush()
    except Exception:
        db.rollback()
        raise
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return res
