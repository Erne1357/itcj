from unittest.mock import MagicMock, patch
from click.testing import CliRunner


def test_new_theme_mundial_runs_sql_syncs_and_warms():
    from itcj2.cli.core import new_theme_mundial_command
    runner = CliRunner()
    with patch("itcj2.cli.core.execute_sql_file") as mock_exec, \
         patch("itcj2.cli.core._get_session") as mock_sess, \
         patch("itcj2.core.services.themes_service.invalidate_active_theme_cache"), \
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
