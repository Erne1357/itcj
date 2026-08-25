/**
 * shared/table-filter.js — filtrado en cliente de las tablas de Calidad.
 *
 * Expone SOLO `window.AdhocTableFilter` (IIFE, sin globales sueltas).
 *
 * QUÉ SUSTITUYE
 * -------------
 * El legacy filtraba por ÍNDICE DE COLUMNA cableado a mano:
 *   - `documents.js:8-17`  → mapa fijo {indiceInput: indiceColumna}
 *   - `advanced_documents.js:118` → `configMap = [2,3,4,5,6,7,8,9,10,11]`
 *   - `incidents.js:95`    → `cells[index + 1]`
 * Añadir un solo <td> desalineaba todos los filtros de la pantalla.
 *
 * Aquí la columna se identifica por CLAVE:
 *   - la <th> lleva  data-adhoc-filter-key="title"
 *   - el input lleva data-adhoc-filter-input="title"
 *   - (recomendado) la <td> lleva data-adhoc-cell="title"
 * El índice, cuando hace falta, se deduce del <thead> en cada pasada; si las
 * celdas están marcadas con data-adhoc-cell, la posición deja de importar.
 *
 * MARCADO SOPORTADO
 * -----------------
 *   <table data-adhoc-table="tabla-docs">          ← id lógico de la tabla
 *     <thead>
 *       <tr><th data-adhoc-filter-key="title">…</th>…</tr>
 *       <tr class="adhoc-filter-row">
 *         <th><input data-adhoc-filter-input="title"></th>…
 *   <tbody data-adhoc-table-body>
 *     <tr><td data-adhoc-cell="title" data-adhoc-value="valor a filtrar">…</td>
 *
 * Filtros de FUERA de la tabla (macro filter_bar):
 *   <div data-adhoc-filter-scope="tabla-docs"> …inputs… </div>
 *   o bien cada input con data-adhoc-filter-target="tabla-docs".
 *
 * Extras:
 *   - <button data-adhoc-filter-clear="tabla-docs">  limpia todos sus filtros.
 *   - <span data-adhoc-filter-count="tabla-docs">    recibe "N de M".
 *   - evento `adhoc:filtered` sobre la <table>, con detail {visible, total}.
 *
 * La comparación ignora mayúsculas Y acentos ("revision" encuentra "Revisión").
 */
(function () {
    'use strict';

    var SEL_TABLE = 'table[data-adhoc-table]';
    var SEL_INPUT = '[data-adhoc-filter-input]';
    var SEL_CLEAR = '[data-adhoc-filter-clear]';

    var _bound = false;

    // ==================== HELPERS ====================

    /** minúsculas + sin acentos + sin espacios sobrantes. */
    function normalize(value) {
        var text = (value === null || value === undefined) ? '' : String(value);
        if (text.normalize) {
            text = text.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        }
        return text.toLowerCase().replace(/\s+/g, ' ').trim();
    }

    function tableId(table) {
        return table.getAttribute('data-adhoc-table') || table.id || '';
    }

    function findTable(id) {
        if (!id) return null;
        return document.querySelector(
            'table[data-adhoc-table="' + cssEscape(id) + '"]'
        ) || document.getElementById(id);
    }

    /** Escape mínimo para meter un id en un selector de atributo. */
    function cssEscape(value) {
        return String(value).replace(/["\\]/g, '\\$&');
    }

    /** {clave: índice} leído del <thead> EN CADA PASADA (nunca cacheado). */
    function headerIndex(table) {
        var map = {};
        var head = table.tHead;
        if (!head || !head.rows.length) return map;
        var cells = head.rows[0].cells;
        for (var i = 0; i < cells.length; i++) {
            var key = cells[i].getAttribute('data-adhoc-filter-key');
            if (key && !(key in map)) map[key] = i;
        }
        return map;
    }

    /** Inputs que filtran esta tabla: los de dentro + los declarados fuera. */
    function inputsFor(table) {
        var id = tableId(table);
        var found = [];
        var i;

        var inside = table.querySelectorAll(SEL_INPUT);
        for (i = 0; i < inside.length; i++) found.push(inside[i]);

        if (id) {
            var scoped = document.querySelectorAll(
                '[data-adhoc-filter-scope="' + cssEscape(id) + '"] ' + SEL_INPUT +
                ', ' + SEL_INPUT + '[data-adhoc-filter-target="' + cssEscape(id) + '"]'
            );
            for (i = 0; i < scoped.length; i++) {
                if (found.indexOf(scoped[i]) === -1) found.push(scoped[i]);
            }
        }
        return found;
    }

    /** Tabla a la que pertenece un input (dentro, por scope o por target). */
    function tableForInput(input) {
        var explicit = input.getAttribute('data-adhoc-filter-target');
        if (explicit) return findTable(explicit);

        var scope = input.closest('[data-adhoc-filter-scope]');
        if (scope) return findTable(scope.getAttribute('data-adhoc-filter-scope'));

        return input.closest(SEL_TABLE);
    }

    /** Texto de la celda: data-adhoc-cell primero, índice del <thead> después. */
    function cellText(row, key, index) {
        var cell = row.querySelector('[data-adhoc-cell="' + cssEscape(key) + '"]');
        if (!cell && index !== undefined && index >= 0 && row.cells && row.cells[index]) {
            cell = row.cells[index];
        }
        if (!cell) return '';
        var override = cell.getAttribute('data-adhoc-value');
        return normalize(override !== null ? override : cell.textContent);
    }

    // ==================== FILTRADO ====================

    /**
     * Aplica los filtros activos a una tabla. Idempotente: se puede llamar
     * cuantas veces haga falta (los módulos la llaman tras re-pintar el tbody).
     * @param {HTMLTableElement} table
     */
    function apply(table) {
        if (!table || !table.tBodies || !table.tBodies.length) return;

        var index = headerIndex(table);
        var inputs = inputsFor(table);
        var active = [];
        var i;

        for (i = 0; i < inputs.length; i++) {
            var key = inputs[i].getAttribute('data-adhoc-filter-input');
            var term = normalize(inputs[i].value);
            if (key && term) active.push({ key: key, term: term, index: index[key] });
        }

        var body = table.tBodies[0];
        var rows = body.rows;
        var total = 0;
        var visible = 0;
        var emptyRow = null;

        for (i = 0; i < rows.length; i++) {
            var row = rows[i];
            if (row.hasAttribute('data-adhoc-empty')) {
                emptyRow = row;
                continue;
            }
            total++;

            var match = true;
            for (var j = 0; j < active.length; j++) {
                if (cellText(row, active[j].key, active[j].index).indexOf(active[j].term) === -1) {
                    match = false;
                    break;
                }
            }

            if (match) {
                row.hidden = false;
                visible++;
            } else {
                row.hidden = true;
            }
        }

        // La fila de "sin resultados" también la esconde el CSS (:has); ambas
        // vías dan el mismo resultado, así que no se contradicen.
        if (emptyRow) emptyRow.hidden = visible > 0;

        updateCount(table, visible, total);

        try {
            table.dispatchEvent(new CustomEvent('adhoc:filtered', {
                bubbles: true,
                detail: { visible: visible, total: total }
            }));
        } catch (e) { /* navegadores sin CustomEvent constructor: irrelevante */ }
    }

    function updateCount(table, visible, total) {
        var id = tableId(table);
        if (!id) return;
        var nodes = document.querySelectorAll(
            '[data-adhoc-filter-count="' + cssEscape(id) + '"]'
        );
        for (var i = 0; i < nodes.length; i++) {
            nodes[i].textContent = (visible === total)
                ? String(total)
                : (visible + ' de ' + total);
        }
    }

    /**
     * Vacía los filtros de una tabla y vuelve a mostrarlo todo.
     * @param {HTMLTableElement} table
     */
    function clear(table) {
        if (!table) return;
        var inputs = inputsFor(table);
        for (var i = 0; i < inputs.length; i++) {
            if (inputs[i].tagName === 'SELECT') {
                inputs[i].selectedIndex = 0;
            } else {
                inputs[i].value = '';
            }
        }
        apply(table);
    }

    /** Aplica los filtros a todas las tablas dentro de `root`. */
    function applyAll(root) {
        var scope = root && root.querySelectorAll ? root : document;
        var tables = scope.querySelectorAll(SEL_TABLE);
        for (var i = 0; i < tables.length; i++) apply(tables[i]);
    }

    // ==================== BINDING ====================

    function onFilterInput(evt) {
        var input = evt.target.closest ? evt.target.closest(SEL_INPUT) : null;
        if (!input) return;
        var table = tableForInput(input);
        if (table) apply(table);
    }

    function onClearClick(evt) {
        var btn = evt.target.closest ? evt.target.closest(SEL_CLEAR) : null;
        if (!btn) return;
        evt.preventDefault();

        var id = btn.getAttribute('data-adhoc-filter-clear');
        var table = id ? findTable(id) : null;
        if (!table) {
            var wrap = btn.closest('[data-adhoc-table-wrap]') ||
                       btn.closest('.adhoc-filter-bar');
            if (wrap) {
                var scoped = wrap.getAttribute('data-adhoc-filter-scope');
                table = scoped ? findTable(scoped) : wrap.querySelector(SEL_TABLE);
            }
        }
        if (!table) {
            // Sin destino declarado: limpia la primera tabla de la página.
            table = document.querySelector(SEL_TABLE);
        }
        if (table) clear(table);
    }

    /** Delegación a nivel documento: una sola vez por carga, sobrevive a HTMX. */
    function bindGlobal() {
        if (_bound) return;
        _bound = true;
        document.addEventListener('input', onFilterInput);
        document.addEventListener('search', onFilterInput);
        document.addEventListener('change', onFilterInput);
        document.addEventListener('click', onClearClick);
    }

    // ==================== INIT ====================

    if (window.AdhocUtils && typeof window.AdhocUtils.onReady === 'function') {
        window.AdhocUtils.onReady(function (root) {
            bindGlobal();
            applyAll(root);
        });
    }

    window.AdhocTableFilter = {
        init: function (root) { bindGlobal(); applyAll(root || document); },
        apply: apply,
        applyAll: applyAll,
        clear: clear,
        normalize: normalize,
        findTable: findTable
    };
})();
