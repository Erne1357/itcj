"""Comandos CLI de la app Cameras (credenciales de DVR por departamento)."""
import click

from itcj2.cli.core import execute_sql_file, PROJECT_ROOT

_DML_FILES = [
    "00_insert_app.sql",
    "01_insert_permissions.sql",
    "02_insert_role_permission.sql",
    "03_grant_access.sql",
]


@click.command("init-cameras")
def init_cameras_command():
    """Carga los DML de la app cameras en orden (idempotente).

    Ejecuta 00 (app), 01 (permisos), 02 (roles) y 03 (acceso espejo desde helpdesk).
    Aborta al primer archivo faltante o con error.
    """
    dml_dir = PROJECT_ROOT / "database" / "DML" / "cameras"
    click.echo(f"Inicializando app cameras (DML: {dml_dir})\n")

    ok = 0
    for sql_file in _DML_FILES:
        file_path = dml_dir / sql_file
        click.echo(f"  Ejecutando: {sql_file}")
        if not file_path.exists():
            click.echo(click.style(f"  ERROR: archivo no encontrado: {file_path}", fg="red"), err=True)
            raise click.Abort()
        try:
            execute_sql_file(str(file_path))
            click.echo(click.style(f"  OK: {sql_file}", fg="green"))
            ok += 1
        except Exception as e:
            click.echo(click.style(f"  ERROR en {sql_file}: {e}", fg="red"), err=True)
            raise click.Abort()

    click.echo(click.style(f"\nOK: {ok}/{len(_DML_FILES)} archivos ejecutados — app cameras lista.", fg="green"))


@click.group("cameras")
def cameras_cli():
    """Comandos administrativos de la app Cameras."""


cameras_cli.add_command(init_cameras_command)
