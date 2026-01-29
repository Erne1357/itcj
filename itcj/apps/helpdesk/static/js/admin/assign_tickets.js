// itcj/apps/helpdesk/static/js/secretary/dashboard.js

/**
 * Secretary Dashboard - Sistema de Tickets ITCJ
 * Gestión y asignación de tickets
 */

// ==================== GLOBAL STATE ====================
let allPendingTickets = [];
let allActiveTickets = [];
let allTechnicians = [];
let ticketToAssign = null;
let ticketToReassign = null;

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', () => {
    initializeDashboard();
    setupFilters();
    setupAssignmentModal();
    setupReassignmentModal();
    setupWebSocketListeners();
});

async function initializeDashboard() {
    try {
        await Promise.all([
            loadDashboardStats(),
            loadPendingTickets(),
            loadActiveTickets(),
            loadTechnicians()
        ]);
        
        // Load stats tab (lazy load)
        document.getElementById('stats-tab').addEventListener('shown.bs.tab', loadStatistics);
        
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

// ==================== DASHBOARD STATS ====================
async function loadDashboardStats() {
    try {
        // Get all tickets and calculate stats
        const response = await HelpdeskUtils.api.getTickets({});
        const allTickets = response.tickets || [];
        
        // Count by status
        const pending = allTickets.filter(t => t.status === 'PENDING').length;
        const unassigned = allTickets.filter(t => t.status === 'PENDING' && !t.assigned_to_user_id).length;
        const inProgress = allTickets.filter(t => t.status === 'IN_PROGRESS').length;
        
        // Count today's tickets
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const todayTickets = allTickets.filter(t => {
            const createdDate = new Date(t.created_at);
            return createdDate >= today;
        }).length;
        
        // Update cards
        document.getElementById('pendingCount').textContent = pending;
        document.getElementById('unassignedCount').textContent = unassigned;
        document.getElementById('inProgressCount').textContent = inProgress;
        document.getElementById('todayCount').textContent = todayTickets;
        
        // Check urgent tickets
        const urgentTickets = allTickets.filter(t => 
            t.priority === 'URGENTE' && ['PENDING', 'ASSIGNED'].includes(t.status)
        );
        
        if (urgentTickets.length > 0) {
            document.getElementById('urgentBadge').style.display = 'inline-block';
            document.getElementById('urgentCount').textContent = urgentTickets.length;
            showUrgentAlert(urgentTickets);
        }
        
    } catch (error) {
        console.error('Error loading dashboard stats:', error);
    }
}

function showUrgentAlert(urgentTickets) {
    const alert = document.getElementById('urgentAlert');
    const list = document.getElementById('urgentTicketsList');
    
    list.innerHTML = urgentTickets.map(ticket => `
        <div class="card mb-2 border-danger">
            <div class="card-body py-2">
                <div class="d-flex justify-content-between align-items-center">
                    <div class="flex-grow-1">
                        <h6 class="mb-1">${ticket.ticket_number}: ${ticket.title}</h6>
                        <small class="text-muted">
                            <i class="fas fa-user me-1"></i>${ticket.requester?.name || 'N/A'}
                            ${ticket.location ? `<i class="fas fa-map-marker-alt ms-2 me-1"></i>${ticket.location}` : ''}
                            <i class="fas fa-clock ms-2 me-1"></i>${HelpdeskUtils.formatTimeAgo(ticket.created_at)}
                        </small>
                    </div>
                    <button class="btn btn-danger btn-sm" onclick="openAssignmentModal(${ticket.id})">
                        <i class="fas fa-bolt me-1"></i>Asignar Ahora
                    </button>
                </div>
            </div>
        </div>
    `).join('');
    
    alert.classList.remove('d-none');
}

// ==================== PENDING TICKETS (QUEUE) ====================
async function loadPendingTickets() {
    const container = document.getElementById('queueList');
    HelpdeskUtils.showLoading('queueList');
    
    try {
        const response = await HelpdeskUtils.api.getTickets({ 
            status: 'PENDING',
            per_page: 50 
        });
        
        allPendingTickets = response.tickets || [];
        
        // Update badge
        document.getElementById('queueBadge').textContent = allPendingTickets.length;
        
        renderPendingTickets(allPendingTickets);
        
    } catch (error) {
        console.error('Error loading pending tickets:', error);
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-exclamation-triangle fa-3x text-danger mb-3"></i>
                <p class="text-danger">Error al cargar tickets pendientes</p>
                <button class="btn btn-primary" onclick="loadPendingTickets()">
                    <i class="fas fa-redo me-2"></i>Reintentar
                </button>
            </div>
        `;
    }
}
window.loadPendingTickets = loadPendingTickets;

function renderPendingTickets(tickets) {
    const container = document.getElementById('queueList');
    
    if (tickets.length === 0) {
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-check-circle fa-3x text-success mb-3"></i>
                <h5 class="text-success">¡Excelente trabajo!</h5>
                <p class="text-muted">No hay tickets pendientes de asignación</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = tickets.map(ticket => createPendingTicketCard(ticket)).join('');
}

function createPendingTicketCard(ticket) {
    return `
        <div class="ticket-queue-card border-bottom p-3 priority-${ticket.priority}" 
             onclick="showTicketQuickView(${ticket.id})">
            <div class="row align-items-center">
                <div class="col-md-8">
                    <div class="d-flex align-items-center gap-2 mb-2">
                        <h6 class="mb-0 fw-bold">${ticket.ticket_number}</h6>
                        ${HelpdeskUtils.getAreaBadge(ticket.area)}
                        ${HelpdeskUtils.getPriorityBadge(ticket.priority)}
                        ${ticket.category ? `<span class="badge bg-secondary">${ticket.category.name}</span>` : ''}
                    </div>
                    
                    <h5 class="mb-2">${ticket.title}</h5>
                    
                    <p class="text-muted mb-2 small" style="max-width: 600px;">
                        ${truncateText(ticket.description, 120)}
                    </p>
                    
                    <div class="text-muted small">
                        <i class="fas fa-user me-1"></i>${ticket.requester?.name || 'N/A'}
                        ${ticket.department ? `
                            <span class="ms-3">
                                <i class="fas fa-building me-1"></i>${ticket.department.name}
                            </span>
                        ` : ''}
                        ${ticket.location ? `
                            <span class="ms-3">
                                <i class="fas fa-map-marker-alt me-1"></i>${ticket.location}
                            </span>
                        ` : ''}
                        <span class="ms-3">
                            <i class="fas fa-clock me-1"></i>${HelpdeskUtils.formatTimeAgo(ticket.created_at)}
                        </span>
                    </div>
                </div>
                
                <div class="col-md-4 text-end">
                    <button class="btn btn-primary btn-sm" 
                            onclick="event.stopPropagation(); openAssignmentModal(${ticket.id})">
                        <i class="fas fa-user-plus me-1"></i>Asignar
                    </button>
                </div>
            </div>
        </div>
    `;
}

// ==================== ACTIVE TICKETS ====================
async function loadActiveTickets() {
    const container = document.getElementById('activeList');
    HelpdeskUtils.showLoading('activeList');
    
    try {
        const response = await HelpdeskUtils.api.getTickets({ 
            status: 'ASSIGNED,IN_PROGRESS',
            per_page: 100 
        });
        
        allActiveTickets = response.tickets || [];
        
        // Update badge
        document.getElementById('activeBadge').textContent = allActiveTickets.length;
        
        renderActiveTickets(allActiveTickets);
        
        // Render by area
        const desarrollo = allActiveTickets.filter(t => t.area === 'DESARROLLO');
        const soporte = allActiveTickets.filter(t => t.area === 'SOPORTE');
        
        renderActiveTickets(desarrollo, 'activeDesarrolloList');
        renderActiveTickets(soporte, 'activeSoporteList');
        
    } catch (error) {
        console.error('Error loading active tickets:', error);
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-exclamation-triangle fa-3x text-danger mb-3"></i>
                <p class="text-danger">Error al cargar tickets activos</p>
            </div>
        `;
    }
}

function renderActiveTickets(tickets, containerId = 'activeList') {
    const container = document.getElementById(containerId);
    
    if (tickets.length === 0) {
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-inbox fa-3x text-muted mb-3"></i>
                <p class="text-muted">No hay tickets activos</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = tickets.map(ticket => `
        <div class="border-bottom p-3">
            <div class="d-flex justify-content-between align-items-start">
                <div class="flex-grow-1">
                    <div class="d-flex align-items-center gap-2 mb-2">
                        <h6 class="mb-0">${ticket.ticket_number}</h6>
                        ${HelpdeskUtils.getStatusBadge(ticket.status)}
                        ${HelpdeskUtils.getPriorityBadge(ticket.priority)}
                    </div>
                    
                    <h5 class="mb-2">${ticket.title}</h5>
                    
                    <div class="text-muted small">
                        <i class="fas fa-user me-1"></i>${ticket.requester?.name || 'N/A'}
                        ${ticket.assigned_to ? `
                            <span class="ms-3 text-primary">
                                <i class="fas fa-user-check me-1"></i>${ticket.assigned_to.name}
                            </span>
                        ` : ticket.assigned_to_team ? `
                            <span class="ms-3 text-info">
                                <i class="fas fa-users me-1"></i>Equipo ${ticket.assigned_to_team}
                            </span>
                        ` : ''}
                        <span class="ms-3">
                            <i class="fas fa-clock me-1"></i>${HelpdeskUtils.formatTimeAgo(ticket.created_at)}
                        </span>
                    </div>
                </div>
                
                <div class="d-flex gap-2">
                    <button class="btn btn-sm btn-outline-warning" 
                            onclick="openReassignmentModal(${ticket.id})">
                        <i class="fas fa-exchange-alt"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-primary" 
                            onclick="showTicketDetail(${ticket.id})">
                        <i class="fas fa-eye"></i>
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

// ==================== TECHNICIANS ====================
async function loadTechnicians() {
    try {
        // Load technicians for both areas
        const [desarrollo, soporte] = await Promise.all([
            HelpdeskUtils.api.request('/assignments/technicians/DESARROLLO'),
            HelpdeskUtils.api.request('/assignments/technicians/SOPORTE')
        ]);
        
        allTechnicians = [
            ...(desarrollo.technicians || []).map(t => ({ ...t, area: 'DESARROLLO' })),
            ...(soporte.technicians || []).map(t => ({ ...t, area: 'SOPORTE' }))
        ];
        
        renderTechnicians();
        populateTechnicianSelects();
        
    } catch (error) {
        console.error('Error loading technicians:', error);
    }
}

function renderTechnicians() {
    const desarrollo = allTechnicians.filter(t => t.area === 'DESARROLLO');
    const soporte = allTechnicians.filter(t => t.area === 'SOPORTE');
    
    renderTechniciansList(desarrollo, 'techDesarrolloList');
    renderTechniciansList(soporte, 'techSoporteList');
}

function renderTechniciansList(technicians, containerId) {
    const container = document.getElementById(containerId);
    
    if (technicians.length === 0) {
        container.innerHTML = `
            <div class="text-center py-3 text-muted">
                <i class="fas fa-user-slash mb-2"></i>
                <p class="mb-0 small">No hay técnicos disponibles</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = technicians.map(tech => {
        const initials = tech.name.split(' ').map(n => n[0]).join('').substring(0, 2);
        const loadClass = tech.active_tickets <= 3 ? 'load-low' : 
                         tech.active_tickets <= 6 ? 'load-medium' : 'load-high';
        
        return `
            <div class="technician-card border rounded p-3 mb-3">
                <div class="d-flex align-items-center gap-3">
                    <div class="technician-avatar">${initials}</div>
                    <div class="flex-grow-1">
                        <div class="fw-bold">${tech.name}</div>
                        <small class="text-muted">${tech.username}</small>
                        <div class="load-indicator mt-2">
                            <div class="load-indicator-fill ${loadClass}"></div>
                        </div>
                        <small class="text-muted">${tech.active_tickets} ticket${tech.active_tickets !== 1 ? 's' : ''} activo${tech.active_tickets !== 1 ? 's' : ''}</small>
                    </div>
                    <button class="btn btn-sm btn-outline-primary" 
                            onclick="filterByTechnician(${tech.id})">
                        <i class="fas fa-list"></i>
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function filterByTechnician(technicianId) {
    // Switch to active tab and filter
    const activeTab = new bootstrap.Tab(document.getElementById('active-tab'));
    activeTab.show();
    
    const filtered = allActiveTickets.filter(t => t.assigned_to_user_id === technicianId);
    renderActiveTickets(filtered);
    
    HelpdeskUtils.showToast(`Mostrando tickets del técnico seleccionado`, 'info');
}
window.filterByTechnician = filterByTechnician;

// ==================== ASSIGNMENT MODAL ====================
function setupAssignmentModal() {
    // Toggle between user/team assignment
    document.querySelectorAll('input[name="assignType"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const isUser = e.target.value === 'user';
            document.getElementById('selectTechnicianContainer').classList.toggle('d-none', !isUser);
            document.getElementById('selectTeamContainer').classList.toggle('d-none', isUser);
        });
    });
    
    // Technician select change
    document.getElementById('technicianSelect').addEventListener('change', (e) => {
        const techId = parseInt(e.target.value);
        const tech = allTechnicians.find(t => t.id === techId);
        
        if (tech) {
            const loadText = tech.active_tickets <= 3 ? '✅ Carga baja' :
                           tech.active_tickets <= 6 ? '⚠️ Carga media' : '🔴 Carga alta';
            document.getElementById('technicianLoad').textContent = 
                `${loadText} - ${tech.active_tickets} tickets activos`;
        }
    });
    
    // Confirm button
    document.getElementById('btnConfirmAssign').addEventListener('click', confirmAssignment);
}

function populateTechnicianSelects() {
    const select = document.getElementById('technicianSelect');
    
    // Group by area
    const desarrollo = allTechnicians.filter(t => t.area === 'DESARROLLO');
    const soporte = allTechnicians.filter(t => t.area === 'SOPORTE');
    
    let html = '<option value="">Selecciona un técnico...</option>';
    
    if (desarrollo.length > 0) {
        html += '<optgroup label="Desarrollo">';
        desarrollo.forEach(tech => {
            html += `<option value="${tech.id}">${tech.name} (${tech.active_tickets} activos)</option>`;
        });
        html += '</optgroup>';
    }
    
    if (soporte.length > 0) {
        html += '<optgroup label="Soporte">';
        soporte.forEach(tech => {
            html += `<option value="${tech.id}">${tech.name} (${tech.active_tickets} activos)</option>`;
        });
        html += '</optgroup>';
    }
    
    select.innerHTML = html;
    
    // Also populate reassignment select
    document.getElementById('newTechnicianSelect').innerHTML = html + `
        <optgroup label="Equipos">
            <option value="team:desarrollo">Equipo Desarrollo</option>
            <option value="team:soporte">Equipo Soporte</option>
        </optgroup>
    `;
}

function openAssignmentModal(ticketId) {
    ticketToAssign = allPendingTickets.find(t => t.id === ticketId);
    if (!ticketToAssign) {
        HelpdeskUtils.showToast('Ticket no encontrado', 'error');
        return;
    }
    
    // Fill ticket info
    document.getElementById('assignTicketInfo').innerHTML = `
        <h6 class="mb-2">${ticketToAssign.ticket_number}: ${ticketToAssign.title}</h6>
        <div class="d-flex gap-2 mb-2">
            ${HelpdeskUtils.getAreaBadge(ticketToAssign.area)}
            ${HelpdeskUtils.getPriorityBadge(ticketToAssign.priority)}
            ${ticketToAssign.category ? `<span class="badge bg-secondary">${ticketToAssign.category.name}</span>` : ''}
        </div>
        <p class="mb-0 small text-muted">${truncateText(ticketToAssign.description, 150)}</p>
        ${ticketToAssign.location ? `
            <small class="text-muted">
                <i class="fas fa-map-marker-alt me-1"></i>${ticketToAssign.location}
            </small>
        ` : ''}
    `;
    
    // Reset form
    document.getElementById('assignUser').checked = true;
    document.getElementById('selectTechnicianContainer').classList.remove('d-none');
    document.getElementById('selectTeamContainer').classList.add('d-none');
    document.getElementById('technicianSelect').value = '';
    document.getElementById('teamSelect').value = '';
    document.getElementById('assignmentReason').value = '';
    document.getElementById('technicianLoad').textContent = '';
    
    // Pre-select team based on area (smart suggestion)
    if (ticketToAssign.area === 'DESARROLLO') {
        document.getElementById('teamSelect').value = 'desarrollo';
    } else {
        document.getElementById('teamSelect').value = 'soporte';
    }
    
    const modal = new bootstrap.Modal(document.getElementById('assignmentModal'));
    modal.show();
}
window.openAssignmentModal = openAssignmentModal;

async function confirmAssignment() {
    const assignType = document.querySelector('input[name="assignType"]:checked').value;
    const reason = document.getElementById('assignmentReason').value.trim();
    
    let assignedToUserId = null;
    let assignedToTeam = null;
    
    if (assignType === 'user') {
        const techId = document.getElementById('technicianSelect').value;
        if (!techId) {
            HelpdeskUtils.showToast('Selecciona un técnico', 'warning');
            return;
        }
        assignedToUserId = parseInt(techId);
    } else {
        const team = document.getElementById('teamSelect').value;
        if (!team) {
            HelpdeskUtils.showToast('Selecciona un equipo', 'warning');
            return;
        }
        assignedToTeam = team;
    }
    
    const btn = document.getElementById('btnConfirmAssign');
    const originalText = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Asignando...';
    
    try {
        await HelpdeskUtils.api.assignTicket(
            ticketToAssign.id,
            assignedToUserId,
            assignedToTeam,
            reason || null
        );
        
        HelpdeskUtils.showToast('Ticket asignado exitosamente', 'success');
        
        // Reset button
        btn.disabled = false;
        btn.innerHTML = originalText;
        
        // Close modal
        const modal = bootstrap.Modal.getInstance(document.getElementById('assignmentModal'));
        modal.hide();
        
        // Refresh dashboard
        await Promise.all([
            loadDashboardStats(),
            loadPendingTickets(),
            loadActiveTickets(),
            loadTechnicians()
        ]);
        
    } catch (error) {
        console.error('Error assigning ticket:', error);
        const errorMessage = error.message || 'Error desconocido';
        HelpdeskUtils.showToast(`Error al asignar ticket: ${errorMessage}`, 'error');
        
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// ==================== REASSIGNMENT MODAL ====================
function setupReassignmentModal() {
    document.getElementById('btnConfirmReassign').addEventListener('click', confirmReassignment);
}

function openReassignmentModal(ticketId) {
    ticketToReassign = allActiveTickets.find(t => t.id === ticketId);
    if (!ticketToReassign) {
        HelpdeskUtils.showToast('Ticket no encontrado', 'error');
        return;
    }
    
    // Fill ticket info
    document.getElementById('reassignTicketInfo').innerHTML = `
        <h6 class="mb-2">${ticketToReassign.ticket_number}: ${ticketToReassign.title}</h6>
        <div class="mb-2">
            ${HelpdeskUtils.getStatusBadge(ticketToReassign.status)}
            ${HelpdeskUtils.getPriorityBadge(ticketToReassign.priority)}
        </div>
        <p class="mb-2 small"><strong>Asignado actualmente a:</strong></p>
        ${ticketToReassign.assigned_to ? `
            <div class="alert alert-info mb-0 py-2">
                <i class="fas fa-user-check me-2"></i>${ticketToReassign.assigned_to.name}
            </div>
        ` : ticketToReassign.assigned_to_team ? `
            <div class="alert alert-info mb-0 py-2">
                <i class="fas fa-users me-2"></i>Equipo ${ticketToReassign.assigned_to_team}
            </div>
        ` : ''}
    `;
    
    // Reset form
    document.getElementById('newTechnicianSelect').value = '';
    document.getElementById('reassignReason').value = '';
    
    const modal = new bootstrap.Modal(document.getElementById('reassignmentModal'));
    modal.show();
}
window.openReassignmentModal = openReassignmentModal;

async function confirmReassignment() {
    const newAssignee = document.getElementById('newTechnicianSelect').value;
    const reason = document.getElementById('reassignReason').value.trim();
    
    if (!newAssignee) {
        HelpdeskUtils.showToast('Selecciona nuevo técnico/equipo', 'warning');
        return;
    }
    
    if (!reason) {
        HelpdeskUtils.showToast('Proporciona una razón para la reasignación', 'warning');
        return;
    }
    
    let assignedToUserId = null;
    let assignedToTeam = null;
    
    if (newAssignee.startsWith('team:')) {
        assignedToTeam = newAssignee.replace('team:', '');
    } else {
        assignedToUserId = parseInt(newAssignee);
    }
    
    const btn = document.getElementById('btnConfirmReassign');
    const originalText = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Reasignando...';
    
    try {
        await HelpdeskUtils.api.request(`/assignments/${ticketToReassign.id}/reassign`, {
            method: 'POST',
            body: JSON.stringify({
                assigned_to_user_id: assignedToUserId,
                assigned_to_team: assignedToTeam,
                reason: reason
            })
        });
        
        HelpdeskUtils.showToast('Ticket reasignado exitosamente', 'success');
        
        // Reset button
        btn.disabled = false;
        btn.innerHTML = originalText;
        
        // Close modal
        const modal = bootstrap.Modal.getInstance(document.getElementById('reassignmentModal'));
        modal.hide();
        
        // Refresh
        await loadActiveTickets();
        await loadTechnicians();
        
    } catch (error) {
        console.error('Error reassigning ticket:', error);
        const errorMessage = error.message || 'Error desconocido';
        HelpdeskUtils.showToast(`Error al reasignar ticket: ${errorMessage}`, 'error');
        
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// ==================== FILTERS ====================
function setupFilters() {
    const filterArea = document.getElementById('filterArea');
    const filterPriority = document.getElementById('filterPriority');
    const searchQueue = document.getElementById('searchQueue');
    
    filterArea.addEventListener('change', applyFilters);
    filterPriority.addEventListener('change', applyFilters);
    
    let searchTimeout;
    searchQueue.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(applyFilters, 300);
    });
}

function applyFilters() {
    const area = document.getElementById('filterArea').value;
    const priority = document.getElementById('filterPriority').value;
    const search = document.getElementById('searchQueue').value.toLowerCase().trim();
    
    let filtered = [...allPendingTickets];
    
    if (area) {
        filtered = filtered.filter(t => t.area === area);
    }
    
    if (priority) {
        filtered = filtered.filter(t => t.priority === priority);
    }
    
    if (search) {
        filtered = filtered.filter(t => {
            return t.title.toLowerCase().includes(search) ||
                   t.description.toLowerCase().includes(search) ||
                   t.ticket_number.toLowerCase().includes(search) ||
                   t.requester?.name.toLowerCase().includes(search) ||
                   t.location?.toLowerCase().includes(search);
        });
    }
    
    renderPendingTickets(filtered);
}

// ==================== STATISTICS ====================
async function loadStatistics() {
    try {
        // Simple stats for now
        const todayStats = document.getElementById('todayStats');
        const deptStats = document.getElementById('deptStats');
        const timeStats = document.getElementById('timeStats');
        
        // For MVP, show placeholder stats
        todayStats.innerHTML = `
            <div class="d-flex justify-content-between mb-2">
                <span>Recibidos</span>
                <strong>${document.getElementById('todayCount').textContent}</strong>
            </div>
            <div class="d-flex justify-content-between mb-2">
                <span>Pendientes</span>
                <strong>${document.getElementById('pendingCount').textContent}</strong>
            </div>
            <div class="d-flex justify-content-between mb-2">
                <span>En Proceso</span>
                <strong>${document.getElementById('inProgressCount').textContent}</strong>
            </div>
            <div class="d-flex justify-content-between">
                <span>Completados</span>
                <strong>-</strong>
            </div>
        `;
        
        deptStats.innerHTML = `
            <p class="text-muted text-center">Estadísticas detalladas próximamente</p>
        `;
        
        timeStats.innerHTML = `
            <p class="text-muted text-center">Métricas de tiempo próximamente</p>
        `;
        
    } catch (error) {
        console.error('Error loading statistics:', error);
    }
}

// ==================== QUICK VIEW ====================
function showTicketQuickView(ticketId) {
    // For now, just show toast with ticket number
    const ticket = allPendingTickets.find(t => t.id === ticketId) || 
                   allActiveTickets.find(t => t.id === ticketId);
    
    window.location.href = `/help-desk/user/tickets/${ticketId}`;
}
window.showTicketQuickView = showTicketQuickView;

// ==================== WEBSOCKET REAL-TIME UPDATES ====================

/**
 * Debounce helper
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
    const checkSocket = setInterval(() => {
        if (window.__helpdeskSocket) {
            clearInterval(checkSocket);
            bindAssignSocketEvents();
        }
    }, 100);

    setTimeout(() => clearInterval(checkSocket), 5000);
}

function bindAssignSocketEvents() {
    const socket = window.__helpdeskSocket;
    if (!socket) return;

    // Unirse al room de admin
    window.__hdJoinAdmin?.();

    const debouncedRefreshPending = debounce(() => {
        loadPendingTickets();
        loadDashboardStats();
        HelpdeskUtils.showToast('Nuevo ticket pendiente', 'info');
    }, 300);

    const debouncedRefreshActive = debounce(() => {
        loadActiveTickets();
        loadTechnicians();
        loadDashboardStats();
    }, 300);

    const debouncedRefreshAll = debounce(() => {
        loadPendingTickets();
        loadActiveTickets();
        loadTechnicians();
        loadDashboardStats();
    }, 300);

    // Remover listeners previos
    socket.off('ticket_created');
    socket.off('ticket_assigned');
    socket.off('ticket_reassigned');
    socket.off('ticket_status_changed');
    socket.off('ticket_self_assigned');

    // Nuevo ticket creado - actualiza cola de pendientes
    socket.on('ticket_created', (data) => {
        console.log('[Assign] ticket_created:', data);
        debouncedRefreshPending();
    });

    // Ticket asignado - sale de pendientes, entra a activos
    socket.on('ticket_assigned', (data) => {
        console.log('[Assign] ticket_assigned:', data);
        debouncedRefreshAll();
    });

    // Ticket reasignado
    socket.on('ticket_reassigned', (data) => {
        console.log('[Assign] ticket_reassigned:', data);
        debouncedRefreshActive();
    });

    // Cambio de estado
    socket.on('ticket_status_changed', (data) => {
        console.log('[Assign] ticket_status_changed:', data);
        debouncedRefreshActive();
    });

    // Técnico tomó un ticket del pool
    socket.on('ticket_self_assigned', (data) => {
        console.log('[Assign] ticket_self_assigned:', data);
        debouncedRefreshAll();
    });

    console.log('[Assign] WebSocket listeners configurados');
}

// ==================== HELPERS ====================
function truncateText(text, maxLength) {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
}

function showTicketDetail(ticketId) {
    HelpdeskUtils.goToTicketDetail(ticketId, 'secretary');
}
window.showTicketDetail = showTicketDetail;