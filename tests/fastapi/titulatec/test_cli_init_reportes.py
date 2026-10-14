"""Comando `titulatec init-reportes` (2026-10-14): permiso del Tablero.

`titulatec.reports.page.view`: el 26 lo inserta y lo concede EXPLICITO a
`titulatec_school_services_head` y a `admin` (revision final I1/I3). En
produccion el `15_grant_admin_all_perms.sql` NUNCA se re-corre, asi que el
comando corre SOLO el 26. El 26 sigue en `SEED_FILES` antes del 15 para las
instalaciones desde cero.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from tests.fastapi.titulatec.test_permissions_contract import requires_dml

PERM = "titulatec.reports.page.view"
ARCHIVO = "reportes_2026_10/26_insert_reports_perm.sql"
QUINCE = "15_grant_admin_all_perms.sql"
DML = Path(__file__).resolve().parents[3] / "database" / "DML" / "titulatec"


def test_seed_files_tiene_el_26_antes_del_15_y_el_15_al_final():
    from itcj2.cli.titulatec import SEED_FILES

    assert ARCHIVO in SEED_FILES
    assert SEED_FILES.index(ARCHIVO) < SEED_FILES.index(QUINCE)
    assert SEED_FILES[-1] == QUINCE


def test_el_comando_corre_solo_el_26_y_verifica():
    from itcj2.cli import titulatec as cli

    ejecutados = []
    with patch("itcj2.cli.core.execute_sql_file",
               side_effect=lambda ruta, **kw: ejecutados.append(Path(ruta).name)), \
            patch("itcj2.core.services.authz_cache.invalidate_app") as inv, \
            patch.object(cli, "_verify_reportes", return_value=[]) as verificar:
        res = CliRunner().invoke(cli.init_reportes_command, [])

    assert res.exit_code == 0, res.output
    assert ejecutados == ["26_insert_reports_perm.sql"]
    inv.assert_called_once_with("titulatec")
    verificar.assert_called_once_with()


def test_el_comando_aborta_si_no_aterrizo():
    from itcj2.cli import titulatec as cli

    with patch("itcj2.cli.core.execute_sql_file"), \
            patch("itcj2.core.services.authz_cache.invalidate_app"), \
            patch.object(cli, "_verify_reportes",
                         return_value=["el rol admin no tiene " + PERM]):
        res = CliRunner().invoke(cli.init_reportes_command, [])

    assert res.exit_code != 0


@requires_dml
def test_dry_run_no_ejecuta_nada_y_no_lista_el_15():
    from itcj2.cli import titulatec as cli

    with patch("itcj2.cli.core.execute_sql_file") as correr:
        res = CliRunner().invoke(cli.init_reportes_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    correr.assert_not_called()
    assert ARCHIVO in res.output
    assert QUINCE not in res.output


@requires_dml
def test_el_sql_es_idempotente_y_concede_a_la_jefa_y_a_admin():
    sql = (DML / ARCHIVO).read_text(encoding="utf-8")
    cuerpo = sql.split("DO $$", 1)[1]
    assert PERM in cuerpo
    assert "ON CONFLICT (app_id, code) DO NOTHING" in cuerpo
    assert "INSERT INTO core_role_permissions (role_id, perm_id)" in cuerpo
    assert "r.name IN ('titulatec_school_services_head', 'admin')" in cuerpo
    assert "ON CONFLICT DO NOTHING" in cuerpo
    assert "core_user_app_roles" not in cuerpo
