"""R8: cargar permisos por DML debe invalidar el caché de authz.

`core execute-sql` es el comando documentado en CLAUDE.md para cargar permisos. Sin
invalidar, un DML que REVOCA un permiso deja una ventana de autorización obsoleta de
hasta AUTHZ_CACHE_TTL (300s) después del despliegue.
"""
from unittest.mock import patch

from click.testing import CliRunner

from itcj2.cli.core import execute_single_sql_command


def test_execute_sql_invalidates_authz_cache(tmp_path):
    sql = tmp_path / "noop.sql"
    sql.write_text("SELECT 1;")

    with patch("itcj2.cli.core.execute_sql_file") as run_sql, \
         patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        result = CliRunner().invoke(execute_single_sql_command, [str(sql)])

    assert result.exit_code == 0, result.output
    run_sql.assert_called_once()
    inv.assert_called_once()


def test_execute_sql_can_skip_invalidation(tmp_path):
    sql = tmp_path / "noop.sql"
    sql.write_text("SELECT 1;")

    with patch("itcj2.cli.core.execute_sql_file"), \
         patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        result = CliRunner().invoke(execute_single_sql_command, [str(sql), "--no-invalidate-authz"])

    assert result.exit_code == 0, result.output
    inv.assert_not_called()
