# itcj/apps/helpdesk/commands.py

"""
Comandos CLI para la aplicación Help-Desk
"""

from flask import current_app
import click
from flask.cli import with_appcontext
from itcj.core.extensions import db
from itcj.apps.helpdesk.models import InventoryCategory, InventoryItem, InventoryGroup, InventoryGroupCapacity
from itcj.core.models.department import Department
from datetime import date
import csv
import os


# ==================== MAPEO DE DEPARTAMENTOS ====================
DEPARTMENT_MAPPING = {
    'CENTRO DE COMPUTO': 'comp_center',
    'CENTRO DE INFORMACION': 'info_resources',
    'CIENCIAS BASICAS': 'basic_sciences',
    'COMUNICACIÓN': 'comms_diffusion',
    'DESARROLLO ACADEMICO': 'academic_dev',
    'DIRECCION': 'direction',
    'DIRECCION ': 'direction',  # Con espacio
    'DIV. EST. PROF': 'prof_studies_div',
    'ECONOMICO ADMINISTARTIVO': 'eco_admin_sci',
    'EDUCACION A DISTANCIA': 'basic_sciences',
    'ELECTRICA-ELECTRONICA': 'elec_electronics',
    'INGENIERIA INDUSTRIAL': 'industrial_eng',
    'MANTENIMIENTO': 'equipment_maint',
    'METAL MECANICA': 'metal_mechanics',
    'METALMECANICA': 'metal_mechanics',
    'METALMECANICA ': 'metal_mechanics',  # Con espacio
    'METALMECANICA TALLER': 'metal_mechanics',
    'PLANEACION': 'planning',
    'POSGRADO': 'postgrad_research',
    'RECURSOS FINANCIEROS': 'financial_resources',
    'RECURSOS MATERIALES ': 'mat_services',
    'SERVICIOS ESCOLARES': 'school_services',
    'SISTEMAS': 'sys_computing',
    'SUBDIRECCION': 'sub_planning',
    'SUBDIRECCION ACADEMICA': 'sub_academic',
    'SUBDIRECCION ADMINISTRATIVA': 'sub_admin_services',
    'VINCULACION': 'tech_management',
    # Mapeos especiales
    'SERVICIO SOCIAL': 'tech_management',
    'SERVICIO MEDICO': 'school_services',
    'CALIDAD': 'direction',
    'MECATRONICA': 'elec_electronics',
    'AUDITORIO': 'comms_diffusion',
    'GIMNACIO': 'extracurricular_act',
    'TITULACION': 'prof_studies_div',
    '800´S': 'industrial_eng',
    'INDUSTRIAL': 'industrial_eng',
    'INDUSTRIAL ': 'industrial_eng',
    'LABORATORIO DE ELECTRICA': 'elec_electronics',
    'DELEGACIÓN SINDICAL' : ''
}

# Mapeo para Delegación Sindical
DEPARTMENT_MAPPING['DELEGACIÓN SINDICAL'] = 'union_delegation'
DEPARTMENT_MAPPING['SINDICATO'] = 'union_delegation'

# Departamentos a ignorar
IGNORE_DEPARTMENTS = ['GUILLOT', 'GUILLOT ']


def normalize_storage(storage_str):
    """Normaliza valores de almacenamiento a GB"""
    storage_str = str(storage_str).strip().upper()
    if 'TERA' in storage_str:
        return 1000
    try:
        return int(float(storage_str))
    except:
        return 500  # Default


def normalize_ram(ram_str):
    """Normaliza valores de RAM a GB"""
    try:
        return int(float(str(ram_str).strip()))
    except:
        return 4  # Default


def determine_group_type(location_name):
    """Determina el tipo de grupo basado en el nombre de ubicación"""
    location_upper = location_name.upper()
    
    if any(word in location_upper for word in ['LABORATORIO', 'LAB', 'TALLER']):
        return 'LABORATORY'
    elif any(word in location_upper for word in ['SALA', 'SALON', 'AULA']):
        return 'CLASSROOM'
    elif any(word in location_upper for word in ['CUBICULO', 'CUBÍCULO', 'OFICINA', 'JEFATURA']):
        return 'OFFICE'
    else:
        return 'CLASSROOM'  # Default


@click.command('load-inventory-csv')
@with_appcontext
def load_inventory_csv():
    """
    Carga el inventario desde CSV y crea equipos y grupos
    
    Lee el archivo database/CSV/inventario.csv y:
    - Crea grupos para ubicaciones con múltiples equipos
    - Crea items de inventario con especificaciones
    - Asocia equipos a grupos automáticamente
    """
    
    csv_path = os.path.join(current_app.root_path, '..', 'database', 'CSV', 'inventario.csv')
    
    if not os.path.exists(csv_path):
        click.echo(click.style(f'❌ Archivo no encontrado: {csv_path}', fg='red'))
        return
    
    click.echo(click.style('🚀 Iniciando carga de inventario desde CSV...', fg='cyan', bold=True))
    click.echo(f'📂 Archivo: {csv_path}')
    
    # Obtener categoría "computer"
    computer_category = InventoryCategory.query.filter_by(code='computer').first()
    if not computer_category:
        click.echo(click.style('❌ Categoría "computer" no encontrada. Ejecuta primero las migraciones.', fg='red'))
        return
    
    click.echo(f'✅ Categoría encontrada: {computer_category.name} (ID: {computer_category.id})')
    
    # Contadores
    stats = {
        'total_rows': 0,
        'ignored': 0,
        'groups_created': 0,
        'items_created': 0,
        'errors': 0
    }
    
    # Almacenar grupos creados para no duplicar
    created_groups = {}  # key: (dept_code, location_name)
    
    # Contador de serie
    serial_counter = 1
    
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as csvfile:
            # Detectar delimitador
            reader = csv.DictReader(csvfile, delimiter=';')
            
            click.echo('\n📊 Procesando registros...\n')
            
            for row in reader:
                stats['total_rows'] += 1
                
                try:
                    # Extraer datos
                    dept_name = row.get('DEPARTAMENTO', '').strip()
                    location = row.get('UBICACIÓN', '').strip() or row.get('UBICACION', '').strip()
                    quantity = int(row.get('CANTIDAD', '1').strip() or '1')
                    brand = row.get('MARCA', '').strip()
                    model = row.get('MODELO', '').strip()
                    storage = row.get('DISCO DURO ', '').strip() or row.get('DISCO DURO', '').strip()
                    ram = row.get('RAM (GB)', '').strip()
                    
                    # Validar departamento
                    if not dept_name or dept_name in IGNORE_DEPARTMENTS:
                        stats['ignored'] += 1
                        click.echo(f'⏭️  Fila {stats["total_rows"]}: Ignorado - {dept_name}')
                        continue
                    
                    # Mapear departamento
                    dept_code = DEPARTMENT_MAPPING.get(dept_name.upper())
                    if not dept_code:
                        click.echo(click.style(f'⚠️  Fila {stats["total_rows"]}: Departamento no mapeado: {dept_name}', fg='yellow'))
                        stats['ignored'] += 1
                        continue
                    
                    # Buscar departamento en BD
                    department = Department.query.filter_by(code=dept_code).first()
                    if not department:
                        click.echo(click.style(f'❌ Fila {stats["total_rows"]}: Departamento no encontrado en BD: {dept_code}', fg='red'))
                        stats['errors'] += 1
                        continue
                    
                    # Normalizar especificaciones
                    storage_gb = normalize_storage(storage)
                    ram_gb = normalize_ram(ram)
                    
                    specifications = {
                        "processor": "N/A",
                        "ram": str(ram_gb),
                        "storage": str(storage_gb),
                        "storage_type": "HDD",
                        "os": "Windows"
                    }
                    
                    # Determinar si crear grupo o equipo individual
                    group = None
                    
                    if quantity > 1 and location:
                        # Crear o recuperar grupo
                        group_key = (dept_code, location.upper())
                        
                        if group_key in created_groups:
                            group = created_groups[group_key]
                            click.echo(f'♻️  Usando grupo existente: {location} ({quantity} equipos)')
                        else:
                            # Crear nuevo grupo
                            group_code = f"{dept_code.upper()}-{location.replace(' ', '-')[:20]}"
                            group_type = determine_group_type(location)
                            
                            group = InventoryGroup(
                                name=location,
                                code=group_code,
                                department_id=department.id,
                                group_type=group_type,
                                description=f"Grupo creado desde CSV - {location}",
                                created_by_id=10
                            )
                            
                            db.session.add(group)
                            db.session.flush()  # Obtener ID
                            
                            # Crear capacidad para computadoras
                            capacity = InventoryGroupCapacity(
                                group_id=group.id,
                                category_id=computer_category.id,
                                max_capacity=quantity + 5  # Un poco más por si acaso
                            )
                            db.session.add(capacity)
                            
                            created_groups[group_key] = group
                            stats['groups_created'] += 1
                            
                            click.echo(click.style(f'✨ Grupo creado: {location} (capacidad: {quantity} equipos)', fg='green'))
                    
                    # Crear equipos
                    for i in range(quantity):
                        # Generar número de inventario
                        inventory_number = f"COMP-2022-{stats['items_created'] + 1:04d}"
                        
                        # Generar número de serie
                        serial_number = f"ITCJ-2022-{serial_counter:06d}"
                        serial_counter += 1
                        
                        # Crear item
                        item = InventoryItem(
                            inventory_number=inventory_number,
                            category_id=computer_category.id,
                            brand=brand or 'N/A',
                            model=model or 'N/A',
                            serial_number=serial_number,
                            specifications=specifications,
                            department_id=department.id,
                            group_id=group.id if group else None,
                            location_detail=location if quantity == 1 else None,  # Solo si es individual
                            status='ACTIVE',
                            acquisition_date=date.today(),
                            registered_by_id=10
                        )
                        
                        db.session.add(item)
                        stats['items_created'] += 1
                    
                    # Commit cada 50 registros
                    if stats['items_created'] % 50 == 0:
                        db.session.commit()
                        click.echo(f'💾 Guardado intermedio: {stats["items_created"]} equipos creados')
                
                except Exception as e:
                    stats['errors'] += 1
                    click.echo(click.style(f'❌ Error en fila {stats["total_rows"]}: {str(e)}', fg='red'))
                    continue
            
            # Commit final
            db.session.commit()
            
            # Resumen
            click.echo('\n' + '='*60)
            click.echo(click.style('✅ PROCESO COMPLETADO', fg='green', bold=True))
            click.echo('='*60)
            click.echo(f'📊 Total de filas procesadas: {stats["total_rows"]}')
            click.echo(f'✨ Grupos creados: {stats["groups_created"]}')
            click.echo(f'💻 Equipos creados: {stats["items_created"]}')
            click.echo(f'⏭️  Registros ignorados: {stats["ignored"]}')
            click.echo(f'❌ Errores: {stats["errors"]}')
            click.echo('='*60)
            
    except Exception as e:
        db.session.rollback()
        click.echo(click.style(f'\n❌ ERROR CRÍTICO: {str(e)}', fg='red', bold=True))
        raise


def register_helpdesk_commands(app):
    """
    Registra todos los comandos de Help-Desk en la aplicación Flask
    """
    app.cli.add_command(load_inventory_csv)