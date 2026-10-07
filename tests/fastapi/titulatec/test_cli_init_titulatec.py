"""Contrato del comando `titulatec init-titulatec` (MINOR de la revision final,
tests-deploy: `itcj2/cli/titulatec.py:736-837` y `:261`).

`_verify_computer_center()` no tenia ninguna prueba, y tampoco la
ACUMULACION de problemas de las TRES verificaciones que corre
`init_titulatec_command` al terminar (`_verify_survey_2026_09` +
`_verify_titulacion` + `_verify_computer_center`, `:261`): un problema SOLO
del ultimo debe abortar igual que uno del primero.

Se parchea `_run_sql_files` entera (no `itcj2.cli.core.execute_sql_file`,
como hace `test_cli_survey_delta.py`): esa funcion es quien comprueba que
los `.sql` existan en disco (`itcj2/cli/titulatec.py:179-188`) antes de
llegar a `execute_sql_file`. Al reemplazarla por completo, esta prueba corre
en CI SIN `database/` en el checkout — no necesita ningun `requires_dml`.
"""
from unittest.mock import patch

from click.testing import CliRunner

from itcj2.cli.titulatec import (
    SEED_FILES,
    _PERM_PROCESS_SUMMARY,
    _PERMISOS_HANDOFF,
    _PERMISOS_RETIRADOS_TITULACION,
    _PERMISOS_ROL_TITULACION,
    _PERMISOS_ROL_TITULACIONES_DIV,
    _ROL_JEFATURA_ESCOLARES,
    _ROL_OPERATIVO_ESCOLARES,
    _ROL_TITULACION,
    _ROL_TITULACIONES_DIV,
    _problemas_grants_titulacion,
    init_titulatec_command,
)

# Spec 2026-10-07-titulatec-liberados-biblioteca-helpdesk, D1 + D7/D8: el set
# EXACTO del Departamento de Titulacion (16) y los 7 que pierde de los 22 de
# antes. Literales a proposito (no se importan las constantes para fijarlas):
# cambiarlos es decision de producto.
_TITULACION_16 = {
    "titulatec.process.api.read.all",
    "titulatec.process.page.summary",
    "titulatec.process.api.approve_phase", "titulatec.process.api.reject_phase",
    "titulatec.process.api.cancel", "titulatec.process.api.hold",
    "titulatec.document.api.approve", "titulatec.document.api.reject",
    "titulatec.format_b.api.approve", "titulatec.format_b.api.reject",
    "titulatec.ceremony.api.create", "titulatec.ceremony.api.update",
    "titulatec.notifications.api.read.own", "titulatec.notifications.api.mark_read",
    "titulatec.handoff.page.list", "titulatec.handoff.api.export",
}
_RETIRADOS = {
    "titulatec.dashboard.titulaciones",
    "titulatec.process.page.list",
    "titulatec.process.page.detail",
    "titulatec.document.page.list",
    "titulatec.document.api.read.all",
    "titulatec.format_b.api.read.all",
    "titulatec.ceremony.page.list",
}


def test_titulacion_queda_con_su_set_exacto_de_16():
    """D1 + D8 (22 - 7 + 1): Liberados, expediente RESUMIDO, notificaciones y
    el dictamen; sin Bandeja, Procesos, Documentos, Actos protocolarios ni el
    expediente completo con su desglose."""
    rol = set(_PERMISOS_ROL_TITULACION)

    assert len(_PERMISOS_ROL_TITULACION) == len(rol) == 16
    assert rol == _TITULACION_16
    assert set(_PERMISOS_RETIRADOS_TITULACION) == _RETIRADOS
    assert _PERM_PROCESS_SUMMARY == "titulatec.process.page.summary"
    assert not rol & _RETIRADOS


def test_titulaciones_sigue_con_sus_25_sin_el_resumido():
    """`titulatec_titulaciones` (jefatura de la Division) NO cambia: la
    separacion de constantes no puede arrastrarla."""
    rol = set(_PERMISOS_ROL_TITULACIONES_DIV)

    assert len(_PERMISOS_ROL_TITULACIONES_DIV) == len(rol) == 25
    assert _RETIRADOS <= rol
    assert _PERM_PROCESS_SUMMARY not in rol
    assert set(_PERMISOS_ROL_TITULACION) - {_PERM_PROCESS_SUMMARY} <= rol


def _concedidos_sanos():
    return {
        _ROL_TITULACION: set(_PERMISOS_ROL_TITULACION),
        _ROL_TITULACIONES_DIV: set(_PERMISOS_ROL_TITULACIONES_DIV),
        _ROL_OPERATIVO_ESCOLARES: {"titulatec.dashboard.school_services", *_PERMISOS_HANDOFF},
        _ROL_JEFATURA_ESCOLARES: {"titulatec.process.api.read.all", *_PERMISOS_HANDOFF},
    }


def test_grants_sanos_no_reportan_nada():
    assert _problemas_grants_titulacion(_concedidos_sanos()) == []


def test_titulacion_con_un_permiso_de_mas_es_un_problema():
    """El 03 converge el rol a su set exacto en cada corrida (DELETE de todo
    lo de titulatec fuera de los 16): si algo de mas sobrevive -- uno de los
    retirados o cualquier otro --, la siembra no aterrizo."""
    for extra in ("titulatec.process.page.detail", "titulatec.cohort.page.list"):
        concedidos = _concedidos_sanos()
        concedidos[_ROL_TITULACION].add(extra)

        problemas = _problemas_grants_titulacion(concedidos)

        assert any("titulatec_titulacion " in p and extra in p for p in problemas), problemas


def test_titulacion_sin_uno_de_sus_16_es_un_problema():
    concedidos = _concedidos_sanos()
    concedidos[_ROL_TITULACION].discard("titulatec.process.page.summary")

    problemas = _problemas_grants_titulacion(concedidos)

    assert any("titulatec.process.page.summary" in p for p in problemas), problemas


def test_titulaciones_sin_una_de_sus_25_es_un_problema():
    concedidos = _concedidos_sanos()
    concedidos[_ROL_TITULACIONES_DIV].discard("titulatec.ceremony.page.list")

    problemas = _problemas_grants_titulacion(concedidos)

    assert any(_ROL_TITULACIONES_DIV in p and "titulatec.ceremony.page.list" in p
               for p in problemas), problemas


def test_servicios_escolares_sin_liberados_es_un_problema():
    """D2: los dos roles de SE deben CONTENER los 2 de Liberados."""
    for rol in (_ROL_OPERATIVO_ESCOLARES, _ROL_JEFATURA_ESCOLARES):
        concedidos = _concedidos_sanos()
        concedidos[rol].discard("titulatec.handoff.api.export")

        problemas = _problemas_grants_titulacion(concedidos)

        assert any(rol in p and "titulatec.handoff.api.export" in p
                   for p in problemas), problemas


def test_corre_los_seeders_en_orden_y_verifica_las_tres_cosas():
    with patch("itcj2.cli.titulatec._run_sql_files") as ejecutar, \
         patch("itcj2.cli.titulatec._verify_survey_2026_09", return_value=[]) as v1, \
         patch("itcj2.cli.titulatec._verify_titulacion", return_value=[]) as v2, \
         patch("itcj2.cli.titulatec._verify_computer_center", return_value=[]) as v3:
        res = CliRunner().invoke(init_titulatec_command, [])

    assert res.exit_code == 0, res.output
    ejecutar.assert_called_once_with(SEED_FILES)
    v1.assert_called_once()
    v2.assert_called_once()
    v3.assert_called_once()
    assert "completado" in res.output


def test_un_problema_solo_de_computer_center_aborta_igual_y_lo_dice():
    """Acumula los problemas de LOS TRES verifies antes de abortar (docstring
    de `init_titulatec_command`): un problema solo de Centro de Cómputo, con
    los otros dos limpios, debe abortar y traer su texto en la salida —antes
    de esta prueba, nada ejercía `_verify_computer_center` en absoluto."""
    problema = ("titulatec_computer_center sin el permiso "
                "titulatec.enrollment_access.api.grant")
    with patch("itcj2.cli.titulatec._run_sql_files"), \
         patch("itcj2.cli.titulatec._verify_survey_2026_09", return_value=[]), \
         patch("itcj2.cli.titulatec._verify_titulacion", return_value=[]), \
         patch("itcj2.cli.titulatec._verify_computer_center", return_value=[problema]):
        res = CliRunner().invoke(init_titulatec_command, [])

    assert res.exit_code != 0, "un problema en CUALQUIERA de los tres debe abortar"
    assert problema in res.output


def test_una_excepcion_al_sembrar_no_llega_a_verificar_nada():
    """Si `_run_sql_files` truena (falta un archivo, error de SQL), el comando
    no debe seguir a la verificación con una BD a medio sembrar."""
    with patch("itcj2.cli.titulatec._run_sql_files",
               side_effect=RuntimeError("boom")), \
         patch("itcj2.cli.titulatec._verify_survey_2026_09") as v1, \
         patch("itcj2.cli.titulatec._verify_titulacion") as v2, \
         patch("itcj2.cli.titulatec._verify_computer_center") as v3:
        res = CliRunner().invoke(init_titulatec_command, [])

    assert res.exit_code != 0
    v1.assert_not_called()
    v2.assert_not_called()
    v3.assert_not_called()
