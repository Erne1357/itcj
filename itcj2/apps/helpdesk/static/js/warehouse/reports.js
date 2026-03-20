// itcj2/apps/helpdesk/static/js/warehouse/reports.js

const WarehouseReports = (function () {
    'use strict';

    const API = '/api/warehouse/v2';

    function today() { return new Date().toISOString().split('T')[0]; }
    function daysAgo(n) {
        const d = new Date();
        d.setDate(d.getDate() - n);
        return d.toISOString().split('T')[0];
    }

    async function loadValuation() {
        document.getElementById('valuationContainer').innerHTML =
            '<div class="text-center py-5"><div class="spinner-border text-primary" role="status"></div></div>';
        try {
            const res = await fetch(`${API}/reports/stock-valuation`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const d = await res.json();
            renderValuation(d);
        } catch (err) {
            document.getElementById('valuationContainer').innerHTML =
                '<div class="alert alert-danger m-3">Error al cargar la valoración.</div>';
        }
    }

    function renderValuation(d) {
        const total = parseFloat(d.grand_total_value || 0);
        const rows = (d.products || []).map(p => `
            <tr>
                <td><code>${p.code}</code></td>
                <td>${p.name}</td>
                <td>${p.category_name || '—'}</td>
                <td>${p.total_stock} ${p.unit_of_measure}</td>
                <td class="text-end fw-bold">$${parseFloat(p.total_value || 0).toFixed(2)}</td>
            </tr>`).join('');

        document.getElementById('valuationContainer').innerHTML = `
            <div class="alert alert-success d-flex justify-content-between align-items-center mb-3">
                <span><i class="fas fa-dollar-sign me-2"></i>Valor total del inventario</span>
                <strong class="fs-5">$${total.toFixed(2)}</strong>
            </div>
            <div class="card border-0 shadow-sm">
                <div class="card-body p-0">
                    <div class="table-responsive">
                        <table class="table table-hover mb-0">
                            <thead class="table-light">
                                <tr>
                                    <th>Código</th><th>Producto</th><th>Categoría</th>
                                    <th>Stock</th><th class="text-end">Valor</th>
                                </tr>
                            </thead>
                            <tbody>${rows || '<tr><td colspan="5" class="text-center text-muted py-4">Sin datos</td></tr>'}</tbody>
                        </table>
                    </div>
                </div>
            </div>`;
    }

    async function loadConsumption() {
        const from = document.getElementById('conFromDate').value;
        const to = document.getElementById('conToDate').value;
        const params = new URLSearchParams();
        if (from) params.set('date_from', from);
        if (to) params.set('date_to', to);

        document.getElementById('consumptionContainer').innerHTML =
            '<div class="text-center py-5"><div class="spinner-border text-primary" role="status"></div></div>';

        try {
            const res = await fetch(`${API}/reports/consumption?${params}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const d = await res.json();
            const rows = (d.products || []).map(p => `
                <tr>
                    <td><code>${p.code}</code></td>
                    <td>${p.name}</td>
                    <td>${p.category_name || '—'}</td>
                    <td class="text-end fw-bold text-danger">${p.total_consumed} ${p.unit_of_measure}</td>
                    <td class="text-end">${p.movement_count}</td>
                </tr>`).join('');

            document.getElementById('consumptionContainer').innerHTML = `
                <div class="text-muted small mb-2">
                    Período: <strong>${d.date_from}</strong> a <strong>${d.date_to}</strong>
                    — ${d.total_products_with_consumption} productos con consumo
                </div>
                <div class="card border-0 shadow-sm">
                    <div class="card-body p-0">
                        <div class="table-responsive">
                            <table class="table table-hover mb-0">
                                <thead class="table-light">
                                    <tr>
                                        <th>Código</th><th>Producto</th><th>Categoría</th>
                                        <th class="text-end">Total Consumido</th><th class="text-end">Movimientos</th>
                                    </tr>
                                </thead>
                                <tbody>${rows || '<tr><td colspan="5" class="text-center text-muted py-4">Sin consumo en el período</td></tr>'}</tbody>
                            </table>
                        </div>
                    </div>
                </div>`;
        } catch (err) {
            document.getElementById('consumptionContainer').innerHTML =
                '<div class="alert alert-danger m-3">Error al cargar el reporte.</div>';
        }
    }

    async function loadMovements() {
        const from = document.getElementById('movFromDate').value;
        const to = document.getElementById('movToDate').value;
        const type = document.getElementById('movTypeFilter').value;
        const params = new URLSearchParams();
        if (from) params.set('date_from', from);
        if (to) params.set('date_to', to);
        if (type) params.set('movement_type', type);

        document.getElementById('movementsReportContainer').innerHTML =
            '<div class="text-center py-5"><div class="spinner-border text-primary" role="status"></div></div>';

        try {
            const res = await fetch(`${API}/reports/movements?${params}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const d = await res.json();

            const summaryItems = Object.entries(d.summary_by_type || {}).map(([type, s]) =>
                `<span class="badge bg-primary me-2">${type}: ${s.count} movs (${s.total_quantity} u.)</span>`
            ).join('');

            const rows = (d.movements || []).map(m => `
                <tr>
                    <td><small>${new Date(m.performed_at).toLocaleString('es-MX')}</small></td>
                    <td><code class="small">${m.product_id}</code></td>
                    <td><span class="badge bg-secondary">${m.movement_type}</span></td>
                    <td class="text-end">${m.quantity}</td>
                    <td>${m.source_app ? `${m.source_app} #${m.source_ticket_id}` : '—'}</td>
                </tr>`).join('');

            document.getElementById('movementsReportContainer').innerHTML = `
                <div class="mb-3">${summaryItems || '<span class="text-muted">Sin movimientos</span>'}</div>
                <p class="text-muted small">Total: ${d.total_movements} movimientos | ${d.date_from} → ${d.date_to}</p>
                <div class="card border-0 shadow-sm">
                    <div class="card-body p-0">
                        <div class="table-responsive">
                            <table class="table table-hover table-sm mb-0">
                                <thead class="table-light">
                                    <tr>
                                        <th>Fecha</th><th>Producto</th><th>Tipo</th>
                                        <th class="text-end">Cantidad</th><th>Origen</th>
                                    </tr>
                                </thead>
                                <tbody>${rows || '<tr><td colspan="5" class="text-center text-muted py-4">Sin movimientos</td></tr>'}</tbody>
                            </table>
                        </div>
                    </div>
                </div>`;
        } catch (err) {
            document.getElementById('movementsReportContainer').innerHTML =
                '<div class="alert alert-danger m-3">Error al cargar el reporte.</div>';
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        const t = today();
        const ago30 = daysAgo(30);
        document.getElementById('conFromDate').value = ago30;
        document.getElementById('conToDate').value = t;
        document.getElementById('movFromDate').value = ago30;
        document.getElementById('movToDate').value = t;
        loadValuation();
    });

    return { loadValuation, loadConsumption, loadMovements };
})();
