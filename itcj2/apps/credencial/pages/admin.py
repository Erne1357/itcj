"""Panel de Servicios Escolares (/credencial/admin/): buscar alumnos, fotos oficiales y bitacora.

Dos routers con el mismo prefijo: `page_router` (paginas completas; sus errores los pinta en HTML el
handler global) y `router` (parciales HTMX, bytes y JSON: 401/403 con HTTPException respondidos en
JSON). `_page_gate`/`_api_gate` dejan pasar al admin global, que `require_page_app` no contempla.
Quien abre el panel sin permiso ve como se verifica una credencial (`render_scan_hint`).
"""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.routing import APIRoute

from itcj2.dependencies import DbSession, is_global_admin, require_page_app, require_page_login
from itcj2.exceptions import PageLoginRequired


class _JsonErrorRoute(APIRoute):
    """El handler global de main.py pinta una pagina HTML para todo HTTPException fuera de /api/.
    Aqui el JS (fetch/HTMX) necesita el JSON con el mensaje, asi que se responde en la propia ruta."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except HTTPException as e:
                return JSONResponse({"success": False, "detail": e.detail}, status_code=e.status_code,
                                    headers=e.headers)

        return handler


page_router = APIRouter(prefix="/admin", tags=["credencial-admin"])
router = APIRouter(prefix="/admin", tags=["credencial-admin"], route_class=_JsonErrorRoute)
logger = logging.getLogger(__name__)

APP = "credencial"
PERM_VIEW = "credencial.admin.page.view"
PERM_UPLOAD = "credencial.photos.api.upload"
PERM_DELETE = "credencial.photos.api.delete"
PERM_LOG = "credencial.verifications.page.list"
BATCH_MAX = 20
SEARCH_PER_PAGE = 25
LOG_PER_PAGE = 50
_NO_STORE = {"Cache-Control": "private, no-store"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _page_gate(perm: str):
    inner = require_page_app(APP, [perm])

    def dependency(request: Request, db: DbSession) -> dict:
        user = getattr(request.state, "current_user", None)
        if not user:
            raise PageLoginRequired()
        return user if is_global_admin(user) else inner(request, db)

    return dependency


def _user_perms(db, user: dict) -> set[str]:
    """Permisos del panel del usuario; el admin global los tiene todos."""
    if is_global_admin(user):
        return {PERM_VIEW, PERM_UPLOAD, PERM_DELETE, PERM_LOG}
    from itcj2.core.services.authz_cache import cached_perms
    try:
        return set(cached_perms(db, int(user["sub"]), APP))
    except HTTPException:  # app credencial ausente o inactiva
        return set()


def _from_page_script(request: Request) -> bool:
    """CSRF: un <form> o un fetch no-cors de otro sitio (todo *.tecnm.mx es same-site para la
    cookie Lax) no puede poner estas cabeceras; HTMX manda HX-Request y admin.js X-Requested-With."""
    return request.headers.get("HX-Request") == "true" or "X-Requested-With" in request.headers


def _api_gate(perm: str):
    def dependency(request: Request, db: DbSession) -> dict:
        user = getattr(request.state, "current_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Inicia sesión para continuar")
        if perm not in _user_perms(db, user):
            raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")
        if request.method not in _SAFE_METHODS and not _from_page_script(request):
            raise HTTPException(status_code=403, detail="Solicitud rechazada: recarga la página e intenta de nuevo")
        return user

    return dependency


def _student_or_404(db, user_id: int):
    from itcj2.core.models.user import User

    student = db.get(User, user_id)
    if student is None or student.control_number is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    return student


def _render(request, template, ctx):
    from itcj2.apps.credencial.pages.render import render_credencial
    return render_credencial(request, template, ctx)


@page_router.get("/", response_class=HTMLResponse)
def admin_index(request: Request, user: dict = Depends(require_page_login), db: DbSession = None):
    from itcj2.apps.credencial.pages.render import render_scan_hint
    from itcj2.apps.credencial.services.admin_service import AdminService
    from itcj2.apps.credencial.services.photo_service import MAX_UPLOAD_BYTES

    perms = _user_perms(db, user)
    if PERM_VIEW not in perms:  # p. ej. vigilancia: su tile del movil abre aqui
        return render_scan_hint(request)
    page = AdminService.search(db, "", 1, SEARCH_PER_PAGE)
    return _render(request, "credencial/admin/index.html", {
        "page": page, "q": "", "missing": False,
        "can_upload": PERM_UPLOAD in perms, "can_log": PERM_LOG in perms,
        "max_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
    })


@router.get("/buscar", response_class=HTMLResponse)
def admin_search(request: Request, q: str = "", page: int = 1, missing: str = "",
                 user: dict = Depends(_api_gate(PERM_VIEW)), db: DbSession = None):
    from itcj2.apps.credencial.services.admin_service import AdminService
    from itcj2.apps.titulatec.utils.paging import normalize_q, parse_page

    q = normalize_q(q) or ""
    result = AdminService.search(db, q, parse_page(page), SEARCH_PER_PAGE, only_missing=bool(missing))
    return _render(request, "credencial/admin/_results.html", {"page": result, "q": q, "missing": bool(missing)})


@router.get("/alumnos/{user_id}", response_class=HTMLResponse)
def admin_student(request: Request, user_id: int, user: dict = Depends(_api_gate(PERM_VIEW)), db: DbSession = None):
    from itcj2.apps.credencial.models import CredentialPhoto
    from itcj2.apps.credencial.services.card_service import CardService

    student = _student_or_404(db, user_id)
    card = CardService.build(db, user_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    perms = _user_perms(db, user)
    return _render(request, "credencial/admin/_student.html", {
        "card": card, "student": student, "photo": db.get(CredentialPhoto, user_id),
        "can_upload": PERM_UPLOAD in perms, "can_delete": PERM_DELETE in perms,
    })


@router.get("/alumnos/{user_id}/foto")
def admin_photo(user_id: int, user: dict = Depends(_api_gate(PERM_VIEW)), db: DbSession = None):
    from itcj2.apps.credencial.models import CredentialPhoto
    from itcj2.apps.credencial.services.photo_service import PHOTO_MIME, PhotoService

    photo = db.get(CredentialPhoto, user_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Sin foto oficial")
    try:
        data = PhotoService.read_bytes(photo)
    except OSError:
        raise HTTPException(status_code=404, detail="Sin foto oficial")
    return Response(data, media_type=PHOTO_MIME, headers=_NO_STORE)


@router.post("/alumnos/{user_id}/foto")
def admin_upload_photo(user_id: int, file: UploadFile = File(...),
                       user: dict = Depends(_api_gate(PERM_UPLOAD)), db: DbSession = None):
    from itcj2.apps.credencial.services.photo_service import MAX_UPLOAD_BYTES, PhotoError, PhotoService

    _student_or_404(db, user_id)
    data = file.file.read(MAX_UPLOAD_BYTES + 1)  # normalize() rechaza lo que pase del tope
    try:
        _, status = PhotoService.save(db, user_id, data, int(user["sub"]))
    except PhotoError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "data": {"status": status}}


@router.delete("/alumnos/{user_id}/foto")
def admin_delete_photo(user_id: int, user: dict = Depends(_api_gate(PERM_DELETE)), db: DbSession = None):
    from itcj2.apps.credencial.services.photo_service import PhotoService

    if not PhotoService.delete(db, user_id):
        raise HTTPException(status_code=404, detail="El alumno no tiene foto")
    return {"success": True, "message": "Foto eliminada"}


@router.post("/fotos/lote")
def admin_batch_upload(files: list[UploadFile] = File(...),
                       user: dict = Depends(_api_gate(PERM_UPLOAD)), db: DbSession = None):
    from dataclasses import asdict

    from itcj2.apps.credencial.services.photo_service import MAX_UPLOAD_BYTES, PhotoService

    if len(files) > BATCH_MAX:
        raise HTTPException(status_code=400, detail=f"Máximo {BATCH_MAX} archivos por envío")
    payload = [(f.filename or "", f.file.read(MAX_UPLOAD_BYTES + 1)) for f in files]
    rows = PhotoService.import_batch(db, payload, int(user["sub"]))
    return {"success": True, "data": [asdict(r) for r in rows]}


@page_router.get("/verificaciones", response_class=HTMLResponse)
def admin_verifications(request: Request, page: int = 1, user: dict = Depends(_page_gate(PERM_LOG)),
                        db: DbSession = None):
    from itcj2.apps.credencial.services.admin_service import AdminService
    from itcj2.apps.titulatec.utils.paging import parse_page

    result = AdminService.verifications(db, parse_page(page), LOG_PER_PAGE)
    return _render(request, "credencial/admin/verifications.html", {"page": result})
