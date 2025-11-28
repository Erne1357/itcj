/**
 * Dashboard de Inventario
 * Carga estadísticas, alertas y gráficas
 */

let categoryChart = null;
let statusChart = null;

document.addEventListener('DOMContentLoaded', function() {
    loadQuickStats();
    loadAlerts();
    loadCategoryChart();
    loadStatusChart();
    loadRecentActivity();
});

// ==================== STATS RÁPIDAS ====================
async function loadQuickStats() {
    try {
        const response = await fetch('/api/help-desk/v1/inventory/dashboard/widgets/quick-stats', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar estadísticas');

        const result = await response.json();
        const stats = result.data;

        document.getElementById('stat-total').textContent = stats.total_items || 0;
        document.getElementById('stat-active').textContent = stats.active || 0;
        document.getElementById('stat-maintenance').textContent = stats.in_maintenance || 0;
        document.getElementById('stat-assigned').textContent = stats.assigned_to_users || 0;

    } catch (error) {
        console.error('Error cargando stats:', error);
        showError('No se pudieron cargar las estadísticas');
    }
}

// ==================== ALERTAS ====================
async function loadAlerts() {
    try {
        const response = await fetch('/api/help-desk/v1/inventory/dashboard/widgets/alerts', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar alertas');

        const result = await response.json();
        const alerts = result.data;

        const container = document.getElementById('alerts-container');
        const countBadge = document.getElementById('alerts-count');

        countBadge.textContent = alerts.length;

        if (alerts.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-4">
                    <i class="fas fa-check-circle fa-3x text-success mb-3"></i>
                    <p>No hay alertas pendientes</p>
                </div>
            `;
            return;
        }

        container.innerHTML = alerts.map(alert => `
            <div class="alert alert-${alert.type} alert-dismissible fade show" role="alert">
                <i class="${alert.icon} mr-2"></i>
                <strong>${alert.title}</strong><br>
                <small>${alert.message}</small>
                ${alert.action ? `<br><a href="${alert.action}" class="alert-link">Ver detalles →</a>` : ''}
                <button type="button" class="close" data-dismiss="alert">
                    <span>&times;</span>
                </button>
            </div>
        `).join('');

    } catch (error) {
        console.error('Error cargando alertas:', error);
    }
}

// ==================== GRÁFICA POR CATEGORÍA ====================
async function loadCategoryChart() {
    try {
        const response = await fetch('/api/help-desk/v1/inventory/dashboard/widgets/category-chart', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar gráfica');

        const result = await response.json();
        const chartData = result.data;

        const ctx = document.getElementById('categoryChart').getContext('2d');
        
        if (categoryChart) categoryChart.destroy();

        categoryChart = new Chart(ctx, {
            type: 'pie',
            data: chartData,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            boxWidth: 12,
                            padding: 10,
                            font: { size: 11 }
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const value = context.parsed || 0;
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((value / total) * 100).toFixed(1);
                                return `${label}: ${value} (${percentage}%)`;
                            }
                        }
                    }
                }
            }
        });

    } catch (error) {
        console.error('Error cargando gráfica de categorías:', error);
    }
}

// ==================== GRÁFICA POR ESTADO ====================
async function loadStatusChart() {
    try {
        const response = await fetch('/api/help-desk/v1/inventory/dashboard/widgets/status-chart', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar gráfica');

        const result = await response.json();
        const chartData = result.data;

        const ctx = document.getElementById('statusChart').getContext('2d');
        
        if (statusChart) statusChart.destroy();

        statusChart = new Chart(ctx, {
            type: 'doughnut',
            data: chartData,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            boxWidth: 12,
                            padding: 10,
                            font: { size: 11 }
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const value = context.parsed || 0;
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((value / total) * 100).toFixed(1);
                                return `${label}: ${value} (${percentage}%)`;
                            }
                        }
                    }
                }
            }
        });

    } catch (error) {
        console.error('Error cargando gráfica de estados:', error);
    }
}

// ==================== ACTIVIDAD RECIENTE ====================
async function loadRecentActivity() {
    try {
        const response = await fetch('/api/help-desk/v1/inventory/dashboard/widgets/recent-activity?limit=10', {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
        });

        if (!response.ok) throw new Error('Error al cargar actividad');

        const result = await response.json();
        const activities = result.data;

        const tbody = document.querySelector('#recent-activity-table tbody');

        if (activities.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="text-center text-muted py-4">
                        No hay actividad reciente
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = activities.map(activity => {
            const date = new Date(activity.timestamp);
            const dateStr = date.toLocaleDateString('es-MX', { 
                day: '2-digit', 
                month: 'short', 
                hour: '2-digit', 
                minute: '2-digit' 
            });

            const eventBadge = getEventBadge(activity.event_type);

            return `
                <tr>
                    <td class="text-nowrap">
                        <small class="text-muted">${dateStr}</small>
                    </td>
                    <td>
                        <span class="badge badge-${eventBadge.color}">
                            ${activity.event_description}
                        </span>
                    </td>
                    <td>
                        <a href="/help-desk/inventory/items/${activity.item.id}">
                            ${activity.item.display_name}
                        </a>
                    </td>
                    <td>
                        <small>${activity.performed_by.full_name}</small>
                    </td>
                    <td>
                        <small class="text-muted">${activity.notes || '-'}</small>
                    </td>
                </tr>
            `;
        }).join('');

    } catch (error) {
        console.error('Error cargando actividad:', error);
    }
}

// ==================== HELPERS ====================
function getEventBadge(eventType) {
    const badges = {
        'REGISTERED': { color: 'success' },
        'ASSIGNED_TO_USER': { color: 'info' },
        'REASSIGNED': { color: 'warning' },
        'UNASSIGNED': { color: 'secondary' },
        'STATUS_CHANGED': { color: 'primary' },
        'MAINTENANCE_COMPLETED': { color: 'success' },
        'DEACTIVATED': { color: 'danger' },
        'TRANSFERRED': { color: 'info' }
    };
    return badges[eventType] || { color: 'secondary' };
}

function showError(message) {
    // Implementar notificación de error (toastr, sweetalert, etc.)
    showToast(message, 'error');
}