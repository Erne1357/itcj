/**
 * Admin Assign Tickets — Sistema de Tickets ITCJ
 * HTMX-nav IIFE: registra init/destroy con window.HelpdeskPage.page()
 *
 * Arquitectura: tarjetas renderizadas server-side (macro ticket_card); el
 * filtrado es show/hide client-side sobre los .hd-assign-item ya presentes.
 * Los arrays allPendingTickets / allAssigned... siguen cargándose para que
 * los modales (openAssignmentModal, openReassignmentModal, openEditTicketModal,
 * showTicketQuickView) continúen funcionando sin cambios.
 * openSplitTicketModal ("Partir ticket") no lee esos arrays: pide el ticket
 * fresco al servidor (el de activos tiene tope de 100).
 * Tras una acción (assign/reassign/edit/split/socket) se llama refreshLists()
 * para recargar los tres fragmentos server-side vía htmx.ajax.
 */
(function () {
    'use strict';

    // ==================== MODULE STATE (reset en cada init) ====================
    let allPendingTickets = [];
    let allAssignedTickets = [];    // status = ASSIGNED
    let allInProgressTickets = [];  // status = IN_PROGRESS
    let allTechnicians = [];
    let ticketToAssign = null;
    let ticketToReassign = null;

    // Filter state — tab Asignado
    let assignedAreaFilter = '';
    let assignedTechFilter = null;

    // Filter state — tab En Proceso
    let inprogressAreaFilter = '';
    let inprogressTechFilter = null;

    // Edit modal state
    let ticketToEdit = null;
    let categoriesCache = { DESARROLLO: [], SOPORTE: [] };
    let originalTicketData = null;

    // Split modal state ("Partir ticket"). splitParts[0] es el original.
    let ticketToSplit = null;
    let splitParts = [];
    let splitAttachmentsCount = 0;
    let _splitSubmitting = false;
    // Contadores monótonos (nunca se reinician): _splitSeq cambia al abrir o
    // cerrar el modal y en destroy, e invalida la carga o el envío en vuelo de
    // la sesión anterior; _splitPageToken solo cambia en destroy (la página se
    // fue: no hay listas que refrescar).
    let _splitSeq = 0;
    let _splitPageToken = 0;

    // Handles para destroy
    let _socketPollerInterval = null;
    let _socketPollerTimeout = null;
    let _searchQueueTimeout = null;
    let _searchAssignedTimeout = null;
    let _searchInprogressTimeout = null;
    let _assignmentModalInstance = null;
    let _reassignmentModalInstance = null;
    let _editTicketModalInstance = null;
    let _splitTicketModalInstance = null;
    let _statsTabListener = null;

    // ==================== INIT ====================
    function init() {
        // Reset state
        allPendingTickets = [];
        allAssignedTickets = [];
        allInProgressTickets = [];
        allTechnicians = [];
        ticketToAssign = null;
        ticketToReassign = null;
        assignedAreaFilter = '';
        assignedTechFilter = null;
        inprogressAreaFilter = '';
        inprogressTechFilter = null;
        ticketToEdit = null;
        categoriesCache = { DESARROLLO: [], SOPORTE: [] };
        originalTicketData = null;
        ticketToSplit = null;
        splitParts = [];
        splitAttachmentsCount = 0;
        _splitSubmitting = false;
        _socketPollerInterval = null;
        _socketPollerTimeout = null;
        _searchQueueTimeout = null;
        _searchAssignedTimeout = null;
        _searchInprogressTimeout = null;
        _assignmentModalInstance = null;
        _reassignmentModalInstance = null;
        _editTicketModalInstance = null;
        _splitTicketModalInstance = null;
        _statsTabListener = null;

        // Exponer funciones globales llamadas por onclick en HTML/JS dinámico
        window.refreshDashboard = refreshDashboard;
        window.loadPendingTickets = loadPendingTickets;
        window.openAssignmentModal = openAssignmentModal;
        window.openReassignmentModal = openReassignmentModal;
        window.openEditTicketModal = openEditTicketModal;
        window.openSplitTicketModal = openSplitTicketModal;
        window.showTicketQuickView = showTicketQuickView;
        window.showTicketDetail = showTicketDetail;
        window.filterByTechnician = filterByTechnician;
        window.setAssignedArea = setAssignedArea;
        window.setInprogressArea = setInprogressArea;
        window.setAssignedTech = setAssignedTech;
        window.setInprogressTech = setInprogressTech;

        initializeDashboard();
        setupFilters();
        setupAssignmentModal();
        setupReassignmentModal();
        setupEditTicketModal();
        setupSplitTicketModal();
        setupUrgentAlertToggle();
        setupWebSocketListeners();
    }

    // ==================== DESTROY ====================
    function destroy() {
        // Limpiar socket poller
        if (_socketPollerInterval !== null) {
            clearInterval(_socketPollerInterval);
            _socketPollerInterval = null;
        }
        if (_socketPollerTimeout !== null) {
            clearTimeout(_socketPollerTimeout);
            _socketPollerTimeout = null;
        }

        // Desregistrar socket events
        const socket = window.__helpdeskSocket;
        if (socket) {
            socket.off('ticket_created');
            socket.off('ticket_assigned');
            socket.off('ticket_reassigned');
            socket.off('ticket_status_changed');
            socket.off('ticket_self_assigned');
        }

        // Salir del room admin:all — sin esto, un tech-admin que morfea a otra
        // página con su propio join (p.ej. technician/dashboard) sigue recibiendo
        // aquí los eventos y le llegan por partida doble.
        window.__hdLeaveAdmin?.();

        // Limpiar timeouts de búsqueda
        if (_searchQueueTimeout !== null) {
            clearTimeout(_searchQueueTimeout);
            _searchQueueTimeout = null;
        }
        if (_searchAssignedTimeout !== null) {
            clearTimeout(_searchAssignedTimeout);
            _searchAssignedTimeout = null;
        }
        if (_searchInprogressTimeout !== null) {
            clearTimeout(_searchInprogressTimeout);
            _searchInprogressTimeout = null;
        }

        // Remover listener stats-tab
        const statsTab = document.getElementById('stats-tab');
        if (statsTab && _statsTabListener) {
            statsTab.removeEventListener('shown.bs.tab', _statsTabListener);
            _statsTabListener = null;
        }

        // Dispose Bootstrap modals
        if (_assignmentModalInstance) {
            try { _assignmentModalInstance.dispose(); } catch (e) { /* noop */ }
            _assignmentModalInstance = null;
        }
        if (_reassignmentModalInstance) {
            try { _reassignmentModalInstance.dispose(); } catch (e) { /* noop */ }
            _reassignmentModalInstance = null;
        }
        if (_editTicketModalInstance) {
            try { _editTicketModalInstance.dispose(); } catch (e) { /* noop */ }
            _editTicketModalInstance = null;
        }
        if (_splitTicketModalInstance) {
            try { _splitTicketModalInstance.dispose(); } catch (e) { /* noop */ }
            _splitTicketModalInstance = null;
        }

        // Invalida la carga/envío de "Partir" que siga en vuelo: al resolver ya
        // no encontrará su página (ni su modal) y no tocará el DOM de la nueva.
        _splitSeq++;
        _splitPageToken++;

        // Limpiar funciones globales
        delete window.refreshDashboard;
        delete window.loadPendingTickets;
        delete window.openAssignmentModal;
        delete window.openReassignmentModal;
        delete window.openEditTicketModal;
        delete window.openSplitTicketModal;
        delete window.showTicketQuickView;
        delete window.showTicketDetail;
        delete window.filterByTechnician;
        delete window.setAssignedArea;
        delete window.setInprogressArea;
        delete window.setAssignedTech;
        delete window.setInprogressTech;

        // Reset state
        allPendingTickets = [];
        allAssignedTickets = [];
        allInProgressTickets = [];
        allTechnicians = [];
        ticketToAssign = null;
        ticketToReassign = null;
        assignedAreaFilter = '';
        assignedTechFilter = null;
        inprogressAreaFilter = '';
        inprogressTechFilter = null;
        ticketToEdit = null;
        categoriesCache = { DESARROLLO: [], SOPORTE: [] };
        originalTicketData = null;
        ticketToSplit = null;
        splitParts = [];
        splitAttachmentsCount = 0;
        _splitSubmitting = false;
    }

    // ==================== INITIALIZATION ====================
    async function initializeDashboard() {
        try {
            await Promise.all([
                loadDashboardStats(),
                loadPendingTickets(),
                loadActiveTickets(),
                loadTechnicians()
            ]);

            // Render tech pills now that both tickets and technicians are loaded
            _renderTechPillsForTab('assigned');
            _renderTechPillsForTab('inprogress');

            // Load stats tab (lazy load)
            _statsTabListener = loadStatistics;
            const statsTabEl = document.getElementById('stats-tab');
            if (statsTabEl) {
                statsTabEl.addEventListener('shown.bs.tab', _statsTabListener);
            }

        } catch (error) {
            console.error('Error initializing dashboard:', error);
            const errorMessage = error.message || 'Error desconocido';
            HelpdeskUtils.showToast(`Error al cargar el dashboard: ${errorMessage}`, 'error');
        }
    }

    async function refreshDashboard() {
        HelpdeskUtils.showToast('Actualizando dashboard...', 'info');
        await initializeDashboard();
        refreshLists();
        HelpdeskUtils.showToast('Dashboard actualizado', 'success');
    }

    // ==================== SERVER-SIDE FRAGMENT REFRESH ====================
    /**
     * Recarga los tres contenedores de listas desde el servidor (HTMX ajax).
     * Se llama tras acciones que cambian el estado de los tickets (assign,
     * reassign, edit, socket events). Los filtros se resetean al estado
     * no-filtrado — es aceptable ya que los arrays también se recargan.
     */
    function refreshLists() {
        if (!window.htmx) return;
        const base = '/help-desk/admin/assign-tickets';
        // Cada lista es `source` de su propia petición. Sin `source`, htmx usa
        // <body> como elemento de sincronización de las tres: la segunda queda
        // en cola tras la primera y la tercera la reemplaza (cola "last"), así
        // que la pestaña Asignado nunca se recargaba.
        window.htmx.ajax('GET', base + '?tab=queue',      { source: '#hd-tab-queue',      target: '#hd-tab-queue',      swap: 'innerHTML' });
        window.htmx.ajax('GET', base + '?tab=assigned',   { source: '#hd-tab-assigned',   target: '#hd-tab-assigned',   swap: 'innerHTML' });
        window.htmx.ajax('GET', base + '?tab=inprogress', { source: '#hd-tab-inprogress', target: '#hd-tab-inprogress', swap: 'innerHTML' });
    }

    // ==================== DASHBOARD STATS ====================
    async function loadDashboardStats() {
        try {
            // Get all tickets and calculate stats
            const response = await HelpdeskUtils.api.getTickets({});
            const allTickets = response.tickets || [];

            // Count by status
            const pending = allTickets.filter(t => t.status === 'PENDING').length;
            const unassigned = allTickets.filter(t => t.status === 'PENDING' && !t.assigned_to?.id).length;
            const inProgress = allTickets.filter(t => t.status === 'IN_PROGRESS').length;

            // Count today's tickets
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            const todayTickets = allTickets.filter(t => {
                const createdDate = new Date(t.created_at);
                return createdDate >= today;
            }).length;

            // Update cards
            document.getElementById('pendingCount').textContent = pending;
            document.getElementById('unassignedCount').textContent = unassigned;
            document.getElementById('inProgressCount').textContent = inProgress;
            document.getElementById('todayCount').textContent = todayTickets;

            // Check urgent tickets (only PENDING, assigned tickets should not appear here)
            const urgentTickets = allTickets.filter(t =>
                t.priority === 'URGENTE' && t.status === 'PENDING'
            );

            if (urgentTickets.length > 0) {
                document.getElementById('urgentBadge').style.display = 'inline-block';
                document.getElementById('urgentCount').textContent = urgentTickets.length;
                showUrgentAlert(urgentTickets);
            } else {
                // Hide alert and badge if no urgent pending tickets
                document.getElementById('urgentBadge').style.display = 'none';
                document.getElementById('urgentAlert').classList.add('d-none');
            }

        } catch (error) {
            console.error('Error loading dashboard stats:', error);
        }
    }

    function showUrgentAlert(urgentTickets) {
        const alert = document.getElementById('urgentAlert');
        const list = document.getElementById('urgentTicketsList');
        const content = document.getElementById('urgentAlertContent');
        const icon = document.getElementById('toggleUrgentIcon');

        list.innerHTML = urgentTickets.map(ticket => `
            <div class="card mb-2 border-danger">
                <div class="card-body py-2">
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="flex-grow-1">
                            <h6 class="mb-1">${ticket.ticket_number}: ${ticket.title}</h6>
                            <small class="text-muted">
                                <i class="fas fa-user me-1"></i>${ticket.requester?.name || 'N/A'}
                                ${ticket.location ? `<i class="fas fa-map-marker-alt ms-2 me-1"></i>${ticket.location}` : ''}
                                <i class="fas fa-clock ms-2 me-1"></i>${HelpdeskUtils.formatTimeAgo(ticket.created_at)}
                            </small>
                        </div>
                        <button class="btn btn-danger btn-sm" onclick="openAssignmentModal(${ticket.id})">
                            <i class="fas fa-bolt me-1"></i>Asignar Ahora
                        </button>
                    </div>
                </div>
            </div>
        `).join('');

        alert.classList.remove('d-none');

        // Restore collapsed state from localStorage
        const isCollapsed = localStorage.getItem('urgentAlertCollapsed') === 'true';
        if (isCollapsed) {
            content.classList.add('d-none');
            icon.classList.remove('fa-chevron-up');
            icon.classList.add('fa-chevron-down');
        } else {
            content.classList.remove('d-none');
            icon.classList.remove('fa-chevron-down');
            icon.classList.add('fa-chevron-up');
        }
    }

    function setupUrgentAlertToggle() {
        const toggleBtn = document.getElementById('toggleUrgentAlert');
        if (!toggleBtn) return;

        toggleBtn.addEventListener('click', () => {
            const content = document.getElementById('urgentAlertContent');
            const icon = document.getElementById('toggleUrgentIcon');
            const isCurrentlyVisible = !content.classList.contains('d-none');

            if (isCurrentlyVisible) {
                // Collapse
                content.classList.add('d-none');
                icon.classList.remove('fa-chevron-up');
                icon.classList.add('fa-chevron-down');
                localStorage.setItem('urgentAlertCollapsed', 'true');
            } else {
                // Expand
                content.classList.remove('d-none');
                icon.classList.remove('fa-chevron-down');
                icon.classList.add('fa-chevron-up');
                localStorage.setItem('urgentAlertCollapsed', 'false');
            }
        });
    }

    // ==================== PENDING TICKETS (QUEUE) ====================
    async function loadPendingTickets() {
        try {
            // per_page: 0 significa sin limite (obtener todos los pendientes)
            const response = await HelpdeskUtils.api.getTickets({
                status: 'PENDING',
                per_page: 0
            });

            allPendingTickets = response.tickets || [];

            // Update badge (sincroniza array JS con el badge; el server ya lo
            // habrá pintado en el render inicial, aquí lo mantiene al día)
            document.getElementById('queueBadge').textContent = allPendingTickets.length;

            // Aplicar filtros show/hide sobre las tarjetas server-rendered
            applyFilters();

        } catch (error) {
            console.error('Error loading pending tickets:', error);
            HelpdeskUtils.showToast('Error al cargar tickets pendientes', 'error');
        }
    }

    // ==================== ACTIVE TICKETS (ASSIGNED + IN_PROGRESS) ====================
    async function loadActiveTickets() {
        try {
            const response = await HelpdeskUtils.api.getTickets({
                status: 'ASSIGNED,IN_PROGRESS',
                per_page: 100
            });

            const tickets = response.tickets || [];
            allAssignedTickets   = tickets.filter(t => t.status === 'ASSIGNED');
            allInProgressTickets = tickets.filter(t => t.status === 'IN_PROGRESS');

            // Update tab badges
            document.getElementById('assignedBadge').textContent   = allAssignedTickets.length;
            document.getElementById('inprogressBadge').textContent = allInProgressTickets.length;

            // Update area pill counts for both tabs
            _updateTabAreaCounts('assigned');
            _updateTabAreaCounts('inprogress');

            // Apply show/hide filters on server-rendered cards
            _filterTab('assigned');
            _filterTab('inprogress');

        } catch (error) {
            console.error('Error loading active tickets:', error);
            HelpdeskUtils.showToast('Error al cargar tickets activos', 'error');
        }
    }

    // ---- Helpers internos de tabs ----

    function _updateTabAreaCounts(tab) {
        const tickets = tab === 'assigned' ? allAssignedTickets : allInProgressTickets;
        const sfx     = tab === 'assigned' ? 'Assigned' : 'Inprogress';
        document.getElementById(`areaCountAll${sfx}`).textContent =
            tickets.length;
        document.getElementById(`areaCountDesarrollo${sfx}`).textContent =
            tickets.filter(t => t.area === 'DESARROLLO').length;
        document.getElementById(`areaCountSoporte${sfx}`).textContent =
            tickets.filter(t => t.area === 'SOPORTE').length;
    }

    /**
     * Muestra/oculta los .hd-assign-item dentro del contenedor de la pestaña
     * según los filtros activos (área, técnico, búsqueda). No re-renderiza nada
     * — las tarjetas son server-side y ya están en el DOM.
     */
    function _filterTab(tab) {
        const isAssigned  = tab === 'assigned';
        const areaFilter  = isAssigned ? assignedAreaFilter   : inprogressAreaFilter;
        const techFilter  = isAssigned ? assignedTechFilter   : inprogressTechFilter;
        const searchEl    = document.getElementById(isAssigned ? 'searchAssigned' : 'searchInprogress');
        const search      = searchEl ? searchEl.value.toLowerCase().trim() : '';
        const containerId = isAssigned ? 'hd-tab-assigned' : 'hd-tab-inprogress';
        const container   = document.getElementById(containerId);
        if (!container) return;

        let visibleCount = 0;
        container.querySelectorAll('.hd-assign-item').forEach(el => {
            const elArea   = el.dataset.area || '';
            const elTech   = el.dataset.tech || '';
            const elSearch = el.dataset.search || '';

            const matchArea   = !areaFilter || elArea === areaFilter;
            const matchTech   = techFilter === null || elTech === String(techFilter);
            const matchSearch = !search || elSearch.includes(search);

            const visible = matchArea && matchTech && matchSearch;
            el.style.display = visible ? '' : 'none';
            if (visible) visibleCount++;
        });

        // Mostrar/ocultar mensaje de "sin resultados por filtro" si no hay visibles
        // pero sí hay tarjetas (el empty_state server-side solo cubre lista vacía real)
        let noFilterEl = container.querySelector('.hd-assign-no-filter-results');
        if (visibleCount === 0 && container.querySelectorAll('.hd-assign-item').length > 0) {
            if (!noFilterEl) {
                noFilterEl = document.createElement('div');
                noFilterEl.className = 'hd-assign-no-filter-results text-center py-4 text-muted';
                noFilterEl.innerHTML = '<i class="fas fa-filter fa-2x mb-2 d-block opacity-50"></i>Sin coincidencias con los filtros aplicados.';
                container.appendChild(noFilterEl);
            }
            noFilterEl.style.display = '';
        } else if (noFilterEl) {
            noFilterEl.style.display = 'none';
        }
    }

    function _renderTechPillsForTab(tab) {
        const isAssigned = tab === 'assigned';
        const container  = document.getElementById(isAssigned ? 'techPillsAssigned' : 'techPillsInprogress');
        if (!container) return;

        const tickets    = isAssigned ? allAssignedTickets   : allInProgressTickets;
        const areaFilter = isAssigned ? assignedAreaFilter   : inprogressAreaFilter;
        const techFilter = isAssigned ? assignedTechFilter   : inprogressTechFilter;
        const setFn      = isAssigned ? 'setAssignedTech'    : 'setInprogressTech';

        const techs = areaFilter === ''
            ? allTechnicians
            : allTechnicians.filter(t => t.area === areaFilter);

        // Contar tickets por técnico para ESTE tab
        const counts = {};
        tickets.forEach(ticket => {
            if (ticket.assigned_to?.id) {
                counts[ticket.assigned_to.id] = (counts[ticket.assigned_to.id] || 0) + 1;
            }
        });

        let html = `
            <small class="text-muted fw-semibold text-nowrap">Técnico:</small>
            <button class="btn btn-sm rounded-pill ${techFilter === null ? 'btn-primary' : 'btn-outline-secondary'} text-nowrap"
                    onclick="${setFn}(null)">
                <i class="fas fa-users me-1"></i>Todos
                <span class="badge ${techFilter === null ? 'bg-white text-primary' : 'bg-primary text-white'} rounded-pill">
                    ${tickets.length}
                </span>
            </button>
        `;

        if (techs.length === 0) {
            html += '<span class="text-muted small fst-italic">Sin técnicos en esta área</span>';
        } else {
            techs.forEach(tech => {
                const initials  = tech.name.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
                const count     = counts[tech.id] || 0;
                const isActive  = techFilter === tech.id;
                const color     = tech.area === 'DESARROLLO' ? 'primary' : 'info';
                html += `
                    <button class="btn btn-sm rounded-pill ${isActive ? `btn-${color}` : 'btn-outline-secondary'} d-inline-flex align-items-center gap-1 text-nowrap"
                            onclick="${setFn}(${tech.id})">
                        <span class="tech-pill-avatar">${initials}</span>
                        <span>${tech.name.split(' ')[0]}</span>
                        <span class="badge ${isActive ? `bg-white text-${color}` : `bg-${color} text-white`} rounded-pill">${count}</span>
                    </button>
                `;
            });
        }

        container.innerHTML = html;
    }

    // ---- API pública para los onclick del HTML ----

    function setAssignedArea(area) {
        assignedAreaFilter = area;
        assignedTechFilter = null;
        document.querySelectorAll('#areaPillsAssigned .nav-link').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.area === area);
        });
        _renderTechPillsForTab('assigned');
        _filterTab('assigned');
    }

    function setInprogressArea(area) {
        inprogressAreaFilter = area;
        inprogressTechFilter = null;
        document.querySelectorAll('#areaPillsInprogress .nav-link').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.area === area);
        });
        _renderTechPillsForTab('inprogress');
        _filterTab('inprogress');
    }

    function setAssignedTech(techId) {
        assignedTechFilter = techId;
        _renderTechPillsForTab('assigned');
        _filterTab('assigned');
    }

    function setInprogressTech(techId) {
        inprogressTechFilter = techId;
        _renderTechPillsForTab('inprogress');
        _filterTab('inprogress');
    }

    // ==================== TECHNICIANS ====================
    async function loadTechnicians() {
        try {
            // Load technicians for both areas
            const [desarrollo, soporte] = await Promise.all([
                HelpdeskUtils.api.request('/assignments/technicians/DESARROLLO'),
                HelpdeskUtils.api.request('/assignments/technicians/SOPORTE')
            ]);

            allTechnicians = [
                ...(desarrollo.technicians || []).map(t => ({ ...t, area: 'DESARROLLO' })),
                ...(soporte.technicians || []).map(t => ({ ...t, area: 'SOPORTE' }))
            ];

            renderTechnicians();
            populateTechnicianSelects();

        } catch (error) {
            console.error('Error loading technicians:', error);
        }
    }

    function renderTechnicians() {
        const desarrollo = allTechnicians.filter(t => t.area === 'DESARROLLO');
        const soporte = allTechnicians.filter(t => t.area === 'SOPORTE');

        renderTechniciansList(desarrollo, 'techDesarrolloList');
        renderTechniciansList(soporte, 'techSoporteList');
    }

    function renderTechniciansList(technicians, containerId) {
        const container = document.getElementById(containerId);

        if (technicians.length === 0) {
            container.innerHTML = `
                <div class="text-center py-3 text-muted">
                    <i class="fas fa-user-slash mb-2"></i>
                    <p class="mb-0 small">No hay técnicos disponibles</p>
                </div>
            `;
            return;
        }

        container.innerHTML = technicians.map(tech => {
            const initials = tech.name.split(' ').map(n => n[0]).join('').substring(0, 2);
            const loadClass = tech.active_tickets <= 3 ? 'load-low' :
                             tech.active_tickets <= 6 ? 'load-medium' : 'load-high';

            return `
                <div class="technician-card border rounded p-3 mb-3">
                    <div class="d-flex align-items-center gap-3">
                        <div class="technician-avatar">${initials}</div>
                        <div class="flex-grow-1">
                            <div class="fw-bold">${tech.name}</div>
                            <small class="text-muted">${tech.username}</small>
                            <div class="load-indicator mt-2">
                                <div class="load-indicator-fill ${loadClass}"></div>
                            </div>
                            <small class="text-muted">${tech.active_tickets} ticket${tech.active_tickets !== 1 ? 's' : ''} activo${tech.active_tickets !== 1 ? 's' : ''}</small>
                        </div>
                        <button class="btn btn-sm btn-outline-primary"
                                onclick="filterByTechnician(${tech.id})">
                            <i class="fas fa-list"></i>
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    }

    function filterByTechnician(technicianId) {
        const tech = allTechnicians.find(t => t.id === technicianId);

        // Aplicar filtro de área en ambos tabs
        if (tech) {
            assignedAreaFilter   = tech.area;
            inprogressAreaFilter = tech.area;
            document.querySelectorAll('#areaPillsAssigned .nav-link').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.area === tech.area);
            });
            document.querySelectorAll('#areaPillsInprogress .nav-link').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.area === tech.area);
            });
        }

        // Aplicar filtro de técnico en ambos tabs
        assignedTechFilter   = technicianId;
        inprogressTechFilter = technicianId;
        _renderTechPillsForTab('assigned');
        _renderTechPillsForTab('inprogress');
        _filterTab('assigned');
        _filterTab('inprogress');

        // Cambiar al tab que tenga más tickets para este técnico
        const hasInprogress = allInProgressTickets.some(t => t.assigned_to?.id === technicianId);
        const targetTabId   = hasInprogress ? 'inprogress-tab' : 'assigned-tab';
        new bootstrap.Tab(document.getElementById(targetTabId)).show();

        HelpdeskUtils.showToast('Mostrando tickets del técnico seleccionado', 'info');
    }

    // ==================== ASSIGNMENT MODAL ====================
    function setupAssignmentModal() {
        // Toggle between user/team assignment
        document.querySelectorAll('input[name="assignType"]').forEach(radio => {
            radio.addEventListener('change', (e) => {
                const isUser = e.target.value === 'user';
                document.getElementById('selectTechnicianContainer').classList.toggle('d-none', !isUser);
                document.getElementById('selectTeamContainer').classList.toggle('d-none', isUser);
            });
        });

        // Technician select change
        document.getElementById('technicianSelect').addEventListener('change', (e) => {
            const techId = parseInt(e.target.value);
            const tech = allTechnicians.find(t => t.id === techId);

            if (tech) {
                const loadText = tech.active_tickets <= 3 ? '✅ Carga baja' :
                               tech.active_tickets <= 6 ? '⚠️ Carga media' : '🔴 Carga alta';
                document.getElementById('technicianLoad').textContent =
                    `${loadText} - ${tech.active_tickets} tickets activos`;
            }
        });

        // Confirm button
        document.getElementById('btnConfirmAssign').addEventListener('click', confirmAssignment);
    }

    function populateTechnicianSelects() {
        const select = document.getElementById('technicianSelect');

        // Group by area
        const desarrollo = allTechnicians.filter(t => t.area === 'DESARROLLO');
        const soporte = allTechnicians.filter(t => t.area === 'SOPORTE');

        let html = '<option value="">Selecciona un técnico...</option>';

        if (desarrollo.length > 0) {
            html += '<optgroup label="Desarrollo">';
            desarrollo.forEach(tech => {
                html += `<option value="${tech.id}">${tech.name} (${tech.active_tickets} activos)</option>`;
            });
            html += '</optgroup>';
        }

        if (soporte.length > 0) {
            html += '<optgroup label="Soporte">';
            soporte.forEach(tech => {
                html += `<option value="${tech.id}">${tech.name} (${tech.active_tickets} activos)</option>`;
            });
            html += '</optgroup>';
        }

        select.innerHTML = html;

        // Also populate reassignment select
        document.getElementById('newTechnicianSelect').innerHTML = html + `
            <optgroup label="Equipos">
                <option value="team:desarrollo">Equipo Desarrollo</option>
                <option value="team:soporte">Equipo Soporte</option>
            </optgroup>
        `;
    }

    function openAssignmentModal(ticketId) {
        ticketToAssign = allPendingTickets.find(t => t.id === ticketId);
        if (!ticketToAssign) {
            HelpdeskUtils.showToast('Ticket no encontrado', 'error');
            return;
        }

        // Fill ticket info
        document.getElementById('assignTicketInfo').innerHTML = `
            <h6 class="mb-2">${ticketToAssign.ticket_number}: ${ticketToAssign.title}</h6>
            <div class="d-flex gap-2 mb-2">
                ${HelpdeskUtils.getAreaBadge(ticketToAssign.area)}
                ${HelpdeskUtils.getPriorityBadge(ticketToAssign.priority)}
                ${ticketToAssign.category ? `<span class="badge bg-secondary">${ticketToAssign.category.name}</span>` : ''}
            </div>
            <p class="mb-0 small text-muted">${truncateText(ticketToAssign.description, 150)}</p>
            ${ticketToAssign.location ? `
                <small class="text-muted">
                    <i class="fas fa-map-marker-alt me-1"></i>${ticketToAssign.location}
                </small>
            ` : ''}
        `;

        // Reset form
        document.getElementById('assignUser').checked = true;
        document.getElementById('selectTechnicianContainer').classList.remove('d-none');
        document.getElementById('selectTeamContainer').classList.add('d-none');
        document.getElementById('technicianSelect').value = '';
        document.getElementById('teamSelect').value = '';
        document.getElementById('assignmentReason').value = '';
        document.getElementById('technicianLoad').textContent = '';

        // Pre-select team based on area (smart suggestion)
        if (ticketToAssign.area === 'DESARROLLO') {
            document.getElementById('teamSelect').value = 'desarrollo';
        } else {
            document.getElementById('teamSelect').value = 'soporte';
        }

        _assignmentModalInstance = bootstrap.Modal.getOrCreateInstance(document.getElementById('assignmentModal'));
        _assignmentModalInstance.show();
    }

    async function confirmAssignment() {
        const assignType = document.querySelector('input[name="assignType"]:checked').value;
        const reason = document.getElementById('assignmentReason').value.trim();

        let assignedToUserId = null;
        let assignedToTeam = null;

        if (assignType === 'user') {
            const techId = document.getElementById('technicianSelect').value;
            if (!techId) {
                HelpdeskUtils.showToast('Selecciona un técnico', 'warning');
                return;
            }
            assignedToUserId = parseInt(techId);
        } else {
            const team = document.getElementById('teamSelect').value;
            if (!team) {
                HelpdeskUtils.showToast('Selecciona un equipo', 'warning');
                return;
            }
            assignedToTeam = team;
        }

        const btn = document.getElementById('btnConfirmAssign');
        const originalText = btn.innerHTML;

        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Asignando...';

        try {
            await HelpdeskUtils.api.assignTicket(
                ticketToAssign.id,
                assignedToUserId,
                assignedToTeam,
                reason || null
            );

            HelpdeskUtils.showToast('Ticket asignado exitosamente', 'success');

            // Reset button
            btn.disabled = false;
            btn.innerHTML = originalText;

            // Close modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('assignmentModal'));
            modal.hide();

            // Refresh arrays + server-rendered lists
            await Promise.all([
                loadDashboardStats(),
                loadPendingTickets(),
                loadActiveTickets(),
                loadTechnicians()
            ]);
            refreshLists();

        } catch (error) {
            console.error('Error assigning ticket:', error);
            const errorMessage = error.message || 'Error desconocido';
            HelpdeskUtils.showToast(`Error al asignar ticket: ${errorMessage}`, 'error');

            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }

    // ==================== REASSIGNMENT MODAL ====================
    function setupReassignmentModal() {
        document.getElementById('btnConfirmReassign').addEventListener('click', confirmReassignment);
    }

    function openReassignmentModal(ticketId) {
        ticketToReassign = allAssignedTickets.find(t => t.id === ticketId) ||
                           allInProgressTickets.find(t => t.id === ticketId);
        if (!ticketToReassign) {
            HelpdeskUtils.showToast('Ticket no encontrado', 'error');
            return;
        }

        // Fill ticket info
        document.getElementById('reassignTicketInfo').innerHTML = `
            <h6 class="mb-2">${ticketToReassign.ticket_number}: ${ticketToReassign.title}</h6>
            <div class="mb-2">
                ${HelpdeskUtils.getStatusBadge(ticketToReassign.status)}
                ${HelpdeskUtils.getPriorityBadge(ticketToReassign.priority)}
            </div>
            <p class="mb-2 small"><strong>Asignado actualmente a:</strong></p>
            ${ticketToReassign.assigned_to ? `
                <div class="alert alert-info mb-0 py-2">
                    <i class="fas fa-user-check me-2"></i>${ticketToReassign.assigned_to.name}
                </div>
            ` : ticketToReassign.assigned_to_team ? `
                <div class="alert alert-info mb-0 py-2">
                    <i class="fas fa-users me-2"></i>Equipo ${ticketToReassign.assigned_to_team}
                </div>
            ` : ''}
        `;

        // Reset form
        document.getElementById('newTechnicianSelect').value = '';
        document.getElementById('reassignReason').value = '';

        _reassignmentModalInstance = bootstrap.Modal.getOrCreateInstance(document.getElementById('reassignmentModal'));
        _reassignmentModalInstance.show();
    }

    async function confirmReassignment() {
        const newAssignee = document.getElementById('newTechnicianSelect').value;
        const reason = document.getElementById('reassignReason').value.trim();

        if (!newAssignee) {
            HelpdeskUtils.showToast('Selecciona nuevo técnico/equipo', 'warning');
            return;
        }

        if (!reason) {
            HelpdeskUtils.showToast('Proporciona una razón para la reasignación', 'warning');
            return;
        }

        let assignedToUserId = null;
        let assignedToTeam = null;

        if (newAssignee.startsWith('team:')) {
            assignedToTeam = newAssignee.replace('team:', '');
        } else {
            assignedToUserId = parseInt(newAssignee);
        }

        const btn = document.getElementById('btnConfirmReassign');
        const originalText = btn.innerHTML;

        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Reasignando...';

        try {
            await HelpdeskUtils.api.request(`/assignments/${ticketToReassign.id}/reassign`, {
                method: 'POST',
                body: JSON.stringify({
                    assigned_to_user_id: assignedToUserId,
                    assigned_to_team: assignedToTeam,
                    reason: reason
                })
            });

            HelpdeskUtils.showToast('Ticket reasignado exitosamente', 'success');

            // Reset button
            btn.disabled = false;
            btn.innerHTML = originalText;

            // Close modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('reassignmentModal'));
            modal.hide();

            // Refresh arrays + server-rendered lists
            await loadActiveTickets();
            await loadTechnicians();
            refreshLists();

        } catch (error) {
            console.error('Error reassigning ticket:', error);
            const errorMessage = error.message || 'Error desconocido';
            HelpdeskUtils.showToast(`Error al reasignar ticket: ${errorMessage}`, 'error');

            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }

    // ==================== FILTERS ====================
    function setupFilters() {
        const filterArea = document.getElementById('filterArea');
        const filterPriority = document.getElementById('filterPriority');
        const searchQueue = document.getElementById('searchQueue');

        filterArea.addEventListener('change', applyFilters);
        filterPriority.addEventListener('change', applyFilters);

        searchQueue.addEventListener('input', () => {
            clearTimeout(_searchQueueTimeout);
            _searchQueueTimeout = setTimeout(applyFilters, 300);
        });

        // Búsqueda en tab Asignado
        document.getElementById('searchAssigned')?.addEventListener('input', () => {
            clearTimeout(_searchAssignedTimeout);
            _searchAssignedTimeout = setTimeout(() => _filterTab('assigned'), 300);
        });

        // Búsqueda en tab En Proceso
        document.getElementById('searchInprogress')?.addEventListener('input', () => {
            clearTimeout(_searchInprogressTimeout);
            _searchInprogressTimeout = setTimeout(() => _filterTab('inprogress'), 300);
        });
    }

    /**
     * Filtra la cola de pendientes (#hd-tab-queue) por área, prioridad y
     * búsqueda usando show/hide sobre los .hd-assign-item server-rendered.
     */
    function applyFilters() {
        const area     = document.getElementById('filterArea').value;
        const priority = document.getElementById('filterPriority').value;
        const search   = document.getElementById('searchQueue').value.toLowerCase().trim();
        const container = document.getElementById('hd-tab-queue');
        if (!container) return;

        let visibleCount = 0;
        container.querySelectorAll('.hd-assign-item').forEach(el => {
            const elArea     = el.dataset.area     || '';
            const elPriority = el.dataset.priority || '';
            const elSearch   = el.dataset.search   || '';

            const matchArea     = !area     || elArea === area;
            const matchPriority = !priority || elPriority === priority;
            const matchSearch   = !search   || elSearch.includes(search);

            const visible = matchArea && matchPriority && matchSearch;
            el.style.display = visible ? '' : 'none';
            if (visible) visibleCount++;
        });

        // Mostrar "sin coincidencias" si hay tarjetas pero ninguna pasa el filtro
        let noFilterEl = container.querySelector('.hd-assign-no-filter-results');
        if (visibleCount === 0 && container.querySelectorAll('.hd-assign-item').length > 0) {
            if (!noFilterEl) {
                noFilterEl = document.createElement('div');
                noFilterEl.className = 'hd-assign-no-filter-results text-center py-4 text-muted';
                noFilterEl.innerHTML = '<i class="fas fa-filter fa-2x mb-2 d-block opacity-50"></i>Sin coincidencias con los filtros aplicados.';
                container.appendChild(noFilterEl);
            }
            noFilterEl.style.display = '';
        } else if (noFilterEl) {
            noFilterEl.style.display = 'none';
        }
    }

    // ==================== STATISTICS ====================
    async function loadStatistics() {
        try {
            // Simple stats for now
            const todayStats = document.getElementById('todayStats');
            const deptStats = document.getElementById('deptStats');
            const timeStats = document.getElementById('timeStats');

            // For MVP, show placeholder stats
            todayStats.innerHTML = `
                <div class="d-flex justify-content-between mb-2">
                    <span>Recibidos</span>
                    <strong>${document.getElementById('todayCount').textContent}</strong>
                </div>
                <div class="d-flex justify-content-between mb-2">
                    <span>Pendientes</span>
                    <strong>${document.getElementById('pendingCount').textContent}</strong>
                </div>
                <div class="d-flex justify-content-between mb-2">
                    <span>En Proceso</span>
                    <strong>${document.getElementById('inProgressCount').textContent}</strong>
                </div>
                <div class="d-flex justify-content-between">
                    <span>Completados</span>
                    <strong>-</strong>
                </div>
            `;

            deptStats.innerHTML = `
                <p class="text-muted text-center">Estadísticas detalladas próximamente</p>
            `;

            timeStats.innerHTML = `
                <p class="text-muted text-center">Métricas de tiempo próximamente</p>
            `;

        } catch (error) {
            console.error('Error loading statistics:', error);
        }
    }

    // ==================== QUICK VIEW ====================
    function showTicketQuickView(ticketId) {
        window.HelpdeskPage.navigate(`/help-desk/user/tickets/${ticketId}`);
    }

    // ==================== WEBSOCKET REAL-TIME UPDATES ====================

    /**
     * Debounce helper
     */
    function debounce(fn, delay) {
        let timeoutId;
        return function (...args) {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => fn.apply(this, args), delay);
        };
    }

    /**
     * Configura los listeners de WebSocket para actualizaciones en tiempo real
     */
    function setupWebSocketListeners() {
        _socketPollerInterval = setInterval(() => {
            if (window.__helpdeskSocket) {
                clearInterval(_socketPollerInterval);
                _socketPollerInterval = null;
                if (_socketPollerTimeout !== null) {
                    clearTimeout(_socketPollerTimeout);
                    _socketPollerTimeout = null;
                }
                bindAssignSocketEvents();
            }
        }, 100);

        _socketPollerTimeout = setTimeout(() => {
            clearInterval(_socketPollerInterval);
            _socketPollerInterval = null;
            _socketPollerTimeout = null;
        }, 5000);
    }

    function bindAssignSocketEvents() {
        const socket = window.__helpdeskSocket;
        if (!socket) return;

        // Unirse al room de admin (recibe todos los eventos de tickets)
        window.__hdJoinAdmin?.();

        const debouncedRefreshPending = debounce(() => {
            loadPendingTickets();
            loadDashboardStats();
            refreshLists();
        }, 300);

        const debouncedRefreshActive = debounce(() => {
            loadActiveTickets();
            loadTechnicians();
            loadDashboardStats();
            refreshLists();
        }, 300);

        const debouncedRefreshAll = debounce(() => {
            loadPendingTickets();
            loadActiveTickets();
            loadTechnicians();
            loadDashboardStats();
            refreshLists();
        }, 300);

        // Remover listeners previos
        socket.off('ticket_created');
        socket.off('ticket_assigned');
        socket.off('ticket_reassigned');
        socket.off('ticket_status_changed');
        socket.off('ticket_self_assigned');

        // Nuevo ticket creado - actualiza cola de pendientes
        socket.on('ticket_created', (data) => {
            if (window.__hdIsOwnEvent?.(data)) return;
            console.log('[Assign] ticket_created:', data);
            const ticketNum = data?.ticket_number ? `#${data.ticket_number}` : '';
            const area = data?.area || '';
            const priority = data?.priority || '';
            const requester = data?.requester || '';
            HelpdeskUtils.showToast(
                `🎫 Nuevo ticket ${ticketNum} (${area}) - ${priority}\nSolicitante: ${requester}`,
                priority === 'URGENTE' ? 'warning' : 'info'
            );
            debouncedRefreshPending();
        });

        // Ticket asignado - sale de pendientes, entra a activos
        socket.on('ticket_assigned', (data) => {
            if (window.__hdIsOwnEvent?.(data)) return;
            console.log('[Assign] ticket_assigned:', data);
            const ticketNum = data?.ticket_number ? `#${data.ticket_number}` : '';
            HelpdeskUtils.showToast(`Ticket ${ticketNum} asignado`, 'success');
            debouncedRefreshAll();
        });

        // Ticket reasignado
        socket.on('ticket_reassigned', (data) => {
            if (window.__hdIsOwnEvent?.(data)) return;
            console.log('[Assign] ticket_reassigned:', data);
            const ticketNum = data?.ticket_number ? `#${data.ticket_number}` : '';
            HelpdeskUtils.showToast(`Ticket ${ticketNum} reasignado`, 'info');
            debouncedRefreshActive();
        });

        // Cambio de estado
        socket.on('ticket_status_changed', (data) => {
            if (window.__hdIsOwnEvent?.(data)) return;
            console.log('[Assign] ticket_status_changed:', data);
            const ticketNum = data?.ticket_number ? `#${data.ticket_number}` : '';
            const newStatus = data?.new_status || '';
            HelpdeskUtils.showToast(`Ticket ${ticketNum} → ${newStatus}`, 'info');
            debouncedRefreshActive();
        });

        // Técnico tomó un ticket del pool
        socket.on('ticket_self_assigned', (data) => {
            if (window.__hdIsOwnEvent?.(data)) return;
            console.log('[Assign] ticket_self_assigned:', data);
            const ticketNum = data?.ticket_number ? `#${data.ticket_number}` : '';
            HelpdeskUtils.showToast(`Ticket ${ticketNum} auto-asignado por técnico`, 'info');
            debouncedRefreshAll();
        });

        console.log('[Assign] WebSocket listeners configurados');
    }

    // ==================== EDIT TICKET MODAL ====================
    function setupEditTicketModal() {
        // Cargar categorias al inicio
        loadCategoriesForEdit();

        // Listener para cambio de area
        document.getElementById('editArea').addEventListener('change', (e) => {
            const area = e.target.value;
            updateCategorySelect(area);

            // Mostrar advertencia si hay custom_fields
            if (ticketToEdit && ticketToEdit.custom_fields && Object.keys(ticketToEdit.custom_fields).length > 0) {
                if (area !== originalTicketData.area) {
                    HelpdeskUtils.showToast('Al cambiar de area, los campos personalizados se borraran', 'warning');
                }
            }
        });

        // Listener para cambio de categoria
        document.getElementById('editCategory').addEventListener('change', (e) => {
            if (ticketToEdit && ticketToEdit.custom_fields && Object.keys(ticketToEdit.custom_fields).length > 0) {
                if (e.target.value != originalTicketData.category?.id) {
                    HelpdeskUtils.showToast('Al cambiar de categoria, los campos personalizados se borraran', 'warning');
                }
            }
        });

        // Contador de caracteres para titulo
        document.getElementById('editTitle').addEventListener('input', (e) => {
            document.getElementById('editTitleCount').textContent = e.target.value.length;
        });

        // Contador de caracteres para descripcion
        document.getElementById('editDescription').addEventListener('input', (e) => {
            document.getElementById('editDescriptionCount').textContent = e.target.value.length;
        });

        // Boton de guardar
        document.getElementById('btnSaveTicketEdit').addEventListener('click', saveTicketEdit);
    }

    async function loadCategoriesForEdit() {
        try {
            const [desarrollo, soporte] = await Promise.all([
                HelpdeskUtils.api.request('/categories?area=DESARROLLO&active=true'),
                HelpdeskUtils.api.request('/categories?area=SOPORTE&active=true')
            ]);

            categoriesCache.DESARROLLO = desarrollo.categories || [];
            categoriesCache.SOPORTE = soporte.categories || [];

        } catch (error) {
            console.error('Error cargando categorias:', error);
        }
    }

    function updateCategorySelect(area) {
        const select = document.getElementById('editCategory');
        const categories = categoriesCache[area] || [];

        if (categories.length === 0) {
            select.innerHTML = '<option value="">No hay categorias disponibles</option>';
            return;
        }

        select.innerHTML = categories.map(cat =>
            `<option value="${cat.id}">${cat.name}</option>`
        ).join('');

        // Si estamos editando y el area no cambio, mantener la categoria original
        if (ticketToEdit && area === originalTicketData.area && originalTicketData.category) {
            select.value = originalTicketData.category.id;
        }
    }

    async function openEditTicketModal(ticketId) {
        ticketToEdit = allPendingTickets.find(t => t.id === ticketId);
        if (!ticketToEdit) {
            HelpdeskUtils.showToast('Ticket no encontrado', 'error');
            return;
        }

        // Guardar datos originales para comparacion
        originalTicketData = JSON.parse(JSON.stringify(ticketToEdit));

        // Llenar vista previa (columna izquierda)
        fillTicketPreview(ticketToEdit);

        // Llenar campos editables (columna derecha)
        fillEditableFields(ticketToEdit);

        // Cargar adjuntos
        loadTicketAttachments(ticketId);

        // Mostrar modal
        _editTicketModalInstance = bootstrap.Modal.getOrCreateInstance(document.getElementById('editTicketModal'));
        _editTicketModalInstance.show();
    }

    function fillTicketPreview(ticket) {
        // Header con numero y badges
        document.getElementById('editTicketHeader').innerHTML = `
            <div class="d-flex align-items-center gap-2 mb-2">
                <h5 class="mb-0 fw-bold">${ticket.ticket_number}</h5>
                ${HelpdeskUtils.getStatusBadge(ticket.status)}
            </div>
            <div class="d-flex gap-2 flex-wrap">
                ${HelpdeskUtils.getAreaBadge(ticket.area)}
                ${HelpdeskUtils.getPriorityBadge(ticket.priority)}
                ${ticket.category ? `<span class="badge bg-secondary">${ticket.category.name}</span>` : ''}
            </div>
        `;

        // Informacion del solicitante
        document.getElementById('editTicketRequester').innerHTML = `
            <div class="mb-2">
                <strong>${ticket.requester?.name || 'N/A'}</strong>
                <small class="text-muted d-block">${ticket.requester?.username || ''}</small>
            </div>
            ${ticket.department ? `
                <div class="mb-2">
                    <i class="fas fa-building me-2 text-muted"></i>
                    <span>${ticket.department.name}</span>
                </div>
            ` : ''}
            ${ticket.location ? `
                <div>
                    <i class="fas fa-map-marker-alt me-2 text-muted"></i>
                    <span>${ticket.location}</span>
                </div>
            ` : ''}
        `;

        // Fechas
        document.getElementById('editTicketDates').innerHTML = `
            <div class="mb-2">
                <small class="text-muted">Creado:</small>
                <span class="ms-2">${HelpdeskUtils.formatDate ? HelpdeskUtils.formatDate(ticket.created_at) : new Date(ticket.created_at).toLocaleString()}</span>
            </div>
            <div>
                <small class="text-muted">Tiempo transcurrido:</small>
                <span class="ms-2">${HelpdeskUtils.formatTimeAgo(ticket.created_at)}</span>
            </div>
        `;

        // Custom Fields
        const customFieldsContainer = document.getElementById('editTicketCustomFieldsContainer');
        const customFieldsDiv = document.getElementById('editTicketCustomFields');

        if (ticket.custom_fields && Object.keys(ticket.custom_fields).length > 0) {
            customFieldsContainer.style.display = 'block';
            customFieldsDiv.innerHTML = Object.entries(ticket.custom_fields).map(([key, value]) => `
                <div class="mb-2">
                    <small class="text-muted text-capitalize">${key.replace(/_/g, ' ')}:</small>
                    <span class="ms-2">${value}</span>
                </div>
            `).join('');
        } else {
            customFieldsContainer.style.display = 'none';
        }
    }

    function fillEditableFields(ticket) {
        // Area
        document.getElementById('editArea').value = ticket.area;
        updateCategorySelect(ticket.area);

        // Categoria (despues de actualizar el select)
        setTimeout(() => {
            if (ticket.category) {
                document.getElementById('editCategory').value = ticket.category.id;
            }
        }, 100);

        // Prioridad
        document.getElementById('editPriority').value = ticket.priority;

        // Titulo
        const titleInput = document.getElementById('editTitle');
        titleInput.value = ticket.title;
        document.getElementById('editTitleCount').textContent = ticket.title.length;

        // Descripcion
        const descInput = document.getElementById('editDescription');
        descInput.value = ticket.description;
        document.getElementById('editDescriptionCount').textContent = ticket.description.length;

        // Ubicacion
        document.getElementById('editLocation').value = ticket.location || '';
    }

    async function loadTicketAttachments(ticketId) {
        const container = document.getElementById('editTicketAttachments');

        try {
            const response = await HelpdeskUtils.api.request(`/attachments/ticket/${ticketId}`);
            const attachments = response.attachments || [];

            if (attachments.length === 0) {
                container.innerHTML = '<small class="text-muted">Sin archivos adjuntos</small>';
                return;
            }

            container.innerHTML = attachments.map(att => `
                <div class="d-flex align-items-center gap-2 mb-2">
                    <i class="fas fa-${att.mime_type?.startsWith('image/') ? 'image' : 'file'} text-primary"></i>
                    <a href="/api/help-desk/v2/attachments/${att.id}/download"
                       target="_blank" class="text-truncate" style="max-width: 200px;">
                        ${att.original_filename}
                    </a>
                    <small class="text-muted">(${formatFileSize(att.file_size)})</small>
                </div>
            `).join('');

        } catch (error) {
            console.error('Error cargando adjuntos:', error);
            container.innerHTML = '<small class="text-muted">Sin archivos adjuntos</small>';
        }
    }

    function formatFileSize(bytes) {
        if (!bytes) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    async function saveTicketEdit() {
        // Recopilar datos del formulario
        const newArea = document.getElementById('editArea').value;
        const newCategoryId = parseInt(document.getElementById('editCategory').value);
        const newPriority = document.getElementById('editPriority').value;
        const newTitle = document.getElementById('editTitle').value.trim();
        const newDescription = document.getElementById('editDescription').value.trim();
        const newLocation = document.getElementById('editLocation').value.trim();

        // Validaciones basicas
        if (newTitle.length < 5) {
            HelpdeskUtils.showToast('El titulo debe tener al menos 5 caracteres', 'warning');
            return;
        }

        if (newDescription.length < 20) {
            HelpdeskUtils.showToast('La descripcion debe tener al menos 20 caracteres', 'warning');
            return;
        }

        if (!newCategoryId) {
            HelpdeskUtils.showToast('Debe seleccionar una categoria', 'warning');
            return;
        }

        // Construir objeto con solo los campos que cambiaron
        const updateData = {};

        if (newArea !== originalTicketData.area) {
            updateData.area = newArea;
            updateData.category_id = newCategoryId; // Obligatorio si cambia area
        } else if (newCategoryId !== originalTicketData.category?.id) {
            updateData.category_id = newCategoryId;
        }

        if (newPriority !== originalTicketData.priority) {
            updateData.priority = newPriority;
        }

        if (newTitle !== originalTicketData.title) {
            updateData.title = newTitle;
        }

        if (newDescription !== originalTicketData.description) {
            updateData.description = newDescription;
        }

        if (newLocation !== (originalTicketData.location || '')) {
            updateData.location = newLocation;
        }

        // Si no hay cambios, cerrar modal
        if (Object.keys(updateData).length === 0) {
            HelpdeskUtils.showToast('No hay cambios que guardar', 'info');
            const modal = bootstrap.Modal.getInstance(document.getElementById('editTicketModal'));
            modal.hide();
            return;
        }

        const btn = document.getElementById('btnSaveTicketEdit');
        const originalText = btn.innerHTML;

        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Guardando...';

        try {
            await HelpdeskUtils.api.request(`/tickets/${ticketToEdit.id}`, {
                method: 'PATCH',
                body: JSON.stringify(updateData)
            });

            HelpdeskUtils.showToast('Ticket actualizado exitosamente', 'success');

            // Cerrar modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('editTicketModal'));
            modal.hide();

            // Refrescar arrays + server-rendered lists
            await loadPendingTickets();
            await loadDashboardStats();
            refreshLists();

        } catch (error) {
            console.error('Error al guardar cambios:', error);
            const errorMessage = error.message || 'Error desconocido';
            HelpdeskUtils.showToast(`Error al guardar: ${errorMessage}`, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }

    // ==================== SPLIT TICKET MODAL ====================
    // "Partir ticket" (POST /tickets/{id}/split): la parte 1 es el original, que
    // se edita para acotarlo; las partes 2..N se crean como tickets nuevos del
    // mismo solicitante. Las tarjetas se re-renderizan desde `splitParts`, así
    // que antes de cada re-render se copia al arreglo lo escrito en el DOM
    // (syncSplitPartsFromDom). Los valores del usuario entran a los inputs por
    // propiedad (.value), nunca interpolados en innerHTML.

    const SPLIT_MAX_TOTAL_PARTS = 5;   // original + 4 nuevas (MAX_TOTAL_PARTS del servicio)
    const SPLIT_TITLE_MIN = 5;
    const SPLIT_TITLE_MAX = 200;
    const SPLIT_DESCRIPTION_MIN = 20;
    const SPLITTABLE_STATUSES = ['PENDING', 'ASSIGNED', 'IN_PROGRESS'];
    const SPLIT_AREA_OPTIONS = [['DESARROLLO', 'Desarrollo'], ['SOPORTE', 'Soporte']];
    const SPLIT_PRIORITY_OPTIONS = [['URGENTE', 'Urgente'], ['ALTA', 'Alta'], ['MEDIA', 'Media'], ['BAJA', 'Baja']];
    const SPLIT_STATUS_LABELS = {
        RESOLVED_SUCCESS: 'resuelto',
        RESOLVED_FAILED: 'no resuelto',
        CLOSED: 'cerrado',
        CANCELED: 'cancelado'
    };

    function setupSplitTicketModal() {
        const modalEl = document.getElementById('splitTicketModal');
        if (!modalEl) return;   // sin el permiso de partir la página no trae el modal

        // Referencias estables (funciones del módulo, no closures creados en cada
        // init): si init corriera dos veces sobre el mismo DOM, addEventListener
        // descarta el duplicado y cada clic sigue disparando una sola vez.
        document.getElementById('btnAddSplitPart').addEventListener('click', addSplitPart);
        document.getElementById('btnConfirmSplit').addEventListener('click', confirmSplitTicket);
        const list = document.getElementById('splitPartsList');
        list.addEventListener('click', onSplitPartsClick);
        list.addEventListener('change', onSplitPartsChange);
        list.addEventListener('input', onSplitPartsInput);
        modalEl.addEventListener('hidden.bs.modal', onSplitModalHidden);
    }

    async function openSplitTicketModal(ticketId) {
        const modalEl = document.getElementById('splitTicketModal');
        if (!modalEl) return;
        if (_splitSubmitting) {
            HelpdeskUtils.showToast('Espera a que termine la división en curso', 'warning');
            return;
        }

        const seq = ++_splitSeq;
        ticketToSplit = null;
        splitParts = [];
        splitAttachmentsCount = 0;
        renderSplitLoading();

        _splitTicketModalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
        _splitTicketModalInstance.show();

        let ticket = null;
        let attachmentsResp = null;
        try {
            // Datos frescos del servidor, no los arreglos de la página: el de
            // activos tiene tope de 100 y la tarjeta pudo quedar vieja.
            const [ticketResp, attResp] = await Promise.all([
                HelpdeskUtils.api.getTicket(ticketId),
                // Sin la lista de adjuntos solo se pierde el aviso de copias.
                HelpdeskUtils.api.request(`/attachments/ticket/${ticketId}`).catch(() => null),
                ensureSplitCategoriesLoaded()
            ]);
            ticket = ticketResp && ticketResp.ticket;
            attachmentsResp = attResp;
            if (!ticket) throw new Error('respuesta sin ticket');
        } catch (error) {
            if (seq !== _splitSeq) return;
            console.error('Error al cargar el ticket a partir:', error);
            renderSplitLoadError(`No se pudo cargar el ticket (${error.message || 'error desconocido'}).`);
            return;
        }
        if (seq !== _splitSeq) return;   // se cerró el modal o se fue la página

        if (!SPLITTABLE_STATUSES.includes(ticket.status)) {
            const label = SPLIT_STATUS_LABELS[ticket.status] || ticket.status;
            renderSplitLoadError(
                `El ticket ${ticket.ticket_number} ya no se puede partir: está ${label}. ` +
                'Solo se parten tickets pendientes, asignados o en proceso.'
            );
            return;
        }

        ticketToSplit = ticket;
        splitAttachmentsCount = ((attachmentsResp && attachmentsResp.attachments) || [])
            .filter(a => a.attachment_type === 'ticket').length;
        splitParts = [originalSplitPart(ticket), newSplitPartFromOriginal()];

        renderSplitOriginalInfo();
        renderSplitParts();
        setSplitFormEnabled(true);
    }

    async function ensureSplitCategoriesLoaded() {
        // loadCategoriesForEdit arranca sin await en init: si el modal se abre
        // antes de que termine, los selects de categoría saldrían vacíos.
        if (categoriesCache.DESARROLLO.length || categoriesCache.SOPORTE.length) return;
        await loadCategoriesForEdit();
    }

    function onSplitModalHidden() {
        // Cerrar invalida la carga en vuelo y vacía el modal: la siguiente
        // apertura arranca de cero y el snapshot de historial de htmx no guarda
        // un formulario a medias.
        _splitSeq++;
        ticketToSplit = null;
        splitParts = [];
        splitAttachmentsCount = 0;
        clearSplitModal();
    }

    function clearSplitModal() {
        ['splitOriginalInfo', 'splitPartsList', 'splitSummary'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = '';
        });
        const limit = document.getElementById('splitPartsLimit');
        if (limit) limit.textContent = '';
    }

    function renderSplitLoading() {
        clearSplitModal();
        document.getElementById('splitOriginalInfo').innerHTML = `
            <div class="d-flex align-items-center justify-content-center gap-2 py-3 text-muted small">
                <span class="spinner-border spinner-border-sm text-primary" aria-hidden="true"></span>
                Cargando ticket...
            </div>
        `;
        setSplitFormEnabled(false);
    }

    function renderSplitLoadError(message) {
        document.getElementById('splitOriginalInfo').innerHTML = `
            <div class="text-danger small" role="alert">
                <i class="fas fa-exclamation-circle me-1"></i>${escapeHtml(message)}
            </div>
        `;
        setSplitFormEnabled(false);
    }

    function setSplitFormEnabled(enabled) {
        // El fieldset deshabilita de una vez todos los campos, "Quitar" y
        // "Agregar parte"; al rehabilitarlo, los que ya tenían su propio
        // `disabled` (área bloqueada, tope de partes) lo conservan.
        const fieldset = document.getElementById('splitPartsFieldset');
        const confirmBtn = document.getElementById('btnConfirmSplit');
        if (fieldset) fieldset.disabled = !enabled;
        if (confirmBtn) confirmBtn.disabled = !enabled;
    }

    function originalSplitPart(ticket) {
        return {
            area: ticket.area || '',
            category_id: ticket.category ? String(ticket.category.id) : '',
            priority: ticket.priority || '',
            title: ticket.title || '',
            description: ticket.description || ''
        };
    }

    function newSplitPartFromOriginal() {
        // Toda parte nueva arranca con los valores del original. Necesita una
        // categoría ACTIVA: si la del original ya no lo está, queda sin elegir.
        const part = originalSplitPart(ticketToSplit);
        const active = (categoriesCache[part.area] || []).some(c => String(c.id) === part.category_id);
        if (!active) part.category_id = '';
        return part;
    }

    function renderSplitOriginalInfo() {
        const t = ticketToSplit;
        let assignee = '<span class="fst-italic">Sin asignar</span>';
        if (t.assigned_to) {
            assignee = escapeHtml(t.assigned_to.name);
        } else if (t.assigned_to_team) {
            assignee = `Equipo ${escapeHtml(t.assigned_to_team)}`;
        }

        const n = splitAttachmentsCount;
        const attachments = n === 0
            ? 'Sin adjuntos iniciales'
            : `${n} adjunto${n === 1 ? '' : 's'} inicial${n === 1 ? '' : 'es'}`;

        document.getElementById('splitOriginalInfo').innerHTML = `
            <div class="d-flex flex-wrap align-items-center gap-2 mb-2">
                <span class="fw-bold text-primary">${escapeHtml(t.ticket_number)}</span>
                ${HelpdeskUtils.getStatusBadge(t.status)}
                ${HelpdeskUtils.getAreaBadge(t.area)}
                ${t.category ? `<span class="badge bg-secondary">${escapeHtml(t.category.name)}</span>` : ''}
                ${HelpdeskUtils.getPriorityBadge(escapeHtml(t.priority))}
            </div>
            <div class="fw-semibold mb-1">${escapeHtml(t.title)}</div>
            <div class="hd-split-original__desc small">${escapeHtml(t.description)}</div>
            <div class="d-flex flex-wrap column-gap-3 row-gap-1 small text-muted mt-2">
                <span><i class="fas fa-user-circle me-1"></i>Solicitante: ${escapeHtml(t.requester?.name || 'N/A')}</span>
                <span><i class="fas fa-user-check me-1"></i>Asignado a: ${assignee}</span>
                <span><i class="fas fa-paperclip me-1"></i>${attachments}</span>
            </div>
        `;
    }

    function renderSplitParts() {
        const list = document.getElementById('splitPartsList');
        list.innerHTML = splitParts.map((_, index) => splitPartCardHtml(index)).join('');
        splitParts.forEach((part, index) => fillSplitPartCard(index, part));

        const atMax = splitParts.length >= SPLIT_MAX_TOTAL_PARTS;
        document.getElementById('btnAddSplitPart').disabled = atMax;
        document.getElementById('splitPartsLimit').textContent = atMax
            ? `Llegaste al máximo de ${SPLIT_MAX_TOTAL_PARTS} partes.`
            : `${splitParts.length} de ${SPLIT_MAX_TOTAL_PARTS} partes como máximo.`;
        updateSplitSummary();
    }

    /** Esqueleto de una tarjeta de parte: solo texto fijo, números y el folio
     *  escapado. Los valores se ponen después por propiedad (fillSplitPartCard). */
    function splitPartCardHtml(index) {
        const isOriginal = index === 0;
        const n = index + 1;
        const id = `splitPart${index}`;
        const areaLocked = isOriginal && ticketToSplit.status !== 'PENDING';
        const header = isOriginal
            ? `Parte 1 · ${escapeHtml(ticketToSplit.ticket_number)} (original)`
            : `Parte ${n} · ticket nuevo`;
        // Con una sola parte nueva no queda nada que partir: no se puede quitar.
        const removeBtn = isOriginal ? '' : `
            <button type="button" class="btn btn-outline-danger btn-sm flex-shrink-0" data-split-remove="${index}"
                    title="Quitar parte ${n}" aria-label="Quitar parte ${n}"${splitParts.length <= 2 ? ' disabled' : ''}>
                <i class="fas fa-times"></i><span class="d-none d-sm-inline ms-1">Quitar</span>
            </button>`;
        // El técnico asignado es de esa área: fuera de PENDING el servidor la rechaza.
        const lockHint = areaLocked ? `
            <div class="form-text" id="${id}AreaHelp">
                El ticket ya está ${ticketToSplit.status === 'IN_PROGRESS' ? 'en proceso' : 'asignado'}: su área no puede cambiar.
            </div>` : '';
        const optionsHtml = options => options
            .map(([value, label]) => `<option value="${value}">${label}</option>`)
            .join('');

        return `
            <div class="card hd-split-part${isOriginal ? ' hd-split-part--original' : ''}" data-split-index="${index}">
                <div class="card-header d-flex align-items-center justify-content-between gap-2 py-2">
                    <span class="fw-semibold small">${header}</span>
                    ${removeBtn}
                </div>
                <div class="card-body">
                    <div class="row g-2">
                        <div class="col-12 col-md-3">
                            <label class="form-label small fw-semibold mb-1" for="${id}Area">Área</label>
                            <select class="form-select" id="${id}Area" data-split-field="area"${areaLocked ? ` disabled aria-describedby="${id}AreaHelp"` : ''}>
                                ${optionsHtml(SPLIT_AREA_OPTIONS)}
                            </select>
                            ${lockHint}
                        </div>
                        <div class="col-12 col-md-6">
                            <label class="form-label small fw-semibold mb-1" for="${id}Category">Categoría</label>
                            <select class="form-select" id="${id}Category" data-split-field="category_id"></select>
                        </div>
                        <div class="col-12 col-md-3">
                            <label class="form-label small fw-semibold mb-1" for="${id}Priority">Prioridad</label>
                            <select class="form-select" id="${id}Priority" data-split-field="priority">
                                ${optionsHtml(SPLIT_PRIORITY_OPTIONS)}
                            </select>
                        </div>
                        <div class="col-12">
                            <label class="form-label small fw-semibold mb-1" for="${id}Title">Título</label>
                            <input type="text" class="form-control" id="${id}Title" data-split-field="title"
                                   maxlength="${SPLIT_TITLE_MAX}" placeholder="Mínimo ${SPLIT_TITLE_MIN} caracteres"
                                   aria-describedby="${id}TitleHelp">
                            <div class="form-text" id="${id}TitleHelp">
                                <span data-split-count="title">0</span>/${SPLIT_TITLE_MAX} caracteres
                            </div>
                        </div>
                        <div class="col-12">
                            <label class="form-label small fw-semibold mb-1" for="${id}Description">Descripción</label>
                            <textarea class="form-control" id="${id}Description" data-split-field="description" rows="3"
                                      placeholder="Mínimo ${SPLIT_DESCRIPTION_MIN} caracteres"
                                      aria-describedby="${id}DescriptionHelp"></textarea>
                            <div class="form-text" id="${id}DescriptionHelp">
                                <span data-split-count="description">0</span> caracteres (mínimo ${SPLIT_DESCRIPTION_MIN})
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    function getSplitCard(index) {
        return document.querySelector(`#splitPartsList .hd-split-part[data-split-index="${index}"]`);
    }

    function fillSplitPartCard(index, part) {
        const card = getSplitCard(index);
        if (!card) return;
        setSplitSelectValue(card.querySelector('[data-split-field="area"]'), part.area);
        fillSplitCategorySelect(card, part.area, part.category_id);
        setSplitSelectValue(card.querySelector('[data-split-field="priority"]'), part.priority);
        card.querySelector('[data-split-field="title"]').value = part.title;
        card.querySelector('[data-split-field="description"]').value = part.description;
        updateSplitCounters(card);
    }

    // Un valor fuera de las opciones fijas (un área o prioridad nueva del
    // catálogo) se agrega, en vez de dejar que el select caiga en silencio a la
    // primera opción y el envío cambie el ticket sin que nadie lo pidiera.
    function setSplitSelectValue(select, value) {
        if (value && !Array.from(select.options).some(o => o.value === value)) {
            select.add(new Option(value, value));
        }
        select.value = value;
    }

    function fillSplitCategorySelect(card, area, selectedId) {
        const select = card.querySelector('[data-split-field="category_id"]');
        const categories = (categoriesCache[area] || []).map(c => ({ id: String(c.id), name: c.name }));

        // El original puede tener una categoría ya inactiva: su tarjeta la ofrece
        // (conservarla no la vuelve a validar el servidor); las partes nuevas no.
        const originalCategory = ticketToSplit && ticketToSplit.category;
        if (card.dataset.splitIndex === '0' && originalCategory && originalCategory.area === area &&
                !categories.some(c => c.id === String(originalCategory.id))) {
            categories.push({ id: String(originalCategory.id), name: `${originalCategory.name} (inactiva)` });
        }

        if (!categories.length) {
            select.innerHTML = '<option value="">No hay categorías disponibles</option>';
            return;
        }
        select.innerHTML = '<option value="">Selecciona una categoría</option>' + categories
            .map(c => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)}</option>`)
            .join('');
        select.value = categories.some(c => c.id === selectedId) ? selectedId : '';
    }

    function updateSplitCounters(card) {
        if (!card) return;
        // El título cuenta tal cual (lo topa maxlength); la descripción sin los
        // espacios de los extremos, que es como la mide el servidor.
        const title = card.querySelector('[data-split-field="title"]');
        const description = card.querySelector('[data-split-field="description"]');
        card.querySelector('[data-split-count="title"]').textContent = title.value.length;
        card.querySelector('[data-split-count="description"]').textContent = description.value.trim().length;
    }

    function onSplitPartsClick(e) {
        const btn = e.target.closest('[data-split-remove]');
        if (btn) removeSplitPart(Number(btn.dataset.splitRemove));
    }

    function onSplitPartsChange(e) {
        const field = e.target.dataset.splitField;
        if (!field) return;
        clearSplitInvalid(e.target);
        if (field === 'area') {
            // Otra área = otras categorías: se obliga a elegir una de verdad.
            fillSplitCategorySelect(e.target.closest('.hd-split-part'), e.target.value, '');
        }
    }

    function onSplitPartsInput(e) {
        const field = e.target.dataset.splitField;
        if (field !== 'title' && field !== 'description') return;
        clearSplitInvalid(e.target);
        updateSplitCounters(e.target.closest('.hd-split-part'));
    }

    function syncSplitPartsFromDom() {
        splitParts = splitParts.map((part, index) => {
            const card = getSplitCard(index);
            if (!card) return part;
            const value = field => card.querySelector(`[data-split-field="${field}"]`).value;
            return {
                area: value('area'),
                category_id: value('category_id'),
                priority: value('priority'),
                title: value('title'),
                description: value('description')
            };
        });
    }

    function addSplitPart() {
        if (!ticketToSplit || splitParts.length >= SPLIT_MAX_TOTAL_PARTS) return;
        syncSplitPartsFromDom();
        splitParts.push(newSplitPartFromOriginal());
        renderSplitParts();

        const card = getSplitCard(splitParts.length - 1);
        if (card) {
            card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            card.querySelector('[data-split-field="title"]').focus({ preventScroll: true });
        }
    }

    function removeSplitPart(index) {
        // La parte 1 es el original y siempre queda al menos una parte nueva.
        if (index < 1 || index >= splitParts.length || splitParts.length <= 2) return;
        syncSplitPartsFromDom();
        splitParts.splice(index, 1);
        renderSplitParts();
        // El botón pulsado ya no existe: el foco pasa a "Agregar parte".
        document.getElementById('btnAddSplitPart').focus();
    }

    function updateSplitSummary() {
        const summary = document.getElementById('splitSummary');
        if (!ticketToSplit) {
            summary.innerHTML = '';
            return;
        }
        const newCount = splitParts.length - 1;
        const requester = `<strong>${escapeHtml(ticketToSplit.requester?.name || 'el solicitante')}</strong>`;
        let text = newCount === 1
            ? `Se creará <strong>1</strong> ticket nuevo a nombre de ${requester}`
            : `Se crearán <strong>${newCount}</strong> tickets nuevos a nombre de ${requester}`;

        const k = splitAttachmentsCount;
        if (k > 0) {
            const verb = k === 1 ? 'copiará' : 'copiarán';
            const what = k === 1 ? '1 adjunto' : `${k} adjuntos`;
            text += newCount === 1 ? ` · se le ${verb} ${what}` : ` · se ${verb} ${what} a cada uno`;
        }
        summary.innerHTML = `<i class="fas fa-info-circle text-primary me-1"></i>${text}`;
    }

    /**
     * Espejo de las reglas del servidor (ticket_split_service), para no gastar
     * un viaje en lo evidente: en las partes nuevas se valida todo; en el
     * original, título y descripción solo si cambiaron (un ticket viejo con
     * descripción corta no debe bloquear la división). El área bloqueada y la
     * categoría del área los garantizan los propios selects.
     */
    function validateSplitParts() {
        for (let index = 0; index < splitParts.length; index++) {
            const part = splitParts[index];
            const isOriginal = index === 0;
            const label = isOriginal ? 'Ticket original' : `Parte ${index + 1}`;
            const title = part.title.trim();
            const description = part.description.trim();

            if (!part.category_id) {
                return { index, field: 'category_id', message: `${label}: Selecciona una categoría` };
            }
            if (title.length > SPLIT_TITLE_MAX) {
                return { index, field: 'title', message: `${label}: El título no debe exceder ${SPLIT_TITLE_MAX} caracteres` };
            }
            if ((!isOriginal || !sameSplitText(title, ticketToSplit.title)) && title.length < SPLIT_TITLE_MIN) {
                return { index, field: 'title', message: `${label}: El título debe tener al menos ${SPLIT_TITLE_MIN} caracteres` };
            }
            if ((!isOriginal || !sameSplitText(description, ticketToSplit.description)) &&
                    description.length < SPLIT_DESCRIPTION_MIN) {
                return {
                    index,
                    field: 'description',
                    message: `${label}: La descripción debe tener al menos ${SPLIT_DESCRIPTION_MIN} caracteres`
                };
            }
        }
        return null;
    }

    // El <textarea> normaliza los saltos de línea a "\n" al leer .value, pero hay
    // descripciones guardadas con "\r\n": sin normalizar, un original intacto
    // viajaría "cambiado" y el servidor le dejaría una edición fantasma.
    function sameSplitText(value, stored) {
        const normalize = s => String(s || '').replace(/\r\n?/g, '\n').trim();
        return normalize(value) === normalize(stored);
    }

    function markSplitInvalid(problem) {
        const card = getSplitCard(problem.index);
        const field = card && card.querySelector(`[data-split-field="${problem.field}"]`);
        if (field) {
            field.classList.add('is-invalid');
            field.setAttribute('aria-invalid', 'true');
            field.focus();
        }
        HelpdeskUtils.showToast(problem.message, 'warning');
    }

    function clearSplitInvalid(field) {
        field.classList.remove('is-invalid');
        field.removeAttribute('aria-invalid');
    }

    async function confirmSplitTicket() {
        if (!ticketToSplit || _splitSubmitting) return;
        syncSplitPartsFromDom();
        const problem = validateSplitParts();
        if (problem) {
            markSplitInvalid(problem);
            return;
        }

        const toPayload = part => ({
            area: part.area,
            category_id: parseInt(part.category_id, 10),
            priority: part.priority,
            title: part.title.trim(),
            description: part.description.trim()
        });
        // Lo que el usuario no tocó del original viaja tal como está guardado
        // (ver sameSplitText): el servidor solo registra lo que cambió.
        const original = toPayload(splitParts[0]);
        if (sameSplitText(original.title, ticketToSplit.title)) original.title = ticketToSplit.title;
        if (sameSplitText(original.description, ticketToSplit.description)) {
            original.description = ticketToSplit.description;
        }
        const ticketId = ticketToSplit.id;
        const payload = {
            original,
            parts: splitParts.slice(1).map(toPayload)
        };

        const seq = _splitSeq;
        const pageToken = _splitPageToken;
        const btn = document.getElementById('btnConfirmSplit');
        const btnHtml = btn.innerHTML;
        _splitSubmitting = true;
        setSplitFormEnabled(false);
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Partiendo...';

        let result = null;
        try {
            // fetch directo y no HelpdeskUtils.api.request: ese cliente lee
            // `data.message` y descarta el `{"error": ...}` del servidor, así que
            // un 400 con "Parte 3: ..." le llegaría al usuario como "HTTP 400".
            const response = await fetch(`/api/help-desk/v2/tickets/${ticketId}/split`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (response.ok) {
                result = await response.json();
            } else {
                const message = await fetchApiError(response, 'No se pudo partir el ticket');
                HelpdeskUtils.showToast(escapeHtml(message), 'error');
            }
        } catch (error) {
            console.error('Error al partir ticket:', error);
            HelpdeskUtils.showToast('Error de conexión al partir el ticket', 'error');
        } finally {
            _splitSubmitting = false;
            btn.innerHTML = btnHtml;
        }

        // Mismo modal abierto con el mismo ticket (no se cerró ni se fue la página).
        const sameSession = seq === _splitSeq;
        if (!result) {
            if (sameSession) setSplitFormEnabled(true);   // corregir y reintentar
            return;
        }

        // Éxito: el formulario queda deshabilitado hasta que el modal termine de
        // cerrarse, para que un segundo clic no vuelva a partir.
        const folios = ((result.data && result.data.tickets) || []).map(t => t.ticket_number).join(', ');
        const message = `${result.message || 'Ticket partido'}${folios ? `. Nuevos: ${folios}` : ''}`;
        HelpdeskUtils.showToast(escapeHtml(message), 'success');

        if (pageToken !== _splitPageToken) return;   // se navegó a otra página
        if (sameSession && _splitTicketModalInstance) _splitTicketModalInstance.hide();

        // Refrescar arreglos + listas server-side (mismo patrón que asignar)
        await Promise.all([
            loadDashboardStats(),
            loadPendingTickets(),
            loadActiveTickets()
        ]);
        refreshLists();
    }

    // ==================== ERROR HELPERS ====================
    // La API responde {"error": "<texto>", "status": N} (HTTPException) o, en un
    // 422, {"error": "validation_error", "detail": [{msg, ...}]}.
    function extractErrorMessage(data, fallback = 'Error desconocido') {
        if (typeof data === 'string') return data || fallback;
        if (!data || typeof data !== 'object') return fallback;
        if (Array.isArray(data.detail)) {
            return data.detail
                .map(e => (e && typeof e === 'object' && e.msg) ? e.msg : String(e))
                .join('; ') || fallback;
        }
        const val = data.error || data.message || data.detail;
        if (typeof val === 'string') return (val && val !== 'internal_error') ? val : fallback;
        if (val && typeof val === 'object') return extractErrorMessage(val, fallback);
        return fallback;
    }

    async function fetchApiError(response, fallback) {
        try {
            const data = await response.json();
            return extractErrorMessage(data, fallback);
        } catch (_) {
            return `${fallback} (HTTP ${response.status})`;
        }
    }

    // ==================== HELPERS ====================
    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function truncateText(text, maxLength) {
        if (!text) return '';
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }

    function showTicketDetail(ticketId) {
        HelpdeskUtils.goToTicketDetail(ticketId, 'secretary');
    }

    // ==================== REGISTER ====================
    window.HelpdeskPage.page('admin_assign_tickets', { init, destroy });

}());
