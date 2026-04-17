/**
 * Formulario de Crear/Editar Equipo
 * Maneja campos dinámicos según categoría seleccionada y modo individual/masivo
 */

let allCategories = [];
let allDepartments = [];
let allGroups = [];
let currentCategory = null;
let currentBulkCategory = null;
let departmentUsers = [];
let currentMode = 'individual';
let bulkItems = [];
let currentCampaignId = null;
let currentPredecessorId = null;
let predecessorDebounce = null;
const COMPUTER_CATEGORY_CODE = 'computer';

// ==================== ERROR HELPERS ====================
function extractErrorMessage(data, fallback = 'Error desconocido') {
    if (typeof data === 'string') return data || fallback;
    if (!data || typeof data !== 'object') return fallback;
    const val = data.error || data.message || data.detail;
    if (typeof val === 'string') return val || fallback;
    if (Array.isArray(val)) {
        return val.map(e => (typeof e === 'object' && e.msg) ? e.msg : String(e)).join('; ') || fallback;
    }
    if (typeof val === 'object' && val !== null) {
        return extractErrorMessage(val, fallback);
    }
    return fallback;
}

async function fetchApiError(response, fallback) {
    try {
        const data = await response.json();
        return extractErrorMessage(data, fallback);
    } catch (_) {
        return `${fallback} (HTTP ${response.status})`;
    }
}

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

    // Crear usuario inactivo
    initCreateInactiveUser();

    // Predecesor (equipo que este reemplaza)
    initPredecessorSearch();

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

    // Contadores de listas de seriales
    document.querySelectorAll('.serial-list-input').forEach(textarea => {
        textarea.addEventListener('input', function () {
            updateSerialCount(this);
            checkSerialMismatch();
        });
    });

    // Al cambiar separador, re-contar
    document.querySelectorAll('input[name="bulk-serial-separator"]').forEach(radio => {
        radio.addEventListener('change', function () {
            document.querySelectorAll('.serial-list-input').forEach(ta => updateSerialCount(ta));
            checkSerialMismatch();
        });
    });
}

function getSelectedSeparator() {
    const sel = document.querySelector('input[name="bulk-serial-separator"]:checked');
    return sel ? sel.value : 'newline';
}

function parseSerialList(raw, separator) {
    if (!raw || !raw.trim()) return [];
    const text = raw.trim();
    let parts;
    if (separator === 'auto') {
        const counts = { '\n': (text.match(/\n/g) || []).length, ',': (text.match(/,/g) || []).length, ';': (text.match(/;/g) || []).length };
        const best = Object.keys(counts).reduce((a, b) => counts[a] >= counts[b] ? a : b);
        separator = counts[best] > 0 ? ({ '\n': 'newline', ',': 'comma', ';': 'semicolon' }[best]) : 'space';
    }
    if (separator === 'newline') parts = text.split('\n');
    else if (separator === 'comma') parts = text.split(',');
    else if (separator === 'semicolon') parts = text.split(';');
    else parts = text.split(/\s+/);
    return parts.map(p => p.trim()).filter(Boolean);
}

function updateSerialCount(textarea) {
    const separator = getSelectedSeparator();
    const items = parseSerialList(textarea.value, separator);
    const labelId = textarea.dataset.countLabel;
    const label = document.getElementById(labelId);
    if (label) label.textContent = items.length;
}

function checkSerialMismatch() {
    const quantity = parseInt(document.getElementById('bulk-quantity').value) || 0;
    const separator = getSelectedSeparator();
    const warnings = [];
    const configs = [
        { id: 'bulk-supplier-serial-list', name: 'Serial proveedor' },
        { id: 'bulk-itcj-serial-list',    name: 'Serial ITCJ' },
        { id: 'bulk-id-tecnm-list',        name: 'ID TecNM' },
    ];
    configs.forEach(cfg => {
        const ta = document.getElementById(cfg.id);
        if (!ta || !ta.value.trim()) return;
        const count = parseSerialList(ta.value, separator).length;
        if (count !== quantity) {
            warnings.push(`${cfg.name}: ${count} entradas (se esperan ${quantity})`);
        }
    });
    const warnDiv = document.getElementById('serial-mismatch-warning');
    const warnMsg = document.getElementById('serial-mismatch-msg');
    if (warnings.length > 0) {
        warnMsg.textContent = 'Longitudes no coinciden: ' + warnings.join(' | ') + '. Los equipos sin serial en esa posición quedarán sin ese identificador.';
        warnDiv.classList.remove('d-none');
    } else {
        warnDiv.classList.add('d-none');
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
        const response = await fetch('/api/help-desk/v2/inventory/categories?active=true', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            throw new Error(await fetchApiError(response, 'Error al cargar categorías'));
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
        const response = await fetch('/api/core/v2/departments?active=true', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            throw new Error(await fetchApiError(response, 'Error al cargar departamentos'));
        }

        const result = await response.json();
        allDepartments = result.data;

        const select = document.getElementById('department-id');
        select.innerHTML = '<option value="">Sin asignar (Limbo CC)</option>';

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
        const response = await fetch(`/api/core/v2/departments/${departmentId}/users?include_inactive=true`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            throw new Error(await fetchApiError(response, 'Error al cargar usuarios del departamento'));
        }

        const result = await response.json();
        departmentUsers = result.data.users ?? result.data;

        const select = document.getElementById('assigned-to-user-id');
        select.innerHTML = '<option value="">Seleccionar usuario...</option>';

        departmentUsers.forEach(user => {
            const option = document.createElement('option');
            option.value = user.id;
            const label = user.is_active === false
                ? `${user.full_name} (cuenta inactiva)`
                : `${user.full_name} (${user.email || user.username})`;
            option.textContent = label;
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
        renderSpecsContextHelp();
        setupSpecFieldDependencies();
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

function renderSpecsContextHelp() {
    const helpBox = document.getElementById('spec-context-help');
    if (!helpBox) return;

    const isComputer = currentCategory && currentCategory.code === COMPUTER_CATEGORY_CODE;
    if (!isComputer) {
        helpBox.style.display = 'none';
        helpBox.innerHTML = '';
        return;
    }

    helpBox.innerHTML = `
        <i class="fas fa-info-circle"></i>
        Si el <strong>Factor de Forma</strong> es <strong>All in One</strong>, el sistema marcará automáticamente
        <strong>Pantalla Integrada</strong>. Si además usa monitores externos, regístralos por separado en la
        categoría <strong>Monitor</strong>.
    `;
    helpBox.style.display = 'block';
}

function setupSpecFieldDependencies() {
    const formFactorField = document.getElementById('spec_form_factor');
    const integratedDisplayField = document.getElementById('spec_integrated_display');

    if (!formFactorField || !integratedDisplayField) return;

    formFactorField.addEventListener('change', applyComputerSpecRules);
    integratedDisplayField.addEventListener('change', applyComputerSpecRules);
    applyComputerSpecRules();
}

function applyComputerSpecRules() {
    if (!currentCategory || currentCategory.code !== COMPUTER_CATEGORY_CODE) return;

    const formFactorField = document.getElementById('spec_form_factor');
    const integratedDisplayField = document.getElementById('spec_integrated_display');
    const displaySizeField = document.getElementById('spec_display_size');

    if (!formFactorField || !integratedDisplayField) return;

    const normalizedFormFactor = (formFactorField.value || '').toString().trim().toLowerCase();
    const isAllInOne = normalizedFormFactor === 'all in one' || normalizedFormFactor === 'all-in-one' || normalizedFormFactor === 'allinone';

    if (isAllInOne) {
        integratedDisplayField.checked = true;
        integratedDisplayField.disabled = true;
    } else {
        integratedDisplayField.disabled = false;
    }

    if (displaySizeField) {
        const displaySizeGroup = displaySizeField.closest('.spec-field');
        if (displaySizeGroup) {
            displaySizeGroup.style.display = integratedDisplayField.checked ? 'block' : 'none';
        }
    }
}

function normalizeComputerSpecificationsByCategory(specifications, category) {
    if (!category || category.code !== COMPUTER_CATEGORY_CODE) return;

    const formFactor = (specifications.form_factor || '').toString().trim().toLowerCase();
    const isAllInOne = formFactor === 'all in one' || formFactor === 'all-in-one' || formFactor === 'allinone';

    if (isAllInOne) {
        specifications.integrated_display = true;
    }

    if (!specifications.integrated_display) {
        delete specifications.display_size;
    }
}

function normalizeComputerSpecifications(specifications) {
    normalizeComputerSpecificationsByCategory(specifications, currentCategory);
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
    renderSpecsContextHelp();
}

// ==================== MANEJO DE DEPARTAMENTO ====================
function handleDepartmentChange(e) {
    const departmentId = e.target.value;

    if (departmentId && document.getElementById('assign-to-user-check').checked) {
        loadDepartmentUsers(departmentId);
    }

    loadActiveCampaign(departmentId);
    clearPredecessor();
}

// ==================== CAMPAÑA ACTIVA ====================
async function loadActiveCampaign(deptId) {
    const section = document.getElementById('campaign-section');
    if (!deptId) {
        section.style.display = 'none';
        currentCampaignId = null;
        document.getElementById('campaign-id').value = '';
        return;
    }
    try {
        const res = await fetch(
            `/api/help-desk/v2/inventory/campaigns?department_id=${deptId}&status=OPEN&per_page=1`,
            { headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` } }
        );
        if (!res.ok) { section.style.display = 'none'; return; }
        const data = await res.json();
        const campaigns = data.data || [];
        if (campaigns.length > 0) {
            const c = campaigns[0];
            currentCampaignId = c.id;
            document.getElementById('campaign-id').value = c.id;
            document.getElementById('campaign-folio').textContent = c.folio;
            document.getElementById('campaign-title').textContent = c.title || '';
            section.style.display = 'block';
        } else {
            section.style.display = 'none';
            currentCampaignId = null;
            document.getElementById('campaign-id').value = '';
        }
    } catch (_) {
        section.style.display = 'none';
    }
}

// ==================== PREDECESOR ====================
let _selectedPredecessorData = null;

const _STATUS_COLORS = {
    ACTIVE: 'success', MAINTENANCE: 'warning', DAMAGED: 'danger',
    LOST: 'secondary', PENDING_ASSIGNMENT: 'info'
};

function initPredecessorSearch() {
    const btnSearch = document.getElementById('btn-search-predecessor');
    const btnClear  = document.getElementById('btn-clear-predecessor');
    const searchInput = document.getElementById('predecessor-search-input');
    const btnConfirm  = document.getElementById('btn-confirm-predecessor');

    if (btnSearch) {
        btnSearch.addEventListener('click', () => {
            _resetPredecessorModal();
            $('#predecessorSearchModal').modal('show');
        });
    }

    // Precargar equipos del dpto cuando el modal termina de abrir
    $('#predecessorSearchModal').on('shown.bs.modal', () => {
        if (searchInput) searchInput.focus();
        searchPredecessorItems('');
    });

    if (btnClear) btnClear.addEventListener('click', clearPredecessor);

    if (searchInput) {
        searchInput.addEventListener('input', () => {
            clearTimeout(predecessorDebounce);
            predecessorDebounce = setTimeout(() => searchPredecessorItems(searchInput.value.trim()), 350);
        });
    }

    if (btnConfirm) {
        btnConfirm.addEventListener('click', () => {
            if (!_selectedPredecessorData) return;
            const i = _selectedPredecessorData;
            const desc = [i.brand, i.model].filter(Boolean).join(' ');
            _confirmPredecessor(i.id, i.inventory_number, desc);
        });
    }
}

function _resetPredecessorModal() {
    const searchInput = document.getElementById('predecessor-search-input');
    if (searchInput) searchInput.value = '';
    document.getElementById('predecessor-results').innerHTML =
        '<div class="text-center py-4"><i class="fas fa-spinner fa-spin text-primary fa-lg"></i></div>';
    document.getElementById('predecessor-detail-empty').style.display = '';
    document.getElementById('predecessor-detail-panel').style.display = 'none';
    document.getElementById('btn-confirm-predecessor').classList.add('d-none');
    _selectedPredecessorData = null;
}

async function searchPredecessorItems(q) {
    const resultsEl = document.getElementById('predecessor-results');
    resultsEl.innerHTML =
        '<div class="text-center py-3"><i class="fas fa-spinner fa-spin text-primary"></i></div>';

    try {
        const deptId = document.getElementById('department-id').value;
        const params = new URLSearchParams({ per_page: 50, sort: 'recent' });
        if (deptId) params.set('department_id', deptId);
        if (q) params.set('search', q);

        const res = await fetch(`/api/help-desk/v2/inventory/items?${params}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
        });
        const data = await res.json();
        const items = (data.data || []).filter(i => i.is_active);

        if (items.length === 0) {
            resultsEl.innerHTML =
                `<div class="text-center text-muted py-4 small">
                    <i class="fas fa-inbox d-block fa-2x mb-2"></i>
                    ${q ? 'Sin resultados para "' + q + '"' : 'Sin equipos en este departamento'}
                 </div>`;
            return;
        }

        resultsEl.innerHTML = items.map(i => {
            const desc = [i.brand, i.model].filter(Boolean).join(' ');
            const sc = _STATUS_COLORS[i.status] || 'secondary';
            return `<div class="pred-item-card border-bottom px-3 py-2" data-id="${i.id}"
                         onclick="showPredecessorDetail(${i.id})">
                <div class="d-flex justify-content-between align-items-start">
                    <div class="overflow-hidden">
                        <div class="font-weight-bold small text-truncate">
                            ${i.inventory_number}
                            ${i.is_locked ? '<i class="fas fa-lock text-warning ml-1" title="Bloqueado"></i>' : ''}
                        </div>
                        <div class="text-muted" style="font-size:.78rem;">${desc || '—'}</div>
                        ${i.itcj_serial ? `<div class="text-muted" style="font-size:.72rem;">${i.itcj_serial}</div>` : ''}
                    </div>
                    <span class="badge badge-${sc} ml-2 flex-shrink-0" style="font-size:.62rem;">${i.status}</span>
                </div>
            </div>`;
        }).join('');

    } catch (err) {
        resultsEl.innerHTML =
            `<div class="text-center text-danger py-3 small">${err.message}</div>`;
    }
}

async function showPredecessorDetail(itemId) {
    const emptyEl  = document.getElementById('predecessor-detail-empty');
    const panelEl  = document.getElementById('predecessor-detail-panel');
    const btnCfm   = document.getElementById('btn-confirm-predecessor');

    // Resaltar card seleccionada
    document.querySelectorAll('.pred-item-card').forEach(el => el.classList.remove('selected'));
    const card = document.querySelector(`.pred-item-card[data-id="${itemId}"]`);
    if (card) card.classList.add('selected');

    // Loading state
    emptyEl.style.display = '';
    emptyEl.innerHTML = '<div class="text-center py-4"><i class="fas fa-spinner fa-spin fa-2x text-primary"></i></div>';
    panelEl.style.display = 'none';
    btnCfm.classList.add('d-none');

    try {
        const res = await fetch(`/api/help-desk/v2/inventory/items/${itemId}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error);

        _selectedPredecessorData = data.data;
        _renderPredecessorDetail(data.data);

        emptyEl.style.display = 'none';
        panelEl.style.display = 'block';
        btnCfm.classList.remove('d-none');

    } catch (err) {
        emptyEl.innerHTML =
            `<div class="text-center text-danger py-4 small">
                <i class="fas fa-exclamation-circle fa-2x d-block mb-2"></i>${err.message}
             </div>`;
    }
}

function _renderPredecessorDetail(item) {
    const panel = document.getElementById('predecessor-detail-panel');
    const sc = _STATUS_COLORS[item.status] || 'secondary';

    // Especificaciones
    let specsHtml = '';
    if (item.specifications && Object.keys(item.specifications).length > 0) {
        const specItems = Object.entries(item.specifications)
            .filter(([, v]) => v !== null && v !== '')
            .map(([k, v]) => `
                <div class="pred-spec-item">
                    <small class="text-muted d-block">${_fmtKey(k)}</small>
                    <span>${v === true ? 'Sí' : v === false ? 'No' : v}</span>
                </div>`).join('');
        specsHtml = `
            <div class="mt-3">
                <div class="text-muted small font-weight-bold text-uppercase mb-2">
                    <i class="fas fa-microchip mr-1"></i>Especificaciones
                </div>
                <div class="pred-spec-grid">${specItems}</div>
            </div>`;
    }

    // Datos de asignación/fechas
    const rows = [
        ['Categoría',     item.category ? item.category.name : null],
        ['Departamento',  item.department ? item.department.name : null],
        ['Asignado a',    item.assigned_to_user ? item.assigned_to_user.full_name : 'Global del depto.'],
        ['Serial ITCJ',   item.itcj_serial],
        ['Serial Prov.',  item.supplier_serial],
        ['ID TecNM',      item.id_tecnm],
        ['Adquisición',   item.acquisition_date],
        ['Garantía',      item.warranty_expiration
            ? `<span class="${item.is_under_warranty ? 'text-success' : 'text-danger'}">${item.warranty_expiration}</span>`
            : null],
    ].filter(([, v]) => v);

    const infoHtml = `
        <div class="pred-spec-grid mt-2">
            ${rows.map(([label, val]) => `
                <div class="pred-spec-item">
                    <small class="text-muted d-block">${label}</small>
                    <span>${val}</span>
                </div>`).join('')}
        </div>`;

    panel.innerHTML = `
        <div class="d-flex justify-content-between align-items-start mb-2">
            <div>
                <h5 class="mb-0 font-weight-bold">${item.inventory_number}</h5>
                <span class="text-muted">${[item.brand, item.model].filter(Boolean).join(' ') || '—'}</span>
            </div>
            <div class="text-right flex-shrink-0 ml-2">
                <span class="badge badge-${sc}">${item.status}</span>
                ${item.is_locked
                    ? '<br><span class="badge badge-warning mt-1"><i class="fas fa-lock mr-1"></i>Bloqueado</span>'
                    : ''}
            </div>
        </div>
        <hr class="my-2">
        ${infoHtml}
        ${specsHtml}
        ${item.notes
            ? `<div class="mt-3"><small class="text-muted d-block">Notas</small><span class="small">${item.notes}</span></div>`
            : ''}`;
}

function _fmtKey(key) {
    return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function _confirmPredecessor(id, invNumber, desc) {
    currentPredecessorId = id;
    document.getElementById('predecessor-item-id').value = id;
    document.getElementById('predecessor-display').value =
        desc.trim() ? `${invNumber} — ${desc}` : invNumber;
    document.getElementById('btn-clear-predecessor').classList.remove('d-none');
    $('#predecessorSearchModal').modal('hide');
}

function selectPredecessor(id, invNumber, desc) {
    _confirmPredecessor(id, invNumber, desc);
}

function clearPredecessor() {
    currentPredecessorId = null;
    _selectedPredecessorData = null;
    document.getElementById('predecessor-item-id').value = '';
    document.getElementById('predecessor-display').value = '';
    document.getElementById('btn-clear-predecessor').classList.add('d-none');
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
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-save"></i> Registrar Equipo';
            return;
        }

        // Enviar a la API
        const response = await fetch('/api/help-desk/v2/inventory/items', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });

        if (!response.ok) {
            let errorData = {};
            try { errorData = await response.json(); } catch (_) {}
            console.error('API Error:', errorData);
            throw new Error(extractErrorMessage(errorData, 'Error al registrar equipo'));
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
    const deptValue = form.querySelector('#department-id').value;
    const formData = {
        category_id: parseInt(form.querySelector('#category-id').value),
        brand: form.querySelector('#brand').value.trim() || null,
        model: form.querySelector('#model').value.trim() || null,
        supplier_serial: form.querySelector('#supplier-serial').value.trim() || null,
        itcj_serial: form.querySelector('#itcj-serial').value.trim() || null,
        id_tecnm: form.querySelector('#id-tecnm').value.trim() || null,
        department_id: deptValue ? parseInt(deptValue) : null,
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

    // Campaña activa (si el usuario eligió asociar)
    const campaignId = document.getElementById('campaign-id').value;
    const campaignCheck = document.getElementById('assign-to-campaign');
    if (campaignId && campaignCheck && campaignCheck.checked) {
        formData.campaign_id = parseInt(campaignId);
    }

    // Predecesor (equipo que este reemplaza)
    const predecessorId = document.getElementById('predecessor-item-id').value;
    if (predecessorId) {
        formData.predecessor_item_id = parseInt(predecessorId);
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

        normalizeComputerSpecifications(specifications);

        if (Object.keys(specifications).length > 0) {
            formData.specifications = specifications;
        }
    }

    return formData;
}

function validateFormData(data) {
    const categorySelect = document.getElementById('category-id');
    if (!data.category_id) {
        categorySelect.classList.add('is-invalid');
        showError('Debe seleccionar una categoría');
        return false;
    }
    categorySelect.classList.remove('is-invalid');

    // department_id es opcional: si no se selecciona, va al limbo del CC
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
        const response = await fetch('/api/help-desk/v2/inventory/categories?active=true', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            throw new Error(await fetchApiError(response, 'Error al cargar categorías'));
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
        const response = await fetch('/api/core/v2/departments?active=true', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            throw new Error(await fetchApiError(response, 'Error al cargar departamentos'));
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
        let url = '/api/help-desk/v2/inventory/groups';
        if (departmentId) {
            url += `?department_id=${departmentId}`;
        }

        const response = await fetch(url, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            throw new Error(await fetchApiError(response, 'Error al cargar grupos'));
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

    if (!categoryId) {
        currentBulkCategory = null;
        hideBulkSpecsSection();
        updateBulkPreview();
        return;
    }

    const selectedOption = e.target.selectedOptions[0];
    currentBulkCategory = selectedOption ? JSON.parse(selectedOption.dataset.category) : null;

    if (currentBulkCategory && currentBulkCategory.requires_specs && currentBulkCategory.spec_template) {
        renderBulkSpecFields(currentBulkCategory.spec_template);
        renderBulkSpecsContextHelp();
        setupBulkSpecFieldDependencies();
        showBulkSpecsSection();
    } else {
        hideBulkSpecsSection();
    }

    updateBulkPreview();
}

function renderBulkSpecFields(template) {
    const container = document.getElementById('bulk-dynamic-specs-container');
    if (!container) return;

    container.innerHTML = '';

    Object.entries(template).forEach(([key, config]) => {
        const fieldHtml = createBulkSpecField(key, config);
        container.insertAdjacentHTML('beforeend', fieldHtml);
    });
}

function createBulkSpecField(key, config) {
    const id = `bulk_spec_${key}`;
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
                        name="bulk_spec_${key}"
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
                        name="bulk_spec_${key}"
                        placeholder="${config.placeholder || ''}"
                        min="${config.min || 0}"
                        ${required}
                    >
                </div>
            `;

        case 'select':
            const options = config.options || [];
            const optionsHtml = options.map(opt => `<option value="${opt}">${opt}</option>`).join('');

            return `
                <div class="form-group spec-field">
                    <label for="${id}" class="${requiredClass}">${label}</label>
                    <select class="form-control" id="${id}" name="bulk_spec_${key}" ${required}>
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
                            name="bulk_spec_${key}"
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
                        name="bulk_spec_${key}"
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

function renderBulkSpecsContextHelp() {
    const helpBox = document.getElementById('bulk-spec-context-help');
    if (!helpBox) return;

    const isComputer = currentBulkCategory && currentBulkCategory.code === COMPUTER_CATEGORY_CODE;
    if (!isComputer) {
        helpBox.style.display = 'none';
        helpBox.innerHTML = '';
        return;
    }

    helpBox.innerHTML = `
        <i class="fas fa-info-circle"></i>
        Para lotes <strong>All in One</strong>, selecciona ese factor de forma y el sistema activará
        <strong>Pantalla Integrada</strong> automáticamente para todo el lote.
    `;
    helpBox.style.display = 'block';
}

function setupBulkSpecFieldDependencies() {
    const formFactorField = document.getElementById('bulk_spec_form_factor');
    const integratedDisplayField = document.getElementById('bulk_spec_integrated_display');

    if (!formFactorField || !integratedDisplayField) return;

    formFactorField.addEventListener('change', applyBulkComputerSpecRules);
    integratedDisplayField.addEventListener('change', applyBulkComputerSpecRules);
    applyBulkComputerSpecRules();
}

function applyBulkComputerSpecRules() {
    if (!currentBulkCategory || currentBulkCategory.code !== COMPUTER_CATEGORY_CODE) return;

    const formFactorField = document.getElementById('bulk_spec_form_factor');
    const integratedDisplayField = document.getElementById('bulk_spec_integrated_display');
    const displaySizeField = document.getElementById('bulk_spec_display_size');

    if (!formFactorField || !integratedDisplayField) return;

    const normalizedFormFactor = (formFactorField.value || '').toString().trim().toLowerCase();
    const isAllInOne = normalizedFormFactor === 'all in one' || normalizedFormFactor === 'all-in-one' || normalizedFormFactor === 'allinone';

    if (isAllInOne) {
        integratedDisplayField.checked = true;
        integratedDisplayField.disabled = true;
    } else {
        integratedDisplayField.disabled = false;
    }

    if (displaySizeField) {
        const displaySizeGroup = displaySizeField.closest('.spec-field');
        if (displaySizeGroup) {
            displaySizeGroup.style.display = integratedDisplayField.checked ? 'block' : 'none';
        }
    }
}

function showBulkSpecsSection() {
    const section = document.getElementById('bulk-specs-section');
    if (section) section.style.display = 'block';
}

function hideBulkSpecsSection() {
    const section = document.getElementById('bulk-specs-section');
    const container = document.getElementById('bulk-dynamic-specs-container');

    if (section) section.style.display = 'none';
    if (container) container.innerHTML = '';
    renderBulkSpecsContextHelp();
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
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-boxes"></i> Registrar <span id="bulk-btn-quantity">0</span> Equipos';
            return;
        }

        // Mostrar modal de progreso
        showProgressModal(formData.items.length);

        // Enviar a la API de bulk create
        const response = await fetch('/api/help-desk/v2/inventory/bulk/create', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });

        if (!response.ok) {
            let errorData = {};
            try { errorData = await response.json(); } catch (_) {}
            throw new Error(extractErrorMessage(errorData, 'Error en registro masivo'));
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
    
    const separator = (form.querySelector('input[name="bulk-serial-separator"]:checked') || {}).value || 'newline';
    const supplierRaw = (form.querySelector('#bulk-supplier-serial-list') || {}).value || '';
    const itcjRaw    = (form.querySelector('#bulk-itcj-serial-list') || {}).value || '';
    const tecnmRaw   = (form.querySelector('#bulk-id-tecnm-list') || {}).value || '';

    const baseData = {
        category_id: parseInt(form.querySelector('#bulk-category-id').value),
        brand: form.querySelector('#bulk-brand').value.trim() || null,
        model: form.querySelector('#bulk-model').value.trim() || null,
        acquisition_date: form.querySelector('#bulk-acquisition-date').value || null,
        warranty_expiration: form.querySelector('#bulk-warranty-expiration').value || null,
        notes: form.querySelector('#bulk-notes').value.trim() || null,
        serial_separator: separator,
        supplier_serial_list: supplierRaw.trim() || null,
        itcj_serial_list: itcjRaw.trim() || null,
        id_tecnm_list: tecnmRaw.trim() || null,
        quantity: quantity,
        items: []
    };

    if (currentBulkCategory && currentBulkCategory.requires_specs && currentBulkCategory.spec_template) {
        const specifications = {};

        Object.keys(currentBulkCategory.spec_template).forEach(key => {
            const field = form.querySelector(`[name="bulk_spec_${key}"]`);
            if (field) {
                if (field.type === 'checkbox') {
                    specifications[key] = field.checked;
                } else if (field.value) {
                    specifications[key] = field.value;
                }
            }
        });

        normalizeComputerSpecificationsByCategory(specifications, currentBulkCategory);

        if (Object.keys(specifications).length > 0) {
            baseData.specifications = specifications;
        }
    }
    
    // Generar items individuales
    for (let i = 1; i <= quantity; i++) {
        const item = {
            supplier_serial: null,
            itcj_serial: null,
            id_tecnm: null
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
    const categorySelect = document.getElementById('bulk-category-id');
    const quantityInput = document.getElementById('bulk-quantity');

    if (!data.category_id) {
        categorySelect?.classList.add('is-invalid');
        showError('Debe seleccionar una categoría');
        return false;
    }
    categorySelect?.classList.remove('is-invalid');

    if (!data.items || data.items.length === 0) {
        quantityInput?.classList.add('is-invalid');
        showError('Debe especificar la cantidad de equipos');
        return false;
    }

    if (data.items.length > 100) {
        quantityInput?.classList.add('is-invalid');
        showError('No se pueden registrar más de 100 equipos de una vez');
        return false;
    }
    quantityInput?.classList.remove('is-invalid');

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

// ==================== CREAR USUARIO INACTIVO ====================

function _normalizeStr(s) {
    return (s || '').toLowerCase()
        .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .replace(/[^a-z0-9]/g, '');
}

function _generateUsernameCandidates(firstName, lastName, middleName) {
    const fn  = _normalizeStr(firstName.trim().split(/\s+/)[0]);   // primer nombre
    const fn2 = _normalizeStr((firstName.trim().split(/\s+/)[1] || ''));  // segundo nombre
    const ln  = _normalizeStr(lastName.trim().split(/\s+/)[0]);    // apellido paterno
    const ln2 = _normalizeStr(middleName ? middleName.trim().split(/\s+/)[0] : ''); // apellido materno

    const candidates = [];
    if (fn && ln)  candidates.push(fn[0] + ln);           // evillarreal
    if (fn && ln2) candidates.push(fn[0] + ln2);          // eibarra
    if (fn2 && ln) candidates.push(fn2[0] + ln);          // vvillarreal
    if (fn && ln)  candidates.push(fn + ln);              // ernestovillarreal
    return candidates.filter((v, i, a) => v.length > 1 && a.indexOf(v) === i);
}

let _usernameCandidates = [];
let _usernameIndex = 0;

function initCreateInactiveUser() {
    const btnOpen = document.getElementById('btn-create-inactive-user');
    if (!btnOpen) return;

    btnOpen.addEventListener('click', () => {
        _usernameCandidates = [];
        _usernameIndex = 0;
        document.getElementById('inactive-first-name').value = '';
        document.getElementById('inactive-last-name').value = '';
        document.getElementById('inactive-middle-name').value = '';
        document.getElementById('inactive-username').value = '';
        document.getElementById('inactive-email').value = '';
        document.getElementById('username-hint').textContent = 'Generado automáticamente. Puedes editarlo si hay conflicto.';
        $('#createInactiveUserModal').modal('show');
    });

    // Auto-generar username al escribir nombre/apellido
    ['inactive-first-name', 'inactive-last-name', 'inactive-middle-name'].forEach(id => {
        document.getElementById(id).addEventListener('input', () => {
            const fn = document.getElementById('inactive-first-name').value;
            const ln = document.getElementById('inactive-last-name').value;
            const mn = document.getElementById('inactive-middle-name').value;
            if (fn && ln) {
                _usernameCandidates = _generateUsernameCandidates(fn, ln, mn);
                _usernameIndex = 0;
                document.getElementById('inactive-username').value = _usernameCandidates[0] || '';
            }
        });
    });

    // Botón para rotar al siguiente candidato
    document.getElementById('btn-next-username').addEventListener('click', () => {
        if (_usernameCandidates.length === 0) return;
        _usernameIndex = (_usernameIndex + 1) % _usernameCandidates.length;
        const next = _usernameCandidates[_usernameIndex];
        document.getElementById('inactive-username').value = next || '';
        if (_usernameIndex === 0) {
            document.getElementById('username-hint').textContent = 'Volviste al inicio. Edítalo manualmente si ninguno funciona.';
        } else {
            document.getElementById('username-hint').textContent = `Variante ${_usernameIndex + 1} de ${_usernameCandidates.length}`;
        }
    });

    // Submit del modal
    document.getElementById('create-inactive-user-form').addEventListener('submit', handleCreateInactiveUser);
}

async function handleCreateInactiveUser(e) {
    e.preventDefault();

    const deptId = parseInt(document.getElementById('department-id')?.value);
    if (!deptId) {
        showError('Selecciona primero el departamento del equipo.');
        return;
    }

    const firstName  = document.getElementById('inactive-first-name').value.trim();
    const lastName   = document.getElementById('inactive-last-name').value.trim();
    const middleName = document.getElementById('inactive-middle-name').value.trim();
    const username   = document.getElementById('inactive-username').value.trim();
    const email      = document.getElementById('inactive-email').value.trim();

    if (!firstName || !lastName || !username) {
        showError('Nombre, apellido y username son obligatorios.');
        return;
    }

    const btn = document.getElementById('btn-confirm-inactive-user');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creando...';

    try {
        const res = await fetch('/api/core/v2/users/create-inactive', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                first_name: firstName,
                last_name: lastName,
                middle_name: middleName || null,
                email: email || null,
                username,
                department_id: deptId,
            }),
        });

        const data = await res.json();

        if (res.status === 409) {
            // Username en uso — rotar al siguiente candidato automáticamente
            const nextIdx = (_usernameIndex + 1) % (_usernameCandidates.length || 1);
            const nextUser = _usernameCandidates[nextIdx];
            if (nextUser && nextUser !== username) {
                _usernameIndex = nextIdx;
                document.getElementById('inactive-username').value = nextUser;
                document.getElementById('username-hint').textContent =
                    `"${username}" ya está en uso. Prueba con "${nextUser}" u edítalo.`;
            } else {
                document.getElementById('username-hint').textContent =
                    `"${username}" ya está en uso. Edítalo manualmente.`;
            }
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-save"></i> Crear usuario';
            return;
        }

        if (!res.ok) throw new Error(data.error || 'Error al crear usuario');

        // Éxito — agregar al select y seleccionarlo
        const newUser = data.data;
        const select = document.getElementById('assigned-to-user-id');
        const opt = document.createElement('option');
        opt.value = newUser.id;
        opt.textContent = `${newUser.full_name} (cuenta inactiva)`;
        opt.setAttribute('data-inactive', 'true');
        select.appendChild(opt);
        select.value = newUser.id;

        $('#createInactiveUserModal').modal('hide');
        showSuccess(`Usuario ${newUser.full_name} creado. Se seleccionó automáticamente.`);

    } catch (err) {
        showError(err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-save"></i> Crear usuario';
    }
}