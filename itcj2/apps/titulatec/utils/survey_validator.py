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
  4. Desaparecen `file`/`maxSize`/`allowedExtensions`. En el bloque `validation`
     solo sobreviven `minLength` y `maxLength`; `pattern`, `min` y `max` no
     existen (`scale` lleva sus propios min/max en su bloque).
  5. `visible_when` corre en el SERVIDOR. Un requerido oculto en el cliente
     sigue siendo requerido cuando su condicion se cumple, y un campo con
     condicion falsa se DESCARTA en vez de guardarse. Solo `select` y `radio`
     pueden ser FUENTE de una condicion: `validate_schema` rechaza al resto
     porque su forma en el cable no coincide con su forma en el schema.
  6. Llave desconocida -> se descarta en silencio (el schema pudo cambiar) y no
     llega a `cleaned`.

El cuerpo llega de `await request.form()`, asi que todo valor escalar puede ser
cadena: `yesno`/`checkbox` se normalizan a booleano ANTES de la rama de
obligatoriedad, para que `checkbox` conserve literalmente el `is not True` del
original y no lo haga verdadero un `"on"`.

Modulo puro a proposito: no importa nada de `itcj2`, no toca BD y no conoce
`Request`. Se prueba con `pytest` sin harness.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("itcj2.apps.titulatec.utils.survey_validator")

FIELD_TYPES = {
    "text", "textarea", "select", "radio", "checkbox",
    "scale", "yesno", "multiselect",
}
TYPES_WITH_OPTIONS = {"select", "radio", "multiselect"}
ALLOWED_VALIDATION_KEYS = {"minLength", "maxLength"}

_TRUE_WORDS = {"true", "on", "1", "si", "sí", "yes", "y"}
_FALSE_WORDS = {"false", "off", "0", "no", "n", ""}


# ---------------------------------------------------------------------------
# Helpers de lectura
# ---------------------------------------------------------------------------
def _label(config: dict) -> str:
    return str(config.get("label") or config.get("key") or "campo")


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
        return isinstance(value, list) and not value
    if field_type in ("checkbox", "yesno"):
        return value is None
    if value is None:
        return True
    return isinstance(value, str) and not value.strip()


# ---------------------------------------------------------------------------
# Visibilidad (delta 5)
# ---------------------------------------------------------------------------
def is_visible(field: dict, submitted: dict) -> bool:
    """Evalua `visible_when` en el SERVIDOR: igualdad exacta, conjuncion (AND).

    Portado de `_check_visibility` (`custom_fields_validator.py:68-74`). Compara
    contra el valor CRUDO enviado, que es lo que emite el radio/select fuente.

    Por eso `validate_schema` solo admite `select`/`radio` como FUENTE: un tipo
    cuya codificacion en el navegador difiere de su codificacion en el schema
    jamas puede satisfacer una igualdad exacta. Un `multiselect` manda una lista;
    un `checkbox` manda `"on"` y el schema declara `true`; un `yesno` igual. En
    los tres casos la condicion nunca casa, el dependiente se toma por invisible
    y su respuesta se descarta EN SILENCIO — justo el fallo que evaluar
    `visible_when` en el servidor existe para evitar.
    """
    visible_when = field.get("visible_when")
    if not visible_when:
        return True
    for key, expected in visible_when.items():
        if submitted.get(key) != expected:
            return False
    return True


# ---------------------------------------------------------------------------
# Validadores por tipo — devuelven mensaje de error o None
# ---------------------------------------------------------------------------
def _validate_text(value, config: dict) -> str | None:
    validation = config.get("validation") or {}
    text = str(value)
    if "minLength" in validation and len(text) < validation["minLength"]:
        return f"{_label(config)} debe tener al menos {validation['minLength']} caracteres"
    if "maxLength" in validation and len(text) > validation["maxLength"]:
        return f"{_label(config)} no puede exceder {validation['maxLength']} caracteres"
    return None


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


# ---------------------------------------------------------------------------
# Validacion de RESPUESTAS
# ---------------------------------------------------------------------------
def validate_answers(schema: dict, submitted: dict) -> tuple[bool, dict[str, str], dict]:
    """Valida respuestas contra el `schema`. Devuelve `(ok, errors, cleaned)`.

    `errors` va indexado POR LLAVE porque un cuestionario largo falla en varios
    campos a la vez y la pagina los pinta en linea (seccion 6.1). `cleaned` solo
    trae llaves del schema que resultaron VISIBLES y validas.
    """
    errors: dict[str, str] = {}
    cleaned: dict = {}

    if not schema or not schema.get("enabled"):
        return True, {}, {}

    submitted = submitted or {}

    for field_config in (schema.get("fields") or []):
        if not isinstance(field_config, dict):
            continue
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
            error = _validate_text(field_value, field_config)
            if error:
                errors[field_key] = error
                continue
            cleaned[field_key] = str(field_value)

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

    return not errors, errors, cleaned


# ---------------------------------------------------------------------------
# Validacion de la DEFINICION
# ---------------------------------------------------------------------------
def validate_schema(schema: dict) -> tuple[bool, list[str]]:
    """Valida la DEFINICION de un formulario (al sembrarlo o editarlo).

    Devuelve `(ok, errores)` con la lista de mensajes, no indexada por llave: el
    destinatario es quien escribe el SQL de siembra, no un visitante.

    Reglas que no se pueden relajar:
      · todo `text`/`textarea` DEBE declarar `validation.maxLength` (seccion 4.1);
        sin eso no hay cota contra una columna `Text`;
      · `validation` solo admite `minLength`/`maxLength` (delta 4);
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
        sobra = set(validation) - ALLOWED_VALIDATION_KEYS
        if sobra:
            errors.append(
                f"'{key}': `validation` solo admite minLength/maxLength "
                f"(sobra: {', '.join(sorted(sobra))}).")
        if field_type in ("text", "textarea") and "maxLength" not in validation:
            errors.append(f"'{key}': todo campo de texto DEBE declarar `validation.maxLength`.")

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
                            f"'{source}': la comparacion es escalar y nunca casaria.")
                    elif by_key[source].get("type") in ("checkbox", "yesno"):
                        errors.append(
                            f"'{key}': `visible_when` no puede depender del "
                            f"{by_key[source].get('type')} '{source}': el navegador lo "
                            f"envia como \"on\"/\"true\" y el schema lo declara como "
                            f"booleano, asi que la igualdad exacta nunca casaria y "
                            f"'{key}' se descartaria en silencio. Usa un radio/select "
                            f"de dos opciones como fuente.")

    return not errors, errors
