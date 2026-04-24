// itcj/apps/helpdesk/static/js/department_head/dashboard.js

/**
 * Department Head Dashboard - Sistema de Tickets ITCJ
 * Gestión de tickets y usuarios del departamento
 */

// ==================== GLOBAL STATE ====================
let departmentTickets = [];
let departmentUsers = [];

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', () => {
    // Guardar la página actual para navegación inteligente
    sessionStorage.setItem('helpdesk_last_page', JSON.stringify({
        url: window.location.href,
        text: 'Departamento'
    }));
    
    initializeDashboard();
    setupFilters();
});

async function initializeDashboard() {
    try {
        await Promise.all([
            loadDepartmentStats(),
            loadDepartmentTickets(),
            loadDepartmentUsers(),
            loadPendingTasks(),
        ]);

        // loadRecentActivity depends on departmentTickets being populated
        await loadRecentActivity();

        // Load stats tab lazy
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

// ==================== LOAD STATS ====================
async function loadDepartmentStats() {
    try {
        // Use dedicated stats endpoint instead of loading all tickets
        const response = await HelpdeskUtils.api.getDepartmentStats(DEPARTMENT_ID);
        const stats = response.data;
        
        // Update UI
        document.getElementById('activeTicketsCount').textContent = stats.active_tickets || 0;
        document.getElementById('resolvedCount').textContent = stats.resolved_tickets || 0;
        
        // Format average time
        const avgTime = stats.avg_resolution_hours 
            ? `${stats.avg_resolution_hours.toFixed(1)}h`
            : '-';
        document.getElementById('avgTime').textContent = avgTime;
        
        // Format satisfaction
        const satisfaction = stats.satisfaction_percent !== null && stats.rated_tickets_count > 0
            ? `${stats.satisfaction_percent.toFixed(0)}%`
            : '-';
        document.getElementById('satisfaction').textContent = satisfaction;
        
    } catch (error) {
        console.error('Error loading stats:', error);
        // Set fallback values
        document.getElementById('activeTicketsCount').textContent = '-';
        document.getElementById('resolvedCount').textContent = '-';
        document.getElementById('avgTime').textContent = '-';
        document.getElementById('satisfaction').textContent = '-';
    }
}

// ==================== LOAD TICKETS ====================
async function loadDepartmentTickets() {
    const container = document.getElementById('ticketsList');
    HelpdeskUtils.showLoading('ticketsList');
    
    try {
        const response = await HelpdeskUtils.api.getTickets({
            department_id: DEPARTMENT_ID,
            per_page: 100
        });
        
        departmentTickets = response.tickets || [];
        document.getElementById('ticketsBadge').textContent = departmentTickets.length;
        
        renderTickets(departmentTickets);
        
    } catch (error) {
        console.error('Error loading tickets:', error);
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-exclamation-triangle fa-3x text-danger mb-3"></i>
                <p class="text-danger">Error al cargar tickets</p>
            </div>
        `;
    }
}

function renderTickets(tickets) {
    const container = document.getElementById('ticketsList');
    
    if (tickets.length === 0) {
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-inbox fa-3x text-muted mb-3"></i>
                <p class="text-muted">No hay tickets del departamento</p>
                <button class="btn btn-primary mt-3" onclick="window.location.href='/help-desk/user/create'">
                    <i class="fas fa-plus me-2"></i>Crear Primer Ticket
                </button>
            </div>
        `;
        return;
    }
    
    container.innerHTML = tickets.map(ticket => `
        <div class="ticket-dept-card border-bottom p-3" 
             onclick="HelpdeskUtils.goToTicketDetail(${ticket.id}, 'department')">
            <div class="d-flex justify-content-between align-items-start">
                <div class="flex-grow-1">
                    <div class="d-flex align-items-center gap-2 mb-2">
                        <h6 class="mb-0 fw-bold">${ticket.ticket_number}</h6>
                        ${HelpdeskUtils.getStatusBadge(ticket.status)}
                        ${HelpdeskUtils.getAreaBadge(ticket.area)}
                        ${ticket.category ? `<span class="badge bg-secondary">${ticket.category.name}</span>` : ''}
                        ${HelpdeskUtils.getPriorityBadge(ticket.priority)}
                    </div>
                    
                    <h5 class="mb-2">${ticket.title}</h5>
                    
                    <div class="text-muted small">
                        <i class="fas fa-user me-1"></i>${ticket.requester?.name || 'N/A'}
                        ${ticket.location ? `
                            <span class="ms-3">
                                <i class="fas fa-map-marker-alt me-1"></i>${ticket.location}
                            </span>
                        ` : ''}
                        <span class="ms-3">
                            <i class="fas fa-clock me-1"></i>${HelpdeskUtils.formatTimeAgo(ticket.created_at)}
                        </span>
                        ${ticket.assigned_to ? `
                            <span class="ms-3 text-primary">
                                <i class="fas fa-user-check me-1"></i>${ticket.assigned_to.name}
                            </span>
                        ` : ''}
                    </div>
                </div>
            </div>
        </div>
    `).join('');
}

// ==================== LOAD USERS ====================
let _showInactiveUsers = false;

window.toggleInactiveUsers = function(checked) {
    _showInactiveUsers = checked;
    loadDepartmentUsers();
};

async function loadDepartmentUsers() {
    const container = document.getElementById('usersList');
    HelpdeskUtils.showLoading('usersList');

    const url = `/api/core/v2/departments/${DEPARTMENT_ID}/users` +
                (_showInactiveUsers ? '?include_inactive=true' : '');

    try {
        const response = await fetch(url, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('auth_token') || ''}`
            }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();

        if (result.status !== 'ok') {
            throw new Error(result.error || 'Error en la respuesta del servidor');
        }

        departmentUsers = result.data.users || [];
        const activeCount = departmentUsers.filter(u => u.is_active).length;
        document.getElementById('usersCount').textContent =
            _showInactiveUsers ? `${activeCount}+${departmentUsers.length - activeCount}` : activeCount;

        renderUsers(departmentUsers);

    } catch (error) {
        console.error('Error loading users:', error);
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-exclamation-triangle fa-3x text-danger mb-3"></i>
                <p class="text-danger">Error al cargar usuarios del departamento</p>
                <small class="text-muted">${error.message}</small>
            </div>
        `;
    }
}

function renderUsers(users) {
    const container = document.getElementById('usersList');
    
    if (users.length === 0) {
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-users-slash fa-3x text-muted mb-3"></i>
                <p class="text-muted">No hay usuarios asignados al departamento</p>
                <small class="text-muted">Los usuarios deben tener puestos activos en este departamento</small>
            </div>
        `;
        return;
    }
    
    container.innerHTML = users.map(user => `
        <div class="border-bottom p-3">
            <div class="d-flex justify-content-between align-items-start">
                <div class="d-flex align-items-center gap-3">
                    <div class="activity-icon bg-primary bg-opacity-10 text-primary">
                        <i class="fas fa-user"></i>
                    </div>
                    <div>
                        <div class="fw-bold">${user.name}</div>
                        <small class="text-muted d-block">
                            <i class="fas fa-envelope me-1"></i>${user.email || user.username}
                        </small>
                        <small class="text-muted d-block">
                            <i class="fas fa-briefcase me-1"></i>${user.position.title}
                        </small>
                        ${user.assignment.start_date ? `
                            <small class="text-muted d-block">
                                <i class="fas fa-calendar me-1"></i>Desde: ${new Date(user.assignment.start_date).toLocaleDateString('es-ES')}
                            </small>
                        ` : ''}
                    </div>
                </div>
                <div class="d-flex flex-column gap-1 align-items-end">
                    <span class="badge ${user.is_active ? 'bg-success' : 'bg-secondary'}">
                        ${user.is_active ? 'Activo' : 'Inactivo'}
                    </span>
                    <span class="badge bg-info">
                        ${user.ticket_count || 0} tickets
                    </span>
                    ${user.role ? `
                        <span class="badge bg-secondary">
                            ${user.role}
                        </span>
                    ` : ''}
                </div>
            </div>
        </div>
    `).join('');
}

// ==================== RECENT ACTIVITY ====================
async function loadRecentActivity() {
    const container = document.getElementById('recentActivity');
    
    try {
        // Get last 5 tickets
        const recent = [...departmentTickets]
            .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
            .slice(0, 5);
        
        if (recent.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-3">
                    <i class="fas fa-inbox fa-2x mb-2"></i>
                    <p class="mb-0 small">Sin actividad reciente</p>
                </div>
            `;
            return;
        }
        
        container.innerHTML = recent.map(ticket => {
            const icon = ticket.status === 'CLOSED' ? 'check-circle' :
                        ticket.status === 'RESOLVED_SUCCESS' ? 'check' :
                        ticket.status === 'IN_PROGRESS' ? 'cog' :
                        'ticket-alt';
            
            const color = ticket.status === 'CLOSED' ? 'success' :
                         ticket.status === 'RESOLVED_SUCCESS' ? 'primary' :
                         ticket.status === 'IN_PROGRESS' ? 'info' :
                         'secondary';
            
            return `
                <div class="activity-item border-bottom">
                    <div class="d-flex align-items-center gap-3">
                        <div class="activity-icon bg-${color} bg-opacity-10 text-${color}">
                            <i class="fas fa-${icon}"></i>
                        </div>
                        <div class="flex-grow-1">
                            <div class="fw-bold small">${ticket.title}</div>
                            <small class="text-muted">
                                ${ticket.requester?.name} • ${HelpdeskUtils.formatTimeAgo(ticket.created_at)}
                            </small>
                        </div>
                        ${HelpdeskUtils.getStatusBadge(ticket.status)}
                    </div>
                </div>
            `;
        }).join('');
        
    } catch (error) {
        console.error('Error loading recent activity:', error);
        container.innerHTML = `
            <div class="text-center text-danger py-3">
                <small>Error al cargar actividad</small>
            </div>
        `;
    }
}

// ==================== FILTERS ====================
function setupFilters() {
    const filterStatus = document.getElementById('filterStatus');
    const filterArea = document.getElementById('filterArea');
    const searchTickets = document.getElementById('searchTickets');
    
    filterStatus.addEventListener('change', applyFilters);
    filterArea.addEventListener('change', applyFilters);
    
    let searchTimeout;
    searchTickets.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(applyFilters, 300);
    });
}

function applyFilters() {
    const status = document.getElementById('filterStatus').value;
    const area = document.getElementById('filterArea').value;
    const search = document.getElementById('searchTickets').value.toLowerCase().trim();
    
    let filtered = [...departmentTickets];
    
    if (status) {
        filtered = filtered.filter(t => t.status === status);
    }
    
    if (area) {
        filtered = filtered.filter(t => t.area === area);
    }
    
    if (search) {
        filtered = filtered.filter(t =>
            t.title.toLowerCase().includes(search) ||
            t.requester?.name.toLowerCase().includes(search) ||
            t.ticket_number.toLowerCase().includes(search)
        );
    }
    
    renderTickets(filtered);
}

// ==================== MODALS ====================
function openCreateUserModal() {
    const modal = new bootstrap.Modal(document.getElementById('createUserModal'));
    modal.show();
}
window.openCreateUserModal = openCreateUserModal;



// ==================== STATISTICS ====================
async function loadStatistics() {
    try {
        // Month stats
        const now = new Date();
        const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
        
        const monthTickets = departmentTickets.filter(t => 
            new Date(t.created_at) >= monthStart
        );
        
        const resolved = monthTickets.filter(t => 
            ['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED'].includes(t.status)
        );
        
        document.getElementById('monthStats').innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3">
                <span>Tickets Creados</span>
                <h4 class="text-primary mb-0">${monthTickets.length}</h4>
            </div>
            <div class="d-flex justify-content-between align-items-center mb-3">
                <span>Resueltos</span>
                <h4 class="text-success mb-0">${resolved.length}</h4>
            </div>
            <div class="d-flex justify-content-between align-items-center">
                <span>Tasa de Resolución</span>
                <h4 class="text-info mb-0">
                    ${monthTickets.length > 0 ? Math.round(resolved.length / monthTickets.length * 100) : 0}%
                </h4>
            </div>
        `;
        
        // Category stats
        const byCategory = {};
        departmentTickets.forEach(t => {
            const cat = t.category?.name || 'Sin categoría';
            byCategory[cat] = (byCategory[cat] || 0) + 1;
        });
        
        const total = departmentTickets.length;
        const categoryHtml = Object.entries(byCategory)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 5)
            .map(([cat, count]) => {
                const percent = Math.round(count / total * 100);
                return `
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <span>${cat}</span>
                        <div class="d-flex align-items-center">
                            <div class="progress me-2" style="width: 100px; height: 8px;">
                                <div class="progress-bar bg-primary" style="width: ${percent}%"></div>
                            </div>
                            <strong>${percent}%</strong>
                        </div>
                    </div>
                `;
            }).join('');
        
        document.getElementById('categoryStats').innerHTML = categoryHtml || 
            '<p class="text-muted text-center">Sin datos</p>';
        
    } catch (error) {
        console.error('Error loading statistics:', error);
    }
}


// ==================== TAREAS PENDIENTES ====================

async function loadPendingTasks() {
    const container = document.getElementById('pendingTasksContainer');
    if (!container) return;

    try {
        const res = await fetch('/api/help-desk/v2/department-head/pending-tasks');
        const json = await res.json();
        if (!json.success) throw new Error(json.error || 'Error al cargar tareas');

        renderPendingTasks(json.data);
    } catch (error) {
        console.error('Error loading pending tasks:', error);
        container.innerHTML = '<p class="text-muted text-center py-3 small">No se pudieron cargar las tareas pendientes.</p>';
    }
}

function renderPendingTasks(data) {
    const container = document.getElementById('pendingTasksContainer');
    const badge = document.getElementById('pendingTasksBadge');
    if (!container) return;

    const campaigns        = data.campaigns        || [];
    const retirements      = data.pending_retirements || [];
    const unratedCount     = data.unrated_tickets?.count || 0;
    const unratedUrl       = data.unrated_tickets?.url   || '#';

    const totalCount = campaigns.length + retirements.length + (unratedCount > 0 ? 1 : 0);

    // Actualizar badge del card header
    if (badge) {
        if (totalCount > 0) {
            badge.textContent = totalCount;
            badge.classList.remove('d-none');
        } else {
            badge.classList.add('d-none');
        }
    }

    if (totalCount === 0) {
        container.innerHTML = `
            <div class="text-center py-4">
                <i class="fas fa-check-circle fa-2x text-success mb-2"></i>
                <p class="text-muted mb-0 small">Sin tareas pendientes</p>
            </div>`;
        return;
    }

    const rows = [];

    // Campañas de inventario pendientes de validación
    campaigns.forEach(c => {
        rows.push(`
            <div class="d-flex align-items-center justify-content-between px-3 py-2 border-bottom">
                <div class="d-flex align-items-center gap-2">
                    <i class="fas fa-box-open text-primary" style="width:18px;"></i>
                    <div>
                        <div class="fw-semibold small">${escHtml(c.folio)} — Campaña de Inventario</div>
                        <div class="text-muted" style="font-size:.8rem;">Pendiente de validación${c.pending_count ? ' · ' + c.pending_count + ' equipos' : ''}</div>
                    </div>
                </div>
                <a href="${escHtml(c.url)}" class="btn btn-sm btn-outline-primary">
                    <i class="fas fa-arrow-right"></i> Validar
                </a>
            </div>`);
    });

    // Solicitudes de baja esperando firma
    retirements.forEach(r => {
        const statusLabel = {
            'AWAITING_RECURSOS_MATERIALES': 'Firma — Rec. Materiales',
            'AWAITING_SUBDIRECTOR':         'Firma — Subdirector',
            'AWAITING_DIRECTOR':            'Firma — Director',
        }[r.status] || r.status;
        rows.push(`
            <div class="d-flex align-items-center justify-content-between px-3 py-2 border-bottom">
                <div class="d-flex align-items-center gap-2">
                    <i class="fas fa-file-signature text-warning" style="width:18px;"></i>
                    <div>
                        <div class="fw-semibold small">${escHtml(r.folio)} — Solicitud de Baja</div>
                        <div class="text-muted" style="font-size:.8rem;">Requiere tu autorización · ${escHtml(statusLabel)}</div>
                    </div>
                </div>
                <a href="${escHtml(r.url)}" class="btn btn-sm btn-outline-warning">
                    <i class="fas fa-arrow-right"></i> Revisar
                </a>
            </div>`);
    });

    // Tickets sin calificar
    if (unratedCount > 0) {
        rows.push(`
            <div class="d-flex align-items-center justify-content-between px-3 py-2">
                <div class="d-flex align-items-center gap-2">
                    <i class="fas fa-star text-info" style="width:18px;"></i>
                    <div>
                        <div class="fw-semibold small">${unratedCount} ticket${unratedCount > 1 ? 's' : ''} sin calificar</div>
                        <div class="text-muted" style="font-size:.8rem;">Los usuarios aún no han evaluado la atención</div>
                    </div>
                </div>
                <a href="${escHtml(unratedUrl)}" class="btn btn-sm btn-outline-info">
                    <i class="fas fa-arrow-right"></i> Ver
                </a>
            </div>`);
    }

    container.innerHTML = rows.join('');
}

function escHtml(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}
