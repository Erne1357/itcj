// itcj2/apps/helpdesk/static/js/user/ticket_detail.js
// Página: user/ticket_detail.html — migrada a navegación HTMX (Fase 2).
// Registrada en HelpdeskPage como 'user_ticket_detail'.

(function () {
    'use strict';

    // ==================== MODULE STATE ====================
    let currentTicket = null;
    let currentRatingAttention = 0;
    let currentRatingSpeed = 0;
    let currentRatingEfficiency = null;
    let commentPendingFiles = [];
    let ticketSocketBound = false;
    let _socketPoller = null;

    // These are read from data-* in init()
    let ticketId = null;
    let currentUserId = null;

    // ==================== INIT ====================
    function init() {
        // Read server data from data-hd-page element
        const root = document.querySelector('[data-hd-page]');
        if (root) {
            ticketId = parseInt(root.dataset.ticketId, 10);
            currentUserId = parseInt(root.dataset.currentUserId, 10);
        }

        // Reset module state (guard against re-init on same session)
        currentTicket = null;
        currentRatingAttention = 0;
        currentRatingSpeed = 0;
        currentRatingEfficiency = null;
        commentPendingFiles = [];
        ticketSocketBound = false;
        _socketPoller = null;

        // Reset resolve panel visibility
        const resolvePanel = document.getElementById('resolvePanel');
        if (resolvePanel) resolvePanel.classList.add('d-none');
        const mainContent = document.getElementById('mainContent');
        if (mainContent) mainContent.classList.remove('d-none');

        // Expose onclick globals
        window.loadTicketDetail = loadTicketDetail;
        window.startTicketWork = startTicketWork;
        window.confirmStartWork = confirmStartWork;
        window.openResolveModal = openResolveModal;
        window.closeResolvePanel = closeResolvePanel;
        window.openRatingModal = openRatingModal;
        window.openCancelModal = openCancelModal;
        window.openResolutionFilesModal = openResolutionFilesModal;
        window.deleteResolutionFile = deleteResolutionFile;
        window.viewAttachmentImage = viewAttachmentImage;
        window.downloadCustomFieldFile = downloadCustomFieldFile;
        window.removeCommentFile = removeCommentFile;
        window.addComment = addComment;
        window.openEquipmentDetail = openEquipmentDetail;
        window.openEquipmentListModal = openEquipmentListModal;
        window.openPhotoModal = openPhotoModal;

        // Setup modal event listeners
        setupRatingModal();
        setupCancelModal();
        setupCommentFileInput();

        // Attach warehouse listeners now that DOM is ready
        if (typeof window.TicketWarehouse !== 'undefined' && window.TicketWarehouse._attachListeners) {
            window.TicketWarehouse._attachListeners();
        }

        // Smart back-button logic (moved from inline header_back script)
        _initBackButton();

        // Start socket listeners
        setupWebSocketListeners();

        // Tutorial
        window.helpdeskTutorial?.maybeAutoStart('ticket_detail');

        // Load the ticket
        loadTicketDetail();
    }

    // ==================== DESTROY ====================
    function destroy() {
        // Leave realtime room
        if (window.__hdLeaveTicket && ticketId) {
            window.__hdLeaveTicket(ticketId);
        }

        // Clear socket poller
        if (_socketPoller) {
            clearInterval(_socketPoller);
            _socketPoller = null;
        }

        // Remove socket event listeners
        const socket = window.__helpdeskSocket;
        if (socket) {
            socket.off('ticket_status_changed');
            socket.off('ticket_comment_added');
            socket.off('ticket_assigned');
            socket.off('ticket_reassigned');
        }
        ticketSocketBound = false;

        // Dispose Bootstrap modals (guarded)
        const modalIds = [
            'startWorkModal',
            'equipmentListModal',
            'photoModal',
            'ratingModal',
            'cancelModal',
            'resolutionFilesModal',
            'attachmentImageModal',
            'warehouseQtyModal',
        ];
        modalIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                const instance = bootstrap.Modal.getInstance(el);
                if (instance) {
                    try { instance.dispose(); } catch (e) { /* ignore */ }
                }
            }
        });

        // Reset resolve panel
        const resolvePanel = document.getElementById('resolvePanel');
        if (resolvePanel) resolvePanel.classList.add('d-none');
        const mainContent = document.getElementById('mainContent');
        if (mainContent) mainContent.classList.remove('d-none');

        // Tutorial teardown
        window.helpdeskTutorial?.teardown();

        // Remove onclick globals
        const fns = [
            'loadTicketDetail', 'startTicketWork', 'confirmStartWork',
            'openResolveModal', 'closeResolvePanel', 'openRatingModal',
            'openCancelModal', 'openResolutionFilesModal', 'deleteResolutionFile',
            'viewAttachmentImage', 'downloadCustomFieldFile', 'removeCommentFile',
            'addComment', 'openEquipmentDetail', 'openEquipmentListModal', 'openPhotoModal',
        ];
        fns.forEach(fn => { delete window[fn]; });

        // Reset module state
        currentTicket = null;
        commentPendingFiles = [];
    }

    // ==================== BACK BUTTON (formerly inline in header_back) ====================
    function _initBackButton() {
        const backButton = document.getElementById('backButton');
        const backButtonText = document.getElementById('backButtonText');
        if (!backButton) return;

        const urlParams = new URLSearchParams(window.location.search);
        const fromParam = urlParams.get('from');
        const referrer = document.referrer;

        let backUrl = '/help-desk/user/tickets'; // Default fallback (url_for resolved server-side)
        let backText = 'Mis Tickets';

        if (fromParam) {
            switch (fromParam) {
                case 'dashboard':
                    backUrl = '/help-desk/user/dashboard';
                    backText = 'Dashboard';
                    break;
                case 'my_tickets':
                    backUrl = '/help-desk/user/tickets';
                    backText = 'Mis Tickets';
                    break;
                case 'department':
                    backUrl = '/help-desk/department/tickets';
                    backText = 'Departamento';
                    break;
                case 'admin':
                    backUrl = '/help-desk/admin/tickets-list';
                    backText = 'Administración';
                    break;
                case 'technician':
                    backUrl = '/help-desk/technician/dashboard';
                    backText = 'Panel de Técnicos';
                    break;
                case 'admin_tickets_list':
                    backUrl = '/help-desk/admin/tickets-list';
                    backText = 'Lista de Tickets';
                    break;
                case 'secretary':
                    backUrl = '/help-desk/admin/assign-tickets';
                    backText = 'Assignar Tickets';
                    break;
                case 'secretary_dashboard':
                    backUrl = '/help-desk/secretary/dashboard';
                    backText = 'Dashboard Secretaría';
                    break;
                default:
                    break;
            }
        } else if (referrer) {
            if (referrer.includes('/help-desk/user/dashboard')) {
                backUrl = '/help-desk/user/dashboard';
                backText = 'Dashboard';
            } else if (referrer.includes('/help-desk/user/tickets')) {
                backUrl = '/help-desk/user/tickets';
                backText = 'Mis Tickets';
            } else if (referrer.includes('/help-desk/admin/tickets-list')) {
                backUrl = '/help-desk/admin/tickets-list';
                backText = 'Lista de Tickets';
            } else if (referrer.includes('/help-desk/department')) {
                backUrl = '/help-desk/department/tickets';
                backText = 'Departamento';
            } else if (referrer.includes('/help-desk/admin/assign-tickets')) {
                backUrl = '/help-desk/admin/assign-tickets';
                backText = 'Administración';
            } else if (referrer.includes('/help-desk/secretary/')) {
                backUrl = '/help-desk/secretary/dashboard';
                backText = 'Dashboard Secretaría';
            } else if (referrer.includes('/help-desk')) {
                backText = 'Volver';
                backUrl = referrer;
            }
        }

        // Fallback: sessionStorage
        if (!fromParam && !referrer) {
            try {
                const lastPage = JSON.parse(sessionStorage.getItem('helpdesk_last_page') || '{}');
                if (lastPage.url && lastPage.text) {
                    backUrl = lastPage.url;
                    backText = lastPage.text;
                }
            } catch (e) {
                // Ignorar errores de JSON parsing
            }
        }

        if (backUrl && (backUrl.includes('/help-desk/') || fromParam || (referrer && referrer.includes('/help-desk/')))) {
            backButton.href = backUrl;
            if (backButtonText) backButtonText.textContent = backText;
            backButton.style.display = 'inline-block';

            sessionStorage.setItem('helpdesk_last_page', JSON.stringify({
                url: backUrl,
                text: backText
            }));
        } else {
            backButton.style.display = 'none';
        }
    }

    // ==================== LOAD TICKET DETAIL ====================
    async function loadTicketDetail() {
        showState('loading');

        try {
            const urlParams = new URLSearchParams(window.location.search);
            const isTutorialParam = urlParams.get('tutorial') === 'true';

            console.log('🎫 [ticket_detail] Cargando ticket...');
            console.log('🎫 Parámetro tutorial en URL:', isTutorialParam);
            console.log('🎫 Ticket ID:', ticketId);

            const isTutorialMode = isTutorialParam || (typeof window.isTutorialModeActive === 'function' && window.isTutorialModeActive());

            if (isTutorialMode) {
                console.log('🎫 Modo tutorial detectado');
                const tutorialTicketId = window.getTutorialTicketId();
                console.log('🎫 Tutorial ticket ID esperado:', tutorialTicketId);

                if (tutorialTicketId && ticketId == tutorialTicketId) {
                    console.log('🎫 Cargando desde JSON (modo tutorial)');
                    const tutorialData = window.getTutorialTicketData();

                    if (tutorialData) {
                        console.log('🎫 Datos del tutorial cargados correctamente');
                        currentTicket = tutorialData.ticket;
                        const comments = tutorialData.comments || [];

                        renderTicketDetail(currentTicket);
                        renderComments(comments);
                        renderStatusTimeline(currentTicket);
                        renderAssignmentInfo(currentTicket);
                        renderActionButtons(currentTicket);

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

            console.log('🎫 Cargando desde la BD (modo normal)');
            const ticketResponse = await HelpdeskUtils.api.getTicket(ticketId);
            currentTicket = ticketResponse.ticket;

            if (typeof currentUserId !== 'undefined' && currentTicket.assigned_to) {
                window.isAssignedToCurrentUser = currentTicket.assigned_to.id === currentUserId;
                console.log('👤 Usuario actual:', currentUserId, '| Técnico asignado:', currentTicket.assigned_to.id, '| ¿Es el mismo?:', window.isAssignedToCurrentUser);
            } else {
                window.isAssignedToCurrentUser = false;
                console.log('👤 No se pudo verificar asignación (currentUserId no definido o sin técnico asignado)');
            }

            const commentsResponse = await HelpdeskUtils.api.getComments(ticketId);
            const comments = commentsResponse.comments || [];

            renderTicketDetail(currentTicket);
            renderComments(comments);
            renderStatusTimeline(currentTicket);
            renderAssignmentInfo(currentTicket);
            renderActionButtons(currentTicket);

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
        document.getElementById('ticketNumber').innerHTML = `
            <i class="fas fa-ticket-alt me-2 text-primary"></i>${ticket.ticket_number}
        `;

        document.getElementById('ticketTitle').textContent = ticket.title;

        document.getElementById('ticketBadges').innerHTML = `
            ${HelpdeskUtils.getStatusBadge(ticket.status)}
            ${HelpdeskUtils.getAreaBadge(ticket.area)}
            ${HelpdeskUtils.getPriorityBadge(ticket.priority)}
            ${ticket.category ? `<span class="badge bg-secondary">${ticket.category.name}</span>` : ''}
        `;

        renderRequesterInfo(ticket);

        document.getElementById('ticketCreated').textContent = HelpdeskUtils.formatDate(ticket.created_at);
        document.getElementById('ticketUpdated').textContent = HelpdeskUtils.formatTimeAgo(ticket.updated_at);

        if (ticket.location) {
            document.getElementById('locationContainer').style.display = '';
            document.getElementById('ticketLocation').textContent = ticket.location;
        }

        if (ticket.office_document_folio) {
            document.getElementById('folioContainer').style.display = '';
            document.getElementById('ticketFolio').textContent = ticket.office_document_folio;
        }

        document.getElementById('ticketDescription').textContent = ticket.description;

        renderCustomFields(ticket);

        if (ticket.resolution_notes) {
            document.getElementById('resolutionContainer').classList.remove('d-none');
            document.getElementById('resolutionNotesDisplay').textContent = ticket.resolution_notes;
            document.getElementById('resolvedBy').textContent = ticket.resolved_by?.full_name || 'N/A';
            document.getElementById('resolvedAt').textContent = HelpdeskUtils.formatDate(ticket.resolved_at);
        }

        if (ticket.materials_used && ticket.materials_used.length > 0) {
            document.getElementById('materialsUsedContainer').classList.remove('d-none');
            document.getElementById('materialsUsedList').innerHTML = ticket.materials_used.map(m => `
                <tr>
                    <td><code class="small">${m.product_code || '—'}</code></td>
                    <td class="small">${m.product_name || '—'}</td>
                    <td class="small text-end">${m.quantity_used} ${m.unit_of_measure || ''}</td>
                </tr>`).join('');
        }

        if (ticket.collaborators && ticket.collaborators.length > 0) {
            document.getElementById('collaboratorsContainer').classList.remove('d-none');
            document.getElementById('ticketCollaborators').innerHTML = HelpdeskUtils.renderCollaborators(ticket.collaborators);
        }

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
            renderEquipmentInfo(ticket.inventory_items);
        } else if (ticket.inventory_item) {
            renderEquipmentInfo(ticket.inventory_item);
        }

        renderQuickActions(ticket);

        const isOpen = !['CLOSED', 'CANCELED'].includes(ticket.status);
        document.getElementById('addCommentForm').classList.toggle('d-none', !isOpen);
    }

    // ==================== RENDER REQUESTER INFO ====================
    function renderRequesterInfo(ticket) {
        const requester = ticket.requester;
        const department = ticket.requester_department || ticket.department || requester?.department;

        const avatarEl = document.getElementById('requesterAvatar');
        if (requester && requester.name) {
            avatarEl.innerHTML = getInitials(requester.name);
        } else {
            avatarEl.innerHTML = '<i class="fas fa-user"></i>';
        }

        const nameEl = document.getElementById('requesterName');
        nameEl.textContent = requester?.name || requester?.full_name || 'Usuario desconocido';

        const emailEl = document.getElementById('requesterEmail');
        emailEl.textContent = requester?.email || 'Sin correo';

        const deptEl = document.getElementById('requesterDepartment');
        const deptTextEl = document.getElementById('requesterDepartmentText');
        if (department) {
            const deptName = typeof department === 'object' ? department.name : department;
            if (deptName) {
                deptTextEl.textContent = deptName;
                deptEl.style.display = 'inline-flex';
            } else {
                deptTextEl.textContent = 'Sin departamento';
                deptEl.style.display = 'inline-flex';
            }
        } else {
            deptTextEl.textContent = 'Sin departamento';
            deptEl.style.display = 'inline-flex';
        }
    }

    function getInitials(name) {
        if (!name) return '?';
        const parts = name.trim().split(' ');
        if (parts.length >= 2) {
            return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
        }
        return name.substring(0, 2).toUpperCase();
    }

    function renderQuickActions(ticket) {
        const menu = document.getElementById('quickActions');
        let html = '';

        html += `
            <li>
                <a class="dropdown-item" href="#" onclick="loadTicketDetail(); return false;">
                    <i class="fas fa-sync me-2"></i>Actualizar
                </a>
            </li>
        `;

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

        if (!ticket.custom_fields || Object.keys(ticket.custom_fields).length === 0) {
            container.classList.add('d-none');
            return;
        }

        const categoryId = ticket.category_id || ticket.category?.id;
        if (!categoryId) {
            container.classList.add('d-none');
            return;
        }

        try {
            const response = await HelpdeskUtils.api.request(`/categories/${categoryId}/field-template`);
            const fieldTemplate = response.field_template;

            if (!fieldTemplate || !fieldTemplate.enabled) {
                container.classList.add('d-none');
                return;
            }

            const fields = fieldTemplate.fields || [];
            let html = '';

            fields.forEach(field => {
                const value = ticket.custom_fields[field.key];

                if (value === undefined || value === null) {
                    return;
                }

                let displayValue = '';

                if (field.type === 'checkbox') {
                    displayValue = value ? '<span class="badge bg-success">Sí</span>' : '<span class="badge bg-secondary">No</span>';
                } else if (field.type === 'select' || field.type === 'radio') {
                    const option = field.options?.find(opt => opt.value === value);
                    displayValue = option ? option.label : value;
                } else if (field.type === 'file') {
                    if (typeof value === 'string' && (value.startsWith('/instance/') || value.includes('/'))) {
                        const filename = value.split('/').pop();
                        const fileExt = filename.split('.').pop().toLowerCase();
                        const imageExtensions = ['jpg', 'jpeg', 'png', 'gif', 'webp'];
                        const isImage = imageExtensions.includes(fileExt);

                        const downloadUrl = `/api/help-desk/v2/attachments/custom-field/${ticket.id}/${field.key}`;

                        if (isImage) {
                            displayValue = `
                                <div class="d-flex align-items-center gap-2">
                                    <i class="fas fa-image text-primary"></i>
                                    <span class="me-2">${filename}</span>
                                    <button type="button"
                                            class="btn btn-sm btn-outline-primary"
                                            onclick="downloadCustomFieldFile('${downloadUrl}', '${filename}')"
                                            title="Descargar foto">
                                        <i class="fas fa-download me-1"></i>Descargar
                                    </button>
                                </div>
                            `;
                        } else {
                            displayValue = `
                                <button type="button"
                                        class="btn btn-sm btn-link text-decoration-none p-0"
                                        onclick="downloadCustomFieldFile('${downloadUrl}', '${filename}')">
                                    <i class="fas fa-file me-1"></i>${filename}
                                </button>
                            `;
                        }
                    } else {
                        displayValue = `<i class="fas fa-file me-1"></i>${value}`;
                    }
                } else {
                    displayValue = value;
                }

                const colClass = field.type === 'file' ? 'col-md-12' : 'col-md-6';

                html += `
                    <div class="${colClass} mb-3">
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

        container.innerHTML = comments.map(comment => {
            let attachmentsHtml = '';
            if (comment.attachments && comment.attachments.length > 0) {
                const items = comment.attachments.map(att => {
                    const isImage = att.mime_type && att.mime_type.startsWith('image/');
                    const downloadUrl = `/api/help-desk/v2/attachments/${att.id}/download`;
                    if (isImage) {
                        return `<img src="${downloadUrl}" alt="${att.original_filename}" class="comment-attachment-thumb rounded"
                            style="max-width:80px;max-height:80px;cursor:pointer;object-fit:cover;"
                            onclick="viewAttachmentImage('${downloadUrl}', '${att.original_filename}')">`;
                    }
                    return `<a href="${downloadUrl}" class="btn btn-sm btn-outline-secondary" download="${att.original_filename}">
                        <i class="fas fa-file me-1"></i>${att.original_filename}
                    </a>`;
                }).join('');
                attachmentsHtml = `<div class="mt-2 d-flex flex-wrap gap-2">${items}</div>`;
            }
            return `
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
                    ${attachmentsHtml}
                </div>
            `;
        }).join('');
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
            if (commentPendingFiles.length > 0) {
                await HelpdeskUtils.api.addCommentWithFiles(ticketId, content, commentPendingFiles);
            } else {
                await HelpdeskUtils.api.addComment(ticketId, content);
            }

            HelpdeskUtils.showToast('Comentario agregado', 'success');
            textarea.value = '';
            commentPendingFiles = [];
            renderCommentFilesPreview();

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
        const isFailedResolution = ticket.status === 'RESOLVED_FAILED';

        const statusFlow = [
            { status: 'PENDING', label: 'Creado', icon: 'fa-plus-circle' },
            { status: 'ASSIGNED', label: 'Asignado', icon: 'fa-user-check' },
            { status: 'IN_PROGRESS', label: 'En Progreso', icon: 'fa-cog' },
            {
                status: isFailedResolution ? 'RESOLVED_FAILED' : 'RESOLVED_SUCCESS',
                label: isFailedResolution ? 'Atendido' : 'Resuelto',
                icon: 'fa-check-circle'
            },
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
                                ${isCurrent ? `<span class="badge bg-primary ms-2">Actual</span>` : ''}
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

        const isAssignedTechnician = window.isAssignedToCurrentUser || false;

        if (isAssignedTechnician) {
            if (ticket.status === 'ASSIGNED') {
                html += `
                    <button class="btn btn-primary btn-lg btn-action" onclick="startTicketWork()">
                        <i class="fas fa-play me-2"></i>Iniciar Trabajo
                    </button>
                `;
            }

            if (ticket.status === 'IN_PROGRESS') {
                html += `
                    <button class="btn btn-success btn-lg btn-action" onclick="openResolveModal()">
                        <i class="fas fa-check-circle me-2"></i>Resolver Ticket
                    </button>
                `;
            }
        }

        const isRequester = typeof currentUserId !== 'undefined' && ticket.requester && ticket.requester.id === currentUserId;
        const canRate = isRequester && ['RESOLVED_SUCCESS', 'RESOLVED_FAILED'].includes(ticket.status) && !ticket.rating_attention;
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

    // ==================== TECHNICIAN ACTIONS ====================
    function startTicketWork() {
        if (!currentTicket) return;

        document.getElementById('startWorkTicketInfo').innerHTML = `
            <div class="d-flex align-items-center">
                <div class="flex-grow-1">
                    <h6 class="mb-1">${currentTicket.ticket_number}</h6>
                    <p class="mb-1 text-truncate">${currentTicket.title}</p>
                    ${HelpdeskUtils.getPriorityBadge(currentTicket.priority)}
                </div>
            </div>
        `;

        const modal = new bootstrap.Modal(document.getElementById('startWorkModal'));
        modal.show();
    }

    async function confirmStartWork() {
        if (!currentTicket) return;

        const btn = document.getElementById('btnConfirmStart');
        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Iniciando...';

        try {
            HelpdeskUtils.showToast('Iniciando trabajo...', 'info');

            const response = await fetch(`/api/help-desk/v2/tickets/${currentTicket.id}/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || 'Error al iniciar trabajo');
            }

            HelpdeskUtils.showToast('¡Trabajo iniciado!', 'success');

            const modal = bootstrap.Modal.getInstance(document.getElementById('startWorkModal'));
            modal.hide();

            await loadTicketDetail();

        } catch (error) {
            console.error('Error starting work:', error);
            HelpdeskUtils.showToast(`Error: ${error.message}`, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    }

    function openResolveModal() {
        if (!currentTicket) return;

        document.getElementById('resolveTicketInfo').innerHTML = `
            <h6 class="mb-2">${currentTicket.ticket_number}: ${currentTicket.title}</h6>
            <div class="d-flex gap-2 mb-2">
                ${HelpdeskUtils.getStatusBadge(currentTicket.status)}
                ${HelpdeskUtils.getPriorityBadge(currentTicket.priority)}
            </div>
            <p class="mb-0 small text-muted">${currentTicket.description.substring(0, 200)}...</p>
        `;

        const refTitle = document.getElementById('resolveRefTitle');
        const refDesc = document.getElementById('resolveRefDesc');
        const refMeta = document.getElementById('resolveRefMeta');
        if (refTitle) refTitle.textContent = `${currentTicket.ticket_number}: ${currentTicket.title}`;
        if (refDesc) refDesc.textContent = currentTicket.description || '-';
        if (refMeta) refMeta.innerHTML = `
            ${HelpdeskUtils.getStatusBadge(currentTicket.status)}
            ${HelpdeskUtils.getPriorityBadge(currentTicket.priority)}
        `;

        const notesField = document.getElementById('resolutionNotes');
        notesField.value = '';
        notesField.classList.remove('is-invalid', 'is-valid');

        document.getElementById('resolutionSuccess').checked = true;
        document.getElementById('timeInvested').value = '';
        document.getElementById('timeUnit').value = 'minutes';

        updateNotesCounter();

        const btn = document.getElementById('btnConfirmResolve');
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-check-circle me-2"></i>Resolver Ticket';

        updateResolutionFilesCount(0);

        const isSoporte = currentTicket.area === 'SOPORTE';
        const soporteFields = document.getElementById('soporteOnlyFields');
        const observationsField = document.getElementById('observationsField');
        if (soporteFields) soporteFields.style.display = isSoporte ? '' : 'none';
        if (observationsField) observationsField.style.display = isSoporte ? '' : 'none';

        if (typeof window.TicketWarehouse !== 'undefined') window.TicketWarehouse.reset();

        loadAvailableTechnicians(currentTicket);

        document.getElementById('mainContent').classList.add('d-none');
        document.getElementById('resolvePanel').classList.remove('d-none');
        window.scrollTo(0, 0);
    }

    function closeResolvePanel() {
        document.getElementById('resolvePanel').classList.add('d-none');
        document.getElementById('mainContent').classList.remove('d-none');
        window.scrollTo(0, 0);
    }

    function updateNotesCounter() {
        const notesField = document.getElementById('resolutionNotes');
        const counter = document.getElementById('resolutionNotesCounter');

        if (!notesField || !counter) return;

        const length = notesField.value.trim().length;
        counter.textContent = `${length} / 10 caracteres mínimo`;

        if (length >= 10) {
            notesField.classList.remove('is-invalid');
            notesField.classList.add('is-valid');
            counter.classList.remove('text-danger');
            counter.classList.add('text-success');
        } else if (length > 0) {
            notesField.classList.remove('is-valid');
            notesField.classList.add('is-invalid');
            counter.classList.remove('text-success');
            counter.classList.add('text-danger');
        } else {
            notesField.classList.remove('is-invalid', 'is-valid');
            counter.classList.remove('text-success', 'text-danger');
        }
    }

    async function loadAvailableTechnicians(ticket) {
        const container = document.getElementById('collaboratorsList');

        container.innerHTML = `
            <div class="text-center text-muted py-2">
                <span class="spinner-border spinner-border-sm me-2"></span>
                Cargando técnicos...
            </div>
        `;

        try {
            const response = await fetch(`/api/help-desk/v2/assignments/technicians/${ticket.area}`);

            if (!response.ok) {
                throw new Error('Error al cargar técnicos');
            }

            const data = await response.json();
            const technicians = data.technicians || [];

            if (technicians.length === 0) {
                container.innerHTML = `
                    <div class="text-center text-muted py-2">
                        <i class="fas fa-users-slash me-2"></i>
                        No hay técnicos disponibles
                    </div>
                `;
                return;
            }

            container.innerHTML = technicians.map(tech => {
                const isAssigned = ticket.assigned_to && tech.id === ticket.assigned_to.id;

                return `
                    <div class="form-check mb-2">
                        <input class="form-check-input collaborator-check"
                               type="checkbox"
                               value="${tech.id}"
                               id="collab_${tech.id}"
                               ${isAssigned ? 'checked disabled' : ''}>
                        <label class="form-check-label d-flex justify-content-between align-items-center w-100"
                               for="collab_${tech.id}">
                            <span>
                                ${tech.name}
                                ${isAssigned ? '<span class="badge bg-primary ms-2">Asignado</span>' : ''}
                            </span>
                            <small class="text-muted">${tech.active_tickets} activos</small>
                        </label>
                    </div>
                `;
            }).join('');

        } catch (error) {
            console.error('Error loading technicians:', error);
            container.innerHTML = `
                <div class="text-center text-danger py-2">
                    <i class="fas fa-exclamation-triangle me-2"></i>
                    <small>Error al cargar técnicos</small>
                </div>
            `;
        }
    }

    async function confirmResolve() {
        if (!currentTicket) return;

        const isSoporte = currentTicket.area === 'SOPORTE';
        const resolutionType = document.querySelector('input[name="resolutionType"]:checked')?.value;
        const notesField = document.getElementById('resolutionNotes');
        const notes = notesField ? notesField.value.trim() : '';
        const maintenanceType = isSoporte ? document.querySelector('input[name="maintenanceType"]:checked')?.value : null;
        const serviceOrigin = isSoporte ? document.querySelector('input[name="serviceOrigin"]:checked')?.value : null;
        const observations = isSoporte ? (document.getElementById('observations')?.value.trim() || null) : null;

        if (isSoporte) {
            if (!maintenanceType) {
                HelpdeskUtils.showToast('Debe seleccionar el tipo de mantenimiento', 'warning');
                return;
            }
            if (!serviceOrigin) {
                HelpdeskUtils.showToast('Debe seleccionar el origen del equipo', 'warning');
                return;
            }
        }

        if (!notes || notes.length < 10) {
            HelpdeskUtils.showToast('Las notas de resolución deben tener al menos 10 caracteres', 'warning');
            if (notesField) {
                notesField.focus();
                notesField.classList.add('is-invalid');
                notesField.classList.remove('is-valid');
                updateNotesCounter();
            }
            return;
        }

        if (notesField) {
            notesField.classList.remove('is-invalid');
            notesField.classList.add('is-valid');
        }

        const timeValue = parseFloat(document.getElementById('timeInvested')?.value) || null;
        const timeUnit = document.getElementById('timeUnit')?.value || 'minutes';
        let timeInvested = null;

        if (timeValue && timeValue > 0) {
            switch (timeUnit) {
                case 'minutes':
                    timeInvested = Math.round(timeValue);
                    break;
                case 'hours':
                    timeInvested = Math.round(timeValue * 60);
                    break;
                case 'days':
                    timeInvested = Math.round(timeValue * 8 * 60);
                    break;
                default:
                    timeInvested = Math.round(timeValue);
            }
        }

        if (!timeInvested || timeInvested <= 0) {
            HelpdeskUtils.showToast('El tiempo invertido es requerido', 'warning');
            document.getElementById('timeInvested').focus();
            return;
        }

        const btn = document.getElementById('btnConfirmResolve');
        const originalText = btn.innerHTML;

        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Resolviendo...';

        try {
            if (typeof window.TicketWarehouse !== 'undefined') {
                await window.TicketWarehouse.consumeAll(currentTicket.id);
            }

            await HelpdeskUtils.api.resolveTicket(currentTicket.id, {
                success: resolutionType === 'success',
                resolution_notes: notes,
                time_invested_minutes: timeInvested,
                maintenance_type: maintenanceType,
                service_origin: serviceOrigin,
                observations: observations
            });

            const selectedCollaborators = [];

            document.querySelectorAll('.collaborator-check:checked:not(:disabled)').forEach(checkbox => {
                selectedCollaborators.push({
                    user_id: parseInt(checkbox.value),
                    collaboration_role: 'COLLABORATOR',
                    time_invested_minutes: null,
                    notes: null
                });
            });

            if (currentTicket.assigned_to && currentTicket.assigned_to.id) {
                selectedCollaborators.push({
                    user_id: currentTicket.assigned_to.id,
                    collaboration_role: 'LEAD',
                    time_invested_minutes: timeInvested,
                    notes: notes
                });
            }

            if (selectedCollaborators.length > 0) {
                try {
                    const collabResponse = await fetch(
                        `/api/help-desk/v2/tickets/${currentTicket.id}/collaborators/batch`,
                        {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ collaborators: selectedCollaborators })
                        }
                    );

                    if (collabResponse.ok) {
                        const collabData = await collabResponse.json();
                        console.log(`${collabData.count} colaboradores agregados`);
                    } else {
                        console.warn('No se pudieron agregar algunos colaboradores');
                    }
                } catch (collabError) {
                    console.error('Error adding collaborators:', collabError);
                }
            }

            HelpdeskUtils.showToast(
                resolutionType === 'success'
                    ? '¡Ticket resuelto exitosamente!'
                    : 'Ticket marcado como atendido',
                'success'
            );

            closeResolvePanel();
            await loadTicketDetail();

        } catch (error) {
            console.error('Error resolving ticket:', error);
            const errorMessage = error.message || 'Error desconocido';
            HelpdeskUtils.showToast(`Error al resolver ticket: ${errorMessage}`, 'error');

            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }

    // ==================== RATING MODAL ====================
    function setupRatingModal() {
        document.querySelectorAll('.star-btn-attention').forEach(btn => {
            btn.addEventListener('click', () => {
                currentRatingAttention = parseInt(btn.dataset.rating);
                updateStarButtons();
            });
        });

        document.querySelectorAll('.star-btn-speed').forEach(btn => {
            btn.addEventListener('click', () => {
                currentRatingSpeed = parseInt(btn.dataset.rating);
                updateStarButtons();
            });
        });

        document.querySelectorAll('input[name="ratingEfficiencyDetail"]').forEach(radio => {
            radio.addEventListener('change', () => {
                currentRatingEfficiency = radio.value === 'true';
                checkRatingFormValidity();
            });
        });

        const btnSubmitRating = document.getElementById('btnSubmitRating');
        if (btnSubmitRating) btnSubmitRating.addEventListener('click', submitRating);

        const btnConfirmResolve = document.getElementById('btnConfirmResolve');
        if (btnConfirmResolve) btnConfirmResolve.addEventListener('click', confirmResolve);

        const btnConfirmStart = document.getElementById('btnConfirmStart');
        if (btnConfirmStart) btnConfirmStart.addEventListener('click', confirmStartWork);

        const resolutionNotes = document.getElementById('resolutionNotes');
        if (resolutionNotes) {
            resolutionNotes.addEventListener('input', updateNotesCounter);
            resolutionNotes.addEventListener('blur', updateNotesCounter);
        }
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

        document.querySelectorAll('input[name="ratingEfficiencyDetail"]').forEach(radio => {
            radio.checked = false;
        });

        document.getElementById('btnSubmitRating').disabled = true;

        const modal = new bootstrap.Modal(document.getElementById('ratingModal'));
        modal.show();
    }

    function updateStarButtons() {
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
            await HelpdeskUtils.api.rateTicket(ticketId, {
                rating_attention: currentRatingAttention,
                rating_speed: currentRatingSpeed,
                rating_efficiency: currentRatingEfficiency,
                comment: document.getElementById('ratingCommentInput').value.trim() || null
            });

            HelpdeskUtils.showToast('¡Gracias por tu evaluación!', 'success');

            const modal = bootstrap.Modal.getInstance(document.getElementById('ratingModal'));
            modal.hide();

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
        const btnConfirmCancel = document.getElementById('btnConfirmCancel');
        if (btnConfirmCancel) btnConfirmCancel.addEventListener('click', confirmCancel);
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

            await loadTicketDetail();

        } catch (error) {
            console.error('Error canceling ticket:', error);
            const errorMessage = error.message || 'Error desconocido';
            HelpdeskUtils.showToast(`Error al cancelar ticket: ${errorMessage}`, 'error');

            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }

    // ==================== EQUIPMENT INFO ====================
    async function renderEquipmentInfo(equipmentData) {
        const container = document.getElementById('equipmentInfo');
        const card = document.getElementById('equipmentCard');

        if (!equipmentData || (Array.isArray(equipmentData) && equipmentData.length === 0)) {
            card.style.display = 'none';
            return;
        }

        card.style.display = 'block';

        const isMultiple = Array.isArray(equipmentData) && equipmentData.length > 1;

        if (isMultiple) {
            renderMultipleEquipmentPreview(equipmentData, container);
        } else {
            const item = Array.isArray(equipmentData) ? equipmentData[0] : equipmentData;
            renderSingleEquipmentPreview(item, container);
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
        renderEquipmentModalList(currentTicket.inventory_items);
        modal.show();
    }

    function openEquipmentDetail(itemId) {
        if (!itemId) {
            console.error('Equipment ID is required');
            return;
        }
        window.location.href = `/help-desk/inventory/items/${itemId}`;
    }

    function renderEquipmentModalList(equipmentList) {
        const listContainer = document.getElementById('equipment-modal-list');
        const groupInfoContainer = document.getElementById('equipment-modal-group-info');

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
                                ${equipment.supplier_serial ? `
                                    <span class="badge bg-light text-dark">
                                        <i class="fas fa-barcode me-1"></i>${equipment.supplier_serial}
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
            const response = await HelpdeskUtils.api.getAttachmentsByType(ticketId, 'ticket');
            const attachments = response.attachments || [];

            if (attachments.length > 0) {
                const photo = attachments[0];
                document.getElementById('photoContainer').style.display = 'block';
                renderPhotoThumbnail(photo);
            }

        } catch (error) {
            console.error('Error loading photo:', error);
        }

        if (currentTicket && currentTicket.resolution_notes) {
            await loadResolutionAttachments(ticketId);
        }
    }

    async function loadResolutionAttachments(ticketId) {
        try {
            const response = await HelpdeskUtils.api.getAttachmentsByType(ticketId, 'resolution');
            const attachments = response.attachments || [];

            const container = document.getElementById('resolutionAttachmentsDisplay');
            const list = document.getElementById('resolutionAttachmentsList');

            if (attachments.length === 0) {
                container.classList.add('d-none');
                return;
            }

            container.classList.remove('d-none');
            list.innerHTML = attachments.map(att => {
                const isImage = att.mime_type && att.mime_type.startsWith('image/');
                const downloadUrl = `/api/help-desk/v2/attachments/${att.id}/download`;

                if (isImage) {
                    return `
                        <div class="border rounded p-2 text-center" style="width:100px;">
                            <img src="${downloadUrl}" alt="${att.original_filename}" class="rounded"
                                style="max-width:80px;max-height:80px;cursor:pointer;object-fit:cover;"
                                onclick="viewAttachmentImage('${downloadUrl}', '${att.original_filename}')">
                            <small class="d-block text-truncate mt-1" title="${att.original_filename}">${att.original_filename}</small>
                        </div>`;
                }

                const icon = getFileIcon(att.original_filename);
                return `
                    <a href="${downloadUrl}" class="btn btn-sm btn-outline-secondary d-flex align-items-center gap-2" download="${att.original_filename}">
                        <i class="${icon}"></i>
                        <span class="text-truncate" style="max-width:200px;">${att.original_filename}</span>
                        <small class="text-muted">(${formatFileSize(att.file_size)})</small>
                    </a>`;
            }).join('');

        } catch (error) {
            console.error('Error loading resolution attachments:', error);
        }
    }

    function renderPhotoThumbnail(photo) {
        const container = document.getElementById('photoThumbnail');

        const fileUrl = `/api/help-desk/v2/attachments/${photo.id}/download`;
        const isImage = photo.mime_type && photo.mime_type.startsWith('image/');
        const uploaded = `<i class="fas fa-clock me-1"></i>Subida ${HelpdeskUtils.formatTimeAgo(photo.uploaded_at)}`;

        const title = document.getElementById('photoSectionTitle');
        if (title) {
            title.innerHTML = isImage
                ? '<i class="fas fa-camera me-2 text-primary"></i>Foto de la solicitud'
                : '<i class="fas fa-paperclip me-2 text-primary"></i>Archivo de la solicitud';
        }

        if (isImage) {
            container.innerHTML = `
                <div class="photo-thumbnail" onclick="openPhotoModal('${fileUrl}')">
                    <img src="${fileUrl}" alt="Foto del problema" class="img-thumbnail">
                    <div class="photo-overlay">
                        <i class="fas fa-search-plus fa-2x"></i>
                    </div>
                </div>
                <div class="mt-2">
                    <small class="text-muted">${uploaded}</small>
                </div>
            `;
            return;
        }

        const icon = getFileIcon(photo.original_filename);
        const size = photo.file_size ? formatFileSize(photo.file_size) : '';
        container.innerHTML = `
            <div class="border rounded p-3 d-flex align-items-center gap-3">
                <i class="${icon} fa-2x text-secondary"></i>
                <div class="flex-grow-1" style="min-width:0;">
                    <div class="fw-semibold text-truncate" title="${photo.original_filename}">${photo.original_filename}</div>
                    <small class="text-muted">${size ? size + ' · ' : ''}${uploaded}</small>
                </div>
                <a href="${fileUrl}" download="${photo.original_filename}" class="btn btn-sm btn-outline-primary">
                    <i class="fas fa-download me-1"></i>Descargar
                </a>
            </div>
        `;
    }

    function openPhotoModal(photoUrl) {
        const modal = new bootstrap.Modal(document.getElementById('photoModal'));
        document.getElementById('photoModalImage').src = photoUrl;
        modal.show();
    }

    // ==================== DOWNLOAD CUSTOM FIELD FILE ====================
    async function downloadCustomFieldFile(downloadUrl, filename) {
        console.log(`📥 Intentando descargar: ${filename}`);

        try {
            const response = await fetch(downloadUrl);

            if (!response.ok) {
                let errorMessage = 'El archivo no existe o no está disponible en el servidor';

                try {
                    const errorData = await response.json();
                    if (errorData.message) {
                        errorMessage = errorData.message;
                    }
                } catch (e) {
                    // No se pudo parsear el JSON
                }

                HelpdeskUtils.showToast(errorMessage, 'warning');
                console.warn(`⚠️ Error al descargar ${filename}:`, errorMessage);
                return;
            }

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();

            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            console.log(`✅ Archivo descargado: ${filename}`);
            HelpdeskUtils.showToast('Archivo descargado exitosamente', 'success');

        } catch (error) {
            console.error('❌ Error al descargar archivo:', error);
            HelpdeskUtils.showToast(
                'Error al descargar el archivo. Por favor, intenta nuevamente.',
                'error'
            );
        }
    }

    // ==================== WEBSOCKET REAL-TIME UPDATES ====================
    function setupWebSocketListeners() {
        _socketPoller = setInterval(() => {
            if (window.__helpdeskSocket) {
                clearInterval(_socketPoller);
                _socketPoller = null;
                bindTicketSocketEvents();
            }
        }, 100);

        // Safety timeout: stop polling after 5s
        setTimeout(() => {
            if (_socketPoller) {
                clearInterval(_socketPoller);
                _socketPoller = null;
            }
        }, 5000);
    }

    function bindTicketSocketEvents() {
        if (ticketSocketBound) return;

        const socket = window.__helpdeskSocket;
        if (!socket || !ticketId) return;

        // Join realtime room
        window.__hdJoinTicket?.(ticketId);

        // Remove any stale listeners
        socket.off('ticket_status_changed');
        socket.off('ticket_comment_added');
        socket.off('ticket_assigned');
        socket.off('ticket_reassigned');

        socket.on('ticket_status_changed', (data) => {
            if (data.ticket_id == ticketId) {
                console.log('[Ticket Detail] ticket_status_changed:', data);
                HelpdeskUtils.showToast('El estado del ticket ha cambiado', 'info');
                loadTicketDetail();
            }
        });

        socket.on('ticket_comment_added', async (data) => {
            if (data.ticket_id == ticketId) {
                console.log('[Ticket Detail] ticket_comment_added:', data);
                HelpdeskUtils.showToast(`Nuevo comentario de ${data.author_name}`, 'info');
                try {
                    const commentsResponse = await HelpdeskUtils.api.getComments(ticketId);
                    renderComments(commentsResponse.comments || []);
                } catch (e) {
                    console.error('Error recargando comentarios:', e);
                }
            }
        });

        socket.on('ticket_assigned', (data) => {
            if (data.ticket_id == ticketId) {
                console.log('[Ticket Detail] ticket_assigned:', data);
                HelpdeskUtils.showToast(`Ticket asignado a ${data.assigned_to_name}`, 'info');
                loadTicketDetail();
            }
        });

        socket.on('ticket_reassigned', (data) => {
            if (data.ticket_id == ticketId) {
                console.log('[Ticket Detail] ticket_reassigned:', data);
                HelpdeskUtils.showToast(`Ticket reasignado a ${data.new_assigned_name}`, 'info');
                loadTicketDetail();
            }
        });

        ticketSocketBound = true;
        console.log('[Ticket Detail] WebSocket listeners configurados para ticket:', ticketId);
    }

    // ==================== FILE HELPERS ====================
    function getFileIcon(filename) {
        const ext = filename.split('.').pop().toLowerCase();
        const icons = {
            pdf: 'fas fa-file-pdf text-danger',
            xlsx: 'fas fa-file-excel text-success',
            xls: 'fas fa-file-excel text-success',
            csv: 'fas fa-file-csv text-success',
            doc: 'fas fa-file-word text-primary',
            docx: 'fas fa-file-word text-primary',
        };
        return icons[ext] || 'fas fa-file text-secondary';
    }

    function formatFileSize(bytes) {
        if (!bytes) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    // ==================== COMMENT FILES ====================
    function setupCommentFileInput() {
        const input = document.getElementById('commentFileInput');
        if (!input) return;
        input.addEventListener('change', function () {
            const maxFiles = 3;
            const newFiles = Array.from(this.files);
            const remaining = maxFiles - commentPendingFiles.length;

            if (newFiles.length > remaining) {
                HelpdeskUtils.showToast(`Solo puedes adjuntar ${maxFiles} archivos por comentario`, 'warning');
            }

            for (let i = 0; i < Math.min(newFiles.length, remaining); i++) {
                commentPendingFiles.push(newFiles[i]);
            }

            renderCommentFilesPreview();
            this.value = '';
        });
    }

    function renderCommentFilesPreview() {
        const container = document.getElementById('commentFilesPreview');
        if (!container) return;

        if (commentPendingFiles.length === 0) {
            container.classList.add('d-none');
            container.innerHTML = '';
            return;
        }

        container.classList.remove('d-none');
        container.innerHTML = commentPendingFiles.map((file, idx) => {
            const icon = file.type.startsWith('image/') ? 'fas fa-image' : getFileIcon(file.name);
            return `
                <span class="badge bg-light text-dark border d-flex align-items-center gap-1 py-1 px-2">
                    <i class="${icon} me-1"></i>
                    <span class="text-truncate" style="max-width:120px;">${file.name}</span>
                    <button type="button" class="btn-close btn-close-sm ms-1" style="font-size:0.6em;"
                        onclick="removeCommentFile(${idx})"></button>
                </span>`;
        }).join('');
    }

    function removeCommentFile(index) {
        commentPendingFiles.splice(index, 1);
        renderCommentFilesPreview();
    }

    // ==================== RESOLUTION FILES MODAL ====================
    function openResolutionFilesModal() {
        if (!currentTicket) return;

        const modal = new bootstrap.Modal(document.getElementById('resolutionFilesModal'));
        loadResolutionFiles();
        setupResolutionDropzone();
        modal.show();
    }

    let resDropzoneSetup = false;

    function setupResolutionDropzone() {
        if (resDropzoneSetup) return;
        resDropzoneSetup = true;

        const dropzone = document.getElementById('resolutionDropzone');
        const input = document.getElementById('resolutionFileInput');

        dropzone.addEventListener('click', () => input.click());

        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.style.borderColor = '#0d6efd';
            dropzone.style.backgroundColor = '#f0f7ff';
        });

        dropzone.addEventListener('dragleave', () => {
            dropzone.style.borderColor = '#dee2e6';
            dropzone.style.backgroundColor = '';
        });

        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.style.borderColor = '#dee2e6';
            dropzone.style.backgroundColor = '';
            const files = Array.from(e.dataTransfer.files);
            uploadResolutionFiles(files);
        });

        input.addEventListener('change', function () {
            uploadResolutionFiles(Array.from(this.files));
            this.value = '';
        });
    }

    async function loadResolutionFiles() {
        if (!currentTicket) return;

        try {
            const response = await HelpdeskUtils.api.getAttachmentsByType(currentTicket.id, 'resolution');
            const attachments = response.attachments || [];
            renderResolutionFilesList(attachments);
            updateResolutionFilesCount(attachments.length);
        } catch (error) {
            console.error('Error loading resolution files:', error);
        }
    }

    function renderResolutionFilesList(attachments) {
        const container = document.getElementById('resolutionFilesList');

        if (attachments.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-3">
                    <i class="fas fa-folder-open fa-2x mb-2"></i>
                    <p class="mb-0">Sin archivos adjuntos</p>
                </div>`;
            return;
        }

        container.innerHTML = attachments.map(att => {
            const isImage = att.mime_type && att.mime_type.startsWith('image/');
            const downloadUrl = `/api/help-desk/v2/attachments/${att.id}/download`;
            const icon = isImage ? 'fas fa-image text-info' : getFileIcon(att.original_filename);

            return `
                <div class="d-flex align-items-center justify-content-between border rounded p-2 mb-2">
                    <div class="d-flex align-items-center gap-2 flex-grow-1 min-width-0">
                        ${isImage ? `<img src="${downloadUrl}" class="rounded" style="width:40px;height:40px;object-fit:cover;cursor:pointer;"
                            onclick="viewAttachmentImage('${downloadUrl}', '${att.original_filename}')">` :
                `<i class="${icon} fa-lg"></i>`}
                        <div class="min-width-0">
                            <div class="text-truncate fw-semibold" style="max-width:300px;" title="${att.original_filename}">${att.original_filename}</div>
                            <small class="text-muted">${formatFileSize(att.file_size)} - ${HelpdeskUtils.formatTimeAgo(att.uploaded_at)}</small>
                        </div>
                    </div>
                    <div class="d-flex gap-1 flex-shrink-0">
                        <a href="${downloadUrl}" class="btn btn-sm btn-outline-primary" download="${att.original_filename}" title="Descargar">
                            <i class="fas fa-download"></i>
                        </a>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteResolutionFile(${att.id})" title="Eliminar">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>`;
        }).join('');
    }

    function updateResolutionFilesCount(count) {
        const badge = document.getElementById('resolutionFilesCount');
        if (badge) badge.textContent = count;

        const modalCount = document.getElementById('resFilesModalCount');
        if (modalCount) modalCount.textContent = `${count} / 10`;
    }

    async function uploadResolutionFiles(files) {
        if (!currentTicket || !files.length) return;

        const progressContainer = document.getElementById('resUploadProgress');
        const progressBar = document.getElementById('resUploadBar');
        const progressText = document.getElementById('resUploadText');

        progressContainer.classList.remove('d-none');
        let uploaded = 0;

        for (const file of files) {
            progressText.textContent = `Subiendo ${file.name}...`;
            progressBar.style.width = `${(uploaded / files.length) * 100}%`;

            try {
                await HelpdeskUtils.api.uploadFile(currentTicket.id, file, 'resolution');
                uploaded++;
            } catch (error) {
                HelpdeskUtils.showToast(`Error al subir ${file.name}: ${error.message}`, 'error');
            }
        }

        progressBar.style.width = '100%';
        progressText.textContent = `${uploaded} de ${files.length} archivos subidos`;

        setTimeout(() => {
            progressContainer.classList.add('d-none');
            progressBar.style.width = '0%';
        }, 1500);

        if (uploaded > 0) {
            HelpdeskUtils.showToast(`${uploaded} archivo(s) subido(s)`, 'success');
        }

        loadResolutionFiles();
    }

    async function deleteResolutionFile(attachmentId) {
        const confirmed = await HelpdeskUtils.confirmDialog(
            'Eliminar archivo',
            '¿Estás seguro de eliminar este archivo?',
            'Eliminar',
            'Cancelar'
        );

        if (!confirmed) return;

        try {
            await HelpdeskUtils.api.deleteAttachment(attachmentId);
            HelpdeskUtils.showToast('Archivo eliminado', 'success');
            loadResolutionFiles();
        } catch (error) {
            HelpdeskUtils.showToast(`Error al eliminar: ${error.message}`, 'error');
        }
    }

    // ==================== ATTACHMENT IMAGE VIEWER ====================
    function viewAttachmentImage(url, title) {
        const modal = new bootstrap.Modal(document.getElementById('attachmentImageModal'));
        document.getElementById('attachmentImageModalImg').src = url;
        document.getElementById('attachmentImageTitle').innerHTML = `<i class="fas fa-image me-2"></i>${title || 'Imagen'}`;
        modal.show();
    }

    // ==================== REGISTER WITH CONTROLLER ====================
    window.HelpdeskPage.page('user_ticket_detail', { init, destroy });

})();
