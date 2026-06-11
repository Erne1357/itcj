/**
 * ticket-detail.js — Controlador principal del detalle de ticket
 * Depende de: ticket-assignment.js, ticket-resolution.js
 */
'use strict';

(function () {

    var API_BASE = '/api/maint/v2';
    var ctx = window.TICKET_CTX || {};
    var _ticket = null;
    var _activeTab = 'info';

    var STATUS_LABEL = {
        PENDING: 'Pendiente', ASSIGNED: 'Asignado', IN_PROGRESS: 'En Progreso',
        RESOLVED_SUCCESS: 'Resuelto', RESOLVED_FAILED: 'Atendido',
        CLOSED: 'Cerrado', CANCELED: 'Cancelado',
    };
    var STATUS_CSS = {
        PENDING: 'mn-status-pending', ASSIGNED: 'mn-status-assigned',
        IN_PROGRESS: 'mn-status-in-progress', RESOLVED_SUCCESS: 'mn-status-resolved-ok',
        RESOLVED_FAILED: 'mn-status-resolved-fail', CLOSED: 'mn-status-closed',
        CANCELED: 'mn-status-canceled',
    };
    var PRIORITY_CSS = {
        BAJA: 'mn-priority-baja', MEDIA: 'mn-priority-media',
        ALTA: 'mn-priority-alta', URGENTE: 'mn-priority-urgente',
    };
    var PRIORITY_LABEL = { BAJA: 'Baja', MEDIA: 'Media', ALTA: 'Alta', URGENTE: 'Urgente' };

    // Formatea minutos a "Xd Yh Zmin" (omite unidades en cero)
    function _fmtDuration(mins) {
        if (mins === null || mins === undefined || mins === '') return '—';
        var m = parseInt(mins, 10);
        if (isNaN(m) || m < 1) return '—';
        var days = Math.floor(m / 1440);
        var hours = Math.floor((m % 1440) / 60);
        var rem = m % 60;
        var parts = [];
        if (days) parts.push(days + 'd');
        if (hours) parts.push(hours + 'h');
        if (rem || !parts.length) parts.push(rem + ' min');
        return parts.join(' ');
    }

    // ── Init ──────────────────────────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', function () {
        _bindTabs();
        _loadTicket();
    });

    function _loadTicket() {
        MaintUtils.api.fetch(API_BASE + '/tickets/' + ctx.ticketId)
            .then(function (data) {
                _ticket = data;
                _renderHeader(data);
                _renderActionButtons(data);
                _renderTab(_activeTab);
            })
            .catch(function (err) {
                document.getElementById('tabContent').innerHTML =
                    '<div class="alert alert-danger"><i class="bi bi-exclamation-triangle me-2"></i>Error al cargar el ticket: ' + _esc(err.message) + '</div>';
            });
    }

    // ── Header ────────────────────────────────────────────────────────────────

    function _renderHeader(t) {
        var skel = document.getElementById('headerSkeleton');
        if (skel) skel.classList.add('d-none');
        var hc = document.getElementById('headerContent');
        hc.classList.remove('d-none');
        hc.classList.add('d-flex');
        hc.classList.add('mn-fade-in');

        document.getElementById('ticketNumber').textContent = t.ticket_number;
        var titleEl = document.getElementById('ticketTitle');
        titleEl.textContent = t.title;
        titleEl.classList.add('mn-fade-in-up');

        // Animar la barra de progreso desde el ancho actual al objetivo
        var pb = document.getElementById('progressBar');
        var target = (t.progress_pct || 0);
        // CSS .mn-progress-fill ya tiene transition: width 0.4s
        requestAnimationFrame(function () { pb.style.width = target + '%'; });

        var sBadge = document.getElementById('statusBadge');
        sBadge.textContent = STATUS_LABEL[t.status] || t.status;
        sBadge.className = 'mn-badge-status ' + (STATUS_CSS[t.status] || '');

        // Overdue badge
        var existingOverdue = document.getElementById('overdueBadge');
        if (existingOverdue) existingOverdue.remove();
        if (t.is_overdue) {
            var oBadge = document.createElement('span');
            oBadge.id = 'overdueBadge';
            oBadge.className = 'mn-badge-overdue';
            oBadge.innerHTML = '<i class="bi bi-exclamation-triangle-fill"></i>Vencido';
            sBadge.insertAdjacentElement('afterend', oBadge);
        }

        var pBadge = document.getElementById('priorityBadge');
        pBadge.textContent = PRIORITY_LABEL[t.priority] || t.priority;
        pBadge.className = 'mn-badge-status ' + (PRIORITY_CSS[t.priority] || '');

        var catBadge = document.getElementById('categoryBadge');
        if (t.category) {
            catBadge.innerHTML = '<i class="bi ' + _esc(t.category.icon || 'bi-tools') + ' me-1"></i>' + _esc(t.category.name);
        }

        // Actualizar badge de técnicos y comentarios
        var activeTechs = (t.technicians || []).filter(function (tc) { return tc.is_active; });
        var techCount = document.getElementById('techCount');
        if (activeTechs.length > 0) { techCount.textContent = activeTechs.length; techCount.style.display = ''; }
        else { techCount.style.display = 'none'; }

        var commentCount = document.getElementById('commentCount');
        if (t.comments && t.comments.length > 0) { commentCount.textContent = t.comments.length; commentCount.style.display = ''; }
        else { commentCount.style.display = 'none'; }
    }

    // ── Action Buttons ────────────────────────────────────────────────────────

    function _renderActionButtons(t) {
        var container = document.getElementById('actionButtons');
        var btns = [];

        var isRequester = t.requester && t.requester.id == ctx.currentUserId;
        var isActiveTech = (t.technicians || []).some(function (tc) {
            return tc.user_id == ctx.currentUserId && tc.is_active;
        });

        // Iniciar progreso
        if (t.status === 'ASSIGNED' && (isActiveTech || ctx.isDispatcher)) {
            btns.push('<button class="btn btn-sm btn-outline-maint" id="startBtn">' +
                '<i class="bi bi-play-circle me-1"></i>Iniciar Progreso</button>');
        }

        // Resolver — D-F: solo dispatcher resuelve directo desde ASSIGNED;
        // técnicos/coordinadores deben iniciar progreso (IN_PROGRESS) primero.
        var canResolveNow = t.status === 'IN_PROGRESS' || (t.status === 'ASSIGNED' && ctx.isDispatcher);
        if (canResolveNow && ctx.canResolve && (isActiveTech || ctx.isDispatcher)) {
            btns.push('<button class="btn btn-sm btn-success" id="resolveBtn">' +
                '<i class="bi bi-check-circle me-1"></i>Resolver</button>');
        }

        // Calificar
        if ((t.status === 'RESOLVED_SUCCESS' || t.status === 'RESOLVED_FAILED') && t.can_be_rated && (isRequester && ctx.canRate)) {
            btns.push('<button class="btn btn-sm btn-warning" id="rateBtn">' +
                '<i class="bi bi-star me-1"></i>Calificar</button>');
        }

        // Cancelar
        var canCancel = isRequester && t.status === 'PENDING';
        if (!canCancel && ctx.isDispatcher) canCancel = t.is_open && t.status !== 'RESOLVED_SUCCESS' && t.status !== 'RESOLVED_FAILED';
        if (canCancel) {
            btns.push('<button class="btn btn-sm btn-outline-danger" id="cancelBtn">' +
                '<i class="bi bi-x-circle me-1"></i>Cancelar</button>');
        }

        container.innerHTML = btns.join('');

        var startBtn = document.getElementById('startBtn');
        if (startBtn) startBtn.addEventListener('click', function () { _doStart(); });

        var resolveBtn = document.getElementById('resolveBtn');
        if (resolveBtn) resolveBtn.addEventListener('click', function () { window.MaintResolution && MaintResolution.openModal(t); });

        var rateBtn = document.getElementById('rateBtn');
        if (rateBtn) rateBtn.addEventListener('click', function () { window.MaintResolution && MaintResolution.openRateModal(); });

        var cancelBtn = document.getElementById('cancelBtn');
        if (cancelBtn) cancelBtn.addEventListener('click', function () { _openCancelModal(); });
    }

    // ── Tabs ──────────────────────────────────────────────────────────────────

    function _bindTabs() {
        document.getElementById('detailTabs').addEventListener('click', function (e) {
            var btn = e.target.closest('[data-tab]');
            if (!btn) return;
            document.querySelectorAll('#detailTabs .nav-link').forEach(function (l) { l.classList.remove('active'); });
            btn.classList.add('active');
            _activeTab = btn.dataset.tab;
            if (_ticket) _renderTab(_activeTab);
        });
    }

    function _renderTab(tab) {
        var content = document.getElementById('tabContent');
        switch (tab) {
            case 'info':
                content.innerHTML = _buildInfoTab(_ticket);
                _loadTicketAttachments();
                break;
            case 'technicians':
                content.innerHTML = _buildTechTab(_ticket);
                window.MaintAssignment && MaintAssignment.bind(_ticket, _reload);
                break;
            case 'comments':
                content.innerHTML = _buildCommentsTab(_ticket);
                _bindCommentForm();
                _staggerComments(content);
                break;
            case 'resolution':
                content.innerHTML = _buildResolutionTab(_ticket);
                _loadMaterials();
                _loadResolutionAttachments();
                break;
            case 'history':
                content.innerHTML = _buildHistoryTab(_ticket);
                _staggerHistory(content);
                break;
        }
        // Reflow + animate the tab content
        content.classList.remove('mn-tab-fading');
        void content.offsetWidth;
        content.classList.add('mn-tab-fading');
    }

    function _staggerComments(content) {
        var bubbles = content.querySelectorAll('.mn-comment-bubble');
        if (!bubbles.length || !window.MaintUtils || !MaintUtils.animate) return;
        for (var i = 0; i < bubbles.length; i++) {
            bubbles[i].style.animationDelay = Math.min(i * 45, 360) + 'ms';
            bubbles[i].classList.add('mn-fade-in-up');
        }
    }

    function _staggerHistory(content) {
        var items = content.querySelectorAll('.mn-history-item');
        if (!items.length) return;
        for (var i = 0; i < items.length; i++) {
            items[i].style.animationDelay = Math.min(i * 40, 320) + 'ms';
            items[i].classList.add('mn-slide-in-left');
        }
    }

    function _reload() {
        _loadTicket();
    }

    // ── Tab: Información ──────────────────────────────────────────────────────

    function _buildInfoTab(t) {
        var due = t.due_at ? new Date(t.due_at) : null;
        var now = new Date();
        var isOverdue = due && due < now && t.is_open && !t.is_resolved;
        var slaText = due ? due.toLocaleString('es-MX') : '—';
        var slaClass = isOverdue ? 'text-danger fw-semibold' : 'text-muted';

        var customHtml = '';
        if (t.category && t.category.field_template && t.category.field_template.length > 0) {
            var cf = t.custom_fields || {};
            customHtml = '<hr><div class="row g-3">';
            t.category.field_template.forEach(function (f) {
                customHtml += '<div class="col-md-4"><div class="mn-detail-label">' + _esc(f.label) + '</div>' +
                    '<div class="mn-detail-value">' + _esc(cf[f.key] || '—') + '</div></div>';
            });
            customHtml += '</div>';
        }

        return '<div class="card border-0 shadow-sm">' +
            '<div class="card-body">' +
                '<div class="row g-3">' +
                    '<div class="col-12"><div class="mn-detail-label">Descripción</div>' +
                        '<div class="mn-detail-value" style="white-space:pre-line;">' + _esc(t.description) + '</div></div>' +
                    (t.location ? '<div class="col-md-6"><div class="mn-detail-label"><i class="bi bi-geo-alt me-1"></i>Ubicación</div>' +
                        '<div class="mn-detail-value">' + _esc(t.location) + '</div></div>' : '') +
                    '<div class="col-md-6"><div class="mn-detail-label">SLA / Vencimiento</div>' +
                        '<div class="mn-detail-value ' + slaClass + '">' + slaText + '</div></div>' +
                    '<div class="col-md-6"><div class="mn-detail-label">Solicitante</div>' +
                        '<div class="mn-requester-card">' +
                            '<div class="mn-requester-avatar">' + _getInitials(t.requester ? t.requester.name : '') + '</div>' +
                            '<div class="mn-requester-info">' +
                                '<div class="mn-requester-name">' + _esc(t.requester ? t.requester.name : '—') + '</div>' +
                                (t.requester_position ? '<div class="mn-requester-meta"><i class="bi bi-briefcase me-1"></i>' + _esc(t.requester_position) + '</div>' : '') +
                                (t.requester_department ? '<div class="mn-requester-meta"><i class="bi bi-building me-1"></i>' + _esc(t.requester_department) + '</div>' : '') +
                                (t.requester && t.requester.email ? '<div class="mn-requester-meta"><i class="bi bi-envelope me-1"></i>' + _esc(t.requester.email) + '</div>' : '') +
                            '</div>' +
                        '</div>' +
                    '</div>' +
                    '<div class="col-md-6"><div class="mn-detail-label">Creado por</div>' +
                        '<div class="mn-detail-value">' + _esc(t.created_by ? t.created_by.name : '—') + '</div>' +
                        '<small class="text-muted">' + (t.created_at ? new Date(t.created_at).toLocaleString('es-MX') : '') + '</small>' + '</div>' +
                    '<div class="col-md-6"><div class="mn-detail-label"><i class="bi bi-person-badge me-1"></i>Coordinador responsable</div>' +
                        '<div class="mn-detail-value">' +
                            (t.coordinator ? _esc(t.coordinator.name || ('ID ' + t.coordinator.id)) : '<span class="text-muted fst-italic">Sin asignar</span>') +
                        '</div></div>' +
                    '<div class="col-12" id="ticketAttachmentsSection">' +
                        '<div class="mn-detail-label"><i class="bi bi-paperclip me-1"></i>Archivos adjuntos</div>' +
                        '<div class="text-muted small mt-1"><span class="spinner-border spinner-border-sm me-1" role="status"></span>Cargando...</div>' +
                    '</div>' +
                '</div>' +
                customHtml +
            '</div>' +
        '</div>';
    }

    // ── Adjuntos: helpers compartidos ────────────────────────────────────────

    function _buildAttachGrid(attachments) {
        if (!attachments || !attachments.length) {
            return '<div class="text-muted small">Sin archivos adjuntos.</div>';
        }
        var items = attachments.map(function (a) {
            if (a.is_purged) {
                var purgedDate = a.purged_at
                    ? new Date(a.purged_at).toLocaleDateString('es-MX', { day: '2-digit', month: '2-digit', year: '2-digit' })
                    : '—';
                return '<div class="mn-attach-purged">' +
                    '<i class="bi bi-file-earmark-x fs-4 mb-1"></i>' +
                    'Archivo eliminado el ' + purgedDate +
                '</div>';
            }
            var downloadUrl = '/api/maint/v2/attachments/' + a.id + '/download';
            var isPdf = a.filename && a.filename.toLowerCase().endsWith('.pdf');
            var isImage = a.filename && /\.(jpe?g|png|gif|webp)$/i.test(a.filename);
            if (isImage) {
                return '<a href="' + downloadUrl + '" target="_blank" class="mn-attach-thumb" title="' + _esc(a.filename || '') + '">' +
                    '<img src="' + downloadUrl + '" alt="' + _esc(a.filename || '') + '" loading="lazy">' +
                '</a>';
            }
            if (isPdf) {
                return '<a href="' + downloadUrl + '" target="_blank" class="mn-attach-pdf" title="' + _esc(a.filename || '') + '">' +
                    '<i class="bi bi-file-earmark-pdf fs-3 mb-1"></i>' +
                    '<span style="word-break:break-all;">' + _esc(a.filename || 'PDF') + '</span>' +
                '</a>';
            }
            return '<a href="' + downloadUrl + '" target="_blank" class="mn-attach-pdf" style="background:#e8f4f8;color:#0c7abf;border-color:#bee5eb;" title="' + _esc(a.filename || '') + '">' +
                '<i class="bi bi-file-earmark fs-3 mb-1"></i>' +
                '<span style="word-break:break-all;">' + _esc(a.filename || 'Archivo') + '</span>' +
            '</a>';
        });
        return '<div class="mn-attach-grid mt-2">' + items.join('') + '</div>';
    }

    function _loadTicketAttachments() {
        var section = document.getElementById('ticketAttachmentsSection');
        if (!section) return;

        MaintUtils.api.fetch(API_BASE + '/tickets/' + ctx.ticketId + '/attachments?type=ticket')
            .then(function (data) {
                var attachments = data.attachments || [];
                section.innerHTML =
                    '<div class="mn-detail-label"><i class="bi bi-paperclip me-1"></i>Archivos adjuntos</div>' +
                    _buildAttachGrid(attachments);
            })
            .catch(function () {
                section.innerHTML =
                    '<div class="mn-detail-label"><i class="bi bi-paperclip me-1"></i>Archivos adjuntos</div>' +
                    '<div class="text-muted small mt-1">No se pudieron cargar los adjuntos.</div>';
            });
    }

    function _loadResolutionAttachments() {
        var section = document.getElementById('resolutionAttachmentsSection');
        if (!section) return;

        MaintUtils.api.fetch(API_BASE + '/tickets/' + ctx.ticketId + '/attachments?type=resolution')
            .then(function (data) {
                var attachments = data.attachments || [];
                section.innerHTML =
                    '<div class="mn-detail-label mt-3"><i class="bi bi-paperclip me-1"></i>Archivos de resolución</div>' +
                    _buildAttachGrid(attachments);
            })
            .catch(function () {
                if (section) section.innerHTML = '';
            });
    }

    // ── Tab: Técnicos ─────────────────────────────────────────────────────────

    function _buildTechTab(t) {
        var active = (t.technicians || []).filter(function (tc) { return tc.is_active; });
        var historical = (t.technicians || []).filter(function (tc) { return !tc.is_active; });

        var html = '<div class="card border-0 shadow-sm"><div class="card-body">';

        if (ctx.canAssign && t.is_open && t.status !== 'RESOLVED_SUCCESS' && t.status !== 'RESOLVED_FAILED') {
            html += '<div class="d-flex justify-content-end mb-3">' +
                '<button class="btn btn-maint btn-sm" id="openAssignBtn">' +
                '<i class="bi bi-person-plus me-1"></i>Asignar Técnico</button></div>';
        }

        if (active.length === 0) {
            html += '<div class="text-muted text-center py-3"><i class="bi bi-person-dash fs-2 d-block mb-1"></i>Sin técnicos asignados</div>';
        } else {
            html += '<h6 class="fw-semibold mb-2" style="color:var(--maint-primary-dark);">Técnicos activos</h6>';
            active.forEach(function (tc) {
                html += '<div class="d-flex align-items-center justify-content-between p-2 mb-2 rounded" style="background:var(--maint-primary-light);">' +
                    '<div><i class="bi bi-person-fill me-2" style="color:var(--maint-primary);"></i>' +
                    '<span class="fw-medium">' + _esc(tc.user_name) + '</span>' +
                    (tc.notes ? '<br><small class="text-muted ms-4">' + _esc(tc.notes) + '</small>' : '') + '</div>' +
                    (ctx.canAssign && t.is_open ?
                        '<button class="btn btn-sm btn-outline-danger unassign-btn" data-uid="' + tc.user_id + '" data-name="' + _esc(tc.user_name) + '">' +
                        '<i class="bi bi-person-x"></i></button>' : '') +
                '</div>';
            });
        }

        if (historical.length > 0) {
            html += '<hr><h6 class="fw-semibold text-muted mb-2">Historial de asignaciones</h6>';
            historical.forEach(function (tc) {
                html += '<div class="text-muted small mb-1"><i class="bi bi-person-check me-1"></i>' +
                    _esc(tc.user_name) + ' <span class="ms-2">Removido</span>' +
                    (tc.unassigned_at ? ' ' + new Date(tc.unassigned_at).toLocaleString('es-MX') : '') + '</div>';
            });
        }

        html += '</div></div>';
        return html;
    }

    // ── Tab: Comentarios ──────────────────────────────────────────────────────

    function _buildCommentsTab(t) {
        var comments = t.comments || [];
        var canInternal = ctx.isDispatcher || ctx.isTechMaint;

        var html = '<div class="card border-0 shadow-sm"><div class="card-body">';

        if (comments.length === 0) {
            html += '<div class="text-muted text-center py-3"><i class="bi bi-chat-left fs-2 d-block mb-1"></i>Sin comentarios</div>';
        } else {
            comments.forEach(function (c) {
                var isInternal = c.is_internal;
                var commentAttachments = c.attachments || [];
                var attachHtml = '';
                if (commentAttachments.length) {
                    var items = commentAttachments.map(function (a) {
                        if (a.is_purged) return '<span class="text-muted small"><i class="bi bi-file-earmark-x me-1"></i>Archivo eliminado</span>';
                        var url = '/api/maint/v2/attachments/' + a.id + '/download';
                        var isImg = a.filename && /\.(jpe?g|png|gif|webp)$/i.test(a.filename);
                        if (isImg) return '<a href="' + url + '" target="_blank"><img src="' + url + '" style="max-height:80px;max-width:100px;border-radius:4px;object-fit:cover;" alt="' + _esc(a.filename || '') + '" loading="lazy"></a>';
                        return '<a href="' + url + '" target="_blank" class="small"><i class="bi bi-paperclip me-1"></i>' + _esc(a.filename || 'Archivo') + '</a>';
                    });
                    attachHtml = '<div class="d-flex flex-wrap gap-2 mt-2">' + items.join('') + '</div>';
                }
                html += '<div class="mn-comment-bubble ' + (isInternal ? 'internal' : '') + ' mb-3">' +
                    '<div class="d-flex justify-content-between align-items-start mb-1">' +
                        '<span class="fw-semibold small">' + _esc(c.author ? c.author.name : '—') + '</span>' +
                        '<div class="d-flex align-items-center gap-2">' +
                            (isInternal ? '<span class="badge bg-warning text-dark" style="font-size:0.65rem;">Interno</span>' : '') +
                            '<small class="text-muted">' + (c.created_at ? new Date(c.created_at).toLocaleString('es-MX') : '') + '</small>' +
                        '</div>' +
                    '</div>' +
                    '<div style="white-space:pre-line;">' + _esc(c.content) + '</div>' +
                    attachHtml +
                '</div>';
            });
        }

        // Formulario de nuevo comentario
        if (t.is_open) {
            html += '<hr><div id="commentForm">' +
                '<textarea class="form-control form-control-sm mb-2" id="newCommentText" rows="3" placeholder="Escribe un comentario..."></textarea>' +
                (canInternal ?
                    '<div class="form-check mb-2"><input class="form-check-input" type="checkbox" id="isInternalCheck">' +
                    '<label class="form-check-label small" for="isInternalCheck">Comentario interno (solo staff operativo)</label></div>' : '') +
                '<div class="d-flex align-items-center gap-2 mb-2">' +
                    '<label class="btn btn-outline-secondary btn-sm mb-0" for="commentFileInput" style="cursor:pointer;">' +
                        '<i class="bi bi-paperclip me-1"></i>Adjuntar archivos' +
                    '</label>' +
                    '<input type="file" id="commentFileInput" multiple accept="image/jpeg,image/png,image/gif,image/webp,application/pdf" style="display:none;">' +
                    '<span id="commentFileCount" class="text-muted small"></span>' +
                '</div>' +
                '<button class="btn btn-maint btn-sm" id="sendCommentBtn"><i class="bi bi-send me-1"></i>Enviar</button>' +
            '</div>';
        }

        html += '</div></div>';
        return html;
    }

    function _bindCommentForm() {
        var btn = document.getElementById('sendCommentBtn');
        if (!btn) return;

        // Track selected files and update label
        var fileInput = document.getElementById('commentFileInput');
        var fileCount = document.getElementById('commentFileCount');
        if (fileInput) {
            fileInput.addEventListener('change', function () {
                var n = fileInput.files ? fileInput.files.length : 0;
                fileCount.textContent = n > 0 ? n + ' archivo' + (n !== 1 ? 's' : '') + ' seleccionado' + (n !== 1 ? 's' : '') : '';
            });
        }

        btn.addEventListener('click', function () {
            var text = (document.getElementById('newCommentText').value || '').trim();
            if (text.length < 1) return;
            var isInternal = document.getElementById('isInternalCheck') ? document.getElementById('isInternalCheck').checked : false;
            var files = fileInput && fileInput.files ? fileInput.files : null;

            MaintUtils.loading.show(btn, 'Enviando...');

            if (files && files.length > 0) {
                // Use multipart/form-data to send content + files together
                var formData = new FormData();
                formData.append('content', text);
                formData.append('is_internal', isInternal ? 'true' : 'false');
                for (var i = 0; i < files.length; i++) {
                    formData.append('files[]', files[i]);
                }
                fetch(API_BASE + '/tickets/' + ctx.ticketId + '/comments', {
                    method: 'POST',
                    credentials: 'include',
                    body: formData,
                })
                    .then(function (res) {
                        if (!res.ok) return res.json().then(function (d) { throw new Error((d && (d.detail || d.message)) || 'Error ' + res.status); });
                        return res.json();
                    })
                    .then(function () {
                        MaintUtils.toast('Comentario enviado', 'success');
                        _reload();
                    })
                    .catch(function (err) {
                        MaintUtils.loading.hide(btn);
                        MaintUtils.toast(err.message, 'error');
                    });
            } else {
                MaintUtils.api.fetch(API_BASE + '/tickets/' + ctx.ticketId + '/comments', {
                    method: 'POST',
                    body: JSON.stringify({ content: text, is_internal: isInternal }),
                })
                    .then(function () {
                        MaintUtils.toast('Comentario enviado', 'success');
                        _reload();
                    })
                    .catch(function (err) {
                        MaintUtils.loading.hide(btn);
                        MaintUtils.toast(err.message, 'error');
                    });
            }
        });
    }

    // ── Tab: Resolución ───────────────────────────────────────────────────────

    function _buildResolutionTab(t) {
        var html = '<div class="card border-0 shadow-sm"><div class="card-body">';

        if (t.resolved_at) {
            var outcomeClass = t.status === 'RESOLVED_SUCCESS' ? 'text-success' : 'text-warning';
            var outcomeLabel = t.status === 'RESOLVED_SUCCESS' ? 'Resuelto exitosamente' : 'Atendido (sin resolución completa)';

            html += '<div class="row g-3">' +
                '<div class="col-12"><h6 class="' + outcomeClass + ' fw-bold"><i class="bi bi-check-circle me-1"></i>' + outcomeLabel + '</h6></div>' +
                '<div class="col-md-3"><div class="mn-detail-label">Tipo</div><div>' + _esc(t.maintenance_type || '—') + '</div></div>' +
                '<div class="col-md-3"><div class="mn-detail-label">Origen</div><div>' + _esc(t.service_origin || '—') + '</div></div>' +
                '<div class="col-md-3"><div class="mn-detail-label">Tiempo invertido</div><div>' + _fmtDuration(t.time_invested_minutes) + '</div></div>' +
                '<div class="col-md-3"><div class="mn-detail-label">Resuelto por</div><div>' + _esc(t.resolved_by ? t.resolved_by.name : '—') + '</div></div>' +
                '<div class="col-12"><div class="mn-detail-label">Notas de resolución</div>' +
                    '<div style="white-space:pre-line;">' + _esc(t.resolution_notes || '—') + '</div></div>' +
                (t.observations ? '<div class="col-12"><div class="mn-detail-label">Observaciones</div>' +
                    '<div>' + _esc(t.observations) + '</div></div>' : '') +
                '<div class="col-12" id="materialsSection">' +
                    '<div class="mn-detail-label"><i class="bi bi-box-seam me-1"></i>Materiales del almacén</div>' +
                    '<div class="text-muted small mt-1"><div class="spinner-border spinner-border-sm me-1" role="status"></div>Cargando...</div>' +
                '</div>' +
                '<div class="col-12" id="resolutionAttachmentsSection">' +
                    '<div class="text-muted small mt-1"><span class="spinner-border spinner-border-sm me-1" role="status"></span>Cargando adjuntos...</div>' +
                '</div>' +
            '</div>';

            if (t.rated_at) {
                html += '<hr><h6 class="fw-semibold mb-3" style="color:var(--maint-primary-dark);"><i class="bi bi-star me-1"></i>Calificación</h6>' +
                    '<div class="row g-2">' +
                    '<div class="col-md-4"><div class="mn-detail-label">Atención</div><div>' + _stars(t.rating_attention) + '</div></div>' +
                    '<div class="col-md-4"><div class="mn-detail-label">Rapidez</div><div>' + _stars(t.rating_speed) + '</div></div>' +
                    '<div class="col-md-4"><div class="mn-detail-label">Eficiencia</div><div>' + (t.rating_efficiency ? '✅ Sí' : '❌ No') + '</div></div>' +
                    (t.rating_comment ? '<div class="col-12"><div class="mn-detail-label">Comentario</div><div>' + _esc(t.rating_comment) + '</div></div>' : '') +
                    '</div>';
            }
        } else {
            var canAct = (t.status === 'IN_PROGRESS' || (t.status === 'ASSIGNED' && ctx.isDispatcher)) && ctx.canResolve;
            html += '<div class="text-muted text-center py-4">' +
                '<i class="bi bi-hourglass-split fs-2 d-block mb-2"></i>' +
                (canAct ? 'Usa el botón <strong>Resolver</strong> para registrar la resolución.' : 'El ticket aún no ha sido resuelto.') +
            '</div>';
        }

        html += '</div></div>';
        return html;
    }

    function _loadMaterials() {
        var section = document.getElementById('materialsSection');
        if (!section) return;

        MaintUtils.api.fetch(API_BASE + '/tickets/' + ctx.ticketId + '/materials')
            .then(function (data) {
                var mats = data.materials || [];
                var canRevert = (ctx.isDispatcher || ctx.isAdmin) && _ticket && _ticket.status !== 'CLOSED';

                if (!mats.length) {
                    section.innerHTML =
                        '<div class="mn-detail-label"><i class="bi bi-box-seam me-1"></i>Materiales del almacén</div>' +
                        '<div class="text-muted small mt-1">Sin materiales registrados.</div>';
                    return;
                }

                var rows = mats.map(function (m) {
                    var revertBtn = canRevert
                        ? '<button type="button" class="btn btn-sm btn-outline-danger py-0 px-1 ms-auto mn-revert-mat-btn"' +
                          ' data-product-id="' + m.product_id + '"' +
                          ' data-product-name="' + _esc(m.product_name || 'Producto #' + m.product_id) + '"' +
                          ' title="Revertir consumo">' +
                          '<i class="bi bi-trash3"></i></button>'
                        : '';
                    return '<div class="d-flex align-items-center gap-2 py-1">' +
                        '<i class="bi bi-box text-secondary"></i>' +
                        '<span class="fw-medium small">' + _esc(m.product_name || 'Producto #' + m.product_id) + '</span>' +
                        '<span class="badge bg-light text-secondary">' + _esc(m.quantity_used) + ' ' + _esc(m.unit_of_measure || '') + '</span>' +
                        (m.notes ? '<span class="text-muted small">— ' + _esc(m.notes) + '</span>' : '') +
                        revertBtn +
                    '</div>';
                });

                section.innerHTML =
                    '<div class="mn-detail-label"><i class="bi bi-box-seam me-1"></i>Materiales del almacén</div>' +
                    '<div class="mt-1" id="materialRows">' + rows.join('') + '</div>';

                // Bind revert buttons
                section.querySelectorAll('.mn-revert-mat-btn').forEach(function (btn) {
                    btn.addEventListener('click', function () {
                        var productId = btn.dataset.productId;
                        var productName = btn.dataset.productName;
                        MaintUtils.confirm({
                            title: 'Revertir material',
                            message: '¿Revertir el consumo de "' + productName + '"? El stock volverá al almacén.',
                            confirmLabel: 'Revertir',
                            confirmClass: 'btn-danger',
                            onConfirm: function () {
                                _revertMaterial(productId);
                            },
                        });
                    });
                });
            })
            .catch(function () {
                var section2 = document.getElementById('materialsSection');
                if (section2) section2.innerHTML =
                    '<div class="mn-detail-label"><i class="bi bi-box-seam me-1"></i>Materiales del almacén</div>' +
                    '<div class="text-muted small mt-1">No se pudo cargar.</div>';
            });
    }

    function _revertMaterial(productId) {
        // Usa el endpoint genérico del warehouse:
        // DELETE /api/warehouse/v2/ticket-materials/maint/{ticketId}/{productId}
        var url = '/api/warehouse/v2/ticket-materials/maint/' + ctx.ticketId + '/' + productId;
        MaintUtils.api.fetch(url, { method: 'DELETE' })
            .then(function () {
                MaintUtils.toast('Material revertido correctamente', 'success');
                _loadMaterials();
            })
            .catch(function (err) {
                MaintUtils.toast('No se pudo revertir: ' + err.message, 'error');
            });
    }

    // ── Tab: Historial ────────────────────────────────────────────────────────

    function _buildHistoryTab(t) {
        var logs = t.status_logs || [];
        if (logs.length === 0) {
            return '<div class="text-muted text-center py-4"><i class="bi bi-clock-history fs-2 d-block mb-2"></i>Sin historial</div>';
        }

        var statusEmoji = {
            PENDING: '🕐', ASSIGNED: '👷', IN_PROGRESS: '⚙️',
            RESOLVED_SUCCESS: '✅', RESOLVED_FAILED: '⚠️', CLOSED: '🔒', CANCELED: '❌',
        };

        var html = '<div class="card border-0 shadow-sm"><div class="card-body">';
        logs.slice().reverse().forEach(function (sl) {
            var label = STATUS_LABEL[sl.to_status] || sl.to_status;
            var emoji = statusEmoji[sl.to_status] || '•';
            html += '<div class="mn-history-item">' +
                '<div class="fw-semibold">' + emoji + ' ' + label + '</div>' +
                (sl.notes ? '<div class="text-muted small">' + _esc(sl.notes) + '</div>' : '') +
                '<div class="small text-muted mt-1">' +
                    '<i class="bi bi-person me-1"></i>' + _esc(sl.changed_by ? sl.changed_by.name : '—') +
                    ' &nbsp;·&nbsp; ' +
                    (sl.created_at ? new Date(sl.created_at).toLocaleString('es-MX') : '') +
                '</div>' +
            '</div>';
        });
        html += '</div></div>';
        return html;
    }

    // ── Acciones ──────────────────────────────────────────────────────────────

    function _doStart() {
        MaintUtils.confirm({
            title: 'Iniciar Progreso',
            message: '¿Confirmas que empezarás a trabajar en este ticket?',
            confirmLabel: 'Iniciar',
            confirmClass: 'btn-maint',
            onConfirm: function () {
                MaintUtils.api.fetch(API_BASE + '/tickets/' + ctx.ticketId + '/start', { method: 'POST' })
                    .then(function () { MaintUtils.toast('Ticket en progreso', 'success'); _reload(); })
                    .catch(function (err) { MaintUtils.toast(err.message, 'error'); });
            },
        });
    }

    function _openCancelModal() {
        var modal = new bootstrap.Modal(document.getElementById('cancelModal'));
        modal.show();
        document.getElementById('confirmCancelBtn').onclick = function () {
            var reason = (document.getElementById('cancelReason').value || '').trim();
            MaintUtils.api.fetch(API_BASE + '/tickets/' + ctx.ticketId + '/cancel', {
                method: 'POST',
                body: JSON.stringify({ reason: reason || null }),
            })
                .then(function () {
                    modal.hide();
                    MaintUtils.toast('Ticket cancelado', 'info');
                    setTimeout(function () { window.location.href = '/maint/tickets'; }, 1000);
                })
                .catch(function (err) { MaintUtils.toast(err.message, 'error'); });
        };
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    function _stars(n) {
        var s = '';
        for (var i = 1; i <= 5; i++) {
            s += '<i class="bi ' + (i <= n ? 'bi-star-fill' : 'bi-star') + '" style="color:#F59E0B;"></i>';
        }
        return s;
    }

    function _esc(s) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(String(s || '')));
        return d.innerHTML;
    }

    function _getInitials(name) {
        if (!name) return '?';
        var parts = String(name).trim().split(/\s+/);
        if (parts.length === 1) return parts[0].substring(0, 2).toUpperCase();
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }

    window._maintDetailReload = _reload;

})();

// =============================================================================
// MaintLiveDetailSync — WebSocket live updates para el detalle de ticket
// =============================================================================
(function () {
    'use strict';

    var ctx = window.TICKET_CTX || {};

    // ── Toast helper ─────────────────────────────────────────────────────────

    function _toast(message, type) {
        if (window.MaintUtils && typeof MaintUtils.toast === 'function') {
            MaintUtils.toast(message, type || 'info');
        } else {
            console.log('[MaintLive] ' + message);
        }
    }

    // ── Esperar a que el socket esté listo (máx 3 s) ─────────────────────────

    function _waitForSocket(callback) {
        var attempts = 0;
        var maxAttempts = 30;
        var interval = setInterval(function () {
            if (window.__maintSocket) {
                clearInterval(interval);
                callback(window.__maintSocket);
                return;
            }
            attempts++;
            if (attempts >= maxAttempts) {
                clearInterval(interval);
                console.warn('[MaintLiveDetailSync] Socket no disponible después de 3 s');
            }
        }, 100);
    }

    // ── Actualizar badge de tech count ────────────────────────────────────────

    function _updateTechBadge(delta) {
        var el = document.getElementById('techCount');
        if (!el) return;
        var current = parseInt(el.textContent, 10) || 0;
        var next = Math.max(0, current + delta);
        if (next > 0) {
            el.textContent = next;
            el.style.display = '';
        } else {
            el.style.display = 'none';
        }
    }

    // ── Actualizar badge de commentCount ─────────────────────────────────────

    function _bumpCommentBadge() {
        var el = document.getElementById('commentCount');
        if (!el) return;
        var current = parseInt(el.textContent, 10) || 0;
        el.textContent = current + 1;
        el.style.display = '';
    }

    // ── Indicador "nuevo comentario" cuando el tab de comentarios no está activo ─

    var _commentIndicator = null;

    function _showCommentIndicator() {
        var tabBtn = document.querySelector('[data-tab="comments"]');
        if (!tabBtn) return;
        if (!_commentIndicator) {
            _commentIndicator = document.createElement('span');
            _commentIndicator.className = 'badge bg-info ms-1';
            _commentIndicator.style.fontSize = '0.65rem';
            _commentIndicator.textContent = 'Nuevo';
            tabBtn.appendChild(_commentIndicator);
        }
        _commentIndicator.style.display = '';
    }

    function _hideCommentIndicator() {
        if (_commentIndicator) _commentIndicator.style.display = 'none';
    }

    // ── Append de comentario en tiempo real ───────────────────────────────────

    function _appendComment(payload) {
        var content = document.getElementById('tabContent');
        if (!content) return;

        // Buscar el contenedor de burbujas de comentario
        var cardBody = content.querySelector('.card-body');
        if (!cardBody) return;

        // Construir burbuja
        var isInternal = !!payload.is_internal;
        var bubble = document.createElement('div');
        bubble.className = 'mn-comment-bubble ' + (isInternal ? 'internal' : '') + ' mb-3';

        var authorName = (payload.author && payload.author.name) ? payload.author.name : '—';
        var createdAt = payload.created_at ? new Date(payload.created_at).toLocaleString('es-MX') : '';

        bubble.innerHTML =
            '<div class="d-flex justify-content-between align-items-start mb-1">' +
                '<span class="fw-semibold small">' + _esc(authorName) + '</span>' +
                '<div class="d-flex align-items-center gap-2">' +
                    (isInternal ? '<span class="badge bg-warning text-dark" style="font-size:0.65rem;">Interno</span>' : '') +
                    '<small class="text-muted">' + _esc(createdAt) + '</small>' +
                '</div>' +
            '</div>' +
            '<div style="white-space:pre-line;">' + _esc(payload.content || '') + '</div>';

        // Insertar antes del formulario (hr + div#commentForm) si existe
        var hr = cardBody.querySelector('hr');
        if (hr) {
            cardBody.insertBefore(bubble, hr);
        } else {
            cardBody.insertBefore(bubble, cardBody.firstChild);
        }

        // Quitar el mensaje de "sin comentarios" si existía
        var empty = cardBody.querySelector('.text-muted.text-center');
        if (empty) empty.remove();

        // Entrada animada + pulso para llamar la atención
        bubble.classList.add('mn-fade-in-down');
        if (window.MaintUtils && MaintUtils.animate) {
            setTimeout(function () { MaintUtils.animate.highlight(bubble); }, 200);
        }
    }

    function _esc(s) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(String(s || '')));
        return d.innerHTML;
    }

    // ── Registro de eventos ───────────────────────────────────────────────────

    function _bindEvents(socket) {
        // Cambio de estado
        socket.on('ticket_status_changed', function (payload) {
            if ((payload.ticket_id || payload.id) !== ctx.ticketId) return;
            var label = payload.status_label || payload.status || 'desconocido';
            _toast('El estado del ticket cambió a: ' + label, 'info');
            if (typeof window._maintDetailReload === 'function') window._maintDetailReload();
        });

        // Asignación de técnico
        socket.on('ticket_assigned', function (payload) {
            if ((payload.ticket_id || payload.id) !== ctx.ticketId) return;
            _toast('Se asignó un técnico al ticket', 'info');
            // Si el tab de técnicos está activo, recargar; si no, actualizar badge
            var activeTab = document.querySelector('#detailTabs .nav-link.active');
            if (activeTab && activeTab.dataset && activeTab.dataset.tab === 'technicians') {
                if (typeof window._maintDetailReload === 'function') window._maintDetailReload();
            } else {
                _updateTechBadge(1);
            }
        });

        // Desasignación de técnico
        socket.on('ticket_unassigned', function (payload) {
            if ((payload.ticket_id || payload.id) !== ctx.ticketId) return;
            _toast('Se removió un técnico del ticket', 'info');
            var activeTab = document.querySelector('#detailTabs .nav-link.active');
            if (activeTab && activeTab.dataset && activeTab.dataset.tab === 'technicians') {
                if (typeof window._maintDetailReload === 'function') window._maintDetailReload();
            } else {
                _updateTechBadge(-1);
            }
        });

        // Nuevo comentario
        socket.on('ticket_comment_added', function (payload) {
            if ((payload.ticket_id || payload.id) !== ctx.ticketId) return;
            var activeTab = document.querySelector('#detailTabs .nav-link.active');
            if (activeTab && activeTab.dataset && activeTab.dataset.tab === 'comments') {
                _appendComment(payload);
                _hideCommentIndicator();
            } else {
                _bumpCommentBadge();
                _showCommentIndicator();
                _toast('Nuevo comentario en el ticket', 'info');
            }
        });

        // Ticket resuelto
        socket.on('ticket_resolved', function (payload) {
            if ((payload.ticket_id || payload.id) !== ctx.ticketId) return;
            _toast('Ticket resuelto', 'success');
            if (typeof window._maintDetailReload === 'function') window._maintDetailReload();
        });

        // Ticket cancelado
        socket.on('ticket_canceled', function (payload) {
            if ((payload.ticket_id || payload.id) !== ctx.ticketId) return;
            _toast('Ticket cancelado', 'warning');
            // Deshabilitar botones de acción
            var actionButtons = document.getElementById('actionButtons');
            if (actionButtons) {
                actionButtons.querySelectorAll('button').forEach(function (btn) {
                    btn.disabled = true;
                });
            }
            if (typeof window._maintDetailReload === 'function') window._maintDetailReload();
        });

        // Ticket calificado
        socket.on('ticket_rated', function (payload) {
            if ((payload.ticket_id || payload.id) !== ctx.ticketId) return;
            if (ctx.isTechMaint) {
                var avg = payload.rating_avg != null ? (' Promedio: ' + Number(payload.rating_avg).toFixed(1) + '/5') : '';
                _toast('El ticket recibió una calificación.' + avg, 'success');
            }
            if (typeof window._maintDetailReload === 'function') window._maintDetailReload();
        });
    }

    // ── Limpiar el room al salir de la página ─────────────────────────────────

    function _bindUnload() {
        window.addEventListener('beforeunload', function () {
            if (window.__maintLeaveTicket && ctx.ticketId) {
                window.__maintLeaveTicket(ctx.ticketId);
            }
        });
    }

    // ── Init ──────────────────────────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', function () {
        if (!ctx.ticketId) return;

        _waitForSocket(function (socket) {
            window.__maintJoinTicket(ctx.ticketId);
            _bindEvents(socket);
        });

        _bindUnload();
    });

    window.MaintLiveDetailSync = {};

})();
