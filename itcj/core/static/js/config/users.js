// users.js - Gestión de usuarios y asignaciones
class UsersManager {
    constructor() {
        this.apiBase = '/api/core/v1';
        this.currentUserId = null;
        this.currentAppKey = null;
        this.apps = [];
        this.permissions = [];
        this.ready = this.init();
        this.newUserModal = null;
    }

    async init() {
        this.bindEvents();
        this.initModals();
        await this.loadAppsData();
        
        // Cargar filtros desde URL si existen
        this.loadFiltersFromURL();
        
        // Cargar usuarios con filtros aplicados
        await this.loadUserApps();
    }

    bindEvents() {
        // Search functionality
        const searchInput = document.getElementById('searchUsers');
        const searchButton = document.getElementById('searchButton');
        
        if (searchInput) {
            // Búsqueda al presionar Enter
            searchInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    this.performSearch();
                }
            });
        }
        
        if (searchButton) {
            // Búsqueda al hacer clic en el botón
            searchButton.addEventListener('click', () => {
                this.performSearch();
            });
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
        const saveNewUserBtn = document.getElementById('saveNewUserBtn');
        if (saveNewUserBtn) {
            saveNewUserBtn.addEventListener('click', () => this.saveNewUser());
        }

        document.querySelectorAll('input[name="userType"]').forEach(radio => {
            radio.addEventListener('change', (e) => this.toggleUserTypeFields(e.target.value));
        });
    }

    initModals() {
        this.assignModal = new bootstrap.Modal(document.getElementById('assignUserModal'));
        const newUserModalElement = document.getElementById('newUserModal');
        if (newUserModalElement) {
            this.newUserModal = new bootstrap.Modal(newUserModalElement);
        }
    }
    toggleUserTypeFields(userType) {
        const studentFields = document.getElementById('studentFields');
        const staffFields = document.getElementById('staffFields');
        const controlNumberInput = document.getElementById('controlNumber');
        const usernameInput = document.getElementById('username');

        if (userType === 'student') {
            studentFields.style.display = 'block';
            staffFields.style.display = 'none';
            controlNumberInput.required = true;
            usernameInput.required = false;
        } else {
            studentFields.style.display = 'none';
            staffFields.style.display = 'block';
            controlNumberInput.required = false;
            usernameInput.required = true;
        }
    }

    async saveNewUser() {
        const form = document.getElementById('newUserForm');
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }

        // Obtener referencia al modal directamente
        const modalElement = document.getElementById('newUserModal');
        const modal = bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);

        const payload = {
            full_name: document.getElementById('fullName').value,
            email: document.getElementById('email').value,
            user_type: document.querySelector('input[name="userType"]:checked').value,
            control_number: document.getElementById('controlNumber').value || null,
            username: document.getElementById('username').value || null,
            password: document.getElementById('password').value
        };

        try {
            const response = await fetch(`${this.apiBase}/users`, {  // Cambiar de /authz/users a /users
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const result = await response.json();

            if (response.ok) {
                this.showSuccess('Usuario creado exitosamente');

                // Limpiar el formulario
                form.reset();

                // Ocultar modal
                modal.hide();

                // Recargar solo la tabla de usuarios sin recargar toda la página
                await this.refreshUsersTable();

            } else {
                this.showError(result.error || 'Ocurrió un error al crear el usuario.');
            }
        } catch (error) {
            console.error('Error creating user:', error);
            this.showError('Error de conexión al crear el usuario.');
        }
    }
    async refreshUsersTable() {
        try {
            // Recargar solo los datos de usuarios sin recargar toda la página
            await this.loadUserApps();

            // Si tienes paginación, podrías recargar la página actual
            // o simplemente mantener al usuario en la página donde está
            this.showSuccess('Lista de usuarios actualizada');

        } catch (error) {
            console.error('Error refreshing users table:', error);
            this.showError('Error al actualizar la lista de usuarios');
        }
    }
    async loadAppsData() {
        try {
            const response = await fetch(`${this.apiBase}/authz/apps`);
            // Maneja 204 ó errores sin body
            let result = {};
            try { result = await response.json(); } catch (_) { }
            if (response.ok && result.data) {
                this.apps = Array.isArray(result.data) ? result.data : [];
            } else {
                this.apps = [];
                console.warn('No apps loaded:', response.status, result?.error);
            }
        } catch (error) {
            this.apps = [];
            console.error('Error loading apps:', error);
        }
    }
    async ensureAppsLoaded() {
        if (this.apps && this.apps.length) return;
        await this.loadAppsData();
    }
    async loadUserApps() {
        await this.ensureAppsLoaded(); // <-- seguridad extra
        const userRows = document.querySelectorAll('[data-user-id]');
        for (const row of userRows) {
            const userId = row.dataset.userId;
            await this.loadUserAppsForRow(userId);
        }
    }

    async loadUserAppsForRow(userId) {
        await this.ensureAppsLoaded(); // <-- seguridad extra
        const container = document.getElementById(`userApps_${userId}`);
        if (!container) return;

        try {
            // paraleliza por app para ese usuario
            const checks = (this.apps || []).map(app =>
                this.checkUserHasAssignments(userId, app.key).then(has => [app.key, has])
            );
            const results = await Promise.all(checks);
            const appKeys = results.filter(([, has]) => has).map(([key]) => key);
            this.renderUserApps(container, appKeys);
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
            } else if (rolesResponse.status !== 404) {
                console.warn(`Error checking roles for user ${userId} in app ${appKey}:`, rolesResponse.status);
            }

            // Check permissions
            const permsResponse = await fetch(`${this.apiBase}/authz/apps/${appKey}/users/${userId}/perms`);
            if (permsResponse.ok) {
                const permsResult = await permsResponse.json();
                if (permsResult.data && permsResult.data.length > 0) {
                    return true;
                }
            } else if (permsResponse.status !== 404) {
                console.warn(`Error checking perms for user ${userId} in app ${appKey}:`, permsResponse.status);
            }

            return false;
        } catch (error) {
            console.error(`Error checking assignments for user ${userId} in app ${appKey}:`, error);
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
            return `<span class="badge bg-${app ? app.key : 'primary'}" title="${app ? app.name : appKey}">${appKey}</span>`;
        }).join(' ');

        container.innerHTML = badges;
    }

    async applyFilters(resetToPage1 = true) {
        const roleFilter = document.getElementById('roleFilter').value;
        const appFilter = document.getElementById('appFilter').value;
        const statusFilter = document.getElementById('statusFilter').value;
        const searchInput = document.getElementById('searchUsers');
        const searchValue = searchInput ? searchInput.value.trim() : '';
        
        // Construir parámetros de consulta
        const params = new URLSearchParams();
        
        if (searchValue) params.append('search', searchValue);
        if (roleFilter) params.append('role', roleFilter);
        if (appFilter) params.append('app', appFilter);
        if (statusFilter) params.append('status', statusFilter);
        
        // Resetear a página 1 solo cuando se aplican nuevos filtros, no al cambiar de página
        const currentPage = resetToPage1 ? '1' : new URLSearchParams(window.location.search).get('page') || '1';
        params.append('page', currentPage);
        params.append('per_page', '20');
        
        try {
            // Hacer petición al API
            const response = await fetch(`${this.apiBase}/users?${params.toString()}`);
            const result = await response.json();
            
            if (response.ok && result.data) {
                // Actualizar la tabla con los nuevos datos
                await this.updateUsersTable(result.data.users, result.data.pagination);
                
                // Actualizar URL para mantener filtros en navegación
                this.updateURL(params);
            } else {
                this.showError('Error al aplicar filtros');
            }
        } catch (error) {
            console.error('Error applying filters:', error);
            this.showError('Error de conexión al aplicar filtros');
        }
    }

    async performSearch() {
        // Simplemente usar la misma lógica de filtros
        await this.applyFilters();
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
                body: JSON.stringify({ role_name: roleName })
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
                body: JSON.stringify({ code: permCode, allow: true })
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

    updateUsersTable(users, pagination) {
        const tbody = document.querySelector('#usersTable tbody');
        if (!tbody) return;
        
        // Limpiar tabla actual
        tbody.innerHTML = '';
        
        if (users.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center py-5">
                        <i class="bi bi-person-lines-fill display-1 text-muted"></i>
                        <h5 class="text-muted mt-3">No se encontraron usuarios</h5>
                        <p class="text-muted">Intenta con otros filtros de búsqueda</p>
                    </td>
                </tr>
            `;
            return;
        }
        
        // Generar filas de usuarios
        users.forEach(user => {
            const row = document.createElement('tr');
            row.className = 'user-row';
            row.setAttribute('data-user-id', user.id);
            
            row.innerHTML = `
                <td class="px-4 py-3">
                    <div class="d-flex align-items-center">
                        <div class="user-avatar rounded-circle d-flex align-items-center justify-content-center text-white me-3">
                            ${user.full_name[0].toUpperCase()}
                        </div>
                        <div>
                            <div class="fw-bold">${user.full_name}</div>
                            ${user.username ? `<small class="text-muted">@${user.username}</small>` : 
                              user.control_number ? `<small class="text-muted">${user.control_number}</small>` : ''}
                        </div>
                    </div>
                </td>
                <td class="py-3">
                    ${user.is_active ? 
                        (user.roles && user.roles.length > 0 ? 
                            user.roles.map(role => `<span class="badge bg-secondary badge-role">${role}</span>`).join(' ') :
                            '<span class="text-muted">Sin rol</span>') :
                        '<span class="text-muted">Usuario inactivo</span>'}
                </td>
                <td class="py-3">${user.email || 'N/A'}</td>
                <td class="py-3">
                    <span class="badge ${user.is_active ? 'bg-success' : 'bg-danger'}">
                        ${user.is_active ? 'Activo' : 'Inactivo'}
                    </span>
                </td>
                <td class="py-3">
                    <div class="d-flex gap-1" id="userApps_${user.id}">
                        <span class="badge bg-light text-muted">Cargando...</span>
                    </div>
                </td>
                <td class="py-3 text-end">
                    <div class="btn-group btn-group-sm">
                        <a href="/itcj/config/users/${user.id}" class="btn btn-outline-primary" title="Ver Detalles">
                            <i class="bi bi-eye"></i>
                        </a>
                        <button class="btn btn-outline-secondary assign-user-btn" 
                                data-user-id="${user.id}" data-user-name="${user.full_name}" 
                                title="Asignar Apps/Roles">
                            <i class="bi bi-gear"></i>
                        </button>
                    </div>
                </td>
            `;
            
            tbody.appendChild(row);
        });
        
        // Actualizar paginación
        this.updatePagination(pagination);
        
        // Cargar apps para cada usuario
        users.forEach(user => {
            this.loadUserAppsForRow(user.id);
        });
    }

    updatePagination(pagination) {
        const paginationContainer = document.querySelector('.pagination');
        if (!paginationContainer) return;
        
        // Limpiar paginación actual
        paginationContainer.innerHTML = '';
        
        // Obtener filtros actuales para mantenerlos en los enlaces
        const currentFilters = new URLSearchParams();
        const searchValue = document.getElementById('searchUsers')?.value.trim();
        const roleFilter = document.getElementById('roleFilter')?.value;
        const appFilter = document.getElementById('appFilter')?.value;
        const statusFilter = document.getElementById('statusFilter')?.value;
        
        if (searchValue) currentFilters.append('search', searchValue);
        if (roleFilter) currentFilters.append('role', roleFilter);
        if (appFilter) currentFilters.append('app', appFilter);
        if (statusFilter) currentFilters.append('status', statusFilter);
        
        // Botón "Anterior"
        const prevLi = document.createElement('li');
        prevLi.className = pagination.has_prev ? 'page-item' : 'page-item disabled';
        
        if (pagination.has_prev) {
            const prevLink = document.createElement('a');
            prevLink.className = 'page-link';
            prevLink.href = '#';
            prevLink.textContent = 'Anterior';
            prevLink.addEventListener('click', (e) => {
                e.preventDefault();
                this.goToPage(pagination.prev_num);
            });
            prevLi.appendChild(prevLink);
        } else {
            const prevSpan = document.createElement('span');
            prevSpan.className = 'page-link';
            prevSpan.textContent = 'Anterior';
            prevLi.appendChild(prevSpan);
        }
        paginationContainer.appendChild(prevLi);
        
        // Números de página
        const startPage = Math.max(1, pagination.page - 2);
        const endPage = Math.min(pagination.pages, pagination.page + 2);
        
        // Primera página si no está en el rango
        if (startPage > 1) {
            const firstLi = document.createElement('li');
            firstLi.className = 'page-item';
            const firstLink = document.createElement('a');
            firstLink.className = 'page-link';
            firstLink.href = '#';
            firstLink.textContent = '1';
            firstLink.addEventListener('click', (e) => {
                e.preventDefault();
                this.goToPage(1);
            });
            firstLi.appendChild(firstLink);
            paginationContainer.appendChild(firstLi);
            
            if (startPage > 2) {
                const dotsLi = document.createElement('li');
                dotsLi.className = 'page-item disabled';
                const dotsSpan = document.createElement('span');
                dotsSpan.className = 'page-link';
                dotsSpan.textContent = '...';
                dotsLi.appendChild(dotsSpan);
                paginationContainer.appendChild(dotsLi);
            }
        }
        
        // Páginas en el rango
        for (let i = startPage; i <= endPage; i++) {
            const pageLi = document.createElement('li');
            pageLi.className = i === pagination.page ? 'page-item active' : 'page-item';
            
            if (i === pagination.page) {
                const pageSpan = document.createElement('span');
                pageSpan.className = 'page-link';
                pageSpan.textContent = i;
                pageLi.appendChild(pageSpan);
            } else {
                const pageLink = document.createElement('a');
                pageLink.className = 'page-link';
                pageLink.href = '#';
                pageLink.textContent = i;
                pageLink.addEventListener('click', (e) => {
                    e.preventDefault();
                    this.goToPage(i);
                });
                pageLi.appendChild(pageLink);
            }
            paginationContainer.appendChild(pageLi);
        }
        
        // Última página si no está en el rango
        if (endPage < pagination.pages) {
            if (endPage < pagination.pages - 1) {
                const dotsLi = document.createElement('li');
                dotsLi.className = 'page-item disabled';
                const dotsSpan = document.createElement('span');
                dotsSpan.className = 'page-link';
                dotsSpan.textContent = '...';
                dotsLi.appendChild(dotsSpan);
                paginationContainer.appendChild(dotsLi);
            }
            
            const lastLi = document.createElement('li');
            lastLi.className = 'page-item';
            const lastLink = document.createElement('a');
            lastLink.className = 'page-link';
            lastLink.href = '#';
            lastLink.textContent = pagination.pages;
            lastLink.addEventListener('click', (e) => {
                e.preventDefault();
                this.goToPage(pagination.pages);
            });
            lastLi.appendChild(lastLink);
            paginationContainer.appendChild(lastLi);
        }
        
        // Botón "Siguiente"
        const nextLi = document.createElement('li');
        nextLi.className = pagination.has_next ? 'page-item' : 'page-item disabled';
        
        if (pagination.has_next) {
            const nextLink = document.createElement('a');
            nextLink.className = 'page-link';
            nextLink.href = '#';
            nextLink.textContent = 'Siguiente';
            nextLink.addEventListener('click', (e) => {
                e.preventDefault();
                this.goToPage(pagination.next_num);
            });
            nextLi.appendChild(nextLink);
        } else {
            const nextSpan = document.createElement('span');
            nextSpan.className = 'page-link';
            nextSpan.textContent = 'Siguiente';
            nextLi.appendChild(nextSpan);
        }
        paginationContainer.appendChild(nextLi);
    }

    updateURL(params) {
        // Actualizar URL para mantener filtros en el historial del navegador
        const newURL = `${window.location.pathname}?${params.toString()}`;
        window.history.replaceState({}, '', newURL);
    }

    async goToPage(pageNumber) {
        const roleFilter = document.getElementById('roleFilter').value;
        const appFilter = document.getElementById('appFilter').value;
        const statusFilter = document.getElementById('statusFilter').value;
        const searchInput = document.getElementById('searchUsers');
        const searchValue = searchInput ? searchInput.value.trim() : '';
        
        // Construir parámetros de consulta manteniendo los filtros actuales
        const params = new URLSearchParams();
        
        if (searchValue) params.append('search', searchValue);
        if (roleFilter) params.append('role', roleFilter);
        if (appFilter) params.append('app', appFilter);
        if (statusFilter) params.append('status', statusFilter);
        
        // Agregar la página específica
        params.append('page', pageNumber.toString());
        params.append('per_page', '20');
        
        try {
            // Hacer petición al API
            const response = await fetch(`${this.apiBase}/users?${params.toString()}`);
            const result = await response.json();
            
            if (response.ok && result.data) {
                // Actualizar la tabla con los nuevos datos
                await this.updateUsersTable(result.data.users, result.data.pagination);
                
                // Actualizar URL para mantener filtros y página en navegación
                this.updateURL(params);
                
                // Scroll hacia arriba para mostrar los nuevos resultados
                window.scrollTo({ top: 0, behavior: 'smooth' });
            } else {
                this.showError('Error al cargar la página');
            }
        } catch (error) {
            console.error('Error loading page:', error);
            this.showError('Error de conexión al cargar la página');
        }
    }

    loadFiltersFromURL() {
        const params = new URLSearchParams(window.location.search);
        
        const roleFilter = document.getElementById('roleFilter');
        const appFilter = document.getElementById('appFilter');
        const statusFilter = document.getElementById('statusFilter');
        const searchInput = document.getElementById('searchUsers');
        
        if (roleFilter && params.get('role')) {
            roleFilter.value = params.get('role');
        }
        if (appFilter && params.get('app')) {
            appFilter.value = params.get('app');
        }
        if (statusFilter && params.get('status')) {
            statusFilter.value = params.get('status');
        }
        if (searchInput && params.get('search')) {
            searchInput.value = params.get('search');
        }
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', async () => {
    const mgr = new UsersManager();
    await mgr.ready;
});