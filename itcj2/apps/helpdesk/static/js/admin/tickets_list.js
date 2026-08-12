// itcj2/apps/helpdesk/static/js/admin/tickets_list.js
//
// PILOTO de componentes server-side: el render de la lista (tarjetas, filtros,
// paginación, empty/error) se movió a macros Jinja + HTMX partial
// (GET /help-desk/admin/tickets-list/partial). Este módulo quedó reducido a:
//   - conteos de resumen (counts globales) vía API,
//   - WebSocket en tiempo real → dispara recarga del partial,
//   - botón "Limpiar" → resetea el form y dispara la recarga.
// Toda la lógica de render/filtro/paginación en JS se eliminó (~250 líneas).
(function () {
    'use strict';

    let socketPoll = null;          // setInterval que espera al socket
    let socketPollTimeout = null;   // timeout de seguridad (5s)
    let silentRefreshTimer = null;  // debounce de refresco por evento de socket
    let _active = false;
    let summaryStats = { total: 0, pending: 0, inProgress: 0, resolved: 0 };

    // ==================== INIT / DESTROY ====================
    function init() {
        _active = true;
        summaryStats = { total: 0, pending: 0, inProgress: 0, resolved: 0 };
        bindClearButton();
        bindFilterChips();
        loadSummaryStats();
        setupWebSocketListeners();
    }

    function destroy() {
        _active = false;
        if (socketPoll) { clearInterval(socketPoll); socketPoll = null; }
        if (socketPollTimeout) { clearTimeout(socketPollTimeout); socketPollTimeout = null; }
        if (silentRefreshTimer) { clearTimeout(silentRefreshTimer); silentRefreshTimer = null; }
        const socket = window.__helpdeskSocket;
        if (socket) {
            socket.off('ticket_created');
            socket.off('ticket_assigned');
            socket.off('ticket_reassigned');
            socket.off('ticket_status_changed');
            socket.off('ticket_self_assigned');
        }
        // Salir del room admin:all — evita eventos duplicados si el usuario morfea
        // a otra página que también une a admin:all sin haber salido primero.
        window.__hdLeaveAdmin?.();
        document.removeEventListener('click', onFilterChipClick);
    }

    // ==================== FILTROS (HTMX) ====================
    function bindClearButton() {
        const btn = document.getElementById('btnClearFilters');
        const form = document.getElementById('hd-filter-form');
        if (!btn || !form) return;
        btn.addEventListener('click', function () {
            form.querySelectorAll('select').forEach((s) => { s.value = ''; });
            form.querySelectorAll('input[type="date"]').forEach((d) => { d.value = ''; });
            const search = document.getElementById('searchInput');
            if (search) search.value = '';
            refreshList();
        });
    }

    // Chips de filtros activos (panel "Más filtros"): cada uno trae un botón
    // data-chip-remove="<param>" que limpia SOLO ese campo del form y refresca.
    // Delegado en `document` (no en #hd-active-chips): cada refresco de filtros
    // reemplaza ese contenedor por un OOB swap (outerHTML), así que un listener
    // atado directamente al nodo se perdería después del primer filtro aplicado.
    function bindFilterChips() {
        document.addEventListener('click', onFilterChipClick);
    }

    function onFilterChipClick(ev) {
        const btn = ev.target.closest('#hd-active-chips [data-chip-remove]');
        if (!btn) return;
        const form = document.getElementById('hd-filter-form');
        const param = btn.getAttribute('data-chip-remove');
        const field = form && form.elements.namedItem(param);
        if (!field) return;
        field.value = '';
        refreshList();
    }

    function refreshList() {
        const form = document.getElementById('hd-filter-form');
        if (form && window.htmx) window.htmx.trigger(form, 'refresh');
    }

    // ==================== SUMMARY STATS (counts globales) ====================
    async function loadSummaryStats() {
        try {
            const [totalResp, pendingResp, inProgressResp, resolvedResp] = await Promise.all([
                HelpdeskUtils.api.getTickets({ per_page: 1, page: 1 }),
                HelpdeskUtils.api.getTickets({ status: 'PENDING', per_page: 1, page: 1 }),
                HelpdeskUtils.api.getTickets({ status: 'ASSIGNED,IN_PROGRESS', per_page: 1, page: 1 }),
                HelpdeskUtils.api.getTickets({ status: 'RESOLVED_SUCCESS,RESOLVED_FAILED,CLOSED', per_page: 1, page: 1 })
            ]);
            if (!_active) return;  // navegó fuera durante el fetch
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

    function updateSummaryCards() {
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        set('totalTickets', summaryStats.total);
        set('pendingTickets', summaryStats.pending);
        set('inProgressTickets', summaryStats.inProgress);
        set('resolvedTickets', summaryStats.resolved);
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
        socketPoll = setInterval(() => {
            if (window.__helpdeskSocket) {
                clearInterval(socketPoll); socketPoll = null;
                bindAdminSocketEvents();
            }
        }, 100);
        socketPollTimeout = setTimeout(() => {
            if (socketPoll) { clearInterval(socketPoll); socketPoll = null; }
        }, 5000);
    }

    function bindAdminSocketEvents() {
        const socket = window.__helpdeskSocket;
        if (!socket) return;
        window.__hdJoinAdmin?.();
        socket.off('ticket_created');
        socket.off('ticket_assigned');
        socket.off('ticket_reassigned');
        socket.off('ticket_status_changed');
        socket.off('ticket_self_assigned');

        socket.on('ticket_created', (data) => {
            if (window.__hdIsOwnEvent?.(data)) return;
            const n = data?.ticket_number ? `#${data.ticket_number}` : '';
            HelpdeskUtils.showToast(`Nuevo ticket ${n} (${data?.area || ''})`, 'info');
            silentRefresh();
        });
        socket.on('ticket_assigned', (data) => {
            if (window.__hdIsOwnEvent?.(data)) return;
            const n = data?.ticket_number ? `#${data.ticket_number}` : '';
            HelpdeskUtils.showToast(`Ticket ${n} asignado`, 'info');
            silentRefresh();
        });
        socket.on('ticket_reassigned', (data) => {
            if (window.__hdIsOwnEvent?.(data)) return;
            const n = data?.ticket_number ? `#${data.ticket_number}` : '';
            HelpdeskUtils.showToast(`Ticket ${n} reasignado`, 'info');
            silentRefresh();
        });
        socket.on('ticket_status_changed', (data) => {
            if (window.__hdIsOwnEvent?.(data)) return;
            const n = data?.ticket_number ? `#${data.ticket_number}` : '';
            HelpdeskUtils.showToast(`Ticket ${n} → ${data?.new_status || ''}`, 'info');
            silentRefresh();
        });
        socket.on('ticket_self_assigned', (data) => {
            if (window.__hdIsOwnEvent?.(data)) return;
            const n = data?.ticket_number ? `#${data.ticket_number}` : '';
            HelpdeskUtils.showToast(`Ticket ${n} auto-asignado`, 'info');
            silentRefresh();
        });
    }

    window.HelpdeskPage.page('admin_tickets_list', { init: init, destroy: destroy });
})();
