// my_equipment.js - Gestión de equipos asignados al usuario actual
// Isla de-jQuery-zada: modal de detalle via bootstrap.Modal (BS5), tabs nativos
// BS5, fetch nativo. Sin $()/window.jQuery.
(function () {
    'use strict';

    const API_BASE = '/api/help-desk/v2/inventory';
    let myEquipment = [];
    let currentEquipment = null;

    // ==================== HELPERS ====================
    function escapeHtml(text) {
        if (text === null || text === undefined) return '';
        return String(text).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m]));
    }

    function getDetailModal() {
        const el = document.getElementById('equipmentDetailModal');
        return el ? bootstrap.Modal.getOrCreateInstance(el) : null;
    }

    // ==================== INIT / DESTROY ====================
    function init() {
        window.showEquipmentDetail = showEquipmentDetail;
        window.refreshEquipment = refreshEquipment;

        if (window.MyEquipmentModal) {
            window.MyEquipmentModal.setup();
        }

        loadMyEquipment();
    }

    function destroy() {
        if (window.MyEquipmentModal) {
            window.MyEquipmentModal.teardown();
        }

        const modalEl = document.getElementById('equipmentDetailModal');
        if (modalEl) {
            try {
                bootstrap.Modal.getInstance(modalEl)?.hide();
                bootstrap.Modal.getInstance(modalEl)?.dispose();
            } catch (e) { /* ignore */ }
        }

        delete window.showEquipmentDetail;
        delete window.refreshEquipment;

        myEquipment = [];
        currentEquipment = null;
    }

    // ==================== CARGA DE DATOS ====================
    function refreshEquipment() {
        loadMyEquipment();
    }

    async function loadMyEquipment() {
        try {
            showLoading();

            const response = await fetch(`${API_BASE}/items/my-equipment`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`
                }
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || errorData.message || `HTTP error! status: ${response.status}`);
            }

            const result = await response.json();

            if (result.data && result.data.length > 0) {
                myEquipment = result.data;
                displayEquipment(myEquipment);
            } else {
                showEmptyState();
            }

        } catch (error) {
            console.error('Error loading my equipment:', error);
            const errorMessage = error.message || 'Error desconocido';
            showError(`Error al cargar los equipos asignados: ${errorMessage}`);
            showEmptyState();
        }
    }

    // ==================== RENDERIZADO ====================
    function displayEquipment(items) {
        const container = document.getElementById('equipment-container');
        container.innerHTML = '';

        items.forEach(item => {
            const card = createEquipmentCard(item);
            container.appendChild(card);
        });

        hideLoading();
        document.getElementById('empty-state').classList.add('d-none');
        container.classList.remove('d-none');
    }

    function createEquipmentCard(item) {
        const col = document.createElement('div');
        col.className = 'col-md-6 col-lg-4 mb-4';

        const categoryIcon = escapeHtml(getCategoryIcon(item.category?.icon));
        const statusBadge = getStatusBadge(item.status);
        const warrantyInfo = getWarrantyInfo(item);

        col.innerHTML = `
            <div class="card equipment-card shadow h-100" onclick="showEquipmentDetail(${item.id})">
                <div class="card-body">
                    <!-- Icono de Categoría -->
                    <div class="text-center equipment-icon">
                        <i class="${categoryIcon}"></i>
                    </div>

                    <!-- Número de Inventario -->
                    <h5 class="text-center mb-3">
                        <strong>${escapeHtml(item.inventory_number)}</strong>
                    </h5>

                    <!-- Estado -->
                    <div class="text-center mb-3">
                        <span class="badge bg-${statusBadge.color} px-3 py-2">
                            ${escapeHtml(statusBadge.text)}
                        </span>
                    </div>

                    <!-- Información Básica -->
                    <div class="detail-row">
                        <div class="info-label">Categoría</div>
                        <div class="info-value">
                            <i class="${categoryIcon} me-1"></i>
                            ${escapeHtml(item.category?.name || 'Sin categoría')}
                        </div>
                    </div>

                    <div class="detail-row">
                        <div class="info-label">Marca / Modelo</div>
                        <div class="info-value">
                            ${escapeHtml(item.brand || '-')} ${escapeHtml(item.model || '')}
                        </div>
                    </div>

                    ${item.supplier_serial ? `
                    <div class="detail-row">
                        <div class="info-label">Serial Proveedor</div>
                        <div class="info-value"><code>${escapeHtml(item.supplier_serial)}</code></div>
                    </div>` : ''}
                    ${item.itcj_serial ? `
                    <div class="detail-row">
                        <div class="info-label">Serial ITCJ</div>
                        <div class="info-value"><code>${escapeHtml(item.itcj_serial)}</code></div>
                    </div>` : ''}
                    ${item.id_tecnm ? `
                    <div class="detail-row">
                        <div class="info-label">ID TecNM</div>
                        <div class="info-value"><code>${escapeHtml(item.id_tecnm)}</code></div>
                    </div>` : ''}

                    <div class="detail-row">
                        <div class="info-label">Ubicación</div>
                        <div class="info-value">
                            <i class="fas fa-map-marker-alt me-1"></i>
                            ${escapeHtml(item.location_detail || 'Sin especificar')}
                        </div>
                    </div>

                    <div class="detail-row">
                        <div class="info-label">Garantía</div>
                        <div class="info-value">
                            ${warrantyInfo}
                        </div>
                    </div>

                    <!-- Botón de Acción -->
                    <div class="text-center mt-3">
                        <button class="btn btn-sm btn-primary" onclick="event.stopPropagation(); showEquipmentDetail(${item.id})">
                            <i class="fas fa-eye"></i> Ver Detalles Completos
                        </button>
                    </div>
                </div>
            </div>
        `;

        return col;
    }

    // ==================== MODAL DE DETALLE ====================
    async function showEquipmentDetail(itemId) {
        currentEquipment = myEquipment.find(e => e.id === itemId);

        if (!currentEquipment) {
            showError('No se encontró el equipo');
            return;
        }

        document.getElementById('modal-loading').classList.remove('d-none');
        document.getElementById('modal-content').classList.add('d-none');

        const modal = getDetailModal();
        if (modal) modal.show();

        try {
            const response = await fetch(`${API_BASE}/items/${itemId}`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`
                }
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || errorData.message || `HTTP error! status: ${response.status}`);
            }

            const result = await response.json();
            const item = result.data;

            document.getElementById('modal-title').textContent = item.inventory_number;

            fillInfoTab(item);
            fillSpecsTab(item);
            loadHistory(itemId);
            loadRelatedTickets(itemId);

            document.getElementById('modal-loading').classList.add('d-none');
            document.getElementById('modal-content').classList.remove('d-none');

            setTimeout(function () {
                const infoTab = document.getElementById('info-tab');
                if (infoTab) bootstrap.Tab.getOrCreateInstance(infoTab).show();
            }, 100);

        } catch (error) {
            console.error('Error loading equipment detail:', error);
            const errorMessage = error.message || 'Error desconocido';
            showError(`Error al cargar los detalles del equipo: ${errorMessage}`);
            if (modal) modal.hide();
        }
    }

    function fillInfoTab(item) {
        const container = document.getElementById('info-container');
        const statusBadge = getStatusBadge(item.status);
        const categoryIcon = escapeHtml(getCategoryIcon(item.category?.icon));
        const warrantyInfo = getWarrantyInfo(item);

        container.innerHTML = `
            <div class="row mb-3">
                <div class="col-md-6">
                    <div class="detail-row">
                        <div class="info-label">Número de Inventario</div>
                        <div class="info-value">
                            <strong>${escapeHtml(item.inventory_number)}</strong>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="detail-row">
                        <div class="info-label">Estado</div>
                        <div class="info-value">
                            <span class="badge bg-${statusBadge.color}">${escapeHtml(statusBadge.text)}</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="row mb-3">
                <div class="col-md-6">
                    <div class="detail-row">
                        <div class="info-label">Categoría</div>
                        <div class="info-value">
                            <i class="${categoryIcon} me-1"></i>
                            ${escapeHtml(item.category?.name || 'Sin categoría')}
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="detail-row">
                        <div class="info-label">Departamento</div>
                        <div class="info-value">
                            <i class="fas fa-building me-1"></i>
                            ${escapeHtml(item.department?.name || 'Sin departamento')}
                        </div>
                    </div>
                </div>
            </div>

            <div class="row mb-3">
                <div class="col-md-6">
                    <div class="detail-row">
                        <div class="info-label">Marca</div>
                        <div class="info-value">${escapeHtml(item.brand || 'No especificada')}</div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="detail-row">
                        <div class="info-label">Modelo</div>
                        <div class="info-value">${escapeHtml(item.model || 'No especificado')}</div>
                    </div>
                </div>
            </div>

            ${(item.supplier_serial || item.itcj_serial || item.id_tecnm) ? `
            <div class="row mb-3">
                <div class="col-12">
                    ${item.supplier_serial ? `<div class="detail-row"><div class="info-label">Serial Proveedor</div><div class="info-value"><code>${escapeHtml(item.supplier_serial)}</code></div></div>` : ''}
                    ${item.itcj_serial    ? `<div class="detail-row"><div class="info-label">Serial ITCJ</div><div class="info-value"><code>${escapeHtml(item.itcj_serial)}</code></div></div>` : ''}
                    ${item.id_tecnm       ? `<div class="detail-row"><div class="info-label">ID TecNM</div><div class="info-value"><code>${escapeHtml(item.id_tecnm)}</code></div></div>` : ''}
                </div>
            </div>
            ` : ''}

            <div class="row mb-3">
                <div class="col-12">
                    <div class="detail-row">
                        <div class="info-label">Ubicación</div>
                        <div class="info-value">
                            <i class="fas fa-map-marker-alt me-1"></i>
                            ${escapeHtml(item.location_detail || 'Sin especificar')}
                        </div>
                    </div>
                </div>
            </div>

            <div class="row mb-3">
                <div class="col-md-6">
                    <div class="detail-row">
                        <div class="info-label">Garantía</div>
                        <div class="info-value">${warrantyInfo}</div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="detail-row">
                        <div class="info-label">Mantenimiento</div>
                        <div class="info-value">
                            ${getMaintenanceInfo(item)}
                        </div>
                    </div>
                </div>
            </div>

            ${item.notes ? `
            <div class="row">
                <div class="col-12">
                    <div class="detail-row">
                        <div class="info-label">Notas</div>
                        <div class="info-value">
                            <div class="alert alert-info mb-0">
                                <i class="fas fa-sticky-note me-1"></i>
                                ${escapeHtml(item.notes)}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            ` : ''}
        `;
    }

    function fillSpecsTab(item) {
        const container = document.getElementById('specs-container');

        if (!item.specs || Object.keys(item.specs).length === 0) {
            container.innerHTML = '<p class="text-muted">No hay especificaciones registradas</p>';
            return;
        }

        let specsHtml = '';
        for (const [key, value] of Object.entries(item.specs)) {
            specsHtml += `
                <div class="spec-item">
                    <strong>${escapeHtml(formatSpecKey(key))}:</strong> ${escapeHtml(value)}
                </div>
            `;
        }

        container.innerHTML = specsHtml;
    }

    async function loadHistory(itemId) {
        const container = document.getElementById('history-container');

        try {
            const response = await fetch(`${API_BASE}/history/item/${itemId}`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`
                }
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || errorData.message || `HTTP error! status: ${response.status}`);
            }

            const result = await response.json();
            const history = result.history || [];

            if (history.length === 0) {
                container.innerHTML = '<p class="text-muted">No hay historial registrado</p>';
                return;
            }

            let historyHtml = '';
            history.forEach((entry) => {
                const icon = escapeHtml(getHistoryIcon(entry.action_type));
                const date = new Date(entry.created_at).toLocaleString('es-MX');

                historyHtml += `
                    <div class="history-item">
                        <div class="history-icon">
                            <i class="${icon}"></i>
                        </div>
                        <div>
                            <strong>${escapeHtml(entry.action_type_display || entry.action_type)}</strong>
                            <div class="text-muted small">${escapeHtml(date)}</div>
                            ${entry.performed_by ? `
                                <div class="text-muted small">
                                    Por: ${escapeHtml(entry.performed_by.full_name)}
                                </div>
                            ` : ''}
                            ${entry.notes ? `
                                <div class="mt-1">
                                    <small>${escapeHtml(entry.notes)}</small>
                                </div>
                            ` : ''}
                        </div>
                    </div>
                `;
            });

            container.innerHTML = historyHtml;

        } catch (error) {
            console.error('Error loading history:', error);
            const errorMessage = error.message || 'Error desconocido';
            container.innerHTML = `<p class="text-danger">Error al cargar el historial: ${escapeHtml(errorMessage)}</p>`;
        }
    }

    async function loadRelatedTickets(itemId) {
        const container = document.getElementById('tickets-container');
        const countBadge = document.getElementById('tickets-count');

        try {
            const response = await fetch(`/api/help-desk/v2/tickets/equipment/${itemId}`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`
                }
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || errorData.message || `HTTP error! status: ${response.status}`);
            }

            const result = await response.json();
            const tickets = result.tickets || [];

            countBadge.textContent = tickets.length;

            if (tickets.length === 0) {
                container.innerHTML = '<p class="text-muted">No hay tickets relacionados con este equipo</p>';
                return;
            }

            let ticketsHtml = '<div class="list-group">';
            tickets.forEach(ticket => {
                const statusClass = getTicketStatusClass(ticket.status);
                const date = new Date(ticket.created_at).toLocaleDateString('es-MX');

                ticketsHtml += `
                    <a href="/help-desk/user/tickets/${ticket.id}"
                       class="list-group-item list-group-item-action"
                       target="_blank">
                        <div class="d-flex w-100 justify-content-between">
                            <h6 class="mb-1">#${escapeHtml(ticket.ticket_number)}</h6>
                            <small class="badge bg-${statusClass}">${escapeHtml(ticket.status)}</small>
                        </div>
                        <p class="mb-1">${escapeHtml(ticket.title)}</p>
                        <small class="text-muted">${escapeHtml(date)}</small>
                    </a>
                `;
            });
            ticketsHtml += '</div>';

            container.innerHTML = ticketsHtml;

        } catch (error) {
            console.error('Error loading related tickets:', error);
            const errorMessage = error.message || 'Error desconocido';
            container.innerHTML = `<p class="text-danger">Error al cargar los tickets: ${escapeHtml(errorMessage)}</p>`;
            countBadge.textContent = '0';
        }
    }

    // ==================== HELPERS ====================
    function getCategoryIcon(icon) {
        return icon || 'fas fa-box';
    }

    function getStatusBadge(status) {
        const badges = {
            'ACTIVE': { color: 'success', text: 'Activo' },
            'MAINTENANCE': { color: 'warning', text: 'Mantenimiento' },
            'DAMAGED': { color: 'danger', text: 'Dañado' },
            'RETIRED': { color: 'secondary', text: 'Retirado' },
            'LOST': { color: 'dark', text: 'Extraviado' }
        };
        return badges[status] || { color: 'secondary', text: status };
    }

    function getWarrantyInfo(item) {
        if (!item.warranty_expiration) {
            return '<span class="text-muted">Sin información</span>';
        }

        const expirationDate = new Date(item.warranty_expiration);
        const now = new Date();
        const daysRemaining = Math.ceil((expirationDate - now) / (1000 * 60 * 60 * 24));

        if (daysRemaining > 0) {
            let indicatorClass = 'active';
            let icon = 'fa-check-circle';

            if (daysRemaining <= 30) {
                indicatorClass = 'expiring';
                icon = 'fa-exclamation-triangle';
            }

            return `
                <span class="warranty-indicator ${indicatorClass}"></span>
                <i class="fas ${icon} me-1"></i>
                ${daysRemaining} días restantes
            `;
        } else {
            return `
                <span class="warranty-indicator expired"></span>
                <i class="fas fa-times-circle me-1 text-danger"></i>
                <span class="text-danger">Vencida</span>
            `;
        }
    }

    function getMaintenanceInfo(item) {
        if (!item.next_maintenance_date) {
            return '<span class="text-muted">No programado</span>';
        }

        const nextDate = new Date(item.next_maintenance_date);
        const now = new Date();
        const daysUntil = Math.ceil((nextDate - now) / (1000 * 60 * 60 * 24));

        if (daysUntil < 0) {
            return `<span class="text-danger"><i class="fas fa-exclamation-circle me-1"></i>Vencido</span>`;
        } else if (daysUntil <= 7) {
            return `<span class="text-warning"><i class="fas fa-clock me-1"></i>En ${daysUntil} días</span>`;
        } else {
            return `<span class="text-success"><i class="fas fa-calendar-check me-1"></i>En ${daysUntil} días</span>`;
        }
    }

    function getHistoryIcon(actionType) {
        const icons = {
            'CREATED': 'fas fa-plus',
            'ASSIGNED': 'fas fa-user-plus',
            'TRANSFERRED': 'fas fa-exchange-alt',
            'UPDATED': 'fas fa-edit',
            'STATUS_CHANGED': 'fas fa-toggle-on',
            'MAINTENANCE': 'fas fa-tools',
            'DEACTIVATED': 'fas fa-trash'
        };
        return icons[actionType] || 'fas fa-circle';
    }

    function getTicketStatusClass(status) {
        const classes = {
            'PENDING': 'warning',
            'ASSIGNED': 'info',
            'IN_PROGRESS': 'primary',
            'RESOLVED': 'success',
            'CLOSED': 'secondary',
            'CANCELLED': 'danger'
        };
        return classes[status] || 'secondary';
    }

    function formatSpecKey(key) {
        return key
            .replace(/_/g, ' ')
            .replace(/\b\w/g, l => l.toUpperCase());
    }

    function showLoading() {
        document.getElementById('loading-state').classList.remove('d-none');
        document.getElementById('empty-state').classList.add('d-none');
        document.getElementById('equipment-container').classList.add('d-none');
    }

    function hideLoading() {
        document.getElementById('loading-state').classList.add('d-none');
    }

    function showEmptyState() {
        hideLoading();
        document.getElementById('empty-state').classList.remove('d-none');
        document.getElementById('equipment-container').classList.add('d-none');
    }

    function showSuccess(message) {
        if (typeof showToast === 'function') {
            showToast(message, 'success');
        } else if (window.HelpdeskUtils) {
            HelpdeskUtils.showToast(message, 'success');
        }
    }

    function showError(message) {
        if (typeof showToast === 'function') {
            showToast(message, 'error');
        } else if (window.HelpdeskUtils) {
            HelpdeskUtils.showToast(message, 'error');
        }
    }

    // ==================== REGISTRO ====================
    window.HelpdeskPage.page('inventory_assignment_my_equipment', { init: init, destroy: destroy });

})();
