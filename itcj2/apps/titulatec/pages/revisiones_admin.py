"""Pestaña «Mis revisiones»: la pantalla del docente sinodal (fase 5).

Spec `docs/superpowers/specs/2026-10-22-titulatec-fase5-revision-sinodales-design.md`
§7 (conversación), §8.2 (pantalla), §12 (alcance) y D1, D6, D7, D10, D13. La
bandeja (Por revisar / En curso / Completados) y, por proceso, la
conversación con el alumno y los otros sinodales: mensajes, adjuntos, votos y
el refresco periódico.

Reparto: todo lo que escribe o decide vive en `ReviewService` (la única puerta
de la fase 5) y la bandeja en `ReviewInboxService`. Aquí solo se arma el
contexto y se traducen los errores.

Acceso (§8.2, §12):
- La bandeja exige `synodal.page.my_reviews` (el ítem del menú). Cada ruta con
  `{process_id}` exige su permiso en el gate (leer `chat.api.read`, escribir
  `chat.api.send` -y `chat.api.upload` si trae archivo-, votar
  `synodal.api.vote`) y, en este orden: `ReviewService.assert_participant`
  como PRIMERA sentencia del `try` (asignación VIGENTE en ese proceso; si no,
  404 sin header: ni el sustituido, ni un extraño, ni un jefe, ni el alumno
  saben si el proceso existe), `_exigir_bandeja` (poder abrir la pestaña) y el
  corte (`ReviewService.operable`: con el corte a T-soft en la fase 5 o antes,
  404 en páginas, parciales y archivos; 400 en acciones).
- Los archivos se resuelven DENTRO de la conversación del proceso ya
  autorizado (`ReviewService.attachment_for`), nunca por ruta estática.

Contrato de respuesta (CLAUDE.md de la app §1): validación -> 200 con el
parcial re-pintado (en el formulario de mensaje, además `X-Tt-Review-Keep: 1`
para que `js/shared/review-thread.js` no lo limpie); guardas -> 400 +
`X-Tt-Error`; éxito -> `X-Tt-Notice`. El voto que cerraría sin `confirm` ->
200 con el panel de reconfirmación (nada escrito, D6); la versión vigente
cambió -> 200 con la conversación re-pintada y aviso.
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool

from itcj2.apps.titulatec.pages.nav import render_titulatec
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.titulatec.pages.revisiones_admin")
router = APIRouter(prefix="/admin/revisiones", tags=["titulatec-pages-revisiones"])

# Abrir la pestaña (y el ítem del menú, `nav._ADMIN_NAV`).
_VIEW_PERMS = ["titulatec.synodal.page.my_reviews"]
_READ_PERM = "titulatec.chat.api.read"
_SEND_PERM = "titulatec.chat.api.send"
_UPLOAD_PERM = "titulatec.chat.api.upload"
_VOTE_PERM = "titulatec.synodal.api.vote"

_BASE_URL = "/titulatec/admin/revisiones"
_PAGE_TPL = "titulatec/admin/revisiones.html"
_BODY_TPL = "titulatec/partials/revisiones/_body.html"
_CONV_TPL = "titulatec/partials/revisiones/_conversacion.html"
_REFRESH_TPL = "titulatec/partials/revisiones/_refresco.html"

# Pestañas en el orden de pantalla (las claves son `ReviewInboxService.TABS`).
_TABS = (("por_revisar", "Por revisar"), ("en_curso", "En curso"),
         ("completados", "Completados"))
_VACIO = "—"

# Por qué la conversación es de solo lectura (D7).
_READONLY_REVOKED = "La inscripción fue revocada: la conversación queda solo para consulta."
_READONLY_RELEASED = "Proyecto liberado: la conversación queda solo para consulta."
_READONLY_PAUSED = "El proceso está en pausa: por ahora la conversación queda solo para consulta."


def _hdr(msg: str) -> str:
    """Percent-encode para que un mensaje acentuado quepa en un header latin-1.

    Gemelo de `pages/sinodales_admin.py::_hdr`; `titulatec-utils.js::
    decodeHeaderMsg` lo deshace al mostrarlo.
    """
    from urllib.parse import quote
    return quote(msg or "", safe="")


def _to_int(raw):
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _error(msg: str) -> Response:
    """Guarda del servicio: 400 + `X-Tt-Error` (htmx no hace swap en un 4xx)."""
    return Response(status_code=400, headers={"X-Tt-Error": _hdr(msg)})


def _exigir_bandeja(db, user_id: int) -> None:
    """Las rutas de una conversación exigen poder ABRIR esta pestaña, no solo
    el permiso de la acción (patrón `sinodales_admin.py::_exigir_bandeja`). 403
    como el gate, ANTES de escribir. Va después de `assert_participant`."""
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.exceptions import PageForbidden

    if not set(_VIEW_PERMS) <= set(cached_perms(db, user_id, "titulatec")):
        raise PageForbidden(has_app_access=True)


def _operable(db) -> bool:
    """¿La fase 5 se opera en esta app? (falla cerrado; spec §14)."""
    from itcj2.apps.titulatec.services.review_service import ReviewService
    return ReviewService.operable(db)


def _nombre(user) -> str:
    """Nombre en orden natural (nombre(s), paterno, materno)."""
    if user is None:
        return ""
    return " ".join(p for p in (user.first_name, user.last_name, user.middle_name) if p)


# ===========================================================================
# Contextos
# ===========================================================================
def _body_ctx(db, *, user_id: int, tab, q, page, per_page: int | None = None) -> dict:
    """Contexto del parcial `_body.html` (y de la página completa)."""
    from itcj2.apps.titulatec.services.review_inbox_service import ReviewInboxService
    from itcj2.apps.titulatec.utils.paging import PAGE_SIZE, normalize_q

    q = normalize_q(q) or ""
    data = ReviewInboxService.list(db, user_id, tab=tab, q=q, page=page,
                                   per_page=per_page or PAGE_SIZE)
    return {"tab": data["tab"], "tabs": _TABS, "q": q, "page": data["page"],
            "rows": data["page"].items, "counts": data["counts"], "base_url": _BASE_URL}


def _state(db, proc, chat, *, user_id: int, perms) -> dict:
    """Lo que decide los paneles VIVOS de la conversación (el formulario de
    mensaje con su sondeo y el panel de voto) y el panel de estado. Dict plano:
    la sesión se cierra antes de pintar."""
    from itcj2.apps.titulatec.services.review_service import (
        CLOSED_MSG,
        CONFIRM_CLOSE_MSG,
        NO_VERSION_MSG,
        NOT_COUNTING_MSG,
        RULE_UNKNOWN_MSG,
        ReviewService,
    )
    from itcj2.apps.titulatec.services.synodal_service import ROLE_LABELS

    role = ReviewService.participant_role(db, proc.id, user_id)
    try:
        counts = role in ReviewService.counting_roles(ReviewService.rule_for(proc))
        rule_error = False
    except ValueError:
        counts, rule_error = False, True
    abierta = ReviewService.is_open(proc, chat)
    version = ReviewService.current_version(db, proc.id)
    numero = version.number if version is not None else None
    estado = ReviewService.status_for_process(db, proc.id)
    mi_voto = next((v["verdict"] for v in (estado or {}).get("votes", ())
                    if v["role"] == role), None)
    puede_votar = _VOTE_PERM in perms
    cerraria = (abierta and counts and numero is not None and puede_votar
                and ReviewService.would_close(db, proc, user_id))

    revocada = proc.status == "cancelled"
    if abierta:
        solo_lectura = None
    elif revocada:
        solo_lectura = _READONLY_REVOKED
    elif chat.closed_at is not None or (estado or {}).get("closed"):
        solo_lectura = _READONLY_RELEASED
    elif proc.status == "on_hold":
        solo_lectura = _READONLY_PAUSED
    else:
        solo_lectura = CLOSED_MSG

    url = f"{_BASE_URL}/{proc.id}"
    return {
        "process_id": proc.id,
        "me_id": int(user_id),
        "url": url,
        "file_base": f"{url}/archivo/",
        "role": role,
        "role_label": ROLE_LABELS.get(role, role or ""),
        "counts": counts,
        "rule_error": rule_error,
        "is_open": abierta,
        "readonly_msg": solo_lectura,
        "revoked": revocada,
        "version": numero,
        "my_verdict": mi_voto,
        "would_close": bool(cerraria),
        "can_send": _SEND_PERM in perms,
        "can_upload": _UPLOAD_PERM in perms,
        "can_vote": puede_votar,
        "review_status": estado,
        "confirm_msg": CONFIRM_CLOSE_MSG,
        "not_counting_msg": NOT_COUNTING_MSG,
        "no_version_msg": NO_VERSION_MSG,
        "rule_unknown_msg": RULE_UNKNOWN_MSG,
        "vote_mode": "form",
        "vote_error": None,
        "draft": "",
        "composer_error": None,
    }


def _conv_ctx(db, proc, chat, *, user_id: int, vote_mode: str = "form",
              vote_error: str | None = None, draft: str = "") -> dict:
    """La conversación completa: encabezado de D13, mensajes y paneles.

    D13: el sinodal ve SOLO nombre, número de control, carrera, modalidad,
    título del proyecto (`FormatB.project_name`, «—» si no hay) y quiénes son
    los otros sinodales con su rol. Nada más del Formato B (teléfono,
    domicilio…), del perfil (CURP…) ni de los documentos de las fases 1-3.
    """
    from itcj2.apps.titulatec.models import FormatB
    from itcj2.apps.titulatec.services.review_service import ReviewService
    from itcj2.apps.titulatec.services.synodal_service import SynodalService
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User
    from itcj2.core.services.authz_cache import cached_perms

    perms = set(cached_perms(db, user_id, "titulatec"))
    conv = _state(db, proc, chat, user_id=user_id, perms=perms)
    alumno = db.get(User, proc.student_id)
    programa = db.get(Program, proc.program_id) if proc.program_id else None
    modalidad = proc.modality
    fb = db.get(FormatB, proc.id)
    conv.update({
        "folio": proc.folio,
        "name": _nombre(alumno) or _VACIO,
        "control": (alumno.control_number if alumno else None) or _VACIO,
        "program": programa.name if programa else _VACIO,
        "modality": modalidad.name if modalidad is not None else _VACIO,
        "project": (getattr(fb, "project_name", None) or "").strip() or _VACIO,
        "others": [{"role": s["role"], "role_label": s["role_label"], "name": s["name"]}
                   for s in SynodalService.active_for_process(db, proc.id)
                   if s["user_id"] != user_id],
        # «thread», no «items»: en Jinja `conv.items` sería el método del dict.
        "thread": ReviewService.messages(db, chat.id),
        "vote_mode": vote_mode,
        "vote_error": vote_error,
        "draft": draft or "",
    })
    return conv


def _marcar_leido(db, chat_id: int, user_id: int, items) -> None:
    """Abrir la conversación o recibir mensajes con ella abierta la marca leída
    hasta el último pintado (§7.1). Va AL FINAL: `mark_read` commitea."""
    from itcj2.apps.titulatec.services.review_service import ReviewService

    if items:
        ReviewService.mark_read(db, chat_id, user_id, items[-1]["id"])


def _conv_response(request, db, proc, user_id: int, **kw):
    """Re-pinta `#tt-rev-conv` (el voto apunta ahí con `morph:outerHTML`)."""
    from itcj2.apps.titulatec.services.review_service import ReviewService

    chat = ReviewService.chat_for(db, proc)
    if chat is None:
        return Response(status_code=404)
    ctx = {"conv": _conv_ctx(db, proc, chat, user_id=user_id, **kw)}
    _marcar_leido(db, chat.id, user_id, ctx["conv"]["thread"])
    return render_titulatec(request, _CONV_TPL, ctx)


def _refresh_ctx(db, proc, chat, *, user_id: int, after) -> dict:
    """Lo nuevo de la conversación (`after` = último id que el cliente tiene).

    Con mensajes nuevos, además el panel de estado fuera de banda; con la
    conversación ya cerrada, también el formulario (sin sondeo: el refresco se
    detiene) y el panel de voto, fuera de banda (D10, §7.1).
    """
    from itcj2.apps.titulatec.services.review_service import ReviewService
    from itcj2.core.services.authz_cache import cached_perms

    items = ReviewService.messages(db, chat.id, after_id=after)
    abierta = ReviewService.is_open(proc, chat)
    conv = None
    if items or not abierta:
        conv = _state(db, proc, chat, user_id=user_id,
                      perms=set(cached_perms(db, user_id, "titulatec")))
    return {"items": items, "me_id": user_id, "conv": conv,
            "file_base": f"{_BASE_URL}/{proc.id}/archivo/",
            "oob_status": bool(conv), "oob_live": conv is not None and not abierta,
            "composer_error": None, "oob_error": False}


# ===========================================================================
# Bandeja
# ===========================================================================
@router.get("", name="titulatec.pages.revisiones.home")
def home(request: Request, tab: str = "", q: str = "", page: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    """Página completa. Los parámetros llegan como `str` (htmx los manda
    vacíos) y se parsean a mano. Con el corte en la fase 5 o antes, 404."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        if not _operable(db):
            return Response(status_code=404)
        ctx = _body_ctx(db, user_id=int(user["sub"]), tab=tab, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, _PAGE_TPL, ctx)


@router.get("/body", name="titulatec.pages.revisiones.body")
def body(request: Request, tab: str = "", q: str = "", page: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    """Parcial `#tt-rev-body`: pestañas, búsqueda y la página de la lista."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        if not _operable(db):
            return Response(status_code=404)
        ctx = _body_ctx(db, user_id=int(user["sub"]), tab=tab, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, _BODY_TPL, ctx)


# ===========================================================================
# Conversación
# ===========================================================================
@router.get("/{process_id}", name="titulatec.pages.revisiones.conversation")
def conversation(process_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=[_READ_PERM]))):
    """La conversación completa (página admin). Crea la conversación si el
    proceso ya estaba en la fase 5 sin ella (`chat_for(create=True)`, §6.2) y
    la marca leída."""
    from itcj2.apps.titulatec.services.review_service import ReviewService
    from itcj2.database import SessionLocal

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = ReviewService.assert_participant(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not _operable(db):
            return Response(status_code=404)
        chat = ReviewService.chat_for(db, proc, create=True)
        if chat is None:
            return Response(status_code=404)
        ctx = {"conv": _conv_ctx(db, proc, chat, user_id=uid)}
        _marcar_leido(db, chat.id, uid, ctx["conv"]["thread"])
    finally:
        db.close()
    return render_titulatec(request, _PAGE_TPL, ctx)


@router.get("/{process_id}/mensajes", name="titulatec.pages.revisiones.messages")
def messages(process_id: int, request: Request, after: str = "",
             user: dict = Depends(require_page_app("titulatec", perms=[_READ_PERM]))):
    """Refresco incremental (cada 15 s con la pestaña visible, D10): solo los
    mensajes posteriores a `after`; vacío si no hay nada nuevo."""
    from itcj2.apps.titulatec.services.review_service import ReviewService
    from itcj2.database import SessionLocal

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = ReviewService.assert_participant(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not _operable(db):
            return Response(status_code=404)
        chat = ReviewService.chat_for(db, proc)
        if chat is None:
            return Response(status_code=404)
        ctx = _refresh_ctx(db, proc, chat, user_id=uid, after=_to_int(after))
        _marcar_leido(db, chat.id, uid, ctx["items"])
    finally:
        db.close()
    return render_titulatec(request, _REFRESH_TPL, ctx)


def _archivo(form):
    """`(raw, nombre)` del campo `archivo`, o `(None, None)` si no viene uno.

    El form ya está leído (`request.form()` lo dejó en un archivo temporal):
    aquí, en el hilo, solo se lee. Un `<input type="file">` vacío llega como
    archivo sin nombre ni contenido: no es adjunto.
    """
    up = form.get("archivo") if form is not None else None
    if up is None or isinstance(up, str) or not hasattr(up, "file"):
        return None, None
    nombre = getattr(up, "filename", None) or ""
    up.file.seek(0)
    raw = up.file.read()
    if not nombre and not raw:
        return None, None
    return raw, nombre


@router.post("/{process_id}/mensaje", name="titulatec.pages.revisiones.message")
async def message(process_id: int, request: Request,
                  user: dict = Depends(require_page_app("titulatec", perms=[_SEND_PERM]))):
    """Mensaje del sinodal: texto (1..4000) con o sin un adjunto PDF/Word."""
    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_message, process_id=process_id, request=request, user=user, form=form)


def _cuerpo_message(process_id, request, user, form):
    """Cuerpo síncrono de `message`: corre en el threadpool, no en el event loop."""
    from itcj2.apps.titulatec.services.review_service import (
        INERT_MSG,
        MESSAGE_EMPTY_MSG,
        MESSAGE_TOO_LONG_MSG,
        ReviewService,
    )
    from itcj2.apps.titulatec.utils.review_files import ReviewFileError
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.database import SessionLocal
    from itcj2.exceptions import PageForbidden

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = ReviewService.assert_participant(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not _operable(db):
            return _error(INERT_MSG)
        raw, nombre = _archivo(form)
        if raw is not None and _UPLOAD_PERM not in cached_perms(db, uid, "titulatec"):
            raise PageForbidden(has_app_access=True)
        try:
            msg = ReviewService.post_message(db, proc, uid, body=form.get("body"),
                                             raw=raw, original_name=nombre)
        except ReviewFileError as exc:
            return _composer_error(request, str(exc))
        except ValueError as exc:
            if str(exc) in (MESSAGE_EMPTY_MSG, MESSAGE_TOO_LONG_MSG):
                return _composer_error(request, str(exc))
            return _error(str(exc))         # cerrada, fuera del corte…
        nuevo = msg.id
        chat = ReviewService.chat_for(db, proc)
        after = _to_int(form.get("after"))
        # Sin `after`, solo lo propio; con él, también lo que el cliente no
        # tenía (el sondeo pide desde el último id pintado: si solo volviera lo
        # propio, lo de otros con id menor se saltaría para siempre).
        ctx = _refresh_ctx(db, proc, chat, user_id=uid,
                           after=after if after is not None and after < nuevo else nuevo - 1)
        ctx["oob_error"] = True                 # limpia el error que hubiera
        _marcar_leido(db, chat.id, uid, ctx["items"])
        return render_titulatec(request, _REFRESH_TPL, ctx)
    finally:
        db.close()


def _composer_error(request, msg: str):
    """Validación del mensaje: 200 sin agregar nada a la lista y el error en el
    formulario (fuera de banda). `X-Tt-Review-Keep` para que el texto se quede."""
    resp = render_titulatec(request, _REFRESH_TPL, {
        "items": [], "conv": None, "oob_status": False, "oob_live": False,
        "composer_error": msg, "oob_error": True})
    resp.headers["X-Tt-Review-Keep"] = "1"
    return resp


# Errores del voto que son del FORMULARIO (200 con el panel re-pintado); los
# demás son guardas (400).
def _vote_validation_msgs():
    from itcj2.apps.titulatec.services.review_service import (
        COMMENT_REQUIRED_MSG,
        COMMENT_TOO_LONG_MSG,
        VERDICT_MSG,
    )
    return (COMMENT_REQUIRED_MSG, COMMENT_TOO_LONG_MSG, VERDICT_MSG)


@router.post("/{process_id}/voto", name="titulatec.pages.revisiones.vote")
async def vote(process_id: int, request: Request,
               user: dict = Depends(require_page_app("titulatec", perms=[_VOTE_PERM]))):
    """Voto del sinodal sobre la versión que tenía en pantalla (§6.3)."""
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_vote, process_id=process_id, request=request, user=user, form=form)


def _cuerpo_vote(process_id, request, user, form):
    """Cuerpo síncrono de `vote`: corre en el threadpool, no en el event loop."""
    from itcj2.apps.titulatec.services.review_service import (
        INERT_MSG,
        VERSION_CHANGED_MSG,
        ReviewNeedsConfirmation,
        ReviewService,
        ReviewVersionChanged,
    )
    from itcj2.database import SessionLocal

    uid = int(user["sub"])
    comentario = str(form.get("comment") or "")
    db = SessionLocal()
    try:
        proc = ReviewService.assert_participant(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not _operable(db):
            return _error(INERT_MSG)
        try:
            res = ReviewService.vote(db, proc, uid, verdict=form.get("verdict") or "",
                                     comment=comentario, seen_version=form.get("version"),
                                     confirm=form.get("confirm"))
        except ReviewNeedsConfirmation:
            # D6: este voto cerraría la revisión y no venía confirmado. Nada se
            # escribió: el panel pide la reconfirmación con lo que el sinodal tecleó.
            return _conv_response(request, db, proc, uid, vote_mode="confirm",
                                  draft=comentario)
        except ReviewVersionChanged:
            resp = _conv_response(request, db, proc, uid, draft=comentario)
            resp.headers["X-Tt-Notice"] = _hdr(VERSION_CHANGED_MSG)
            resp.headers["X-Tt-Notice-Kind"] = "warning"
            return resp
        except ValueError as exc:
            if str(exc) in _vote_validation_msgs():
                return _conv_response(request, db, proc, uid, vote_error=str(exc),
                                      draft=comentario)
            return _error(str(exc))         # no cuenta, cerrada, sin versión…
        numero = res["version"]
        if res["closed"]:
            aviso = (f"Aprobaste la versión {numero}: la revisión quedó cerrada y el "
                     "proyecto, liberado.")
        elif (form.get("verdict") or "") == "approved":
            aviso = f"Tu voto quedó registrado: aprobaste la versión {numero}."
        else:
            aviso = f"Tu voto quedó registrado: pediste cambios en la versión {numero}."
        resp = _conv_response(request, db, proc, uid)
        resp.headers["X-Tt-Notice"] = _hdr(aviso)
        resp.headers["X-Tt-Notice-Kind"] = "success"
        return resp
    finally:
        db.close()


# ===========================================================================
# Archivos
# ===========================================================================
@router.get("/{process_id}/archivo/{message_id}", name="titulatec.pages.revisiones.file")
def attachment(process_id: int, message_id: int, request: Request,
               user: dict = Depends(require_page_app("titulatec", perms=[_READ_PERM]))):
    """El archivo de un mensaje (versión del proyecto o adjunto), buscado
    DENTRO de la conversación de este proceso (§7.2, §12): PDF `inline`, Word
    `attachment`, nombre saneado y `nosniff`."""
    from itcj2.apps.titulatec.services.review_service import ReviewService
    from itcj2.database import SessionLocal

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        ReviewService.assert_participant(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not _operable(db):
            return Response(status_code=404)
        info = ReviewService.attachment_for(db, process_id, message_id)
    finally:
        db.close()
    if info is None:
        return Response(status_code=404)
    return FileResponse(
        str(info["path"]), media_type=info["mime"],
        headers={"Content-Disposition": f'{info["disposition"]}; filename="{info["download_name"]}"',
                 "X-Content-Type-Options": "nosniff"})
