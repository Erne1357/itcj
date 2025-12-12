let currentTicket = null;
let currentRatingAttention = 0;
let currentRatingSpeed = 0;
let currentRatingEfficiency = null;

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
        // Verificar si hay parámetro tutorial=true en la URL
        const urlParams = new URLSearchParams(window.location.search);
        const isTutorialParam = urlParams.get('tutorial') === 'true';

        console.log('🎫 [ticket_detail] Cargando ticket...');
        console.log('🎫 Parámetro tutorial en URL:', isTutorialParam);
        console.log('🎫 Ticket ID:', ticketId);

        // Verificar si está en modo tutorial (por URL o por estado)
        const isTutorialMode = isTutorialParam || (typeof window.isTutorialModeActive === 'function' && window.isTutorialModeActive());

        if (isTutorialMode) {
            console.log('🎫 Modo tutorial detectado');
            const tutorialTicketId = window.getTutorialTicketId();
            console.log('🎫 Tutorial ticket ID esperado:', tutorialTicketId);

            // Si el ID coincide con el del tutorial, cargar desde JSON
            if (tutorialTicketId && ticketId == tutorialTicketId) {
                console.log('🎫 Cargando desde JSON (modo tutorial)');
                const tutorialData = window.getTutorialTicketData();

                if (tutorialData) {
                    console.log('🎫 Datos del tutorial cargados correctamente');
                    currentTicket = tutorialData.ticket;
                    const comments = tutorialData.comments || [];

                    // Render everything
                    renderTicketDetail(currentTicket);
                    renderComments(comments);
                    renderStatusTimeline(currentTicket);
                    renderAssignmentInfo(currentTicket);
                    renderActionButtons(currentTicket);
                    
                    // Cargar photo attachment para mostrar badge
                    await loadPhotoAttachment(currentTicket.id);

                    showState('main');
                    return;
                } else {
                    console.warn('⚠️ No se encontraron datos del tutorial en sessionStorage');
                }
            } else {
                console.warn('⚠️ ID no coincide:', { ticketId, tutorialTicketId });
            }
        }

        // Modo normal: cargar desde la BD
        console.log('🎫 Cargando desde la BD (modo normal)');
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
        
        // Cargar photo attachment para mostrar badge
        await loadPhotoAttachment(currentTicket.id);

        showState('main');

    } catch (error) {
        console.error('Error loading ticket:', error);
        const errorMessage = error.message || 'Error desconocido';
        showError(`No se pudo cargar el ticket: ${errorMessage}`);
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

    // Custom Fields (if exist)
    renderCustomFields(ticket);

    // Resolution (if exists)
    if (ticket.resolution_notes) {
        document.getElementById('resolutionContainer').classList.remove('d-none');
        document.getElementById('resolutionNotes').textContent = ticket.resolution_notes;
        document.getElementById('resolvedBy').textContent = ticket.resolved_by?.full_name || 'N/A';
        document.getElementById('resolvedAt').textContent = HelpdeskUtils.formatDate(ticket.resolved_at);
    }

    // Collaborators (if exist)
    if (ticket.collaborators && ticket.collaborators.length > 0) {
        document.getElementById('collaboratorsContainer').classList.remove('d-none');
        document.getElementById('ticketCollaborators').innerHTML = HelpdeskUtils.renderCollaborators(ticket.collaborators);
    }

    // Rating (if exists)
    if (ticket.rating_attention) {
        document.getElementById('ratingContainer').classList.remove('d-none');
        document.getElementById('ratingStars').innerHTML = `
            <div><i class="fas fa-user-tie me-1"></i><strong>Atención:</strong> ${HelpdeskUtils.renderStarRating(ticket.rating_attention)}</div>
            <div><i class="fas fa-tachometer-alt me-1"></i><strong>Rapidez:</strong> ${HelpdeskUtils.renderStarRating(ticket.rating_speed)}</div>
            <div><i class="fas fa-check-circle me-1"></i><strong>Eficiencia:</strong> ${ticket.rating_efficiency ? '<span class="text-success">Sí</span>' : '<span class="text-danger">No</span>'}</div>
        `;
        if (ticket.rating_comment) {
            document.getElementById('ratingComment').textContent = ticket.rating_comment;
        } else {
            document.getElementById('ratingComment').textContent = 'Sin comentarios adicionales';
        }
    }
    if (ticket.inventory_items && ticket.inventory_items.length > 0) {
        // Múltiples equipos
        renderEquipmentInfo(ticket.inventory_items);
    } else if (ticket.inventory_item) {
        // Un solo equipo (compatibilidad con versión anterior)
        renderEquipmentInfo(ticket.inventory_item);
    }

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

// ==================== RENDER CUSTOM FIELDS ====================
async function renderCustomFields(ticket) {
    const container = document.getElementById('customFieldsContainer');
    const content = document.getElementById('customFieldsContent');

    // Si no hay custom_fields o está vacío, ocultar
    if (!ticket.custom_fields || Object.keys(ticket.custom_fields).length === 0) {
        container.classList.add('d-none');
        return;
    }

    // Obtener category_id del ticket
    const categoryId = ticket.category_id || ticket.category?.id;
    if (!categoryId) {
        container.classList.add('d-none');
        return;
    }

    try {
        // Obtener el field_template de la categoría
        const response = await HelpdeskUtils.api.request(`/categories/${categoryId}/field-template`);
        const fieldTemplate = response.field_template;

        if (!fieldTemplate || !fieldTemplate.enabled) {
            container.classList.add('d-none');
            return;
        }

        // Renderizar los campos
        const fields = fieldTemplate.fields || [];
        let html = '';

        fields.forEach(field => {
            const value = ticket.custom_fields[field.key];

            // Skip si no hay valor
            if (value === undefined || value === null) {
                return;
            }

            let displayValue = '';

            // Formatear valor según tipo
            if (field.type === 'checkbox') {
                displayValue = value ? '<span class="badge bg-success">Sí</span>' : '<span class="badge bg-secondary">No</span>';
            } else if (field.type === 'select' || field.type === 'radio') {
                const option = field.options?.find(opt => opt.value === value);
                displayValue = option ? option.label : value;
            } else if (field.type === 'file') {
                // Mostrar nombre del archivo o link si es ruta
                if (typeof value === 'string' && value.includes('/')) {
                    const filename = value.split('/').pop();
                    displayValue = `<a href="${value}" target="_blank" class="text-decoration-none">
                        <i class="fas fa-file me-1"></i>${filename}
                    </a>`;
                } else {
                    displayValue = `<i class="fas fa-file me-1"></i>${value}`;
                }
            } else {
                // text, textarea
                displayValue = value;
            }

            html += `
                <div class="col-md-6">
                    <small class="text-muted d-block mb-1">
                        <i class="fas fa-chevron-right me-1"></i>${field.label}
                    </small>
                    <strong>${displayValue}</strong>
                </div>
            `;
        });

        if (html) {
            content.innerHTML = html;
            container.classList.remove('d-none');
        } else {
            container.classList.add('d-none');
        }

    } catch (error) {
        console.error('Error loading custom fields template:', error);
        container.classList.add('d-none');
    }
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
        const errorMessage = error.message || 'Error desconocido';
        HelpdeskUtils.showToast(`Error al agregar comentario: ${errorMessage}`, 'error');
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

    const canRate = ['RESOLVED_SUCCESS', 'RESOLVED_FAILED'].includes(ticket.status) && !ticket.rating_attention;
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
    // Configurar estrellas de atención
    document.querySelectorAll('.star-btn-attention').forEach(btn => {
        btn.addEventListener('click', () => {
            currentRatingAttention = parseInt(btn.dataset.rating);
            updateStarButtons();
        });
    });

    // Configurar estrellas de rapidez
    document.querySelectorAll('.star-btn-speed').forEach(btn => {
        btn.addEventListener('click', () => {
            currentRatingSpeed = parseInt(btn.dataset.rating);
            updateStarButtons();
        });
    });

    // Configurar radio buttons de eficiencia
    document.querySelectorAll('input[name="ratingEfficiencyDetail"]').forEach(radio => {
        radio.addEventListener('change', () => {
            currentRatingEfficiency = radio.value === 'true';
            checkRatingFormValidity();
        });
    });

    document.getElementById('btnSubmitRating').addEventListener('click', submitRating);
}

function checkRatingFormValidity() {
    const isValid = currentRatingAttention > 0 && currentRatingSpeed > 0 && currentRatingEfficiency !== null;
    document.getElementById('btnSubmitRating').disabled = !isValid;
}

function openRatingModal() {
    currentRatingAttention = 0;
    currentRatingSpeed = 0;
    currentRatingEfficiency = null;
    updateStarButtons();
    document.getElementById('ratingCommentInput').value = '';
    
    // Reset radio buttons
    document.querySelectorAll('input[name="ratingEfficiencyDetail"]').forEach(radio => {
        radio.checked = false;
    });
    
    document.getElementById('btnSubmitRating').disabled = true;

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
    
    checkRatingFormValidity();
}

async function submitRating() {
    if (currentRatingAttention === 0 || currentRatingSpeed === 0 || currentRatingEfficiency === null) {
        HelpdeskUtils.showToast('Por favor completa todos los campos obligatorios', 'warning');
        return;
    }

    const btn = document.getElementById('btnSubmitRating');
    const originalText = btn.innerHTML;

    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Enviando...';

    try {
        const response = await HelpdeskUtils.api.rateTicket(ticketId, {
            rating_attention: currentRatingAttention,
            rating_speed: currentRatingSpeed,
            rating_efficiency: currentRatingEfficiency,
            comment: document.getElementById('ratingCommentInput').value.trim() || null
        });

        HelpdeskUtils.showToast('¡Gracias por tu evaluación!', 'success');

        const modal = bootstrap.Modal.getInstance(document.getElementById('ratingModal'));
        modal.hide();

        // Reload ticket
        await loadTicketDetail();

    } catch (error) {
        console.error('Error al enviar evaluación:', error);
        const errorMessage = error.message || 'Error desconocido';
        HelpdeskUtils.showToast(`Error al enviar la evaluación: ${errorMessage}`, 'danger');
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
        const errorMessage = error.message || 'Error desconocido';
        HelpdeskUtils.showToast(`Error al cancelar ticket: ${errorMessage}`, 'error');

        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}
async function renderEquipmentInfo(equipmentData) {
    const container = document.getElementById('equipmentInfo');
    const card = document.getElementById('equipmentCard');

    // Si no hay equipos, ocultar card
    if (!equipmentData || (Array.isArray(equipmentData) && equipmentData.length === 0)) {
        card.style.display = 'none';
        return;
    }

    // Mostrar card
    card.style.display = 'block';

    // Determinar si son múltiples equipos o uno solo
    const isMultiple = Array.isArray(equipmentData);

    if (isMultiple) {
        // Múltiples equipos (de un grupo)
        renderMultipleEquipmentPreview(equipmentData, container);
    } else {
        // Equipo individual
        renderSingleEquipmentPreview(equipmentData, container);
    }
}

function renderSingleEquipmentPreview(equipment, container) {
    const icon = equipment.category?.icon || 'fas fa-laptop';

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
        <div class="d-flex align-items-start gap-3 cursor-pointer hover-bg-light p-2 rounded" onclick="openEquipmentDetail(${equipment.id})" title="Click para ver detalles del equipo">
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
                <div class="mt-2">
                    <small class="text-muted">
                        <i class="fas fa-hand-pointer me-1"></i>Click para ver más detalles
                    </small>
                </div>
            </div>
        </div>
    `;
}

function renderMultipleEquipmentPreview(equipmentList, container) {
    // Obtener información del grupo si todos los equipos pertenecen al mismo
    const firstEquipment = equipmentList[0];
    const groupInfo = firstEquipment.group || null;

    container.innerHTML = `
        <div class="multiple-equipment-preview cursor-pointer hover-bg-light p-2 rounded" onclick="openEquipmentListModal()" title="Click para ver la lista completa de equipos">
            <div class="d-flex align-items-start gap-3">
                <div class="equipment-icon-detail">
                    <i class="fas fa-layer-group"></i>
                </div>
                <div class="flex-grow-1">
                    ${groupInfo ? `
                        <div class="fw-bold text-info mb-1">
                            <i class="fas fa-door-open me-1"></i>${groupInfo.name}
                        </div>
                        <small class="text-muted d-block mb-2">${groupInfo.description || 'Grupo de equipos'}</small>
                    ` : `
                        <div class="fw-bold text-primary mb-1">Equipos Múltiples</div>
                    `}
                    <div class="mb-2">
                        <span class="badge bg-success">
                            <i class="fas fa-laptop me-1"></i>${equipmentList.length} equipos
                        </span>
                    </div>
                    ${groupInfo && (groupInfo.building || groupInfo.floor) ? `
                        <div>
                            <small class="text-muted">
                                <i class="fas fa-map-marker-alt me-1"></i>
                                ${[groupInfo.building, groupInfo.floor ? `Piso ${groupInfo.floor}` : ''].filter(Boolean).join(' - ')}
                            </small>
                        </div>
                    ` : ''}
                </div>
                <div class="ms-auto">
                    <i class="fas fa-chevron-right text-muted"></i>
                </div>
            </div>
            <div class="mt-3 pt-3 border-top">
                <small class="text-primary">
                    <i class="fas fa-hand-pointer me-1"></i>
                    Click para ver detalles de todos los equipos
                </small>
            </div>
        </div>
    `;
}

function openEquipmentListModal() {
    if (!currentTicket || !currentTicket.inventory_items || currentTicket.inventory_items.length === 0) {
        return;
    }

    const modal = new bootstrap.Modal(document.getElementById('equipmentListModal'));

    // Renderizar lista de equipos
    renderEquipmentModalList(currentTicket.inventory_items);

    modal.show();
}

// ==================== NAVIGATE TO EQUIPMENT DETAIL ====================
function openEquipmentDetail(itemId) {
    if (!itemId) {
        console.error('Equipment ID is required');
        return;
    }
    // Navegar a la página de detalle del equipo
    window.location.href = `/help-desk/inventory/items/${itemId}`;
}

function renderEquipmentModalList(equipmentList) {
    const listContainer = document.getElementById('equipment-modal-list');
    const groupInfoContainer = document.getElementById('equipment-modal-group-info');

    // Verificar si hay info de grupo
    const firstEquipment = equipmentList[0];
    if (firstEquipment.group) {
        groupInfoContainer.style.display = 'block';
        groupInfoContainer.innerHTML = `
            <div class="d-flex align-items-center">
                <i class="fas fa-door-open fa-2x me-3 text-info"></i>
                <div>
                    <h6 class="mb-0 fw-bold">${firstEquipment.group.name}</h6>
                    <small class="text-muted">${firstEquipment.group.description || ''}</small>
                    ${firstEquipment.group.building || firstEquipment.group.floor ? `
                        <div class="mt-1">
                            <span class="badge bg-light text-dark">
                                <i class="fas fa-map-marker-alt me-1"></i>
                                ${[firstEquipment.group.building, firstEquipment.group.floor ? `Piso ${firstEquipment.group.floor}` : ''].filter(Boolean).join(' - ')}
                            </span>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    } else {
        groupInfoContainer.style.display = 'none';
    }

    // Renderizar equipos
    listContainer.innerHTML = equipmentList.map(equipment => {
        const icon = equipment.category?.icon || 'fas fa-laptop';

        return `
            <div class="equipment-modal-item cursor-pointer" onclick="openEquipmentDetail(${equipment.id})" title="Click para ver detalles">
                <div class="d-flex align-items-start gap-3">
                    <div class="equipment-modal-icon">
                        <i class="${icon}"></i>
                    </div>
                    <div class="flex-grow-1">
                        <div class="fw-bold text-primary mb-1">${equipment.inventory_number}</div>
                        <div class="mb-2">
                            <strong>${equipment.brand || 'N/A'} ${equipment.model || ''}</strong>
                        </div>
                        <div class="d-flex flex-wrap gap-2 mb-2">
                            <span class="badge bg-info">
                                <i class="fas fa-tag me-1"></i>${equipment.category?.name || 'Sin categoría'}
                            </span>
                            ${equipment.serial_number ? `
                                <span class="badge bg-light text-dark">
                                    <i class="fas fa-barcode me-1"></i>${equipment.serial_number}
                                </span>
                            ` : ''}
                            ${getEquipmentStatusBadge(equipment.status)}
                        </div>
                        ${equipment.assigned_to_user ? `
                            <div class="mb-1">
                                <small class="text-muted">
                                    <i class="fas fa-user me-1"></i>${equipment.assigned_to_user.full_name}
                                </small>
                            </div>
                        ` : `
                            <div class="mb-1">
                                <small class="text-muted">
                                    <i class="fas fa-building me-1"></i>Global del Departamento
                                </small>
                            </div>
                        `}
                        ${equipment.location_detail ? `
                            <div>
                                <small class="text-muted">
                                    <i class="fas fa-map-marker-alt me-1"></i>${equipment.location_detail}
                                </small>
                            </div>
                        ` : ''}
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function getEquipmentStatusBadge(status) {
    const statusMap = {
        'ACTIVE': { class: 'success', text: 'Activo' },
        'MAINTENANCE': { class: 'warning', text: 'Mantenimiento' },
        'DAMAGED': { class: 'danger', text: 'Dañado' },
        'RETIRED': { class: 'secondary', text: 'Retirado' },
        'LOST': { class: 'dark', text: 'Extraviado' },
        'PENDING_ASSIGNMENT': { class: 'info', text: 'Pendiente' }
    };
    const config = statusMap[status] || { class: 'secondary', text: status };
    return `<span class="badge bg-${config.class}">${config.text}</span>`;
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

// ==================== EXPORT GLOBAL FUNCTIONS ====================
// Exportar funciones para que el tutorial pueda acceder a ellas
window.loadTicketDetail = loadTicketDetail;