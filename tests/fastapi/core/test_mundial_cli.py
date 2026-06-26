from unittest.mock import MagicMock, patch
from click.testing import CliRunner


def test_new_theme_mundial_runs_sql_syncs_and_warms(tmp_path):
    # Los SQL reales viven en database/DML/core/themes/mundial/, que está
    # gitignored y NO existe en un clon limpio (CI). Para que el test sea
    # autocontenido y corra en cualquier lado, creamos fixtures de SQL en un
    # PROJECT_ROOT temporal y lo parcheamos. execute_sql_file va mockeado, así
    # que el contenido de los .sql no importa: solo que el glob los encuentre.
    mundial_dir = tmp_path / "database" / "DML" / "core" / "themes" / "mundial"
    mundial_dir.mkdir(parents=True)
    (mundial_dir / "01_theme.sql").write_text("-- theme")
    (mundial_dir / "02_task.sql").write_text("-- task")

    from itcj2.cli import core as cli_core
    from itcj2.cli.core import new_theme_mundial_command

    runner = CliRunner()
    with patch.object(cli_core, "PROJECT_ROOT", tmp_path), \
         patch("itcj2.cli.core.execute_sql_file") as mock_exec, \
         patch("itcj2.cli.core._get_session") as mock_sess, \
         patch("itcj2.core.services.themes_service.invalidate_active_theme_cache") as mock_invalidate, \
         patch("itcj2.core.services.mundial_service.sync_periodic_task", return_value=True) as mock_sync, \
         patch("itcj2.core.services.mundial_service.get_today_cached",
               return_value={"date": "2026-06-18", "matches": [{"id": "A"}]}) as mock_warm:
        mock_sess.return_value = MagicMock()
        result = runner.invoke(new_theme_mundial_command)
    assert result.exit_code == 0, result.output
    # Ejecutó el SQL del tema y el de la tarea
    assert mock_exec.call_count >= 2
    mock_sync.assert_called_once()
    mock_warm.assert_called_once_with(force=True)
    mock_invalidate.assert_called_once()
