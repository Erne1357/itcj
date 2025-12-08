// itcj/apps/helpdesk/static/js/user/my_tickets.js

let allTickets = [];
let filteredTickets = [];
let currentPage = 1;
const itemsPerPage = 10;

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
        loadMyTickets();
        setupFilters();
        setupRatingModal();
        setupCancelModal();
    }, delay);
});

// ==================== LOAD TICKETS ====================
async function loadMyTickets() {
    try {
        console.log('🎫 Cargando tickets...');

        // Verificar si está en modo tutorial
        const isTutorialMode = typeof window.isTutorialModeActive === 'function' && window.isTutorialModeActive();
        console.log('🎫 Modo tutorial activo:', isTutorialMode);

        if (isTutorialMode) {
            // Modo tutorial: cargar solo el ticket de ejemplo
            const tutorialData = window.getTutorialTicketData();
            console.log('🎫 Datos del tutorial:', tutorialData);

            if (tutorialData && tutorialData.ticket) {
                console.log('🎫 Cargando ticket de ejemplo del tutorial');
                allTickets = [tutorialData.ticket];
                filteredTickets = [...allTickets];

                updateSummaryCards();
                renderTickets();
                return;
            } else {
                console.warn('⚠️ Modo tutorial activo pero sin datos de ticket');
            }
        }

        // Modo normal: cargar tickets de la BD
        console.log('🎫 Cargando tickets desde la BD');
        const response = await HelpdeskUtils.api.getTickets({ created_by_me: true });
        allTickets = response.tickets || [];
        filteredTickets = [...allTickets];

        updateSummaryCards();
        renderTickets();

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
    const active = allTickets.filter(t => 
        ['PENDING', 'ASSIGNED', 'IN_PROGRESS'].includes(t.status)
    ).length;
    const resolved = allTickets.filter(t => 
        ['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED'].includes(t.status)
    ).length;
    const pendingRating = allTickets.filter(t => 
        ['RESOLVED_SUCCESS', 'RESOLVED_FAILED'].includes(t.status) && !t.rating_attention
    ).length;
    
    document.getElementById('totalTickets').textContent = total;
    document.getElementById('activeTickets').textContent = active;
    document.getElementById('resolvedTickets').textContent = resolved;
    document.getElementById('pendingRating').textContent = pendingRating;
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
            <div class="empty-state">
                <i class="fas fa-inbox text-muted"></i>
                <h5 class="text-muted">No hay tickets</h5>
                <p class="text-muted">
                    ${allTickets.length === 0 
                        ? 'Aún no has creado ningún ticket.' 
                        : 'No hay tickets que coincidan con los filtros.'}
                </p>
                ${allTickets.length === 0 ? `
                    <a href="/help-desk/user/create" class="btn btn-primary mt-3">
                        <i class="fas fa-plus me-2"></i>Crear mi primer ticket
                    </a>
                ` : ''}
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
    const canRate = ['RESOLVED_SUCCESS', 'RESOLVED_FAILED'].includes(ticket.status) && !ticket.rating_attention;
    const canCancel = ['PENDING', 'ASSIGNED'].includes(ticket.status);
    const hasRating = ticket.rating_attention !== null;
    
    return `
        <div class="ticket-card border-bottom p-3" onclick="showTicketDetail(${ticket.id})">
            <div class="row align-items-start">
                <!-- Main Info -->
                <div class="col-md-8">
                    <div class="d-flex align-items-center gap-2 mb-2">
                        <h6 class="mb-0 fw-bold">${ticket.ticket_number}</h6>
                        ${HelpdeskUtils.getAreaBadge(ticket.area)}
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
                        
                        <div class="btn-group" role="group">
                            <button class="btn btn-outline-primary btn-sm" onclick="showTicketDetail(${ticket.id})">
                                <i class="fas fa-eye me-1"></i>Vista Rápida
                            </button>
                            <button class="btn btn-primary btn-sm" onclick="goToTicketDetail(${ticket.id})">
                                <i class="fas fa-external-link-alt me-1"></i>Abrir
                            </button>
                        </div>
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
    renderTickets();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ==================== FILTERS ====================
function setupFilters() {
    const filterStatus = document.getElementById('filterStatus');
    const filterArea = document.getElementById('filterArea');
    const searchInput = document.getElementById('searchInput');
    
    filterStatus.addEventListener('change', applyFilters);
    filterArea.addEventListener('change', applyFilters);
    
    // Debounce search
    let searchTimeout;
    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(applyFilters, 300);
    });
}

function applyFilters() {
    const status = document.getElementById('filterStatus').value;
    const area = document.getElementById('filterArea').value;
    const search = document.getElementById('searchInput').value.toLowerCase().trim();
    
    filteredTickets = allTickets.filter(ticket => {
        // Status filter
        if (status && ticket.status !== status) return false;
        
        // Area filter
        if (area && ticket.area !== area) return false;
        
        // Search filter
        if (search) {
            const matchTitle = ticket.title.toLowerCase().includes(search);
            const matchNumber = ticket.ticket_number.toLowerCase().includes(search);
            const matchDescription = ticket.description.toLowerCase().includes(search);
            if (!matchTitle && !matchNumber && !matchDescription) return false;
        }
        
        return true;
    });
    
    currentPage = 1;
    renderTickets();
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

// ==================== TICKET DETAIL MODAL ====================
async function showTicketDetail(ticketId) {
    const modal = new bootstrap.Modal(document.getElementById('detailModal'));
    const body = document.getElementById('detailModalBody');
    
    // Show loading
    body.innerHTML = `
        <div class="text-center py-5">
            <div class="spinner-border text-primary" role="status"></div>
            <p class="text-muted mt-3">Cargando detalles...</p>
        </div>
    `;
    
    modal.show();
    
    try {
        const response = await HelpdeskUtils.api.getTicket(ticketId);
        const ticket = response.ticket;
        
        // Get comments
        const commentsResponse = await HelpdeskUtils.api.getComments(ticketId);
        const comments = commentsResponse.comments || [];
        
        // Render detail
        renderTicketDetail(ticket, comments);
        
    } catch (error) {
        console.error('Error loading ticket detail:', error);
        body.innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-circle me-2"></i>
                Error al cargar los detalles del ticket
            </div>
        `;
    }
}

function renderTicketDetail(ticket, comments) {
    const body = document.getElementById('detailModalBody');
    const title = document.getElementById('detailModalTitle');
    
    title.textContent = ticket.ticket_number;
    
    body.innerHTML = `
        <!-- Header -->
        <div class="mb-4">
            <h4 class="mb-3">${ticket.title}</h4>
            <div class="d-flex gap-2 flex-wrap">
                ${HelpdeskUtils.getStatusBadge(ticket.status)}
                ${HelpdeskUtils.getAreaBadge(ticket.area)}
                ${HelpdeskUtils.getPriorityBadge(ticket.priority)}
                ${ticket.category ? `<span class="badge bg-secondary">${ticket.category.name}</span>` : ''}
            </div>
        </div>
        
        <!-- Info Grid -->
        <div class="row g-3 mb-4">
            <div class="col-md-6">
                <small class="text-muted d-block">Creado</small>
                <strong>${HelpdeskUtils.formatDate(ticket.created_at)}</strong>
            </div>
            
            ${ticket.location ? `
            <div class="col-md-6">
                <small class="text-muted d-block">Ubicación</small>
                <strong><i class="fas fa-map-marker-alt me-1"></i>${ticket.location}</strong>
            </div>
            ` : ''}
            
            ${ticket.assigned_to ? `
            <div class="col-md-6">
                <small class="text-muted d-block">Asignado a</small>
                <strong><i class="fas fa-user-check me-1"></i>${ticket.assigned_to.name}</strong>
            </div>
            ` : ''}
            
            ${ticket.resolved_at ? `
            <div class="col-md-6">
                <small class="text-muted d-block">Resuelto</small>
                <strong>${HelpdeskUtils.formatDate(ticket.resolved_at)}</strong>
            </div>
            ` : ''}
        </div>
        
        <!-- Description -->
        <div class="mb-4">
            <h6 class="fw-bold mb-2">Descripción</h6>
            <p class="text-muted">${ticket.description}</p>
        </div>
        
        ${ticket.resolution_notes ? `
        <div class="mb-4">
            <h6 class="fw-bold mb-2">Solución</h6>
            <div class="alert alert-success mb-0">
                <i class="fas fa-check-circle me-2"></i>
                ${ticket.resolution_notes}
            </div>
        </div>
        ` : ''}
        
        ${ticket.rating ? `
        <div class="mb-4">
            <h6 class="fw-bold mb-2">Tu Calificación</h6>
            <div class="p-3 bg-light rounded">
                ${HelpdeskUtils.renderStarRating(ticket.rating, '2x')}
                ${ticket.rating_comment ? `
                    <p class="mb-0 mt-2 text-muted">"${ticket.rating_comment}"</p>
                ` : ''}
            </div>
        </div>
        ` : ''}
        
        <!-- Comments -->
        ${comments.length > 0 ? `
        <div class="mb-3">
            <h6 class="fw-bold mb-3">Comentarios (${comments.length})</h6>
            ${comments.map(c => `
                <div class="card mb-2">
                    <div class="card-body py-2">
                        <div class="d-flex justify-content-between align-items-start">
                            <div>
                                <strong>${c.author.name}</strong>
                                <small class="text-muted ms-2">${HelpdeskUtils.formatTimeAgo(c.created_at)}</small>
                            </div>
                        </div>
                        <p class="mb-0 mt-2">${c.content}</p>
                    </div>
                </div>
            `).join('')}
        </div>
        ` : ''}
    `;
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

// ==================== EXPORT FOR INLINE CALLS ====================
window.showTicketDetail = showTicketDetail;
// ==================== NAVIGATION ====================
function goToTicketDetail(ticketId) {
    HelpdeskUtils.goToTicketDetail(ticketId, 'my_tickets');
}

// Global functions
window.openRatingModal = openRatingModal;
window.openCancelModal = openCancelModal;
window.goToTicketDetail = goToTicketDetail;
window.changePage = changePage;
window.loadMyTickets = loadMyTickets; // Exportar para que el tutorial pueda recargar