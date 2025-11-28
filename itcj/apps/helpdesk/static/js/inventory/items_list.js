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

document.addEventListener('DOMContentLoaded', function() {
    initializeFilters();
    loadCategories();
    loadDepartments();
    loadItems();
    
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
    });

    // Form submit - Cambiar estado
    document.getElementById('change-status-form').addEventListener('submit', handleChangeStatus);
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

        const response = await fetch(`/api/help-desk/v1/inventory/items?${params}`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar inventario');

        const result = await response.json();
        
        totalItems = result.total;
        totalPages = result.total_pages;
        
        renderTable(result.data);
        renderPagination();
        updateStats();
        hideLoading();

    } catch (error) {
        console.error('Error:', error);
        showError('No se pudo cargar el inventario');
        hideLoading();
    }
}

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
    }
}

async function loadDepartments() {
    const deptFilter = document.getElementById('department-filter');
    if (!deptFilter) return; // No disponible para jefes de depto

    try {
        const response = await fetch('/api/core/v1/departments?active=true', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar departamentos');

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

    tbody.innerHTML = items.map(item => {
        const statusBadge = getStatusBadge(item.status);
        const warrantyIndicator = getWarrantyIndicator(item);
        const categoryIcon = getCategoryIcon(item.category?.icon);

        return `
            <tr>
                <td>
                    <input type="checkbox" class="item-checkbox" data-item-id="${item.id}">
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
                        <span class="badge badge-secondary">Global</span>
                    `}
                </td>
                <td>
                    <span class="badge badge-${statusBadge.color} status-badge">
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
            <button class="list-group-item list-group-item-action text-danger" onclick="confirmDeactivate(${itemId})">
                <i class="fas fa-trash-alt mr-2"></i> Dar de Baja
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
        const response = await fetch(`/api/help-desk/v1/inventory/items/${itemId}/status`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ status: newStatus, notes })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error al cambiar estado');
        }

        $('#changeStatusModal').modal('hide');
        showSuccess('Estado actualizado correctamente');
        loadItems(currentPage); // Recargar

    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
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