"""Comandos CLI de la app Credencial."""
import click

from itcj2.cli.core import execute_sql_file, PROJECT_ROOT

_DML_BASE_FILES = [
    "00_insert_app.sql",
    "01_insert_permissions.sql",
    "02_insert_roles.sql",
    "03_insert_role_permission.sql",
]


@click.group("credencial")
def credencial_cli():
    """Comandos de la app Credencial Digital."""


@credencial_cli.command("init-credencial")
def init_credencial_command():
    """Carga los DML de la app credencial en orden (idempotente).

    Ejecuta en secuencia:
      00_insert_app.sql              registra la core_app
      01_insert_permissions.sql      inserta los permisos
      02_insert_roles.sql            crea el rol verifier
      03_insert_role_permission.sql  asigna permisos a admin y verifier
    """
    dml_dir = PROJECT_ROOT / "database" / "DML" / "credencial"
    click.echo(f"Inicializando app credencial (DML: {dml_dir})\n")

    ok = 0
    for sql_file in _DML_BASE_FILES:
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

    click.echo(click.style(f"\nOK: {ok}/{len(_DML_BASE_FILES)} archivos ejecutados. App credencial lista.", fg="green"))
