"""Pestaña «Docentes»: catálogo de docentes por departamento académico.

Spec `docs/superpowers/specs/2026-10-21-titulatec-fase4-sinodales-design.md`
§8 y §16b (R-B con su enmienda de seguridad, R-G). La lógica vive en
`TeacherService`; aquí solo se arma el contexto, se traducen los errores y se
manda el correo de acceso DESPUÉS del commit.

Acceso: la página exige `teacher.page.list`; toda acción (y la búsqueda de
cuentas, que expone nombres y correos) exige `teacher.api.manage`. Quien actúa
solo opera los departamentos de `manageable_departments`: uno ajeno es 403. Con
el corte a T-soft en la fase de sinodales o antes (`TeacherService.operable`)
la pestaña es un estado vacío y las acciones responden 400 (R-G).

Contrato de respuestas: validación (datos del formulario, cuenta que no se
puede usar…) → 200 con el cuerpo re-pintado y el mensaje en el formulario;
guardas (corte, quitar/reenviar que el servicio rechaza) → 400 +
`X-Tt-Error`; éxito → `X-Tt-Notice`. Si el correo de acceso no sale, el alta
queda hecha y el aviso va con `X-Tt-Notice-Kind: warning`.

La contraseña temporal NUNCA llega aquí: ni al HTML, ni a headers, ni a logs.
Tampoco se registra el texto de una excepción de BD (trae parámetros SQL: hash
y correo): solo se muestra el mensaje de un `ValueError` del servicio.
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.docentes_admin")
router = APIRouter(prefix="/admin/docentes", tags=["titulatec-pages-docentes"])

_VIEW_PERMS = ["titulatec.teacher.page.list"]
_MANAGE_PERM = "titulatec.teacher.api.manage"

_BASE_URL = "/titulatec/admin/docentes"
_PAGE_TPL = "titulatec/admin/docentes.html"
_BODY_TPL = "titulatec/partials/docentes/_body.html"
_CANDIDATES_TPL = "titulatec/partials/docentes/_candidatos.html"

# Motivos de `send_access_email` -> frase para la persona que opera.
_MAIL_REASONS = {
    "inerte": "la función todavía no está operando",
    "sin_credencial_temporal": "la persona ya cambió su contraseña",
    "cuenta_con_privilegios": "la cuenta tiene otros accesos en la plataforma",
}


def _hdr(msg: str) -> str:
    """Percent-encode para que un mensaje acentuado quepa en un header latin-1
    (gemelo de `pages/titulacion_admin.py::_hdr`)."""
    from urllib.parse import quote
    return quote(msg or "", safe="")


def _to_int(raw):
    try:
        return int(str(raw).strip()) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _bloqueo(msg: str) -> Response:
    return Response(status_code=400, headers={"X-Tt-Error": _hdr(msg)})


def _resolver_depto(db, uid: int, raw):
    """(departamentos operables, el elegido). Sin `dept` (o ilegible) se elige el
    primero; uno bien formado pero ajeno es 403 ANTES de leer o escribir."""
    from itcj2.apps.titulatec.services.scope_service import manageable_departments
    from itcj2.exceptions import PageForbidden

    deptos = manageable_departments(db, uid)
    pedido = _to_int(raw)
    if pedido is None:
        return deptos, (deptos[0] if deptos else None)
    for d in deptos:
        if d["id"] == pedido:
            return deptos, d
    raise PageForbidden(has_app_access=True)


def _body_ctx(db, uid: int, dept_raw, *, q: str = "", form_error: str | None = None,
              form: dict | None = None, candidates=None, candidates_title: str | None = None,
              name_match: bool = False) -> dict:
    """Contexto del cuerpo: selector, lista, buscador y formulario de alta.

    Todo es dict plano. `candidates` (de un error del servicio) pisa la
    búsqueda; sin él y con `q`, se busca de nuevo para que tras un error de un
    candidato la lista siga a la vista.
    """
    from itcj2.apps.titulatec.services.teacher_service import TeacherService
    from itcj2.apps.titulatec.utils.paging import normalize_q
    from itcj2.core.services.authz_cache import cached_perms

    perms = cached_perms(db, uid, "titulatec")
    deptos, depto = _resolver_depto(db, uid, dept_raw)
    operable = TeacherService.operable(db)
    can_manage = _MANAGE_PERM in perms
    ctx = {
        "operable": operable, "can_manage": can_manage, "departments": deptos,
        "dept": depto, "rows": [], "q": normalize_q(q) or "", "candidates": [],
        "candidates_title": candidates_title, "form_error": form_error,
        "form": form or {}, "name_match": name_match, "searched": False,
    }
    if not (operable and depto):
        return ctx

    rows = TeacherService.roster(db, depto["id"])
    for r in rows:
        privilegiada = TeacherService.has_privileges(db, r["user_id"])
        r["privileged"] = privilegiada
        # «Reenviar acceso» solo donde el servicio lo aceptaría: cuenta activa,
        # sin privilegios y sin primer acceso.
        r["can_resend"] = (r["account_status"] == "pending_first_login"
                           and not privilegiada)
    ctx["rows"] = rows
    if candidates is not None:
        ctx["candidates"] = candidates
        ctx["searched"] = True
    elif ctx["q"]:
        ctx["candidates"] = TeacherService.search_candidates(db, ctx["q"])
        ctx["searched"] = True
    return ctx


def _candidatos_por_id(db, user_id: int) -> list[dict]:
    """El candidato `user_id` con la misma forma que la búsqueda (para volver a
    pintar su fila con el error). Se consulta por correo/usuario exacto vía el
    propio servicio: `search_candidates` no filtra por id."""
    from itcj2.apps.titulatec.services.teacher_service import TeacherService
    from itcj2.core.models.user import User

    user = db.get(User, user_id)
    if user is None:
        return []
    return [c for c in TeacherService.search_candidates(
        db, user.email or user.username or "", limit=50) if c["user_id"] == user_id]


def _exigir_depto_y_manage(db, uid: int, dept_raw):
    """Guarda de TODA acción: el permiso de gestión (los datos de cuentas son
    sensibles aunque el gate solo pida abrir la página) y el departamento
    operable. Devuelve el departamento elegido; sin ninguno, 403."""
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.exceptions import PageForbidden

    if _MANAGE_PERM not in cached_perms(db, uid, "titulatec"):
        raise PageForbidden(has_app_access=True)
    _deptos, depto = _resolver_depto(db, uid, dept_raw)
    # Una acción exige un departamento EXPLÍCITO y operable: sin él no hay a
    # quién cargarle el cambio.
    if depto is None or _to_int(dept_raw) is None:
        raise PageForbidden(has_app_access=True)
    return depto


def _repintar(request, db, uid: int, dept_raw, aviso: str, *, kind: str = "success"):
    ctx = _body_ctx(db, uid, dept_raw)
    resp = render_titulatec(request, _BODY_TPL, ctx)
    resp.headers["X-Tt-Notice"] = _hdr(aviso)
    resp.headers["X-Tt-Notice-Kind"] = kind
    return resp


def _aviso_correo(user_id: int, *, hecho: str, enviar: bool = True) -> tuple[str, str]:
    """(aviso, tipo) tras una acción que pudo requerir el correo de acceso. Se
    llama DESPUÉS del commit; si el correo falla la acción ya está hecha."""
    from itcj2.apps.titulatec.services.teacher_service import TeacherService

    if not enviar:
        return hecho, "success"
    ok, motivo = TeacherService.send_access_email(user_id)
    if ok:
        return f"{hecho} Se envió su acceso por correo.", "success"
    razon = _MAIL_REASONS.get(motivo or "", "el correo no salió")
    return (f"{hecho} No se pudo enviar el correo de acceso ({razon}): "
            "usa «Reenviar acceso» cuando se resuelva."), "warning"


# ===========================================================================
# Página y cuerpo
# ===========================================================================
@router.get("", name="titulatec.pages.docentes.home")
def home(request: Request, dept: str = "", q: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    """Página completa (los parámetros llegan como `str` y se parsean a mano)."""
    from itcj2.database import SessionLocal

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, uid, dept, q=q)
    finally:
        db.close()
    return render_titulatec(request, _PAGE_TPL, ctx)


@router.get("/body", name="titulatec.pages.docentes.body")
def body(request: Request, dept: str = "", q: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    """Solo el cuerpo (cambio de departamento)."""
    from itcj2.database import SessionLocal

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, uid, dept, q=q)
    finally:
        db.close()
    return render_titulatec(request, _BODY_TPL, ctx)


@router.get("/buscar", name="titulatec.pages.docentes.search")
def search(request: Request, dept: str = "", q: str = "",
           user: dict = Depends(require_page_app("titulatec", perms=[_MANAGE_PERM]))):
    """Candidatos para «Agregar docente»: solo la lista (parcial)."""
    from itcj2.database import SessionLocal

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        _exigir_depto_y_manage(db, uid, dept)
        ctx = _body_ctx(db, uid, dept, q=q)
    finally:
        db.close()
    return render_titulatec(request, _CANDIDATES_TPL, ctx)


# ===========================================================================
# Acciones
# ===========================================================================
@router.post("/agregar", name="titulatec.pages.docentes.add")
async def add(request: Request,
              user: dict = Depends(require_page_app("titulatec", perms=[_MANAGE_PERM]))):
    """Hace docente a una cuenta que ya existe (R-B)."""
    form = dict(await request.form())
    return await run_in_threadpool(_cuerpo_add, request=request, user=user, form=form)


def _cuerpo_add(request, user, form):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.teacher_service import (
        INERT_MSG, TeacherService,
    )

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        depto = _exigir_depto_y_manage(db, uid, form.get("dept"))
        if not TeacherService.operable(db):
            return _bloqueo(INERT_MSG)
        target = _to_int(form.get("user_id"))
        try:
            if target is None:
                raise ValueError("Elige a la persona que vas a agregar.")
            resultado = TeacherService.add_existing(
                db, uid, depto["id"], target,
                academic_degree=form.get("academic_degree"),
                professional_license=form.get("professional_license"),
                institutional_email=form.get("institutional_email") or None)
        except ValueError as exc:
            # Validación: 200 con el cuerpo y el mensaje en la fila de la cuenta.
            cands = _candidatos_por_id(db, target) if target else []
            ctx = _body_ctx(db, uid, form.get("dept"), q=form.get("q") or "",
                            form_error=str(exc), candidates=cands or None,
                            form={"target_id": target})
            return render_titulatec(request, _BODY_TPL, ctx)
        aviso, kind = _aviso_correo(resultado["user_id"], hecho="Docente agregado.",
                                    enviar=resultado["access_email_needed"])
        return _repintar(request, db, uid, form.get("dept"), aviso, kind=kind)
    finally:
        db.close()


@router.post("/crear", name="titulatec.pages.docentes.create")
async def create(request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=[_MANAGE_PERM]))):
    """Crea la cuenta de un docente que no existe y lo agrega (R-B)."""
    form = dict(await request.form())
    return await run_in_threadpool(_cuerpo_create, request=request, user=user, form=form)


_CREATE_FIELDS = ("first_name", "last_name", "middle_name", "email",
                  "academic_degree", "professional_license")


def _cuerpo_create(request, user, form):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.teacher_service import (
        INERT_MSG, EmailTakenError, NameMatchError, TeacherService,
    )

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        depto = _exigir_depto_y_manage(db, uid, form.get("dept"))
        if not TeacherService.operable(db):
            return _bloqueo(INERT_MSG)
        valores = {k: form.get(k) or "" for k in _CREATE_FIELDS}
        confirmado = bool(form.get("confirm_other_person"))
        valores["confirm_other_person"] = confirmado
        try:
            resultado = TeacherService.create_and_add(
                db, uid, depto["id"], confirm_other_person=confirmado,
                first_name=valores["first_name"], last_name=valores["last_name"],
                middle_name=valores["middle_name"] or None, email=valores["email"],
                academic_degree=valores["academic_degree"],
                professional_license=valores["professional_license"])
        except (EmailTakenError, NameMatchError) as exc:
            # Cuentas que ya existen: se muestran para reutilizarlas. Si solo
            # coincide el nombre, el formulario pide «Es otra persona».
            ctx = _body_ctx(db, uid, form.get("dept"), form_error=str(exc), form=valores,
                            candidates=list(exc.candidates),
                            candidates_title=("Ya existe una cuenta con ese correo"
                                              if isinstance(exc, EmailTakenError)
                                              else "Cuentas con ese nombre"),
                            name_match=isinstance(exc, NameMatchError))
            return render_titulatec(request, _BODY_TPL, ctx)
        except ValueError as exc:
            ctx = _body_ctx(db, uid, form.get("dept"), form_error=str(exc), form=valores)
            return render_titulatec(request, _BODY_TPL, ctx)
        aviso, kind = _aviso_correo(resultado["user_id"], hecho="Docente creado.")
        return _repintar(request, db, uid, form.get("dept"), aviso, kind=kind)
    finally:
        db.close()


@router.post("/editar", name="titulatec.pages.docentes.edit")
async def edit(request: Request,
               user: dict = Depends(require_page_app("titulatec", perms=[_MANAGE_PERM]))):
    """Corrige grado y cédula del perfil (único para todos sus departamentos)."""
    form = dict(await request.form())
    return await run_in_threadpool(_cuerpo_edit, request=request, user=user, form=form)


def _cuerpo_edit(request, user, form):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.teacher_service import INERT_MSG, TeacherService

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        depto = _exigir_depto_y_manage(db, uid, form.get("dept"))
        if not TeacherService.operable(db):
            return _bloqueo(INERT_MSG)
        target = _to_int(form.get("user_id"))
        try:
            if target is None:
                raise ValueError("Elige a la persona que vas a editar.")
            TeacherService.update_profile(
                db, uid, depto["id"], target,
                academic_degree=form.get("academic_degree"),
                professional_license=form.get("professional_license"))
        except ValueError as exc:
            ctx = _body_ctx(db, uid, form.get("dept"), form_error=str(exc),
                            form={"target_id": target, "edit": True})
            return render_titulatec(request, _BODY_TPL, ctx)
        return _repintar(request, db, uid, form.get("dept"), "Perfil actualizado.")
    finally:
        db.close()


@router.post("/quitar", name="titulatec.pages.docentes.remove")
async def remove(request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=[_MANAGE_PERM]))):
    """Termina el puesto de docente en el departamento (nunca borra la cuenta)."""
    form = dict(await request.form())
    return await run_in_threadpool(_cuerpo_remove, request=request, user=user, form=form)


def _cuerpo_remove(request, user, form):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.teacher_service import INERT_MSG, TeacherService

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        depto = _exigir_depto_y_manage(db, uid, form.get("dept"))
        if not TeacherService.operable(db):
            return _bloqueo(INERT_MSG)
        target = _to_int(form.get("user_id"))
        if target is None:
            return _bloqueo("Elige a la persona que vas a quitar.")
        try:
            TeacherService.remove_from_department(db, uid, depto["id"], target)
        except ValueError as exc:
            # Asignaciones vigentes, ya no es docente…: guarda, no formulario.
            return _bloqueo(str(exc))
        return _repintar(request, db, uid, form.get("dept"),
                         "Se quitó del departamento. Su cuenta sigue activa.")
    finally:
        db.close()


@router.post("/reenviar", name="titulatec.pages.docentes.resend")
async def resend(request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=[_MANAGE_PERM]))):
    """Restablece la contraseña temporal y reenvía el acceso (solo a quien nunca
    ha entrado y no tiene otros accesos)."""
    form = dict(await request.form())
    return await run_in_threadpool(_cuerpo_resend, request=request, user=user, form=form)


def _cuerpo_resend(request, user, form):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.teacher_service import INERT_MSG, TeacherService

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        depto = _exigir_depto_y_manage(db, uid, form.get("dept"))
        if not TeacherService.operable(db):
            return _bloqueo(INERT_MSG)
        target = _to_int(form.get("user_id"))
        if target is None:
            return _bloqueo("Elige a la persona a la que reenviarás el acceso.")
        try:
            TeacherService.reset_access(db, uid, depto["id"], target)
        except ValueError as exc:
            return _bloqueo(str(exc))
        aviso, kind = _aviso_correo(target, hecho="Acceso restablecido.")
        return _repintar(request, db, uid, form.get("dept"), aviso, kind=kind)
    finally:
        db.close()
