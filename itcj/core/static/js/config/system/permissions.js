// permissions.js - Gestión de permisos por aplicación
class PermissionsManager {
    constructor() {
        this.apiBase = '/api/core/v1';
        this.appKey = window.appKey;
        this.roles = [];
        this.permissions = [];
        this.selectedRole = null;
        this.init();
    }

    init() {
        this.bindEvents();
        this.initModals();
        this.loadRoles();
    }

    bindEvents() {
        // Form submissions
        const createForm = document.getElementById('createPermForm');

        if (createForm) {
            createForm.addEventListener('submit', (e) => this.handleCreatePermission(e));
        }

        // Delete buttons
        document.addEventListener('click', (e) => {
            if (e.target.closest('.delete-perm-btn')) {
                const btn = e.target.closest('.delete-perm-btn');
                this.showDeleteModal(btn);
            }
        });

        // Confirm delete
        const confirmDeleteBtn = document.getElementById('confirmDeletePerm');
        if (confirmDeleteBtn) {
            confirmDeleteBtn.addEventListener('click', () => this.handleDeletePermission());
        }

        // Role selection
        const roleSelect = document.getElementById('roleSelect');
        if (roleSelect) {
            roleSelect.addEventListener('change', (e) => this.handleRoleSelection(e.target.value));
        }

        // Save role permissions
        const saveBtn = document.getElementById('saveRolePermissions');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => this.saveRolePermissions());
        }

        // Input validation
        const permCodeInput = document.getElementById('permCode');
        if (permCodeInput) {
            permCodeInput.addEventListener('input', this.validatePermCode);
        }
    }

    initModals() {
        this.createModal = new bootstrap.Modal(document.getElementById('createPermModal'));
        this.deleteModal = new bootstrap.Modal(document.getElementById('deletePermModal'));
    }

    validatePermCode(e) {
        const value = e.target.value;
        const pattern = /^[a-z0-9._]*$/;

        if (!pattern.test(value)) {
            e.target.classList.add('is-invalid');
            e.target.setCustomValidity('Solo se permiten letras minúsculas, números, puntos y guiones bajos');
        } else {
            e.target.classList.remove('is-invalid');
            e.target.setCustomValidity('');
        }
    }

    async loadRoles() {
        try {
            const response = await fetch(`${this.apiBase}/authz/roles`);
            const result = await response.json();

            if (response.ok && result.data) {
                this.roles = result.data;
                this.populateRoleSelect();
            }
        } catch (error) {
            console.error('Error loading roles:', error);
        }
    }

    populateRoleSelect() {
        const select = document.getElementById('roleSelect');
        if (!select) return;

        // Clear existing options (except first)
        while (select.children.length > 1) {
            select.removeChild(select.lastChild);
        }

        this.roles.forEach(role => {
            const option = document.createElement('option');
            option.value = role.name;
            option.textContent = role.name;
            select.appendChild(option);
        });
    }

    async handleCreatePermission(e) {
        e.preventDefault();

        const formData = new FormData(e.target);
        const data = {
            code: formData.get('code'),
            name: formData.get('name'),
            description: formData.get('description') || undefined
        };

        try {
            const response = await fetch(`${this.apiBase}/authz/apps/${this.appKey}/perms`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (response.ok) {
                this.showSuccess('Permiso creado correctamente');
                this.createModal.hide();
                this.addPermissionToTable(result.data);
                e.target.reset();
                this.refreshPermissionsList();
            } else {
                this.showError(result.error || 'Error al crear el permiso');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error creating permission:', error);
        }
    }

    showDeleteModal(btn) {
        const permCode = btn.dataset.permCode;
        const permName = btn.dataset.permName;

        this.deletePermCode = permCode;
        document.getElementById('deletePermName').textContent = permName;
        this.deleteModal.show();
    }

    async handleDeletePermission() {
        try {
            const response = await fetch(`${this.apiBase}/authz/apps/${this.appKey}/perms/${this.deletePermCode}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                this.showSuccess('Permiso eliminado correctamente');
                this.deleteModal.hide();
                this.removePermissionFromTable(this.deletePermCode);
                this.refreshPermissionsList();
            } else {
                const result = await response.json();
                this.showError(result.error || 'Error al eliminar el permiso');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error deleting permission:', error);
        }
    }

    async handleRoleSelection(roleName) {
        if (!roleName) {
            this.hideRolePermissions();
            return;
        }

        this.selectedRole = roleName;
        document.getElementById('selectedRoleName').textContent = roleName;

        try {
            // Load app permissions
            const permsResponse = await fetch(`${this.apiBase}/authz/apps/${this.appKey}/perms`);
            const permsResult = await permsResponse.json();

            // Load role permissions for this app
            const rolePermsResponse = await fetch(`${this.apiBase}/authz/apps/${this.appKey}/roles/${roleName}/perms`);
            const rolePermsResult = await rolePermsResponse.json();

            if (permsResponse.ok && rolePermsResponse.ok) {
                this.permissions = permsResult.data || [];
                const rolePermissions = rolePermsResult.data || [];
                this.showRolePermissions(rolePermissions);
            }
        } catch (error) {
            this.showError('Error al cargar los permisos');
            console.error('Error loading permissions:', error);
        }
    }

    /**
     * Agrupa permisos por módulos y tipo
     */
    groupPermissions(permissions) {
        const groups = {
            pages: [],
            dashboards: [],
            modules: {}
        };

        permissions.forEach(perm => {
            const parts = perm.code.split('.');

            // Determinar si es página, dashboard o API
            if (perm.code.includes('.page.')) {
                groups.pages.push(perm);
            } else if (perm.code.includes('.dashboard')) {
                groups.dashboards.push(perm);
            } else if (perm.code.includes('.api.')) {
                // Extraer el módulo (segundo segmento)
                // Formato: app.modulo.api.accion[.scope]
                const moduleName = parts[1]; // Ej: tickets, inventory, users

                if (!groups.modules[moduleName]) {
                    groups.modules[moduleName] = [];
                }
                groups.modules[moduleName].push(perm);
            } else {
                // Otros permisos (general, etc.)
                const moduleName = parts[1] || 'otros';
                if (!groups.modules[moduleName]) {
                    groups.modules[moduleName] = [];
                }
                groups.modules[moduleName].push(perm);
            }
        });

        return groups;
    }

    /**
     * Genera un nombre amigable para el módulo
     */
    getModuleFriendlyName(moduleName) {
        const names = {
            // HELPDESK
            'tickets': 'Tickets',
            'assignments': 'Asignaciones',
            'collaborators': 'Colaboradores',
            'comments': 'Comentarios',
            'attachments': 'Adjuntos',
            'categories': 'Categorías',
            'inventory': 'Inventario',
            'inventory_categories': 'Categorías Inventario',
            'inventory_groups': 'Grupos/Salones',
            'reports': 'Reportes',
            'stats': 'Estadísticas',

            // AGENDATEC
            'admin_dashboard': 'Dashboard Admin',
            'coord_dashboard': 'Dashboard Coordinador',
            'users': 'Usuarios',
            'requests': 'Solicitudes',
            'slots': 'Horarios',
            'appointments': 'Citas',
            'drops': 'Bajas',
            'social': 'Servicio Social',
            'surveys': 'Encuestas',
            'programs': 'Programas',

            // CORE
            'apps': 'Aplicaciones',
            'departments': 'Departamentos',
            'positions': 'Puestos',
            'roles': 'Roles',
            'permissions': 'Permisos',
            'authz': 'Autorización',
            'config': 'Configuración',
            'system': 'Sistema',
            'general': 'General',

            // Default
            'otros': 'Otros'
        };

        return names[moduleName] || moduleName.charAt(0).toUpperCase() + moduleName.slice(1);
    }

    showRolePermissions(rolePermissions) {
        const content = document.getElementById('rolePermissionsContent');
        const noRoleSelected = document.getElementById('noRoleSelected');

        // Agrupar permisos
        const groups = this.groupPermissions(this.permissions);

        // Construir tabs
        const tabsHtml = this.buildPermissionsTabs(groups, rolePermissions);

        // Insertar en el DOM
        const tabsContainer = document.getElementById('permissionsModuleTabs');
        tabsContainer.innerHTML = tabsHtml;

        content.classList.remove('d-none');
        noRoleSelected.classList.add('d-none');
    }

    buildPermissionsTabs(groups, rolePermissions) {
        let navHtml = '<ul class="nav nav-tabs mb-3" id="modulePermsTabs" role="tablist">';
        let contentHtml = '<div class="tab-content" id="modulePermsTabContent">';

        let firstTab = true;
        let tabIndex = 0;

        // Tab para Páginas
        if (groups.pages.length > 0) {
            const tabId = 'pages-tab';
            const paneId = 'pages-pane';

            navHtml += `
                <li class="nav-item" role="presentation">
                    <button class="nav-link ${firstTab ? 'active' : ''}" id="${tabId}"
                            data-bs-toggle="tab" data-bs-target="#${paneId}" type="button" role="tab">
                        <i class="bi bi-window me-1"></i>Páginas (${groups.pages.length})
                    </button>
                </li>
            `;

            contentHtml += `
                <div class="tab-pane fade ${firstTab ? 'show active' : ''}" id="${paneId}" role="tabpanel">
                    <div class="row g-2">
                        ${this.buildPermissionCheckboxes(groups.pages, rolePermissions)}
                    </div>
                </div>
            `;

            firstTab = false;
            tabIndex++;
        }

        // Tab para Dashboards
        if (groups.dashboards.length > 0) {
            const tabId = 'dashboards-tab';
            const paneId = 'dashboards-pane';

            navHtml += `
                <li class="nav-item" role="presentation">
                    <button class="nav-link ${firstTab ? 'active' : ''}" id="${tabId}"
                            data-bs-toggle="tab" data-bs-target="#${paneId}" type="button" role="tab">
                        <i class="bi bi-speedometer2 me-1"></i>Dashboards (${groups.dashboards.length})
                    </button>
                </li>
            `;

            contentHtml += `
                <div class="tab-pane fade ${firstTab ? 'show active' : ''}" id="${paneId}" role="tabpanel">
                    <div class="row g-2">
                        ${this.buildPermissionCheckboxes(groups.dashboards, rolePermissions)}
                    </div>
                </div>
            `;

            firstTab = false;
            tabIndex++;
        }

        // Tabs para módulos API
        const moduleNames = Object.keys(groups.modules).sort();

        moduleNames.forEach(moduleName => {
            const perms = groups.modules[moduleName];
            const friendlyName = this.getModuleFriendlyName(moduleName);
            const tabId = `module-${moduleName}-tab`;
            const paneId = `module-${moduleName}-pane`;

            // Icono según módulo
            const icon = this.getModuleIcon(moduleName);

            navHtml += `
                <li class="nav-item" role="presentation">
                    <button class="nav-link ${firstTab ? 'active' : ''}" id="${tabId}"
                            data-bs-toggle="tab" data-bs-target="#${paneId}" type="button" role="tab">
                        <i class="${icon} me-1"></i>${friendlyName} (${perms.length})
                    </button>
                </li>
            `;

            contentHtml += `
                <div class="tab-pane fade ${firstTab ? 'show active' : ''}" id="${paneId}" role="tabpanel">
                    <div class="row g-2">
                        ${this.buildPermissionCheckboxes(perms, rolePermissions)}
                    </div>
                </div>
            `;

            firstTab = false;
            tabIndex++;
        });

        navHtml += '</ul>';
        contentHtml += '</div>';

        return navHtml + contentHtml;
    }

    buildPermissionCheckboxes(permissions, rolePermissions) {
        return permissions.map(perm => {
            const isAssigned = rolePermissions.includes(perm.code);
            return `
                <div class="col-12 col-md-6 col-lg-4">
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox"
                               id="perm_${perm.code.replace(/\./g, '_')}"
                               value="${perm.code}"
                               ${isAssigned ? 'checked' : ''}>
                        <label class="form-check-label" for="perm_${perm.code.replace(/\./g, '_')}">
                            <strong>${perm.name}</strong><br>
                            <small class="text-muted">${perm.code}</small>
                            ${perm.description ? `<br><small class="text-muted">${perm.description}</small>` : ''}
                        </label>
                    </div>
                </div>
            `;
        }).join('');
    }

    getModuleIcon(moduleName) {
        const icons = {
            // HELPDESK
            'tickets': 'bi bi-ticket',
            'assignments': 'bi bi-person-check',
            'collaborators': 'bi bi-people',
            'comments': 'bi bi-chat-left-text',
            'attachments': 'bi bi-paperclip',
            'categories': 'bi bi-tags',
            'inventory': 'bi bi-box-seam',
            'inventory_categories': 'bi bi-list-ul',
            'inventory_groups': 'bi bi-collection',
            'reports': 'bi bi-file-earmark-bar-graph',
            'stats': 'bi bi-graph-up',

            // AGENDATEC
            'users': 'bi bi-person',
            'requests': 'bi bi-clipboard-data',
            'slots': 'bi bi-calendar-week',
            'appointments': 'bi bi-calendar-event',
            'drops': 'bi bi-person-dash',
            'social': 'bi bi-heart',
            'surveys': 'bi bi-list-check',

            // CORE
            'apps': 'bi bi-grid',
            'departments': 'bi bi-building',
            'positions': 'bi bi-person-badge',
            'roles': 'bi bi-shield',
            'permissions': 'bi bi-key',
            'authz': 'bi bi-shield-check',
            'config': 'bi bi-gear',
            'system': 'bi bi-cpu',
            'general': 'bi bi-star'
        };

        return icons[moduleName] || 'bi bi-circle';
    }

    hideRolePermissions() {
        const content = document.getElementById('rolePermissionsContent');
        const noRoleSelected = document.getElementById('noRoleSelected');

        content.classList.add('d-none');
        noRoleSelected.classList.remove('d-none');
        this.selectedRole = null;
    }

    async saveRolePermissions() {
        if (!this.selectedRole) return;

        const checkboxes = document.querySelectorAll('#permissionsModuleTabs input[type="checkbox"]');
        const selectedPermissions = Array.from(checkboxes)
            .filter(cb => cb.checked)
            .map(cb => cb.value);

        try {
            const response = await fetch(`${this.apiBase}/authz/apps/${this.appKey}/roles/${this.selectedRole}/perms`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({codes: selectedPermissions})
            });

            if (response.ok) {
                this.showSuccess('Permisos del rol actualizados correctamente');
            } else {
                const result = await response.json();
                this.showError(result.error || 'Error al actualizar los permisos');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error saving role permissions:', error);
        }
    }

    async refreshPermissionsList() {
        if (this.selectedRole) {
            // Reload permissions for current role
            await this.handleRoleSelection(this.selectedRole);
        }
    }

    addPermissionToTable(permData) {
        const tbody = document.querySelector('#permissionsTable tbody');
        const row = this.createPermissionRow(permData);
        tbody.appendChild(row);

        // Remove empty state if present
        const emptyState = document.getElementById('emptyPermsState');
        if (emptyState) {
            emptyState.remove();
        }

        // Update tab count
        const tab = document.getElementById('permissions-tab');
        if (tab) {
            const match = tab.textContent.match(/\((\d+)\)/);
            if (match) {
                const count = parseInt(match[1]) + 1;
                tab.innerHTML = tab.innerHTML.replace(/\(\d+\)/, `(${count})`);
            }
        }
    }

    removePermissionFromTable(permCode) {
        const row = document.querySelector(`tr[data-perm-code="${permCode}"]`);
        if (row) {
            row.remove();
        }

        // Check if table is empty
        const tbody = document.querySelector('#permissionsTable tbody');
        if (tbody.children.length === 0) {
            location.reload(); // Reload to show empty state
        } else {
            // Update tab count
            const tab = document.getElementById('permissions-tab');
            if (tab) {
                const match = tab.textContent.match(/\((\d+)\)/);
                if (match) {
                    const count = Math.max(0, parseInt(match[1]) - 1);
                    tab.innerHTML = tab.innerHTML.replace(/\(\d+\)/, `(${count})`);
                }
            }
        }
    }

    createPermissionRow(permData) {
        const row = document.createElement('tr');
        row.setAttribute('data-perm-code', permData.code);

        row.innerHTML = `
            <td class="px-4 py-3">
                <code class="bg-light px-2 py-1 rounded">${permData.code}</code>
            </td>
            <td class="py-3">
                <strong>${permData.name}</strong>
            </td>
            <td class="py-3">
                <small class="text-muted">${permData.description || 'Sin descripción'}</small>
            </td>
            <td class="py-3 text-end">
                <button class="btn btn-sm btn-outline-danger delete-perm-btn"
                        data-perm-code="${permData.code}"
                        data-perm-name="${permData.name}"
                        title="Eliminar">
                    <i class="bi bi-trash"></i>
                </button>
            </td>
        `;

        return row;
    }

    showSuccess(message) {
        const toast = document.getElementById('successToast');
        const messageEl = document.getElementById('successMessage');
        messageEl.textContent = message;

        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();
    }

    showError(message) {
        const toast = document.getElementById('errorToast');
        const messageEl = document.getElementById('errorMessage');
        messageEl.textContent = message;

        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new PermissionsManager();
});
