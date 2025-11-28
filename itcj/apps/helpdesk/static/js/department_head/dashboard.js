// itcj/apps/helpdesk/static/js/department_head/dashboard.js

/**
 * Department Head Dashboard - Sistema de Tickets ITCJ
 * Gestión de tickets y         container.innerHTML = tickets.map(ticket => `
        <div class="ticket-dept-card border-bottom p-3" 
             onclick="HelpdeskUtils.goToTicketDetailNewTab(${ticket.id}, 'department')"arios del departamento
 */

// ==================== GLOBAL STATE ====================
let departmentTickets = [];
let departmentUsers = [];
let categories = [];

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', () => {
    // Guardar la página actual para navegación inteligente
    sessionStorage.setItem('helpdesk_last_page', JSON.stringify({
        url: window.location.href,
        text: 'Departamento'
    }));
    
    initializeDashboard();
    setupModals();
    setupFilters();
});

async function initializeDashboard() {
    try {
        await Promise.all([
            loadDepartmentStats(),
            loadDepartmentTickets(),
            loadDepartmentUsers(),
            loadCategories(),
            loadRecentActivity()
        ]);
        
        // Load stats tab lazy
        document.getElementById('stats-tab').addEventListener('shown.bs.tab', loadStatistics);
        
    } catch (error) {
        console.error('Error initializing dashboard:', error);
        HelpdeskUtils.showToast('Error al cargar el dashboard', 'error');
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
        const response = await HelpdeskUtils.api.getTickets({
            department_id: DEPARTMENT_ID,
            per_page: 1000
        });
        
        const tickets = response.items || [];
        
        // Active tickets
        const active = tickets.filter(t => 
            !['CLOSED', 'CANCELED'].includes(t.status)
        ).length;
        
        // Resolved tickets
        const resolved = tickets.filter(t => 
            ['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED'].includes(t.status)
        ).length;
        
        // Calculate average time
        const resolvedWithTime = tickets.filter(t => 
            t.resolved_at && t.created_at
        );
        
        let avgHours = 0;
        if (resolvedWithTime.length > 0) {
            const totalHours = resolvedWithTime.reduce((sum, t) => {
                const created = new Date(t.created_at);
                const resolved = new Date(t.resolved_at);
                const hours = (resolved - created) / (1000 * 60 * 60);
                return sum + hours;
            }, 0);
            avgHours = totalHours / resolvedWithTime.length;
        }
        
        // Calculate satisfaction
        const rated = tickets.filter(t => t.rating);
        const satisfaction = rated.length > 0
            ? (rated.reduce((sum, t) => sum + t.rating, 0) / rated.length / 5 * 100)
            : 0;
        
        // Update UI
        document.getElementById('activeTicketsCount').textContent = active;
        document.getElementById('resolvedCount').textContent = resolved;
        document.getElementById('avgTime').textContent = avgHours > 0 
            ? `${avgHours.toFixed(1)}h` 
            : '-';
        document.getElementById('satisfaction').textContent = satisfaction > 0 
            ? `${satisfaction.toFixed(0)}%` 
            : '-';
        
    } catch (error) {
        console.error('Error loading stats:', error);
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
        
        departmentTickets = response.items || [];
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
                <button class="btn btn-primary mt-3" onclick="openCreateTicketModal()">
                    <i class="fas fa-plus me-2"></i>Crear Primer Ticket
                </button>
            </div>
        `;
        return;
    }
    
    container.innerHTML = tickets.map(ticket => `
        <div class="ticket-dept-card border-bottom p-3" 
             onclick="HelpdeskUtils.goToTicketDetailNewTab(${ticket.id}, 'department')"
            <div class="d-flex justify-content-between align-items-start">
                <div class="flex-grow-1">
                    <div class="d-flex align-items-center gap-2 mb-2">
                        <h6 class="mb-0 fw-bold">${ticket.ticket_number}</h6>
                        ${HelpdeskUtils.getStatusBadge(ticket.status)}
                        ${HelpdeskUtils.getAreaBadge(ticket.area)}
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
async function loadDepartmentUsers() {
    const container = document.getElementById('usersList');
    HelpdeskUtils.showLoading('usersList');
    
    try {
        // Usar la nueva API del core para obtener usuarios del departamento
        const response = await fetch(`/api/core/v1/departments/${DEPARTMENT_ID}/users`, {
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
        
        document.getElementById('usersCount').textContent = departmentUsers.length;
        
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

// ==================== CATEGORIES ====================
async function loadCategories() {
    try {
        const response = await HelpdeskUtils.api.getCategories();
        categories = response.categories || [];
    } catch (error) {
        console.error('Error loading categories:', error);
    }
}

function updateCategoriesSelect(area) {
    const select = document.getElementById('ticketCategory');
    const filtered = categories.filter(c => c.area === area && c.is_active);
    
    select.innerHTML = filtered.length > 0
        ? '<option value="">Selecciona una categoría...</option>' +
          filtered.map(c => `<option value="${c.id}">${c.name}</option>`).join('')
        : '<option value="">No hay categorías disponibles</option>';
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
function setupModals() {
    // Area change in create ticket
    document.querySelectorAll('input[name="ticketArea"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            updateCategoriesSelect(e.target.value);
        });
    });
    
    // Submit buttons
    document.getElementById('btnSubmitTicket').addEventListener('click', submitTicket);
    document.getElementById('btnSubmitUser').addEventListener('click', submitUser);
}

function openCreateTicketModal() {
    // Reset form
    document.getElementById('createTicketForm').reset();
    document.getElementById('areaSoporte').checked = true;
    updateCategoriesSelect('SOPORTE');
    
    const modal = new bootstrap.Modal(document.getElementById('createTicketModal'));
    modal.show();
}
window.openCreateTicketModal = openCreateTicketModal;

async function submitTicket() {
    const area = document.querySelector('input[name="ticketArea"]:checked').value;
    const categoryId = document.getElementById('ticketCategory').value;
    const title = document.getElementById('ticketTitle').value.trim();
    const description = document.getElementById('ticketDescription').value.trim();
    const priority = document.getElementById('ticketPriority').value;
    const location = document.getElementById('ticketLocation').value.trim();
    
    // Validation
    if (!categoryId) {
        HelpdeskUtils.showToast('Selecciona una categoría', 'warning');
        return;
    }
    
    if (!title || title.length < 5) {
        HelpdeskUtils.showToast('El título debe tener al menos 5 caracteres', 'warning');
        return;
    }
    
    if (!description || description.length < 20) {
        HelpdeskUtils.showToast('La descripción debe tener al menos 20 caracteres', 'warning');
        return;
    }
    
    const btn = document.getElementById('btnSubmitTicket');
    const originalText = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Creando...';
    
    try {
        await HelpdeskUtils.api.createTicket({
            area,
            category_id: parseInt(categoryId),
            title,
            description,
            priority,
            location: location || null
        });
        
        HelpdeskUtils.showToast('Ticket creado exitosamente', 'success');
        
        const modal = bootstrap.Modal.getInstance(document.getElementById('createTicketModal'));
        modal.hide();
        
        // Refresh
        await loadDepartmentTickets();
        await loadDepartmentStats();
        await loadRecentActivity();
        
    } catch (error) {
        console.error('Error creating ticket:', error);
        HelpdeskUtils.showToast(error.message || 'Error al crear ticket', 'error');
        
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

function openCreateUserModal() {
    document.getElementById('createUserForm').reset();
    const modal = new bootstrap.Modal(document.getElementById('createUserModal'));
    modal.show();
}
window.openCreateUserModal = openCreateUserModal;

async function submitUser() {
    const name = document.getElementById('userName').value.trim();
    const username = document.getElementById('userUsername').value.trim();
    const email = document.getElementById('userEmail').value.trim();
    const nip = document.getElementById('userNIP').value.trim();
    
    // Validation
    if (!name || name.length < 3) {
        HelpdeskUtils.showToast('Ingresa un nombre válido', 'warning');
        return;
    }
    
    if (!username || username.length < 3) {
        HelpdeskUtils.showToast('Ingresa un username válido', 'warning');
        return;
    }
    
    if (!/^[a-z0-9._-]+$/.test(username)) {
        HelpdeskUtils.showToast('El username solo puede contener letras minúsculas, números, puntos, guiones', 'warning');
        return;
    }
    
    if (!email || !email.includes('@')) {
        HelpdeskUtils.showToast('Ingresa un email válido', 'warning');
        return;
    }
    
    if (!/^\d{4}$/.test(nip)) {
        HelpdeskUtils.showToast('El NIP debe ser de 4 dígitos', 'warning');
        return;
    }
    
    const btn = document.getElementById('btnSubmitUser');
    const originalText = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Creando...';
    
    try {
        await HelpdeskUtils.api.request(`/department/${DEPARTMENT_ID}/users`, {
            method: 'POST',
            body: JSON.stringify({
                name,
                username,
                email,
                nip,
                department_id: DEPARTMENT_ID
            })
        });
        
        HelpdeskUtils.showToast('Usuario creado exitosamente', 'success');
        
        const modal = bootstrap.Modal.getInstance(document.getElementById('createUserModal'));
        modal.hide();
        
        // Refresh
        await loadDepartmentUsers();
        
    } catch (error) {
        console.error('Error creating user:', error);
        HelpdeskUtils.showToast(error.message || 'Error al crear usuario', 'error');
        
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

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
