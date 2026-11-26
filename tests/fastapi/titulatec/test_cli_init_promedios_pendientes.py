"""Comando `titulatec init-promedios-pendientes` (2026-11-26): permisos de la bandeja «Promedios».

El 28 inserta los 3 `titulatec.average.*` y los concede EXPLICITO (con `admin`).
En produccion el `15_grant_admin_all_perms.sql` NUNCA se re-corre, asi que el
comando corre SOLO el 28. El 28 sigue en `SEED_FILES` antes del 15 para las
instalaciones desde cero. Molde: `test_cli_init_reemplazo_docs.py`.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from tests.fastapi.titulatec.test_permissions_contract import requires_dml

ARCHIVO = "promedios_2026_11/28_insert_average_queue_perms.sql"
QUINCE = "15_grant_admin_all_perms.sql"
DML = Path(__file__).resolve().parents[3] / "database" / "DML" / "titulatec"
CUATRO = {"admin", "titulatec_computer_center", "titulatec_school_services",
          "titulatec_school_services_head"}


def test_seed_files_tiene_el_28_antes_del_15_y_el_15_al_final():
    from itcj2.cli.titulatec import SEED_FILES

    assert ARCHIVO in SEED_FILES
    assert SEED_FILES.index(ARCHIVO) < SEED_FILES.index(QUINCE)
    assert SEED_FILES[-1] == QUINCE


def _dml_en_tmp(tmp_path):
    carpeta = tmp_path / "promedios_2026_11"
    carpeta.mkdir(parents=True)
    (carpeta / "28_insert_average_queue_perms.sql").write_text("-- stub", encoding="utf-8")
    return tmp_path


def test_el_comando_corre_solo_el_28_y_verifica(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import promedios as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", _dml_en_tmp(tmp_path))
    ejecutados = []
    with patch("itcj2.cli.core.execute_sql_file",
               side_effect=lambda ruta, **kw: ejecutados.append((Path(ruta).name, kw))), \
            patch("itcj2.core.services.authz_cache.invalidate_app") as inv, \
            patch.object(cli, "_verify_promedios_pendientes", return_value=[]) as verificar:
        res = CliRunner().invoke(cli.init_promedios_pendientes_command, [])

    assert res.exit_code == 0, res.output
    assert ejecutados == [("28_insert_average_queue_perms.sql", {"invalidate_authz": False})]
    inv.assert_called_once_with("titulatec")
    verificar.assert_called_once_with()


def test_el_comando_aborta_si_no_aterrizo(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import promedios as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", _dml_en_tmp(tmp_path))
    with patch("itcj2.cli.core.execute_sql_file"), \
            patch("itcj2.core.services.authz_cache.invalidate_app"), \
            patch.object(cli, "_verify_promedios_pendientes",
                         return_value=["permiso ausente: titulatec.average.api.request"]):
        res = CliRunner().invoke(cli.init_promedios_pendientes_command, [])

    assert res.exit_code != 0
    assert "faltan archivos" not in res.output


def test_dry_run_no_ejecuta_nada_y_aborta_si_falta_el_archivo(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import promedios as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", _dml_en_tmp(tmp_path))
    with patch("itcj2.cli.core.execute_sql_file") as correr:
        res = CliRunner().invoke(cli.init_promedios_pendientes_command, ["--dry-run"])
        assert res.exit_code == 0, res.output
        assert ARCHIVO in res.output and QUINCE not in res.output

        monkeypatch.setattr(cli, "DML_TITULATEC", tmp_path / "vacio")
        res = CliRunner().invoke(cli.init_promedios_pendientes_command, ["--dry-run"])
        assert res.exit_code != 0
    correr.assert_not_called()


def test_verificar_contra_la_bd(db_session, patched_session_local, make_role, monkeypatch):
    """Con los grants puestos no hay problemas; un permiso o un rol que falte se
    nombra (codigo y rol FICTICIOS: la prueba no depende de lo que traiga dev)."""
    from itcj2.cli.titulatec import promedios as cli

    for rol, codigos in {r: [c for c, roles in cli._AVERAGE_GRANTS.items() if r in roles]
                         for r in CUATRO}.items():
        make_role(rol, codigos)
    assert cli._verify_promedios_pendientes() == []

    make_role("tt_test_avg_otro_rol")
    monkeypatch.setattr(cli, "_AVERAGE_GRANTS", {
        **cli._AVERAGE_GRANTS,
        "titulatec.average.api.request": ("admin", "tt_test_avg_otro_rol"),
        "titulatec.average.api.fantasma": ("admin",),
    })
    assert cli._verify_promedios_pendientes() == [
        "permiso ausente: titulatec.average.api.fantasma",
        "el rol tt_test_avg_otro_rol no tiene titulatec.average.api.request",
    ]


@requires_dml
def test_el_sql_es_idempotente_y_concede_a_quien_dice_la_spec():
    sql = (DML / ARCHIVO).read_text(encoding="utf-8")
    cuerpo = re.sub(r"--[^\n]*", "", sql.split("DO $$", 1)[1])
    assert cuerpo.count("ON CONFLICT (app_id, code) DO NOTHING") == 1
    assert cuerpo.count("INSERT INTO core_role_permissions (role_id, perm_id)") == 2
    assert cuerpo.count("ON CONFLICT DO NOTHING") == 2
    assert "core_user_app_roles" not in cuerpo
    bloques = cuerpo.split("INSERT INTO core_role_permissions")[1:]
    roles = [set(re.findall(r"'([a-z_]+)'", b.split("AND p.code")[0])) for b in bloques]
    assert roles == [CUATRO, {"admin", "titulatec_computer_center"}]
    assert "'titulatec.average.page.list', 'titulatec.average.api.capture'" in bloques[0]
    assert "p.code = 'titulatec.average.api.request'" in bloques[1]
