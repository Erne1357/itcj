"""Especialidades de la encuesta de egresados agrupadas por carrera (2026-10-08).

Las opciones de un campo con opciones pueden traer `group` (un texto o una
LISTA de textos). La lista desplegable (un `select`, o un `radio` de 20+
opciones) se pinta con un `<optgroup>` por grupo, en orden alfabetico en
espanol; una opcion de varias carreras sale bajo cada una con el MISMO valor.
Lo que viaja, se valida y se guarda no cambia.

El delta `survey_2026_10/26_especialidades_por_carrera.sql` (gitignored) y su
comando `titulatec init-especialidades` aplican eso al formulario abierto.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from tests.fastapi.titulatec.test_permissions_contract import requires_dml

SURVEY_URL = "/titulatec/encuesta-egresados"
ARCHIVO = "survey_2026_10/26_especialidades_por_carrera.sql"
ONCE = "survey_2026_09/11_seed_survey_form.sql"
QUINCE = "15_grant_admin_all_perms.sql"
DML = Path(__file__).resolve().parents[3] / "database" / "DML" / "titulatec"

OPCIONES = [
    {"value": "Diseño (Ing. Mecánica)", "label": "Diseño", "group": "Ing. Mecánica"},
    {"value": "No tiene", "label": "No tiene"},
    {"value": "Diseño (Ing. Electromecánica)", "label": "Diseño", "group": "Ing. Electromecánica"},
    {"value": "Montaje", "label": "Tecnología de montaje superficial",
     "group": ["Ing. Mecánica", "Ing. Electromecánica"]},
    {"value": "Auto (Ing. Electromecánica)", "label": "Automatización",
     "group": "Ing. Electromecánica"},
    {"value": "Energía (Ing. Eléctrica)", "label": "Sistemas eficientes de energía",
     "group": "Ing. Eléctrica"},
]


def _schema(opciones):
    # 20+ opciones: el `radio` se pinta como <select> (umbral de survey_form.html).
    relleno = [{"value": f"x{i}", "label": f"Relleno {i}", "group": "Ing. Industrial"}
               for i in range(1, 16)]
    return {
        "enabled": True,
        "sections": [{"key": "perfil", "title": "Perfil del egresado"},
                     {"key": "cierre", "title": "Cierre"}],
        "fields": [
            {"key": "especialidad", "section": "perfil", "type": "radio",
             "label": "Especialidad", "required": True, "options": opciones + relleno},
            {"key": "comentario", "section": "cierre", "type": "textarea",
             "label": "Comentario", "required": False, "validation": {"maxLength": 200}},
        ],
    }


# ---------------------------------------------------------------------------
# option_groups
# ---------------------------------------------------------------------------
def test_sin_group_no_agrupa():
    from itcj2.apps.titulatec.utils.survey_validator import option_groups

    assert option_groups([{"value": "a", "label": "A"}]) is None
    assert option_groups([]) is None
    assert option_groups(None) is None


def test_grupos_en_orden_alfabetico_espanol_y_sueltas_al_final():
    from itcj2.apps.titulatec.utils.survey_validator import option_groups

    grupos = option_groups(OPCIONES)
    nombres = [g for g, _ in grupos]
    # «Eléctrica» antes de «Electromecánica»: un sort por código lo invierte.
    assert nombres == ["Ing. Eléctrica", "Ing. Electromecánica", "Ing. Mecánica", None]
    assert [o["value"] for o in grupos[-1][1]] == ["No tiene"]


def test_opciones_ordenadas_por_etiqueta_y_compartidas_en_cada_grupo():
    from itcj2.apps.titulatec.utils.survey_validator import option_groups

    grupos = dict(option_groups(OPCIONES))
    assert [o["label"] for o in grupos["Ing. Electromecánica"]] == [
        "Automatización", "Diseño", "Tecnología de montaje superficial"]
    assert [o["value"] for o in grupos["Ing. Mecánica"]] == [
        "Diseño (Ing. Mecánica)", "Montaje"]
    assert "Montaje" in [o["value"] for o in grupos["Ing. Electromecánica"]]


# ---------------------------------------------------------------------------
# validate_schema
# ---------------------------------------------------------------------------
def test_validate_schema_acepta_group_texto_o_lista():
    from itcj2.apps.titulatec.utils.survey_validator import validate_schema

    ok, errores = validate_schema(_schema(OPCIONES))
    assert ok, errores


@pytest.mark.parametrize("malo", ["", "   ", [], ["Ing. Mecánica", ""], [3], 7, None])
def test_validate_schema_rechaza_group_vacio_o_raro(malo):
    from itcj2.apps.titulatec.utils.survey_validator import validate_schema

    opciones = [{"value": "a", "label": "A", "group": malo}]
    ok, errores = validate_schema(_schema(opciones))
    assert not ok
    assert any("`group`" in e for e in errores), errores


# ---------------------------------------------------------------------------
# Pintado
# ---------------------------------------------------------------------------
def _select(cuerpo: str) -> str:
    m = re.search(r'<select\b[^>]*\bname="especialidad"[^>]*>(.*?)</select>', cuerpo, flags=re.S)
    assert m, "no se pinto el <select> de especialidad"
    return m.group(1)


def test_la_lista_sale_con_optgroup_por_carrera(client_as, make_student, make_survey_form):
    make_survey_form(schema=_schema(OPCIONES))

    html = _select(client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text)

    grupos = re.findall(r'<optgroup label="([^"]*)">', html)
    assert grupos == ["Ing. Eléctrica", "Ing. Electromecánica", "Ing. Industrial", "Ing. Mecánica"]
    # La compartida sale en las dos carreras, con el MISMO valor.
    assert len(re.findall(r'<option value="Montaje"', html)) == 2
    # «No tiene» fuera de todo grupo y al final.
    assert html.rstrip().endswith('<option value="No tiene">No tiene</option>')
    # El texto visible es la etiqueta corta; el valor sigue siendo el de siempre.
    assert '<option value="Diseño (Ing. Mecánica)">Diseño</option>' in html


def test_la_compartida_del_borrador_se_marca_una_sola_vez(
    client_as, make_student, make_survey_form, db_session,
):
    from itcj2.apps.titulatec.models import SurveyDraft

    schema = _schema(OPCIONES)
    # Una obligatoria vacia en el MISMO paso: sin ella `_start_step` salta a
    # 'cierre' (especialidad ya contestada) y el <select> no se pinta.
    schema["fields"].insert(1, {
        "key": "carrera", "section": "perfil", "type": "radio", "label": "Carrera",
        "required": True, "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]})
    form = make_survey_form(schema=schema)
    student = make_student()
    db_session.add(SurveyDraft(form_id=form.id, user_id=student.id,
                               answers={"especialidad": "Montaje"}))
    db_session.flush()

    html = _select(client_as(student).get(SURVEY_URL, follow_redirects=False).text)

    assert html.count(" selected>") == 1, html
    assert '<option value="Montaje" selected>' in html


def test_sin_group_la_lista_sigue_igual(client_as, make_student, make_survey_form):
    opciones = [{"value": f"e{i}", "label": f"Esp {i}"} for i in range(1, 21)]
    schema = _schema([])
    schema["fields"][0]["options"] = opciones
    make_survey_form(schema=schema)

    html = _select(client_as(make_student()).get(SURVEY_URL, follow_redirects=False).text)

    assert "<optgroup" not in html
    assert re.findall(r'<option value="([^"]*)"', html) == [""] + [f"e{i}" for i in range(1, 21)]


# ---------------------------------------------------------------------------
# Importador de Forms: una etiqueta repetida no decide la carrera
# ---------------------------------------------------------------------------
def _normalize(raw):
    from itcj2.apps.titulatec.services.survey_import_service import SurveyImportService

    campo = {"key": "especialidad", "type": "radio", "options": OPCIONES}
    return SurveyImportService.normalize(campo, raw)


def test_import_empata_primero_por_valor():
    assert _normalize("Diseño (Ing. Electromecánica)") == ("Diseño (Ing. Electromecánica)", False)


def test_import_con_etiqueta_unica_empata():
    assert _normalize("Automatización") == ("Auto (Ing. Electromecánica)", False)


def test_import_con_etiqueta_repetida_se_guarda_crudo():
    valor, crudo = _normalize("Diseño")
    assert crudo is True and valor == "Diseño"


# ---------------------------------------------------------------------------
# CLI y DML
# ---------------------------------------------------------------------------
def test_seed_files_tiene_el_26_despues_del_11_y_el_15_al_final():
    from itcj2.cli.titulatec import SEED_FILES

    assert ARCHIVO in SEED_FILES
    assert SEED_FILES.index(ONCE) < SEED_FILES.index(ARCHIVO) < SEED_FILES.index(QUINCE)
    assert SEED_FILES[-1] == QUINCE


def test_el_comando_corre_solo_el_26_y_verifica():
    from itcj2.cli import titulatec as cli

    with patch.object(cli, "_run_sql_files") as correr, \
            patch.object(cli, "_verify_especialidades", return_value=[]) as verificar:
        res = CliRunner().invoke(cli.init_especialidades_command, [])

    assert res.exit_code == 0, res.output
    correr.assert_called_once_with([ARCHIVO])
    verificar.assert_called_once_with()


def test_el_comando_aborta_si_no_aterrizo():
    from itcj2.cli import titulatec as cli

    with patch.object(cli, "_run_sql_files"), \
            patch.object(cli, "_verify_especialidades",
                         return_value=["opciones de especialidad sin carrera: ['x']"]):
        res = CliRunner().invoke(cli.init_especialidades_command, [])

    assert res.exit_code != 0


@requires_dml
def test_dry_run_no_ejecuta_nada():
    from itcj2.cli import titulatec as cli

    with patch.object(cli, "_run_sql_files") as correr:
        res = CliRunner().invoke(cli.init_especialidades_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    correr.assert_not_called()
    assert ARCHIVO in res.output
    assert ONCE not in res.output


def _opciones_del_sql() -> list[dict]:
    sql = (DML / ARCHIVO).read_text(encoding="utf-8")
    m = re.search(r"\$json\$(.*?)\$json\$", sql, flags=re.S)
    assert m, "el 26 no trae su bloque $json$"
    return json.loads(m.group(1))


@requires_dml
def test_el_sql_sobrevive_al_cargador_y_no_quita_valores():
    sql = (DML / ARCHIVO).read_text(encoding="utf-8")
    bloque = re.search(r"\$json\$(.*?)\$json\$", sql, flags=re.S).group(1)
    # `execute_sql_file` borra lo que sigue a `--` y `text()` toma `:palabra` por parametro.
    assert "--" not in bloque
    assert not re.search(r":\S", bloque)
    assert "code = 'egresados' AND status = 'open'" in sql
    assert "Se perderian opciones del formulario abierto" in sql   # guarda de valores


@requires_dml
def test_las_opciones_del_sql_son_validas_y_todas_tienen_carrera():
    from itcj2.apps.titulatec.utils.survey_validator import option_group_names, validate_schema

    opciones = _opciones_del_sql()
    schema = _schema([])
    schema["fields"][0]["options"] = opciones
    ok, errores = validate_schema(schema)
    assert ok, errores
    assert [o["value"] for o in opciones if not option_group_names(o)] == ["No tiene"]
