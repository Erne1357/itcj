// itcj/apps/helpdesk/static/js/technician/dashboard.js

/**
 * Technician Dashboard - Sistema de Tickets ITCJ
 * Gestión de tickets del técnico
 */

// ==================== GLOBAL STATE ====================
let pendingScrollRestore = 0;
let myTickets = {
    assigned: [],
    inProgress: [],
    team: [],
    resolved: []
};

let ticketToStart = null;
let ticketToResolve = null;
let ticketToSelfAssign = null;

// WebSocket state
let techArea = null;
let socketRoomsBound = false;

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', () => {
    initializeDashboard().then(() => {
        // Restore state if coming back from a ticket detail
        if (document.referrer.includes('/help-desk/user/tickets/')) {
            const saved = HelpdeskUtils.NavState.load('technician_dashboard');
            if (saved) {
                if (saved.activeTab) {
                    const tabEl = document.getElementById(saved.activeTab);
                    if (tabEl) bootstrap.Tab.getOrCreateInstance(tabEl).show();
                }
                if (saved.historyFilter) {
                    const hf = document.getElementById('historyFilter');
                    if (hf) { hf.value = saved.historyFilter; applyHistoryFilters(); }
                }
                if (saved.historySearch) {
                    const hs = document.getElementById('historySearch');
                    if (hs) { hs.value = saved.historySearch; applyHistoryFilters(); }
                }
                if (saved.scrollY) {
                    setTimeout(() => window.scrollTo({ top: saved.scrollY, behavior: 'instant' }), 200);
                }
            }
        }
    });
    setupModals();
    setupFilters();
    setupWebSocketListeners();
});

async function initializeDashboard() {
    try {
        await Promise.all([
            loadAssignedTickets(),
            loadInProgressTickets(),
            loadTeamTickets(),
            loadResolvedTickets()
        ]);
        
        updateDashboardStats();
        
    } catch (error) {
        console.error('Error initializing dashboard:', error);
        const errorMessage = error.message || 'Error desconocido';
        HelpdeskUtils.showToast(`Error al cargar el dashboard: ${errorMessage}`, 'error');
    }
}

async function refreshDashboard() {
    HelpdeskUtils.showToast('Actualizando dashboard...', 'info');
    await initializeDashboard();
    HelpdeskUtils.showToast('Dashboard actualizado', 'success');
}
window.refreshDashboard = refreshDashboard;

// ==================== LOAD TICKETS ====================
async function loadAssignedTickets() {
    const container = document.getElementById('queueList');
    HelpdeskUtils.showLoading('queueList');
    
    try {
        const response = await HelpdeskUtils.api.getTickets({
            assigned_to_me: true,
            status: 'ASSIGNED'
        });
        
        myTickets.assigned = response.tickets || [];
        document.getElementById('queueBadge').textContent = myTickets.assigned.length;
        
        renderTicketList(myTickets.assigned, container, 'assigned');
        
    } catch (error) {
        console.error('Error loading assigned tickets:', error);
        showErrorState(container);
    }
}

async function loadInProgressTickets() {
    const container = document.getElementById('workingList');
    HelpdeskUtils.showLoading('workingList');
    
    try {
        const response = await HelpdeskUtils.api.getTickets({
            assigned_to_me: true,
            status: 'IN_PROGRESS'
        });
        
        myTickets.inProgress = response.tickets || [];
        document.getElementById('workingBadge').textContent = myTickets.inProgress.length;
        
        renderTicketList(myTickets.inProgress, container, 'inProgress');
        
    } catch (error) {
        console.error('Error loading in-progress tickets:', error);
        showErrorState(container);
    }
}

async function loadTeamTickets() {
    const container = document.getElementById('teamList');
    HelpdeskUtils.showLoading('teamList');
    
    try {
        // Get current user's team
        const userResponse = await fetch('/api/core/v2/user/me');
        const user = await userResponse.json();
        const userRoles = user.data.roles.helpdesk || [];

        
        let team = null;
        if (userRoles.includes('tech_desarrollo')) {
            team = 'desarrollo';
        } else if (userRoles.includes('tech_soporte')) {
            team = 'soporte';
        }
        
        if (!team) {
            container.innerHTML = `
                <div class="text-center py-5 text-muted">
                    <i class="fas fa-user-slash fa-3x mb-3"></i>
                    <p>No estás asignado a ningún equipo</p>
                </div>
            `;
            return;
        }
        
        const response = await HelpdeskUtils.api.getTickets({
            assigned_to_team: team,
            status: 'ASSIGNED'
        });
        
        myTickets.team = response.tickets || [];
        document.getElementById('teamBadge').textContent = myTickets.team.length;
        
        renderTicketList(myTickets.team, container, 'team');
        
    } catch (error) {
        console.error('Error loading team tickets:', error);
        showErrorState(container);
    }
}

async function loadResolvedTickets() {
    const container = document.getElementById('historyList');
    HelpdeskUtils.showLoading('historyList');

    try {
        // Limit to 20 most recent resolved tickets instead of 100
        const response = await HelpdeskUtils.api.getTickets({
            assigned_to_me: true,
            status: 'RESOLVED_SUCCESS,RESOLVED_FAILED,CLOSED',
            per_page: 20
        });

        myTickets.resolved = response.tickets || [];

        renderTicketList(myTickets.resolved, container, 'resolved');

    } catch (error) {
        console.error('Error loading resolved tickets:', error);
        showErrorState(container);
    }
}

// ==================== RENDER TICKETS ====================
function renderTicketList(tickets, container, type) {
    if (tickets.length === 0) {
        const messages = {
            assigned: { icon: 'inbox', text: 'No tienes tickets asignados', color: 'muted' },
            inProgress: { icon: 'coffee', text: '¡Buen momento para un descanso!', color: 'success' },
            team: { icon: 'users-slash', text: 'No hay tickets del equipo disponibles', color: 'muted' },
            resolved: { icon: 'history', text: 'No hay tickets resueltos', color: 'muted' }
        };
        
        const msg = messages[type];
        container.innerHTML = `
            <div class="text-center py-5 text-${msg.color}">
                <i class="fas fa-${msg.icon} fa-3x mb-3"></i>
                <p class="mb-0">${msg.text}</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = tickets.map(ticket => createTicketCard(ticket, type)).join('');
}

function createTicketCard(ticket, type) {
    const timeAgo = HelpdeskUtils.formatTimeAgo(ticket.created_at);
    
    return `
        <div class="ticket-tech-card border-bottom p-3 priority-${ticket.priority}">
            <div class="row align-items-start">
                <div class="col-md-8">
                    <div class="d-flex align-items-center flex-wrap gap-1 gap-md-2 mb-2">
                        <h6 class="mb-0 fw-bold me-1">${ticket.ticket_number}</h6>
                        <div class="d-flex flex-wrap gap-1">
                            ${HelpdeskUtils.getStatusBadge(ticket.status)}
                            ${HelpdeskUtils.getAreaBadge(ticket.area)}
                            ${ticket.category ? `<span class="badge bg-secondary">${ticket.category.name}</span>` : ''}
                            ${HelpdeskUtils.getPriorityBadge(ticket.priority)}
                        </div>
                    </div>
                    
                    <h5 class="mb-2">${ticket.title}</h5>
                    
                    <p class="text-muted mb-2 small">
                        ${truncateText(ticket.description, 120)}
                    </p>
                    
                    <div class="text-muted small d-flex flex-wrap gap-2">
                        <span><i class="fas fa-user me-1"></i>${ticket.requester?.name || 'N/A'}</span>
                        ${ticket.location ? `
                            <span>
                                <i class="fas fa-map-marker-alt me-1"></i>${ticket.location}
                            </span>
                        ` : ''}
                        <span>
                            <i class="fas fa-clock me-1"></i>${timeAgo}
                        </span>
                    </div>
                    
                    ${ticket.resolution_notes && type === 'resolved' ? `
                        <div class="alert alert-success mt-2 mb-0 py-2 small">
                            <strong>Solución:</strong> ${truncateText(ticket.resolution_notes, 150)}
                        </div>
                    ` : ''}
                    
                    ${ticket.rating && type === 'resolved' ? `
                        <div class="mt-2">
                            ${HelpdeskUtils.renderStarRating(ticket.rating)}
                        </div>
                    ` : ''}
                </div>
                
                <div class="col-md-4 text-md-end mt-2 mt-md-0">
                    ${getActionButtons(ticket, type)}
                </div>
            </div>
        </div>
    `;
}

function getActionButtons(ticket, type) {
    let buttons = '';
    
    if (type === 'assigned') {
        buttons = `
            <button class="btn btn-primary btn-sm mb-2" onclick="openStartWorkModal(${ticket.id})">
                <i class="fas fa-play me-1"></i>Iniciar
            </button>
        `;
    } else if (type === 'inProgress') {
        buttons = `
            <button class="btn btn-success btn-sm mb-2" onclick="openResolveModal(${ticket.id})">
                <i class="fas fa-check-circle me-1"></i>Resolver
            </button>
        `;
    } else if (type === 'team') {
        buttons = `
            <button class="btn btn-primary btn-sm mb-2" onclick="openSelfAssignModal(${ticket.id})">
                <i class="fas fa-hand-paper me-1"></i>Tomar
            </button>
        `;
    }
    
    buttons += `
        <button class="btn btn-outline-secondary btn-sm d-block w-100"
                onclick="goToTicketDetailWithState(${ticket.id})">
            <i class="fas fa-eye me-1"></i>Ver Detalle
        </button>
    `;
    
    return buttons;
}

function goToTicketDetailWithState(ticketId) {
    const activeTabEl = document.querySelector('#technicianTabs .nav-link.active');
    HelpdeskUtils.NavState.save('technician_dashboard', {
        activeTab: activeTabEl?.id || 'queue-tab',
        historyFilter: document.getElementById('historyFilter')?.value || '',
        historySearch: document.getElementById('historySearch')?.value || '',
        scrollY: window.scrollY,
    });
    HelpdeskUtils.goToTicketDetail(ticketId, 'technician');
}

// ==================== DASHBOARD STATS ====================
async function updateDashboardStats() {
    try {
        // Use dedicated stats endpoint instead of local calculations
        const response = await HelpdeskUtils.api.getTechnicianStats();
        const stats = response.data;
        
        const totalTickets = stats.assigned_count + stats.in_progress_count;
        
        document.getElementById('myTicketsCount').textContent = totalTickets;
        document.getElementById('assignedCount').textContent = stats.assigned_count;
        document.getElementById('inProgressCount').textContent = stats.in_progress_count;
        document.getElementById('resolvedTodayCount').textContent = stats.resolved_today_count || 0;
        
    } catch (error) {
        console.error('Error loading technician stats:', error);
        // Fallback to local calculations if API fails
        const totalTickets = myTickets.assigned.length + myTickets.inProgress.length;
        
        // Count resolved today from loaded tickets
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const resolvedToday = myTickets.resolved.filter(t => {
            const resolvedDate = new Date(t.resolved_at);
            return resolvedDate >= today;
        }).length;
        
        document.getElementById('myTicketsCount').textContent = totalTickets;
        document.getElementById('assignedCount').textContent = myTickets.assigned.length;
        document.getElementById('inProgressCount').textContent = myTickets.inProgress.length;
        document.getElementById('resolvedTodayCount').textContent = resolvedToday;
    }
}

// ==================== START WORK MODAL ====================
function setupModals() {
    document.getElementById('btnConfirmStart').addEventListener('click', confirmStartWork);
    document.getElementById('btnConfirmResolve').addEventListener('click', confirmResolve);
    document.getElementById('btnConfirmSelfAssign').addEventListener('click', confirmSelfAssign);
    const resolutionNotes = document.getElementById('resolutionNotes');
    if (resolutionNotes) {
        resolutionNotes.addEventListener('input', updateNotesCounter);
        resolutionNotes.addEventListener('blur', updateNotesCounter);
    }
}

function openStartWorkModal(ticketId) {
    ticketToStart = myTickets.assigned.find(t => t.id === ticketId);
    if (!ticketToStart) return;
    
    document.getElementById('startWorkTicketInfo').innerHTML = `
        <h6 class="mb-2">${ticketToStart.ticket_number}: ${ticketToStart.title}</h6>
        <div class="d-flex gap-2">
            ${HelpdeskUtils.getPriorityBadge(ticketToStart.priority)}
            ${HelpdeskUtils.getAreaBadge(ticketToStart.area)}
        </div>
    `;
    
    // Reiniciar estado del botón
    const btn = document.getElementById('btnConfirmStart');
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-play me-2"></i>Sí, Iniciar';
    
    const modal = new bootstrap.Modal(document.getElementById('startWorkModal'));
    modal.show();
}
window.openStartWorkModal = openStartWorkModal;

async function confirmStartWork() {
    if (!ticketToStart) return;
    
    const btn = document.getElementById('btnConfirmStart');
    const originalText = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Iniciando...';
    
    try {
        await HelpdeskUtils.api.startTicket(ticketToStart.id);
        
        HelpdeskUtils.showToast('¡Ticket iniciado! Ahora está en progreso', 'success');
        
        const modal = bootstrap.Modal.getInstance(document.getElementById('startWorkModal'));
        modal.hide();
        
        // Refresh
        await Promise.all([
            loadAssignedTickets(),
            loadInProgressTickets()
        ]);
        updateDashboardStats();
        
    } catch (error) {
        console.error('Error starting ticket:', error);
        const errorMessage = error.message || 'Error desconocido';
        HelpdeskUtils.showToast(`Error al iniciar ticket: ${errorMessage}`, 'error');
        
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// ==================== RESOLVE TAB ====================
function openResolveModal(ticketId) {
    ticketToResolve = myTickets.inProgress.find(t => t.id === ticketId);
    if (!ticketToResolve) return;

    document.getElementById('resolveTicketInfo').innerHTML = `
        <h6 class="mb-2">${ticketToResolve.ticket_number}: ${ticketToResolve.title}</h6>
        <div class="d-flex gap-2 mb-2">
            ${HelpdeskUtils.getStatusBadge(ticketToResolve.status)}
            ${HelpdeskUtils.getPriorityBadge(ticketToResolve.priority)}
        </div>
        <p class="mb-0 small text-muted">${truncateText(ticketToResolve.description, 200)}</p>
    `;

    // Fill reference panel
    const refTitle = document.getElementById('resolveRefTitle');
    const refDesc = document.getElementById('resolveRefDesc');
    const refMeta = document.getElementById('resolveRefMeta');
    if (refTitle) refTitle.textContent = `${ticketToResolve.ticket_number}: ${ticketToResolve.title}`;
    if (refDesc) refDesc.textContent = ticketToResolve.description || '-';
    if (refMeta) refMeta.innerHTML = `
        ${HelpdeskUtils.getStatusBadge(ticketToResolve.status)}
        ${HelpdeskUtils.getPriorityBadge(ticketToResolve.priority)}
    `;

    // Reset form
    const notesField = document.getElementById('resolutionNotes');
    notesField.value = '';
    notesField.classList.remove('is-invalid', 'is-valid');
    document.getElementById('resolutionSuccess').checked = true;
    document.getElementById('timeInvested').value = '';
    document.getElementById('timeUnit').value = 'minutes';
    updateNotesCounter();

    const btn = document.getElementById('btnConfirmResolve');
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-check-circle me-2"></i>Resolver Ticket';

    updateResolutionFilesCount(0);

    const isSoporte = ticketToResolve.area === 'SOPORTE';
    const soporteFields = document.getElementById('soporteOnlyFields');
    const observationsField = document.getElementById('observationsField');
    if (soporteFields) soporteFields.style.display = isSoporte ? '' : 'none';
    if (observationsField) observationsField.style.display = isSoporte ? '' : 'none';

    // Reset warehouse materials if present
    if (typeof TicketWarehouse !== 'undefined') TicketWarehouse.reset();

    // Update tab label and show resolve tab
    const tabLabel = document.getElementById('resolveTabLabel');
    if (tabLabel) tabLabel.textContent = ticketToResolve.ticket_number;
    const tabItem = document.getElementById('resolveTabItem');
    if (tabItem) tabItem.classList.remove('d-none');
    const resolveTab = new bootstrap.Tab(document.getElementById('resolve-tab'));
    resolveTab.show();

    loadAvailableTechnicians(ticketToResolve);
}
window.openResolveModal = openResolveModal;

function closeResolveTab() {
    const tabItem = document.getElementById('resolveTabItem');
    if (tabItem) tabItem.classList.add('d-none');
    const workingTabEl = document.getElementById('working-tab');
    if (workingTabEl) new bootstrap.Tab(workingTabEl).show();
}
window.closeResolveTab = closeResolveTab;

function updateNotesCounter() {
    const notesField = document.getElementById('resolutionNotes');
    const counter = document.getElementById('resolutionNotesCounter');
    if (!notesField || !counter) return;
    const length = notesField.value.trim().length;
    counter.textContent = `${length} / 10 caracteres mínimo`;
    if (length >= 10) {
        notesField.classList.remove('is-invalid');
        notesField.classList.add('is-valid');
        counter.classList.remove('text-danger');
        counter.classList.add('text-success');
    } else if (length > 0) {
        notesField.classList.remove('is-valid');
        notesField.classList.add('is-invalid');
        counter.classList.remove('text-success');
        counter.classList.add('text-danger');
    } else {
        notesField.classList.remove('is-invalid', 'is-valid');
        counter.classList.remove('text-success', 'text-danger');
    }
}

async function loadAvailableTechnicians(ticket) {
    const container = document.getElementById('collaboratorsList');
    
    // Mostrar loading
    container.innerHTML = `
        <div class="text-center text-muted py-2">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Cargando técnicos...
        </div>
    `;
    
    try {
        // Obtener técnicos del área del ticket
        const response = await fetch(`/api/help-desk/v2/assignments/technicians/${ticket.area}`);
        
        if (!response.ok) {
            throw new Error('Error al cargar técnicos');
        }
        
        const data = await response.json();
        const technicians = data.technicians || [];
        
        if (technicians.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-2">
                    <i class="fas fa-users-slash me-2"></i>
                    No hay técnicos disponibles
                </div>
            `;
            return;
        }
        
        // Renderizar checkboxes
        container.innerHTML = technicians.map(tech => {
            const isAssigned = ticket.assigned_to && tech.id === ticket.assigned_to.id;
            
            return `
                <div class="form-check mb-2">
                    <input class="form-check-input collaborator-check" 
                           type="checkbox" 
                           value="${tech.id}" 
                           id="collab_${tech.id}"
                           ${isAssigned ? 'checked disabled' : ''}>
                    <label class="form-check-label d-flex justify-content-between align-items-center w-100" 
                           for="collab_${tech.id}">
                        <span>
                            ${tech.name}
                            ${isAssigned ? '<span class="badge bg-primary ms-2">Asignado</span>' : ''}
                        </span>
                        <small class="text-muted">${tech.active_tickets} activos</small>
                    </label>
                </div>
            `;
        }).join('');
        
    } catch (error) {
        console.error('Error loading technicians:', error);
        container.innerHTML = `
            <div class="text-center text-danger py-2">
                <i class="fas fa-exclamation-triangle me-2"></i>
                <small>Error al cargar técnicos</small>
            </div>
        `;
    }
}

async function confirmResolve() {
    if (!ticketToResolve) return;

    const isSoporte = ticketToResolve.area === 'SOPORTE';
    const resolutionType = document.querySelector('input[name="resolutionType"]:checked').value;
    const notes = document.getElementById('resolutionNotes').value.trim();
    const maintenanceType = isSoporte ? document.querySelector('input[name="maintenanceType"]:checked')?.value : null;
    const serviceOrigin = isSoporte ? document.querySelector('input[name="serviceOrigin"]:checked')?.value : null;
    const observations = isSoporte ? (document.getElementById('observations')?.value.trim() || null) : null;

    // Obtener tiempo y convertir a minutos segun la unidad seleccionada
    const timeValue = parseFloat(document.getElementById('timeInvested').value) || null;
    const timeUnit = document.getElementById('timeUnit').value;
    let timeInvested = null;

    if (timeValue && timeValue > 0) {
        switch (timeUnit) {
            case 'minutes':
                timeInvested = Math.round(timeValue);
                break;
            case 'hours':
                timeInvested = Math.round(timeValue * 60);
                break;
            case 'days':
                // 1 dia = 8 horas laborales = 480 minutos
                timeInvested = Math.round(timeValue * 8 * 60);
                break;
            default:
                timeInvested = Math.round(timeValue);
        }
    }

    // Validar campos de Soporte
    if (isSoporte) {
        if (!maintenanceType) {
            HelpdeskUtils.showToast('Debe seleccionar el tipo de mantenimiento', 'warning');
            return;
        }
        if (!serviceOrigin) {
            HelpdeskUtils.showToast('Debe seleccionar el origen del equipo', 'warning');
            return;
        }
    }

    // Validar notas
    if (!notes || notes.length < 10) {
        HelpdeskUtils.showToast('Las notas de resolución deben tener al menos 10 caracteres', 'warning');
        const notesEl = document.getElementById('resolutionNotes');
        if (notesEl) {
            notesEl.focus();
            notesEl.classList.add('is-invalid');
            notesEl.classList.remove('is-valid');
            updateNotesCounter();
        }
        return;
    }
    // Marcar notas como válidas
    const notesEl = document.getElementById('resolutionNotes');
    if (notesEl) {
        notesEl.classList.remove('is-invalid');
        notesEl.classList.add('is-valid');
    }

    // Validar tiempo invertido (requerido)
    if (!timeInvested || timeInvested <= 0) {
        HelpdeskUtils.showToast('El tiempo invertido es requerido', 'warning');
        document.getElementById('timeInvested').focus();
        return;
    }

    const btn = document.getElementById('btnConfirmResolve');
    const originalText = btn.innerHTML;

    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Resolviendo...';

    try {
        // 0. Consumir materiales del almacén (si aplica)
        if (typeof TicketWarehouse !== 'undefined') {
            await TicketWarehouse.consumeAll(ticketToResolve.id);
        }

        // 1. Resolver el ticket
        await HelpdeskUtils.api.resolveTicket(ticketToResolve.id, {
            success: resolutionType === 'success',
            resolution_notes: notes,
            time_invested_minutes: timeInvested,
            maintenance_type: maintenanceType,
            service_origin: serviceOrigin,
            observations: observations
        });
        
        // 2. Capturar colaboradores seleccionados (NUEVO)
        const selectedCollaborators = [];
        
        // Obtener checkboxes marcados (excepto el disabled que es el asignado)
        document.querySelectorAll('.collaborator-check:checked:not(:disabled)').forEach(checkbox => {
            selectedCollaborators.push({
                user_id: parseInt(checkbox.value),
                collaboration_role: 'COLLABORATOR', // Se auto-sugiere en backend
                time_invested_minutes: null,
                notes: null
            });
        });
        
        // El asignado principal siempre se agrega como LEAD
        if (ticketToResolve.assigned_to && ticketToResolve.assigned_to.id) {
            selectedCollaborators.push({
                user_id: ticketToResolve.assigned_to.id,
                collaboration_role: 'LEAD',
                time_invested_minutes: timeInvested,
                notes: notes
            });
        }
        
        // 3. Agregar colaboradores si hay (NUEVO)
        if (selectedCollaborators.length > 0) {
            try {
                const collabResponse = await fetch(
                    `/api/help-desk/v2/tickets/${ticketToResolve.id}/collaborators/batch`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ collaborators: selectedCollaborators })
                    }
                );
                
                if (collabResponse.ok) {
                    const collabData = await collabResponse.json();
                    console.log(`${collabData.count} colaboradores agregados`);
                } else {
                    console.warn('No se pudieron agregar algunos colaboradores');
                    // No bloquear el flujo si falla esto
                }
            } catch (collabError) {
                console.error('Error adding collaborators:', collabError);
                // No bloquear el flujo
            }
        }
        
        // 4. Mostrar éxito
        HelpdeskUtils.showToast(
            resolutionType === 'success' 
                ? '¡Ticket resuelto exitosamente!' 
                : 'Ticket marcado como atendido',
            'success'
        );
        
        // 5. Cerrar panel
        closeResolveTab();
        
        // 6. Refrescar listas
        await Promise.all([
            loadInProgressTickets(),
            loadResolvedTickets()
        ]);
        updateDashboardStats();
        
    } catch (error) {
        console.error('Error resolving ticket:', error);
        const errorMessage = error.message || 'Error desconocido';
        HelpdeskUtils.showToast(`Error al resolver ticket: ${errorMessage}`, 'error');
        
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// ==================== SELF-ASSIGN MODAL ====================
function openSelfAssignModal(ticketId) {
    ticketToSelfAssign = myTickets.team.find(t => t.id === ticketId);
    if (!ticketToSelfAssign) return;
    
    document.getElementById('selfAssignTicketInfo').innerHTML = `
        <h6 class="mb-2">${ticketToSelfAssign.ticket_number}: ${ticketToSelfAssign.title}</h6>
        <div class="d-flex gap-2">
            ${HelpdeskUtils.getPriorityBadge(ticketToSelfAssign.priority)}
            ${HelpdeskUtils.getAreaBadge(ticketToSelfAssign.area)}
        </div>
    `;
    
    // Reiniciar estado del botón
    const btn = document.getElementById('btnConfirmSelfAssign');
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-hand-paper me-2"></i>Sí, Tomar Ticket';
    
    const modal = new bootstrap.Modal(document.getElementById('selfAssignModal'));
    modal.show();
}
window.openSelfAssignModal = openSelfAssignModal;

async function confirmSelfAssign() {
    if (!ticketToSelfAssign) return;
    
    const btn = document.getElementById('btnConfirmSelfAssign');
    const originalText = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Asignando...';
    
    try {
        await HelpdeskUtils.api.selfAssignTicket(ticketToSelfAssign.id);
        
        HelpdeskUtils.showToast('¡Ticket asignado a ti!', 'success');
        
        // Reiniciar botón ANTES de cerrar el modal
        btn.disabled = false;
        btn.innerHTML = originalText;
        
        const modal = bootstrap.Modal.getInstance(document.getElementById('selfAssignModal'));
        modal.hide();
        
        // Refresh
        await Promise.all([
            loadAssignedTickets(),
            loadTeamTickets()
        ]);
        updateDashboardStats();
        
    } catch (error) {
        console.error('Error self-assigning ticket:', error);
        const errorMessage = error.message || 'Error desconocido';
        HelpdeskUtils.showToast(`Error al tomar ticket: ${errorMessage}`, 'error');
        
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// ==================== FILTERS ====================
function setupFilters() {
    const historyFilter = document.getElementById('historyFilter');
    const historySearch = document.getElementById('historySearch');
    
    historyFilter.addEventListener('change', applyHistoryFilters);
    
    let searchTimeout;
    historySearch.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(applyHistoryFilters, 300);
    });
}

function applyHistoryFilters() {
    const filter = document.getElementById('historyFilter').value;
    const search = document.getElementById('historySearch').value.toLowerCase().trim();
    
    let filtered = [...myTickets.resolved];
    
    // Time filter
    const now = new Date();
    if (filter === 'today') {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        filtered = filtered.filter(t => new Date(t.resolved_at) >= today);
    } else if (filter === 'week') {
        const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        filtered = filtered.filter(t => new Date(t.resolved_at) >= weekAgo);
    } else if (filter === 'month') {
        const monthAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
        filtered = filtered.filter(t => new Date(t.resolved_at) >= monthAgo);
    }
    
    // Search filter
    if (search) {
        filtered = filtered.filter(t => 
            t.title.toLowerCase().includes(search) ||
            t.ticket_number.toLowerCase().includes(search) ||
            t.description.toLowerCase().includes(search)
        );
    }
    
    renderTicketList(filtered, document.getElementById('historyList'), 'resolved');
}

// ==================== WEBSOCKET REAL-TIME UPDATES ====================

/**
 * Debounce helper para evitar múltiples recargas rápidas
 */
function debounce(fn, delay) {
    let timeoutId;
    return function(...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn.apply(this, args), delay);
    };
}

/**
 * Configura los listeners de WebSocket para actualizaciones en tiempo real
 */
function setupWebSocketListeners() {
    // Esperar a que el socket esté disponible
    const checkSocket = setInterval(() => {
        if (window.__helpdeskSocket) {
            clearInterval(checkSocket);
            bindSocketEvents();
        }
    }, 100);

    // Timeout después de 5 segundos
    setTimeout(() => clearInterval(checkSocket), 5000);
}

/**
 * Une a los rooms y configura los event listeners
 */
async function bindSocketEvents() {
    if (socketRoomsBound) return;

    const socket = window.__helpdeskSocket;
    if (!socket) {
        console.warn('[Dashboard] Socket no disponible');
        return;
    }

    // Obtener el área del técnico
    try {
        const userResponse = await fetch('/api/core/v2/user/me');
        const user = await userResponse.json();
        const userRoles = user.data.roles.helpdesk || [];

        if (userRoles.includes('tech_desarrollo')) {
            techArea = 'desarrollo';
        } else if (userRoles.includes('tech_soporte')) {
            techArea = 'soporte';
        }
    } catch (e) {
        console.warn('[Dashboard] No se pudo obtener área del técnico:', e);
    }

    // Unirse a los rooms correspondientes
    window.__hdJoinTech?.();
    if (techArea) {
        window.__hdJoinTeam?.(techArea);
    }

    // Configurar listeners con debounce (250ms)
    const debouncedRefreshAssigned = debounce(() => {
        loadAssignedTickets();
        updateDashboardStats();
        showRealtimeToast('Nueva asignación recibida');
    }, 250);

    const debouncedRefreshTeam = debounce(() => {
        loadTeamTickets();
        updateDashboardStats();
    }, 250);

    const debouncedRefreshAll = debounce(() => {
        loadAssignedTickets();
        loadInProgressTickets();
        loadTeamTickets();
        updateDashboardStats();
    }, 250);

    // Remover listeners previos (si los hay) para evitar duplicados
    socket.off('ticket_assigned');
    socket.off('ticket_reassigned');
    socket.off('ticket_status_changed');
    socket.off('ticket_created');
    socket.off('ticket_self_assigned');

    // Nuevo ticket asignado a mí
    socket.on('ticket_assigned', (data) => {
        console.log('[Dashboard] ticket_assigned:', data);
        debouncedRefreshAssigned();
    });

    // Ticket reasignado (puede ser a mí o desde mí)
    socket.on('ticket_reassigned', (data) => {
        console.log('[Dashboard] ticket_reassigned:', data);
        debouncedRefreshAll();
        showRealtimeToast('Ticket reasignado');
    });

    // Cambio de estado de ticket
    socket.on('ticket_status_changed', (data) => {
        console.log('[Dashboard] ticket_status_changed:', data);
        // Refrescar según el tab activo
        const activeTab = document.querySelector('.nav-link.active[data-bs-toggle="tab"]');
        const tabId = activeTab?.getAttribute('href') || '';

        if (tabId.includes('queue')) {
            loadAssignedTickets();
        } else if (tabId.includes('working')) {
            loadInProgressTickets();
        } else if (tabId.includes('team')) {
            loadTeamTickets();
        } else if (tabId.includes('history')) {
            loadResolvedTickets();
        }
        updateDashboardStats();
    });

    // Nuevo ticket creado (para el pool del equipo)
    socket.on('ticket_created', (data) => {
        console.log('[Dashboard] ticket_created:', data);
        // Solo refrescar si el ticket es de mi área
        if (techArea && data.area?.toLowerCase() === techArea) {
            debouncedRefreshTeam();
            showRealtimeToast(`Nuevo ticket: ${data.ticket_number}`);
        }
    });

    // Ticket auto-asignado por otro técnico (sale del pool)
    socket.on('ticket_self_assigned', (data) => {
        console.log('[Dashboard] ticket_self_assigned:', data);
        debouncedRefreshTeam();
    });

    socketRoomsBound = true;
    console.log('[Dashboard] WebSocket listeners configurados');
}

/**
 * Muestra un toast sutil para actualizaciones en tiempo real
 */
function showRealtimeToast(message) {
    // Usar HelpdeskUtils si está disponible, sino crear toast simple
    if (window.HelpdeskUtils?.showToast) {
        HelpdeskUtils.showToast(message, 'info');
    }
}

// ==================== HELPERS ====================
function truncateText(text, maxLength) {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
}

function showErrorState(container) {
    container.innerHTML = `
        <div class="text-center py-5">
            <i class="fas fa-exclamation-triangle fa-3x text-danger mb-3"></i>
            <p class="text-danger">Error al cargar tickets</p>
            <button class="btn btn-primary" onclick="refreshDashboard()">
                <i class="fas fa-redo me-2"></i>Reintentar
            </button>
        </div>
    `;
}

// ==================== RESOLUTION FILES ====================
function getFileIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const icons = {
        pdf: 'fas fa-file-pdf text-danger',
        xlsx: 'fas fa-file-excel text-success',
        xls: 'fas fa-file-excel text-success',
        csv: 'fas fa-file-csv text-success',
        doc: 'fas fa-file-word text-primary',
        docx: 'fas fa-file-word text-primary',
    };
    return icons[ext] || 'fas fa-file text-secondary';
}

function formatFileSize(bytes) {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function openResolutionFilesModal() {
    if (!ticketToResolve) return;
    const modal = new bootstrap.Modal(document.getElementById('resolutionFilesModal'));
    loadResolutionFiles();
    setupResolutionDropzone();
    modal.show();
}
window.openResolutionFilesModal = openResolutionFilesModal;

let resDropzoneSetup = false;

function setupResolutionDropzone() {
    if (resDropzoneSetup) return;
    resDropzoneSetup = true;

    const dropzone = document.getElementById('resolutionDropzone');
    const input = document.getElementById('resolutionFileInput');

    dropzone.addEventListener('click', () => input.click());

    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.style.borderColor = '#0d6efd';
        dropzone.style.backgroundColor = '#f0f7ff';
    });

    dropzone.addEventListener('dragleave', () => {
        dropzone.style.borderColor = '#dee2e6';
        dropzone.style.backgroundColor = '';
    });

    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.style.borderColor = '#dee2e6';
        dropzone.style.backgroundColor = '';
        uploadResolutionFiles(Array.from(e.dataTransfer.files));
    });

    input.addEventListener('change', function () {
        uploadResolutionFiles(Array.from(this.files));
        this.value = '';
    });
}

async function loadResolutionFiles() {
    if (!ticketToResolve) return;
    try {
        const response = await HelpdeskUtils.api.getAttachmentsByType(ticketToResolve.id, 'resolution');
        const attachments = response.attachments || [];
        renderResolutionFilesList(attachments);
        updateResolutionFilesCount(attachments.length);
    } catch (error) {
        console.error('Error loading resolution files:', error);
    }
}

function renderResolutionFilesList(attachments) {
    const container = document.getElementById('resolutionFilesList');
    if (attachments.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-3">
                <i class="fas fa-folder-open fa-2x mb-2"></i>
                <p class="mb-0">Sin archivos adjuntos</p>
            </div>`;
        return;
    }

    container.innerHTML = attachments.map(att => {
        const isImage = att.mime_type && att.mime_type.startsWith('image/');
        const downloadUrl = `/api/help-desk/v2/attachments/${att.id}/download`;
        const icon = isImage ? 'fas fa-image text-info' : getFileIcon(att.original_filename);

        return `
            <div class="d-flex align-items-center justify-content-between border rounded p-2 mb-2">
                <div class="d-flex align-items-center gap-2 flex-grow-1 min-width-0">
                    ${isImage ? `<img src="${downloadUrl}" class="rounded" style="width:40px;height:40px;object-fit:cover;cursor:pointer;"
                        onclick="viewAttachmentImage('${downloadUrl}', '${att.original_filename}')">` :
                `<i class="${icon} fa-lg"></i>`}
                    <div class="min-width-0">
                        <div class="text-truncate fw-semibold" style="max-width:300px;" title="${att.original_filename}">${att.original_filename}</div>
                        <small class="text-muted">${formatFileSize(att.file_size)} - ${HelpdeskUtils.formatTimeAgo(att.uploaded_at)}</small>
                    </div>
                </div>
                <div class="d-flex gap-1 flex-shrink-0">
                    <a href="${downloadUrl}" class="btn btn-sm btn-outline-primary" download="${att.original_filename}" title="Descargar">
                        <i class="fas fa-download"></i>
                    </a>
                    <button class="btn btn-sm btn-outline-danger" onclick="deleteResolutionFile(${att.id})" title="Eliminar">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>`;
    }).join('');
}

function updateResolutionFilesCount(count) {
    const badge = document.getElementById('resolutionFilesCount');
    if (badge) badge.textContent = count;
    const modalCount = document.getElementById('resFilesModalCount');
    if (modalCount) modalCount.textContent = `${count} / 10`;
}

async function uploadResolutionFiles(files) {
    if (!ticketToResolve || !files.length) return;

    const progressContainer = document.getElementById('resUploadProgress');
    const progressBar = document.getElementById('resUploadBar');
    const progressText = document.getElementById('resUploadText');

    progressContainer.classList.remove('d-none');
    let uploaded = 0;

    for (const file of files) {
        progressText.textContent = `Subiendo ${file.name}...`;
        progressBar.style.width = `${(uploaded / files.length) * 100}%`;
        try {
            await HelpdeskUtils.api.uploadFile(ticketToResolve.id, file, 'resolution');
            uploaded++;
        } catch (error) {
            HelpdeskUtils.showToast(`Error al subir ${file.name}: ${error.message}`, 'error');
        }
    }

    progressBar.style.width = '100%';
    progressText.textContent = `${uploaded} de ${files.length} archivos subidos`;
    setTimeout(() => {
        progressContainer.classList.add('d-none');
        progressBar.style.width = '0%';
    }, 1500);

    if (uploaded > 0) {
        HelpdeskUtils.showToast(`${uploaded} archivo(s) subido(s)`, 'success');
    }
    loadResolutionFiles();
}

async function deleteResolutionFile(attachmentId) {
    const confirmed = await HelpdeskUtils.confirmDialog(
        'Eliminar archivo',
        '¿Estás seguro de eliminar este archivo?',
        'Eliminar',
        'Cancelar'
    );
    if (!confirmed) return;

    try {
        await HelpdeskUtils.api.deleteAttachment(attachmentId);
        HelpdeskUtils.showToast('Archivo eliminado', 'success');
        loadResolutionFiles();
    } catch (error) {
        HelpdeskUtils.showToast(`Error al eliminar: ${error.message}`, 'error');
    }
}
window.deleteResolutionFile = deleteResolutionFile;

function viewAttachmentImage(url, title) {
    const modal = new bootstrap.Modal(document.getElementById('attachmentImageModal'));
    document.getElementById('attachmentImageModalImg').src = url;
    document.getElementById('attachmentImageTitle').innerHTML = `<i class="fas fa-image me-2"></i>${title || 'Imagen'}`;
    modal.show();
}
window.viewAttachmentImage = viewAttachmentImage;