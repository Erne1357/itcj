"""Bandeja de Biblioteca para el no adeudo (Biblioteca -> Caja).

El Centro de Información (rol `titulatec_library`, puesto «Biblioteca · No
adeudo») trabaja aquí la cola FIFO de TODA inscripción aceptada
(`LibraryClearance`, Tarea 4): «Sin adeudo» (fila y lote), «Con adeudo…»
(monto + nota) y «Constancia previa…» (fecha + nota) desde «Por revisar»;
«Corregir…» desde «En caja»; «Revertir…»/«Deshacer…» desde «Liberados»;
«Observar…» desde «Por revisar»/«En caja» y, en «Con observaciones»,
«Actualizar observación…» y «Rehabilitar» (spec 2026-10-05 §3.5).

Cada ruta lleva EXACTAMENTE un código en `perms=[...]`: la lista es OR
(`itcj2/dependencies.py:131`), así que un código de más abre la bandeja
entera a quien no debería.

Pestañas por estado, «Por revisar» por omisión (es la cola de trabajo
pendiente). Cada acción vuelve a pintar la pestaña donde estaba Biblioteca:
cada formulario de fila la manda de vuelta en `status`, `q` y `page` (campos
ocultos) -- mismo patrón que `pages/survey_reviews_admin.py`.

Las rutas van por `clearance_id`, NUNCA por `process_id` (spec
`docs/superpowers/specs/2026-10-01-titulatec-biblioteca-caja-design.md` §4.6:
Biblioteca no tiene alcance por carrera, ve todo; §5 invariante 6, censo en
`tests/fastapi/titulatec/test_scope_guard.py`).

Concurrencia (Ruling R8, spec §4.7): cada formulario de registrar/corregir
lleva en campos ocultos el estado (`expected_status`) y, al corregir, el total
(`expected_total`) que el usuario VIO; `LibraryClearanceService.register` los
compara contra la fila bajo `FOR UPDATE` y levanta `ClearanceConflict` (un
`ValueError`) si otra persona ya la movió (Review Focus #1). Ruling R24: ese
choque responde 200 con la bandeja re-pintada y el aviso en `X-Tt-Notice`
(warning), nunca 400; el lote ya lo hacía (lo omite con su motivo).
`expected_total` se convierte con `Decimal(...)` DIRECTO (`_expected_total`),
nunca con `parse_amount` -- ese tiene tope y solo acepta formatos de tecleo;
el total oculto es un dato que esta misma bandeja ya mostró, no algo que el
usuario escribe.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec
from itcj2.apps.titulatec.utils.paging import PAGE_SIZE
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("itcj2.apps.titulatec.pages.library_admin")
router = APIRouter(prefix="/admin/biblioteca", tags=["titulatec-pages-library"])

_LIST = ["titulatec.library_clearance.page.list"]
_REGISTER = ["titulatec.library_clearance.api.register"]
_PRIOR = ["titulatec.library_clearance.api.prior"]
_REVERT = ["titulatec.library_clearance.api.revert"]


# Pestañas, en el orden en que se pintan. `pending` es la que ve Biblioteca al
# entrar: es la cola de trabajo pendiente (FIFO por inscripción, spec §4.7).
_TABS = (
    ("pending", "Por revisar"),
    ("awaiting_payment", "En caja"),
    ("observed", "Con observaciones"),
    ("cleared", "Liberados"),
)
_TAB_KEYS = tuple(key for key, _ in _TABS)
_DEFAULT_TAB = "pending"


def _hdr(msg: str) -> str:
    """Percent-encode para que un mensaje acentuado quepa en un header latin-1.

    Gemelo de `pages/survey_reviews_admin.py:54`;
    `titulatec-utils.js::decodeHeaderMsg` lo deshace al mostrarlo.
    """
    from urllib.parse import quote
    return quote(msg or "", safe="")


def _to_int(raw):
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _tab(raw) -> str:
    """La pestaña pedida, o «Por revisar». Nunca un filtro arbitrario."""
    return raw if isinstance(raw, str) and raw in _TAB_KEYS else _DEFAULT_TAB


def _expected_total(raw):
    """El total oculto que el usuario vio: `Decimal` DIRECTO (Ruling R8), NO
    `parse_amount` (ese tiene tope y solo acepta formatos de tecleo). Un valor
    fuera de forma -campo oculto manipulado a mano, o una página vieja que ya
    no coincide- es una regla de negocio más: 400 legible, nunca un 500."""
    if raw in (None, ""):
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("El total no es válido; recarga la bandeja e intenta de nuevo.")


def _bulk_notice(result: dict) -> str:
    """«N registrados · M omitidos» (D10), con los motivos de lo omitido."""
    done, skipped = result["done"], result["skipped"]
    registrados = "registrado" if done == 1 else "registrados"
    omitidos = "omitido" if len(skipped) == 1 else "omitidos"
    aviso = f"{done} {registrados} · {len(skipped)} {omitidos}"
    if skipped:
        motivos = list(dict.fromkeys(motivo for _cid, motivo in skipped))
        aviso += ": " + "; ".join(motivos)
    return aviso


def _body_ctx(db, *, status, q, page, per_page: int = PAGE_SIZE):
    """Contexto del parcial. `q` en blanco (o solo espacios) se normaliza a
    `None` AQUÍ: `LibraryClearanceService.list_for_inbox` trataría "   " como
    un patrón `ILIKE '%%'` de verdad, así que el recorte vive en la ruta y no
    en el service (mismo criterio que `survey_reviews_admin.py:76-95`)."""
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService, format_amount,
    )

    tab = _tab(status)
    q_clean = (q or "").strip() or None
    page = max(1, _to_int(page) or 1)

    counts = LibraryClearanceService.counts_by_status(db, q=q_clean)
    pagina = LibraryClearanceService.list_for_inbox(
        db, status=tab, q=q_clean, page=page, per_page=per_page)
    missing_donation = LibraryClearanceService.cohorts_missing_donation(db)

    return {
        "tabs": _TABS, "status": tab, "counts": counts, "rows": pagina.items,
        "q": q_clean or "", "page": pagina.page, "pg": pagina,
        "missing_donation": missing_donation, "format_amount": format_amount,
    }


@router.get("", name="titulatec.pages.library.list")
def list_library(request: Request, status: str = "", q: str = "", page: str = "1",
                 user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, status=status, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/library.html", ctx)


@router.get("/body", name="titulatec.pages.library.body")
def body(request: Request, status: str = "", q: str = "", page: str = "1",
         user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    """Hermana de la página: acepta LOS MISMOS query params (HTMX manda
    `status`/`q`/`page` vacíos la primera vez)."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, status=status, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/library_body.html", ctx)


@router.post("/registrar", name="titulatec.pages.library.register_bulk")
async def register_bulk(request: Request,
                        user: dict = Depends(require_page_app("titulatec", perms=_REGISTER))):
    """Lote «Sin adeudo» (D10): registra adeudo 0 sobre los ids marcados en
    «Por revisar», en UNA transacción (`register_no_debt_bulk`). Los que no
    pasan la validación se omiten con su motivo; el aviso «N registrados · M
    omitidos» viaja en `X-Tt-Notice` (lo pinta `titulatec-utils.js`)."""
    form = await request.form()
    return await run_in_threadpool(_cuerpo_register_bulk, request=request, user=user, form=form)


def _cuerpo_register_bulk(request, user, form):
    """Cuerpo síncrono de `register_bulk`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    raw_ids = form.getlist("ids")
    status, q, page = form.get("status"), form.get("q"), form.get("page")

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        try:
            clearance_ids = [int(cid) for cid in raw_ids if str(cid).strip()]
        except (TypeError, ValueError):
            return Response(status_code=400,
                            headers={"X-Tt-Error": _hdr("Selección inválida.")})
        if not clearance_ids:
            return Response(status_code=400,
                            headers={"X-Tt-Error": _hdr("Selecciona al menos un caso.")})
        result = LibraryClearanceService.register_no_debt_bulk(db, clearance_ids, uid)
        ctx = _body_ctx(db, status=status, q=q, page=page)
    finally:
        db.close()
    resp = render_titulatec(request, "titulatec/admin/partials/library_body.html", ctx)
    resp.headers["X-Tt-Notice"] = _hdr(_bulk_notice(result))
    resp.headers["X-Tt-Notice-Kind"] = "warning" if result["skipped"] else "success"
    return resp


@router.post("/{clearance_id}/registrar", name="titulatec.pages.library.register")
async def register(clearance_id: int, request: Request,
                   user: dict = Depends(require_page_app("titulatec", perms=_REGISTER))):
    """Registrar (desde «Por revisar») o Corregir (desde «En caja»): mismo
    verbo en el service (`LibraryClearanceService.register`); solo cambia el
    `expected_status` oculto que manda cada formulario («Sin adeudo»/«Con
    adeudo…» -> `pending`; «Corregir…» -> `awaiting_payment` + el total
    mostrado en `expected_total`, spec §4.7 Ruling R8).

    Si otra persona movió la fila mientras tanto (`ClearanceConflict`, Ruling
    R24) NO es un 400: se responde 200 con la bandeja RE-PINTADA -con el
    estado y el monto vigentes- y el motivo en `X-Tt-Notice` (warning), el
    patrón de colisión de estado de la app (htmx no hace swap en un 4xx). Las
    demás reglas de negocio siguen en 400 + `X-Tt-Error`."""
    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_register, clearance_id=clearance_id, request=request, user=user, form=form)


def _cuerpo_register(clearance_id, request, user, form):
    """Cuerpo síncrono de `register`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.library_clearance_service import (
        ClearanceConflict, LibraryClearanceService, parse_amount,
    )

    note = form.get("note") or None
    status, q, page = form.get("status"), form.get("q"), form.get("page")
    expected_status = form.get("expected_status") or None

    choque = None
    db = SessionLocal()
    try:
        uid = int(user["sub"])
        try:
            debt_amount = parse_amount(form.get("debt_amount"))
            expected_total = _expected_total(form.get("expected_total"))
            LibraryClearanceService.register(
                db, clearance_id, uid, debt_amount=debt_amount, note=note,
                expected_status=expected_status, expected_total=expected_total)
        except LookupError:
            return Response(status_code=404)
        except ClearanceConflict as e:
            choque = str(e)
        except ValueError as e:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(e))})
        ctx = _body_ctx(db, status=status, q=q, page=page)
    finally:
        db.close()
    resp = render_titulatec(request, "titulatec/admin/partials/library_body.html", ctx)
    if choque:
        resp.headers["X-Tt-Notice"] = _hdr(choque)
        resp.headers["X-Tt-Notice-Kind"] = "warning"
    return resp


@router.post("/{clearance_id}/previa", name="titulatec.pages.library.prior")
async def prior(clearance_id: int, request: Request,
                user: dict = Depends(require_page_app("titulatec", perms=_PRIOR))):
    """Constancia previa (D9): el egresado ya pagó y trae su papel -lo
    registra Biblioteca sin pasar por Caja (`register_prior(by="library")`)."""
    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_prior, clearance_id=clearance_id, request=request, user=user, form=form)


def _cuerpo_prior(clearance_id, request, user, form):
    """Cuerpo síncrono de `prior`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    from itcj2.apps.titulatec.utils.form_dates import parse_issued_on

    note = form.get("note") or None
    status, q, page = form.get("status"), form.get("q"), form.get("page")

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        try:
            issued_on = parse_issued_on(form.get("issued_on"))
            LibraryClearanceService.register_prior(
                db, clearance_id, uid, issued_on=issued_on, note=note, by="library")
        except LookupError:
            return Response(status_code=404)
        except ValueError as e:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(e))})
        ctx = _body_ctx(db, status=status, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/library_body.html", ctx)


@router.post("/{clearance_id}/deshacer-previa", name="titulatec.pages.library.undo_prior")
async def undo_prior(clearance_id: int, request: Request,
                     user: dict = Depends(require_page_app("titulatec", perms=_PRIOR))):
    """Deshacer constancia previa (motivo obligatorio): `cleared/prior` ->
    `pending`. Solo si la fase 2 no está aprobada (`can_revert`)."""
    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_undo_prior, clearance_id=clearance_id, request=request, user=user, form=form)


def _cuerpo_undo_prior(clearance_id, request, user, form):
    """Cuerpo síncrono de `undo_prior`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    reason = form.get("reason") or ""
    status, q, page = form.get("status"), form.get("q"), form.get("page")

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        try:
            LibraryClearanceService.undo_prior(db, clearance_id, uid, reason)
        except LookupError:
            return Response(status_code=404)
        except ValueError as e:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(e))})
        ctx = _body_ctx(db, status=status, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/library_body.html", ctx)


@router.post("/{clearance_id}/revertir", name="titulatec.pages.library.revert")
async def revert(clearance_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_REVERT))):
    """Revertir una liberación sin cargo o legado (motivo obligatorio):
    `cleared/no_charge|legacy` -> `pending`. Un pago lo revierte Caja: el
    service levanta `ValueError` si `cleared_via == 'payment'` y esta ruta lo
    traduce al mismo 400 de cualquier otra regla de negocio."""
    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_revert, clearance_id=clearance_id, request=request, user=user, form=form)


def _cuerpo_revert(clearance_id, request, user, form):
    """Cuerpo síncrono de `revert`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    reason = form.get("reason") or ""
    status, q, page = form.get("status"), form.get("q"), form.get("page")

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        try:
            LibraryClearanceService.revert_clearance(db, clearance_id, uid, reason)
        except LookupError:
            return Response(status_code=404)
        except ValueError as e:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(e))})
        ctx = _body_ctx(db, status=status, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/library_body.html", ctx)


@router.post("/{clearance_id}/observar", name="titulatec.pages.library.observe")
async def observe(clearance_id: int, request: Request,
                  user: dict = Depends(require_page_app("titulatec", perms=_REGISTER))):
    """Observar (desde «Por revisar»/«En caja») o Actualizar observación (desde
    «Con observaciones»): mismo verbo en el service
    (`LibraryClearanceService.observe`, spec 2026-10-05 §3.2/§3.5). Motivo
    obligatorio (form `reason`); re-pinta la pestaña/página/búsqueda de donde
    vino. Reglas de negocio -> 400 + `X-Tt-Error` (vía `_hdr`)."""
    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_observe, clearance_id=clearance_id, request=request, user=user, form=form)


def _cuerpo_observe(clearance_id, request, user, form):
    """Cuerpo síncrono de `observe`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    reason = form.get("reason") or ""
    status, q, page = form.get("status"), form.get("q"), form.get("page")

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        try:
            LibraryClearanceService.observe(db, clearance_id, reason=reason, actor_id=uid)
        except LookupError:
            return Response(status_code=404)
        except ValueError as e:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(e))})
        ctx = _body_ctx(db, status=status, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/library_body.html", ctx)


@router.post("/{clearance_id}/rehabilitar", name="titulatec.pages.library.reenable")
async def reenable(clearance_id: int, request: Request,
                   user: dict = Depends(require_page_app("titulatec", perms=_REGISTER))):
    """Rehabilitar: `observed` -> `pending` («Por revisar») con los montos
    que tuviera (`LibraryClearanceService.reenable`, spec 2026-10-05 §3.2).
    Re-pinta la pestaña/página/búsqueda de donde vino."""
    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_reenable, clearance_id=clearance_id, request=request, user=user, form=form)


def _cuerpo_reenable(clearance_id, request, user, form):
    """Cuerpo síncrono de `reenable`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService

    status, q, page = form.get("status"), form.get("q"), form.get("page")

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        try:
            LibraryClearanceService.reenable(db, clearance_id, actor_id=uid)
        except LookupError:
            return Response(status_code=404)
        except ValueError as e:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(e))})
        ctx = _body_ctx(db, status=status, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/library_body.html", ctx)
