"""R8 (vistetec, hallazgo de la Tarea 7 — "cuarta puerta" del mismo hueco):
`init-vistetec` carga `database/DML/vistetec/`, que incluye
`02_insert_permissions.sql` y `03_insert_role_permissions.sql` (confirmado
leyendo el SQL). Su `_execute_sql_scripts` es una copia PRIVADA y SEPARADA del
helper homónimo de `itcj2/cli/agendatec.py` — deliberadamente no unificados
(ver la nota en `itcj2/cli/vistetec.py::_execute_sql_scripts`), pero el hueco
era idéntico: cargar permisos sin invalidar nada.

Vive en `tests/fastapi/core/` en vez de un paquete `tests/fastapi/vistetec/`
porque no existe ningún harness de fixtures de VisteTec en el repo todavía y
este test no lo necesita — `db` va completamente mockeado, igual que
`test_cli_invalidation.py` y `test_mundial_cli.py`, sus vecinos en este mismo
directorio.

Igual que en agendatec: invalidación DENTRO del helper (antes del commit del
caller) más una SEGUNDA después del `db.commit()` del comando — belt-and-braces
contra la Carrera A6 (Tareas 5/6, cerrada ahí para la época de sesión; aquí
para el caché de authz).
"""
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from itcj2.cli.vistetec import _execute_sql_scripts, init_vistetec_command


def test_execute_sql_scripts_invalidates_authz_cache_after_running(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "02_insert_permissions.sql").write_text("-- perms")

    db = MagicMock()
    with patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        manager = MagicMock()
        manager.attach_mock(db.execute, "db_execute")
        manager.attach_mock(inv, "invalidate_all")

        executed = _execute_sql_scripts(db, str(scripts_dir))

    assert executed == 1
    db.execute.assert_called_once()
    inv.assert_called_once()

    names_in_order = [c[0] for c in manager.mock_calls]
    assert names_in_order.index("db_execute") < names_in_order.index("invalidate_all")


def test_execute_sql_scripts_skips_invalidation_when_dir_missing(tmp_path):
    missing_dir = tmp_path / "does_not_exist"
    db = MagicMock()

    with patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        executed = _execute_sql_scripts(db, str(missing_dir))

    assert executed == 0
    db.execute.assert_not_called()
    inv.assert_not_called()


def test_init_vistetec_command_invalidates_authz_cache_twice_around_commit(tmp_path):
    """Prueba el comando real (`vistetec init-vistetec`), no solo el helper.

    `PROJECT_ROOT` se parchea a un directorio temporal con un .sql fixture
    (los reales están gitignored, mismo truco que `test_mundial_cli.py`).
    `SessionLocal` se parchea a un context manager que envuelve un `db`
    mockeado. Se prueba que AMBAS invalidaciones ocurren, con el
    `db.commit()` (condicionado a `scripts_executed > 0` en este comando)
    estrictamente entre ellas.
    """
    from itcj2.cli import vistetec as cli_vistetec

    scripts_dir = tmp_path / "database" / "DML" / "vistetec"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "02_insert_permissions.sql").write_text("-- perms")
    (scripts_dir / "03_insert_role_permissions.sql").write_text("-- role perms")

    db = MagicMock()
    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = db
    session_ctx.__exit__.return_value = False

    with patch.object(cli_vistetec, "PROJECT_ROOT", tmp_path), \
         patch("itcj2.database.SessionLocal", return_value=session_ctx), \
         patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        manager = MagicMock()
        manager.attach_mock(db.commit, "db_commit")
        manager.attach_mock(inv, "invalidate_all")

        result = CliRunner().invoke(init_vistetec_command)

    assert result.exit_code == 0, result.output
    assert db.execute.call_count == 2  # los dos .sql del directorio
    db.commit.assert_called_once()
    assert inv.call_count == 2

    names_in_order = [c[0] for c in manager.mock_calls]
    commit_positions = [i for i, n in enumerate(names_in_order) if n == "db_commit"]
    invalidate_positions = [i for i, n in enumerate(names_in_order) if n == "invalidate_all"]
    assert len(commit_positions) == 1, names_in_order
    assert len(invalidate_positions) == 2, names_in_order
    assert invalidate_positions[0] < commit_positions[0] < invalidate_positions[-1], names_in_order
