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
    "06_repair_document_202_flow.sql",
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
      06_repair_document_202_flow.sql — sanea el documento 202 (flujo a medio arrancar)

    El 06 es el único que repara DATOS en vez de sembrar configuración, y por eso
    va el último: además de las tablas necesita que el historial del SGC esté
    cargado (``adhoc import-legacy``). En una base sin ese historial no encuentra
    la fila y es un no-op limpio, no un fallo.
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


@click.command("grant-incident-files")
def grant_incident_files_command():
    """Carga los permisos de archivos de incidencia (delta posterior a init).

    Corre **solo** ``database/DML/adhoc/incident_files/``. El DML de ``init/``
    no se vuelve a ejecutar: en producción re-correr un DML viejo es la forma
    más fácil de reintroducir algo que ya se había corregido a mano.

    Los tres permisos (``adhoc.incidents.api.files.{create,delete,download}``)
    no existían porque la app se construyó asumiendo que las incidencias no
    llevan adjuntos. El SGC legacy sí los tenía, y al importar el historial
    aparecieron 351 archivos sin forma de verse.
    """
    dml_dir = PROJECT_ROOT / "database" / "DML" / "adhoc" / "incident_files"
    files = ["01_insert_permissions.sql", "02_insert_role_permission.sql"]

    click.echo(f"Cargando permisos de archivos de incidencia ({dml_dir})\n")
    for sql_file in files:
        path = dml_dir / sql_file
        if not path.exists():
            click.echo(click.style(f"  ERROR: no existe {path}", fg="red"), err=True)
            raise click.Abort()
        click.echo(f"  Ejecutando: {sql_file}")
        try:
            execute_sql_file(str(path))
        except Exception as exc:
            click.echo(click.style(f"  ERROR en {sql_file}: {exc}", fg="red"), err=True)
            raise click.Abort()
        click.echo(click.style(f"  OK: {sql_file}", fg="green"))

    click.echo(click.style("\nOK: permisos de archivos de incidencia cargados.", fg="green"))


@click.command("import-legacy")
@click.option("--dry-run", is_flag=True,
              help="Corre todo y revierte al final: valida sin dejar rastro.")
def import_legacy_command(dry_run: bool):
    """Importa el historial del SGC legacy (ControlDocumental, SQL Server).

    Los .sql los genera `scripts/adhoc_etl/run.py` a partir del volcado del
    legacy. Este comando solo los ejecuta, en orden y **en una sola
    transacción**: si algo falla a media carga no queda la base truncada con
    medio historial dentro.

    NO usa `execute_sql_file`. Ese helper parte el archivo por `;` y recorta lo
    que sigue a `--` línea por línea, incluso dentro de literales, y borra las
    líneas en blanco. Con datos reales eso corrompe en silencio: 24 incidencias
    y 10 comentarios del legacy traen `;` en el texto, 26 comentarios tienen
    línea en blanco interna y 78 son multilínea. Aquí el archivo se manda
    entero a psycopg2, que acepta multi-sentencia y respeta comillas y `$$`.

    La transacción única también es lo que hace válida la tabla temporal
    `_adhoc_user_map`, de la que cuelga todo el mapeo de identidades.

    Tampoco puede ir por `exec_driver_sql`: SQLAlchemy lo pasa por la
    interpolación de psycopg2 y cualquier `%` del SQL revienta con
    "immutabledict is not a sequence". Y hay porcentajes de verdad en los datos
    (22 en incidencias, 12 en tareas, 10 en comentarios), no solo en los
    comentarios del script. `cursor.execute(sql)` con un solo argumento no
    interpola nada.
    """
    from itcj2.database import engine

    import_dir = PROJECT_ROOT / "database" / "DML" / "adhoc" / "legacy_import"
    if not import_dir.exists():
        click.echo(click.style(
            f"ERROR: no existe {import_dir}.\n"
            "Genera los .sql primero: python scripts/adhoc_etl/run.py", fg="red"), err=True)
        raise click.Abort()

    files = sorted(import_dir.glob("*.sql"))
    if not files:
        click.echo(click.style(f"ERROR: no hay .sql en {import_dir}", fg="red"), err=True)
        raise click.Abort()

    click.echo(f"Importando el SGC legacy desde {import_dir}")
    click.echo(f"{len(files)} archivos, una sola transacción"
               + (" (DRY-RUN: se revierte al final)\n" if dry_run else "\n"))

    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        for path in files:
            click.echo(f"  {path.name} ... ", nl=False)
            cursor.execute(path.read_text(encoding="utf-8"))
            for notice in getattr(raw.driver_connection, "notices", [])[-3:]:
                click.echo(click.style(f"\n      {notice.strip()}", fg="cyan"), nl=False)
            click.echo(click.style(" OK", fg="green"))
        if dry_run:
            raw.rollback()
            click.echo(click.style(
                "\nDRY-RUN: todo corrió y se revirtió. La base quedó como estaba.",
                fg="yellow"))
        else:
            raw.commit()
            click.echo(click.style(
                "\nOK: historial del SGC legacy importado y verificado.", fg="green"))
    except Exception as exc:
        raw.rollback()
        click.echo(click.style(f"FALLO\n\n{exc}", fg="red"), err=True)
        click.echo(click.style(
            "La transacción se revirtió entera: la base quedó como estaba.", fg="yellow"),
            err=True)
        raise click.Abort()
    finally:
        raw.close()


@click.group("adhoc")
def adhoc_cli():
    """Comandos administrativos de la app Adhoc (Calidad)."""


adhoc_cli.add_command(init_adhoc_command)
adhoc_cli.add_command(grant_incident_files_command)
adhoc_cli.add_command(import_legacy_command)
