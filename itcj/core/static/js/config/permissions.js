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

    showRolePermissions(rolePermissions) {
        const container = document.getElementById('permissionsList');
        const content = document.getElementById('rolePermissionsContent');
        const noRoleSelected = document.getElementById('noRoleSelected');
        
        container.innerHTML = '';
        
        this.permissions.forEach(perm => {
            const isAssigned = rolePermissions.includes(perm.code);
            
            const div = document.createElement('div');
            div.className = 'col-12 col-md-6 col-lg-4';
            div.innerHTML = `
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" 
                           id="perm_${perm.code}" value="${perm.code}" ${isAssigned ? 'checked' : ''}>
                    <label class="form-check-label" for="perm_${perm.code}">
                        <strong>${perm.name}</strong><br>
                        <small class="text-muted">${perm.code}</small>
                        ${perm.description ? `<br><small class="text-muted">${perm.description}</small>` : ''}
                    </label>
                </div>
            `;
            
            container.appendChild(div);
        });
        
        content.classList.remove('d-none');
        noRoleSelected.classList.add('d-none');
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
        
        const checkboxes = document.querySelectorAll('#permissionsList input[type="checkbox"]');
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