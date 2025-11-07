/**
 * Gestión de Asignaciones de Equipos
 * Interfaz para Jefes de Departamento
 */

let currentDepartment = null;
let departmentUsers = [];
let departmentEquipment = [];
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

    const availableEquipment = departmentEquipment.filter(e => 
        !e.is_assigned_to_user && e.status === 'ACTIVE'
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

    // Equipos disponibles
    const availableContainer = document.getElementById('available-equipment-list');
    document.getElementById('available-count').textContent = availableEquipment.length;

    if (availableEquipment.length === 0) {
        availableContainer.innerHTML = `
            <div class="text-center text-muted py-3">
                <i class="fas fa-info-circle fa-2x mb-2"></i>
                <p class="mb-0">No hay equipos disponibles para asignar</p>
            </div>
        `;
    } else {
        availableContainer.innerHTML = availableEquipment.map(item => 
            renderEquipmentItem(item, 'available')
        ).join('');
    }
}

function renderEquipmentItem(item, type) {
    const isAssigned = type === 'assigned';
    const icon = item.category?.icon || 'fas fa-box';

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

// ==================== FILTROS ====================
function filterUsers() {
    const searchTerm = document.getElementById('search-users').value;
    renderUsersList(searchTerm);
}

function filterEquipment() {
    // Implementar filtrado de equipos disponibles
    // Por simplicidad, re-renderizar todo
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
        
        // Recargar datos
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
        
        // Recargar datos
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
        
        renderStats();
        renderUsersList();
        
        if (selectedUser) {
            // Re-seleccionar el usuario actual
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
    // Implementar con tu sistema de notificaciones
    alert(message);
}

function showError(message) {
    alert(message);
}