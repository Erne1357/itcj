"""Semestres (`core_academic_periods`) y periodo de Prórrogas de cada uno."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.exc import IntegrityError

from itcj2.apps.prorrogas_tec.models.period import ProrrogaPeriod
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.formatting import fecha_larga, semestre_label
from itcj2.core.models.academic_period import AcademicPeriod
from itcj2.core.utils.timezone import db_now

_CHOQUES = ("ex_prorrogas_periods_ventana", "uq_prorrogas_periods_semestre")


def period_for(db, day: date) -> AcademicPeriod | None:
    """Semestre no archivado cuyo rango contiene ``day`` (el más reciente si hubiera traslape)."""
    return (
        db.query(AcademicPeriod)
        .filter(AcademicPeriod.start_date <= day, AcademicPeriod.end_date >= day,
                AcademicPeriod.status != "ARCHIVED")
        .order_by(AcademicPeriod.start_date.desc())
        .first()
    )


def period_label(p: AcademicPeriod) -> str:
    return semestre_label(p.start_date, p.end_date)


def open_window(db, day: date) -> ProrrogaPeriod | None:
    """Periodo de Prórrogas que admite solicitudes en ``day``; puede abrir antes de que empiece su semestre."""
    return (
        db.query(ProrrogaPeriod).join(ProrrogaPeriod.period)
        .filter(ProrrogaPeriod.opens_on <= day, ProrrogaPeriod.closes_on >= day,
                AcademicPeriod.status != "ARCHIVED")
        .first()
    )


def configuracion(db, today: date) -> dict:
    """Semestres para la pestaña Configuración: primero el actual (o el próximo), luego del más nuevo al más viejo."""
    semestres = (db.query(AcademicPeriod).filter(AcademicPeriod.status != "ARCHIVED")
                 .order_by(AcademicPeriod.start_date.desc()).all())
    filas = {f.period_id: f for f in db.query(ProrrogaPeriod).all()}
    proximos = [p for p in semestres if p.start_date > today]
    primero = period_for(db, today) or (proximos[-1] if proximos else None)
    if primero:
        semestres.sort(key=lambda p: p.id != primero.id)  # sort estable: el resto conserva su orden

    def periodo(f: ProrrogaPeriod | None) -> dict | None:
        return f and {"abre": f.opens_on.isoformat(), "cierra": f.closes_on.isoformat(),
                      "pago1": f.payment_1_on.isoformat(), "pago2": f.payment_2_on.isoformat()}

    return {"hoy": today.isoformat(), "items": [
        {"id": p.id, "label": period_label(p), "inicio": p.start_date.isoformat(), "fin": p.end_date.isoformat(),
         "periodo": periodo(filas.get(p.id))} for p in semestres]}


def guardar(db, period_id: int, actor_id: int, *, abre: date, cierra: date, pago1: date, pago2: date,
            now: datetime | None = None) -> ProrrogaPeriod:
    """Crea o corrige el periodo de un semestre; los planes ya creados conservan sus fechas."""
    semestre = db.get(AcademicPeriod, period_id)
    if semestre is None or semestre.status == "ARCHIVED":
        raise ServiceError("no_encontrado", "No se encontró el semestre.", status=404)
    if cierra <= abre:
        raise ServiceError("fechas_invalidas", "El cierre de solicitudes debe ser después de la apertura.")
    if pago1 <= abre:
        raise ServiceError("fechas_invalidas", "El pago 1 debe ser después de la apertura.")
    if pago2 <= pago1:
        raise ServiceError("fechas_invalidas", "El pago 2 debe ser después del pago 1.")
    if pago2 >= semestre.end_date:
        raise ServiceError("fechas_invalidas",
                           f"Las fechas de pago deben ser antes del fin del semestre ({fecha_larga(semestre.end_date)}).")
    fila = db.query(ProrrogaPeriod).filter_by(period_id=period_id).first() or ProrrogaPeriod(period_id=period_id)
    fila.opens_on, fila.closes_on, fila.payment_1_on, fila.payment_2_on = abre, cierra, pago1, pago2
    fila.updated_by_id = actor_id
    fila.updated_at = now or db_now()
    db.add(fila)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        if getattr(getattr(e.orig, "diag", None), "constraint_name", None) not in _CHOQUES:
            raise
        raise ServiceError("periodo_encimado", "El periodo de solicitudes se encima con el de otro semestre.", status=409)
    return fila
