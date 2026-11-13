"""CLI `cameras init-cameras`: corre los 4 DML en orden y aborta al primer faltante.

database/ esta gitignored y no existe en un clon limpio (CI), asi que los .sql se
crean en un PROJECT_ROOT temporal y execute_sql_file va mockeado.
"""
from unittest.mock import patch

from click.testing import CliRunner

from itcj2.cli import cameras as cli_cameras
from itcj2.cli.main import cli

_FILES = [
    "00_insert_app.sql",
    "01_insert_permissions.sql",
    "02_insert_role_permission.sql",
    "03_grant_access.sql",
]


def _project_root(tmp_path, files=_FILES):
    dml = tmp_path / "database" / "DML" / "cameras"
    dml.mkdir(parents=True)
    for name in files:
        (dml / name).write_text("-- sql", encoding="utf-8")
    return tmp_path


def test_init_cameras_runs_files_in_order(tmp_path):
    root = _project_root(tmp_path)
    with patch.object(cli_cameras, "PROJECT_ROOT", root), \
         patch.object(cli_cameras, "execute_sql_file", return_value=True) as mock_exec:
        result = CliRunner().invoke(cli, ["cameras", "init-cameras"])
    assert result.exit_code == 0, result.output
    assert mock_exec.call_count == 4
    llamadas = [c.args[0] for c in mock_exec.call_args_list]
    for llamada, nombre in zip(llamadas, _FILES):
        assert llamada.endswith(nombre), (llamada, nombre)


def test_init_cameras_aborta_si_falta_un_archivo(tmp_path):
    root = _project_root(tmp_path, files=_FILES[:-1])
    with patch.object(cli_cameras, "PROJECT_ROOT", root), \
         patch.object(cli_cameras, "execute_sql_file", return_value=True) as mock_exec:
        result = CliRunner().invoke(cli, ["cameras", "init-cameras"])
    assert result.exit_code != 0
    assert mock_exec.call_count == 3


def test_init_cameras_aborta_al_primer_error_sql(tmp_path):
    root = _project_root(tmp_path)
    with patch.object(cli_cameras, "PROJECT_ROOT", root), \
         patch.object(cli_cameras, "execute_sql_file", side_effect=[True, Exception("boom")]) as mock_exec:
        result = CliRunner().invoke(cli, ["cameras", "init-cameras"])
    assert result.exit_code != 0
    assert mock_exec.call_count == 2
