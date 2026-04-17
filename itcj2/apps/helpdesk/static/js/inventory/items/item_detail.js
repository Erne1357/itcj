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
    // Tabs - Cargar contenido al hacer clic usando Bootstrap 5 events
    const historyTab = document.getElementById('history-tab');
    const ticketsTab = document.getElementById('tickets-tab');
    
    historyTab.addEventListener('shown.bs.tab', function() {
        if (itemHistory.length === 0) loadHistory();
    });

    ticketsTab.addEventListener('shown.bs.tab', function() {
        if (itemTickets.length === 0) loadTickets();
    });

    // Forms
    document.getElementById('edit-basic-form').addEventListener('submit', handleEditBasic);
    document.getElementById('edit-specs-form').addEventListener('submit', handleEditSpecs);
    document.getElementById('assign-user-form').addEventListener('submit', handleAssignUser);
    document.getElementById('change-status-form').addEventListener('submit', handleChangeStatus);
    document.getElementById('deactivate-form').addEventListener('submit', handleDeactivate);
    const lockedFieldForm = document.getElementById('edit-locked-field-form');
    if (lockedFieldForm) lockedFieldForm.addEventListener('submit', handleEditLockedField);

    const unlockForm = document.getElementById('unlock-item-form');
    if (unlockForm) unlockForm.addEventListener('submit', handleUnlockItem);

    const predecessorSearch = document.getElementById('predecessor-search-input');
    if (predecessorSearch) {
        predecessorSearch.addEventListener('input', () => {
            clearTimeout(predecessorDebounce);
            predecessorDebounce = setTimeout(() => searchPredecessorItems(predecessorSearch.value.trim()), 350);
        });
    }
    const btnConfirmPred = document.getElementById('btn-confirm-predecessor');
    if (btnConfirmPred) btnConfirmPred.addEventListener('click', confirmLinkPredecessor);

    const versionsTab = document.getElementById('versions-tab');
    if (versionsTab) {
        versionsTab.addEventListener('shown.bs.tab', () => {
            if (currentItem) loadVersionChain();
        });
    }
}

// ==================== CARGAR DATOS PRINCIPALES ====================
async function loadItemDetail() {
    try {
        const response = await fetch(`/api/help-desk/v2/inventory/items/${ITEM_ID}`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            if (response.status === 404) {
                showNotFound();
                return;
            }
            if (response.status === 403) {
                showForbidden();
                return;
            }
            throw new Error('Error al cargar equipo');
        }

        const result = await response.json();
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
    const categoryIcon = item.category?.icon || 'fas fa-desktop';
    document.getElementById('header-icon').className = categoryIcon;
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

    // Cadena de versiones
    loadVersionChain();

    // Main content visible
    document.getElementById('main-content').style.display = 'block';
}

function renderStatusBadge(item) {
    const container = document.getElementById('status-badge-container');
    const statusInfo = getStatusInfo(item.status);

    const lockBadge = item.is_locked
        ? `<span class="badge bg-warning text-dark badge-lg px-3 py-2 ml-2" style="font-size:0.9rem;"
               title="Bloqueado por campaña validada${item.validated_at ? ' el ' + formatDate(item.validated_at) : ''}">
               <i class="fas fa-lock"></i> Bloqueado
           </span>`
        : '';

    container.innerHTML = `
        <div class="d-inline-flex align-items-center flex-wrap gap-2">
            <span class="badge bg-${statusInfo.color} text-white badge-lg px-3 py-2" style="font-size: 0.9rem;">
                <span class="status-indicator ${statusInfo.class}"></span>
                ${statusInfo.text}
            </span>
            ${lockBadge}
        </div>
    `;
}

function renderActionButtons(item) {
    const container = document.getElementById('header-actions');
    
    // Siempre mostrar el botón de crear ticket
    let buttons = `
        <div class="btn-group">
            <a href="/help-desk/user/create?item=${item.id}" class="btn btn-success action-button">
                <i class="fas fa-plus-circle"></i> Crear Ticket
            </a>
    `;

    // Solo mostrar botones de administración si tiene permisos
    if (CAN_EDIT) {
        buttons += `
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

        // Botón desbloquear (solo admin, solo si está bloqueado)
        if (IS_ADMIN && item.is_locked) {
            buttons += `
                <button class="btn btn-outline-danger action-button" onclick="openUnlockModal()">
                    <i class="fas fa-lock-open"></i> Desbloquear
                </button>
            `;
        }
    }

    buttons += `</div>`;
    container.innerHTML = buttons;
}

function _lockedFieldBtn(field, label, currentVal) {
    if (!IS_ADMIN || !currentItem.is_locked) return '';
    return `<button type="button" class="btn btn-xs btn-outline-warning ml-2 py-0 px-1"
                title="Editar campo bloqueado"
                onclick="openEditLockedField('${field}','${label}','${(currentVal||'').replace(/'/g,"\\'")}')">
                <i class="fas fa-lock-open" style="font-size:.7rem;"></i>
            </button>`;
}

function renderGeneralInfo(item) {
    const container = document.getElementById('general-info');

    container.innerHTML = `
        <div class="info-label">Número de Inventario</div>
        <div class="info-value d-flex align-items-center">
            ${item.inventory_number}
            ${_lockedFieldBtn('inventory_number','Número de Inventario', item.inventory_number)}
        </div>

        <div class="info-label">Categoría</div>
        <div class="info-value">
            <i class="${item.category?.icon || 'fas fa-box'} mr-2"></i>
            ${item.category?.name || 'N/A'}
        </div>

        <div class="info-label">Marca</div>
        <div class="info-value ${item.brand ? '' : 'empty'} d-flex align-items-center">
            ${item.brand || 'No especificada'}
            ${_lockedFieldBtn('brand','Marca', item.brand)}
        </div>

        <div class="info-label">Modelo</div>
        <div class="info-value ${item.model ? '' : 'empty'} d-flex align-items-center">
            ${item.model || 'No especificado'}
            ${_lockedFieldBtn('model','Modelo', item.model)}
        </div>

        <div class="info-label">Serial Proveedor</div>
        <div class="info-value ${item.supplier_serial ? '' : 'empty'} d-flex align-items-center">
            ${item.supplier_serial || 'No registrado'}
            ${_lockedFieldBtn('supplier_serial','Serial Proveedor', item.supplier_serial)}
        </div>

        <div class="info-label">Serial ITCJ / Activo</div>
        <div class="info-value ${item.itcj_serial ? '' : 'empty'} d-flex align-items-center">
            ${item.itcj_serial || 'No registrado'}
            ${_lockedFieldBtn('itcj_serial','Serial ITCJ', item.itcj_serial)}
        </div>

        <div class="info-label">ID TecNM</div>
        <div class="info-value ${item.id_tecnm ? '' : 'empty'} d-flex align-items-center">
            ${item.id_tecnm || 'No registrado'}
            ${_lockedFieldBtn('id_tecnm','ID TecNM', item.id_tecnm)}
        </div>

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
                <span class="badge bg-secondary text-white">Global del Departamento</span>
            `}
        </div>

        <div class="info-label">Tickets Relacionados</div>
        <div class="info-value">
            <span class="badge bg-info text-white">${item.tickets_count || 0} Total</span>
            ${item.active_tickets_count > 0 ? `
                <span class="badge bg-warning text-dark">${item.active_tickets_count} Activos</span>
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
    const specTemplate = item.category?.spec_template || {};

    const editButton = CAN_EDIT ? `
        <div class="d-flex justify-content-end mb-3">
            <button class="btn btn-sm btn-outline-primary" onclick="openEditSpecsModal()">
                <i class="fas fa-edit"></i> Editar Especificaciones
            </button>
        </div>
    ` : '';

    if (!item.specifications || Object.keys(item.specifications).length === 0) {
        container.innerHTML = editButton + `
            <div class="text-center text-muted py-4">
                <i class="fas fa-microchip fa-2x mb-3"></i>
                <p class="mb-0">No hay especificaciones técnicas registradas</p>
            </div>
        `;
        return;
    }

    let html = '<div class="row">';

    Object.entries(item.specifications).forEach(([key, value]) => {
        const label = specTemplate[key]?.label || formatSpecLabel(key);
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
    container.innerHTML = editButton + html;
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
        const response = await fetch(`/api/help-desk/v2/inventory/history/item/${ITEM_ID}?limit=50`, {
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
        const errorMessage = error.message.includes('Failed to fetch') 
            ? 'No se pudo conectar con el servidor. Verifica tu conexión.' 
            : 'No se pudo cargar el historial';
        
        document.getElementById('history-container').innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-triangle"></i>
                ${errorMessage}
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
        const response = await fetch(`/api/help-desk/v2/inventory/items/${ITEM_ID}/tickets`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) {
            if (response.status === 403) {
                document.getElementById('tickets-container').innerHTML = `
                    <div class="alert alert-warning">
                        <i class="fas fa-lock"></i>
                        No tienes permisos para ver los tickets de este equipo
                    </div>
                `;
                return;
            }
            throw new Error('Error al cargar tickets');
        }

        const result = await response.json();
        itemTickets = result.tickets || [];

        document.getElementById('tickets-count').textContent = itemTickets.length;
        renderTickets(itemTickets);

    } catch (error) {
        console.error('Error:', error);
        const errorMessage = error.message.includes('Failed to fetch') 
            ? 'No se pudo conectar con el servidor. Verifica tu conexión.' 
            : 'No se pudieron cargar los tickets';
        
        document.getElementById('tickets-container').innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-triangle"></i>
                ${errorMessage}
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
                <a href="/help-desk/user/create?item=${ITEM_ID}" class="btn btn-sm btn-primary mt-3">
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
            <a href="/help-desk/user/tickets/${ticket.id}" class="list-group-item list-group-item-action">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <strong>${ticket.ticket_number}</strong> - ${escapeHtml(ticket.title)}
                        <br>
                        <small class="text-muted">${formatDateTime(ticket.created_at)}</small>
                    </div>
                    <div class="text-right">
                        <span class="badge bg-${statusBadge.color} text-white">${statusBadge.text}</span>
                        <span class="badge bg-${priorityBadge.color} text-white">${priorityBadge.text}</span>
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
    document.getElementById('edit-supplier-serial').value = currentItem.supplier_serial || '';
    document.getElementById('edit-itcj-serial').value = currentItem.itcj_serial || '';
    document.getElementById('edit-id-tecnm').value = currentItem.id_tecnm || '';
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
        supplier_serial: document.getElementById('edit-supplier-serial').value.trim() || null,
        itcj_serial: document.getElementById('edit-itcj-serial').value.trim() || null,
        id_tecnm: document.getElementById('edit-id-tecnm').value.trim() || null,
        location_detail: document.getElementById('edit-location').value.trim() || null,
        warranty_expiration: document.getElementById('edit-warranty').value || null,
        maintenance_frequency_days: parseInt(document.getElementById('edit-maintenance-freq').value) || null,
        notes: document.getElementById('edit-notes').value.trim() || null
    };

    try {
        const response = await fetch(`/api/help-desk/v2/inventory/items/${ITEM_ID}`, {
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
        const response = await fetch(`/api/core/v2/departments/${currentItem.department_id}/users`, {
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
        const response = await fetch('/api/help-desk/v2/inventory/assignments/assign', {
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
    if (!await HelpdeskUtils.confirmDialog('Liberar equipo', '¿Está seguro de liberar este equipo? Volverá a ser global del departamento.')) return;

    try {
        const response = await fetch('/api/help-desk/v2/inventory/assignments/unassign', {
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
        const response = await fetch(`/api/help-desk/v2/inventory/items/${ITEM_ID}/status`, {
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
    // Redirige al flujo formal de solicitud de baja
    window.location.href = `/help-desk/inventory/retirement-requests/create?item_id=${ITEM_ID}`;
}

async function handleDeactivate(e) {
    e.preventDefault();

    const reason = document.getElementById('deactivation-reason').value.trim();

    if (reason.length < 10) {
        showError('La razón debe tener al menos 10 caracteres');
        return;
    }

    try {
        const response = await fetch(`/api/help-desk/v2/inventory/items/${ITEM_ID}/deactivate`, {
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

// ==================== VERSIONADO DE ITEMS ====================

async function loadVersionChain() {
    const container = document.getElementById('versions-container');
    if (!container) return;

    try {
        const res = await fetch(`/api/help-desk/v2/inventory/items/${ITEM_ID}/version-chain`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error);

        renderVersionChain(data.data);
    } catch (err) {
        container.innerHTML = `<div class="alert alert-danger small">${err.message}</div>`;
    }
}

function renderVersionChain(chain) {
    const container = document.getElementById('versions-container');

    const canLink = CAN_EDIT;

    // Badge de estado de versión en el item actual
    const currentNode = chain.find(n => n.is_current);
    if (currentNode) {
        const versionBadge = document.getElementById('version-badge-placeholder');
        if (versionBadge) {
            versionBadge.innerHTML = currentNode.is_latest
                ? '<span class="badge bg-success text-white ml-2"><i class="fas fa-check-circle"></i> Versión más reciente</span>'
                : `<span class="badge bg-secondary text-white ml-2"><i class="fas fa-history"></i> Reemplazado</span>`;
        }
    }

    let html = '';

    if (chain.length <= 1 && !currentNode?.is_latest === false) {
        // Solo este item, sin cadena
    }

    if (chain.length === 1 && currentNode?.is_latest) {
        html += `
        <div class="text-muted small py-2">
            <i class="fas fa-info-circle"></i> Este equipo no tiene versiones anteriores ni posteriores registradas.
        </div>`;
    } else {
        // Mostrar cadena
        html += '<div class="d-flex align-items-center flex-wrap gap-2 mb-3">';
        chain.forEach((node, idx) => {
            const isCurrent = node.is_current;
            const isActive = node.is_active;
            const year = node.registered_at ? new Date(node.registered_at).getFullYear() : '—';

            html += `
            <div class="version-node ${isCurrent ? 'version-node--current' : ''} ${!isActive ? 'version-node--inactive' : ''}">
                <a href="/help-desk/inventory/items/${node.id}" ${isCurrent ? 'class="font-weight-bold"' : 'class="text-muted"'}>
                    <i class="fas fa-${isActive ? 'desktop' : 'archive'} mr-1"></i>
                    ${node.inventory_number}
                </a>
                <div class="small text-muted">${node.brand || ''} ${node.model || ''}</div>
                <div class="small text-muted">${year}</div>
                ${isCurrent ? '<span class="badge badge-primary badge-sm mt-1">Este equipo</span>' : ''}
                ${node.is_latest && !isCurrent ? '<span class="badge badge-success badge-sm mt-1">Más reciente</span>' : ''}
                ${!isActive ? '<span class="badge badge-secondary badge-sm mt-1">Dado de baja</span>' : ''}
            </div>`;

            if (idx < chain.length - 1) {
                html += '<i class="fas fa-arrow-right text-muted mx-1"></i>';
            }
        });
        html += '</div>';
    }

    // Botón vincular (solo CC/admin)
    if (canLink) {
        const hasPredecessor = currentNode && !chain[0]?.is_current;
        html += `<div class="mt-2 d-flex gap-2 flex-wrap">`;
        html += `
            <button class="btn btn-sm btn-outline-secondary" onclick="openLinkPredecessorModal()">
                <i class="fas fa-link"></i> Vincular como sucesor de otro equipo
            </button>`;
        if (hasPredecessor || (currentNode && chain.length > 1 && chain[0]?.is_current === false)) {
            html += `
            <button class="btn btn-sm btn-outline-danger" onclick="unlinkPredecessor()">
                <i class="fas fa-unlink"></i> Desvincular predecesor
            </button>`;
        }
        html += `</div>`;
    }

    container.innerHTML = html;
}

let predecessorDebounce = null;
let selectedPredecessorId = null;

function openLinkPredecessorModal() {
    selectedPredecessorId = null;
    document.getElementById('predecessor-search-input').value = '';
    document.getElementById('predecessor-search-results').innerHTML =
        '<div class="text-center text-muted small py-3"><i class="fas fa-search"></i> Escribe para buscar</div>';
    document.getElementById('btn-confirm-predecessor').disabled = true;
    $('#linkPredecessorModal').modal('show');
}

async function searchPredecessorItems(search) {
    const results = document.getElementById('predecessor-search-results');
    if (!search) {
        results.innerHTML = '<div class="text-center text-muted small py-3"><i class="fas fa-search"></i> Escribe para buscar</div>';
        return;
    }
    results.innerHTML = '<div class="text-center py-3"><i class="fas fa-spinner fa-spin text-primary"></i></div>';

    const params = new URLSearchParams({ search, per_page: 20 });
    if (currentItem?.department_id) params.set('department_id', currentItem.department_id);

    try {
        const res = await fetch(`/api/help-desk/v2/inventory/items?${params}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
        });
        const data = await res.json();
        const items = (data.data || []).filter(i => i.id !== ITEM_ID);

        if (items.length === 0) {
            results.innerHTML = '<div class="text-center text-muted small py-3">Sin resultados</div>';
            return;
        }

        results.innerHTML = items.map(i => `
            <div class="list-group-item list-group-item-action py-2 px-3 predecessor-option"
                 style="cursor:pointer;" data-id="${i.id}"
                 onclick="selectPredecessor(${i.id}, this)">
                <strong>${i.inventory_number}</strong>
                <span class="text-muted small ml-1">${i.brand || ''} ${i.model || ''}</span>
                ${i.is_latest_version ? '' : '<span class="badge badge-warning badge-sm ml-1">Ya tiene sucesor</span>'}
                ${!i.is_active ? '<span class="badge badge-secondary badge-sm ml-1">Dado de baja</span>' : ''}
            </div>`).join('');
    } catch (err) {
        results.innerHTML = `<div class="text-center text-danger small py-3">${err.message}</div>`;
    }
}

function selectPredecessor(itemId, el) {
    document.querySelectorAll('.predecessor-option').forEach(e => e.classList.remove('active'));
    el.classList.add('active');
    selectedPredecessorId = itemId;
    document.getElementById('btn-confirm-predecessor').disabled = false;
}

async function confirmLinkPredecessor() {
    if (!selectedPredecessorId) return;
    const btn = document.getElementById('btn-confirm-predecessor');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

    try {
        const res = await fetch(`/api/help-desk/v2/inventory/items/${ITEM_ID}/set-predecessor`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ predecessor_item_id: selectedPredecessorId }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Error al vincular');

        $('#linkPredecessorModal').modal('hide');
        showSuccess('Equipo vinculado correctamente');
        loadItemDetail();
    } catch (err) {
        showError(err.message);
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-link"></i> Vincular';
    }
}

async function unlinkPredecessor() {
    if (!await HelpdeskUtils.confirmDialog(
        'Desvincular predecesor',
        '¿Deseas eliminar la relación con el equipo predecesor?',
        'Desvincular'
    )) return;

    try {
        const res = await fetch(`/api/help-desk/v2/inventory/items/${ITEM_ID}/predecessor`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Error al desvincular');
        showSuccess('Predecesor desvinculado');
        loadItemDetail();
    } catch (err) {
        showError(err.message);
    }
}

// ==================== CAMPO BLOQUEADO (ADMIN) ====================
function openEditLockedField(field, label, currentVal) {
    document.getElementById('locked-field-name').value = field;
    document.getElementById('locked-field-label').textContent = label;
    document.getElementById('locked-field-value').value = currentVal;
    document.getElementById('locked-field-justification').value = '';
    $('#editLockedFieldModal').modal('show');
}

async function handleEditLockedField(e) {
    e.preventDefault();

    const field = document.getElementById('locked-field-name').value;
    const newValue = document.getElementById('locked-field-value').value.trim();
    const justification = document.getElementById('locked-field-justification').value.trim();

    if (justification.length < 10) {
        showError('La justificación debe tener al menos 10 caracteres');
        return;
    }

    try {
        const response = await fetch(`/api/help-desk/v2/inventory/items/${ITEM_ID}`, {
            method: 'PATCH',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ [field]: newValue || null, _justification: justification }),
        });

        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Error al actualizar');

        $('#editLockedFieldModal').modal('hide');
        showSuccess('Campo actualizado. El cambio quedó registrado en el historial.');
        loadItemDetail();
    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
    }
}

// ==================== DESBLOQUEAR EQUIPO (ADMIN) ====================

function openUnlockModal() {
    document.getElementById('unlock-justification').value = '';
    $('#unlockItemModal').modal('show');
}

async function handleUnlockItem(e) {
    e.preventDefault();

    const justification = document.getElementById('unlock-justification').value.trim();
    if (justification.length < 10) {
        showError('La justificación debe tener al menos 10 caracteres');
        return;
    }

    if (!currentItem || !currentItem.locked_campaign_id) {
        showError('No se encontró la campaña que bloqueó este equipo');
        return;
    }

    const submitBtn = e.target.querySelector('[type="submit"]');
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Desbloqueando...';

    try {
        const response = await fetch(
            `/api/help-desk/v2/inventory/campaigns/${currentItem.locked_campaign_id}/items/${ITEM_ID}/unlock`,
            {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ justification }),
            }
        );

        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Error al desbloquear');

        $('#unlockItemModal').modal('hide');
        showSuccess('Equipo desbloqueado. El cambio quedó registrado en el historial.');
        loadItemDetail();
    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-lock-open"></i> Desbloquear';
    }
}

// ==================== ESPECIFICACIONES ====================
function openEditSpecsModal() {
    const specTemplate = currentItem.category?.spec_template;
    const currentSpecs = currentItem.specifications || {};
    const container = document.getElementById('specs-form-container');

    if (!specTemplate || Object.keys(specTemplate).length === 0) {
        container.innerHTML = `
            <div class="alert alert-info">
                <i class="fas fa-info-circle"></i>
                Esta categoría no tiene un template de especificaciones definido.
            </div>
        `;
        $('#editSpecsModal').modal('show');
        return;
    }

    let html = '<div class="row">';

    Object.entries(specTemplate).forEach(([key, fieldDef]) => {
        const label = fieldDef.label || formatSpecLabel(key);
        const required = fieldDef.required ? 'required' : '';
        const requiredMark = fieldDef.required ? ' <span class="text-danger">*</span>' : '';
        const currentValue = currentSpecs[key];

        html += `<div class="col-md-6 mb-3"><div class="form-group">`;
        html += `<label>${label}${requiredMark}</label>`;

        if (fieldDef.type === 'select') {
            html += `<select class="form-control" name="${key}" id="spec-${key}" ${required}>`;
            html += `<option value="">Seleccionar...</option>`;
            (fieldDef.options || []).forEach(opt => {
                const selected = currentValue === opt ? 'selected' : '';
                html += `<option value="${opt}" ${selected}>${opt}</option>`;
            });
            html += `</select>`;

        } else if (fieldDef.type === 'boolean') {
            const checked = currentValue === true ? 'checked' : '';
            html += `
                <div class="mt-2">
                    <div class="form-check">
                        <input type="checkbox" class="form-check-input" name="${key}" id="spec-${key}" ${checked}>
                        <label class="form-check-label" for="spec-${key}">Sí</label>
                    </div>
                </div>
            `;

        } else if (fieldDef.type === 'number') {
            const val = currentValue !== undefined && currentValue !== null ? currentValue : '';
            html += `<input type="number" class="form-control" name="${key}" id="spec-${key}" value="${val}" ${required} min="0" step="any">`;

        } else {
            const val = currentValue !== undefined && currentValue !== null ? escapeHtml(String(currentValue)) : '';
            html += `<input type="text" class="form-control" name="${key}" id="spec-${key}" value="${val}" ${required}>`;
        }

        html += `</div></div>`;
    });

    html += '</div>';
    container.innerHTML = html;
    $('#editSpecsModal').modal('show');
}

async function handleEditSpecs(e) {
    e.preventDefault();

    const specTemplate = currentItem.category?.spec_template;
    if (!specTemplate || Object.keys(specTemplate).length === 0) {
        $('#editSpecsModal').modal('hide');
        return;
    }

    const specifications = {};

    Object.entries(specTemplate).forEach(([key, fieldDef]) => {
        const el = document.getElementById(`spec-${key}`);
        if (!el) return;

        if (fieldDef.type === 'boolean') {
            specifications[key] = el.checked;
        } else if (fieldDef.type === 'number') {
            const val = el.value.trim();
            if (val !== '') specifications[key] = parseFloat(val);
        } else {
            const val = el.value.trim();
            if (val !== '') specifications[key] = val;
        }
    });

    try {
        const response = await fetch(`/api/help-desk/v2/inventory/items/${ITEM_ID}`, {
            method: 'PATCH',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ specifications })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error al actualizar especificaciones');
        }

        $('#editSpecsModal').modal('hide');
        showSuccess('Especificaciones actualizadas correctamente');
        loadItemDetail();

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

function showForbidden() {
    document.getElementById('loading-state').innerHTML = `
        <div class="text-center py-5">
            <i class="fas fa-lock fa-4x text-danger mb-4"></i>
            <h3>Acceso Denegado</h3>
            <p class="text-muted">No tienes permisos para ver la información de este equipo</p>
            <div id="backButtonContainer-forbidden" class="mt-3">
                <button onclick="window.history.back()" class="btn btn-secondary">
                    <i class="fas fa-arrow-left"></i> Volver
                </button>
            </div>
            <a href="/help-desk/inventory/items" class="btn btn-primary mt-3">
                <i class="fas fa-list"></i> Ver Inventario
            </a>
        </div>
    `;
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
    showToast(message, 'success'); // Reemplazar con tu sistema de notificaciones
}

function showError(message) {
    showToast(message, 'error'); // Reemplazar con tu sistema de notificaciones
}