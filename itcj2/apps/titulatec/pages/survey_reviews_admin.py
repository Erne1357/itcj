"""Bandeja de liberaciones de GTV para la encuesta de egresados.

Gestión Tecnológica y Vinculación (GTV, `core_departments.code = 'tech_management'`)
revisa lo que el egresado ya envió (`SurveyReview`, Tarea 2) y decide si libera
el requisito de cotejo `graduate_survey` o deja observaciones. Lo que detecta
lo atiende físicamente en su ventanilla (Residencias, Prácticas, Servicio
Social); el egresado no vuelve a tocar la encuesta desde el sistema.

Cada ruta lleva EXACTAMENTE un código en `perms=[...]`: la lista es OR
(`itcj2/dependencies.py:131`), así que un código de más abre la bandeja
entera a quien no debería.

Pestañas por estado, «En revisión» por omisión (es la cola de trabajo
pendiente). Liberar, observar y revocar vuelven a pintar la pestaña donde
estaba GTV: cada formulario de fila la manda de vuelta en `status`, `q` y
`page` (campos ocultos).

Las acciones van por `review_id`, NUNCA por `process_id`: GTV no tiene
alcance por carrera (ve todas las solicitudes), y
`tests/fastapi/titulatec/test_scope_guard.py` exige la guarda de carrera a
toda ruta con `{process_id}` en el path.

Detalle en
`docs/superpowers/specs/2026-09-15-titulatec-liberacion-gtv-design.md` §6.3.
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.survey_reviews_admin")
router = APIRouter(prefix="/admin/liberaciones", tags=["titulatec-pages-survey-reviews"])

_LIST = ["titulatec.survey_review.page.list"]
_APPROVE = ["titulatec.survey_review.api.approve"]
_REJECT = ["titulatec.survey_review.api.reject"]

_PAGE_SIZE = 50

# Pestañas, en el orden en que se pintan. `in_review` es la que ve GTV al
# entrar: es la cola de trabajo pendiente.
_TABS = (
    ("in_review", "En revisión"),
    ("rejected", "Con observaciones"),
    ("approved", "Liberadas"),
)
_TAB_KEYS = tuple(key for key, _ in _TABS)
_DEFAULT_TAB = "in_review"


def _hdr(msg: str) -> str:
    """Percent-encode para que un mensaje acentuado quepa en un header latin-1.

    Gemelo de `pages/requests_admin.py:56`; `titulatec-utils.js::decodeHeaderMsg`
    lo deshace al mostrarlo.
    """
    from urllib.parse import quote
    return quote(msg or "", safe="")


def _to_int(raw):
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _tab(raw) -> str:
    """La pestaña pedida, o «En revisión». Nunca un filtro arbitrario."""
    return raw if isinstance(raw, str) and raw in _TAB_KEYS else _DEFAULT_TAB


def _body_ctx(db, *, status, q, page):
    """Contexto del parcial. `q` en blanco (o solo espacios) se normaliza a
    `None` AQUÍ: `SurveyReviewService.list_for_inbox` trataría "   " como un
    patrón `ILIKE '%%'` de verdad (coincide con todo por casualidad, no
    porque "sin búsqueda" sea su contrato), así que el recorte vive en la
    ruta y no en el service."""
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    tab = _tab(status)
    q_clean = (q or "").strip() or None
    page = max(1, _to_int(page) or 1)

    counts = SurveyReviewService.counts_by_status(db)
    rows, has_more = SurveyReviewService.list_for_inbox(
        db, status=tab, q=q_clean, page=page, per_page=_PAGE_SIZE)

    return {
        "tabs": _TABS, "status": tab, "counts": counts, "rows": rows,
        "q": q_clean or "", "page": page, "has_more": has_more,
    }


@router.get("", name="titulatec.pages.releases.list")
async def list_releases(request: Request, status: str = "", q: str = "", page: str = "1",
                        user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, status=status, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/survey_reviews.html", ctx)


@router.get("/body", name="titulatec.pages.releases.body")
async def body(request: Request, status: str = "", q: str = "", page: str = "1",
               user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    """Hermana de la página: acepta LOS MISMOS query params."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, status=status, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/survey_reviews_body.html", ctx)


@router.post("/{review_id}/liberar", name="titulatec.pages.releases.approve")
async def approve(review_id: int, request: Request,
                  user: dict = Depends(require_page_app("titulatec", perms=_APPROVE))):
    """Liberar: válido desde «En revisión» o «Con observaciones». Acredita
    `graduate_survey` (efecto del service, no de esta ruta)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    form = await request.form()
    status, q, page = form.get("status"), form.get("q"), form.get("page")

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        try:
            SurveyReviewService.approve(db, review_id, uid)
        except LookupError:
            return Response(status_code=404)
        except ValueError as e:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(e))})
        ctx = _body_ctx(db, status=status, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/survey_reviews_body.html", ctx)


@router.post("/{review_id}/observar", name="titulatec.pages.releases.reject")
async def reject(review_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_REJECT))):
    """Observar: motivo obligatorio (lo valida el service). Válido desde «En
    revisión» o «Con observaciones» (en este segundo caso, actualiza el texto)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    form = await request.form()
    reason = form.get("reason") or ""
    status, q, page = form.get("status"), form.get("q"), form.get("page")

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        try:
            SurveyReviewService.reject(db, review_id, uid, reason)
        except LookupError:
            return Response(status_code=404)
        except ValueError as e:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(e))})
        ctx = _body_ctx(db, status=status, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/survey_reviews_body.html", ctx)


@router.post("/{review_id}/revocar", name="titulatec.pages.releases.revoke")
async def revoke(review_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_REJECT))):
    """Revocar: solo desde «Liberada» y solo si la fase 2 de ese proceso
    todavía no está aprobada (`can_revoke`, calculado por el service)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

    form = await request.form()
    reason = form.get("reason") or ""
    status, q, page = form.get("status"), form.get("q"), form.get("page")

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        try:
            SurveyReviewService.revoke(db, review_id, uid, reason)
        except LookupError:
            return Response(status_code=404)
        except ValueError as e:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(e))})
        ctx = _body_ctx(db, status=status, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/survey_reviews_body.html", ctx)
