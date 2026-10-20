"""El comando nuevo corre SOLO la subcarpeta config_2026_09.

Re-ejecutar el DML viejo en produccion es justo lo que este patron existe para
evitar.
"""
import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from itcj2.cli.directory import (
    _DML_CONFIG_2026_09_FILES, directory_seed_files, load_config_2026_09_command,
)

_DML_DIR = "database/DML/directory/config_2026_09"


def test_seed_files_are_relative_to_dml_root():
    """Un prefijo database/DML/ aqui hace que seed-reference-data los omita en silencio."""
    rels = directory_seed_files()
    assert rels
    assert all(not r.startswith("database/") for r in rels), rels
    assert all(r.startswith("directory/") for r in rels), rels


def test_seed_files_include_base_and_delta():
    rels = directory_seed_files()
    assert any("config_2026_09" in r for r in rels)
    assert any(r.endswith("00_insert_app.sql") for r in rels)


@pytest.mark.skipif(not os.path.isdir(_DML_DIR),
                    reason="database/ esta gitignored: no existe en CI")
def test_runs_only_config_2026_09_files():
    with patch("itcj2.cli.directory.execute_sql_file", return_value=True) as mock_exec, \
         patch("itcj2.cli.directory._verify_settings_permission", return_value=True):
        result = CliRunner().invoke(load_config_2026_09_command, [])
    assert result.exit_code == 0, result.output
    paths = [str(call.args[0]) for call in mock_exec.call_args_list]
    assert len(paths) == len(_DML_CONFIG_2026_09_FILES)
    assert all("config_2026_09" in p for p in paths)
    assert not any("00_insert_app" in p or "03_grant" in p for p in paths)


@pytest.mark.skipif(not os.path.isdir(_DML_DIR),
                    reason="database/ esta gitignored: no existe en CI")
def test_dry_run_executes_nothing():
    with patch("itcj2.cli.directory.execute_sql_file") as mock_exec:
        result = CliRunner().invoke(load_config_2026_09_command, ["--dry-run"])
    assert result.exit_code == 0
    mock_exec.assert_not_called()


@pytest.mark.skipif(not os.path.isdir(_DML_DIR),
                    reason="database/ esta gitignored: no existe en CI")
def test_aborts_when_verification_fails():
    """Los RAISE NOTICE son invisibles: sin esto el operador ve OK pase lo que pase."""
    with patch("itcj2.cli.directory.execute_sql_file", return_value=True), \
         patch("itcj2.cli.directory._verify_settings_permission", return_value=False):
        result = CliRunner().invoke(load_config_2026_09_command, [])
    assert result.exit_code != 0
