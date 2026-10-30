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
    "04_insert_secretaria.sql",
    "05_insert_plan2.sql",
    "06_insert_plan3.sql",
    "07_insert_plan4.sql",
]


@click.command("init-prorrogas")
def init_prorrogas_command():
    """Carga los DML de la app prorrogas_tec en orden (idempotente).

    Ejecuta en secuencia:
      00_insert_app.sql             — registra la core_app (key prorrogas_tec, url /prorrogas)
      01_insert_permissions.sql     — inserta los 12 permisos del módulo
      02_insert_role_permission.sql — admin: todo; student: solo lo propio
      03_grant_prorrogas_access.sql — espeja admin desde itcj (los alumnos entran por QR o invitación)
      04_insert_secretaria.sql      — rol secretaria y permisos de Documentos (secretaria y admin)
      05_insert_plan2.sql           — permisos de invitaciones, solicitudes y decisión (secretaria, admin, student)
      06_insert_plan3.sql           — permisos de plan de pago, recibos, recordatorios y exportación (secretaria, admin) y firma propia (student)
      07_insert_plan4.sql           — permiso de estadísticas (secretaria, admin)

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


@click.command("excel-limpiar")
@click.argument("origen", type=click.Path(exists=True, dir_okay=False))
@click.option("--salida", required=True, type=click.Path(dir_okay=False))
def excel_limpiar_command(origen, salida):
    """Lee el Excel histórico y escribe el archivo limpio para revisar (no toca la base).

    Imprime solo conteos: nunca nombres ni números de control.
    """
    from collections import Counter

    from itcj2.apps.prorrogas_tec.importacion.hojas import leer_libro
    from itcj2.apps.prorrogas_tec.importacion.limpio import escribir_limpio

    try:
        solicitudes = leer_libro(origen)
        res = escribir_limpio(solicitudes, salida)
    except Exception as e:  # el mensaje podría citar una celda: solo el tipo
        click.secho(f"Error al leer el libro: {type(e).__name__}", fg="red")
        raise click.Abort()
    click.echo(f"Solicitudes: {res['solicitudes']} · Parcialidades: {res['parcialidades']} "
               f"· Con problema: {res['con_problema']}")
    motivos = Counter(p.problema for s in solicitudes for p in s.parcialidades if p.problema)
    motivos.update(s.problema for s in solicitudes if s.problema)
    motivos.update("sin parcialidades" for s in solicitudes if not s.parcialidades and not s.problema)
    for motivo, n in motivos.most_common():
        click.echo(f"  {motivo}: {n}")
    click.echo(f"Archivo: {salida}")


@click.command("import-excel")
@click.argument("limpio", type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True, help="Valida y cuenta sin escribir en la base.")
def import_excel_command(limpio, dry_run):
    """Importa a la base el archivo limpio (idempotente por referencia).

    Imprime solo referencias (hoja#renglón) y conteos: nunca nombres ni números de control.
    """
    from itcj2.apps.prorrogas_tec.importacion.importador import importar
    from itcj2.apps.prorrogas_tec.importacion.limpio import leer_limpio
    from itcj2.database import SessionLocal

    try:
        solicitudes, errores = leer_limpio(limpio)
    except ValueError as e:
        click.secho(str(e), fg="red")
        raise click.Abort()
    from sqlalchemy.exc import SQLAlchemyError

    try:
        with SessionLocal() as db:
            res = importar(db, solicitudes, dry_run=dry_run)
    except SQLAlchemyError as e:  # su mensaje trae los parámetros (nombres, controles)
        click.secho(f"Error de base de datos: {type(e).__name__}", fg="red")
        raise click.Abort()
    for ref, motivo in [*errores, *res["con_error"]]:
        click.echo(f"{ref}: {motivo}")
    prefijo = "SIMULACRO — " if dry_run else ""
    click.echo(f"{prefijo}Creadas: {res['creadas']} · Ya existían: {res['ya_existian']} "
               f"· Con error: {len(errores) + len(res['con_error'])} "
               f"· Sin semestre en core: {res['sin_semestre_core']} · Sin cuenta: {res['sin_cuenta']}")


@click.group("prorrogas")
def prorrogas_cli():
    """Comandos administrativos de la app Prórrogas."""


prorrogas_cli.add_command(init_prorrogas_command)
prorrogas_cli.add_command(excel_limpiar_command)
prorrogas_cli.add_command(import_excel_command)
