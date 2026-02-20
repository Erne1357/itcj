/**
 * Help-Desk - Generación de Documentos
 * Admin page para generar PDF/DOCX de tickets
 */
(function () {
    'use strict';

    let tickets = [];
    let selectedTicketIds = new Set();

    // ==================== INICIALIZACIÓN ====================

    document.addEventListener('DOMContentLoaded', () => {
        setupEventListeners();
    });

    function setupEventListeners() {
        // Select all checkbox
        document.getElementById('selectAll').addEventListener('change', function () {
            const checkboxes = document.querySelectorAll('.ticket-checkbox');
            checkboxes.forEach(cb => {
                cb.checked = this.checked;
                const id = parseInt(cb.value);
                if (this.checked) {
                    selectedTicketIds.add(id);
                } else {
                    selectedTicketIds.delete(id);
                }
            });
            updateSelectionUI();
        });

        // Output mode: concatenated solo disponible con PDF
        document.querySelectorAll('input[name="docFormat"]').forEach(radio => {
            radio.addEventListener('change', function () {
                const concatenatedRadio = document.getElementById('outputConcatenated');
                if (this.value === 'docx') {
                    concatenatedRadio.disabled = true;
                    document.getElementById('outputZip').checked = true;
                } else {
                    concatenatedRadio.disabled = false;
                }
            });
        });

        // Buscar con Enter
        document.getElementById('filterSearch').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                loadTickets();
            }
        });
    }

    // ==================== CARGA DE TICKETS ====================

    async function loadTickets() {
        const container = document.getElementById('ticketsList');
        container.innerHTML = '<div class="text-center py-5"><div class="spinner-border text-primary"></div><p class="mt-2 text-muted small">Cargando tickets...</p></div>';

        const params = {};
        const status = document.getElementById('filterStatus').value;
        const area = document.getElementById('filterArea').value;
        const search = document.getElementById('filterSearch').value.trim();

        if (status) params.status = status;
        if (area) params.area = area;
        if (search) params.search = search;
        params.per_page = 500;

        try {
            const response = await HelpdeskUtils.api.getTickets(params);
            tickets = response.tickets || [];

            // Filtrar por fecha en frontend
            const dateFrom = document.getElementById('filterDateFrom').value;
            const dateTo = document.getElementById('filterDateTo').value;

            if (dateFrom) {
                const from = new Date(dateFrom);
                tickets = tickets.filter(t => new Date(t.created_at) >= from);
            }
            if (dateTo) {
                const to = new Date(dateTo);
                to.setHours(23, 59, 59);
                tickets = tickets.filter(t => new Date(t.created_at) <= to);
            }

            // Reset selección
            selectedTicketIds.clear();
            document.getElementById('selectAll').checked = false;

            renderTickets(tickets);
            document.getElementById('ticketsCount').textContent = tickets.length;
            updateSelectionUI();

        } catch (error) {
            console.error('Error cargando tickets:', error);
            container.innerHTML = `
                <div class="alert alert-danger m-3">
                    <i class="fas fa-exclamation-triangle me-2"></i>
                    Error al cargar tickets: ${error.message || 'Error desconocido'}
                </div>
            `;
        }
    }

    // ==================== RENDER ====================

    function renderTickets(ticketsToRender) {
        const container = document.getElementById('ticketsList');

        if (ticketsToRender.length === 0) {
            container.innerHTML = `
                <div class="text-center py-5 text-muted">
                    <i class="fas fa-inbox fa-3x mb-3 d-block"></i>
                    <p>No se encontraron tickets con los filtros seleccionados</p>
                </div>
            `;
            return;
        }

        container.innerHTML = ticketsToRender.map(ticket => {
            const statusBadge = getStatusBadge(ticket.status);
            const areaBadge = ticket.area === 'DESARROLLO'
                ? '<span class="badge bg-primary">Desarrollo</span>'
                : '<span class="badge bg-info">Soporte</span>';

            const requesterName = ticket.requester ? ticket.requester.name : 'N/A';
            const createdDate = new Date(ticket.created_at).toLocaleDateString('es-MX');
            const isResolved = ticket.status.startsWith('RESOLVED') || ticket.status === 'CLOSED';

            return `
                <div class="border-bottom px-3 py-2 ticket-row" data-id="${ticket.id}">
                    <div class="d-flex align-items-start gap-2">
                        <div class="form-check mt-1">
                            <input class="form-check-input ticket-checkbox" type="checkbox"
                                   value="${ticket.id}" id="ticket_${ticket.id}"
                                   onchange="window._docOnTicketChange(${ticket.id}, this.checked)">
                        </div>
                        <div class="flex-grow-1">
                            <div class="d-flex justify-content-between align-items-start">
                                <div>
                                    <span class="fw-bold small">${ticket.ticket_number}</span>
                                    <span class="small text-muted ms-1">- ${truncateText(ticket.title, 50)}</span>
                                </div>
                                <div class="d-flex gap-1">
                                    ${statusBadge}
                                    ${areaBadge}
                                </div>
                            </div>
                            <div class="small text-muted mt-1">
                                <i class="fas fa-user me-1"></i>${requesterName}
                                <i class="fas fa-calendar ms-2 me-1"></i>${createdDate}
                                ${isResolved ? '<i class="fas fa-check-circle ms-2 text-success" title="Resuelto"></i>' : ''}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    // ==================== SELECCIÓN ====================

    function onTicketSelectionChange(ticketId, isChecked) {
        if (isChecked) {
            selectedTicketIds.add(ticketId);
        } else {
            selectedTicketIds.delete(ticketId);
            document.getElementById('selectAll').checked = false;
        }
        updateSelectionUI();
    }

    function updateSelectionUI() {
        const count = selectedTicketIds.size;
        const btnGenerate = document.getElementById('btnGenerate');
        const selectionCount = document.getElementById('selectionCount');

        btnGenerate.disabled = count === 0;

        if (count === 0) {
            selectionCount.textContent = 'Selecciona tickets para generar';
            selectionCount.className = 'text-muted';
        } else {
            selectionCount.textContent = `${count} ticket${count > 1 ? 's' : ''} seleccionado${count > 1 ? 's' : ''}`;
            selectionCount.className = 'text-primary fw-bold';
        }

        // Mostrar/ocultar modo de salida
        const outputModeContainer = document.getElementById('outputModeContainer');
        outputModeContainer.style.display = count > 1 ? 'block' : 'none';
    }

    // ==================== GENERACIÓN ====================

    async function generateDocuments() {
        if (selectedTicketIds.size === 0) {
            HelpdeskUtils.showToast('Selecciona al menos un ticket', 'warning');
            return;
        }

        const docType = document.querySelector('input[name="docType"]:checked').value;
        const docFormat = document.querySelector('input[name="docFormat"]:checked').value;
        const outputMode = selectedTicketIds.size > 1
            ? document.querySelector('input[name="outputMode"]:checked').value
            : 'zip';

        // Validar que concatenado solo sea PDF
        if (outputMode === 'concatenated' && docFormat === 'docx') {
            HelpdeskUtils.showToast('El modo concatenado solo está disponible para PDF', 'warning');
            return;
        }

        // Advertir si hay tickets no resueltos al generar orden de trabajo o combinado
        if (docType === 'orden_trabajo' || docType === 'combinado') {
            const selectedTickets = tickets.filter(t => selectedTicketIds.has(t.id));
            const unresolvedCount = selectedTickets.filter(t =>
                !t.status.startsWith('RESOLVED') && t.status !== 'CLOSED'
            ).length;

            if (docType === 'orden_trabajo' && unresolvedCount > 0 && unresolvedCount === selectedTickets.length) {
                HelpdeskUtils.showToast('Ninguno de los tickets seleccionados está resuelto. La orden de trabajo requiere tickets resueltos.', 'error');
                return;
            }
            if (unresolvedCount > 0) {
                const msg = docType === 'combinado'
                    ? `${unresolvedCount} ticket(s) no resueltos: solo se generará la solicitud (sin orden de trabajo).`
                    : `${unresolvedCount} ticket(s) no resueltos serán omitidos.`;
                HelpdeskUtils.showToast(msg, 'warning');
            }
        }

        const btn = document.getElementById('btnGenerate');
        const originalHTML = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Generando...';

        try {
            const response = await fetch('/api/help-desk/v1/documents/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ticket_ids: Array.from(selectedTicketIds),
                    doc_type: docType,
                    format: docFormat,
                    output_mode: outputMode,
                }),
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `Error ${response.status}`);
            }

            // Descargar archivo
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;

            // Extraer nombre del header Content-Disposition
            const disposition = response.headers.get('Content-Disposition');
            let filename = `documento.${docFormat}`;
            if (disposition) {
                const matches = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/.exec(disposition);
                if (matches && matches[1]) {
                    filename = matches[1].replace(/['"]/g, '');
                }
            }

            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            HelpdeskUtils.showToast('Documentos generados exitosamente', 'success');

        } catch (error) {
            console.error('Error generando documentos:', error);
            HelpdeskUtils.showToast(`Error: ${error.message}`, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHTML;
            updateSelectionUI();
        }
    }

    // ==================== UTILIDADES ====================

    function getStatusBadge(status) {
        const map = {
            'PENDING': '<span class="badge bg-secondary" style="font-size: 0.65rem">Pendiente</span>',
            'ASSIGNED': '<span class="badge bg-warning text-dark" style="font-size: 0.65rem">Asignado</span>',
            'IN_PROGRESS': '<span class="badge bg-info" style="font-size: 0.65rem">En Progreso</span>',
            'RESOLVED_SUCCESS': '<span class="badge bg-success" style="font-size: 0.65rem">Resuelto</span>',
            'RESOLVED_FAILED': '<span class="badge bg-warning" style="font-size: 0.65rem">No Resuelto</span>',
            'CLOSED': '<span class="badge bg-dark" style="font-size: 0.65rem">Cerrado</span>',
            'CANCELED': '<span class="badge bg-danger" style="font-size: 0.65rem">Cancelado</span>',
        };
        return map[status] || '<span class="badge bg-secondary" style="font-size: 0.65rem">?</span>';
    }

    function truncateText(text, maxLen) {
        if (!text) return '';
        return text.length > maxLen ? text.substring(0, maxLen) + '...' : text;
    }

    // Exponer funciones globales necesarias para onclick en HTML
    window.loadTickets = loadTickets;
    window.generateDocuments = generateDocuments;
    window._docOnTicketChange = onTicketSelectionChange;

})();
