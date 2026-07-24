/**
 * Lista de Solicitudes de Baja — migrada a componentes server-side + HTMX.
 * La tabla, los filtros y la paginación los rinde el servidor (ver
 * _retirement_requests_list_results.html + pages/inventory.py). Este módulo
 * conserva SOLO la lógica de cliente: navegación por clic de fila (morph) y el
 * botón Limpiar de la barra de filtros. Sin jQuery.
 */
(function () {
    'use strict';

    // === LISTENER TEARDOWN REFS ===
    let _rowClickHandler = null;
    let _rowKeyHandler = null;
    let _clearHandler = null;

    // Dispara el hx-get del form de filtros (recarga el fragmento server-side).
    function refreshList() {
        const form = document.getElementById('hd-filter-form');
        if (form && window.htmx) window.htmx.trigger(form, 'refresh');
    }

    function bindClearButton() {
        const btn = document.getElementById('btnClearFilters');
        const form = document.getElementById('hd-filter-form');
        if (!btn || !form) return;
        _clearHandler = function () {
            form.querySelectorAll('select').forEach((s) => { s.selectedIndex = 0; });
            const search = document.getElementById('searchInput');
            if (search) search.value = '';
            refreshList();
        };
        btn.addEventListener('click', _clearHandler);
    }

    // Navegación por clic de fila → morph (no recarga completa).
    function navigateRow(tr) {
        const url = tr.getAttribute('data-href');
        if (url) window.HelpdeskPage.navigate(url);
    }

    window.HelpdeskPage.page('inventory_retirement_retirement_requests_list', {
        init() {
            const results = document.getElementById('hd-retirement-results');

            _rowClickHandler = function (e) {
                // El botón "ojo" (o cualquier enlace/botón) maneja su propia acción.
                if (e.target.closest('a, button')) return;
                const tr = e.target.closest('tr[data-href]');
                if (tr) navigateRow(tr);
            };
            _rowKeyHandler = function (e) {
                if (e.key !== 'Enter') return;
                const tr = e.target.closest('tr[data-href]');
                if (tr) { e.preventDefault(); navigateRow(tr); }
            };

            if (results) {
                results.addEventListener('click', _rowClickHandler);
                results.addEventListener('keydown', _rowKeyHandler);
            }

            bindClearButton();
        },

        destroy() {
            const results = document.getElementById('hd-retirement-results');
            if (results && _rowClickHandler) results.removeEventListener('click', _rowClickHandler);
            if (results && _rowKeyHandler) results.removeEventListener('keydown', _rowKeyHandler);

            const btn = document.getElementById('btnClearFilters');
            if (btn && _clearHandler) btn.removeEventListener('click', _clearHandler);

            _rowClickHandler = null;
            _rowKeyHandler = null;
            _clearHandler = null;
        }
    });
})();
