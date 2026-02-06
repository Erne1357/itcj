/**
 * VisteTec - Gestión de Citas (Voluntario)
 */
(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1';

    // DOM Elements - Today
    const todayList = document.getElementById('todayList');
    const todayEmpty = document.getElementById('todayEmpty');
    const todayLoading = document.getElementById('todayLoading');
    const todayCount = document.getElementById('todayCount');

    // DOM Elements - Slots
    const slotsList = document.getElementById('slotsList');
    const slotsEmpty = document.getElementById('slotsEmpty');
    const slotsLoading = document.getElementById('slotsLoading');

    // Modals
    let slotModal, attendModal;

    // State
    let currentAppointment = null;

    const statusLabels = {
        scheduled: 'Programada',
        attended: 'En proceso',
        completed: 'Completada',
        no_show: 'No asistió',
    };

    // ==================== Today's Appointments ====================

    async function loadTodayAppointments() {
        todayLoading.classList.remove('d-none');
        todayList.innerHTML = '';
        todayEmpty.classList.add('d-none');

        try {
            const res = await fetch(`${API_BASE}/appointments/volunteer/today`);
            if (!res.ok) throw new Error('Error al cargar citas');
            const appointments = await res.json();

            todayLoading.classList.add('d-none');
            todayCount.textContent = appointments.length;

            if (!appointments.length) {
                todayEmpty.classList.remove('d-none');
                return;
            }

            renderTodayAppointments(appointments);

        } catch (e) {
            console.error(e);
            todayLoading.classList.add('d-none');
            todayEmpty.classList.remove('d-none');
        }
    }

    function renderTodayAppointments(appointments) {
        todayList.innerHTML = appointments.map(a => {
            const slot = a.slot || {};
            const garment = a.garment || {};
            const student = a.student || {};
            const timeStr = slot.start_time && slot.end_time
                ? `${formatTime(slot.start_time)} - ${formatTime(slot.end_time)}`
                : '';

            const imageHtml = garment.image_path
                ? `<img src="${API_BASE}/garments/image/${garment.image_path}" class="garment-mini" alt="${garment.name}">`
                : `<div class="garment-mini-placeholder"><i class="bi bi-image text-muted"></i></div>`;

            const statusLabel = statusLabels[a.status] || a.status;
            const canAttend = a.status === 'scheduled';
            const canComplete = a.status === 'attended';

            let actionBtn = '';
            if (canAttend) {
                actionBtn = `<button class="btn btn-sm" style="background-color: #8B1538; color: white;" onclick="window.openAttendModal(${a.id})">
                    <i class="bi bi-person-check me-1"></i>Atender
                </button>`;
            } else if (canComplete) {
                actionBtn = `<button class="btn btn-sm btn-outline-success" onclick="window.openAttendModal(${a.id})">
                    <i class="bi bi-check2-circle me-1"></i>Completar
                </button>`;
            }

            return `
            <div class="card appointment-item status-${a.status} mb-3 border-0 shadow-sm">
                <div class="card-body p-3">
                    <div class="d-flex gap-3 align-items-start">
                        ${imageHtml}
                        <div class="flex-grow-1 min-width-0">
                            <div class="d-flex justify-content-between align-items-start flex-wrap gap-2">
                                <div>
                                    <h6 class="fw-bold mb-1">${garment.name || 'Prenda'}</h6>
                                    <p class="text-muted small mb-1">
                                        <i class="bi bi-person me-1"></i>${student.name || 'Estudiante'}
                                    </p>
                                    <p class="text-muted small mb-0">
                                        <i class="bi bi-clock me-1"></i>${timeStr}
                                        <span class="badge bg-secondary-subtle text-secondary ms-2">${a.code}</span>
                                    </p>
                                </div>
                                <div class="text-end">
                                    <span class="badge bg-${getStatusColor(a.status)}-subtle text-${getStatusColor(a.status)} d-block mb-2">${statusLabel}</span>
                                    ${actionBtn}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>`;
        }).join('');
    }

    function getStatusColor(status) {
        const colors = {
            scheduled: 'primary',
            attended: 'info',
            completed: 'success',
            no_show: 'secondary',
        };
        return colors[status] || 'secondary';
    }

    // ==================== My Slots ====================

    async function loadMySlots() {
        slotsLoading.classList.remove('d-none');
        slotsList.innerHTML = '';
        slotsEmpty.classList.add('d-none');

        try {
            const res = await fetch(`${API_BASE}/slots/my-slots`);
            if (!res.ok) throw new Error('Error al cargar horarios');
            const slots = await res.json();

            slotsLoading.classList.add('d-none');

            if (!slots.length) {
                slotsEmpty.classList.remove('d-none');
                return;
            }

            renderSlots(slots);

        } catch (e) {
            console.error(e);
            slotsLoading.classList.add('d-none');
            slotsEmpty.classList.remove('d-none');
        }
    }

    function renderSlots(slots) {
        // Agrupar por fecha
        const grouped = {};
        slots.forEach(s => {
            const date = s.date;
            if (!grouped[date]) grouped[date] = [];
            grouped[date].push(s);
        });

        let html = '';
        Object.keys(grouped).sort().forEach(date => {
            const dateSlots = grouped[date];
            const dateStr = formatDate(date);

            html += `<div class="mb-4">
                <h6 class="fw-bold text-muted small mb-2">${dateStr}</h6>`;

            dateSlots.forEach(s => {
                const timeStr = `${formatTime(s.start_time)} - ${formatTime(s.end_time)}`;
                const spotsUsed = `${s.current_appointments}/${s.max_appointments}`;
                const locationName = s.location ? s.location.name : '';
                const isInactive = !s.is_active;

                html += `
                <div class="card slot-item ${isInactive ? 'inactive' : ''} mb-2 border-0 shadow-sm">
                    <div class="card-body p-3">
                        <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
                            <div>
                                <span class="fw-bold">${timeStr}</span>
                                ${locationName ? `<span class="text-muted ms-2"><i class="bi bi-geo-alt me-1"></i>${locationName}</span>` : ''}
                            </div>
                            <div class="d-flex align-items-center gap-2">
                                <span class="badge ${s.is_full ? 'bg-warning' : 'bg-light'} text-dark">
                                    <i class="bi bi-people me-1"></i>${spotsUsed}
                                </span>
                                ${!isInactive && s.current_appointments === 0 ? `
                                <button class="btn btn-sm btn-outline-danger" onclick="window.cancelSlot(${s.id})">
                                    <i class="bi bi-trash"></i>
                                </button>` : ''}
                            </div>
                        </div>
                    </div>
                </div>`;
            });

            html += `</div>`;
        });

        slotsList.innerHTML = html;
    }

    // ==================== Create Slot ====================

    async function loadLocations() {
        try {
            const res = await fetch(`${API_BASE}/slots/locations`);
            if (!res.ok) return;
            const locations = await res.json();

            const select = document.getElementById('slotLocation');
            locations.forEach(loc => {
                const opt = document.createElement('option');
                opt.value = loc.id;
                opt.textContent = loc.name;
                select.appendChild(opt);
            });
        } catch (e) {
            console.error('Error cargando ubicaciones:', e);
        }
    }

    async function createSlot() {
        const btn = document.getElementById('btnSaveSlot');
        const btnText = document.getElementById('saveSlotText');
        const btnLoading = document.getElementById('saveSlotLoading');

        const date = document.getElementById('slotDate').value;
        const startTime = document.getElementById('slotStartTime').value;
        const endTime = document.getElementById('slotEndTime').value;
        const maxAppts = document.getElementById('slotMaxAppts').value;
        const locationId = document.getElementById('slotLocation').value;

        if (!date || !startTime || !endTime) {
            showToast('Completa todos los campos requeridos', 'warning');
            return;
        }

        btn.disabled = true;
        btnText.classList.add('d-none');
        btnLoading.classList.remove('d-none');

        try {
            const res = await fetch(`${API_BASE}/slots`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    date,
                    start_time: startTime,
                    end_time: endTime,
                    max_appointments: parseInt(maxAppts),
                    location_id: locationId || null,
                }),
            });

            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.error || 'Error al crear horario');
            }

            slotModal.hide();
            showToast('Horario creado exitosamente', 'success');
            loadMySlots();
            document.getElementById('slotForm').reset();

        } catch (e) {
            showToast(e.message, 'danger');
        } finally {
            btn.disabled = false;
            btnText.classList.remove('d-none');
            btnLoading.classList.add('d-none');
        }
    }

    window.cancelSlot = async function (slotId) {
        if (!confirm('¿Eliminar este horario?')) return;

        try {
            const res = await fetch(`${API_BASE}/slots/${slotId}`, {
                method: 'DELETE',
            });

            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.error || 'Error al eliminar');
            }

            showToast('Horario eliminado', 'success');
            loadMySlots();

        } catch (e) {
            showToast(e.message, 'danger');
        }
    };

    // ==================== Attend Appointment ====================

    window.openAttendModal = async function (appointmentId) {
        // Load appointment details
        try {
            const res = await fetch(`${API_BASE}/appointments/volunteer/list`);
            if (!res.ok) throw new Error('Error al cargar cita');
            const appointments = await res.json();
            currentAppointment = appointments.find(a => a.id === appointmentId);

            if (!currentAppointment) {
                showToast('Cita no encontrada', 'danger');
                return;
            }

            const garment = currentAppointment.garment || {};
            const student = currentAppointment.student || {};

            document.getElementById('attendInfo').innerHTML = `
                <div class="d-flex gap-3 align-items-center">
                    ${garment.image_path
                    ? `<img src="${API_BASE}/garments/image/${garment.image_path}" class="garment-mini" alt="${garment.name}">`
                    : `<div class="garment-mini-placeholder"><i class="bi bi-image text-muted"></i></div>`}
                    <div>
                        <h6 class="fw-bold mb-1">${garment.name || 'Prenda'}</h6>
                        <p class="text-muted small mb-0">
                            <i class="bi bi-person me-1"></i>${student.name || 'Estudiante'}
                        </p>
                    </div>
                </div>`;

            // Reset modal state
            document.getElementById('attendanceStep').classList.remove('d-none');
            document.getElementById('outcomeStep').classList.add('d-none');

            if (currentAppointment.status === 'attended') {
                // Skip to outcome step
                document.getElementById('attendanceStep').classList.add('d-none');
                document.getElementById('outcomeStep').classList.remove('d-none');
            }

            attendModal.show();

        } catch (e) {
            showToast('Error al cargar detalles', 'danger');
        }
    };

    async function markAttendance(attended) {
        if (!currentAppointment) return;

        try {
            const res = await fetch(`${API_BASE}/appointments/${currentAppointment.id}/attendance`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ attended }),
            });

            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.error || 'Error al registrar');
            }

            if (attended) {
                // Show outcome step
                document.getElementById('attendanceStep').classList.add('d-none');
                document.getElementById('outcomeStep').classList.remove('d-none');
                currentAppointment.status = 'attended';
            } else {
                // No show - close and refresh
                attendModal.hide();
                showToast('Inasistencia registrada', 'info');
                loadTodayAppointments();
            }

        } catch (e) {
            showToast(e.message, 'danger');
        }
    }

    async function completeAppointment(outcome) {
        if (!currentAppointment) return;

        const notes = document.getElementById('outcomeNotes').value;

        try {
            const res = await fetch(`${API_BASE}/appointments/${currentAppointment.id}/complete`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ outcome, notes }),
            });

            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.error || 'Error al completar');
            }

            attendModal.hide();
            showToast('Cita completada', 'success');
            loadTodayAppointments();
            document.getElementById('outcomeNotes').value = '';

        } catch (e) {
            showToast(e.message, 'danger');
        }
    }

    // ==================== Utilities ====================

    function formatDate(dateStr) {
        const date = new Date(dateStr + 'T00:00:00');
        const options = { weekday: 'long', day: 'numeric', month: 'long' };
        let formatted = date.toLocaleDateString('es-MX', options);
        return formatted.charAt(0).toUpperCase() + formatted.slice(1);
    }

    function formatTime(timeStr) {
        const [h, m] = timeStr.split(':');
        const hour = parseInt(h, 10);
        const ampm = hour >= 12 ? 'PM' : 'AM';
        const hour12 = hour % 12 || 12;
        return `${hour12}:${m} ${ampm}`;
    }

    function showToast(message, type = 'info') {
        const container = document.getElementById('toastContainer');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast align-items-center text-bg-${type} border-0 show`;
        toast.setAttribute('role', 'alert');
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>`;

        container.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    }

    // ==================== Event Listeners ====================

    document.getElementById('btnNewSlot').addEventListener('click', () => {
        // Set min date to today
        const today = new Date().toISOString().split('T')[0];
        document.getElementById('slotDate').min = today;
        document.getElementById('slotDate').value = today;
        slotModal.show();
    });

    document.getElementById('btnSaveSlot').addEventListener('click', createSlot);

    document.getElementById('btnAttended').addEventListener('click', () => markAttendance(true));
    document.getElementById('btnNoShow').addEventListener('click', () => markAttendance(false));

    document.querySelectorAll('[data-outcome]').forEach(btn => {
        btn.addEventListener('click', () => {
            completeAppointment(btn.dataset.outcome);
        });
    });

    // Tab change listeners
    document.getElementById('slots-tab').addEventListener('shown.bs.tab', loadMySlots);

    // ==================== Init ====================

    slotModal = new bootstrap.Modal(document.getElementById('slotModal'));
    attendModal = new bootstrap.Modal(document.getElementById('attendModal'));

    loadLocations();
    loadTodayAppointments();
})();
