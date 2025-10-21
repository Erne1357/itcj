from flask import current_app, url_for
import click
from flask.cli import with_appcontext
from itcj.core.models.app import App
from itcj.core.models.permission import Permission
from itcj.core.extensions import db
# itcj/apps/helpdesk/commands.py

@click.command('init-helpdesk-navigation-perms')
@with_appcontext
def init_helpdesk_navigation_permissions():
    """Inicializa permisos para navegación de Help-Desk"""
    
    app = App.query.filter_by(key='helpdesk').first()
    if not app:
        click.echo("❌ App 'helpdesk' no encontrada. Créala primero.")
        return
    
    navigation_permissions = [
        # Usuarios
        {'code': 'helpdesk.tickets.create', 'name': 'Crear tickets', 'description': 'Crear nuevos tickets'},
        {'code': 'helpdesk.tickets.own.read', 'name': 'Ver propios tickets', 'description': 'Ver sus propios tickets'},
        
        # Secretaría
        {'code': 'helpdesk.secretary.dashboard', 'name': 'Dashboard secretaría', 'description': 'Acceso a dashboard de secretaría'},
        {'code': 'helpdesk.stats.view', 'name': 'Ver estadísticas', 'description': 'Ver estadísticas del sistema'},
        
        # Técnicos
        {'code': 'helpdesk.technician.dashboard', 'name': 'Dashboard técnico', 'description': 'Acceso a dashboard de técnico'},
        {'code': 'helpdesk.tickets.assigned.read', 'name': 'Ver tickets asignados', 'description': 'Ver tickets asignados personalmente'},
        {'code': 'helpdesk.tickets.team.read', 'name': 'Ver tickets del equipo', 'description': 'Ver tickets del equipo completo'},
        
        # Jefe de Departamento
        {'code': 'helpdesk.department.dashboard', 'name': 'Dashboard departamento', 'description': 'Dashboard del departamento'},
        {'code': 'helpdesk.inventory.view_own_dept', 'name': 'Ver inventario depto', 'description': 'Ver inventario del departamento'},
        
        # Admin
        {'code': 'helpdesk.admin.access', 'name': 'Acceso admin', 'description': 'Acceso a sección administrativa'},
        {'code': 'helpdesk.inventory.view', 'name': 'Ver todo inventario', 'description': 'Ver inventario completo'},
    ]
    
    for perm_data in navigation_permissions:
        existing = Permission.query.filter_by(
            app_id=app.id,
            code=perm_data['code']
        ).first()
        
        if not existing:
            perm = Permission(
                app_id=app.id,
                code=perm_data['code'],
                name=perm_data['name'],
                description=perm_data['description']
            )
            db.session.add(perm)
            click.echo(f"✓ Creado: {perm_data['code']}")
        else:
            click.echo(f"- Ya existe: {perm_data['code']}")
    
    db.session.commit()
    click.echo("✅ Permisos de navegación inicializados")


@click.command('init-inventory-perms')
@with_appcontext
def init_inventory_permissions():
    """Inicializa permisos para el módulo de inventario"""
    
    app = App.query.filter_by(key='helpdesk').first()
    if not app:
        click.echo("❌ App 'helpdesk' no encontrada.")
        return
    
    inventory_permissions = [
        # ==================== ADMIN ====================
        {'code': 'helpdesk.inventory.view', 'name': 'Ver inventario completo', 
         'description': 'Ver todos los equipos del inventario institucional'},
        {'code': 'helpdesk.inventory.create', 'name': 'Registrar equipos', 
         'description': 'Registrar nuevos equipos en el inventario'},
        {'code': 'helpdesk.inventory.edit', 'name': 'Editar equipos', 
         'description': 'Modificar información de equipos'},
        {'code': 'helpdesk.inventory.deactivate', 'name': 'Dar de baja equipos', 
         'description': 'Desactivar equipos del inventario'},
        {'code': 'helpdesk.inventory.transfer', 'name': 'Transferir entre departamentos', 
         'description': 'Mover equipos entre departamentos'},
        {'code': 'helpdesk.inventory.stats', 'name': 'Ver estadísticas inventario', 
         'description': 'Acceso a reportes y estadísticas de inventario'},
        {'code': 'helpdesk.inventory.export', 'name': 'Exportar inventario', 
         'description': 'Exportar datos del inventario'},
        
        # ==================== JEFE DE DEPARTAMENTO ====================
        {'code': 'helpdesk.inventory.view_own_dept', 'name': 'Ver inventario departamento', 
         'description': 'Ver equipos del propio departamento'},
        {'code': 'helpdesk.inventory.assign', 'name': 'Asignar equipos', 
         'description': 'Asignar equipos a usuarios del departamento'},
        {'code': 'helpdesk.inventory.unassign', 'name': 'Liberar equipos', 
         'description': 'Liberar equipos asignados'},
        {'code': 'helpdesk.inventory.update_location', 'name': 'Actualizar ubicación', 
         'description': 'Cambiar ubicación física de equipos'},
        
        # ==================== CATEGORÍAS ====================
        {'code': 'helpdesk.inventory_categories.view', 'name': 'Ver categorías inventario', 
         'description': 'Ver categorías de inventario'},
        {'code': 'helpdesk.inventory_categories.manage', 'name': 'Gestionar categorías', 
         'description': 'Crear y editar categorías de inventario'},
    ]
    
    for perm_data in inventory_permissions:
        existing = Permission.query.filter_by(
            app_id=app.id,
            code=perm_data['code']
        ).first()
        
        if not existing:
            perm = Permission(
                app_id=app.id,
                code=perm_data['code'],
                name=perm_data['name'],
                description=perm_data['description']
            )
            db.session.add(perm)
            click.echo(f"✓ Creado: {perm_data['code']}")
        else:
            click.echo(f"- Ya existe: {perm_data['code']}")
    
    db.session.commit()
    click.echo("✅ Permisos de inventario inicializados")


@click.command('assign-inventory-perms')
@with_appcontext
def assign_inventory_permissions_to_roles():
    """Asigna permisos de inventario a los roles existentes"""
    from itcj.core.models.role import Role
    from itcj.core.models.role_permission import RolePermission
    
    app = App.query.filter_by(key='helpdesk').first()
    if not app:
        click.echo("❌ App 'helpdesk' no encontrada.")
        return
    
    # Definir qué permisos tiene cada rol
    role_permissions = {
        'admin': [
            'helpdesk.inventory.view',
            'helpdesk.inventory.create',
            'helpdesk.inventory.edit',
            'helpdesk.inventory.deactivate',
            'helpdesk.inventory.transfer',
            'helpdesk.inventory.stats',
            'helpdesk.inventory.export',
            'helpdesk.inventory_categories.view',
            'helpdesk.inventory_categories.manage',
        ],
        'secretary': [
            'helpdesk.inventory.view',
            'helpdesk.inventory.create',
            'helpdesk.inventory.edit',
            'helpdesk.inventory.stats',
            'helpdesk.inventory_categories.view',
        ],
        'department_head': [
            'helpdesk.inventory.view_own_dept',
            'helpdesk.inventory.assign',
            'helpdesk.inventory.unassign',
            'helpdesk.inventory.update_location',
            'helpdesk.inventory_categories.view',
        ],
        # Usuarios regulares: solo pueden VER sus equipos (sin permiso específico, por lógica)
    }
    
    for role_name, perm_codes in role_permissions.items():
        role = Role.query.filter_by(name=role_name).first()
        if not role:
            click.echo(f"⚠️  Rol '{role_name}' no encontrado, saltando...")
            continue
        
        for perm_code in perm_codes:
            # Buscar permiso
            perm = Permission.query.filter_by(
                app_id=app.id,
                code=perm_code
            ).first()
            
            if not perm:
                click.echo(f"⚠️  Permiso '{perm_code}' no encontrado")
                continue
            
            # Verificar si ya tiene el permiso
            existing = RolePermission.query.filter_by(
                role_id=role.id,
                perm_id=perm.id
            ).first()
            
            if not existing:
                role_perm = RolePermission(
                    role_id=role.id,
                    perm_id=perm.id
                )
                db.session.add(role_perm)
                click.echo(f"✓ Asignado '{perm_code}' a rol '{role_name}'")
            else:
                click.echo(f"- '{role_name}' ya tiene '{perm_code}'")
    
    db.session.commit()
    click.echo("✅ Permisos asignados a roles")

@click.command('init-inventory-categories')
@with_appcontext
def init_inventory_categories():
    """Crea categorías iniciales de inventario"""
    from itcj.apps.helpdesk.models import InventoryCategory
    
    categories = [
        {
            'code': 'computer',
            'name': 'Computadora',
            'description': 'Equipos de cómputo (Desktop, Laptop, All-in-One)',
            'icon': 'fas fa-desktop',
            'inventory_prefix': 'COMP',
            'requires_specs': True,
            'display_order': 1,
            'spec_template': {
                'processor': {'label': 'Procesador', 'type': 'text', 'required': True},
                'ram': {'label': 'RAM (GB)', 'type': 'number', 'required': True},
                'storage': {'label': 'Almacenamiento (GB)', 'type': 'number', 'required': True},
                'storage_type': {'label': 'Tipo Almacenamiento', 'type': 'select', 
                                'options': ['HDD', 'SSD', 'Hybrid'], 'required': True},
                'os': {'label': 'Sistema Operativo', 'type': 'text', 'required': False},
                'has_monitor': {'label': '¿Tiene monitor?', 'type': 'boolean', 'required': False},
                'monitor_size': {'label': 'Tamaño Monitor (pulgadas)', 'type': 'number', 'required': False}
            }
        },
        {
            'code': 'printer',
            'name': 'Impresora',
            'description': 'Impresoras y multifuncionales',
            'icon': 'fas fa-print',
            'inventory_prefix': 'IMP',
            'requires_specs': True,
            'display_order': 2,
            'spec_template': {
                'type': {'label': 'Tipo', 'type': 'select', 
                        'options': ['Láser', 'Inyección', 'Matriz'], 'required': True},
                'color': {'label': '¿Imprime a color?', 'type': 'boolean', 'required': True},
                'network': {'label': '¿Red?', 'type': 'boolean', 'required': False},
                'duplex': {'label': '¿Dúplex?', 'type': 'boolean', 'required': False},
                'scanner': {'label': '¿Escáner?', 'type': 'boolean', 'required': False}
            }
        },
        {
            'code': 'projector',
            'name': 'Proyector/Cañón',
            'description': 'Proyectores para aulas y salas',
            'icon': 'fas fa-video',
            'inventory_prefix': 'PROJ',
            'requires_specs': True,
            'display_order': 3,
            'spec_template': {
                'lumens': {'label': 'Lúmenes', 'type': 'number', 'required': False},
                'resolution': {'label': 'Resolución', 'type': 'text', 'required': False},
                'connection_types': {'label': 'Tipos de conexión', 'type': 'text', 'required': False}
            }
        },
        {
            'code': 'network_device',
            'name': 'Dispositivo de Red',
            'description': 'Switches, routers, access points',
            'icon': 'fas fa-network-wired',
            'inventory_prefix': 'NET',
            'requires_specs': True,
            'display_order': 4,
            'spec_template': {
                'device_type': {'label': 'Tipo', 'type': 'select', 
                               'options': ['Switch', 'Router', 'Access Point', 'Firewall'], 'required': True},
                'ports': {'label': 'Número de puertos', 'type': 'number', 'required': False},
                'speed': {'label': 'Velocidad', 'type': 'text', 'required': False},
                'managed': {'label': '¿Administrable?', 'type': 'boolean', 'required': False}
            }
        },
        {
            'code': 'phone',
            'name': 'Teléfono',
            'description': 'Teléfonos IP y análogos',
            'icon': 'fas fa-phone',
            'inventory_prefix': 'TEL',
            'requires_specs': False,
            'display_order': 5,
            'spec_template': {
                'type': {'label': 'Tipo', 'type': 'select', 
                        'options': ['IP', 'Análogo'], 'required': True},
                'extension': {'label': 'Extensión', 'type': 'text', 'required': False}
            }
        },
        {
            'code': 'scanner',
            'name': 'Escáner',
            'description': 'Escáneres dedicados',
            'icon': 'fas fa-scanner',
            'inventory_prefix': 'SCAN',
            'requires_specs': False,
            'display_order': 6
        },
        {
            'code': 'other',
            'name': 'Otro Equipo',
            'description': 'Otros equipos no clasificados',
            'icon': 'fas fa-box',
            'inventory_prefix': 'OTH',
            'requires_specs': False,
            'display_order': 99
        }
    ]
    
    for cat_data in categories:
        existing = InventoryCategory.query.filter_by(code=cat_data['code']).first()
        if not existing:
            category = InventoryCategory(**cat_data)
            db.session.add(category)
            click.echo(f"✓ Creada categoría: {cat_data['name']}")
        else:
            click.echo(f"- Ya existe: {cat_data['name']}")
    
    db.session.commit()
    click.echo("✅ Categorías de inventario inicializadas")

# Registrar comandos en la app
def register_helpdesk_commands(app):
    """Registra todos los comandos de Help-Desk"""
    app.cli.add_command(init_helpdesk_navigation_permissions)  # Fase 1
    app.cli.add_command(init_inventory_permissions)  # Nuevo
    app.cli.add_command(assign_inventory_permissions_to_roles)  # Nuevo
    app.cli.add_command(init_inventory_categories)