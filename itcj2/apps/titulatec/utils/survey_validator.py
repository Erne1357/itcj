"""Validador del motor de encuestas de TitulaTec.

Port de `itcj2/apps/helpdesk/utils/custom_fields_validator.py` (126 lineas). Se
PORTA y no se importa: acoplar titulatec al ciclo de release de helpdesk por 126
lineas estables no sale a cuenta (decision E6 del diseno).

Delta sobre el original, punto por punto (seccion 4.3 del diseno):

  1. Firma nueva. El original devuelve `(ok, errors)`; aqui `(ok, errors, cleaned)`.
     `cleaned` es la PROYECCION VALIDADA: es lo que se guarda en
     `titulatec_survey_responses.answers` y lo que acota su tamano.
  2. Tipos nuevos: `scale` (entero en [min,max]), `yesno` (booleano) y
     `multiselect` (lista de valores de `options`).
  3. `multiselect` exige LISTA. Un no-lista es error, no un pase silencioso;
     "requerido" significa lista con al menos un elemento. NO se reutiliza el
     test `field_value is not True` de `checkbox`, que es verdadero para
     cualquier lista, ni `_validate_select`, que es escalar.
  4. Desaparecen `file`/`maxSize`/`allowedExtensions`, y `validation` es un
     VOCABULARIO CERRADO (`ALLOWED_VALIDATION_KEYS`). En su primera version solo
     sobrevivian `minLength` y `maxLength`; el punto 7 devuelve `min`/`max`, pero
     SOLO como parametros de un `format`. `pattern` -una regex escrita a mano en
     un seeder, que nadie revisa y que un retroceso catastrofico convierte en un
     proceso colgado- sigue sin existir (`scale` lleva sus propios min/max en su
     bloque).
  5. `visible_when` corre en el SERVIDOR. Un requerido oculto en el cliente
     sigue siendo requerido cuando su condicion se cumple, y un campo con
     condicion falsa se DESCARTA en vez de guardarse. Solo `select` y `radio`
     pueden ser FUENTE de una condicion: `validate_schema` rechaza al resto
     porque su forma en el cable no coincide con su forma en el schema.
  6. Llave desconocida -> se descarta en silencio (el schema pudo cambiar) y no
     llega a `cleaned`.
  7. (2026-09-15) Formatos por campo, tipo `date` y una regla cruzada:
       · un `text` puede declarar `validation.format`, uno de `TEXT_FORMATS`:
           - `digits`: exactamente `length` digitos ASCII;
           - `phone`: exactamente 10 digitos. Admite espacio, guion, punto y
             parentesis ("656 123 4567" SI son diez digitos) y guarda solo los
             digitos;
           - `year`: 4 digitos en [`min`, `max`]; `max` puede ser el literal
             "current", el ano en curso resuelto al validar;
           - `decimal`: numero en [`min`, `max`] con hasta 2 decimales. Admite
             COMA decimal ("87,5") y lo guarda con punto;
           - `email`: delega en `core.utils.email_tools.is_valid_email`, sin
             copiar su regex;
           - `person_name`: letras Unicode (acentos, ene, dieresis), espacios,
             guion y apostrofo, con al menos 2 letras. Se guarda en NFC y con
             los espacios colapsados;
       · `date`: `AAAA-MM-DD` real -lo que manda `<input type="date">`- con
         `validation.minAge`/`maxAge` contra HOY. Se guarda como texto ISO;
       · `validation.gte_field`: un `year` no puede ser menor que otro `year`
         de su MISMA seccion. Se evalua solo cuando los dos valores ya pasaron
         su propia validacion.
     Un campo con formato guarda el valor NORMALIZADO: el export y los
     promedios no tienen que adivinar como lo escribio cada quien. Sin formato,
     `text` y `textarea` siguen guardando el texto tal cual llego.

El cuerpo llega de `await request.form()`, asi que todo valor escalar puede ser
cadena: `yesno`/`checkbox` se normalizan a booleano ANTES de la rama de
obligatoriedad, para que `checkbox` conserve literalmente el `is not True` del
original y no lo haga verdadero un `"on"`.

Modulo casi puro, a proposito: no toca BD ni conoce `Request`, y se prueba con
`pytest` sin harness. Solo importa, y de forma LOCAL, dos utilidades del core que
tampoco tocan nada: `email_tools` (solo `re`) y `timezone.db_now` (solo
`zoneinfo`), para que "hoy" sea el de la app y no el UTC del contenedor.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal

logger = logging.getLogger("itcj2.apps.titulatec.utils.survey_validator")

FIELD_TYPES = {
    "text", "textarea", "select", "radio", "checkbox",
    "scale", "yesno", "multiselect", "date",
}
TYPES_WITH_OPTIONS = {"select", "radio", "multiselect"}

# — Vocabulario CERRADO de `validation` (puntos 4 y 7) —
TEXT_FORMATS = ("digits", "phone", "year", "decimal", "email", "person_name")
# Llaves que solo existen como parametro de un formato, y de cual.
_FORMAT_PARAMS = {
    "digits": {"length"},
    "phone": set(),
    "year": {"min", "max", "gte_field"},
    "decimal": {"min", "max"},
    "email": set(),
    "person_name": set(),
}
_PARAM_KEYS = {"length", "min", "max", "gte_field"}
_AGE_KEYS = {"minAge", "maxAge"}
ALLOWED_VALIDATION_KEYS = {"minLength", "maxLength", "format"} | _PARAM_KEYS | _AGE_KEYS

CURRENT_YEAR = "current"
PHONE_DIGITS = 10
YEAR_DIGITS = 4
DECIMAL_PLACES = 2
PERSON_NAME_MIN_LETTERS = 2

# `autocomplete` que un `text`/`date` puede declarar para pisar el que deriva de
# su formato. Existe por un caso real del instrumento: el telefono del encargado
# de RH NO es el del egresado, y con `tel-national` el navegador ofreceria
# autollenarlo con el suyo.
AUTOCOMPLETE_TOKENS = {"off", "name", "email", "tel", "tel-national", "bday"}

_TRUE_WORDS = {"true", "on", "1", "si", "sí", "yes", "y"}
_FALSE_WORDS = {"false", "off", "0", "no", "n", ""}

# `[0-9]` y no `\d`: en Python `\d` casa tambien digitos arabigo-indicos o
# devanagari, y `str.isdigit()` hasta un "²".
_RE_DIGITS = re.compile(r"[0-9]+")
_RE_YEAR = re.compile(r"[0-9]{%d}" % YEAR_DIGITS)
_RE_DECIMAL = re.compile(r"[0-9]+(?:[.,][0-9]{1,%d})?" % DECIMAL_PLACES)
# Forma exacta ANTES de construir la fecha: `date.fromisoformat` de 3.11+ acepta
# tambien "20000101" y semanas ISO, que ningun `<input type="date">` manda.
_RE_ISO_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_RE_PHONE_SEPARATORS = re.compile(r"[\s().\-]")
_RE_TRAILING_PARENS = re.compile(r"\s*\([^()]*\)\s*$")
_NAME_MARKS = frozenset(" -'’")


# ---------------------------------------------------------------------------
# Helpers de lectura
# ---------------------------------------------------------------------------
def _label(config: dict) -> str:
    return str(config.get("label") or config.get("key") or "campo")


def _label_corto(config: dict) -> str:
    """Rotulo apto para una frase de error.

    El instrumento real trae rotulos de FORMULARIO, no sustantivos: «No. Control:»,
    «Año de INGRESO (EJ. 1999)», «Número telefónico (10 dígitos):». Pegados tal
    cual a «debe tener…» meten la pista del rotulo en medio del mensaje. Se corta
    en el primer ":" y se quitan los parentesis del final; lo que queda sigue
    nombrando el campo que el visitante tiene justo encima del error.
    """
    texto = _label(config).split(":", 1)[0]
    previo = None
    while texto != previo:
        previo = texto
        texto = _RE_TRAILING_PARENS.sub("", texto)
    return texto.strip() or str(config.get("key") or "campo")


def _validation_de(config: dict) -> dict:
    validation = config.get("validation")
    return validation if isinstance(validation, dict) else {}


def _es_entero(valor) -> bool:
    """`int` de verdad: en Python `True` tambien es un `int`."""
    return isinstance(valor, int) and not isinstance(valor, bool)


def _es_numero(valor) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def _option_values(config: dict) -> list[str]:
    return [str(opt.get("value")) for opt in (config.get("options") or [])
            if isinstance(opt, dict) and opt.get("value") is not None]


def _as_bool(value):
    """Booleano de un valor de formulario. `None` si no se puede decidir."""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    word = str(value).strip().lower()
    if word in _TRUE_WORDS:
        return True
    if word in _FALSE_WORDS:
        return False
    return None


def _as_int(value):
    """Entero de un valor de formulario. `None` si no es un entero."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _is_empty(field_type: str, value) -> bool:
    """Equivalente por tipo del `if not field_value: continue` del original.

    El original (`custom_fields_validator.py:52-53`) usa la falsedad de Python,
    que aqui descartaria un `False` de checkbox/yesno y un `0` de scale — y esos
    SI son respuestas. Un `multiselect` que no es lista tampoco es "vacio": es
    un error, y por eso cae al validador.
    """
    if field_type == "multiselect":
        # AUSENTE es vacio, y no es lo mismo que un no-lista PRESENTE. Un grupo
        # de casillas sin ninguna marcada no manda la llave, asi que el cuerpo
        # llega sin ella: tomarlo por "no vacio" lo mandaba a
        # `_validate_multiselect`, que lo rechazaba por no ser lista, e
        # invalidaba el formulario entero por un campo OPCIONAL que nadie
        # estaba obligado a contestar. Un `"en"` presente si sigue siendo error
        # (delta 3): eso es un cliente mal formado, no una omision.
        if value is None:
            return True
        return isinstance(value, list) and not value
    if field_type in ("checkbox", "yesno"):
        return value is None
    if value is None:
        return True
    return isinstance(value, str) and not value.strip()


# ---------------------------------------------------------------------------
# Calendario (punto 7): "hoy", edades y rango del <input type="date">
# ---------------------------------------------------------------------------
def _hoy() -> date:
    """Fecha LOCAL de la app, no la del contenedor.

    El contenedor corre en UTC: de 18:00 a 23:59 de Ciudad Juarez ya es "manana"
    y un cumpleanos o el ano en curso se correrian un dia. `db_now` es la hora
    local de la app (solo `zoneinfo`: no arrastra configuracion ni BD).
    """
    from itcj2.core.utils.timezone import db_now
    return db_now().date()


def _edad(nacimiento: date, hoy: date) -> int:
    return hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))


def _restar_anios(dia: date, anios: int) -> date:
    anio = max(dia.year - anios, 1)
    try:
        return dia.replace(year=anio)
    except ValueError:             # 29 de febrero hacia un ano que no es bisiesto
        return dia.replace(year=anio, day=28)


def date_bounds(config: dict, today: date | None = None) -> dict[str, str]:
    """`min`/`max` ISO para el `<input type="date">` de un campo con edad acotada.

    Misma aritmetica que `_validate_date`, a proposito en el mismo modulo: si el
    selector ofreciera un dia que el servidor rechaza (o al reves), el visitante
    no tendria forma de entender el error. `max` es el dia en que se cumple
    `minAge`; `min`, el dia siguiente a aquel en que se cumplirian `maxAge + 1`.
    Sin `minAge` ni `maxAge` no acota nada: una fecha cualquiera no es una edad.
    """
    validation = _validation_de(config or {})
    min_age, max_age = validation.get("minAge"), validation.get("maxAge")
    if not (_es_entero(min_age) or _es_entero(max_age)):
        return {}
    hoy = today or _hoy()
    limites: dict[str, str] = {}
    if _es_entero(max_age):
        limites["min"] = (_restar_anios(hoy, max_age + 1) + timedelta(days=1)).isoformat()
    if _es_entero(min_age):
        limites["max"] = _restar_anios(hoy, min_age).isoformat()
    return limites


# ---------------------------------------------------------------------------
# Visibilidad (delta 5)
# ---------------------------------------------------------------------------
def is_visible(field: dict, submitted: dict) -> bool:
    """Evalua `visible_when` en el SERVIDOR: igualdad exacta o pertenencia, conjuncion (AND).

    Portado de `_check_visibility` (`custom_fields_validator.py:68-74`). Compara
    contra el valor CRUDO enviado, que es lo que emite el radio/select fuente.

    Si el valor esperado es una LISTA o TUPLA, la condicion se cumple cuando el
    valor ENVIADO pertenece a ella (membership). Si es un ESCALAR, se mantiene
    la igualdad exacta del comportamiento original.

    Por eso `validate_schema` solo admite `select`/`radio` como FUENTE: un tipo
    cuya codificacion en el navegador difiere de su codificacion en el schema
    jamas puede satisfacer una igualdad exacta (escalar) ni una pertenencia
    (lista contra lista). Un `multiselect` manda una lista; un `checkbox` manda
    `"on"` y el schema declara `true`; un `yesno` igual. En los tres casos la
    condicion nunca casa, el dependiente se toma por invisible y su respuesta se
    descarta EN SILENCIO — justo el fallo que evaluar `visible_when` en el
    servidor existe para evitar. Una lista en `visible_when` no relaja esta
    restriccion: la fuente sigue siendo `select`/`radio`, que manda un escalar.
    """
    visible_when = field.get("visible_when")
    if not visible_when:
        return True
    for key, expected in visible_when.items():
        submitted_value = submitted.get(key)
        # Si expected es una lista o tupla, verificar membership
        if isinstance(expected, (list, tuple)):
            if submitted_value not in expected:
                return False
        # Si es un escalar, mantener igualdad exacta
        else:
            if submitted_value != expected:
                return False
    return True


# ---------------------------------------------------------------------------
# Formatos de `text` (punto 7) — reciben el texto YA sin espacios alrededor y
# devuelven `(error, valor_a_guardar)`
# ---------------------------------------------------------------------------
def _fmt_digits(texto: str, config: dict, validation: dict, hoy: date):
    largo = validation.get("length")
    if not _RE_DIGITS.fullmatch(texto) or len(texto) != largo:
        return f"{_label_corto(config)} debe tener exactamente {largo} dígitos", None
    return None, texto


def _fmt_phone(texto: str, config: dict, validation: dict, hoy: date):
    digitos = _RE_PHONE_SEPARATORS.sub("", texto)
    if not _RE_DIGITS.fullmatch(digitos) or len(digitos) != PHONE_DIGITS:
        return f"{_label_corto(config)} debe tener exactamente {PHONE_DIGITS} dígitos", None
    return None, digitos


def _fmt_year(texto: str, config: dict, validation: dict, hoy: date):
    bajo = validation.get("min")
    alto = hoy.year if validation.get("max") == CURRENT_YEAR else validation.get("max")
    rango = f" entre {bajo} y {alto}" if _es_entero(bajo) and _es_entero(alto) else ""
    if (not _RE_YEAR.fullmatch(texto)
            or (_es_entero(bajo) and int(texto) < bajo)
            or (_es_entero(alto) and int(texto) > alto)):
        return f"{_label_corto(config)} debe ser un año de {YEAR_DIGITS} dígitos{rango}", None
    return None, texto


def _fmt_decimal(texto: str, config: dict, validation: dict, hoy: date):
    corto = _label_corto(config)
    if not _RE_DECIMAL.fullmatch(texto):
        return (f"{corto} debe ser un número con hasta {DECIMAL_PLACES} decimales "
                "(por ejemplo 93 u 87.5)"), None
    valor = Decimal(texto.replace(",", "."))
    bajo, alto = validation.get("min"), validation.get("max")
    if ((_es_numero(bajo) and valor < Decimal(str(bajo)))
            or (_es_numero(alto) and valor > Decimal(str(alto)))):
        return f"{corto} debe estar entre {bajo} y {alto}", None
    # `str(Decimal)` conserva los decimales escritos ("87.50") y quita los ceros
    # a la izquierda ("093" -> "93").
    return None, str(valor)


def _fmt_email(texto: str, config: dict, validation: dict, hoy: date):
    # Se lee el ATRIBUTO del modulo en cada llamada: una sola regex de correo en
    # el repo, la del core, y no una copia que diverja en silencio.
    from itcj2.core.utils import email_tools

    if not email_tools.is_valid_email(texto):
        return (f"{_label_corto(config)} no es un correo válido "
                "(por ejemplo, nombre@dominio.com)"), None
    return None, texto


def _fmt_person_name(texto: str, config: dict, validation: dict, hoy: date):
    nombre = unicodedata.normalize("NFC", " ".join(texto.split()))
    corto = _label_corto(config)
    # Las marcas combinantes (categoria M) cuentan como parte de una letra: NFC no
    # tiene forma precompuesta para toda combinacion.
    if any(not (ch.isalpha() or unicodedata.category(ch).startswith("M") or ch in _NAME_MARKS)
           for ch in nombre):
        return f"{corto} solo puede llevar letras, espacios, guion y apóstrofo", None
    if sum(1 for ch in nombre if ch.isalpha()) < PERSON_NAME_MIN_LETTERS:
        return f"{corto} debe tener al menos {PERSON_NAME_MIN_LETTERS} letras", None
    return None, nombre


_FORMATOS = {
    "digits": _fmt_digits,
    "phone": _fmt_phone,
    "year": _fmt_year,
    "decimal": _fmt_decimal,
    "email": _fmt_email,
    "person_name": _fmt_person_name,
}


# ---------------------------------------------------------------------------
# Validadores por tipo
# ---------------------------------------------------------------------------
def _validate_text(value, config: dict, hoy: date) -> tuple[str | None, str | None]:
    """`text`/`textarea`. Devuelve `(error, valor_a_guardar)`.

    Con `format`, el formato va PRIMERO: a «902000011» le sirve «debe tener
    exactamente 8 digitos», no «no puede exceder 8 caracteres». Y el largo se
    mide sobre el valor ya normalizado, que es el que se guarda.
    """
    validation = _validation_de(config)
    formato = _FORMATOS.get(validation.get("format")) if config.get("type") == "text" else None
    if formato is not None:
        error, text = formato(str(value).strip(), config, validation, hoy)
        if error:
            return error, None
    else:
        text = str(value)
    if "minLength" in validation and len(text) < validation["minLength"]:
        return f"{_label(config)} debe tener al menos {validation['minLength']} caracteres", None
    if "maxLength" in validation and len(text) > validation["maxLength"]:
        return f"{_label(config)} no puede exceder {validation['maxLength']} caracteres", None
    return None, text


def _fecha_iso(texto: str) -> date | None:
    m = _RE_ISO_DATE.fullmatch(texto)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:              # 2000-02-30, mes 13, ano 0000
        return None


def _validate_date(value, config: dict, hoy: date) -> tuple[str | None, str | None]:
    """`date` (punto 7). Devuelve `(error, fecha_iso)`."""
    corto = _label_corto(config)
    fecha = _fecha_iso(str(value).strip())
    if fecha is None:
        return f"{corto} no es una fecha válida", None
    validation = _validation_de(config)
    min_age, max_age = validation.get("minAge"), validation.get("maxAge")
    if not (_es_entero(min_age) or _es_entero(max_age)):
        return None, fecha.isoformat()
    # Con edad acotada la fecha es un nacimiento: una futura daria una edad
    # negativa y el mensaje de "menor a N anos" no le diria nada a nadie.
    if fecha > hoy:
        return f"{corto} no puede ser una fecha futura", None
    edad = _edad(fecha, hoy)
    if _es_entero(min_age) and edad < min_age:
        return f"{corto} indica una edad menor a {min_age} años", None
    if _es_entero(max_age) and edad > max_age:
        return f"{corto} indica una edad mayor a {max_age} años", None
    return None, fecha.isoformat()


def _validate_select(value, config: dict) -> str | None:
    if str(value) not in _option_values(config):
        return f"Valor invalido para {_label(config)}"
    return None


def _validate_scale(value, config: dict) -> tuple[str | None, int | None]:
    block = config.get("scale") or {}
    low = block.get("min", 1)
    high = block.get("max", 5)
    parsed = _as_int(value)
    if parsed is None:
        return f"{_label(config)}: elige un valor entre {low} y {high}", None
    if parsed < low or parsed > high:
        return f"{_label(config)} debe estar entre {low} y {high}", None
    return None, parsed


def _validate_multiselect(value, config: dict) -> tuple[str | None, list | None]:
    """Delta 3. `_validate_select` es escalar y NO sirve tal cual."""
    if not isinstance(value, list):
        return f"{_label(config)}: se esperaba una lista de opciones", None
    valid = _option_values(config)
    out: list[str] = []
    for item in value:
        item = str(item)
        if item not in valid:
            return f"Valor invalido para {_label(config)}", None
        if item not in out:          # el mismo checkbox marcado dos veces no duplica fila
            out.append(item)
    return None, out


def _aplicar_gte_field(fields: list[dict], errors: dict, cleaned: dict) -> None:
    """Regla cruzada del punto 7, sobre lo YA validado.

    Solo compara cuando los dos valores estan en `cleaned`: si la referencia es
    invalida su error ya esta pintado en su campo, si es invisible no aplica, y
    si no viene en este schema (el mini-schema de un paso) no hay regla que
    evaluar. `validate_schema` exige que ambos campos vivan en la misma seccion,
    asi que en el paso real la referencia siempre viaja.
    """
    by_key = {f.get("key"): f for f in fields if f.get("key")}
    for key, config in by_key.items():
        ref = _validation_de(config).get("gte_field")
        if not ref or key not in cleaned or ref not in cleaned:
            continue
        try:
            menor = int(cleaned[key]) < int(cleaned[ref])
        except (TypeError, ValueError):
            continue
        if menor:
            errors[key] = (f"{_label_corto(config)} no puede ser anterior a "
                           f"{_label_corto(by_key[ref])} ({cleaned[ref]})")
            del cleaned[key]


# ---------------------------------------------------------------------------
# Validacion de RESPUESTAS
# ---------------------------------------------------------------------------
def validate_answers(schema: dict, submitted: dict, *, today: date | None = None
                     ) -> tuple[bool, dict[str, str], dict]:
    """Valida respuestas contra el `schema`. Devuelve `(ok, errors, cleaned)`.

    `errors` va indexado POR LLAVE porque un cuestionario largo falla en varios
    campos a la vez y la pagina los pinta en linea (seccion 6.1). `cleaned` solo
    trae llaves del schema que resultaron VISIBLES y validas.

    `today` existe para las pruebas: la edad de un nacimiento y el `max:
    "current"` de un ano dependen del calendario. Sin el, "hoy" es el de la app.
    """
    errors: dict[str, str] = {}
    cleaned: dict = {}

    if not schema or not schema.get("enabled"):
        return True, {}, {}

    submitted = submitted or {}
    hoy = today or _hoy()
    fields = [f for f in (schema.get("fields") or []) if isinstance(f, dict)]

    for field_config in fields:
        field_key = field_config.get("key")
        field_type = field_config.get("type")
        is_required = bool(field_config.get("required", False))

        if not field_key or field_type not in FIELD_TYPES:
            continue                                   # delta 6, del lado del schema

        if not is_visible(field_config, submitted):
            continue                                   # delta 5: se descarta

        raw = submitted.get(field_key)
        if field_type in ("checkbox", "yesno"):
            field_value = _as_bool(raw)
        else:
            field_value = raw

        # — Obligatoriedad, por tipo —
        if is_required:
            if field_type == "multiselect":
                if not isinstance(field_value, list) or not field_value:
                    errors[field_key] = f"Selecciona al menos una opcion en '{_label(field_config)}'"
                    continue
            elif field_type == "checkbox":
                if field_value is not True:            # el test del original, intacto
                    errors[field_key] = f"Debe marcar '{_label(field_config)}'"
                    continue
            elif field_type == "yesno":
                if field_value is None:
                    errors[field_key] = f"El campo '{_label(field_config)}' es obligatorio"
                    continue
            elif field_type == "scale":
                if field_value is None or (isinstance(field_value, str)
                                           and not field_value.strip()):
                    errors[field_key] = f"El campo '{_label(field_config)}' es obligatorio"
                    continue
            else:
                if not field_value or (isinstance(field_value, str)
                                       and not field_value.strip()):
                    errors[field_key] = f"El campo '{_label(field_config)}' es obligatorio"
                    continue

        # — Vacio no obligatorio: ni error ni fila —
        if _is_empty(field_type, field_value):
            continue

        # — Validacion por tipo —
        if field_type in ("text", "textarea"):
            error, text = _validate_text(field_value, field_config, hoy)
            if error:
                errors[field_key] = error
                continue
            cleaned[field_key] = text

        elif field_type == "date":
            error, iso = _validate_date(field_value, field_config, hoy)
            if error:
                errors[field_key] = error
                continue
            cleaned[field_key] = iso

        elif field_type in ("select", "radio"):
            error = _validate_select(field_value, field_config)
            if error:
                errors[field_key] = error
                continue
            cleaned[field_key] = str(field_value)

        elif field_type in ("checkbox", "yesno"):
            cleaned[field_key] = bool(field_value)

        elif field_type == "scale":
            error, parsed = _validate_scale(field_value, field_config)
            if error:
                errors[field_key] = error
                continue
            cleaned[field_key] = parsed

        elif field_type == "multiselect":
            error, values = _validate_multiselect(field_value, field_config)
            if error:
                errors[field_key] = error
                continue
            cleaned[field_key] = values

    _aplicar_gte_field(fields, errors, cleaned)
    return not errors, errors, cleaned


# ---------------------------------------------------------------------------
# Validacion de la DEFINICION
# ---------------------------------------------------------------------------
def _errores_de_validation(key: str, field_type: str, validation: dict) -> list[str]:
    """Reglas del bloque `validation` de UN campo (puntos 4 y 7)."""
    errores: list[str] = []

    sobra = set(validation) - ALLOWED_VALIDATION_KEYS
    if sobra:
        errores.append(
            f"'{key}': `validation` no admite {', '.join(sorted(sobra))}: su vocabulario "
            f"es cerrado ({', '.join(sorted(ALLOWED_VALIDATION_KEYS))}).")

    for llave in ("minLength", "maxLength", "minAge", "maxAge"):
        if llave in validation and (not _es_entero(validation[llave]) or validation[llave] < 0):
            errores.append(f"'{key}': `{llave}` debe ser un entero no negativo.")
    for menor, mayor in (("minLength", "maxLength"), ("minAge", "maxAge")):
        a, b = validation.get(menor), validation.get(mayor)
        if _es_entero(a) and _es_entero(b) and a > b:
            errores.append(f"'{key}': `{menor}` no puede ser mayor que `{mayor}`.")

    if field_type == "date":
        ajenas = set(validation) & (ALLOWED_VALIDATION_KEYS - _AGE_KEYS)
        if ajenas:
            errores.append(f"'{key}': un campo date solo admite minAge/maxAge en `validation` "
                           f"(sobra: {', '.join(sorted(ajenas))}).")
        return errores

    if set(validation) & _AGE_KEYS:
        errores.append(f"'{key}': minAge/maxAge solo aplican a un campo date.")
    if field_type in ("text", "textarea") and "maxLength" not in validation:
        errores.append(f"'{key}': todo campo de texto DEBE declarar `validation.maxLength`.")

    formato = validation.get("format")
    parametros = set(validation) & _PARAM_KEYS
    if formato is None:
        if parametros:
            errores.append(f"'{key}': {', '.join(sorted(parametros))} solo existe como "
                           f"parametro de un `format`.")
        return errores
    if field_type != "text":
        errores.append(f"'{key}': `format` solo aplica a campos text, no a {field_type}.")
        return errores
    if not isinstance(formato, str) or formato not in _FORMAT_PARAMS:
        errores.append(f"'{key}': format desconocido '{formato}' "
                       f"(admitidos: {', '.join(TEXT_FORMATS)}).")
        return errores
    ajenos = parametros - _FORMAT_PARAMS[formato]
    if ajenos:
        errores.append(f"'{key}': el format {formato} no admite {', '.join(sorted(ajenos))}.")

    tope = validation.get("maxLength")
    if formato == "digits":
        largo = validation.get("length")
        if not _es_entero(largo) or largo < 1:
            errores.append(f"'{key}': el format digits necesita `length`, un entero mayor que 0.")
        elif _es_entero(tope) and tope < largo:
            errores.append(f"'{key}': `maxLength` ({tope}) no puede ser menor que "
                           f"`length` ({largo}).")
    elif formato == "phone":
        if _es_entero(tope) and tope < PHONE_DIGITS:
            errores.append(f"'{key}': un phone necesita `maxLength` de al menos {PHONE_DIGITS}.")
    elif formato == "year":
        bajo, alto = validation.get("min"), validation.get("max")
        if not _es_entero(bajo):
            errores.append(f"'{key}': el format year necesita `min` entero.")
        if not (_es_entero(alto) or alto == CURRENT_YEAR):
            errores.append(f"'{key}': el format year necesita `max` entero o \"{CURRENT_YEAR}\".")
        alto_hoy = _hoy().year if alto == CURRENT_YEAR else alto
        if _es_entero(bajo) and _es_entero(alto_hoy) and bajo > alto_hoy:
            errores.append(f"'{key}': `min` ({bajo}) no puede ser mayor que `max` ({alto}).")
        if _es_entero(tope) and tope < YEAR_DIGITS:
            errores.append(f"'{key}': un year necesita `maxLength` de al menos {YEAR_DIGITS}.")
    elif formato == "decimal":
        bajo, alto = validation.get("min"), validation.get("max")
        if not (_es_numero(bajo) and _es_numero(alto)):
            errores.append(f"'{key}': el format decimal necesita `min` y `max` numericos.")
        elif bajo >= alto:
            errores.append(f"'{key}': `min` debe ser menor que `max`.")
    return errores


def _errores_de_gte_field(key: str, field: dict, ref, by_key: dict) -> list[str]:
    """`gte_field` apunta a OTRO `year` de la MISMA seccion (punto 7)."""
    if not isinstance(ref, str) or not ref:
        return [f"'{key}': `gte_field` debe ser la llave de otro campo."]
    if ref == key:
        return [f"'{key}': `gte_field` no puede apuntar a si mismo."]
    otro = by_key.get(ref)
    if otro is None:
        return [f"'{key}': `gte_field` apunta a '{ref}', que no existe."]
    if not (otro.get("type") == "text" and _validation_de(otro).get("format") == "year"):
        return [f"'{key}': `gte_field` apunta a '{ref}', que no es un text con format year."]
    if otro.get("section") != field.get("section"):
        return [f"'{key}': `gte_field` apunta a '{ref}', de otra seccion: el paso valida solo "
                f"los campos de la suya y la regla no se evaluaria al avanzar."]
    return []


def validate_schema(schema: dict) -> tuple[bool, list[str]]:
    """Valida la DEFINICION de un formulario (al sembrarlo o editarlo).

    Devuelve `(ok, errores)` con la lista de mensajes, no indexada por llave: el
    destinatario es quien escribe el SQL de siembra, no un visitante.

    Reglas que no se pueden relajar:
      · todo `text`/`textarea` DEBE declarar `validation.maxLength` (seccion 4.1);
        sin eso no hay cota contra una columna `Text`;
      · `validation` es un vocabulario CERRADO (puntos 4 y 7): `format` solo en
        `text` y con sus propios parametros, `minAge`/`maxAge` solo en `date`, y
        cualquier combinacion que ningun valor podria satisfacer (`length` mayor
        que `maxLength`, `min` mayor que `max`) se rechaza aqui y no al primer
        egresado que se tope con ella;
      · solo `select`/`radio` pueden ser FUENTE de un `visible_when`. Se rechaza
        `multiselect`, `checkbox` y `yesno` por la MISMA razon: su forma en el
        cable no coincide con su forma en el schema (una lista contra un escalar;
        un `"on"` contra un `true`), asi que la igualdad exacta nunca casaria y
        el campo dependiente se descartaria en silencio, sin error, en cada
        envio real. Rechazarlo AQUI es ruidoso y gratis —salta al sembrar, con
        el autor delante y el arreglo a la vista—; descubrirlo al recibir
        respuestas es silencioso y caro: se pierde la respuesta de un alumno y
        nadie se entera. Quien quiera "muestra esto solo si marcan aquello"
        expresa la fuente como un `radio`/`select` de dos opciones.
    """
    errors: list[str] = []

    if not isinstance(schema, dict):
        return False, ["El esquema debe ser un objeto JSON."]

    fields = schema.get("fields")
    if not isinstance(fields, list) or not fields:
        return False, ["El esquema necesita una lista `fields` con al menos un campo."]

    sections = schema.get("sections") or []
    if not isinstance(sections, list):
        errors.append("`sections` debe ser una lista.")
        sections = []
    section_keys: set[str] = set()
    for section in sections:
        if not isinstance(section, dict) or not section.get("key"):
            errors.append("Cada seccion necesita una llave `key`.")
            continue
        section_keys.add(str(section["key"]))

    by_key: dict[str, dict] = {}
    for field in fields:
        if not isinstance(field, dict):
            errors.append("Cada campo debe ser un objeto JSON.")
            continue
        key = field.get("key")
        if not key or not isinstance(key, str):
            errors.append("Hay un campo sin `key`.")
            continue
        if key in by_key:
            errors.append(f"Llave repetida: '{key}'.")
            continue
        by_key[key] = field

    for key, field in by_key.items():
        field_type = field.get("type")
        if field_type not in FIELD_TYPES:
            errors.append(f"'{key}': tipo desconocido '{field_type}'.")
            continue
        if not field.get("label"):
            errors.append(f"'{key}': falta `label`.")

        section = field.get("section")
        if section is not None and str(section) not in section_keys:
            errors.append(f"'{key}': la seccion '{section}' no esta declarada en `sections`.")

        if field_type in TYPES_WITH_OPTIONS:
            values = _option_values(field)
            if not values:
                errors.append(f"'{key}': un campo {field_type} necesita `options`.")
            elif len(set(values)) != len(values):
                errors.append(f"'{key}': hay valores repetidos en `options`.")
        elif field.get("options"):
            errors.append(f"'{key}': un campo {field_type} no lleva `options`.")

        if field_type == "scale":
            block = field.get("scale")
            if not isinstance(block, dict):
                errors.append(f"'{key}': un campo scale necesita el bloque `scale`.")
            else:
                low, high = block.get("min"), block.get("max")
                if (not isinstance(low, int) or isinstance(low, bool)
                        or not isinstance(high, int) or isinstance(high, bool)
                        or low >= high):
                    errors.append(
                        f"'{key}': `scale.min` debe ser un entero menor que `scale.max`.")

        validation = field.get("validation") or {}
        if not isinstance(validation, dict):
            errors.append(f"'{key}': `validation` debe ser un objeto.")
            validation = {}
        errors.extend(_errores_de_validation(key, field_type, validation))
        if validation.get("gte_field") is not None:
            errors.extend(_errores_de_gte_field(key, field, validation["gte_field"], by_key))

        autocomplete = field.get("autocomplete")
        if autocomplete is not None:
            if field_type not in ("text", "date"):
                errors.append(f"'{key}': `autocomplete` solo aplica a campos text o date.")
            elif not isinstance(autocomplete, str) or autocomplete not in AUTOCOMPLETE_TOKENS:
                errors.append(f"'{key}': `autocomplete` '{autocomplete}' no esta en el "
                              f"vocabulario ({', '.join(sorted(AUTOCOMPLETE_TOKENS))}).")

        visible_when = field.get("visible_when")
        if visible_when is not None:
            if not isinstance(visible_when, dict) or not visible_when:
                errors.append(
                    f"'{key}': `visible_when` debe ser un objeto con al menos una condicion.")
            else:
                for source in visible_when:
                    if source == key:
                        errors.append(f"'{key}': `visible_when` no puede depender de si mismo.")
                    elif source not in by_key:
                        errors.append(f"'{key}': `visible_when` apunta a '{source}', que no existe.")
                    elif by_key[source].get("type") == "multiselect":
                        errors.append(
                            f"'{key}': `visible_when` no puede depender del multiselect "
                            f"'{source}': un multiselect manda lista y la comparacion "
                            f"(escalar o lista) nunca casaria.")
                    elif by_key[source].get("type") in ("checkbox", "yesno"):
                        errors.append(
                            f"'{key}': `visible_when` no puede depender del "
                            f"{by_key[source].get('type')} '{source}': el navegador lo "
                            f"envia como \"on\"/\"true\" y el schema lo declara como "
                            f"booleano, asi que la comparacion nunca casaria y "
                            f"'{key}' se descartaria en silencio. Usa un radio/select "
                            f"de dos opciones como fuente.")

    return not errors, errors
