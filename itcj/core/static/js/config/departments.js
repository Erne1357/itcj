// itcj/core/static/js/config/departments.js
class DepartmentsManager {
    constructor() {
        this.apiBase = '/api/core/v1';
        this.currentView = 'top-level'; // 'top-level' | 'subdirections' | 'departments'
        this.selectedTopLevel = null; // Dirección o Sindicato
        this.selectedSubdirection = null;
        this.topLevelEntities = []; // Dirección y Sindicato
        this.subdirections = [];
        this.departments = [];
        this.navigationStack = [];
        
        // Mapeo de iconos por código
        this.ICON_MAP = {
            // Dirección y Sindicato
            'direction': 'bi-briefcase',
            'union_delegation': 'bi-people-fill',
            
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
            'metal_mechanics': 'bi-tools',
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
        await this.loadTopLevelEntities();
        this.renderTopLevelView();
    }

    bindEvents() {
        const createForm = document.getElementById('createDepartmentForm');
        if (createForm) {
            createForm.addEventListener('submit', (e) => this.handleCreateDepartment(e));
        }

        const backBtn = document.getElementById('backBtn');
        if (backBtn) {
            backBtn.addEventListener('click', () => this.goBack());
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
            const response = await fetch(`${this.apiBase}/departments/parent-options`);
            const result = await response.json();
            
            if (response.ok && result.data) {
                const select = document.getElementById('deptParent');
                // Preservar la primera opción
                const firstOption = select.querySelector('option[value=""]');
                select.innerHTML = '';
                if (firstOption) {
                    select.appendChild(firstOption);
                }
                
                result.data.forEach(dept => {
                    const option = document.createElement('option');
                    option.value = dept.id;
                    const level = dept.parent_id ? '├─ ' : '📁 ';
                    option.textContent = level + dept.name;
                    select.appendChild(option);
                });
            }
        } catch (error) {
            console.error('Error loading parent options:', error);
        }
    }

    async loadTopLevelEntities() {
        try {
            // Cargar dirección
            const dirResponse = await fetch(`${this.apiBase}/departments/direction`);
            const dirResult = await dirResponse.json();
            
            // Cargar sindicato
            const unionResponse = await fetch(`${this.apiBase}/departments/union-delegation`);
            const unionResult = await unionResponse.json();
            
            this.topLevelEntities = [];
            
            if (dirResponse.ok && dirResult.data) {
                this.topLevelEntities.push(dirResult.data);
            }
            
            if (unionResponse.ok && unionResult.data) {
                this.topLevelEntities.push(unionResult.data);
            }
        } catch (error) {
            console.error('Error loading top level entities:', error);
            this.showError('Error al cargar la estructura organizacional');
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

    renderTopLevelView() {
        this.currentView = 'top-level';
        const container = document.getElementById('mainContainer');
        
        // Update header
        document.getElementById('currentBreadcrumb').textContent = 'Estructura Organizacional';
        document.getElementById('pageTitle').innerHTML = '<i class="bi bi-building me-2"></i>Estructura Organizacional';
        document.getElementById('pageSubtitle').textContent = 'Dirección y Delegación Sindical del instituto';
        document.getElementById('backBtn').style.display = 'none';
        this.navigationStack = [];

        if (this.topLevelEntities.length === 0) {
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="bi bi-building display-1 text-muted"></i>
                    <h5 class="text-muted mt-3">No hay estructura organizacional registrada</h5>
                    <p class="text-muted">Crea la dirección o delegación sindical</p>
                </div>
            `;
            return;
        }

        // Renderizar entidades de nivel superior lado a lado
        container.innerHTML = `
            <div class="row justify-content-center g-4">
                ${this.topLevelEntities.map(entity => `
                    <div class="col-12 col-lg-6">
                        ${this.createTopLevelCard(entity)}
                    </div>
                `).join('')}
            </div>
        `;

        // Bind click events
        document.querySelectorAll('.top-level-card').forEach(card => {
            card.addEventListener('click', async (e) => {
                if (e.target.closest('.admin-btn')) {
                    e.stopPropagation();
                    return;
                }
                const entityId = parseInt(card.dataset.entityId);
                await this.selectTopLevel(entityId);
            });
        });

        // Bind admin button events
        document.querySelectorAll('.admin-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const deptId = parseInt(btn.dataset.deptId);
                window.location.href = `/itcj/config/departments/${deptId}`;
            });
        });
    }

    renderSubdirectionsView() {
        this.currentView = 'subdirections';
        const container = document.getElementById('mainContainer');
        
        // Update header
        document.getElementById('currentBreadcrumb').textContent = this.selectedTopLevel.name;
        document.getElementById('pageTitle').innerHTML = `
            <i class="${this.getIcon(this.selectedTopLevel.code, this.selectedTopLevel.icon_class)} me-2"></i>${this.selectedTopLevel.name}
        `;
        document.getElementById('pageSubtitle').textContent = 'Selecciona una subdirección para ver sus departamentos';
        document.getElementById('backBtn').style.display = 'inline-block';

        if (this.subdirections.length === 0) {
            container.innerHTML = `
                <div class="text-center py-5 fade-in">
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
                if (e.target.closest('.admin-btn')) {
                    e.stopPropagation();
                    return;
                }
                const subdirId = parseInt(card.dataset.subdirId);
                await this.selectSubdirection(subdirId, card);
            });
        });

        // Bind admin button events
        document.querySelectorAll('.admin-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const deptId = parseInt(btn.dataset.deptId);
                window.location.href = `/itcj/config/departments/${deptId}`;
            });
        });
    }

    createTopLevelCard(entity) {
        const icon = this.getIcon(entity.code, entity.icon_class);
        const isDirection = entity.code === 'direction';
        const childrenLabel = isDirection ? 'Subdirecciones' : 'Departamentos';
        const childrenIcon = isDirection ? 'bi-diagram-3' : 'bi-building';
        
        return `
            <div class="card top-level-card shadow-lg border-0 fade-in" data-entity-id="${entity.id}">
                <div class="card-body text-center p-5 position-relative">
                    <!-- Botón de administración discreto -->
                    <button class="btn btn-sm btn-outline-secondary admin-btn position-absolute top-0 end-0 m-3" 
                            data-dept-id="${entity.id}" title="Administrar ${entity.name}">
                        <i class="bi bi-gear"></i>
                    </button>
                    
                    <div class="top-level-icon mb-4">
                        <i class="${icon}" style="font-size: 4rem; color: #0d6efd;"></i>
                    </div>
                    <h2 class="card-title mb-3">${entity.name}</h2>
                    ${entity.description ? 
                        `<p class="card-text text-muted mb-4">${entity.description}</p>` : 
                        ''
                    }
                    <div class="mt-4">
                        <span class="badge bg-primary fs-5">
                            <i class="${childrenIcon} me-1"></i>${entity.children_count} ${childrenLabel}
                        </span>
                    </div>
                    <div class="mt-4">
                        <p class="text-muted small">Haz clic para explorar</p>
                    </div>
                </div>
            </div>
        `;
    }

    createSubdirectionCard(subdirection) {
        const icon = this.getIcon(subdirection.code, subdirection.icon_class);
        
        return `
            <div class="col-12 col-md-6 col-lg-4">
                <div class="card subdirection-card h-100 shadow-sm fade-in position-relative" data-subdir-id="${subdirection.id}">
                    <!-- Botón de administración discreto -->
                    <button class="btn btn-sm btn-outline-secondary admin-btn position-absolute top-0 end-0 m-2" 
                            data-dept-id="${subdirection.id}" title="Administrar subdirección">
                        <i class="bi bi-gear" style="font-size: 0.8rem;"></i>
                    </button>
                    
                    <div class="card-body text-center p-4">
                        <div class="subdirection-icon mb-3">
                            <i class="${icon}" style="font-size: 2.5rem; color: #0d6efd;"></i>
                        </div>
                        <h4 class="card-title mb-3">${subdirection.name}</h4>
                        ${subdirection.description ? 
                            `<p class="card-text text-muted small">${subdirection.description}</p>` : 
                            ''
                        }
                        <div class="mt-3">
                            <span class="badge bg-primary">
                                <i class="bi bi-building me-1"></i>${subdirection.children_count} Departamentos
                            </span>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    async selectTopLevel(entityId) {
        const entity = this.topLevelEntities.find(e => e.id === entityId);
        if (!entity) return;
        
        // Si no tiene hijos, ir directo al detalle
        if (!entity.children_count || entity.children_count === 0) {
            window.location.href = `/itcj/config/departments/${entityId}`;
            return;
        }
        
        // Animación de expansión
        const card = document.querySelector(`.top-level-card[data-entity-id="${entityId}"]`);
        if (card) {
            card.classList.add('expand-out');
            await new Promise(resolve => setTimeout(resolve, 300));
        }
        
        this.navigationStack.push({view: 'top-level'});
        this.selectedTopLevel = entity;
        
        // Si es dirección, cargar subdirecciones
        if (entity.code === 'direction') {
            await this.loadSubdirections();
            this.renderSubdirectionsView();
        } else {
            // Si es sindicato u otra entidad, cargar departamentos directamente
            await this.loadDepartmentsByParent(entityId);
            this.renderDepartmentsView();
        }
    }

    async selectSubdirection(subdirId, cardElement) {
        // Animación de expansión
        if (cardElement) {
            cardElement.classList.add('expand-out');
            await new Promise(resolve => setTimeout(resolve, 300));
        }
        
        // Cargar departamentos
        const subdirection = this.subdirections.find(s => s.id === subdirId);
        if (!subdirection) return;
        
        this.navigationStack.push({view: 'subdirections'});
        this.selectedSubdirection = subdirection;
        await this.loadDepartmentsByParent(subdirId);
        this.renderDepartmentsView();
    }

    renderDepartmentsView() {
        this.currentView = 'departments';
        const container = document.getElementById('mainContainer');
        
        // Determinar si es subdirección o entidad de nivel superior (sindicato)
        const parent = this.selectedSubdirection || this.selectedTopLevel;
        
        // Update header
        document.getElementById('currentBreadcrumb').textContent = parent.name;
        document.getElementById('pageTitle').innerHTML = `
            <i class="${this.getIcon(parent.code, parent.icon_class)} me-2"></i>${parent.name}
        `;
        document.getElementById('pageSubtitle').textContent = parent.description || 'Departamentos';
        document.getElementById('backBtn').style.display = 'inline-block';

        if (this.departments.length === 0) {
            const parentType = this.selectedSubdirection ? 'subdirección' : 'dependencia';
            container.innerHTML = `
                <div class="text-center py-5 fade-in">
                    <i class="bi bi-building display-1 text-muted"></i>
                    <h5 class="text-muted mt-3">No hay departamentos en esta ${parentType}</h5>
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

    async goBack() {
        const previousView = this.navigationStack.pop();
        
        if (!previousView) {
            // Si no hay vista anterior, ir a nivel superior
            await this.goToTopLevel();
            return;
        }
        
        switch (previousView.view) {
            case 'top-level':
                await this.goToTopLevel();
                break;
            case 'subdirections':
                await this.goToSubdirections();
                break;
            default:
                await this.goToTopLevel();
        }
    }

    async goToTopLevel() {
        this.selectedTopLevel = null;
        this.selectedSubdirection = null;
        this.departments = [];
        this.navigationStack = [];
        await this.loadTopLevelEntities();
        this.renderTopLevelView();
    }

    async goToSubdirections() {
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
            if (response.ok) {
                this.showSuccess('Departamento creado correctamente');
                this.createModal.hide();
                e.target.reset();
                
                // Recargar vista actual
                switch (this.currentView) {
                    case 'top-level':
                        await this.loadTopLevelEntities();
                        this.renderTopLevelView();
                        break;
                    case 'subdirections':
                        await this.loadSubdirections();
                        this.renderSubdirectionsView();
                        break;
                    case 'departments':
                        if (this.selectedSubdirection) {
                            await this.loadDepartmentsByParent(this.selectedSubdirection.id);
                            this.renderDepartmentsView();
                        } else if (this.selectedTopLevel) {
                            await this.loadDepartmentsByParent(this.selectedTopLevel.id);
                            this.renderDepartmentsView();
                        }
                        break;
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