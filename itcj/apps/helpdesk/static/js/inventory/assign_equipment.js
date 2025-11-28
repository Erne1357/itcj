/**
 * Gestión de Asignaciones de Equipos
 * Interfaz para Jefes de Departamento
 */

let currentDepartment = null;
let departmentUsers = [];
let departmentEquipment = [];
let departmentGroups = []; // NUEVO
let selectedUser = null;
let allCategories = [];

document.addEventListener('DOMContentLoaded', function() {
    loadInitialData();
    setupEventListeners();
});

// ==================== SETUP ====================
function setupEventListeners() {
    // Búsqueda de usuarios
    document.getElementById('search-users').addEventListener('input', filterUsers);

    // Filtros de equipos
    document.getElementById('filter-category').addEventListener('change', filterEquipment);
    document.getElementById('filter-equipment').addEventListener('input', filterEquipment);

    // Búsqueda en modal de grupo
    document.getElementById('search-group-equipment').addEventListener('input', filterGroupEquipmentModal);

    // Forms
    document.getElementById('assign-form').addEventListener('submit', handleAssign);
    document.getElementById('unassign-form').addEventListener('submit', handleUnassign);
}

// ==================== CARGAR DATOS ====================
async function loadInitialData() {
    try {
        // Cargar departamento del usuario actual
        await loadUserDepartment();

        // Cargar usuarios del departamento
        await loadDepartmentUsers();

        // Cargar equipos del departamento
        await loadDepartmentEquipment();

        // Cargar grupos del departamento (NUEVO)
        await loadDepartmentGroups();

        // Cargar categorías para filtros
        await loadCategories();

        // Renderizar todo
        renderStats();
        renderUsersList();

        hideLoading();

    } catch (error) {
        console.error('Error cargando datos:', error);
        showError('No se pudieron cargar los datos del departamento');
    }
}

async function loadUserDepartment() {
    try {
        const response = await fetch('/api/core/v1/users/me/department', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar departamento');

        const result = await response.json();
        currentDepartment = result.data;

        document.getElementById('department-info').textContent = 
            `Gestionando equipos del ${currentDepartment.name}`;

    } catch (error) {
        console.error('Error:', error);
        throw error;
    }
}

async function loadDepartmentUsers() {
    try {
        const response = await fetch(`/api/core/v1/departments/${currentDepartment.id}/users`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar usuarios');

        const result = await response.json();
        departmentUsers = result.data.users.sort((a, b) => 
            a.full_name.localeCompare(b.full_name)
        );

    } catch (error) {
        console.error('Error:', error);
        throw error;
    }
}

async function loadDepartmentEquipment() {
    try {
        const response = await fetch(
            `/api/help-desk/v1/inventory/items/department/${currentDepartment.id}?include_assigned=true`,
            {
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`
                }
            }
        );

        if (!response.ok) throw new Error('Error al cargar equipos');

        const result = await response.json();
        departmentEquipment = result.data;

    } catch (error) {
        console.error('Error:', error);
        throw error;
    }
}

async function loadDepartmentGroups() {
    try {
        const response = await fetch(
            `/api/help-desk/v1/inventory/groups/department/${currentDepartment.id}`,
            {
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`
                }
            }
        );

        if (!response.ok) {
            console.warn('No se pudieron cargar grupos');
            departmentGroups = [];
            return;
        }

        const result = await response.json();
        departmentGroups = result.data || [];

    } catch (error) {
        console.error('Error cargando grupos:', error);
        departmentGroups = [];
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

        // Llenar select de filtro
        const select = document.getElementById('filter-category');
        select.innerHTML = '<option value="">Todas las categorías</option>';
        allCategories.forEach(cat => {
            const option = document.createElement('option');
            option.value = cat.id;
            option.textContent = cat.name;
            select.appendChild(option);
        });

    } catch (error) {
        console.error('Error:', error);
    }
}

// ==================== RENDERIZADO ====================
function renderStats() {
    const totalUsers = departmentUsers.length;
    const totalEquipment = departmentEquipment.length;
    const assigned = departmentEquipment.filter(e => e.is_assigned_to_user).length;
    const available = totalEquipment - assigned;

    document.getElementById('stat-total-users').textContent = totalUsers;
    document.getElementById('stat-total-equipment').textContent = totalEquipment;
    document.getElementById('stat-assigned').textContent = assigned;
    document.getElementById('stat-available').textContent = available;
}

function renderUsersList(filter = '') {
    const container = document.getElementById('users-list');
    const filterLower = filter.toLowerCase();

    const filteredUsers = filter 
        ? departmentUsers.filter(u => 
            u.full_name.toLowerCase().includes(filterLower) ||
            u.email.toLowerCase().includes(filterLower)
        )
        : departmentUsers;

    document.getElementById('users-count').textContent = filteredUsers.length;

    if (filteredUsers.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-users-slash fa-2x mb-2"></i>
                <p>No se encontraron usuarios</p>
            </div>
        `;
        return;
    }

    container.innerHTML = filteredUsers.map(user => {
        const userEquipment = departmentEquipment.filter(e => e.assigned_to_user_id === user.id);
        const isSelected = selectedUser && selectedUser.id === user.id;

        return `
            <div class="user-card ${isSelected ? 'selected' : ''} p-3 mb-2" 
                 onclick="selectUser(${user.id})">
                <div class="d-flex align-items-center">
                    <div class="mr-3">
                        <div class="rounded-circle bg-primary text-white d-flex align-items-center justify-content-center"
                             style="width: 45px; height: 45px; font-size: 1.2rem;">
                            ${user.full_name.charAt(0).toUpperCase()}
                        </div>
                    </div>
                    <div class="flex-grow-1">
                        <div class="font-weight-bold">${user.full_name}</div>
                        <small class="text-muted">${user.email}</small>
                    </div>
                    <div class="text-right">
                        <span class="badge badge-${userEquipment.length > 0 ? 'info' : 'secondary'}">
                            ${userEquipment.length} equipos
                        </span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function selectUser(userId) {
    selectedUser = departmentUsers.find(u => u.id === userId);
    
    if (!selectedUser) return;

    // Actualizar UI
    document.querySelectorAll('.user-card').forEach(card => {
        card.classList.remove('selected');
    });
    event.currentTarget.classList.add('selected');

    // Mostrar sección de equipos
    document.getElementById('no-user-selected').style.display = 'none';
    document.getElementById('user-equipment-section').style.display = 'block';

    // Actualizar título
    document.getElementById('equipment-panel-title').innerHTML = `
        <i class="fas fa-laptop"></i> Equipos de ${selectedUser.full_name}
    `;

    // Renderizar equipos
    renderUserEquipment();
}

function renderUserEquipment() {
    if (!selectedUser) return;

    const assignedEquipment = departmentEquipment.filter(e => 
        e.assigned_to_user_id === selectedUser.id
    );

    // Equipos individuales disponibles (sin grupo y no asignados)
    const individualAvailable = departmentEquipment.filter(e => 
        !e.is_assigned_to_user && e.status === 'ACTIVE' && !e.is_in_group
    );

    // Equipos asignados
    const assignedContainer = document.getElementById('assigned-equipment-list');
    document.getElementById('assigned-count').textContent = assignedEquipment.length;

    if (assignedEquipment.length === 0) {
        assignedContainer.innerHTML = `
            <div class="text-center text-muted py-3">
                <i class="fas fa-inbox fa-2x mb-2"></i>
                <p class="mb-0">Este usuario no tiene equipos asignados</p>
            </div>
        `;
    } else {
        assignedContainer.innerHTML = assignedEquipment.map(item => 
            renderEquipmentItem(item, 'assigned')
        ).join('');
    }

    // Equipos individuales disponibles
    const individualContainer = document.getElementById('individual-equipment-list');
    document.getElementById('individual-count').textContent = individualAvailable.length;

    if (individualAvailable.length === 0) {
        individualContainer.innerHTML = `
            <div class="text-center text-muted py-3">
                <i class="fas fa-info-circle fa-2x mb-2"></i>
                <p class="mb-0">No hay equipos individuales disponibles</p>
            </div>
        `;
    } else {
        individualContainer.innerHTML = individualAvailable.map(item => 
            renderEquipmentItem(item, 'available')
        ).join('');
    }

    // Grupos disponibles
    renderGroupsList();
}

function renderGroupsList() {
    const container = document.getElementById('groups-list');
    document.getElementById('groups-count').textContent = departmentGroups.length;

    if (departmentGroups.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-3">
                <i class="fas fa-layer-group fa-2x mb-2"></i>
                <p class="mb-0">No hay grupos disponibles en este departamento</p>
            </div>
        `;
        return;
    }

    container.innerHTML = departmentGroups.map(group => {
        // Contar equipos disponibles del grupo
        const groupEquipment = departmentEquipment.filter(e => 
            e.group_id === group.id && !e.is_assigned_to_user && e.status === 'ACTIVE'
        );

        const groupTypeIcons = {
            'CLASSROOM': 'fa-chalkboard-teacher',
            'LABORATORY': 'fa-flask',
            'OFFICE': 'fa-briefcase',
            'MEETING_ROOM': 'fa-users',
            'WORKSHOP': 'fa-tools',
            'OTHER': 'fa-door-open'
        };

        const icon = groupTypeIcons[group.group_type] || 'fa-door-open';

        return `
            <div class="equipment-item group-item" onclick="openGroupModal(${group.id})">
                <div class="d-flex align-items-center">
                    <div class="mr-3">
                        <i class="fas ${icon} fa-2x text-info"></i>
                    </div>
                    <div class="flex-grow-1">
                        <div class="font-weight-bold">
                            <i class="fas fa-layer-group mr-1"></i>
                            ${group.name}
                        </div>
                        <small class="text-muted">
                            ${group.description || 'Sin descripción'}
                        </small>
                        <br>
                        <span class="badge badge-success mt-1">
                            <i class="fas fa-laptop mr-1"></i>
                            ${groupEquipment.length} equipos disponibles
                        </span>
                        ${group.building || group.floor ? `
                            <span class="badge badge-light text-dark mt-1">
                                <i class="fas fa-map-marker-alt mr-1"></i>
                                ${[group.building, group.floor ? `Piso ${group.floor}` : ''].filter(Boolean).join(' - ')}
                            </span>
                        ` : ''}
                    </div>
                    <div>
                        <button class="btn btn-sm btn-info" onclick="event.stopPropagation(); openGroupModal(${group.id});">
                            <i class="fas fa-hand-pointer"></i> Ver Equipos
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function renderEquipmentItem(item, type) {
    const isAssigned = type === 'assigned';
    const icon = item.category?.icon || 'fas fa-box';

    // Determinar badge de grupo si aplica
    let groupBadge = '';
    if (item.is_in_group && item.group) {
        groupBadge = `
            <br><small class="badge badge-info mt-1">
                <i class="fas fa-layer-group mr-1"></i>${item.group.name}
            </small>
        `;
    }

    return `
        <div class="equipment-item ${isAssigned ? 'assigned' : 'global'}">
            <div class="d-flex align-items-center">
                <div class="mr-3">
                    <i class="${icon} fa-2x text-${isAssigned ? 'info' : 'secondary'}"></i>
                </div>
                <div class="flex-grow-1">
                    <div class="font-weight-bold">
                        ${item.inventory_number}
                    </div>
                    <small class="text-muted">
                        ${item.brand || 'N/A'} ${item.model || ''}
                    </small>
                    ${item.location_detail ? `
                        <br><small class="text-muted">
                            <i class="fas fa-map-marker-alt"></i> ${item.location_detail}
                        </small>
                    ` : ''}
                    ${groupBadge}
                </div>
                <div>
                    ${isAssigned ? `
                        <button class="btn btn-sm btn-warning quick-assign-btn" 
                                onclick="openUnassignModal(${item.id}); event.stopPropagation();">
                            <i class="fas fa-times"></i> Liberar
                        </button>
                    ` : `
                        <button class="btn btn-sm btn-success quick-assign-btn" 
                                onclick="openAssignModal(${item.id}); event.stopPropagation();">
                            <i class="fas fa-plus"></i> Asignar
                        </button>
                    `}
                    <a href="/help-desk/inventory/items/${item.id}" 
                       class="btn btn-sm btn-outline-secondary quick-assign-btn ml-1" 
                       target="_blank"
                       onclick="event.stopPropagation();">
                        <i class="fas fa-external-link-alt"></i>
                    </a>
                </div>
            </div>
        </div>
    `;
}

// ==================== MODAL DE GRUPO ====================
let currentGroupEquipment = [];

async function openGroupModal(groupId) {
    if (!selectedUser) {
        showError('Seleccione un usuario primero');
        return;
    }

    const group = departmentGroups.find(g => g.id === groupId);
    if (!group) return;

    // Actualizar info del grupo
    document.getElementById('selected-group-id').value = groupId;
    document.getElementById('group-modal-name').textContent = group.name;
    document.getElementById('group-modal-description').textContent = group.description || 'Sin descripción';

    // Limpiar búsqueda
    document.getElementById('search-group-equipment').value = '';

    // Abrir modal
    $('#selectGroupEquipmentModal').modal('show');

    // Cargar equipos del grupo
    await loadGroupEquipment(groupId);
}

async function loadGroupEquipment(groupId) {
    const container = document.getElementById('group-equipment-list');
    
    container.innerHTML = `
        <div class="text-center py-4">
            <i class="fas fa-spinner fa-spin fa-2x text-info"></i>
            <p class="text-muted mt-2">Cargando equipos...</p>
        </div>
    `;

    try {
        const response = await fetch(
            `/api/help-desk/v1/inventory/groups/${groupId}/items`,
            {
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`
                }
            }
        );

        if (!response.ok) throw new Error('Error al cargar equipos del grupo');

        const result = await response.json();
        
        // Filtrar solo equipos disponibles (no asignados)
        currentGroupEquipment = result.data.filter(item => 
            !item.is_assigned_to_user && item.status === 'ACTIVE'
        );

        renderGroupEquipmentList();

    } catch (error) {
        console.error('Error:', error);
        container.innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-triangle"></i> 
                Error al cargar equipos del grupo
            </div>
        `;
    }
}

function renderGroupEquipmentList(filter = '') {
    const container = document.getElementById('group-equipment-list');

    const filterLower = filter.toLowerCase();
    const filteredEquipment = filter
        ? currentGroupEquipment.filter(item =>
            item.inventory_number.toLowerCase().includes(filterLower) ||
            (item.brand && item.brand.toLowerCase().includes(filterLower)) ||
            (item.model && item.model.toLowerCase().includes(filterLower))
        )
        : currentGroupEquipment;

    if (filteredEquipment.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="fas fa-inbox fa-2x mb-2"></i>
                <p class="mb-0">${filter ? 'No se encontraron equipos' : 'No hay equipos disponibles en este grupo'}</p>
            </div>
        `;
        return;
    }

    container.innerHTML = filteredEquipment.map(item => {
        const icon = item.category?.icon || 'fas fa-laptop';
        
        return `
            <div class="equipment-item selectable-item" onclick="quickAssignFromGroup(${item.id})">
                <div class="d-flex align-items-center">
                    <div class="mr-3">
                        <i class="${icon} fa-2x text-primary"></i>
                    </div>
                    <div class="flex-grow-1">
                        <div class="font-weight-bold">
                            ${item.inventory_number}
                        </div>
                        <small class="text-muted">
                            ${item.brand || 'N/A'} ${item.model || ''}
                        </small>
                        ${item.location_detail ? `
                            <br><small class="text-muted">
                                <i class="fas fa-map-marker-alt"></i> ${item.location_detail}
                            </small>
                        ` : ''}
                    </div>
                    <div>
                        <button class="btn btn-sm btn-success" onclick="event.stopPropagation(); quickAssignFromGroup(${item.id});">
                            <i class="fas fa-plus"></i> Asignar
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function filterGroupEquipmentModal() {
    const searchTerm = document.getElementById('search-group-equipment').value;
    renderGroupEquipmentList(searchTerm);
}

async function quickAssignFromGroup(itemId) {
    if (!selectedUser) return;

    // Cerrar modal
    $('#selectGroupEquipmentModal').modal('hide');

    // Abrir modal de confirmación
    openAssignModal(itemId);
}

// ==================== FILTROS ====================
function filterUsers() {
    const searchTerm = document.getElementById('search-users').value;
    renderUsersList(searchTerm);
}

function filterEquipment() {
    if (selectedUser) {
        renderUserEquipment();
    }
}

function toggleFilters() {
    const filters = document.getElementById('equipment-filters');
    filters.style.display = filters.style.display === 'none' ? 'block' : 'none';
}

// ==================== ASIGNACIÓN ====================
function openAssignModal(itemId) {
    if (!selectedUser) {
        showError('Seleccione un usuario primero');
        return;
    }

    const item = departmentEquipment.find(e => e.id === itemId);
    if (!item) return;

    document.getElementById('assign-item-id').value = itemId;
    document.getElementById('assign-user-id').value = selectedUser.id;
    document.getElementById('assign-item-name').textContent = item.display_name;
    document.getElementById('assign-user-name').textContent = selectedUser.full_name;
    document.getElementById('assign-location').value = '';
    document.getElementById('assign-notes').value = '';

    $('#assignModal').modal('show');
}

async function handleAssign(e) {
    e.preventDefault();

    const itemId = parseInt(document.getElementById('assign-item-id').value);
    const userId = parseInt(document.getElementById('assign-user-id').value);
    const location = document.getElementById('assign-location').value.trim();
    const notes = document.getElementById('assign-notes').value.trim();

    try {
        const response = await fetch('/api/help-desk/v1/inventory/assignments/assign', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                item_id: itemId,
                user_id: userId,
                location: location || null,
                notes: notes || null
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error al asignar equipo');
        }

        $('#assignModal').modal('hide');
        showSuccess('Equipo asignado correctamente');
        
        await refreshData();

    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
    }
}

// ==================== LIBERACIÓN ====================
function openUnassignModal(itemId) {
    const item = departmentEquipment.find(e => e.id === itemId);
    if (!item) return;

    document.getElementById('unassign-item-id').value = itemId;
    document.getElementById('unassign-item-name').textContent = item.display_name;
    document.getElementById('unassign-user-name').textContent = 
        item.assigned_to_user?.full_name || 'N/A';
    document.getElementById('unassign-notes').value = '';

    $('#unassignModal').modal('show');
}

async function handleUnassign(e) {
    e.preventDefault();

    const itemId = parseInt(document.getElementById('unassign-item-id').value);
    const notes = document.getElementById('unassign-notes').value.trim();

    try {
        const response = await fetch('/api/help-desk/v1/inventory/assignments/unassign', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                item_id: itemId,
                notes: notes || 'Equipo liberado desde vista de asignaciones'
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error al liberar equipo');
        }

        $('#unassignModal').modal('hide');
        showSuccess('Equipo liberado correctamente');
        
        await refreshData();

    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
    }
}

// ==================== REFRESH ====================
async function refreshData() {
    showLoading();
    
    try {
        await loadDepartmentUsers();
        await loadDepartmentEquipment();
        await loadDepartmentGroups();
        
        renderStats();
        renderUsersList();
        
        if (selectedUser) {
            const updatedUser = departmentUsers.find(u => u.id === selectedUser.id);
            if (updatedUser) {
                selectedUser = updatedUser;
                renderUserEquipment();
            }
        }
        
        hideLoading();
        
    } catch (error) {
        console.error('Error:', error);
        showError('Error al actualizar datos');
    }
}

// ==================== HELPERS ====================
function showLoading() {
    document.getElementById('loading-state').style.display = 'block';
    document.getElementById('main-content').style.display = 'none';
}

function hideLoading() {
    document.getElementById('loading-state').style.display = 'none';
    document.getElementById('main-content').style.display = 'block';
}

function showSuccess(message) {
    showToast(message, 'success');
}

function showError(message) {
    showToast(message, 'error');
}
