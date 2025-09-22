// users.js - Gestión de usuarios y asignaciones
class UsersManager {
    constructor() {
        this.apiBase = '/api/core/v1';
        this.currentUserId = null;
        this.currentAppKey = null;
        this.apps = [];
        this.permissions = [];
        this.init();
    }

    init() {
        this.bindEvents();
        this.initModals();
        this.loadUserApps();
        this.loadAppsData();
    }

    bindEvents() {
        // Search functionality
        const searchInput = document.getElementById('searchUsers');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => this.handleSearch(e.target.value));
        }

        // Filter functionality
        const filters = ['roleFilter', 'appFilter', 'statusFilter'];
        filters.forEach(filterId => {
            const filter = document.getElementById(filterId);
            if (filter) {
                filter.addEventListener('change', () => this.applyFilters());
            }
        });

        // Assign user buttons
        document.addEventListener('click', (e) => {
            if (e.target.closest('.assign-user-btn')) {
                const btn = e.target.closest('.assign-user-btn');
                this.showAssignModal(btn);
            }
        });

        // App selection in modal
        document.addEventListener('click', (e) => {
            if (e.target.closest('.app-item')) {
                const btn = e.target.closest('.app-item');
                this.selectApp(btn);
            }
        });

        // Role assignment
        const assignRoleBtn = document.getElementById('assignRoleBtn');
        if (assignRoleBtn) {
            assignRoleBtn.addEventListener('click', () => this.assignRole());
        }

        // Permission assignment
        const assignPermBtn = document.getElementById('assignPermBtn');
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
        this.assignModal = new bootstrap.Modal(document.getElementById('assignUserModal'));
    }

    async loadAppsData() {
        try {
            const response = await fetch(`${this.apiBase}/authz/apps`);
            const result = await response.json();
            
            if (response.ok && result.data) {
                this.apps = result.data;
            }
        } catch (error) {
            console.error('Error loading apps:', error);
        }
    }

    async loadUserApps() {
        const userRows = document.querySelectorAll('[data-user-id]');
        
        for (const row of userRows) {
            const userId = row.dataset.userId;
            await this.loadUserAppsForRow(userId);
        }
    }

    async loadUserAppsForRow(userId) {
        const container = document.getElementById(`userApps_${userId}`);
        if (!container) return;

        try {
            const userApps = new Set();
            
            // Check all apps for this user
            for (const app of this.apps) {
                const hasAssignments = await this.checkUserHasAssignments(userId, app.key);
                if (hasAssignments) {
                    userApps.add(app.key);
                }
            }

            this.renderUserApps(container, Array.from(userApps));
        } catch (error) {
            container.innerHTML = '<span class="badge bg-danger">Error</span>';
            console.error('Error loading user apps:', error);
        }
    }

    async checkUserHasAssignments(userId, appKey) {
        try {
            // Check roles
            const rolesResponse = await fetch(`${this.apiBase}/authz/apps/${appKey}/users/${userId}/roles`);
            if (rolesResponse.ok) {
                const rolesResult = await rolesResponse.json();
                if (rolesResult.data && rolesResult.data.length > 0) {
                    return true;
                }
            }

            // Check permissions
            const permsResponse = await fetch(`${this.apiBase}/authz/apps/${appKey}/users/${userId}/perms`);
            if (permsResponse.ok) {
                const permsResult = await permsResponse.json();
                if (permsResult.data && permsResult.data.length > 0) {
                    return true;
                }
            }

            return false;
        } catch (error) {
            return false;
        }
    }

    renderUserApps(container, appKeys) {
        if (appKeys.length === 0) {
            container.innerHTML = '<span class="badge bg-light text-muted">Sin apps</span>';
            return;
        }

        const badges = appKeys.map(appKey => {
            const app = this.apps.find(a => a.key === appKey);
            return `<span class="badge bg-primary" title="${app ? app.name : appKey}">${appKey}</span>`;
        }).join(' ');

        container.innerHTML = badges;
    }

    handleSearch(query) {
        const rows = document.querySelectorAll('.user-row');
        const lowerQuery = query.toLowerCase();
        
        rows.forEach(row => {
            const userText = row.textContent.toLowerCase();
            const matches = userText.includes(lowerQuery);
            row.style.display = matches ? '' : 'none';
        });
    }

    applyFilters() {
        const roleFilter = document.getElementById('roleFilter').value;
        const appFilter = document.getElementById('appFilter').value;
        const statusFilter = document.getElementById('statusFilter').value;
        
        const rows = document.querySelectorAll('.user-row');
        
        rows.forEach(row => {
            let show = true;
            
            // Role filter
            if (roleFilter) {
                const roleElement = row.querySelector('.badge-role');
                const userRole = roleElement ? roleElement.textContent.trim() : '';
                if (userRole !== roleFilter) {
                    show = false;
                }
            }
            
            // Status filter
            if (statusFilter) {
                const statusElement = row.querySelector('td:nth-child(4) .badge');
                const isActive = statusElement ? statusElement.classList.contains('bg-success') : false;
                if (statusFilter === 'active' && !isActive) {
                    show = false;
                } else if (statusFilter === 'inactive' && isActive) {
                    show = false;
                }
            }
            
            // App filter (more complex - would need to check actual assignments)
            // For now, we'll skip this filter or implement it based on visible badges
            
            row.style.display = show ? '' : 'none';
        });
    }

    showAssignModal(btn) {
        this.currentUserId = btn.dataset.userId;
        const userName = btn.dataset.userName;
        
        document.getElementById('assignUserName').textContent = userName;
        this.assignModal.show();
        
        // Reset the panel
        document.getElementById('appAssignmentPanel').style.display = 'none';
        document.querySelectorAll('.app-item').forEach(item => {
            item.classList.remove('active');
        });
    }

    async selectApp(btn) {
        // Update UI
        document.querySelectorAll('.app-item').forEach(item => {
            item.classList.remove('active');
        });
        btn.classList.add('active');
        
        this.currentAppKey = btn.dataset.appKey;
        const appName = btn.dataset.appName;
        
        document.getElementById('selectedAppName').textContent = appName;
        document.getElementById('appAssignmentPanel').style.display = 'block';
        
        // Load data for this app
        await this.loadUserAssignments();
        await this.loadAppPermissions();
    }

    async loadUserAssignments() {
        if (!this.currentUserId || !this.currentAppKey) return;
        
        try {
            // Load roles
            const rolesResponse = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/users/${this.currentUserId}/roles`);
            const rolesResult = await rolesResponse.json();
            const userRoles = rolesResult.data || [];
            
            // Load permissions
            const permsResponse = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/users/${this.currentUserId}/perms`);
            const permsResult = await permsResponse.json();
            const userPerms = permsResult.data || [];
            
            // Load effective permissions
            const effectiveResponse = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/users/${this.currentUserId}/effective-perms`);
            const effectiveResult = await effectiveResponse.json();
            const effectivePerms = effectiveResult.data?.effective || [];
            
            this.renderUserRoles(userRoles);
            this.renderUserPermissions(userPerms);
            this.renderEffectivePermissions(effectivePerms);
            
        } catch (error) {
            this.showError('Error al cargar las asignaciones del usuario');
            console.error('Error loading user assignments:', error);
        }
    }

    async loadAppPermissions() {
        if (!this.currentAppKey) return;
        
        try {
            const response = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/perms`);
            const result = await response.json();
            
            if (response.ok && result.data) {
                this.permissions = result.data;
                this.populatePermissionSelect();
            }
        } catch (error) {
            console.error('Error loading app permissions:', error);
        }
    }

    populatePermissionSelect() {
        const select = document.getElementById('permToAssign');
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

    renderUserRoles(roles) {
        const container = document.getElementById('userRolesList');
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

    renderUserPermissions(permissions) {
        const container = document.getElementById('userPermsList');
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

    renderEffectivePermissions(permissions) {
        const container = document.getElementById('effectivePermsList');
        if (!container) return;
        
        if (permissions.length === 0) {
            container.innerHTML = '<small class="text-muted">Sin permisos efectivos</small>';
            return;
        }
        
        const badges = permissions.map(perm => 
            `<span class="badge bg-info">${perm}</span>`
        ).join(' ');
        
        container.innerHTML = badges;
    }

    async assignRole() {
        const select = document.getElementById('roleToAssign');
        const roleName = select.value;
        
        if (!roleName) {
            this.showError('Selecciona un rol');
            return;
        }
        
        try {
            const response = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/users/${this.currentUserId}/roles`, {
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
                await this.loadUserAssignments();
                await this.loadUserAppsForRow(this.currentUserId);
            } else {
                this.showError(result.error || 'Error al asignar el rol');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error assigning role:', error);
        }
    }

    async assignPermission() {
        const select = document.getElementById('permToAssign');
        const permCode = select.value;
        
        if (!permCode) {
            this.showError('Selecciona un permiso');
            return;
        }
        
        try {
            const response = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/users/${this.currentUserId}/perms`, {
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
                await this.loadUserAssignments();
                await this.loadUserAppsForRow(this.currentUserId);
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
            const response = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/users/${this.currentUserId}/roles/${roleName}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                this.showSuccess('Rol removido correctamente');
                await this.loadUserAssignments();
                await this.loadUserAppsForRow(this.currentUserId);
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
            const response = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/users/${this.currentUserId}/perms/${permCode}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                this.showSuccess('Permiso removido correctamente');
                await this.loadUserAssignments();
                await this.loadUserAppsForRow(this.currentUserId);
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
    new UsersManager();
});