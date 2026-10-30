"""Cuenta del estudiante: cómo lo pagado cubre las parcialidades vigentes (más vieja primero)."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func

from ..models.plan import ProrrogaInstallment, ProrrogaPayment

CERO = Decimal("0")


@dataclass(frozen=True)
class Parcialidad:
    number: int
    amount: Decimal
    due_date: date
    cubierto: Decimal
    estado: str  # pagada | vencida | parcial | pendiente


@dataclass(frozen=True)
class Cuenta:
    total: Decimal | None
    pagado: Decimal
    saldo: Decimal | None
    parcialidades: tuple[Parcialidad, ...]
    situacion: str  # sin_plan | liquidada | atrasada | al_corriente
    faltantes: int
    vencida_desde: date | None
    proxima: Parcialidad | None


def cuenta(total: Decimal | None, installments: Sequence[tuple[int, Decimal, date]], pagado: Decimal,
           today: date) -> Cuenta:
    if total is None:
        return Cuenta(None, pagado, None, (), "sin_plan", 0, None, None)
    resto = pagado
    partes = []
    for number, amount, due in sorted(installments, key=lambda i: i[0]):
        cubierto = min(resto, amount)
        resto -= cubierto
        if cubierto == amount:
            estado = "pagada"
        elif due < today:
            estado = "vencida"
        elif cubierto > 0:
            estado = "parcial"
        else:
            estado = "pendiente"
        partes.append(Parcialidad(number, amount, due, cubierto, estado))
    vencidas = [p.due_date for p in partes if p.estado == "vencida"]
    sin_cubrir = [p for p in partes if p.estado != "pagada"]
    situacion = "liquidada" if pagado >= total else "atrasada" if vencidas else "al_corriente"
    return Cuenta(total, pagado, max(total - pagado, CERO), tuple(partes), situacion, len(sin_cubrir),
                  min(vencidas, default=None), sin_cubrir[0] if sin_cubrir else None)


def money(x: Decimal) -> str:
    return str(x.quantize(Decimal("0.01")))


def _parcialidad_json(p: Parcialidad) -> dict:
    return {"numero": p.number, "monto": money(p.amount), "fecha": p.due_date.isoformat(),
            "cubierto": money(p.cubierto), "estado": p.estado}


def cuenta_json(c: Cuenta) -> dict:
    return {
        "total": None if c.total is None else money(c.total),
        "pagado": money(c.pagado),
        "saldo": None if c.saldo is None else money(c.saldo),
        "situacion": c.situacion,
        "faltantes": c.faltantes,
        "vencida_desde": c.vencida_desde.isoformat() if c.vencida_desde else None,
        "proxima": _parcialidad_json(c.proxima) if c.proxima else None,
        "parcialidades": [_parcialidad_json(p) for p in c.parcialidades],
    }


def load_many(db, reqs, today: date) -> dict[int, Cuenta]:
    """Cuentas de varias solicitudes en 2 consultas (parcialidades vigentes; suma de recibos no anulados)."""
    if not reqs:
        return {}
    ids = [r.id for r in reqs]
    plan: dict[int, list] = {i: [] for i in ids}
    for rid, number, amount, due in db.query(
            ProrrogaInstallment.request_id, ProrrogaInstallment.number, ProrrogaInstallment.amount,
            ProrrogaInstallment.due_date).filter(ProrrogaInstallment.request_id.in_(ids),
                                                 ProrrogaInstallment.superseded_at.is_(None)):
        plan[rid].append((number, amount, due))
    pagos = dict(db.query(ProrrogaPayment.request_id, func.sum(ProrrogaPayment.amount)).filter(
        ProrrogaPayment.request_id.in_(ids), ProrrogaPayment.voided_at.is_(None))
        .group_by(ProrrogaPayment.request_id).all())
    return {r.id: cuenta(r.total_amount, plan[r.id], pagos.get(r.id) or CERO, today) for r in reqs}


def load(db, req, today: date) -> Cuenta:
    return load_many(db, [req], today)[req.id]


def cobertura(installments: Sequence[tuple[int, Decimal, date]],
              recibos: Sequence[tuple[date, Decimal]]) -> list[date | None]:
    """Por parcialidad (en orden de número), el día en que la suma de recibos alcanzó su monto acumulado."""
    pagos = sorted(recibos, key=lambda r: r[0])  # estable: a igual fecha respeta el orden recibido (id)
    acumulados = []
    suma = CERO
    for paid_on, amount in pagos:
        suma += amount
        acumulados.append((suma, paid_on))
    salida: list[date | None] = []
    meta = CERO
    for _, amount, _due in sorted(installments, key=lambda i: i[0]):
        meta += amount
        salida.append(next((d for s, d in acumulados if s >= meta), None))
    return salida
