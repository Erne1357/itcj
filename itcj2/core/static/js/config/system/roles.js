// roles.js - Gestión de roles globales
class RolesManager {
    constructor() {
        this.apiBase = '/api/core/v1';
        this.init();
    }

    init() {
        this.bindEvents();
        this.initModals();
    }

    bindEvents() {
        // Form submissions
        const createForm = document.getElementById('createRoleForm');
        
        if (createForm) {
            createForm.addEventListener('submit', (e) => this.handleCreateRole(e));
        }

        // Delete buttons
        document.addEventListener('click', (e) => {
            if (e.target.closest('.delete-role-btn')) {
                const btn = e.target.closest('.delete-role-btn');
                this.showDeleteModal(btn);
            }
        });

        // Confirm delete
        const confirmDeleteBtn = document.getElementById('confirmDeleteRole');
        if (confirmDeleteBtn) {
            confirmDeleteBtn.addEventListener('click', () => this.handleDeleteRole());
        }

        // Input validation for role name
        const roleNameInput = document.getElementById('roleName');
        if (roleNameInput) {
            roleNameInput.addEventListener('input', this.validateRoleName);
        }
    }

    initModals() {
        this.createModal = new bootstrap.Modal(document.getElementById('createRoleModal'));
        this.deleteModal = new bootstrap.Modal(document.getElementById('deleteRoleModal'));
    }

    validateRoleName(e) {
        const value = e.target.value;
        const pattern = /^[a-z0-9_]*$/;
        
        if (!pattern.test(value)) {
            e.target.classList.add('is-invalid');
            e.target.setCustomValidity('Solo se permiten letras minúsculas, números y guiones bajos');
        } else {
            e.target.classList.remove('is-invalid');
            e.target.setCustomValidity('');
        }
    }

    async handleCreateRole(e) {
        e.preventDefault();
        
        const formData = new FormData(e.target);
        const data = {
            name: formData.get('name')
        };

        try {
            const response = await fetch(`${this.apiBase}/authz/roles`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (response.ok) {
                this.showSuccess('Rol creado correctamente');
                this.createModal.hide();
                this.addRoleToContainer(result.data);
                e.target.reset();
            } else {
                this.showError(result.error || 'Error al crear el rol');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error creating role:', error);
        }
    }

    showDeleteModal(btn) {
        const roleName = btn.dataset.roleName;

        this.deleteRoleName = roleName;
        document.getElementById('deleteRoleName').textContent = roleName;
        this.deleteModal.show();
    }

    async handleDeleteRole() {
        try {
            const response = await fetch(`${this.apiBase}/authz/roles/${this.deleteRoleName}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                this.showSuccess('Rol eliminado correctamente');
                this.deleteModal.hide();
                this.removeRoleFromContainer(this.deleteRoleName);
            } else {
                const result = await response.json();
                this.showError(result.error || 'Error al eliminar el rol');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error deleting role:', error);
        }
    }

    addRoleToContainer(roleData) {
        const container = document.getElementById('rolesContainer');
        const roleCard = this.createRoleCard(roleData);
        container.appendChild(roleCard);
        
        // Remove empty state if present
        const emptyState = document.getElementById('emptyState');
        if (emptyState) {
            emptyState.remove();
        }
    }

    removeRoleFromContainer(roleName) {
        const roleCard = document.querySelector(`[data-role-name="${roleName}"]`);
        if (roleCard) {
            roleCard.remove();
        }
        
        // Check if container is empty
        const container = document.getElementById('rolesContainer');
        if (container.children.length === 0) {
            this.showEmptyState();
        }
    }

    createRoleCard(roleData) {
        const colDiv = document.createElement('div');
        colDiv.className = 'col-12 col-md-6 col-lg-4';
        colDiv.setAttribute('data-role-name', roleData.name);
        
        colDiv.innerHTML = `
            <div class="card h-100 shadow-sm">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start mb-3">
                        <div class="d-flex align-items-center">
                            <div class="bg-success bg-opacity-10 rounded p-2 me-3">
                                <i class="bi bi-person-badge text-success"></i>
                            </div>
                            <div>
                                <h5 class="card-title mb-1">${roleData.name}</h5>
                                <small class="text-muted">Rol global</small>
                            </div>
                        </div>
                        <div class="dropdown">
                            <button class="btn btn-sm btn-outline-secondary" 
                                    data-bs-toggle="dropdown" aria-expanded="false">
                                <i class="bi bi-three-dots-vertical"></i>
                            </button>
                            <ul class="dropdown-menu">
                                <li>
                                    <button class="dropdown-item text-danger delete-role-btn" 
                                            data-role-name="${roleData.name}">
                                        <i class="bi bi-trash me-2"></i>Eliminar Rol
                                    </button>
                                </li>
                            </ul>
                        </div>
                    </div>
                    
                    <div class="d-flex justify-content-between align-items-center">
                        <small class="text-muted">
                            <i class="bi bi-people me-1"></i>
                            0 usuarios asignados
                        </small>
                    </div>
                </div>
            </div>
        `;
        
        return colDiv;
    }

    showEmptyState() {
        const container = document.getElementById('rolesContainer');
        const emptyDiv = document.createElement('div');
        emptyDiv.id = 'emptyState';
        emptyDiv.className = 'text-center py-5';
        emptyDiv.innerHTML = `
            <i class="bi bi-people display-1 text-muted"></i>
            <h5 class="text-muted mt-3">No hay roles registrados</h5>
            <p class="text-muted">Crea tu primer rol para comenzar</p>
        `;
        
        container.parentNode.appendChild(emptyDiv);
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
    new RolesManager();
});