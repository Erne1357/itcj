/**
 * Detalle de Grupo de Equipos
 * Visualización y gestión de equipos dentro de un grupo
 */

let currentGroup = null;
let groupEquipment = [];
let availableEquipment = [];
let allCategories = [];

document.addEventListener('DOMContentLoaded', function() {
    loadCategories();
    loadGroupDetail();
    
    // Event listeners
    document.getElementById('equipment-search').addEventListener('input', debounce(filterGroupEquipment, 300));
    document.getElementById('equipment-category-filter').addEventListener('change', filterGroupEquipment);
    document.getElementById('equipment-status-filter').addEventListener('change', filterGroupEquipment);
    
    // Select all
    const selectAllCheckbox = document.getElementById('select-all-equipment');
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', function(e) {
            document.querySelectorAll('.equipment-item-checkbox').forEach(cb => {
                cb.checked = e.target.checked;
            });
            updateRemoveButton();
        });
    }

    // Select all available
    document.getElementById('select-all-available').addEventListener('change', function(e) {
        document.querySelectorAll('.available-equipment-checkbox').forEach(cb => {
            cb.checked = e.target.checked;
        });
        updateSelectedCount();
    });
});

// ==================== CARGAR DATOS ====================
async function loadGroupDetail() {
    showLoading();

    try {
        const response = await fetch(`/api/help-desk/v1/inventory/groups/${GROUP_ID}`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            if (response.status === 404) {
                showError('Grupo no encontrado');
                setTimeout(() => window.location.href = '/help-desk/inventory/groups', 2000);
                return;
            }
            throw new Error('Error al cargar grupo');
        }

        const result = await response.json();
        currentGroup = result.data;

        console.log('Grupo cargado:', result);

        renderGroupHeader();
        renderStatistics();
        renderCapacities();
        loadGroupEquipment();

    } catch (error) {
        console.error('Error:', error);
        showError('No se pudo cargar el grupo');
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

        // Llenar filtros
        const filters = ['equipment-category-filter', 'available-category-filter'];
        filters.forEach(filterId => {
            const select = document.getElementById(filterId);
            select.innerHTML = '<option value="">Todas las categorías</option>';
            allCategories.forEach(cat => {
                const option = document.createElement('option');
                option.value = cat.id;
                option.textContent = cat.name;
                select.appendChild(option);
            });
        });

    } catch (error) {
        console.error('Error cargando categorías:', error);
    }
}

async function loadGroupEquipment() {
    document.getElementById('equipment-loading').style.display = 'block';
    document.getElementById('equipment-table-container').style.display = 'none';
    document.getElementById('equipment-empty').style.display = 'none';

    try {
        const response = await fetch(`/api/help-desk/v1/inventory/selection/by-group/${GROUP_ID}`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar equipos');

        const result = await response.json();
        groupEquipment = result.items_by_category.flatMap(cat => cat.items);

        renderGroupEquipment(groupEquipment);

    } catch (error) {
        console.error('Error:', error);
        showError('No se pudieron cargar los equipos del grupo');
    } finally {
        document.getElementById('equipment-loading').style.display = 'none';
    }
}

async function loadAvailableEquipment() {
    if (!currentGroup) return;

    document.getElementById('available-equipment-loading').style.display = 'block';
    document.getElementById('available-equipment-container').style.display = 'none';
    document.getElementById('available-equipment-empty').style.display = 'none';

    try {
        const params = new URLSearchParams({
            department_id: currentGroup.department_id,
            include_group_equipment: 'false'
        });

        const search = document.getElementById('available-search').value.trim();
        if (search) params.append('search', search);

        const categoryId = document.getElementById('available-category-filter').value;
        if (categoryId) params.append('category_id', categoryId);

        const response = await fetch(`/api/help-desk/v1/inventory/items?${params}`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar equipos disponibles');

        const result = await response.json();
        availableEquipment = result.data.filter(item => !item.group_id);

        renderAvailableEquipment(availableEquipment);

    } catch (error) {
        console.error('Error:', error);
        showError('No se pudieron cargar los equipos disponibles');
    } finally {
        document.getElementById('available-equipment-loading').style.display = 'none';
    }
}

// ==================== RENDERIZADO ====================
function renderGroupHeader() {
    const typeInfo = getGroupTypeInfo(currentGroup.type);

    document.getElementById('group-icon').className = typeInfo.icon + ' mr-2';
    document.getElementById('group-name').textContent = currentGroup.name;
    document.getElementById('group-description').textContent = currentGroup.description || '';
    document.getElementById('group-type-badge').textContent = typeInfo.label;
    document.getElementById('group-type-badge').className = `badge bg-${typeInfo.color} text-white mr-2`;
    document.getElementById('group-department').textContent = currentGroup.department?.name || 'N/A';

    // Ubicación
    if (currentGroup.building || currentGroup.floor) {
        let locationText = '';
        if (currentGroup.building) locationText += `Edificio ${currentGroup.building}`;
        if (currentGroup.floor) locationText += ` - Piso ${currentGroup.floor}`;
        if (currentGroup.location_notes) locationText += ` (${currentGroup.location_notes})`;

        document.getElementById('location-text').textContent = locationText;
        document.getElementById('location-info').style.display = 'block';
    }

    hideLoading();
}

function renderStatistics() {
    const capacities = currentGroup.capacities || [];
    const totalCapacity = capacities.reduce((sum, cap) => sum + (cap.max_capacity || 0), 0);
    const totalCurrent = capacities.reduce((sum, cap) => sum + (cap.current_count || 0), 0);
    const occupancy = totalCapacity > 0 ? Math.round((totalCurrent / totalCapacity) * 100) : 0;

    document.getElementById('stat-total').textContent = totalCurrent;
    document.getElementById('stat-capacity').textContent = totalCapacity;
    document.getElementById('stat-occupancy').textContent = occupancy + '%';
    document.getElementById('stat-categories').textContent = capacities.length;
}

function renderCapacities() {
    const container = document.getElementById('capacities-list');
    const capacities = currentGroup.capacities || [];

    if (capacities.length === 0) {
        container.innerHTML = '<p class="text-muted">No hay capacidades definidas para este grupo</p>';
        return;
    }

    container.innerHTML = capacities.map(cap => {
        const category = allCategories.find(c => c.id === cap.category_id);
        const percentage = cap.max_capacity > 0 ? Math.round((cap.current_count / cap.max_capacity) * 100) : 0;
        const progressClass = percentage <= 50 ? 'success' : percentage <= 80 ? 'warning' : 'danger';

        return `
            <div class="mb-3">
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <div>
                        <i class="${category?.icon || 'fas fa-box'} mr-2"></i>
                        <strong>${category?.name || 'N/A'}</strong>
                    </div>
                    <div>
                        <span class="badge bg-${progressClass} text-white">
                            ${cap.current_count} / ${cap.max_capacity}
                        </span>
                    </div>
                </div>
                <div class="progress capacity-progress">
                    <div 
                        class="progress-bar bg-${progressClass}" 
                        style="width: ${percentage}%"
                        role="progressbar"
                    >
                        ${percentage}%
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function renderGroupEquipment(equipment) {
    const tbody = document.querySelector('#equipment-table tbody');

    if (equipment.length === 0) {
        document.getElementById('equipment-empty').style.display = 'block';
        return;
    }

    document.getElementById('equipment-table-container').style.display = 'block';

    tbody.innerHTML = equipment.map(item => {
        const statusBadge = getStatusBadge(item.status);
        const category = allCategories.find(c => c.id === item.category_id);

        return `
            <tr class="equipment-item">
                ${document.getElementById('select-all-equipment') ? `
                    <td>
                        <input 
                            type="checkbox" 
                            class="equipment-checkbox equipment-item-checkbox" 
                            data-item-id="${item.id}"
                            onchange="updateRemoveButton()"
                        >
                    </td>
                ` : ''}
                <td>
                    <a href="/help-desk/inventory/items/${item.id}" class="font-weight-bold">
                        ${item.inventory_number}
                    </a>
                </td>
                <td>
                    <i class="${category?.icon || 'fas fa-box'} mr-1"></i>
                    <small>${category?.name || 'N/A'}</small>
                </td>
                <td>
                    <div class="font-weight-bold">${item.brand || 'N/A'}</div>
                    <small class="text-muted">${item.model || ''}</small>
                </td>
                <td>
                    <span class="badge bg-${statusBadge.color} text-white">
                        ${statusBadge.text}
                    </span>
                </td>
                <td>
                    <small>${item.location_detail || 'N/A'}</small>
                </td>
                <td class="text-center">
                    <div class="btn-group btn-group-sm">
                        <a href="/help-desk/inventory/items/${item.id}" 
                           class="btn btn-sm btn-outline-primary"
                           title="Ver detalle">
                            <i class="fas fa-eye"></i>
                        </a>
                        ${document.getElementById('select-all-equipment') ? `
                            <button 
                                class="btn btn-sm btn-outline-danger" 
                                onclick="removeEquipmentFromGroup(${item.id})"
                                title="Remover del grupo">
                                <i class="fas fa-times"></i>
                            </button>
                        ` : ''}
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function renderAvailableEquipment(equipment) {
    const tbody = document.getElementById('available-equipment-tbody');

    if (equipment.length === 0) {
        document.getElementById('available-equipment-empty').style.display = 'block';
        return;
    }

    document.getElementById('available-equipment-container').style.display = 'block';

    tbody.innerHTML = equipment.map(item => {
        const statusBadge = getStatusBadge(item.status);
        const category = allCategories.find(c => c.id === item.category_id);

        return `
            <tr>
                <td>
                    <input 
                        type="checkbox" 
                        class="equipment-checkbox available-equipment-checkbox" 
                        data-item-id="${item.id}"
                        onchange="updateSelectedCount()"
                    >
                </td>
                <td>${item.inventory_number}</td>
                <td>
                    <i class="${category?.icon || 'fas fa-box'} mr-1"></i>
                    ${category?.name || 'N/A'}
                </td>
                <td>
                    ${item.brand || 'N/A'} ${item.model || ''}
                </td>
                <td>
                    <span class="badge bg-${statusBadge.color} text-white badge-sm">
                        ${statusBadge.text}
                    </span>
                </td>
            </tr>
        `;
    }).join('');
}

// ==================== FILTROS ====================
function filterGroupEquipment() {
    const search = document.getElementById('equipment-search').value.toLowerCase();
    const categoryId = document.getElementById('equipment-category-filter').value;
    const status = document.getElementById('equipment-status-filter').value;

    let filtered = [...groupEquipment];

    if (search) {
        filtered = filtered.filter(item =>
            item.inventory_number.toLowerCase().includes(search) ||
            (item.brand && item.brand.toLowerCase().includes(search)) ||
            (item.model && item.model.toLowerCase().includes(search))
        );
    }

    if (categoryId) {
        filtered = filtered.filter(item => item.category_id == categoryId);
    }

    if (status) {
        filtered = filtered.filter(item => item.status === status);
    }

    renderGroupEquipment(filtered);
}

// ==================== ACCIONES ====================
function openAddEquipmentModal() {
    loadAvailableEquipment();
    $('#addEquipmentModal').modal('show');
}

async function addSelectedEquipment() {
    const checkboxes = document.querySelectorAll('.available-equipment-checkbox:checked');
    
    if (checkboxes.length === 0) {
        showError('Selecciona al menos un equipo');
        return;
    }

    const itemIds = Array.from(checkboxes).map(cb => parseInt(cb.dataset.itemId));

    try {
        const response = await fetch(`/api/help-desk/v1/inventory/groups/${GROUP_ID}/items`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ item_ids: itemIds })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error al agregar equipos');
        }

        $('#addEquipmentModal').modal('hide');
        showSuccess(`${itemIds.length} equipo(s) agregado(s) al grupo`);
        
        // Recargar
        loadGroupDetail();

    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
    }
}

async function removeEquipmentFromGroup(itemId) {
    if (!confirm('¿Remover este equipo del grupo?')) return;

    try {
        const response = await fetch(`/api/help-desk/v1/inventory/groups/${GROUP_ID}/items/${itemId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error al remover equipo');
        }

        showSuccess('Equipo removido del grupo');
        loadGroupDetail();

    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
    }
}

async function removeSelectedEquipment() {
    const checkboxes = document.querySelectorAll('.equipment-item-checkbox:checked');
    
    if (checkboxes.length === 0) {
        showError('Selecciona al menos un equipo');
        return;
    }

    if (!confirm(`¿Remover ${checkboxes.length} equipo(s) del grupo?`)) return;

    const itemIds = Array.from(checkboxes).map(cb => parseInt(cb.dataset.itemId));

    try {
        // Remover uno por uno
        for (const itemId of itemIds) {
            await fetch(`/api/help-desk/v1/inventory/groups/${GROUP_ID}/items/${itemId}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`
                }
            });
        }

        showSuccess(`${itemIds.length} equipo(s) removido(s) del grupo`);
        loadGroupDetail();

    } catch (error) {
        console.error('Error:', error);
        showError('Error al remover equipos');
    }
}

function updateRemoveButton() {
    const checked = document.querySelectorAll('.equipment-item-checkbox:checked').length;
    const btn = document.getElementById('remove-selected-btn');
    if (btn) {
        btn.style.display = checked > 0 ? 'inline-block' : 'none';
        btn.textContent = `Remover ${checked} Seleccionado(s)`;
    }
}

function updateSelectedCount() {
    const count = document.querySelectorAll('.available-equipment-checkbox:checked').length;
    document.getElementById('selected-count').textContent = count;
}

function editGroup() {
    window.location.href = `/help-desk/inventory/groups?edit=${GROUP_ID}`;
}

async function confirmDeleteGroup() {
    if (!confirm('¿Eliminar este grupo? Los equipos NO serán eliminados, solo se removerán del grupo.')) return;

    try {
        const response = await fetch(`/api/help-desk/v1/inventory/groups/${GROUP_ID}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error al eliminar grupo');
        }

        showSuccess('Grupo eliminado');
        setTimeout(() => window.location.href = '/help-desk/inventory/groups', 1500);

    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
    }
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

function getStatusBadge(status) {
    const badges = {
        'ACTIVE': { color: 'success', text: 'Activo' },
        'MAINTENANCE': { color: 'warning', text: 'Mantenimiento' },
        'DAMAGED': { color: 'danger', text: 'Dañado' },
        'RETIRED': { color: 'secondary', text: 'Retirado' },
        'LOST': { color: 'dark', text: 'Extraviado' },
        'PENDING_ASSIGNMENT': { color: 'warning', text: 'Pendiente' }
    };
    return badges[status] || { color: 'secondary', text: status };
}

function showLoading() {
    document.getElementById('loading-container').style.display = 'block';
    document.getElementById('main-content').style.display = 'none';
}

function hideLoading() {
    document.getElementById('loading-container').style.display = 'none';
    document.getElementById('main-content').style.display = 'block';
}

function showSuccess(message) {
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