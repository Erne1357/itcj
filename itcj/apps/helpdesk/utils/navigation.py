# itcj/apps/helpdesk/utils/navigation.py

def get_helpdesk_navigation(user_permissions: set[str], user_roles: set[str]):
    """
    Devuelve la navegación de Help-Desk basada en permisos y roles del usuario.
    Similar a get_agendatec_navigation pero para helpdesk.
    """
    
    # Estructura completa de navegación con permisos requeridos
    full_nav_structure = [
        # ==================== USUARIOS REGULARES ====================
        {
            "label": "Crear Ticket",
            "endpoint": "helpdesk_pages.user_pages.create_ticket",
            "icon": "fa-plus-circle",
            "permission": "helpdesk.tickets.create",
            "group": "user"
        },
        {
            "label": "Mis Tickets",
            "endpoint": "helpdesk_pages.user_pages.my_tickets",
            "icon": "fa-list",
            "permission": "helpdesk.tickets.own.read",
            "group": "user"
        },
        
        # ==================== SECRETARÍA ====================
        {
            "label": "Dashboard",
            "endpoint": "helpdesk_pages.secretary_pages.dashboard",
            "icon": "fa-tachometer-alt",
            "permission": "helpdesk.secretary.dashboard",
            "group": "secretary",
            "dropdown": [
                {
                    "label": "Cola de Tickets",
                    "endpoint": "helpdesk_pages.secretary_pages.dashboard",
                    "icon": "fa-inbox",
                    "fragment": "#queue"  # Para hacer scroll a sección
                },
                {
                    "label": "Tickets Activos",
                    "endpoint": "helpdesk_pages.secretary_pages.dashboard",
                    "icon": "fa-tasks",
                    "fragment": "#active"
                },
                {
                    "label": "Técnicos",
                    "endpoint": "helpdesk_pages.secretary_pages.dashboard",
                    "icon": "fa-users",
                    "fragment": "#technicians"
                }
            ]
        },
        {
            "label": "Estadísticas",
            "endpoint": "#",# "helpdesk_pages.secretary_pages.stats",
            "icon": "fa-chart-bar",
            "permission": "helpdesk.stats.view",
            "group": "secretary"
        },
        
        # ==================== TÉCNICOS ====================
        {
            "label": "Mi Dashboard",
            "endpoint": "helpdesk_pages.technician_pages.dashboard",
            "icon": "fa-clipboard-list",
            "permission": "helpdesk.technician.dashboard",
            "group": "technician"
        },
        {
            "label": "Mis Asignaciones",
            "endpoint": "helpdesk_pages.technician_pages.my_assignments",
            "icon": "fa-user-check",
            "permission": "helpdesk.tickets.assigned.read",
            "group": "technician"
        },
        {
            "label": "Equipo",
            "endpoint": "helpdesk_pages.technician_pages.team",
            "icon": "fa-users-cog",
            "permission": "helpdesk.tickets.team.read",
            "group": "technician"
        },
        
        # ==================== JEFE DE DEPARTAMENTO ====================
        {
            "label": "Dashboard Dept.",
            "endpoint": "helpdesk_pages.department_pages.tickets",
            "icon": "fa-building",
            "permission": "helpdesk.department.dashboard",
            "group": "department"
        },
        {
            "label": "Inventario",
            "endpoint": "#",
            "icon": "fa-boxes",
            "permission": "helpdesk.inventory.view_own_dept",
            "group": "department",
            "dropdown": [{
                "label": "Mi Inventario",
                "endpoint": "helpdesk_pages.inventory_pages.items_list",
                "icon": "fa-list"
            },
            {
                "label": "Asignar Equipo",
                "endpoint": "helpdesk_pages.inventory_pages.assign_equipment",
                "icon": "fa-plus"
            }]
        },
        
        # ==================== ADMIN ====================
        {
            "label": "Gestión",
            "endpoint": "#",
            "icon": "fa-cog",
            "permission": "helpdesk.admin.access",
            "group": "admin",
            "dropdown": [
                {
                    "label": "Dashboard Admin",
                    "endpoint": "helpdesk_pages.secretary_pages.dashboard",  # Reusa secretary
                    "icon": "fa-tachometer-alt"
                },
                {
                    "label": "Todos los Tickets",
                    "endpoint": "helpdesk_pages.admin_pages.all_tickets",
                    "icon": "fa-ticket-alt"
                },
                {
                    "label": "Categorías",
                    "endpoint": "helpdesk_pages.admin_pages.categories",
                    "icon": "fa-tags"
                },
                {
                    "label": "Estadísticas",
                    "endpoint": "#",#"helpdesk_pages.secretary_pages.stats",
                    "icon": "fa-chart-line"
                }
            ]
        },
        {
            "label": "Inventario",
            "endpoint": "#",
            "icon": "fa-warehouse",
            "permission": "helpdesk.inventory.view",
            "group": "admin",
            "dropdown": [
                {
                    "label": "Ver Inventario",
                    "endpoint": "helpdesk_pages.admin_pages.inventory_list",
                    "icon": "fa-list"
                },
                {
                    "label": "Registrar Equipo",
                    "endpoint": "helpdesk_pages.admin_pages.inventory_create",
                    "icon": "fa-plus"
                },
                {
                    "label": "Categorías Inv.",
                    "endpoint": "helpdesk_pages.admin_pages.inventory_categories",
                    "icon": "fa-folder"
                },
                {
                    "label": "Reportes",
                    "endpoint": "helpdesk_pages.admin_pages.inventory_reports",
                    "icon": "fa-file-export"
                }
            ]
        }
    ]
    
    # Filtrar items según permisos
    nav_items = []
    for item in full_nav_structure:
        # Verificar si el usuario tiene el permiso
        if "permission" in item and item["permission"] not in user_permissions:
            continue

        # Si tiene dropdown, filtrar sus items también
        if "dropdown" in item:
            filtered_dropdown = []
            for sub_item in item["dropdown"]:
                if "permission" not in sub_item or sub_item["permission"] in user_permissions:
                    filtered_dropdown.append(sub_item)
            
            # Solo incluir si tiene sub-items después del filtrado
            if filtered_dropdown:
                item_copy = item.copy()
                item_copy["dropdown"] = filtered_dropdown
                nav_items.append(item_copy)
        else:
            nav_items.append(item)
    
    return nav_items


def get_helpdesk_role_groups(user_roles: set[str]):
    """
    Determina qué grupos de navegación mostrar según los roles.
    Útil para optimizar el context processor.
    """
    groups = set()
    
    role_to_group = {
        "admin": ["admin", "secretary", "user"],  # Admin ve todo
        "secretary": ["secretary", "user"],
        "tech_desarrollo": ["technician", "user"],
        "tech_soporte": ["technician", "user"],
        "department_head": ["department", "user"],
        "staff": ["user"]
    }
    
    for role in user_roles:
        if role in role_to_group:
            groups.update(role_to_group[role])
    
    return groups