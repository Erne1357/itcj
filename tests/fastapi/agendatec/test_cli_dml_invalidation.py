"""R8 (agendatec, concern 2 de la Tarea 7): cargar DML por directorio debe
invalidar el caché de authz, sin importar por qué comando se llegue ahí.

`_execute_sql_scripts` es el helper COMPARTIDO detrás de tres comandos:
`seed-periods` (carga `database/DML/agendatec/periods/`, que SÍ inserta
permisos/role_permissions), `load-help` (`.../help/`, ídem) y
`load-split-scope-2026-08` (`.../split_scope_2026-08/`, ídem). Poner la
invalidación en cada comando por separado es exactamente el tipo de decisión
que alguien olvida en el próximo comando que use este helper — por eso vive al
final de `_execute_sql_scripts`, no en cada `click.command`.

Se invalida INCONDICIONALMENTE (no solo si el directorio "se sabe" que toca
permisos): el costo es un refill de caché en un comando que corre en deploy, y
el criterio-por-caller es la alternativa que se quiere evitar.
"""
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from itcj2.cli.agendatec import _execute_sql_scripts, load_help_command


def test_execute_sql_scripts_invalidates_authz_cache_after_running(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "01_insert_permissions.sql").write_text("-- perms")

    db = MagicMock()
    with patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        manager = MagicMock()
        manager.attach_mock(db.execute, "db_execute")
        manager.attach_mock(inv, "invalidate_all")

        executed = _execute_sql_scripts(db, str(scripts_dir))

    assert executed == 1
    db.execute.assert_called_once()
    inv.assert_called_once()

    # El caché se invalida DESPUÉS de correr los scripts, no antes.
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


def test_execute_sql_scripts_skips_invalidation_when_dir_empty(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    db = MagicMock()

    with patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        executed = _execute_sql_scripts(db, str(empty_dir))

    assert executed == 0
    db.execute.assert_not_called()
    inv.assert_not_called()


def test_load_help_command_invalidates_authz_cache_end_to_end(tmp_path):
    """Prueba el comando real (`agendatec load-help`), no solo el helper.

    Reproduce el patrón de `test_mundial_cli.py`: los SQL reales de
    `database/DML/agendatec/help/` están gitignored y no existen en un clon
    limpio, así que se parchea `PROJECT_ROOT` a un directorio temporal con
    fixtures propias. `execute_sql_file`/`db.execute` van mockeados: el
    contenido de los .sql no importa, solo que el comando encuentre el
    directorio correcto y que la invalidación se dispare al final.
    """
    from itcj2.cli import agendatec as cli_agendatec

    help_dir = tmp_path / "database" / "DML" / "agendatec" / "help"
    help_dir.mkdir(parents=True)
    (help_dir / "01_insert_help_permissions.sql").write_text("-- perms")
    (help_dir / "02_insert_help_role_permissions.sql").write_text("-- role perms")

    db = MagicMock()
    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = db
    session_ctx.__exit__.return_value = False

    with patch.object(cli_agendatec, "PROJECT_ROOT", tmp_path), \
         patch("itcj2.database.SessionLocal", return_value=session_ctx), \
         patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        result = CliRunner().invoke(load_help_command)

    assert result.exit_code == 0, result.output
    assert db.execute.call_count == 2  # los dos .sql del directorio
    db.commit.assert_called_once()
    inv.assert_called_once()
