// user_detail.js - Detalle de usuario con asignaciones por app
class UserDetailManager {
    constructor() {
        this.apiBase = '/api/core/v1';
        this.userId = window.userId;
        this.currentAppKey = null;
        this.permissions = [];
        this.init();
    }

    init() {
        this.bindEvents();
        this.initModals();
        this.loadAllUserAssignments();
    }

    bindEvents() {
        // Manage app buttons
        document.addEventListener('click', (e) => {
            if (e.target.closest('.manage-app-btn')) {
                const btn = e.target.closest('.manage-app-btn');
                this.showManageModal(btn);
            }
        });

        // Role assignment in modal
        const assignRoleBtn = document.getElementById('modalAssignRole');
        if (assignRoleBtn) {
            assignRoleBtn.addEventListener('click', () => this.assignRole());
        }

        // Permission assignment in modal
        const assignPermBtn = document.getElementById('modalAssignPerm');
        if (assignPermBtn) {
            assignPermBtn.addEventListener('click', () => this.assignPermission());
        }

        // Remove assignments (delegated events)
        document.addEventListener('click', (e) => {
            if (e.target.closest('.remove-role-btn')) {
                const btn = e.target.closest('.remove-role-btn');
                this.removeRole(btn.dataset.roleName);
            }
            
            if (e.target.closest('.remove-perm-btn')) {
                const btn = e.target.closest('.remove-perm-btn');
                this.removePermission(btn.dataset.permCode);
            }
        });
    }

    initModals() {
        this.manageModal = new bootstrap.Modal(document.getElementById('manageAssignmentsModal'));
    }

    async loadAllUserAssignments() {
        const appCards = document.querySelectorAll('[data-app-key]');
        
        for (const card of appCards) {
            const appKey = card.dataset.appKey;
            await this.loadUserAssignmentsForApp(appKey);
        }
    }

    async loadUserAssignmentsForApp(appKey) {
        try {
            // Load roles
            const rolesResponse = await fetch(`${this.apiBase}/authz/apps/${appKey}/users/${this.userId}/roles`);
            const rolesResult = await rolesResponse.json();
            const userRoles = rolesResult.data || [];
            
            // Load permissions
            const permsResponse = await fetch(`${this.apiBase}/authz/apps/${appKey}/users/${this.userId}/perms`);
            const permsResult = await permsResponse.json();
            const userPerms = permsResult.data || [];
            
            // Load effective permissions
            const effectiveResponse = await fetch(`${this.apiBase}/authz/apps/${appKey}/users/${this.userId}/effective-perms`);
            const effectiveResult = await effectiveResponse.json();
            const effectivePerms = effectiveResult.data?.effective || [];
            
            this.renderAppAssignments(appKey, userRoles, userPerms, effectivePerms);
            
        } catch (error) {
            this.renderAppError(appKey);
            console.error(`Error loading assignments for ${appKey}:`, error);
        }
    }

    renderAppAssignments(appKey, roles, permissions, effectivePerms) {
        // Render roles
        const rolesContainer = document.getElementById(`roles_${appKey}`);
        if (rolesContainer) {
            if (roles.length === 0) {
                rolesContainer.innerHTML = '<small class="text-muted">Sin roles asignados</small>';
            } else {
                const badges = roles.map(role => 
                    `<span class="badge bg-primary">${role}</span>`
                ).join(' ');
                rolesContainer.innerHTML = badges;
            }
        }

        // Render direct permissions
        const permsContainer = document.getElementById(`perms_${appKey}`);
        if (permsContainer) {
            if (permissions.length === 0) {
                permsContainer.innerHTML = '<small class="text-muted">Sin permisos directos</small>';
            } else {
                const badges = permissions.map(perm => 
                    `<span class="badge bg-success permission-badge">${perm}</span>`
                ).join(' ');
                permsContainer.innerHTML = badges;
            }
        }

        // Render effective permissions
        const effectiveContainer = document.getElementById(`effective_${appKey}`);
        if (effectiveContainer) {
            if (effectivePerms.length === 0) {
                effectiveContainer.innerHTML = '<small class="text-muted">Sin permisos efectivos</small>';
            } else {
                const badges = effectivePerms.map(perm => 
                    `<span class="badge bg-info permission-badge">${perm}</span>`
                ).join(' ');
                effectiveContainer.innerHTML = badges;
            }
        }
    }

    renderAppError(appKey) {
        const containers = [
            document.getElementById(`roles_${appKey}`),
            document.getElementById(`perms_${appKey}`),
            document.getElementById(`effective_${appKey}`)
        ];

        containers.forEach(container => {
            if (container) {
                container.innerHTML = '<span class="badge bg-danger">Error</span>';
            }
        });
    }

    async showManageModal(btn) {
        this.currentAppKey = btn.dataset.appKey;
        const appName = btn.dataset.appName;
        
        document.getElementById('modalAppName').textContent = appName;
        this.manageModal.show();
        
        // Load data for modal
        await this.loadModalAssignments();
        await this.loadAppPermissions();
    }

    async loadModalAssignments() {
        if (!this.currentAppKey) return;
        
        try {
            // Load roles
            const rolesResponse = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/users/${this.userId}/roles`);
            const rolesResult = await rolesResponse.json();
            const userRoles = rolesResult.data || [];
            
            // Load permissions
            const permsResponse = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/users/${this.userId}/perms`);
            const permsResult = await permsResponse.json();
            const userPerms = permsResult.data || [];
            
            // Load effective permissions
            const effectiveResponse = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/users/${this.userId}/effective-perms`);
            const effectiveResult = await effectiveResponse.json();
            const effectivePerms = effectiveResult.data?.effective || [];
            
            this.renderModalAssignments(userRoles, userPerms, effectivePerms);
            
        } catch (error) {
            this.showError('Error al cargar las asignaciones');
            console.error('Error loading modal assignments:', error);
        }
    }

    async loadAppPermissions() {
        if (!this.currentAppKey) return;
        
        try {
            const response = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/perms`);
            const result = await response.json();
            
            if (response.ok && result.data) {
                this.permissions = result.data;
                this.populateModalPermissionSelect();
            }
        } catch (error) {
            console.error('Error loading app permissions:', error);
        }
    }

    populateModalPermissionSelect() {
        const select = document.getElementById('modalPermToAssign');
        if (!select) return;
        
        // Clear existing options (except first)
        while (select.children.length > 1) {
            select.removeChild(select.lastChild);
        }
        
        this.permissions.forEach(perm => {
            const option = document.createElement('option');
            option.value = perm.code;
            option.textContent = `${perm.name} (${perm.code})`;
            select.appendChild(option);
        });
    }

    renderModalAssignments(roles, permissions, effectivePerms) {
        this.renderModalRoles(roles);
        this.renderModalPermissions(permissions);
        this.renderModalEffectivePermissions(effectivePerms);
    }

    renderModalRoles(roles) {
        const container = document.getElementById('modalUserRoles');
        if (!container) return;
        
        if (roles.length === 0) {
            container.innerHTML = '<small class="text-muted">Sin roles asignados</small>';
            return;
        }
        
        const badges = roles.map(role => 
            `<span class="badge bg-primary d-flex align-items-center gap-1">
                ${role}
                <button class="btn-close btn-close-white btn-sm remove-role-btn" 
                        data-role-name="${role}" style="font-size: 0.6em;"></button>
            </span>`
        ).join('');
        
        container.innerHTML = badges;
    }

    renderModalPermissions(permissions) {
        const container = document.getElementById('modalUserPerms');
        if (!container) return;
        
        if (permissions.length === 0) {
            container.innerHTML = '<small class="text-muted">Sin permisos directos</small>';
            return;
        }
        
        const badges = permissions.map(perm => 
            `<span class="badge bg-success d-flex align-items-center gap-1">
                ${perm}
                <button class="btn-close btn-close-white btn-sm remove-perm-btn" 
                        data-perm-code="${perm}" style="font-size: 0.6em;"></button>
            </span>`
        ).join('');
        
        container.innerHTML = badges;
    }

    renderModalEffectivePermissions(permissions) {
        const container = document.getElementById('modalEffectivePerms');
        if (!container) return;
        
        if (permissions.length === 0) {
            container.innerHTML = '<small class="text-muted">Sin permisos efectivos</small>';
            return;
        }
        
        const badges = permissions.map(perm => 
            `<span class="badge bg-info permission-badge">${perm}</span>`
        ).join(' ');
        
        container.innerHTML = badges;
    }

    async assignRole() {
        const select = document.getElementById('modalRoleToAssign');
        const roleName = select.value;
        
        if (!roleName) {
            this.showError('Selecciona un rol');
            return;
        }
        
        try {
            const response = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/users/${this.userId}/roles`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({role_name: roleName})
            });
            
            const result = await response.json();
            
            if (response.ok) {
                this.showSuccess('Rol asignado correctamente');
                select.value = '';
                await this.loadModalAssignments();
                await this.loadUserAssignmentsForApp(this.currentAppKey);
            } else {
                this.showError(result.error || 'Error al asignar el rol');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error assigning role:', error);
        }
    }

    async assignPermission() {
        const select = document.getElementById('modalPermToAssign');
        const permCode = select.value;
        
        if (!permCode) {
            this.showError('Selecciona un permiso');
            return;
        }
        
        try {
            const response = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/users/${this.userId}/perms`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({code: permCode, allow: true})
            });
            
            const result = await response.json();
            
            if (response.ok) {
                this.showSuccess('Permiso asignado correctamente');
                select.value = '';
                await this.loadModalAssignments();
                await this.loadUserAssignmentsForApp(this.currentAppKey);
            } else {
                this.showError(result.error || 'Error al asignar el permiso');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error assigning permission:', error);
        }
    }

    async removeRole(roleName) {
        try {
            const response = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/users/${this.userId}/roles/${roleName}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                this.showSuccess('Rol removido correctamente');
                await this.loadModalAssignments();
                await this.loadUserAssignmentsForApp(this.currentAppKey);
            } else {
                const result = await response.json();
                this.showError(result.error || 'Error al remover el rol');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error removing role:', error);
        }
    }

    async removePermission(permCode) {
        try {
            const response = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/users/${this.userId}/perms/${permCode}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                this.showSuccess('Permiso removido correctamente');
                await this.loadModalAssignments();
                await this.loadUserAssignmentsForApp(this.currentAppKey);
            } else {
                const result = await response.json();
                this.showError(result.error || 'Error al remover el permiso');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error removing permission:', error);
        }
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
    new UserDetailManager();
});