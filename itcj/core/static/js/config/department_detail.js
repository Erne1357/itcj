// itcj/core/static/js/config/department_detail.js
class DepartmentDetailManager {
    constructor(departmentId) {
        this.apiBase = '/api/core/v1';
        this.departmentId = departmentId;
        this.currentPositionId = null;
        this.currentAppKey = null;
        this.positions = [];
        this.department = null;
        this.apps = [];
        this.permissions = [];
        this.init();
    }

    async init() {
        this.bindEvents();
        this.initModals();
        await this.loadDepartmentInfo();
        await this.loadPositions();
    }

    bindEvents() {
        const createForm = document.getElementById('createPositionForm');
        if (createForm) {
            createForm.addEventListener('submit', (e) => this.handleCreatePosition(e));
        }

        const assignForm = document.getElementById('assignUserForm');
        if (assignForm) {
            assignForm.addEventListener('submit', (e) => this.handleAssignUser(e));
        }

        // Event delegation para botones dinámicos
        document.addEventListener('click', (e) => {
            if (e.target.id === 'assignUserBtn' || e.target.closest('#assignUserBtn')) {
                this.showAssignUserModal(this.currentPositionId);
            }
            if (e.target.id === 'removeUserBtn' || e.target.closest('#removeUserBtn')) {
                this.handleRemoveUser();
            }
            if (e.target.id === 'manageAppsBtn' || e.target.closest('#manageAppsBtn')) {
                this.showManageAppsModal();
            }
        });

        // Gestión de apps - event delegation
        document.addEventListener('click', (e) => {
            // Seleccionar app en modal
            if (e.target.closest('.app-item-position')) {
                const btn = e.target.closest('.app-item-position');
                this.selectAppForPosition(btn);
            }

            // Asignar rol
            if (e.target.id === 'assignRoleBtnPosition') {
                this.assignRoleToPosition();
            }

            // Asignar permiso
            if (e.target.id === 'assignPermBtnPosition') {
                this.assignPermissionToPosition();
            }

            // Remover rol
            if (e.target.closest('.remove-role-btn-position')) {
                const btn = e.target.closest('.remove-role-btn-position');
                this.removeRoleFromPosition(btn.dataset.roleName);
            }

            // Remover permiso
            if (e.target.closest('.remove-perm-btn-position')) {
                const btn = e.target.closest('.remove-perm-btn-position');
                this.removePermissionFromPosition(btn.dataset.permCode);
            }
        });

        // Limpiar modal cuando se cierre
        document.getElementById('assignUserModal')?.addEventListener('hidden.bs.modal', () => {
            this.cleanupAssignUserModal();
        });

        // Manejar el checkbox de múltiples usuarios para mostrar/ocultar email
        const allowsMultipleCheckbox = document.getElementById('allowsMultiple');
        const emailField = document.getElementById('positionEmail');
        if (allowsMultipleCheckbox && emailField) {
            const toggleEmailField = () => {
                const parentDiv = emailField.closest('.mb-3');
                if (allowsMultipleCheckbox.checked) {
                    parentDiv.style.display = 'none';
                    emailField.value = '';
                    emailField.removeAttribute('required');
                } else {
                    parentDiv.style.display = 'block';
                }
            };

            allowsMultipleCheckbox.addEventListener('change', toggleEmailField);
            // Inicializar estado
            toggleEmailField();
        }
    }

    initModals() {
        this.createModal = new bootstrap.Modal(document.getElementById('createPositionModal'));
        this.manageModal = new bootstrap.Modal(document.getElementById('managePositionModal'));
        this.assignUserModal = new bootstrap.Modal(document.getElementById('assignUserModal'));
        this.manageAppsModal = new bootstrap.Modal(document.getElementById('managePositionAppsModal'));
    }

    async loadDepartmentInfo() {
        try {
            const response = await fetch(`${this.apiBase}/departments/${this.departmentId}`);
            const result = await response.json();

            if (response.ok && result.data) {
                this.department = result.data;

                // Update UI
                document.getElementById('deptNameBreadcrumb').textContent = this.department.name;
                document.getElementById('deptNameTitle').textContent = this.department.name;
                document.getElementById('deptDescription').textContent = this.department.description || 'Sin descripción';

                // Show head info
                if (this.department.head) {
                    document.getElementById('deptHeadInfo').style.display = 'block';
                    document.getElementById('headName').textContent = this.department.head.full_name;
                }
            }
        } catch (error) {
            console.error('Error loading department info:', error);
        }
    }

    async loadPositions() {
        try {
            const response = await fetch(`${this.apiBase}/departments/${this.departmentId}`);
            const result = await response.json();

            if (response.ok && result.data) {
                this.positions = result.data.positions || [];
                this.renderPositions();
            }
        } catch (error) {
            console.error('Error loading positions:', error);
            this.showError('Error al cargar los puestos');
        }
    }

    renderPositions() {
        const container = document.getElementById('positionsContainer');
        if (!container) return;

        if (this.positions.length === 0) {
            container.innerHTML = `
                <div class="col-12">
                    <div class="text-center py-5">
                        <i class="bi bi-buildings display-1 text-muted"></i>
                        <h5 class="text-muted mt-3">No hay puestos en este departamento</h5>
                        <p class="text-muted">Crea el primer puesto</p>
                    </div>
                </div>
            `;
            return;
        }

        container.innerHTML = this.positions.map(pos => this.createPositionCard(pos)).join('');

        document.querySelectorAll('.view-position-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const positionId = parseInt(btn.dataset.positionId);
                window.location.href = `/itcj/config/positions/${positionId}`;
            });
        });
    }

    // itcj/core/static/js/config/department_detail.js (continuación)

    createPositionCard(position) {
        const currentUser = position.current_user;
        const statusBadge = position.is_active ?
            '<span class="badge bg-success">Activo</span>' :
            '<span class="badge bg-secondary">Inactivo</span>';

        // ⭐ NUEVO: Icono según allows_multiple
        const positionIcon = position.allows_multiple ?
            'bi-people-fill' : 'bi-person-fill';
        const iconColor = position.allows_multiple ? 'text-info' : 'text-primary';

        return `
        <div class="col-12 col-md-6 col-lg-4" data-position-id="${position.id}">
            <div class="card h-100 shadow-sm">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start mb-3">
                        <div class="d-flex align-items-center">
                            <!-- ⭐ ICONO GRANDE -->
                            <div style="font-size: 2.5rem;" class="${iconColor} me-3">
                                <i class="${positionIcon}"></i>
                            </div>
                            <div>
                                <h5 class="card-title mb-1">${position.title}</h5>
                                <small class="text-muted">${position.code}</small>
                            </div>
                        </div>
                        ${statusBadge}
                    </div>
                    
                    ${position.description ? `<p class="card-text text-muted small">${position.description}</p>` : ''}
                    
                    <!-- ⭐ NUEVO: Mostrar email si existe y es puesto único -->
                    ${!position.allows_multiple && position.email ? `
                        <div class="alert alert-info py-2 px-3 mb-3">
                            <i class="bi bi-envelope me-2"></i>
                            <small><strong>Email:</strong> ${position.email}</small>
                        </div>
                    ` : ''}
                    
                    <div class="border-top pt-3 mt-3">
                        <h6 class="small text-muted mb-2">
                            ${position.allows_multiple ? 'Usuarios Asignados:' : 'Usuario Asignado:'}
                        </h6>
                        ${currentUser ? `
                            <div class="d-flex align-items-center">
                                <div class="bg-primary bg-opacity-10 rounded-circle p-2 me-2">
                                    <i class="bi bi-person text-primary"></i>
                                </div>
                                <div>
                                    <div class="fw-bold small">${currentUser.full_name}</div>
                                    <small class="text-muted">Desde: ${new Date(currentUser.start_date).toLocaleDateString('es-ES')}</small>
                                </div>
                            </div>
                        ` : `
                            <p class="text-muted small mb-0"><i class="bi bi-x-circle me-1"></i>Sin asignar</p>
                        `}
                    </div>
                </div>
                <div class="card-footer bg-transparent">
                    <button class="btn btn-sm btn-outline-primary w-100 view-position-btn" 
                            data-position-id="${position.id}">
                        <i class="bi bi-pencil me-1"></i>Editar Puesto
                    </button>
                </div>
            </div>
        </div>
    `;
    }

    async handleCreatePosition(e) {
        e.preventDefault();

        const formData = new FormData(e.target);

        // Depuración: ver todos los valores del formulario
        console.log('=== FORM DATA DEBUG ===');
        for (let [key, value] of formData.entries()) {
            console.log(`${key}:`, value);
        }

        const data = {
            code: formData.get('code'),
            title: formData.get('title'),
            department_id: this.departmentId,
            description: formData.get('description') || null,
            allows_multiple: formData.get('allows_multiple') === 'on',  // CORREGIDO: era 'allowsMultiple'
            is_active: formData.get('is_active') === 'on'  // Ahora lee del checkbox
        };

        console.log('=== FINAL DATA OBJECT ===');
        console.log('Creating position with data:', data);
        console.log('allows_multiple específicamente:', data.allows_multiple);
        try {
            const response = await fetch(`${this.apiBase}/positions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });

            const result = await response.json();
            console.log('Create position response:', result);
            if (response.ok) {
                this.showSuccess('Puesto creado correctamente');
                this.createModal.hide();
                e.target.reset();
                await this.loadPositions();
            } else {
                this.showError(result.error || 'Error al crear el puesto');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error creating position:', error);
        }
    }

    async showManageModal(positionId) {
        this.currentPositionId = positionId;
        const position = this.positions.find(p => p.id === positionId);

        if (!position) {
            this.showError('Puesto no encontrado');
            return;
        }

        document.getElementById('modalPositionTitle').textContent = position.title;

        await this.loadPositionCurrentUser(positionId);
        await this.loadPositionAssignments(positionId);
        await this.loadPositionApps(positionId);

        this.manageModal.show();
    }

    async loadPositionCurrentUser(positionId) {
        const container = document.getElementById('currentUserInfo');

        try {
            // Cargar todos los usuarios del puesto
            const response = await fetch(`${this.apiBase}/positions/${positionId}/users`);
            const result = await response.json();

            const users = result.data || [];

            if (users.length === 0) {
                container.innerHTML = `
                <div class="alert alert-info mb-0">
                    <i class="bi bi-info-circle me-2"></i>No hay usuarios asignados a este puesto
                </div>
            `;
                document.getElementById('removeUserBtn').style.display = 'none';
            } else if (users.length === 1) {
                // Mostrar como antes (un solo usuario)
                const user = users[0];
                container.innerHTML = `
                <div class="d-flex align-items-center">
                    <div class="bg-primary bg-opacity-10 rounded-circle p-3 me-3">
                        <i class="bi bi-person-fill text-primary fs-4"></i>
                    </div>
                    <div>
                        <h6 class="mb-1">${user.full_name}</h6>
                        <small class="text-muted">${user.email || 'Sin email'}</small><br>
                        <small class="text-muted">Desde: ${new Date(user.start_date).toLocaleDateString('es-ES')}</small>
                    </div>
                </div>
            `;
                document.getElementById('removeUserBtn').style.display = 'inline-block';
            } else {
                // Mostrar lista de múltiples usuarios
                container.innerHTML = `
                <div class="alert alert-success mb-3">
                    <i class="bi bi-people-fill me-2"></i><strong>${users.length} usuarios asignados</strong>
                </div>
                <div class="list-group">
                    ${users.map(user => `
                        <div class="list-group-item d-flex justify-content-between align-items-center">
                            <div>
                                <strong>${user.full_name}</strong><br>
                                <small class="text-muted">${user.email || 'Sin email'}</small><br>
                                <small class="text-muted">Desde: ${new Date(user.start_date).toLocaleDateString('es-ES')}</small>
                            </div>
                            <button class="btn btn-sm btn-outline-danger remove-single-user-btn" 
                                    data-user-id="${user.user_id}">
                                <i class="bi bi-x-lg"></i>
                            </button>
                        </div>
                    `).join('')}
                </div>
            `;

                // Agregar event listeners para remover usuarios individuales
                document.querySelectorAll('.remove-single-user-btn').forEach(btn => {
                    btn.addEventListener('click', () => {
                        this.handleRemoveSpecificUser(parseInt(btn.dataset.userId));
                    });
                });
            }
        } catch (error) {
            container.innerHTML = '<div class="alert alert-danger">Error al cargar usuarios</div>';
            console.error('Error loading current users:', error);
        }
    }

    async loadPositionAssignments(positionId) {
        const container = document.getElementById('positionAppsPermissions');

        try {
            const response = await fetch(`${this.apiBase}/positions/${positionId}/assignments`);
            const result = await response.json();

            if (!response.ok || !result.data) {
                container.innerHTML = '<p class="text-muted">Error al cargar asignaciones</p>';
                return;
            }

            const assignments = result.data;
            const appsData = assignments.apps || {};

            if (Object.keys(appsData).length === 0) {
                container.innerHTML = `
                    <div class="alert alert-info">
                        <i class="bi bi-info-circle me-2"></i>
                        Este puesto no tiene permisos asignados en ninguna aplicación
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
                    '<span class="text-muted small">Sin permisos directos</span>'}
                            </div>
                        </div>
                    </div>
                </div>
            `).join('');

        } catch (error) {
            container.innerHTML = '<div class="alert alert-danger">Error al cargar las asignaciones</div>';
            console.error('Error loading assignments:', error);
        }
    }

    async loadPositionApps(positionId) {
        const container = document.getElementById('positionAppsList');

        try {
            // Load available apps
            const appsResponse = await fetch(`${this.apiBase}/authz/apps`);

            if (!appsResponse.ok) {
                container.innerHTML = '<p class="text-muted">Error al cargar aplicaciones</p>';
                return;
            }

            const appsResult = await appsResponse.json();
            console.log('Apps response:', appsResult);

            if (appsResult.status !== 'ok' || !appsResult.data) {
                container.innerHTML = '<p class="text-muted">Error al cargar aplicaciones</p>';
                return;
            }

            // Load position assignments
            const assignmentsResponse = await fetch(`${this.apiBase}/positions/${positionId}/assignments`);
            let positionApps = {};

            if (assignmentsResponse.ok) {
                const assignmentsResult = await assignmentsResponse.json();
                console.log('Assignments response:', assignmentsResult);
                if (assignmentsResult.status === 'ok' && assignmentsResult.data && assignmentsResult.data.apps) {
                    positionApps = assignmentsResult.data.apps;
                }
            }

            const apps = appsResult.data;

            if (apps.length === 0) {
                container.innerHTML = '<div class="alert alert-info">No hay aplicaciones disponibles</div>';
                return;
            }

            this.apps = apps;
            this.renderAppsInterface(apps, positionApps);

        } catch (error) {
            container.innerHTML = '<div class="alert alert-danger">Error al cargar aplicaciones</div>';
            console.error('Error loading position apps:', error);
        }
    }

    renderAppsInterface(apps, positionApps) {
        const container = document.getElementById('positionAppsList');

        container.innerHTML = apps.map(app => {
            const appAssignments = positionApps[app.key] || { roles: [], direct_permissions: [] };
            const hasAssignments = appAssignments.roles.length > 0 || appAssignments.direct_permissions.length > 0;

            return `
                <div class="card mb-3">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <div>
                            <strong>${app.name}</strong>
                            <small class="text-muted">(${app.key})</small>
                            ${hasAssignments ? '<span class="badge bg-primary ms-2">Asignado</span>' : ''}
                        </div>
                        <button type="button" class="btn btn-sm btn-outline-primary" 
                                data-bs-toggle="collapse" 
                                data-bs-target="#appCollapse${app.id}" 
                                aria-expanded="false">
                            <i class="bi bi-chevron-down"></i>
                        </button>
                    </div>
                    <div class="collapse" id="appCollapse${app.id}">
                        <div class="card-body">
                            <div class="row">
                                <div class="col-md-6">
                                    <h6>Roles</h6>
                                    <div id="appRoles${app.id}">
                                        <div class="d-flex justify-content-center">
                                            <div class="spinner-border spinner-border-sm" role="status"></div>
                                        </div>
                                    </div>
                                </div>
                                <div class="col-md-6">
                                    <h6>Permisos</h6>
                                    <div id="appPerms${app.id}">
                                        <div class="d-flex justify-content-center">
                                            <div class="spinner-border spinner-border-sm" role="status"></div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        // Add event listeners for collapse events
        apps.forEach(app => {
            const collapseEl = document.getElementById(`appCollapse${app.id}`);
            if (collapseEl) {
                collapseEl.addEventListener('show.bs.collapse', () => {
                    console.log('Loading app:', app.key, 'for position:', this.currentPositionId);
                    this.currentAppKey = app.key;
                    this.loadAppRolesAndPermissions(app.key, app.id, positionApps[app.key] || {});
                });
            } else {
                console.error('Collapse element not found:', `appCollapse${app.id}`);
            }
        });
    }

    async loadAppRolesAndPermissions(appKey, appId, currentAssignments) {
        try {
            // Load global roles (roles are not app-specific)
            const rolesResponse = await fetch(`${this.apiBase}/authz/roles`);

            // Load permissions for this app
            const permsResponse = await fetch(`${this.apiBase}/authz/apps/${appKey}/perms`);

            // Load current position roles for this app
            const positionRolesResponse = await fetch(`${this.apiBase}/positions/${this.currentPositionId}/apps/${appKey}/roles`);

            // Load current position permissions for this app
            const positionPermsResponse = await fetch(`${this.apiBase}/positions/${this.currentPositionId}/apps/${appKey}/perms`);

            // Get all available roles
            let availableRoles = [];
            if (rolesResponse.ok) {
                const rolesResult = await rolesResponse.json();
                console.log('Available roles response:', rolesResult);
                if (rolesResult.status === 'ok' && rolesResult.data) {
                    availableRoles = rolesResult.data;
                }
            }

            // Get current position roles for this app
            let assignedRoles = [];
            if (positionRolesResponse.ok) {
                const positionRolesResult = await positionRolesResponse.json();
                console.log('Position roles response:', positionRolesResult);
                if (positionRolesResult.status === 'ok' && positionRolesResult.data) {
                    assignedRoles = positionRolesResult.data;
                }
            }

            // Get available permissions for this app
            let availablePerms = [];
            if (permsResponse.ok) {
                const permsResult = await permsResponse.json();
                console.log('Available permissions response:', permsResult);
                if (permsResult.status === 'ok' && permsResult.data) {
                    availablePerms = permsResult.data;
                }
            }

            // Get current position permissions for this app
            let assignedPerms = [];
            if (positionPermsResponse.ok) {
                const positionPermsResult = await positionPermsResponse.json();
                console.log('Position permissions response:', positionPermsResult);
                if (positionPermsResult.status === 'ok' && positionPermsResult.data) {
                    assignedPerms = positionPermsResult.data;
                }
            }

            // Render the interfaces
            this.renderAppRoles(appId, availableRoles, assignedRoles);
            this.renderAppPermissions(appId, availablePerms, assignedPerms);

        } catch (error) {
            console.error('Error loading app roles and permissions:', error);
            // Show error message in containers
            const rolesContainer = document.getElementById(`appRoles${appId}`);
            const permsContainer = document.getElementById(`appPerms${appId}`);
            if (rolesContainer) rolesContainer.innerHTML = '<div class="text-danger small">Error al cargar roles</div>';
            if (permsContainer) permsContainer.innerHTML = '<div class="text-danger small">Error al cargar permisos</div>';
        }
    }

    renderAppRoles(appId, roles, assignedRoles) {
        const container = document.getElementById(`appRoles${appId}`);

        if (roles.length === 0) {
            container.innerHTML = '<p class="text-muted small">No hay roles disponibles</p>';
            return;
        }

        container.innerHTML = roles.map((role, index) => {
            // Roles come as objects with 'name' property from /authz/roles
            const roleName = role.name || role;
            const isAssigned = assignedRoles.includes(roleName);
            const checkboxId = `role_${appId}_${index}`;
            return `
                <div class="form-check">
                    <input class="form-check-input role-checkbox" type="checkbox" 
                           id="${checkboxId}" 
                           data-role-name="${roleName}"
                           ${isAssigned ? 'checked' : ''}>
                    <label class="form-check-label small" for="${checkboxId}">
                        ${roleName}
                    </label>
                </div>
            `;
        }).join('');

        // Add event listeners to role checkboxes
        container.querySelectorAll('.role-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const roleName = e.target.getAttribute('data-role-name');
                const isChecked = e.target.checked;
                this.togglePositionRole(roleName, isChecked);
            });
        });
    }

    renderAppPermissions(appId, permissions, assignedPerms) {
        const container = document.getElementById(`appPerms${appId}`);

        if (permissions.length === 0) {
            container.innerHTML = '<p class="text-muted small">No hay permisos disponibles</p>';
            return;
        }

        container.innerHTML = permissions.map((perm, index) => {
            // Permissions come as objects with 'code', 'name', 'description' properties
            const permCode = perm.code || perm;
            const isAssigned = assignedPerms.includes(permCode);
            const checkboxId = `perm_${appId}_${index}`;
            return `
                <div class="form-check">
                    <input class="form-check-input perm-checkbox" type="checkbox" 
                           id="${checkboxId}" 
                           data-perm-code="${permCode}"
                           ${isAssigned ? 'checked' : ''}>
                    <label class="form-check-label small" for="${checkboxId}">
                        ${perm.name || permCode}
                        ${perm.description ? `<br><small class="text-muted">${perm.description}</small>` : ''}
                    </label>
                </div>
            `;
        }).join('');

        // Add event listeners to permission checkboxes
        container.querySelectorAll('.perm-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const permCode = e.target.getAttribute('data-perm-code');
                const isChecked = e.target.checked;
                this.togglePositionPermission(permCode, isChecked);
            });
        });
    }

    async togglePositionRole(roleName, assign) {
        console.log('togglePositionRole called:', { roleName, assign, currentAppKey: this.currentAppKey, currentPositionId: this.currentPositionId });

        if (!this.currentAppKey) {
            this.showError('No hay aplicación seleccionada');
            return;
        }

        if (!this.currentPositionId) {
            this.showError('No hay puesto seleccionado');
            return;
        }

        try {
            if (assign) {
                await this.assignRoleToPosition(roleName);
            } else {
                await this.removeRoleFromPosition(roleName);
            }
        } catch (error) {
            console.error('Error toggling role:', error);
            this.showError('Error al cambiar el rol');
        }
    }

    async togglePositionPermission(permCode, assign) {
        console.log('togglePositionPermission called:', { permCode, assign, currentAppKey: this.currentAppKey, currentPositionId: this.currentPositionId });

        if (!this.currentAppKey) {
            this.showError('No hay aplicación seleccionada');
            return;
        }

        if (!this.currentPositionId) {
            this.showError('No hay puesto seleccionado');
            return;
        }

        try {
            if (assign) {
                await this.assignPermissionToPosition(permCode, true);
            } else {
                await this.removePermissionFromPosition(permCode);
            }
        } catch (error) {
            console.error('Error toggling permission:', error);
            this.showError('Error al cambiar el permiso');
        }
    }

    async showAssignUserModal(positionId = null) {
        // Si no se pasa positionId, usar el currentPositionId
        if (positionId) {
            this.currentPositionId = positionId;
        }

        if (!this.currentPositionId) {
            this.showError('No se ha seleccionado una posición válida');
            return;
        }

        await this.loadAvailableUsers();
        this.setupUserSearch();
        this.assignUserModal.show();
    }

    setupUserSearch() {
        const select = document.getElementById('userSelect');
        let searchTimeout;

        // Agregar un pequeño input de búsqueda (opcional)
        const searchInput = document.createElement('input');
        searchInput.type = 'text';
        searchInput.className = 'form-control form-control-sm mb-2';
        searchInput.placeholder = 'Buscar usuario...';
        searchInput.id = 'userSearch';

        // Insertar antes del select
        select.parentNode.insertBefore(searchInput, select);

        // Manejar búsqueda
        searchInput.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                this.searchUsers(e.target.value);
            }, 300);
        });
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

    cleanupAssignUserModal() {
        // Remover el input de búsqueda si existe
        const searchInput = document.getElementById('userSearch');
        if (searchInput) {
            searchInput.remove();
        }

        // Limpiar el select
        const select = document.getElementById('userSelect');
        if (select) {
            select.innerHTML = '<option value="">Seleccionar usuario...</option>';
        }

        // Limpiar el formulario
        const form = document.getElementById('assignUserForm');
        if (form) {
            form.reset();
        }
    }

    async loadAvailableUsers() {
        const select = document.getElementById('userSelect');

        try {
            select.innerHTML = '<option value="">Cargando usuarios...</option>';

            const response = await fetch(`${this.apiBase}/users?limit=100`);
            const result = await response.json();

            console.log('Users API response:', result); // Debug log

            if (response.ok && result.data) {
                select.innerHTML = '<option value="">Seleccionar usuario...</option>';

                // ⭐ VALIDACIÓN: Verificar que result.data sea un array
                if (Array.isArray(result.data)) {
                    result.data.forEach(user => {
                        const option = document.createElement('option');
                        option.value = user.id;
                        option.textContent = `${user.name}${user.email ? ` (${user.email})` : ''}`;
                        select.appendChild(option);
                    });

                    if (result.data.length === 0) {
                        select.innerHTML = '<option value="">No hay usuarios disponibles</option>';
                    }
                } else {
                    // ⭐ MANEJO: Si data no es array
                    console.error('Expected array but got:', typeof result.data, result.data);
                    throw new Error('La respuesta de usuarios no tiene el formato esperado');
                }
            } else {
                throw new Error(result.error || 'Error al obtener usuarios');
            }

        } catch (error) {
            console.error('Error loading users:', error);
            select.innerHTML = '<option value="">Error al cargar usuarios</option>';
            this.showError('Error al cargar la lista de usuarios');
        }
    }

    async handleAssignUser(e) {
        e.preventDefault();

        if (!this.currentPositionId) return;

        const formData = new FormData(e.target);
        const userId = formData.get('user_id');

        if (!userId) {
            this.showError('Debe seleccionar un usuario');
            return;
        }

        const data = {
            user_id: parseInt(userId),
            start_date: formData.get('start_date') || null,
            notes: formData.get('notes') || null
        };

        try {
            const response = await fetch(`${this.apiBase}/positions/${this.currentPositionId}/assign-user`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (response.ok) {
                this.showSuccess('Usuario asignado correctamente');
                this.assignUserModal.hide();
                e.target.reset();
                await this.loadPositionCurrentUser(this.currentPositionId);
                await this.loadPositions();
            } else {
                this.showError(result.error || 'Error al asignar usuario');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error assigning user:', error);
        }
    }

    async handleRemoveUser() {
        if (!this.currentPositionId) return;

        if (!confirm('¿Estás seguro de remover el usuario de este puesto?')) return;

        try {
            const response = await fetch(`${this.apiBase}/positions/${this.currentPositionId}/remove-user`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });

            const result = await response.json();

            if (response.ok) {
                this.showSuccess('Usuario removido correctamente');
                await this.loadPositionCurrentUser(this.currentPositionId);
                await this.loadPositions();
            } else {
                this.showError(result.error || 'Error al remover usuario');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error removing user:', error);
        }
    }

    async handleRemoveSpecificUser(userId) {
        if (!this.currentPositionId) return;

        if (!confirm('¿Estás seguro de remover este usuario del puesto?')) return;

        try {
            const response = await fetch(`${this.apiBase}/positions/${this.currentPositionId}/remove-user`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId })
            });

            const result = await response.json();

            if (response.ok) {
                this.showSuccess('Usuario removido correctamente');
                await this.loadPositionCurrentUser(this.currentPositionId);
                await this.loadPositions();
            } else {
                this.showError(result.error || 'Error al remover usuario');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error removing specific user:', error);
        }
    }

    // ========================================
    // GESTIÓN DE APLICACIONES Y PERMISOS
    // ========================================

    async showManageAppsModal() {
        if (!this.currentPositionId) {
            this.showError('No hay posición seleccionada');
            return;
        }

        const position = this.positions.find(p => p.id === this.currentPositionId);
        if (position) {
            document.getElementById('modalPositionName').textContent = position.title;
        }

        await this.loadApps();
        this.manageAppsModal.show();

        // Reset panel
        document.getElementById('appAssignmentPanelPosition').style.display = 'none';
        document.querySelectorAll('.app-item-position').forEach(item => {
            item.classList.remove('active');
        });
    }

    async loadApps() {
        try {
            const response = await fetch(`${this.apiBase}/authz/apps`);
            let result = {};

            if (response.status === 204) {
                result = { data: [] };
            } else {
                result = await response.json();
            }

            if (response.ok && result.data) {
                this.apps = result.data;
                this.renderAppsList();
            } else {
                this.apps = [];
                this.renderAppsError();
            }
        } catch (error) {
            console.error('Error loading apps:', error);
            this.apps = [];
            this.renderAppsError();
        }
    }

    renderAppsList() {
        const container = document.getElementById('appsListPosition');
        if (!container) return;

        if (this.apps.length === 0) {
            container.innerHTML = '<div class="text-center py-3 text-muted">No hay aplicaciones disponibles</div>';
            return;
        }

        const appsHtml = this.apps.map(app => `
            <button class="list-group-item list-group-item-action app-item-position d-flex align-items-center"
                    data-app-key="${app.key}" data-app-name="${app.name}">
                <i class="bi bi-app me-2 text-primary"></i>
                <div>
                    <div class="fw-bold">${app.name}</div>
                    <small class="text-muted">${app.key}</small>
                </div>
            </button>
        `).join('');

        container.innerHTML = appsHtml;
    }

    renderAppsError() {
        const container = document.getElementById('appsListPosition');
        if (container) {
            container.innerHTML = '<div class="alert alert-danger">Error al cargar aplicaciones</div>';
        }
    }

    async selectAppForPosition(btn) {
        // Update UI
        document.querySelectorAll('.app-item-position').forEach(item => {
            item.classList.remove('active');
        });
        btn.classList.add('active');

        this.currentAppKey = btn.dataset.appKey;
        const appName = btn.dataset.appName;

        document.getElementById('selectedAppNamePosition').textContent = appName;
        document.getElementById('appAssignmentPanelPosition').style.display = 'block';

        // Load data for this app and position
        await this.loadPositionAssignments();
        await this.loadAppRolesAndPermissions();
    }

    async loadPositionAssignments() {
        if (!this.currentPositionId || !this.currentAppKey) return;

        try {
            // Load position roles for this app
            const rolesResponse = await fetch(`${this.apiBase}/positions/${this.currentPositionId}/apps/${this.currentAppKey}/roles`);
            const rolesResult = rolesResponse.ok ? await rolesResponse.json() : { data: [] };
            const positionRoles = rolesResult.data || [];

            // Load position permissions for this app
            const permsResponse = await fetch(`${this.apiBase}/positions/${this.currentPositionId}/apps/${this.currentAppKey}/perms`);
            const permsResult = permsResponse.ok ? await permsResponse.json() : { data: [] };
            const positionPerms = permsResult.data || [];

            // Calculate effective permissions (would need backend endpoint)
            // For now, we'll combine roles and direct permissions
            const effectivePerms = [...positionPerms]; // Simplified

            this.renderPositionRoles(positionRoles);
            this.renderPositionPermissions(positionPerms);
            this.renderPositionEffectivePermissions(effectivePerms);

        } catch (error) {
            this.showError('Error al cargar las asignaciones del puesto');
            console.error('Error loading position assignments:', error);
        }
    }

    async loadAppRolesAndPermissions() {
        if (!this.currentAppKey) return;

        try {
            // Load available roles for this app
            const rolesResponse = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/roles`);
            if (rolesResponse.ok) {
                const rolesResult = await rolesResponse.json();
                this.populateRoleSelect(rolesResult.data || []);
            }

            // Load available permissions for this app
            const permsResponse = await fetch(`${this.apiBase}/authz/apps/${this.currentAppKey}/perms`);
            if (permsResponse.ok) {
                const permsResult = await permsResponse.json();
                this.permissions = permsResult.data || [];
                this.populatePermissionSelect();
            }
        } catch (error) {
            console.error('Error loading app roles and permissions:', error);
        }
    }

    populateRoleSelect(roles) {
        const select = document.getElementById('roleToAssignPosition');
        if (!select) return;

        // Clear existing options (except first)
        while (select.children.length > 1) {
            select.removeChild(select.lastChild);
        }

        roles.forEach(role => {
            const option = document.createElement('option');
            option.value = role.name;
            option.textContent = role.name;
            select.appendChild(option);
        });
    }

    populatePermissionSelect() {
        const select = document.getElementById('permToAssignPosition');
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

    renderPositionRoles(roles) {
        const container = document.getElementById('positionRolesList');
        if (!container) return;

        if (roles.length === 0) {
            container.innerHTML = '<small class="text-muted">Sin roles asignados al puesto</small>';
            return;
        }

        const badges = roles.map(role =>
            `<span class="badge bg-primary d-flex align-items-center gap-1">
                ${role}
                <button class="btn-close btn-close-white btn-sm remove-role-btn-position" 
                        data-role-name="${role}" style="font-size: 0.6em;"></button>
            </span>`
        ).join('');

        container.innerHTML = badges;
    }

    renderPositionPermissions(permissions) {
        const container = document.getElementById('positionPermsList');
        if (!container) return;

        if (permissions.length === 0) {
            container.innerHTML = '<small class="text-muted">Sin permisos directos asignados al puesto</small>';
            return;
        }

        const badges = permissions.map(perm =>
            `<span class="badge bg-success d-flex align-items-center gap-1">
                ${perm}
                <button class="btn-close btn-close-white btn-sm remove-perm-btn-position" 
                        data-perm-code="${perm}" style="font-size: 0.6em;"></button>
            </span>`
        ).join('');

        container.innerHTML = badges;
    }

    renderPositionEffectivePermissions(permissions) {
        const container = document.getElementById('effectivePermsListPosition');
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

    async assignRoleToPosition(roleName = null) {
        if (!roleName) {
            const select = document.getElementById('roleToAssignPosition');
            roleName = select ? select.value : null;
        }

        if (!roleName) {
            this.showError('Selecciona un rol');
            return;
        }

        try {
            const response = await fetch(`${this.apiBase}/positions/${this.currentPositionId}/apps/${this.currentAppKey}/roles`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role_name: roleName })
            });

            const result = await response.json();

            if (response.ok) {
                this.showSuccess('Rol asignado correctamente');
                const select = document.getElementById('roleToAssignPosition');
                if (select) select.value = '';
                await this.loadPositionApps(this.currentPositionId);
            } else {
                this.showError(result.error || 'Error al asignar el rol');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error assigning role to position:', error);
        }
    }

    async assignPermissionToPosition(permCode = null, allow = true) {
        if (!permCode) {
            const select = document.getElementById('permToAssignPosition');
            permCode = select ? select.value : null;
        }

        if (!permCode) {
            this.showError('Selecciona un permiso');
            return;
        }

        try {
            const response = await fetch(`${this.apiBase}/positions/${this.currentPositionId}/apps/${this.currentAppKey}/perms`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: permCode, allow: allow })
            });

            const result = await response.json();

            if (response.ok) {
                this.showSuccess('Permiso asignado correctamente');
                const select = document.getElementById('permToAssignPosition');
                if (select) select.value = '';
                await this.loadPositionApps(this.currentPositionId);
            } else {
                this.showError(result.error || 'Error al asignar el permiso');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error assigning permission to position:', error);
        }
    }

    async removeRoleFromPosition(roleName) {
        try {
            const response = await fetch(`${this.apiBase}/positions/${this.currentPositionId}/apps/${this.currentAppKey}/roles/${roleName}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                this.showSuccess('Rol removido correctamente');
                await this.loadPositionApps(this.currentPositionId);
            } else {
                const result = await response.json();
                this.showError(result.error || 'Error al remover el rol');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error removing role from position:', error);
        }
    }

    async removePermissionFromPosition(permCode) {
        try {
            const response = await fetch(`${this.apiBase}/positions/${this.currentPositionId}/apps/${this.currentAppKey}/perms/${permCode}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                this.showSuccess('Permiso removido correctamente');
                await this.loadPositionApps(this.currentPositionId);
            } else {
                const result = await response.json();
                this.showError(result.error || 'Error al remover el permiso');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error removing permission from position:', error);
        }
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
    if (typeof DEPARTMENT_ID !== 'undefined') {
        window.departmentManager = new DepartmentDetailManager(DEPARTMENT_ID);
    }
});