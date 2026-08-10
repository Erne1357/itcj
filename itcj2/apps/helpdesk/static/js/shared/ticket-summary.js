// itcj2/apps/helpdesk/static/js/shared/ticket-summary.js
//
// Modal compartido de resumen de ticket: liga comentarios de calificación
// (stats) y filas de outliers/clustering (analysis) a su ticket sin salir de
// la página. Expone HelpdeskUtils.showTicketSummary(ticketId, {from}).
//
// Requiere que la página incluya el macro
// helpdesk/_components/ticket_summary_modal.html (ticket_summary_modal()) y
// que helpdesk-utils.js ya esté cargado (siempre lo está: base_helpdesk.html
// lo incluye en TODAS las páginas de helpdesk).
//
// Se carga vía HD_PAGE_MODULES (pages/nav.py) solo en las páginas que lo usan
// (admin_stats, admin_analysis) — el controller HelpdeskPage (shared/base.js)
// dedup por src, así que este IIFE corre UNA sola vez por sesión.
(function () {
    'use strict';

    if (!window.HelpdeskUtils) {
        console.error('[TicketSummary] HelpdeskUtils no está cargado — helpdesk-utils.js debe cargar antes.');
        return;
    }

    const API = '/api/help-desk/v2/stats/tickets';

    function esc(s) {
        const d = document.createElement('div');
        d.textContent = s || '';
        return d.innerHTML;
    }

    function fmtHours(h) {
        if (h === null || h === undefined) return '—';
        if (h < 1) return `${Math.round(h * 60)}min`;
        if (h < 24) return `${h.toFixed(1)}h`;
        return `${(h / 24).toFixed(1)}d`;
    }

    function metaRow(label, value) {
        if (value === null || value === undefined || value === '') return '';
        return `<div class="col"><span class="text-muted">${esc(label)}:</span> <strong>${esc(String(value))}</strong></div>`;
    }

    function showLoading() {
        document.getElementById('ticketSummaryLoading')?.classList.remove('d-none');
        document.getElementById('ticketSummaryError')?.classList.add('d-none');
        document.getElementById('ticketSummaryContent')?.classList.add('d-none');
    }

    function showError(message) {
        document.getElementById('ticketSummaryLoading')?.classList.add('d-none');
        document.getElementById('ticketSummaryContent')?.classList.add('d-none');
        const err = document.getElementById('ticketSummaryError');
        if (err) {
            // Mensaje propio (no HTML del servidor) — no requiere escape, pero
            // se usa textContent de todas formas por si algún día viaja detail.
            err.textContent = message;
            err.classList.remove('d-none');
        }
    }

    // Todo lo que viene de `d` es del servidor: se pasa por esc() o se asigna
    // con textContent, nunca directo a innerHTML.
    function render(d) {
        document.getElementById('ticketSummaryLoading')?.classList.add('d-none');
        document.getElementById('ticketSummaryError')?.classList.add('d-none');

        const numberEl = document.getElementById('ticketSummaryNumber');
        if (numberEl) numberEl.textContent = d.ticket_number || `#${d.id}`;

        const titleEl = document.getElementById('ticketSummaryTitle');
        if (titleEl) titleEl.textContent = d.title || '';

        const descEl = document.getElementById('ticketSummaryDescription');
        if (descEl) descEl.textContent = d.description || '';

        const badgesEl = document.getElementById('ticketSummaryBadges');
        if (badgesEl) {
            badgesEl.innerHTML =
                HelpdeskUtils.getStatusBadge(d.status) +
                HelpdeskUtils.getPriorityBadge(d.priority) +
                HelpdeskUtils.getAreaBadge(d.area);
        }

        const metaEl = document.getElementById('ticketSummaryMeta');
        if (metaEl) {
            metaEl.innerHTML = [
                metaRow('Categoría', d.category_name),
                metaRow('Solicitante', d.requester_name),
                metaRow('Asignado a', d.assigned_to_name),
                metaRow('Departamento', d.department_name),
                metaRow('Creado', HelpdeskUtils.formatDate(d.created_at)),
                metaRow('Resuelto', d.resolved_at ? HelpdeskUtils.formatDate(d.resolved_at) : '—'),
                metaRow('Tiempo de resolución', fmtHours(d.resolution_hours)),
                metaRow('Tiempo invertido', fmtHours(d.time_invested_hours)),
            ].join('');
        }

        const ratingBlock = document.getElementById('ticketSummaryRatingBlock');
        if (ratingBlock) {
            const hasRating = d.rating_attention || d.rating_speed || d.rating_comment;
            ratingBlock.classList.toggle('d-none', !hasRating);
            if (hasRating) {
                const attEl = document.getElementById('ticketSummaryRatingAtt');
                const spdEl = document.getElementById('ticketSummaryRatingSpd');
                if (attEl) attEl.innerHTML = d.rating_attention ? HelpdeskUtils.renderStarRating(d.rating_attention) : '—';
                if (spdEl) spdEl.innerHTML = d.rating_speed ? HelpdeskUtils.renderStarRating(d.rating_speed) : '—';

                const commentEl = document.getElementById('ticketSummaryRatingComment');
                if (commentEl) {
                    commentEl.textContent = d.rating_comment || '';
                    commentEl.classList.toggle('d-none', !d.rating_comment);
                }
            }
        }

        document.getElementById('ticketSummaryContent')?.classList.remove('d-none');
    }

    function wireFooterButtons(ticketId, from) {
        const openBtn = document.getElementById('ticketSummaryOpenBtn');
        if (openBtn) {
            openBtn.onclick = function () {
                const modalEl = document.getElementById('ticketSummaryModal');
                const inst = modalEl && window.bootstrap && bootstrap.Modal.getInstance(modalEl);
                if (inst) inst.hide();
                // goToTicketDetail navega por morph (como el resto de la app) y
                // arma la URL con `?from=` para que el botón "Volver" del
                // detalle sepa que viene de stats/analysis.
                HelpdeskUtils.goToTicketDetail(ticketId, from);
            };
        }

        const newTabBtn = document.getElementById('ticketSummaryNewTabBtn');
        if (newTabBtn) {
            newTabBtn.onclick = function () {
                HelpdeskUtils.goToTicketDetailNewTab(ticketId, from);
            };
        }
    }

    /**
     * Abre el modal de resumen de un ticket y carga su información.
     * @param {number} ticketId
     * @param {{from?: string}} [opts] - `from`: slug de origen ('stats'|'analysis')
     *   para el botón "Abrir ticket" (ver pages/origins.py).
     */
    async function showTicketSummary(ticketId, opts) {
        const modalEl = document.getElementById('ticketSummaryModal');
        if (!modalEl || !window.bootstrap) {
            console.error('[TicketSummary] Falta el modal en la página (incluir ticket_summary_modal()).');
            return;
        }
        const from = (opts && opts.from) || null;

        wireFooterButtons(ticketId, from);
        showLoading();
        bootstrap.Modal.getOrCreateInstance(modalEl).show();

        try {
            const res = await fetch(`${API}/${ticketId}/summary`, { credentials: 'include' });
            const json = await res.json().catch(() => ({}));
            // Formato de error del proyecto: {"error": {...}, "status": N}
            // (itcj2/main.py::http_exception_handler) — NO {"detail": ...}.
            if (!res.ok || !json.success) {
                const errObj = json && json.error;
                const msg = (errObj && typeof errObj === 'object' && errObj.message)
                    || (typeof errObj === 'string' ? errObj : null)
                    || `No se pudo cargar el ticket (HTTP ${res.status}).`;
                throw new Error(msg);
            }
            render(json.data);
        } catch (err) {
            console.error('[TicketSummary] Error cargando resumen:', err);
            showError(err.message || 'No se pudo cargar el resumen del ticket.');
        }
    }

    window.HelpdeskUtils.showTicketSummary = showTicketSummary;
})();
