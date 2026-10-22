"""Pestaña «Días inhábiles» (spec 2026-10-22 fase 5 §9.1, D11).

Calendario de días inhábiles de toda la app: los conteos de días hábiles (bandejas,
Tablero, plazos de revisión) descuentan estas fechas. Abrir exige
`non_working_day.page.list`; agregar o quitar, `non_working_day.api.manage`.
La lógica vive en `NonWorkingDayService`; aquí solo se arma el contexto y se
traducen los errores:

- validación del formulario (fechas, descripción, rango) → 200 con el parcial
  re-pintado y el mensaje en `#tt-dias-error`;
- guarda de permiso → 400 + `X-Tt-Error`;
- éxito → parcial re-pintado + `X-Tt-Notice`.

Sin guarda de fase: el calendario es de toda la app. En producción queda
invisible porque el permiso solo lo concede `init-titulatec-fase-2`.
Ninguna ruta lleva `{process_id}`.
"""
import logging
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from itcj2.apps.titulatec.pages.nav import render_titulatec
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.titulatec.pages.dias_inhabiles_admin")
router = APIRouter(prefix="/admin/dias-inhabiles", tags=["titulatec-pages-dias-inhabiles"])

_VIEW_PERMS = ["titulatec.non_working_day.page.list"]
_MANAGE_PERMS = ["titulatec.non_working_day.api.manage"]

_PAGE_TPL = "titulatec/admin/dias_inhabiles.html"
_BODY_TPL = "titulatec/partials/dias_inhabiles/_body.html"

_ANIO_MIN, _ANIO_MAX = 2000, 2100
_DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def _hdr(msg: str) -> str:
    """Percent-encode para que un mensaje acentuado quepa en un header latin-1
    (`titulatec-utils.js::decodeHeaderMsg` lo deshace al mostrarlo)."""
    return quote(msg or "", safe="")


def _fecha_es(d: date) -> str:
    """`lun 24 dic 2026`."""
    return f"{_DIAS[d.weekday()]} {d.day} {_MESES[d.month - 1]} {d.year}"


def _parse_iso(raw):
    """`YYYY-MM-DD` → date; vacío o basura → None."""
    try:
        return date.fromisoformat((raw or "").strip()) if raw else None
    except (TypeError, ValueError):
        return None


def _parse_anio(raw, default: int) -> int:
    try:
        anio = int(raw)
    except (TypeError, ValueError):
        return default
    return anio if _ANIO_MIN <= anio <= _ANIO_MAX else default


def _body_ctx(db, user_id: int, anio: int, error: str = "", values: dict | None = None) -> dict:
    from itcj2.apps.titulatec.services.non_working_day_service import NonWorkingDayService
    from itcj2.core.services.authz_cache import cached_perms

    can_manage = set(_MANAGE_PERMS) <= set(cached_perms(db, user_id, "titulatec"))
    filas = [{"id": r["id"], "iso": r["day"].isoformat(), "label": _fecha_es(r["day"]),
              "description": r["description"]}
             for r in NonWorkingDayService.list_year(db, anio)]
    return {
        "anio": anio,
        "anio_prev": anio - 1 if anio > _ANIO_MIN else None,
        "anio_next": anio + 1 if anio < _ANIO_MAX else None,
        "rows": filas,
        "can_manage": can_manage,
        "error": error,
        "values": values or {},
        "max_range": NonWorkingDayService.MAX_RANGE_DAYS,
        "max_description": NonWorkingDayService.MAX_DESCRIPTION,
    }


def _repintar(request, db, user_id: int, anio: int, aviso: str = "", kind: str = "success",
              error: str = "", values: dict | None = None):
    resp = render_titulatec(request, _BODY_TPL, _body_ctx(db, user_id, anio, error, values))
    if aviso:
        resp.headers["X-Tt-Notice"] = _hdr(aviso)
        resp.headers["X-Tt-Notice-Kind"] = kind
    return resp


def _plural(n: int, uno: str, varios: str) -> str:
    return f"{n} {uno if n == 1 else varios}"


# ===========================================================================
# Páginas
# ===========================================================================
@router.get("", name="titulatec.pages.dias_inhabiles.home")
def home(request: Request, anio: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    from itcj2.core.utils.timezone import db_now
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        anio_n = _parse_anio(anio, db_now().date().year)
        ctx = _body_ctx(db, int(user["sub"]), anio_n)
    finally:
        db.close()
    return render_titulatec(request, _PAGE_TPL, ctx)


@router.get("/body", name="titulatec.pages.dias_inhabiles.body")
def body(request: Request, anio: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    from itcj2.core.utils.timezone import db_now
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        anio_n = _parse_anio(anio, db_now().date().year)
        ctx = _body_ctx(db, int(user["sub"]), anio_n)
    finally:
        db.close()
    return render_titulatec(request, _BODY_TPL, ctx)


# ===========================================================================
# Acciones
# ===========================================================================
@router.post("/agregar", name="titulatec.pages.dias_inhabiles.add")
async def add(request: Request,
              user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    form = dict(await request.form())
    return await run_in_threadpool(_cuerpo_add, request=request, user=user, form=form)


def _cuerpo_add(request, user, form):
    """Cuerpo síncrono de `add`: corre en el threadpool."""
    from itcj2.apps.titulatec.services.non_working_day_service import NonWorkingDayService
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.core.utils.timezone import db_now
    from itcj2.database import SessionLocal

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        if not set(_MANAGE_PERMS) <= set(cached_perms(db, uid, "titulatec")):
            return Response(status_code=400,
                            headers={"X-Tt-Error": _hdr("No tienes permiso para modificar el calendario.")})
        hoy_anio = db_now().date().year
        anio = _parse_anio(form.get("anio"), hoy_anio)
        values = {"start": form.get("start") or "", "end": form.get("end") or "",
                  "description": form.get("description") or ""}
        start = _parse_iso(values["start"])
        end = _parse_iso(values["end"]) if values["end"] else start
        if start is None or end is None:
            return _repintar(request, db, uid, anio, values=values,
                             error="Indica la fecha de inicio y, si aplica, la de fin.")
        try:
            res = NonWorkingDayService.add_range(
                db, uid, start=start, end=end, description=values["description"])
        except ValueError as exc:
            # El servicio valida ANTES de escribir: no hay nada que deshacer.
            return _repintar(request, db, uid, anio, values=values, error=str(exc))
        anio = start.year if _ANIO_MIN <= start.year <= _ANIO_MAX else anio
        aviso = f"Se registraron {_plural(res['added'], 'día inhábil', 'días inhábiles')}."
        extra = []
        if res["weekend"]:
            extra.append(f"{_plural(res['weekend'], 'fin de semana', 'días de fin de semana')} omitido(s)")
        if res["existing"]:
            extra.append(f"{_plural(res['existing'], 'ya estaba registrado', 'ya estaban registrados')}")
        if extra:
            aviso = aviso[:-1] + " (" + "; ".join(extra) + ")."
        return _repintar(request, db, uid, anio, aviso=aviso,
                         kind="success" if res["added"] else "warning")
    finally:
        db.close()


@router.post("/quitar", name="titulatec.pages.dias_inhabiles.remove")
async def remove(request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    form = dict(await request.form())
    return await run_in_threadpool(_cuerpo_remove, request=request, user=user, form=form)


def _cuerpo_remove(request, user, form):
    """Cuerpo síncrono de `remove`: corre en el threadpool."""
    from itcj2.apps.titulatec.services.non_working_day_service import NonWorkingDayService
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.core.utils.timezone import db_now
    from itcj2.database import SessionLocal

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        if not set(_MANAGE_PERMS) <= set(cached_perms(db, uid, "titulatec")):
            return Response(status_code=400,
                            headers={"X-Tt-Error": _hdr("No tienes permiso para modificar el calendario.")})
        anio = _parse_anio(form.get("anio"), db_now().date().year)
        values = {"start": form.get("start") or "", "end": form.get("end") or ""}
        # «Quitar un rango» (`mode=range`) exige las DOS fechas: su confirmación
        # habla de un rango, y con «Al» vacío quitaría un solo día. La X de una
        # fila (un día suelto) no manda `mode` ni `end`: sigue siendo `end = start`.
        if form.get("mode") == "range" and not values["end"].strip():
            return _repintar(request, db, uid, anio, values={"rm_start": values["start"],
                                                             "rm_end": values["end"]},
                             error="Indica la fecha de inicio y la de fin del rango.")
        start = _parse_iso(values["start"])
        end = _parse_iso(values["end"]) if values["end"] else start
        if start is None or end is None:
            return _repintar(request, db, uid, anio, values={"rm_start": values["start"],
                                                             "rm_end": values["end"]},
                             error="Indica la fecha de inicio y, si aplica, la de fin.")
        try:
            quitados = NonWorkingDayService.remove_range(db, uid, start=start, end=end)
        except ValueError as exc:
            return _repintar(request, db, uid, anio, values={"rm_start": values["start"],
                                                             "rm_end": values["end"]},
                             error=str(exc))
        if not quitados:
            return _repintar(request, db, uid, anio,
                             aviso="No había días inhábiles en ese rango.", kind="warning")
        return _repintar(request, db, uid, anio,
                         aviso=f"Se quitaron {_plural(quitados, 'día inhábil', 'días inhábiles')}.")
    finally:
        db.close()
