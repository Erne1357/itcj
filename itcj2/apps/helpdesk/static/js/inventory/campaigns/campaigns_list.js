'use strict';
(function () {

    const STATUS_LABELS = {
        OPEN:                { label: 'Abierta',              cls: 'bg-primary text-white' },
        PENDING_VALIDATION:  { label: 'Pendiente validación', cls: 'bg-warning text-dark' },
        VALIDATED:           { label: 'Validada',             cls: 'bg-success text-white' },
        REJECTED:            { label: 'Rechazada',            cls: 'bg-danger text-white' },
    };

    let currentPage = 1;
    const PAGE_SIZE = 20;
    let debounceTimer = null;

    const el = {
        folio:        document.getElementById('filter-folio'),
        status:       document.getElementById('filter-status'),
        department:   document.getElementById('filter-department'),
        clear:        document.getElementById('btn-clear-filters'),
        tbody:        document.getElementById('campaigns-tbody'),
        total:        document.getElementById('total-count'),
        pagInfo:      document.getElementById('pagination-info'),
        pagList:      document.getElementById('pagination-list'),
        pagContainer: document.getElementById('pagination-container'),
    };

    function statusBadge(status) {
        const s = STATUS_LABELS[status] || { label: status, cls: 'bg-light text-dark' };
        return `<span class="badge ${s.cls} campaign-status-badge">${s.label}</span>`;
    }

    function fmtDate(iso) {
        if (!iso) return '—';
        return new Date(iso).toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' });
    }

    function goToCampaign(id) {
        HelpdeskUtils.NavState.save('campaigns_list', {
            folio: el.folio ? el.folio.value : '',
            status: el.status ? el.status.value : '',
            department: el.department ? el.department.value : '',
            page: currentPage,
            scrollY: window.scrollY,
        });
        window.location = `/help-desk/inventory/campaigns/${id}`;
    }

    function buildRow(c) {
        const dept = c.department ? c.department.name : '—';
        return `
        <tr style="cursor:pointer;" onclick="goToCampaign(${c.id})">
            <td class="pl-3 font-weight-bold">${c.folio}</td>
            <td>${statusBadge(c.status)}</td>
            <td class="d-none d-md-table-cell">${dept}</td>
            <td class="d-none d-sm-table-cell text-center">${c.items_count}</td>
            <td class="d-none d-lg-table-cell">${fmtDate(c.started_at)}</td>
            <td class="d-none d-lg-table-cell">${fmtDate(c.closed_at)}</td>
            <td class="text-center">
                <a href="/help-desk/inventory/campaigns/${c.id}"
                   class="btn btn-sm btn-outline-primary py-0 px-1"
                   onclick="event.stopPropagation();" title="Ver detalle">
                    <i class="fas fa-eye"></i>
                </a>
                ${c.status === 'PENDING_VALIDATION' ? `
                <a href="/help-desk/inventory/campaigns/${c.id}/validate"
                   class="btn btn-sm btn-outline-warning py-0 px-1 ml-1"
                   onclick="event.stopPropagation();" title="Validar">
                    <i class="fas fa-clipboard-check"></i>
                </a>` : ''}
            </td>
        </tr>`;
    }

    async function loadCampaigns() {
        const params = new URLSearchParams();
        params.set('page', currentPage);
        params.set('per_page', PAGE_SIZE);

        const folio = el.folio ? el.folio.value.trim() : '';
        const status = el.status ? el.status.value : '';
        const deptId = el.department ? el.department.value : '';

        if (folio)  params.set('folio', folio);
        if (status) params.set('status', status);
        if (deptId) params.set('department_id', deptId);
        // Si es department_head, el backend filtra automáticamente

        el.tbody.innerHTML = `<tr><td colspan="7" class="text-center py-3">
            <i class="fas fa-spinner fa-spin text-primary"></i> Cargando...</td></tr>`;

        try {
            const res = await fetch(`/api/help-desk/v2/inventory/campaigns?${params}`);
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Error al cargar');

            const campaigns = data.campaigns || [];
            el.total.textContent = data.total || 0;

            if (campaigns.length === 0) {
                el.tbody.innerHTML = `<tr><td colspan="7" class="text-center py-4 text-muted">
                    <i class="fas fa-inbox fa-lg mb-1 d-block"></i>No hay campañas</td></tr>`;
            } else {
                el.tbody.innerHTML = campaigns.map(buildRow).join('');
            }

            renderPagination(data.total, data.page, data.total_pages);
        } catch (err) {
            el.tbody.innerHTML = `<tr><td colspan="7" class="text-center py-4 text-danger">
                <i class="fas fa-exclamation-circle"></i> ${err.message}</td></tr>`;
        }
    }

    function renderPagination(total, page, totalPages) {
        if (!el.pagContainer) return;
        if (totalPages <= 1) {
            el.pagContainer.style.display = 'none';
            return;
        }
        el.pagContainer.style.removeProperty('display');
        el.pagInfo.textContent = `Mostrando página ${page} de ${totalPages} (${total} campañas)`;

        let html = '';
        if (page > 1) html += `<li class="page-item"><a class="page-link" href="#" data-page="${page - 1}">&laquo;</a></li>`;
        for (let p = Math.max(1, page - 2); p <= Math.min(totalPages, page + 2); p++) {
            html += `<li class="page-item ${p === page ? 'active' : ''}">
                <a class="page-link" href="#" data-page="${p}">${p}</a></li>`;
        }
        if (page < totalPages) html += `<li class="page-item"><a class="page-link" href="#" data-page="${page + 1}">&raquo;</a></li>`;
        el.pagList.innerHTML = html;
    }

    async function loadDepartments() {
        if (!el.department) return;
        try {
            const res = await fetch('/api/core/v2/departments?active=true');
            const data = await res.json();
            const depts = data.data || data.departments || [];
            depts.forEach(d => {
                const opt = document.createElement('option');
                opt.value = d.id;
                opt.textContent = d.name;
                el.department.appendChild(opt);
            });
        } catch (_) { /* silencioso */ }
    }

    function initEvents() {
        const debounce = (fn) => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(fn, 350);
        };

        if (el.folio) el.folio.addEventListener('input', () => { currentPage = 1; debounce(loadCampaigns); });
        if (el.status) el.status.addEventListener('change', () => { currentPage = 1; loadCampaigns(); });
        if (el.department) el.department.addEventListener('change', () => { currentPage = 1; loadCampaigns(); });

        if (el.clear) {
            el.clear.addEventListener('click', () => {
                if (el.folio) el.folio.value = '';
                if (el.status) el.status.value = '';
                if (el.department) el.department.value = '';
                currentPage = 1;
                loadCampaigns();
            });
        }

        document.addEventListener('click', e => {
            const link = e.target.closest('[data-page]');
            if (!link) return;
            e.preventDefault();
            currentPage = parseInt(link.dataset.page, 10);
            loadCampaigns();
            window.scrollTo(0, 0);
        });
    }

    function restoreNavState() {
        const saved = HelpdeskUtils.NavState.load('campaigns_list');
        if (!saved) return;
        if (el.folio && saved.folio)        el.folio.value = saved.folio;
        if (el.status && saved.status)      el.status.value = saved.status;
        if (el.department && saved.department) el.department.value = saved.department;
        if (saved.page) currentPage = saved.page;
        if (saved.scrollY) setTimeout(() => window.scrollTo(0, saved.scrollY), 300);
    }

    function init() {
        initEvents();
        if (CAN_VIEW_ALL) loadDepartments();
        restoreNavState();
        loadCampaigns();
    }

    document.addEventListener('DOMContentLoaded', init);

})();
