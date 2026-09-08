"""Rutas PUBLICAS de TitulaTec — sin sesión obligatoria y sin permisos.

Este es el único módulo de la app sin `require_page_app` (los otros 67 usos lo
llevan). En este repo una ruta es pública **por omitir la dependencia**: no hay
allowlist, ni decorador, ni prefijo exento — `JWTMiddleware`
(`itcj2/middleware.py`) corre en todas las peticiones y nunca rechaza, solo fija
`request.state.current_user`. El único precedente es `GET /itcj/login`
(`itcj2/core/pages/auth.py:18-35`), y de ahí sale el patrón
`Depends(get_current_user_optional)`.

Regla de códigos de respuesta (spec §6.1): *cualquier resultado que el visitante
deba VER y ACTUAR devuelve 200*, porque htmx no hace swap en 4xx. El
`400 + X-Tt-Error` queda para el único estado sin formulario que renderizar, y
el `413` para el cuerpo que se rechaza antes de leerlo.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from itcj2.apps.titulatec.pages.nav import render_titulatec
from itcj2.dependencies import get_current_user_optional

logger = logging.getLogger("itcj2.apps.titulatec.pages.public")

router = APIRouter(tags=["titulatec-pages-public"])

SURVEY_URL = "/titulatec/encuesta-egresados"
SURVEY_DRAFT_URL = f"{SURVEY_URL}/borrador"
SURVEY_RL_LIMIT = 10        # spec §8.1: survey:ip:{ip} -> 10 / hora
SURVEY_RL_WINDOW = 3600

# Llave que `SurveyService.submit` usa para el error que NO cuelga de ningún
# campo (la respuesta entera excede la cota de la columna JSON). Si el
# formulario solo supiera pintar errores en línea, ese mensaje sería invisible.
FORM_ERROR_KEY = "__form__"


def _hdr(msg: str) -> str:
    """Percent-codifica un mensaje para que quepa en un header HTTP.

    Gemelo del de `pages/admin.py` y `pages/appointments.py`. Los valores de
    header son latin-1 por especificación: un mensaje con acentos —o sea, todos
    los nuestros— llega como bytes que no son UTF-8 válidos y revienta al
    decodificarlos. `TitulaTecUtils.decodeHeaderMsg` lo deshace en el cliente, y
    es lo que hace `js/shared/tt-errors.js` en toda página pública.
    """
    return quote(msg or "", safe="")


def _submitted_from_form(schema: dict, data) -> dict:
    """`FormData` -> dict apto para el validador. Puente OBLIGATORIO.

    Delega en `SurveyService.form_to_dict` y no reimplementa nada: quien sabe
    qué llaves son `multiselect` es el `schema`, y ese módulo ya lo interpreta
    (`submit` construye el mismo índice para mapear tipo → columna). Dos copias
    de esta lectura es todo lo que hace falta para que una se olvide y vuelva el
    fallo silencioso que motivó el puente.

    El fallo, medido en el contenedor: `FormData` NO colapsa las llaves
    repetidas. Para `[("idiomas","en"),("idiomas","fr")]`, tanto `.get()` como
    `dict()` devuelven **solo `'fr'`**. Un escalar donde el validador espera
    lista hace fallar TODO `multiselect` con «se esperaba una lista de opciones»
    —o «selecciona al menos una opción» si es obligatorio—, señalando un campo
    que el visitante llenó bien.

    La función conserva su nombre porque es lo que consume la Tarea 13.
    """
    from itcj2.apps.titulatec.services.survey_service import form_to_dict
    return form_to_dict(schema, data)


def _display_values(schema: dict, values: dict) -> dict:
    """Normaliza los valores para PINTARLOS, sin tocar los que se validan.

    Al formulario le llegan de dos sitios y en dos formas distintas: el borrador
    de BD trae lo que guardó la Tarea 13 (texto crudo del navegador) y el
    re-render de un envío fallido trae lo que se acaba de recibir. En los dos
    casos un `yesno` viaja como `"si"`, un `scale` como `"4"` y un `multiselect`
    como lista de cadenas, mientras que un borrador viejo podría traer ya el
    booleano o el entero.

    Sin este puente, la comparación de la plantilla falla para UNA de las dos
    formas y el control vuelve en blanco: el visitante corrige un campo y
    descubre que se le borraron otros tres. Se normaliza solo la vista; lo que
    se manda a `submit` sigue siendo el crudo, que es lo que el validador sabe
    interpretar.
    """
    # Se importa el `_as_bool` del validador a propósito, en vez de copiar sus
    # listas de palabras: si divergieran, el servidor aceptaría un `"on"` que la
    # casilla luego pinta desmarcada.
    from itcj2.apps.titulatec.utils.survey_validator import _as_bool

    out: dict = {}
    for field in ((schema or {}).get("fields") or []):
        if not isinstance(field, dict):
            continue
        key = field.get("key")
        if not key or key not in (values or {}):
            continue
        raw = values[key]
        ftype = field.get("type")

        if ftype == "multiselect":
            out[key] = [str(v) for v in raw] if isinstance(raw, list) else [str(raw)]
        elif ftype in ("checkbox", "yesno"):
            out[key] = _as_bool(raw)
        elif ftype == "scale":
            out[key] = "" if raw is None else str(raw)
        else:
            out[key] = "" if raw is None else str(raw)
    return out


def _sections(schema: dict) -> list[dict]:
    """Agrupa los campos por sección conservando el orden del `schema`.

    Las secciones solo AGRUPAN visualmente y marcan los puntos de flush del
    borrador: la encuesta es UNA página, no un asistente por pasos (§4.1). Un
    campo sin `section` (o con una que no existe) cae en un grupo suelto al
    final en vez de desaparecer del formulario — perder una pregunta por una
    llave mal escrita en el seeder sería invisible hasta el export.
    """
    declaradas = (schema or {}).get("sections") or []
    grupos = [{"key": s.get("key"), "title": s.get("title") or "", "fields": []}
              for s in declaradas if isinstance(s, dict)]
    indice = {g["key"]: g for g in grupos}
    sueltos = {"key": "_", "title": "", "fields": []}
    for field in ((schema or {}).get("fields") or []):
        if not isinstance(field, dict) or not field.get("key"):
            continue
        (indice.get(field.get("section")) or sueltos)["fields"].append(field)
    if sueltos["fields"]:
        grupos.append(sueltos)
    return [g for g in grupos if g["fields"]]


def _form_ctx(form, *, values, errors, is_authenticated, draft_updated_at=""):
    """Contexto del parcial re-renderizable. Idéntico en el GET y en el POST fallido.

    **Nada de esto es un objeto ORM, y es deliberado.** La ruta cierra su sesión
    en el `finally`; un `SurveyForm` en el contexto se renderiza después de eso y
    revienta con `DetachedInstanceError` en producción. En los tests no: el
    `_TestSession` del arnés tiene un `close()` que no hace nada, así que ese
    fallo es INVISIBLE bajo pytest. Por eso se aplana aquí, con la sesión viva.
    """
    schema = form.schema or {}
    orden = [f.get("key") for f in (schema.get("fields") or []) if isinstance(f, dict)]
    return {
        "form": {"id": form.id, "code": form.code, "title": form.title,
                 "description": form.description, "version": form.version},
        "sections": _sections(schema),
        "values": _display_values(schema, values or {}),
        "errors": errors or {},
        "form_error": (errors or {}).get(FORM_ERROR_KEY),
        "first_error_key": next((k for k in orden if k in (errors or {})), None),
        "is_authenticated": is_authenticated,
        "draft_url": SURVEY_DRAFT_URL,
        "draft_updated_at": draft_updated_at,
        "survey_url": SURVEY_URL,
        "login_url": f"/itcj/login?next={SURVEY_URL}",
    }


_CLOSED_CARD = {
    "notice_key": "closed",
    "notice_icon": "clipboard-x",
    "notice_class": "tt-card--accent",
    "notice_title": "La encuesta no está abierta",
    "notice_body": ("En este momento no hay una encuesta de egresados publicada. "
                    "Vuelve a intentarlo más tarde."),
}

_RATE_LIMITED_CARD = {
    "notice_key": "rate_limited",
    "notice_icon": "hourglass-split",
    "notice_class": "tt-card--accent",
    "notice_title": "Demasiados envíos",
    "notice_body": ("Recibimos varios envíos desde tu conexión. "
                    "Espera unos minutos e inténtalo de nuevo."),
}


@router.get("/encuesta-egresados", name="titulatec.pages.public.survey",
            response_model=None)
async def survey(
    request: Request,
    user: dict | None = Depends(get_current_user_optional),
):
    """Encuesta de egresados: UNA página con secciones, nunca un asistente.

    Anónimo: banner persistente de §6.1 y borrador solo en `localStorage`.
    Con sesión: aviso de que sí acredita y precarga del borrador de BD.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.survey_service import SURVEY_CODE, SurveyService

    db = SessionLocal()
    try:
        form = SurveyService.open_form(db, SURVEY_CODE)
        if form is None:
            ctx = dict(_CLOSED_CARD, no_form=True)
        else:
            values: dict = {}
            draft_updated = ""
            if user:
                # El borrador va por (form_id, user_id). Con solo `form_id`, el
                # de quien contestó primero se le pintaría a toda la generación.
                draft = SurveyService.get_draft(db, form.id, int(user["sub"]))
                if draft:
                    values = dict(draft.answers or {})
                    draft_updated = (draft.updated_at.isoformat()
                                     if draft.updated_at else "")
            ctx = _form_ctx(form, values=values, errors={},
                            is_authenticated=bool(user),
                            draft_updated_at=draft_updated)
            ctx["no_form"] = False
    finally:
        db.close()
    return render_titulatec(request, "titulatec/public/survey.html", ctx)


@router.post("/encuesta-egresados", name="titulatec.pages.public.survey_submit",
             response_model=None)
async def survey_submit(
    request: Request,
    user: dict | None = Depends(get_current_user_optional),
):
    """Envío de la encuesta. Orden: tope → trampa → límite → formulario → validación."""
    from itcj2.database import SessionLocal
    from itcj2.core.utils.client_ip import client_ip
    from itcj2.core.utils.rate_limit import check_and_count
    from itcj2.apps.titulatec.services.survey_service import (
        MAX_PUBLIC_BODY_BYTES, SURVEY_CODE, SurveyService,
    )

    # 1) Tope de tamaño ANTES de `request.form()`: esa llamada bufferea el cuerpo
    #    ENTERO en memoria, así que rechazar después ya pagó el coste que el tope
    #    existe para evitar.
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > MAX_PUBLIC_BODY_BYTES:
        return Response(status_code=413, headers={
            "X-Tt-Error": _hdr("Tu respuesta es demasiado grande. Acórtala e "
                               "inténtalo de nuevo.")})

    data = await request.form()
    ip = client_ip(request)   # obligatorio: nunca `request.client.host`, que
                              # detrás de nginx es nginx y mete a todo internet
                              # en un solo cubo.

    # 2) Trampa (E3). Un bot que la llena recibe la MISMA tarjeta de éxito y no
    #    se escribe nada: sin respuesta distinta, no hay señal que optimizar.
    if str(data.get("website") or "").strip():
        logger.info("survey: trampa llena desde %s", ip)
        return render_titulatec(
            request, "titulatec/public/partials/survey_thanks.html",
            {"credit_status": "anonymous"})

    # 3) Límite por IP. `fail_open=False` (E2): en una escritura anónima, una
    #    caída de Redis elimina el ÚNICO control que hay, así que se niega.
    permitido, retry_after = check_and_count(
        "survey", f"ip:{ip}",
        limit=SURVEY_RL_LIMIT, window=SURVEY_RL_WINDOW, fail_open=False,
    )
    if not permitido:
        logger.info("survey: limite por IP alcanzado (%s)", ip)
        resp = render_titulatec(
            request, "titulatec/public/partials/notice_card.html",
            dict(_RATE_LIMITED_CARD))
        resp.headers["Retry-After"] = str(max(1, int(retry_after)))
        return resp

    db = SessionLocal()
    try:
        form = SurveyService.open_form(db, SURVEY_CODE)
        if form is None:
            # Único 400 público: no hay formulario que re-renderizar (§6.1).
            return Response(status_code=400, headers={
                "X-Tt-Error": _hdr("La encuesta ya no está disponible. "
                                   "Recarga la página.")})

        submitted = _submitted_from_form(form.schema, data)
        _resp, errors, credit_status = SurveyService.submit(
            db, form, submitted,
            user_id=int(user["sub"]) if user else None,
            client_ip=ip,
            user_agent=request.headers.get("user-agent"),
        )
        if errors:
            # 200, no 400: htmx no swappea en 4xx, así que un 400 dejaría la
            # pantalla intacta y el visitante no vería NADA al pulsar Enviar.
            # Conservar lo capturado es responsabilidad del servidor.
            ctx = _form_ctx(form, values=submitted, errors=errors,
                            is_authenticated=bool(user))
            plantilla = "titulatec/public/partials/survey_form.html"
        else:
            ctx = {"credit_status": credit_status}
            plantilla = "titulatec/public/partials/survey_thanks.html"
    finally:
        db.close()
    return render_titulatec(request, plantilla, ctx)
