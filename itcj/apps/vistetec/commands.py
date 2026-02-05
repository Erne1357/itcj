#!/usr/bin/env python3
"""
Comandos Flask para VisteTec - Inicialización de datos
"""
from pathlib import Path

import click
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import text

from itcj.core.extensions import db


def _execute_sql_scripts(scripts_dir: str) -> int:
    """
    Ejecuta todos los scripts SQL de un directorio en orden alfabético.
    
    Args:
        scripts_dir: Ruta al directorio con los scripts SQL.
        
    Returns:
        Número de scripts ejecutados.
    """
    scripts_path = Path(scripts_dir)
    
    if not scripts_path.exists():
        click.echo(f'   ⚠️  Directorio no encontrado: {scripts_dir}')
        return 0
    
    # Obtener scripts SQL ordenados
    sql_files = sorted(scripts_path.glob('*.sql'))
    
    if not sql_files:
        click.echo(f'   ℹ️  No hay scripts SQL en: {scripts_dir}')
        return 0
    
    executed = 0
    for sql_file in sql_files:
        try:
            click.echo(f'   📄 Ejecutando: {sql_file.name}')
            sql_content = sql_file.read_text(encoding='utf-8')
            db.session.execute(text(sql_content))
            executed += 1
        except Exception as e:
            click.echo(f'   ❌ Error en {sql_file.name}: {str(e)}')
            raise
    
    return executed


@click.command('init-vistetec')
@with_appcontext
def init_vistetec_command():
    """
    Inicializa la aplicación VisteTec ejecutando los scripts DML.
    
    Ejecuta todos los archivos SQL de database/DML/vistetec/ en orden:
    - 00_insert_app.sql: Registra la app en el sistema
    - 01_insert_roles.sql: Crea los roles de la app
    - 02_insert_permissions.sql: Define los permisos
    - 03_insert_role_permissions.sql: Asocia permisos a roles
    """
    click.echo('👕 Iniciando configuración de VisteTec...\n')
    
    try:
        # Determinar la ruta base del proyecto
        base_path = Path(current_app.root_path).parent  # itcj/ -> raíz del proyecto
        scripts_dir = base_path / 'database' / 'DML' / 'vistetec'
        
        click.echo(f'📂 Directorio de scripts: {scripts_dir}\n')
        
        # Ejecutar scripts SQL
        click.echo('🔐 Ejecutando scripts de inicialización...')
        scripts_executed = _execute_sql_scripts(str(scripts_dir))
        
        if scripts_executed > 0:
            db.session.commit()
            click.echo(f'\n✅ VisteTec inicializado correctamente ({scripts_executed} scripts ejecutados)')
        else:
            click.echo('\n⚠️  No se ejecutaron scripts')
            
    except Exception as e:
        db.session.rollback()
        click.echo(f'\n❌ Error durante la inicialización: {str(e)}')
        raise click.Abort()


def register_vistetec_commands(app):
    """Registra los comandos CLI de VisteTec en la aplicación Flask."""
    app.cli.add_command(init_vistetec_command)
