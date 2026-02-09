/**
 * VisteTec - Mis Citas (Estudiante)
 */
(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1/appointments';
    const list = document.getElementById('appointmentsList');
    const emptyState = document.getElementById('emptyState');
    const loadingState = document.getElementById('loadingState');
    const filterStatus = document.getElementById('filterStatus');

    const statusLabels = {
        scheduled: 'Programada',
        attended: 'En proceso',
        completed: 'Completada',
        cancelled: 'Cancelada',
        no_show: 'No asistió',
    };

    const statusColors = {
        scheduled: 'primary',
        attended: 'info',
        completed: 'success',
        cancelled: 'danger',
        no_show: 'secondary',
    };

    let cancelModal;
    let appointmentToCancel = null;

    async function loadAppointments() {
        showLoading(true);

        const status = filterStatus.value;
        const params = new URLSearchParams();
        if (status) params.set('status', status);
        params.set('include_past', 'true');

        try {
            const res = await fetch(`${API_BASE}/my-appointments?${params}`);
            if (!res.ok) throw new Error('Error al cargar citas');
            const appointments = await res.json();

            renderAppointments(appointments);
        } catch (e) {
            console.error(e);
            list.innerHTML = '';
            showEmpty(true);
        } finally {
            showLoading(false);
        }
    }

    function renderAppointments(appointments) {
        if (!appointments.length) {
            list.innerHTML = '';
            showEmpty(true);
            return;
        }

        showEmpty(false);
        list.innerHTML = appointments.map(a => {
            const slot = a.slot || {};
            const garment = a.garment || {};
            const dateStr = slot.date ? formatDate(slot.date) : 'Sin fecha';
            const timeStr = slot.start_time && slot.end_time
                ? `${formatTime(slot.start_time)} - ${formatTime(slot.end_time)}`
                : 'Sin horario';

            const imageHtml = garment.image_path
                ? `<img src="/api/vistetec/v1/garments/image/${garment.image_path}" class="garment-thumb" alt="${garment.name}">`
                : `<div class="garment-thumb-placeholder"><i class="bi bi-image text-muted"></i></div>`;

            const canCancel = a.status === 'scheduled';
            const statusLabel = statusLabels[a.status] || a.status;
            const statusColor = statusColors[a.status] || 'secondary';

            return `
            <div class="card appointment-card status-${a.status} mb-3 border-0 shadow-sm">
                <div class="card-body p-3">
                    <div class="d-flex gap-3">
                        ${imageHtml}
                        <div class="flex-grow-1 min-width-0">
                            <div class="d-flex justify-content-between align-items-start mb-1">
                                <h6 class="fw-bold mb-0 text-truncate">${garment.name || 'Prenda'}</h6>
                                <span class="badge bg-${statusColor}-subtle text-${statusColor} ms-2">${statusLabel}</span>
                            </div>
                            <div class="text-muted small mb-2">
                                <i class="bi bi-calendar3 me-1"></i>${dateStr}
                                <span class="mx-2">|</span>
                                <i class="bi bi-clock me-1"></i>${timeStr}
                            </div>
                            <div class="d-flex gap-2 flex-wrap">
                                ${garment.size ? `<span class="badge bg-light text-dark border">${garment.size}</span>` : ''}
                                ${a.location ? `<span class="badge bg-light text-dark border"><i class="bi bi-geo-alt me-1"></i>${a.location.name}</span>` : ''}
                                <span class="badge bg-light text-dark border">${a.code}</span>
                            </div>
                        </div>
                    </div>
                    ${canCancel ? `
                    <div class="mt-3 pt-2 border-top">
                        <button class="btn btn-outline-danger btn-sm" onclick="window.showCancelModal(${a.id})">
                            <i class="bi bi-x-circle me-1"></i>Cancelar cita
                        </button>
                    </div>` : ''}
                    ${a.outcome ? `
                    <div class="mt-2 pt-2 border-top">
                        <small class="text-muted">
                            <i class="bi bi-check2-circle me-1"></i>
                            Resultado: ${getOutcomeLabel(a.outcome)}
                        </small>
                    </div>` : ''}
                </div>
            </div>`;
        }).join('');
    }

    function formatDate(dateStr) {
        const date = new Date(dateStr + 'T00:00:00');
        const options = { weekday: 'short', day: 'numeric', month: 'short' };
        return date.toLocaleDateString('es-MX', options);
    }

    function formatTime(timeStr) {
        const [h, m] = timeStr.split(':');
        const hour = parseInt(h, 10);
        const ampm = hour >= 12 ? 'PM' : 'AM';
        const hour12 = hour % 12 || 12;
        return `${hour12}:${m} ${ampm}`;
    }

    function getOutcomeLabel(outcome) {
        const labels = {
            taken: 'Te llevaste la prenda',
            not_fit: 'No fue tu talla',
            declined: 'Decidiste no llevarla',
        };
        return labels[outcome] || outcome;
    }

    function showLoading(show) {
        loadingState.classList.toggle('d-none', !show);
        if (show) {
            list.innerHTML = '';
            emptyState.classList.add('d-none');
        }
    }

    function showEmpty(show) {
        emptyState.classList.toggle('d-none', !show);
    }

    // Modal de cancelación
    window.showCancelModal = function (appointmentId) {
        appointmentToCancel = appointmentId;
        cancelModal.show();
    };

    async function cancelAppointment() {
        if (!appointmentToCancel) return;

        const btn = document.getElementById('btnConfirmCancel');
        const btnText = document.getElementById('cancelBtnText');
        const btnLoading = document.getElementById('cancelBtnLoading');

        btn.disabled = true;
        btnText.classList.add('d-none');
        btnLoading.classList.remove('d-none');

        try {
            const res = await fetch(`${API_BASE}/${appointmentToCancel}/cancel`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });

            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.error || 'Error al cancelar');
            }

            cancelModal.hide();
            VisteTecUtils.showToast('Cita cancelada correctamente', 'success');
            loadAppointments();

        } catch (e) {
            VisteTecUtils.showToast(e.message, 'danger');
        } finally {
            btn.disabled = false;
            btnText.classList.remove('d-none');
            btnLoading.classList.add('d-none');
            appointmentToCancel = null;
        }
    }

    // Event listeners
    filterStatus.addEventListener('change', loadAppointments);

    document.getElementById('btnConfirmCancel').addEventListener('click', cancelAppointment);

    // Init
    cancelModal = new bootstrap.Modal(document.getElementById('cancelModal'));
    loadAppointments();
})();
