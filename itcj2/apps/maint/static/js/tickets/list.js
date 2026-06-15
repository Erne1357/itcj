/**
 * tickets-list.js — Lista de tickets de Mantenimiento
 *
 * Chips de scope (vista): Mi departamento | Asignados a mí | Mis solicitudes | Por calificar
 * Chips de estado: filtro adicional dentro del scope activo.
 * Lee los query params de la URL al cargar para activar la pestaña correcta
 * (permite que un enlace externo abra una vista filtrada, p.ej. ?unrated=1).
 */
'use strict';

(function () {

    var API_BASE = '/api/maint/v2';

    var STATUS_LABEL = {
        PENDING: 'Pendiente', ASSIGNED: 'Asignado', IN_PROGRESS: 'En Progreso',
        RESOLVED_SUCCESS: 'Resuelto', RESOLVED_FAILED: 'Atendido',
        CLOSED: 'Cerrado', CANCELED: 'Cancelado',
    };
    var STATUS_CSS = {
        PENDING: 'mn-status-pending', ASSIGNED: 'mn-status-assigned',
        IN_PROGRESS: 'mn-status-in-progress', RESOLVED_SUCCESS: 'mn-status-resolved-ok',
        RESOLVED_FAILED: 'mn-status-resolved-fail', CLOSED: 'mn-status-closed',
        CANCELED: 'mn-status-canceled',
    };
    var PRIORITY_CSS = {
        BAJA: 'mn-priority-baja', MEDIA: 'mn-priority-media',
        ALTA: 'mn-priority-alta', URGENTE: 'mn-priority-urgente',
    };
    var PRIORITY_LABEL = { BAJA: 'Baja', MEDIA: 'Media', ALTA: 'Alta', URGENTE: 'Urgente' };

    // ── Estado ────────────────────────────────────────────────────────────────
    // scope: 'dept' | 'assigned' | 'mine' | 'unrated' | ''
    var _state = {
        scope: '',
        status: '', category_id: '', priority: '', search: '',
        page: 1, per_page: 20,
        // Campos derivados del scope (enviados al API):
        assigned_to: '', requester: '', unrated: '',
    };
    var _searchTimer = null;
    var _isTechMaint = false;
    var _isDeptHead  = false;
    var _isAssigner  = false;

    // ── Init ──────────────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', function () {
        _detectRoles();
        _configureScopeChips();
        _readUrlParams();
        _loadCategories();
        _bindFilters();
        _loadUnratedCount();
        _fetchTickets();
    });

    // ── Detección de rol ──────────────────────────────────────────────────────
    function _detectRoles() {
        var ctx = window.MAINT_CTX || {};
        _isTechMaint = !!ctx.isTechMaint && !ctx.isAdmin && !ctx.isDispatcher;
        _isAssigner  = !!ctx.isAssigner  && !ctx.isAdmin && !ctx.isDispatcher;
        _isDeptHead  = !!ctx.isDeptHead  && !ctx.isAdmin && !ctx.isDispatcher && !ctx.isTechMaint;
    }

    // ── Configurar visibilidad de chips de scope ──────────────────────────────
    // "Mi departamento" → solo jefe/secretaria (isDeptHead)
    // "Asignados a mí" → técnicos Y coordinadores (pueden auto-asignarse, H1)
    // "Mis solicitudes" y "Por calificar" → todos
    function _configureScopeChips() {
        var chipDept     = document.getElementById('chip-dept');
        var chipAssigned = document.getElementById('chip-assigned');

        if (chipDept) {
            if (!_isDeptHead) chipDept.classList.add('d-none');
        }
        if (chipAssigned) {
            // Técnicos y coordinadores pueden ser técnicos activos de un ticket.
            if (!(_isTechMaint || _isAssigner)) chipAssigned.classList.add('d-none');
        }

        // Default de scope según rol (se puede sobreescribir por URL params):
        if (_isTechMaint) {
            _state.scope = 'assigned';
        } else if (_isDeptHead) {
            _state.scope = 'dept';
        } else {
            _state.scope = 'mine';
        }
        _applyScopeToState();
    }

    // ── Leer query params de la URL para activar pestaña correcta ─────────────
    // Soporta: ?unrated=1, ?requester=me, ?assigned_to=me
    // Permite que enlaces externos abran una vista filtrada.
    function _readUrlParams() {
        var params = new URLSearchParams(window.location.search);

        if (params.get('unrated') === '1') {
            _state.scope = 'unrated';
        } else if (params.get('requester') === 'me') {
            _state.scope = 'mine';
        } else if (params.get('assigned_to') === 'me') {
            if (_isTechMaint) _state.scope = 'assigned';
        }
        // status desde URL (ej: ?status=PENDING)
        if (params.get('status')) {
            _state.status = params.get('status');
        }
        _applyScopeToState();
    }

    // ── Derivar assigned_to/requester/unrated según scope ────────────────────
    function _applyScopeToState() {
        _state.assigned_to = '';
        _state.requester   = '';
        _state.unrated     = '';

        if (_state.scope === 'assigned') {
            _state.assigned_to = 'me';
        } else if (_state.scope === 'mine') {
            _state.requester = 'me';
        } else if (_state.scope === 'unrated') {
            _state.unrated = '1';
        }
        // scope === 'dept' → sin params extra (el backend lo aplica por rol)

        _activateScopeChip(_state.scope);
    }

    // ── Marcar chip de scope activo ───────────────────────────────────────────
    function _activateScopeChip(scope) {
        document.querySelectorAll('#scopeFilters .mn-status-filter').forEach(function (b) {
            b.classList.remove('active');
        });
        var map = {
            dept:     'chip-dept',
            assigned: 'chip-assigned',
            mine:     'chip-mine',
            unrated:  'chip-unrated',
        };
        var targetId = map[scope];
        if (targetId) {
            var el = document.getElementById(targetId);
            // Solo activar si el chip es visible (no d-none)
            if (el && !el.classList.contains('d-none')) {
                el.classList.add('active');
            }
        }
    }

    // ── Cargar conteo de "Por calificar" para el badge ────────────────────────
    // Fetch liviano con per_page=1 para leer solo el total.
    function _loadUnratedCount() {
        MaintUtils.api.fetch(API_BASE + '/tickets?unrated=1&per_page=1')
            .then(function (data) {
                var total = data.total || 0;
                var badge = document.getElementById('unratedBadge');
                if (!badge) return;
                if (total > 0) {
                    badge.textContent = total > 99 ? '99+' : String(total);
                    badge.classList.remove('d-none');
                } else {
                    badge.classList.add('d-none');
                }
            })
            .catch(function () { /* badge de conteo es opcional */ });
    }

    function _loadCategories() {
        MaintUtils.api.fetch(API_BASE + '/categories')
            .then(function (data) {
                var sel = document.getElementById('categoryFilter');
                (data.categories || []).forEach(function (c) {
                    var opt = document.createElement('option');
                    opt.value = c.id;
                    opt.textContent = c.name;
                    sel.appendChild(opt);
                });
            })
            .catch(function () { /* categorías opcionales */ });
    }

    function _bindFilters() {
        // ── Chips de scope (vista) ────────────────────────────────────────────
        var scopeContainer = document.getElementById('scopeFilters');
        if (scopeContainer) {
            scopeContainer.addEventListener('click', function (e) {
                var btn = e.target.closest('.mn-status-filter');
                if (!btn || btn.classList.contains('d-none')) return;
                _state.scope  = btn.dataset.scope || '';
                _state.status = '';  // reset status al cambiar scope
                _state.page   = 1;
                _applyScopeToState();
                // Resetear chips de status al cambiar scope
                document.querySelectorAll('#statusFilters .mn-status-filter').forEach(function (b) {
                    b.classList.remove('active');
                });
                var allBtn = document.querySelector('#statusFilters .mn-status-filter--all');
                if (allBtn) allBtn.classList.add('active');
                _fetchTickets();
            });
        }

        // ── Chips de estado ───────────────────────────────────────────────────
        document.getElementById('statusFilters').addEventListener('click', function (e) {
            var btn = e.target.closest('.mn-status-filter');
            if (!btn) return;
            document.querySelectorAll('#statusFilters .mn-status-filter').forEach(function (b) {
                b.classList.remove('active');
            });
            btn.classList.add('active');
            _state.status = btn.dataset.status || '';
            _state.page = 1;
            _fetchTickets();
        });

        document.getElementById('categoryFilter').addEventListener('change', function () {
            _state.category_id = this.value;
            _state.page = 1;
            _fetchTickets();
        });

        document.getElementById('priorityFilter').addEventListener('change', function () {
            _state.priority = this.value;
            _state.page = 1;
            _fetchTickets();
        });

        document.getElementById('searchInput').addEventListener('input', function () {
            clearTimeout(_searchTimer);
            var val = this.value;
            _searchTimer = setTimeout(function () {
                _state.search = val;
                _state.page = 1;
                _fetchTickets();
            }, 400);
        });

        document.getElementById('clearFilters').addEventListener('click', function () {
            // Restaurar scope al default del rol
            if (_isTechMaint) {
                _state.scope = 'assigned';
            } else if (_isDeptHead) {
                _state.scope = 'dept';
            } else {
                _state.scope = 'mine';
            }
            _state.status = '';
            _state.category_id = '';
            _state.priority = '';
            _state.search = '';
            _state.page = 1;
            _applyScopeToState();

            document.getElementById('searchInput').value = '';
            document.getElementById('categoryFilter').value = '';
            document.getElementById('priorityFilter').value = '';
            // Reset chips de status
            document.querySelectorAll('#statusFilters .mn-status-filter').forEach(function (b) {
                b.classList.remove('active');
            });
            var allBtn = document.querySelector('#statusFilters .mn-status-filter--all');
            if (allBtn) allBtn.classList.add('active');
            _fetchTickets();
        });
    }

    function _fetchTickets() {
        var container = document.getElementById('ticketList');
        container.classList.remove('mn-stagger');
        if (window.MaintUtils && MaintUtils.skeleton) {
            MaintUtils.skeleton.show(container, 'ticket-card', 4);
        } else {
            container.innerHTML = _skeletonHTML();
        }

        var params = new URLSearchParams({ page: _state.page, per_page: _state.per_page });
        if (_state.status)      params.set('status',      _state.status);
        if (_state.category_id) params.set('category_id', _state.category_id);
        if (_state.priority)    params.set('priority',    _state.priority);
        if (_state.search)      params.set('search',      _state.search);
        if (_state.assigned_to) params.set('assigned_to', _state.assigned_to);
        if (_state.requester)   params.set('requester',   _state.requester);
        if (_state.unrated)     params.set('unrated',     _state.unrated);

        MaintUtils.api.fetch(API_BASE + '/tickets?' + params.toString())
            .then(function (data) {
                _renderTickets(data);
            })
            .catch(function (err) {
                container.innerHTML =
                    '<div class="alert alert-danger"><i class="bi bi-exclamation-triangle me-2"></i>' +
                    'Error al cargar tickets: ' + _esc(err.message) + '</div>';
            });
    }

    function _renderTickets(data) {
        var container = document.getElementById('ticketList');
        var tickets = data.tickets || [];

        var countEl = document.getElementById('resultsCount');
        countEl.textContent = data.total > 0
            ? data.total + ' resultado' + (data.total !== 1 ? 's' : '')
            : '';

        if (tickets.length === 0) {
            container.innerHTML =
                '<div class="text-center py-5 text-muted mn-empty">' +
                '<i class="bi bi-clipboard-x fs-1 d-block mb-2"></i>' +
                '<p class="mb-0">No se encontraron tickets</p>' +
                '</div>';
            document.getElementById('paginationContainer').innerHTML = '';
            return;
        }

        container.innerHTML = tickets.map(_renderCard).join('');
        container.classList.add('mn-stagger');
        // ensure each direct child has the entrance class (CSS handles the rest)
        Array.prototype.forEach.call(container.children, function (a) {
            a.classList.add('mn-fade-in-up');
        });
        _renderPagination(data);
    }

    function _renderCard(t) {
        var now = new Date();
        var dueDate = t.due_at ? new Date(t.due_at) : null;
        var isOverdue = dueDate && dueDate < now && t.status !== 'CLOSED' && t.status !== 'CANCELED' && t.status !== 'RESOLVED_SUCCESS' && t.status !== 'RESOLVED_FAILED';
        var isDueSoon = !isOverdue && dueDate && (dueDate - now) < 24 * 3600 * 1000;

        var slaClass = isOverdue ? 'mn-sla-overdue' : (isDueSoon ? 'mn-sla-warning' : 'mn-sla-ok');
        var slaIcon = isOverdue ? 'bi-exclamation-triangle-fill' : 'bi-clock';
        var slaText = dueDate ? _formatDate(dueDate) : '';

        var cardBorderClass = isOverdue ? 'mn-overdue' : (isDueSoon ? 'mn-due-soon' : '');

        var techs = (t.active_technicians || []).map(function (tech) {
            return '<span class="mn-technician-chip">' +
                '<i class="bi bi-person-fill" style="font-size:0.7rem;"></i> ' +
                _esc(tech.name) + '</span>';
        }).join(' ');

        var catIcon = t.category ? t.category.icon : 'bi-tools';
        var catName = t.category ? t.category.name : '—';
        var requesterName = t.requester ? t.requester.name : '—';

        // Usar is_overdue del servidor si está disponible; si no, calcularlo localmente
        var serverOverdue = (t.is_overdue === true);
        var overdueBadge = (isOverdue || serverOverdue)
            ? '<span class="mn-badge-overdue ms-1"><i class="bi bi-exclamation-triangle-fill"></i>Vencido</span>'
            : '';

        return '<a href="/maint/tickets/' + t.id + '" class="text-decoration-none">' +
            '<div class="mn-ticket-card ' + cardBorderClass + ' mb-3 p-3">' +
                '<div class="d-flex justify-content-between align-items-start flex-wrap gap-2">' +
                    '<div class="d-flex align-items-start gap-2 flex-wrap">' +
                        '<span class="mn-badge-status ' + (STATUS_CSS[t.status] || '') + '">' +
                            (STATUS_LABEL[t.status] || t.status) + '</span>' +
                        overdueBadge +
                        '<span class="mn-badge-status ' + (PRIORITY_CSS[t.priority] || '') + '">' +
                            (PRIORITY_LABEL[t.priority] || t.priority) + '</span>' +
                        '<span class="mn-category-badge"><i class="bi ' + _esc(catIcon) + ' me-1"></i>' + _esc(catName) + '</span>' +
                    '</div>' +
                    '<span class="mn-ticket-number">' + _esc(t.ticket_number) + '</span>' +
                '</div>' +
                '<div class="mt-2">' +
                    '<div class="fw-semibold" style="color: var(--maint-primary-darker);">' + _esc(t.title) + '</div>' +
                    (t.location ? '<small class="text-muted"><i class="bi bi-geo-alt me-1"></i>' + _esc(t.location) + '</small>' : '') +
                '</div>' +
                '<div class="mn-progress-bar mt-2 mb-2">' +
                    '<div class="mn-progress-fill" style="width:' + (t.progress_pct || 0) + '%"></div>' +
                '</div>' +
                '<div class="d-flex justify-content-between align-items-center flex-wrap gap-2">' +
                    '<div class="d-flex flex-wrap gap-1">' + (techs || '<small class="text-muted">Sin técnico asignado</small>') + '</div>' +
                    '<div class="d-flex align-items-center gap-3">' +
                        '<small class="text-muted"><i class="bi bi-person me-1"></i>' + _esc(requesterName) + '</small>' +
                        (slaText ? '<span class="mn-sla-indicator ' + slaClass + '"><i class="bi ' + slaIcon + '"></i>' + slaText + '</span>' : '') +
                    '</div>' +
                '</div>' +
            '</div>' +
        '</a>';
    }

    function _renderPagination(data) {
        var container = document.getElementById('paginationContainer');
        if (data.pages <= 1) { container.innerHTML = ''; return; }

        var html = '<ul class="pagination pagination-sm">';

        html += '<li class="page-item ' + (data.has_prev ? '' : 'disabled') + '">' +
            '<button class="page-link" data-page="' + (_state.page - 1) + '">&laquo;</button></li>';

        for (var p = 1; p <= data.pages; p++) {
            if (p === 1 || p === data.pages || Math.abs(p - _state.page) <= 2) {
                html += '<li class="page-item ' + (p === _state.page ? 'active' : '') + '">' +
                    '<button class="page-link" data-page="' + p + '">' + p + '</button></li>';
            } else if (Math.abs(p - _state.page) === 3) {
                html += '<li class="page-item disabled"><span class="page-link">…</span></li>';
            }
        }

        html += '<li class="page-item ' + (data.has_next ? '' : 'disabled') + '">' +
            '<button class="page-link" data-page="' + (_state.page + 1) + '">&raquo;</button></li>';

        html += '</ul>';
        container.innerHTML = html;

        container.querySelectorAll('[data-page]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                _state.page = parseInt(this.dataset.page, 10);
                _fetchTickets();
                window.scrollTo({ top: 0, behavior: 'smooth' });
            });
        });
    }

    function _skeletonHTML() {
        var item = '<div class="mn-ticket-card mb-3 p-3">' +
            '<div class="d-flex gap-2 mb-2">' +
                '<div class="mn-skeleton rounded-pill" style="height:22px;width:90px;"></div>' +
                '<div class="mn-skeleton rounded-pill" style="height:22px;width:60px;"></div>' +
                '<div class="mn-skeleton rounded-pill" style="height:22px;width:120px;"></div>' +
            '</div>' +
            '<div class="mn-skeleton rounded mb-1" style="height:18px;width:70%;"></div>' +
            '<div class="mn-skeleton rounded mb-2" style="height:14px;width:40%;"></div>' +
            '<div class="mn-skeleton rounded" style="height:6px;width:100%;"></div>' +
        '</div>';
        return item + item + item;
    }

    function _formatDate(d) {
        return d.toLocaleDateString('es-MX', { day: '2-digit', month: 'short' }) +
               ' ' + d.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit' });
    }

    function _esc(s) {
        // H9: escapa comillas además de &<> para ser seguro en atributos (title="...").
        var map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
        return String(s || '').replace(/[&<>"']/g, function (ch) { return map[ch]; });
    }

})();

// =============================================================================
// MaintLiveListSync — WebSocket live updates para la lista de tickets
// =============================================================================
(function () {
    'use strict';

    var _newBannerCount = 0;
    var _bannerEl = null;

    // ── Esperar a que el socket esté listo (máx 3 s) ─────────────────────────

    function _waitForSocket(callback) {
        var attempts = 0;
        var maxAttempts = 30; // 30 × 100 ms = 3 s
        var interval = setInterval(function () {
            if (window.__maintSocket) {
                clearInterval(interval);
                callback(window.__maintSocket);
                return;
            }
            attempts++;
            if (attempts >= maxAttempts) {
                clearInterval(interval);
                console.warn('[MaintLiveListSync] Socket no disponible después de 3 s — sin actualizaciones en tiempo real');
            }
        }, 100);
    }

    // ── Unirse a los rooms según el rol del usuario ───────────────────────────

    function _joinRooms() {
        var ctx = window.MAINT_CTX || {};

        // Siempre unirse al room personal (recibe ticket_assigned)
        window.__maintJoinTech();

        // Dispatcher y admin ven todos los tickets
        if (ctx.isDispatcher) {
            window.__maintJoinDispatcher();
        }

        // department_head / secretary: no se une a dept room porque el
        // department_id del usuario no está disponible en esta página sin una
        // llamada adicional al backend. El room personal (join_tech) es suficiente
        // para ticket_assigned; los eventos de estado llegarán al dispatcher si aplica.
    }

    // ── Banner de "hay N tickets nuevos" ─────────────────────────────────────

    function _ensureBanner() {
        if (_bannerEl) return;
        _bannerEl = document.createElement('div');
        _bannerEl.id = 'liveNewBanner';
        _bannerEl.style.cssText =
            'display:none;cursor:pointer;background:#0d6efd;color:#fff;' +
            'text-align:center;padding:8px 12px;border-radius:6px;margin-bottom:12px;font-size:0.875rem;';
        _bannerEl.addEventListener('click', function () {
            _newBannerCount = 0;
            _hideBanner();
            if (typeof _fetchTickets === 'function') _fetchTickets();
        });

        var listEl = document.getElementById('ticketList');
        if (listEl && listEl.parentNode) {
            listEl.parentNode.insertBefore(_bannerEl, listEl);
        }
    }

    function _showBanner() {
        _ensureBanner();
        _bannerEl.style.display = 'block';
        _bannerEl.textContent =
            'Hay ' + _newBannerCount + ' ticket' + (_newBannerCount !== 1 ? 's' : '') +
            ' nuevo' + (_newBannerCount !== 1 ? 's' : '') + '. Haz clic para actualizar.';
    }

    function _hideBanner() {
        if (_bannerEl) _bannerEl.style.display = 'none';
    }

    // ── Comprobar si un ticket recién creado pasa los filtros actuales ────────

    function _matchesCurrentFilters(payload) {
        // _state es la variable de estado del IIFE principal (closure compartido
        // entre los dos IIFEs en el mismo archivo).
        // Como ambos IIFEs están en el mismo archivo, _state NO es accesible aquí.
        // Se accede a través de los filtros activos del DOM, que es la fuente de
        // verdad observable desde el exterior.
        var activeStatusBtn = document.querySelector('.mn-status-filter.active');
        var statusFilter   = activeStatusBtn ? (activeStatusBtn.dataset.status || '') : '';
        var catFilter      = (document.getElementById('categoryFilter') || {}).value || '';
        var priorityFilter = (document.getElementById('priorityFilter') || {}).value || '';
        var searchFilter   = ((document.getElementById('searchInput') || {}).value || '').toLowerCase().trim();

        if (statusFilter && payload.status !== statusFilter) return false;
        if (catFilter && String(payload.category_id) !== String(catFilter)) return false;
        if (priorityFilter && payload.priority !== priorityFilter) return false;
        if (searchFilter) {
            var title  = (payload.title || '').toLowerCase();
            var number = (payload.ticket_number || '').toLowerCase();
            if (title.indexOf(searchFilter) === -1 && number.indexOf(searchFilter) === -1) return false;
        }
        return true;
    }

    // ── Flash animation en tarjeta nueva ─────────────────────────────────────

    function _flashCard(cardEl) {
        if (window.MaintUtils && MaintUtils.animate) {
            MaintUtils.animate.highlight(cardEl);
            return;
        }
        cardEl.style.transition = 'background-color 0.4s ease';
        cardEl.style.backgroundColor = '#d1e7dd';
        setTimeout(function () { cardEl.style.backgroundColor = ''; }, 1200);
    }

    // ── Actualizar tarjeta existente en la lista ──────────────────────────────

    var STATUS_LABEL = {
        PENDING: 'Pendiente', ASSIGNED: 'Asignado', IN_PROGRESS: 'En Progreso',
        RESOLVED_SUCCESS: 'Resuelto', RESOLVED_FAILED: 'Atendido',
        CLOSED: 'Cerrado', CANCELED: 'Cancelado',
    };
    var STATUS_CSS = {
        PENDING: 'mn-status-pending', ASSIGNED: 'mn-status-assigned',
        IN_PROGRESS: 'mn-status-in-progress', RESOLVED_SUCCESS: 'mn-status-resolved-ok',
        RESOLVED_FAILED: 'mn-status-resolved-fail', CLOSED: 'mn-status-closed',
        CANCELED: 'mn-status-canceled',
    };
    var PRIORITY_CSS = {
        BAJA: 'mn-priority-baja', MEDIA: 'mn-priority-media',
        ALTA: 'mn-priority-alta', URGENTE: 'mn-priority-urgente',
    };
    var PRIORITY_LABEL = { BAJA: 'Baja', MEDIA: 'Media', ALTA: 'Alta', URGENTE: 'Urgente' };

    function _updateCardInPlace(payload) {
        // Las tarjetas son <a href="..."><div class="mn-ticket-card ...">
        // Buscamos por ticket_number o construimos el href
        var ticketId = payload.ticket_id;
        if (!ticketId) return false;

        var link = document.querySelector('#ticketList a[href="/maint/tickets/' + ticketId + '"]');
        if (!link) return false;

        // Actualizar badge de estado
        if (payload.status) {
            var badges = link.querySelectorAll('.mn-badge-status');
            // El primer badge es el de estado, el segundo es prioridad
            if (badges[0]) {
                badges[0].textContent = STATUS_LABEL[payload.status] || payload.status;
                badges[0].className = 'mn-badge-status ' + (STATUS_CSS[payload.status] || '');
            }
        }

        // Actualizar badge de prioridad
        if (payload.priority) {
            var badges2 = link.querySelectorAll('.mn-badge-status');
            if (badges2[1]) {
                badges2[1].textContent = PRIORITY_LABEL[payload.priority] || payload.priority;
                badges2[1].className = 'mn-badge-status ' + (PRIORITY_CSS[payload.priority] || '');
            }
        }

        // Actualizar chips de técnicos
        if (payload.active_technicians !== undefined) {
            var techsContainer = link.querySelector('.mn-ticket-card > div:last-child > div:first-child');
            if (techsContainer) {
                var techs = (payload.active_technicians || []).map(function (tech) {
                    return '<span class="mn-technician-chip">' +
                        '<i class="bi bi-person-fill" style="font-size:0.7rem;"></i> ' +
                        _escLocal(tech.name || tech.user_name || '') + '</span>';
                }).join(' ');
                techsContainer.innerHTML = techs || '<small class="text-muted">Sin técnico asignado</small>';
            }
        }

        return true;
    }

    function _escLocal(s) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(String(s || '')));
        return d.innerHTML;
    }

    // ── Prepend de tarjeta nueva ──────────────────────────────────────────────

    function _prependNewCard(payload) {
        var container = document.getElementById('ticketList');
        if (!container) return;

        // Construir un <a> wrapper mínimo con la data del payload
        var wrapper = document.createElement('a');
        wrapper.href = '/maint/tickets/' + payload.id;
        wrapper.className = 'text-decoration-none';

        var card = document.createElement('div');
        card.className = 'mn-ticket-card mb-3 p-3';
        card.innerHTML =
            '<div class="d-flex justify-content-between align-items-start flex-wrap gap-2">' +
                '<div class="d-flex align-items-start gap-2 flex-wrap">' +
                    '<span class="mn-badge-status ' + (STATUS_CSS[payload.status] || '') + '">' +
                        (STATUS_LABEL[payload.status] || payload.status) + '</span>' +
                    '<span class="mn-badge-status ' + (PRIORITY_CSS[payload.priority] || '') + '">' +
                        (PRIORITY_LABEL[payload.priority] || payload.priority) + '</span>' +
                '</div>' +
                '<span class="mn-ticket-number">' + _escLocal(payload.ticket_number || '') + '</span>' +
            '</div>' +
            '<div class="mt-2">' +
                '<div class="fw-semibold" style="color: var(--maint-primary-darker);">' + _escLocal(payload.title || '') + '</div>' +
                (payload.location ? '<small class="text-muted"><i class="bi bi-geo-alt me-1"></i>' + _escLocal(payload.location) + '</small>' : '') +
            '</div>' +
            '<div class="mn-progress-bar mt-2 mb-2"><div class="mn-progress-fill" style="width:0%"></div></div>' +
            '<div class="d-flex justify-content-between align-items-center flex-wrap gap-2">' +
                '<small class="text-muted">Sin técnico asignado</small>' +
                '<small class="text-muted"><i class="bi bi-person me-1"></i>' +
                    _escLocal((payload.requester && payload.requester.name) || '') + '</small>' +
            '</div>';

        wrapper.appendChild(card);
        wrapper.classList.add('mn-fade-in-down');

        // Insertar antes del primer hijo (o como único hijo si la lista estaba vacía)
        if (container.firstChild && !container.querySelector('.text-center')) {
            container.insertBefore(wrapper, container.firstChild);
        } else {
            container.innerHTML = '';
            container.appendChild(wrapper);
        }

        _flashCard(card);
    }

    // ── Registro de eventos ───────────────────────────────────────────────────

    function _bindEvents(socket) {
        // Ticket creado: solo dispatcher/admin lo reciben (vía dispatcher:all y dept room)
        socket.on('ticket_created', function (payload) {
            if (_matchesCurrentFilters(payload)) {
                _prependNewCard(payload);
                _hideBanner();
            } else {
                _newBannerCount++;
                _showBanner();
            }
        });

        // Cambios de estado/asignación: actualizar tarjeta existente si está renderizada
        var _updateEvents = [
            'ticket_assigned',
            'ticket_unassigned',
            'ticket_status_changed',
            'ticket_resolved',
            'ticket_canceled',
            'ticket_rated',
        ];

        _updateEvents.forEach(function (eventName) {
            socket.on(eventName, function (payload) {
                // Normalizar ticket_id (puede venir como id en algunos payloads)
                var tid = payload.ticket_id || payload.id;
                if (!tid) return;
                var normalized = Object.assign({}, payload, { ticket_id: tid });
                _updateCardInPlace(normalized);
                // No tocar el estado interno — la próxima carga del servidor
                // traerá los datos correctos con filtros y paginación.
            });
        });
    }

    // ── Init ──────────────────────────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', function () {
        _waitForSocket(function (socket) {
            _joinRooms();
            _bindEvents(socket);
        });
    });

    window.MaintLiveListSync = { joinRooms: _joinRooms };

})();
