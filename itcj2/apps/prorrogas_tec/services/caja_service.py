"""Caja: lista de solicitudes por cobrar y búsqueda (solo `aceptada` con semestre de core)."""
from __future__ import annotations

from datetime import date

from itcj2.apps.prorrogas_tec.importacion.normaliza import normalizar
from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
from itcj2.apps.prorrogas_tec.services import account
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.identity import folio

FILTROS = ("todos", "con_adeudo", "al_corriente")
ORDENES = ("urgente", "proximo", "saldo", "nombre")


class CajaService:
    POR_PAGINA = 8
    MAX_RESULTADOS = 50

    @staticmethod
    def _universo(db):
        # Las históricas del Excel sin semestre de core (period_id nulo) quedan fuera de Caja.
        return db.query(ProrrogaRequest).filter(ProrrogaRequest.status == "aceptada",
                                                ProrrogaRequest.period_id.isnot(None))

    @staticmethod
    def solicitud(db, request_id: int) -> ProrrogaRequest | None:
        return CajaService._universo(db).filter(ProrrogaRequest.id == request_id).first()

    @staticmethod
    def _item(req, c) -> dict:
        p = c.proxima
        return {
            "id": req.id, "control": req.control_number, "nombre": req.student_name, "semestre": req.period_label,
            "folio": folio(req), "situacion": c.situacion,
            "siguiente": None if p is None else {"fecha": p.due_date.isoformat(),
                                                 "monto": account.money(p.amount - p.cubierto), "faltan": c.faltantes},
        }

    @staticmethod
    def listar(db, *, q: str | None = None, semestre: int | None = None, filtro: str = "todos",
               orden: str = "urgente", page: int = 1, today: date) -> dict:
        if filtro not in FILTROS:
            raise ServiceError("filtro_invalido", "Filtro no válido.", 400)
        if orden not in ORDENES:
            raise ServiceError("orden_invalido", "Orden no válido.", 400)
        qry = CajaService._universo(db)
        if semestre is not None:
            qry = qry.filter(ProrrogaRequest.period_id == semestre)
        reqs = qry.all()
        # shortcut: cuentas en Python sobre todo el universo; pasar a SQL si supera ~2000 solicitudes
        cuentas = account.load_many(db, reqs, today)
        nombre = {r.id: normalizar(r.student_name) for r in reqs}
        por_pagina = CajaService.POR_PAGINA

        texto = normalizar(q or "")
        if texto:
            palabras = texto.split()
            halladas = [r for r in reqs if texto in normalizar(r.control_number)
                        or all(w in nombre[r.id] for w in palabras)]  # el nombre se guarda con apellidos primero
            halladas.sort(key=lambda r: (nombre[r.id], r.id))
            return {"items": [CajaService._item(r, cuentas[r.id]) for r in halladas[:CajaService.MAX_RESULTADOS]],
                    "total": len(halladas), "page": 1, "per_page": por_pagina, "conteos": None}

        cobrables = [r for r in reqs if cuentas[r.id].proxima]
        vencida = {r.id: cuentas[r.id].proxima.due_date < today for r in cobrables}
        conteos = {"todos": len(cobrables), "con_adeudo": sum(vencida.values()),
                   "al_corriente": len(cobrables) - sum(vencida.values())}
        if filtro != "todos":
            cobrables = [r for r in cobrables if vencida[r.id] == (filtro == "con_adeudo")]
        claves = {
            # una vencida siempre tiene fecha menor que una al corriente: `urgente` y `proximo` coinciden
            "urgente": lambda r: (cuentas[r.id].proxima.due_date, nombre[r.id], r.id),
            "proximo": lambda r: (cuentas[r.id].proxima.due_date, nombre[r.id], r.id),
            "saldo": lambda r: (-cuentas[r.id].saldo, nombre[r.id], r.id),
            "nombre": lambda r: (nombre[r.id], r.id),
        }
        cobrables.sort(key=claves[orden])
        ultima = max(1, -(-len(cobrables) // por_pagina))
        page = min(max(page, 1), ultima)
        trozo = cobrables[(page - 1) * por_pagina:page * por_pagina]
        return {"items": [CajaService._item(r, cuentas[r.id]) for r in trozo], "total": len(cobrables),
                "page": page, "per_page": por_pagina, "conteos": conteos}
