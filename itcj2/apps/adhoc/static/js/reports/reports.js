/**
 * reports/reports.js — Centro de Reportes: elección + filtros + vista previa.
 *
 * Expone SOLO `window.AdhocReports` (IIFE, sin globales sueltas).
 * Se carga en `/adhoc/reportes`.
 *
 * QUÉ SUSTITUYE
 * -------------
 * `control_panel/reports.js` del legacy (clase `ReportsManager`, global suelta):
 *   · Abría/cerraba a mano DOS `.modal-overlay` con `style.display='flex'`.
 *     Aquí es UN modal de Bootstrap 5.3 que conmuta la vista previa.
 *   · Escribía el título con `innerHTML = '... ' + reportTitle` — el título
 *     venía de un `data-title` del DOM, pero el patrón (concatenar sin escapar)
 *     es el mismo que provocaba los XSS del resto de la app. Aquí todo pasa por
 *     `AdhocUtils.escapeHtml`.
 *   · Filtraba las filas por ÍNDICE DE COLUMNA (`cells[index]`), así que un
 *     `<td>` de más desalineaba los tres filtros. Aquí se filtra sobre los
 *     datos, no sobre el DOM, y las filas se repintan.
 *   · "Documentos y Notas" abría un modal cuyo pie solo tenía "Cerrar": el
 *     reporte era inalcanzable desde la interfaz. Ahora usa el mismo formulario
 *     que los otros cuatro.
 *
 * page_data esperado (lo emite pages/reports.py con ReportService.get_selection_data):
 *   { reports: [...], areas: [...],
 *     users:            [{first_name, last_name, areas}],
 *     users_diffusion:  [{first_name, last_name, areas}],
 *     documents:        [{code, title, author, area, status, version, created_at, notes}] }
 *
 * DOS EJES, NO UNO
 * ----------------
 * `subject` ("users" | "documents") dice qué PANEL se enseña y con qué columnas
 * y filtros. `preview` ("users" | "users_diffusion" | "documents") dice de qué
 * COLECCIÓN salen las filas. Eran la misma clave hasta que "Difusión
 * Documental" dejó de partir de `_fetch_users` (29 personas con acceso) y pasó
 * a partir de `_fetch_users_with_visibility` (55 con difusión): 30 personas
 * están en el reporte y no en aquella lista, así que la previa contestaba "0
 * coincidencias" a filtros que en el reporte devuelven filas. Como las dos
 * colecciones de personas tienen la misma forma, comparten panel: lo único que
 * cambia es de dónde se leen las filas.
 *
 * MARCADO
 * -------
 *   <button data-adhoc-report="{tipo}" data-adhoc-report-label data-adhoc-report-subject
 *           data-adhoc-report-preview>
 *   <form id="adhoc-report-form">                 action = /adhoc/reportes/{tipo}
 *   <input|select data-adhoc-report-filter="nombre|apellidos|area">
 *   <button data-adhoc-report-clear>            "Limpiar" del legacy
 *   <button data-adhoc-report-search>           "Buscar" del legacy (repinta)
 *   <div data-adhoc-preview="users|documents">    contenedor de cada tabla
 *   <span data-adhoc-preview-count>               "N de M"
 *
 * Los listeners son DELEGADOS sobre `document`, así que sobreviven a los swaps
 * de HTMX (`hx-boost` en el nav) sin volver a engancharse.
 */
(function () {
    'use strict';

    // Re-ejecución idempotente: con hx-boost, HTMX vuelve a insertar (y a
    // ejecutar) los <script> de la página que entra. Los listeners de este
    // módulo son DELEGADOS sobre `document` y siguen vivos tras el swap, así
    // que una segunda ejecución solo serviría para duplicarlos.
    if (window.AdhocReports) return;

    var U = window.AdhocUtils;

    var MODAL_ID = 'adhoc-report-modal';
    var FORM_ID = 'adhoc-report-form';
    var BASE_URL = '/adhoc/reportes/';

    /** Techo de filas pintadas en la vista previa. No limita el reporte: solo
     *  evita meter miles de <tr> en un modal para "echar un vistazo". */
    var PREVIEW_LIMIT = 300;

    /** Columnas de cada vista previa, en el mismo orden que el <thead> del template. */
    var PREVIEW_COLUMNS = {
        users: ['first_name', 'last_name', 'areas'],
        documents: ['code', 'title', 'author', 'area', 'status', 'version', 'created_at', 'notes']
    };

    /** Qué campos mira cada filtro en cada vista previa. */
    var FILTER_FIELDS = {
        users: { nombre: ['first_name'], apellidos: ['last_name'], area: ['areas'] },
        documents: { nombre: ['code', 'title'], apellidos: ['author'], area: ['area'] }
    };

    var _bound = false;

    // ==================== HELPERS ====================

    /** minúsculas + sin acentos, para comparar como lo hace el ILIKE del servidor. */
    function normalize(value) {
        var text = (value === null || value === undefined) ? '' : String(value);
        if (text.normalize) {
            text = text.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        }
        return text.toLowerCase().trim();
    }

    function escape(value) {
        if (U && typeof U.escapeHtml === 'function') return U.escapeHtml(value);
        return String(value === null || value === undefined ? '' : value);
    }

    function data() {
        return (U && typeof U.pageData === 'function') ? U.pageData() : {};
    }

    function modalEl() {
        return document.getElementById(MODAL_ID);
    }

    function formEl() {
        return document.getElementById(FORM_ID);
    }

    function filterInputs() {
        return document.querySelectorAll('[data-adhoc-report-filter]');
    }

    /** Valores actuales de los tres filtros del formulario. */
    function currentFilters() {
        var out = { nombre: '', apellidos: '', area: '' };
        var inputs = filterInputs();
        for (var i = 0; i < inputs.length; i++) {
            var key = inputs[i].getAttribute('data-adhoc-report-filter');
            if (key in out) out[key] = inputs[i].value || '';
        }
        return out;
    }

    // ==================== FILTRADO Y PINTADO ====================

    /**
     * Aplica los filtros sobre los DATOS (no sobre el DOM).
     * `area` compara por igualdad —viene de un <select> con el nombre exacto—
     * salvo en usuarios, donde la celda puede listar varias áreas separadas por
     * coma y basta con que una coincida.
     */
    function filterRows(subject, rows, filters) {
        var fields = FILTER_FIELDS[subject] || FILTER_FIELDS.users;

        return rows.filter(function (row) {
            var key, needle, haystack, i, ok;

            for (key in fields) {
                if (!Object.prototype.hasOwnProperty.call(fields, key)) continue;
                needle = normalize(filters[key]);
                if (!needle) continue;

                if (key === 'area') {
                    ok = false;
                    for (i = 0; i < fields[key].length; i++) {
                        haystack = normalize(row[fields[key][i]]);
                        if (haystack === needle) { ok = true; break; }
                        // "Área A, Área B" → cualquiera de las dos vale.
                        if (haystack.split(',').some(function (part) {
                            return part.trim() === needle;
                        })) { ok = true; break; }
                    }
                    if (!ok) return false;
                    continue;
                }

                ok = false;
                for (i = 0; i < fields[key].length; i++) {
                    if (normalize(row[fields[key][i]]).indexOf(needle) !== -1) { ok = true; break; }
                }
                if (!ok) return false;
            }
            return true;
        });
    }

    function rowsHtml(subject, rows) {
        var columns = PREVIEW_COLUMNS[subject] || [];
        var html = '';
        var i, c;

        for (i = 0; i < rows.length; i++) {
            html += '<tr>';
            for (c = 0; c < columns.length; c++) {
                html += '<td data-adhoc-cell="' + columns[c] + '">' +
                        escape(rows[i][columns[c]]) + '</td>';
            }
            html += '</tr>';
        }
        return html;
    }

    /**
     * Reemplaza las filas del <tbody> conservando la fila de estado vacío que
     * emite la macro `data_table` (el CSS la esconde sola cuando hay filas).
     */
    function paint(tbody, html) {
        if (!tbody) return;
        var stale = tbody.querySelectorAll('tr:not([data-adhoc-empty])');
        for (var i = 0; i < stale.length; i++) stale[i].remove();

        var empty = tbody.querySelector('[data-adhoc-empty]');
        if (empty) {
            empty.insertAdjacentHTML('beforebegin', html);
        } else {
            tbody.insertAdjacentHTML('beforeend', html);
        }
    }

    /** Repinta la vista previa del reporte activo con los filtros actuales. */
    function refresh() {
        var modal = modalEl();
        if (!modal) return;

        var subject = modal.getAttribute('data-adhoc-subject') || 'users';
        // De dónde salen las filas. Cae a `subject` si el atributo falta, que
        // es el comportamiento de antes y sigue siendo correcto para los cuatro
        // reportes cuya colección sí es la de su panel.
        var source = modal.getAttribute('data-adhoc-preview-source') || subject;
        var all = data()[source] || [];
        var matched = filterRows(subject, all, currentFilters());
        var shown = matched.slice(0, PREVIEW_LIMIT);

        var tbody = document.getElementById(
            subject === 'documents' ? 'adhoc-report-docs-body' : 'adhoc-report-users-body'
        );
        paint(tbody, rowsHtml(subject, shown));

        var counter = modal.querySelector('[data-adhoc-preview-count]');
        if (counter) {
            counter.textContent = shown.length === matched.length
                ? matched.length + ' de ' + all.length
                : shown.length + ' de ' + matched.length + ' coincidencias (vista previa recortada)';
        }

        // Conmuta qué tabla se ve.
        var panes = modal.querySelectorAll('[data-adhoc-preview]');
        for (var i = 0; i < panes.length; i++) {
            panes[i].hidden = panes[i].getAttribute('data-adhoc-preview') !== subject;
        }
    }

    function clearFilters() {
        var inputs = filterInputs();
        for (var i = 0; i < inputs.length; i++) inputs[i].value = '';
        refresh();
    }

    // ==================== MODAL ====================

    /**
     * Abre el modal de filtros para un tipo de reporte.
     * @param {string} type  p. ej. "documentos_notas"
     * @param {string} label título de la tarjeta
     * @param {string} subject "users" | "documents" — panel, columnas y filtros
     * @param {string} preview "users" | "users_diffusion" | "documents" — colección
     */
    function open(type, label, subject, preview) {
        var modal = modalEl();
        var form = formEl();
        if (!modal || !form) return;

        modal.setAttribute('data-adhoc-subject', subject === 'documents' ? 'documents' : 'users');
        // Whitelist, no el atributo tal cual: `data()[source]` con una clave
        // inventada devolvería `undefined` y la previa saldría vacía sin decir
        // por qué. Lo desconocido cae a la colección del panel.
        modal.setAttribute(
            'data-adhoc-preview-source',
            (preview === 'users_diffusion' || preview === 'documents' || preview === 'users')
                ? preview
                : (subject === 'documents' ? 'documents' : 'users')
        );
        form.setAttribute('action', BASE_URL + encodeURIComponent(type));

        var title = modal.querySelector('[data-adhoc-report-title]');
        if (title) title.textContent = 'Filtros: ' + (label || '');

        clearFilters();   // el legacy también limpiaba al abrir

        if (window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(modal).show();
        }
    }

    // ==================== INIT ====================

    function bindOnce() {
        if (_bound) return;
        _bound = true;

        document.addEventListener('click', function (evt) {
            var target = evt.target;
            if (!target || !target.closest) return;

            var card = target.closest('[data-adhoc-report]');
            if (card) {
                evt.preventDefault();
                open(
                    card.getAttribute('data-adhoc-report'),
                    card.getAttribute('data-adhoc-report-label'),
                    card.getAttribute('data-adhoc-report-subject'),
                    card.getAttribute('data-adhoc-report-preview')
                );
                return;
            }

            if (target.closest('[data-adhoc-report-clear]')) {
                evt.preventDefault();
                clearFilters();
                return;
            }

            // "Buscar" del legacy. El filtrado ya es en vivo (input/change), así
            // que aquí solo fuerza un repintado; el botón se conserva porque
            // está en el original.
            if (target.closest('[data-adhoc-report-search]')) {
                evt.preventDefault();
                refresh();
            }
        });

        document.addEventListener('input', function (evt) {
            if (evt.target && evt.target.matches &&
                evt.target.matches('[data-adhoc-report-filter]')) {
                refresh();
            }
        });

        document.addEventListener('change', function (evt) {
            if (evt.target && evt.target.matches &&
                evt.target.matches('[data-adhoc-report-filter]')) {
                refresh();
            }
        });
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(function () { bindOnce(); });
    } else if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindOnce);
    } else {
        bindOnce();
    }

    window.AdhocReports = {
        open: open,
        refresh: refresh,
        clearFilters: clearFilters,
        filterRows: filterRows,
        normalize: normalize
    };
})();
