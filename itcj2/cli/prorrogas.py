"""Comandos CLI de la app Prórrogas."""
from pathlib import Path

import click

from itcj2.cli.core import execute_sql_file, PROJECT_ROOT

# El orden importa: cada script asume que el anterior corrió.
_DML_FILES = [
    "00_insert_app.sql",
    "01_insert_permissions.sql",
    "02_insert_role_permission.sql",
    "03_grant_prorrogas_access.sql",
]


@click.command("init-prorrogas")
def init_prorrogas_command():
    """Carga los DML de la app prorrogas_tec en orden (idempotente).

    Ejecuta en secuencia:
      00_insert_app.sql             — registra la core_app (key prorrogas_tec, url /prorrogas)
      01_insert_permissions.sql     — inserta los 12 permisos del módulo
      02_insert_role_permission.sql — admin: todo; student: solo lo propio
      03_grant_prorrogas_access.sql — espeja admin desde itcj y student desde agendatec

    Corre SOLO `database/DML/prorrogas_tec/`: no re-ejecuta ningún DML ya
    aplicado de otras apps. Todo el SQL usa ON CONFLICT, así que repetirlo es
    inofensivo.

    La invalidación del caché de authz la hereda de `execute_sql_file`, que es
    el chokepoint por el que pasan las ~14 cargas de DML del proyecto — sin ella
    un permiso recién sembrado tardaría hasta AUTHZ_CACHE_TTL en verse.
    """
    dml_dir = PROJECT_ROOT / "database" / "DML" / "prorrogas_tec"
    click.echo(f"Inicializando app prorrogas_tec (DML: {dml_dir})\n")

    ok = 0
    for sql_file in _DML_FILES:
        file_path = dml_dir / sql_file
        click.echo(f"  Ejecutando: {sql_file}")
        if not file_path.exists():
            click.echo(
                click.style(f"  ERROR: archivo no encontrado: {file_path}", fg="red"),
                err=True,
            )
            click.echo(
                "  database/ está gitignored: súbelo al servidor por scp.",
                err=True,
            )
            raise click.Abort()
        try:
            execute_sql_file(str(file_path))
            click.echo(click.style(f"  OK: {sql_file}", fg="green"))
            ok += 1
        except Exception as e:
            click.echo(click.style(f"  ERROR en {sql_file}: {e}", fg="red"), err=True)
            raise click.Abort()

    click.echo(click.style(
        f"\nOK: {ok}/{len(_DML_FILES)} archivos ejecutados — app prorrogas_tec lista.",
        fg="green",
    ))


@click.group("prorrogas")
def prorrogas_cli():
    """Comandos administrativos de la app Prórrogas."""


prorrogas_cli.add_command(init_prorrogas_command)
