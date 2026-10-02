"""Bandeja de Caja para cobrar el no adeudo de biblioteca (Biblioteca -> Caja).

Recursos Financieros (rol `titulatec_cashier`, puesto «Caja») busca a un
egresado por control o nombre -EN CUALQUIER ESTADO, `LibraryClearanceService.
search`-, ve el desglose adeudo + donación voluntaria de libro = total
(congelado por Biblioteca, Tarea 4), registra el pago («Registrar pago»,
número de recibo opcional) y puede revertir un cobro equivocado («Revertir
pago…», motivo) mientras la fase 2 no esté aprobada (`can_revert`). Sin citas
en Caja (D4). «Pagados» («Corte del día», E3) es un corte FIJO: los cobros del
día más las reversas HECHAS ese día, como renglón negativo
(`LibraryClearanceService.day_cut`) -- una reversa de OTRO día nunca mueve el
corte de un día ya cerrado (spec `2026-10-02-titulatec-constancias-y-
pendientes-design.md` §3.6).

Cada ruta lleva EXACTAMENTE un código en `perms=[...]`: la lista es OR
(`itcj2/dependencies.py:131`), así que un código de más abre la bandeja entera
a quien no debería.

El buscador tiene PRECEDENCIA sobre las pestañas (spec
`docs/superpowers/specs/2026-10-01-titulatec-biblioteca-caja-design.md` §4.8):
con `q` no vacío se listan resultados de `search` en cualquier estado, con la
píldora PROPIA de Caja (E11, macro `caja_pill` de `cashier_body.html`): «En
Biblioteca», «Por cobrar $X», «Pagado» o «Liberado» -- nunca la compartida
`library_clearance_pill` (spec `2026-10-02-titulatec-constancias-y-pendientes-
design.md` §3.6, m27). Sin importar la pestaña activa; limpiar el buscador
regresa a la pestaña. Sin `q`: «Por cobrar» (`awaiting_payment`, FIFO por
`ready_at`, Ruling R9: solo procesos admitidos, mismo filtro que «Por
revisar» de Biblioteca) o «Pagados» («Corte del día»: selector de día, por
omisión hoy vía `db_now().date()`, con «Cobrado/Revertido/Total del día»).

Las rutas van por `clearance_id`, NUNCA por `process_id` (§4.6: Caja no tiene
alcance por carrera, ve todo; §5 invariante 6, censo en
`tests/fastapi/titulatec/test_scope_guard.py`).

Concurrencia (Ruling R8, spec §4.8): el formulario de «Registrar pago» lleva
en un campo oculto el total que la cajera VIO (`expected_total`);
`LibraryClearanceService.register_payment` lo compara contra la fila bajo
`FOR UPDATE` y levanta `ClearanceConflict` (un `ValueError`) si Biblioteca lo
corrigió mientras tanto (Review Focus #1): nunca se cobra un monto que la
cajera no vio, y la ruta re-pinta la bandeja con el monto vigente + un aviso
(Ruling R24) en vez de un 400 sin swap.
`expected_total` se convierte con `Decimal(...)` DIRECTO (`_expected_total`),
nunca con `parse_amount` -- ese tiene tope y solo acepta formatos de tecleo;
el total oculto es un dato que esta misma bandeja ya mostró. Ruling R9: el
service ya no le aplica el tope `AMOUNT_MAX` a `expected_total` (un adeudo al
tope más la donación lo supera sin dejar de ser un total legítimo), así que
esta ruta no necesita ninguna validación de rango propia -el service es dueño
de esa regla.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.cashier_admin")
router = APIRouter(prefix="/admin/caja", tags=["titulatec-pages-cashier"])

_LIST = ["titulatec.library_payment.page.list"]
_PAY = ["titulatec.library_payment.api.register"]
_REVERT = ["titulatec.library_payment.api.revert"]

_PAGE_SIZE = 50

# Pestañas, en el orden en que se pintan. `por_cobrar` es la que ve Caja al
# entrar: es la cola de trabajo pendiente (FIFO por `ready_at`, spec §4.8).
_TABS = (
    ("por_cobrar", "Por cobrar"),
    ("pagados", "Corte del día"),
)
_TAB_KEYS = tuple(key for key, _ in _TABS)
_DEFAULT_TAB = "por_cobrar"


def _hdr(msg: str) -> str:
    """Percent-encode para que un mensaje acentuado quepa en un header latin-1.

    Gemelo de `pages/survey_reviews_admin.py:54` y `pages/library_admin.py`;
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
    """La pestaña pedida, o «Por cobrar». Nunca un filtro arbitrario."""
    return raw if isinstance(raw, str) and raw in _TAB_KEYS else _DEFAULT_TAB


def _parse_dia(raw):
    """«AAAA-MM-DD» del selector de día -> `date`, o `None` si viene vacío o
    no es una fecha ISO real (campo manipulado a mano, o la primera carga sin
    seleccionar nada): es un filtro de VISTA, nunca una acción, así que un
    valor fuera de forma cae en blanco -el llamador pone el día de hoy- en
    vez de responder 400."""
    texto = (raw or "").strip()
    if not texto:
        return None
    from datetime import date
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


def _expected_total(raw):
    """El total oculto que la cajera VIO: `Decimal` DIRECTO (Ruling R8), NO
    `parse_amount` (ese tiene tope y solo acepta formatos de tecleo). Un valor
    fuera de forma -campo oculto manipulado a mano, o una página vieja que ya
    no coincide- es una regla de negocio más: 400 legible, nunca un 500."""
    if raw in (None, ""):
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("El total no es válido; recarga la bandeja e intenta de nuevo.")


def _body_ctx(db, *, tab, q, dia, page):
    """Contexto del parcial. `q` en blanco (o solo espacios) se normaliza a
    `None` AQUÍ, igual que en `library_admin.py`. Con `q` se listan los
    resultados de `search` (cualquier estado, sin paginar); sin `q`, la
    pestaña activa: `por_cobrar` (paginada, fila de `LibraryClearanceService.
    _rows`) o `pagados` (`day_cut`: corte del día FIJO -- E3, spec
    `2026-10-02-titulatec-constancias-y-pendientes-design.md` §3.6 -- con su
    propia forma de renglón, `None` en cualquier otra pestaña/búsqueda)."""
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService, format_amount,
    )
    from itcj2.core.utils.timezone import db_now

    tab = _tab(tab)
    q_clean = (q or "").strip() or None
    page_n = max(1, _to_int(page) or 1)
    dia_sel = _parse_dia(dia) or db_now().date()

    # «Por cobrar» siempre trae su contador, aunque la pestaña activa sea
    # «Pagados» o se esté buscando: así el botón de la pestaña nunca anuncia
    # un número que no corresponde a lo que pintaría al entrar ahí.
    # `admitted_only=True` (Ruling R9, spec §4.8): Caja no tiene ningún uso
    # para un proceso revocado o terminado -sin acciones posibles sobre él-,
    # así que lo saca de la lista Y del contador; Biblioteca («En caja») no
    # pide este flag y sigue mostrándolo con la píldora «Revocada» (Tarea 7).
    por_cobrar_count = LibraryClearanceService.counts_by_status(
        db, admitted_only=True)["awaiting_payment"]

    has_more = False
    day_cut = None
    if q_clean:
        rows = LibraryClearanceService.search(db, q_clean)
    elif tab == "pagados":
        rows = []
        day_cut = LibraryClearanceService.day_cut(db, dia_sel)
    else:
        rows, has_more = LibraryClearanceService.list_for_inbox(
            db, status="awaiting_payment", q=None, page=page_n, per_page=_PAGE_SIZE,
            admitted_only=True)

    return {
        "tabs": _TABS, "tab": tab, "q": q_clean or "", "page": page_n,
        "dia": dia_sel.isoformat(), "rows": rows, "has_more": has_more,
        "day_cut": day_cut, "por_cobrar_count": por_cobrar_count,
        "searching": q_clean is not None, "format_amount": format_amount,
    }


@router.get("", name="titulatec.pages.cashier.list")
async def list_cashier(request: Request, tab: str = "", q: str = "", dia: str = "",
                       page: str = "1",
                       user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, tab=tab, q=q, dia=dia, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/cashier.html", ctx)


@router.get("/body", name="titulatec.pages.cashier.body")
async def body(request: Request, tab: str = "", q: str = "", dia: str = "", page: str = "1",
               user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    """Hermana de la página: acepta LOS MISMOS query params (HTMX manda
    `tab`/`q`/`dia`/`page` vacíos la primera vez)."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, tab=tab, q=q, dia=dia, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/cashier_body.html", ctx)


@router.post("/{clearance_id}/pagar", name="titulatec.pages.cashier.pay")
async def pay(clearance_id: int, request: Request,
             user: dict = Depends(require_page_app("titulatec", perms=_PAY))):
    """Registrar pago: `awaiting_payment` -> `cleared/payment`
    (`LibraryClearanceService.register_payment`). Cobra el monto CONGELADO de
    la fila -nunca lo que mande el formulario-; número de recibo opcional
    (<= 40). `expected_total` guarda la concurrencia (Ruling R8): si
    Biblioteca corrigió el monto mientras tanto (`ClearanceConflict`, Ruling
    R24) se responde 200 con la bandeja RE-PINTADA -el monto vigente a la
    vista, para volver a confirmar- y el motivo en `X-Tt-Notice` (warning);
    las demás reglas siguen en 400 + `X-Tt-Error`."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.library_clearance_service import (
        ClearanceConflict, LibraryClearanceService,
    )

    form = await request.form()
    recibo = form.get("recibo") or None
    tab, q, dia, page = form.get("tab"), form.get("q"), form.get("dia"), form.get("page")

    choque = None
    db = SessionLocal()
    try:
        uid = int(user["sub"])
        try:
            expected_total = _expected_total(form.get("expected_total"))
            LibraryClearanceService.register_payment(
                db, clearance_id, uid, receipt_number=recibo, expected_total=expected_total)
        except LookupError:
            return Response(status_code=404)
        except ClearanceConflict as e:
            choque = str(e)
        except ValueError as e:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(e))})
        ctx = _body_ctx(db, tab=tab, q=q, dia=dia, page=page)
    finally:
        db.close()
    resp = render_titulatec(request, "titulatec/admin/partials/cashier_body.html", ctx)
    if choque:
        resp.headers["X-Tt-Notice"] = _hdr(choque)
        resp.headers["X-Tt-Notice-Kind"] = "warning"
    return resp


@router.post("/{clearance_id}/revertir", name="titulatec.pages.cashier.revert")
async def revert(clearance_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_REVERT))):
    """Revertir pago (motivo obligatorio): `cleared/payment` ->
    `awaiting_payment` (`LibraryClearanceService.revert_payment`). Solo si la
    fase 2 no está aprobada (`can_revert`); el monto congelado se queda (sigue
    debiéndolo) y se anula la constancia. El corte del día del cobro original
    NO cambia (E3, invariante 3): esta reversa entra al corte de HOY como su
    propio renglón, en negativo -- si la cajera revertía mientras veía el
    corte de OTRO día, el aviso de éxito (`X-Tt-Notice`, success) se lo
    aclara."""
    from datetime import date

    from itcj2.database import SessionLocal
    from itcj2.core.utils.timezone import db_now
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService, format_amount,
    )

    form = await request.form()
    reason = form.get("reason") or ""
    tab, q, dia, page = form.get("tab"), form.get("q"), form.get("dia"), form.get("page")

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        try:
            clearance = LibraryClearanceService.revert_payment(db, clearance_id, uid, reason)
        except LookupError:
            return Response(status_code=404)
        except ValueError as e:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(e))})
        monto_revertido = clearance.total_amount   # leer ANTES de cerrar (expire_on_commit)
        ctx = _body_ctx(db, tab=tab, q=q, dia=dia, page=page)
    finally:
        db.close()

    hoy = db_now().date()
    dia_vista = date.fromisoformat(ctx["dia"])
    if dia_vista != hoy:
        aviso = (f"Pago revertido. La reversa (−{format_amount(monto_revertido)}) "
                 f"quedó en el corte de hoy ({hoy.strftime('%d/%m/%Y')}).")
    else:
        aviso = "Pago revertido."

    resp = render_titulatec(request, "titulatec/admin/partials/cashier_body.html", ctx)
    resp.headers["X-Tt-Notice"] = _hdr(aviso)
    resp.headers["X-Tt-Notice-Kind"] = "success"
    return resp
