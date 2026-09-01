#!/usr/bin/env python3
"""
Comandos CLI de VisteTec para itcj2 — sin Flask context.
Equivalente a itcj/apps/vistetec/commands.py.
"""
from pathlib import Path

import click
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).parent.parent.parent


def _execute_sql_scripts(db, scripts_dir: str) -> int:
    """Ejecuta todos los scripts SQL de un directorio en orden alfabético.

    Invalida el caché de authz al final, incondicionalmente: `database/DML/
    vistetec/` incluye `02_insert_permissions.sql` y
    `03_insert_role_permissions.sql`, así que este helper es la misma puerta
    de entrada que `itcj2/cli/agendatec.py::_execute_sql_scripts` ya tuvo que
    cerrar (Tarea 7) — es una copia deliberadamente separada, no compartida
    con esa (ver la nota en el CLI de agendatec sobre por qué no se unificaron),
    pero el hueco es idéntico y necesita el mismo cierre.

    Este `db` es del CALLER y no se commitea aquí, así que esta invalidación
    corre ANTES de ese commit. `init_vistetec_command` invalida OTRA VEZ
    después de su propio `db.commit()` — sin eso, un lector que caiga en la
    ventana pre-commit repuebla el caché con el estado viejo aún no
    commiteado y esa entrada sobrevive el TTL completo (mismo patrón que
    `bump_version`/`forget_cached_version`, Tareas 5/6, para la época de
    sesión).
    """
    scripts_path = Path(scripts_dir)
    if not scripts_path.exists():
        click.echo(f"   ⚠️  Directorio no encontrado: {scripts_dir}")
        return 0

    sql_files = sorted(scripts_path.glob("*.sql"))
    if not sql_files:
        click.echo(f"   ℹ️  No hay scripts SQL en: {scripts_dir}")
        return 0

    executed = 0
    for sql_file in sql_files:
        try:
            click.echo(f"   📄 Ejecutando: {sql_file.name}")
            sql_content = sql_file.read_text(encoding="utf-8")
            db.execute(text(sql_content))
            executed += 1
        except Exception as e:
            click.echo(f"   ❌ Error en {sql_file.name}: {str(e)}")
            raise

    try:
        from itcj2.core.services.authz_cache import invalidate_all
        invalidate_all()
        click.echo("   🧹 Caché de authz invalidado.")
    except Exception as e:
        click.echo(f"   ⚠️  No se pudo invalidar el caché de authz ({e}). "
                   "Aplicará en ≤5 min por TTL.")

    return executed


@click.command("init-vistetec")
def init_vistetec_command():
    """
    Inicializa la aplicación VisteTec ejecutando los scripts DML.

    Ejecuta todos los archivos SQL de database/DML/vistetec/ en orden.
    """
    from itcj2.database import SessionLocal

    click.echo("👕 Iniciando configuración de VisteTec...\n")
    scripts_dir = PROJECT_ROOT / "database" / "DML" / "vistetec"
    click.echo(f"📂 Directorio de scripts: {scripts_dir}\n")

    with SessionLocal() as db:
        try:
            click.echo("🔐 Ejecutando scripts de inicialización...")
            scripts_executed = _execute_sql_scripts(db, str(scripts_dir))

            if scripts_executed > 0:
                db.commit()
                # Segunda invalidación, ya con el commit hecho: cierra la
                # ventana pre-commit de _execute_sql_scripts (ver su
                # docstring). No es redundante con esa.
                from itcj2.core.services.authz_cache import invalidate_all
                invalidate_all()
                click.echo(f"\n✅ VisteTec inicializado correctamente ({scripts_executed} scripts ejecutados)")
            else:
                click.echo("\n⚠️  No se ejecutaron scripts")

        except Exception as e:
            db.rollback()
            click.echo(f"\n❌ Error durante la inicialización: {str(e)}")
            raise click.Abort()


@click.group("vistetec")
def vistetec_cli():
    """Comandos CLI del módulo VisteTec."""


vistetec_cli.add_command(init_vistetec_command)
