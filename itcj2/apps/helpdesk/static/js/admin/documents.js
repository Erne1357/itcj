/**
 * Help-Desk - Generación de Documentos
 *
 * Migrado a componentes server-side + HTMX + Alpine (docs/auditoria_ui_helpdesk.md §8):
 *   - la LISTA la rinde el server (fragmento + macros de badges);
 *   - los FILTROS van por HTMX (form hx-get a la misma URL);
 *   - la SELECCIÓN masiva y las opciones de documento son estado de cliente en
 *     Alpine (x-data en documents.html), regla de zonas §4.2.
 * Aquí sólo queda la lógica genuinamente cliente: generar el archivo (fetch +
 * blob download), expuesta como window.hdDocsGenerate y llamada desde Alpine.
 */
(function () {
    'use strict';

    // ==================== GENERACIÓN (descarga de archivo) ====================
    // items: [{ id, status }]; opts: docType, docFormat, outputMode (ya resuelto).
    async function hdDocsGenerate(items, docType, docFormat, outputMode) {
        if (!items || items.length === 0) {
            HelpdeskUtils.showToast('Selecciona al menos un ticket', 'warning');
            return;
        }

        // Validar: concatenado solo aplica a PDF.
        if (outputMode === 'concatenated' && docFormat === 'docx') {
            HelpdeskUtils.showToast('El modo concatenado solo está disponible para PDF', 'warning');
            return;
        }

        // Advertir si hay tickets no resueltos para orden de trabajo / combinado.
        if (docType === 'orden_trabajo' || docType === 'combinado') {
            const unresolved = items.filter(t => !String(t.status).startsWith('RESOLVED') && t.status !== 'CLOSED');
            if (docType === 'orden_trabajo' && unresolved.length > 0 && unresolved.length === items.length) {
                HelpdeskUtils.showToast('Ninguno de los tickets seleccionados está resuelto. La orden de trabajo requiere tickets resueltos.', 'error');
                return;
            }
            if (unresolved.length > 0) {
                const msg = docType === 'combinado'
                    ? `${unresolved.length} ticket(s) no resueltos: solo se generará la solicitud (sin orden de trabajo).`
                    : `${unresolved.length} ticket(s) no resueltos serán omitidos.`;
                HelpdeskUtils.showToast(msg, 'warning');
            }
        }

        const btn = document.getElementById('btnGenerate');
        const originalHTML = btn ? btn.innerHTML : '';
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Generando...'; }

        let objectUrl = null;
        try {
            const response = await fetch('/api/help-desk/v2/documents/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ticket_ids: items.map(t => t.id),
                    doc_type: docType,
                    format: docFormat,
                    output_mode: outputMode,
                }),
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || errorData.detail || `Error ${response.status}`);
            }

            const blob = await response.blob();
            objectUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = objectUrl;

            const disposition = response.headers.get('Content-Disposition');
            let filename = `documento.${docFormat}`;
            if (disposition) {
                const matches = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/.exec(disposition);
                if (matches && matches[1]) filename = matches[1].replace(/['"]/g, '');
            }
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);

            HelpdeskUtils.showToast('Documentos generados exitosamente', 'success');
        } catch (error) {
            console.error('Error generando documentos:', error);
            HelpdeskUtils.showToast(`Error: ${error.message}`, 'error');
        } finally {
            if (objectUrl) { window.URL.revokeObjectURL(objectUrl); objectUrl = null; }
            if (btn) { btn.disabled = false; btn.innerHTML = originalHTML; }
        }
    }

    // ==================== HTMX LIFECYCLE ====================
    function init() {
        window.hdDocsGenerate = hdDocsGenerate;
    }

    function destroy() {
        delete window.hdDocsGenerate;
    }

    window.HelpdeskPage.page('admin_documents', { init, destroy });
})();
