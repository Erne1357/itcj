/**
 * Formulario de Crear/Editar Equipo
 * Maneja campos dinámicos según categoría seleccionada
 */

let allCategories = [];
let allDepartments = [];
let currentCategory = null;
let departmentUsers = [];

document.addEventListener('DOMContentLoaded', function() {
    loadCategories();
    loadDepartments();
    setupEventListeners();
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

    // Submit del formulario
    document.getElementById('create-item-form').addEventListener('submit', handleSubmit);
}

// ==================== CARGAR DATOS ====================
async function loadCategories() {
    try {
        const response = await fetch('/api/help-desk/v1/inventory/categories?active=true', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar categorías');

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
        showError('No se pudieron cargar las categorías');
    }
}

async function loadDepartments() {
    try {
        const response = await fetch('/api/core/v1/departments?active=true', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar departamentos');

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
        showError('No se pudieron cargar los departamentos');
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

        if (!response.ok) throw new Error('Error al cargar usuarios');

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
            throw new Error(error.error || 'Error al registrar equipo');
        }

        const result = await response.json();
        const createdItem = result.data;

        // Mostrar modal de éxito
        showSuccessModal(createdItem);

    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
        
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
    alert(message); // Reemplazar con tu sistema de notificaciones
}

function showSuccess(message) {
    alert(message);
}