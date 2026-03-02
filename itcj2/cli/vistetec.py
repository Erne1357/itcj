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
    """Ejecuta todos los scripts SQL de un directorio en orden alfabético."""
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
