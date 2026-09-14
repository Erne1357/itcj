"""Contrato del INSTRUMENTO REAL de la Encuesta de Egresados (Tarea 5).

Estas pruebas leen el esquema DE LA BASE (`titulatec_survey_forms`), nunca del
archivo `.sql`: lo que importa es lo que quedo sembrado, no lo que el DML dice
que va a sembrar. `database/DML/titulatec/survey_2026_09/11_seed_survey_form.sql`
esta gitignored (`database/` completo) y nunca llega a CI, asi que estas
pruebas dependen de que alguien ya haya corrido
`titulatec load-survey-2026-09` contra la base de dev (`itcj-postgres-1`) --
igual que ya asumen `test_public_routes.py:86-89` y
`test_public_survey_routes.py`, que documentan que "la BD de dev puede traer
ya la v1 sembrada por su seeder".

GUARDA `requires_dml` (patron de `test_permissions_contract.py` y
`test_cli_survey_delta.py`): `.github/workflows/deploy.yml` corre
`pytest tests/fastapi -q` como gate BLOQUEANTE contra un esquema construido
con `create_all`, sin ningun seeder -- `database/` nunca llega al checkout de
CI. Sin la guarda, `_form_egresados_v1` truena con `NoResultFound` en vez de
saltarse, y tumba el gate por una razon que no tiene nada que ver con un
defecto real. La guarda mira el ARCHIVO en disco, no "hay formulario en la
base": si alguien tiene `database/` completo y aun asi el formulario no esta
sembrado, eso SI es un fallo real que se quiere ver, no un skip.

Referencia: spec `docs/superpowers/specs/2026-09-14-titulatec-encuesta-egresados-design.md`,
seccion 4 (el instrumento). El mapa condicional exacto vive en la seccion 4.3;
la obligatoriedad en la 4.4.

`(code, version)` es unico (`uq_titulatec_survey_forms_code_version`), asi que
`_form_egresados_v1` puede pedir `.one()` sin riesgo de ambiguedad.
"""
from __future__ import annotations

from collections import Counter

import pytest

from itcj2.apps.titulatec.utils.survey_validator import validate_schema
from itcj2.cli.titulatec import DML_TITULATEC, _DML_SURVEY_2026_09_DIR

TRABAJA = ["Trabaja", "Estudia y trabaja"]
ESTUDIA = ["Estudia", "Estudia y trabaja"]

# D7: estas opciones eran la muleta de Forms por no tener logica condicional.
# Ahora ese trabajo lo hace `visible_when`, asi que ninguna debe sobrevivir en
# ninguna lista de `options` del instrumento sembrado.
MULETAS = {"No trabajo", "No estudio", "Desempleado (a)", "Ninguno", "Ninguno/otro"}

# El archivo concreto que este modulo verifica -- no solo el directorio -- para
# que el motivo del skip apunte exactamente a lo que hace falta recuperar.
_SEED_FILE = DML_TITULATEC / _DML_SURVEY_2026_09_DIR / "11_seed_survey_form.sql"

requires_dml = pytest.mark.skipif(
    not _SEED_FILE.exists(),
    reason=(
        "database/DML/titulatec/survey_2026_09/11_seed_survey_form.sql no esta "
        "en el checkout (gitignored a proposito: database/ lleva PII real y "
        "nunca llega a CI, que construye el esquema con create_all y sin "
        "seeders). Sin el archivo, nadie pudo correr "
        "`titulatec load-survey-2026-09` en esta base: 'egresados' v1 no "
        "existe y estas pruebas no tienen que leer."
    ),
)


def _form_egresados_v1(db_session):
    from itcj2.apps.titulatec.models import SurveyForm

    return (
        db_session.query(SurveyForm)
        .filter(SurveyForm.code == "egresados", SurveyForm.version == 1)
        .one()
    )


@requires_dml
def test_el_esquema_sembrado_pasa_el_validador(db_session):
    """`validate_schema` devuelve ok y lista de errores vacia."""
    form = _form_egresados_v1(db_session)

    ok, errores = validate_schema(form.schema)

    assert ok, errores
    assert errores == []


@requires_dml
def test_tiene_siete_secciones_en_el_orden_del_instrumento(db_session):
    form = _form_egresados_v1(db_session)
    secciones = form.schema["sections"]

    assert [s["key"] for s in secciones] == [
        "perfil",
        "pertinencia",
        "idiomas",
        "ubicacion_laboral",
        "desempeno",
        "participacion",
        "comentarios",
    ]
    # D1: los titulos se conservan tal cual los fija la seccion 4.1 del spec.
    assert [s["title"] for s in secciones] == [
        "Perfil del egresado",
        "Pertinencia y disponibilidad de medios y recursos para el aprendizaje",
        "Habilidades: idiomas",
        "Ubicación laboral de los egresados",
        "Desempeño profesional de los egresados",
        "Participación social de los egresados",
        "Comentarios y sugerencias",
    ]


@requires_dml
def test_tiene_las_55_preguntas_mas_las_nueve_escalas_de_la_49(db_session):
    """La 49 es una matriz y el motor no tiene matrices: son 9 campos scale
    bajo un encabezado comun. Nueve y no diez: la fila 'No trabajo' se fue."""
    form = _form_egresados_v1(db_session)
    fields = form.schema["fields"]

    assert len(fields) == 63

    # 55 preguntas - 1 (la 49, que se reparte) + 9 (sus escalas) = 63.
    # Por tipo (spec 4.2): 17 text, 36 radio, 9 scale (todas de la 49), 1 textarea.
    tipos = Counter(f["type"] for f in fields)
    assert tipos == {"text": 17, "radio": 36, "scale": 9, "textarea": 1}

    escalas = [f for f in fields if f["type"] == "scale"]
    assert len(escalas) == 9
    for f in escalas:
        assert f["scale"]["min"] == 1
        assert f["scale"]["max"] == 5
        assert "no trabajo" not in f["label"].lower()

    # Llaves unicas: el validador ya lo exige, pero lo dejamos explicito aqui
    # porque es la garantia de que 63 "fields" son 63 preguntas distinguibles,
    # no un campo repetido por accidente de copy-paste.
    keys = [f["key"] for f in fields]
    assert len(keys) == len(set(keys))


@requires_dml
def test_las_obligatorias_son_las_que_dice_el_spec(db_session):
    """1-50, 52, 54 y 55 obligatorias; 51 y 53 no marcadas required pero
    condicionadas."""
    form = _form_egresados_v1(db_session)
    fields = form.schema["fields"]
    by_key = {f["key"]: f for f in fields}

    requeridos = {f["key"] for f in fields if f.get("required")}
    no_requeridos = {f["key"] for f in fields if not f.get("required")}

    # 1-50 (50 preguntas, la 49 aporta sus 9 escalas) + 52 + 54 + 55 = 61.
    assert len(requeridos) == 61
    assert no_requeridos == {"nombre_org_social", "nombre_asoc_egresados"}

    # 51 y 53: NO required, pero SI condicionadas (el motor las exige solo
    # cuando son visibles -- seccion 4.4 del spec).
    assert not by_key["nombre_org_social"].get("required")
    assert not by_key["nombre_asoc_egresados"].get("required")
    assert by_key["nombre_org_social"]["visible_when"] == {"pertenece_org_social": "Si"}
    assert by_key["nombre_asoc_egresados"]["visible_when"] == {
        "pertenece_asoc_egresados": "Si"
    }

    # Piso explicito contra un desliz de un solo campo: si "48" o "50"
    # perdieran su required por error de transcripcion, el conteo de arriba ya
    # lo detecta, pero nombrar un par de anclas ayuda a ubicar el culpable.
    assert by_key["utilidad_residencias"]["required"] is True     # 48
    assert by_key["pertenece_org_social"]["required"] is True     # 50
    assert by_key["comentario_sugerencia"]["required"] is True    # 55


@requires_dml
def test_el_bloque_laboral_cuelga_de_la_26_con_lista(db_session):
    """Las preguntas del mapa condicional del spec (seccion 4.3) apuntan a la
    26 con listas: ['Trabaja', 'Estudia y trabaja'] y ['Estudia', 'Estudia y
    trabaja']. La condicion con lista es la que habilito la Tarea 1."""
    form = _form_egresados_v1(db_session)
    fields = form.schema["fields"]
    by_key = {f["key"]: f for f in fields}

    assert by_key["actividad_actual"]["type"] == "radio"
    opciones = {o["value"] for o in by_key["actividad_actual"]["options"]}
    assert opciones == {"Estudia", "Trabaja", "Estudia y trabaja", "No estudia, ni trabaja"}

    gated_trabaja = [f for f in fields
                     if f.get("visible_when") == {"actividad_actual": TRABAJA}]
    # 29-44 (16) + 47 (1) + las 9 escalas de la 49 = 26 CAMPOS reales (el spec
    # habla de 18 PREGUNTAS porque la 49 todavia era una sola en el papel).
    assert len(gated_trabaja) == 26, sorted(f["key"] for f in gated_trabaja)

    gated_estudia = [f for f in fields
                     if f.get("visible_when") == {"actividad_actual": ESTUDIA}]
    assert len(gated_estudia) == 2, sorted(f["key"] for f in gated_estudia)
    assert {f["key"] for f in gated_estudia} == {"tipo_estudio", "institucion_estudio"}

    # Las cuatro condiciones sueltas (escalar, no lista) del resto del mapa.
    assert by_key["que_idioma"]["visible_when"] == {"domina_otro_idioma": "Si"}
    assert by_key["nombre_empresa_propia"]["visible_when"] == {"empresa_propia": "Si"}
    assert by_key["nombre_org_social"]["visible_when"] == {"pertenece_org_social": "Si"}
    assert by_key["nombre_asoc_egresados"]["visible_when"] == {
        "pertenece_asoc_egresados": "Si"
    }

    # No condicionadas (spec 4.3): entre ellas 26, 45 y 48 -- si alguna de
    # estas tres cargara un visible_when por error, seria la fuente de una
    # cascada silenciosa (D26 gobierna a 20 campos).
    assert "visible_when" not in by_key["actividad_actual"]
    assert "visible_when" not in by_key["empresa_propia"]
    assert "visible_when" not in by_key["utilidad_residencias"]


@requires_dml
def test_ninguna_pregunta_conserva_la_opcion_muleta(db_session):
    """Ninguna opcion de ningun campo dice 'No trabajo', 'No estudio' ni
    'Desempleado': eso lo hace ahora la condicion (D7)."""
    form = _form_egresados_v1(db_session)
    fields = form.schema["fields"]

    for f in fields:
        for o in f.get("options", []):
            assert o["label"] not in MULETAS, f"{f['key']} conserva {o['label']!r}"
            assert o["value"] not in MULETAS, f"{f['key']} conserva {o['value']!r}"

    by_key = {f["key"]: f for f in fields}

    # De la 25 se va "Ninguno" pero se conserva "Otro" (spec 4.3).
    idioma_labels = [o["label"] for o in by_key["que_idioma"]["options"]]
    assert "Otro" in idioma_labels
    assert "Ninguno" not in idioma_labels

    # Puntos nombrados por el spec 4.3 donde vivia cada muleta.
    assert "Desempleado (a)" not in [o["label"] for o in by_key["condicion_trabajo"]["options"]]
    assert "No estudio" not in [o["label"] for o in by_key["tipo_estudio"]["options"]]
    assert len(by_key["nivel_jerarquico"]["options"]) == 11   # 12 - "No trabajo"


@requires_dml
def test_el_formulario_esta_abierto_y_no_es_anonimo(db_session):
    """version 1, status open, is_anonymous False: lo que la Tarea 2 necesita
    para exigir sesion."""
    from itcj2.apps.titulatec.models import SurveyForm

    form = _form_egresados_v1(db_session)

    assert form.version == 1
    assert form.status == "open"
    assert form.is_anonymous is False

    # El indice parcial uq_titulatec_survey_forms_open exige exactamente una
    # fila 'open' por code: lo confirmamos tambien por conteo directo.
    abiertos = (
        db_session.query(SurveyForm)
        .filter(SurveyForm.code == "egresados", SurveyForm.status == "open")
        .count()
    )
    assert abiertos == 1
