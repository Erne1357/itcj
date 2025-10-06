// itcj/core/static/js/config/department_detail.js
class DepartmentDetailManager {
    constructor(departmentId) {
        this.apiBase = '/api/core/v1';
        this.departmentId = departmentId;
        this.currentPositionId = null;
        this.positions = [];
        this.department = null;
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

        document.getElementById('assignUserBtn')?.addEventListener('click', () => this.showAssignUserModal());
        document.getElementById('removeUserBtn')?.addEventListener('click', () => this.handleRemoveUser());
    }

    initModals() {
        this.createModal = new bootstrap.Modal(document.getElementById('createPositionModal'));
        this.manageModal = new bootstrap.Modal(document.getElementById('managePositionModal'));
        this.assignUserModal = new bootstrap.Modal(document.getElementById('assignUserModal'));
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

        document.querySelectorAll('.manage-position-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const positionId = parseInt(btn.dataset.positionId);
                this.showManageModal(positionId);
            });
        });
    }

    // itcj/core/static/js/config/department_detail.js (continuación)

    createPositionCard(position) {
        const currentUser = position.current_user;
        const statusBadge = position.is_active ?
            '<span class="badge bg-success">Activo</span>' :
            '<span class="badge bg-secondary">Inactivo</span>';

        return `
            <div class="col-12 col-md-6 col-lg-4" data-position-id="${position.id}">
                <div class="card h-100 shadow-sm">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-start mb-3">
                            <div>
                                <h5 class="card-title mb-1">${position.title}</h5>
                                <small class="text-muted">${position.code}</small>
                            </div>
                            ${statusBadge}
                        </div>
                        
                        ${position.description ? `<p class="card-text text-muted small">${position.description}</p>` : ''}
                        
                        <div class="border-top pt-3 mt-3">
                            <h6 class="small text-muted mb-2">Usuario Asignado:</h6>
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
                        <button class="btn btn-sm btn-outline-primary w-100 manage-position-btn" 
                                data-position-id="${position.id}">
                            <i class="bi bi-gear me-1"></i>Gestionar
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    async handleCreatePosition(e) {
        e.preventDefault();

        const formData = new FormData(e.target);
        const data = {
            code: formData.get('code'),
            title: formData.get('title'),
            department_id: this.departmentId, // Importante: asociar al departamento actual
            description: formData.get('description') || null
        };

        try {
            const response = await fetch(`${this.apiBase}/positions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });

            const result = await response.json();

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

    showAssignUserModal() {
        // TODO: Cargar lista de usuarios
        this.assignUserModal.show();
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
        new DepartmentDetailManager(DEPARTMENT_ID);
    }
});