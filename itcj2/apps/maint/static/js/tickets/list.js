/**
 * tickets-list.js — Lista de tickets de Mantenimiento
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
    var _state = {
        status: '', category_id: '', priority: '', search: '',
        page: 1, per_page: 20,
    };
    var _searchTimer = null;

    // ── Init ──────────────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', function () {
        _loadCategories();
        _bindFilters();
        _fetchTickets();
    });

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
        document.getElementById('statusFilters').addEventListener('click', function (e) {
            var btn = e.target.closest('.mn-status-filter');
            if (!btn) return;
            document.querySelectorAll('.mn-status-filter').forEach(function (b) { b.classList.remove('active'); });
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
            _state = { status: '', category_id: '', priority: '', search: '', page: 1, per_page: 20 };
            document.getElementById('searchInput').value = '';
            document.getElementById('categoryFilter').value = '';
            document.getElementById('priorityFilter').value = '';
            document.querySelectorAll('.mn-status-filter').forEach(function (b) { b.classList.remove('active'); });
            document.querySelector('[data-status=""]').classList.add('active');
            _fetchTickets();
        });
    }

    function _fetchTickets() {
        var container = document.getElementById('ticketList');
        container.innerHTML = _skeletonHTML();

        var params = new URLSearchParams({ page: _state.page, per_page: _state.per_page });
        if (_state.status)      params.set('status', _state.status);
        if (_state.category_id) params.set('category_id', _state.category_id);
        if (_state.priority)    params.set('priority', _state.priority);
        if (_state.search)      params.set('search', _state.search);

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
                '<div class="text-center py-5 text-muted">' +
                '<i class="bi bi-clipboard-x fs-1 d-block mb-2"></i>' +
                '<p class="mb-0">No se encontraron tickets</p>' +
                '</div>';
            document.getElementById('paginationContainer').innerHTML = '';
            return;
        }

        container.innerHTML = tickets.map(_renderCard).join('');
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

        return '<a href="/maintenance/tickets/' + t.id + '" class="text-decoration-none">' +
            '<div class="mn-ticket-card ' + cardBorderClass + ' mb-3 p-3">' +
                '<div class="d-flex justify-content-between align-items-start flex-wrap gap-2">' +
                    '<div class="d-flex align-items-start gap-2 flex-wrap">' +
                        '<span class="mn-badge-status ' + (STATUS_CSS[t.status] || '') + '">' +
                            (STATUS_LABEL[t.status] || t.status) + '</span>' +
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
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(String(s || '')));
        return d.innerHTML;
    }

})();
