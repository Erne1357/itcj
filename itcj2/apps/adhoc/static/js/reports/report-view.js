/**
 * reports/report-view.js — acciones de un reporte imprimible.
 *
 * Expone SOLO `window.AdhocReportView` (IIFE, sin globales sueltas).
 * Se carga en `/adhoc/reportes/{tipo}` — los cinco tipos.
 *
 * QUÉ SUSTITUYE
 * -------------
 * Los CINCO archivos del legacy (`view_report_areas.js`, `view_report_tasks.js`,
 * `view_report_users_documents.js`, `view_report_documents_users.js`,
 * `view_report_documents_notes.js`) eran **el mismo código** copiado cinco
 * veces: 200 líneas idénticas cuya única diferencia era el nombre de la clase
 * ES6 global, el nombre de la hoja de Excel y el prefijo del archivo. Aquí es un
 * módulo parametrizado: la hoja y el prefijo llegan en el bloque
 * `<script id="adhoc-page-data" type="application/json">` que emite el template.
 *
 * page_data esperado:
 *   { reportType: "area_usuarios", sheet: "Usuarios y Areas",
 *     filePrefix: "Reporte_Areas_Usuarios", date: "25/08/2026", rows: 42 }
 *
 * MARCADO
 * -------
 *   <table id="adhoc-report-table">                 la tabla a exportar
 *   <button data-adhoc-report-excel>                exportar a .xlsx
 *   <button data-adhoc-report-print>                window.print()
 *
 * Los listeners son DELEGADOS sobre `document`: sobreviven a los swaps de HTMX
 * (`hx-boost` en el nav reemplaza el contenido de <body>) sin necesidad de
 * volver a enganchar nada.
 */
(function () {
    'use strict';

    // Re-ejecución idempotente: con hx-boost, HTMX vuelve a insertar (y a
    // ejecutar) los <script> de la página que entra. Los listeners de este
    // módulo son DELEGADOS sobre `document` y siguen vivos tras el swap, así
    // que una segunda ejecución solo serviría para duplicarlos.
    if (window.AdhocReportView) return;

    var U = window.AdhocUtils;

    var SEL_TABLE = '#adhoc-report-table';
    var SEL_EXCEL = '[data-adhoc-report-excel]';
    var SEL_PRINT = '[data-adhoc-report-print]';

    var _bound = false;

    // ==================== HELPERS ====================

    /** Metadatos del reporte, con valores por defecto si el bloque falta. */
    function meta() {
        var data = (U && typeof U.pageData === 'function') ? U.pageData() : {};
        return {
            reportType: data.reportType || 'reporte',
            sheet: data.sheet || 'Reporte',
            filePrefix: data.filePrefix || 'Reporte',
            date: data.date || '',
            rows: typeof data.rows === 'number' ? data.rows : null
        };
    }

    /**
     * Nombre del archivo: `{prefijo}_{dd-mm-aaaa}.xlsx`.
     * La fecha viene del servidor con `/`, que en Windows y en macOS es un
     * separador de ruta prohibido en un nombre de archivo.
     */
    function fileName(info) {
        var stamp = String(info.date || '').replace(/[/\\:]/g, '-');
        return info.filePrefix + (stamp ? '_' + stamp : '') + '.xlsx';
    }

    function toast(message, type) {
        if (U && typeof U.showToast === 'function') {
            U.showToast(message, type || 'info');
        }
    }

    // ==================== ACCIONES ====================

    /**
     * Exporta la tabla del reporte a .xlsx con SheetJS.
     *
     * `table_to_book` lee el <table> del DOM tal cual, así que la tabla del
     * reporte se renderiza SIN la fila fantasma de "sin resultados" que llevan
     * las tablas de la macro `data_table` (iría a parar dentro del Excel) y sin
     * `colspan` en las filas de relleno (desalinea las columnas). Eso se
     * resuelve en el template y en report_service, no aquí.
     *
     * @returns {boolean} true si el archivo se generó.
     */
    function exportExcel() {
        var table = document.querySelector(SEL_TABLE);
        if (!table) {
            toast('No se encontró la tabla del reporte.', 'error');
            return false;
        }
        if (typeof window.XLSX === 'undefined') {
            // El vendor pineado no cargó (bloqueo de red, 404 de nginx...).
            toast('No se pudo cargar el generador de Excel. Usa "Imprimir PDF".', 'error');
            return false;
        }

        var info = meta();
        try {
            var book = window.XLSX.utils.table_to_book(table, { sheet: info.sheet });
            window.XLSX.writeFile(book, fileName(info));
            return true;
        } catch (e) {
            console.error('[adhoc] fallo al exportar el reporte:', e);
            toast('No se pudo generar el archivo de Excel.', 'error');
            return false;
        }
    }

    function print() {
        window.print();
    }

    // ==================== INIT ====================

    function bindOnce() {
        if (_bound) return;
        _bound = true;

        document.addEventListener('click', function (evt) {
            var target = evt.target;
            if (!target || !target.closest) return;

            if (target.closest(SEL_EXCEL)) {
                evt.preventDefault();
                exportExcel();
                return;
            }
            if (target.closest(SEL_PRINT)) {
                evt.preventDefault();
                print();
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

    window.AdhocReportView = {
        exportExcel: exportExcel,
        print: print,
        meta: meta,
        fileName: fileName
    };
})();
