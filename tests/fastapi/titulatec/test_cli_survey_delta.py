"""Contrato del comando `titulatec load-survey-2026-09`.

Por que existe
--------------
Los `RAISE NOTICE` del DML son INVISIBLES: nada en `itcj2/` lee
`connection.notices`, asi que sin una verificacion posterior el operador ve
"OK" pase lo que pase — incluido el caso en que el rol al que se concede el
permiso no existe todavia y el `INSERT ... SELECT` inserta CERO filas sin
error. Es el mismo motivo por el que `itcj2/cli/directory.py:78-95` tiene
`_verify_settings_permission`, y este comando esta calcado de aquel.

`execute_sql_file` se importa DENTRO de la funcion del comando (import local,
convencion del proyecto contra los circulares), asi que el patch va sobre el
modulo FUENTE `itcj2.cli.core`, no sobre `itcj2.cli.titulatec`.
"""
from unittest.mock import patch

from click.testing import CliRunner

from itcj2.cli.titulatec import (
    SEED_FILES,
    _DML_SURVEY_2026_09_FILES,
    _SURVEY_2026_09_PERMS,
    load_survey_2026_09_command,
)


def test_el_delta_esta_en_seed_files_con_su_prefijo_de_subcarpeta():
    """Sin esto, una base NUEVA (`core seed-reference-data`) nace sin los 8.

    `_titulatec_seed_files()` (itcj2/cli/core.py:205-215) hace
    `f"titulatec/{name}"` y el bucle de `seed_reference_data_command`
    (`:346-352`) OMITE EN SILENCIO el archivo que no existe, saliendo 0.
    """
    for nombre in _DML_SURVEY_2026_09_FILES:
        assert f"survey_2026_09/{nombre}" in SEED_FILES, (
            f"{nombre} no esta en SEED_FILES con el prefijo survey_2026_09/")


def test_los_ocho_codigos_del_delta_son_los_del_contrato():
    assert set(_SURVEY_2026_09_PERMS) == {
        "titulatec.survey.page.list",
        "titulatec.survey.api.read",
        "titulatec.survey.api.export",
        "titulatec.survey.api.manage",
        "titulatec.enrollment_request.page.list",
        "titulatec.enrollment_request.api.approve",
        "titulatec.enrollment_request.api.reject",
        "titulatec.process.api.requirement.mark",
    }


def test_dry_run_no_ejecuta_sql_ni_verifica():
    with patch("itcj2.cli.core.execute_sql_file") as ejecutar, \
         patch("itcj2.cli.titulatec._verify_survey_2026_09") as verificar:
        res = CliRunner().invoke(load_survey_2026_09_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    ejecutar.assert_not_called()
    verificar.assert_not_called()
    assert "[dry-run]" in res.output


def test_corre_los_cuatro_archivos_del_delta_y_ninguno_mas():
    with patch("itcj2.cli.core.execute_sql_file", return_value=True) as ejecutar, \
         patch("itcj2.cli.titulatec._verify_survey_2026_09", return_value=[]):
        res = CliRunner().invoke(load_survey_2026_09_command, [])

    assert res.exit_code == 0, res.output
    corridos = [str(c.args[0]) for c in ejecutar.call_args_list]
    assert len(corridos) == 4, corridos
    for nombre in _DML_SURVEY_2026_09_FILES:
        assert any(r.endswith(nombre) for r in corridos), f"no corrio {nombre}"
    # NUNCA el DML base: el 03 revocaria permisos concedidos a mano.
    assert not any("03_insert_role_permissions" in r for r in corridos), corridos


def test_aborta_si_la_verificacion_reporta_un_permiso_sin_aterrizar():
    with patch("itcj2.cli.core.execute_sql_file", return_value=True), \
         patch("itcj2.cli.titulatec._verify_survey_2026_09",
               return_value=["sin grant a la jefatura: titulatec.survey.api.export"]):
        res = CliRunner().invoke(load_survey_2026_09_command, [])

    assert res.exit_code != 0, "un delta a medias NO puede salir 0"
    assert "titulatec.survey.api.export" in res.output
