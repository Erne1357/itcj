"""Validador de la encuesta de egresados: el DELTA sobre el port de helpdesk.

Pruebas puras: ni BD, ni `client`, ni fixtures del conftest. El modulo bajo
prueba (`utils/survey_validator.py`) no importa nada de `itcj2` a proposito, asi
que estas pruebas corren igual contra la CI de base vacia.

Origen: `itcj2/apps/helpdesk/utils/custom_fields_validator.py`. El delta que se
verifica aqui es el de la seccion 4.3 del diseno:

  1. firma `(ok, errors, cleaned)` en vez de `(ok, errors)`;
  2. tipos nuevos `scale`, `yesno`, `multiselect`;
  3. `multiselect` exige LISTA, valida cada elemento y "requerido" significa
     lista no vacia (NO se reutiliza el `field_value is not True` de checkbox,
     que da verdadero para cualquier lista);
  4. solo sobreviven `minLength`/`maxLength`;
  5. `visible_when` se evalua en el SERVIDOR;
  6. llave desconocida -> se descarta en silencio y NO llega a `cleaned`.
"""
from __future__ import annotations

import pytest

from itcj2.apps.titulatec.utils.survey_validator import (
    FIELD_TYPES,
    TYPES_WITH_OPTIONS,
    is_visible,
    validate_answers,
)


# --------------------------------------------------------------------------
# Esquemas de apoyo
# --------------------------------------------------------------------------
def _schema(*fields, enabled=True):
    return {"enabled": enabled, "fields": list(fields)}


F_RADIO = {
    "key": "situacion_laboral", "type": "radio", "required": True,
    "label": "Cual es tu situacion laboral actual?",
    "options": [
        {"value": "empleado", "label": "Trabajando"},
        {"value": "buscando", "label": "Buscando empleo"},
        {"value": "estudiando", "label": "Estudiando"},
    ],
}

F_SCALE = {
    "key": "relacion_carrera", "type": "scale", "required": True,
    "label": "Que tanto se relaciona tu empleo con tu carrera?",
    "scale": {"min": 1, "max": 5,
              "min_label": "Nada relacionado", "max_label": "Totalmente relacionado"},
    "visible_when": {"situacion_laboral": "empleado"},
}

F_MULTI = {
    "key": "idiomas", "type": "multiselect", "required": True,
    "label": "Idiomas que dominas",
    "options": [
        {"value": "en", "label": "Ingles"},
        {"value": "fr", "label": "Frances"},
        {"value": "de", "label": "Aleman"},
    ],
}

F_TEXT = {
    "key": "comentario", "type": "textarea", "required": False,
    "label": "Comentarios", "validation": {"minLength": 5, "maxLength": 40},
}

F_CHECK = {"key": "aviso", "type": "checkbox", "required": True,
           "label": "Acepto el aviso de privacidad"}

F_YESNO = {"key": "recomendarias", "type": "yesno", "required": True,
           "label": "Recomendarias el Tec?"}


# --------------------------------------------------------------------------
# Superficie del modulo
# --------------------------------------------------------------------------
def test_los_ocho_tipos_soportados_son_exactamente_los_del_diseno():
    """Tabla de 4.1: los cinco de helpdesk (sin `file`) + scale/yesno/multiselect."""
    assert FIELD_TYPES == {
        "text", "textarea", "select", "radio", "checkbox",
        "scale", "yesno", "multiselect",
    }
    assert TYPES_WITH_OPTIONS == {"select", "radio", "multiselect"}


def test_un_schema_deshabilitado_acepta_cualquier_cosa_sin_limpiar_nada():
    """Puerta `enabled` del original (custom_fields_validator.py:18)."""
    ok, errors, cleaned = validate_answers(
        _schema(F_RADIO, enabled=False), {"situacion_laboral": "lo-que-sea"})
    assert (ok, errors, cleaned) == (True, {}, {})


# --------------------------------------------------------------------------
# Obligatoriedad y tipos escalares
# --------------------------------------------------------------------------
def test_un_requerido_ausente_da_error_con_su_llave():
    ok, errors, cleaned = validate_answers(_schema(F_RADIO), {})
    assert ok is False
    assert "situacion_laboral" in errors
    assert cleaned == {}


def test_un_valor_fuera_de_options_es_invalido():
    ok, errors, _ = validate_answers(
        _schema(F_RADIO), {"situacion_laboral": "jubilado"})
    assert ok is False
    assert "situacion_laboral" in errors


def test_el_caso_feliz_devuelve_cleaned_con_el_valor():
    ok, errors, cleaned = validate_answers(
        _schema(F_RADIO), {"situacion_laboral": "empleado"})
    assert (ok, errors) == (True, {})
    assert cleaned == {"situacion_laboral": "empleado"}


def test_minlength_y_maxlength_son_las_unicas_validaciones_de_texto():
    corto = validate_answers(_schema(F_TEXT), {"comentario": "hola"})
    largo = validate_answers(_schema(F_TEXT), {"comentario": "x" * 41})
    justo = validate_answers(_schema(F_TEXT), {"comentario": "todo bien"})
    assert corto[0] is False and "comentario" in corto[1]
    assert largo[0] is False and "comentario" in largo[1]
    assert justo[0] is True and justo[2] == {"comentario": "todo bien"}


def test_checkbox_conserva_el_test_de_helpdesk_is_not_true():
    """`checkbox` sigue siendo el booleano UNICO de consentimiento (4.1)."""
    sin_marcar = validate_answers(_schema(F_CHECK), {"aviso": False})
    marcado = validate_answers(_schema(F_CHECK), {"aviso": True})
    assert sin_marcar[0] is False and "aviso" in sin_marcar[1]
    assert marcado[0] is True and marcado[2] == {"aviso": True}


def test_checkbox_acepta_el_on_nativo_del_html_y_rechaza_lo_demas():
    """Un `<input type="checkbox">` marcado envia la cadena `"on"`, no `True`.

    La normalizacion a booleano corre ANTES de la rama de obligatoriedad
    justamente por esto: sin ella el `is not True` heredado del original
    rechazaria un consentimiento REAL y el aviso de privacidad seria
    imposible de aceptar desde el formulario publico.
    """
    marcado = validate_answers(_schema(F_CHECK), {"aviso": "on"})
    assert marcado[0] is True
    assert marcado[2] == {"aviso": True}
    for sin_marcar in ("false", "off", "0", ""):
        ok, errors, cleaned = validate_answers(_schema(F_CHECK), {"aviso": sin_marcar})
        assert ok is False, sin_marcar
        assert "aviso" in errors, sin_marcar
        assert cleaned == {}, sin_marcar


def test_yesno_acepta_booleano_y_la_cadena_del_formulario():
    """El cuerpo llega de `await request.form()`: todo es cadena."""
    for enviado in (True, "true", "on", "1", "si"):
        ok, errors, cleaned = validate_answers(
            _schema(F_YESNO), {"recomendarias": enviado})
        assert (ok, errors) == (True, {}), enviado
        assert cleaned == {"recomendarias": True}, enviado
    ok, _, cleaned = validate_answers(_schema(F_YESNO), {"recomendarias": "false"})
    assert ok is True and cleaned == {"recomendarias": False}


# --------------------------------------------------------------------------
# scale
# --------------------------------------------------------------------------
def test_scale_acepta_un_entero_dentro_del_rango_y_lo_devuelve_como_int():
    schema = _schema(F_RADIO, F_SCALE)
    ok, errors, cleaned = validate_answers(
        schema, {"situacion_laboral": "empleado", "relacion_carrera": "4"})
    assert (ok, errors) == (True, {})
    assert cleaned["relacion_carrera"] == 4
    assert isinstance(cleaned["relacion_carrera"], int)


def test_scale_con_min_cero_no_descarta_el_cero_como_si_fuera_vacio():
    """El `if not field_value: continue` del original tirarian este `0`.

    `_is_empty` existe precisamente para eso: en una escala que empieza en 0,
    el 0 ES una respuesta. El borrador viaja como JSON, asi que el valor puede
    volver ya como entero y no como cadena.
    """
    campo = {"key": "meses_busqueda", "type": "scale", "required": True,
             "label": "Meses que llevas buscando empleo",
             "scale": {"min": 0, "max": 10}}
    ok, errors, cleaned = validate_answers(_schema(campo), {"meses_busqueda": 0})
    assert (ok, errors) == (True, {})
    assert cleaned == {"meses_busqueda": 0}


@pytest.mark.parametrize("valor", ["0", "6", "-1", "cuatro", "3.5"])
def test_scale_fuera_de_rango_o_no_entero_es_error(valor):
    schema = _schema(F_RADIO, F_SCALE)
    ok, errors, cleaned = validate_answers(
        schema, {"situacion_laboral": "empleado", "relacion_carrera": valor})
    assert ok is False, valor
    assert "relacion_carrera" in errors, valor
    assert "relacion_carrera" not in cleaned, valor


# --------------------------------------------------------------------------
# multiselect — el delta con mas filo
# --------------------------------------------------------------------------
def test_multiselect_requerido_con_dos_opciones_validas_pasa():
    ok, errors, cleaned = validate_answers(_schema(F_MULTI), {"idiomas": ["en", "fr"]})
    assert (ok, errors) == (True, {})
    assert cleaned == {"idiomas": ["en", "fr"]}


def test_multiselect_colapsa_los_repetidos_para_no_duplicar_filas():
    """4.4 escribe UNA fila de `survey_answers` por opcion marcada.

    Sin colapsar, un POST publico que repite la misma opcion N veces escribe N
    filas identicas. Colapsar + validar cada elemento contra `options` es lo
    unico que acota las filas de un campo a `len(options)`.
    """
    ok, errors, cleaned = validate_answers(
        _schema(F_MULTI), {"idiomas": ["en", "en", "fr", "en"]})
    assert (ok, errors) == (True, {})
    assert cleaned == {"idiomas": ["en", "fr"]}


def test_multiselect_con_un_elemento_fuera_de_options_falla():
    ok, errors, cleaned = validate_answers(_schema(F_MULTI), {"idiomas": ["en", "klingon"]})
    assert ok is False
    assert "idiomas" in errors
    assert "idiomas" not in cleaned


def test_multiselect_que_no_es_lista_falla_en_vez_de_pasar_en_silencio():
    """Un no-lista NO puede colarse. Es el caso que `_validate_select` dejaria pasar."""
    ok, errors, cleaned = validate_answers(_schema(F_MULTI), {"idiomas": "en"})
    assert ok is False
    assert "idiomas" in errors
    assert cleaned == {}


def test_multiselect_requerido_con_lista_vacia_falla():
    """Con el test de checkbox (`is not True`) una lista vacia habria pasado."""
    ok, errors, _ = validate_answers(_schema(F_MULTI), {"idiomas": []})
    assert ok is False
    assert "idiomas" in errors


def test_multiselect_no_requerido_y_vacio_no_es_error_ni_llega_a_cleaned():
    opcional = dict(F_MULTI, required=False)
    ok, errors, cleaned = validate_answers(_schema(opcional), {"idiomas": []})
    assert (ok, errors, cleaned) == (True, {}, {})


# --------------------------------------------------------------------------
# visible_when en el SERVIDOR
# --------------------------------------------------------------------------
def test_is_visible_es_igualdad_exacta_y_conjuncion():
    campo = {"visible_when": {"a": "1", "b": "2"}}
    assert is_visible(campo, {"a": "1", "b": "2"}) is True
    assert is_visible(campo, {"a": "1", "b": "3"}) is False
    assert is_visible({}, {}) is True


def test_un_requerido_oculto_no_se_exige():
    """El cliente oculto no basta: el servidor decide. Condicion falsa -> no aplica."""
    schema = _schema(F_RADIO, F_SCALE)
    ok, errors, cleaned = validate_answers(schema, {"situacion_laboral": "estudiando"})
    assert (ok, errors) == (True, {})
    assert cleaned == {"situacion_laboral": "estudiando"}


def test_un_campo_con_condicion_falsa_se_descarta_aunque_venga_relleno():
    """Delta 5: se DESCARTA, no se guarda. Es el cliente bajo control del atacante."""
    schema = _schema(F_RADIO, F_SCALE)
    ok, errors, cleaned = validate_answers(
        schema, {"situacion_laboral": "buscando", "relacion_carrera": "5"})
    assert (ok, errors) == (True, {})
    assert "relacion_carrera" not in cleaned


def test_un_requerido_visible_por_su_condicion_si_se_exige():
    schema = _schema(F_RADIO, F_SCALE)
    ok, errors, _ = validate_answers(schema, {"situacion_laboral": "empleado"})
    assert ok is False
    assert "relacion_carrera" in errors


# --------------------------------------------------------------------------
# Llaves desconocidas
# --------------------------------------------------------------------------
def test_una_llave_desconocida_se_descarta_en_silencio():
    """Delta 6: no es error (el schema pudo cambiar) y no llega a `cleaned`."""
    ok, errors, cleaned = validate_answers(
        _schema(F_RADIO),
        {"situacion_laboral": "empleado", "sueldo": "999999", "website": "bot"})
    assert (ok, errors) == (True, {})
    assert cleaned == {"situacion_laboral": "empleado"}


# ===========================================================================
# validate_schema — el lado de la DEFINICION (al sembrar o editar un formulario)
# ===========================================================================
from itcj2.apps.titulatec.utils.survey_validator import validate_schema  # noqa: E402


SCHEMA_V1 = {
    "enabled": True,
    "sections": [{"key": "empleo", "title": "Situacion laboral"}],
    "fields": [dict(F_RADIO, section="empleo"), dict(F_SCALE, section="empleo")],
}


def test_el_schema_v1_del_diseno_es_valido():
    """El de la seccion 4.2, tal cual lo sembrara `11_seed_survey_form.sql`."""
    ok, errors = validate_schema(SCHEMA_V1)
    assert ok is True, errors


def test_un_schema_sin_fields_se_rechaza():
    ok, errors = validate_schema({"enabled": True, "fields": []})
    assert ok is False and errors


def test_un_tipo_desconocido_se_rechaza():
    ok, errors = validate_schema(
        {"enabled": True, "fields": [{"key": "x", "type": "file", "label": "Archivo"}]})
    assert ok is False
    assert any("file" in e for e in errors)


def test_un_texto_sin_maxlength_se_rechaza():
    """Seccion 4.1: sin `maxLength` no hay cota contra una columna Text."""
    ok, errors = validate_schema(
        {"enabled": True,
         "fields": [{"key": "libre", "type": "textarea", "label": "Comentario"}]})
    assert ok is False
    assert any("maxLength" in e for e in errors)


def test_validation_solo_admite_minlength_y_maxlength():
    """Delta 4: `pattern`, `min` y `max` no existen en este dialecto."""
    ok, errors = validate_schema(
        {"enabled": True,
         "fields": [{"key": "libre", "type": "text", "label": "Nombre",
                     "validation": {"maxLength": 40, "pattern": "^[a-z]+$"}}]})
    assert ok is False
    assert any("pattern" in e for e in errors)


def test_un_select_sin_options_se_rechaza():
    ok, errors = validate_schema(
        {"enabled": True, "fields": [{"key": "s", "type": "select", "label": "Elige"}]})
    assert ok is False and errors


def test_un_multiselect_no_puede_ser_fuente_de_visible_when():
    """La comparacion de `visible_when` es escalar: contra una lista nunca casa."""
    ok, errors = validate_schema({
        "enabled": True,
        "fields": [
            F_MULTI,
            {"key": "cual", "type": "text", "label": "Cual usas mas?",
             "validation": {"maxLength": 60}, "visible_when": {"idiomas": "en"}},
        ],
    })
    assert ok is False
    assert any("idiomas" in e for e in errors)


def test_un_checkbox_no_puede_ser_fuente_de_visible_when():
    """El navegador manda `"on"`; el schema declara `true`. Nunca casan.

    Sin este rechazo el dependiente se descarta EN SILENCIO en cada envio real
    (verificado: `validate_answers` devolvia `ok=True` y `detalle` no aparecia
    en `cleaned`). Se caza al sembrar, con el autor delante, no al recibir.
    """
    ok, errors = validate_schema({
        "enabled": True,
        "fields": [
            F_CHECK,
            {"key": "detalle", "type": "text", "label": "Cuentanos mas",
             "validation": {"maxLength": 60}, "visible_when": {"aviso": True}},
        ],
    })
    assert ok is False
    assert any("aviso" in e for e in errors)


def test_un_yesno_no_puede_ser_fuente_de_visible_when():
    """Mismo desajuste cable/schema que el checkbox, misma resolucion."""
    ok, errors = validate_schema({
        "enabled": True,
        "fields": [
            F_YESNO,
            {"key": "por_que", "type": "text", "label": "Por que?",
             "validation": {"maxLength": 60}, "visible_when": {"recomendarias": True}},
        ],
    })
    assert ok is False
    assert any("recomendarias" in e for e in errors)


@pytest.mark.parametrize("tipo", ["radio", "select"])
def test_un_radio_o_select_si_puede_ser_fuente_de_visible_when(tipo):
    """La regla NO es "sin fuentes": `select`/`radio` mandan la cadena de
    `options`, que es exactamente lo que el `visible_when` declara.

    Esta prueba existe para que el rechazo no se ensanche por un edit posterior
    hasta dejar `visible_when` inservible.
    """
    ok, errors = validate_schema({
        "enabled": True,
        "fields": [
            dict(F_RADIO, type=tipo),
            dict(F_SCALE),
        ],
    })
    assert ok is True, errors


def test_visible_when_hacia_una_llave_inexistente_se_rechaza():
    ok, errors = validate_schema({
        "enabled": True,
        "fields": [dict(F_SCALE, visible_when={"no_existe": "empleado"})],
    })
    assert ok is False
    assert any("no_existe" in e for e in errors)


def test_una_seccion_no_declarada_se_rechaza():
    ok, errors = validate_schema(
        {"enabled": True, "sections": [], "fields": [dict(F_RADIO, section="empleo")]})
    assert ok is False
    assert any("empleo" in e for e in errors)


def test_llaves_repetidas_se_rechazan():
    ok, errors = validate_schema({"enabled": True, "fields": [F_RADIO, F_RADIO]})
    assert ok is False
    assert any("situacion_laboral" in e for e in errors)
