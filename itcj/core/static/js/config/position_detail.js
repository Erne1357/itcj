// itcj/core/static/js/config/position_detail.js

class PositionDetailManager {
    constructor(positionId, availableRoles) {
        this.apiBase = '/api/core/v1';
        this.positionId = positionId;
        this.positionData = null;
        this.currentAppKey = null;
        this.apps = [];
        this.permissions = [];
        this.availableRoles = availableRoles || []; // ⭐ NUEVO
        this.pendingConfirmAction = null;
        this.init();
    }

    async init() {
        this.bindEvents();
        this.initModals();
        await this.loadPosition();
        await this.loadUsers();
        await this.loadAppsAssignments();
    }

    bindEvents() {
        // Guardar cambios
        document.getElementById('savePositionBtn')?.addEventListener('click', () => this.savePosition());
        
        // Borrar puesto
        document.getElementById('deletePositionBtn')?.addEventListener('click', () => this.deletePosition());
        
        // Asignar usuario
        document.getElementById('assignUserBtn')?.addEventListener('click', () => this.showAssignUserModal());
        
        // Gestionar apps
        document.getElementById('manageAppsBtn')?.addEventListener('click', () => this.showManageAppsModal());
        
        // Form de asignar usuario
        document.getElementById('assignUserForm')?.addEventListener('submit', (e) => this.handleAssignUser(e));
        
        // Búsqueda de usuarios
        document.getElementById('userSearch')?.addEventListener('input', (e) => {
            clearTimeout(this.searchTimeout);
            this.searchTimeout = setTimeout(() => this.searchUsers(e.target.value), 300);
        });
        
        // Toggle email field based on allows_multiple
        document.getElementById('allowsMultiple')?.addEventListener('change', (e) => {
            const emailField = document.getElementById('positionEmail');
            if (e.target.checked) {
                emailField.value = '';
                emailField.disabled = true;
            } else {
                emailField.disabled = false;
            }
        });
        
        // Event delegation para botones dinámicos
        document.addEventListener('click', (e) => {
            // Remover usuario
            if (e.target.closest('.remove-user-btn')) {
                const btn = e.target.closest('.remove-user-btn');
                this.removeUser(parseInt(btn.dataset.userId));
            }
            
            // Seleccionar app
            if (e.target.closest('.app-item')) {
                const btn = e.target.closest('.app-item');
                this.selectApp(btn);
            }
            
            // Asignar rol
            if (e.target.id === 'assignRoleBtn') {
                this.assignRole();
            }
            
            // Asignar permiso
            if (e.target.id === 'assignPermBtn') {
                this.assignPermission();
            }
            
            // Remover rol
            if (e.target.closest('.remove-role-btn')) {
                const btn = e.target.closest('.remove-role-btn');
                this.removeRole(btn.dataset.roleName);
            }
            
            // Remover permiso
            if (e.target.closest('.remove-perm-btn')) {
                const btn = e.target.closest('.remove-perm-btn');
                this.removePermission(btn.dataset.permCode);
            }
        });
    }

    initModals() {
        this.assignUserModal = new bootstrap.Modal(document.getElementById('assignUserModal'));
        this.manageAppsModal = new bootstrap.Modal(document.getElementById('manageAppsModal'));
        this.confirmModal = new bootstrap.Modal(document.getElementById('confirmModal'));
        
        // Manejar confirmación
        document.getElementById('confirmActionBtn')?.addEventListener('click', () => {
            if (this.pendingConfirmAction) {
                this.confirmModal.hide();
                this.pendingConfirmAction();
                this.pendingConfirmAction = null;
            }
        });
    }

    async loadPosition() {
        try {
            const response = await fetch(`${this.apiBase}/positions/${this.positionId}`);
            const result = await response.json();

            if (response.ok && result.data) {
                this.positionData = result.data;
                this.renderPositionInfo();
            } else {
                this.showError('Error al cargar el puesto');
                setTimeout(() => window.history.back(), 2000);
            }
        } catch (error) {
            console.error('Error loading position:', error);
            this.showError('Error de conexión');
        }
    }

    renderPositionInfo() {
        const pos = this.positionData;
        
        document.getElementById('positionBreadcrumb').textContent = pos.title;
        document.getElementById('positionName').textContent = pos.title;
        document.getElementById('positionCode').textContent = `código: ${pos.code}`;
        
        if (pos.department_id) {
            const departmentLink = document.getElementById('departmentBreadcrumb');
            departmentLink.href = `/itcj/config/departments/${pos.department_id}`;
            this.loadDepartmentName(pos.department_id);
        }
        
        document.getElementById('positionTitleInput').value = pos.title || '';
        document.getElementById('positionDescription').value = pos.description || '';
        document.getElementById('positionEmail').value = pos.email || '';
        document.getElementById('allowsMultiple').checked = pos.allows_multiple;
        document.getElementById('isActive').checked = pos.is_active;
        document.getElementById('displayCode').textContent = pos.code;
        
        document.getElementById('positionEmail').disabled = pos.allows_multiple;
    }

    async loadDepartmentName(deptId) {
        try {
            const response = await fetch(`${this.apiBase}/departments/${deptId}`);
            const result = await response.json();
            if (response.ok && result.data) {
                document.getElementById('departmentBreadcrumb').textContent = result.data.name;
            }
        } catch (error) {
            console.error('Error loading department name:', error);
        }
    }

    async loadUsers() {
        const container = document.getElementById('usersListContainer');
        
        try {
            const users = this.positionData?.current_users || [];
            
            if (users.length === 0) {
                container.innerHTML = `
                    <div class="alert alert-info mb-0">
                        <i class="bi bi-info-circle me-2"></i>No hay usuarios asignados
                    </div>
                `;
                return;
            }
            
            container.innerHTML = `
                <div class="list-group">
                    ${users.map(user => `
                        <div class="list-group-item d-flex justify-content-between align-items-center">
                            <div>
                                <div class="fw-bold">${user.full_name}</div>
                                <small class="text-muted">${user.email || 'Sin email'}</small><br>
                                <small class="text-muted">
                                    <i class="bi bi-calendar me-1"></i>
                                    Desde: ${new Date(user.start_date).toLocaleDateString('es-ES')}
                                </small>
                            </div>
                            <button class="btn btn-sm btn-outline-danger remove-user-btn" 
                                    data-user-id="${user.user_id}"
                                    title="Remover usuario">
                                <i class="bi bi-x-lg"></i>
                            </button>
                        </div>
                    `).join('')}
                </div>
            `;
            
        } catch (error) {
            container.innerHTML = '<div class="alert alert-danger">Error al cargar usuarios</div>';
            console.error('Error loading users:', error);
        }
    }

    async loadAppsAssignments() {
        const container = document.getElementById('appsContainer');
        
        try {
            const assignments = this.positionData?.assignments || {};
            const appsData = assignments.apps || {};
            
            if (Object.keys(appsData).length === 0) {
                container.innerHTML = `
                    <div class="alert alert-info">
                        <i class="bi bi-info-circle me-2"></i>
                        Este puesto no tiene aplicaciones asignadas
                    </div>
                `;
                return;
            }
            
            container.innerHTML = Object.entries(appsData).map(([appKey, appData]) => `
                <div class="card mb-3">
                    <div class="card-header">
                        <strong>${appData.app_name}</strong>
                        <small class="text-muted">(${appKey})</small>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-6">
                                <h6 class="text-primary small">Roles:</h6>
                                ${appData.roles.length > 0 ?
                                    appData.roles.map(r => `<span class="badge bg-primary me-1">${r}</span>`).join('') :
                                    '<span class="text-muted small">Sin roles</span>'}
                            </div>
                            <div class="col-md-6">
                                <h6 class="text-success small">Permisos Directos:</h6>
                                ${appData.direct_permissions.length > 0 ?
                                    appData.direct_permissions.map(p => `<span class="badge bg-success me-1 mb-1">${p}</span>`).join('') :
                                    '<span class="text-muted small">Sin permisos</span>'}
                            </div>
                        </div>
                    </div>
                </div>
            `).join('');
            
        } catch (error) {
            container.innerHTML = '<div class="alert alert-danger">Error al cargar asignaciones</div>';
            console.error('Error loading apps assignments:', error);
        }
    }

    async savePosition() {
        const data = {
            title: document.getElementById('positionTitleInput').value.trim(),
            description: document.getElementById('positionDescription').value.trim() || null,
            email: document.getElementById('positionEmail').value.trim() || null,
            allows_multiple: document.getElementById('allowsMultiple').checked,
            is_active: document.getElementById('isActive').checked
        };
        
        if (!data.title) {
            this.showError('El título es obligatorio');
            return;
        }
        
        try {
            const response = await fetch(`${this.apiBase}/positions/${this.positionId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            
            const result = await response.json();
            
            if (response.ok) {
                this.showSuccess('Cambios guardados correctamente');
                await this.loadPosition();
            } else {
                this.showError(result.error || 'Error al guardar cambios');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error saving position:', error);
        }
    }

    async deletePosition() {
        const users = this.positionData?.current_users || [];
        
        if (users.length > 0) {
            this.showError('No se puede eliminar el puesto porque tiene usuarios asignados');
            return;
        }
        
        const message = `¿Estás seguro de eliminar el puesto "${this.positionData.title}"?\n\nEsta acción no se puede deshacer.`;
        this.showConfirmation(message, async () => {
            await this.executeDeletePosition();
        });
    }

    async executeDeletePosition() {
        try {
            const response = await fetch(`${this.apiBase}/positions/${this.positionId}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                this.showSuccess('Puesto eliminado correctamente');
                setTimeout(() => {
                    window.history.back();
                }, 1000);
            } else {
                const result = await response.json();
                if (result.error === 'position_has_active_users') {
                    this.showError('El puesto tiene usuarios asignados activos');
                } else {
                    this.showError(result.error || 'Error al eliminar el puesto');
                }
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error deleting position:', error);
        }
    }

    // ===========================================
    // GESTIÓN DE USUARIOS
    // ===========================================

    async showAssignUserModal() {
        await this.loadAvailableUsers();
        this.assignUserModal.show();
    }

    async loadAvailableUsers() {
        const select = document.getElementById('userSelect');
        
        try {
            select.innerHTML = '<option value="">Cargando usuarios...</option>';
            
            const response = await fetch(`${this.apiBase}/users?limit=100`);
            const result = await response.json();
            
            if (response.ok && result.data) {
                select.innerHTML = '<option value="">Seleccionar usuario...</option>';
                
                result.data.forEach(user => {
                    const option = document.createElement('option');
                    option.value = user.id;
                    option.textContent = `${user.name}${user.email ? ` (${user.email})` : ''}`;
                    select.appendChild(option);
                });
                
                if (result.data.length === 0) {
                    select.innerHTML = '<option value="">No hay usuarios disponibles</option>';
                }
            }
        } catch (error) {
            console.error('Error loading users:', error);
            select.innerHTML = '<option value="">Error al cargar usuarios</option>';
        }
    }

    async searchUsers(searchTerm) {
        const select = document.getElementById('userSelect');
        
        try {
            const url = searchTerm ?
                `${this.apiBase}/users?search=${encodeURIComponent(searchTerm)}&limit=50` :
                `${this.apiBase}/users?limit=50`;
            
            const response = await fetch(url);
            const result = await response.json();
            
            if (response.ok && result.data) {
                select.innerHTML = '<option value="">Seleccionar usuario...</option>';
                
                result.data.forEach(user => {
                    const option = document.createElement('option');
                    option.value = user.id;
                    option.textContent = `${user.name}${user.email ? ` (${user.email})` : ''}`;
                    select.appendChild(option);
                });
            }
        } catch (error) {
            console.error('Error searching users:', error);
        }
    }

    async handleAssignUser(e) {
        e.preventDefault();
        
        const formData = new FormData(e.target);
        const userId = formData.get('user_id') || document.getElementById('userSelect').value;
        
        if (!userId) {
            this.showError('Debe seleccionar un usuario');
            return;
        }
        
        const data = {
            user_id: parseInt(userId),
            start_date: document.getElementById('startDate').value || null,
            notes: document.getElementById('assignmentNotes').value.trim() || null
        };
        
        try {
            const response = await fetch(`${this.apiBase}/positions/${this.positionId}/assign-user`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            
            const result = await response.json();
            
            if (response.ok) {
                this.showSuccess('Usuario asignado correctamente');
                this.assignUserModal.hide();
                e.target.reset();
                await this.loadPosition();
                await this.loadUsers();
            } else {
                this.showError(result.error || 'Error al asignar usuario');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error assigning user:', error);
        }
    }

    async removeUser(userId) {
        const message = '¿Estás seguro de remover este usuario del puesto?';
        this.showConfirmation(message, async () => {
            await this.executeRemoveUser(userId);
        });
    }

    async executeRemoveUser(userId) {
        try {
            const response = await fetch(`${this.apiBase}/positions/${this.positionId}/remove-user`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId })
            });
            
            if (response.ok) {
                this.showSuccess('Usuario removido correctamente');
                await this.loadPosition();
                await this.loadUsers();
            } else {
                const result = await response.json();
                this.showError(result.error || 'Error al remover usuario');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error removing user:', error);
        }
    }

    // ===========================================
    // GESTIÓN DE APLICACIONES Y PERMISOS
    // ===========================================

    async showManageAppsModal() {
        await this.loadAppsForModal();
        this.populateGlobalRoles(); // ⭐ NUEVO: Poblar roles globales
        this.manageAppsModal.show();
        
        document.getElementById('appAssignmentPanel').style.display = 'none';
    }

    // ⭐ NUEVO: Poblar roles globales en el select
    populateGlobalRoles() {
        const select = document.getElementById('roleToAssign');
        if (!select) return;
        
        select.innerHTML = '<option value="">Seleccionar rol...</option>';
        this.availableRoles.forEach(role => {
            const option = document.createElement('option');
            option.value = role.name;
            option.textContent = role.name;
            select.appendChild(option);
        });
    }

    async loadAppsForModal() {
        const container = document.getElementById('appsListModal');
        
        try {
            const response = await fetch(`${this.apiBase}/authz/apps`);
            const result = await response.json();
            
            if (response.ok && result.data) {
                this.apps = result.data;
                
                if (this.apps.length === 0) {
                    container.innerHTML = '<div class="text-muted text-center py-3">No hay aplicaciones</div>';
                    return;
                }
                
                container.innerHTML = this.apps.map(app => `
                    <button class="list-group-item list-group-item-action app-item d-flex align-items-center"
                            data-app-key="${app.key}" data-app-name="${app.name}">
                        <i class="bi bi-app me-2 text-primary"></i>
                        <div>
                            <div class="fw-bold">${app.name}</div>
                            <small class="text-muted">${app.key}</small>
                        </div>
                    </button>
                `).join('');
            } else {
                container.innerHTML = '<div class="alert alert-danger">Error al cargar aplicaciones</div>';
            }
        } catch (error) {
            console.error('Error loading apps:', error);
            container.innerHTML = '<div class="alert alert-danger">Error de conexión</div>';
        }
    }

    async selectApp(btn) {
        document.querySelectorAll('.app-item').forEach(item => {
            item.classList.remove('active');
        });
        btn.classList.add('active');
        
        this.currentAppKey = btn.dataset.appKey;
        const appName = btn.dataset.appName;
        
        document.getElementById('selectedAppName').textContent = appName;
        document.getElementById('appAssignmentPanel').style.display = 'block';
        
        await this.loadAppAssignments();
    }

    async loadAppAssignments() {
        if (!this.currentAppKey) return;
        
        try {
            const rolesResponse = await fetch(`${this.apiBase}/positions/${this.positionId}/apps/${this.currentAppKey}/roles`);
            const rolesResult = rolesResponse.ok ? await rolesResponse.json() : { data: [] };
            const roles = rolesResult.data || [];
            
            const permsResponse = await fetch(`${this.apiBase}/positions/${this.positionId}/apps/${this.currentAppKey}/perms`);
            const permsResult = permsResponse.ok ? await permsResponse.json() : { data: [] };
            const perms = permsResult.data || [];
            
            const effectiveResponse = await fetch(`${this.apiBase}/positions/${this.positionId}/effective-perms/${this.currentAppKey}`);
            const effectiveResult = effectiveResponse.ok ? await effectiveResponse.json() : { data: [] };
            const effectivePerms = effectiveResult.data || [];
            
            this.renderRoles(roles);
            this.renderPermissions(perms);
            this.renderEffectivePermissions(effectivePerms);
            
            // ⭐ MODIFICADO: Ya no necesitamos cargar roles (ya están cargados)
            await this.loadAppPermissions();
            
        } catch (error) {
            console.error('Error loading app assignments:', error);
        }
    }

    // ⭐ MODIFICADO: Solo cargar permisos (roles ya están cargados)
    async loadAppPermissions() {
        if (!this.currentAppKey) return;
        
        try {
            const permsResponse = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/perms`);
            if (permsResponse.ok) {
                const permsResult = await permsResponse.json();
                this.permissions = permsResult.data || [];
                this.populatePermissionSelect();
            }
        } catch (error) {
            console.error('Error loading app permissions:', error);
        }
    }

    populatePermissionSelect() {
        const select = document.getElementById('permToAssign');
        if (!select) return;
        
        select.innerHTML = '<option value="">Seleccionar permiso...</option>';
        this.permissions.forEach(perm => {
            const option = document.createElement('option');
            option.value = perm.code;
            option.textContent = `${perm.name} (${perm.code})`;
            select.appendChild(option);
        });
    }

    renderRoles(roles) {
        const container = document.getElementById('rolesList');
        if (!container) return;
        
        if (roles.length === 0) {
            container.innerHTML = '<small class="text-muted">Sin roles</small>';
            return;
        }
        
        container.innerHTML = roles.map(role => `
            <span class="badge bg-primary d-flex align-items-center gap-1">
                ${role}
                <button class="btn-close btn-close-white btn-sm remove-role-btn" 
                        data-role-name="${role}" style="font-size: 0.6em;"></button>
            </span>
        `).join('');
    }

    renderPermissions(perms) {
        const container = document.getElementById('permsList');
        if (!container) return;
        
        if (perms.length === 0) {
            container.innerHTML = '<small class="text-muted">Sin permisos directos</small>';
            return;
        }
        
        container.innerHTML = perms.map(perm => `
            <span class="badge bg-success d-flex align-items-center gap-1">
                ${perm}
                <button class="btn-close btn-close-white btn-sm remove-perm-btn" 
                        data-perm-code="${perm}" style="font-size: 0.6em;"></button>
            </span>
        `).join('');
    }

    renderEffectivePermissions(perms) {
        const container = document.getElementById('effectivePermsList');
        if (!container) return;
        
        if (perms.length === 0) {
            container.innerHTML = '<small class="text-muted">Sin permisos efectivos</small>';
            return;
        }
        
        container.innerHTML = perms.map(perm => 
            `<span class="badge bg-info">${perm}</span>`
        ).join(' ');
    }

    async assignRole() {
        const select = document.getElementById('roleToAssign');
        const roleName = select?.value;
        
        if (!roleName) {
            this.showError('Selecciona un rol');
            return;
        }
        
        try {
            const response = await fetch(`${this.apiBase}/positions/${this.positionId}/apps/${this.currentAppKey}/roles`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role_name: roleName })
            });
            
            if (response.ok) {
                this.showSuccess('Rol asignado correctamente');
                select.value = '';
                await this.loadAppAssignments();
                await this.loadPosition();
                await this.loadAppsAssignments();
            } else {
                const result = await response.json();
                this.showError(result.error || 'Error al asignar rol');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error assigning role:', error);
        }
    }

    async assignPermission() {
        const select = document.getElementById('permToAssign');
        const permCode = select?.value;
        
        if (!permCode) {
            this.showError('Selecciona un permiso');
            return;
        }
        
        try {
            const response = await fetch(`${this.apiBase}/positions/${this.positionId}/apps/${this.currentAppKey}/perms`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: permCode, allow: true })
            });
            
            if (response.ok) {
                this.showSuccess('Permiso asignado correctamente');
                select.value = '';
                await this.loadAppAssignments();
                await this.loadPosition();
                await this.loadAppsAssignments();
            } else {
                const result = await response.json();
                this.showError(result.error || 'Error al asignar permiso');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error assigning permission:', error);
        }
    }

    async removeRole(roleName) {
        try {
            const response = await fetch(`${this.apiBase}/positions/${this.positionId}/apps/${this.currentAppKey}/roles/${roleName}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                this.showSuccess('Rol removido correctamente');
                await this.loadAppAssignments();
                await this.loadPosition();
                await this.loadAppsAssignments();
            } else {
                const result = await response.json();
                this.showError(result.error || 'Error al remover rol');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error removing role:', error);
        }
    }

    async removePermission(permCode) {
        try {
            const response = await fetch(`${this.apiBase}/positions/${this.positionId}/apps/${this.currentAppKey}/perms/${permCode}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                this.showSuccess('Permiso removido correctamente');
                await this.loadAppAssignments();
                await this.loadPosition();
                await this.loadAppsAssignments();
            } else {
                const result = await response.json();
                this.showError(result.error || 'Error al remover permiso');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error removing permission:', error);
        }
    }

    // ===========================================
    // UTILIDADES
    // ===========================================

    showConfirmation(message, callback) {
        const messageEl = document.getElementById('confirmMessage');
        messageEl.textContent = message;
        this.pendingConfirmAction = callback;
        this.confirmModal.show();
    }

    showSuccess(message) {
        const toast = document.getElementById('successToast');
        const messageEl = document.getElementById('successMessage');
        messageEl.textContent = message;
        new bootstrap.Toast(toast).show();
    }

    showError(message) {
        const toast = document.getElementById('errorToast');
        const messageEl = document.getElementById('errorMessage');
        messageEl.textContent = message;
        new bootstrap.Toast(toast).show();
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    if (typeof POSITION_ID !== 'undefined' && typeof AVAILABLE_ROLES !== 'undefined') {
        new PositionDetailManager(POSITION_ID, AVAILABLE_ROLES);
    }
});