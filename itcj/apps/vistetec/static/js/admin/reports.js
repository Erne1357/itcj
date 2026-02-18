(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1/reports';
    const MONTH_NAMES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];

    let dateFrom = '';
    let dateTo = '';

    document.addEventListener('DOMContentLoaded', () => {
        bindFilters();
        loadAllReports();
    });

    function bindFilters() {
        document.getElementById('dateFrom').addEventListener('change', function () {
            dateFrom = this.value;
        });
        document.getElementById('dateTo').addEventListener('change', function () {
            dateTo = this.value;
        });
        document.getElementById('btnApplyFilter').addEventListener('click', loadAllReports);
        document.getElementById('btnClearFilter').addEventListener('click', () => {
            dateFrom = '';
            dateTo = '';
            document.getElementById('dateFrom').value = '';
            document.getElementById('dateTo').value = '';
            loadAllReports();
        });
    }

    async function loadAllReports() {
        const params = new URLSearchParams();
        if (dateFrom) params.append('date_from', dateFrom);
        if (dateTo) params.append('date_to', dateTo);
        const qs = params.toString() ? '?' + params.toString() : '';

        // Load all three reports in parallel
        await Promise.all([
            loadGarmentReport(qs),
            loadDonationReport(qs),
            loadAppointmentReport(qs),
        ]);
    }

    // ==================== GARMENT REPORT ====================

    async function loadGarmentReport(qs) {
        const container = document.getElementById('garmentReport');
        container.innerHTML = '<div class="text-center py-3"><div class="spinner-border spinner-border-sm text-muted"></div></div>';

        try {
            const res = await fetch(`${API_BASE}/garments${qs}`);
            if (!res.ok) throw new Error('Error');
            const data = await res.json();

            let html = '';

            // Stats row
            const status = data.by_status || {};
            html += `
                <div class="row g-2 mb-3">
                    <div class="col-3 report-stat">
                        <div class="stat-value" style="color: #198754;">${status.available || 0}</div>
                        <div class="stat-label">Disponibles</div>
                    </div>
                    <div class="col-3 report-stat">
                        <div class="stat-value" style="color: #ffc107;">${status.reserved || 0}</div>
                        <div class="stat-label">Reservadas</div>
                    </div>
                    <div class="col-3 report-stat">
                        <div class="stat-value" style="color: #0d6efd;">${status.delivered || 0}</div>
                        <div class="stat-label">Entregadas</div>
                    </div>
                    <div class="col-3 report-stat">
                        <div class="stat-value" style="color: #6c757d;">${status.withdrawn || 0}</div>
                        <div class="stat-label">Retiradas</div>
                    </div>
                </div>
            `;

            // Category breakdown
            if (data.by_category && data.by_category.length > 0) {
                html += '<h6 class="fw-bold mb-2 small">Por categoría</h6>';
                const maxCat = Math.max(...data.by_category.map(c => c.count));
                html += data.by_category.map(c => `
                    <div class="breakdown-row">
                        <span class="small" style="min-width: 80px;">${escapeHtml(c.category)}</span>
                        <div class="breakdown-bar">
                            <div class="breakdown-bar-fill" style="width: ${maxCat ? (c.count / maxCat * 100) : 0}%; background-color: #8B1538;"></div>
                        </div>
                        <strong class="small">${c.count}</strong>
                    </div>
                `).join('');
            }

            // Condition breakdown
            if (data.by_condition && data.by_condition.length > 0) {
                html += '<h6 class="fw-bold mb-2 mt-3 small">Por condición</h6>';
                const condLabels = { nuevo: 'Nuevo', como_nuevo: 'Como nuevo', buen_estado: 'Buen estado', usado: 'Usado' };
                const maxCond = Math.max(...data.by_condition.map(c => c.count));
                html += data.by_condition.map(c => `
                    <div class="breakdown-row">
                        <span class="small" style="min-width: 80px;">${escapeHtml(condLabels[c.condition] || c.condition)}</span>
                        <div class="breakdown-bar">
                            <div class="breakdown-bar-fill" style="width: ${maxCond ? (c.count / maxCond * 100) : 0}%; background-color: #6f42c1;"></div>
                        </div>
                        <strong class="small">${c.count}</strong>
                    </div>
                `).join('');
            }

            container.innerHTML = html;
        } catch (err) {
            container.innerHTML = '<p class="text-danger small text-center">Error cargando reporte de prendas</p>';
        }
    }

    // ==================== DONATION REPORT ====================

    async function loadDonationReport(qs) {
        const container = document.getElementById('donationReport');
        container.innerHTML = '<div class="text-center py-3"><div class="spinner-border spinner-border-sm text-muted"></div></div>';

        try {
            const res = await fetch(`${API_BASE}/donations${qs}`);
            if (!res.ok) throw new Error('Error');
            const data = await res.json();

            let html = '';

            // Stats
            const byType = data.by_type || {};
            html += `
                <div class="row g-2 mb-3">
                    <div class="col-4 report-stat">
                        <div class="stat-value" style="color: #8B1538;">${data.total}</div>
                        <div class="stat-label">Total</div>
                    </div>
                    <div class="col-4 report-stat">
                        <div class="stat-value" style="color: #dc3545;">${byType.garment || 0}</div>
                        <div class="stat-label">Ropa</div>
                    </div>
                    <div class="col-4 report-stat">
                        <div class="stat-value" style="color: #0d6efd;">${byType.pantry || 0}</div>
                        <div class="stat-label">Despensa</div>
                    </div>
                </div>
            `;

            // Monthly chart
            if (data.monthly && data.monthly.length > 0) {
                html += '<h6 class="fw-bold mb-2 small">Donaciones por mes</h6>';
                const maxMonth = Math.max(...data.monthly.map(m => m.count));
                html += '<div class="chart-bar">';
                html += data.monthly.map(m => {
                    const pct = maxMonth ? (m.count / maxMonth * 100) : 0;
                    return `
                        <div class="chart-bar-item">
                            <span class="chart-bar-value">${m.count}</span>
                            <div class="chart-bar-fill" style="height: ${Math.max(pct, 4)}%; background-color: #dc3545;"></div>
                            <span class="chart-bar-label">${MONTH_NAMES[m.month - 1]}</span>
                        </div>
                    `;
                }).join('');
                html += '</div>';
            }

            // Top pantry items
            if (data.top_pantry_items && data.top_pantry_items.length > 0) {
                html += '<h6 class="fw-bold mb-2 mt-3 small">Top artículos de despensa</h6>';
                const maxPantry = Math.max(...data.top_pantry_items.map(i => i.total_quantity));
                html += data.top_pantry_items.map(i => `
                    <div class="breakdown-row">
                        <span class="small" style="min-width: 100px;">${escapeHtml(i.item_name)}</span>
                        <div class="breakdown-bar">
                            <div class="breakdown-bar-fill" style="width: ${maxPantry ? (i.total_quantity / maxPantry * 100) : 0}%; background-color: #0d6efd;"></div>
                        </div>
                        <strong class="small">${i.total_quantity}</strong>
                    </div>
                `).join('');
            }

            container.innerHTML = html;
        } catch (err) {
            container.innerHTML = '<p class="text-danger small text-center">Error cargando reporte de donaciones</p>';
        }
    }

    // ==================== APPOINTMENT REPORT ====================

    async function loadAppointmentReport(qs) {
        const container = document.getElementById('appointmentReport');
        container.innerHTML = '<div class="text-center py-3"><div class="spinner-border spinner-border-sm text-muted"></div></div>';

        try {
            const res = await fetch(`${API_BASE}/appointments${qs}`);
            if (!res.ok) throw new Error('Error');
            const data = await res.json();

            let html = '';

            // Stats
            const status = data.by_status || {};
            html += `
                <div class="row g-2 mb-3">
                    <div class="col-3 report-stat">
                        <div class="stat-value" style="color: #8B1538;">${data.total}</div>
                        <div class="stat-label">Total</div>
                    </div>
                    <div class="col-3 report-stat">
                        <div class="stat-value" style="color: #198754;">${status.completed || 0}</div>
                        <div class="stat-label">Completadas</div>
                    </div>
                    <div class="col-3 report-stat">
                        <div class="stat-value" style="color: #dc3545;">${status.no_show || 0}</div>
                        <div class="stat-label">No asistieron</div>
                    </div>
                    <div class="col-3 report-stat">
                        <div class="stat-value" style="color: #0d6efd;">${data.attendance_rate}%</div>
                        <div class="stat-label">Asistencia</div>
                    </div>
                </div>
            `;

            // Outcomes breakdown
            const outcomes = data.by_outcome || {};
            const taken = outcomes.taken || 0;
            const notFit = outcomes.not_fit || 0;
            const declined = outcomes.declined || 0;
            const totalOutcomes = taken + notFit + declined;

            if (totalOutcomes > 0) {
                html += '<h6 class="fw-bold mb-2 small">Resultados de citas</h6>';
                const items = [
                    { label: 'Se la llevaron', value: taken, color: '#198754' },
                    { label: 'No les quedó', value: notFit, color: '#ffc107' },
                    { label: 'Declinaron', value: declined, color: '#dc3545' },
                ];
                html += items.map(i => `
                    <div class="breakdown-row">
                        <span class="small" style="min-width: 110px;">${i.label}</span>
                        <div class="breakdown-bar">
                            <div class="breakdown-bar-fill" style="width: ${(i.value / totalOutcomes * 100)}%; background-color: ${i.color};"></div>
                        </div>
                        <strong class="small">${i.value}</strong>
                    </div>
                `).join('');
            }

            // Monthly chart
            if (data.monthly && data.monthly.length > 0) {
                html += '<h6 class="fw-bold mb-2 mt-3 small">Citas por mes</h6>';
                const maxMonth = Math.max(...data.monthly.map(m => m.count));
                html += '<div class="chart-bar">';
                html += data.monthly.map(m => {
                    const pct = maxMonth ? (m.count / maxMonth * 100) : 0;
                    return `
                        <div class="chart-bar-item">
                            <span class="chart-bar-value">${m.count}</span>
                            <div class="chart-bar-fill" style="height: ${Math.max(pct, 4)}%; background-color: #198754;"></div>
                            <span class="chart-bar-label">${MONTH_NAMES[m.month - 1]}</span>
                        </div>
                    `;
                }).join('');
                html += '</div>';
            }

            container.innerHTML = html;
        } catch (err) {
            container.innerHTML = '<p class="text-danger small text-center">Error cargando reporte de citas</p>';
        }
    }

    // ==================== UTILS ====================

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
})();
