"""R8: cargar permisos por DML debe invalidar el caché de authz.

Sin invalidar, un DML que REVOCA un permiso deja una ventana de autorización
obsoleta de hasta AUTHZ_CACHE_TTL (300s) después del despliegue.

**Dónde vive la invalidación y por qué ahí.** Hay ~14 comandos CLI que cargan
DML (`core init-db`, `core init-tasks`, `core init-config-2026-07`,
`directory init-directory`, `helpdesk._run_sql_files`, `maint._run_sql_files`,
`maint._seed_config_files`, `titulatec`, `warehouse`, …) y TODOS pasan por
`itcj2.cli.core.execute_sql_file`, que abre su propia conexión y commitea
internamente. Poner la invalidación en cada comando cerraba unas puertas y
dejaba otras abiertas (y cada comando futuro nacería abierto); ponerla en el
chokepoint las cierra todas de una vez, y además queda DESPUÉS del commit, que
es la única posición correcta: invalidar antes deja que un lector repueble el
caché con los permisos viejos y esa entrada le sobrevive el TTL completo.
"""
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from itcj2.cli.core import execute_single_sql_command, execute_sql_file


def _mock_engine():
    """Engine falso: `execute_sql_file` no debe tocar Postgres en estos tests."""
    engine = MagicMock()
    return engine


# ---------------------------------------------------------------------------
# El chokepoint
# ---------------------------------------------------------------------------
def test_execute_sql_file_invalidates_authz_after_commit(tmp_path):
    """Todo comando que cargue DML hereda la invalidación por pasar por aquí."""
    sql = tmp_path / "noop.sql"
    sql.write_text("SELECT 1;")

    engine = _mock_engine()
    connection = engine.connect.return_value.__enter__.return_value

    with patch("itcj2.cli.core._get_engine", return_value=engine), \
         patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        manager = MagicMock()
        manager.attach_mock(connection.commit, "commit")
        manager.attach_mock(inv, "invalidate_all")

        assert execute_sql_file(str(sql)) is True

    inv.assert_called_once()
    # El ORDEN importa: invalidar ANTES del commit deja una ventana en la que un
    # lector repuebla el caché con los permisos viejos (todavía no commiteados) y
    # esa entrada le dura los 300s completos del TTL.
    names = [c[0] for c in manager.mock_calls]
    assert names.index("commit") < names.index("invalidate_all"), names


def test_execute_sql_file_can_skip_invalidation(tmp_path):
    """Escotilla para SQL que no toca permisos/roles (imports masivos, catálogos)."""
    sql = tmp_path / "noop.sql"
    sql.write_text("SELECT 1;")

    with patch("itcj2.cli.core._get_engine", return_value=_mock_engine()), \
         patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        assert execute_sql_file(str(sql), invalidate_authz=False) is False

    inv.assert_not_called()


def test_execute_sql_file_survives_a_broken_cache(tmp_path):
    """Un Redis caído no puede tumbar la carga de DML: el SQL ya está commiteado.

    Y el retorno lo dice, para que `core execute-sql` no anuncie una
    invalidación que no ocurrió.
    """
    sql = tmp_path / "noop.sql"
    sql.write_text("SELECT 1;")

    with patch("itcj2.cli.core._get_engine", return_value=_mock_engine()), \
         patch("itcj2.core.services.authz_cache.invalidate_all",
               side_effect=RuntimeError("redis caido")):
        assert execute_sql_file(str(sql)) is False  # no debe lanzar


def test_execute_sql_file_does_not_invalidate_when_the_sql_fails(tmp_path):
    """Si el DML no llegó a aplicarse, no hay nada que invalidar."""
    sql = tmp_path / "noop.sql"
    sql.write_text("SELECT 1;")

    engine = _mock_engine()
    engine.connect.return_value.__enter__.return_value.execute.side_effect = RuntimeError("boom")

    with patch("itcj2.cli.core._get_engine", return_value=engine), \
         patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        try:
            execute_sql_file(str(sql))
        except Exception:
            pass

    inv.assert_not_called()


# ---------------------------------------------------------------------------
# `core execute-sql` — el flag debe llegar al chokepoint, no quedarse en el cuerpo
# ---------------------------------------------------------------------------
def test_execute_sql_command_delegates_invalidation(tmp_path):
    """`core execute-sql` es el comando documentado en CLAUDE.md para cargar permisos."""
    sql = tmp_path / "noop.sql"
    sql.write_text("SELECT 1;")

    with patch("itcj2.cli.core.execute_sql_file") as run_sql:
        result = CliRunner().invoke(execute_single_sql_command, [str(sql)])

    assert result.exit_code == 0, result.output
    run_sql.assert_called_once_with(str(sql), invalidate_authz=True)


def test_execute_sql_command_can_skip_invalidation(tmp_path):
    """`--no-invalidate-authz` debe PROPAGARSE.

    Si el flag se resolviera en el cuerpo del comando (invalidando ahí) mientras
    `execute_sql_file` invalida siempre por su cuenta, el opt-out quedaría
    silenciosamente derrotado: el usuario pide no invalidar y se invalida igual.
    """
    sql = tmp_path / "noop.sql"
    sql.write_text("SELECT 1;")

    with patch("itcj2.cli.core.execute_sql_file") as run_sql:
        result = CliRunner().invoke(
            execute_single_sql_command, [str(sql), "--no-invalidate-authz"]
        )

    assert result.exit_code == 0, result.output
    run_sql.assert_called_once_with(str(sql), invalidate_authz=False)


# ---------------------------------------------------------------------------
# Una de las puertas que estaban abiertas antes del chokepoint
# ---------------------------------------------------------------------------
def test_init_directory_goes_through_the_chokepoint():
    """`directory init-directory` carga permisos y role_permissions de directory.

    No invalidaba nada. No se le añade una llamada propia: se comprueba que sus
    cargas pasan por `execute_sql_file` SIN optar por salirse, que es de donde
    hereda la invalidación.
    """
    from itcj2.cli.directory import init_directory_command

    with patch("itcj2.cli.directory.execute_sql_file") as run_sql:
        result = CliRunner().invoke(init_directory_command, [])

    assert result.exit_code == 0, result.output
    assert run_sql.call_count >= 1
    for call in run_sql.call_args_list:
        assert call.kwargs.get("invalidate_authz", True) is True, call
