// itcj/apps/helpdesk/static/js/secretary/dashboard.js

/**
 * Secretary Dashboard (Simple) - Sistema de Tickets ITCJ
 * Vista limitada: solo tickets del departamento, sin asignación
 */

// ==================== GLOBAL STATE ====================
let allDeptTickets = [];
let allInventoryItems = [];

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', () => {
    initializeDashboard();
    setupFilters();
});

async function initializeDashboard() {
    try {
        await Promise.all([
            loadDashboardStats(),
            loadDepartmentTickets(),
            loadDepartmentInventory()
        ]);
        
        // Load stats tab (lazy load)
        document.getElementById('summary-tab').addEventListener('shown.bs.tab', loadSummaryStats);
        
    } catch (error) {
        console.error('Error initializing dashboard:', error);
        const errorMessage = error.message || 'Error desconocido';
        HelpdeskUtils.showToast(`Error al cargar el dashboard: ${errorMessage}`, 'error');
    }
}

async function refreshDashboard() {
    HelpdeskUtils.showToast('Actualizando...', 'info');
    await initializeDashboard();
    HelpdeskUtils.showToast('Dashboard actualizado', 'success');
}
window.refreshDashboard = refreshDashboard;

// ==================== DASHBOARD STATS ====================
async function loadDashboardStats() {
    try {
        // Get department tickets
        const response = await HelpdeskUtils.api.getTickets({
            department_id: DEPARTMENT_ID,
            per_page: 100
        });
        
        const tickets = response.tickets || [];
        
        // Count active tickets
        const active = tickets.filter(t => 
            ['PENDING', 'ASSIGNED', 'IN_PROGRESS'].includes(t.status)
        ).length;
        
        // Count resolved
        const resolved = tickets.filter(t => 
            ['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED'].includes(t.status)
        ).length;
        
        // Calculate average time (placeholder for now)
        const avgTime = calculateAverageTime(tickets);
        
        // Calculate satisfaction (placeholder for now)
        const satisfaction = calculateSatisfaction(tickets);
        
        // Update cards
        document.getElementById('activeTicketsCount').textContent = active;
        document.getElementById('resolvedCount').textContent = resolved;
        document.getElementById('avgTime').textContent = avgTime;
        document.getElementById('satisfaction').textContent = satisfaction;
        
    } catch (error) {
        console.error('Error loading dashboard stats:', error);
    }
}

function calculateAverageTime(tickets) {
    const resolvedTickets = tickets.filter(t => t.resolved_at);
    if (resolvedTickets.length === 0) return '-';
    
    const totalHours = resolvedTickets.reduce((sum, ticket) => {
        const created = new Date(ticket.created_at);
        const resolved = new Date(ticket.resolved_at);
        const hours = (resolved - created) / (1000 * 60 * 60);
        return sum + hours;
    }, 0);
    
    const avgHours = totalHours / resolvedTickets.length;
    
    if (avgHours < 24) {
        return `${Math.round(avgHours)}h`;
    } else {
        return `${Math.round(avgHours / 24)}d`;
    }
}

function calculateSatisfaction(tickets) {
    const ratedTickets = tickets.filter(t => t.rating !== null && t.rating !== undefined);
    if (ratedTickets.length === 0) return '-';
    
    const avgRating = ratedTickets.reduce((sum, t) => sum + t.rating, 0) / ratedTickets.length;
    return `${avgRating.toFixed(1)}⭐`;
}

// ==================== DEPARTMENT TICKETS ====================
async function loadDepartmentTickets() {
    const container = document.getElementById('ticketsList');
    HelpdeskUtils.showLoading('ticketsList');
    
    try {
        const response = await HelpdeskUtils.api.getTickets({
            department_id: DEPARTMENT_ID,
            per_page: 100
        });
        
        allDeptTickets = response.tickets || [];
        
        // Update badge
        document.getElementById('ticketsBadge').textContent = allDeptTickets.length;
        
        renderTickets(allDeptTickets);
        
    } catch (error) {
        console.error('Error loading department tickets:', error);
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-exclamation-triangle fa-3x text-danger mb-3"></i>
                <p class="text-danger">Error al cargar tickets</p>
                <button class="btn btn-primary" onclick="loadDepartmentTickets()">
                    <i class="fas fa-redo me-2"></i>Reintentar
                </button>
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
                <h5 class="text-muted">No hay tickets</h5>
                <p class="text-muted">Crea el primer ticket de tu departamento</p>
                <button class="btn btn-primary" onclick="createTicket()">
                    <i class="fas fa-plus me-2"></i>Crear Ticket
                </button>
            </div>
        `;
        return;
    }
    
    container.innerHTML = tickets.map(ticket => `
        <div class="border-bottom p-3 hover-bg-light" onclick="viewTicket(${ticket.id})">
            <div class="d-flex justify-content-between align-items-start">
                <div class="flex-grow-1">
                    <div class="d-flex align-items-center gap-2 mb-2">
                        <h6 class="mb-0 fw-bold">${ticket.ticket_number}</h6>
                        ${HelpdeskUtils.getStatusBadge(ticket.status)}
                        ${HelpdeskUtils.getPriorityBadge(ticket.priority)}
                        ${HelpdeskUtils.getAreaBadge(ticket.area)}
                    </div>
                    
                    <h5 class="mb-2">${ticket.title}</h5>
                    
                    <div class="text-muted small">
                        <i class="fas fa-user me-1"></i>${ticket.requester?.name || 'N/A'}
                        ${ticket.assigned_to ? `
                            <span class="ms-3 text-primary">
                                <i class="fas fa-user-check me-1"></i>${ticket.assigned_to.name}
                            </span>
                        ` : ''}
                        <span class="ms-3">
                            <i class="fas fa-clock me-1"></i>${HelpdeskUtils.formatTimeAgo(ticket.created_at)}
                        </span>
                    </div>
                </div>
                
                <button class="btn btn-sm btn-outline-primary" onclick="event.stopPropagation(); viewTicket(${ticket.id})">
                    <i class="fas fa-eye"></i>
                </button>
            </div>
        </div>
    `).join('');
}

// ==================== DEPARTMENT INVENTORY ====================
async function loadDepartmentInventory() {
    const container = document.getElementById('inventoryList');
    HelpdeskUtils.showLoading('inventoryList');
    
    try {
        // Load inventory for this department (read-only)
        const params = new URLSearchParams({
            department_id: DEPARTMENT_ID,
            per_page: 50
        });
        const response = await HelpdeskUtils.api.request(`/inventory/items?${params}`);
        console.log('Inventory response:', response);
        allInventoryItems = response.data || [];
        
        renderInventory(allInventoryItems);
        
    } catch (error) {
        console.error('Error loading inventory:', error);
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-exclamation-triangle fa-3x text-warning mb-3"></i>
                <p class="text-muted">No se pudo cargar el inventario</p>
            </div>
        `;
    }
}

function renderInventory(items) {
    const container = document.getElementById('inventoryList');
    
    if (items.length === 0) {
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-box-open fa-3x text-muted mb-3"></i>
                <p class="text-muted">No hay equipos registrados en este departamento</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = items.map(item => {
        const icon = item.category?.icon || 'fas fa-laptop';
        const statusColor = getEquipmentStatusColor(item.status);
        
        return `
            <div class="inventory-item-card border-bottom p-3 cursor-pointer hover-bg-light" 
                 onclick="viewInventoryItem(${item.id})" 
                 title="Click para ver detalles del equipo">
                <div class="d-flex align-items-start gap-3">
                    <div class="equipment-icon-dashboard">
                        <i class="${icon}"></i>
                    </div>
                    <div class="flex-grow-1">
                        <div class="d-flex justify-content-between align-items-start mb-2">
                            <div>
                                <div class="fw-bold text-primary mb-1">${item.inventory_number || 'N/A'}</div>
                                <h6 class="mb-2">${item.brand || 'N/A'} ${item.model || ''}</h6>
                            </div>
                            <span class="badge ${statusColor}">
                                ${item.status || 'UNKNOWN'}
                            </span>
                        </div>
                        
                        <div class="mb-2">
                            <span class="badge bg-info">
                                <i class="fas fa-tag me-1"></i>${item.category?.name || 'Sin categoría'}
                            </span>
                        </div>
                        
                        ${item.assigned_to ? `
                            <div class="mb-2">
                                <small class="text-muted d-block">Asignado a:</small>
                                <strong><i class="fas fa-user me-1"></i>${item.assigned_to.name}</strong>
                            </div>
                        ` : `
                            <div class="mb-2">
                                <span class="badge bg-secondary">
                                    <i class="fas fa-building me-1"></i>Disponible
                                </span>
                            </div>
                        `}
                        
                        ${item.location_detail ? `
                            <div>
                                <small class="text-muted">
                                    <i class="fas fa-map-marker-alt me-1"></i>${item.location_detail}
                                </small>
                            </div>
                        ` : ''}
                        
                        <div class="mt-2">
                            <small class="text-muted">
                                <i class="fas fa-hand-pointer me-1"></i>Click para ver más detalles
                            </small>
                        </div>
                    </div>
                    <div class="d-flex align-items-center">
                        <i class="fas fa-chevron-right text-muted"></i>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function getEquipmentStatusColor(status) {
    const statusColors = {
        'ACTIVE': 'bg-success',
        'ACTIVO': 'bg-success',
        'MAINTENANCE': 'bg-warning',
        'MANTENIMIENTO': 'bg-warning',
        'DAMAGED': 'bg-danger',
        'DAÑADO': 'bg-danger',
        'LOST': 'bg-dark',
        'EXTRAVIADO': 'bg-dark',
        'INACTIVE': 'bg-secondary',
        'INACTIVO': 'bg-secondary'
    };
    return statusColors[status] || 'bg-secondary';
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
    
    let filtered = [...allDeptTickets];
    
    if (status) {
        filtered = filtered.filter(t => t.status === status);
    }
    
    if (area) {
        filtered = filtered.filter(t => t.area === area);
    }
    
    if (search) {
        filtered = filtered.filter(t => {
            return t.title.toLowerCase().includes(search) ||
                   t.ticket_number.toLowerCase().includes(search) ||
                   t.requester?.name.toLowerCase().includes(search);
        });
    }
    
    renderTickets(filtered);
}

// ==================== SUMMARY STATS ====================
async function loadSummaryStats() {
    try {
        const monthStats = document.getElementById('monthStats');
        const categoryStats = document.getElementById('categoryStats');
        
        // Calculate month stats
        const now = new Date();
        const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
        
        const monthTickets = allDeptTickets.filter(t => 
            new Date(t.created_at) >= startOfMonth
        );
        
        monthStats.innerHTML = `
            <div class="d-flex justify-content-between mb-2">
                <span>Recibidos</span>
                <strong>${monthTickets.length}</strong>
            </div>
            <div class="d-flex justify-content-between mb-2">
                <span>Resueltos</span>
                <strong>${monthTickets.filter(t => t.status.startsWith('RESOLVED')).length}</strong>
            </div>
            <div class="d-flex justify-content-between">
                <span>Pendientes</span>
                <strong>${monthTickets.filter(t => t.status === 'PENDING').length}</strong>
            </div>
        `;
        
        // Calculate category stats
        const categoryCount = {};
        allDeptTickets.forEach(t => {
            const cat = t.category?.name || 'Sin categoría';
            categoryCount[cat] = (categoryCount[cat] || 0) + 1;
        });
        
        const sortedCategories = Object.entries(categoryCount)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 5);
        
        if (sortedCategories.length === 0) {
            categoryStats.innerHTML = '<p class="text-muted text-center">No hay datos</p>';
        } else {
            categoryStats.innerHTML = sortedCategories.map(([cat, count]) => `
                <div class="d-flex justify-content-between mb-2">
                    <span class="text-truncate" style="max-width: 70%;">${cat}</span>
                    <strong>${count}</strong>
                </div>
            `).join('');
        }
        
    } catch (error) {
        console.error('Error loading summary stats:', error);
    }
}

// ==================== ACTIONS ====================
function createTicket() {
    // Redirect to create ticket page
    window.location.href = '/help-desk/user/create';
}
window.createTicket = createTicket;

function viewTicket(ticketId) {
    // Redirect to ticket detail page
    window.location.href = `/help-desk/user/tickets/${ticketId}`;
}
window.viewTicket = viewTicket;

function viewInventoryItem(itemId) {
    // Redirect to inventory item detail page
    window.location.href = `/help-desk/inventory/items/${itemId}`;
}
window.viewInventoryItem = viewInventoryItem;