#!/usr/bin/env python3
"""
Comandos Flask para ejecutar scripts SQL de inicialización
"""
import os
import click
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import text
from itcj.core.extensions import db


@click.command('init-db')
@with_appcontext
def init_database_command():
    """Ejecuta todos los scripts SQL de inicialización en orden."""
    click.echo('Iniciando carga de datos base...')
    
    # Definir el orden de ejecución de los directorios
    sql_directories = [
        ('app/database/DML/core', [
            '00_insert_apps.sql',
            '01_insert_departments.sql',
            '02_insert_positions.sql',
            '03_insert_icons_deparments.sql',
            '04_insert_roles.sql',
            '05_insert_permissions.sql',
            '06_insert_role_permissions.sql',
            '07_insert_user.sql',
            '08_insert_role_positions_helpdesk.sql',
            '09_insert_user_positions.sql',
            '10_insert_user_roles.sql'
        ]),
        ('app/database/DML/core/agendatec', [
            '01_insert_permissions.sql',
            '02_insert_user_app.sql',
            '03_insert_role_permission.sql',
        ]),
        ('app/database/DML/helpdesk', [
            '01_insert_permissions.sql',
            '02_insert_roles.sql',
            '03_insert_role_permission.sql',
            '04_insert_categories.sql',
            '05_insert_inventory_categories.sql',
            '06_insert_enhanced_inventory_categories.sql',
            '07_insert_position_app_perm.sql'
        ])
    ]
    
    # Obtener la ruta base del proyecto
    base_path = current_app.root_path
    project_root = os.path.dirname(os.path.dirname(base_path))
    
    try:
        for directory, files in sql_directories:
            directory_path = os.path.join(project_root, directory)
            
            click.echo(f'\n📁 Procesando directorio: {directory}')
            
            if not os.path.exists(directory_path):
                click.echo(f'⚠️  Directorio no encontrado: {directory_path}')
                continue
            
            for sql_file in files:
                file_path = os.path.join(directory_path, sql_file)
                
                if not os.path.exists(file_path):
                    click.echo(f'⚠️  Archivo no encontrado: {sql_file}')
                    continue
                
                try:
                    click.echo(f'   🔄 Ejecutando: {sql_file}')
                    execute_sql_file(file_path)
                    click.echo(f'   ✅ Completado: {sql_file}')
                    
                except Exception as e:
                    click.echo(f'   ❌ Error en {sql_file}: {str(e)}')
                    raise
        
        click.echo('\n🎉 ¡Inicialización completada exitosamente!')
        
    except Exception as e:
        click.echo(f'\n💥 Error durante la inicialización: {str(e)}')
        raise


def execute_sql_file(file_path):
    """Ejecuta un archivo SQL específico."""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            sql_content = file.read()
        
        # Limpiar comentarios de una forma más inteligente
        cleaned_lines = []
        for line in sql_content.split('\n'):
            # Si la línea tiene comentario en línea, mantener solo la parte antes del comentario
            if '--' in line:
                # Buscar el comentario pero asegurarse que no esté dentro de una cadena
                comment_pos = line.find('--')
                # Tomar solo la parte antes del comentario
                line = line[:comment_pos].rstrip()
            
            # Agregar la línea si no está vacía
            if line.strip():
                cleaned_lines.append(line)
        
        cleaned_content = '\n'.join(cleaned_lines)
        
        # Detectar si hay bloques DO $$ ... END $$; o CREATE FUNCTION, etc.
        if any(keyword in cleaned_content.upper() for keyword in ['DO $$', 'CREATE OR REPLACE FUNCTION', 'CREATE FUNCTION']):
            # Ejecutar todo el archivo como un solo bloque
            with db.engine.connect() as connection:
                if cleaned_content.strip():
                    connection.execute(text(cleaned_content))
                    connection.commit()
        else:
            # Para archivos SQL simples, dividir por statements
            statements = [stmt.strip() for stmt in cleaned_content.split(';') if stmt.strip()]
            
            with db.engine.connect() as connection:
                for statement in statements:
                    if statement and statement.strip():
                        connection.execute(text(statement))
                connection.commit()
                
    except Exception as e:
        raise Exception(f"Error ejecutando {file_path}: {str(e)}")


@click.command('reset-db')
@with_appcontext 
def reset_database_command():
    """Reinicia la base de datos y ejecuta las migraciones."""
    click.echo('🔄 Reiniciando base de datos...')
    
    try:
        # Eliminar todas las tablas
        db.drop_all()
        click.echo('✅ Tablas eliminadas')
        
        # Crear todas las tablas
        db.create_all()
        click.echo('✅ Tablas creadas')
        
        # Ejecutar inicialización
        ctx = click.get_current_context()
        ctx.invoke(init_database_command)
        
    except Exception as e:
        click.echo(f'❌ Error durante el reset: {str(e)}')
        raise


@click.command('check-db')
@with_appcontext
def check_database_command():
    """Verifica el estado de la base de datos."""
    click.echo('🔍 Verificando estado de la base de datos...')
    
    try:
        with db.engine.connect() as connection:
            # Verificar apps
            result = connection.execute(text("SELECT COUNT(*) as count FROM core_apps")).fetchone()
            click.echo(f'📱 Apps registradas: {result.count}')
            
            # Verificar departamentos
            result = connection.execute(text("SELECT COUNT(*) as count FROM core_departments")).fetchone()
            click.echo(f'🏢 Departamentos: {result.count}')
            
            # Verificar posiciones
            result = connection.execute(text("SELECT COUNT(*) as count FROM core_positions")).fetchone()
            click.echo(f'👔 Posiciones: {result.count}')
            
            # Verificar permisos
            result = connection.execute(text("SELECT COUNT(*) as count FROM core_permissions")).fetchone()
            click.echo(f'🔐 Permisos: {result.count}')
            
            # Verificar roles
            result = connection.execute(text("SELECT COUNT(*) as count FROM core_roles")).fetchone()
            click.echo(f'👥 Roles: {result.count}')
            
        click.echo('✅ Verificación completada')
        
    except Exception as e:
        click.echo(f'❌ Error durante la verificación: {str(e)}')
        raise


@click.command('execute-sql')
@click.argument('sql_file')
@with_appcontext
def execute_single_sql_command(sql_file):
    """Ejecuta un archivo SQL específico."""
    click.echo(f'🔄 Ejecutando archivo: {sql_file}')
    
    # Obtener la ruta base del proyecto
    base_path = current_app.root_path
    project_root = os.path.dirname(os.path.dirname(base_path))
    
    # Construir la ruta completa
    if not os.path.isabs(sql_file):
        file_path = os.path.join(project_root, sql_file)
    else:
        file_path = sql_file
    
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Archivo no encontrado: {file_path}")
            
        execute_sql_file(file_path)
        click.echo(f'✅ Archivo ejecutado exitosamente: {sql_file}')
        
    except Exception as e:
        click.echo(f'❌ Error ejecutando {sql_file}: {str(e)}')
        raise


def register_commands(app):
    """Registra todos los comandos en la aplicación Flask."""
    app.cli.add_command(init_database_command)
    app.cli.add_command(reset_database_command)
    app.cli.add_command(check_database_command)
    app.cli.add_command(execute_single_sql_command)