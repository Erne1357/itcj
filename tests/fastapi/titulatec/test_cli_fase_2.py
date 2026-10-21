"""Comando `titulatec init-titulatec-fase-2`: unico camino del DML de la fase 2
del desarrollo (fases 3-8). Primer archivo: `fase_2/01_titulacion_formato_b.sql`.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from tests.fastapi.titulatec.test_permissions_contract import requires_dml

ARCHIVO = "fase_2/01_titulacion_formato_b.sql"
DML = Path(__file__).resolve().parents[3] / "database" / "DML" / "titulatec"
P_LIST = "titulatec.titulacion.page.list"
P_READ_ALL = "titulatec.format_b.api.read.all"
P_CORRECT = "titulatec.format_b.api.correct_registry"


def _dml_en_tmp(tmp_path):
    """Stub del 01 en un directorio temporal: el test no depende de database/ (gitignored)."""
    carpeta = tmp_path / "fase_2"
    carpeta.mkdir(parents=True)
    (carpeta / "01_titulacion_formato_b.sql").write_text("-- stub", encoding="utf-8")
    return tmp_path


def test_expected_son_exactamente_los_grants_del_spec():
    from itcj2.cli.titulatec import fase2

    assert fase2._FASE_2_EXPECTED == {
        "titulatec_titulacion": {P_LIST, P_READ_ALL, P_CORRECT},
        "titulatec_titulaciones": {P_LIST, P_CORRECT},
        "admin": {P_LIST, P_CORRECT},
    }
    assert fase2._DML_FASE_2_DIR == "fase_2"
    assert fase2._DML_FASE_2_FILES == ["01_titulacion_formato_b.sql"]


def test_el_comando_corre_los_archivos_de_fase_2_y_verifica(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import fase2 as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", _dml_en_tmp(tmp_path))
    ejecutados = []
    with patch("itcj2.cli.core.execute_sql_file",
               side_effect=lambda ruta, **kw: ejecutados.append((Path(ruta).name, kw))), \
            patch("itcj2.core.services.authz_cache.invalidate_app") as inv, \
            patch.object(cli, "_verify_fase_2", return_value=[]) as verificar:
        res = CliRunner().invoke(cli.init_titulatec_fase_2_command, [])

    assert res.exit_code == 0, res.output
    assert ejecutados == [("01_titulacion_formato_b.sql", {"invalidate_authz": False})]
    inv.assert_called_once_with("titulatec")
    verificar.assert_called_once_with()
    assert "OK" in res.output


def test_el_comando_aborta_si_no_aterrizo(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import fase2 as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", _dml_en_tmp(tmp_path))
    with patch("itcj2.cli.core.execute_sql_file"), \
            patch("itcj2.core.services.authz_cache.invalidate_app"), \
            patch.object(cli, "_verify_fase_2", return_value=["el rol admin no tiene x"]):
        res = CliRunner().invoke(cli.init_titulatec_fase_2_command, [])

    assert res.exit_code != 0
    assert "faltan archivos" not in res.output


def test_dry_run_con_archivo_ausente_aborta_sin_ejecutar(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import fase2 as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", tmp_path)  # sin fase_2/
    with patch("itcj2.cli.core.execute_sql_file") as correr:
        res = CliRunner().invoke(cli.init_titulatec_fase_2_command, ["--dry-run"])

    assert res.exit_code != 0
    correr.assert_not_called()
    assert "faltan archivos" in res.output


def test_dry_run_lista_el_archivo_y_no_ejecuta(tmp_path, monkeypatch):
    from itcj2.cli.titulatec import fase2 as cli

    monkeypatch.setattr(cli, "DML_TITULATEC", _dml_en_tmp(tmp_path))
    with patch("itcj2.cli.core.execute_sql_file") as correr:
        res = CliRunner().invoke(cli.init_titulatec_fase_2_command, ["--dry-run"])

    assert res.exit_code == 0, res.output
    correr.assert_not_called()
    assert ARCHIVO in res.output


def test_verify_fase_2_reporta_un_grant_faltante(db_session, make_role, patched_session_local):
    from itcj2.cli.titulatec import fase2 as cli
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role import Role
    from itcj2.core.models.role_permission import RolePermission

    for rol, codigos in cli._FASE_2_EXPECTED.items():
        make_role(rol, sorted(codigos))
    assert cli._verify_fase_2() == []

    rol = db_session.query(Role).filter_by(name="titulatec_titulaciones").one()
    perm = db_session.query(Permission).filter_by(code=P_CORRECT).one()
    db_session.query(RolePermission).filter_by(role_id=rol.id, perm_id=perm.id).delete()
    db_session.flush()

    assert cli._verify_fase_2() == [f"el rol titulatec_titulaciones no tiene {P_CORRECT}"]


@requires_dml
def test_el_sql_es_idempotente_y_concede_explicito():
    sql = (DML / ARCHIVO).read_text(encoding="utf-8")
    cuerpo = sql.split("DO $$", 1)[1]
    for codigo in (P_LIST, P_CORRECT, P_READ_ALL):
        assert codigo in cuerpo
    assert "ON CONFLICT (app_id, code) DO NOTHING" in cuerpo
    assert "INSERT INTO core_role_permissions (role_id, perm_id)" in cuerpo
    assert "ON CONFLICT DO NOTHING" in cuerpo
    assert "permission_id" not in cuerpo
