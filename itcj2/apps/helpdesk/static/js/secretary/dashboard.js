// itcj/apps/helpdesk/static/js/secretary/dashboard.js

/**
 * Secretary Dashboard - Sistema de Tickets ITCJ
 *
 * Migrado (docs/auditoria_ui_helpdesk.md §8): la LISTA de tickets del depto la
 * rinde el server (fragmento + macros, filtros/paginación por HTMX). Este módulo
 * conserva: KPIs (endpoint stats), inventario (lectura), pestaña Resumen (calcula
 * sobre allDeptTickets cargado aparte), sockets → recarga del fragmento, y el
 * botón Limpiar. El render JS divergente de la lista (renderTickets/applyFilters)
 * se eliminó.
 */
;(function () {
    'use strict';

    let DEPARTMENT_ID = null;
    let allDeptTickets = [];          // sólo para la pestaña Resumen
    let allInventoryItems = [];

    let _socketPoller = null;
    let _summaryTabHandler = null;

    // ==================== INIT / DESTROY ====================
    function init() {
        const root = document.querySelector('[data-hd-page]');
        DEPARTMENT_ID = parseInt(root.dataset.departmentId, 10);

        window.refreshDashboard = refreshDashboard;
        window.createTicket = createTicket;
        window.viewInventoryItem = viewInventoryItem;

        bindClearButton();
        initializeDashboard();
        setupWebSocketListeners();
    }

    function destroy() {
        delete window.refreshDashboard;
        delete window.createTicket;
        delete window.viewInventoryItem;

        const socket = window.__helpdeskSocket;
        if (socket) {
            socket.off('ticket_created');
            socket.off('ticket_assigned');
            socket.off('ticket_status_changed');
        }
        if (_socketPoller !== null) { clearInterval(_socketPoller); _socketPoller = null; }
        if (_summaryTabHandler) {
            const summaryTab = document.getElementById('summary-tab');
            if (summaryTab) summaryTab.removeEventListener('shown.bs.tab', _summaryTabHandler);
            _summaryTabHandler = null;
        }

        allDeptTickets = [];
        allInventoryItems = [];
        DEPARTMENT_ID = null;
    }

    // ==================== FILTROS / LISTA (HTMX) ====================
    function bindClearButton() {
        const btn = document.getElementById('btnClearFilters');
        const form = document.getElementById('hd-filter-form');
        if (!btn || !form) return;
        btn.addEventListener('click', function () {
            form.querySelectorAll('select').forEach((s) => { s.value = ''; });
            const search = document.getElementById('searchInput');
            if (search) search.value = '';
            refreshList();
        });
    }

    function refreshList() {
        const form = document.getElementById('hd-filter-form');
        if (form && window.htmx) window.htmx.trigger(form, 'refresh');
    }

    // ==================== INITIALIZATION ====================
    async function initializeDashboard() {
        try {
            await Promise.all([
                loadDashboardStats(),
                loadDeptTicketsForSummary(),
                loadDepartmentInventory()
            ]);
            _summaryTabHandler = loadSummaryStats;
            document.getElementById('summary-tab').addEventListener('shown.bs.tab', _summaryTabHandler);
        } catch (error) {
            console.error('Error initializing dashboard:', error);
            HelpdeskUtils.showToast(`Error al cargar el dashboard: ${error.message || 'Error desconocido'}`, 'error');
        }
    }

    async function refreshDashboard() {
        HelpdeskUtils.showToast('Actualizando...', 'info');
        refreshList();
        await initializeDashboard();
        HelpdeskUtils.showToast('Dashboard actualizado', 'success');
    }

    // ==================== DASHBOARD STATS (KPIs) ====================
    async function loadDashboardStats() {
        try {
            const response = await HelpdeskUtils.api.getDepartmentStats(DEPARTMENT_ID);
            const stats = response.data;
            document.getElementById('activeTicketsCount').textContent = stats.active_tickets || 0;
            document.getElementById('resolvedCount').textContent = stats.resolved_tickets || 0;
            const avgTime = stats.avg_resolution_hours
                ? (stats.avg_resolution_hours < 24 ? `${Math.round(stats.avg_resolution_hours)}h` : `${Math.round(stats.avg_resolution_hours / 24)}d`)
                : '-';
            document.getElementById('avgTime').textContent = avgTime;
            const satisfaction = stats.satisfaction_percent !== null && stats.rated_tickets_count > 0
                ? `${stats.satisfaction_percent.toFixed(0)}%` : '-';
            document.getElementById('satisfaction').textContent = satisfaction;
        } catch (error) {
            console.error('Error loading dashboard stats:', error);
            ['activeTicketsCount', 'resolvedCount', 'avgTime', 'satisfaction'].forEach(id => {
                const el = document.getElementById(id); if (el) el.textContent = '-';
            });
        }
    }

    // ==================== TICKETS (sólo para Resumen) ====================
    async function loadDeptTicketsForSummary() {
        try {
            const response = await HelpdeskUtils.api.getTickets({ department_id: DEPARTMENT_ID, per_page: 100 });
            allDeptTickets = response.tickets || [];
        } catch (error) {
            console.error('Error loading department tickets:', error);
            allDeptTickets = [];
        }
    }

    // ==================== DEPARTMENT INVENTORY ====================
    async function loadDepartmentInventory() {
        const container = document.getElementById('inventoryList');
        HelpdeskUtils.showLoading('inventoryList');
        try {
            const params = new URLSearchParams({ department_id: DEPARTMENT_ID, per_page: 50 });
            const response = await HelpdeskUtils.api.request(`/inventory/items?${params}`);
            allInventoryItems = response.data || [];
            renderInventory(allInventoryItems);
        } catch (error) {
            console.error('Error loading inventory:', error);
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="fas fa-exclamation-triangle fa-3x text-warning mb-3"></i>
                    <p class="text-muted">No se pudo cargar el inventario</p>
                </div>`;
        }
    }

    function renderInventory(items) {
        const container = document.getElementById('inventoryList');
        if (items.length === 0) {
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="fas fa-box-open fa-3x text-muted mb-3"></i>
                    <p class="text-muted">No hay equipos registrados en este departamento</p>
                </div>`;
            return;
        }
        container.innerHTML = items.map(item => {
            const icon = item.category?.icon || 'fas fa-laptop';
            const statusColor = getEquipmentStatusColor(item.status);
            return `
                <div class="inventory-item-card border-bottom p-3 cursor-pointer hover-bg-light"
                     onclick="viewInventoryItem(${item.id})" title="Click para ver detalles del equipo">
                    <div class="d-flex align-items-start gap-3">
                        <div class="equipment-icon-dashboard"><i class="${icon}"></i></div>
                        <div class="flex-grow-1">
                            <div class="d-flex justify-content-between align-items-start mb-2">
                                <div>
                                    <div class="fw-bold text-primary mb-1">${item.inventory_number || 'N/A'}</div>
                                    <h6 class="mb-2">${item.brand || 'N/A'} ${item.model || ''}</h6>
                                </div>
                                <span class="badge ${statusColor}">${item.status || 'UNKNOWN'}</span>
                            </div>
                            <div class="mb-2">
                                <span class="badge bg-info"><i class="fas fa-tag me-1"></i>${item.category?.name || 'Sin categoría'}</span>
                            </div>
                            ${item.assigned_to ? `
                                <div class="mb-2">
                                    <small class="text-muted d-block">Asignado a:</small>
                                    <strong><i class="fas fa-user me-1"></i>${item.assigned_to.name}</strong>
                                </div>` : `
                                <div class="mb-2">
                                    <span class="badge bg-secondary"><i class="fas fa-building me-1"></i>Disponible</span>
                                </div>`}
                            ${item.location_detail ? `
                                <div><small class="text-muted"><i class="fas fa-map-marker-alt me-1"></i>${item.location_detail}</small></div>` : ''}
                        </div>
                        <div class="d-flex align-items-center"><i class="fas fa-chevron-right text-muted"></i></div>
                    </div>
                </div>`;
        }).join('');
    }

    function getEquipmentStatusColor(status) {
        const statusColors = {
            'ACTIVE': 'bg-success', 'ACTIVO': 'bg-success',
            'MAINTENANCE': 'bg-warning', 'MANTENIMIENTO': 'bg-warning',
            'DAMAGED': 'bg-danger', 'DAÑADO': 'bg-danger',
            'LOST': 'bg-dark', 'EXTRAVIADO': 'bg-dark',
            'INACTIVE': 'bg-secondary', 'INACTIVO': 'bg-secondary'
        };
        return statusColors[status] || 'bg-secondary';
    }

    // ==================== SUMMARY STATS (pestaña Resumen) ====================
    async function loadSummaryStats() {
        try {
            const monthStats = document.getElementById('monthStats');
            const categoryStats = document.getElementById('categoryStats');
            const now = new Date();
            const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
            const monthTickets = allDeptTickets.filter(t => new Date(t.created_at) >= startOfMonth);

            monthStats.innerHTML = `
                <div class="d-flex justify-content-between mb-2"><span>Recibidos</span><strong>${monthTickets.length}</strong></div>
                <div class="d-flex justify-content-between mb-2"><span>Resueltos</span><strong>${monthTickets.filter(t => t.status.startsWith('RESOLVED')).length}</strong></div>
                <div class="d-flex justify-content-between"><span>Pendientes</span><strong>${monthTickets.filter(t => t.status === 'PENDING').length}</strong></div>`;

            const categoryCount = {};
            allDeptTickets.forEach(t => {
                const cat = t.category?.name || 'Sin categoría';
                categoryCount[cat] = (categoryCount[cat] || 0) + 1;
            });
            const sortedCategories = Object.entries(categoryCount).sort((a, b) => b[1] - a[1]).slice(0, 5);
            categoryStats.innerHTML = sortedCategories.length === 0
                ? '<p class="text-muted text-center">No hay datos</p>'
                : sortedCategories.map(([cat, count]) => `
                    <div class="d-flex justify-content-between mb-2">
                        <span class="text-truncate" style="max-width: 70%;">${cat}</span><strong>${count}</strong>
                    </div>`).join('');
        } catch (error) {
            console.error('Error loading summary stats:', error);
        }
    }

    // ==================== WEBSOCKET REAL-TIME ====================
    function setupWebSocketListeners() {
        _socketPoller = setInterval(() => {
            if (window.__helpdeskSocket) {
                clearInterval(_socketPoller); _socketPoller = null;
                bindSecretarySocketEvents();
            }
        }, 100);
        setTimeout(() => { if (_socketPoller !== null) { clearInterval(_socketPoller); _socketPoller = null; } }, 5000);
    }

    function bindSecretarySocketEvents() {
        const socket = window.__helpdeskSocket;
        if (!socket) return;
        if (DEPARTMENT_ID) window.__hdJoinDept?.(DEPARTMENT_ID);

        let t = null;
        const debouncedRefresh = () => {
            clearTimeout(t);
            t = setTimeout(() => {
                refreshList();
                loadDashboardStats();
                loadDeptTicketsForSummary();
            }, 500);
        };

        socket.off('ticket_created');
        socket.off('ticket_assigned');
        socket.off('ticket_status_changed');
        socket.on('ticket_created', debouncedRefresh);
        socket.on('ticket_assigned', debouncedRefresh);
        socket.on('ticket_status_changed', debouncedRefresh);
    }

    // ==================== ACTIONS ====================
    function createTicket() {
        window.HelpdeskPage.navigate('/help-desk/user/create');
    }

    function viewInventoryItem(itemId) {
        window.HelpdeskPage.navigate(`/help-desk/inventory/items/${itemId}`);
    }

    // ==================== REGISTER MODULE ====================
    window.HelpdeskPage.page('secretary_dashboard', { init, destroy });

})();
