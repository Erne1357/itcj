"""Comandos CLI de la app Directory."""
from pathlib import Path

import click

from itcj2.cli.core import execute_sql_file, PROJECT_ROOT

_DML_FILES = [
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
    for sql_file in _DML_FILES:
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

    click.echo(click.style(f"\nOK: {ok}/{len(_DML_FILES)} archivos ejecutados — app directory lista.", fg="green"))


@click.group("directory")
def directory_cli():
    """Comandos administrativos de la app Directory."""


directory_cli.add_command(init_directory_command)
