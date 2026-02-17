// itcj/apps/helpdesk/static/js/user/my_tickets.js

let currentPage = 1;
const itemsPerPage = 10;
let currentFilters = {};
let totalTickets = 0;
let summaryStats = {
    total: 0,
    active: 0,
    resolved: 0,
    pendingRating: 0
};

let currentRatingAttention = 0;
let currentRatingSpeed = 0;
let currentRatingEfficiency = null;
let ticketToRate = null;
let ticketToCancel = null;

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', () => {
    // Guardar la página actual para navegación inteligente
    sessionStorage.setItem('helpdesk_last_page', JSON.stringify({
        url: window.location.href,
        text: 'Mis Tickets'
    }));

    // Dar tiempo para que el tutorial se inicialice primero
    // Si está en modo tutorial, esperar un poco más
    const isTutorialMode = typeof window.isTutorialModeActive === 'function' && window.isTutorialModeActive();
    const delay = isTutorialMode ? 100 : 0;

    setTimeout(() => {
        loadSummaryStats();
        loadMyTickets();
        setupFilters();
        setupRatingModal();
        setupCancelModal();
    }, delay);
});

// ==================== LOAD SUMMARY STATS ====================
async function loadSummaryStats() {
    try {
        // Verificar si está en modo tutorial
        const isTutorialMode = typeof window.isTutorialModeActive === 'function' && window.isTutorialModeActive();

        if (isTutorialMode) {
            const tutorialData = window.getTutorialTicketData();
            if (tutorialData && tutorialData.ticket) {
                summaryStats = {
                    total: 1,
                    active: 1,
                    resolved: 0,
                    pendingRating: 0
                };
                updateSummaryCards();
                return;
            }
        }

        // Cargar estadísticas de resumen (solo conteos)
        const [totalResp, activeResp, resolvedResp, ratingResp] = await Promise.all([
            HelpdeskUtils.api.getTickets({ created_by_me: true, per_page: 1, page: 1 }),
            HelpdeskUtils.api.getTickets({ created_by_me: true, status: 'PENDING,ASSIGNED,IN_PROGRESS', per_page: 1, page: 1 }),
            HelpdeskUtils.api.getTickets({ created_by_me: true, status: 'RESOLVED_SUCCESS,RESOLVED_FAILED,CLOSED', per_page: 1, page: 1 }),
            HelpdeskUtils.api.getTickets({ created_by_me: true, status: 'RESOLVED_SUCCESS,RESOLVED_FAILED', per_page: 1, page: 1 })
        ]);

        summaryStats = {
            total: totalResp.total || 0,
            active: activeResp.total || 0,
            resolved: resolvedResp.total || 0,
            pendingRating: ratingResp.total || 0
        };

        updateSummaryCards();
    } catch (error) {
        console.error('Error loading summary stats:', error);
    }
}

// ==================== LOAD TICKETS (CON PAGINACIÓN BACKEND) ====================
async function loadMyTickets() {
    try {
        console.log('🎫 Cargando tickets (página', currentPage, ')...');

        // Verificar si está en modo tutorial
        const isTutorialMode = typeof window.isTutorialModeActive === 'function' && window.isTutorialModeActive();
        console.log('🎫 Modo tutorial activo:', isTutorialMode);

        if (isTutorialMode) {
            // Modo tutorial: cargar solo el ticket de ejemplo
            const tutorialData = window.getTutorialTicketData();
            console.log('🎫 Datos del tutorial:', tutorialData);

            if (tutorialData && tutorialData.ticket) {
                console.log('🎫 Cargando ticket de ejemplo del tutorial');
                const tickets = [tutorialData.ticket];
                totalTickets = 1;
                renderTickets(tickets);
                return;
            } else {
                console.warn('⚠️ Modo tutorial activo pero sin datos de ticket');
            }
        }

        // Modo normal: cargar tickets de la BD con paginación
        console.log('🎫 Cargando tickets desde la BD');
        
        // Construir parámetros de consulta
        const params = {
            created_by_me: true,
            page: currentPage,
            per_page: itemsPerPage,
            ...currentFilters
        };

        const response = await HelpdeskUtils.api.getTickets(params);
        const tickets = response.tickets || [];
        totalTickets = response.total || 0;

        renderTickets(tickets);

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
    document.getElementById('activeTickets').textContent = summaryStats.active;
    document.getElementById('resolvedTickets').textContent = summaryStats.resolved;
    document.getElementById('pendingRating').textContent = summaryStats.pendingRating;
}

// ==================== FILTERS ====================
function setupFilters() {
    const filterStatus = document.getElementById('filterStatus');
    const filterArea = document.getElementById('filterArea');
    const searchInput = document.getElementById('searchInput');

    filterStatus.addEventListener('change', applyFilters);
    filterArea.addEventListener('change', applyFilters);
    
    // Debounce para búsqueda
    let searchTimeout;
    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(applyFilters, 500);
    });
}

function applyFilters() {
    const statusFilter = document.getElementById('filterStatus').value;
    const areaFilter = document.getElementById('filterArea').value;
    const searchText = document.getElementById('searchInput').value.trim();

    // Construir objeto de filtros
    currentFilters = {};
    
    if (statusFilter) currentFilters.status = statusFilter;
    if (areaFilter) currentFilters.area = areaFilter;
    if (searchText) currentFilters.search = searchText;

    // Resetear a página 1 cuando cambian los filtros
    currentPage = 1;
    
    // Recargar tickets con nuevos filtros
    loadMyTickets();
    
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
            <div class="empty-state">
                <i class="fas fa-inbox text-muted"></i>
                <h5 class="text-muted">No hay tickets</h5>
                <p class="text-muted">
                    ${totalTickets === 0 
                        ? 'Aún no has creado ningún ticket.' 
                        : 'No hay tickets que coincidan con los filtros.'}
                </p>
                ${totalTickets === 0 ? `
                    <a href="/help-desk/user/create" class="btn btn-primary mt-3">
                        <i class="fas fa-plus me-2"></i>Crear mi primer ticket
                    </a>
                ` : ''}
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
    const canRate = ['RESOLVED_SUCCESS', 'RESOLVED_FAILED'].includes(ticket.status) && !ticket.rating_attention;
    const canCancel = ['PENDING', 'ASSIGNED'].includes(ticket.status);
    const hasRating = ticket.rating_attention !== null;
    
    return `
        <div class="ticket-card border-bottom p-3" onclick="goToTicketDetail(${ticket.id})">
            <div class="row align-items-start">
                <!-- Main Info -->
                <div class="col-md-8">
                    <div class="d-flex align-items-center gap-2 mb-2">
                        <h6 class="mb-0 fw-bold">${ticket.ticket_number}</h6>
                        ${HelpdeskUtils.getAreaBadge(ticket.area)}
                        ${ticket.category ? `<span class="badge bg-secondary">${ticket.category.name}</span>` : ''}
                        ${HelpdeskUtils.getPriorityBadge(ticket.priority)}
                    </div>
                    
                    <h5 class="mb-2">${ticket.title}</h5>
                    
                    <p class="text-muted mb-2 small" style="max-width: 600px;">
                        ${truncateText(ticket.description, 150)}
                    </p>
                    
                    ${ticket.location ? `
                        <div class="text-muted small mb-2">
                            <i class="fas fa-map-marker-alt me-1"></i>${ticket.location}
                        </div>
                    ` : ''}
                    
                    <div class="text-muted small">
                        <i class="fas fa-clock me-1"></i>
                        Creado ${HelpdeskUtils.formatTimeAgo(ticket.created_at)}
                        
                        ${ticket.assigned_to ? `
                            <span class="ms-3">
                                <i class="fas fa-user-check me-1"></i>
                                Asignado a: ${ticket.assigned_to.name}
                            </span>
                        ` : ticket.assigned_to_team ? `
                            <span class="ms-3">
                                <i class="fas fa-users me-1"></i>
                                Equipo: ${ticket.assigned_to_team}
                            </span>
                        ` : ''}
                        
                        ${ticket.resolved_at ? `
                            <span class="ms-3">
                                <i class="fas fa-check me-1"></i>
                                Resuelto ${HelpdeskUtils.formatTimeAgo(ticket.resolved_at)}
                            </span>
                        ` : ''}
                    </div>
                    
                    ${ticket.resolution_notes ? `
                        <div class="alert alert-success mt-2 mb-0 py-2 small">
                            <i class="fas fa-check-circle me-1"></i>
                            <strong>Solución:</strong> ${truncateText(ticket.resolution_notes, 200)}
                        </div>
                    ` : ''}
                    
                    ${hasRating ? `
                        <div class="mt-2 p-2 bg-light rounded small">
                            <strong>Tu evaluación:</strong>
                            <div class="mt-1">
                                <span class="me-3"><i class="fas fa-user-tie me-1"></i>Atención: ${HelpdeskUtils.renderStarRating(ticket.rating_attention)}</span>
                                <span class="me-3"><i class="fas fa-tachometer-alt me-1"></i>Rapidez: ${HelpdeskUtils.renderStarRating(ticket.rating_speed)}</span>
                                <span><i class="fas fa-check-circle me-1"></i>Eficiencia: ${ticket.rating_efficiency ? 'Sí' : 'No'}</span>
                            </div>
                            ${ticket.rating_comment ? `
                                <div class="mt-1 text-muted">
                                    <i class="fas fa-comment me-1"></i>"${ticket.rating_comment}"
                                </div>
                            ` : ''}
                        </div>
                    ` : ''}
                </div>
                
                <!-- Status & Actions -->
                <div class="col-md-4 text-md-end">
                    <div class="mb-3">
                        ${HelpdeskUtils.getStatusBadge(ticket.status)}
                    </div>
                    
                    <div class="d-flex flex-column gap-2" onclick="event.stopPropagation()">
                        ${canRate ? `
                            <button class="btn btn-warning btn-sm" onclick="openRatingModal(${ticket.id})">
                                <i class="fas fa-star me-1"></i>Calificar
                            </button>
                        ` : ''}
                        
                        ${canCancel ? `
                            <button class="btn btn-outline-danger btn-sm" onclick="openCancelModal(${ticket.id})">
                                <i class="fas fa-ban me-1"></i>Cancelar
                            </button>
                        ` : ''}
                        
                        <button class="btn btn-primary btn-sm w-100" onclick="goToTicketDetail(${ticket.id})">
                            <i class="fas fa-eye me-1"></i>Ver Detalle
                        </button>
                    </div>
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
    
    let html = '';
    
    // Previous
    html += `
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="changePage(${currentPage - 1}); return false;">
                <i class="fas fa-chevron-left"></i>
            </a>
        </li>
    `;
    
    // Pages
    for (let i = 1; i <= totalPages; i++) {
        if (i === 1 || i === totalPages || (i >= currentPage - 1 && i <= currentPage + 1)) {
            html += `
                <li class="page-item ${i === currentPage ? 'active' : ''}">
                    <a class="page-link" href="#" onclick="changePage(${i}); return false;">${i}</a>
                </li>
            `;
        } else if (i === currentPage - 2 || i === currentPage + 2) {
            html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        }
    }
    
    // Next
    html += `
        <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="changePage(${currentPage + 1}); return false;">
                <i class="fas fa-chevron-right"></i>
            </a>
        </li>
    `;
    
    paginationList.innerHTML = html;
}

function changePage(page) {
    currentPage = page;
    loadMyTickets(); // Cargar desde backend
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ==================== RATING MODAL ====================
function setupRatingModal() {
    // Configurar estrellas de atención
    document.querySelectorAll('.star-btn-attention').forEach(btn => {
        btn.addEventListener('click', () => {
            currentRatingAttention = parseInt(btn.dataset.rating);
            updateStarButtons();
            checkRatingFormValidity();
        });
    });

    // Configurar estrellas de rapidez
    document.querySelectorAll('.star-btn-speed').forEach(btn => {
        btn.addEventListener('click', () => {
            currentRatingSpeed = parseInt(btn.dataset.rating);
            updateStarButtons();
            checkRatingFormValidity();
        });
    });

    // Configurar radio buttons de eficiencia
    document.querySelectorAll('input[name="ratingEfficiency"]').forEach(radio => {
        radio.addEventListener('change', () => {
            currentRatingEfficiency = radio.value === 'true';
            checkRatingFormValidity();
        });
    });
    
    // Submit button
    document.getElementById('btnSubmitRating').addEventListener('click', submitRating);
}

function openRatingModal(ticketId) {
    ticketToRate = allTickets.find(t => t.id === ticketId);
    if (!ticketToRate) {
        HelpdeskUtils.showToast('Ticket no encontrado', 'danger');
        return;
    }
    
    // Reset ratings
    currentRatingAttention = 0;
    currentRatingSpeed = 0;
    currentRatingEfficiency = null;
    
    // Update summary
    document.getElementById('ratingTicketSummary').innerHTML = `
        <div class="d-flex justify-content-between align-items-start">
            <div>
                <strong>${ticketToRate.ticket_number}</strong>
                <p class="mb-0 text-muted small">${ticketToRate.title}</p>
            </div>
            ${HelpdeskUtils.getStatusBadge(ticketToRate.status)}
        </div>
    `;
    
    // Reset form
    updateStarButtons();
    document.getElementById('ratingComment').value = '';
    
    // Reset radio buttons
    document.querySelectorAll('input[name="ratingEfficiency"]').forEach(radio => {
        radio.checked = false;
    });
    
    document.getElementById('btnSubmitRating').disabled = true;
    
    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('ratingModal'));
    modal.show();
}

function updateStarButtons() {
    // Actualizar estrellas de atención
    document.querySelectorAll('.star-btn-attention').forEach(btn => {
        const rating = parseInt(btn.dataset.rating);
        if (rating <= currentRatingAttention) {
            btn.classList.add('active');
            btn.querySelector('i').classList.replace('far', 'fas');
        } else {
            btn.classList.remove('active');
            btn.querySelector('i').classList.replace('fas', 'far');
        }
    });

    // Actualizar estrellas de rapidez
    document.querySelectorAll('.star-btn-speed').forEach(btn => {
        const rating = parseInt(btn.dataset.rating);
        if (rating <= currentRatingSpeed) {
            btn.classList.add('active');
            btn.querySelector('i').classList.replace('far', 'fas');
        } else {
            btn.classList.remove('active');
            btn.querySelector('i').classList.replace('fas', 'far');
        }
    });
}

function checkRatingFormValidity() {
    const isValid = currentRatingAttention > 0 && currentRatingSpeed > 0 && currentRatingEfficiency !== null;
    document.getElementById('btnSubmitRating').disabled = !isValid;
}

async function submitRating() {
    if (currentRatingAttention === 0 || currentRatingSpeed === 0 || currentRatingEfficiency === null) {
        HelpdeskUtils.showToast('Por favor completa todos los campos obligatorios', 'warning');
        return;
    }
    
    const submitBtn = document.getElementById('btnSubmitRating');
    const originalText = submitBtn.innerHTML;
    
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Enviando...';
    
    try {
        const response = await HelpdeskUtils.api.rateTicket(ticketToRate.id, {
            rating_attention: currentRatingAttention,
            rating_speed: currentRatingSpeed,
            rating_efficiency: currentRatingEfficiency,
            comment: document.getElementById('ratingComment').value.trim() || null
        });
        
        HelpdeskUtils.showToast('¡Gracias por tu evaluación!', 'success');
        
        // Close modal
        const modal = bootstrap.Modal.getInstance(document.getElementById('ratingModal'));
        modal.hide();
        
        // Reload tickets
        await loadMyTickets();
        
    } catch (error) {
        console.error('Error submitting rating:', error);
        HelpdeskUtils.showToast(error.message || 'Error al enviar calificación', 'error');
        
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
    }
}

// ==================== CANCEL MODAL ====================
function setupCancelModal() {
    document.getElementById('btnConfirmCancel').addEventListener('click', confirmCancel);
}

function openCancelModal(ticketId) {
    ticketToCancel = allTickets.find(t => t.id === ticketId);
    if (!ticketToCancel) return;
    
    document.getElementById('cancelTicketInfo').textContent = 
        `Ticket ${ticketToCancel.ticket_number}: ${ticketToCancel.title}`;
    
    document.getElementById('cancelReason').value = '';
    
    const modal = new bootstrap.Modal(document.getElementById('cancelModal'));
    modal.show();
}

async function confirmCancel() {
    if (!ticketToCancel) return;
    
    const confirmBtn = document.getElementById('btnConfirmCancel');
    const originalText = confirmBtn.innerHTML;
    
    confirmBtn.disabled = true;
    confirmBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Cancelando...';
    
    try {
        const reason = document.getElementById('cancelReason').value.trim();
        
        await HelpdeskUtils.api.cancelTicket(ticketToCancel.id, reason || null);
        
        HelpdeskUtils.showToast('Ticket cancelado exitosamente', 'success');
        
        // Close modal
        const modal = bootstrap.Modal.getInstance(document.getElementById('cancelModal'));
        modal.hide();
        
        // Reload tickets
        await loadMyTickets();
        
    } catch (error) {
        console.error('Error canceling ticket:', error);
        HelpdeskUtils.showToast(error.message || 'Error al cancelar ticket', 'error');
        
        confirmBtn.disabled = false;
        confirmBtn.innerHTML = originalText;
    }
}

// ==================== HELPERS ====================
function truncateText(text, maxLength) {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
}

function showErrorState() {
    document.getElementById('ticketsList').innerHTML = `
        <div class="empty-state">
            <i class="fas fa-exclamation-triangle text-danger"></i>
            <h5 class="text-danger">Error al cargar tickets</h5>
            <p class="text-muted">Ocurrió un error al cargar tus tickets. Por favor intenta de nuevo.</p>
            <button class="btn btn-primary mt-3" onclick="loadMyTickets()">
                <i class="fas fa-redo me-2"></i>Reintentar
            </button>
        </div>
    `;
}

// ==================== NAVIGATION ====================
function goToTicketDetail(ticketId) {
    HelpdeskUtils.goToTicketDetail(ticketId, 'my_tickets');
}

// ==================== WEBSOCKET REAL-TIME UPDATES ====================

let userSocketBound = false;

/**
 * Configura los listeners de WebSocket para actualizaciones en tiempo real
 */
function setupWebSocketListeners() {
    const checkSocket = setInterval(() => {
        if (window.__helpdeskSocket) {
            clearInterval(checkSocket);
            bindUserSocketEvents();
        }
    }, 100);

    setTimeout(() => clearInterval(checkSocket), 5000);
}

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

function bindUserSocketEvents() {
    if (userSocketBound) return;

    const socket = window.__helpdeskSocket;
    if (!socket) return;

    const debouncedRefresh = debounce(() => {
        loadMyTickets();
    }, 500);

    // Remover listeners previos
    socket.off('ticket_status_changed');
    socket.off('ticket_assigned');
    socket.off('ticket_comment_added');

    // Cambio de estado de mis tickets
    socket.on('ticket_status_changed', (data) => {
        // Verificar si es uno de mis tickets
        const myTicket = allTickets.find(t => t.id == data.ticket_id);
        if (myTicket) {
            console.log('[My Tickets] ticket_status_changed:', data);
            HelpdeskUtils.showToast(`Ticket ${data.ticket_number}: estado actualizado`, 'info');
            debouncedRefresh();
        }
    });

    // Ticket asignado
    socket.on('ticket_assigned', (data) => {
        const myTicket = allTickets.find(t => t.id == data.ticket_id);
        if (myTicket) {
            console.log('[My Tickets] ticket_assigned:', data);
            HelpdeskUtils.showToast(`Tu ticket fue asignado a ${data.assigned_to_name}`, 'info');
            debouncedRefresh();
        }
    });

    // Nuevo comentario en mis tickets
    socket.on('ticket_comment_added', (data) => {
        const myTicket = allTickets.find(t => t.id == data.ticket_id);
        if (myTicket) {
            console.log('[My Tickets] ticket_comment_added:', data);
            HelpdeskUtils.showToast(`Nuevo comentario en ${myTicket.ticket_number}`, 'info');
        }
    });

    userSocketBound = true;
    console.log('[My Tickets] WebSocket listeners configurados');
}

// Inicializar WebSocket al cargar
document.addEventListener('DOMContentLoaded', () => {
    // Dar tiempo para que se cargue el socket
    setTimeout(setupWebSocketListeners, 500);
});

// Global functions
window.openRatingModal = openRatingModal;
window.openCancelModal = openCancelModal;
window.goToTicketDetail = goToTicketDetail;
window.changePage = changePage;
window.loadMyTickets = loadMyTickets; // Exportar para que el tutorial pueda recargar