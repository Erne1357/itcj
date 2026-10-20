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
  4. `validation` es un vocabulario CERRADO: sin `pattern` ni regex libre;
  5. `visible_when` se evalua en el SERVIDOR;
  6. llave desconocida -> se descarta en silencio y NO llega a `cleaned`;
  7. (2026-09-15) formatos por campo -`digits`, `phone`, `year`, `decimal`,
     `email`, `person_name`-, el tipo `date` con edad acotada y la regla
     cruzada `gte_field`. Al final del archivo.
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
def test_los_nueve_tipos_soportados_son_exactamente_los_del_diseno():
    """Tabla de 4.1: los cinco de helpdesk (sin `file`) + scale/yesno/multiselect,
    y `date` desde el delta 7 (2026-09-15)."""
    assert FIELD_TYPES == {
        "text", "textarea", "select", "radio", "checkbox",
        "scale", "yesno", "multiselect", "date",
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


def test_multiselect_opcional_AUSENTE_no_es_error():
    """La llave NO viaja cuando no se marca ninguna casilla del grupo.

    Es distinto de `{"idiomas": []}` (el caso de arriba, con la llave presente):
    un navegador que envia un `multiselect` sin ninguna casilla marcada NO manda
    la llave, asi que el cuerpo llega SIN ella. Es el caso MAYORITARIO de todo
    campo opcional, y `_is_empty` lo tomaba por "no vacio" —`isinstance(None,
    list)` es falso— y lo mandaba a `_validate_multiselect`, que lo rechazaba
    con "se esperaba una lista de opciones". Resultado: un formulario entero
    invalidado por un campo que nadie estaba obligado a contestar, y sin manera
    de que el alumno adivine cual.
    """
    opcional = dict(F_MULTI, required=False)
    ok, errors, cleaned = validate_answers(_schema(opcional), {})
    assert (ok, errors, cleaned) == (True, {}, {})


def test_multiselect_REQUERIDO_y_ausente_sigue_fallando():
    """Contraparte de la de arriba: tratar el ausente como vacio no puede
    convertir un obligatorio en opcional. La rama de obligatoriedad corre ANTES
    de `_is_empty`, y este test es lo que lo mantiene asi."""
    ok, errors, cleaned = validate_answers(_schema(F_MULTI), {})
    assert ok is False
    assert "idiomas" in errors
    assert cleaned == {}


def test_multiselect_escalar_presente_SIGUE_siendo_error():
    """Guarda del delta 3. Tratar el ausente como vacio no debe abrir la puerta
    a que un no-lista se cuele: `"en"` presente sigue siendo un error, no un
    descarte silencioso."""
    opcional = dict(F_MULTI, required=False)
    ok, errors, cleaned = validate_answers(_schema(opcional), {"idiomas": "en"})
    assert ok is False
    assert "idiomas" in errors
    assert cleaned == {}


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


def test_validation_sigue_sin_admitir_pattern_ni_regex_libre():
    """Delta 4, revisado en el 7: el vocabulario de `validation` es CERRADO.

    Volvieron `min`/`max`, pero solo como parametros de un `format`; `pattern`
    -una regex escrita a mano en un seeder- sigue sin existir.
    """
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


# ===========================================================================
# visible_when con lista de valores — TASK 1
# ===========================================================================
def test_visible_when_con_lista_casa_con_cualquiera_de_los_valores():
    campo = {"key": "empresa", "type": "text",
             "visible_when": {"actividad": ["Trabaja", "Estudia y trabaja"]}}
    assert is_visible(campo, {"actividad": "Trabaja"})
    assert is_visible(campo, {"actividad": "Estudia y trabaja"})


def test_visible_when_con_lista_no_casa_con_un_valor_fuera():
    campo = {"key": "empresa", "type": "text",
             "visible_when": {"actividad": ["Trabaja", "Estudia y trabaja"]}}
    assert not is_visible(campo, {"actividad": "Estudia"})
    assert not is_visible(campo, {"actividad": None})
    assert not is_visible(campo, {})


def test_visible_when_con_un_solo_valor_se_comporta_igual_que_antes():
    """Guarda de no-regresion: los esquemas ya sembrados no cambian de conducta."""
    campo = {"key": "nombre_org", "type": "text", "visible_when": {"pertenece": "Si"}}
    assert is_visible(campo, {"pertenece": "Si"})
    assert not is_visible(campo, {"pertenece": "No"})


def test_una_lista_vacia_deja_el_campo_siempre_invisible():
    """No es un caso util, pero el comportamiento tiene que ser definido y no un crash."""
    campo = {"key": "x", "type": "text", "visible_when": {"a": []}}
    assert not is_visible(campo, {"a": "lo que sea"})


def test_validate_schema_rechaza_una_lista_cuya_fuente_no_es_select_ni_radio():
    """La restriccion de fuente existe porque un multiselect manda lista y un
    checkbox manda 'on': la condicion nunca casaria y el dependiente se
    descartaria EN SILENCIO. La lista no la relaja."""
    schema = {
        "sections": [{"key": "s1", "title": "S1"}],
        "fields": [
            {"key": "idiomas", "type": "multiselect", "label": "Idiomas",
             "section": "s1", "options": [{"value": "a"}, {"value": "b"}]},
            {"key": "cual", "type": "text", "label": "Cual", "section": "s1",
             "validation": {"maxLength": 60},
             "visible_when": {"idiomas": ["a", "b"]}},
        ],
    }
    ok, errores = validate_schema(schema)
    assert not ok
    assert any("idiomas" in e for e in errores)


# ===========================================================================
# Delta 7 (2026-09-15): formatos por campo, tipo `date` y regla cruzada
# ===========================================================================
# Todo lo que depende de "hoy" recibe `today` explicito: la edad de una fecha
# de nacimiento y el `max: "current"` de un ano cambian con el calendario, y
# una prueba que dependiera del reloj real se pondria roja sola un 1 de enero.
from datetime import date  # noqa: E402

from itcj2.apps.titulatec.utils.survey_validator import date_bounds  # noqa: E402

HOY = date(2026, 9, 15)

F_CONTROL = {"key": "no_control", "type": "text", "required": True, "label": "No. Control:",
             "validation": {"format": "digits", "length": 8, "maxLength": 8}}
F_TEL = {"key": "telefono", "type": "text", "required": True,
         "label": "Número telefónico (10 dígitos):",
         "validation": {"format": "phone", "maxLength": 20}}
F_INGRESO = {"key": "anio_ingreso", "type": "text", "required": True,
             "label": "Año de INGRESO (EJ. 1999)",
             "validation": {"format": "year", "min": 1950, "max": "current", "maxLength": 4}}
F_EGRESO = {"key": "anio_egreso", "type": "text", "required": True,
            "label": "Año de EGRESO (EJ. 1999)",
            "validation": {"format": "year", "min": 1950, "max": "current", "maxLength": 4,
                           "gte_field": "anio_ingreso"}}
F_PROMEDIO = {"key": "promedio_final", "type": "text", "required": True,
              "label": "Promedio final obtenido (Ej. 93 u 87.5)",
              "validation": {"format": "decimal", "min": 70, "max": 100, "maxLength": 6}}
F_CORREO = {"key": "correo_personal", "type": "text", "required": True,
            "label": "Correo Personal: (Cuenta electrónica que sea utilizada de forma continua)",
            "validation": {"format": "email", "maxLength": 150}}
F_NOMBRE = {"key": "nombre_completo", "type": "text", "required": True,
            "label": "Nombre (s) y Apellidos completos: (Sino escribe de forma correcta su información)",
            "validation": {"format": "person_name", "maxLength": 200}}
F_NACIMIENTO = {"key": "fecha_nacimiento", "type": "date", "required": True,
                "label": "Fecha de nacimiento", "validation": {"minAge": 15, "maxAge": 90}}


def _uno(campo, valor, today=HOY):
    """Valida UN campo con `valor`: `(ok, su_error_o_None, su_valor_limpio_o_None)`."""
    ok, errors, cleaned = validate_answers(_schema(campo), {campo["key"]: valor}, today=today)
    return ok, errors.get(campo["key"]), cleaned.get(campo["key"])


# --------------------------------------------------------------------------
# El mensaje lleva el rotulo del campo, sin la pista de formato del rotulo
# --------------------------------------------------------------------------
def test_el_mensaje_usa_el_rotulo_sin_lo_que_sigue_a_los_dos_puntos_ni_el_parentesis_final():
    """El instrumento trae rotulos de FORMULARIO («No. Control:», «Año de INGRESO
    (EJ. 1999)»). Pegados tal cual a «debe tener…» meten el ejemplo en medio del
    error; el rotulo recortado sigue diciendo de que campo se habla."""
    assert _uno(F_CONTROL, "123")[1] == "No. Control debe tener exactamente 8 dígitos"
    assert _uno(F_INGRESO, "12")[1] == "Año de INGRESO debe ser un año de 4 dígitos entre 1950 y 2026"


# --------------------------------------------------------------------------
# digits
# --------------------------------------------------------------------------
@pytest.mark.parametrize("valor", ["90200001", " 90200001 "])
def test_digits_acepta_exactamente_length_digitos_sin_espacios_alrededor(valor):
    assert _uno(F_CONTROL, valor) == (True, None, "90200001")


@pytest.mark.parametrize("valor", [
    "9020001",          # 7: el caso del alumno que se come un digito
    "902000011",        # 9: el mensaje es el del formato, no el de maxLength
    "9020000A",
    "9020 0001",
    "-9020000",
    "٩٠٢٠٠٠٠١",         # ocho digitos arabigo-indicos: `isdigit()` los aceptaria
])
def test_digits_rechaza_otro_largo_o_lo_que_no_son_digitos_ascii(valor):
    ok, error, limpio = _uno(F_CONTROL, valor)
    assert (ok, limpio) == (False, None), valor
    assert error == "No. Control debe tener exactamente 8 dígitos", valor


# --------------------------------------------------------------------------
# phone
# --------------------------------------------------------------------------
@pytest.mark.parametrize("valor", ["6561234567", "656 123 4567", "(656) 123-4567", "656.123.4567"])
def test_phone_acepta_diez_digitos_con_separadores_comunes_y_guarda_solo_digitos(valor):
    """Quien escribe «656 123 4567» SI escribio diez digitos: rechazarlo culpa al
    visitante de un formato que nadie le pidio. Se guarda normalizado."""
    assert _uno(F_TEL, valor) == (True, None, "6561234567")


@pytest.mark.parametrize("valor", ["656123456", "65612345678", "+52 656 123 4567", "656-123-45ab"])
def test_phone_rechaza_lo_que_no_son_exactamente_diez_digitos(valor):
    ok, error, limpio = _uno(F_TEL, valor)
    assert (ok, limpio) == (False, None), valor
    assert error == "Número telefónico debe tener exactamente 10 dígitos", valor


# --------------------------------------------------------------------------
# year
# --------------------------------------------------------------------------
@pytest.mark.parametrize("valor", ["1950", "1999", "2026"])
def test_year_acepta_los_bordes_del_rango(valor):
    assert _uno(F_INGRESO, valor) == (True, None, valor)


@pytest.mark.parametrize("valor", ["1949", "2027", "99", "20155", "20a5", "2015.0"])
def test_year_rechaza_fuera_de_rango_o_lo_que_no_es_un_anio_de_4_digitos(valor):
    ok, error, limpio = _uno(F_INGRESO, valor)
    assert (ok, limpio) == (False, None), valor
    assert error == "Año de INGRESO debe ser un año de 4 dígitos entre 1950 y 2026", valor


def test_year_max_current_se_resuelve_contra_hoy():
    assert _uno(F_INGRESO, "2027", today=date(2027, 1, 1))[0] is True
    assert _uno(F_INGRESO, "2027", today=date(2026, 12, 31))[0] is False


# --------------------------------------------------------------------------
# decimal
# --------------------------------------------------------------------------
@pytest.mark.parametrize("valor,limpio", [
    ("93", "93"), ("87.5", "87.5"), ("87.50", "87.50"),
    ("87,5", "87.5"),          # coma decimal: se acepta y se guarda con punto
    ("70", "70"), ("100", "100"), ("100.00", "100.00"), (" 90 ", "90"),
])
def test_decimal_acepta_hasta_dos_decimales_con_punto_o_coma(valor, limpio):
    assert _uno(F_PROMEDIO, valor) == (True, None, limpio)


@pytest.mark.parametrize("valor", ["69.99", "100.01", "0"])
def test_decimal_fuera_de_rango(valor):
    ok, error, limpio = _uno(F_PROMEDIO, valor)
    assert (ok, limpio) == (False, None), valor
    assert error == "Promedio final obtenido debe estar entre 70 y 100", valor


@pytest.mark.parametrize("valor", ["87.555", "abc", "-80", "1e2", ".5", "87.", "8 7"])
def test_decimal_con_forma_invalida(valor):
    ok, error, limpio = _uno(F_PROMEDIO, valor)
    assert (ok, limpio) == (False, None), valor
    assert error == ("Promedio final obtenido debe ser un número con hasta 2 decimales "
                     "(por ejemplo 93 u 87.5)"), valor


# --------------------------------------------------------------------------
# email
# --------------------------------------------------------------------------
@pytest.mark.parametrize("valor", ["andrea@example.com", " andrea.r+egresados@correo.mx "])
def test_email_acepta_un_correo_valido_sin_espacios_alrededor(valor):
    assert _uno(F_CORREO, valor) == (True, None, valor.strip())


@pytest.mark.parametrize("valor", ["andrea@", "andrea example.com", "a@b", "@example.com"])
def test_email_rechaza_un_correo_invalido(valor):
    ok, error, limpio = _uno(F_CORREO, valor)
    assert (ok, limpio) == (False, None), valor
    assert error == "Correo Personal no es un correo válido (por ejemplo, nombre@dominio.com)"


def test_email_delega_en_is_valid_email_del_core_y_no_copia_su_regex(monkeypatch):
    """Una copia de la regex aqui divergiria de la del core en silencio."""
    from itcj2.core.utils import email_tools

    monkeypatch.setattr(email_tools, "is_valid_email", lambda value: value == "SOLO-ESTE")
    assert _uno(F_CORREO, "SOLO-ESTE")[0] is True
    assert _uno(F_CORREO, "andrea@example.com")[0] is False


# --------------------------------------------------------------------------
# person_name
# --------------------------------------------------------------------------
@pytest.mark.parametrize("valor,limpio", [
    ("María José Núñez", "María José Núñez"),
    ("Ana-Lucía O'Connor", "Ana-Lucía O'Connor"),
    ("Günther Müller", "Günther Müller"),
    ("D’Angelo Peña", "D’Angelo Peña"),
    ("  Ana   María  ", "Ana María"),
    ("José Pérez", "José Pérez"),     # descompuesto (NFD) -> NFC
    ("Li", "Li"),
])
def test_person_name_acepta_letras_unicode_espacios_guion_y_apostrofo(valor, limpio):
    assert _uno(F_NOMBRE, valor) == (True, None, limpio)


@pytest.mark.parametrize("valor", ["Ana2", "Ma. Guadalupe", "Ana_María", "<b>Ana</b>", "Ana@"])
def test_person_name_rechaza_digitos_y_signos(valor):
    """El punto tambien: el diseno cierra el conjunto en letras, espacios, guion y
    apostrofo. Medido en dev: 0 de los 37 alumnos con proceso llevan uno."""
    ok, error, limpio = _uno(F_NOMBRE, valor)
    assert (ok, limpio) == (False, None), valor
    assert error == ("Nombre (s) y Apellidos completos solo puede llevar letras, espacios, "
                     "guion y apóstrofo"), valor


@pytest.mark.parametrize("valor", ["A", "-", "--", "'-"])
def test_person_name_exige_al_menos_dos_letras(valor):
    ok, error, limpio = _uno(F_NOMBRE, valor)
    assert (ok, limpio) == (False, None), valor
    assert error == "Nombre (s) y Apellidos completos debe tener al menos 2 letras", valor


def test_un_campo_con_formato_opcional_y_vacio_no_es_error_ni_llega_a_cleaned():
    opcional = dict(F_TEL, required=False)
    assert validate_answers(_schema(opcional), {"telefono": "  "}, today=HOY) == (True, {}, {})


# --------------------------------------------------------------------------
# date
# --------------------------------------------------------------------------
@pytest.mark.parametrize("valor", [
    "2000-01-01",
    "2011-09-15",       # cumple 15 HOY: ya entra
    "1935-09-16",       # tiene 90 y cumple 91 manana: todavia entra
    "2000-02-29",       # bisiesto
])
def test_date_acepta_una_fecha_real_dentro_de_la_edad(valor):
    assert _uno(F_NACIMIENTO, valor) == (True, None, valor)


@pytest.mark.parametrize("valor", [
    "2000-02-30", "2001-02-29", "2000-13-01",
    "01/01/2000",       # la forma que pedia el rotulo viejo
    "20000101",         # `date.fromisoformat` de 3.11 SI la aceptaria
    "2000-1-1", "hoy", "0000-01-01",
])
def test_date_rechaza_lo_que_no_es_una_fecha_iso_real(valor):
    ok, error, limpio = _uno(F_NACIMIENTO, valor)
    assert (ok, limpio) == (False, None), valor
    assert error == "Fecha de nacimiento no es una fecha válida", valor


def test_date_respeta_min_age_contra_hoy():
    ok, error, _ = _uno(F_NACIMIENTO, "2011-09-16")          # cumple 15 manana
    assert (ok, error) == (False, "Fecha de nacimiento indica una edad menor a 15 años")


def test_date_respeta_max_age_contra_hoy():
    ok, error, _ = _uno(F_NACIMIENTO, "1935-09-15")          # cumple 91 hoy
    assert (ok, error) == (False, "Fecha de nacimiento indica una edad mayor a 90 años")


def test_date_con_edad_acotada_no_admite_una_fecha_futura():
    ok, error, _ = _uno(F_NACIMIENTO, "2026-09-16")
    assert (ok, error) == (False, "Fecha de nacimiento no puede ser una fecha futura")


def test_date_sin_edad_admite_cualquier_fecha_real():
    libre = {"key": "fecha_evento", "type": "date", "required": True, "label": "Fecha del evento"}
    assert _uno(libre, "2030-01-01") == (True, None, "2030-01-01")


def test_date_opcional_vacia_no_es_error_ni_llega_a_cleaned():
    opcional = dict(F_NACIMIENTO, required=False)
    assert validate_answers(_schema(opcional), {"fecha_nacimiento": ""}, today=HOY) == (True, {}, {})


def test_date_bounds_usa_la_misma_aritmetica_que_la_validacion():
    """El `min`/`max` del `<input type="date">` sale de aqui: si divergiera de la
    validacion, el selector ofreceria fechas que el servidor rechaza."""
    assert date_bounds(F_NACIMIENTO, today=HOY) == {"min": "1935-09-16", "max": "2011-09-15"}
    assert _uno(F_NACIMIENTO, "1935-09-16")[0] and _uno(F_NACIMIENTO, "2011-09-15")[0]
    assert not _uno(F_NACIMIENTO, "1935-09-15")[0]
    assert not _uno(F_NACIMIENTO, "2011-09-16")[0]


def test_date_bounds_un_29_de_febrero_no_revienta_y_sus_bordes_validan():
    hoy = date(2028, 2, 29)
    limites = date_bounds(F_NACIMIENTO, today=hoy)
    assert limites == {"min": "1937-03-01", "max": "2013-02-28"}
    for borde in limites.values():
        assert _uno(F_NACIMIENTO, borde, today=hoy)[0] is True, borde


def test_date_bounds_sin_edad_no_acota():
    assert date_bounds({"key": "f", "type": "date", "label": "F"}, today=HOY) == {}


# --------------------------------------------------------------------------
# gte_field: anio_egreso >= anio_ingreso
# --------------------------------------------------------------------------
def _anios(ingreso, egreso):
    return validate_answers(_schema(F_INGRESO, F_EGRESO),
                            {"anio_ingreso": ingreso, "anio_egreso": egreso}, today=HOY)


def test_gte_field_acepta_egreso_igual_o_posterior_al_ingreso():
    assert _anios("2015", "2020") == (True, {}, {"anio_ingreso": "2015", "anio_egreso": "2020"})
    assert _anios("2015", "2015")[0] is True


def test_gte_field_rechaza_egreso_anterior_y_marca_el_campo_que_declara_la_regla():
    ok, errors, cleaned = _anios("2020", "2015")
    assert ok is False
    assert errors == {"anio_egreso": "Año de EGRESO no puede ser anterior a Año de INGRESO (2020)"}
    assert cleaned == {"anio_ingreso": "2020"}


def test_gte_field_no_compara_contra_un_valor_invalido():
    """El error ya es del otro campo: repetirlo aqui culparia al equivocado."""
    ok, errors, _ = _anios("20a0", "2015")
    assert ok is False
    assert set(errors) == {"anio_ingreso"}


def test_gte_field_con_la_referencia_fuera_del_schema_no_revienta():
    """Un mini-schema de paso sin la referencia no tiene regla que evaluar."""
    ok, errors, cleaned = validate_answers(
        _schema(F_EGRESO), {"anio_ingreso": "2020", "anio_egreso": "2015"}, today=HOY)
    assert (ok, errors, cleaned) == (True, {}, {"anio_egreso": "2015"})


def test_gte_field_con_la_referencia_invisible_no_se_evalua():
    fuente = {"key": "egresado", "type": "radio", "required": True, "label": "Egresaste?",
              "options": [{"value": "si", "label": "Si"}, {"value": "no", "label": "No"}]}
    ingreso = dict(F_INGRESO, visible_when={"egresado": "si"})
    ok, errors, cleaned = validate_answers(
        _schema(fuente, ingreso, F_EGRESO),
        {"egresado": "no", "anio_ingreso": "2020", "anio_egreso": "2015"}, today=HOY)
    assert (ok, errors) == (True, {})
    assert "anio_ingreso" not in cleaned and cleaned["anio_egreso"] == "2015"


# --------------------------------------------------------------------------
# validate_schema: el vocabulario cerrado del lado de la DEFINICION
# --------------------------------------------------------------------------
SCHEMA_FORMATOS = {
    "enabled": True,
    "sections": [{"key": "perfil", "title": "Perfil del egresado"}],
    "fields": [dict(f, section="perfil") for f in (
        F_NOMBRE, F_CONTROL, F_NACIMIENTO, F_CORREO, F_TEL, F_INGRESO, F_EGRESO, F_PROMEDIO)],
}


def test_validate_schema_acepta_los_seis_formatos_date_y_gte_field():
    ok, errors = validate_schema(SCHEMA_FORMATOS)
    assert ok is True, errors


def _con_validation(tipo, validation):
    campo = {"key": "x", "type": tipo, "label": "X", "validation": validation}
    return {"enabled": True, "fields": [campo]}


@pytest.mark.parametrize("tipo,validation,pista", [
    ("text", {"maxLength": 20, "format": "regex"}, "regex"),
    ("text", {"maxLength": 20, "pattern": "^[0-9]+$"}, "pattern"),
    ("textarea", {"maxLength": 20, "format": "email"}, "format"),
    ("yesno", {"format": "email"}, "format"),
    ("text", {"maxLength": 20, "length": 8}, "length"),          # length sin format
    ("text", {"maxLength": 20, "min": 1}, "min"),                # min sin format
    ("text", {"maxLength": 8, "format": "digits"}, "length"),    # digits sin length
    ("text", {"maxLength": 8, "format": "digits", "length": 0}, "length"),
    ("text", {"maxLength": 8, "format": "digits", "length": True}, "length"),
    ("text", {"maxLength": 7, "format": "digits", "length": 8}, "maxLength"),
    ("text", {"maxLength": 20, "format": "phone", "length": 10}, "length"),
    ("text", {"maxLength": 9, "format": "phone"}, "maxLength"),
    ("text", {"maxLength": 4, "format": "year", "max": "current"}, "min"),
    ("text", {"maxLength": 4, "format": "year", "min": 1950}, "max"),
    ("text", {"maxLength": 4, "format": "year", "min": 1950, "max": "tomorrow"}, "max"),
    ("text", {"maxLength": 4, "format": "year", "min": 2000, "max": 1990}, "min"),
    ("text", {"maxLength": 3, "format": "year", "min": 1950, "max": "current"}, "maxLength"),
    ("text", {"maxLength": 6, "format": "decimal", "min": 100, "max": 70}, "min"),
    ("text", {"maxLength": 6, "format": "decimal", "min": "70", "max": 100}, "min"),
    ("text", {"maxLength": 6, "format": "decimal", "min": 70, "max": 100, "gte_field": "y"},
     "gte_field"),
    ("text", {"maxLength": 20, "minAge": 15}, "minAge"),
    ("date", {"maxLength": 10}, "maxLength"),
    ("date", {"format": "digits"}, "format"),
    ("date", {"minAge": 90, "maxAge": 15}, "minAge"),
    ("date", {"minAge": -1}, "minAge"),
])
def test_validate_schema_rechaza_combinaciones_invalidas(tipo, validation, pista):
    ok, errors = validate_schema(_con_validation(tipo, validation))
    assert ok is False, validation
    assert any(pista in e for e in errors), errors


def test_gte_field_debe_apuntar_a_un_year_existente_de_la_misma_seccion():
    """Misma seccion: el paso valida un mini-schema con SOLO los campos de su
    seccion, y una regla cuya referencia viviera en otro paso no se evaluaria
    nunca al avanzar."""
    base = {"enabled": True, "sections": [{"key": "a", "title": "A"}, {"key": "b", "title": "B"}]}
    egreso = dict(F_EGRESO, section="a")

    def definicion(*fields):
        return validate_schema(dict(base, fields=list(fields)))

    ok, errors = definicion(egreso)
    assert not ok and any("anio_ingreso" in e for e in errors), errors

    a_si_mismo = dict(egreso, validation=dict(egreso["validation"], gte_field="anio_egreso"))
    ok, errors = definicion(a_si_mismo)
    assert not ok and any("si mismo" in e for e in errors), errors

    no_year = {"key": "anio_ingreso", "section": "a", "type": "text", "label": "Ingreso",
               "validation": {"maxLength": 4}}
    ok, errors = definicion(egreso, no_year)
    assert not ok and any("year" in e for e in errors), errors

    ok, errors = definicion(egreso, dict(F_INGRESO, section="b"))
    assert not ok and any("seccion" in e for e in errors), errors

    ok, errors = definicion(egreso, dict(F_INGRESO, section="a"))
    assert ok, errors


def test_autocomplete_es_un_vocabulario_cerrado_y_solo_para_text_o_date():
    """El telefono del encargado de RH no es el del egresado: sin poder decir
    `off`, el navegador ofreceria autollenarlo con el suyo."""
    assert validate_schema({"enabled": True, "fields": [dict(F_TEL, autocomplete="off")]})[0]

    ok, errors = validate_schema({"enabled": True, "fields": [dict(F_TEL, autocomplete="telefono")]})
    assert not ok and any("autocomplete" in e for e in errors), errors

    ok, errors = validate_schema({"enabled": True, "fields": [dict(F_RADIO, autocomplete="off")]})
    assert not ok and any("autocomplete" in e for e in errors), errors
