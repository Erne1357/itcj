// itcj2/apps/helpdesk/static/js/technician/dashboard.js
// Módulo IIFE — registrado para technician_dashboard. Cargado por HelpdeskPage.
//
// Migrado (docs/auditoria_ui_helpdesk.md §8): las 4 listas (asignados/en progreso/
// equipo/historial) las rinde el server (fragmento + macro ticket_card) y se
// recargan por HTMX (htmx.ajax a ?tab=...). Los modales de acción (Iniciar/Resolver/
// Tomar) leen los datos del ticket desde data-* del botón (sin arrays JS). El flujo
// de RESOLVER (tab con almacén + colaboradores + archivos) se conserva igual.

(function () {
    'use strict';

    // ==================== MODULE STATE ====================
    var ticketToStart = null;
    var ticketToResolve = null;
    var ticketToSelfAssign = null;

    var techArea = null;
    var socketRoomsBound = false;
    var _socketCheckInterval = null;
    var resDropzoneSetup = false;

    var TAB_TARGET = {
        assigned: '#hd-tab-queue',
        inProgress: '#hd-tab-working',
        team: '#hd-tab-team',
        resolved: '#hd-tab-history'
    };

    // ==================== INIT / DESTROY ====================
    function init() {
        var pageEl = document.querySelector('[data-hd-page]');
        var hdPage = pageEl ? pageEl.getAttribute('data-hd-page') : '';
        if (hdPage === 'technician_dashboard') _initDashboard();
    }

    function destroy() {
        if (_socketCheckInterval) { clearInterval(_socketCheckInterval); _socketCheckInterval = null; }
        var socket = window.__helpdeskSocket;
        if (socket) {
            socket.off('ticket_assigned');
            socket.off('ticket_reassigned');
            socket.off('ticket_status_changed');
            socket.off('ticket_created');
            socket.off('ticket_self_assigned');
        }
        ticketToStart = null; ticketToResolve = null; ticketToSelfAssign = null;
        techArea = null; socketRoomsBound = false; resDropzoneSetup = false;

        ['startWorkModal', 'selfAssignModal', 'resolutionFilesModal', 'attachmentImageModal', 'warehouseQtyModal'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) { try { var inst = bootstrap.Modal.getInstance(el); if (inst) inst.dispose(); } catch (e) { /* ignore */ } }
        });

        ['refreshDashboard', 'openStartWorkModal', 'openResolveModal', 'closeResolveTab',
         'openResolutionFilesModal', 'deleteResolutionFile', 'viewAttachmentImage', 'openSelfAssignModal'
        ].forEach(function (fn) { delete window[fn]; });
    }

    function _initDashboard() {
        window.refreshDashboard = refreshDashboard;
        window.openStartWorkModal = openStartWorkModal;
        window.openResolveModal = openResolveModal;
        window.closeResolveTab = closeResolveTab;
        window.openResolutionFilesModal = openResolutionFilesModal;
        window.deleteResolutionFile = deleteResolutionFile;
        window.viewAttachmentImage = viewAttachmentImage;
        window.openSelfAssignModal = openSelfAssignModal;

        updateDashboardStats();
        setupModals();
        setupWebSocketListeners();
    }

    // ==================== LISTAS (server-side; refresh por HTMX) ====================
    function refreshTab(tab) {
        var target = TAB_TARGET[tab];
        if (!target || !window.htmx) return;
        var url = '/help-desk/technician/dashboard?tab=' + tab;
        if (tab === 'resolved') {
            var hf = document.getElementById('historyFilter');
            var hs = document.getElementById('historySearch');
            if (hf) url += '&hist=' + encodeURIComponent(hf.value || 'all');
            if (hs && hs.value) url += '&search=' + encodeURIComponent(hs.value);
        }
        window.htmx.ajax('GET', url, { target: target, swap: 'innerHTML' });
    }

    function refreshAll() {
        ['assigned', 'inProgress', 'team', 'resolved'].forEach(refreshTab);
    }

    async function refreshDashboard() {
        HelpdeskUtils.showToast('Actualizando dashboard...', 'info');
        refreshAll();
        await updateDashboardStats();
        HelpdeskUtils.showToast('Dashboard actualizado', 'success');
    }

    // Reconstruye el objeto ticket que necesitan los modales desde los data-* del botón.
    function _ticketFromBtn(btn) {
        var d = btn.dataset;
        return {
            id: parseInt(d.id, 10),
            ticket_number: d.number,
            title: d.title,
            description: d.description || '',
            priority: d.priority,
            area: d.area,
            status: d.status,
            assigned_to: d.assignedId ? { id: parseInt(d.assignedId, 10) } : null
        };
    }

    // ==================== DASHBOARD STATS ====================
    async function updateDashboardStats() {
        var myTicketsCount = document.getElementById('myTicketsCount');
        if (!myTicketsCount) return;
        try {
            var response = await HelpdeskUtils.api.getTechnicianStats();
            var stats = response.data;
            myTicketsCount.textContent = (stats.assigned_count + stats.in_progress_count);
            var a = document.getElementById('assignedCount'); if (a) a.textContent = stats.assigned_count;
            var ip = document.getElementById('inProgressCount'); if (ip) ip.textContent = stats.in_progress_count;
            var rt = document.getElementById('resolvedTodayCount'); if (rt) rt.textContent = stats.resolved_today_count || 0;
        } catch (error) {
            console.error('Error loading technician stats:', error);
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

    function openStartWorkModal(btn) {
        ticketToStart = _ticketFromBtn(btn);
        if (!ticketToStart.id) return;
        var infoEl = document.getElementById('startWorkTicketInfo');
        if (infoEl) {
            infoEl.innerHTML = '<h6 class="mb-2">' + ticketToStart.ticket_number + ': ' + ticketToStart.title + '</h6><div class="d-flex gap-2">' + HelpdeskUtils.getPriorityBadge(ticketToStart.priority) + HelpdeskUtils.getAreaBadge(ticketToStart.area) + '</div>';
        }
        var b = document.getElementById('btnConfirmStart');
        if (b) { b.disabled = false; b.innerHTML = '<i class="fas fa-play me-2"></i>Sí, Iniciar'; }
        var modalEl = document.getElementById('startWorkModal');
        if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).show();
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
            if (modalEl) { var m = bootstrap.Modal.getInstance(modalEl); if (m) m.hide(); }
            refreshTab('assigned'); refreshTab('inProgress');
            updateDashboardStats();
        } catch (error) {
            console.error('Error starting ticket:', error);
            HelpdeskUtils.showToast('Error al iniciar ticket: ' + (error.message || 'Error desconocido'), 'error');
            if (btn) { btn.disabled = false; btn.innerHTML = originalText; }
        }
    }

    // ==================== RESOLVE TAB ====================
    function openResolveModal(btn) {
        ticketToResolve = _ticketFromBtn(btn);
        if (!ticketToResolve.id) return;

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
        if (notesField) { notesField.value = ''; notesField.classList.remove('is-invalid', 'is-valid'); }
        var resSuccess = document.getElementById('resolutionSuccess');
        if (resSuccess) resSuccess.checked = true;
        var timeInvested = document.getElementById('timeInvested');
        if (timeInvested) timeInvested.value = '';
        var timeUnit = document.getElementById('timeUnit');
        if (timeUnit) timeUnit.value = 'minutes';
        updateNotesCounter();

        var b = document.getElementById('btnConfirmResolve');
        if (b) { b.disabled = false; b.innerHTML = '<i class="fas fa-check-circle me-2"></i>Resolver Ticket'; }

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
            notesField.classList.remove('is-invalid'); notesField.classList.add('is-valid');
            counter.classList.remove('text-danger'); counter.classList.add('text-success');
        } else if (length > 0) {
            notesField.classList.remove('is-valid'); notesField.classList.add('is-invalid');
            counter.classList.remove('text-success'); counter.classList.add('text-danger');
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
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ collaborators: selectedCollaborators })
                    });
                    if (collabResp.ok) { var cd = await collabResp.json(); console.log(cd.count + ' colaboradores agregados'); }
                } catch (e) { console.error('Error adding collaborators:', e); }
            }

            HelpdeskUtils.showToast(resolutionType === 'success' ? '¡Ticket resuelto exitosamente!' : 'Ticket marcado como atendido', 'success');
            closeResolveTab();
            refreshTab('inProgress'); refreshTab('resolved');
            updateDashboardStats();
        } catch (error) {
            console.error('Error resolving ticket:', error);
            HelpdeskUtils.showToast('Error al resolver ticket: ' + (error.message || 'Error desconocido'), 'error');
            if (btn) { btn.disabled = false; btn.innerHTML = originalText; }
        }
    }

    // ==================== SELF-ASSIGN MODAL ====================
    function openSelfAssignModal(btn) {
        ticketToSelfAssign = _ticketFromBtn(btn);
        if (!ticketToSelfAssign.id) return;
        var infoEl = document.getElementById('selfAssignTicketInfo');
        if (infoEl) {
            infoEl.innerHTML = '<h6 class="mb-2">' + ticketToSelfAssign.ticket_number + ': ' + ticketToSelfAssign.title + '</h6><div class="d-flex gap-2">' + HelpdeskUtils.getPriorityBadge(ticketToSelfAssign.priority) + HelpdeskUtils.getAreaBadge(ticketToSelfAssign.area) + '</div>';
        }
        var b = document.getElementById('btnConfirmSelfAssign');
        if (b) { b.disabled = false; b.innerHTML = '<i class="fas fa-hand-paper me-2"></i>Sí, Tomar Ticket'; }
        var modalEl = document.getElementById('selfAssignModal');
        if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).show();
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
            if (modalEl) { var m = bootstrap.Modal.getInstance(modalEl); if (m) m.hide(); }
            refreshTab('assigned'); refreshTab('team');
            updateDashboardStats();
        } catch (error) {
            console.error('Error self-assigning ticket:', error);
            HelpdeskUtils.showToast('Error al tomar ticket: ' + (error.message || 'Error desconocido'), 'error');
            if (btn) { btn.disabled = false; btn.innerHTML = originalText; }
        }
    }

    // ==================== WEBSOCKET (DASHBOARD) ====================
    function setupWebSocketListeners() {
        _socketCheckInterval = setInterval(function () {
            if (window.__helpdeskSocket) {
                clearInterval(_socketCheckInterval); _socketCheckInterval = null;
                bindSocketEvents();
            }
        }, 100);
        setTimeout(function () { if (_socketCheckInterval) { clearInterval(_socketCheckInterval); _socketCheckInterval = null; } }, 5000);
    }

    async function bindSocketEvents() {
        if (socketRoomsBound) return;
        var socket = window.__helpdeskSocket;
        if (!socket) return;

        try {
            var userResponse = await fetch('/api/core/v2/user/me');
            var user = await userResponse.json();
            var userRoles = (user.data && user.data.roles && user.data.roles.helpdesk) || [];
            if (userRoles.includes('tech_desarrollo')) techArea = 'desarrollo';
            else if (userRoles.includes('tech_soporte')) techArea = 'soporte';
        } catch (e) { console.warn('[Dashboard] No se pudo obtener área del técnico:', e); }

        window.__hdJoinTech?.();
        if (techArea) window.__hdJoinTeam?.(techArea);

        var dRefreshAssigned = debounce(function () { refreshTab('assigned'); updateDashboardStats(); showRealtimeToast('Nueva asignación recibida'); }, 250);
        var dRefreshTeam = debounce(function () { refreshTab('team'); updateDashboardStats(); }, 250);
        var dRefreshAll = debounce(function () { refreshAll(); updateDashboardStats(); }, 250);

        socket.off('ticket_assigned');
        socket.off('ticket_reassigned');
        socket.off('ticket_status_changed');
        socket.off('ticket_created');
        socket.off('ticket_self_assigned');

        socket.on('ticket_assigned', function () { dRefreshAssigned(); });
        socket.on('ticket_reassigned', function () { dRefreshAll(); showRealtimeToast('Ticket reasignado'); });
        socket.on('ticket_status_changed', function () { dRefreshAll(); });
        socket.on('ticket_created', function (data) {
            if (techArea && data.area && data.area.toLowerCase() === techArea) {
                dRefreshTeam(); showRealtimeToast('Nuevo ticket: ' + data.ticket_number);
            }
        });
        socket.on('ticket_self_assigned', function () { dRefreshTeam(); });

        socketRoomsBound = true;
    }

    function showRealtimeToast(message) {
        if (window.HelpdeskUtils && window.HelpdeskUtils.showToast) HelpdeskUtils.showToast(message, 'info');
    }

    // ==================== RESOLUTION FILES ====================
    function getFileIcon(filename) {
        var ext = filename.split('.').pop().toLowerCase();
        var icons = { pdf: 'fas fa-file-pdf text-danger', xlsx: 'fas fa-file-excel text-success', xls: 'fas fa-file-excel text-success', csv: 'fas fa-file-csv text-success', doc: 'fas fa-file-word text-primary', docx: 'fas fa-file-word text-primary' };
        return icons[ext] || 'fas fa-file text-secondary';
    }

    function formatFileSize(bytes) {
        if (!bytes) return '0 B';
        var k = 1024; var sizes = ['B', 'KB', 'MB'];
        var i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    function openResolutionFilesModal() {
        if (!ticketToResolve) return;
        var modalEl = document.getElementById('resolutionFilesModal');
        if (!modalEl) return;
        loadResolutionFiles();
        setupResolutionDropzone();
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }

    function setupResolutionDropzone() {
        if (resDropzoneSetup) return;
        resDropzoneSetup = true;
        var dropzone = document.getElementById('resolutionDropzone');
        var input = document.getElementById('resolutionFileInput');
        if (!dropzone || !input) return;
        dropzone.addEventListener('click', function () { input.click(); });
        dropzone.addEventListener('dragover', function (e) { e.preventDefault(); dropzone.style.borderColor = '#0d6efd'; dropzone.style.backgroundColor = '#f0f7ff'; });
        dropzone.addEventListener('dragleave', function () { dropzone.style.borderColor = '#dee2e6'; dropzone.style.backgroundColor = ''; });
        dropzone.addEventListener('drop', function (e) { e.preventDefault(); dropzone.style.borderColor = '#dee2e6'; dropzone.style.backgroundColor = ''; uploadResolutionFiles(Array.from(e.dataTransfer.files)); });
        input.addEventListener('change', function () { uploadResolutionFiles(Array.from(this.files)); this.value = ''; });
    }

    async function loadResolutionFiles() {
        if (!ticketToResolve) return;
        try {
            var response = await HelpdeskUtils.api.getAttachmentsByType(ticketToResolve.id, 'resolution');
            var attachments = response.attachments || [];
            renderResolutionFilesList(attachments);
            updateResolutionFilesCount(attachments.length);
        } catch (error) { console.error('Error loading resolution files:', error); }
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
            try { await HelpdeskUtils.api.uploadFile(ticketToResolve.id, file, 'resolution'); uploaded++; }
            catch (error) { HelpdeskUtils.showToast('Error al subir ' + file.name + ': ' + error.message, 'error'); }
        }
        if (progressBar) progressBar.style.width = '100%';
        if (progressText) progressText.textContent = uploaded + ' de ' + files.length + ' archivos subidos';
        setTimeout(function () { if (progressContainer) progressContainer.classList.add('d-none'); if (progressBar) progressBar.style.width = '0%'; }, 1500);
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
        } catch (error) { HelpdeskUtils.showToast('Error al eliminar: ' + error.message, 'error'); }
    }

    function viewAttachmentImage(url, title) {
        var modalEl = document.getElementById('attachmentImageModal');
        if (!modalEl) return;
        var imgEl = document.getElementById('attachmentImageModalImg');
        var titleEl = document.getElementById('attachmentImageTitle');
        if (imgEl) imgEl.src = url;
        if (titleEl) titleEl.innerHTML = '<i class="fas fa-image me-2"></i>' + (title || 'Imagen');
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }

    // ==================== HELPERS ====================
    function truncateText(text, maxLength) {
        if (!text) return '';
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }

    function debounce(fn, delay) {
        var timeoutId;
        return function () {
            var args = arguments; var ctx = this;
            clearTimeout(timeoutId);
            timeoutId = setTimeout(function () { fn.apply(ctx, args); }, delay);
        };
    }

    // ==================== CONTROLLER REGISTRATION ====================
    window.HelpdeskPage.page('technician_dashboard', { init: init, destroy: destroy });

})();
