// itcj2/apps/helpdesk/static/js/warehouse/dashboard.js

(function () {
    'use strict';

    const API = '/api/warehouse/v2';

    async function load() {
        try {
            const res = await fetch(`${API}/dashboard`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const d = await res.json();

            document.getElementById('kpiProducts').textContent   = d.total_products ?? '-';
            document.getElementById('kpiCategories').textContent = d.total_categories ?? '-';
            document.getElementById('kpiLowStock').textContent   = d.low_stock_count ?? '-';
            document.getElementById('kpiMovements').textContent  = d.movements_today ?? '-';
            document.getElementById('kpiEntries').textContent    = d.entries_this_month ?? '-';

            const val = parseFloat(d.total_stock_value || 0);
            document.getElementById('kpiValue').textContent = `$${val.toFixed(2)}`;

            renderLowStock(d.low_stock_products || []);
        } catch (err) {
            console.error('Dashboard error:', err);
            document.getElementById('lowStockTable').innerHTML =
                '<div class="alert alert-danger m-3">Error al cargar el dashboard.</div>';
        }
    }

    function renderLowStock(products) {
        const container = document.getElementById('lowStockTable');
        if (!products.length) {
            container.innerHTML = `
                <div class="text-center text-success py-4">
                    <i class="fas fa-check-circle fa-2x mb-2"></i>
                    <p class="mb-0">Todos los productos tienen stock suficiente.</p>
                </div>`;
            return;
        }

        const rows = products.map(p => `
            <tr>
                <td><span class="badge bg-secondary">${p.code || '-'}</span></td>
                <td>${p.name}</td>
                <td><span class="text-danger fw-bold">${p.total_stock}</span> ${p.unit_of_measure || ''}</td>
                <td>${p.restock_point}</td>
                <td><span class="badge bg-warning text-dark">${p.department_code || '-'}</span></td>
            </tr>`).join('');

        container.innerHTML = `
            <div class="table-responsive">
                <table class="table table-hover mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>Código</th><th>Producto</th><th>Stock Actual</th>
                            <th>Punto Restock</th><th>Departamento</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>`;
    }

    document.addEventListener('DOMContentLoaded', load);
})();
