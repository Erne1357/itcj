# itcj/apps/helpdesk/utils/navigation.py

def get_helpdesk_navigation(user_permissions: set[str], user_roles: set[str]):
    """
    Devuelve la navegación de Help-Desk basada SOLO en permisos del usuario.
    No hay separación por grupos - todo se controla por permisos individuales.
    """

    # Estructura completa de navegación con permisos requeridos
    full_nav_structure = [
        # ==================== USUARIOS ====================
        {
            "label": "Crear Ticket",
            "endpoint": "helpdesk_pages.user_pages.create_ticket",
            "icon": "fa-plus-circle",
            "permission": "helpdesk.tickets.page.create"
        },
        {
            "label": "Mis Tickets",
            "endpoint": "helpdesk_pages.user_pages.my_tickets",
            "icon": "fa-list",
            "permission": "helpdesk.tickets.page.my_tickets"
        },
        {
            "label": "Mi Equipo",
            "endpoint": "helpdesk_pages.inventory_pages.my_equipment",
            "icon": "fa-laptop",
            "permission": "helpdesk.inventory.page.my_equipment"
        },

        # ==================== DASHBOARDS ====================
        {
            "label": "Dashboard Secretaría",
            "endpoint": "helpdesk_pages.secretary_pages.dashboard",
            "icon": "fa-building",
            "permission": "helpdesk.dashboard.secretary"
        },
        {
            "label": "Dashboard Técnicos",
            "endpoint": "helpdesk_pages.technician_pages.dashboard",
            "icon": "fa-clipboard-list",
            "permission": "helpdesk.dashboard.technician"
        },
        {
            "label": "Dashboard Departamento",
            "endpoint": "helpdesk_pages.department_pages.tickets",
            "icon": "fa-users-cog",
            "permission": "helpdesk.dashboard.department"
        },

        # ==================== ASIGNACIÓN ====================
        {
            "label": "Asignar Tickets",
            "endpoint": "helpdesk_pages.admin_pages.assign_tickets",
            "icon": "fa-user-plus",
            "permission": "helpdesk.assignments.page.list"
        },

        # ==================== INVENTARIO (UNIFICADO) ====================
        {
            "label": "Inventario",
            "endpoint": "#",
            "icon": "fa-warehouse",
            "permission": "helpdesk.inventory.page.list",  # Permiso base para ver el dropdown
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
                    "icon": "fa-list",
                    "permission": "helpdesk.inventory.api.read"
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

    # Filtrar items según permisos (sin considerar grupos)
    nav_items = []
    for item in full_nav_structure:
        # Verificar si el usuario tiene el permiso
        if "permission" in item and item["permission"] not in user_permissions:
            continue

        # Si tiene dropdown, filtrar sus items también
        if "dropdown" in item:
            filtered_dropdown = []
            for sub_item in item["dropdown"]:
                # Si el sub-item tiene submenu, filtrar también
                if "submenu" in sub_item:
                    # Para reportes, verificar el permiso del padre
                    if "permission" not in sub_item or sub_item["permission"] in user_permissions:
                        filtered_dropdown.append(sub_item)
                # Si es un item normal, verificar permiso
                elif "permission" not in sub_item or sub_item["permission"] in user_permissions:
                    filtered_dropdown.append(sub_item)

            # Solo incluir si tiene sub-items después del filtrado
            if filtered_dropdown:
                item_copy = item.copy()
                item_copy["dropdown"] = filtered_dropdown
                nav_items.append(item_copy)
        else:
            nav_items.append(item)

    return nav_items
