// itcj/core/static/js/config/departments.js
class DepartmentsManager {
    constructor() {
        this.apiBase = '/api/core/v1';
        this.currentView = 'subdirections'; // 'subdirections' | 'departments'
        this.selectedSubdirection = null;
        this.subdirections = [];
        this.departments = [];
        
        // Mapeo de iconos por código
        this.ICON_MAP = {
            // Subdirecciones
            'sub_planning': 'bi-diagram-3',
            'sub_academic': 'bi-mortarboard',
            'sub_admin_services': 'bi-gear',
            
            // Departamentos - Planeación
            'planning': 'bi-bar-chart-line',
            'comms_diffusion': 'bi-megaphone',
            'school_services': 'bi-person-badge',
            'extracurricular_act': 'bi-palette',
            'tech_management': 'bi-handshake',
            'info_resources': 'bi-book',
            
            // Departamentos - Académica
            'basic_sciences': 'bi-calculator',
            'mechanical_eng': 'bi-tools',
            'elec_electronics': 'bi-lightning',
            'academic_dev': 'bi-journal-check',
            'sys_computing': 'bi-code-slash',
            'industrial_eng': 'bi-factory',
            'eco_admin_sci': 'bi-cash-coin',
            'prof_studies_div': 'bi-briefcase',
            'postgrad_research': 'bi-flask',
            
            // Departamentos - Servicios Admin
            'human_resources': 'bi-people',
            'financial_resources': 'bi-wallet',
            'mat_services': 'bi-box-seam',
            'equipment_maint': 'bi-wrench',
            'comp_center': 'bi-hdd-stack'
        };
        
        this.init();
    }

    async init() {
        this.bindEvents();
        this.initModals();
        await this.loadSubdirections();
        this.renderSubdirectionsView();
    }

    bindEvents() {
        const createForm = document.getElementById('createDepartmentForm');
        if (createForm) {
            createForm.addEventListener('submit', (e) => this.handleCreateDepartment(e));
        }

        const backBtn = document.getElementById('backBtn');
        if (backBtn) {
            backBtn.addEventListener('click', () => this.goBackToSubdirections());
        }
    }

    initModals() {
        this.createModal = new bootstrap.Modal(document.getElementById('createDepartmentModal'));
        
        // Cargar subdirecciones en el select del modal
        const parentSelect = document.getElementById('deptParent');
        if (parentSelect) {
            this.loadParentOptions();
        }
    }

    async loadParentOptions() {
        try {
            const response = await fetch(`${this.apiBase}/departments/subdirections`);
            const result = await response.json();
            
            if (response.ok && result.data) {
                const select = document.getElementById('deptParent');
                const currentOptions = select.innerHTML;
                
                result.data.forEach(sub => {
                    const option = document.createElement('option');
                    option.value = sub.id;
                    option.textContent = sub.name;
                    select.appendChild(option);
                });
            }
        } catch (error) {
            console.error('Error loading parent options:', error);
        }
    }

    async loadSubdirections() {
        try {
            const response = await fetch(`${this.apiBase}/departments/subdirections`);
            const result = await response.json();
            
            if (response.ok && result.data) {
                this.subdirections = result.data;
            }
        } catch (error) {
            console.error('Error loading subdirections:', error);
            this.showError('Error al cargar las subdirecciones');
        }
    }

    async loadDepartmentsByParent(parentId) {
        try {
            const response = await fetch(`${this.apiBase}/departments/by-parent?parent_id=${parentId}`);
            const result = await response.json();
            
            if (response.ok && result.data) {
                this.departments = result.data;
            }
        } catch (error) {
            console.error('Error loading departments:', error);
            this.showError('Error al cargar los departamentos');
        }
    }

    renderSubdirectionsView() {
        this.currentView = 'subdirections';
        const container = document.getElementById('mainContainer');
        
        // Update header
        document.getElementById('currentBreadcrumb').textContent = 'Subdirecciones';
        document.getElementById('pageTitle').innerHTML = '<i class="bi bi-diagram-3 me-2"></i>Subdirecciones';
        document.getElementById('pageSubtitle').textContent = 'Selecciona una subdirección para ver sus departamentos';
        document.getElementById('backBtn').style.display = 'none';

        if (this.subdirections.length === 0) {
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="bi bi-diagram-3 display-1 text-muted"></i>
                    <h5 class="text-muted mt-3">No hay subdirecciones registradas</h5>
                    <p class="text-muted">Crea la primera subdirección organizacional</p>
                </div>
            `;
            return;
        }

        // Renderizar subdirecciones centradas
        container.innerHTML = `
            <div class="row justify-content-center g-4">
                ${this.subdirections.map(sub => this.createSubdirectionCard(sub)).join('')}
            </div>
        `;

        // Bind click events
        document.querySelectorAll('.subdirection-card').forEach(card => {
            card.addEventListener('click', async (e) => {
                const subdirId = parseInt(card.dataset.subdirId);
                await this.selectSubdirection(subdirId, card);
            });
        });
    }

    createSubdirectionCard(subdirection) {
        const icon = this.getIcon(subdirection.code, subdirection.icon_class);
        
        return `
            <div class="col-12 col-md-6 col-lg-4">
                <div class="card subdirection-card h-100 shadow-sm fade-in" data-subdir-id="${subdirection.id}">
                    <div class="card-body text-center p-5">
                        <div class="subdirection-icon mb-4">
                            <i class="${icon}"></i>
                        </div>
                        <h3 class="card-title mb-3">${subdirection.name}</h3>
                        ${subdirection.description ? 
                            `<p class="card-text text-muted">${subdirection.description}</p>` : 
                            ''
                        }
                        <div class="mt-4">
                            <span class="badge bg-primary fs-6">
                                <i class="bi bi-building me-1"></i>${subdirection.children_count} Departamentos
                            </span>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    async selectSubdirection(subdirId, cardElement) {
        // Animación de expansión
        cardElement.classList.add('expand-out');
        
        // Esperar a que termine la animación
        await new Promise(resolve => setTimeout(resolve, 300));
        
        // Cargar departamentos
        const subdirection = this.subdirections.find(s => s.id === subdirId);
        if (!subdirection) return;
        
        this.selectedSubdirection = subdirection;
        await this.loadDepartmentsByParent(subdirId);
        this.renderDepartmentsView();
    }

    renderDepartmentsView() {
        this.currentView = 'departments';
        const container = document.getElementById('mainContainer');
        const sub = this.selectedSubdirection;
        
        // Update header
        document.getElementById('currentBreadcrumb').textContent = sub.name;
        document.getElementById('pageTitle').innerHTML = `
            <i class="${this.getIcon(sub.code, sub.icon_class)} me-2"></i>${sub.name}
        `;
        document.getElementById('pageSubtitle').textContent = sub.description || 'Departamentos de esta subdirección';
        document.getElementById('backBtn').style.display = 'inline-block';

        if (this.departments.length === 0) {
            container.innerHTML = `
                <div class="text-center py-5 fade-in">
                    <i class="bi bi-building display-1 text-muted"></i>
                    <h5 class="text-muted mt-3">No hay departamentos en esta subdirección</h5>
                    <p class="text-muted">Crea el primer departamento</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="row g-4">
                ${this.departments.map(dept => this.createDepartmentCard(dept)).join('')}
            </div>
        `;

        // Bind click events
        document.querySelectorAll('.view-dept-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const deptId = parseInt(btn.dataset.deptId);
                window.location.href = `/itcj/config/departments/${deptId}`;
            });
        });
    }

    createDepartmentCard(dept) {
        const icon = this.getIcon(dept.code, dept.icon_class);
        const statusBadge = dept.is_active ? 
            '<span class="badge bg-success">Activo</span>' : 
            '<span class="badge bg-secondary">Inactivo</span>';

        return `
            <div class="col-12 col-md-6 col-lg-4 fade-in" data-dept-id="${dept.id}">
                <div class="card department-card h-100 shadow-sm">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-start mb-3">
                            <div class="d-flex align-items-center">
                                <div class="department-icon text-primary me-3">
                                    <i class="bi ${icon}"></i>
                                </div>
                                <div>
                                    <h5 class="card-title mb-1">${dept.name}</h5>
                                    <small class="text-muted">${dept.code}</small>
                                </div>
                            </div>
                            ${statusBadge}
                        </div>
                        
                        ${dept.description ? 
                            `<p class="card-text text-muted small">${dept.description}</p>` : 
                            ''
                        }
                        
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

    async goBackToSubdirections() {
        this.selectedSubdirection = null;
        this.departments = [];
        await this.loadSubdirections();
        this.renderSubdirectionsView();
    }

    getIcon(code, iconClass) {
        // Prioridad: iconClass en BD > mapeo por código > icono por defecto
        if (iconClass) return iconClass;
        if (this.ICON_MAP[code]) return this.ICON_MAP[code];
        return 'bi-building'; // Icono por defecto
    }

    async handleCreateDepartment(e) {
        e.preventDefault();
        
        const formData = new FormData(e.target);
        const data = {
            code: formData.get('code'),
            name: formData.get('name'),
            description: formData.get('description') || null,
            parent_id: formData.get('parent_id') || null,
            icon_class: formData.get('icon_class') || null
        };

        try {
            const response = await fetch(`${this.apiBase}/departments`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            });

            const result = await response.json();
            console.log(result);
            if (response.ok) {
                this.showSuccess('Departamento creado correctamente');
                this.createModal.hide();
                e.target.reset();
                
                // Recargar vista actual
                if (this.currentView === 'subdirections') {
                    await this.loadSubdirections();
                    this.renderSubdirectionsView();
                } else if (this.selectedSubdirection) {
                    await this.loadDepartmentsByParent(this.selectedSubdirection.id);
                    this.renderDepartmentsView();
                }
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