// itcj2/apps/helpdesk/static/js/warehouse/movements.js

const WarehouseMovements = (function () {
    'use strict';

    const API = '/api/warehouse/v2';
    let currentPage = 1;
    let totalPages = 1;

    const TYPE_LABELS = {
        ENTRY: { label: 'Entrada', cls: 'bg-success' },
        CONSUMED: { label: 'Consumo', cls: 'bg-primary' },
        ADJUSTED_IN: { label: 'Ajuste +', cls: 'bg-info' },
        ADJUSTED_OUT: { label: 'Ajuste -', cls: 'bg-warning text-dark' },
        RETURNED: { label: 'Devolución', cls: 'bg-secondary' },
        VOIDED: { label: 'Anulado', cls: 'bg-dark' },
    };

    async function loadProducts() {
        try {
            const res = await fetch(`${API}/products?per_page=200`);
            const d = await res.json();
            const opts = (d.products || []).map(p =>
                `<option value="${p.id}">${p.code} — ${p.name}</option>`).join('');
            document.getElementById('productFilter').insertAdjacentHTML('beforeend', opts);
        } catch (e) { console.error(e); }
    }

    async function load(page) {
        page = page || currentPage;
        currentPage = page;

        const params = new URLSearchParams({ page, per_page: 30 });
        const productId = document.getElementById('productFilter').value;
        const type = document.getElementById('typeFilter').value;
        const app = document.getElementById('appFilter').value;

        if (productId) params.set('product_id', productId);
        if (type) params.set('movement_type', type);
        if (app) params.set('source_app', app);

        document.getElementById('movementsContainer').innerHTML =
            '<div class="text-center py-5"><div class="spinner-border text-primary" role="status"></div></div>';

        try {
            const res = await fetch(`${API}/movements?${params}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const d = await res.json();
            totalPages = d.pages || 1;
            renderMovements(d.movements || []);
            renderPagination(d.total || 0, d.page || 1, d.pages || 1);
        } catch (err) {
            document.getElementById('movementsContainer').innerHTML =
                '<div class="alert alert-danger m-3">Error al cargar los movimientos.</div>';
        }
    }

    function renderMovements(movements) {
        if (!movements.length) {
            document.getElementById('movementsContainer').innerHTML =
                '<div class="text-center py-5 text-muted"><i class="fas fa-exchange-alt fa-3x mb-3"></i><p>Sin movimientos.</p></div>';
            return;
        }

        const rows = movements.map(m => {
            const type = TYPE_LABELS[m.movement_type] || { label: m.movement_type, cls: 'bg-secondary' };
            const date = new Date(m.performed_at).toLocaleString('es-MX', {
                day: '2-digit', month: '2-digit', year: '2-digit',
                hour: '2-digit', minute: '2-digit'
            });
            const ticket = m.source_ticket_id
                ? `<small class="text-muted">${m.source_app} #${m.source_ticket_id}</small>`
                : '—';
            return `
                <tr>
                    <td>${date}</td>
                    <td><code class="small">${m.product_id}</code></td>
                    <td><span class="badge ${type.cls}">${type.label}</span></td>
                    <td class="text-end">${m.quantity}</td>
                    <td>${ticket}</td>
                    <td class="text-muted small">${m.notes || '—'}</td>
                </tr>`;
        }).join('');

        document.getElementById('movementsContainer').innerHTML = `
            <div class="table-responsive">
                <table class="table table-hover table-sm mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>Fecha</th><th>Producto</th><th>Tipo</th>
                            <th class="text-end">Cantidad</th><th>Origen</th><th>Notas</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>`;
    }

    function renderPagination(total, page, pages) {
        const pag = document.getElementById('pagination');
        pag.classList.remove('d-none');
        document.getElementById('paginationInfo').textContent =
            `Página ${page} de ${pages} (${total} movimientos)`;
        document.getElementById('btnPrev').disabled = page <= 1;
        document.getElementById('btnNext').disabled = page >= pages;
    }

    function prevPage() { if (currentPage > 1) load(currentPage - 1); }
    function nextPage() { if (currentPage < totalPages) load(currentPage + 1); }

    document.addEventListener('DOMContentLoaded', function () {
        loadProducts();
        load(1);
    });

    return { load, prevPage, nextPage };
})();
