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
 * Añadir una sola <td> desalineaba todos los filtros de la pantalla.
 *
 * Aquí el trabajo pesado lo hace `document-list.js` (filtros y paginación de
 * SERVIDOR); este módulo solo dice cómo se pinta una fila de consulta.
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;
    var List = window.AdhocDocumentList;
    var H = List ? List.helpers : null;

    var TABLE_ID = 'adhoc-documents-table';

    /** Una fila de la tabla de consulta. Cero innerHTML con datos del servidor. */
    function buildRow(doc, canDownload) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-id', String(doc.id));

        H.cell(tr, 'code', H.text(doc.code, '—'), 'adhoc-cell-nowrap');
        H.cell(tr, 'title', H.text(doc.title));
        H.cell(tr, 'version', H.text(doc.version), 'adhoc-cell-nowrap');

        var tdStatus = document.createElement('td');
        tdStatus.setAttribute('data-adhoc-cell', 'status');
        tdStatus.appendChild(H.statusBadge(doc.status));
        tr.appendChild(tdStatus);

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

        return tr;
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

        return List.create(root, {
            tableId: TABLE_ID,
            perPage: data.per_page,
            buildRow: function (doc) { return buildRow(doc, canDownload); }
        });
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { init(root || document); });
    }

    window.AdhocDocuments = { init: init };
})();
