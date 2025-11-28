// my_equipment.js - Gestión de equipos asignados al usuario actual
(function() {
    'use strict';

    const API_BASE = '/api/help-desk/v1/inventory';
    let myEquipment = [];
    let currentEquipment = null;

    // ==================== INICIALIZACIÓN ====================
    document.addEventListener('DOMContentLoaded', function() {
        loadMyEquipment();
    });

    // ==================== CARGA DE DATOS ====================
    async function loadMyEquipment() {
        try {
            showLoading();

            // Llamar al endpoint que obtiene equipos del usuario actual
            const response = await fetch(`${API_BASE}/items/my-equipment`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
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
            showError('Error al cargar los equipos asignados');
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
        document.getElementById('empty-state').style.display = 'none';
        container.style.display = 'flex';
    }

    function createEquipmentCard(item) {
        const col = document.createElement('div');
        col.className = 'col-md-6 col-lg-4 mb-4';

        const categoryIcon = getCategoryIcon(item.category?.icon);
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
                        <strong>${item.inventory_number}</strong>
                    </h5>

                    <!-- Estado -->
                    <div class="text-center mb-3">
                        <span class="badge badge-${statusBadge.color} px-3 py-2">
                            ${statusBadge.text}
                        </span>
                    </div>

                    <!-- Información Básica -->
                    <div class="detail-row">
                        <div class="info-label">Categoría</div>
                        <div class="info-value">
                            <i class="${categoryIcon} mr-1"></i>
                            ${item.category?.name || 'Sin categoría'}
                        </div>
                    </div>

                    <div class="detail-row">
                        <div class="info-label">Marca / Modelo</div>
                        <div class="info-value">
                            ${item.brand || '-'} ${item.model || ''}
                        </div>
                    </div>

                    ${item.serial_number ? `
                    <div class="detail-row">
                        <div class="info-label">Serie</div>
                        <div class="info-value">
                            <code>${item.serial_number}</code>
                        </div>
                    </div>
                    ` : ''}

                    <div class="detail-row">
                        <div class="info-label">Ubicación</div>
                        <div class="info-value">
                            <i class="fas fa-map-marker-alt mr-1"></i>
                            ${item.location_detail || 'Sin especificar'}
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
    window.showEquipmentDetail = async function(itemId) {
        currentEquipment = myEquipment.find(e => e.id === itemId);

        if (!currentEquipment) {
            showError('No se encontró el equipo');
            return;
        }

        // Mostrar loading primero
        document.getElementById('modal-loading').style.display = 'block';
        document.getElementById('modal-content').style.display = 'none';
        
        // Abrir modal (compatible con iframe y navegación normal)
        const $modal = $('#equipmentDetailModal');
        
        // Verificar si estamos en iframe
        const inIframe = window.self !== window.top;
        
        $modal.modal({
            backdrop: inIframe ? true : true,  // Permitir cerrar con click fuera
            keyboard: true,                     // Permitir cerrar con ESC
            focus: true                         // Auto-foco en el modal
        });
        $modal.modal('show');

        try {
            // Cargar información detallada
            const response = await fetch(`${API_BASE}/items/${itemId}`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const result = await response.json();
            const item = result.data;

            // Actualizar título del modal
            document.getElementById('modal-title').textContent = item.inventory_number;

            // Llenar información básica
            fillInfoTab(item);

            // Llenar especificaciones
            fillSpecsTab(item);

            // Cargar historial
            loadHistory(itemId);

            // Cargar tickets
            loadRelatedTickets(itemId);

            // Mostrar contenido
            document.getElementById('modal-loading').style.display = 'none';
            document.getElementById('modal-content').style.display = 'block';

            // Activar el primer tab
            setTimeout(() => {
                $('#equipmentTabs a[href="#info-content"]').tab('show');
            }, 100);

        } catch (error) {
            console.error('Error loading equipment detail:', error);
            showError('Error al cargar los detalles del equipo');
            $modal.modal('hide');
        }
    };

    function fillInfoTab(item) {
        const container = document.getElementById('info-container');
        const statusBadge = getStatusBadge(item.status);
        const categoryIcon = getCategoryIcon(item.category?.icon);
        const warrantyInfo = getWarrantyInfo(item);

        container.innerHTML = `
            <div class="row mb-3">
                <div class="col-md-6">
                    <div class="detail-row">
                        <div class="info-label">Número de Inventario</div>
                        <div class="info-value">
                            <strong>${item.inventory_number}</strong>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="detail-row">
                        <div class="info-label">Estado</div>
                        <div class="info-value">
                            <span class="badge badge-${statusBadge.color}">${statusBadge.text}</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="row mb-3">
                <div class="col-md-6">
                    <div class="detail-row">
                        <div class="info-label">Categoría</div>
                        <div class="info-value">
                            <i class="${categoryIcon} mr-1"></i>
                            ${item.category?.name || 'Sin categoría'}
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="detail-row">
                        <div class="info-label">Departamento</div>
                        <div class="info-value">
                            <i class="fas fa-building mr-1"></i>
                            ${item.department?.name || 'Sin departamento'}
                        </div>
                    </div>
                </div>
            </div>

            <div class="row mb-3">
                <div class="col-md-6">
                    <div class="detail-row">
                        <div class="info-label">Marca</div>
                        <div class="info-value">${item.brand || 'No especificada'}</div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="detail-row">
                        <div class="info-label">Modelo</div>
                        <div class="info-value">${item.model || 'No especificado'}</div>
                    </div>
                </div>
            </div>

            ${item.serial_number ? `
            <div class="row mb-3">
                <div class="col-12">
                    <div class="detail-row">
                        <div class="info-label">Número de Serie</div>
                        <div class="info-value"><code>${item.serial_number}</code></div>
                    </div>
                </div>
            </div>
            ` : ''}

            <div class="row mb-3">
                <div class="col-12">
                    <div class="detail-row">
                        <div class="info-label">Ubicación</div>
                        <div class="info-value">
                            <i class="fas fa-map-marker-alt mr-1"></i>
                            ${item.location_detail || 'Sin especificar'}
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
                                <i class="fas fa-sticky-note mr-1"></i>
                                ${item.notes}
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
                    <strong>${formatSpecKey(key)}:</strong> ${value}
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
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const result = await response.json();
            const history = result.history || [];

            if (history.length === 0) {
                container.innerHTML = '<p class="text-muted">No hay historial registrado</p>';
                return;
            }

            let historyHtml = '';
            history.forEach((entry, index) => {
                const icon = getHistoryIcon(entry.action_type);
                const date = new Date(entry.created_at).toLocaleString('es-MX');

                historyHtml += `
                    <div class="history-item">
                        <div class="history-icon">
                            <i class="${icon}"></i>
                        </div>
                        <div>
                            <strong>${entry.action_type_display || entry.action_type}</strong>
                            <div class="text-muted small">${date}</div>
                            ${entry.performed_by ? `
                                <div class="text-muted small">
                                    Por: ${entry.performed_by.full_name}
                                </div>
                            ` : ''}
                            ${entry.notes ? `
                                <div class="mt-1">
                                    <small>${entry.notes}</small>
                                </div>
                            ` : ''}
                        </div>
                    </div>
                `;
            });

            container.innerHTML = historyHtml;

        } catch (error) {
            console.error('Error loading history:', error);
            container.innerHTML = '<p class="text-danger">Error al cargar el historial</p>';
        }
    }

    async function loadRelatedTickets(itemId) {
        const container = document.getElementById('tickets-container');
        const countBadge = document.getElementById('tickets-count');

        try {
            const response = await fetch(`/api/help-desk/v1/tickets/equipment/${itemId}`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
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
                    <a href="/helpdesk/user/tickets/${ticket.id}"
                       class="list-group-item list-group-item-action"
                       target="_blank">
                        <div class="d-flex w-100 justify-content-between">
                            <h6 class="mb-1">#${ticket.ticket_number}</h6>
                            <small class="badge badge-${statusClass}">${ticket.status}</small>
                        </div>
                        <p class="mb-1">${ticket.title}</p>
                        <small class="text-muted">${date}</small>
                    </a>
                `;
            });
            ticketsHtml += '</div>';

            container.innerHTML = ticketsHtml;

        } catch (error) {
            console.error('Error loading related tickets:', error);
            container.innerHTML = '<p class="text-danger">Error al cargar los tickets</p>';
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
                <i class="fas ${icon} mr-1"></i>
                ${daysRemaining} días restantes
            `;
        } else {
            return `
                <span class="warranty-indicator expired"></span>
                <i class="fas fa-times-circle mr-1 text-danger"></i>
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
            return `<span class="text-danger"><i class="fas fa-exclamation-circle mr-1"></i>Vencido</span>`;
        } else if (daysUntil <= 7) {
            return `<span class="text-warning"><i class="fas fa-clock mr-1"></i>En ${daysUntil} días</span>`;
        } else {
            return `<span class="text-success"><i class="fas fa-calendar-check mr-1"></i>En ${daysUntil} días</span>`;
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
        document.getElementById('loading-state').style.display = 'block';
        document.getElementById('empty-state').style.display = 'none';
        document.getElementById('equipment-container').style.display = 'none';
    }

    function hideLoading() {
        document.getElementById('loading-state').style.display = 'none';
    }

    function showEmptyState() {
        hideLoading();
        document.getElementById('empty-state').style.display = 'block';
        document.getElementById('equipment-container').style.display = 'none';
    }

    function showSuccess(message) {
        if (typeof showToast === 'function') {
            showToast(message, 'success');
        } else {
            alert(message);
        }
    }

    function showError(message) {
        if (typeof showToast === 'function') {
            showToast(message, 'error');
        } else {
            alert(message);
        }
    }

    // ==================== FUNCIONES PÚBLICAS ====================
    window.refreshEquipment = function() {
        loadMyEquipment();
    };

})();
