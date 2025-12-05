/**
 * Formulario de Crear/Editar Equipo
 * Maneja campos dinámicos según categoría seleccionada y modo individual/masivo
 */

let allCategories = [];
let allDepartments = [];
let allGroups = [];
let currentCategory = null;
let departmentUsers = [];
let currentMode = 'individual';
let bulkItems = [];

document.addEventListener('DOMContentLoaded', function() {
    loadCategories();
    loadDepartments();
    setupEventListeners();
    
    // Si viene en modo bulk desde el parámetro
    if (typeof BULK_MODE !== 'undefined' && BULK_MODE) {
        switchMode('bulk');
    }
});

// ==================== SETUP ====================
function setupEventListeners() {
    // Cambio de categoría
    document.getElementById('category-id').addEventListener('change', handleCategoryChange);
    
    // Cambio de departamento
    document.getElementById('department-id').addEventListener('change', handleDepartmentChange);
    
    // Checkbox de asignación
    document.getElementById('assign-to-user-check').addEventListener('change', function(e) {
        document.getElementById('user-assignment-section').style.display = 
            e.target.checked ? 'block' : 'none';
    });

    // Submit del formulario individual
    document.getElementById('create-item-form').addEventListener('submit', handleSubmit);
    
    // Submit del formulario masivo
    document.getElementById('bulk-create-form').addEventListener('submit', handleBulkSubmit);
    
    // Listeners para modo masivo
    setupBulkListeners();
}

function setupBulkListeners() {
    // Cambio de categoría en modo masivo
    const bulkCategory = document.getElementById('bulk-category-id');
    if (bulkCategory) {
        bulkCategory.addEventListener('change', handleBulkCategoryChange);
    }
    
    // Cambio de tipo de destino
    const destinationType = document.getElementById('bulk-destination-type');
    if (destinationType) {
        destinationType.addEventListener('change', handleDestinationTypeChange);
    }
    
    // Cambio de departamento en modo masivo
    const bulkDepartment = document.getElementById('bulk-department-id');
    if (bulkDepartment) {
        bulkDepartment.addEventListener('change', handleBulkDepartmentChange);
    }
    
    // Campo de cantidad
    const quantityField = document.getElementById('bulk-quantity');
    if (quantityField) {
        quantityField.addEventListener('input', updateBulkPreview);
    }
}

// ==================== CAMBIO DE MODO ====================
function switchMode(mode) {
    currentMode = mode;
    
    const individualForm = document.getElementById('create-item-form');
    const bulkForm = document.getElementById('bulk-create-form');
    const individualPreview = document.getElementById('individual-preview');
    const bulkPreview = document.getElementById('bulk-preview');
    const individualBtn = document.getElementById('mode-individual-btn');
    const bulkBtn = document.getElementById('mode-bulk-btn');
    const pageTitle = document.getElementById('page-title');
    const pageSubtitle = document.getElementById('page-subtitle');
    const modeDescription = document.getElementById('mode-description');
    
    if (mode === 'individual') {
        // Mostrar formulario individual
        individualForm.style.display = 'block';
        bulkForm.style.display = 'none';
        individualPreview.style.display = 'block';
        bulkPreview.style.display = 'none';
        
        // Actualizar botones
        individualBtn.classList.add('active');
        bulkBtn.classList.remove('active');
        
        // Actualizar textos
        pageTitle.textContent = 'Registrar Nuevo Equipo';
        pageSubtitle.textContent = 'Complete la información del equipo para agregarlo al inventario';
        modeDescription.textContent = 'Registra un equipo con toda su información detallada';
        
    } else if (mode === 'bulk') {
        // Mostrar formulario masivo
        individualForm.style.display = 'none';
        bulkForm.style.display = 'block';
        individualPreview.style.display = 'none';
        bulkPreview.style.display = 'block';
        
        // Actualizar botones
        individualBtn.classList.remove('active');
        bulkBtn.classList.add('active');
        
        // Actualizar textos
        pageTitle.textContent = 'Registro Masivo de Equipos';
        pageSubtitle.textContent = 'Registre múltiples equipos de la misma categoría y especificaciones';
        modeDescription.textContent = 'Ideal para lotes de equipos idénticos';
        
        // Cargar datos necesarios para modo masivo
        loadBulkCategories();
        loadBulkDepartments();
    }
}

// ==================== CARGAR DATOS ====================
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

        const select = document.getElementById('category-id');
        select.innerHTML = '<option value="">Seleccionar categoría...</option>';

        allCategories.forEach(cat => {
            const option = document.createElement('option');
            option.value = cat.id;
            option.textContent = cat.name;
            option.dataset.category = JSON.stringify(cat);
            select.appendChild(option);
        });

    } catch (error) {
        console.error('Error cargando categorías:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`No se pudieron cargar las categorías: ${errorMessage}`);
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

        const select = document.getElementById('department-id');
        select.innerHTML = '<option value="">Seleccionar departamento...</option>';

        allDepartments.forEach(dept => {
            const option = document.createElement('option');
            option.value = dept.id;
            option.textContent = dept.name;
            select.appendChild(option);
        });

    } catch (error) {
        console.error('Error cargando departamentos:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`No se pudieron cargar los departamentos: ${errorMessage}`);
    }
}

async function loadDepartmentUsers(departmentId) {
    if (!departmentId) {
        document.getElementById('assigned-to-user-id').innerHTML = 
            '<option value="">Primero selecciona un departamento</option>';
        return;
    }

    try {
        const response = await fetch(`/api/core/v1/departments/${departmentId}/users`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || errorData.message || 'Error al cargar usuarios');
        }

        const result = await response.json();
        departmentUsers = result.data;

        const select = document.getElementById('assigned-to-user-id');
        select.innerHTML = '<option value="">Seleccionar usuario...</option>';

        departmentUsers.forEach(user => {
            const option = document.createElement('option');
            option.value = user.id;
            option.textContent = `${user.full_name} (${user.email})`;
            select.appendChild(option);
        });

    } catch (error) {
        console.error('Error cargando usuarios:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`No se pudieron cargar los usuarios del departamento: ${errorMessage}`);
    }
}

// ==================== MANEJO DE CATEGORÍA ====================
function handleCategoryChange(e) {
    const categoryId = e.target.value;
    
    if (!categoryId) {
        hideSpecsSection();
        hideCategoryPreview();
        clearInventoryPreview();
        return;
    }

    const selectedOption = e.target.selectedOptions[0];
    currentCategory = JSON.parse(selectedOption.dataset.category);

    // Mostrar preview de categoría
    showCategoryPreview(currentCategory);

    // Actualizar preview de número de inventario
    updateInventoryPreview(currentCategory.inventory_prefix);

    // Generar campos de especificaciones
    if (currentCategory.requires_specs && currentCategory.spec_template) {
        renderSpecFields(currentCategory.spec_template);
        showSpecsSection();
    } else {
        hideSpecsSection();
    }
}

function showCategoryPreview(category) {
    const preview = document.getElementById('category-preview');
    const icon = document.getElementById('category-icon-display');
    const description = document.getElementById('category-description');

    icon.className = category.icon || 'fas fa-box text-primary';
    description.textContent = category.description || '';

    preview.style.display = 'block';
}

function hideCategoryPreview() {
    document.getElementById('category-preview').style.display = 'none';
}

function updateInventoryPreview(prefix) {
    const currentYear = new Date().getFullYear();
    document.getElementById('preview-inventory-number').textContent = 
        `${prefix}-${currentYear}-####`;
}

function clearInventoryPreview() {
    document.getElementById('preview-inventory-number').textContent = '---';
}

// ==================== ESPECIFICACIONES DINÁMICAS ====================
function renderSpecFields(template) {
    const container = document.getElementById('dynamic-specs-container');
    container.innerHTML = '';

    Object.entries(template).forEach(([key, config]) => {
        const fieldHtml = createSpecField(key, config);
        container.insertAdjacentHTML('beforeend', fieldHtml);
    });
}

function createSpecField(key, config) {
    const id = `spec_${key}`;
    const label = config.label || key;
    const required = config.required ? 'required' : '';
    const requiredClass = config.required ? 'required-field' : '';

    switch (config.type) {
        case 'text':
            return `
                <div class="form-group spec-field">
                    <label for="${id}" class="${requiredClass}">${label}</label>
                    <input 
                        type="text" 
                        class="form-control" 
                        id="${id}" 
                        name="spec_${key}" 
                        placeholder="${config.placeholder || ''}"
                        ${required}
                    >
                </div>
            `;

        case 'number':
            return `
                <div class="form-group spec-field">
                    <label for="${id}" class="${requiredClass}">${label}</label>
                    <input 
                        type="number" 
                        class="form-control" 
                        id="${id}" 
                        name="spec_${key}" 
                        placeholder="${config.placeholder || ''}"
                        min="${config.min || 0}"
                        ${required}
                    >
                </div>
            `;

        case 'select':
            const options = config.options || [];
            const optionsHtml = options.map(opt => 
                `<option value="${opt}">${opt}</option>`
            ).join('');

            return `
                <div class="form-group spec-field">
                    <label for="${id}" class="${requiredClass}">${label}</label>
                    <select class="form-control" id="${id}" name="spec_${key}" ${required}>
                        <option value="">Seleccionar...</option>
                        ${optionsHtml}
                    </select>
                </div>
            `;

        case 'boolean':
            return `
                <div class="form-group spec-field">
                    <div class="custom-control custom-checkbox">
                        <input 
                            type="checkbox" 
                            class="custom-control-input" 
                            id="${id}" 
                            name="spec_${key}"
                        >
                        <label class="custom-control-label" for="${id}">
                            ${label}
                        </label>
                    </div>
                </div>
            `;

        case 'textarea':
            return `
                <div class="form-group spec-field">
                    <label for="${id}" class="${requiredClass}">${label}</label>
                    <textarea 
                        class="form-control" 
                        id="${id}" 
                        name="spec_${key}" 
                        rows="3" 
                        placeholder="${config.placeholder || ''}"
                        ${required}
                    ></textarea>
                </div>
            `;

        default:
            return '';
    }
}

function showSpecsSection() {
    document.getElementById('specs-section').style.display = 'block';
}

function hideSpecsSection() {
    document.getElementById('specs-section').style.display = 'none';
    document.getElementById('dynamic-specs-container').innerHTML = '';
}

// ==================== MANEJO DE DEPARTAMENTO ====================
function handleDepartmentChange(e) {
    const departmentId = e.target.value;
    
    if (departmentId && document.getElementById('assign-to-user-check').checked) {
        loadDepartmentUsers(departmentId);
    }
}

// ==================== SUBMIT ====================
async function handleSubmit(e) {
    e.preventDefault();

    const submitBtn = document.getElementById('submit-btn');
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Registrando...';

    try {
        // Recolectar datos del formulario
        const formData = collectFormData();

        // Validar
        if (!validateFormData(formData)) {
            throw new Error('Por favor complete todos los campos requeridos');
        }

        // Enviar a la API
        const response = await fetch('/api/help-desk/v1/inventory/items', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || error.message || 'Error al registrar equipo');
        }

        const result = await response.json();
        const createdItem = result.data;

        // Mostrar modal de éxito
        showSuccessModal(createdItem);

    } catch (error) {
        console.error('Error:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`Error al registrar equipo: ${errorMessage}`);
        
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-save"></i> Registrar Equipo';
    }
}

function collectFormData() {
    const form = document.getElementById('create-item-form');
    const formData = {
        category_id: parseInt(form.querySelector('#category-id').value),
        brand: form.querySelector('#brand').value.trim() || null,
        model: form.querySelector('#model').value.trim() || null,
        serial_number: form.querySelector('#serial-number').value.trim() || null,
        department_id: parseInt(form.querySelector('#department-id').value),
        location_detail: form.querySelector('#location-detail').value.trim() || null,
        acquisition_date: form.querySelector('#acquisition-date').value || null,
        warranty_expiration: form.querySelector('#warranty-expiration').value || null,
        maintenance_frequency_days: parseInt(form.querySelector('#maintenance-frequency').value) || null,
        notes: form.querySelector('#notes').value.trim() || null
    };

    // Asignación a usuario (opcional)
    const assignCheck = document.getElementById('assign-to-user-check');
    if (assignCheck.checked) {
        const userId = form.querySelector('#assigned-to-user-id').value;
        if (userId) {
            formData.assigned_to_user_id = parseInt(userId);
        }
    }

    // Especificaciones técnicas
    if (currentCategory && currentCategory.requires_specs && currentCategory.spec_template) {
        const specifications = {};
        
        Object.keys(currentCategory.spec_template).forEach(key => {
            const field = form.querySelector(`[name="spec_${key}"]`);
            if (field) {
                if (field.type === 'checkbox') {
                    specifications[key] = field.checked;
                } else if (field.value) {
                    specifications[key] = field.value;
                }
            }
        });

        if (Object.keys(specifications).length > 0) {
            formData.specifications = specifications;
        }
    }

    return formData;
}

function validateFormData(data) {
    if (!data.category_id) {
        showError('Debe seleccionar una categoría');
        return false;
    }

    if (!data.department_id) {
        showError('Debe seleccionar un departamento');
        return false;
    }

    return true;
}

// ==================== MODAL DE ÉXITO ====================
function showSuccessModal(item) {
    document.getElementById('success-inventory-number').textContent = item.inventory_number;
    document.getElementById('view-item-link').href = `/help-desk/inventory/items/${item.id}`;
    
    $('#successModal').modal('show');
}

// ==================== HELPERS ====================
function showError(message) {
    showToast(message, 'error'); // Reemplazar con tu sistema de notificaciones
}

function showSuccess(message) {
    showToast(message, 'success');
}

// ==================== MODO MASIVO ====================
async function loadBulkCategories() {
    if (allCategories.length > 0) {
        populateBulkCategories();
        return;
    }
    
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
        populateBulkCategories();

    } catch (error) {
        console.error('Error cargando categorías para bulk:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`No se pudieron cargar las categorías: ${errorMessage}`);
    }
}

function populateBulkCategories() {
    const select = document.getElementById('bulk-category-id');
    if (!select) return;
    
    select.innerHTML = '<option value="">Seleccionar categoría...</option>';
    
    allCategories.forEach(cat => {
        const option = document.createElement('option');
        option.value = cat.id;
        option.textContent = cat.name;
        option.dataset.category = JSON.stringify(cat);
        select.appendChild(option);
    });
}

async function loadBulkDepartments() {
    if (allDepartments.length > 0) {
        populateBulkDepartments();
        return;
    }
    
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
        populateBulkDepartments();

    } catch (error) {
        console.error('Error cargando departamentos para bulk:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`No se pudieron cargar los departamentos: ${errorMessage}`);
    }
}

function populateBulkDepartments() {
    const select = document.getElementById('bulk-department-id');
    if (!select) return;
    
    select.innerHTML = '<option value="">Seleccionar departamento...</option>';
    
    allDepartments.forEach(dept => {
        const option = document.createElement('option');
        option.value = dept.id;
        option.textContent = dept.name;
        select.appendChild(option);
    });
}

async function loadGroups(departmentId = null) {
    try {
        let url = '/api/help-desk/v1/inventory/groups';
        if (departmentId) {
            url += `?department_id=${departmentId}`;
        }

        const response = await fetch(url, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || errorData.message || 'Error al cargar grupos');
        }

        const result = await response.json();
        allGroups = result.data || [];

        populateBulkGroups();

    } catch (error) {
        console.error('Error cargando grupos:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`No se pudieron cargar los grupos: ${errorMessage}`);
        allGroups = [];
        populateBulkGroups();
    }
}

function populateBulkGroups() {
    const select = document.getElementById('bulk-group-id');
    if (!select) return;
    
    select.innerHTML = '<option value="">Seleccionar grupo...</option>';
    
    allGroups.forEach(group => {
        const option = document.createElement('option');
        option.value = group.id;
        option.textContent = `${group.name} (${group.department?.name || 'Sin depto'})`;
        select.appendChild(option);
    });
}

function handleBulkCategoryChange(e) {
    const categoryId = e.target.value;
    updateBulkPreview();
}

function handleDestinationTypeChange(e) {
    const type = e.target.value;
    const deptSection = document.getElementById('bulk-department-section');
    const groupSection = document.getElementById('bulk-group-section');
    
    // Ocultar todas las secciones
    deptSection.style.display = 'none';
    groupSection.style.display = 'none';
    
    if (type === 'department') {
        deptSection.style.display = 'block';
    } else if (type === 'group') {
        groupSection.style.display = 'block';
        loadGroups(); // Cargar todos los grupos
    }
    
    updateBulkPreview();
}

function handleBulkDepartmentChange(e) {
    const departmentId = e.target.value;
    
    // Si el destino es por grupo, recargar grupos del departamento seleccionado
    const destinationType = document.getElementById('bulk-destination-type').value;
    if (destinationType === 'group' && departmentId) {
        loadGroups(departmentId);
    }
    
    updateBulkPreview();
}

function updateBulkPreview() {
    const quantity = parseInt(document.getElementById('bulk-quantity')?.value) || 0;
    const category = document.getElementById('bulk-category-id')?.selectedOptions[0];
    const brand = document.getElementById('bulk-brand')?.value || '';
    const model = document.getElementById('bulk-model')?.value || '';
    const destinationType = document.getElementById('bulk-destination-type')?.value || '';
    
    // Actualizar cantidad en preview
    document.getElementById('preview-bulk-quantity').textContent = quantity;
    document.getElementById('bulk-btn-quantity').textContent = quantity;
    
    // Actualizar resumen
    const summaryHtml = `
        <div class="mb-2">
            <strong>Cantidad:</strong> ${quantity} equipos
        </div>
        ${category ? `<div class="mb-2"><strong>Categoría:</strong> ${category.textContent}</div>` : ''}
        ${brand ? `<div class="mb-2"><strong>Marca:</strong> ${brand}</div>` : ''}
        ${model ? `<div class="mb-2"><strong>Modelo:</strong> ${model}</div>` : ''}
        ${destinationType ? `<div class="mb-2"><strong>Destino:</strong> ${getDestinationText(destinationType)}</div>` : ''}
    `;
    
    document.getElementById('bulk-summary').innerHTML = summaryHtml;
}

function getDestinationText(type) {
    switch(type) {
        case 'pending': return 'Equipos Pendientes (Limbo)';
        case 'department': return 'Asignar a Departamento';
        case 'group': return 'Asignar a Grupo/Salón';
        default: return '';
    }
}

async function handleBulkSubmit(e) {
    e.preventDefault();

    const submitBtn = document.getElementById('bulk-submit-btn');
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Preparando...';

    try {
        // Recolectar datos del formulario masivo
        const formData = collectBulkFormData();

        // Validar
        if (!validateBulkFormData(formData)) {
            throw new Error('Por favor complete todos los campos requeridos');
        }

        // Mostrar modal de progreso
        showProgressModal(formData.items.length);

        // Enviar a la API de bulk create
        const response = await fetch('/api/help-desk/v1/inventory/bulk/create', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || error.message || 'Error en registro masivo');
        }

        const result = await response.json();

        // Ocultar modal de progreso
        $('#progressModal').modal('hide');

        // Mostrar modal de éxito masivo
        showBulkSuccessModal(result);

    } catch (error) {
        console.error('Error:', error);
        $('#progressModal').modal('hide');
        const errorMessage = error.message || 'Error desconocido';
        showError(`Error en registro masivo: ${errorMessage}`);
        
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-boxes"></i> Registrar <span id="bulk-btn-quantity">0</span> Equipos';
    }
}

function collectBulkFormData() {
    const form = document.getElementById('bulk-create-form');
    const quantity = parseInt(form.querySelector('#bulk-quantity').value) || 0;
    const destinationType = form.querySelector('#bulk-destination-type').value;
    
    const baseData = {
        category_id: parseInt(form.querySelector('#bulk-category-id').value),
        brand: form.querySelector('#bulk-brand').value.trim() || null,
        model: form.querySelector('#bulk-model').value.trim() || null,
        acquisition_date: form.querySelector('#bulk-acquisition-date').value || null,
        warranty_expiration: form.querySelector('#bulk-warranty-expiration').value || null,
        notes: form.querySelector('#bulk-notes').value.trim() || null,
        items: []
    };
    
    // Generar items individuales
    for (let i = 1; i <= quantity; i++) {
        const item = {
            serial_number: null // Se generará automáticamente o se dejará vacío
        };
        
        // Determinar destino según tipo
        if (destinationType === 'department') {
            const deptId = form.querySelector('#bulk-department-id').value;
            if (deptId) {
                item.department_id = parseInt(deptId);
                item.location_detail = form.querySelector('#bulk-location-detail').value.trim() || null;
            }
        } else if (destinationType === 'group') {
            const groupId = form.querySelector('#bulk-group-id').value;
            if (groupId) {
                item.group_id = parseInt(groupId);
            }
        }
        // Para 'pending' no se asigna departamento ni grupo
        
        baseData.items.push(item);
    }
    
    return baseData;
}

function validateBulkFormData(data) {
    if (!data.category_id) {
        showError('Debe seleccionar una categoría');
        return false;
    }

    if (!data.items || data.items.length === 0) {
        showError('Debe especificar la cantidad de equipos');
        return false;
    }

    if (data.items.length > 100) {
        showError('No se pueden registrar más de 100 equipos de una vez');
        return false;
    }

    return true;
}

function showProgressModal(total) {
    document.getElementById('progress-total').textContent = total;
    document.getElementById('progress-current').textContent = '0';
    document.getElementById('progress-bar').style.width = '0%';
    document.getElementById('progress-text').textContent = '0%';
    
    $('#progressModal').modal('show');
}

function showBulkSuccessModal(result) {
    document.getElementById('bulk-success-count').textContent = result.items.length;
    
    // Generar lista de equipos creados
    const detailsHtml = result.items.map(item => `
        <div class="d-flex justify-content-between align-items-center py-2 border-bottom">
            <span><i class="fas fa-check-circle text-success mr-2"></i>${item.inventory_number}</span>
            <small class="text-muted">${item.brand || ''} ${item.model || ''}</small>
        </div>
    `).join('');
    
    document.getElementById('bulk-success-details').innerHTML = detailsHtml;
    
    $('#bulkSuccessModal').modal('show');
}