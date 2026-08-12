// itcj2/apps/helpdesk/static/js/user/my_tickets.js
//
// Migrado a componentes server-side + HTMX (docs/auditoria_ui_helpdesk.md §8):
// la lista (tarjetas, filtros, paginación, empty) la rinde el server (macros
// Jinja + fragmento HTMX). Este módulo quedó reducido a lo genuinamente cliente:
//   - conteos de resumen (counts) vía API,
//   - WebSocket en tiempo real → dispara recarga del fragmento (htmx refresh),
//   - botón "Limpiar" → resetea el form y recarga,
//   - modales de Calificar / Cancelar (interacción de cliente),
//   - ISLA de modo TUTORIAL: rinde el ticket de ejemplo (fake, en memoria) en el
//     contenedor de resultados, porque ese ticket NO existe en BD (§4.3).
(function () {
    'use strict';

    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    let _active = false;
    let summaryStats = { total: 0, active: 0, resolved: 0, pendingRating: 0 };

    // Modales (sin allTickets: los datos vienen del dataset del botón)
    let ratingAttention = 0;
    let ratingSpeed = 0;
    let ratingEfficiency = null;
    let ticketToRateId = null;
    let ticketToCancelId = null;

    // WebSocket
    let userSocketBound = false;
    let socketCheckInterval = null;
    let socketSafetyTimeout = null;
    let silentRefreshTimer = null;

    // ==================== INIT / DESTROY ====================
    function init() {
        _active = true;
        summaryStats = { total: 0, active: 0, resolved: 0, pendingRating: 0 };
        ratingAttention = 0; ratingSpeed = 0; ratingEfficiency = null;
        ticketToRateId = null; ticketToCancelId = null;
        userSocketBound = false;

        // Funciones globales que usan los onclick de las tarjetas server-rendered.
        window.openRatingModal = openRatingModal;
        window.openCancelModal = openCancelModal;

        bindClearButton();
        setupRatingModal();
        setupCancelModal();

        if (isTutorialMode()) {
            // Isla: render del ticket de ejemplo (no está en BD). Compat con el
            // tutorial, que vuelve a llamar window.loadMyTickets tras arrancar.
            window.loadMyTickets = renderTutorialCard;
            renderTutorialCard();
            setTutorialSummary();
        } else {
            loadSummaryStats();
            setTimeout(setupWebSocketListeners, 500);
        }

        // Arranque del tutorial si corresponde (flujo create_ticket → my_tickets).
        window.helpdeskTutorial?.maybeAutoStart('my_tickets');
    }

    function destroy() {
        _active = false;
        const socket = window.__helpdeskSocket;
        if (socket) {
            socket.off('ticket_status_changed');
            socket.off('ticket_assigned');
            socket.off('ticket_comment_added');
        }
        if (socketCheckInterval) { clearInterval(socketCheckInterval); socketCheckInterval = null; }
        if (socketSafetyTimeout) { clearTimeout(socketSafetyTimeout); socketSafetyTimeout = null; }
        if (silentRefreshTimer) { clearTimeout(silentRefreshTimer); silentRefreshTimer = null; }
        userSocketBound = false;

        disposeModal('ratingModal');
        disposeModal('cancelModal');

        delete window.openRatingModal;
        delete window.openCancelModal;
        delete window.loadMyTickets;

        window.helpdeskTutorial?.teardown();
    }

    function disposeModal(id) {
        const el = document.getElementById(id);
        if (!el) return;
        try { bootstrap.Modal.getInstance(el)?.dispose(); } catch (e) { /* ignore */ }
    }

    // ==================== FILTROS (HTMX) ====================
    function bindClearButton() {
        const btn = document.getElementById('btnClearFilters');
        const form = document.getElementById('hd-filter-form');
        if (!btn || !form) return;
        btn.addEventListener('click', function () {
            form.querySelectorAll('select').forEach((s) => { s.value = ''; });
            const search = document.getElementById('searchInput');
            if (search) search.value = '';
            refreshList();
        });
    }

    function refreshList() {
        const form = document.getElementById('hd-filter-form');
        if (form && window.htmx) window.htmx.trigger(form, 'refresh');
    }

    // ==================== SUMMARY STATS ====================
    async function loadSummaryStats() {
        try {
            const [totalResp, activeResp, resolvedResp, ratingResp] = await Promise.all([
                HelpdeskUtils.api.getTickets({ created_by_me: true, per_page: 1, page: 1 }),
                HelpdeskUtils.api.getTickets({ created_by_me: true, status: 'PENDING,ASSIGNED,IN_PROGRESS', per_page: 1, page: 1 }),
                HelpdeskUtils.api.getTickets({ created_by_me: true, status: 'RESOLVED_SUCCESS,RESOLVED_FAILED,CLOSED', per_page: 1, page: 1 }),
                HelpdeskUtils.api.getTickets({ created_by_me: true, status: 'RESOLVED_SUCCESS,RESOLVED_FAILED', per_page: 1, page: 1 })
            ]);
            if (!_active) return;
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

    function updateSummaryCards() {
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        set('totalTickets', summaryStats.total);
        set('activeTickets', summaryStats.active);
        set('resolvedTickets', summaryStats.resolved);
        set('pendingRating', summaryStats.pendingRating);
    }

    function setTutorialSummary() {
        summaryStats = { total: 1, active: 1, resolved: 0, pendingRating: 0 };
        updateSummaryCards();
    }

    // ==================== TUTORIAL ISLAND ====================
    function isTutorialMode() {
        return typeof window.isTutorialModeActive === 'function' && window.isTutorialModeActive();
    }

    function renderTutorialCard() {
        const container = document.getElementById('hd-tickets-results');
        if (!container) return;
        const data = typeof window.getTutorialTicketData === 'function' ? window.getTutorialTicketData() : null;
        const t = data && data.ticket;
        if (!t) return;
        // Clases hd-ticket-card (estilo unificado) + ticket-card (hook que el
        // tutorial usa en attachTo). Incluye un .btn-primary como ancla del paso.
        container.innerHTML = `
            <a class="hd-ticket-card ticket-card" href="/help-desk/user/tickets/${t.id}?from=my_tickets&tutorial=true">
              <div class="row g-3">
                <div class="col-md-9">
                  <div class="d-flex align-items-center flex-wrap gap-2 mb-1">
                    <span class="fw-bold text-primary">${escapeHtml(t.ticket_number || '')}</span>
                    ${HelpdeskUtils.getAreaBadge(t.area)}
                    ${HelpdeskUtils.getPriorityBadge(t.priority)}
                  </div>
                  <div class="hd-ticket-card__title">${escapeHtml(t.title || '')}</div>
                  <div class="hd-ticket-card__desc">${escapeHtml(t.description || '')}</div>
                </div>
                <div class="col-md-3">
                  <div class="hd-ticket-card__label">Estado</div>
                  <div class="mb-2">${HelpdeskUtils.getStatusBadge(t.status)}</div>
                  <div class="mt-2 d-flex flex-column gap-2" onclick="event.stopPropagation()">
                    <a class="btn btn-primary btn-sm w-100" href="/help-desk/user/tickets/${t.id}?from=my_tickets&tutorial=true">
                      <i class="fas fa-eye me-1"></i>Abrir
                    </a>
                  </div>
                </div>
              </div>
            </a>`;
    }

    // ==================== WEBSOCKET REAL-TIME ====================
    function silentRefresh() {
        clearTimeout(silentRefreshTimer);
        silentRefreshTimer = setTimeout(() => {
            if (!_active) return;
            loadSummaryStats();
            refreshList();
        }, 500);
    }

    function setupWebSocketListeners() {
        socketCheckInterval = setInterval(() => {
            if (!_active) { clearInterval(socketCheckInterval); socketCheckInterval = null; return; }
            if (window.__helpdeskSocket) {
                clearInterval(socketCheckInterval); socketCheckInterval = null;
                bindUserSocketEvents();
            }
        }, 100);
        socketSafetyTimeout = setTimeout(() => {
            socketSafetyTimeout = null;
            if (socketCheckInterval) { clearInterval(socketCheckInterval); socketCheckInterval = null; }
        }, 5000);
    }

    function bindUserSocketEvents() {
        if (!_active || userSocketBound) return;
        const socket = window.__helpdeskSocket;
        if (!socket) return;

        socket.off('ticket_status_changed');
        socket.off('ticket_assigned');
        socket.off('ticket_comment_added');

        socket.on('ticket_status_changed', (data) => {
            HelpdeskUtils.showToast(`Ticket ${data.ticket_number}: estado actualizado`, 'info');
            silentRefresh();
        });
        socket.on('ticket_assigned', (data) => {
            HelpdeskUtils.showToast(`Tu ticket fue asignado a ${data.assigned_to_name || ''}`, 'info');
            silentRefresh();
        });
        socket.on('ticket_comment_added', (data) => {
            HelpdeskUtils.showToast(`Nuevo comentario en ${data.ticket_number || 'tu ticket'}`, 'info');
        });

        userSocketBound = true;
    }

    // ==================== RATING MODAL ====================
    function setupRatingModal() {
        document.querySelectorAll('.star-btn-attention').forEach(btn => {
            btn.addEventListener('click', () => {
                ratingAttention = parseInt(btn.dataset.rating);
                updateStarButtons();
                checkRatingFormValidity();
            });
        });
        document.querySelectorAll('.star-btn-speed').forEach(btn => {
            btn.addEventListener('click', () => {
                ratingSpeed = parseInt(btn.dataset.rating);
                updateStarButtons();
                checkRatingFormValidity();
            });
        });
        document.querySelectorAll('input[name="ratingEfficiency"]').forEach(radio => {
            radio.addEventListener('change', () => {
                ratingEfficiency = radio.value === 'true';
                checkRatingFormValidity();
            });
        });
        const submit = document.getElementById('btnSubmitRating');
        if (submit) submit.addEventListener('click', submitRating);
    }

    function openRatingModal(btn) {
        ticketToRateId = parseInt(btn.dataset.id);
        ratingAttention = 0; ratingSpeed = 0; ratingEfficiency = null;

        const summary = document.getElementById('ratingTicketSummary');
        if (summary) {
            summary.innerHTML = `
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <strong>${escapeHtml(btn.dataset.number || '')}</strong>
                        <p class="mb-0 text-muted small">${escapeHtml(btn.dataset.title || '')}</p>
                    </div>
                    ${HelpdeskUtils.getStatusBadge(btn.dataset.status)}
                </div>`;
        }

        updateStarButtons();
        const comment = document.getElementById('ratingComment');
        if (comment) comment.value = '';
        document.querySelectorAll('input[name="ratingEfficiency"]').forEach(r => { r.checked = false; });

        const submitBtn = document.getElementById('btnSubmitRating');
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-paper-plane me-2"></i>Enviar Calificación';

        bootstrap.Modal.getOrCreateInstance(document.getElementById('ratingModal')).show();
    }

    function updateStarButtons() {
        const paint = (selector, value) => {
            document.querySelectorAll(selector).forEach(btn => {
                const rating = parseInt(btn.dataset.rating);
                const icon = btn.querySelector('i');
                if (rating <= value) {
                    btn.classList.add('active');
                    icon.classList.replace('far', 'fas');
                } else {
                    btn.classList.remove('active');
                    icon.classList.replace('fas', 'far');
                }
            });
        };
        paint('.star-btn-attention', ratingAttention);
        paint('.star-btn-speed', ratingSpeed);
    }

    function checkRatingFormValidity() {
        const ok = ratingAttention > 0 && ratingSpeed > 0 && ratingEfficiency !== null;
        document.getElementById('btnSubmitRating').disabled = !ok;
    }

    async function submitRating() {
        if (ratingAttention === 0 || ratingSpeed === 0 || ratingEfficiency === null) {
            HelpdeskUtils.showToast('Por favor completa todos los campos obligatorios', 'warning');
            return;
        }
        const submitBtn = document.getElementById('btnSubmitRating');
        const original = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Enviando...';
        try {
            await HelpdeskUtils.api.rateTicket(ticketToRateId, {
                rating_attention: ratingAttention,
                rating_speed: ratingSpeed,
                rating_efficiency: ratingEfficiency,
                comment: (document.getElementById('ratingComment').value || '').trim() || null
            });
            HelpdeskUtils.showToast('¡Gracias por tu evaluación!', 'success');
            bootstrap.Modal.getInstance(document.getElementById('ratingModal'))?.hide();
            refreshList();
            loadSummaryStats();
        } catch (error) {
            console.error('Error submitting rating:', error);
            HelpdeskUtils.showToast(error.message || 'Error al enviar calificación', 'error');
            submitBtn.disabled = false;
            submitBtn.innerHTML = original;
        }
    }

    // ==================== CANCEL MODAL ====================
    function setupCancelModal() {
        const btn = document.getElementById('btnConfirmCancel');
        if (btn) btn.addEventListener('click', confirmCancel);
    }

    function openCancelModal(btn) {
        ticketToCancelId = parseInt(btn.dataset.id);
        const info = document.getElementById('cancelTicketInfo');
        if (info) info.textContent = `Ticket ${btn.dataset.number}: ${btn.dataset.title}`;
        const reason = document.getElementById('cancelReason');
        if (reason) reason.value = '';
        bootstrap.Modal.getOrCreateInstance(document.getElementById('cancelModal')).show();
    }

    async function confirmCancel() {
        if (!ticketToCancelId) return;
        const confirmBtn = document.getElementById('btnConfirmCancel');
        const original = confirmBtn.innerHTML;
        confirmBtn.disabled = true;
        confirmBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Cancelando...';
        try {
            const reason = (document.getElementById('cancelReason').value || '').trim();
            await HelpdeskUtils.api.cancelTicket(ticketToCancelId, reason || null);
            HelpdeskUtils.showToast('Ticket cancelado exitosamente', 'success');
            bootstrap.Modal.getInstance(document.getElementById('cancelModal'))?.hide();
            refreshList();
            loadSummaryStats();
        } catch (error) {
            console.error('Error canceling ticket:', error);
            HelpdeskUtils.showToast(error.message || 'Error al cancelar ticket', 'error');
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = original;
        }
    }

    // ==================== REGISTRO EN EL CONTROLLER ====================
    window.HelpdeskPage.page('user_my_tickets', { init, destroy });
})();
