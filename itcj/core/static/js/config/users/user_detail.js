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
        this.loadUserPositions();
        this.loadAllUserAssignments();
    }

    bindEvents() {
        // Reset Password button
        const resetPasswordBtn = document.getElementById('btnResetPassword');
        if (resetPasswordBtn) {
            resetPasswordBtn.addEventListener('click', () => this.showResetPasswordModal());
        }

        // Confirm reset password
        const confirmResetBtn = document.getElementById('confirmResetPasswordBtn');
        if (confirmResetBtn) {
            confirmResetBtn.addEventListener('click', () => this.resetPassword());
        }

        // Edit user button
        const editUserBtn = document.getElementById('btnEditUser');
        if (editUserBtn) {
            editUserBtn.addEventListener('click', () => this.showEditUserModal());
        }

        // Edit user form submit
        const editUserForm = document.getElementById('editUserForm');
        if (editUserForm) {
            editUserForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.saveUserInfo();
            });
        }

        // Toggle status button
        const toggleStatusBtn = document.getElementById('btnToggleStatus');
        if (toggleStatusBtn) {
            toggleStatusBtn.addEventListener('click', () => this.showToggleStatusModal());
        }

        // Confirm toggle status
        const confirmToggleBtn = document.getElementById('confirmToggleStatusBtn');
        if (confirmToggleBtn) {
            confirmToggleBtn.addEventListener('click', () => this.toggleStatus());
        }

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

        // Tab change events - load data when tabs are activated
        const tabTriggers = document.querySelectorAll('#userDetailTabs button[data-bs-toggle="tab"]');
        tabTriggers.forEach(tab => {
            tab.addEventListener('shown.bs.tab', (e) => {
                const targetId = e.target.getAttribute('data-bs-target');
                
                if (targetId === '#positions-pane') {
                    // Recargar puestos si es necesario
                    this.loadUserPositions();
                } else if (targetId === '#apps-pane') {
                    // Recargar asignaciones por app si es necesario
                    this.loadAllUserAssignments();
                }
                // activity-pane no necesita cargar datos por ahora
            });
        });
    }

    initModals() {
        this.manageModal = new bootstrap.Modal(document.getElementById('manageAssignmentsModal'));
        this.resetPasswordModal = new bootstrap.Modal(document.getElementById('confirmResetPasswordModal'));
        const toggleModal = document.getElementById('confirmToggleStatusModal');
        if (toggleModal) {
            this.toggleStatusModal = new bootstrap.Modal(toggleModal);
        }
        const editModal = document.getElementById('editUserModal');
        if (editModal) {
            this.editUserModal = new bootstrap.Modal(editModal);
        }
    }

    async loadUserPositions() {
        try {
            const response = await fetch(`${this.apiBase}/positions/users/${this.userId}/positions`);
            const result = await response.json();
            
            if (response.ok && result.data) {
                this.renderUserPositions(result.data);
            } else {
                this.renderPositionsError();
            }
        } catch (error) {
            console.error('Error loading user positions:', error);
            this.renderPositionsError();
        }
    }

    renderUserPositions(positions) {
        const container = document.getElementById('userPositionsContainer');
        if (!container) return;

        container.innerHTML = '';

        if (positions.length === 0) {
            container.innerHTML = `
                <div class="col-12">
                    <div class="text-center py-5">
                        <i class="bi bi-briefcase display-1 text-muted"></i>
                        <h5 class="text-muted mt-3">Sin puestos asignados</h5>
                        <p class="text-muted">Este usuario no tiene puestos organizacionales activos</p>
                    </div>
                </div>
            `;
            return;
        }

        positions.forEach(position => {
            const positionCard = document.createElement('div');
            positionCard.className = 'col-12 col-md-6 col-lg-4';
            
            positionCard.innerHTML = `
                <div class="card h-100 shadow-sm position-card">
                    <div class="card-header bg-primary text-white">
                        <div class="d-flex align-items-center">
                            <i class="bi bi-briefcase me-2"></i>
                            <div>
                                <h6 class="mb-0">${position.title}</h6>
                                <small class="opacity-75">${position.code}</small>
                            </div>
                        </div>
                    </div>
                    <div class="card-body">
                        ${position.department ? `
                            <div class="mb-3">
                                <h6 class="text-muted mb-2">
                                    <i class="bi bi-building me-1"></i>Departamento
                                </h6>
                                <div class="d-flex align-items-center">
                                    ${position.department.icon_class ? 
                                        `<i class="${position.department.icon_class} me-2 text-primary"></i>` : 
                                        '<i class="bi bi-building me-2 text-primary"></i>'}
                                    <div>
                                        <div class="fw-bold">${position.department.name}</div>
                                        <small class="text-muted">${position.department.code}</small>
                                    </div>
                                </div>
                            </div>
                        ` : ''}
                        
                        <div class="mb-3">
                            <h6 class="text-success mb-2">
                                <i class="bi bi-calendar-check me-1"></i>Información
                            </h6>
                            <div class="small text-muted">
                                <div><strong>Inicio:</strong> ${new Date(position.start_date).toLocaleDateString('es-ES')}</div>
                                ${position.notes ? `<div><strong>Notas:</strong> ${position.notes}</div>` : ''}
                            </div>
                        </div>

                        <div>
                            <h6 class="text-info mb-2">
                                <i class="bi bi-shield-check me-1"></i>Permisos por Puesto
                            </h6>
                            <div id="positionPerms_${position.position_id}" class="d-flex flex-wrap gap-1">
                                <span class="badge bg-light text-muted">Cargando...</span>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            
            container.appendChild(positionCard);
            
            // Cargar permisos del puesto
            this.loadPositionPermissions(position.position_id);
        });
    }

    async loadPositionPermissions(positionId) {
        try {
            const response = await fetch(`${this.apiBase}/positions/${positionId}/assignments`);
            const result = await response.json();
            
            if (response.ok && result.data) {
                this.renderPositionPermissions(positionId, result.data.apps);
            } else {
                this.renderPositionPermissionsError(positionId);
            }
        } catch (error) {
            console.error(`Error loading permissions for position ${positionId}:`, error);
            this.renderPositionPermissionsError(positionId);
        }
    }

    renderPositionPermissions(positionId, apps) {
        const container = document.getElementById(`positionPerms_${positionId}`);
        if (!container) return;

        if (!apps || Object.keys(apps).length === 0) {
            container.innerHTML = '<small class="text-muted">Sin permisos asignados</small>';
            return;
        }

        let badges = [];
        
        Object.entries(apps).forEach(([appKey, appData]) => {
            // Roles
            if (appData.roles && appData.roles.length > 0) {
                appData.roles.forEach(role => {
                    badges.push(`<span class="badge bg-primary" title="${appData.app_name} - Rol">${appKey}: ${role}</span>`);
                });
            }
            
            // Permisos directos
            if (appData.direct_permissions && appData.direct_permissions.length > 0) {
                appData.direct_permissions.forEach(perm => {
                    badges.push(`<span class="badge bg-success" title="${appData.app_name} - Permiso directo">${appKey}: ${perm}</span>`);
                });
            }
        });

        if (badges.length === 0) {
            container.innerHTML = '<small class="text-muted">Sin permisos asignados</small>';
        } else {
            container.innerHTML = badges.join(' ');
        }
    }

    renderPositionPermissionsError(positionId) {
        const container = document.getElementById(`positionPerms_${positionId}`);
        if (container) {
            container.innerHTML = '<span class="badge bg-danger">Error al cargar</span>';
        }
    }

    renderPositionsError() {
        const container = document.getElementById('userPositionsContainer');
        if (container) {
            container.innerHTML = `
                <div class="col-12">
                    <div class="text-center py-5">
                        <i class="bi bi-exclamation-triangle display-1 text-danger"></i>
                        <h5 class="text-danger mt-3">Error al cargar puestos</h5>
                        <p class="text-muted">No se pudieron cargar los puestos organizacionales</p>
                    </div>
                </div>
            `;
        }
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

    showResetPasswordModal() {
        this.resetPasswordModal.show();
    }

    async resetPassword() {
        const confirmBtn = document.getElementById('confirmResetPasswordBtn');
        const originalText = confirmBtn.innerHTML;

        try {
            confirmBtn.disabled = true;
            confirmBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Reseteando...';

            const response = await fetch(`${this.apiBase}/users/${this.userId}/reset-password`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include'
            });

            const result = await response.json();

            if (response.ok) {
                this.resetPasswordModal.hide();
                this.showSuccess('Contraseña reseteada exitosamente. Nueva contraseña: "tecno#2K"');
            } else {
                if (result.error === 'cannot_reset_student_password') {
                    this.showError('No se puede resetear la contraseña de estudiantes');
                } else {
                    this.showError(result.error || 'Error al resetear la contraseña');
                }
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error resetting password:', error);
        } finally {
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = originalText;
        }
    }

    showToggleStatusModal() {
        if (this.toggleStatusModal) {
            this.toggleStatusModal.show();
        }
    }

    async toggleStatus() {
        const confirmBtn = document.getElementById('confirmToggleStatusBtn');
        const originalText = confirmBtn.innerHTML;

        try {
            confirmBtn.disabled = true;
            confirmBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Procesando...';

            const response = await fetch(`${this.apiBase}/users/${this.userId}/toggle-status`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include'
            });

            const result = await response.json();

            if (response.ok) {
                this.toggleStatusModal.hide();
                const action = result.data.is_active ? 'activada' : 'desactivada';
                this.showSuccess(`Cuenta ${action} exitosamente`);
                // Recargar la pagina para reflejar el nuevo estado
                setTimeout(() => location.reload(), 1000);
            } else {
                if (result.error === 'cannot_toggle_own_account') {
                    this.showError('No puedes desactivar tu propia cuenta');
                } else {
                    this.showError(result.error || 'Error al cambiar el estado de la cuenta');
                }
            }
        } catch (error) {
            this.showError('Error de conexion');
            console.error('Error toggling user status:', error);
        } finally {
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = originalText;
        }
    }

    showEditUserModal() {
        if (this.editUserModal) {
            this.editUserModal.show();
        }
    }

    async saveUserInfo() {
        const saveBtn = document.getElementById('saveEditUserBtn');
        const originalText = saveBtn.innerHTML;

        // Recopilar datos del formulario
        const data = {};

        const firstName = document.getElementById('editFirstName');
        if (firstName) data.first_name = firstName.value.trim();

        const lastName = document.getElementById('editLastName');
        if (lastName) data.last_name = lastName.value.trim();

        const middleName = document.getElementById('editMiddleName');
        if (middleName) data.middle_name = middleName.value.trim();

        const email = document.getElementById('editEmail');
        if (email) data.email = email.value.trim();

        const username = document.getElementById('editUsername');
        if (username) data.username = username.value.trim();

        const controlNumber = document.getElementById('editControlNumber');
        if (controlNumber) data.control_number = controlNumber.value.trim();

        try {
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Guardando...';

            const response = await fetch(`${this.apiBase}/users/${this.userId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (response.ok) {
                this.editUserModal.hide();
                this.showSuccess('Informacion actualizada exitosamente');
                setTimeout(() => location.reload(), 1000);
            } else {
                const errorMessages = {
                    'first_name_required': 'El nombre es obligatorio',
                    'last_name_required': 'El apellido paterno es obligatorio',
                    'username_required': 'El nombre de usuario es obligatorio',
                    'username_already_exists': 'Ese nombre de usuario ya esta en uso',
                    'invalid_control_number': 'El numero de control debe ser de 8 digitos',
                    'control_number_already_exists': 'Ese numero de control ya esta registrado',
                    'duplicate_value': 'Ya existe un registro con ese valor'
                };
                this.showError(errorMessages[result.error] || result.error || 'Error al guardar los cambios');
            }
        } catch (error) {
            this.showError('Error de conexion');
            console.error('Error saving user info:', error);
        } finally {
            saveBtn.disabled = false;
            saveBtn.innerHTML = originalText;
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