"""Comandos CLI de la app Directory."""
from pathlib import Path

import click

from itcj2.cli.core import execute_sql_file, PROJECT_ROOT

_DML_BASE_FILES = [
    "00_insert_app.sql",
    "01_insert_permissions.sql",
    "02_insert_role_permission.sql",
    "03_grant_directory_access.sql",
]


@click.command("init-directory")
def init_directory_command():
    """Carga los DML de la app directory en orden (idempotente).

    Ejecuta en secuencia:
      00_insert_app.sql             — registra la core_app (mobile_enabled=true)
      01_insert_permissions.sql     — inserta los permisos
      02_insert_role_permission.sql — asigna permisos a roles
      03_grant_directory_access.sql — espeja acceso desde itcj (staff ve la app en móvil)
    """
    dml_dir = PROJECT_ROOT / "database" / "DML" / "directory"
    click.echo(f"Inicializando app directory (DML: {dml_dir})\n")

    ok = 0
    for sql_file in _DML_BASE_FILES:
        file_path = dml_dir / sql_file
        click.echo(f"  Ejecutando: {sql_file}")
        if not file_path.exists():
            click.echo(
                click.style(f"  ERROR: archivo no encontrado: {file_path}", fg="red"),
                err=True,
            )
            raise click.Abort()
        try:
            execute_sql_file(str(file_path))
            click.echo(click.style(f"  OK: {sql_file}", fg="green"))
            ok += 1
        except Exception as e:
            click.echo(
                click.style(f"  ERROR en {sql_file}: {e}", fg="red"),
                err=True,
            )
            raise click.Abort()

    click.echo(click.style(f"\nOK: {ok}/{len(_DML_BASE_FILES)} archivos ejecutados — app directory lista.", fg="green"))



_DML_CONFIG_2026_09_DIR = "config_2026_09"
_DML_CONFIG_2026_09_FILES = [
    "01_insert_permissions.sql",
    "02_insert_role_permission.sql",
]

_SETTINGS_PERM = "directory.settings.api.manage"


def directory_seed_files() -> list[str]:
    """Rutas relativas a `database/DML/` de TODO el DML de directory, en orden.

    Mismo contrato que `_titulatec_seed_files()` en cli/core.py:
    `seed_reference_data_command` hace `PROJECT_ROOT/"database"/"DML" / rel`, asi
    que un prefijo "database/DML/" aqui produce database/DML/database/DML/... y el
    bucle OMITE EL ARCHIVO EN SILENCIO saliendo 0: el DML de directory
    desapareceria de toda base nueva sin un solo error visible.
    """
    return (
        [f"directory/{f}" for f in _DML_BASE_FILES]
        + [f"directory/{_DML_CONFIG_2026_09_DIR}/{f}" for f in _DML_CONFIG_2026_09_FILES]
    )


def _verify_settings_permission() -> bool:
    """True si el permiso existe Y esta asignado al rol admin.

    Existe porque los RAISE NOTICE del DML son INVISIBLES: nada en itcj2/ lee
    connection.notices, asi que sin esto el operador ve "OK" pase lo que pase.
    """
    from sqlalchemy import text
    from itcj2.cli.core import _get_engine

    with _get_engine().connect() as conn:
        return bool(conn.execute(text("""
            SELECT 1
            FROM core_permissions p
            JOIN core_apps a ON a.id = p.app_id AND a.key = 'directory'
            JOIN core_role_permissions rp ON rp.perm_id = p.id
            JOIN core_roles r ON r.id = rp.role_id AND r.name = 'admin'
            WHERE p.code = :code
        """), {"code": _SETTINGS_PERM}).first())


@click.command("load-config-2026-09")
@click.option("--dry-run", is_flag=True, help="Lista los archivos sin ejecutarlos.")
def load_config_2026_09_command(dry_run):
    """Carga SOLO el delta de septiembre 2026 (permiso del ajuste global).

    NO re-ejecuta el DML base de la app: en produccion eso es justo lo que no se
    quiere. Idempotente: los dos archivos llevan ON CONFLICT DO NOTHING.
    """
    dml_dir = PROJECT_ROOT / "database" / "DML" / "directory" / _DML_CONFIG_2026_09_DIR
    if not dml_dir.is_dir():
        click.echo(click.style(
            f"ERROR: no existe {dml_dir}. `database/` esta gitignored: subelo por scp al host.",
            fg="red"), err=True)
        raise click.Abort()

    for sql_file in _DML_CONFIG_2026_09_FILES:
        file_path = dml_dir / sql_file
        if not file_path.exists():
            click.echo(click.style(f"ERROR: falta {file_path}", fg="red"), err=True)
            raise click.Abort()
        if dry_run:
            click.echo(f"  [dry-run] {file_path}")
            continue
        click.echo(f"  Ejecutando: {sql_file}")
        invalidated = execute_sql_file(str(file_path))
        click.echo(click.style(
            f"  OK: {sql_file} (cache authz invalidado: {invalidated})", fg="green"))

    if dry_run:
        click.echo("Dry-run: no se ejecuto nada.")
        return

    if not _verify_settings_permission():
        click.echo(click.style(
            f"ERROR: {_SETTINGS_PERM} no quedo creado y asignado al rol admin.",
            fg="red"), err=True)
        raise click.Abort()
    click.echo(click.style(f"OK: {_SETTINGS_PERM} verificado en la base.", fg="green"))


@click.group("directory")
def directory_cli():
    """Comandos administrativos de la app Directory."""


directory_cli.add_command(init_directory_command)
directory_cli.add_command(load_config_2026_09_command)
