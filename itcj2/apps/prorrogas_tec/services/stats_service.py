"""Estadísticas de la secretaria: cumplimiento, aceptación y línea de tiempo por semestre (§17.4)."""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment, ProrrogaPayment
from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
from itcj2.apps.prorrogas_tec.services.account import CERO, cobertura, money
from itcj2.apps.prorrogas_tec.services.periods import period_for, period_label
from itcj2.core.models.academic_period import AcademicPeriod
from itcj2.core.utils.timezone import db_now

SIN_CARRERA = "Sin carrera"
ENCABEZADO = ["Carrera", "Solicitudes", "Aceptación (%)", "Monto prorrogado", "Vencidas", "Pagó a tiempo",
              "Pagó tarde", "Sin pago"]


def _pct(aceptadas: int, rechazadas: int) -> int | None:
    return round(100 * aceptadas / (aceptadas + rechazadas)) if aceptadas + rechazadas else None


def _orden_etiqueta(label: str) -> tuple[int, int]:
    """Año y mitad del año de «enero – junio 2025»; lo que no se entiende queda al final (clave menor)."""
    p = label.split()
    try:
        return int(p[-1]), 0 if p[0].lower().startswith("enero") else 1
    except (ValueError, IndexError):
        return 0, 0


class StatsService:
    @staticmethod
    def semestres(db) -> dict:
        filas = (db.query(ProrrogaRequest.period_label, ProrrogaRequest.period_id, AcademicPeriod.start_date)
                 .outerjoin(AcademicPeriod, AcademicPeriod.id == ProrrogaRequest.period_id)
                 .filter(ProrrogaRequest.status != "cancelada", ProrrogaRequest.period_label.isnot(None))
                 .distinct().all())
        por_label: dict[str, tuple] = {}
        for label, pid, inicio in filas:
            if label not in por_label or (pid is not None and por_label[label][0] is None):
                por_label[label] = (pid, inicio)

        def clave(label):
            pid, inicio = por_label[label]
            y, h = (inicio.year, 0 if inicio.month < 7 else 1) if inicio else _orden_etiqueta(label)
            return y, h

        labels = sorted(por_label, key=clave, reverse=True)
        items = [{"label": lb, "period_id": por_label[lb][0]} for lb in labels]
        hoy = period_for(db, db_now().date())
        actual = period_label(hoy) if hoy else None
        if actual not in labels:
            actual = labels[0] if labels else None
        return {"items": items, "actual": actual}

    @staticmethod
    def resumen(db, semestre: str | None, today: date) -> dict:
        # shortcut: cálculo en Python por semestre; pasar a SQL si un semestre supera ~2000 solicitudes
        q = db.query(ProrrogaRequest).filter(ProrrogaRequest.status != "cancelada")
        if semestre:
            q = q.filter(ProrrogaRequest.period_label == semestre)
        reqs = q.all()
        ids = [r.id for r in reqs]
        vigentes: dict[int, list] = defaultdict(list)
        replanteadas: set[int] = set()
        recibos: dict[int, list] = defaultdict(list)
        if ids:
            for rid, n, amount, due, sup in db.query(
                    ProrrogaInstallment.request_id, ProrrogaInstallment.number, ProrrogaInstallment.amount,
                    ProrrogaInstallment.due_date, ProrrogaInstallment.superseded_at
            ).filter(ProrrogaInstallment.request_id.in_(ids)):
                if sup is None:
                    vigentes[rid].append((n, amount, due))
                else:
                    replanteadas.add(rid)
            for rid, paid_on, amount in db.query(
                    ProrrogaPayment.request_id, ProrrogaPayment.paid_on, ProrrogaPayment.amount
            ).filter(ProrrogaPayment.request_id.in_(ids), ProrrogaPayment.voided_at.is_(None)
                     ).order_by(ProrrogaPayment.paid_on, ProrrogaPayment.id):
                recibos[rid].append((paid_on, amount))

        carreras: dict[str, dict] = {}
        tot = dict.fromkeys(("vencidas", "a_tiempo", "tarde", "sin_pago"), 0)
        sin_pago_est = 0
        semanal: dict[date, list[int]] = defaultdict(lambda: [0, 0])
        mensual: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        pendientes = []
        respuestas = []
        monto_total = CERO
        plazos = []
        for r in reqs:
            c = carreras.setdefault(r.program_name or SIN_CARRERA, {
                "solicitudes": 0, "aceptadas": 0, "rechazadas": 0, "monto": CERO,
                "vencidas": 0, "a_tiempo": 0, "tarde": 0, "sin_pago": 0})
            c["solicitudes"] += 1
            if r.total_amount is not None:
                c["monto"] += r.total_amount
                monto_total += r.total_amount
            if r.status == "pendiente":
                pendientes.append(r.created_at.date())
            if r.decided_at is not None:
                respuestas.append((r.decided_at - r.created_at).total_seconds() / 86400)
            if r.status in ("aceptada", "rechazada"):
                c[r.status + "s"] += 1
                d = r.created_at.date()
                i = 0 if r.status == "aceptada" else 1
                semanal[d - timedelta(days=d.weekday())][i] += 1
                mensual[d.strftime("%Y-%m")][i] += 1
            if r.status == "aceptada":
                plazos.append(r.requested_terms if r.requested_terms is not None else len(vigentes[r.id]))
            plan = sorted(vigentes[r.id], key=lambda i: i[0])
            sin_pago_req = False
            for (_, _, due), cubierta in zip(plan, cobertura(plan, recibos[r.id])):
                if due >= today:
                    continue
                k = "sin_pago" if cubierta is None else "a_tiempo" if cubierta <= due else "tarde"
                c["vencidas"] += 1
                c[k] += 1
                tot["vencidas"] += 1
                tot[k] += 1
                sin_pago_req = sin_pago_req or k == "sin_pago"
            sin_pago_est += sin_pago_req

        acept = sum(c["aceptadas"] for c in carreras.values())
        rech = sum(c["rechazadas"] for c in carreras.values())
        filas = [{"carrera": k, **v, "monto": money(v["monto"])} for k, v in carreras.items()]
        filas.sort(key=lambda f: (-f["solicitudes"], f["carrera"]))
        return {
            "semestre": semestre or None,
            "total": len(reqs),
            "por_carrera": filas,
            "aceptacion": {"aceptadas": acept, "rechazadas": rech, "pct_aceptadas": _pct(acept, rech)},
            "linea": {
                "semanal": [{"inicio": d.isoformat(), "aceptadas": v[0], "rechazadas": v[1]}
                            for d, v in sorted(semanal.items())],
                "mensual": [{"mes": m, "aceptadas": v[0], "rechazadas": v[1]} for m, v in sorted(mensual.items())],
            },
            "kpis": {
                "pendientes": len(pendientes),
                "pendiente_mas_vieja_dias": (today - min(pendientes)).days if pendientes else None,
                "respuesta_promedio_dias": round(sum(respuestas) / len(respuestas), 1) if respuestas else None,
                "monto_total": money(monto_total),
                "plazos_promedio": round(sum(plazos) / len(plazos), 1) if plazos else None,
                "replanteadas": len(replanteadas),
            },
            "cumplimiento": {
                **tot, "estudiantes_sin_pago": sin_pago_est,
                "period_id": next((r.period_id for r in reqs if r.period_id is not None), None) if semestre else None,
            },
        }

    @staticmethod
    def csv(db, semestre: str | None, today: date) -> str:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\r\n")
        w.writerow(ENCABEZADO)
        for f in StatsService.resumen(db, semestre, today)["por_carrera"]:
            pct = _pct(f["aceptadas"], f["rechazadas"])
            w.writerow([f["carrera"], f["solicitudes"], "" if pct is None else pct, f["monto"], f["vencidas"],
                        f["a_tiempo"], f["tarde"], f["sin_pago"]])
        return "\ufeff" + buf.getvalue()
