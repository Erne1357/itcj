// itcj2/apps/helpdesk/static/js/technician/dashboard.js
// Módulo IIFE — registrado para technician_dashboard / technician_my_assignments / technician_team.
// Cargado por el controller HelpdeskPage (base.js) vía data-hd-modules; NO usa DOMContentLoaded.

(function () {
    'use strict';

    // ==================== MODULE STATE ====================
    // Todo el estado es local al IIFE para que destroy() pueda limpiarlo sin contaminación global.
    var myTickets = {
        assigned: [],
        inProgress: [],
        team: [],
        resolved: []
    };

    var ticketToStart = null;
    var ticketToResolve = null;
    var ticketToSelfAssign = null;

    // WebSocket state
    var techArea = null;
    var socketRoomsBound = false;

    // Intervalo del poller del socket (para clearInterval en destroy)
    var _socketCheckInterval = null;

    // Flag para dropzone de archivos de resolución
    var resDropzoneSetup = false;

    // ==================== INIT / DESTROY (controller API) ====================

    function init() {
        var pageEl = document.querySelector('[data-hd-page]');
        var hdPage = pageEl ? pageEl.getAttribute('data-hd-page') : '';

        // Exponer funciones en window según la página activa.
        // destroy() las elimina todas para evitar fugas.
        if (hdPage === 'technician_dashboard') {
            _initDashboard();
        } else if (hdPage === 'technician_my_assignments') {
            _initMyAssignments();
        } else if (hdPage === 'technician_team') {
            _initTeam();
        }
    }

    function destroy() {
        // Limpiar intervalo del socket poller
        if (_socketCheckInterval) {
            clearInterval(_socketCheckInterval);
            _socketCheckInterval = null;
        }

        // Quitar listeners de socket
        var socket = window.__helpdeskSocket;
        if (socket) {
            socket.off('ticket_assigned');
            socket.off('ticket_reassigned');
            socket.off('ticket_status_changed');
            socket.off('ticket_created');
            socket.off('ticket_self_assigned');
        }

        // Reset estado del módulo
        myTickets = { assigned: [], inProgress: [], team: [], resolved: [] };
        ticketToStart = null;
        ticketToResolve = null;
        ticketToSelfAssign = null;
        techArea = null;
        socketRoomsBound = false;
        resDropzoneSetup = false;

        // Dispose modales de Bootstrap que hayamos creado (si el DOM aún existe)
        var modalIds = ['startWorkModal', 'selfAssignModal', 'resolutionFilesModal', 'attachmentImageModal', 'warehouseQtyModal'];
        modalIds.forEach(function (id) {
            var el = document.getElementById(id);
            if (el) {
                try {
                    var inst = bootstrap.Modal.getInstance(el);
                    if (inst) inst.dispose();
                } catch (e) { /* ignorar */ }
            }
        });

        // Limpiar funciones globales expuestas por este módulo
        var globalFns = [
            'refreshDashboard',
            'openStartWorkModal',
            'openResolveModal',
            'closeResolveTab',
            'openResolutionFilesModal',
            'deleteResolutionFile',
            'viewAttachmentImage',
            'openSelfAssignModal',
            'goToTicketDetailWithState'
        ];
        globalFns.forEach(function (fn) {
            delete window[fn];
        });

        // TicketWarehouse se gestiona por warehouse_ticket.js (IIFE propio); no lo tocamos.
    }

    // ==================== BRANCH: DASHBOARD ====================

    function _initDashboard() {
        // Exponer funciones que usa el HTML del dashboard vía onclick=""
        window.refreshDashboard = refreshDashboard;
        window.openStartWorkModal = openStartWorkModal;
        window.openResolveModal = openResolveModal;
        window.closeResolveTab = closeResolveTab;
        window.openResolutionFilesModal = openResolutionFilesModal;
        window.deleteResolutionFile = deleteResolutionFile;
        window.viewAttachmentImage = viewAttachmentImage;
        window.openSelfAssignModal = openSelfAssignModal;
        window.goToTicketDetailWithState = goToTicketDetailWithState;

        initializeDashboard().then(function () {
            // Restaurar estado si venimos de un detalle de ticket
            var referrer = document.referrer || '';
            if (referrer.includes('/help-desk/user/tickets/') || referrer.includes('/help-desk/technician/tickets/')) {
                var saved = HelpdeskUtils.NavState.load('technician_dashboard');
                if (saved) {
                    if (saved.activeTab) {
                        var tabEl = document.getElementById(saved.activeTab);
                        if (tabEl) bootstrap.Tab.getOrCreateInstance(tabEl).show();
                    }
                    if (saved.historyFilter) {
                        var hf = document.getElementById('historyFilter');
                        if (hf) { hf.value = saved.historyFilter; applyHistoryFilters(); }
                    }
                    if (saved.historySearch) {
                        var hs = document.getElementById('historySearch');
                        if (hs) { hs.value = saved.historySearch; applyHistoryFilters(); }
                    }
                    if (saved.scrollY) {
                        setTimeout(function () { window.scrollTo({ top: saved.scrollY, behavior: 'instant' }); }, 200);
                    }
                }
            }
        });

        setupModals();
        setupFilters();
        setupWebSocketListeners();
    }

    // ==================== BRANCH: MY ASSIGNMENTS ====================

    function _initMyAssignments() {
        window.goToTicketDetailWithState = goToTicketDetailWithState;
        window.openStartWorkModal = openStartWorkModal;
        window.openResolveModal = openResolveModal;
        window.openSelfAssignModal = openSelfAssignModal;

        loadAssignedTickets();
        _setupWebSocketMy();
    }

    function _setupWebSocketMy() {
        _socketCheckInterval = setInterval(function () {
            if (window.__helpdeskSocket) {
                clearInterval(_socketCheckInterval);
                _socketCheckInterval = null;
                _bindSocketMyAssignments();
            }
        }, 100);
        setTimeout(function () {
            if (_socketCheckInterval) { clearInterval(_socketCheckInterval); _socketCheckInterval = null; }
        }, 5000);
    }

    function _bindSocketMyAssignments() {
        if (socketRoomsBound) return;
        var socket = window.__helpdeskSocket;
        if (!socket) return;

        window.__hdJoinTech?.();

        socket.off('ticket_assigned');
        socket.off('ticket_reassigned');
        socket.off('ticket_status_changed');
        socket.off('ticket_created');
        socket.off('ticket_self_assigned');

        var debouncedRefresh = debounce(function () { loadAssignedTickets(); }, 300);
        socket.on('ticket_assigned', debouncedRefresh);
        socket.on('ticket_reassigned', debouncedRefresh);
        socket.on('ticket_status_changed', debouncedRefresh);

        socketRoomsBound = true;
    }

    // ==================== BRANCH: TEAM ====================

    function _initTeam() {
        window.openSelfAssignModal = openSelfAssignModal;
        window.goToTicketDetailWithState = goToTicketDetailWithState;

        loadTeamTickets();
        _setupWebSocketTeam();
    }

    function _setupWebSocketTeam() {
        _socketCheckInterval = setInterval(function () {
            if (window.__helpdeskSocket) {
                clearInterval(_socketCheckInterval);
                _socketCheckInterval = null;
                _bindSocketTeam();
            }
        }, 100);
        setTimeout(function () {
            if (_socketCheckInterval) { clearInterval(_socketCheckInterval); _socketCheckInterval = null; }
        }, 5000);
    }

    async function _bindSocketTeam() {
        if (socketRoomsBound) return;
        var socket = window.__helpdeskSocket;
        if (!socket) return;

        // Obtener área del técnico para unirse al room de equipo
        try {
            var userResp = await fetch('/api/core/v2/user/me');
            var user = await userResp.json();
            var userRoles = (user.data && user.data.roles && user.data.roles.helpdesk) || [];
            if (userRoles.includes('tech_desarrollo')) techArea = 'desarrollo';
            else if (userRoles.includes('tech_soporte')) techArea = 'soporte';
        } catch (e) {
            console.warn('[Team] No se pudo obtener área:', e);
        }

        window.__hdJoinTech?.();
        if (techArea) window.__hdJoinTeam?.(techArea);

        socket.off('ticket_assigned');
        socket.off('ticket_reassigned');
        socket.off('ticket_status_changed');
        socket.off('ticket_created');
        socket.off('ticket_self_assigned');

        var debouncedRefresh = debounce(function () { loadTeamTickets(); }, 300);
        socket.on('ticket_created', function (data) {
            if (techArea && data.area && data.area.toLowerCase() === techArea) debouncedRefresh();
        });
        socket.on('ticket_self_assigned', debouncedRefresh);
        socket.on('ticket_reassigned', debouncedRefresh);

        socketRoomsBound = true;
    }

    // ==================== DASHBOARD INITIALIZATION ====================

    async function initializeDashboard() {
        try {
            await Promise.all([
                loadAssignedTickets(),
                loadInProgressTickets(),
                loadTeamTickets(),
                loadResolvedTickets()
            ]);
            updateDashboardStats();
        } catch (error) {
            console.error('Error initializing dashboard:', error);
            HelpdeskUtils.showToast('Error al cargar el dashboard: ' + (error.message || 'Error desconocido'), 'error');
        }
    }

    async function refreshDashboard() {
        HelpdeskUtils.showToast('Actualizando dashboard...', 'info');
        await initializeDashboard();
        HelpdeskUtils.showToast('Dashboard actualizado', 'success');
    }

    // ==================== LOAD TICKETS ====================

    async function loadAssignedTickets() {
        var container = document.getElementById('queueList') || document.getElementById('assignmentsList');
        if (!container) return;

        HelpdeskUtils.showLoading(container.id);

        try {
            var response = await HelpdeskUtils.api.getTickets({
                assigned_to_me: true,
                status: 'ASSIGNED'
            });

            myTickets.assigned = response.tickets || [];

            var queueBadge = document.getElementById('queueBadge');
            if (queueBadge) queueBadge.textContent = myTickets.assigned.length;

            // my_assignments: actualizar contadores
            var countPending = document.getElementById('countPending');
            if (countPending) countPending.textContent = myTickets.assigned.length;

            // Cargar también los in_progress para my_assignments
            var hdPage = _getHdPage();
            if (hdPage === 'technician_my_assignments') {
                await _loadMyAssignmentsAll(container);
            } else {
                renderTicketList(myTickets.assigned, container, 'assigned');
            }

        } catch (error) {
            console.error('Error loading assigned tickets:', error);
            showErrorState(container);
        }
    }

    async function _loadMyAssignmentsAll(container) {
        // Para my_assignments cargamos todos los estados y mostramos con filtro
        var statusFilter = document.getElementById('statusFilter');
        var status = (statusFilter && statusFilter.value) ? statusFilter.value : '';

        try {
            var params = { assigned_to_me: true };
            if (status) params.status = status;
            else params.status = 'ASSIGNED,IN_PROGRESS,RESOLVED_SUCCESS,RESOLVED_FAILED,CLOSED';

            var response = await HelpdeskUtils.api.getTickets(params);
            var tickets = response.tickets || [];

            // Separar por estado para contadores
            var pending = tickets.filter(function (t) { return t.status === 'ASSIGNED'; });
            var inProg = tickets.filter(function (t) { return t.status === 'IN_PROGRESS'; });
            var resolved = tickets.filter(function (t) { return ['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED'].includes(t.status); });

            var cp = document.getElementById('countPending');
            var ci = document.getElementById('countInProgress');
            var cr = document.getElementById('countResolved');
            var ct = document.getElementById('countTotal');

            if (cp) cp.textContent = pending.length;
            if (ci) ci.textContent = inProg.length;
            if (cr) cr.textContent = resolved.length;
            if (ct) ct.textContent = tickets.length;

            // Determinar tipo para acciones de tarjeta
            if (tickets.length === 0) {
                container.innerHTML = '<div class="text-center py-5 text-muted"><i class="fas fa-check-circle fa-3x mb-3"></i><p>No hay tickets</p></div>';
                return;
            }

            container.innerHTML = tickets.map(function (t) {
                var type = t.status === 'ASSIGNED' ? 'assigned' : (t.status === 'IN_PROGRESS' ? 'inProgress' : 'resolved');
                return createTicketCard(t, type);
            }).join('');

        } catch (error) {
            console.error('Error loading my assignments:', error);
            showErrorState(container);
        }
    }

    async function loadInProgressTickets() {
        var container = document.getElementById('workingList');
        if (!container) return;
        HelpdeskUtils.showLoading('workingList');

        try {
            var response = await HelpdeskUtils.api.getTickets({
                assigned_to_me: true,
                status: 'IN_PROGRESS'
            });

            myTickets.inProgress = response.tickets || [];
            var workingBadge = document.getElementById('workingBadge');
            if (workingBadge) workingBadge.textContent = myTickets.inProgress.length;

            renderTicketList(myTickets.inProgress, container, 'inProgress');
        } catch (error) {
            console.error('Error loading in-progress tickets:', error);
            showErrorState(container);
        }
    }

    async function loadTeamTickets() {
        var container = document.getElementById('teamList');
        if (!container) return;
        HelpdeskUtils.showLoading('teamList');

        try {
            var userResponse = await fetch('/api/core/v2/user/me');
            var user = await userResponse.json();
            var userRoles = (user.data && user.data.roles && user.data.roles.helpdesk) || [];

            var team = null;
            if (userRoles.includes('tech_desarrollo')) team = 'desarrollo';
            else if (userRoles.includes('tech_soporte')) team = 'soporte';

            if (!team) {
                container.innerHTML = '<div class="text-center py-5 text-muted"><i class="fas fa-user-slash fa-3x mb-3"></i><p>No estás asignado a ningún equipo</p></div>';
                // Actualizar badge/contador si existe
                var tc = document.getElementById('teamCount');
                if (tc) tc.textContent = 0;
                var tb = document.getElementById('teamBadge');
                if (tb) tb.textContent = 0;
                return;
            }

            var response = await HelpdeskUtils.api.getTickets({
                assigned_to_team: team,
                status: 'ASSIGNED'
            });

            myTickets.team = response.tickets || [];

            var teamBadge = document.getElementById('teamBadge');
            if (teamBadge) teamBadge.textContent = myTickets.team.length;
            var teamCount = document.getElementById('teamCount');
            if (teamCount) teamCount.textContent = myTickets.team.length;

            // team.html tiene un searchInput — conectarlo si existe
            var searchInput = document.getElementById('searchInput');
            if (searchInput) {
                searchInput.addEventListener('input', function () {
                    var q = this.value.toLowerCase().trim();
                    var filtered = q
                        ? myTickets.team.filter(function (t) {
                            return (t.title || '').toLowerCase().includes(q) ||
                                (t.ticket_number || '').toLowerCase().includes(q);
                        })
                        : myTickets.team;
                    renderTicketList(filtered, container, 'team');
                });
            }

            renderTicketList(myTickets.team, container, 'team');
        } catch (error) {
            console.error('Error loading team tickets:', error);
            showErrorState(container);
        }
    }

    async function loadResolvedTickets() {
        var container = document.getElementById('historyList');
        if (!container) return;
        HelpdeskUtils.showLoading('historyList');

        try {
            var response = await HelpdeskUtils.api.getTickets({
                assigned_to_me: true,
                status: 'RESOLVED_SUCCESS,RESOLVED_FAILED,CLOSED',
                per_page: 20
            });

            myTickets.resolved = response.tickets || [];
            renderTicketList(myTickets.resolved, container, 'resolved');
        } catch (error) {
            console.error('Error loading resolved tickets:', error);
            showErrorState(container);
        }
    }

    // ==================== RENDER TICKETS ====================

    function renderTicketList(tickets, container, type) {
        if (!container) return;
        if (tickets.length === 0) {
            var messages = {
                assigned: { icon: 'inbox', text: 'No tienes tickets asignados', color: 'muted' },
                inProgress: { icon: 'coffee', text: '¡Buen momento para un descanso!', color: 'success' },
                team: { icon: 'users-slash', text: 'No hay tickets del equipo disponibles', color: 'muted' },
                resolved: { icon: 'history', text: 'No hay tickets resueltos', color: 'muted' }
            };
            var msg = messages[type] || { icon: 'inbox', text: 'Sin tickets', color: 'muted' };
            container.innerHTML = '<div class="text-center py-5 text-' + msg.color + '"><i class="fas fa-' + msg.icon + ' fa-3x mb-3"></i><p class="mb-0">' + msg.text + '</p></div>';
            return;
        }
        container.innerHTML = tickets.map(function (ticket) { return createTicketCard(ticket, type); }).join('');
    }

    function createTicketCard(ticket, type) {
        var timeAgo = HelpdeskUtils.formatTimeAgo(ticket.created_at);

        return '<div class="ticket-tech-card border-bottom p-3 priority-' + ticket.priority + '">' +
            '<div class="row align-items-start">' +
            '<div class="col-md-8">' +
            '<div class="d-flex align-items-center flex-wrap gap-1 gap-md-2 mb-2">' +
            '<h6 class="mb-0 fw-bold me-1">' + ticket.ticket_number + '</h6>' +
            '<div class="d-flex flex-wrap gap-1">' +
            HelpdeskUtils.getStatusBadge(ticket.status) +
            HelpdeskUtils.getAreaBadge(ticket.area) +
            (ticket.category ? '<span class="badge bg-secondary">' + ticket.category.name + '</span>' : '') +
            HelpdeskUtils.getPriorityBadge(ticket.priority) +
            '</div></div>' +
            '<h5 class="mb-2">' + ticket.title + '</h5>' +
            '<p class="text-muted mb-2 small">' + truncateText(ticket.description, 120) + '</p>' +
            '<div class="text-muted small d-flex flex-wrap gap-2">' +
            '<span><i class="fas fa-user me-1"></i>' + (ticket.requester ? ticket.requester.name : 'N/A') + '</span>' +
            (ticket.location ? '<span><i class="fas fa-map-marker-alt me-1"></i>' + ticket.location + '</span>' : '') +
            '<span><i class="fas fa-clock me-1"></i>' + timeAgo + '</span>' +
            '</div>' +
            (ticket.resolution_notes && type === 'resolved' ? '<div class="alert alert-success mt-2 mb-0 py-2 small"><strong>Solución:</strong> ' + truncateText(ticket.resolution_notes, 150) + '</div>' : '') +
            (ticket.rating && type === 'resolved' ? '<div class="mt-2">' + HelpdeskUtils.renderStarRating(ticket.rating) + '</div>' : '') +
            '</div>' +
            '<div class="col-md-4 text-md-end mt-2 mt-md-0">' +
            getActionButtons(ticket, type) +
            '</div></div></div>';
    }

    function getActionButtons(ticket, type) {
        var buttons = '';

        if (type === 'assigned') {
            buttons = '<button class="btn btn-primary btn-sm mb-2" onclick="openStartWorkModal(' + ticket.id + ')"><i class="fas fa-play me-1"></i>Iniciar</button>';
        } else if (type === 'inProgress') {
            buttons = '<button class="btn btn-success btn-sm mb-2" onclick="openResolveModal(' + ticket.id + ')"><i class="fas fa-check-circle me-1"></i>Resolver</button>';
        } else if (type === 'team') {
            buttons = '<button class="btn btn-primary btn-sm mb-2" onclick="openSelfAssignModal(' + ticket.id + ')"><i class="fas fa-hand-paper me-1"></i>Tomar</button>';
        }

        buttons += '<button class="btn btn-outline-secondary btn-sm d-block w-100" onclick="goToTicketDetailWithState(' + ticket.id + ')"><i class="fas fa-eye me-1"></i>Ver Detalle</button>';

        return buttons;
    }

    function goToTicketDetailWithState(ticketId) {
        var activeTabEl = document.querySelector('#technicianTabs .nav-link.active');
        HelpdeskUtils.NavState.save('technician_dashboard', {
            activeTab: activeTabEl ? activeTabEl.id : 'queue-tab',
            historyFilter: document.getElementById('historyFilter') ? document.getElementById('historyFilter').value : '',
            historySearch: document.getElementById('historySearch') ? document.getElementById('historySearch').value : '',
            scrollY: window.scrollY,
        });
        HelpdeskUtils.goToTicketDetail(ticketId, 'technician');
    }

    // ==================== DASHBOARD STATS ====================

    async function updateDashboardStats() {
        var myTicketsCount = document.getElementById('myTicketsCount');
        var assignedCount = document.getElementById('assignedCount');
        var inProgressCount = document.getElementById('inProgressCount');
        var resolvedTodayCount = document.getElementById('resolvedTodayCount');

        if (!myTicketsCount) return; // no estamos en el dashboard

        try {
            var response = await HelpdeskUtils.api.getTechnicianStats();
            var stats = response.data;
            var totalTickets = stats.assigned_count + stats.in_progress_count;
            myTicketsCount.textContent = totalTickets;
            if (assignedCount) assignedCount.textContent = stats.assigned_count;
            if (inProgressCount) inProgressCount.textContent = stats.in_progress_count;
            if (resolvedTodayCount) resolvedTodayCount.textContent = stats.resolved_today_count || 0;
        } catch (error) {
            console.error('Error loading technician stats:', error);
            var totalTickets = myTickets.assigned.length + myTickets.inProgress.length;
            var today = new Date();
            today.setHours(0, 0, 0, 0);
            var resolvedToday = myTickets.resolved.filter(function (t) {
                return new Date(t.resolved_at) >= today;
            }).length;
            myTicketsCount.textContent = totalTickets;
            if (assignedCount) assignedCount.textContent = myTickets.assigned.length;
            if (inProgressCount) inProgressCount.textContent = myTickets.inProgress.length;
            if (resolvedTodayCount) resolvedTodayCount.textContent = resolvedToday;
        }
    }

    // ==================== START WORK MODAL ====================

    function setupModals() {
        var btnStart = document.getElementById('btnConfirmStart');
        if (btnStart) btnStart.addEventListener('click', confirmStartWork);

        var btnResolve = document.getElementById('btnConfirmResolve');
        if (btnResolve) btnResolve.addEventListener('click', confirmResolve);

        var btnSelfAssign = document.getElementById('btnConfirmSelfAssign');
        if (btnSelfAssign) btnSelfAssign.addEventListener('click', confirmSelfAssign);

        var resolutionNotes = document.getElementById('resolutionNotes');
        if (resolutionNotes) {
            resolutionNotes.addEventListener('input', updateNotesCounter);
            resolutionNotes.addEventListener('blur', updateNotesCounter);
        }
    }

    function openStartWorkModal(ticketId) {
        ticketToStart = myTickets.assigned.find(function (t) { return t.id === ticketId; });
        if (!ticketToStart) return;

        var infoEl = document.getElementById('startWorkTicketInfo');
        if (infoEl) {
            infoEl.innerHTML = '<h6 class="mb-2">' + ticketToStart.ticket_number + ': ' + ticketToStart.title + '</h6><div class="d-flex gap-2">' + HelpdeskUtils.getPriorityBadge(ticketToStart.priority) + HelpdeskUtils.getAreaBadge(ticketToStart.area) + '</div>';
        }

        var btn = document.getElementById('btnConfirmStart');
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-play me-2"></i>Sí, Iniciar'; }

        var modalEl = document.getElementById('startWorkModal');
        if (modalEl) new bootstrap.Modal(modalEl).show();
    }

    async function confirmStartWork() {
        if (!ticketToStart) return;

        var btn = document.getElementById('btnConfirmStart');
        var originalText = btn ? btn.innerHTML : '';
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Iniciando...'; }

        try {
            await HelpdeskUtils.api.startTicket(ticketToStart.id);
            HelpdeskUtils.showToast('¡Ticket iniciado! Ahora está en progreso', 'success');

            var modalEl = document.getElementById('startWorkModal');
            if (modalEl) {
                var m = bootstrap.Modal.getInstance(modalEl);
                if (m) m.hide();
            }

            await Promise.all([loadAssignedTickets(), loadInProgressTickets()]);
            updateDashboardStats();
        } catch (error) {
            console.error('Error starting ticket:', error);
            HelpdeskUtils.showToast('Error al iniciar ticket: ' + (error.message || 'Error desconocido'), 'error');
            if (btn) { btn.disabled = false; btn.innerHTML = originalText; }
        }
    }

    // ==================== RESOLVE TAB ====================

    function openResolveModal(ticketId) {
        ticketToResolve = myTickets.inProgress.find(function (t) { return t.id === ticketId; });
        if (!ticketToResolve) return;

        var resolveTicketInfo = document.getElementById('resolveTicketInfo');
        if (resolveTicketInfo) {
            resolveTicketInfo.innerHTML = '<h6 class="mb-2">' + ticketToResolve.ticket_number + ': ' + ticketToResolve.title + '</h6><div class="d-flex gap-2 mb-2">' + HelpdeskUtils.getStatusBadge(ticketToResolve.status) + HelpdeskUtils.getPriorityBadge(ticketToResolve.priority) + '</div><p class="mb-0 small text-muted">' + truncateText(ticketToResolve.description, 200) + '</p>';
        }

        var refTitle = document.getElementById('resolveRefTitle');
        var refDesc = document.getElementById('resolveRefDesc');
        var refMeta = document.getElementById('resolveRefMeta');
        if (refTitle) refTitle.textContent = ticketToResolve.ticket_number + ': ' + ticketToResolve.title;
        if (refDesc) refDesc.textContent = ticketToResolve.description || '-';
        if (refMeta) refMeta.innerHTML = HelpdeskUtils.getStatusBadge(ticketToResolve.status) + HelpdeskUtils.getPriorityBadge(ticketToResolve.priority);

        var notesField = document.getElementById('resolutionNotes');
        if (notesField) {
            notesField.value = '';
            notesField.classList.remove('is-invalid', 'is-valid');
        }
        var resSuccess = document.getElementById('resolutionSuccess');
        if (resSuccess) resSuccess.checked = true;
        var timeInvested = document.getElementById('timeInvested');
        if (timeInvested) timeInvested.value = '';
        var timeUnit = document.getElementById('timeUnit');
        if (timeUnit) timeUnit.value = 'minutes';
        updateNotesCounter();

        var btn = document.getElementById('btnConfirmResolve');
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-check-circle me-2"></i>Resolver Ticket'; }

        updateResolutionFilesCount(0);

        var isSoporte = ticketToResolve.area === 'SOPORTE';
        var soporteFields = document.getElementById('soporteOnlyFields');
        var observationsField = document.getElementById('observationsField');
        if (soporteFields) soporteFields.style.display = isSoporte ? '' : 'none';
        if (observationsField) observationsField.style.display = isSoporte ? '' : 'none';

        if (typeof TicketWarehouse !== 'undefined') TicketWarehouse.reset();

        var tabLabel = document.getElementById('resolveTabLabel');
        if (tabLabel) tabLabel.textContent = ticketToResolve.ticket_number;
        var tabItem = document.getElementById('resolveTabItem');
        if (tabItem) tabItem.classList.remove('d-none');
        var resolveTabEl = document.getElementById('resolve-tab');
        if (resolveTabEl) new bootstrap.Tab(resolveTabEl).show();

        loadAvailableTechnicians(ticketToResolve);
    }

    function closeResolveTab() {
        var tabItem = document.getElementById('resolveTabItem');
        if (tabItem) tabItem.classList.add('d-none');
        var workingTabEl = document.getElementById('working-tab');
        if (workingTabEl) new bootstrap.Tab(workingTabEl).show();
    }

    function updateNotesCounter() {
        var notesField = document.getElementById('resolutionNotes');
        var counter = document.getElementById('resolutionNotesCounter');
        if (!notesField || !counter) return;
        var length = notesField.value.trim().length;
        counter.textContent = length + ' / 10 caracteres mínimo';
        if (length >= 10) {
            notesField.classList.remove('is-invalid');
            notesField.classList.add('is-valid');
            counter.classList.remove('text-danger');
            counter.classList.add('text-success');
        } else if (length > 0) {
            notesField.classList.remove('is-valid');
            notesField.classList.add('is-invalid');
            counter.classList.remove('text-success');
            counter.classList.add('text-danger');
        } else {
            notesField.classList.remove('is-invalid', 'is-valid');
            counter.classList.remove('text-success', 'text-danger');
        }
    }

    async function loadAvailableTechnicians(ticket) {
        var container = document.getElementById('collaboratorsList');
        if (!container) return;

        container.innerHTML = '<div class="text-center text-muted py-2"><span class="spinner-border spinner-border-sm me-2"></span>Cargando técnicos...</div>';

        try {
            var response = await fetch('/api/help-desk/v2/assignments/technicians/' + ticket.area);
            if (!response.ok) throw new Error('Error al cargar técnicos');
            var data = await response.json();
            var technicians = data.technicians || [];

            if (technicians.length === 0) {
                container.innerHTML = '<div class="text-center text-muted py-2"><i class="fas fa-users-slash me-2"></i>No hay técnicos disponibles</div>';
                return;
            }

            container.innerHTML = technicians.map(function (tech) {
                var isAssigned = ticket.assigned_to && tech.id === ticket.assigned_to.id;
                return '<div class="form-check mb-2"><input class="form-check-input collaborator-check" type="checkbox" value="' + tech.id + '" id="collab_' + tech.id + '"' + (isAssigned ? ' checked disabled' : '') + '><label class="form-check-label d-flex justify-content-between align-items-center w-100" for="collab_' + tech.id + '"><span>' + tech.name + (isAssigned ? '<span class="badge bg-primary ms-2">Asignado</span>' : '') + '</span><small class="text-muted">' + tech.active_tickets + ' activos</small></label></div>';
            }).join('');
        } catch (error) {
            console.error('Error loading technicians:', error);
            container.innerHTML = '<div class="text-center text-danger py-2"><i class="fas fa-exclamation-triangle me-2"></i><small>Error al cargar técnicos</small></div>';
        }
    }

    async function confirmResolve() {
        if (!ticketToResolve) return;

        var isSoporte = ticketToResolve.area === 'SOPORTE';
        var resTypeEl = document.querySelector('input[name="resolutionType"]:checked');
        var resolutionType = resTypeEl ? resTypeEl.value : 'success';
        var notesEl = document.getElementById('resolutionNotes');
        var notes = notesEl ? notesEl.value.trim() : '';
        var maintenanceTypeEl = isSoporte ? document.querySelector('input[name="maintenanceType"]:checked') : null;
        var maintenanceType = maintenanceTypeEl ? maintenanceTypeEl.value : null;
        var serviceOriginEl = isSoporte ? document.querySelector('input[name="serviceOrigin"]:checked') : null;
        var serviceOrigin = serviceOriginEl ? serviceOriginEl.value : null;
        var obsEl = isSoporte ? document.getElementById('observations') : null;
        var observations = obsEl ? (obsEl.value.trim() || null) : null;

        var timeValueEl = document.getElementById('timeInvested');
        var timeUnitEl = document.getElementById('timeUnit');
        var timeValue = timeValueEl ? (parseFloat(timeValueEl.value) || null) : null;
        var timeUnit = timeUnitEl ? timeUnitEl.value : 'minutes';
        var timeInvested = null;

        if (timeValue && timeValue > 0) {
            if (timeUnit === 'hours') timeInvested = Math.round(timeValue * 60);
            else if (timeUnit === 'days') timeInvested = Math.round(timeValue * 8 * 60);
            else timeInvested = Math.round(timeValue);
        }

        if (isSoporte && !maintenanceType) { HelpdeskUtils.showToast('Debe seleccionar el tipo de mantenimiento', 'warning'); return; }
        if (isSoporte && !serviceOrigin) { HelpdeskUtils.showToast('Debe seleccionar el origen del equipo', 'warning'); return; }

        if (!notes || notes.length < 10) {
            HelpdeskUtils.showToast('Las notas de resolución deben tener al menos 10 caracteres', 'warning');
            if (notesEl) { notesEl.focus(); notesEl.classList.add('is-invalid'); notesEl.classList.remove('is-valid'); updateNotesCounter(); }
            return;
        }
        if (notesEl) { notesEl.classList.remove('is-invalid'); notesEl.classList.add('is-valid'); }

        if (!timeInvested || timeInvested <= 0) {
            HelpdeskUtils.showToast('El tiempo invertido es requerido', 'warning');
            if (timeValueEl) timeValueEl.focus();
            return;
        }

        var btn = document.getElementById('btnConfirmResolve');
        var originalText = btn ? btn.innerHTML : '';
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Resolviendo...'; }

        try {
            if (typeof TicketWarehouse !== 'undefined') await TicketWarehouse.consumeAll(ticketToResolve.id);

            await HelpdeskUtils.api.resolveTicket(ticketToResolve.id, {
                success: resolutionType === 'success',
                resolution_notes: notes,
                time_invested_minutes: timeInvested,
                maintenance_type: maintenanceType,
                service_origin: serviceOrigin,
                observations: observations
            });

            var selectedCollaborators = [];
            document.querySelectorAll('.collaborator-check:checked:not(:disabled)').forEach(function (checkbox) {
                selectedCollaborators.push({ user_id: parseInt(checkbox.value), collaboration_role: 'COLLABORATOR', time_invested_minutes: null, notes: null });
            });
            if (ticketToResolve.assigned_to && ticketToResolve.assigned_to.id) {
                selectedCollaborators.push({ user_id: ticketToResolve.assigned_to.id, collaboration_role: 'LEAD', time_invested_minutes: timeInvested, notes: notes });
            }
            if (selectedCollaborators.length > 0) {
                try {
                    var collabResp = await fetch('/api/help-desk/v2/tickets/' + ticketToResolve.id + '/collaborators/batch', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ collaborators: selectedCollaborators })
                    });
                    if (collabResp.ok) {
                        var cd = await collabResp.json();
                        console.log(cd.count + ' colaboradores agregados');
                    }
                } catch (e) { console.error('Error adding collaborators:', e); }
            }

            HelpdeskUtils.showToast(resolutionType === 'success' ? '¡Ticket resuelto exitosamente!' : 'Ticket marcado como atendido', 'success');
            closeResolveTab();
            await Promise.all([loadInProgressTickets(), loadResolvedTickets()]);
            updateDashboardStats();
        } catch (error) {
            console.error('Error resolving ticket:', error);
            HelpdeskUtils.showToast('Error al resolver ticket: ' + (error.message || 'Error desconocido'), 'error');
            if (btn) { btn.disabled = false; btn.innerHTML = originalText; }
        }
    }

    // ==================== SELF-ASSIGN MODAL ====================

    function openSelfAssignModal(ticketId) {
        ticketToSelfAssign = myTickets.team.find(function (t) { return t.id === ticketId; }) ||
                             myTickets.assigned.find(function (t) { return t.id === ticketId; });
        if (!ticketToSelfAssign) return;

        var infoEl = document.getElementById('selfAssignTicketInfo');
        if (infoEl) {
            infoEl.innerHTML = '<h6 class="mb-2">' + ticketToSelfAssign.ticket_number + ': ' + ticketToSelfAssign.title + '</h6><div class="d-flex gap-2">' + HelpdeskUtils.getPriorityBadge(ticketToSelfAssign.priority) + HelpdeskUtils.getAreaBadge(ticketToSelfAssign.area) + '</div>';
        }

        var btn = document.getElementById('btnConfirmSelfAssign');
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-hand-paper me-2"></i>Sí, Tomar Ticket'; }

        var modalEl = document.getElementById('selfAssignModal');
        if (modalEl) new bootstrap.Modal(modalEl).show();
    }

    async function confirmSelfAssign() {
        if (!ticketToSelfAssign) return;

        var btn = document.getElementById('btnConfirmSelfAssign');
        var originalText = btn ? btn.innerHTML : '';
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Asignando...'; }

        try {
            await HelpdeskUtils.api.selfAssignTicket(ticketToSelfAssign.id);
            HelpdeskUtils.showToast('¡Ticket asignado a ti!', 'success');
            if (btn) { btn.disabled = false; btn.innerHTML = originalText; }

            var modalEl = document.getElementById('selfAssignModal');
            if (modalEl) {
                var m = bootstrap.Modal.getInstance(modalEl);
                if (m) m.hide();
            }

            await Promise.all([loadAssignedTickets(), loadTeamTickets()]);
            updateDashboardStats();
        } catch (error) {
            console.error('Error self-assigning ticket:', error);
            HelpdeskUtils.showToast('Error al tomar ticket: ' + (error.message || 'Error desconocido'), 'error');
            if (btn) { btn.disabled = false; btn.innerHTML = originalText; }
        }
    }

    // ==================== FILTERS ====================

    function setupFilters() {
        var historyFilter = document.getElementById('historyFilter');
        var historySearch = document.getElementById('historySearch');

        if (historyFilter) historyFilter.addEventListener('change', applyHistoryFilters);

        if (historySearch) {
            var searchTimeout;
            historySearch.addEventListener('input', function () {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(applyHistoryFilters, 300);
            });
        }
    }

    function applyHistoryFilters() {
        var filterEl = document.getElementById('historyFilter');
        var searchEl = document.getElementById('historySearch');
        var filter = filterEl ? filterEl.value : '';
        var search = searchEl ? searchEl.value.toLowerCase().trim() : '';

        var filtered = myTickets.resolved.slice();
        var now = new Date();

        if (filter === 'today') {
            var today = new Date(); today.setHours(0, 0, 0, 0);
            filtered = filtered.filter(function (t) { return new Date(t.resolved_at) >= today; });
        } else if (filter === 'week') {
            var weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
            filtered = filtered.filter(function (t) { return new Date(t.resolved_at) >= weekAgo; });
        } else if (filter === 'month') {
            var monthAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
            filtered = filtered.filter(function (t) { return new Date(t.resolved_at) >= monthAgo; });
        }

        if (search) {
            filtered = filtered.filter(function (t) {
                return (t.title || '').toLowerCase().includes(search) ||
                    (t.ticket_number || '').toLowerCase().includes(search) ||
                    (t.description || '').toLowerCase().includes(search);
            });
        }

        var historyList = document.getElementById('historyList');
        if (historyList) renderTicketList(filtered, historyList, 'resolved');
    }

    // ==================== WEBSOCKET (DASHBOARD) ====================

    function setupWebSocketListeners() {
        _socketCheckInterval = setInterval(function () {
            if (window.__helpdeskSocket) {
                clearInterval(_socketCheckInterval);
                _socketCheckInterval = null;
                bindSocketEvents();
            }
        }, 100);
        setTimeout(function () {
            if (_socketCheckInterval) { clearInterval(_socketCheckInterval); _socketCheckInterval = null; }
        }, 5000);
    }

    async function bindSocketEvents() {
        if (socketRoomsBound) return;
        var socket = window.__helpdeskSocket;
        if (!socket) { console.warn('[Dashboard] Socket no disponible'); return; }

        try {
            var userResponse = await fetch('/api/core/v2/user/me');
            var user = await userResponse.json();
            var userRoles = (user.data && user.data.roles && user.data.roles.helpdesk) || [];
            if (userRoles.includes('tech_desarrollo')) techArea = 'desarrollo';
            else if (userRoles.includes('tech_soporte')) techArea = 'soporte';
        } catch (e) {
            console.warn('[Dashboard] No se pudo obtener área del técnico:', e);
        }

        window.__hdJoinTech?.();
        if (techArea) window.__hdJoinTeam?.(techArea);

        var debouncedRefreshAssigned = debounce(function () {
            loadAssignedTickets();
            updateDashboardStats();
            showRealtimeToast('Nueva asignación recibida');
        }, 250);

        var debouncedRefreshTeam = debounce(function () {
            loadTeamTickets();
            updateDashboardStats();
        }, 250);

        var debouncedRefreshAll = debounce(function () {
            loadAssignedTickets();
            loadInProgressTickets();
            loadTeamTickets();
            updateDashboardStats();
        }, 250);

        socket.off('ticket_assigned');
        socket.off('ticket_reassigned');
        socket.off('ticket_status_changed');
        socket.off('ticket_created');
        socket.off('ticket_self_assigned');

        socket.on('ticket_assigned', function (data) {
            console.log('[Dashboard] ticket_assigned:', data);
            debouncedRefreshAssigned();
        });

        socket.on('ticket_reassigned', function (data) {
            console.log('[Dashboard] ticket_reassigned:', data);
            debouncedRefreshAll();
            showRealtimeToast('Ticket reasignado');
        });

        socket.on('ticket_status_changed', function (data) {
            console.log('[Dashboard] ticket_status_changed:', data);
            var activeTab = document.querySelector('.nav-link.active[data-bs-toggle="tab"]');
            var tabId = activeTab ? (activeTab.getAttribute('href') || '') : '';
            if (tabId.includes('queue')) loadAssignedTickets();
            else if (tabId.includes('working')) loadInProgressTickets();
            else if (tabId.includes('team')) loadTeamTickets();
            else if (tabId.includes('history')) loadResolvedTickets();
            updateDashboardStats();
        });

        socket.on('ticket_created', function (data) {
            console.log('[Dashboard] ticket_created:', data);
            if (techArea && data.area && data.area.toLowerCase() === techArea) {
                debouncedRefreshTeam();
                showRealtimeToast('Nuevo ticket: ' + data.ticket_number);
            }
        });

        socket.on('ticket_self_assigned', function (data) {
            console.log('[Dashboard] ticket_self_assigned:', data);
            debouncedRefreshTeam();
        });

        socketRoomsBound = true;
        console.log('[Dashboard] WebSocket listeners configurados');
    }

    function showRealtimeToast(message) {
        if (window.HelpdeskUtils && window.HelpdeskUtils.showToast) {
            HelpdeskUtils.showToast(message, 'info');
        }
    }

    // ==================== RESOLUTION FILES ====================

    function getFileIcon(filename) {
        var ext = filename.split('.').pop().toLowerCase();
        var icons = {
            pdf: 'fas fa-file-pdf text-danger',
            xlsx: 'fas fa-file-excel text-success',
            xls: 'fas fa-file-excel text-success',
            csv: 'fas fa-file-csv text-success',
            doc: 'fas fa-file-word text-primary',
            docx: 'fas fa-file-word text-primary'
        };
        return icons[ext] || 'fas fa-file text-secondary';
    }

    function formatFileSize(bytes) {
        if (!bytes) return '0 B';
        var k = 1024;
        var sizes = ['B', 'KB', 'MB'];
        var i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    function openResolutionFilesModal() {
        if (!ticketToResolve) return;
        var modalEl = document.getElementById('resolutionFilesModal');
        if (!modalEl) return;
        loadResolutionFiles();
        setupResolutionDropzone();
        new bootstrap.Modal(modalEl).show();
    }

    function setupResolutionDropzone() {
        if (resDropzoneSetup) return;
        resDropzoneSetup = true;

        var dropzone = document.getElementById('resolutionDropzone');
        var input = document.getElementById('resolutionFileInput');
        if (!dropzone || !input) return;

        dropzone.addEventListener('click', function () { input.click(); });

        dropzone.addEventListener('dragover', function (e) {
            e.preventDefault();
            dropzone.style.borderColor = '#0d6efd';
            dropzone.style.backgroundColor = '#f0f7ff';
        });

        dropzone.addEventListener('dragleave', function () {
            dropzone.style.borderColor = '#dee2e6';
            dropzone.style.backgroundColor = '';
        });

        dropzone.addEventListener('drop', function (e) {
            e.preventDefault();
            dropzone.style.borderColor = '#dee2e6';
            dropzone.style.backgroundColor = '';
            uploadResolutionFiles(Array.from(e.dataTransfer.files));
        });

        input.addEventListener('change', function () {
            uploadResolutionFiles(Array.from(this.files));
            this.value = '';
        });
    }

    async function loadResolutionFiles() {
        if (!ticketToResolve) return;
        try {
            var response = await HelpdeskUtils.api.getAttachmentsByType(ticketToResolve.id, 'resolution');
            var attachments = response.attachments || [];
            renderResolutionFilesList(attachments);
            updateResolutionFilesCount(attachments.length);
        } catch (error) {
            console.error('Error loading resolution files:', error);
        }
    }

    function renderResolutionFilesList(attachments) {
        var container = document.getElementById('resolutionFilesList');
        if (!container) return;
        if (attachments.length === 0) {
            container.innerHTML = '<div class="text-center text-muted py-3"><i class="fas fa-folder-open fa-2x mb-2"></i><p class="mb-0">Sin archivos adjuntos</p></div>';
            return;
        }
        container.innerHTML = attachments.map(function (att) {
            var isImage = att.mime_type && att.mime_type.startsWith('image/');
            var downloadUrl = '/api/help-desk/v2/attachments/' + att.id + '/download';
            var icon = isImage ? 'fas fa-image text-info' : getFileIcon(att.original_filename);
            return '<div class="d-flex align-items-center justify-content-between border rounded p-2 mb-2">' +
                '<div class="d-flex align-items-center gap-2 flex-grow-1 min-width-0">' +
                (isImage ? '<img src="' + downloadUrl + '" class="rounded" style="width:40px;height:40px;object-fit:cover;cursor:pointer;" onclick="viewAttachmentImage(\'' + downloadUrl + '\', \'' + att.original_filename + '\')">' : '<i class="' + icon + ' fa-lg"></i>') +
                '<div class="min-width-0"><div class="text-truncate fw-semibold" style="max-width:300px;" title="' + att.original_filename + '">' + att.original_filename + '</div><small class="text-muted">' + formatFileSize(att.file_size) + ' - ' + HelpdeskUtils.formatTimeAgo(att.uploaded_at) + '</small></div>' +
                '</div><div class="d-flex gap-1 flex-shrink-0">' +
                '<a href="' + downloadUrl + '" class="btn btn-sm btn-outline-primary" download="' + att.original_filename + '" title="Descargar"><i class="fas fa-download"></i></a>' +
                '<button class="btn btn-sm btn-outline-danger" onclick="deleteResolutionFile(' + att.id + ')" title="Eliminar"><i class="fas fa-trash"></i></button>' +
                '</div></div>';
        }).join('');
    }

    function updateResolutionFilesCount(count) {
        var badge = document.getElementById('resolutionFilesCount');
        if (badge) badge.textContent = count;
        var modalCount = document.getElementById('resFilesModalCount');
        if (modalCount) modalCount.textContent = count + ' / 10';
    }

    async function uploadResolutionFiles(files) {
        if (!ticketToResolve || !files.length) return;

        var progressContainer = document.getElementById('resUploadProgress');
        var progressBar = document.getElementById('resUploadBar');
        var progressText = document.getElementById('resUploadText');

        if (progressContainer) progressContainer.classList.remove('d-none');
        var uploaded = 0;

        for (var i = 0; i < files.length; i++) {
            var file = files[i];
            if (progressText) progressText.textContent = 'Subiendo ' + file.name + '...';
            if (progressBar) progressBar.style.width = (uploaded / files.length * 100) + '%';
            try {
                await HelpdeskUtils.api.uploadFile(ticketToResolve.id, file, 'resolution');
                uploaded++;
            } catch (error) {
                HelpdeskUtils.showToast('Error al subir ' + file.name + ': ' + error.message, 'error');
            }
        }

        if (progressBar) progressBar.style.width = '100%';
        if (progressText) progressText.textContent = uploaded + ' de ' + files.length + ' archivos subidos';
        setTimeout(function () {
            if (progressContainer) progressContainer.classList.add('d-none');
            if (progressBar) progressBar.style.width = '0%';
        }, 1500);

        if (uploaded > 0) HelpdeskUtils.showToast(uploaded + ' archivo(s) subido(s)', 'success');
        loadResolutionFiles();
    }

    async function deleteResolutionFile(attachmentId) {
        var confirmed = await HelpdeskUtils.confirmDialog('Eliminar archivo', '¿Estás seguro de eliminar este archivo?', 'Eliminar', 'Cancelar');
        if (!confirmed) return;
        try {
            await HelpdeskUtils.api.deleteAttachment(attachmentId);
            HelpdeskUtils.showToast('Archivo eliminado', 'success');
            loadResolutionFiles();
        } catch (error) {
            HelpdeskUtils.showToast('Error al eliminar: ' + error.message, 'error');
        }
    }

    function viewAttachmentImage(url, title) {
        var modalEl = document.getElementById('attachmentImageModal');
        if (!modalEl) return;
        var imgEl = document.getElementById('attachmentImageModalImg');
        var titleEl = document.getElementById('attachmentImageTitle');
        if (imgEl) imgEl.src = url;
        if (titleEl) titleEl.innerHTML = '<i class="fas fa-image me-2"></i>' + (title || 'Imagen');
        new bootstrap.Modal(modalEl).show();
    }

    // ==================== HELPERS ====================

    function _getHdPage() {
        var el = document.querySelector('[data-hd-page]');
        return el ? el.getAttribute('data-hd-page') : '';
    }

    function truncateText(text, maxLength) {
        if (!text) return '';
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }

    function showErrorState(container) {
        if (!container) return;
        container.innerHTML = '<div class="text-center py-5"><i class="fas fa-exclamation-triangle fa-3x text-danger mb-3"></i><p class="text-danger">Error al cargar tickets</p><button class="btn btn-primary" onclick="refreshDashboard ? refreshDashboard() : location.reload()"><i class="fas fa-redo me-2"></i>Reintentar</button></div>';
    }

    function debounce(fn, delay) {
        var timeoutId;
        return function () {
            var args = arguments;
            var ctx = this;
            clearTimeout(timeoutId);
            timeoutId = setTimeout(function () { fn.apply(ctx, args); }, delay);
        };
    }

    // ==================== CONTROLLER REGISTRATION ====================
    // Registrar las 3 claves con el mismo objeto hooks.
    // El controller (base.js) invocará init() cuando la página activa coincida.
    var hooks = { init: init, destroy: destroy };
    window.HelpdeskPage.page('technician_dashboard', hooks);
    window.HelpdeskPage.page('technician_my_assignments', hooks);
    window.HelpdeskPage.page('technician_team', hooks);

})();
