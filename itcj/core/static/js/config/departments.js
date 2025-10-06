// itcj/core/static/js/config/departments.js
class DepartmentsManager {
    constructor() {
        this.apiBase = '/api/core/v1';
        this.departments = [];
        this.init();
    }

    async init() {
        this.bindEvents();
        this.initModals();
        await this.loadDepartments();
    }

    bindEvents() {
        const createForm = document.getElementById('createDepartmentForm');
        if (createForm) {
            createForm.addEventListener('submit', (e) => this.handleCreateDepartment(e));
        }
    }

    initModals() {
        this.createModal = new bootstrap.Modal(document.getElementById('createDepartmentModal'));
    }

    async loadDepartments() {
        try {
            const response = await fetch(`${this.apiBase}/departments`);
            const result = await response.json();
            
            if (response.ok && result.data) {
                this.departments = result.data;
                this.renderDepartments();
            }
        } catch (error) {
            console.error('Error loading departments:', error);
            this.showError('Error al cargar los departamentos');
        }
    }

    renderDepartments() {
        const container = document.getElementById('departmentsContainer');
        if (!container) return;

        if (this.departments.length === 0) {
            container.innerHTML = `
                <div class="col-12">
                    <div class="text-center py-5">
                        <i class="bi bi-diagram-3 display-1 text-muted"></i>
                        <h5 class="text-muted mt-3">No hay departamentos registrados</h5>
                        <p class="text-muted">Crea el primer departamento organizacional</p>
                    </div>
                </div>
            `;
            return;
        }

        container.innerHTML = this.departments.map(dept => this.createDepartmentCard(dept)).join('');

        // Bind click events
        document.querySelectorAll('.view-dept-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const deptId = parseInt(btn.dataset.deptId);
                window.location.href = `/itcj/config/departments/${deptId}`;
            });
        });
    }

    createDepartmentCard(dept) {
        const statusBadge = dept.is_active ? 
            '<span class="badge bg-success">Activo</span>' : 
            '<span class="badge bg-secondary">Inactivo</span>';

        return `
            <div class="col-12 col-md-6 col-lg-4" data-dept-id="${dept.id}">
                <div class="card h-100 shadow-sm">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-start mb-3">
                            <div>
                                <h5 class="card-title mb-1">${dept.name}</h5>
                                <small class="text-muted">${dept.code}</small>
                            </div>
                            ${statusBadge}
                        </div>
                        
                        ${dept.description ? `<p class="card-text text-muted small">${dept.description}</p>` : ''}
                        
                        <div class="border-top pt-3 mt-3">
                            <div class="row text-center">
                                <div class="col-6">
                                    <div class="fw-bold text-primary">${dept.positions_count}</div>
                                    <small class="text-muted">Puestos</small>
                                </div>
                                <div class="col-6">
                                    <div class="small">
                                        ${dept.head ? 
                                            `<i class="bi bi-person-badge text-success"></i><br><small>${dept.head.full_name}</small>` :
                                            `<i class="bi bi-x-circle text-muted"></i><br><small>Sin jefe</small>`
                                        }
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="card-footer bg-transparent">
                        <button class="btn btn-sm btn-outline-primary w-100 view-dept-btn" 
                                data-dept-id="${dept.id}">
                            <i class="bi bi-arrow-right-circle me-1"></i>Ver Puestos
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    async handleCreateDepartment(e) {
        e.preventDefault();
        
        const formData = new FormData(e.target);
        const data = {
            code: formData.get('code'),
            name: formData.get('name'),
            description: formData.get('description') || null
        };

        try {
            const response = await fetch(`${this.apiBase}/departments`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (response.ok) {
                this.showSuccess('Departamento creado correctamente');
                this.createModal.hide();
                e.target.reset();
                await this.loadDepartments();
            } else {
                this.showError(result.error || 'Error al crear el departamento');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error creating department:', error);
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
    new DepartmentsManager();
});