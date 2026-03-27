/**
 * Lista de Equipos del Inventario
 * Filtros, búsqueda, paginación y acciones
 */

let currentPage = 1;
let totalPages = 1;
let totalItems = 0;
let perPage = 20;
let currentFilters = {};
let allCategories = [];
let allDepartments = [];
let pendingScrollRestore = 0;

document.addEventListener('DOMContentLoaded', function() {
    // Restore state if coming back from an item detail page
    if (/\/help-desk\/inventory\/items\/\d+/.test(document.referrer)) {
        const saved = HelpdeskUtils.NavState.load('inventory_items');
        if (saved) {
            document.getElementById('search-input').value = saved.search || '';
            document.getElementById('category-filter').value = saved.category_id || '';
            document.getElementById('status-filter').value = saved.status || '';
            document.getElementById('assigned-filter').value = saved.assigned || '';
            const deptEl = document.getElementById('department-filter');
            if (deptEl) deptEl.value = saved.department_id || '';
            currentFilters = saved.filters || {};
            currentPage = saved.page || 1;
            pendingScrollRestore = saved.scrollY || 0;
        }
    }

    initializeFilters();
    loadCategories();
    loadDepartments();
    loadItems(currentPage);
    
    // Event listeners
    document.getElementById('search-input').addEventListener('input', debounce(applyFilters, 500));
    document.getElementById('category-filter').addEventListener('change', applyFilters);
    document.getElementById('status-filter').addEventListener('change', applyFilters);
    document.getElementById('assigned-filter').addEventListener('change', applyFilters);
    
    const deptFilter = document.getElementById('department-filter');
    if (deptFilter) {
        deptFilter.addEventListener('change', applyFilters);
    }

    // Select all checkbox
    document.getElementById('select-all').addEventListener('change', function(e) {
        const checkboxes = document.querySelectorAll('#items-table tbody input[type="checkbox"]');
        checkboxes.forEach(cb => cb.checked = e.target.checked);
        updateBulkBar();
    });

    // Bulk transfer button
    const btnBulkTransfer = document.getElementById('btn-bulk-transfer');
    if (btnBulkTransfer) btnBulkTransfer.addEventListener('click', openBulkTransferModal);
    const btnBulkDeselect = document.getElementById('btn-bulk-deselect');
    if (btnBulkDeselect) btnBulkDeselect.addEventListener('click', () => {
        document.querySelectorAll('.item-checkbox, #select-all').forEach(cb => cb.checked = false);
        updateBulkBar();
    });
    const btnConfirmBulkTransfer = document.getElementById('btn-confirm-bulk-transfer');
    if (btnConfirmBulkTransfer) btnConfirmBulkTransfer.addEventListener('click', executeBulkTransfer);

    const btnBulkBaja = document.getElementById('btn-bulk-baja');
    if (btnBulkBaja) btnBulkBaja.addEventListener('click', () => {
        const ids = getSelectedItemIds();
        if (!ids.length) return;
        window.location.href = `/help-desk/inventory/retirement-requests/create?item_ids=${ids.join(',')}`;
    });

    const btnBulkLimbo = document.getElementById('btn-bulk-limbo');
    if (btnBulkLimbo) btnBulkLimbo.addEventListener('click', executeBulkLimbo);

    // Form submit - Cambiar estado
    document.getElementById('change-status-form').addEventListener('submit', handleChangeStatus);

    // Save state when navigating to an item detail
    document.addEventListener('click', function(e) {
        const link = e.target.closest('a[href]');
        if (link && /^\/help-desk\/inventory\/items\/\d+$/.test(link.getAttribute('href'))) {
            HelpdeskUtils.NavState.save('inventory_items', {
                search: document.getElementById('search-input').value,
                category_id: document.getElementById('category-filter').value,
                status: document.getElementById('status-filter').value,
                assigned: document.getElementById('assigned-filter').value,
                department_id: document.getElementById('department-filter')?.value || '',
                filters: currentFilters,
                page: currentPage,
                scrollY: window.scrollY,
            });
        }
    });
});

// ==================== CARGAR DATOS ====================
async function loadItems(page = 1) {
    showLoading();
    currentPage = page;

    try {
        // Construir query params
        const params = new URLSearchParams({
            page: page,
            per_page: perPage
        });

        if (currentFilters.search) params.append('search', currentFilters.search);
        if (currentFilters.category_id) params.append('category_id', currentFilters.category_id);
        if (currentFilters.status) params.append('status', currentFilters.status);
        if (currentFilters.assigned) params.append('assigned', currentFilters.assigned);
        if (currentFilters.department_id) params.append('department_id', currentFilters.department_id);

        const response = await fetch(`/api/help-desk/v2/inventory/items?${params}`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || errorData.message || 'Error al cargar inventario');
        }

        const result = await response.json();

        totalItems = result.total;
        totalPages = result.total_pages;

        renderTable(result.data);
        renderPagination();
        updateStats();
        hideLoading();

        if (pendingScrollRestore > 0) {
            const sy = pendingScrollRestore;
            pendingScrollRestore = 0;
            requestAnimationFrame(() => window.scrollTo({ top: sy, behavior: 'instant' }));
        }

    } catch (error) {
        console.error('Error:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`No se pudo cargar el inventario: ${errorMessage}`);
        hideLoading();
    }
}

async function loadCategories() {
    try {
        const response = await fetch('/api/help-desk/v2/inventory/categories?active=true', {
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

        const select = document.getElementById('category-filter');
        select.innerHTML = '<option value="">Todas las categorías</option>';

        allCategories.forEach(cat => {
            const option = document.createElement('option');
            option.value = cat.id;
            option.textContent = cat.name;
            select.appendChild(option);
        });

    } catch (error) {
        console.error('Error cargando categorías:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`No se pudieron cargar las categorías: ${errorMessage}`);
    }
}

async function loadDepartments() {
    const deptFilter = document.getElementById('department-filter');
    if (!deptFilter) return; // No disponible para jefes de depto

    try {
        const response = await fetch('/api/core/v2/departments?active=true', {
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

        deptFilter.innerHTML = '<option value="">Todos los departamentos</option>';

        allDepartments.forEach(dept => {
            const option = document.createElement('option');
            option.value = dept.id;
            option.textContent = dept.name;
            deptFilter.appendChild(option);
        });

    } catch (error) {
        console.error('Error cargando departamentos:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`No se pudieron cargar los departamentos: ${errorMessage}`);
    }
}

// ==================== RENDERIZADO ====================
function renderTable(items) {
    const tbody = document.querySelector('#items-table tbody');
    
    if (items.length === 0) {
        document.getElementById('table-container').style.display = 'none';
        document.getElementById('empty-state').style.display = 'block';
        return;
    }

    document.getElementById('table-container').style.display = 'block';
    document.getElementById('empty-state').style.display = 'none';

    // Reset select-all and bulk bar after render
    const selectAllCb = document.getElementById('select-all');
    if (selectAllCb) selectAllCb.checked = false;

    const tbodyHtml = items.map(item => {
        const statusBadge = getStatusBadge(item.status);
        const warrantyIndicator = getWarrantyIndicator(item);
        const categoryIcon = getCategoryIcon(item.category?.icon);

        return `
            <tr>
                <td>
                    <input type="checkbox" class="item-checkbox" data-item-id="${item.id}"
                           onchange="updateBulkBar()">
                </td>
                <td>
                    <a href="/help-desk/inventory/items/${item.id}" class="font-weight-bold">
                        ${item.inventory_number}
                    </a>
                </td>
                <td>
                    <i class="${categoryIcon} mr-1"></i>
                    <small>${item.category?.name || 'N/A'}</small>
                </td>
                <td>
                    <div class="font-weight-bold">${item.brand || 'N/A'}</div>
                    <small class="text-muted">${item.model || ''}</small>
                </td>
                <td>${buildSerialsCell(item)}</td>
                <td>
                    <small>${item.department?.name || 'N/A'}</small>
                </td>
                <td>
                    ${item.assigned_to_user ? `
                        <div>
                            <i class="fas fa-user-check text-info mr-1"></i>
                            <small>${item.assigned_to_user.full_name}</small>
                        </div>
                    ` : `
                        <span class="badge bg-secondary text-white">Global</span>
                    `}
                </td>
                <td>
                    <span class="badge bg-${statusBadge.color} text-white status-badge">
                        ${statusBadge.text}
                    </span>
                </td>
                <td>
                    ${warrantyIndicator.html}
                </td>
                <td class="text-center table-actions">
                    <div class="btn-group btn-group-sm">
                        <a href="/help-desk/inventory/items/${item.id}" 
                           class="btn btn-sm btn-outline-primary" 
                           title="Ver detalle">
                            <i class="fas fa-eye"></i>
                        </a>
                        <button class="btn btn-sm btn-outline-secondary" 
                                onclick="showQuickActions(${item.id})" 
                                title="Acciones">
                            <i class="fas fa-ellipsis-v"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
    tbody.innerHTML = tbodyHtml;
    updateBulkBar();
}

function renderPagination() {
    const container = document.getElementById('pagination-container');
    
    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    let html = '';

    // Previous
    html += `
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="loadItems(${currentPage - 1}); return false;">
                <i class="fas fa-chevron-left"></i>
            </a>
        </li>
    `;

    // Pages
    const maxVisible = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    let endPage = Math.min(totalPages, startPage + maxVisible - 1);

    if (endPage - startPage < maxVisible - 1) {
        startPage = Math.max(1, endPage - maxVisible + 1);
    }

    if (startPage > 1) {
        html += `<li class="page-item"><a class="page-link" href="#" onclick="loadItems(1); return false;">1</a></li>`;
        if (startPage > 2) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
    }

    for (let i = startPage; i <= endPage; i++) {
        html += `
            <li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#" onclick="loadItems(${i}); return false;">${i}</a>
            </li>
        `;
    }

    if (endPage < totalPages) {
        if (endPage < totalPages - 1) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        html += `<li class="page-item"><a class="page-link" href="#" onclick="loadItems(${totalPages}); return false;">${totalPages}</a></li>`;
    }

    // Next
    html += `
        <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="loadItems(${currentPage + 1}); return false;">
                <i class="fas fa-chevron-right"></i>
            </a>
        </li>
    `;

    container.innerHTML = html;
}

function updateStats() {
    const from = totalItems === 0 ? 0 : (currentPage - 1) * perPage + 1;
    const to = Math.min(currentPage * perPage, totalItems);

    document.getElementById('showing-from').textContent = from;
    document.getElementById('showing-to').textContent = to;
    document.getElementById('showing-total').textContent = totalItems;

    document.getElementById('total-items-text').textContent = 
        `${totalItems} equipo${totalItems !== 1 ? 's' : ''} en total`;
}

// ==================== FILTROS ====================
function initializeFilters() {
    currentFilters = {};
}

function applyFilters() {
    currentFilters = {
        search: document.getElementById('search-input').value.trim() || null,
        category_id: document.getElementById('category-filter').value || null,
        status: document.getElementById('status-filter').value || null,
        assigned: document.getElementById('assigned-filter').value || null
    };

    const deptFilter = document.getElementById('department-filter');
    if (deptFilter) {
        currentFilters.department_id = deptFilter.value || null;
    }

    renderActiveFilters();
    loadItems(1); // Reset a página 1
}

function renderActiveFilters() {
    const container = document.getElementById('active-filters');
    const filters = [];

    if (currentFilters.search) {
        filters.push({
            label: `Búsqueda: "${currentFilters.search}"`,
            key: 'search'
        });
    }

    if (currentFilters.category_id) {
        const cat = allCategories.find(c => c.id == currentFilters.category_id);
        if (cat) {
            filters.push({
                label: `Categoría: ${cat.name}`,
                key: 'category_id'
            });
        }
    }

    if (currentFilters.status) {
        const statusLabels = {
            'ACTIVE': 'Activo',
            'MAINTENANCE': 'Mantenimiento',
            'DAMAGED': 'Dañado',
            'LOST': 'Extraviado'
        };
        filters.push({
            label: `Estado: ${statusLabels[currentFilters.status]}`,
            key: 'status'
        });
    }

    if (currentFilters.assigned) {
        const assignedLabels = {
            'yes': 'Asignados',
            'no': 'Globales'
        };
        filters.push({
            label: `Asignación: ${assignedLabels[currentFilters.assigned]}`,
            key: 'assigned'
        });
    }

    if (currentFilters.department_id) {
        const dept = allDepartments.find(d => d.id == currentFilters.department_id);
        if (dept) {
            filters.push({
                label: `Departamento: ${dept.name}`,
                key: 'department_id'
            });
        }
    }

    container.innerHTML = filters.map(filter => `
        <span class="filter-chip">
            ${filter.label}
            <span class="close" onclick="removeFilter('${filter.key}')">&times;</span>
        </span>
    `).join('');
}

function removeFilter(key) {
    currentFilters[key] = null;
    
    // Actualizar controles
    if (key === 'search') document.getElementById('search-input').value = '';
    if (key === 'category_id') document.getElementById('category-filter').value = '';
    if (key === 'status') document.getElementById('status-filter').value = '';
    if (key === 'assigned') document.getElementById('assigned-filter').value = '';
    if (key === 'department_id' && document.getElementById('department-filter')) {
        document.getElementById('department-filter').value = '';
    }

    renderActiveFilters();
    loadItems(1);
}

function clearFilters() {
    document.getElementById('filters-form').reset();
    initializeFilters();
    renderActiveFilters();
    HelpdeskUtils.NavState.clear('inventory_items');
    loadItems(1);
}

// ==================== ACCIONES ====================
function showQuickActions(itemId) {
    const modal = $('#quickActionsModal');
    const body = document.getElementById('quick-actions-body');

    body.innerHTML = `
        <div class="list-group">
            <a href="/help-desk/inventory/items/${itemId}" class="list-group-item list-group-item-action">
                <i class="fas fa-eye text-primary mr-2"></i> Ver Detalle
            </a>
            <button class="list-group-item list-group-item-action" onclick="openChangeStatus(${itemId})">
                <i class="fas fa-toggle-on text-warning mr-2"></i> Cambiar Estado
            </button>
            <button class="list-group-item list-group-item-action" onclick="openAssignModal(${itemId})">
                <i class="fas fa-user-plus text-info mr-2"></i> Asignar a Usuario
            </button>
            <button class="list-group-item list-group-item-action text-danger"
                    onclick="window.location='/help-desk/inventory/retirement-requests/create?item_id=${itemId}'">
                <i class="fas fa-file-alt mr-2"></i> Solicitar Baja
            </button>
            <button class="list-group-item list-group-item-action text-warning"
                    onclick="sendSingleToLimbo(${itemId})">
                <i class="fas fa-inbox mr-2"></i> Enviar al Limbo
            </button>
        </div>
    `;

    modal.modal('show');
}

function openChangeStatus(itemId) {
    $('#quickActionsModal').modal('hide');
    document.getElementById('change-status-item-id').value = itemId;
    $('#changeStatusModal').modal('show');
}

async function handleChangeStatus(e) {
    e.preventDefault();

    const itemId = document.getElementById('change-status-item-id').value;
    const newStatus = document.getElementById('new-status').value;
    const notes = document.getElementById('status-notes').value;

    if (!newStatus) {
        showToast('Debes seleccionar un estado', 'error');
        return;
    }

    try {
        const response = await fetch(`/api/help-desk/v2/inventory/items/${itemId}/status`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ status: newStatus, notes })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || error.message || 'Error al cambiar estado');
        }

        $('#changeStatusModal').modal('hide');
        showSuccess('Estado actualizado correctamente');
        loadItems(currentPage); // Recargar

    } catch (error) {
        console.error('Error:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`Error al cambiar estado: ${errorMessage}`);
    }
}

// ==================== EXPORTAR ====================
function exportToExcel() {
    showToast('Función de exportación en desarrollo', 'info');
    // TODO: Implementar exportación a Excel
}

// ==================== HELPERS ====================
function getStatusBadge(status) {
    const badges = {
        'ACTIVE': { color: 'success', text: 'Activo' },
        'MAINTENANCE': { color: 'warning', text: 'Mantenimiento' },
        'DAMAGED': { color: 'danger', text: 'Dañado' },
        'RETIRED': { color: 'secondary', text: 'Retirado' },
        'LOST': { color: 'dark', text: 'Extraviado' }
    };
    return badges[status] || { color: 'secondary', text: status };
}

function getWarrantyIndicator(item) {
    if (!item.warranty_expiration) {
        return { html: '<small class="text-muted">Sin info</small>' };
    }

    if (item.is_under_warranty) {
        const days = item.warranty_days_remaining;
        let className = 'active';
        let text = `${days} días`;

        if (days <= 30) {
            className = 'expiring';
            text = `⚠️ ${days} días`;
        }

        return {
            html: `
                <span class="warranty-indicator ${className}"></span>
                <small>${text}</small>
            `
        };
    } else {
        return {
            html: `
                <span class="warranty-indicator expired"></span>
                <small class="text-danger">Vencida</small>
            `
        };
    }
}

function getCategoryIcon(icon) {
    return icon || 'fas fa-box';
}

function buildSerialsCell(item) {
    const parts = [];
    if (item.supplier_serial) {
        parts.push(`<small class="d-block text-truncate" style="max-width:120px;" title="Serial Proveedor: ${escapeHtml(item.supplier_serial)}"><span class="text-muted">Prov:</span> ${escapeHtml(item.supplier_serial)}</small>`);
    }
    if (item.itcj_serial) {
        parts.push(`<small class="d-block text-truncate" style="max-width:120px;" title="Serial ITCJ: ${escapeHtml(item.itcj_serial)}"><span class="text-muted">ITCJ:</span> ${escapeHtml(item.itcj_serial)}</small>`);
    }
    if (item.id_tecnm) {
        parts.push(`<small class="d-block text-truncate" style="max-width:120px;" title="ID TecNM: ${escapeHtml(item.id_tecnm)}"><span class="text-muted">TecNM:</span> ${escapeHtml(item.id_tecnm)}</small>`);
    }
    return parts.length ? parts.join('') : '<small class="text-muted">—</small>';
}

function escapeHtml(text) {
    if (!text) return '';
    return String(text).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
}

function showLoading() {
    document.getElementById('loading-container').style.display = 'block';
    document.getElementById('table-container').style.display = 'none';
    document.getElementById('empty-state').style.display = 'none';
}

function hideLoading() {
    document.getElementById('loading-container').style.display = 'none';
}

function showSuccess(message) {
    // Implementar con tu librería de notificaciones (toastr, sweetalert, etc.)
    showToast(message, 'success');
}

function showError(message) {
    showToast(message, 'error');
}

function debounce(func, wait) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

// ==================== SELECCIÓN / ACCIONES MASIVAS ====================
function getSelectedItemIds() {
    return Array.from(document.querySelectorAll('.item-checkbox:checked'))
        .map(cb => parseInt(cb.dataset.itemId));
}

function updateBulkBar() {
    const ids = getSelectedItemIds();
    const bar = document.getElementById('bulk-action-bar');
    const countEl = document.getElementById('bulk-selected-count');
    if (!bar) return;
    if (ids.length > 0) {
        bar.style.display = '';
        if (countEl) countEl.textContent = ids.length;
    } else {
        bar.style.display = 'none';
    }
}

function openBulkTransferModal() {
    const ids = getSelectedItemIds();
    if (!ids.length) return;

    const countEl = document.getElementById('bulk-transfer-count');
    if (countEl) countEl.textContent = ids.length;

    // Populate department select from already-loaded allDepartments
    const deptSelect = document.getElementById('bulk-transfer-dept');
    if (deptSelect && allDepartments.length) {
        deptSelect.innerHTML = '<option value="">Seleccionar...</option>';
        allDepartments.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.id;
            opt.textContent = d.name;
            deptSelect.appendChild(opt);
        });
    }

    $('#bulkTransferModal').modal('show');
}

async function executeBulkTransfer() {
    const ids = getSelectedItemIds();
    const deptId = parseInt(document.getElementById('bulk-transfer-dept').value);
    if (!deptId) { showToast('Selecciona un departamento destino', 'error'); return; }

    const btn = document.getElementById('btn-confirm-bulk-transfer');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Transfiriendo...'; }

    try {
        const res = await fetch('/api/help-desk/v2/inventory/items/bulk-transfer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
            body: JSON.stringify({ item_ids: ids, target_department_id: deptId }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Error al transferir');

        $('#bulkTransferModal').modal('hide');
        document.querySelectorAll('.item-checkbox, #select-all').forEach(cb => cb.checked = false);
        updateBulkBar();

        const transferred = data.transferred_ids ? data.transferred_ids.length : 0;
        const errors = data.errors ? data.errors.length : 0;
        let msg = `${transferred} equipo(s) transferido(s) correctamente.`;
        if (errors) msg += ` ${errors} con errores.`;
        showToast(msg, transferred > 0 ? 'success' : 'error');
        loadItems(currentPage);

    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-exchange-alt"></i> Transferir'; }
    }
}

async function executeBulkLimbo() {
    const ids = getSelectedItemIds();
    if (!ids.length) return;
    if (!await HelpdeskUtils.confirmDialog('Enviar al limbo', `¿Enviar ${ids.length} equipo(s) al limbo? Quedarán sin departamento ni usuario asignado.`)) return;

    const btn = document.getElementById('btn-bulk-limbo');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>'; }

    try {
        const res = await fetch('/api/help-desk/v2/inventory/items/bulk-send-to-limbo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
            body: JSON.stringify({ item_ids: ids }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Error al enviar al limbo');

        document.querySelectorAll('.item-checkbox, #select-all').forEach(cb => cb.checked = false);
        updateBulkBar();

        const sent = data.sent_ids ? data.sent_ids.length : 0;
        const errors = data.errors ? data.errors.length : 0;
        let msg = `${sent} equipo(s) enviado(s) al limbo.`;
        if (errors) msg += ` ${errors} con errores.`;
        showToast(msg, sent > 0 ? 'success' : 'error');
        loadItems(currentPage);

    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-inbox"></i> Limbo'; }
    }
}

async function sendSingleToLimbo(itemId) {
    $('#quickActionsModal').modal('hide');
    if (!await HelpdeskUtils.confirmDialog('Enviar al limbo', '¿Enviar este equipo al limbo? Quedará sin departamento ni usuario asignado.')) return;

    try {
        const res = await fetch('/api/help-desk/v2/inventory/items/bulk-send-to-limbo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
            body: JSON.stringify({ item_ids: [itemId] }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Error al enviar al limbo');
        showToast('Equipo enviado al limbo correctamente', 'success');
        loadItems(currentPage);
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
}