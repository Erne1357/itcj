(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1/garments';
    const STATUSES = {
        available: { label: 'Disponible', class: 'status-available' },
        reserved: { label: 'Reservada', class: 'status-reserved' },
        delivered: { label: 'Entregada', class: 'status-delivered' },
        withdrawn: { label: 'Retirada', class: 'status-withdrawn' },
    };
    const CONDITIONS = {
        nuevo: 'Nuevo',
        como_nuevo: 'Como nuevo',
        buen_estado: 'Buen estado',
        usado: 'Usado',
    };

    let currentPage = 1;
    let currentStatus = '';
    let currentCategory = '';
    let currentSearch = '';
    let totalPages = 1;

    document.addEventListener('DOMContentLoaded', () => {
        loadGarments();
        bindFilters();
    });

    // ==================== FILTERS ====================

    function bindFilters() {
        document.getElementById('filterStatus').addEventListener('change', function () {
            currentStatus = this.value;
            currentPage = 1;
            loadGarments();
        });

        document.getElementById('filterCategory').addEventListener('change', function () {
            currentCategory = this.value;
            currentPage = 1;
            loadGarments();
        });

        let searchTimeout;
        document.getElementById('filterSearch').addEventListener('input', function () {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                currentSearch = this.value.trim();
                currentPage = 1;
                loadGarments();
            }, 400);
        });

        // Status pills
        document.querySelectorAll('.stat-pill[data-status]').forEach(pill => {
            pill.addEventListener('click', () => {
                const status = pill.dataset.status;
                currentStatus = currentStatus === status ? '' : status;
                document.getElementById('filterStatus').value = currentStatus;
                document.querySelectorAll('.stat-pill').forEach(p => p.classList.remove('active'));
                if (currentStatus) pill.classList.add('active');
                currentPage = 1;
                loadGarments();
            });
        });
    }

    // ==================== LOAD DATA ====================

    async function loadGarments() {
        const tbody = document.getElementById('garmentsBody');
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4"><div class="spinner-border spinner-border-sm text-muted"></div></td></tr>';

        const params = new URLSearchParams({ page: currentPage, per_page: 20 });
        if (currentStatus) params.append('status', currentStatus);
        if (currentCategory) params.append('category', currentCategory);
        if (currentSearch) params.append('search', currentSearch);

        try {
            const res = await fetch(`${API_BASE}?${params}`);
            if (!res.ok) throw new Error('Error cargando prendas');
            const data = await res.json();

            totalPages = data.pages || 1;
            renderGarments(data.items);
            renderPagination(data);
            updateStatCounts(data);
        } catch (err) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-danger">Error cargando prendas</td></tr>';
        }
    }

    function renderGarments(items) {
        const tbody = document.getElementById('garmentsBody');

        if (!items || items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-muted">No se encontraron prendas</td></tr>';
            return;
        }

        tbody.innerHTML = items.map(g => {
            const statusInfo = STATUSES[g.status] || { label: g.status, class: '' };
            const condLabel = CONDITIONS[g.condition] || g.condition;
            const imgHtml = g.image_path
                ? `<img src="/api/vistetec/v1/garments/image/${escapeAttr(g.image_path)}" class="garment-thumb" alt="">`
                : '<div class="garment-thumb-placeholder"><i class="bi bi-image"></i></div>';

            return `
                <tr>
                    <td>${imgHtml}</td>
                    <td>
                        <div class="fw-semibold">${escapeHtml(g.name)}</div>
                        <span class="garment-code">${escapeHtml(g.code)}</span>
                    </td>
                    <td>${escapeHtml(g.category || '-')}</td>
                    <td>${escapeHtml(g.size || '-')}</td>
                    <td><span class="condition-badge">${escapeHtml(condLabel)}</span></td>
                    <td><span class="status-badge ${statusInfo.class}">${statusInfo.label}</span></td>
                    <td>
                        <div class="dropdown">
                            <button class="btn btn-sm btn-outline-secondary dropdown-toggle" data-bs-toggle="dropdown">
                                <i class="bi bi-three-dots"></i>
                            </button>
                            <ul class="dropdown-menu dropdown-menu-end">
                                ${g.status === 'available' ? `<li><a class="dropdown-item" href="#" onclick="GarmentAdmin.withdraw(${g.id}); return false;"><i class="bi bi-box-arrow-right me-2"></i>Retirar</a></li>` : ''}
                                <li><a class="dropdown-item text-danger" href="#" onclick="GarmentAdmin.remove(${g.id}, '${escapeAttr(g.name)}'); return false;"><i class="bi bi-trash me-2"></i>Eliminar</a></li>
                            </ul>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
    }

    function updateStatCounts(data) {
        document.getElementById('totalCount').textContent = data.total || 0;
    }

    function renderPagination(data) {
        const container = document.getElementById('pagination');
        if (!data.pages || data.pages <= 1) {
            container.innerHTML = '';
            return;
        }

        let html = '<nav><ul class="pagination pagination-sm justify-content-center mb-0">';
        html += `<li class="page-item ${!data.has_prev ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="GarmentAdmin.goPage(${currentPage - 1}); return false;">&laquo;</a></li>`;

        for (let i = 1; i <= data.pages; i++) {
            if (data.pages > 7 && Math.abs(i - currentPage) > 2 && i !== 1 && i !== data.pages) {
                if (i === 2 || i === data.pages - 1) html += '<li class="page-item disabled"><span class="page-link">...</span></li>';
                continue;
            }
            html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#" onclick="GarmentAdmin.goPage(${i}); return false;">${i}</a></li>`;
        }

        html += `<li class="page-item ${!data.has_next ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="GarmentAdmin.goPage(${currentPage + 1}); return false;">&raquo;</a></li>`;
        html += '</ul></nav>';
        container.innerHTML = html;
    }

    // ==================== ACTIONS ====================

    async function withdrawGarment(id) {
        const ok = await VisteTecUtils.confirmModal('¿Retirar esta prenda del catálogo?', 'Retirar');
        if (!ok) return;

        try {
            const res = await fetch(`${API_BASE}/${id}/withdraw`, { method: 'POST' });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.error || 'Error');
            }
            VisteTecUtils.showToast('Prenda retirada', 'success');
            loadGarments();
        } catch (err) {
            VisteTecUtils.showToast(err.message, 'danger');
        }
    }

    async function deleteGarment(id, name) {
        const ok = await VisteTecUtils.confirmModal(`¿Eliminar permanentemente "${name}"?`, 'Eliminar');
        if (!ok) return;

        try {
            const res = await fetch(`${API_BASE}/${id}`, { method: 'DELETE' });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.error || 'Error');
            }
            VisteTecUtils.showToast('Prenda eliminada', 'success');
            loadGarments();
        } catch (err) {
            VisteTecUtils.showToast(err.message, 'danger');
        }
    }

    // ==================== UTILS ====================

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function escapeAttr(str) {
        if (!str) return '';
        return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
    }

    // Public API
    window.GarmentAdmin = {
        withdraw: withdrawGarment,
        remove: deleteGarment,
        goPage: function (page) {
            if (page < 1 || page > totalPages) return;
            currentPage = page;
            loadGarments();
        },
    };
})();
