"""Comandos CLI de la app Adhoc (Calidad — SGC ISO 9001)."""
from pathlib import Path

import click

from itcj2.cli.core import execute_sql_file, PROJECT_ROOT

_DML_FILES = [
    "00_insert_app.sql",
    "01_insert_roles.sql",
    "02_insert_permissions.sql",
    "03_insert_role_permission.sql",
    "04_grant_adhoc_access.sql",
    "05_seed_catalogs.sql",
]


@click.command("init-adhoc")
def init_adhoc_command():
    """Carga los DML de la app adhoc en orden (idempotente).

    Ejecuta en secuencia:
      00_insert_app.sql             — registra la core_app 'adhoc' (Calidad)
      01_insert_roles.sql           — consult, supervisor_doc, supervisor_inc, supervisor_prog
      02_insert_permissions.sql     — inserta los permisos adhoc.*
      03_insert_role_permission.sql — asigna permisos a roles (aditivo)
      04_grant_adhoc_access.sql     — espeja acceso desde itcj (has_any_assignment)
      05_seed_catalogs.sql          — mail config singleton y catálogos base
    """
    dml_dir = PROJECT_ROOT / "database" / "DML" / "adhoc" / "init"
    click.echo(f"Inicializando app adhoc (DML: {dml_dir})\n")

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

    click.echo(click.style(f"\nOK: {ok}/{len(_DML_FILES)} archivos ejecutados — app adhoc lista.", fg="green"))


@click.group("adhoc")
def adhoc_cli():
    """Comandos administrativos de la app Adhoc (Calidad)."""


adhoc_cli.add_command(init_adhoc_command)
