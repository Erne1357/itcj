'use strict';
(function () {

    const STATUS_LABELS = {
        DRAFT:     { label: 'Borrador',  cls: 'bg-secondary text-white' },
        PENDING:   { label: 'Pendiente', cls: 'bg-warning text-dark' },
        APPROVED:  { label: 'Aprobada',  cls: 'bg-success text-white' },
        REJECTED:  { label: 'Rechazada', cls: 'bg-danger text-white' },
        CANCELLED: { label: 'Cancelada', cls: 'bg-secondary text-white' },
    };

    let currentPage = 1;
    const PAGE_SIZE = 20;
    let debounceTimer = null;
    let pendingScrollRestore = 0;

    const el = {
        search: document.getElementById('search-input'),
        status: document.getElementById('status-filter'),
        scope:  document.getElementById('scope-filter'),
        clear:  document.getElementById('btn-clear-filters'),
        tbody:  document.getElementById('requests-tbody'),
        total:  document.getElementById('total-count'),
        pagInfo: document.getElementById('pagination-info'),
        pagList: document.getElementById('pagination-list'),
        pagContainer: document.getElementById('pagination-container'),
    };

    function statusBadge(status) {
        const s = STATUS_LABELS[status] || { label: status, cls: 'bg-light text-dark' };
        return `<span class="badge ${s.cls} status-badge">${s.label}</span>`;
    }

    function fmtDate(iso) {
        if (!iso) return '—';
        return new Date(iso).toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' });
    }

    function goToRequest(id) {
        HelpdeskUtils.NavState.save('retirement_requests', {
            search: el.search ? el.search.value : '',
            status: el.status ? el.status.value : '',
            scope: el.scope ? el.scope.value : 'all',
            page: currentPage,
            scrollY: window.scrollY,
        });
        window.location = `/help-desk/inventory/retirement-requests/${id}`;
    }

    function buildRow(r) {
        const itemsCount = r.items_count !== undefined ? r.items_count : '—';
        return `<tr style="cursor:pointer;" onclick="goToRequest(${r.id})">
            <td class="pl-3 folio-cell">${r.folio}</td>
            <td>${statusBadge(r.status)}</td>
            <td class="d-none d-md-table-cell text-truncate" style="max-width:200px;" title="${r.reason}">${r.reason}</td>
            <td class="d-none d-sm-table-cell">${itemsCount}</td>
            <td class="d-none d-md-table-cell">${r.requested_by ? r.requested_by.full_name : '—'}</td>
            <td class="d-none d-lg-table-cell">${fmtDate(r.created_at)}</td>
            <td class="text-center">
                <a href="/help-desk/inventory/retirement-requests/${r.id}" class="btn btn-sm btn-outline-primary py-0 px-1"
                   onclick="event.stopPropagation();">
                    <i class="fas fa-eye"></i>
                </a>
            </td>
        </tr>`;
    }

    async function loadRequests() {
        const params = new URLSearchParams();
        params.set('page', currentPage);
        params.set('per_page', PAGE_SIZE);
        const search = el.search ? el.search.value.trim() : '';
        const status = el.status ? el.status.value : '';
        const scope  = el.scope  ? el.scope.value  : '';
        if (search) params.set('search', search);
        if (status) params.set('status', status);
        if (scope === 'mine') params.set('mine', '1');

        el.tbody.innerHTML = `<tr><td colspan="7" class="text-center py-3">
            <i class="fas fa-spinner fa-spin text-primary"></i> Cargando...
        </td></tr>`;

        try {
            const res = await fetch(`/api/help-desk/v2/inventory/retirement-requests?${params}`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();

            const items = data.requests || [];
            const total = data.total || items.length;

            if (el.total) el.total.textContent = total;

            if (!items.length) {
                el.tbody.innerHTML = `<tr><td colspan="7" class="text-center py-4 text-muted">
                    <i class="fas fa-inbox fa-2x mb-2 d-block"></i>
                    No se encontraron solicitudes con los filtros actuales.
                </td></tr>`;
                renderPagination(0, total);
                return;
            }

            el.tbody.innerHTML = items.map(buildRow).join('');
            renderPagination(items.length, total);

            if (pendingScrollRestore > 0) {
                const sy = pendingScrollRestore;
                pendingScrollRestore = 0;
                requestAnimationFrame(() => window.scrollTo({ top: sy, behavior: 'instant' }));
            }

        } catch (err) {
            el.tbody.innerHTML = `<tr><td colspan="7" class="text-center py-3 text-danger">
                <i class="fas fa-exclamation-circle"></i> Error al cargar: ${err.message}
            </td></tr>`;
        }
    }

    function renderPagination(count, total) {
        if (!el.pagContainer) return;
        const totalPages = Math.ceil(total / PAGE_SIZE);
        if (totalPages <= 1) {
            el.pagContainer.style.display = 'none';
            return;
        }
        el.pagContainer.style.display = 'flex';
        if (el.pagInfo) el.pagInfo.textContent = `Página ${currentPage} de ${totalPages} (${total} total)`;
        if (!el.pagList) return;

        const pages = [];
        for (let p = 1; p <= totalPages; p++) {
            if (p === 1 || p === totalPages || Math.abs(p - currentPage) <= 2) {
                pages.push(p);
            } else if (pages[pages.length - 1] !== '...') {
                pages.push('...');
            }
        }

        el.pagList.innerHTML = pages.map(p => {
            if (p === '...') return `<li class="page-item disabled"><span class="page-link">…</span></li>`;
            const active = p === currentPage ? 'active' : '';
            return `<li class="page-item ${active}">
                <button class="page-link" data-page="${p}">${p}</button>
            </li>`;
        }).join('');

        el.pagList.querySelectorAll('[data-page]').forEach(btn => {
            btn.addEventListener('click', () => {
                currentPage = parseInt(btn.dataset.page);
                loadRequests();
            });
        });
    }

    function scheduleSearch() {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            currentPage = 1;
            loadRequests();
        }, 350);
    }

    function init() {
        // Restore state if coming back from a request detail
        if (document.referrer.includes('/help-desk/inventory/retirement-requests/')) {
            const saved = HelpdeskUtils.NavState.load('retirement_requests');
            if (saved) {
                if (el.search) el.search.value = saved.search || '';
                if (el.status) el.status.value = saved.status || '';
                if (el.scope)  el.scope.value  = saved.scope  || 'all';
                currentPage = saved.page || 1;
                pendingScrollRestore = saved.scrollY || 0;
            }
        }

        if (el.search)  el.search.addEventListener('input', scheduleSearch);
        if (el.status)  el.status.addEventListener('change', () => { currentPage = 1; loadRequests(); });
        if (el.scope)   el.scope.addEventListener('change',  () => { currentPage = 1; loadRequests(); });
        if (el.clear) {
            el.clear.addEventListener('click', () => {
                if (el.search) el.search.value = '';
                if (el.status) el.status.value = '';
                if (el.scope)  el.scope.value  = 'all';
                currentPage = 1;
                HelpdeskUtils.NavState.clear('retirement_requests');
                loadRequests();
            });
        }
        loadRequests();
    }

    document.addEventListener('DOMContentLoaded', init);

    // Expose goToRequest for use in onclick handlers
    window.goToRequest = goToRequest;

})();
