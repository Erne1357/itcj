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
from fastapi.responses import RedirectResponse, Response

from itcj2.apps.titulatec.pages.nav import render_titulatec
from itcj2.dependencies import get_current_user_optional

logger = logging.getLogger("itcj2.apps.titulatec.pages.public")

router = APIRouter(tags=["titulatec-pages-public"])

SURVEY_URL = "/titulatec/encuesta-egresados"
SURVEY_DRAFT_URL = f"{SURVEY_URL}/borrador"
# Tarea 3: avanza o retrocede UN paso. Nunca escribe nada -ni borrador ni
# respuesta-, así que vive fuera del limitador `survey` (§4 más abajo) y no
# exige el presupuesto que sí gastan `SURVEY_URL`/`SURVEY_DRAFT_URL`.
SURVEY_STEP_URL = f"{SURVEY_URL}/paso"

# `next` construido sobre la propia encuesta. Viaja tal cual al validador que ya
# existe en el login (`safe_next`, `itcj2/core/pages/auth.py`): es una ruta
# relativa de una sola pieza, sin esquema ni `//host`, así que sobrevive esa
# validación sin quitarle nada. Un solo literal, reutilizado por el redirect del
# GET (Tarea 2) y por el enlace "Iniciar sesión y continuar" del banner anónimo
# (`_form_ctx`, más abajo) para que los dos no puedan divergir.
SURVEY_LOGIN_URL = f"/itcj/login?next={SURVEY_URL}"

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


def _sections(schema: dict, submitted: dict | None = None) -> list[dict]:
    """Agrupa los campos por sección conservando el orden del `schema`.

    Un campo sin `section` (o con una que no existe) cae en un grupo suelto al
    final en vez de desaparecer del formulario — perder una pregunta por una
    llave mal escrita en el seeder sería invisible hasta el export.

    Tarea 3: la encuesta pasó de UNA página a un asistente por pasos, y cada
    grupo aquí es un PASO candidato. Por eso cada dict trae ahora `visible`:
    `True` si alguno de sus campos es visible con las respuestas de
    `submitted` (vía `is_visible`, el mismo evaluador de `visible_when` que ya
    usa la validación). Una sección con todos sus campos condicionados a una
    respuesta que no se dio (o que apunta a "no") cuenta como paso INVISIBLE:
    quien arma la lista de pasos navegables la descarta, en los dos sentidos
    (spec 3.3). El agrupado en sí -qué campo cae en qué sección- no cambia, y
    `submitted=None` (values vacíos) no rompe nada: simplemente ningún campo
    condicional resulta visible todavía, que es la realidad de una encuesta
    recién abierta.
    """
    from itcj2.apps.titulatec.utils.survey_validator import is_visible

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
    grupos = [g for g in grupos if g["fields"]]
    datos = submitted or {}
    for g in grupos:
        g["visible"] = any(is_visible(f, datos) for f in g["fields"])
    return grupos


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
              draft_updated_at="", notice=None, step=None):
    """Contexto del parcial re-renderizable. Idéntico en el GET y en el POST fallido.

    Tarea 3: `step` decide el modo de paginado, y es lo único nuevo del
    contrato (el resto de parámetros no cambió de forma).

      * `step=None` (envío final, `survey_submit`): el contexto sigue siendo
        el de SIEMPRE -TODAS las secciones, una detrás de otra- porque el
        envío final revalida el formulario ENTERO (spec 5) y un error puede
        caer en cualquier sección, no solo en la que el visitante tenía
        abierta. Partir esa vista en un solo paso le escondería al visitante
        errores que sí existen pero que no vería en pantalla.
      * `step` es un índice hacia `_sections(schema, values)` (GET y la ruta
        `SURVEY_STEP_URL`): el contexto trae UNA sola sección -la de ese
        índice, ajustado a la sección VISIBLE más cercana si la pedida no lo
        es (spec 3.3, "se salta en los dos sentidos")-, más el índice, la
        lista de pasos visibles (para el indicador de progreso) y si es el
        último. Los demás campos del `schema` viajan en `other_fields`, que
        la plantilla pinta como ocultos: es como NO se pierde lo capturado en
        otros pasos al hacer swap, sin inventar sesión de servidor (el estado
        completo ya viaja en las respuestas acumuladas de cada envío).
    """
    campos = [f for f in ((schema or {}).get("fields") or []) if isinstance(f, dict)]
    orden = [f.get("key") for f in campos]
    values = values or {}
    grupos = _sections(schema, values)
    ctx = {
        "form": meta,
        "sections": grupos,
        "values": _display_values(schema, values),
        "errors": errors or {},
        "form_error": (errors or {}).get(FORM_ERROR_KEY),
        "first_error_key": next((k for k in orden if k in (errors or {})), None),
        "is_authenticated": is_authenticated,
        "draft_url": SURVEY_DRAFT_URL,
        "draft_updated_at": draft_updated_at,
        "survey_url": SURVEY_URL,
        "step_url": SURVEY_STEP_URL,
        "login_url": SURVEY_LOGIN_URL,
        "no_form": False,
        # Modo "formulario entero" por omisión; el bloque de abajo lo
        # sobreescribe cuando `step` pide el modo paginado.
        "step_index": None,
        "steps": [],
        "step_number": None,
        "step_count": None,
        "is_first_step": True,
        "is_last_step": True,
        "other_fields": [],
    }
    if step is not None and grupos:
        visibles = [i for i, g in enumerate(grupos) if g["visible"]] or list(range(len(grupos)))
        if step not in visibles:
            # Se pidió un paso que hoy no es navegable (invisible, o ya fuera
            # de rango): se ajusta hacia adelante -y si no hay nada después,
            # al último visible-, nunca se revienta con un IndexError.
            posteriores = [i for i in visibles if i > step]
            step = posteriores[0] if posteriores else visibles[-1]
        pos = visibles.index(step)
        actual = grupos[step]
        propios = {f.get("key") for f in actual["fields"]}
        ctx.update(
            sections=[actual],
            step_index=step,
            steps=[{"key": grupos[i]["key"], "title": grupos[i]["title"],
                    "index": i, "current": i == step} for i in visibles],
            step_number=pos + 1,
            step_count=len(visibles),
            is_first_step=(pos == 0),
            is_last_step=(pos == len(visibles) - 1),
            other_fields=[f for f in campos if f.get("key") not in propios],
        )
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
# 4b. Sesión requerida (Tarea 2): `SurveyForm.is_anonymous` decide, no la ruta
# ---------------------------------------------------------------------------
def _requiere_sesion(form) -> bool:
    """True si ESTE formulario exige sesión para verlo/contestarlo.

    Único lector de `SurveyForm.is_anonymous` en todo el repo (`models/
    survey.py:47`): la columna existía desde antes y nadie la consultaba, así
    que hasta hoy la encuesta se abría sin sesión sin importar su valor. El
    banner anónimo, el origen `anonymous` y el borrador en `localStorage`
    siguen existiendo: un formulario futuro con `is_anonymous=True` los sigue
    usando tal cual. Vive suelta -no inline en cada ruta- para que las tres
    lean la MISMA condición; repetirla en `survey`, `survey_submit` y
    `survey_draft` es la forma en la que un día se desincronizarían.
    """
    return not form.is_anonymous


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
@router.get("/encuesta-egresados", name="titulatec.pages.public.survey",
            response_model=None)
async def survey(
    request: Request,
    user: dict | None = Depends(get_current_user_optional),
):
    """Encuesta de egresados: un asistente por pasos, uno por sección (Tarea 3).

    Anónimo (formulario con `is_anonymous=True`): banner persistente de §6.1 y
    borrador solo en `localStorage`. Con sesión: aviso de que sí acredita y
    precarga del borrador de BD.

    Tarea 2: un formulario que NO es anónimo exige sesión. Sin ella, redirige
    al login con `next` apuntando a esta misma encuesta -antes de construir
    nada del contexto, ni siquiera para un visitante que ya tiene un borrador
    guardado de una sesión anterior expirada-.

    Tarea 3: la carga inicial siempre pide el paso 0 -la primera sección
    declarada en el `schema`-. No se intenta "reanudar" en el paso donde el
    visitante iba: eso exigiría guardar el índice en algún lado (sesión de
    servidor, que el spec prohíbe) o adivinarlo a partir del borrador, y con
    el borrador ya precargado en `values` avanzar de nuevo toma como mucho un
    click por sección ya contestada -ninguno vuelve a teclear nada-.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.survey_service import SURVEY_CODE, SurveyService

    db = SessionLocal()
    try:
        form = SurveyService.open_form(db, SURVEY_CODE)
        if form is None:
            ctx = dict(_CLOSED_CARD, no_form=True)
        elif _requiere_sesion(form) and user is None:
            return RedirectResponse(SURVEY_LOGIN_URL, status_code=302)
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
                            draft_updated_at=draft_updated, step=0)
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

    Orden: tamaño declarado → trampa → formulario abierto → sesión (Tarea 2) →
    presupuesto → escritura → cobro. El presupuesto se lee antes de escribir y
    se cobra después, y ninguno de los dos pasos puede dejar al visitante sin
    cuestionario: todo lo que devuelve esta ruta con contenido re-imprime lo que
    el visitante escribió.

    Tarea 2: si el formulario abierto NO es anónimo (`_requiere_sesion`) y no
    hay usuario en la petición, corta con 401 antes de leer el presupuesto o
    llamar a `SurveyService.submit` -no se escribe nada-. Un formulario con
    `is_anonymous=True` sigue aceptando el envío sin sesión, exactamente igual
    que hoy.
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

        # Tarea 2: formulario NO anónimo sin sesión -> corta AQUÍ, antes de
        # tocar `submitted`, el presupuesto o `SurveyService.submit`. Ni
        # rate-limit ni validación corren para una petición que ni siquiera
        # puede escribir; un 401 sin cuerpo ni `X-Tt-Error` no revela nada del
        # formulario (ni que existe, ni si está abierto). Este visitante no
        # debería llegar aquí nunca por la UI real -el GET ya lo mandó al
        # login antes de mostrarle nada que enviar-; es la defensa para quien
        # postea directo, o cuya sesión murió entre el GET y este POST.
        if _requiere_sesion(form) and user is None:
            return Response(status_code=401)

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
# 4c. Avance/retroceso de un paso (Tarea 3, spec 3.3). Nunca escribe nada.
# ---------------------------------------------------------------------------
def _parse_step_index(raw, tope: int) -> int:
    """Índice de paso a partir de lo posteado. Nunca revienta ni sale de rango.

    `raw` es lo que trae `tt_step` -texto, o `None` si el cliente lo omitió-.
    Cualquier cosa que no sea un entero válido, o uno negativo, cae a `0`: es
    el mismo criterio defensivo que `_declared_body_size` (fallar a un valor
    seguro, no a una excepción) para una entrada que el visitante no debería
    poder forjar desde la UI real, pero que sí puede desde un POST directo.
    """
    try:
        n = int(str(raw))
    except (TypeError, ValueError):
        return 0
    if n < 0:
        return 0
    if tope and n >= tope:
        return tope - 1
    return n


@router.post("/encuesta-egresados/paso", name="titulatec.pages.public.survey_step",
             response_model=None)
async def survey_step(
    request: Request,
    user: dict | None = Depends(get_current_user_optional),
):
    """Avanza o retrocede UN paso del cuestionario. Nunca escribe en BD.

    Una sola ruta para las dos direcciones (spec 3.3), distinguidas por CUÁL
    botón se pulsó -`tt_next` o `tt_back`, el `name` del control de envío-, no
    por una URL distinta cada una: es la misma idea que ya usa `_form_ctx`
    para no duplicar el camino de re-render entre el GET y el envío.

    Hacia adelante es ESTRICTO: se valida `validate_answers` sobre un
    "mini-schema" con SOLO los campos de la sección actual (`tt_step`) -nunca
    se reimplementa la validación, se le pasa un `schema` recortado-, y si hay
    error se re-pinta el MISMO paso. Si pasa, avanza al siguiente paso
    VISIBLE, saltándose cualquiera que se haya quedado sin campos visibles
    (spec 3.3) y sin mirar lo que el cliente haya pedido en `tt_next`: no hay
    forma de "saltarse" una sección sin pasar por su validación.

    Hacia atrás es LIBRE: no valida nada, y se mueve al paso VISIBLE anterior
    -otra vez saltándose los que no lo son-. Repetir "Atrás" alcanza cualquier
    sección ya visitada, que es el "volver a cualquier sección" del spec.

    El estado del recorrido es el propio `submitted`: `_submitted_from_form`
    ya reconstruye TODAS las respuestas acumuladas -las de esta sección, en
    controles vivos, más las de las demás, en los ocultos que pinta
    `other_fields`-, así que no hace falta fusionar nada a mano ni inventar
    una sesión de servidor (spec 3.3, brief). Por lo mismo, un `_cleaned` de
    `validate_answers` no se usa para "guardar": lo que viaja de vuelta en
    `values` es siempre `submitted`, crudo, para que un texto que todavía no
    pasa su propia validación (por ejemplo, uno que excede `maxLength`) no
    desaparezca del paso si el visitante retrocede sin corregirlo.

    Misma frontera de tamaño que `survey_submit`/`survey_draft`: un
    `Content-Length` ausente, no numérico o negativo responde 411; por
    encima de `MAX_PUBLIC_BODY_BYTES`, 413. Y la misma guarda de sesión que
    `survey_submit` (Tarea 2): un formulario NO anónimo sin sesión corta con
    401 sin cuerpo -este visitante nunca debería llegar aquí por la UI real,
    porque el GET ya lo mandó al login antes de mostrarle nada que avanzar-.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.survey_service import (
        MAX_PUBLIC_BODY_BYTES, SURVEY_CODE, SurveyService,
    )
    from itcj2.apps.titulatec.utils.survey_validator import validate_answers

    tamano = _declared_body_size(request.headers)
    if tamano is None:
        return Response(status_code=411, headers={
            "X-Tt-Error": _hdr("No pudimos leer el tamaño de tu respuesta. "
                               "Recarga la página e inténtalo de nuevo.")})
    if tamano > MAX_PUBLIC_BODY_BYTES:
        return Response(status_code=413, headers={
            "X-Tt-Error": _hdr("Tu respuesta es demasiado grande. Acórtala e "
                               "inténtalo de nuevo.")})

    data = await request.form()

    db = SessionLocal()
    try:
        form = SurveyService.open_form(db, SURVEY_CODE)
        if form is None:
            return Response(status_code=400, headers={
                "X-Tt-Error": _hdr("La encuesta ya no está disponible. "
                                   "Recarga la página.")})
        if _requiere_sesion(form) and user is None:
            return Response(status_code=401)

        meta, schema = _form_meta(form), (form.schema or {})
        submitted = _submitted_from_form(schema, data)
        grupos = _sections(schema, submitted)

        if not grupos:
            ctx = _form_ctx(meta, schema, values=submitted, errors={},
                            is_authenticated=bool(user), step=0)
        else:
            visibles = ([i for i, g in enumerate(grupos) if g["visible"]]
                       or list(range(len(grupos))))
            actual = _parse_step_index(data.get("tt_step"), len(grupos))
            if actual not in visibles:
                posteriores = [i for i in visibles if i > actual]
                actual = posteriores[0] if posteriores else visibles[-1]
            pos = visibles.index(actual)

            if data.get("tt_back") and pos > 0:
                objetivo, errores = visibles[pos - 1], {}
            else:
                seccion = grupos[actual]
                mini_schema = {"enabled": bool(schema.get("enabled", True)),
                               "fields": seccion["fields"]}
                ok, errores, _cleaned = validate_answers(mini_schema, submitted)
                if ok and pos < len(visibles) - 1:
                    objetivo = visibles[pos + 1]
                else:
                    objetivo = actual        # error, o ya es el último paso

            ctx = _form_ctx(meta, schema, values=submitted, errors=errores,
                            is_authenticated=bool(user), step=objetivo)
    finally:
        db.close()

    return render_titulatec(request, "titulatec/public/partials/survey_form.html", ctx)


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

    Tarea 2 (`_requiere_sesion`, `SurveyForm.is_anonymous`) NO se consulta
    aquí, y no es un olvido: `SurveyDraft.user_id` es `nullable=False`
    (`models/survey.py:137`), así que un borrador de servidor es estructuralmente
    imposible sin sesión, sea o no anónimo el formulario. El `if not user`
    de arriba ya corta ANTES de tocar nada para los dos valores de
    `is_anonymous` -para uno porque la Tarea 2 lo exige, para el otro porque
    ya lo exigía la propia tabla-, que es exactamente "las tres rutas se
    comportan igual" del brief. El anónimo sigue teniendo su borrador, solo
    que vive en `localStorage` y nunca toca esta ruta de verdad (§6.4/D3).
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
        try:
            form = SurveyService.open_form(db, SURVEY_CODE)
            if form is None:
                return Response(status_code=204)

            answers = _draft_answers(form.schema or {}, data)

            # 3) Segunda cota, sobre la proyección YA FILTRADA: un cuerpo que
            #    cabe holgado bajo `MAX_PUBLIC_BODY_BYTES` puede traer un solo
            #    campo de texto que por sí solo exceda `MAX_ANSWERS_JSON_BYTES`
            #    al serializarse. Se RECHAZA, nunca se trunca: un borrador
            #    recortado en silencio le borra respuestas al alumno sin que
            #    lo note.
            if (len(json.dumps(answers, ensure_ascii=False).encode("utf-8"))
                    > MAX_ANSWERS_JSON_BYTES):
                return Response(status_code=413, headers={
                    "X-Tt-Error": _hdr("El borrador es demasiado grande.")})

            SurveyService.save_draft(db, form.id, int(user["sub"]), answers)
        except Exception:
            # Segunda capa contra el 500 (mismo principio del docstring del
            # módulo -"Ninguna entrada del visitante puede producir un 500"-
            # y mismo patrón que el `except` de `survey_submit`): un
            # deadlock, una conexión caída o una violación de constraint en
            # `save_draft` -o incluso en `open_form`- no tienen nada que ver
            # con las dos guardas de tamaño de arriba, así que ninguna de
            # ellas lo cubre. A diferencia de `survey_submit`, aquí no hay
            # formulario que re-renderizar -es un autosave de fondo- ni el
            # cliente puede reaccionar a un error de verdad: el contrato de
            # esta ruta es "204 siempre (con y sin sesión)" (ver Interfaces
            # del brief), así que el fallo se registra y se responde IGUAL
            # que un éxito, nunca un 500 pelado.
            logger.exception("survey_draft: fallo al guardar el borrador (user=%s)",
                             user["sub"])
            try:
                db.rollback()
            except Exception:      # pragma: no cover - sesión ya inservible
                logger.warning("survey_draft: rollback fallido tras el error de escritura")
    finally:
        db.close()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# 6. Inscripción pública (Tarea 19, §6.8)
# ---------------------------------------------------------------------------
# Contexto de `notice_card.html` (T12): `notice_key`, `notice_icon` SIN el
# prefijo `bi-` -la plantilla escribe `class="bi bi-{{ notice_icon }}"`, así que
# pasarlo con prefijo produce `bi bi-bi-envelope-check`-, `notice_title`,
# `notice_body` y el opcional `notice_class`.
#
# E8: la MISMA tarjeta para las tres ramas indistinguibles ("ok", "ya existe
# solicitud viva", "ya tiene proceso"). Sin nombre de convocatoria ni botón de
# reenvío condicional -cualquiera de los dos es el mismo oráculo anónimo que E8
# existe para evitar-.
_ENROLL_CARD = {
    "notice_key": "generic",
    "notice_icon": "envelope-check",
    "notice_title": "Revisa tu correo",
    "notice_body": ("Si tus datos son correctos, te enviamos un correo con el siguiente "
                    "paso. Revisa también la carpeta de correo no deseado."),
}

# — Presupuestos del limitador de inscripción (revisión 2026-09-10, RULING R1/R2) —
#
# El diseño original (§8.1) traía `enroll:ip` en 5/hora con `check_and_count`
# EN LA PUERTA: los mismos dos defectos que ya se corrigieron arriba en
# `SURVEY_RL_LIMIT_IP`.
#
#  1. El ITCJ entero sale a internet por UNA sola dirección pública: 5/hora
#     deja sin poder inscribirse a una generación entera de egresados que lo
#     intenten desde el campus, y la inscripción es la puerta a un requisito
#     de titulación -eso no es una defensa, es una caída-.
#  2. `check_and_count` hace `INCR` ANTES de comparar, así que una errata de
#     formulario (falta el nombre, el correo mal escrito) gasta presupuesto
#     igual que un envío bueno. Cinco erratas y la persona se queda fuera una
#     hora.
#
# Se sube a 30/hora y se pasa al patrón leer-antes/cobrar-después: `check_only`
# ANTES de trabajar (no cuenta el intento), `check_and_count` solo DESPUÉS de
# que `EnrollmentRequestService.create` termine SIN EXCEPCIÓN -mismo patrón que
# `_puede_enviar`/`_contar_envio` de la encuesta, arriba en este módulo-.
#
# El límite por número de control se queda en 3/día -es el control anti-abuso
# de verdad, porque va por identidad y no por IP compartida-, pero TAMBIÉN pasa
# a leer-antes/cobrar-después: para que un `create` que falle (una excepción de
# escritura, no un rechazo de validación) no queme uno de los tres intentos del
# egresado.
ENROLL_RL_LIMIT_IP = 30
ENROLL_RL_WINDOW_IP = 3600
ENROLL_RL_LIMIT_CN = 3
ENROLL_RL_WINDOW_CN = 86400


def _enroll_ip_ok(ip: str) -> tuple[bool, int]:
    """LEE el cubo de IP sin cobrarlo. `fail_open=False`: E2 del spec."""
    from itcj2.core.utils.rate_limit import check_only
    return check_only("enroll:ip", ip, limit=ENROLL_RL_LIMIT_IP,
                      window=ENROLL_RL_WINDOW_IP, fail_open=False)


def _enroll_charge_ip(ip: str) -> None:
    """Cobra UNA unidad del cubo de IP. Solo se llama tras un `create` exitoso."""
    from itcj2.core.utils.rate_limit import check_and_count
    check_and_count("enroll:ip", ip, limit=ENROLL_RL_LIMIT_IP,
                    window=ENROLL_RL_WINDOW_IP, fail_open=False)


def _enroll_cn_ok(control: str) -> tuple[bool, int]:
    """LEE el cubo del número de control sin cobrarlo."""
    from itcj2.core.utils.rate_limit import check_only
    return check_only("enroll:cn", control, limit=ENROLL_RL_LIMIT_CN,
                      window=ENROLL_RL_WINDOW_CN, fail_open=False)


def _enroll_charge_cn(control: str) -> None:
    """Cobra UNA unidad del cubo del número de control."""
    from itcj2.core.utils.rate_limit import check_and_count
    check_and_count("enroll:cn", control, limit=ENROLL_RL_LIMIT_CN,
                    window=ENROLL_RL_WINDOW_CN, fail_open=False)


def _enroll_generic_card(request):
    """La ÚNICA salida de las tres ramas indistinguibles de E8.

    Mismo contexto siempre ⇒ mismos bytes y mismas cabeceras. No lleva el nombre
    de la convocatoria ni un botón de reenvío condicional: cualquiera de los dos
    convertiría el endpoint en un oráculo anónimo de "¿existe este control?".
    """
    return render_titulatec(
        request, "titulatec/public/partials/notice_card.html", dict(_ENROLL_CARD))


def _enroll_wait_card(request, retry: int):
    resp = render_titulatec(request, "titulatec/public/partials/notice_card.html", {
        "notice_key": "rate_limited",
        "notice_icon": "hourglass-split",
        "notice_class": "tt-card--accent",
        "notice_title": "Demasiados intentos",
        "notice_body": f"Espera {max(1, retry // 60)} minutos e inténtalo de nuevo.",
    })
    resp.headers["Retry-After"] = str(max(1, retry))   # E4
    return resp


def _enroll_programs(db):
    from itcj2.core.models.program import Program
    return [{"id": p.id, "name": p.name}
            for p in db.query(Program).order_by(Program.name).all()]


def _enroll_form_ctx(db, *, values=None, errors=None):
    return {"programs": _enroll_programs(db),
            "values": values or {}, "errors": errors or {}, "notice": False}


@router.get("/inscripcion", name="titulatec.pages.public.enroll")
async def enroll(request: Request):
    """Formulario público, gateado por la ventana de la convocatoria (§6.6)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    db = SessionLocal()
    try:
        cohort, err = CohortService.public_enrollment_cohort(db)
        if err == "ambiguous":
            # Falla CERRADO. Los nombres que chocan van al log del operador, no
            # a una pantalla pública.
            logger.error("Más de una convocatoria abierta: la inscripción pública "
                         "queda deshabilitada hasta que quede una sola.")
            return render_titulatec(request, "titulatec/public/enroll.html", {
                "notice": True, "notice_key": "unavailable",
                "notice_icon": "exclamation-octagon",
                "notice_title": "La inscripción no está disponible",
                "notice_body": "Inténtalo más tarde. Ya avisamos a Servicios Escolares.",
            }, status_code=503)
        if err == "closed" or cohort is None:
            return render_titulatec(request, "titulatec/public/enroll.html", {
                "notice": True, "notice_key": "closed",
                "notice_icon": "calendar-x",
                "notice_title": "La inscripción está cerrada",
                "notice_body": ("Ahora mismo no hay una convocatoria abierta. Consulta "
                                "las fechas con Servicios Escolares."),
            })
        ctx = _enroll_form_ctx(db)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/public/enroll.html", ctx)


@router.post("/inscripcion", name="titulatec.pages.public.enroll_submit")
async def enroll_submit(request: Request):
    """Alta de solicitud.

    Orden: tamaño declarado → trampa → límite por IP → ventana → validación →
    límite por número de control → escritura → cobro. Ninguna entrada del
    visitante puede producir un 500 (ver el docstring del módulo): la escritura
    va protegida con el mismo criterio que `survey_submit` (`try/except`
    alrededor de la llamada al service, `rollback` en el `except`).

    Todas las salidas desde la ventana abierta en adelante son la MISMA tarjeta
    (E8): el handler ignora A PROPÓSITO el valor de retorno de
    `EnrollmentRequestService.create` -lo que distingue cada rama viaja por
    correo, nunca por esta respuesta-.
    """
    from itcj2.database import SessionLocal
    from itcj2.core.utils.client_ip import client_ip
    from itcj2.core.utils.email_tools import is_valid_email, normalize_email
    from itcj2.apps.titulatec.services.cohort_service import CohortService
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        CONTROL_NUMBER_RE, MAX_PUBLIC_BODY_BYTES, EnrollmentRequestService,
    )

    # 1) Tamaño ANTES de `request.form()`, que bufferea el cuerpo ENTERO en
    #    memoria. RULING R3: se reutiliza `_declared_body_size` (§1 de este
    #    módulo) en vez de un parser nuevo -el que traía el brief no comprobaba
    #    el signo (`Content-Length: -1` pasaba como "no es grande") y devolvía
    #    `False` sin cabecera, así que un cuerpo `chunked` se leía SIN TOPE-.
    tamano = _declared_body_size(request.headers)
    if tamano is None:
        return Response(status_code=411, headers={
            "X-Tt-Error": _hdr("No pudimos leer el tamaño de tu envío. "
                               "Recarga la página e inténtalo de nuevo.")})
    if tamano > MAX_PUBLIC_BODY_BYTES:
        return Response(status_code=413,
                        headers={"X-Tt-Error": _hdr("El formulario es demasiado grande.")})

    form = await request.form()
    if (form.get("website") or "").strip():
        # Trampa (E3). RULING R4: usa `.tt-public-hp`, ya definida; ver la
        # plantilla. Misma tarjeta genérica, cero escritura, cero cobro.
        return _enroll_generic_card(request)

    ip = client_ip(request)   # nunca `request.client.host`: detrás de nginx es
                              # siempre nginx y mete a todo internet en un cubo.
    ok_ip, retry_ip = _enroll_ip_ok(ip)
    if not ok_ip:
        return _enroll_wait_card(request, retry_ip)

    values = {k: (form.get(k) or "").strip() for k in (
        "control_number", "first_name", "last_name", "middle_name",
        "program_id", "program_text", "phone", "contact_email")}
    values["has_efirma"] = "1" if (form.get("has_efirma") or "") == "1" else "0"

    db = SessionLocal()
    try:
        cohort, err = CohortService.public_enrollment_cohort(db)
        if err == "ambiguous":
            # Ronda de arreglos 1, Important 2. Este POST SIEMPRE llega por htmx
            # (`enroll_form.html`: hx-post + hx-swap="outerHTML"), y htmx NO hace
            # swap en un 5xx: un `render_titulatec(..., status_code=503)` con el
            # aviso en el CUERPO se descarta en silencio, y el visitante ve el
            # toast genérico de `tt-errors.js` en vez del mensaje real. Mismo
            # patrón que el 411/413 de arriba (§1 de este módulo): `Response`
            # SIN formulario, con el mensaje en la CABECERA, que es lo único que
            # el escucha de `htmx:responseError` sí lee en un error.
            logger.error("Más de una convocatoria abierta: POST de inscripción rechazado.")
            return Response(status_code=503, headers={
                "X-Tt-Error": _hdr("La inscripción no está disponible por el momento. "
                                   "Inténtalo más tarde.")})
        if err == "closed" or cohort is None:
            return render_titulatec(request, "titulatec/public/partials/notice_card.html", {
                "notice_key": "closed",
                "notice_icon": "calendar-x",
                "notice_title": "La inscripción está cerrada",
                "notice_body": ("Ahora mismo no hay una convocatoria abierta. Consulta "
                                "las fechas con Servicios Escolares."),
            })

        errors: dict[str, str] = {}
        control = values["control_number"]
        if not CONTROL_NUMBER_RE.fullmatch(control):
            errors["control_number"] = ("Escribe tu número de control tal como "
                                        "aparece en tu credencial.")
        email = normalize_email(values["contact_email"])
        if not is_valid_email(email):
            errors["contact_email"] = "Escribe un correo personal válido."
        if not values["first_name"]:
            errors["first_name"] = "Escribe tu nombre."
        if not values["last_name"]:
            errors["last_name"] = "Escribe tu apellido paterno."
        if not values["phone"]:
            errors["phone"] = "Escribe un teléfono donde podamos localizarte."

        prog_raw = values["program_id"]
        program_id = int(prog_raw) if prog_raw.isdigit() else None
        program_text = values["program_text"][:160] or None
        if program_id is None and not program_text:
            errors["program_id"] = "Elige tu carrera o escríbela si no aparece."

        if errors:
            # 200 con el formulario re-renderizado: es un resultado que el
            # visitante debe VER y CORREGIR, y un formulario puede fallar en
            # varios campos a la vez (§6.1). Ni el cubo de IP ni el de control
            # se tocan: una errata no es un ataque.
            return render_titulatec(
                request, "titulatec/public/partials/enroll_form.html",
                _enroll_form_ctx(db, values=values, errors=errors))

        # El presupuesto por control va DESPUÉS de la regex: keyear Redis con
        # entrada sin validar convierte el contador en un sumidero de
        # cardinalidad. RULING R2: se LEE aquí y se COBRA solo tras un `create`
        # exitoso -mismo patrón que el de IP, arriba-.
        ok_cn, retry_cn = _enroll_cn_ok(control)
        if not ok_cn:
            return _enroll_wait_card(request, retry_cn)

        try:
            EnrollmentRequestService.create(db, cohort, {
                "control_number": control,
                "first_name": values["first_name"][:80],
                "last_name": values["last_name"][:80],
                "middle_name": values["middle_name"][:80] or None,
                "program_id": program_id,
                "program_text": program_text,
                "phone": values["phone"][:20],
                "contact_email": email,
                "has_efirma": values["has_efirma"] == "1",
            }, client_ip=ip)
        except Exception:
            # Ninguna entrada del visitante puede producir un 500 (docstring
            # del módulo). La tarjeta de abajo es la MISMA que la de éxito -ni
            # aquí se distingue la respuesta- y ninguno de los dos cubos se
            # cobra: un `create` que falla no debe quemar uno de los tres
            # intentos del egresado (RULING R1/R2).
            logger.exception("enroll: fallo al crear la solicitud (ip=%s)", ip)
            try:
                db.rollback()
            except Exception:      # pragma: no cover - sesión ya inservible
                logger.warning("enroll: rollback fallido tras el error de escritura")
        else:
            _enroll_charge_ip(ip)
            _enroll_charge_cn(control)
    finally:
        db.close()

    return _enroll_generic_card(request)


# ---------------------------------------------------------------------------
# 7. Verificación de la liga de inscripción y conversión (Tarea 20, §6.9)
# ---------------------------------------------------------------------------
def _verify_card(outcome: str, folio: str) -> dict:
    """Tarjeta por resultado de la verificación.

    `converted` y `already_converted` comparten tarjeta, y `pending_review` con
    `already_pending`: es lo que hace idempotente el GET frente al prefetch de
    Outlook Safe Links (§6.8).

    El contexto es el del parcial `notice_card.html` (Tarea 12): `notice_key`,
    `notice_icon` SIN el prefijo `bi-` (la plantilla ya escribe
    `class="bi bi-{{ notice_icon }}"`, así que pasarlo lo duplicaría),
    `notice_title` y `notice_body`. Los cuatro `notice_key` salen del
    vocabulario cerrado del contrato §8, que `notice_card.html` ya declara en
    su propio comentario: `verified`, `pending`, `expired`, `invalid`.
    """
    if outcome in ("converted", "already_converted"):
        # Dice «ya estás inscrito» y no «te inscribimos» porque le sirve igual
        # al que se inscribió aquí y al que ya venía de un CSV del personal (§6.9).
        return {"notice_key": "verified", "notice_icon": "check-circle",
                "notice_title": "Listo, ya estás inscrito",
                "notice_body": (f"Tu folio es {folio}. Si ya estabas inscrito, este "
                                "es el mismo folio de siempre. Entra a TitulaTec con "
                                "tu número de control y tu NIP para subir tus "
                                "documentos.")}
    if outcome in ("pending_review", "already_pending"):
        return {"notice_key": "pending", "notice_icon": "inbox",
                "notice_title": "Recibimos tu solicitud",
                "notice_body": ("Servicios Escolares la va a revisar y te contactará "
                                "por correo. No necesitas hacer nada más.")}
    if outcome == "expired":
        return {"notice_key": "expired", "notice_icon": "clock-history",
                "notice_title": "Esa liga ya venció",
                "notice_body": ("Vuelve a llenar el formulario de inscripción para "
                                "que te enviemos una nueva.")}
    # Catch-all: "invalid" declarado Y cualquier outcome que no se reconozca
    # (ver el `except` de `enroll_verify`, abajo): NUNCA se distingue "token mal
    # formado" de "algo se rompió en el servidor" — sería un oráculo nuevo.
    return {"notice_key": "invalid", "notice_icon": "x-circle",
            "notice_title": "No pudimos validar tu liga",
            "notice_body": ("Puede que esté incompleta. Vuelve a llenar el formulario "
                            "de inscripción para recibir una nueva.")}


@router.get("/inscripcion/verificar", name="titulatec.pages.public.enroll_verify")
async def enroll_verify(request: Request, t: str = ""):
    """Abre la liga de verificación. IDEMPOTENTE (§6.8).

    DESVIACIÓN DEL BORRADOR DEL BRIEF: el cuerpo va en un `try/except` que el
    borrador no traía. Esta ruta la abre un clic real de correo, sin htmx de
    por medio: un 500 aquí no es un stack trace invisible en un log, es la
    pantalla que ve un egresado que ya demostró quién es (docstring del módulo,
    "Ninguna entrada del visitante puede producir un 500"). Mismo criterio que
    `survey_submit`/`survey_draft`/`enroll_submit`, arriba en este archivo:
    `except Exception` + `db.rollback()` + una tarjeta en vez de una excepción
    que escapa. Ante cualquier fallo se cae a la MISMA tarjeta que un token que
    no existe ("invalid"), para no abrir un oráculo nuevo ("este token era
    válido pero algo se rompió" vs "este token no existe"). El token NUNCA se
    loguea — ni aquí ni en el `except`: es una credencial al portador que viaja
    en la URL.
    """
    from itcj2.database import SessionLocal
    from itcj2.core.utils.client_ip import client_ip
    from itcj2.core.utils.rate_limit import check_and_count
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    ok, retry = check_and_count("enroll_verify:ip", client_ip(request),
                                limit=30, window=3600, fail_open=False)
    if not ok:
        resp = render_titulatec(request, "titulatec/public/enroll.html", {
            "notice": True, "notice_key": "rate_limited",
            "notice_icon": "hourglass-split",
            "notice_class": "tt-card--accent",
            "notice_title": "Demasiados intentos",
            "notice_body": f"Espera {max(1, retry // 60)} minutos e inténtalo de nuevo.",
        })
        resp.headers["Retry-After"] = str(max(1, retry))
        return resp

    db = SessionLocal()
    try:
        try:
            req, outcome = EnrollmentRequestService.verify(db, t)
            folio = ""
            if req is not None and req.converted_process_id:
                proc = db.get(TitulationProcess, req.converted_process_id)
                folio = proc.folio if proc is not None else ""
            ctx = _verify_card(outcome, folio)
        except Exception:
            # Ver el docstring de arriba: ninguna entrada del visitante puede
            # producir un 500, y el token NUNCA va en el log (ni en el mensaje
            # ni en la traza — no se interpola `t` en ningún argumento de abajo).
            logger.exception("enroll_verify: fallo inesperado al verificar la liga")
            try:
                db.rollback()
            except Exception:      # pragma: no cover - sesión ya inservible
                logger.warning("enroll_verify: rollback fallido tras el error")
            ctx = _verify_card("invalid", "")
    finally:
        db.close()
    ctx["notice"] = True
    return render_titulatec(request, "titulatec/public/enroll.html", ctx)


# ---------------------------------------------------------------------------
# 8. Reenvío de la liga y confirmación del correo personal (Tarea 21, §6.8, D17)
# ---------------------------------------------------------------------------
# Contexto de `notice_card.html` (T12): `notice_key`, `notice_icon` SIN el
# prefijo `bi-`, `notice_title`, `notice_body` y el opcional `notice_class`.
#
# §6.8 exige que 'sent' y 'noop' sean INDISTINGUIBLES: la misma tarjeta para el
# control+correo que sí casan con una solicitud viva, para el que no casa, para
# el tope agotado, para la ventana cerrada Y para la trampa. Cualquier tarjeta
# propia para alguno de esos casos es un oráculo anónimo de "¿existe este
# número de control?" (RULING R4, Tarea 21).
_RESEND_CARD = {
    "notice_key": "generic",
    "notice_icon": "envelope-check",
    "notice_title": "Listo",
    "notice_body": ("Si esos datos corresponden a una solicitud pendiente, ya te "
                    "reenviamos la liga. Revisa también el correo no deseado."),
}

# — Presupuesto del limitador de reenvío (RULING R3, Tarea 21) —
#
# El brief original traía `enroll_resend:ip` a 3/hora. Sube a 10/hora por el
# mismo motivo que ya subieron `SURVEY_RL_LIMIT_IP` y `ENROLL_RL_LIMIT_IP` más
# arriba en este módulo: el ITCJ entero sale a internet por UNA sola dirección
# pública, así que 3/hora deja al cuarto egresado que necesita un reenvío desde
# el campus sin poder pedirlo.
#
# A DIFERENCIA de `ENROLL_RL_LIMIT_IP`/`SURVEY_RL_LIMIT_IP`, este cubo se queda
# EN LA PUERTA (`check_and_count`, no `check_only` + cobro condicionado): en las
# Tareas 12 y 19 el patrón leer-antes/cobrar-después existe para no dejar fuera
# de un trámite obligatorio a quien se equivoca de campo. Aquí NO aplica, y
# aplicarlo sería un fallo de seguridad — §6.8 exige que 'sent' y 'noop' cuesten
# EXACTAMENTE lo mismo. Si el cobro solo ocurriera cuando `resend()` manda de
# verdad, cualquiera podría enviar N intentos con un número de control candidato
# y medir a qué velocidad se agota su propio cubo de IP para saber si ese
# control existe — un oráculo por temporización, la misma familia de fuga que
# `hmac.compare_digest` (R1) existe para cerrar en la comparación de tokens.
# Los dos resultados ('sent' y 'noop') tienen que costar lo mismo: se cobra
# SIEMPRE, antes de llamar a `EnrollmentRequestService.resend`, y una excepción
# dentro de `resend` tampoco cambia el cobro ni la tarjeta de vuelta.
ENROLL_RESEND_RL_LIMIT_IP = 10
ENROLL_RESEND_RL_WINDOW_IP = 3600


@router.post("/inscripcion/reenviar", name="titulatec.pages.public.enroll_resend")
async def enroll_resend(request: Request):
    """Reenvía la liga de verificación. Salida idéntica case o no case (§6.8).

    Orden: tamaño declarado → trampa → presupuesto por IP (cobrado SIEMPRE,
    RULING R3) → escritura. Ninguna entrada del visitante puede producir un
    500 (docstring del módulo): la llamada al service va protegida igual que
    `enroll_submit`/`survey_submit`, arriba en este archivo.

    RULING R2: usa `_declared_body_size` (§1 de este módulo) en vez de un
    parser nuevo — `_enroll_too_big` no existe, nunca existió.
    """
    from itcj2.database import SessionLocal
    from itcj2.core.utils.client_ip import client_ip
    from itcj2.core.utils.rate_limit import check_and_count
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        MAX_PUBLIC_BODY_BYTES, EnrollmentRequestService,
    )

    # 1) Tamaño ANTES de `request.form()`, que bufferea el cuerpo ENTERO en
    #    memoria. Mismo patrón que `enroll_submit`/`survey_submit`.
    tamano = _declared_body_size(request.headers)
    if tamano is None:
        return Response(status_code=411, headers={
            "X-Tt-Error": _hdr("No pudimos leer el tamaño de tu envío. "
                               "Recarga la página e inténtalo de nuevo.")})
    if tamano > MAX_PUBLIC_BODY_BYTES:
        return Response(status_code=413,
                        headers={"X-Tt-Error": _hdr("El formulario es demasiado grande.")})

    form = await request.form()
    if (form.get("website") or "").strip():
        # Trampa (E3): tercera salida indistinguible (RULING R4). MISMA tarjeta,
        # cero escritura, cero cobro — igual que la trampa de `enroll_submit`.
        return render_titulatec(
            request, "titulatec/public/partials/notice_card.html", dict(_RESEND_CARD))

    # 2) Presupuesto por IP. Se cobra AQUÍ, SIEMPRE, antes de saber si el
    #    control+correo van a casar con algo (RULING R3): es lo que hace que
    #    'sent' y 'noop' cuesten lo mismo.
    ip = client_ip(request)
    ok, retry = check_and_count("enroll_resend:ip", ip,
                                limit=ENROLL_RESEND_RL_LIMIT_IP,
                                window=ENROLL_RESEND_RL_WINDOW_IP, fail_open=False)
    if not ok:
        return _enroll_wait_card(request, retry)

    control = (form.get("control_number") or "").strip()
    email = (form.get("contact_email") or "").strip()

    db = SessionLocal()
    try:
        EnrollmentRequestService.resend(db, control, email)
    except Exception:
        # Ninguna entrada del visitante puede producir un 500. El presupuesto
        # de arriba YA se cobró (RULING R3): una excepción no debe cambiar ni
        # el cobro ni la tarjeta de vuelta, o la excepción misma se volvería
        # una señal distinguible.
        logger.exception("enroll_resend: fallo al reenviar (ip=%s)", ip)
        try:
            db.rollback()
        except Exception:      # pragma: no cover - sesión ya inservible
            logger.warning("enroll_resend: rollback fallido tras el error de escritura")
    finally:
        db.close()

    # 'sent', 'noop' y la excepción devuelven lo MISMO a propósito (§6.8, R4).
    return render_titulatec(
        request, "titulatec/public/partials/notice_card.html", dict(_RESEND_CARD))


@router.get("/inscripcion/correo", name="titulatec.pages.public.contact_confirm")
async def contact_confirm(request: Request, t: str = ""):
    """Confirma el correo personal. NO bloquea la inscripción (D17).

    A diferencia del reenvío, aquí 'confirmado' y 'no confirmado' SÍ se
    distinguen (`contact_ok` vs `contact_invalid`, notice_key distintos): no es
    un oráculo de existencia porque la llave es el propio token —un
    `secrets.token_urlsafe(32)` que solo posee quien recibió el correo—, no un
    número de control adivinable como en `enroll_resend`. §6.8/E8 no aplican
    aquí; el vocabulario cerrado de `notice_card.html` ya preveía estas dos
    llaves (Tarea 12).

    Comparte el cubo `enroll_verify:ip` (30/hora) con `enroll_verify`
    (Tarea 20) a propósito: las dos son clics de liga y ese presupuesto es
    holgado para ese uso.

    Ninguna entrada del visitante puede producir un 500 (docstring del
    módulo): mismo criterio que `enroll_verify`, arriba — `except Exception` +
    `db.rollback()` + la tarjeta de "no pudimos confirmar" en vez de una
    excepción que escapa. El token NUNCA se loguea, ni aquí ni en el `except`.
    """
    from itcj2.database import SessionLocal
    from itcj2.core.utils.client_ip import client_ip
    from itcj2.core.utils.rate_limit import check_and_count
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    ok, retry = check_and_count("enroll_verify:ip", client_ip(request),
                                limit=30, window=3600, fail_open=False)
    if not ok:
        # `notice` es la bandera de PÁGINA que `enroll.html` mira para incluir el
        # parcial; no forma parte del contexto de `notice_card.html`.
        resp = render_titulatec(request, "titulatec/public/enroll.html", {
            "notice": True, "notice_key": "rate_limited",
            "notice_icon": "hourglass-split",
            "notice_class": "tt-card--accent",
            "notice_title": "Demasiados intentos",
            "notice_body": f"Espera {max(1, retry // 60)} minutos e inténtalo de nuevo.",
        })
        resp.headers["Retry-After"] = str(max(1, retry))
        return resp

    db = SessionLocal()
    try:
        try:
            confirmado = EnrollmentRequestService.confirm_contact(db, t)
        except Exception:
            # Ver el docstring de arriba: el token NUNCA va en el log (ni en el
            # mensaje ni en la traza — no se interpola `t` en ningún argumento).
            logger.exception("contact_confirm: fallo inesperado al confirmar el correo")
            try:
                db.rollback()
            except Exception:      # pragma: no cover - sesión ya inservible
                logger.warning("contact_confirm: rollback fallido tras el error")
            confirmado = False
    finally:
        db.close()

    if confirmado:
        ctx = {"notice_key": "contact_ok", "notice_icon": "check-circle",
               "notice_title": "Correo personal confirmado",
               "notice_body": ("Ya podemos escribirte ahí. Tu inscripción sigue su curso "
                               "por separado: no necesitas hacer nada más aquí.")}
    else:
        ctx = {"notice_key": "contact_invalid", "notice_icon": "x-circle",
               "notice_title": "No pudimos confirmar ese correo",
               "notice_body": ("La liga puede estar incompleta o vencida. Esto no afecta "
                               "tu inscripción.")}
    ctx["notice"] = True
    return render_titulatec(request, "titulatec/public/enroll.html", ctx)
