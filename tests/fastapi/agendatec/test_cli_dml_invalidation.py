"""R8 (agendatec, concern 2 de la Tarea 7): cargar DML por directorio debe
invalidar el caché de authz, sin importar por qué comando se llegue ahí.

`_execute_sql_scripts` es el helper COMPARTIDO detrás de tres comandos:
`seed-periods` (carga `database/DML/agendatec/periods/`, que SÍ inserta
permisos/role_permissions — confirmado leyendo el SQL, no solo el nombre del
archivo: `01_insert_permissions_periods.sql` inserta en `core_permissions`,
`02_insert_role_permissions_periods.sql` en `core_role_permissions`),
`load-help` (`.../help/`, ídem) y `load-split-scope-2026-08`
(`.../split_scope_2026-08/`, ídem). Poner la invalidación en cada comando por
separado es exactamente el tipo de decisión que alguien olvida en el próximo
comando que use este helper — por eso vive al final de `_execute_sql_scripts`,
no en cada `click.command`.

Se invalida INCONDICIONALMENTE (no solo si el directorio "se sabe" que toca
permisos): el costo es un refill de caché en un comando que corre en deploy, y
el criterio-por-caller es la alternativa que se quiere evitar.

SEGUNDA invalidación, belt-and-braces: `_execute_sql_scripts` recibe un `db`
que no le pertenece y no lo commitea — su invalidación corre ANTES del commit
del caller. Es la misma forma de la Carrera A6 que `bump_version`/
`forget_cached_version` (Tareas 5/6) cerraron para la época de sesión, aplicada
ahora al caché de authz: un lector que caiga en la ventana pre-commit repuebla
el caché con el estado viejo aún no commiteado, y esa entrada sobrevive el TTL
completo. Por eso cada uno de los tres comandos invalida OTRA VEZ justo después
de su propio `db.commit()`. Los tests de más abajo prueban que ambas
invalidaciones ocurren, con el commit estrictamente entre ellas — no solo que
"se llamó una vez", que sería insuficiente para probar el cierre de la ventana.
"""
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from itcj2.cli.agendatec import (
    _execute_sql_scripts,
    load_help_command,
    load_split_scope_command,
    seed_periods_command,
)


def _assert_invalidate_wraps_commit(manager, expected_commit_calls=1):
    """Verifica el patrón belt-and-braces: invalidate_all - commit - invalidate_all.

    No basta con `call_count == 2`: si las dos llamadas ocurrieran ANTES del
    commit (p.ej. un bug que duplicara la del helper sin mover la segunda a su
    lugar), el conteo seguiría siendo 2 pero la ventana de la Carrera A6
    seguiría abierta. Se exige que el/los commit(s) caigan estrictamente entre
    la primera y la última invalidación.
    """
    names_in_order = [c[0] for c in manager.mock_calls]
    commit_positions = [i for i, n in enumerate(names_in_order) if n == "db_commit"]
    invalidate_positions = [i for i, n in enumerate(names_in_order) if n == "invalidate_all"]
    assert len(commit_positions) == expected_commit_calls, names_in_order
    assert len(invalidate_positions) == 2, names_in_order
    assert invalidate_positions[0] < commit_positions[0] < invalidate_positions[-1], names_in_order


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


def test_load_help_command_invalidates_authz_cache_twice_around_commit(tmp_path):
    """Prueba el comando real (`agendatec load-help`), no solo el helper.

    Reproduce el patrón de `test_mundial_cli.py`: los SQL reales de
    `database/DML/agendatec/help/` están gitignored y no existen en un clon
    limpio, así que se parchea `PROJECT_ROOT` a un directorio temporal con
    fixtures propias. `execute_sql_file`/`db.execute` van mockeados: el
    contenido de los .sql no importa, solo que el comando encuentre el
    directorio correcto y que AMBAS invalidaciones se disparen, en el orden
    correcto respecto al commit (belt-and-braces, ver docstring del módulo).
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
        manager = MagicMock()
        manager.attach_mock(db.commit, "db_commit")
        manager.attach_mock(inv, "invalidate_all")

        result = CliRunner().invoke(load_help_command)

    assert result.exit_code == 0, result.output
    assert db.execute.call_count == 2  # los dos .sql del directorio
    db.commit.assert_called_once()
    assert inv.call_count == 2
    _assert_invalidate_wraps_commit(manager)


def test_load_split_scope_command_invalidates_authz_cache_twice_around_commit(tmp_path):
    from itcj2.cli import agendatec as cli_agendatec

    scope_dir = tmp_path / "database" / "DML" / "agendatec" / "split_scope_2026-08"
    scope_dir.mkdir(parents=True)
    (scope_dir / "01_fix_admin_create_request_perm.sql").write_text("-- perms")

    db = MagicMock()
    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = db
    session_ctx.__exit__.return_value = False

    with patch.object(cli_agendatec, "PROJECT_ROOT", tmp_path), \
         patch("itcj2.database.SessionLocal", return_value=session_ctx), \
         patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        manager = MagicMock()
        manager.attach_mock(db.commit, "db_commit")
        manager.attach_mock(inv, "invalidate_all")

        result = CliRunner().invoke(load_split_scope_command)

    assert result.exit_code == 0, result.output
    db.commit.assert_called_once()
    assert inv.call_count == 2
    _assert_invalidate_wraps_commit(manager)


def test_seed_periods_command_invalidates_authz_cache_twice_around_commit(tmp_path):
    """Prueba `agendatec seed-periods`, el tercer caller (encontrado por el
    barrido de grep del helper, no de la lectura original) — su directorio
    `database/DML/agendatec/periods/` también inserta permisos/role_permissions
    (confirmado leyendo el SQL, ver docstring del módulo), así que también le
    corresponde el mismo cierre belt-and-braces.

    `db` va mockeado y `db.query` distingue por modelo: `AcademicPeriod.count()
    == 0` (evita el prompt interactivo `click.confirm`) y `Request` filtrado
    devuelve `[]` (nada que migrar). El resto del comando solo construye
    objetos ORM (`AgendaTecPeriodConfig`, `PeriodEnabledDay`) y los agrega a un
    `db` mockeado — no requiere Postgres real.
    """
    from itcj2.apps.agendatec.models import Request
    from itcj2.cli import agendatec as cli_agendatec
    from itcj2.core.models import AcademicPeriod

    periods_dir = tmp_path / "database" / "DML" / "agendatec" / "periods"
    periods_dir.mkdir(parents=True)
    (periods_dir / "01_insert_permissions_periods.sql").write_text("-- perms")

    def _query_side_effect(model):
        q = MagicMock()
        if model is AcademicPeriod:
            q.count.return_value = 0
        elif model is Request:
            q.filter.return_value.all.return_value = []
        return q

    db = MagicMock()
    db.query.side_effect = _query_side_effect
    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = db
    session_ctx.__exit__.return_value = False

    with patch.object(cli_agendatec, "PROJECT_ROOT", tmp_path), \
         patch("itcj2.database.SessionLocal", return_value=session_ctx), \
         patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        manager = MagicMock()
        manager.attach_mock(db.commit, "db_commit")
        manager.attach_mock(inv, "invalidate_all")

        result = CliRunner().invoke(seed_periods_command)

    assert result.exit_code == 0, result.output
    db.commit.assert_called_once()
    assert inv.call_count == 2
    _assert_invalidate_wraps_commit(manager)
