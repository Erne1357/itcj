// itcj2/apps/helpdesk/static/js/admin/home.js
//
// Rediseño (2026-08): la página ahora se renderiza ENTERA server-side
// (KPIs, banda de atención, riel de acciones, actividad reciente) — ver
// `pages/admin.py::_query_admin_overview_ctx` / `AdminDashboardService`. Ya
// no hay `loadDashboardStats()` con fetch + relleno manual del DOM: el botón
// "Actualizar" re-navega la página vía `HelpdeskPage.refresh()` (mismo patrón
// que `campaign_detail.js`), que hace un GET boosteado a la misma URL y
// morfea el contenido con datos frescos del servidor — sin flash en blanco,
// sin duplicar la lógica de render en JS.
(function () {
    'use strict';

    function bindRefreshButton() {
        var btn = document.getElementById('hdHomeRefreshBtn');
        if (!btn || btn.dataset.hdBound === '1') return;
        btn.dataset.hdBound = '1';
        btn.addEventListener('click', function () {
            var icon = document.getElementById('hdHomeRefreshIcon');
            if (icon) icon.classList.add('hd-spin');
            btn.disabled = true;
            if (window.HelpdeskPage && typeof window.HelpdeskPage.refresh === 'function') {
                window.HelpdeskPage.refresh();
            } else {
                window.location.reload();
            }
            // Fallback: si el morph tarda o falla, no dejar el botón bloqueado.
            setTimeout(function () {
                btn.disabled = false;
                if (icon) icon.classList.remove('hd-spin');
            }, 1500);
        });
    }

    window.HelpdeskPage.page('admin_home', { init: bindRefreshButton });
})();
