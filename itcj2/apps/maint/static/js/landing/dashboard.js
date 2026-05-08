/**
 * landing/dashboard.js — Mantenimiento
 * KPI cards y actividad reciente en la landing page.
 * Fetch GET /api/maint/v2/dashboard y renderiza en #mn-kpi-section y #mn-activity-section.
 */
(function () {
    'use strict';

    var API_URL = '/api/maint/v2/dashboard';

    // ──────────────────────────────────────────────────────────────────────────
    // Labels de estado para la actividad reciente
    // ──────────────────────────────────────────────────────────────────────────
    var ACTION_LABELS = {
        CREATED:                 'Ticket creado',
        TECHNICIAN_ASSIGNED:     'Técnico asignado',
        TECHNICIAN_UNASSIGNED:   'Técnico removido',
        STATUS_CHANGED:          'Estado actualizado',
        RESOLVED_BY_ASSIGNED:    'Resuelto por técnico',
        RESOLVED_BY_DISPATCHER:  'Resuelto por dispatcher',
        RATED:                   'Calificado',
        COMMENTED:               'Comentario agregado',
        ATTACHMENT_ADDED:        'Archivo adjunto',
        EDITED:                  'Ticket editado',
        CANCELED:                'Cancelado',
        WAREHOUSE_MATERIAL_ADDED:'Material registrado',
    };

    var STATUS_LABELS = {
        PENDING:          'Pendiente',
        ASSIGNED:         'Asignado',
        IN_PROGRESS:      'En progreso',
        RESOLVED_SUCCESS: 'Resuelto',
        RESOLVED_FAILED:  'Resuelto (fallido)',
        CLOSED:           'Cerrado',
        CANCELED:         'Cancelado',
    };

    // ──────────────────────────────────────────────────────────────────────────
    // Utilidades
    // ──────────────────────────────────────────────────────────────────────────

    function formatDatetime(iso) {
        if (!iso) return '—';
        try {
            var d = new Date(iso);
            return d.toLocaleDateString('es-MX', {
                day: '2-digit', month: 'short', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
            });
        } catch (_) {
            return iso;
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Render KPI cards
    // ──────────────────────────────────────────────────────────────────────────

    function renderKpis(data, roleHint) {
        var kpiGrid = document.getElementById('mn-kpi-grid');
        if (!kpiGrid) return;

        // Determinar la 4.ª card según roleHint expuesto en el HTML
        var fourthCard;
        if (roleHint === 'privileged' && data.activity_24h !== null && data.activity_24h !== undefined) {
            fourthCard = buildCard(
                'mn-kpi--activity',
                'bi-activity',
                data.activity_24h,
                'Actividad (24 h)',
                'Acciones registradas hoy',
                null
            );
        } else if (data.last_ticket) {
            fourthCard = buildCard(
                'mn-kpi--last',
                'bi-ticket',
                null,
                'Mi última solicitud',
                data.last_ticket.ticket_number,
                STATUS_LABELS[data.last_ticket.status] || data.last_ticket.status
            );
        } else {
            fourthCard = buildCard(
                'mn-kpi--last',
                'bi-ticket',
                '—',
                'Mi última solicitud',
                'Sin solicitudes',
                null
            );
        }

        var overdueCls = data.overdue > 0 ? 'mn-kpi--danger' : '';
        var unratedCls = data.unrated_resolved > 0 ? 'mn-kpi--warning' : '';

        var html = [
            buildCard('mn-kpi--open', 'bi-folder2-open', data.open_total, 'Abiertas', 'Solicitudes activas', null),
            buildCard('mn-kpi--overdue ' + overdueCls, 'bi-alarm', data.overdue, 'Vencidas', 'Fuera de plazo SLA', null),
            buildCard('mn-kpi--unrated ' + unratedCls, 'bi-star', data.unrated_resolved, 'Sin calificar', 'Tus solicitudes pendientes de calificar', null),
            fourthCard,
        ].join('');

        kpiGrid.innerHTML = html;

        // Mostrar banner si hay solicitudes sin calificar
        if (data.unrated_resolved > 0) {
            var banner = document.getElementById('mn-unrated-banner');
            if (banner) {
                banner.querySelector('.mn-unrated-count').textContent = data.unrated_resolved;
                banner.classList.remove('d-none');
            }
        }
    }

    function buildCard(extraClass, icon, value, label, sub, badge) {
        var valueHtml = (value !== null && value !== undefined)
            ? '<div class="mn-kpi-value">' + value + '</div>'
            : '<div class="mn-kpi-value text-muted" style="font-size:1rem">' + (sub || '—') + '</div>';

        var subHtml = (value !== null && value !== undefined && sub)
            ? '<div class="mn-kpi-sub">' + escHtml(sub) + '</div>'
            : '';

        var badgeHtml = badge
            ? '<span class="badge mn-kpi-badge">' + escHtml(badge) + '</span>'
            : '';

        return (
            '<div class="col-6 col-md-3">' +
            '<div class="mn-kpi-card card shadow-sm ' + extraClass + '">' +
            '<div class="card-body d-flex align-items-center gap-3 p-3">' +
            '<div class="mn-kpi-icon flex-shrink-0"><i class="bi ' + icon + '"></i></div>' +
            '<div class="mn-kpi-body">' +
            valueHtml + subHtml + badgeHtml +
            '<div class="mn-kpi-label">' + escHtml(label) + '</div>' +
            '</div>' +
            '</div>' +
            '</div>' +
            '</div>'
        );
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Render actividad reciente
    // ──────────────────────────────────────────────────────────────────────────

    function renderActivity(items) {
        var section = document.getElementById('mn-activity-section');
        if (!section) return;
        if (!items || items.length === 0) {
            section.classList.add('d-none');
            return;
        }

        var timeline = document.getElementById('mn-activity-timeline');
        if (!timeline) return;

        var html = items.map(function (item) {
            var label = ACTION_LABELS[item.action] || item.action;
            return (
                '<div class="mn-activity-item">' +
                '<div class="mn-activity-dot"></div>' +
                '<div class="mn-activity-content">' +
                '<div class="mn-activity-action">' + escHtml(label) + '</div>' +
                '<div class="mn-activity-meta">' +
                '<a href="/maintenance/tickets/' + item.ticket_id + '" class="mn-activity-ticket">' +
                escHtml(item.ticket_number) + '</a>' +
                '<span class="mn-activity-by">por ' + escHtml(item.performed_by) + '</span>' +
                '<span class="mn-activity-time">' + formatDatetime(item.performed_at) + '</span>' +
                '</div>' +
                '</div>' +
                '</div>'
            );
        }).join('');

        timeline.innerHTML = html;
        section.classList.remove('d-none');
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Skeleton loading
    // ──────────────────────────────────────────────────────────────────────────

    function showSkeletons() {
        var kpiGrid = document.getElementById('mn-kpi-grid');
        if (!kpiGrid) return;
        var skel = '';
        for (var i = 0; i < 4; i++) {
            skel += (
                '<div class="col-6 col-md-3">' +
                '<div class="mn-kpi-card card shadow-sm">' +
                '<div class="card-body d-flex align-items-center gap-3 p-3">' +
                '<div class="mn-kpi-icon flex-shrink-0 mn-skeleton" style="border-radius:10px"></div>' +
                '<div class="mn-kpi-body w-100">' +
                '<div class="mn-skeleton mn-skeleton--value mb-1"></div>' +
                '<div class="mn-skeleton mn-skeleton--label"></div>' +
                '</div>' +
                '</div>' +
                '</div>' +
                '</div>'
            );
        }
        kpiGrid.innerHTML = skel;
    }

    function hideKpisSection() {
        var wrap = document.getElementById('mn-kpi-section');
        if (wrap) wrap.classList.add('d-none');
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Escape HTML básico
    // ──────────────────────────────────────────────────────────────────────────

    function escHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Init
    // ──────────────────────────────────────────────────────────────────────────

    function init() {
        var kpiSection = document.getElementById('mn-kpi-section');
        if (!kpiSection) return;  // Página sin KPIs — nada que hacer

        var roleHint = kpiSection.dataset.roleHint || 'staff';

        showSkeletons();

        fetch(API_URL, { credentials: 'include' })
            .then(function (res) {
                if (!res.ok) throw new Error('HTTP ' + res.status);
                return res.json();
            })
            .then(function (json) {
                if (!json.success || !json.data) throw new Error('Respuesta inválida');
                renderKpis(json.data, roleHint);
                renderActivity(json.data.recent_activity);
            })
            .catch(function (err) {
                console.warn('[maint dashboard] Error cargando KPIs:', err);
                hideKpisSection();
            });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
