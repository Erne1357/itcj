// itcj/apps/helpdesk/static/js/admin/tickets_list.js

let allTickets = [];
let filteredTickets = [];
let currentPage = 1;
const itemsPerPage = 15;

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', () => {
    loadAllTickets();
    setupFilters();
});

// ==================== LOAD TICKETS ====================
async function loadAllTickets() {
    try {
        console.log('🎫 Cargando todos los tickets del sistema...');

        // Cargar todos los tickets usando la API de admin
        const response = await HelpdeskUtils.api.getTickets({ all: true });
        allTickets = response.tickets || [];

        // Ordenar por fecha de creación descendente (más nuevos primero)
        allTickets.sort((a, b) => {
            const dateA = new Date(a.created_at);
            const dateB = new Date(b.created_at);
            return dateB - dateA; // Descendente
        });

        filteredTickets = [...allTickets];

        updateSummaryCards();
        renderTickets();

        console.log('✅ Tickets cargados:', allTickets.length);

    } catch (error) {
        console.error('Error loading tickets:', error);
        const errorMessage = error.message || 'Error desconocido';
        HelpdeskUtils.showToast(`Error al cargar tickets: ${errorMessage}`, 'error');
        showErrorState();
    }
}

// ==================== SUMMARY CARDS ====================
function updateSummaryCards() {
    const total = allTickets.length;
    const pending = allTickets.filter(t => t.status === 'PENDING').length;
    const inProgress = allTickets.filter(t =>
        ['ASSIGNED', 'IN_PROGRESS'].includes(t.status)
    ).length;
    const resolved = allTickets.filter(t =>
        ['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED'].includes(t.status)
    ).length;

    document.getElementById('totalTickets').textContent = total;
    document.getElementById('pendingTickets').textContent = pending;
    document.getElementById('inProgressTickets').textContent = inProgress;
    document.getElementById('resolvedTickets').textContent = resolved;
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
    searchInput.addEventListener('input', applyFilters);

    btnClearFilters.addEventListener('click', () => {
        filterStatus.value = '';
        filterArea.value = '';
        filterPriority.value = '';
        searchInput.value = '';
        applyFilters();
    });
}

function applyFilters() {
    const statusFilter = document.getElementById('filterStatus').value;
    const areaFilter = document.getElementById('filterArea').value;
    const priorityFilter = document.getElementById('filterPriority').value;
    const searchText = document.getElementById('searchInput').value.toLowerCase();

    filteredTickets = allTickets.filter(ticket => {
        // Filtro por estado
        if (statusFilter && ticket.status !== statusFilter) return false;

        // Filtro por área
        if (areaFilter && ticket.area !== areaFilter) return false;

        // Filtro por prioridad
        if (priorityFilter && ticket.priority !== priorityFilter) return false;

        // Filtro por búsqueda de texto
        if (searchText) {
            const titleMatch = ticket.title.toLowerCase().includes(searchText);
            const numberMatch = ticket.ticket_number.toLowerCase().includes(searchText);
            const descMatch = ticket.description.toLowerCase().includes(searchText);

            if (!titleMatch && !numberMatch && !descMatch) return false;
        }

        return true;
    });

    currentPage = 1;
    renderTickets();
}

// ==================== RENDER TICKETS ====================
function renderTickets() {
    const container = document.getElementById('ticketsList');
    const countBadge = document.getElementById('ticketCount');

    // Update count
    countBadge.textContent = `${filteredTickets.length} ticket${filteredTickets.length !== 1 ? 's' : ''}`;

    // Empty state
    if (filteredTickets.length === 0) {
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-inbox fa-3x text-muted mb-3"></i>
                <h5 class="text-muted">No hay tickets</h5>
                <p class="text-muted">
                    ${allTickets.length === 0
                        ? 'Aún no hay tickets en el sistema.'
                        : 'No hay tickets que coincidan con los filtros aplicados.'}
                </p>
            </div>
        `;
        document.getElementById('paginationNav').style.display = 'none';
        return;
    }

    // Pagination
    const totalPages = Math.ceil(filteredTickets.length / itemsPerPage);
    const startIndex = (currentPage - 1) * itemsPerPage;
    const endIndex = startIndex + itemsPerPage;
    const ticketsToShow = filteredTickets.slice(startIndex, endIndex);

    // Render tickets
    container.innerHTML = ticketsToShow.map(ticket => createTicketCard(ticket)).join('');

    // Render pagination
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
                        <span class="badge badge-priority-${ticket.priority}">${ticket.priority}</span>
                    </div>

                    <h6 class="mb-2">${ticket.title}</h6>

                    <div class="text-muted small mb-2">
                        ${truncateText(ticket.description, 100)}
                    </div>

                    ${ticket.category ? `
                        <div class="mb-2">
                            <span class="badge bg-light text-dark">
                                <i class="fas fa-tag me-1"></i>${ticket.category.name}
                            </span>
                        </div>
                    ` : ''}

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
    renderTickets();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ==================== TICKET DETAIL ====================
function goToTicketDetail(ticketId) {
    // Redirigir a la página de detalle del ticket con el parámetro from
    window.location.href = `/help-desk/user/tickets/${ticketId}?from=admin_tickets_list`;
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
