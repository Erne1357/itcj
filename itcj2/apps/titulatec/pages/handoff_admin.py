"""Bandeja de solo lectura: egresados liberados al Departamento de Titulacion.

Tarea 5 del deslinde a T-soft (spec `2026-09-21-titulatec-dpto-titulacion`,
design doc S5, D10-D12). Consume `HandoffService` (Tarea 4,
`services/handoff_service.py`) sin ninguna escritura propia: nada de
"entregado a T-soft", nada de tabla nueva. El Departamento de Titulacion (y la
jefatura de la Division, via el rol de supervision) usa esta pestana para ver
a quien Servicios Escolares ya libero (fase 2 -- Cita de cotejo -- aprobada) y
exportarlo a CSV para darlo de alta a mano en T-soft.

Cada ruta lleva EXACTAMENTE el codigo que le toca en `perms=[...]`: la lista
es OR (`itcj2/dependencies.py:131`), asi que un codigo de mas abre la bandeja
entera a quien no deberia. `page.list` cubre listar y el parcial de filtros;
`api.export` es EXCLUSIVO del CSV (alguien puede ver la bandeja sin poder
descargarla, y viceversa).

ORDEN DE DECLARACION: `/export.csv` y `/body` van declaradas antes que
cualquier ruta con `{param}` (no hay ninguna hoy, pero se deja el orden listo
-- ver la docstring de `surveys_admin.py:3-9` para el porque exacto).

El alcance por carrera sale de `scope_service.officer_programs(db, user_id)`
y se le pasa TAL CUAL a `HandoffService`: "ALL" o un `set[int]` (vacio =
fail-closed, no ve nada hasta que le asignen carreras).
"""
import csv
import io
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.handoff_admin")
router = APIRouter(prefix="/admin/liberados", tags=["titulatec-pages-handoff"])

_LIST = ["titulatec.handoff.page.list"]
_EXPORT = ["titulatec.handoff.api.export"]

_PAGE_SIZE = 50

_CSV_HEADERS = ("No. control", "Nombre", "Correo", "Carrera", "Modalidad",
                "Convocatoria", "Liberado el")


def _to_int(raw):
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _officer_scope(db, user_id: int):
    """Alcance del actor ('ALL' o `set[int]`). Import local, evita ciclos."""
    from itcj2.apps.titulatec.services.scope_service import officer_programs
    return officer_programs(db, user_id)


def _body_ctx(db, *, user_id: int, cohort_id, program_id, modality_id, q, page: int) -> dict:
    """Contexto del parcial. Distingue el alcance vacio (fail-closed, en
    silencio) de "sin resultados con este filtro" -- mismo riesgo que
    `requests_admin.py:_body_ctx` para la bandeja de Solicitudes."""
    from itcj2.core.models.program import Program
    from itcj2.apps.titulatec.models import Cohort, Modality
    from itcj2.apps.titulatec.services.handoff_service import HandoffService
    from itcj2.core.services.authz_service import get_user_permissions_for_app

    # Arreglo A5 (revision final 2026-09-21): el boton «Exportar CSV» se
    # pintaba sin comprobar `titulatec.handoff.api.export` -- justo el
    # permiso EXCLUSIVO del CSV que el docstring del modulo (arriba) dice
    # querer soportar ("alguien puede ver la bandeja sin poder descargarla").
    # Mismo criterio que `can_mark_reqs` (`pages/admin.py:1285-1291`): un
    # boton que dispara un GET que responde 403 es peor que no estar.
    can_export = "titulatec.handoff.api.export" in get_user_permissions_for_app(
        db, user_id, "titulatec")

    scope = _officer_scope(db, user_id)
    ctx = {
        "rows": [], "total": 0, "page": max(1, page or 1), "has_more": False,
        "cohort_id": cohort_id, "program_id": program_id, "modality_id": modality_id,
        "q": q or "", "no_programs": False,
        "cohorts": [], "programs": [], "modalities": [],
        "can_export": can_export,
    }
    if scope != "ALL" and not scope:
        ctx["no_programs"] = True
        return ctx

    ctx["cohorts"] = [{"id": c.id, "name": c.name}
                      for c in db.query(Cohort).order_by(Cohort.name).all()]
    programs_q = db.query(Program).order_by(Program.name)
    if scope != "ALL":
        programs_q = programs_q.filter(Program.id.in_(scope))
    ctx["programs"] = [{"id": p.id, "name": p.name} for p in programs_q.all()]
    ctx["modalities"] = [{"id": m.id, "name": m.name} for m in
                         db.query(Modality).filter_by(is_active=True)
                         .order_by(Modality.name).all()]

    q_clean = (q or "").strip() or None
    page = max(1, page or 1)
    rows, total = HandoffService.list_released(
        db, allowed_program_ids=scope, cohort_id=cohort_id, program_id=program_id,
        modality_id=modality_id, q=q_clean, page=page, per_page=_PAGE_SIZE,
    )
    ctx.update({
        "rows": rows, "total": total, "page": page,
        "has_more": (page * _PAGE_SIZE) < total,
        "q": q_clean or "",
    })
    return ctx


@router.get("", name="titulatec.pages.handoff.list")
async def list_released(request: Request, cohort_id: str = "", program_id: str = "",
                        modality_id: str = "", q: str = "", page: str = "1",
                        user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), cohort_id=_to_int(cohort_id),
                        program_id=_to_int(program_id), modality_id=_to_int(modality_id),
                        q=q, page=_to_int(page) or 1)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/handoff.html", ctx)


@router.get("/body", name="titulatec.pages.handoff.body")
async def body(request: Request, cohort_id: str = "", program_id: str = "",
               modality_id: str = "", q: str = "", page: str = "1",
               user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    """Hermana de la pagina: acepta LOS MISMOS query params."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), cohort_id=_to_int(cohort_id),
                        program_id=_to_int(program_id), modality_id=_to_int(modality_id),
                        q=q, page=_to_int(page) or 1)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/handoff_table.html", ctx)


@router.get("/export.csv", name="titulatec.pages.handoff.export")
async def export(request: Request, cohort_id: str = "", program_id: str = "",
                 modality_id: str = "", q: str = "",
                 user: dict = Depends(require_page_app("titulatec", perms=_EXPORT))):
    """CSV de todos los liberados que caen en el alcance + filtros del actor.

    Las celdas se escapan con `escape_formula` (services/survey_service.py,
    a proposito de nivel de modulo): mismo tratamiento incondicional que le
    da `SurveyService.export_rows` a toda columna, no solo a las de riesgo.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.handoff_service import HandoffService
    from itcj2.apps.titulatec.services.survey_service import escape_formula

    db = SessionLocal()
    try:
        scope = _officer_scope(db, int(user["sub"]))
        rows = HandoffService.export_rows(
            db, allowed_program_ids=scope, cohort_id=_to_int(cohort_id),
            program_id=_to_int(program_id), modality_id=_to_int(modality_id),
            q=(q or "").strip() or None,
        )
    finally:
        db.close()

    output = io.StringIO()
    output.write("﻿")  # BOM UTF-8 para Excel en Windows
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(_CSV_HEADERS)
    for r in rows:
        crudas = [
            r.control_number,
            r.full_name,
            r.email or "",
            r.program_name,
            r.modality_name or "",
            r.cohort_name,
            r.released_at.isoformat(sep=" ", timespec="seconds") if r.released_at else "",
        ]
        writer.writerow([escape_formula(c) for c in crudas])

    filename = f"liberados-titulacion-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
