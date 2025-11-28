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
            "permission": "helpdesk.tickets.page.create",
            "group": "user"
        },
        {
            "label": "Mis Tickets",
            "endpoint": "helpdesk_pages.user_pages.my_tickets",
            "icon": "fa-list",
            "permission": "helpdesk.tickets.page.my_tickets",
            "group": "user"
        },
        {
            "label": "Mi Equipo",
            "endpoint": "helpdesk_pages.inventory_pages.my_equipment",
            "icon": "fa-laptop",
            "permission": "helpdesk.inventory.page.my_equipment",
            "group": "user"
        },

        # ==================== SECRETARÍA ====================
        {
            "label": "Dashboard",
            "endpoint": "helpdesk_pages.secretary_pages.dashboard",
            "icon": "fa-building",
            "permission": "helpdesk.dashboard.secretary",
            "group": "secretary"
        },

        # ==================== TÉCNICOS ====================
        {
            "label": "Dashboard",
            "endpoint": "helpdesk_pages.technician_pages.dashboard",
            "icon": "fa-clipboard-list",
            "permission": "helpdesk.dashboard.technician",
            "group": "technician"
        },

        # ==================== JEFE DE DEPARTAMENTO ====================
        {
            "label": "Dashboard",
            "endpoint": "helpdesk_pages.department_pages.tickets",
            "icon": "fa-building",
            "permission": "helpdesk.dashboard.department",
            "group": "department"
        },

        # ==================== ADMIN ====================
        {
            "label": "Asignar Tickets",
            "endpoint": "helpdesk_pages.admin_pages.assign_tickets",
            "icon": "fa-user-plus",
            "permission": "helpdesk.assignments.page.list",
            "group": "admin"
        },
        {
            "label": "Inventario",
            "endpoint": "#",
            "icon": "fa-warehouse",
            "permission": "helpdesk.inventory.page.list",
            "group": "admin",
            "dropdown": [
                {
                    "label": "Dashboard Inventario",
                    "endpoint": "helpdesk_pages.inventory_pages.dashboard",
                    "icon": "fa-tachometer-alt",
                    "permission": "helpdesk.inventory.page.list"
                },
                {
                    "label": "Ver Inventario",
                    "endpoint": "helpdesk_pages.inventory_pages.items_list",
                    "icon": "fa-list"
                },
                {
                    "label": "Registrar Equipo",
                    "endpoint": "helpdesk_pages.inventory_pages.item_create",
                    "icon": "fa-plus",
                    "permission": "helpdesk.inventory.page.create"
                },
                {
                    "label": "Registro Masivo",
                    "endpoint": "helpdesk_pages.inventory_pages.bulk_register",
                    "icon": "fa-upload",
                    "permission": "helpdesk.inventory.api.bulk.create"
                },
                {
                    "label": "Grupos/Salones",
                    "endpoint": "helpdesk_pages.inventory_pages.groups_list",
                    "icon": "fa-door-open",
                    "permission": "helpdesk.inventory_groups.page.list"
                },
                {
                    "label": "Pendientes",
                    "endpoint": "helpdesk_pages.inventory_pages.pending_items",
                    "icon": "fa-clock",
                    "permission": "helpdesk.inventory.page.pending"
                },
                {
                    "label": "Asignar Equipos",
                    "endpoint": "helpdesk_pages.inventory_pages.assign_equipment",
                    "icon": "fa-user-plus",
                    "permission": "helpdesk.inventory.api.assign"
                },
                {
                    "label": "Reportes",
                    "endpoint": "#",
                    "icon": "fa-chart-bar",
                    "permission": "helpdesk.inventory.page.reports",
                    "submenu": [
                        {
                            "label": "Garantías",
                            "endpoint": "helpdesk_pages.inventory_pages.warranty_report",
                            "icon": "fa-shield-alt"
                        },
                        {
                            "label": "Mantenimientos",
                            "endpoint": "helpdesk_pages.inventory_pages.maintenance_report",
                            "icon": "fa-tools"
                        },
                        {
                            "label": "Ciclo de Vida",
                            "endpoint": "helpdesk_pages.inventory_pages.lifecycle_report",
                            "icon": "fa-history"
                        }
                    ]
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