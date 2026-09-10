"""Rutas PUBLICAS de TitulaTec — sin sesión obligatoria y sin permisos.

Este es el único módulo de la app sin `require_page_app` (los otros 67 usos lo
llevan). En este repo una ruta es pública **por omitir la dependencia**: no hay
allowlist, ni decorador, ni prefijo exento — `JWTMiddleware`
(`itcj2/middleware.py`) corre en todas las peticiones y nunca rechaza, solo fija
`request.state.current_user`. El único precedente es `GET /itcj/login`
(`itcj2/core/pages/auth.py:18-35`), y de ahí sale el patrón
`Depends(get_current_user_optional)`.

Regla de códigos de respuesta (spec §6.1): *cualquier resultado que el visitante
deba VER y ACTUAR devuelve 200*, porque htmx no hace swap en 4xx. Las
excepciones son las tres que el visitante no puede corregir escribiendo: el
`411` sin `Content-Length`, el `413` del cuerpo demasiado grande y el `400`
cuando no hay formulario que re-renderizar.

**Ninguna entrada del visitante puede producir un 500.** Es una ruta anónima:
un stack trace en los logs por un carácter pegado desde Word no es un incidente
de seguridad, pero sí pierde el cuestionario entero —htmx tampoco swappea en
5xx— y deja al egresado sin nada que recuperar. De ahí las dos capas de §2 y el
`except` alrededor de la escritura.
"""
from __future__ import annotations

import json
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

# — Presupuestos del limitador (revisión 2026-09-08) —
#
# El spec §8.1 decía `survey:ip:{ip}` a 10/hora y punto. Se sube y se parte en
# dos cubos porque el ITCJ entero sale a internet por UNA dirección pública: con
# un solo cubo por IP, la primera decena de egresados que contesta desde el wifi
# del campus deja sin encuesta a toda la generación durante una hora. Y la
# encuesta es requisito de titulación, así que eso no es una defensa, es una
# caída.
#
#  · Anónimo -> `ip:{ip}`, 60/hora. Sesenta cuestionarios COMPLETOS Y VÁLIDOS
#    por hora desde una dirección siguen frenando la automatización (ver
#    `_contar_envio`: solo cuenta lo que se escribió), y dejan sitio de sobra a
#    una sala de cómputo entera.
#  · Con sesión -> `user:{sub}`, 30/hora. Quien inició sesión está identificado
#    y es atribuible: no tiene por qué compartir cubo con medio instituto. Un
#    alumno envía la encuesta una vez, dos si se equivoca.
SURVEY_RL_LIMIT_IP = 60
SURVEY_RL_LIMIT_USER = 30
SURVEY_RL_WINDOW = 3600

# Llave que `SurveyService.submit` usa para el error que NO cuelga de ningún
# campo (la respuesta entera excede la cota de la columna JSON). Si el
# formulario solo supiera pintar errores en línea, ese mensaje sería invisible.
FORM_ERROR_KEY = "__form__"

_ERROR_ESCRITURA = ("No pudimos guardar tu respuesta. Revisa que el texto no "
                    "traiga caracteres extraños (por ejemplo, si lo pegaste "
                    "desde otro programa) e inténtalo de nuevo.")


def _hdr(msg: str) -> str:
    """Percent-codifica un mensaje para que quepa en un header HTTP.

    Gemelo del de `pages/admin.py` y `pages/appointments.py`. Los valores de
    header son latin-1 por especificación: un mensaje con acentos —o sea, todos
    los nuestros— llega como bytes que no son UTF-8 válidos y revienta al
    decodificarlos. `TitulaTecUtils.decodeHeaderMsg` lo deshace en el cliente, y
    es lo que hace `js/shared/tt-errors.js` en toda página pública.
    """
    return quote(msg or "", safe="")


# ---------------------------------------------------------------------------
# 1. Frontera de entrada: tamaño declarado
# ---------------------------------------------------------------------------
def _declared_body_size(headers) -> int | None:
    """Bytes que el cliente DECLARA en `Content-Length`, o `None` si no valen.

    Devuelve `None` en los tres casos que no son un tamaño: cabecera ausente
    (cuerpo `chunked`), texto que no es un entero (`"1e9"`) y número negativo
    (`"-1"`).

    `.isdigit()` NO servía como validación, y fallaba del lado peligroso: es
    `False` tanto para `"1e9"` como para `"-1"`, así que la guarda anterior
    —`if declarado and declarado.isdigit() and int(declarado) > TOPE`— se
    saltaba entera y el cuerpo se leía **sin tope ninguno**. Se convierte con
    `int()` y se comprueba el signo.

    Un `None` se responde con **411**, no dejándolo pasar: sin `Content-Length`
    el tope de tamaño no puede aplicarse ANTES de `request.form()`, que es el
    único momento en que sirve. Hoy nginx re-enmarca todo cuerpo con su
    `Content-Length` y el 8001 no está publicado en ningún compose, así que el
    411 no lo ve nadie por accidente; existe para que la defensa no dependa de
    esa topología.
    """
    crudo = headers.get("content-length")
    if crudo is None:
        return None
    try:
        tamano = int(str(crudo).strip())
    except (TypeError, ValueError):
        return None
    return tamano if tamano >= 0 else None


# ---------------------------------------------------------------------------
# 2. Frontera de tipos: del cable al validador
# ---------------------------------------------------------------------------
def _valor_de_cable(value):
    """Valor de formulario apto para el validador, o `None` si hay que tirarlo.

    Dos cosas, y las dos nacieron de un fallo real:

    1. **Se quitan los NUL (`U+0000`).** Postgres los prohíbe en `text` y en
       `json`, así que un `\\x00` pegado desde otro programa —invisible en
       pantalla, y perfectamente válido en un cuerpo urlencoded— llegaba intacto
       hasta `db.commit()` y salía como `ValueError: A string literal cannot
       contain NUL (0x00) characters`, o sea un **500** para el visitante. Se
       limpian en vez de rechazarse porque un NUL nunca es una respuesta: pedirle
       al egresado que «quite el carácter invisible» es pedirle lo imposible.
    2. **Se descarta lo que no es un escalar del cable.** Un cuerpo multipart
       puede mandar cualquier campo como PARTE DE ARCHIVO, y entonces
       `request.form()` devuelve un `UploadFile`. `_validate_text` hace
       `str(value)`, así que eso aterrizaba en la BD como
       `"UploadFile(filename='evil.txt', size=100, headers=...)"`. Tirarlo deja
       la llave ausente, que es lo correcto: si el campo era obligatorio el
       validador lo marca en línea, y si era opcional no había nada que guardar.

    Se dejan pasar `bool`/`int`/`float` porque `form_to_dict` admite también un
    dict plano ya tipado (su rama sin `getlist`); de un `FormData` real solo
    llegan cadenas y `UploadFile`.
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, (bool, int, float)):
        return value
    return None


def _submitted_from_form(schema: dict, data) -> dict:
    """`FormData` -> dict apto para el validador. Puente OBLIGATORIO.

    Delega el reparto de llaves en `SurveyService.form_to_dict` y no reimplementa
    nada: quien sabe qué llaves son `multiselect` es el `schema`, y ese módulo ya
    lo interpreta (`submit` construye el mismo índice para mapear tipo →
    columna). Dos copias de esa lectura es todo lo que hace falta para que una se
    olvide y vuelva el fallo silencioso que motivó el puente.

    El fallo, medido en el contenedor: `FormData` NO colapsa las llaves
    repetidas. Para `[("idiomas","en"),("idiomas","fr")]`, tanto `.get()` como
    `dict()` devuelven **solo `'fr'`**. Un escalar donde el validador espera
    lista hace fallar TODO `multiselect` con «se esperaba una lista de opciones»
    —o «selecciona al menos una opción» si es obligatorio—, señalando un campo
    que el visitante llenó bien.

    Encima de eso, aquí va la frontera de tipos: ver `_valor_de_cable`.

    La función conserva su nombre porque es lo que consume la Tarea 13.
    """
    from itcj2.apps.titulatec.services.survey_service import form_to_dict

    limpio: dict = {}
    for key, value in (form_to_dict(schema, data) or {}).items():
        if isinstance(value, list):
            depurados = [_valor_de_cable(v) for v in value]
            limpio[key] = [v for v in depurados if v is not None]
        else:
            valor = _valor_de_cable(value)
            if valor is not None:
                limpio[key] = valor
    return limpio


def _trampa_llena(data) -> bool:
    """True solo si la trampa trae TEXTO escrito.

    El `isinstance` no es defensivo de adorno. Un `UploadFile` es un objeto
    verdadero, así que `str(data.get("website") or "").strip()` era no vacío
    para una parte de archivo **vacía** llamada `website`: un cuerpo multipart
    perfectamente legítimo hacía que la respuesta de un egresado se tirara a la
    basura mostrándole una tarjeta de éxito. Silencioso por diseño —esa es la
    gracia de la trampa— y por tanto invisible para todo el mundo.
    """
    valor = data.get("website")
    return isinstance(valor, str) and bool(valor.strip())


# ---------------------------------------------------------------------------
# 3. Vista: normalización para PINTAR
# ---------------------------------------------------------------------------
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


def _form_meta(form) -> dict:
    """Instantánea PLANA del formulario, tomada con la sesión viva.

    Nada de lo que llega a la plantilla es un objeto ORM, y es deliberado por
    partida doble: la ruta cierra su sesión en el `finally` (un `SurveyForm` en
    el contexto se renderiza DESPUÉS y revienta con `DetachedInstanceError` en
    producción), y el camino de recuperación de un fallo de escritura hace
    `rollback()`, que expira todas las instancias. En los tests ninguno de los
    dos se nota: el `_TestSession` del arnés tiene un `close()` que no hace nada.
    """
    return {"id": form.id, "code": form.code, "title": form.title,
            "description": form.description, "version": form.version}


def _form_ctx(meta: dict, schema: dict, *, values, errors, is_authenticated,
              draft_updated_at="", notice=None):
    """Contexto del parcial re-renderizable. Idéntico en el GET y en el POST fallido."""
    orden = [f.get("key") for f in ((schema or {}).get("fields") or [])
             if isinstance(f, dict)]
    ctx = {
        "form": meta,
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
        "no_form": False,
    }
    if notice:
        # El aviso se pinta DENTRO del formulario a propósito (ver la plantilla):
        # así desaparece solo en el siguiente render en vez de quedarse colgado.
        ctx.update(notice)
    return ctx


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
    "notice_body": ("Recibimos varios envíos desde tu conexión en poco tiempo. "
                    "Espera unos minutos e inténtalo otra vez: lo que escribiste "
                    "sigue aquí."),
}


# ---------------------------------------------------------------------------
# 4. Limitador
# ---------------------------------------------------------------------------
def _rate_bucket(user, ip) -> tuple[str, int]:
    """Cubo y presupuesto que le tocan a este visitante. Ver las constantes."""
    if user:
        return f"user:{user.get('sub')}", SURVEY_RL_LIMIT_USER
    return f"ip:{ip}", SURVEY_RL_LIMIT_IP


def _puede_enviar(user, ip) -> tuple[bool, int]:
    """LEE el contador sin tocarlo. `fail_open=False` (E2 del spec).

    Se lee y no se incrementa porque el presupuesto lo gasta el envío que SÍ se
    escribió (`_contar_envio`), no el intento. Un egresado que se equivoca en un
    campo obligatorio no es un atacante, y con `check_and_count` en la puerta
    —que hace `INCR` antes de comparar— diez erratas lo dejaban fuera de una
    encuesta obligatoria durante una hora.

    `fail_open=False`: en una escritura ANÓNIMA, una caída de Redis elimina el
    único control que hay.
    """
    from itcj2.core.utils.rate_limit import check_only

    key, limite = _rate_bucket(user, ip)
    return check_only("survey", key, limit=limite, window=SURVEY_RL_WINDOW,
                      fail_open=False)


def _contar_envio(user, ip) -> None:
    """Cobra UNA unidad de presupuesto por una respuesta ya escrita.

    El resultado no se lee: la puerta ya la abrió `_puede_enviar`, y este
    `INCR` es lo que hará que el siguiente intento la encuentre cerrada.
    """
    from itcj2.core.utils.rate_limit import check_and_count

    key, limite = _rate_bucket(user, ip)
    check_and_count("survey", key, limit=limite, window=SURVEY_RL_WINDOW,
                    fail_open=False)


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
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
            ctx = _form_ctx(_form_meta(form), form.schema or {},
                            values=values, errors={},
                            is_authenticated=bool(user),
                            draft_updated_at=draft_updated)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/public/survey.html", ctx)


@router.post("/encuesta-egresados", name="titulatec.pages.public.survey_submit",
             response_model=None)
async def survey_submit(
    request: Request,
    user: dict | None = Depends(get_current_user_optional),
):
    """Envío de la encuesta.

    Orden: tamaño declarado → trampa → formulario abierto → presupuesto →
    escritura → cobro. El presupuesto se lee antes de escribir y se cobra
    después, y ninguno de los dos pasos puede dejar al visitante sin
    cuestionario: todo lo que devuelve esta ruta con contenido re-imprime lo que
    el visitante escribió.
    """
    from itcj2.database import SessionLocal
    from itcj2.core.utils.client_ip import client_ip
    from itcj2.apps.titulatec.services.survey_service import (
        MAX_PUBLIC_BODY_BYTES, SURVEY_CODE, SurveyService,
    )

    # 1) Tamaño ANTES de `request.form()`: esa llamada bufferea el cuerpo ENTERO
    #    en memoria, así que rechazar después ya pagó el coste que el tope existe
    #    para evitar. Sin `Content-Length` no hay nada que comparar -> 411.
    tamano = _declared_body_size(request.headers)
    if tamano is None:
        return Response(status_code=411, headers={
            "X-Tt-Error": _hdr("No pudimos leer el tamaño de tu envío. "
                               "Recarga la página e inténtalo de nuevo.")})
    if tamano > MAX_PUBLIC_BODY_BYTES:
        return Response(status_code=413, headers={
            "X-Tt-Error": _hdr("Tu respuesta es demasiado grande. Acórtala e "
                               "inténtalo de nuevo.")})

    data = await request.form()
    ip = client_ip(request)   # obligatorio: nunca `request.client.host`, que
                              # detrás de nginx es nginx y mete a todo internet
                              # en un solo cubo.

    # 2) Trampa (E3). Un bot que la llena recibe la MISMA tarjeta de éxito y no
    #    se escribe nada: sin respuesta distinta, no hay señal que optimizar.
    if _trampa_llena(data):
        logger.info("survey: trampa llena desde %s", ip)
        return render_titulatec(
            request, "titulatec/public/partials/survey_thanks.html",
            {"credit_status": "anonymous"})

    cabeceras: dict[str, str] = {}
    db = SessionLocal()
    try:
        form = SurveyService.open_form(db, SURVEY_CODE)
        if form is None:
            # Único 400 público: no hay formulario que re-renderizar (§6.1).
            return Response(status_code=400, headers={
                "X-Tt-Error": _hdr("La encuesta ya no está disponible. "
                                   "Recarga la página.")})

        # Instantánea plana ANTES de escribir: el camino de recuperación hace
        # `rollback()` y ahí toda instancia ORM queda expirada.
        meta, schema = _form_meta(form), (form.schema or {})
        submitted = _submitted_from_form(schema, data)
        plantilla = "titulatec/public/partials/survey_form.html"

        # 3) Presupuesto. Se LEE; se cobra abajo, solo si se escribió.
        permitido, retry_after = _puede_enviar(user, ip)
        if not permitido:
            logger.info("survey: presupuesto agotado (%s)", _rate_bucket(user, ip)[0])
            cabeceras["Retry-After"] = str(max(1, int(retry_after)))
            ctx = _form_ctx(meta, schema, values=submitted, errors={},
                            is_authenticated=bool(user), notice=_RATE_LIMITED_CARD)
        else:
            try:
                _resp, errors, credit_status = SurveyService.submit(
                    db, form, submitted,
                    user_id=int(user["sub"]) if user else None,
                    client_ip=ip,
                    user_agent=request.headers.get("user-agent"),
                )
            except Exception:
                # Segunda capa contra el 500 (ver el docstring del módulo). La
                # primera —`_valor_de_cable`— para el carácter que ya conocemos;
                # esta para el que todavía no. El visitante recupera su
                # cuestionario con un error de formulario completo en vez de un
                # toast genérico sobre una pantalla que no se movió.
                logger.exception("survey: fallo al escribir la respuesta (ip=%s)", ip)
                try:
                    db.rollback()
                except Exception:       # pragma: no cover - sesión ya inservible
                    logger.warning("survey: rollback fallido tras el error de escritura")
                ctx = _form_ctx(meta, schema, values=submitted,
                                errors={FORM_ERROR_KEY: _ERROR_ESCRITURA},
                                is_authenticated=bool(user))
            else:
                if errors:
                    # 200, no 400: htmx no swappea en 4xx, así que un 400 dejaría
                    # la pantalla intacta y el visitante no vería NADA al pulsar
                    # Enviar. Conservar lo capturado es del servidor.
                    ctx = _form_ctx(meta, schema, values=submitted, errors=errors,
                                    is_authenticated=bool(user))
                else:
                    _contar_envio(user, ip)
                    ctx = {"credit_status": credit_status}
                    plantilla = "titulatec/public/partials/survey_thanks.html"
    finally:
        db.close()

    resp = render_titulatec(request, plantilla, ctx)
    for nombre, valor in cabeceras.items():
        resp.headers[nombre] = valor
    return resp


# ---------------------------------------------------------------------------
# 5. Borrador automático (Tarea 13, spec 6.4)
# ---------------------------------------------------------------------------
def _draft_answers(schema: dict, data) -> dict:
    """`FormData` -> respuestas del borrador, restringidas a llaves del `schema`.

    Delega en `_submitted_from_form` (limpieza de NUL y de tipos de cable) y le
    suma el filtro que ese puente NO hace: una llave que el `schema` no declara
    se descarta en silencio, igual que la "llave desconocida" de
    `validate_answers` (delta 6, `utils/survey_validator.py:26`).

    Es la única diferencia real de fondo con el envío. `survey_submit` nunca
    necesitó este filtro explícito porque `validate_answers` ya construye
    `cleaned` recorriendo `schema['fields']` uno por uno -una llave ajena
    simplemente nunca se lee-. El borrador NO pasa por ese validador (es
    intencionalmente parcial: nada de obligatoriedad todavía), así que sin este
    filtro la trampa (`website`) y cualquier campo retirado del formulario se
    guardarían tal cual en la columna JSON del borrador.
    """
    claves = {f.get("key") for f in ((schema or {}).get("fields") or [])
              if isinstance(f, dict) and f.get("key")}
    return {k: v for k, v in _submitted_from_form(schema, data).items() if k in claves}


@router.post("/encuesta-egresados/borrador", name="titulatec.pages.public.survey_draft",
             response_model=None)
async def survey_draft(
    request: Request,
    user: dict | None = Depends(get_current_user_optional),
):
    """Autosave del borrador. Exige SESIÓN, no acceso a la app.

    A propósito **no** usa `require_page_app` (§7.2): un egresado con cuenta pero
    sin proceso puede contestar la encuesta, y `require_page_app` le devolvería
    un 302 al login que el `fetch` de salida no puede aprovechar. Sin sesión:
    `204` y no se escribe nada -ni siquiera se lee el cuerpo-: ninguna escritura
    a BD ocurre antes de que exista la sesión (§6.5).

    Una sola fila `(form_id, user_id)`, UPDATE en sitio, sin historial y sin
    `ProcessEvent`: el techo de D3 son 2 escrituras por minuto por alumno. Por
    eso esta ruta a propósito NO toca el limitador `survey` (§4 de este módulo):
    ese cubo lo gasta el envío (`_puede_enviar`/`_contar_envio`), y un autosave
    cada 30 s compartiendo cubo lo vaciaría en minutos.

    Misma frontera de tamaño que `survey_submit`, con `_declared_body_size`
    (revisión 2026-09-08 de este módulo): un `Content-Length` ausente, no
    numérico o negativo responde `411` en vez de dejar pasar el cuerpo sin
    tope; por encima de `MAX_PUBLIC_BODY_BYTES` responde `413`. Las dos rutas
    quedan idénticas en esa frontera de entrada.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.survey_service import (
        MAX_ANSWERS_JSON_BYTES, MAX_PUBLIC_BODY_BYTES, SURVEY_CODE, SurveyService,
    )

    # 1) Tamaño ANTES de `request.form()`, igual que en `survey_submit`: esa
    #    llamada bufferea el cuerpo ENTERO en memoria.
    tamano = _declared_body_size(request.headers)
    if tamano is None:
        return Response(status_code=411, headers={
            "X-Tt-Error": _hdr("No pudimos leer el tamaño de tu borrador. "
                               "Recarga la página e inténtalo de nuevo.")})
    if tamano > MAX_PUBLIC_BODY_BYTES:
        return Response(status_code=413,
                        headers={"X-Tt-Error": _hdr("El borrador es demasiado grande.")})

    # 2) Sesión. Sin ella no hay a quién atribuirle el borrador -ver el
    #    docstring- y el cuerpo ni siquiera se lee.
    if not user:
        return Response(status_code=204)

    data = await request.form()
    db = SessionLocal()
    try:
        form = SurveyService.open_form(db, SURVEY_CODE)
        if form is None:
            return Response(status_code=204)

        answers = _draft_answers(form.schema or {}, data)

        # 3) Segunda cota, sobre la proyección YA FILTRADA: un cuerpo que cabe
        #    holgado bajo `MAX_PUBLIC_BODY_BYTES` puede traer un solo campo de
        #    texto que por sí solo exceda `MAX_ANSWERS_JSON_BYTES` al
        #    serializarse. Se RECHAZA, nunca se trunca: un borrador recortado
        #    en silencio le borra respuestas al alumno sin que lo note.
        if len(json.dumps(answers, ensure_ascii=False).encode("utf-8")) > MAX_ANSWERS_JSON_BYTES:
            return Response(status_code=413,
                            headers={"X-Tt-Error": _hdr("El borrador es demasiado grande.")})

        SurveyService.save_draft(db, form.id, int(user["sub"]), answers)
    finally:
        db.close()
    return Response(status_code=204)
