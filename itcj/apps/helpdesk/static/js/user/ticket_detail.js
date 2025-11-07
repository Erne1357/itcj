let currentTicket = null;
let currentRating = 0;

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', () => {
    loadTicketDetail();
    setupRatingModal();
    setupCancelModal();
});

// ==================== LOAD TICKET DETAIL ====================
async function loadTicketDetail() {
    showState('loading');
    
    try {
        // Load ticket data
        const ticketResponse = await HelpdeskUtils.api.getTicket(ticketId);
        currentTicket = ticketResponse.ticket;
        
        // Load comments
        const commentsResponse = await HelpdeskUtils.api.getComments(ticketId);
        const comments = commentsResponse.comments || [];
        
        // Render everything
        renderTicketDetail(currentTicket);
        renderComments(comments);
        renderStatusTimeline(currentTicket);
        renderAssignmentInfo(currentTicket);
        renderActionButtons(currentTicket);
        
        showState('main');
        
    } catch (error) {
        console.error('Error loading ticket:', error);
        showError(error.message || 'No se pudo cargar el ticket');
    }
}

function showState(state) {
    document.getElementById('loadingState').classList.toggle('d-none', state !== 'loading');
    document.getElementById('errorState').classList.toggle('d-none', state !== 'error');
    document.getElementById('mainContent').classList.toggle('d-none', state !== 'main');
}

function showError(message) {
    document.getElementById('errorMessage').textContent = message;
    showState('error');
}

// ==================== RENDER TICKET DETAIL ====================
function renderTicketDetail(ticket) {
    // Header
    document.getElementById('ticketNumber').innerHTML = `
        <i class="fas fa-ticket-alt me-2 text-primary"></i>${ticket.ticket_number}
    `;
    
    // Title
    document.getElementById('ticketTitle').textContent = ticket.title;
    
    // Badges
    document.getElementById('ticketBadges').innerHTML = `
        ${HelpdeskUtils.getStatusBadge(ticket.status)}
        ${HelpdeskUtils.getAreaBadge(ticket.area)}
        ${HelpdeskUtils.getPriorityBadge(ticket.priority)}
        ${ticket.category ? `<span class="badge bg-secondary">${ticket.category.name}</span>` : ''}
    `;
    
    // Dates
    document.getElementById('ticketCreated').textContent = HelpdeskUtils.formatDate(ticket.created_at);
    document.getElementById('ticketUpdated').textContent = HelpdeskUtils.formatTimeAgo(ticket.updated_at);
    
    // Location (optional)
    if (ticket.location) {
        document.getElementById('locationContainer').style.display = '';
        document.getElementById('ticketLocation').textContent = ticket.location;
    }
    
    // Folio (optional)
    if (ticket.office_document_folio) {
        document.getElementById('folioContainer').style.display = '';
        document.getElementById('ticketFolio').textContent = ticket.office_document_folio;
    }
    
    // Description
    document.getElementById('ticketDescription').textContent = ticket.description;
    

    // Resolution (if exists)
    if (ticket.resolution_notes) {
        document.getElementById('resolutionContainer').classList.remove('d-none');
        document.getElementById('resolutionNotes').textContent = ticket.resolution_notes;
        document.getElementById('resolvedBy').textContent = ticket.resolved_by?.full_name || 'N/A';
        document.getElementById('resolvedAt').textContent = HelpdeskUtils.formatDate(ticket.resolved_at);
    }
    
    // Rating (if exists)
    if (ticket.rating) {
        document.getElementById('ratingContainer').classList.remove('d-none');
        document.getElementById('ratingStars').innerHTML = HelpdeskUtils.renderStarRating(ticket.rating, '2x');
        if (ticket.rating_comment) {
            document.getElementById('ratingComment').textContent = ticket.rating_comment;
        } else {
            document.getElementById('ratingComment').textContent = 'Sin comentarios adicionales';
        }
    }
    if (ticket.inventory_item) {
        renderEquipmentInfo(ticket.inventory_item);
    }
    
    // Photo Attachment (if exists)
    loadPhotoAttachment(ticket.id);
    // Quick Actions Menu
    renderQuickActions(ticket);
    
    // Show comment form if ticket is open
    const isOpen = !['CLOSED', 'CANCELED'].includes(ticket.status);
    document.getElementById('addCommentForm').classList.toggle('d-none', !isOpen);
}

function renderQuickActions(ticket) {
    const menu = document.getElementById('quickActions');
    let html = '';
    
    // Refresh
    html += `
        <li>
            <a class="dropdown-item" href="#" onclick="loadTicketDetail(); return false;">
                <i class="fas fa-sync me-2"></i>Actualizar
            </a>
        </li>
    `;
    
    // Print
    html += `
        <li>
            <a class="dropdown-item" href="#" onclick="window.print(); return false;">
                <i class="fas fa-print me-2"></i>Imprimir
            </a>
        </li>
    `;
    
    menu.innerHTML = html;
}

// ==================== RENDER COMMENTS ====================
function renderComments(comments) {
    const container = document.getElementById('commentsList');
    const countBadge = document.getElementById('commentsCount');
    
    countBadge.textContent = comments.length;
    
    if (comments.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="fas fa-comment-slash fa-2x mb-2"></i>
                <p class="mb-0">No hay comentarios aún</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = comments.map(comment => `
        <div class="comment-bubble ${comment.author.id === currentTicket.requester.id ? 'own' : ''}">
            <div class="d-flex justify-content-between align-items-start">
                <div class="comment-author">
                    <i class="fas fa-user-circle me-1"></i>${comment.author.name}
                </div>
                <div class="comment-time">
                    ${HelpdeskUtils.formatTimeAgo(comment.created_at)}
                </div>
            </div>
            <div class="comment-text">${comment.content}</div>
        </div>
    `).join('');
}

// ==================== ADD COMMENT ====================
async function addComment() {
    const textarea = document.getElementById('newCommentText');
    const content = textarea.value.trim();
    
    if (!content) {
        HelpdeskUtils.showToast('Escribe un comentario', 'warning');
        return;
    }
    
    const btn = document.getElementById('btnAddComment');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    
    try {
        await HelpdeskUtils.api.addComment(ticketId, content);
        
        HelpdeskUtils.showToast('Comentario agregado', 'success');
        textarea.value = '';
        
        // Reload comments
        const commentsResponse = await HelpdeskUtils.api.getComments(ticketId);
        renderComments(commentsResponse.comments || []);
        
    } catch (error) {
        console.error('Error adding comment:', error);
        HelpdeskUtils.showToast(error.message || 'Error al agregar comentario', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-paper-plane"></i>';
    }
}

// ==================== RENDER STATUS TIMELINE ====================
function renderStatusTimeline(ticket) {
    const container = document.getElementById('statusTimeline');
    
    // Define status flow
    const statusFlow = [
        { status: 'PENDING', label: 'Creado', icon: 'fa-plus-circle' },
        { status: 'ASSIGNED', label: 'Asignado', icon: 'fa-user-check' },
        { status: 'IN_PROGRESS', label: 'En Progreso', icon: 'fa-cog' },
        { status: 'RESOLVED_SUCCESS', label: 'Resuelto', icon: 'fa-check-circle' },
        { status: 'CLOSED', label: 'Cerrado', icon: 'fa-lock' }
    ];
    
    const currentStatusIndex = statusFlow.findIndex(s => s.status === ticket.status);
    
    container.innerHTML = `
        <div class="timeline">
            ${statusFlow.map((item, index) => {
                const isPast = index < currentStatusIndex;
                const isCurrent = index === currentStatusIndex;
                const isActive = isPast || isCurrent;
                
                return `
                    <div class="timeline-item ${isCurrent ? 'active' : ''} ${!isActive ? 'text-muted' : ''}">
                        <div class="timeline-item-content">
                            <i class="fas ${item.icon} me-2"></i>
                            <strong>${item.label}</strong>
                            ${isCurrent ? '<span class="badge bg-primary ms-2">Actual</span>' : ''}
                        </div>
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

// ==================== RENDER ASSIGNMENT INFO ====================
function renderAssignmentInfo(ticket) {
    const container = document.getElementById('assignmentInfo');
    
    if (ticket.assigned_to) {
        const initials = ticket.assigned_to.name.split(' ').map(n => n[0]).join('').substring(0, 2);
        container.innerHTML = `
            <div class="d-flex align-items-center gap-3">
                <div class="assignment-avatar">${initials}</div>
                <div>
                    <div class="fw-bold">${ticket.assigned_to.name}</div>
                    <small class="text-muted">Técnico Asignado</small>
                </div>
            </div>
        `;
    } else if (ticket.assigned_to_team) {
        container.innerHTML = `
            <div class="text-center">
                <i class="fas fa-users fa-2x text-primary mb-2"></i>
                <p class="mb-0 fw-bold">Equipo ${ticket.assigned_to_team}</p>
                <small class="text-muted">Pendiente de asignación individual</small>
            </div>
        `;
    } else {
        container.innerHTML = `
            <div class="text-center text-muted">
                <i class="fas fa-clock fa-2x mb-2"></i>
                <p class="mb-0">Sin asignar</p>
                <small>Esperando asignación</small>
            </div>
        `;
    }
}

// ==================== RENDER ACTION BUTTONS ====================
function renderActionButtons(ticket) {
    const container = document.getElementById('actionButtons');
    let html = '';
    
    const canRate = ['RESOLVED_SUCCESS', 'RESOLVED_FAILED'].includes(ticket.status) && !ticket.rating;
    const canCancel = ['PENDING', 'ASSIGNED'].includes(ticket.status);
    
    if (canRate) {
        html += `
            <button class="btn btn-warning btn-lg btn-action" onclick="openRatingModal()">
                <i class="fas fa-star me-2"></i>Calificar Servicio
            </button>
        `;
    }
    
    if (canCancel) {
        html += `
            <button class="btn btn-outline-danger btn-action" onclick="openCancelModal()">
                <i class="fas fa-ban me-2"></i>Cancelar Ticket
            </button>
        `;
    }
    
    container.innerHTML = html;
}

// ==================== RATING MODAL ====================
function setupRatingModal() {
    document.querySelectorAll('.star-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            currentRating = parseInt(this.dataset.rating);
            updateStarButtons();
            document.getElementById('btnSubmitRating').disabled = false;
        });
    });
    
    document.getElementById('btnSubmitRating').addEventListener('click', submitRating);
}

function openRatingModal() {
    currentRating = 0;
    updateStarButtons();
    document.getElementById('ratingCommentInput').value = '';
    document.getElementById('btnSubmitRating').disabled = true;
    
    const modal = new bootstrap.Modal(document.getElementById('ratingModal'));
    modal.show();
}

function updateStarButtons() {
    document.querySelectorAll('.star-btn').forEach(btn => {
        const rating = parseInt(btn.dataset.rating);
        if (rating <= currentRating) {
            btn.classList.remove('btn-outline-warning');
            btn.classList.add('btn-warning', 'active');
        } else {
            btn.classList.remove('btn-warning', 'active');
            btn.classList.add('btn-outline-warning');
        }
    });
}

async function submitRating() {
    if (currentRating === 0) return;
    
    const btn = document.getElementById('btnSubmitRating');
    const originalText = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Enviando...';
    
    try {
        const comment = document.getElementById('ratingCommentInput').value.trim();
        
        await HelpdeskUtils.api.rateTicket(ticketId, {
            rating: currentRating,
            comment: comment || null
        });
        
        HelpdeskUtils.showToast('¡Gracias por tu calificación!', 'success');
        
        const modal = bootstrap.Modal.getInstance(document.getElementById('ratingModal'));
        modal.hide();
        
        // Reload ticket
        await loadTicketDetail();
        
    } catch (error) {
        console.error('Error submitting rating:', error);
        HelpdeskUtils.showToast(error.message || 'Error al enviar calificación', 'error');
        
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// ==================== CANCEL MODAL ====================
function setupCancelModal() {
    document.getElementById('btnConfirmCancel').addEventListener('click', confirmCancel);
}

function openCancelModal() {
    document.getElementById('cancelReason').value = '';
    const modal = new bootstrap.Modal(document.getElementById('cancelModal'));
    modal.show();
}

async function confirmCancel() {
    const btn = document.getElementById('btnConfirmCancel');
    const originalText = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Cancelando...';
    
    try {
        const reason = document.getElementById('cancelReason').value.trim();
        
        await HelpdeskUtils.api.cancelTicket(ticketId, reason || null);
        
        HelpdeskUtils.showToast('Ticket cancelado exitosamente', 'success');
        
        const modal = bootstrap.Modal.getInstance(document.getElementById('cancelModal'));
        modal.hide();
        
        // Reload ticket
        await loadTicketDetail();
        
    } catch (error) {
        console.error('Error canceling ticket:', error);
        HelpdeskUtils.showToast(error.message || 'Error al cancelar ticket', 'error');
        
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}
function renderEquipmentInfo(equipment) {
    const container = document.getElementById('equipmentInfo');
    const card = document.getElementById('equipmentCard');
    
    if (!equipment) {
        card.style.display = 'none';
        return;
    }
    
    // Mostrar card
    card.style.display = 'block';
    
    // Icono según categoría
    const icon = equipment.category?.icon || 'fas fa-laptop';
    
    // Información del propietario
    let ownerHtml = '';
    if (equipment.assigned_to_user) {
        ownerHtml = `
            <div class="mb-2">
                <small class="text-muted d-block">Asignado a:</small>
                <strong><i class="fas fa-user me-1"></i>${equipment.assigned_to_user.full_name}</strong>
            </div>
        `;
    } else {
        ownerHtml = `
            <div class="mb-2">
                <span class="badge bg-secondary">
                    <i class="fas fa-building me-1"></i>Global del Departamento
                </span>
            </div>
        `;
    }
    
    container.innerHTML = `
        <div class="d-flex align-items-start gap-3">
            <div class="equipment-icon-detail">
                <i class="${icon}"></i>
            </div>
            <div class="flex-grow-1">
                <div class="fw-bold text-primary mb-1">${equipment.inventory_number}</div>
                <div class="mb-2">
                    <strong>${equipment.brand || 'N/A'} ${equipment.model || ''}</strong>
                </div>
                <div class="mb-2">
                    <span class="badge bg-info">
                        <i class="fas fa-tag me-1"></i>${equipment.category?.name || 'Sin categoría'}
                    </span>
                </div>
                ${ownerHtml}
                ${equipment.location_detail ? `
                    <div>
                        <small class="text-muted">
                            <i class="fas fa-map-marker-alt me-1"></i>${equipment.location_detail}
                        </small>
                    </div>
                ` : ''}
            </div>
        </div>
    `;
}

// ==================== LOAD AND RENDER PHOTO ====================
async function loadPhotoAttachment(ticketId) {
    try {
        const response = await HelpdeskUtils.api.getAttachments(ticketId);
        const attachments = response.attachments || [];
        
        if (attachments.length === 0) {
            return; // No hay foto
        }
        
        // Tomar el primer attachment (asumiendo que es la única foto)
        const photo = attachments[0];
        
        // Mostrar container
        document.getElementById('photoContainer').style.display = 'block';
        
        // Renderizar thumbnail
        renderPhotoThumbnail(photo);
        
    } catch (error) {
        console.error('Error loading photo:', error);
        // No mostrar error al usuario, simplemente no mostrar la foto
    }
}

function renderPhotoThumbnail(photo) {
    const container = document.getElementById('photoThumbnail');
    
    // URL para descargar/ver la foto
    const photoUrl = `/api/help-desk/v1/attachments/${photo.id}/download`;
    
    container.innerHTML = `
        <div class="photo-thumbnail" onclick="openPhotoModal('${photoUrl}')">
            <img src="${photoUrl}" alt="Foto del problema" class="img-thumbnail">
            <div class="photo-overlay">
                <i class="fas fa-search-plus fa-2x"></i>
            </div>
        </div>
        <div class="mt-2">
            <small class="text-muted">
                <i class="fas fa-clock me-1"></i>Subida ${HelpdeskUtils.formatTimeAgo(photo.uploaded_at)}
            </small>
        </div>
    `;
}

function openPhotoModal(photoUrl) {
    const modal = new bootstrap.Modal(document.getElementById('photoModal'));
    document.getElementById('photoModalImage').src = photoUrl;
    modal.show();
}