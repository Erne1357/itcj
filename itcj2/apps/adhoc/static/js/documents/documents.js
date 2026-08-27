/**
 * documents/documents.js — vista de consulta de /adhoc/documentos.
 *
 * Expone SOLO `window.AdhocDocuments` (IIFE, sin globales sueltas).
 *
 * QUÉ SUSTITUYE
 * -------------
 * `static/js/documents/documents.js` del legacy: una clase ES6 suelta en el
 * scope global (`DocumentFilterManager`) que filtraba la tabla YA PINTADA
 * mapeando cada input a un ÍNDICE de columna (`mapaFiltros`, líneas 8-17).
 * Añadir una sola <td> desalineaba todos los filtros de la pantalla. Este
 * archivo mete DOS columnas nuevas y no hay ningún índice que corregir: los
 * filtros van por `data-adhoc-doc-filter` y los pinta el servidor.
 *
 * Aquí el trabajo pesado lo hace `document-list.js` (filtros y paginación de
 * SERVIDOR, incluido el volcado de los filtros que vengan en la URL); este
 * módulo solo dice cómo se pinta una fila de consulta y engancha el botón del
 * historial de versiones.
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;
    var List = window.AdhocDocumentList;
    var H = List ? List.helpers : null;

    var TABLE_ID = 'adhoc-documents-table';

    /**
     * Una fila de la tabla de consulta, en el ORDEN DE COLUMNAS DE LA PANTALLA:
     * Código · Nombre Doc · Versión/Estatus · Vigencia · Enlace · Categoría ·
     * Área · Proceso · Clasificación · Aprobación · Acciones.
     *
     * Las tres últimas cosas son nuevas respecto del porte original: la celda de
     * vigencia, la marca "Superada" dentro de la celda de versión y el botón del
     * historial. Las tres las construyen helpers de `document-list.js`, no este
     * archivo, para que una versión se vea IGUAL aquí, en el panel y dentro del
     * modal del historial.
     *
     * Cero innerHTML con datos del servidor.
     */
    function buildRow(doc, canDownload) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-id', String(doc.id));

        H.cell(tr, 'code', H.text(doc.code, '—'), 'adhoc-cell-nowrap');
        // El título va ACOTADO a dos líneas, igual que en el panel. El ancho de
        // una tabla `auto` no lo fija su `min-width`: lo fija la columna que más
        // pide, y "Nombre Doc" es la única celda de texto libre de las once. Con
        // un título del SGC de 120 caracteres la tabla se estiraba muy por
        // encima de los 1400px de `.adhoc-table-xl` y las dos columnas nuevas
        // —Vigencia y Acciones— se iban fuera de pantalla a 1280px, que es la
        // resolución habitual de los equipos del ITCJ. El texto íntegro queda en
        // el `title` del <td>.
        H.clampCell(tr, 'title', H.text(doc.title));

        // — versión + estatus en una sola celda, como el legacy —
        var tdVersion = document.createElement('td');
        tdVersion.setAttribute('data-adhoc-cell', 'version');
        tdVersion.className = 'adhoc-cell-nowrap';
        var version = document.createElement('span');
        version.className = 'adhoc-doc-version';
        version.textContent = 'v' + H.text(doc.version);
        tdVersion.appendChild(version);
        tdVersion.appendChild(H.statusBadge(doc.status));
        // "Superada": solo aparece con la casilla "Ver versiones anteriores"
        // marcada, porque por defecto la lista solo trae la punta de cada
        // cadena. Sin ella, dos filas del mismo código se ven idénticas salvo
        // por el número de versión, y ninguna dice cuál es la que vale.
        var superada = H.currentBadge(doc);
        if (superada) tdVersion.appendChild(superada);
        tr.appendChild(tdVersion);

        // — vigencia: la fecha y, si toca, el badge rojo o ámbar —
        H.expiryCell(tr, doc);

        var tdFile = document.createElement('td');
        tdFile.setAttribute('data-adhoc-cell', 'file');
        tdFile.className = 'adhoc-col-center';
        tdFile.appendChild(H.fileCell(doc, canDownload));
        tr.appendChild(tdFile);

        H.cell(tr, 'category', H.named(doc.category));
        H.cell(tr, 'area', H.named(doc.area));
        H.cell(tr, 'process', H.named(doc.process));
        H.cell(tr, 'classification', H.named(doc.classification));
        H.cell(tr, 'approval_date', H.isoDate(doc.approval_date) || 'Pendiente',
               'adhoc-cell-nowrap');

        // — acciones: aquí solo el historial de versiones —
        // Va envuelto en `.adhoc-actions` aunque hoy sea un botón único: es el
        // contenedor que centra los iconos bajo un `.adhoc-col-center` y el que
        // usa el panel, así que el día que la consulta gane una segunda acción
        // no hay que rehacer la celda.
        var tdActions = document.createElement('td');
        tdActions.setAttribute('data-adhoc-cell', 'actions');
        tdActions.className = 'adhoc-col-center';
        var acciones = document.createElement('div');
        acciones.className = 'adhoc-actions';
        acciones.appendChild(H.versionButton(doc));
        tdActions.appendChild(acciones);
        tr.appendChild(tdActions);

        return tr;
    }

    /**
     * Abre el historial de versiones al pulsar el botón de la fila.
     *
     * Delegado sobre la raíz de la pantalla, no enganchado botón a botón: el
     * tbody se vuelve a pintar entero en cada consulta y en cada cambio de
     * página, así que cualquier listener puesto sobre una fila se iría con ella.
     *
     * El id sale del propio botón (`data-adhoc-doc-id`) y no de la fila: el
     * helper lo escribe ahí precisamente para no tener que buscar el `<tr>` ni
     * cruzarlo con `list.find()`.
     */
    function bindVersions(root) {
        root.addEventListener('click', function (evt) {
            var btn = evt.target.closest('[data-adhoc-doc-action="versions"]');
            if (!btn) return;
            evt.preventDefault();

            var Versions = window.AdhocDocumentVersions;
            if (!Versions) {
                console.error('[adhoc] documents: falta document-versions.js');
                if (U) U.showToast('No se pudo abrir el historial de versiones.', 'error');
                return;
            }
            Versions.open(btn.getAttribute('data-adhoc-doc-id'));
        });
    }

    // ==================== API PÚBLICA ====================

    function init(scope) {
        if (!List) {
            console.error('[adhoc] documents: falta document-list.js');
            return null;
        }
        var node = scope || document;
        var root = (node.matches && node.matches('[data-adhoc-documents]'))
            ? node
            : node.querySelector('[data-adhoc-documents]');
        if (!root) return null;
        if (root.dataset.adhocDocumentsBound === '1') return null;   // idempotente
        root.dataset.adhocDocumentsBound = '1';

        var data = (U && typeof U.pageData === 'function') ? U.pageData() : {};
        var canDownload = !!data.can_download;

        bindVersions(root);

        // Los filtros que vengan en la URL los vuelca `document-list.js` sobre
        // la barra antes de su primera consulta (`initialFilters`): es el mismo
        // volcado en las dos pantallas, así que vive con el resto del contrato
        // de la barra y no duplicado aquí.
        return List.create(root, {
            tableId: TABLE_ID,
            perPage: data.per_page,
            initialFilters: data.initial_filters,
            buildRow: function (doc) { return buildRow(doc, canDownload); }
        });
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { init(root || document); });
    }

    window.AdhocDocuments = { init: init };
})();
