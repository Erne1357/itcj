/**
 * board.js — Tablero de asignación de tickets para coordinadores de Mantenimiento.
 *
 * Consume:
 *   GET  /api/maint/v2/tickets/board  → tickets PENDING/ASSIGNED/IN_PROGRESS
 *   GET  /api/maint/v2/technicians    → lista de técnicos activos
 *   POST /api/maint/v2/tickets/{id}/assign   → asignar técnicos
 *   POST /api/maint/v2/tickets/{id}/unassign → remover técnico
 *   GET  /api/maint/v2/config/areas   → catálogo de áreas (para el filtro)
 *
 * Depende de: window.MaintUtils (maint-utils.js)
 */

'use strict';

(function () {

    // === CONSTANTES ===
    var API_BOARD       = '/api/maint/v2/tickets/board';
    var API_TECHNICIANS = '/api/maint/v2/technicians';
    var API_ASSIGN      = '/api/maint/v2/tickets/{id}/assign';
    var API_UNASSIGN    = '/api/maint/v2/tickets/{id}/unassign';
    var API_AREAS       = '/api/maint/v2/coordinators/areas';

    var STATUS_LABELS = {
        PENDING:     { label: 'Pendiente',   cls: 'bg-secondary' },
        ASSIGNED:    { label: 'Asignado',    cls: 'bg-info text-dark' },
        IN_PROGRESS: { label: 'En progreso', cls: 'bg-primary' },
    };

    var PRIORITY_LABELS = {
        BAJA:    { label: 'Baja',    cls: 'bg-success' },
        MEDIA:   { label: 'Media',   cls: 'bg-warning text-dark' },
        ALTA:    { label: 'Alta',    cls: 'bg-danger' },
        URGENTE: { label: 'Urgente', cls: 'bg-dark' },
    };

    // === ESTADO ===
    var _ctx          = window.BOARD_CTX || {};
    var _currentPage  = 1;
    var _totalPages   = 1;
    var _total        = 0;
    var _tickets      = [];
    var _allTechs     = [];       // todos los técnicos activos
    var _suggestedIds = new Set(); // IDs de técnicos sugeridos por el board endpoint

    // Estado del modal de asignación
    var _activeTicketId    = null;
    var _assignedTechIds   = new Set();  // técnicos ya asignados al ticket activo
    var _selectedNewIds    = new Set();  // nuevos a asignar en esta operación
    var _assignModal       = null;
    var _unassignModal     = null;
    var _pendingUnassign   = { techId: null, techName: '' };
    var _suggestedTechs    = [];   // sugeridos devueltos por el board

    // === INICIALIZACIÓN ===
    document.addEventListener('DOMContentLoaded', function () {
        _initModals();
        _loadAreas();
        _loadBoard();
        _setupEventListeners();
        _initRealtime();
    });

    // === REALTIME (M8/M9) ===
    // La cola del coordinador refresca en vivo cuando el dispatcher le enruta un
    // ticket (ticket_routed → room personal) o cambia una asignación visible.
    function _initRealtime() {
        var tries = 0;
        var timer = setInterval(function () {
            if (window.__maintSocket) {
                clearInterval(timer);
                _bindRealtime(window.__maintSocket);
            } else if (++tries > 50) {
                clearInterval(timer);
            }
        }, 200);
    }

    function _bindRealtime(socket) {
        // Room personal: ahí llega ticket_routed cuando el dispatcher enruta a
        // la cola de este coordinador.
        if (window.__maintJoinTech) window.__maintJoinTech();
        var reload = _debounce(function () { _loadBoard(); }, 400);
        socket.on('ticket_routed',     reload);
        socket.on('ticket_assigned',   reload);
        socket.on('ticket_unassigned', reload);
        socket.on('ticket_canceled',   reload);
    }

    // === MODALES ===
    function _initModals() {
        var assignEl = document.getElementById('assign-modal');
        if (assignEl) {
            _assignModal = new bootstrap.Modal(assignEl);
            assignEl.addEventListener('hidden.bs.modal', function () {
                _selectedNewIds.clear();
                document.getElementById('assign-notes').value = '';
                document.getElementById('tech-search-input').value = '';
                document.getElementById('btn-confirm-assign').disabled = true;
            });
        }
        var unassignEl = document.getElementById('unassign-confirm-modal');
        if (unassignEl) {
            _unassignModal = new bootstrap.Modal(unassignEl);
            unassignEl.addEventListener('hidden.bs.modal', function () {
                document.getElementById('unassign-reason').value = '';
                _pendingUnassign = { techId: null, techName: '' };
            });
        }
    }

    // === SETUP LISTENERS ===
    function _setupEventListeners() {
        document.getElementById('btn-refresh').addEventListener('click', function () {
            _currentPage = 1;
            _loadBoard();
        });

        document.getElementById('statusFilter').addEventListener('change', function () {
            _currentPage = 1;
            _loadBoard();
        });

        document.getElementById('areaFilter').addEventListener('change', function () {
            _currentPage = 1;
            _loadBoard();
        });

        document.getElementById('tech-search-input').addEventListener('input', _debounce(function () {
            _filterTechList(this.value);
        }, 200));

        document.getElementById('btn-confirm-assign').addEventListener('click', _handleAssign);
        document.getElementById('btn-confirm-unassign').addEventListener('click', _handleUnassign);
    }

    // === CARGA DE ÁREAS (para el selector de filtro) ===
    function _loadAreas() {
        MaintUtils.api.fetch(API_AREAS)
            .then(function (data) {
                var areas = (data.data || []).filter(function (a) { return a.is_active; });
                var sel = document.getElementById('areaFilter');
                areas.forEach(function (a) {
                    var opt = document.createElement('option');
                    opt.value = MaintUtils.escapeHtml(a.code);
                    opt.textContent = MaintUtils.escapeHtml(a.label || a.code);
                    sel.appendChild(opt);
                });
                if (areas.length > 0) {
                    sel.classList.remove('d-none');
                }
            })
            .catch(function () { /* áreas no disponibles — silencioso */ });
    }

    // === CARGA DEL BOARD ===
    function _loadBoard() {
        var statusVal = document.getElementById('statusFilter').value;
        var areaVal   = document.getElementById('areaFilter').value;
        var url = API_BOARD + '?page=' + _currentPage + '&per_page=25';
        if (statusVal) url += '&status=' + encodeURIComponent(statusVal);
        if (areaVal)   url += '&area_code=' + encodeURIComponent(areaVal);

        var tbody = document.getElementById('board-tbody');
        tbody.innerHTML =
            '<tr><td colspan="7" class="text-center py-5 text-muted">' +
            '<span class="spinner-border spinner-border-sm me-2" role="status"></span>' +
            'Cargando tickets...</td></tr>';
        document.getElementById('board-count-label').textContent = 'Cargando...';

        MaintUtils.api.fetch(url)
            .then(function (data) {
                _tickets = data.data || [];
                _total   = data.total || 0;
                _totalPages = data.total_pages || 1;
                _suggestedTechs = data.suggested_technicians || [];
                _suggestedIds = new Set(_suggestedTechs.map(function (t) { return t.user_id; }));
                _renderBoard();
                _renderPagination();
            })
            .catch(function (err) {
                tbody.innerHTML =
                    '<tr><td colspan="7" class="text-center py-4 text-danger">' +
                    '<i class="fas fa-exclamation-circle me-2"></i>' +
                    MaintUtils.escapeHtml(err.message || 'Error al cargar el tablero') +
                    '</td></tr>';
                document.getElementById('board-count-label').textContent = '';
            });
    }

    // === RENDER TABLA ===
    function _renderBoard() {
        var tbody = document.getElementById('board-tbody');
        var countLabel = document.getElementById('board-count-label');

        if (!_tickets.length) {
            tbody.innerHTML =
                '<tr><td colspan="7" class="text-center py-5 text-muted">' +
                '<i class="fas fa-inbox fa-2x d-block mb-2 opacity-50"></i>' +
                'No hay tickets que requieran asignación con los filtros seleccionados.' +
                '</td></tr>';
            countLabel.textContent = '0 tickets';
            return;
        }

        countLabel.textContent = _total + ' ticket' + (_total !== 1 ? 's' : '');

        tbody.innerHTML = _tickets.map(function (t) {
            var statusInfo   = STATUS_LABELS[t.status]   || { label: t.status,   cls: 'bg-secondary' };
            var priorityInfo = PRIORITY_LABELS[t.priority] || { label: t.priority || '—', cls: 'bg-secondary' };
            var techsHtml    = _renderTechBadges(t.active_technicians || []);
            var createdDate  = t.created_at ? new Date(t.created_at).toLocaleDateString('es-MX') : '—';
            var ticketNum    = MaintUtils.escapeHtml(t.ticket_number || '#' + t.id);
            var title        = MaintUtils.escapeHtml(t.title || '—');

            return (
                '<tr data-ticket-id="' + t.id + '">' +
                '<td><a href="/maint/tickets/' + t.id + '" class="text-decoration-none fw-medium small">' +
                ticketNum + '</a></td>' +
                '<td class="text-wrap" style="max-width:18rem;">' +
                '<span class="d-block" title="' + title + '">' + title + '</span>' +
                '</td>' +
                '<td class="d-none d-md-table-cell">' +
                '<span class="badge ' + statusInfo.cls + ' small">' + MaintUtils.escapeHtml(statusInfo.label) + '</span>' +
                '</td>' +
                '<td class="d-none d-lg-table-cell">' +
                '<span class="badge ' + priorityInfo.cls + ' small">' + MaintUtils.escapeHtml(priorityInfo.label) + '</span>' +
                '</td>' +
                '<td class="d-none d-md-table-cell small text-muted">' + createdDate + '</td>' +
                '<td>' + techsHtml + '</td>' +
                '<td class="text-end">' +
                '<button class="btn btn-sm btn-outline-primary" ' +
                'onclick="MaintBoard.openAssignModal(' + t.id + ')" ' +
                'title="Gestionar técnicos">' +
                '<i class="fas fa-people-arrows me-1"></i>' +
                '<span class="d-none d-md-inline">Asignar</span>' +
                '</button>' +
                '</td>' +
                '</tr>'
            );
        }).join('');
    }

    function _renderTechBadges(technicians) {
        if (!technicians.length) {
            return '<span class="text-muted small fst-italic">Sin técnicos</span>';
        }
        return technicians.map(function (tech) {
            var userId = tech.user_id;
            var isSugg = _suggestedIds.has(userId);
            var badgeCls = isSugg ? 'bg-primary-subtle text-primary-emphasis' : 'bg-light text-secondary border';
            return (
                '<span class="badge ' + badgeCls + ' small me-1 mb-1 py-1 px-2">' +
                '<i class="fas fa-user me-1"></i>' +
                (tech.name ? MaintUtils.escapeHtml(tech.name) : '#' + userId) +
                '</span>'
            );
        }).join('');
    }

    // === PAGINACIÓN ===
    function _renderPagination() {
        var wrap = document.getElementById('board-pagination');
        var info = document.getElementById('pagination-info');
        var btns = document.getElementById('pagination-buttons');

        if (_totalPages <= 1 && _total <= 25) {
            wrap.classList.add('d-none');
            return;
        }
        wrap.classList.remove('d-none');
        var start = (_currentPage - 1) * 25 + 1;
        var end   = Math.min(_currentPage * 25, _total);
        info.textContent = 'Mostrando ' + start + '–' + end + ' de ' + _total;

        var html = '';
        html += '<button class="btn btn-sm btn-outline-secondary" ' +
            (_currentPage === 1 ? 'disabled' : '') +
            ' onclick="MaintBoard._goPage(' + (_currentPage - 1) + ')">' +
            '<i class="fas fa-chevron-left"></i></button>';

        for (var p = Math.max(1, _currentPage - 2); p <= Math.min(_totalPages, _currentPage + 2); p++) {
            html += '<button class="btn btn-sm ' +
                (p === _currentPage ? 'btn-primary' : 'btn-outline-secondary') + '" ' +
                'onclick="MaintBoard._goPage(' + p + ')">' + p + '</button>';
        }

        html += '<button class="btn btn-sm btn-outline-secondary" ' +
            (_currentPage === _totalPages ? 'disabled' : '') +
            ' onclick="MaintBoard._goPage(' + (_currentPage + 1) + ')">' +
            '<i class="fas fa-chevron-right"></i></button>';

        btns.innerHTML = html;
    }

    function _goPage(page) {
        if (page < 1 || page > _totalPages) return;
        _currentPage = page;
        _loadBoard();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    // === MODAL DE ASIGNACIÓN ===
    function _openAssignModal(ticketId) {
        _activeTicketId  = ticketId;
        _selectedNewIds.clear();

        // Buscar el ticket en la lista actual
        var ticket = null;
        for (var i = 0; i < _tickets.length; i++) {
            if (_tickets[i].id === ticketId) { ticket = _tickets[i]; break; }
        }
        if (!ticket) { MaintUtils.toast('Ticket no encontrado en el tablero', 'error'); return; }

        // Rellenar info del ticket
        document.getElementById('assign-modal-ticket-info').textContent =
            (ticket.ticket_number || '#' + ticket.id) + ' — ' + (ticket.title || '');

        // Técnicos ya asignados
        _assignedTechIds = new Set((ticket.active_technicians || []).map(function (t) { return t.user_id; }));
        _renderAssignedTechs(ticket.active_technicians || []);

        // Sugeridos
        var sugSection = document.getElementById('suggested-section');
        if (_suggestedTechs.length) {
            sugSection.classList.remove('d-none');
            _renderSuggestedTechs();
        } else {
            sugSection.classList.add('d-none');
        }

        // Cargar técnicos disponibles
        _loadTechniciansForModal();

        _assignModal.show();
    }

    function _renderAssignedTechs(technicians) {
        var container = document.getElementById('assigned-list');
        if (!technicians.length) {
            container.innerHTML = '<p class="text-muted small fst-italic">Sin técnicos asignados.</p>';
            return;
        }
        container.innerHTML = technicians.map(function (tech) {
            var userId = tech.user_id;
            var name   = tech.name || ('#' + userId);
            return (
                '<div class="d-flex align-items-center justify-content-between gap-2 py-1 border-bottom">' +
                '<span class="small"><i class="fas fa-user me-2 text-muted"></i>' + MaintUtils.escapeHtml(name) + '</span>' +
                '<button class="btn btn-outline-danger btn-sm py-0 px-2" style="font-size:.75rem;" ' +
                'onclick="MaintBoard._confirmUnassign(' + userId + ', \'' + MaintUtils.escapeHtml(name).replace(/'/g, "\\'") + '\')">' +
                '<i class="fas fa-times"></i>' +
                '</button>' +
                '</div>'
            );
        }).join('');
    }

    function _renderSuggestedTechs() {
        var container = document.getElementById('suggested-list');
        container.innerHTML = _suggestedTechs.map(function (tech) {
            var isAssigned  = _assignedTechIds.has(tech.user_id);
            var isSelected  = _selectedNewIds.has(tech.user_id);
            var disabled    = isAssigned ? 'disabled' : '';
            var badgeTxt    = isAssigned ? 'Ya asignado' : (isSelected ? 'Seleccionado' : '');
            var badgeCls    = isSelected ? 'badge bg-success ms-1' : (isAssigned ? 'badge bg-secondary ms-1' : '');
            return (
                '<div class="d-flex align-items-center gap-2 py-1">' +
                '<input class="form-check-input mt-0" type="checkbox" ' +
                'id="sugg-' + tech.user_id + '" ' +
                'value="' + tech.user_id + '" ' +
                (isAssigned ? 'disabled checked' : (isSelected ? 'checked' : '')) + ' ' +
                'onchange="MaintBoard._toggleTech(' + tech.user_id + ', this.checked)">' +
                '<label class="form-check-label small flex-grow-1" for="sugg-' + tech.user_id + '">' +
                MaintUtils.escapeHtml(tech.name || '#' + tech.user_id) +
                (tech.area ? ' <span class="text-muted">(' + MaintUtils.escapeHtml(tech.area) + ')</span>' : '') +
                '</label>' +
                (badgeTxt ? '<span class="' + badgeCls + '">' + badgeTxt + '</span>' : '') +
                '</div>'
            );
        }).join('');
    }

    function _loadTechniciansForModal() {
        var container = document.getElementById('tech-list-container');
        container.innerHTML =
            '<div class="text-center py-3 text-muted">' +
            '<span class="spinner-border spinner-border-sm me-2"></span>Cargando técnicos...</div>';

        MaintUtils.api.fetch(API_TECHNICIANS)
            .then(function (data) {
                _allTechs = data.data || [];
                _renderTechListInModal(_allTechs);
            })
            .catch(function () {
                container.innerHTML = '<p class="text-danger small p-2">No se pudo cargar la lista de técnicos.</p>';
            });
    }

    function _renderTechListInModal(techs) {
        var container = document.getElementById('tech-list-container');
        if (!techs.length) {
            container.innerHTML = '<p class="text-muted small p-2 fst-italic">No se encontraron técnicos.</p>';
            return;
        }
        container.innerHTML = techs.map(function (tech) {
            var isAssigned = _assignedTechIds.has(tech.user_id || tech.id);
            var uid        = tech.user_id || tech.id;
            var isSelected = _selectedNewIds.has(uid);
            return (
                '<div class="d-flex align-items-center gap-2 py-1 border-bottom">' +
                '<input class="form-check-input mt-0" type="checkbox" ' +
                'id="tech-' + uid + '" value="' + uid + '" ' +
                (isAssigned ? 'disabled checked title="Ya asignado"' : (isSelected ? 'checked' : '')) + ' ' +
                'onchange="MaintBoard._toggleTech(' + uid + ', this.checked)">' +
                '<label class="form-check-label small flex-grow-1" for="tech-' + uid + '">' +
                MaintUtils.escapeHtml(tech.name || tech.full_name || '#' + uid) +
                (isAssigned ? ' <span class="badge bg-secondary ms-1" style="font-size:.7rem;">Asignado</span>' : '') +
                '</label>' +
                '</div>'
            );
        }).join('');
    }

    function _filterTechList(query) {
        var q = (query || '').toLowerCase().trim();
        var filtered = q
            ? _allTechs.filter(function (t) {
                var name = (t.name || t.full_name || '').toLowerCase();
                return name.includes(q);
            })
            : _allTechs;
        _renderTechListInModal(filtered);
    }

    function _toggleTech(userId, checked) {
        if (checked) {
            _selectedNewIds.add(userId);
        } else {
            _selectedNewIds.delete(userId);
        }
        // Sincronizar checkbox en sugeridos si existe
        var suggCheck = document.getElementById('sugg-' + userId);
        if (suggCheck && !suggCheck.disabled) {
            suggCheck.checked = checked;
        }
        // Actualizar estado del botón
        document.getElementById('btn-confirm-assign').disabled = _selectedNewIds.size === 0;
    }

    // === ACCIÓN: ASIGNAR ===
    function _handleAssign() {
        if (!_activeTicketId || _selectedNewIds.size === 0) return;
        var btn = document.getElementById('btn-confirm-assign');
        var notes = document.getElementById('assign-notes').value.trim();
        var url = API_ASSIGN.replace('{id}', _activeTicketId);
        MaintUtils.loading.show(btn, 'Asignando...');
        MaintUtils.api.fetch(url, {
            method: 'POST',
            body: JSON.stringify({
                user_ids: Array.from(_selectedNewIds),
                notes: notes || null,
            }),
        })
        .then(function (data) {
            MaintUtils.loading.hide(btn);
            _assignModal.hide();
            MaintUtils.toast(
                'Técnico(s) asignado(s) correctamente (' + (data.assigned_count || _selectedNewIds.size) + ')',
                'success'
            );
            _loadBoard();
        })
        .catch(function (err) {
            MaintUtils.loading.hide(btn);
            // El 403 de restricción de área lleva mensaje del backend — mostrarlo al usuario
            var msg = err.message || 'Error al asignar técnico(s)';
            MaintUtils.toast(msg, 'error', 0);
        });
    }

    // === ACCIÓN: DESASIGNAR ===
    function _confirmUnassign(techId, techName) {
        _pendingUnassign = { techId: techId, techName: techName };
        document.getElementById('unassign-tech-name').textContent = techName;
        // Ocultar el modal de asignación primero
        _assignModal.hide();
        // Mostrar el de confirmación después del cierre
        var assignEl = document.getElementById('assign-modal');
        assignEl.addEventListener('hidden.bs.modal', function once() {
            assignEl.removeEventListener('hidden.bs.modal', once);
            _unassignModal.show();
        });
    }

    function _handleUnassign() {
        if (!_activeTicketId || !_pendingUnassign.techId) return;
        var btn    = document.getElementById('btn-confirm-unassign');
        var reason = document.getElementById('unassign-reason').value.trim();
        var url    = API_UNASSIGN.replace('{id}', _activeTicketId);
        MaintUtils.loading.show(btn, 'Removiendo...');
        MaintUtils.api.fetch(url, {
            method: 'POST',
            body: JSON.stringify({
                user_id: _pendingUnassign.techId,
                reason: reason || null,
            }),
        })
        .then(function () {
            MaintUtils.loading.hide(btn);
            _unassignModal.hide();
            MaintUtils.toast(
                MaintUtils.escapeHtml(_pendingUnassign.techName) + ' removido del ticket',
                'success'
            );
            _loadBoard();
        })
        .catch(function (err) {
            MaintUtils.loading.hide(btn);
            MaintUtils.toast(err.message || 'Error al remover técnico', 'error');
        });
    }

    // === UTILIDADES ===
    function _debounce(fn, delay) {
        var timer;
        return function () {
            var ctx = this;
            var args = arguments;
            clearTimeout(timer);
            timer = setTimeout(function () { fn.apply(ctx, args); }, delay);
        };
    }

    // === API PÚBLICA (usada por botones onclick inline) ===
    window.MaintBoard = {
        openAssignModal: _openAssignModal,
        _confirmUnassign: _confirmUnassign,
        _toggleTech: _toggleTech,
        _goPage: _goPage,
    };

})();
