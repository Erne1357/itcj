// itcj2/apps/helpdesk/static/js/admin/home.js

// Load global stats via dedicated endpoint
document.addEventListener('DOMContentLoaded', async () => {
    try {
        const response = await HelpdeskUtils.api.getGlobalStats();
        const stats = response.data;

        // Total tickets
        document.getElementById('totalTickets').textContent = stats.total || 0;

        // Pending tickets
        const pending = (stats.by_status?.PENDING || 0) + (stats.by_status?.ASSIGNED || 0);
        document.getElementById('pendingTickets').textContent = pending;

        // Rated count
        document.getElementById('activeUsers').textContent = stats.rated_count || 0;

        // Satisfaction (avg_rating_attention is 1-5 scale)
        if (stats.avg_rating_attention) {
            document.getElementById('avgRating').textContent =
                `${stats.avg_rating_attention.toFixed(1)}/5`;
        } else {
            document.getElementById('avgRating').textContent = '-';
        }
    } catch (error) {
        console.error('Error loading stats:', error);
    }
});
