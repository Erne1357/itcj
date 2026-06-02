/**
 * triage/board.js — Tablero de triage y enrutado de tickets de Mantenimiento.
 *
 * Consume:
 *   GET  /api/maint/v2/tickets/triage         → {unrouted:[], mine:[]}
 *   GET  /api/maint/v2/tickets/route-targets   → coordinadores destino válidos
 *   POST /api/maint/v2/tickets/{id}/route      → body {coordinator_id}
 *
 * Depende de: window.MaintUtils (maint-utils.js)
 * Namespace público: window.MaintTriage
 */

'use strict';

(function () {

    // === CONSTANTES ===
    var API_TRIAGE        = '/api/maint/v2/tickets/triage';
    var API_ROUTE_TARGETS = '/api/maint/v2/tickets/route-targets';
    var API_ROUTE         = '/api/maint/v2/tickets/{id}/route';

    var STATUS_LABELS = {
        PENDING:     { label: 'Pendiente',   cls: 'bg-secondary' },
        ASSIGNED:    { label: 'Asignado',    cls: 'bg-info text-dark' },
        IN_PROGRESS: { label: 'En progreso', cls: 'bg-primary' },
        RESOLVED_SUCCESS: { label: 'Resuelto', cls: 'bg-success' },
        RESOLVED_FAILED:  { label: 'Atendido', cls: 'bg-warning text-dark' },
        CLOSED:           { label: 'Cerrado',  cls: 'bg-dark' },
        CANCELED:         { label: 'Cancelado', cls: 'bg-danger' },
    };

    var PRIORITY_LABELS = {
        ALTA:    { label: 'Alta',    cls: 'bg-danger' },
        MEDIA:   { label: 'Media',   cls: 'bg-warning text-dark' },
        BAJA:    { label: 'Baja',    cls: 'bg-success' },
        CRITICA: { label: 'Crítica', cls: 'bg-dark' },
        URGENTE: { label: 'Urgente', cls: 'bg-dark' },
    };

    // === ESTADO ===
    var _ctx            = window.TRIAGE_CTX || {};
    var _unrouted       = [];
    var _mine           = [];
    var _routeTargets   = null;   // cache de destinos (se carga al abrir el modal)
    var _activeTicketId = null;
    var _routeModal     = null;

    // === INICIALIZACIÓN ===
    document.addEventListener('DOMContentLoaded', function () {
        _initModal();
        _loadTriage();
        _setupEventListeners();
    });

    // === MODAL ===
    function _initModal() {
        var el = document.getElementById('route-modal');
        if (!el) return;
        _routeModal = new bootstrap.Modal(el);
        el.addEventListener('hidden.bs.modal', function () {
            _activeTicketId = null;
            document.getElementById('route-coordinator-select').value = '';
            document.getElementById('btn-confirm-route').disabled = true;
            document.getElementById('route-coord-info').classList.add('d-none');
        });
    }

    // === SETUP LISTENERS ===
    function _setupEventListeners() {
        document.getElementById('btn-refresh').addEventListener('click', function () {
            _loadTriage();
        });

        document.getElementById('route-coordinator-select').addEventListener('change', function () {
            var val = this.value;
            document.getElementById('btn-confirm-route').disabled = !val;
            _updateCoordInfo(val);
        });

        document.getElementById('btn-confirm-route').addEventListener('click', _handleRoute);
    }

    // === CARGA DE DATOS ===
    function _loadTriage() {
        _setLoadingState(true);

        MaintUtils.api.fetch(API_TRIAGE)
            .then(function (data) {
                _unrouted = (data.data && data.data.unrouted) || [];
                _mine     = (data.data && data.data.mine) || [];
                _renderUnrouted();
                _renderMine();
            })
            .catch(function (err) {
                _renderError('unrouted-tbody', 7, err.message || 'Error al cargar los tickets');
                document.getElementById('unrouted-count-label').textContent = '';
            })
            .finally(function () {
                _setLoadingState(false);
            });
    }

    function _setLoadingState(loading) {
        var btn = document.getElementById('btn-refresh');
        if (!btn) return;
        btn.disabled = loading;
        var icon = btn.querySelector('i');
        if (icon) {
            if (loading) {
                icon.classList.remove('fa-sync-alt');
                icon.classList.add('fa-spin', 'fa-circle-notch');
            } else {
                icon.classList.add('fa-sync-alt');
                icon.classList.remove('fa-spin', 'fa-circle-notch');
            }
        }
    }

    // === RENDER: POR ENRUTAR ===
    function _renderUnrouted() {
        var tbody = document.getElementById('unrouted-tbody');
        var label = document.getElementById('unrouted-count-label');

        if (!_unrouted.length) {
            tbody.innerHTML =
                '<tr><td colspan="7" class="text-center py-5 text-muted">' +
                '<i class="fas fa-check-circle fa-2x d-block mb-2 text-success opacity-75"></i>' +
                'No hay tickets pendientes de enrutado.' +
                '</td></tr>';
            label.textContent = 'Sin tickets por enrutar';
            return;
        }

        label.textContent = _unrouted.length + ' ticket' + (_unrouted.length !== 1 ? 's' : '') + ' por enrutar';

        tbody.innerHTML = _unrouted.map(function (t) {
            return _buildRow(t, 'unrouted');
        }).join('');
    }

    // === RENDER: MI COLA ===
    function _renderMine() {
        var section = document.getElementById('section-mine');
        var tbody   = document.getElementById('mine-tbody');
        var label   = document.getElementById('mine-count-label');

        if (!_mine.length) {
            section.classList.add('d-none');
            return;
        }

        section.classList.remove('d-none');
        label.textContent = _mine.length + ' ticket' + (_mine.length !== 1 ? 's' : '') + ' en mi cola';

        tbody.innerHTML = _mine.map(function (t) {
            return _buildRow(t, 'mine');
        }).join('');
    }

    // === FILA DE TABLA ===
    function _buildRow(t, section) {
        var statusInfo   = STATUS_LABELS[t.status]    || { label: t.status    || '—', cls: 'bg-secondary' };
        var priorityInfo = PRIORITY_LABELS[t.priority] || { label: t.priority || '—', cls: 'bg-secondary' };
        var createdDate  = t.created_at ? new Date(t.created_at).toLocaleDateString('es-MX') : '—';
        var ticketNum    = MaintUtils.escapeHtml(t.ticket_number || ('#' + t.id));
        var title        = MaintUtils.escapeHtml(t.title || '—');
        var catCode      = t.category_code ? MaintUtils.escapeHtml(t.category_code) : '—';

        var actionHtml;
        if (section === 'unrouted') {
            actionHtml =
                '<button class="btn btn-sm btn-outline-primary" ' +
                'onclick="MaintTriage.openRouteModal(' + t.id + ')" ' +
                'title="Enrutar ticket">' +
                '<i class="fas fa-share-square me-1"></i>' +
                '<span class="d-none d-md-inline">Enrutar</span>' +
                '</button>';
        } else {
            // Cola del coordinador general: re-enrutar + ir a asignación
            actionHtml =
                '<div class="d-flex gap-1 justify-content-end flex-wrap">' +
                '<button class="btn btn-sm btn-outline-secondary" ' +
                'onclick="MaintTriage.openRouteModal(' + t.id + ')" ' +
                'title="Re-enrutar a otro coordinador">' +
                '<i class="fas fa-exchange-alt me-1"></i>' +
                '<span class="d-none d-lg-inline">Re-enrutar</span>' +
                '</button>' +
                '<a href="/maint/asignacion" class="btn btn-sm btn-outline-primary" ' +
                'title="Ir al tablero de asignación">' +
                '<i class="fas fa-people-arrows me-1"></i>' +
                '<span class="d-none d-lg-inline">Asignar</span>' +
                '</a>' +
                '</div>';
        }

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
            '<td class="d-none d-md-table-cell small text-muted">' + catCode + '</td>' +
            '<td class="d-none d-md-table-cell small text-muted">' + createdDate + '</td>' +
            '<td class="text-end">' + actionHtml + '</td>' +
            '</tr>'
        );
    }

    function _renderError(tbodyId, colspan, message) {
        var tbody = document.getElementById(tbodyId);
        if (!tbody) return;
        tbody.innerHTML =
            '<tr><td colspan="' + colspan + '" class="text-center py-4 text-danger">' +
            '<i class="fas fa-exclamation-circle me-2"></i>' +
            MaintUtils.escapeHtml(message) +
            '</td></tr>';
    }

    // === MODAL DE ENRUTADO ===
    function _openRouteModal(ticketId) {
        _activeTicketId = ticketId;

        // Buscar el ticket en ambas listas
        var ticket = null;
        var allTickets = _unrouted.concat(_mine);
        for (var i = 0; i < allTickets.length; i++) {
            if (allTickets[i].id === ticketId) { ticket = allTickets[i]; break; }
        }

        var infoEl = document.getElementById('route-modal-ticket-info');
        if (ticket) {
            infoEl.textContent =
                (ticket.ticket_number || ('#' + ticketId)) + ' — ' + (ticket.title || '');
        } else {
            infoEl.textContent = '#' + ticketId;
        }

        // Resetear select y botón
        var sel = document.getElementById('route-coordinator-select');
        sel.innerHTML = '<option value="">Selecciona un coordinador...</option>';
        sel.classList.add('d-none');
        document.getElementById('btn-confirm-route').disabled = true;
        document.getElementById('route-coord-info').classList.add('d-none');
        document.getElementById('route-targets-error').classList.add('d-none');
        document.getElementById('route-targets-loading').classList.remove('d-none');

        _routeModal.show();

        // Cargar destinos (con cache)
        if (_routeTargets !== null) {
            _populateRouteSelect(_routeTargets);
        } else {
            _loadRouteTargets();
        }
    }

    function _loadRouteTargets() {
        MaintUtils.api.fetch(API_ROUTE_TARGETS)
            .then(function (data) {
                _routeTargets = data.data || [];
                _populateRouteSelect(_routeTargets);
            })
            .catch(function (err) {
                document.getElementById('route-targets-loading').classList.add('d-none');
                var errEl = document.getElementById('route-targets-error');
                errEl.textContent = 'No se pudo cargar la lista de coordinadores: ' +
                    MaintUtils.escapeHtml(err.message || 'Error desconocido');
                errEl.classList.remove('d-none');
            });
    }

    function _populateRouteSelect(targets) {
        document.getElementById('route-targets-loading').classList.add('d-none');

        if (!targets.length) {
            var errEl = document.getElementById('route-targets-error');
            errEl.textContent = 'No hay coordinadores disponibles como destino.';
            errEl.classList.remove('d-none');
            return;
        }

        var sel = document.getElementById('route-coordinator-select');
        sel.innerHTML = '<option value="">Selecciona un coordinador...</option>';

        // Agrupar: generales primero, luego área
        var generals = targets.filter(function (c) { return c.is_general; });
        var area     = targets.filter(function (c) { return !c.is_general; });

        if (generals.length) {
            var grpG = document.createElement('optgroup');
            grpG.label = 'Coordinadores generales';
            generals.forEach(function (c) {
                var opt = document.createElement('option');
                opt.value = c.user_id;
                opt.textContent = MaintUtils.escapeHtml(c.name || ('Usuario #' + c.user_id));
                opt.dataset.isGeneral = 'true';
                opt.dataset.areas = JSON.stringify(c.areas || []);
                grpG.appendChild(opt);
            });
            sel.appendChild(grpG);
        }

        if (area.length) {
            var grpA = document.createElement('optgroup');
            grpA.label = 'Coordinadores de área';
            area.forEach(function (c) {
                var opt = document.createElement('option');
                opt.value = c.user_id;
                opt.textContent = MaintUtils.escapeHtml(c.name || ('Usuario #' + c.user_id));
                opt.dataset.isGeneral = 'false';
                opt.dataset.areas = JSON.stringify(c.areas || []);
                grpA.appendChild(opt);
            });
            sel.appendChild(grpA);
        }

        sel.classList.remove('d-none');
    }

    function _updateCoordInfo(coordId) {
        var infoWrap  = document.getElementById('route-coord-info');
        var infoText  = document.getElementById('route-coord-detail');

        if (!coordId || !_routeTargets) {
            infoWrap.classList.add('d-none');
            return;
        }

        var coord = null;
        for (var i = 0; i < _routeTargets.length; i++) {
            if (String(_routeTargets[i].user_id) === String(coordId)) {
                coord = _routeTargets[i];
                break;
            }
        }

        if (!coord) {
            infoWrap.classList.add('d-none');
            return;
        }

        var parts = [];
        if (coord.is_general) {
            parts.push('Coordinador general');
        } else {
            parts.push('Coordinador de área');
            if (coord.areas && coord.areas.length) {
                parts.push('Áreas: ' + coord.areas.map(function (a) {
                    return MaintUtils.escapeHtml(a);
                }).join(', '));
            }
        }

        infoText.textContent = parts.join(' — ');
        infoWrap.classList.remove('d-none');
    }

    // === ACCIÓN: ENRUTAR ===
    function _handleRoute() {
        var coordId = document.getElementById('route-coordinator-select').value;
        if (!_activeTicketId || !coordId) return;

        var btn = document.getElementById('btn-confirm-route');
        MaintUtils.loading.show(btn, 'Enrutando...');

        var url = API_ROUTE.replace('{id}', _activeTicketId);

        MaintUtils.api.fetch(url, {
            method: 'POST',
            body: JSON.stringify({ coordinator_id: parseInt(coordId, 10) }),
        })
        .then(function (data) {
            MaintUtils.loading.hide(btn);
            _routeModal.hide();

            var coordName = '';
            if (data.data && data.data.coordinator) {
                coordName = data.data.coordinator.name || '';
            }
            var msg = 'Ticket enrutado correctamente';
            if (coordName) msg += ' a ' + MaintUtils.escapeHtml(coordName);
            MaintUtils.toast(msg, 'success');

            // Invalidar cache de targets para reflejar cambios (por si cambia la lógica)
            _routeTargets = null;
            _loadTriage();
        })
        .catch(function (err) {
            MaintUtils.loading.hide(btn);
            // El 403 trae el mensaje específico del backend — mostrarlo completo
            var msg = (err && err.message) ? err.message : 'Error al enrutar el ticket';
            MaintUtils.toast(msg, 'error', 0);
        });
    }

    // === API PÚBLICA (usada por onclick inline) ===
    window.MaintTriage = {
        openRouteModal: _openRouteModal,
    };

})();
