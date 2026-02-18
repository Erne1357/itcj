/**
 * VisteTec - Volunteer Dashboard Stats
 */
(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', async () => {
        // Cargar stats de catalogo
        try {
            const res = await fetch('/api/vistetec/v1/catalog/stats');
            if (res.ok) {
                const data = await res.json();
                document.getElementById('statAvailable').textContent = data.available || 0;
                document.getElementById('statDelivered').textContent = data.delivered || 0;
                document.getElementById('statTotal').textContent = data.total_registered || 0;
            }
        } catch (e) {
            console.error('Error cargando stats catalogo:', e);
        }

        // Cargar stats de citas
        try {
            const res = await fetch('/api/vistetec/v1/appointments/stats');
            if (res.ok) {
                const data = await res.json();
                document.getElementById('statAppointments').textContent = data.today || 0;
            }
        } catch (e) {
            console.error('Error cargando stats citas:', e);
            document.getElementById('statAppointments').textContent = '0';
        }
    });

})();
