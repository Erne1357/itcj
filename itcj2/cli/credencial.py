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


@credencial_cli.command("import-photos")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=str))
@click.option("--dry-run", is_flag=True, help="Solo muestra qué pasaría; no escribe nada.")
def import_photos_command(directory, dry_run):
    """Carga masiva de fotos oficiales; el nombre del archivo es el número de control."""
    from collections import Counter
    from pathlib import Path

    from itcj2.apps.credencial.services.photo_service import MAX_UPLOAD_BYTES, PhotoService
    from itcj2.database import SessionLocal

    exts = {".jpg", ".jpeg", ".png", ".webp"}
    paths = sorted(p for p in Path(directory).iterdir() if p.is_file() and p.suffix.lower() in exts)
    totals = Counter()
    with SessionLocal() as db:
        for i in range(0, len(paths), 50):
            chunk = paths[i:i + 50]
            if dry_run:
                rows = [(p.name, "no_student" if PhotoService.match_filename(db, p.name) is None else "match", "")
                        for p in chunk]
            else:
                big = [p for p in chunk if p.stat().st_size > MAX_UPLOAD_BYTES]
                res = PhotoService.import_batch(
                    db, [(p.name, p.read_bytes()) for p in chunk if p not in big], None)
                rows = [(p.name, "invalid", "La imagen pesa más de 10 MB") for p in big]
                rows += [(r.filename, r.status, r.detail) for r in res]
            for name, status, detail in rows:
                totals[status] += 1
                click.echo(f"{status:11} {name} {detail}".rstrip())
    click.echo(("\n[dry-run] " if dry_run else "\n") + ", ".join(f"{k}: {v}" for k, v in totals.items())
               + f" (total {len(paths)})")


@credencial_cli.command("assign-programs")
@click.option("--csv-path", "csv_paths", multiple=True, type=click.Path(exists=True, dir_okay=False, path_type=str),
              help="CSV de alumnos (repetible). Por defecto, los cinco de database/CSV/ que existan.")
@click.option("--overwrite", is_flag=True, help="Pisa carrera y datos que el perfil ya tiene.")
@click.option("--dry-run", is_flag=True, help="Calcula el reporte sin escribir nada.")
def assign_programs_command(csv_paths, overwrite, dry_run):
    """Asigna la carrera de cada alumno desde los CSV del padrón (gana el archivo más reciente)."""
    from pathlib import Path

    from itcj2.apps.credencial.services.program_import_service import (
        DEFAULT_CSVS, ProgramImportService, read_student_rows,
    )
    from itcj2.database import SessionLocal

    paths = [Path(p) for p in csv_paths] or [PROJECT_ROOT / p for p in DEFAULT_CSVS if (PROJECT_ROOT / p).exists()]
    if not paths:
        raise click.ClickException("No hay CSV de alumnos que leer.")
    rows = read_student_rows(paths)
    click.echo(f"{len(rows)} alumnos distintos en {len(paths)} archivo(s)")
    with SessionLocal() as db:
        rep = ProgramImportService.apply(db, rows, overwrite=overwrite, dry_run=dry_run)
    click.echo(("[dry-run] " if dry_run else "")
               + f"actualizados: {rep.updated}, creados: {rep.created}, sin alumno en BD: {rep.no_user}")
    click.echo(f"carreras sin mapear: {dict(rep.unmapped) or 'ninguna'}")
