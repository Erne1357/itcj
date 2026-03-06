// itcj/apps/helpdesk/static/js/admin/tickets_list.js

let currentPage = 1;
const itemsPerPage = 20;
let currentFilters = {};
let totalTickets = 0;
let pendingScrollRestore = 0;
let summaryStats = {
    total: 0,
    pending: 0,
    inProgress: 0,
    resolved: 0
};

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', () => {
    // Restore state if coming back from a ticket detail
    if (document.referrer.includes('/help-desk/user/tickets/')) {
        const saved = HelpdeskUtils.NavState.load('admin_tickets_list');
        if (saved) {
            document.getElementById('searchInput').value = saved.search || '';
            document.getElementById('filterStatus').value = saved.status || '';
            document.getElementById('filterArea').value = saved.area || '';
            document.getElementById('filterPriority').value = saved.priority || '';
            currentFilters = saved.filters || {};
            currentPage = saved.page || 1;
            pendingScrollRestore = saved.scrollY || 0;
        }
    }
    loadSummaryStats();
    loadTickets();
    setupFilters();
    setupWebSocketListeners();
});

// ==================== LOAD SUMMARY STATS ====================
async function loadSummaryStats() {
    try {
        // Cargar estadísticas de resumen (solo conteos, sin paginación)
        const [totalResp, pendingResp, inProgressResp, resolvedResp] = await Promise.all([
            HelpdeskUtils.api.getTickets({ per_page: 1, page: 1 }),
            HelpdeskUtils.api.getTickets({ status: 'PENDING', per_page: 1, page: 1 }),
            HelpdeskUtils.api.getTickets({ status: 'ASSIGNED,IN_PROGRESS', per_page: 1, page: 1 }),
            HelpdeskUtils.api.getTickets({ status: 'RESOLVED_SUCCESS,RESOLVED_FAILED,CLOSED', per_page: 1, page: 1 })
        ]);

        summaryStats = {
            total: totalResp.total || 0,
            pending: pendingResp.total || 0,
            inProgress: inProgressResp.total || 0,
            resolved: resolvedResp.total || 0
        };

        updateSummaryCards();
    } catch (error) {
        console.error('Error loading summary stats:', error);
    }
}

// ==================== LOAD TICKETS (CON PAGINACIÓN BACKEND) ====================
async function loadTickets() {
    try {
        console.log('🎫 Cargando tickets (página', currentPage, ')...');

        // Construir parámetros de consulta
        const params = {
            page: currentPage,
            per_page: itemsPerPage,
            ...currentFilters
        };

        const response = await HelpdeskUtils.api.getTickets(params);
        const tickets = response.tickets || [];
        totalTickets = response.total || 0;

        renderTickets(tickets);

        if (pendingScrollRestore > 0) {
            const sy = pendingScrollRestore;
            pendingScrollRestore = 0;
            requestAnimationFrame(() => window.scrollTo({ top: sy, behavior: 'instant' }));
        }

        console.log('✅ Tickets cargados:', tickets.length, 'de', totalTickets);

    } catch (error) {
        console.error('Error loading tickets:', error);
        const errorMessage = error.message || 'Error desconocido';
        HelpdeskUtils.showToast(`Error al cargar tickets: ${errorMessage}`, 'error');
        showErrorState();
    }
}

// ==================== SUMMARY CARDS ====================
function updateSummaryCards() {
    document.getElementById('totalTickets').textContent = summaryStats.total;
    document.getElementById('pendingTickets').textContent = summaryStats.pending;
    document.getElementById('inProgressTickets').textContent = summaryStats.inProgress;
    document.getElementById('resolvedTickets').textContent = summaryStats.resolved;
}

// ==================== FILTERS ====================
function setupFilters() {
    const filterStatus = document.getElementById('filterStatus');
    const filterArea = document.getElementById('filterArea');
    const filterPriority = document.getElementById('filterPriority');
    const searchInput = document.getElementById('searchInput');
    const btnClearFilters = document.getElementById('btnClearFilters');

    filterStatus.addEventListener('change', applyFilters);
    filterArea.addEventListener('change', applyFilters);
    filterPriority.addEventListener('change', applyFilters);
    
    // Debounce para búsqueda
    let searchTimeout;
    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(applyFilters, 500);
    });

    btnClearFilters.addEventListener('click', () => {
        filterStatus.value = '';
        filterArea.value = '';
        filterPriority.value = '';
        searchInput.value = '';
        HelpdeskUtils.NavState.clear('admin_tickets_list');
        applyFilters();
    });
}

function applyFilters() {
    const statusFilter = document.getElementById('filterStatus').value;
    const areaFilter = document.getElementById('filterArea').value;
    const priorityFilter = document.getElementById('filterPriority').value;
    const searchText = document.getElementById('searchInput').value.trim();

    // Construir objeto de filtros
    currentFilters = {};
    
    if (statusFilter) currentFilters.status = statusFilter;
    if (areaFilter) currentFilters.area = areaFilter;
    if (priorityFilter) currentFilters.priority = priorityFilter;
    if (searchText) currentFilters.search = searchText;

    // Resetear a página 1 cuando cambian los filtros
    currentPage = 1;
    
    // Recargar tickets con nuevos filtros
    loadTickets();
    
    // Recargar estadísticas de resumen con filtros
    loadSummaryStats();
}

// ==================== RENDER TICKETS ====================
function renderTickets(tickets) {
    const container = document.getElementById('ticketsList');
    const countBadge = document.getElementById('ticketCount');

    // Update count
    countBadge.textContent = `${totalTickets} ticket${totalTickets !== 1 ? 's' : ''}`;

    // Empty state
    if (tickets.length === 0) {
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-inbox fa-3x text-muted mb-3"></i>
                <h5 class="text-muted">No hay tickets</h5>
                <p class="text-muted">
                    ${totalTickets === 0
                        ? 'Aún no hay tickets en el sistema.'
                        : 'No hay tickets que coincidan con los filtros aplicados.'}
                </p>
            </div>
        `;
        document.getElementById('paginationNav').style.display = 'none';
        return;
    }

    // Render tickets
    container.innerHTML = tickets.map(ticket => createTicketCard(ticket)).join('');

    // Render pagination
    const totalPages = Math.ceil(totalTickets / itemsPerPage);
    renderPagination(totalPages);
}

function createTicketCard(ticket) {
    return `
        <div class="ticket-card status-${ticket.status} border-bottom p-3" onclick="goToTicketDetail(${ticket.id})">
            <div class="row g-3">
                <!-- Columna Principal: Información del Ticket -->
                <div class="col-md-6">
                    <div class="d-flex align-items-center gap-2 mb-2">
                        <h6 class="mb-0 fw-bold text-primary">${ticket.ticket_number}</h6>
                        ${HelpdeskUtils.getAreaBadge(ticket.area)}
                        ${ticket.category ? `<span class="badge bg-secondary">${ticket.category.name}</span>` : ''}
                        <span class="badge badge-priority-${ticket.priority}">${ticket.priority}</span>
                    </div>

                    <h6 class="mb-2">${ticket.title}</h6>

                    <div class="text-muted small mb-2">
                        ${truncateText(ticket.description, 100)}
                    </div>

                    <div class="text-muted small">
                        <i class="fas fa-calendar-alt me-1"></i>
                        ${HelpdeskUtils.formatDate(ticket.created_at)}
                        <span class="ms-2 text-muted">(${HelpdeskUtils.formatTimeAgo(ticket.created_at)})</span>
                    </div>
                </div>

                <!-- Columna de Personas: Creador y Solicitante -->
                <div class="col-md-3">
                    <div class="mb-2">
                        <div class="ticket-info-label">
                            <i class="fas fa-user-edit me-1"></i>Creado por
                        </div>
                        <div class="ticket-info-value">
                            ${ticket.created_by ? ticket.created_by.name : 'N/A'}
                        </div>
                    </div>

                    <div>
                        <div class="ticket-info-label">
                            <i class="fas fa-user-circle me-1"></i>Solicitante
                        </div>
                        <div class="ticket-info-value">
                            ${ticket.requester ? ticket.requester.name : 'N/A'}
                        </div>
                    </div>
                </div>

                <!-- Columna de Estado y Asignación -->
                <div class="col-md-3">
                    <div class="mb-2">
                        <div class="ticket-info-label">
                            <i class="fas fa-info-circle me-1"></i>Estado
                        </div>
                        <div>
                            ${HelpdeskUtils.getStatusBadge(ticket.status)}
                        </div>
                    </div>

                    ${ticket.assigned_to || ticket.assigned_to_team ? `
                        <div>
                            <div class="ticket-info-label">
                                <i class="fas fa-user-check me-1"></i>Asignado a
                            </div>
                            <div class="ticket-info-value">
                                ${ticket.assigned_to
                                    ? ticket.assigned_to.name
                                    : `<span class="badge bg-info">Equipo: ${ticket.assigned_to_team}</span>`}
                            </div>
                        </div>
                    ` : `
                        <div>
                            <div class="ticket-info-label">
                                <i class="fas fa-user-times me-1"></i>Asignado a
                            </div>
                            <div class="ticket-info-value text-muted">
                                Sin asignar
                            </div>
                        </div>
                    `}
                </div>
            </div>
        </div>
    `;
}

// ==================== PAGINATION ====================
function renderPagination(totalPages) {
    const paginationNav = document.getElementById('paginationNav');
    const paginationList = document.getElementById('paginationList');

    if (totalPages <= 1) {
        paginationNav.style.display = 'none';
        return;
    }

    paginationNav.style.display = 'block';

    let paginationHTML = '';

    // Previous button
    paginationHTML += `
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="changePage(${currentPage - 1}); return false;">
                <i class="fas fa-chevron-left"></i>
            </a>
        </li>
    `;

    // Page numbers
    const maxVisiblePages = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisiblePages / 2));
    let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);

    if (endPage - startPage < maxVisiblePages - 1) {
        startPage = Math.max(1, endPage - maxVisiblePages + 1);
    }

    // First page
    if (startPage > 1) {
        paginationHTML += `
            <li class="page-item">
                <a class="page-link" href="#" onclick="changePage(1); return false;">1</a>
            </li>
        `;
        if (startPage > 2) {
            paginationHTML += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        }
    }

    // Page numbers
    for (let i = startPage; i <= endPage; i++) {
        paginationHTML += `
            <li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#" onclick="changePage(${i}); return false;">${i}</a>
            </li>
        `;
    }

    // Last page
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) {
            paginationHTML += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        }
        paginationHTML += `
            <li class="page-item">
                <a class="page-link" href="#" onclick="changePage(${totalPages}); return false;">${totalPages}</a>
            </li>
        `;
    }

    // Next button
    paginationHTML += `
        <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="changePage(${currentPage + 1}); return false;">
                <i class="fas fa-chevron-right"></i>
            </a>
        </li>
    `;

    paginationList.innerHTML = paginationHTML;
}

function changePage(page) {
    currentPage = page;
    loadTickets(); // Cargar desde backend
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ==================== TICKET DETAIL ====================
function goToTicketDetail(ticketId) {
    HelpdeskUtils.NavState.save('admin_tickets_list', {
        search: document.getElementById('searchInput').value,
        status: document.getElementById('filterStatus').value,
        area: document.getElementById('filterArea').value,
        priority: document.getElementById('filterPriority').value,
        filters: currentFilters,
        page: currentPage,
        scrollY: window.scrollY,
    });
    window.location.href = `/help-desk/user/tickets/${ticketId}?from=admin_tickets_list`;
}

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
            bindAdminSocketEvents();
        }
    }, 100);

    setTimeout(() => clearInterval(checkSocket), 5000);
}

function bindAdminSocketEvents() {
    const socket = window.__helpdeskSocket;
    if (!socket) return;

    // Unirse al room de admin (recibe todos los eventos de tickets)
    window.__hdJoinAdmin?.();

    const silentRefresh = debounce(() => {
        loadSummaryStats();
        loadTickets();
    }, 500);

    // Remover listeners previos
    socket.off('ticket_created');
    socket.off('ticket_assigned');
    socket.off('ticket_reassigned');
    socket.off('ticket_status_changed');
    socket.off('ticket_self_assigned');

    // Nuevo ticket creado
    socket.on('ticket_created', (data) => {
        console.log('[Admin List] ticket_created:', data);
        const ticketNum = data?.ticket_number ? `#${data.ticket_number}` : '';
        const area = data?.area || '';
        HelpdeskUtils.showToast(`Nuevo ticket ${ticketNum} (${area})`, 'info');
        silentRefresh();
    });

    // Ticket asignado
    socket.on('ticket_assigned', (data) => {
        console.log('[Admin List] ticket_assigned:', data);
        const ticketNum = data?.ticket_number ? `#${data.ticket_number}` : '';
        HelpdeskUtils.showToast(`Ticket ${ticketNum} asignado`, 'info');
        silentRefresh();
    });

    // Ticket reasignado
    socket.on('ticket_reassigned', (data) => {
        console.log('[Admin List] ticket_reassigned:', data);
        const ticketNum = data?.ticket_number ? `#${data.ticket_number}` : '';
        HelpdeskUtils.showToast(`Ticket ${ticketNum} reasignado`, 'info');
        silentRefresh();
    });

    // Cambio de estado
    socket.on('ticket_status_changed', (data) => {
        console.log('[Admin List] ticket_status_changed:', data);
        const ticketNum = data?.ticket_number ? `#${data.ticket_number}` : '';
        const newStatus = data?.new_status || '';
        HelpdeskUtils.showToast(`Ticket ${ticketNum} → ${newStatus}`, 'info');
        silentRefresh();
    });

    // Técnico tomó un ticket del pool
    socket.on('ticket_self_assigned', (data) => {
        console.log('[Admin List] ticket_self_assigned:', data);
        const ticketNum = data?.ticket_number ? `#${data.ticket_number}` : '';
        HelpdeskUtils.showToast(`Ticket ${ticketNum} auto-asignado`, 'info');
        silentRefresh();
    });

    console.log('[Admin List] WebSocket listeners configurados');
}

// ==================== UTILITY FUNCTIONS ====================
function truncateText(text, maxLength) {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
}

function showErrorState() {
    const container = document.getElementById('ticketsList');
    container.innerHTML = `
        <div class="text-center py-5">
            <i class="fas fa-exclamation-triangle fa-3x text-danger mb-3"></i>
            <h5 class="text-danger">Error al cargar tickets</h5>
            <p class="text-muted">Por favor, intenta recargar la página.</p>
            <button class="btn btn-primary mt-3" onclick="location.reload()">
                <i class="fas fa-sync-alt me-2"></i>Recargar
            </button>
        </div>
    `;
}
