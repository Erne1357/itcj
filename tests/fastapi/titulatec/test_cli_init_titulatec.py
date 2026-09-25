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

from itcj2.cli.titulatec import SEED_FILES, init_titulatec_command


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
