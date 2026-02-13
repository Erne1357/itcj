(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1/reports';

    document.addEventListener('DOMContentLoaded', () => {
        loadDashboard();
        loadActivity();
    });

    // ==================== DASHBOARD SUMMARY ====================

    async function loadDashboard() {
        const loading = document.getElementById('dashboardLoading');

        try {
            const res = await fetch(`${API_BASE}/dashboard`);
            if (!res.ok) throw new Error('Error');
            const data = await res.json();

            renderKPIs(data);
            renderGarmentStatus(data.garments);
            renderAppointmentStatus(data.appointments);

            loading.classList.add('d-none');
            document.getElementById('dashboardContent').classList.remove('d-none');
        } catch (err) {
            loading.innerHTML = '<p class="text-danger">Error cargando datos del dashboard</p>';
        }
    }

    function renderKPIs(data) {
        const g = data.garments;
        const d = data.donations;
        const a = data.appointments;
        const p = data.pantry;

        document.getElementById('kpiGarments').textContent = g.total;
        document.getElementById('kpiGarmentsAvailable').textContent = `${g.available} disponibles`;
        document.getElementById('kpiDonations').textContent = d.total;
        document.getElementById('kpiDonationsRecent').textContent = `${d.recent_30d} últimos 30 días`;
        document.getElementById('kpiAppointments').textContent = a.total;
        document.getElementById('kpiAttendanceRate').textContent = `${a.attendance_rate}% asistencia`;
        document.getElementById('kpiPantryStock').textContent = p.total_stock;
        document.getElementById('kpiPantryCampaigns').textContent = `${p.active_campaigns} campañas activas`;
    }

    function renderGarmentStatus(g) {
        const container = document.getElementById('garmentStatusList');
        const statuses = [
            { label: 'Disponibles', value: g.available, color: '#198754' },
            { label: 'Reservadas', value: g.reserved, color: '#ffc107' },
            { label: 'Entregadas', value: g.delivered, color: '#0d6efd' },
            { label: 'Retiradas', value: g.withdrawn, color: '#6c757d' },
        ];

        container.innerHTML = statuses.map(s => `
            <div class="status-row">
                <span><span class="status-dot" style="background-color: ${s.color};"></span>${s.label}</span>
                <strong>${s.value}</strong>
            </div>
        `).join('');
    }

    function renderAppointmentStatus(a) {
        const container = document.getElementById('appointmentStatusList');
        const statuses = [
            { label: 'Programadas', value: a.scheduled, color: '#0d6efd' },
            { label: 'Completadas', value: a.completed, color: '#198754' },
            { label: 'No asistieron', value: a.no_show, color: '#dc3545' },
            { label: 'Canceladas', value: a.cancelled, color: '#6c757d' },
        ];

        container.innerHTML = statuses.map(s => `
            <div class="status-row">
                <span><span class="status-dot" style="background-color: ${s.color};"></span>${s.label}</span>
                <strong>${s.value}</strong>
            </div>
        `).join('');

        // Outcomes
        const outcomesContainer = document.getElementById('outcomesSection');
        if (a.outcomes) {
            const taken = a.outcomes.taken || 0;
            const notFit = a.outcomes.not_fit || 0;
            const declined = a.outcomes.declined || 0;
            const total = taken + notFit + declined;

            if (total > 0) {
                const successRate = Math.round(taken / total * 100);
                outcomesContainer.innerHTML = `
                    <div class="mt-3 pt-3 border-top">
                        <small class="text-muted d-block mb-2">Resultados de citas completadas</small>
                        <div class="d-flex gap-3">
                            <span class="small"><strong>${taken}</strong> se llevaron</span>
                            <span class="small"><strong>${notFit}</strong> no les quedó</span>
                            <span class="small"><strong>${declined}</strong> declinaron</span>
                        </div>
                        <div class="small text-muted mt-1">Tasa de éxito: <strong>${successRate}%</strong></div>
                    </div>
                `;
            }
        }
    }

    // ==================== ACTIVITY ====================

    async function loadActivity() {
        const container = document.getElementById('activityList');

        try {
            const res = await fetch(`${API_BASE}/activity?limit=10`);
            if (!res.ok) throw new Error('Error');
            const activities = await res.json();

            if (activities.length === 0) {
                container.innerHTML = '<p class="text-muted text-center py-3">Sin actividad reciente</p>';
                return;
            }

            container.innerHTML = activities.map(a => `
                <div class="activity-item">
                    <div class="activity-icon" style="background-color: ${a.color}20; color: ${a.color};">
                        <i class="bi ${a.icon}"></i>
                    </div>
                    <div>
                        <div class="activity-text">${escapeHtml(a.message)}</div>
                        <div class="activity-date">${formatDate(a.date)}</div>
                    </div>
                </div>
            `).join('');
        } catch (err) {
            container.innerHTML = '<p class="text-muted text-center py-3">Error cargando actividad</p>';
        }
    }

    // ==================== UTILS ====================

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function formatDate(isoStr) {
        if (!isoStr) return '';
        const d = new Date(isoStr);
        const now = new Date();
        const diff = now - d;
        const mins = Math.floor(diff / 60000);
        const hours = Math.floor(diff / 3600000);
        const days = Math.floor(diff / 86400000);

        if (mins < 60) return `Hace ${mins} min`;
        if (hours < 24) return `Hace ${hours}h`;
        if (days < 7) return `Hace ${days}d`;
        return d.toLocaleDateString('es-MX', { day: 'numeric', month: 'short' });
    }
})();
