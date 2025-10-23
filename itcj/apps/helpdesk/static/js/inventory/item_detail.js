/**
 * Detalle de Equipo de Inventario
 * Muestra información completa, historial, tickets y acciones
 */

let currentItem = null;
let itemHistory = [];
let itemTickets = [];
let departmentUsers = [];

document.addEventListener('DOMContentLoaded', function() {
    loadItemDetail();
    setupEventListeners();
});

// ==================== SETUP ====================
function setupEventListeners() {
    // Tabs - Cargar contenido al hacer clic
    document.getElementById('history-tab').addEventListener('click', function() {
        if (itemHistory.length === 0) loadHistory();
    });

    document.getElementById('tickets-tab').addEventListener('click', function() {
        if (itemTickets.length === 0) loadTickets();
    });

    // Forms
    document.getElementById('edit-basic-form').addEventListener('submit', handleEditBasic);
    document.getElementById('assign-user-form').addEventListener('submit', handleAssignUser);
    document.getElementById('change-status-form').addEventListener('submit', handleChangeStatus);
    document.getElementById('deactivate-form').addEventListener('submit', handleDeactivate);
}

// ==================== CARGAR DATOS PRINCIPALES ====================
async function loadItemDetail() {
    try {
        const response = await fetch(`/api/help-desk/v1/inventory/items/${ITEM_ID}`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            if (response.status === 404) {
                showNotFound();
                return;
            }
            throw new Error('Error al cargar equipo');
        }

        const result = await response.json();
        console.log('Item Detail:', result);
        currentItem = result.data;

        renderItemDetail(currentItem);
        hideLoading();

    } catch (error) {
        console.error('Error:', error);
        showError('No se pudo cargar la información del equipo');
    }
}

// ==================== RENDERIZADO PRINCIPAL ====================
function renderItemDetail(item) {
    // Header
    document.getElementById('header-inventory-number').textContent = item.inventory_number;
    document.getElementById('header-description').textContent = 
        `${item.brand || ''} ${item.model || ''}`.trim() || 'Sin información de marca/modelo';

    // Status Badge
    renderStatusBadge(item);

    // Botones de acción
    renderActionButtons(item);

    // Información general
    renderGeneralInfo(item);

    // Ubicación y asignación
    renderLocationInfo(item);

    // Garantía
    renderWarrantyInfo(item);

    // Mantenimiento
    renderMaintenanceInfo(item);

    // Especificaciones
    renderSpecifications(item);

    // Notas
    renderNotes(item);

    // Main content visible
    document.getElementById('main-content').style.display = 'block';
}

function renderStatusBadge(item) {
    const container = document.getElementById('status-badge-container');
    const statusInfo = getStatusInfo(item.status);
    
    container.innerHTML = `
        <div class="d-inline-block">
            <span class="badge badge-${statusInfo.color} badge-lg px-3 py-2" style="font-size: 0.9rem;">
                <span class="status-indicator ${statusInfo.class}"></span>
                ${statusInfo.text}
            </span>
        </div>
    `;
}

function renderActionButtons(item) {
    const container = document.getElementById('header-actions');
    
    let buttons = `
        <div class="btn-group">
            <a href="/help-desk/tickets/create?item=${item.id}" class="btn btn-success action-button">
                <i class="fas fa-plus-circle"></i> Crear Ticket
            </a>
            <button class="btn btn-primary action-button" onclick="openEditModal()">
                <i class="fas fa-edit"></i> Editar
            </button>
            <button class="btn btn-warning action-button" onclick="openChangeStatusModal()">
                <i class="fas fa-toggle-on"></i> Cambiar Estado
            </button>
    `;

    // Botón asignar/liberar
    if (item.is_assigned_to_user) {
        buttons += `
            <button class="btn btn-info action-button" onclick="unassignUser()">
                <i class="fas fa-user-times"></i> Liberar
            </button>
        `;
    } else {
        buttons += `
            <button class="btn btn-info action-button" onclick="openAssignModal()">
                <i class="fas fa-user-plus"></i> Asignar
            </button>
        `;
    }

    // Botón dar de baja (solo si está activo)
    if (item.is_active) {
        buttons += `
            <button class="btn btn-danger action-button" onclick="openDeactivateModal()">
                <i class="fas fa-trash-alt"></i> Dar de Baja
            </button>
        `;
    }

    buttons += `</div>`;
    container.innerHTML = buttons;
}

function renderGeneralInfo(item) {
    const container = document.getElementById('general-info');
    
    container.innerHTML = `
        <div class="info-label">Número de Inventario</div>
        <div class="info-value">${item.inventory_number}</div>

        <div class="info-label">Categoría</div>
        <div class="info-value">
            <i class="${item.category?.icon || 'fas fa-box'} mr-2"></i>
            ${item.category?.name || 'N/A'}
        </div>

        <div class="info-label">Marca</div>
        <div class="info-value ${item.brand ? '' : 'empty'}">${item.brand || 'No especificada'}</div>

        <div class="info-label">Modelo</div>
        <div class="info-value ${item.model ? '' : 'empty'}">${item.model || 'No especificado'}</div>

        <div class="info-label">Número de Serie</div>
        <div class="info-value ${item.serial_number ? '' : 'empty'}">${item.serial_number || 'No registrado'}</div>

        <div class="info-label">Fecha de Adquisición</div>
        <div class="info-value ${item.acquisition_date ? '' : 'empty'}">
            ${item.acquisition_date ? formatDate(item.acquisition_date) : 'No registrada'}
        </div>

        <div class="info-label">Registrado Por</div>
        <div class="info-value">
            ${item.registered_by?.full_name || 'N/A'}
            <small class="text-muted d-block">${formatDateTime(item.registered_at)}</small>
        </div>
    `;
}

function renderLocationInfo(item) {
    const container = document.getElementById('location-info');
    
    container.innerHTML = `
        <div class="info-label">Departamento</div>
        <div class="info-value">
            <i class="fas fa-building mr-2 text-primary"></i>
            ${item.department?.name || 'N/A'}
        </div>

        <div class="info-label">Ubicación Específica</div>
        <div class="info-value ${item.location_detail ? '' : 'empty'}">
            <i class="fas fa-map-marker-alt mr-2 text-danger"></i>
            ${item.location_detail || 'No especificada'}
        </div>

        <div class="info-label">Estado de Asignación</div>
        <div class="info-value">
            ${item.is_assigned_to_user ? `
                <div class="alert alert-info mb-0 py-2">
                    <i class="fas fa-user-check mr-2"></i>
                    <strong>Asignado a:</strong> ${item.assigned_to_user.full_name}
                    <br>
                    <small class="text-muted">
                        Fecha: ${formatDateTime(item.assigned_at)}<br>
                        Por: ${item.assigned_by?.full_name || 'N/A'}
                    </small>
                </div>
            ` : `
                <span class="badge badge-secondary">Global del Departamento</span>
            `}
        </div>

        <div class="info-label">Tickets Relacionados</div>
        <div class="info-value">
            <span class="badge badge-info">${item.tickets_count || 0} Total</span>
            ${item.active_tickets_count > 0 ? `
                <span class="badge badge-warning">${item.active_tickets_count} Activos</span>
            ` : ''}
        </div>
    `;
}

function renderWarrantyInfo(item) {
    const card = document.getElementById('warranty-card');
    const container = document.getElementById('warranty-info');

    if (!item.warranty_expiration) {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="fas fa-info-circle fa-2x mb-3"></i>
                <p class="mb-0">No hay información de garantía registrada</p>
            </div>
        `;
        return;
    }

    if (item.is_under_warranty) {
        const days = item.warranty_days_remaining;
        let alertClass = 'success';
        let icon = 'check-circle';
        
        if (days <= 30) {
            alertClass = 'warning';
            icon = 'exclamation-triangle';
            card.classList.add('warranty-card', 'expiring');
        } else {
            card.classList.add('warranty-card');
        }

        container.innerHTML = `
            <div class="alert alert-${alertClass} mb-0">
                <i class="fas fa-${icon} fa-2x float-left mr-3"></i>
                <div>
                    <strong>Garantía Vigente</strong><br>
                    <span class="h5 mb-0">${days} días restantes</span><br>
                    <small class="text-muted">Vence: ${formatDate(item.warranty_expiration)}</small>
                </div>
            </div>
        `;
    } else {
        card.classList.add('warranty-card', 'expired');
        container.innerHTML = `
            <div class="alert alert-danger mb-0">
                <i class="fas fa-times-circle fa-2x float-left mr-3"></i>
                <div>
                    <strong>Garantía Vencida</strong><br>
                    <small class="text-muted">Venció: ${formatDate(item.warranty_expiration)}</small>
                </div>
            </div>
        `;
    }
}

function renderMaintenanceInfo(item) {
    const container = document.getElementById('maintenance-info');

    if (!item.maintenance_frequency_days && !item.last_maintenance_date) {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="fas fa-tools fa-2x mb-3"></i>
                <p class="mb-0">No hay plan de mantenimiento configurado</p>
            </div>
        `;
        return;
    }

    let html = '';

    if (item.last_maintenance_date) {
        html += `
            <div class="info-label">Último Mantenimiento</div>
            <div class="info-value">${formatDate(item.last_maintenance_date)}</div>
        `;
    }

    if (item.maintenance_frequency_days) {
        html += `
            <div class="info-label">Frecuencia</div>
            <div class="info-value">Cada ${item.maintenance_frequency_days} días</div>
        `;
    }

    if (item.next_maintenance_date) {
        const isOverdue = item.needs_maintenance;
        html += `
            <div class="info-label">Próximo Mantenimiento</div>
            <div class="info-value">
                <div class="alert alert-${isOverdue ? 'danger' : 'info'} mb-0 py-2">
                    <i class="fas fa-${isOverdue ? 'exclamation-triangle' : 'calendar-alt'} mr-2"></i>
                    ${formatDate(item.next_maintenance_date)}
                    ${isOverdue ? '<br><small><strong>¡Vencido!</strong></small>' : ''}
                </div>
            </div>
        `;
    }

    container.innerHTML = html;
}

function renderSpecifications(item) {
    const container = document.getElementById('specs-container');

    if (!item.specifications || Object.keys(item.specifications).length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="fas fa-microchip fa-2x mb-3"></i>
                <p class="mb-0">No hay especificaciones técnicas registradas</p>
            </div>
        `;
        return;
    }

    let html = '<div class="row">';
    
    Object.entries(item.specifications).forEach(([key, value]) => {
        const label = formatSpecLabel(key);
        const displayValue = formatSpecValue(value);

        html += `
            <div class="col-md-6 mb-3">
                <div class="spec-badge w-100">
                    <strong>${label}:</strong> ${displayValue}
                </div>
            </div>
        `;
    });

    html += '</div>';
    container.innerHTML = html;
}

function renderNotes(item) {
    const container = document.getElementById('notes-container');

    if (!item.notes || item.notes.trim() === '') {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="fas fa-sticky-note fa-2x mb-3"></i>
                <p class="mb-0">No hay notas adicionales</p>
            </div>
        `;
        return;
    }

    container.innerHTML = `
        <div class="alert alert-light">
            <p class="mb-0" style="white-space: pre-wrap;">${escapeHtml(item.notes)}</p>
        </div>
    `;
}

// ==================== HISTORIAL ====================
async function loadHistory() {
    try {
        const response = await fetch(`/api/help-desk/v1/inventory/history/item/${ITEM_ID}?limit=50`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar historial');

        const result = await response.json();
        itemHistory = result.data.history;

        document.getElementById('history-count').textContent = itemHistory.length;
        renderHistory(itemHistory);

    } catch (error) {
        console.error('Error:', error);
        document.getElementById('history-container').innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-triangle"></i>
                No se pudo cargar el historial
            </div>
        `;
    }
}

function renderHistory(history) {
    const container = document.getElementById('history-container');

    if (history.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="fas fa-history fa-2x mb-3"></i>
                <p class="mb-0">No hay historial registrado</p>
            </div>
        `;
        return;
    }

    let html = '<div class="timeline">';

    history.forEach(event => {
        const eventClass = getEventClass(event.event_type);
        
        html += `
            <div class="timeline-item ${eventClass}">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <strong>${event.event_description || event.event_type}</strong>
                        <br>
                        <small class="text-muted">
                            ${event.performed_by?.full_name || 'Sistema'} · 
                            ${formatDateTime(event.timestamp)}
                        </small>
                        ${event.notes ? `<p class="mb-0 mt-2 text-muted"><small>${escapeHtml(event.notes)}</small></p>` : ''}
                    </div>
                </div>
            </div>
        `;
    });

    html += '</div>';
    container.innerHTML = html;
}

// ==================== TICKETS ====================
async function loadTickets() {
    try {
        const response = await fetch(`/api/help-desk/v1/tickets?inventory_item_id=${ITEM_ID}`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar tickets');

        const result = await response.json();
        itemTickets = result.tickets;

        document.getElementById('tickets-count').textContent = itemTickets.length;
        renderTickets(itemTickets);

    } catch (error) {
        console.error('Error:', error);
        document.getElementById('tickets-container').innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-triangle"></i>
                No se pudieron cargar los tickets
            </div>
        `;
    }
}

function renderTickets(tickets) {
    const container = document.getElementById('tickets-container');

    if (tickets.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="fas fa-ticket-alt fa-2x mb-3"></i>
                <p class="mb-0">No hay tickets relacionados con este equipo</p>
                <a href="/help-desk/tickets/create?item=${ITEM_ID}" class="btn btn-sm btn-primary mt-3">
                    <i class="fas fa-plus"></i> Crear Primer Ticket
                </a>
            </div>
        `;
        return;
    }

    let html = '<div class="list-group">';

    tickets.forEach(ticket => {
        const statusBadge = getTicketStatusBadge(ticket.status);
        const priorityBadge = getTicketPriorityBadge(ticket.priority);

        html += `
            <a href="/help-desk/tickets/${ticket.id}" class="list-group-item list-group-item-action">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <strong>${ticket.ticket_number}</strong> - ${escapeHtml(ticket.title)}
                        <br>
                        <small class="text-muted">${formatDateTime(ticket.created_at)}</small>
                    </div>
                    <div class="text-right">
                        <span class="badge badge-${statusBadge.color}">${statusBadge.text}</span>
                        <span class="badge badge-${priorityBadge.color}">${priorityBadge.text}</span>
                    </div>
                </div>
            </a>
        `;
    });

    html += '</div>';
    container.innerHTML = html;
}

// ==================== MODALES Y ACCIONES ====================
function openEditModal() {
    // Prellenar formulario
    document.getElementById('edit-brand').value = currentItem.brand || '';
    document.getElementById('edit-model').value = currentItem.model || '';
    document.getElementById('edit-location').value = currentItem.location_detail || '';
    document.getElementById('edit-warranty').value = currentItem.warranty_expiration || '';
    document.getElementById('edit-maintenance-freq').value = currentItem.maintenance_frequency_days || '';
    document.getElementById('edit-notes').value = currentItem.notes || '';

    $('#editBasicInfoModal').modal('show');
}

async function handleEditBasic(e) {
    e.preventDefault();

    const formData = {
        brand: document.getElementById('edit-brand').value.trim() || null,
        model: document.getElementById('edit-model').value.trim() || null,
        location_detail: document.getElementById('edit-location').value.trim() || null,
        warranty_expiration: document.getElementById('edit-warranty').value || null,
        maintenance_frequency_days: parseInt(document.getElementById('edit-maintenance-freq').value) || null,
        notes: document.getElementById('edit-notes').value.trim() || null
    };

    try {
        const response = await fetch(`/api/help-desk/v1/inventory/items/${ITEM_ID}`, {
            method: 'PATCH',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error al actualizar');
        }

        $('#editBasicInfoModal').modal('hide');
        showSuccess('Información actualizada correctamente');
        loadItemDetail(); // Recargar

    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
    }
}

async function openAssignModal() {
    // Cargar usuarios del departamento
    try {
        const response = await fetch(`/api/core/v1/departments/${currentItem.department_id}/users`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar usuarios');

        const result = await response.json();
        departmentUsers = result.data;

        const select = document.getElementById('assign-user-select');
        select.innerHTML = '<option value="">Seleccionar usuario...</option>';
        
        departmentUsers.forEach(user => {
            const option = document.createElement('option');
            option.value = user.id;
            option.textContent = `${user.full_name} (${user.email})`;
            select.appendChild(option);
        });

        $('#assignUserModal').modal('show');

    } catch (error) {
        console.error('Error:', error);
        showError('No se pudieron cargar los usuarios');
    }
}

async function handleAssignUser(e) {
    e.preventDefault();

    const userId = document.getElementById('assign-user-select').value;
    const location = document.getElementById('assign-location').value.trim();
    const notes = document.getElementById('assign-notes').value.trim();

    if (!userId) {
        showError('Debe seleccionar un usuario');
        return;
    }

    try {
        const response = await fetch('/api/help-desk/v1/inventory/assignments/assign', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                item_id: ITEM_ID,
                user_id: parseInt(userId),
                location: location || null,
                notes: notes || null
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error al asignar');
        }

        $('#assignUserModal').modal('hide');
        showSuccess('Equipo asignado correctamente');
        loadItemDetail(); // Recargar

    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
    }
}

async function unassignUser() {
    if (!confirm('¿Está seguro de liberar este equipo? Volverá a ser global del departamento.')) {
        return;
    }

    try {
        const response = await fetch('/api/help-desk/v1/inventory/assignments/unassign', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                item_id: ITEM_ID,
                notes: 'Equipo liberado desde vista de detalle'
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error al liberar');
        }

        showSuccess('Equipo liberado correctamente');
        loadItemDetail(); // Recargar

    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
    }
}

function openChangeStatusModal() {
    document.getElementById('new-status').value = '';
    document.getElementById('status-notes').value = '';
    $('#changeStatusModal').modal('show');
}

async function handleChangeStatus(e) {
    e.preventDefault();

    const newStatus = document.getElementById('new-status').value;
    const notes = document.getElementById('status-notes').value.trim();

    if (!newStatus || !notes) {
        showError('Complete todos los campos');
        return;
    }

    try {
        const response = await fetch(`/api/help-desk/v1/inventory/items/${ITEM_ID}/status`, {
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
        loadItemDetail(); // Recargar

    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
    }
}

function openDeactivateModal() {
    document.getElementById('deactivation-reason').value = '';
    $('#deactivateModal').modal('show');
}

async function handleDeactivate(e) {
    e.preventDefault();

    const reason = document.getElementById('deactivation-reason').value.trim();

    if (reason.length < 10) {
        showError('La razón debe tener al menos 10 caracteres');
        return;
    }

    try {
        const response = await fetch(`/api/help-desk/v1/inventory/items/${ITEM_ID}/deactivate`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ reason })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error al dar de baja');
        }

        $('#deactivateModal').modal('hide');
        showSuccess('Equipo dado de baja correctamente');
        
        // Redirigir a lista
        setTimeout(() => {
            window.location.href = '/help-desk/inventory/items';
        }, 2000);

    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
    }
}

// ==================== HELPERS ====================
function getStatusInfo(status) {
    const statuses = {
        'ACTIVE': { text: 'Activo', color: 'success', class: 'active' },
        'MAINTENANCE': { text: 'En Mantenimiento', color: 'warning', class: 'maintenance' },
        'DAMAGED': { text: 'Dañado', color: 'danger', class: 'damaged' },
        'RETIRED': { text: 'Retirado', color: 'secondary', class: 'retired' },
        'LOST': { text: 'Extraviado', color: 'dark', class: 'lost' }
    };
    return statuses[status] || { text: status, color: 'secondary', class: '' };
}

function getEventClass(eventType) {
    if (eventType.includes('ASSIGNED') || eventType.includes('REASSIGNED')) return 'event-assigned';
    if (eventType.includes('STATUS')) return 'event-status';
    if (eventType.includes('MAINTENANCE')) return 'event-maintenance';
    if (eventType.includes('DEACTIVATED') || eventType.includes('DAMAGED')) return 'event-danger';
    return '';
}

function getTicketStatusBadge(status) {
    const badges = {
        'PENDING': { color: 'warning', text: 'Pendiente' },
        'ASSIGNED': { color: 'info', text: 'Asignado' },
        'IN_PROGRESS': { color: 'primary', text: 'En Progreso' },
        'RESOLVED_SUCCESS': { color: 'success', text: 'Resuelto' },
        'CLOSED': { color: 'secondary', text: 'Cerrado' }
    };
    return badges[status] || { color: 'secondary', text: status };
}

function getTicketPriorityBadge(priority) {
    const badges = {
        'URGENTE': { color: 'danger', text: 'Urgente' },
        'ALTA': { color: 'warning', text: 'Alta' },
        'MEDIA': { color: 'info', text: 'Media' },
        'BAJA': { color: 'secondary', text: 'Baja' }
    };
    return badges[priority] || { color: 'secondary', text: priority };
}

function formatDate(dateStr) {
    if (!dateStr) return 'N/A';
    const date = new Date(dateStr);
    return date.toLocaleDateString('es-MX', { day: '2-digit', month: 'long', year: 'numeric' });
}

function formatDateTime(dateStr) {
    if (!dateStr) return 'N/A';
    const date = new Date(dateStr);
    return date.toLocaleString('es-MX', { 
        day: '2-digit', 
        month: 'short', 
        year: 'numeric',
        hour: '2-digit', 
        minute: '2-digit' 
    });
}

function formatSpecLabel(key) {
    return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function formatSpecValue(value) {
    if (typeof value === 'boolean') {
        return value ? '<i class="fas fa-check text-success"></i> Sí' : '<i class="fas fa-times text-danger"></i> No';
    }
    return escapeHtml(String(value));
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

function hideLoading() {
    document.getElementById('loading-state').style.display = 'none';
}

function showNotFound() {
    document.getElementById('loading-state').innerHTML = `
        <div class="text-center py-5">
            <i class="fas fa-exclamation-triangle fa-4x text-warning mb-4"></i>
            <h3>Equipo No Encontrado</h3>
            <p class="text-muted">El equipo solicitado no existe o no tiene permiso para verlo</p>
            <a href="/help-desk/inventory/items" class="btn btn-primary mt-3">
                <i class="fas fa-arrow-left"></i> Volver a Inventario
            </a>
        </div>
    `;
}

function showSuccess(message) {
    alert(message); // Reemplazar con tu sistema de notificaciones
}

function showError(message) {
    alert(message);
}