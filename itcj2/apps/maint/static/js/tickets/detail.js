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
        document.getElementById('headerSkeleton').style.display = 'none';
        document.getElementById('headerContent').style.display = '';

        document.getElementById('ticketNumber').textContent = t.ticket_number;
        document.getElementById('ticketTitle').textContent = t.title;
        document.getElementById('progressBar').style.width = (t.progress_pct || 0) + '%';

        var sBadge = document.getElementById('statusBadge');
        sBadge.textContent = STATUS_LABEL[t.status] || t.status;
        sBadge.className = 'mn-badge-status ' + (STATUS_CSS[t.status] || '');

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

        // Resolver
        if ((t.status === 'ASSIGNED' || t.status === 'IN_PROGRESS') && ctx.canResolve && (isActiveTech || ctx.isDispatcher)) {
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
            case 'info':       content.innerHTML = _buildInfoTab(_ticket); break;
            case 'technicians': content.innerHTML = _buildTechTab(_ticket);
                window.MaintAssignment && MaintAssignment.bind(_ticket, _reload); break;
            case 'comments':   content.innerHTML = _buildCommentsTab(_ticket); _bindCommentForm(); break;
            case 'resolution': content.innerHTML = _buildResolutionTab(_ticket); _loadMaterials(); break;
            case 'history':    content.innerHTML = _buildHistoryTab(_ticket); break;
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
                    '<div class="col-md-3"><div class="mn-detail-label">Solicitante</div>' +
                        '<div class="mn-detail-value">' + _esc(t.requester ? t.requester.name : '—') + '</div>' +
                        (t.requester_department ? '<small class="text-muted">' + _esc(t.requester_department) + '</small>' : '') + '</div>' +
                    '<div class="col-md-3"><div class="mn-detail-label">SLA / Vencimiento</div>' +
                        '<div class="mn-detail-value ' + slaClass + '">' + slaText + '</div></div>' +
                    '<div class="col-md-3"><div class="mn-detail-label">Creado por</div>' +
                        '<div class="mn-detail-value">' + _esc(t.created_by ? t.created_by.name : '—') + '</div>' +
                        '<small class="text-muted">' + (t.created_at ? new Date(t.created_at).toLocaleString('es-MX') : '') + '</small>' + '</div>' +
                '</div>' +
                customHtml +
            '</div>' +
        '</div>';
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
                html += '<div class="mn-comment-bubble ' + (isInternal ? 'internal' : '') + ' mb-3">' +
                    '<div class="d-flex justify-content-between align-items-start mb-1">' +
                        '<span class="fw-semibold small">' + _esc(c.author ? c.author.name : '—') + '</span>' +
                        '<div class="d-flex align-items-center gap-2">' +
                            (isInternal ? '<span class="badge bg-warning text-dark" style="font-size:0.65rem;">Interno</span>' : '') +
                            '<small class="text-muted">' + (c.created_at ? new Date(c.created_at).toLocaleString('es-MX') : '') + '</small>' +
                        '</div>' +
                    '</div>' +
                    '<div style="white-space:pre-line;">' + _esc(c.content) + '</div>' +
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
                '<button class="btn btn-maint btn-sm" id="sendCommentBtn"><i class="bi bi-send me-1"></i>Enviar</button>' +
            '</div>';
        }

        html += '</div></div>';
        return html;
    }

    function _bindCommentForm() {
        var btn = document.getElementById('sendCommentBtn');
        if (!btn) return;
        btn.addEventListener('click', function () {
            var text = (document.getElementById('newCommentText').value || '').trim();
            if (text.length < 1) return;
            var isInternal = document.getElementById('isInternalCheck') ? document.getElementById('isInternalCheck').checked : false;

            MaintUtils.loading.show(btn, 'Enviando...');
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
                '<div class="col-md-3"><div class="mn-detail-label">Tiempo invertido</div><div>' + (t.time_invested_minutes ? t.time_invested_minutes + ' min' : '—') + '</div></div>' +
                '<div class="col-md-3"><div class="mn-detail-label">Resuelto por</div><div>' + _esc(t.resolved_by ? t.resolved_by.name : '—') + '</div></div>' +
                '<div class="col-12"><div class="mn-detail-label">Notas de resolución</div>' +
                    '<div style="white-space:pre-line;">' + _esc(t.resolution_notes || '—') + '</div></div>' +
                (t.observations ? '<div class="col-12"><div class="mn-detail-label">Observaciones</div>' +
                    '<div>' + _esc(t.observations) + '</div></div>' : '') +
                '<div class="col-12" id="materialsSection">' +
                    '<div class="mn-detail-label"><i class="bi bi-box-seam me-1"></i>Materiales del almacén</div>' +
                    '<div class="text-muted small mt-1"><div class="spinner-border spinner-border-sm me-1" role="status"></div>Cargando...</div>' +
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
            var canAct = (t.status === 'ASSIGNED' || t.status === 'IN_PROGRESS') && ctx.canResolve;
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
                if (!mats.length) {
                    section.innerHTML =
                        '<div class="mn-detail-label"><i class="bi bi-box-seam me-1"></i>Materiales del almacén</div>' +
                        '<div class="text-muted small mt-1">Sin materiales registrados.</div>';
                    return;
                }
                var rows = mats.map(function (m) {
                    return '<div class="d-flex align-items-center gap-2 py-1">' +
                        '<i class="bi bi-box text-secondary"></i>' +
                        '<span class="fw-medium small">' + _esc(m.product_name || 'Producto #' + m.product_id) + '</span>' +
                        '<span class="badge bg-light text-secondary">' + _esc(m.quantity_used) + ' ' + _esc(m.product_unit || '') + '</span>' +
                        (m.notes ? '<span class="text-muted small">— ' + _esc(m.notes) + '</span>' : '') +
                    '</div>';
                });
                section.innerHTML =
                    '<div class="mn-detail-label"><i class="bi bi-box-seam me-1"></i>Materiales del almacén</div>' +
                    '<div class="mt-1">' + rows.join('') + '</div>';
            })
            .catch(function () {
                var section2 = document.getElementById('materialsSection');
                if (section2) section2.innerHTML =
                    '<div class="mn-detail-label"><i class="bi bi-box-seam me-1"></i>Materiales del almacén</div>' +
                    '<div class="text-muted small mt-1">No se pudo cargar.</div>';
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
                    setTimeout(function () { window.location.href = '/maintenance/tickets'; }, 1000);
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

    window._maintDetailReload = _reload;

})();
