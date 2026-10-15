"""Comando `titulatec init-reemplazo-docs` (2026-10-15): permiso del reemplazo en cotejo.

`titulatec.document.api.request_replacement`: el 27 lo inserta y lo concede
EXPLICITO a `titulatec_school_services_head` y a `admin`. En produccion el
`15_grant_admin_all_perms.sql` NUNCA se re-corre, asi que el comando corre SOLO
el 27. El 27 sigue en `SEED_FILES` antes del 15 para las instalaciones desde cero.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from tests.fastapi.titulatec.test_permissions_contract import requires_dml

PERM = "titulatec.document.api.request_replacement"
ARCHIVO = "reemplazo_2026_10/27_insert_doc_replacement_perm.sql"
QUINCE = "15_grant_admin_all_perms.sql"
DML = Path(__file__).resolve().parents[3] / "database" / "DML" / "titulatec"


def test_seed_files_tiene_el_27_antes_del_15_y_el_15_al_final():
    from itcj2.cli.titulatec import SEED_FILES

    assert ARCHIVO in SEED_FILES
    assert SEED_FILES.index(ARCHIVO) < SEED_FILES.index(QUINCE)
    assert SEED_FILES[-1] == QUINCE


def _dml_en_tmp(tmp_path):
    """Stub del 27 en un directorio temporal: el test no depende de database/ (gitignored)."""
    carpeta = tmp_path / "reemplazo_2026_10"
    carpeta.mkdir(parents=True)
    (carpeta / "27_insert_doc_replacement_perm.sql").write_text("-- stub", encoding="utf-8")
    return tmp_path


def test_el_comando_corre_solo_el_27_y_verifica(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import documentos as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", _dml_en_tmp(tmp_path))
    ejecutados = []
    with patch("itcj2.cli.core.execute_sql_file",
               side_effect=lambda ruta, **kw: ejecutados.append(Path(ruta).name)), \
            patch("itcj2.core.services.authz_cache.invalidate_app") as inv, \
            patch.object(cli, "_verify_reemplazo_docs", return_value=[]) as verificar:
        res = CliRunner().invoke(cli.init_reemplazo_docs_command, [])

    assert res.exit_code == 0, res.output
    assert ejecutados == ["27_insert_doc_replacement_perm.sql"]
    inv.assert_called_once_with("titulatec")
    verificar.assert_called_once_with()


def test_el_comando_aborta_si_no_aterrizo(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import documentos as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", _dml_en_tmp(tmp_path))
    with patch("itcj2.cli.core.execute_sql_file"), \
            patch("itcj2.core.services.authz_cache.invalidate_app"), \
            patch.object(cli, "_verify_reemplazo_docs",
                         return_value=["el rol admin no tiene " + PERM]) as verificar:
        res = CliRunner().invoke(cli.init_reemplazo_docs_command, [])

    assert res.exit_code != 0
    # Debe abortar por la verificacion, no por el archivo faltante.
    assert "faltan archivos" not in res.output
    verificar.assert_called_once_with()


def test_dry_run_con_stub_no_ejecuta_nada_y_no_lista_el_15(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import documentos as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", _dml_en_tmp(tmp_path))
    with patch("itcj2.cli.core.execute_sql_file") as correr:
        res = CliRunner().invoke(cli.init_reemplazo_docs_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    correr.assert_not_called()
    assert ARCHIVO in res.output
    assert QUINCE not in res.output


def test_dry_run_aborta_si_falta_el_archivo(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import documentos as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", tmp_path)
    with patch("itcj2.cli.core.execute_sql_file") as correr:
        res = CliRunner().invoke(cli.init_reemplazo_docs_command, ["--dry-run"])

    assert res.exit_code != 0
    correr.assert_not_called()


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
