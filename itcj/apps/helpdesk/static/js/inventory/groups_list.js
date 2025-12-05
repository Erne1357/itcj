/**
 * Lista de Grupos de Equipos
 * Gestión de salones, laboratorios y agrupaciones
 */

let allGroups = [];
let allDepartments = [];
let allCategories = [];
let currentFilters = {};

// Inicializar department_id correctamente
currentFilters.department_id = (typeof departmentId !== 'undefined' && departmentId !== null) ? departmentId : null;


document.addEventListener('DOMContentLoaded', function () {
    loadDepartments();
    loadCategories();
    loadGroups();

    // Event listeners
    document.getElementById('search-input').addEventListener('input', debounce(applyFilters, 500));
    document.getElementById('type-filter').addEventListener('change', applyFilters);

    const deptFilter = document.getElementById('department-filter');
    if (deptFilter) {
        deptFilter.addEventListener('change', applyFilters);
    }

    // Form submit
    document.getElementById('group-form').addEventListener('submit', handleSubmit);
});

// ==================== CARGAR DATOS ====================
async function loadGroups() {
    showLoading();

    try {
        const params = new URLSearchParams();

        if (currentFilters.search) params.append('search', currentFilters.search);
        if (currentFilters.type) params.append('type', currentFilters.type);
        if (currentFilters.department_id) params.append('department_id', currentFilters.department_id);
        
        let response;
        if (typeof canViewAll !== 'undefined' && canViewAll === true) {
            response  = await fetch(`/api/help-desk/v1/inventory/groups/?${params}`, {
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                }
            });
        } else {
            response  = await fetch(`/api/help-desk/v1/inventory/groups/department/${currentFilters.department_id}`, {
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                }
            });
        }
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || errorData.message || 'Error al cargar grupos');
        }

        const result = await response.json();
        allGroups = result.data;

        renderGroups(allGroups);
        hideLoading();

    } catch (error) {
        console.error('Error:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`No se pudieron cargar los grupos: ${errorMessage}`);
        hideLoading();
    }
}

async function loadDepartments() {
    try {
        const response = await fetch('/api/core/v1/departments?active=true', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || errorData.message || 'Error al cargar departamentos');
        }

        const result = await response.json();
        allDepartments = result.data;

        // Llenar filtro
        const deptFilter = document.getElementById('department-filter');
        if (deptFilter) {
            deptFilter.innerHTML = '<option value="">Todos los departamentos</option>';
            allDepartments.forEach(dept => {
                const option = document.createElement('option');
                option.value = dept.id;
                option.textContent = dept.name;
                deptFilter.appendChild(option);
            });
        }

        // Llenar select del modal
        const modalSelect = document.getElementById('group-department');
        modalSelect.innerHTML = '<option value="">Seleccionar...</option>';
        allDepartments.forEach(dept => {
            const option = document.createElement('option');
            option.value = dept.id;
            option.textContent = dept.name;
            modalSelect.appendChild(option);
        });

    } catch (error) {
        console.error('Error cargando departamentos:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`No se pudieron cargar los departamentos: ${errorMessage}`);
    }
}

async function loadCategories() {
    try {
        const response = await fetch('/api/help-desk/v1/inventory/categories?active=true', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || errorData.message || 'Error al cargar categorías');
        }

        const result = await response.json();
        allCategories = result.data;

    } catch (error) {
        console.error('Error cargando categorías:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`No se pudieron cargar las categorías: ${errorMessage}`);
    }
}

// ==================== RENDERIZADO ====================
function renderGroups(groups) {
    const container = document.getElementById('groups-container');

    if (groups.length === 0) {
        container.style.display = 'none';
        document.getElementById('empty-state').style.display = 'block';
        return;
    }

    container.style.display = 'flex';
    document.getElementById('empty-state').style.display = 'none';

    container.innerHTML = groups.map(group => {
        const typeInfo = getGroupTypeInfo(group.type);
        const occupancy = calculateOccupancy(group);
        const occupancyClass = getOccupancyClass(occupancy.percentage);

        return `
            <div class="col-md-6 col-lg-4 mb-4">
                <div class="card shadow group-card h-100" onclick="goToGroupDetail(${group.id})">
                    <div class="card-body">
                        <!-- Header -->
                        <div class="d-flex justify-content-between align-items-start mb-3">
                            <div>
                                <h5 class="card-title mb-1">
                                    <i class="${typeInfo.icon} text-primary mr-2"></i>
                                    ${group.name}
                                </h5>
                                <small class="text-muted">
                                    <i class="fas fa-building mr-1"></i>
                                    ${group.department?.name || 'Sin departamento'}
                                </small>
                            </div>
                            <span class="badge bg-${typeInfo.color} text-white">
                                ${typeInfo.label}
                            </span>
                        </div>

                        <!-- Descripción -->
                        ${group.description ? `
                            <p class="card-text text-muted small mb-3">
                                ${group.description}
                            </p>
                        ` : ''}

                        <!-- Ubicación -->
                        ${group.building || group.floor ? `
                            <div class="mb-3">
                                <small class="text-muted">
                                    <i class="fas fa-map-marker-alt mr-1"></i>
                                    ${group.building ? `Edificio ${group.building}` : ''}
                                    ${group.floor ? ` - Piso ${group.floor}` : ''}
                                </small>
                            </div>
                        ` : ''}

                        <!-- Estadísticas -->
                        <div class="group-stats">
                            <div class="group-stat">
                                <div class="group-stat-value">${occupancy.current}</div>
                                <div class="group-stat-label">Equipos</div>
                            </div>
                            <div class="group-stat">
                                <div class="group-stat-value">${occupancy.total}</div>
                                <div class="group-stat-label">Capacidad</div>
                            </div>
                            <div class="group-stat">
                                <div class="group-stat-value ${occupancyClass}">
                                    ${occupancy.percentage}%
                                </div>
                                <div class="group-stat-label">Ocupación</div>
                            </div>
                        </div>

                        <!-- Barra de ocupación -->
                        <div class="progress" style="height: 6px;">
                            <div 
                                class="progress-bar bg-${occupancyClass === 'text-success' ? 'success' : occupancyClass === 'text-warning' ? 'warning' : 'danger'}" 
                                style="width: ${occupancy.percentage}%"
                            ></div>
                        </div>

                        <!-- Capacidades por categoría -->
                        ${group.capacities && group.capacities.length > 0 ? `
                            <div class="mt-3">
                                <small class="text-muted d-block mb-2">Capacidades:</small>
                                <div class="d-flex flex-wrap gap-1">
                                    ${group.capacities.slice(0, 3).map(cap => {
            const cat = allCategories.find(c => c.id === cap.category_id);
            return `
                                            <span class="capacity-badge badge bg-light text-dark">
                                                <i class="${cat?.icon || 'fas fa-box'} mr-1"></i>
                                                ${cat?.name || 'N/A'}: ${cap.current_count}/${cap.max_capacity}
                                            </span>
                                        `;
        }).join('')}
                                    ${group.capacities.length > 3 ? `
                                        <span class="capacity-badge badge bg-secondary text-white">
                                            +${group.capacities.length - 3} más
                                        </span>
                                    ` : ''}
                                </div>
                            </div>
                        ` : ''}
                    </div>

                    <!-- Footer con acciones -->
                    <div class="card-footer bg-transparent border-top-0">
                        <div class="d-flex justify-content-between align-items-center">
                            <small class="text-muted">
                                <i class="fas fa-calendar mr-1"></i>
                                ${formatDate(group.created_at)}
                            </small>
                            <div class="btn-group btn-group-sm" onclick="event.stopPropagation()">
                                <button 
                                    class="btn btn-sm btn-outline-primary" 
                                    onclick="goToGroupDetail(${group.id})"
                                    title="Ver detalle"
                                >
                                    <i class="fas fa-eye"></i>
                                </button>
                                <button 
                                    class="btn btn-sm btn-outline-secondary" 
                                    onclick="openEditGroupModal(${group.id})"
                                    title="Editar"
                                >
                                    <i class="fas fa-edit"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// ==================== FILTROS ====================
function applyFilters() {
    currentFilters = {
        search: document.getElementById('search-input').value.trim() || null,
        type: document.getElementById('type-filter').value || null
    };

    const deptFilter = document.getElementById('department-filter');
    if (deptFilter) {
        currentFilters.department_id = deptFilter.value || null;
    }

    loadGroups();
}

// ==================== MODAL CREATE/EDIT ====================
function openCreateGroupModal() {
    resetGroupForm();
    document.getElementById('modal-title').textContent = 'Crear Grupo';
    document.getElementById('group-id').value = '';

    // Renderizar capacidades vacías
    renderCapacitiesForm();

    $('#groupModal').modal('show');
}

async function openEditGroupModal(groupId) {
    try {
        const response = await fetch(`/api/help-desk/v1/inventory/groups/${groupId}`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || errorData.message || 'Error al cargar grupo');
        }

        const result = await response.json();
        const group = result.data;

        // Llenar formulario
        document.getElementById('modal-title').textContent = 'Editar Grupo';
        document.getElementById('group-id').value = group.id;
        document.getElementById('group-name').value = group.name;
        document.getElementById('group-type').value = group.type;
        document.getElementById('group-department').value = group.department_id;
        document.getElementById('group-description').value = group.description || '';
        document.getElementById('group-building').value = group.building || '';
        document.getElementById('group-floor').value = group.floor || '';
        document.getElementById('group-location-notes').value = group.location_notes || '';

        // Renderizar capacidades con datos existentes
        renderCapacitiesForm(group.capacities);

        $('#groupModal').modal('show');

    } catch (error) {
        console.error('Error:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`No se pudo cargar el grupo: ${errorMessage}`);
    }
}

function resetGroupForm() {
    document.getElementById('group-form').reset();
    document.getElementById('group-id').value = '';
}

function renderCapacitiesForm(existingCapacities = []) {
    const container = document.getElementById('capacities-container');

    if (allCategories.length === 0) {
        container.innerHTML = '<p class="text-muted">Cargando categorías...</p>';
        return;
    }

    container.innerHTML = allCategories.map(category => {
        const existing = existingCapacities.find(c => c.category_id === category.id);
        const maxCapacity = existing?.max_capacity || '';

        return `
            <div class="form-row align-items-center mb-2">
                <div class="col-md-6">
                    <label class="mb-0">
                        <i class="${category.icon || 'fas fa-box'} mr-1"></i>
                        ${category.name}
                    </label>
                </div>
                <div class="col-md-4">
                    <input 
                        type="number" 
                        class="form-control form-control-sm" 
                        name="capacity_${category.id}" 
                        placeholder="Capacidad máxima"
                        min="0"
                        value="${maxCapacity}"
                    >
                </div>
                <div class="col-md-2">
                    ${existing ? `
                        <small class="text-muted">
                            Actual: ${existing.current_count}
                        </small>
                    ` : ''}
                </div>
            </div>
        `;
    }).join('');
}

// ==================== SUBMIT ====================
async function handleSubmit(e) {
    e.preventDefault();

    const submitBtn = e.target.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Guardando...';

    try {
        const formData = collectGroupFormData();

        if (!validateGroupData(formData)) {
            throw new Error('Complete todos los campos requeridos');
        }

        const groupId = document.getElementById('group-id').value;
        const isEdit = !!groupId;

        const url = isEdit
            ? `/api/help-desk/v1/inventory/groups/${groupId}`
            : '/api/help-desk/v1/inventory/groups';

        const method = isEdit ? 'PUT' : 'POST';

        const response = await fetch(url, {
            method: method,
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || error.message || 'Error al guardar grupo');
        }

        $('#groupModal').modal('hide');
        showSuccess(isEdit ? 'Grupo actualizado' : 'Grupo creado exitosamente');
        loadGroups(); // Recargar lista

    } catch (error) {
        console.error('Error:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`Error al guardar grupo: ${errorMessage}`);
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-save"></i> Guardar Grupo';
    }
}

function collectGroupFormData() {
    const form = document.getElementById('group-form');

    const data = {
        name: form.querySelector('#group-name').value.trim(),
        type: form.querySelector('#group-type').value,
        department_id: parseInt(form.querySelector('#group-department').value),
        description: form.querySelector('#group-description').value.trim() || null,
        building: form.querySelector('#group-building').value.trim() || null,
        floor: form.querySelector('#group-floor').value.trim() || null,
        location_notes: form.querySelector('#group-location-notes').value.trim() || null
    };

    // Recolectar capacidades
    const capacities = {};
    allCategories.forEach(cat => {
        const input = form.querySelector(`[name="capacity_${cat.id}"]`);
        if (input && input.value) {
            const value = parseInt(input.value);
            if (value > 0) {
                capacities[cat.id] = value;
            }
        }
    });

    if (Object.keys(capacities).length > 0) {
        data.capacities = capacities;
    }

    return data;
}

function validateGroupData(data) {
    if (!data.name) {
        showError('El nombre es requerido');
        return false;
    }

    if (!data.type) {
        showError('El tipo es requerido');
        return false;
    }

    if (!data.department_id) {
        showError('El departamento es requerido');
        return false;
    }

    return true;
}

// ==================== NAVEGACIÓN ====================
function goToGroupDetail(groupId) {
    window.location.href = `/help-desk/inventory/groups/${groupId}`;
}

// ==================== HELPERS ====================
function getGroupTypeInfo(type) {
    const types = {
        'CLASSROOM': { icon: 'fas fa-chalkboard-teacher', label: 'Salón', color: 'primary' },
        'LABORATORY': { icon: 'fas fa-flask', label: 'Laboratorio', color: 'success' },
        'OFFICE': { icon: 'fas fa-briefcase', label: 'Oficina', color: 'info' },
        'MEETING_ROOM': { icon: 'fas fa-users', label: 'Sala de Reuniones', color: 'warning' },
        'WORKSHOP': { icon: 'fas fa-tools', label: 'Taller', color: 'danger' },
        'OTHER': { icon: 'fas fa-folder', label: 'Otro', color: 'secondary' }
    };
    return types[type] || types['OTHER'];
}

function calculateOccupancy(group) {
    if (!group.capacities || group.capacities.length === 0) {
        return { current: 0, total: 0, percentage: 0 };
    }

    const current = group.capacities.reduce((sum, cap) => sum + (cap.current_count || 0), 0);
    const total = group.capacities.reduce((sum, cap) => sum + (cap.max_capacity || 0), 0);
    const percentage = total > 0 ? Math.round((current / total) * 100) : 0;

    return { current, total, percentage };
}

function getOccupancyClass(percentage) {
    if (percentage <= 50) return 'text-success';
    if (percentage <= 80) return 'text-warning';
    return 'text-danger';
}

function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleDateString('es-MX', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}

function showLoading() {
    document.getElementById('loading-container').style.display = 'block';
    document.getElementById('groups-container').style.display = 'none';
    document.getElementById('empty-state').style.display = 'none';
}

function hideLoading() {
    document.getElementById('loading-container').style.display = 'none';
}

function showSuccess(message) {
    showToast(message, 'success');
}

function showError(message) {
    showToast(message, 'error');
}

function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}