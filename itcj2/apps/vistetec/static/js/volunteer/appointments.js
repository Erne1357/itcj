/**
 * VisteTec - Gestión de Citas (Voluntario)
 * Horarios generales con inscripción de voluntarios.
 */
(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1';

    // Modals
    let scheduleModal, attendModal;

    // State
    let currentAppointment = null;

    const statusLabels = {
        scheduled: 'Programada',
        attended: 'En proceso',
        completed: 'Completada',
        no_show: 'No asistió',
    };

    // ==================== TODAY'S APPOINTMENTS ====================

    async function loadTodayAppointments(date = null) {
        const list = document.getElementById('todayList');
        const empty = document.getElementById('todayEmpty');
        const loading = document.getElementById('todayLoading');
        const filterDateInput = document.getElementById('filterTodayDate');
        const dateIndicator = document.getElementById('todayDateIndicator');

        loading.classList.remove('d-none');
        list.innerHTML = '';
        empty.classList.add('d-none');

        try {
            // Si no se proporciona fecha, usar el día de hoy
            const targetDate = date || new Date().toISOString().split('T')[0];
            
            // Actualizar el input de fecha para reflejar la fecha que se está mostrando
            filterDateInput.value = targetDate;

            // Actualizar indicador de fecha
            const dateObj = new Date(targetDate + 'T00:00:00');
            const today = new Date().toISOString().split('T')[0];
            const isToday = targetDate === today;
            
            if (isToday) {
                dateIndicator.innerHTML = '<i class="bi bi-circle-fill text-success me-1" style="font-size: 0.5rem;"></i>Mostrando citas de hoy';
            } else {
                const options = { weekday: 'long', day: 'numeric', month: 'long' };
                let dateStr = dateObj.toLocaleDateString('es-MX', options);
                dateStr = dateStr.charAt(0).toUpperCase() + dateStr.slice(1);
                dateIndicator.innerHTML = `<i class="bi bi-calendar-event me-1"></i>Mostrando: ${dateStr}`;
            }

            const res = await fetch(`${API_BASE}/appointments/volunteer/list?date=${targetDate}`);
            if (!res.ok) throw new Error('Error');
            const appointments = await res.json();

            loading.classList.add('d-none');
            document.getElementById('todayCount').textContent = appointments.length;

            if (!appointments.length) {
                empty.classList.remove('d-none');
                // Actualizar el mensaje para que sea más claro
                const emptyTitle = document.querySelector('#todayEmpty h5');
                if (emptyTitle) {
                    emptyTitle.textContent = isToday ? 'No hay citas para hoy' : 'No hay citas para este día';
                }
                return;
            }

            list.innerHTML = appointments.map(renderAppointmentCard).join('');
        } catch (e) {
            console.error('Error loading appointments:', e);
            loading.classList.add('d-none');
            empty.classList.remove('d-none');
        }
    }

    function renderAppointmentCard(a) {
        const slot = a.slot || {};
        const garment = a.garment || {};
        const student = a.student || {};
        const timeStr = slot.start_time && slot.end_time
            ? `${formatTime(slot.start_time)} - ${formatTime(slot.end_time)}`
            : '';

        const imageHtml = garment.image_path
            ? `<img src="${API_BASE}/garments/image/${garment.image_path}" class="garment-mini" alt="">`
            : `<div class="garment-mini-placeholder"><i class="bi bi-image text-muted"></i></div>`;

        const statusLabel = statusLabels[a.status] || a.status;
        const canAttend = a.status === 'scheduled';
        const canComplete = a.status === 'attended';

        const donationBadge = a.will_bring_donation
            ? '<span class="badge bg-warning-subtle text-warning ms-2"><i class="bi bi-gift me-1"></i>Donación</span>'
            : '';

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
                                <h6 class="fw-bold mb-1">${escapeHtml(garment.name || 'Prenda')}</h6>
                                <p class="text-muted small mb-1">
                                    <i class="bi bi-person me-1"></i>${escapeHtml(student.name || 'Estudiante')}
                                    ${donationBadge}
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
    }

    function getStatusColor(status) {
        const colors = { scheduled: 'primary', attended: 'info', completed: 'success', no_show: 'secondary' };
        return colors[status] || 'secondary';
    }

    // ==================== AVAILABLE SLOTS ====================

    let allAvailableSlots = [];
    let slotsByDateAvailable = {};
    let currentMonthAvailable = new Date();
    let selectedDateAvailable = null;
    let selectedSlotIds = new Set();

    async function loadAvailableSlots() {
        const content = document.getElementById('availableContent');
        const empty = document.getElementById('availableEmpty');
        const loading = document.getElementById('availableLoading');
        const noDateSelected = document.getElementById('noDateSelected');
        const dateSelectedContent = document.getElementById('dateSelectedContent');

        loading.classList.remove('d-none');
        content.classList.add('d-none');
        empty.classList.add('d-none');
        noDateSelected.classList.remove('d-none');
        dateSelectedContent.classList.add('d-none');

        selectedSlotIds.clear();
        updateBulkSignupButton();

        try {
            const res = await fetch(`${API_BASE}/slots/all`);
            if (!res.ok) throw new Error('Error');
            allAvailableSlots = await res.json();

            loading.classList.add('d-none');

            if (!allAvailableSlots.length) {
                empty.classList.remove('d-none');
                return;
            }

            // Agrupar slots por fecha
            slotsByDateAvailable = {};
            allAvailableSlots.forEach(s => {
                if (!slotsByDateAvailable[s.date]) {
                    slotsByDateAvailable[s.date] = [];
                }
                slotsByDateAvailable[s.date].push(s);
            });

            // Inicializar mes actual al primer día disponible
            const firstDate = Object.keys(slotsByDateAvailable).sort()[0];
            currentMonthAvailable = new Date(firstDate + 'T00:00:00');

            renderAvailableCalendar();
            content.classList.remove('d-none');

        } catch (e) {
            loading.classList.add('d-none');
            empty.classList.remove('d-none');
        }
    }

    function renderAvailableCalendar() {
        const monthDisplay = document.getElementById('availableCalendarMonth');
        const grid = document.querySelector('.calendar-grid-volunteer');
        
        // Mostrar mes/año
        const options = { month: 'long', year: 'numeric' };
        let monthStr = currentMonthAvailable.toLocaleDateString('es-MX', options);
        monthStr = monthStr.charAt(0).toUpperCase() + monthStr.slice(1);
        monthDisplay.textContent = monthStr;

        // Limpiar días anteriores (mantener headers)
        const existingDays = grid.querySelectorAll('.calendar-day-volunteer');
        existingDays.forEach(day => day.remove());

        // Calcular inicio del mes
        const firstDay = new Date(currentMonthAvailable.getFullYear(), currentMonthAvailable.getMonth(), 1);
        const lastDay = new Date(currentMonthAvailable.getFullYear(), currentMonthAvailable.getMonth() + 1, 0);
        
        // Ajustar para que Lunes sea 0
        let startDayOfWeek = firstDay.getDay() - 1;
        if (startDayOfWeek === -1) startDayOfWeek = 6;

        // Agregar días vacíos al inicio
        for (let i = 0; i < startDayOfWeek; i++) {
            const emptyDay = document.createElement('div');
            emptyDay.className = 'calendar-day-volunteer empty';
            grid.appendChild(emptyDay);
        }

        // Agregar días del mes
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        for (let day = 1; day <= lastDay.getDate(); day++) {
            const currentDate = new Date(currentMonthAvailable.getFullYear(), currentMonthAvailable.getMonth(), day);
            const dateStr = formatDateKey(currentDate);
            const daySlots = slotsByDateAvailable[dateStr] || [];
            
            const dayElement = document.createElement('div');
            dayElement.className = 'calendar-day-volunteer';
            dayElement.textContent = day;
            
            // Verificar si el día está en el pasado
            if (currentDate < today) {
                dayElement.classList.add('disabled');
            } else if (daySlots.length > 0) {
                dayElement.classList.add('available');
                
                // Verificar si todos los slots están inscritos
                const signedUpCount = daySlots.filter(s => s.is_signed_up).length;
                if (signedUpCount === daySlots.length) {
                    dayElement.classList.add('has-signups');
                } else if (signedUpCount > 0) {
                    dayElement.classList.add('has-partial-signups');
                }
                
                dayElement.dataset.date = dateStr;
                dayElement.addEventListener('click', () => selectAvailableDate(dateStr));
                
                // Marcar si es el día seleccionado
                if (dateStr === selectedDateAvailable) {
                    dayElement.classList.add('active');
                }
            } else {
                dayElement.classList.add('disabled');
            }
            
            grid.appendChild(dayElement);
        }
    }

    function selectAvailableDate(dateStr) {
        selectedDateAvailable = dateStr;
        
        // Actualizar visual del calendario
        document.querySelectorAll('.calendar-day-volunteer.available').forEach(day => {
            day.classList.remove('active');
        });
        document.querySelector(`[data-date="${dateStr}"]`)?.classList.add('active');
        
        // Mostrar horarios
        const noDateSelected = document.getElementById('noDateSelected');
        const dateSelectedContent = document.getElementById('dateSelectedContent');
        noDateSelected.classList.add('d-none');
        dateSelectedContent.classList.remove('d-none');
        
        renderAvailableTimeSlots(dateStr);
    }

    function renderAvailableTimeSlots(dateStr) {
        const dateTitle = document.getElementById('selectedDateTitle');
        const dateSummary = document.getElementById('selectedDateSummary');
        const timeSlotsList = document.getElementById('availableTimeSlots');
        
        // Formatear fecha para mostrar
        dateTitle.textContent = formatDate(dateStr);
        
        const daySlots = slotsByDateAvailable[dateStr] || [];
        daySlots.sort((a, b) => a.start_time.localeCompare(b.start_time));
        
        const signedUpCount = daySlots.filter(s => s.is_signed_up).length;
        dateSummary.textContent = `${daySlots.length} horario${daySlots.length !== 1 ? 's' : ''} disponible${daySlots.length !== 1 ? 's' : ''} • ${signedUpCount} inscrito${signedUpCount !== 1 ? 's' : ''}`;
        
        let html = '<div class="d-flex flex-column gap-2">';
        
        daySlots.forEach(s => {
            const timeStr = `${formatTime(s.start_time)} - ${formatTime(s.end_time)}`;
            const locationName = s.location ? s.location.name : '';
            const spotsUsed = `${s.current_appointments}/${s.max_appointments}`;
            const volunteerCount = s.volunteers ? s.volunteers.length : 0;
            
            const isSelected = selectedSlotIds.has(s.id);
            const isAlreadySigned = s.is_signed_up;
            
            html += `
            <div class="volunteer-time-slot ${isAlreadySigned ? 'already-signed' : ''} ${isSelected ? 'selected' : ''} p-3" data-slot-id="${s.id}">
                <div class="d-flex align-items-start gap-3">
                    <input type="checkbox" ${isAlreadySigned ? 'checked disabled' : ''} 
                           ${isSelected ? 'checked' : ''} 
                           data-slot-id="${s.id}"
                           class="mt-1">
                    <div class="flex-grow-1">
                        <div class="fw-bold mb-1">${timeStr}</div>
                        ${locationName ? `<div class="text-muted small">
                            <i class="bi bi-geo-alt me-1"></i>${escapeHtml(locationName)}
                        </div>` : ''}
                        <div class="d-flex gap-2 mt-2">
                            <span class="badge bg-light text-dark" title="Alumnos agendados">
                                <i class="bi bi-people me-1"></i>${spotsUsed}
                            </span>
                            <span class="badge ${volunteerCount > 0 ? 'bg-success-subtle text-success' : 'bg-warning-subtle text-warning'}" title="Voluntarios inscritos">
                                <i class="bi bi-person-badge me-1"></i>${volunteerCount}
                            </span>
                            ${isAlreadySigned ? '<span class="badge bg-success-subtle text-success"><i class="bi bi-check-circle me-1"></i>Ya inscrito</span>' : ''}
                        </div>
                    </div>
                </div>
            </div>`;
        });
        
        html += '</div>';
        timeSlotsList.innerHTML = html;
        
        // Event listeners para selección
        timeSlotsList.querySelectorAll('.volunteer-time-slot:not(.already-signed)').forEach(card => {
            card.addEventListener('click', (e) => {
                if (e.target.tagName === 'INPUT') return; // Ya se maneja en el checkbox
                const checkbox = card.querySelector('input[type="checkbox"]');
                checkbox.checked = !checkbox.checked;
                toggleSlotSelection(parseInt(card.dataset.slotId), checkbox.checked);
            });
        });
        
        timeSlotsList.querySelectorAll('input[type="checkbox"]:not([disabled])').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                toggleSlotSelection(parseInt(e.target.dataset.slotId), e.target.checked);
            });
        });
    }

    function toggleSlotSelection(slotId, isSelected) {
        if (isSelected) {
            selectedSlotIds.add(slotId);
        } else {
            selectedSlotIds.delete(slotId);
        }
        
        // Actualizar visual
        const card = document.querySelector(`.volunteer-time-slot[data-slot-id="${slotId}"]`);
        if (card) {
            card.classList.toggle('selected', isSelected);
        }
        
        updateBulkSignupButton();
    }

    function updateBulkSignupButton() {
        const btn = document.getElementById('btnBulkSignup');
        const countBadge = document.getElementById('bulkSignupCount');
        
        const count = selectedSlotIds.size;
        countBadge.textContent = count;
        btn.disabled = count === 0;
        
        if (count === 0) {
            document.getElementById('bulkSignupText').textContent = 'Inscribirme';
        } else {
            document.getElementById('bulkSignupText').textContent = `Inscribirme a ${count}`;
        }
    }

    function changeAvailableMonth(direction) {
        currentMonthAvailable = new Date(currentMonthAvailable.getFullYear(), currentMonthAvailable.getMonth() + direction, 1);
        renderAvailableCalendar();
    }

    function selectAllTimesForDay() {
        if (!selectedDateAvailable) return;
        
        const daySlots = slotsByDateAvailable[selectedDateAvailable] || [];
        const checkboxes = document.querySelectorAll('#availableTimeSlots input[type="checkbox"]:not([disabled])');
        
        // Verificar si todos están seleccionados
        const allSelected = Array.from(checkboxes).every(cb => cb.checked);
        
        // Alternar
        checkboxes.forEach(cb => {
            const slotId = parseInt(cb.dataset.slotId);
            cb.checked = !allSelected;
            toggleSlotSelection(slotId, !allSelected);
        });
    }

    async function bulkSignup() {
        if (selectedSlotIds.size === 0) return;
        
        const btn = document.getElementById('btnBulkSignup');
        const btnIcon = btn.querySelector('i.bi-check2-all');
        const btnText = document.getElementById('bulkSignupText');
        const btnCount = document.getElementById('bulkSignupCount');
        
        const originalBtnText = btnText.textContent;
        const originalCountDisplay = btnCount.style.display;
        
        // Cambiar a estado de cargando
        btn.disabled = true;
        btnIcon.className = 'bi bi-hourglass-split spinner-icon me-1';
        btnText.textContent = 'Inscribiendo...';
        btnCount.style.display = 'none';
        
        try {
            const slotIds = Array.from(selectedSlotIds);
            
            // Procesar cada inscripción y capturar los errores con detalles
            const results = await Promise.allSettled(
                slotIds.map(async slotId => {
                    const res = await fetch(`${API_BASE}/slots/${slotId}/signup`, { method: 'POST' });
                    const data = await res.json();
                    
                    if (!res.ok) {
                        throw new Error(data.error || data.message || 'Error desconocido');
                    }
                    
                    return data;
                })
            );
            
            const successful = results.filter(r => r.status === 'fulfilled');
            const failed = results.filter(r => r.status === 'rejected');
            
            // Restaurar el botón ANTES de mostrar mensajes y recargar
            btn.disabled = false;
            btnIcon.className = 'bi bi-check2-all me-1';
            btnText.textContent = originalBtnText;
            btnCount.style.display = originalCountDisplay;
            
            // Mostrar mensajes de éxito
            if (successful.length > 0) {
                VisteTecUtils.showToast(
                    `✓ Te inscribiste exitosamente a ${successful.length} horario${successful.length !== 1 ? 's' : ''}`, 
                    'success'
                );
            }
            
            // Mostrar mensajes de error específicos
            if (failed.length > 0) {
                // Agrupar errores similares
                const errorMessages = failed.map(r => r.reason.message);
                const uniqueErrors = [...new Set(errorMessages)];
                
                if (uniqueErrors.length === 1) {
                    // Un solo tipo de error
                    VisteTecUtils.showToast(
                        `✗ ${failed.length} horario${failed.length !== 1 ? 's' : ''}: ${uniqueErrors[0]}`, 
                        'danger'
                    );
                } else {
                    // Múltiples errores diferentes
                    VisteTecUtils.showToast(
                        `✗ No se pudo inscribir a ${failed.length} horario${failed.length !== 1 ? 's' : ''}. Revisa los detalles.`, 
                        'warning'
                    );
                    
                    // Log detallado en consola para debugging
                    console.warn('Detalles de errores de inscripción:');
                    failed.forEach((r, i) => {
                        console.warn(`  Horario ${i + 1}:`, r.reason.message);
                    });
                }
            }
            
            // Limpiar selección
            selectedSlotIds.clear();
            
            // Recargar slots después de restaurar el botón
            await loadAvailableSlots();
            
            // Si había un día seleccionado, volver a mostrarlo
            if (selectedDateAvailable && slotsByDateAvailable[selectedDateAvailable]) {
                selectAvailableDate(selectedDateAvailable);
            }
            
        } catch (e) {
            console.error('Error inesperado en inscripción:', e);
            VisteTecUtils.showToast('Error inesperado al inscribirse. Por favor intenta de nuevo.', 'danger');
            
            // Asegurarse de restaurar el botón incluso si hay error
            const currentBtn = document.getElementById('btnBulkSignup');
            const currentBtnIcon = currentBtn?.querySelector('i');
            const currentBtnText = document.getElementById('bulkSignupText');
            const currentBtnCount = document.getElementById('bulkSignupCount');
            
            if (currentBtn) currentBtn.disabled = false;
            if (currentBtnIcon) currentBtnIcon.className = 'bi bi-check2-all me-1';
            if (currentBtnText) currentBtnText.textContent = originalBtnText;
            if (currentBtnCount) currentBtnCount.style.display = originalCountDisplay;
        }
    }

    function formatDateKey(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    // ==================== MY SIGNUPS ====================

    async function loadMySignups() {
        const list = document.getElementById('signupsList');
        const empty = document.getElementById('signupsEmpty');
        const loading = document.getElementById('signupsLoading');

        loading.classList.remove('d-none');
        list.innerHTML = '';
        empty.classList.add('d-none');

        try {
            const res = await fetch(`${API_BASE}/slots/my-slots`);
            if (!res.ok) throw new Error('Error');
            const slots = await res.json();

            loading.classList.add('d-none');

            if (!slots.length) {
                empty.classList.remove('d-none');
                return;
            }

            renderMySignups(slots, list);
        } catch (e) {
            loading.classList.add('d-none');
            empty.classList.remove('d-none');
        }
    }

    function renderMySignups(slots, container) {
        const grouped = {};
        slots.forEach(s => {
            if (!grouped[s.date]) grouped[s.date] = [];
            grouped[s.date].push(s);
        });

        let html = '<div class="accordion" id="mySignupsAccordion">';
        Object.keys(grouped).sort().forEach((dateKey, index) => {
            const dateSlots = grouped[dateKey];
            const dateStr = formatDate(dateKey);
            const accordionId = `signupsCollapse${index}`;

            html += `
            <div class="accordion-item border-0 mb-2">
                <h2 class="accordion-header">
                    <button class="accordion-button ${index !== 0 ? 'collapsed' : ''}" type="button"
                            data-bs-toggle="collapse" data-bs-target="#${accordionId}"
                            aria-expanded="${index === 0}" aria-controls="${accordionId}"
                            style="background-color: #fdf2f4; color: #8B1538; font-size: 0.9rem;">
                        <i class="bi bi-calendar3 me-2"></i>${dateStr}
                        <span class="badge bg-light text-dark ms-2">${dateSlots.length} ${dateSlots.length === 1 ? 'horario' : 'horarios'}</span>
                    </button>
                </h2>
                <div id="${accordionId}" class="accordion-collapse collapse ${index === 0 ? 'show' : ''}"
                     data-bs-parent="#mySignupsAccordion">
                    <div class="accordion-body p-2">`;

            dateSlots.forEach(s => {
                const timeStr = `${formatTime(s.start_time)} - ${formatTime(s.end_time)}`;
                const spotsUsed = `${s.current_appointments}/${s.max_appointments}`;
                const locationName = s.location ? escapeHtml(s.location.name) : '';
                const volunteerCount = s.volunteers ? s.volunteers.length : 0;

                html += `
                <div class="card slot-item signed-up mb-2 border-0 shadow-sm">
                    <div class="card-body p-3">
                        <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
                            <div>
                                <span class="fw-bold">${timeStr}</span>
                                ${locationName ? `<span class="text-muted ms-2"><i class="bi bi-geo-alt me-1"></i>${locationName}</span>` : ''}
                            </div>
                            <div class="d-flex align-items-center gap-2">
                                <span class="badge bg-light text-dark">
                                    <i class="bi bi-people me-1"></i>${spotsUsed}
                                </span>
                                <span class="badge bg-success-subtle text-success">
                                    <i class="bi bi-person-badge me-1"></i>${volunteerCount}
                                </span>
                                <button class="btn btn-sm btn-outline-danger" onclick="window.unsignupSlot(${s.id})">
                                    <i class="bi bi-x-lg me-1"></i>Salir
                                </button>
                            </div>
                        </div>
                    </div>
                </div>`;
            });

            html += `</div></div></div>`;
        });

        html += '</div>';
        container.innerHTML = html;
    }

    // ==================== SIGNUP/UNSIGNUP ====================

    window.signupSlot = async function (slotId) {
        try {
            const res = await fetch(`${API_BASE}/slots/${slotId}/signup`, { method: 'POST' });
            const data = await res.json();
            
            if (!res.ok) {
                throw new Error(data.error || data.message || 'Error al inscribirse');
            }

            VisteTecUtils.showToast('✓ Te has inscrito al horario', 'success');
            loadAvailableSlots();
        } catch (e) {
            console.error('Error en inscripción:', e);
            VisteTecUtils.showToast(`✗ ${e.message}`, 'danger');
        }
    };

    window.unsignupSlot = async function (slotId) {
        const ok = await VisteTecUtils.confirmModal('¿Desinscribirte de este horario?', 'Desinscribir');
        if (!ok) return;

        try {
            const res = await fetch(`${API_BASE}/slots/${slotId}/unsignup`, { method: 'POST' });
            const data = await res.json();
            
            if (!res.ok) {
                throw new Error(data.error || data.message || 'Error al desinscribirse');
            }

            VisteTecUtils.showToast('✓ Inscripción cancelada', 'info');
            loadAvailableSlots();
            loadMySignups();
        } catch (e) {
            console.error('Error al desinscribirse:', e);
            VisteTecUtils.showToast(`✗ ${e.message}`, 'danger');
        }
    };

    // ==================== CREATE SCHEDULE ====================

    async function loadLocations() {
        try {
            const res = await fetch(`${API_BASE}/slots/locations`);
            if (!res.ok) return;
            const locations = await res.json();

            const select = document.getElementById('schedLocation');
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

    function calculatePreview() {
        const startDate = document.getElementById('schedStartDate').value;
        const endDate = document.getElementById('schedEndDate').value;
        const startTime = document.getElementById('schedStartTime').value;
        const endTime = document.getElementById('schedEndTime').value;
        const duration = parseInt(document.getElementById('schedDuration').value);
        const previewEl = document.getElementById('previewText');

        const selectedDays = [];
        document.querySelectorAll('.weekday-btn.active').forEach(btn => {
            selectedDays.push(parseInt(btn.dataset.day));
        });

        if (!startDate || !endDate || !startTime || !endTime || !selectedDays.length) {
            previewEl.textContent = 'Selecciona fechas y horarios para ver la vista previa';
            return;
        }

        // Calcular slots por bloque horario
        const [sh, sm] = startTime.split(':').map(Number);
        const [eh, em] = endTime.split(':').map(Number);
        const blockMinutes = (eh * 60 + em) - (sh * 60 + sm);

        if (blockMinutes <= 0) {
            previewEl.textContent = 'La hora de fin debe ser posterior a la de inicio';
            return;
        }

        const slotsPerDay = Math.floor(blockMinutes / duration);

        // Calcular días
        const start = new Date(startDate + 'T00:00:00');
        const end = new Date(endDate + 'T00:00:00');
        let matchingDays = 0;
        const current = new Date(start);
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        while (current <= end) {
            if (selectedDays.includes(current.getDay() === 0 ? 6 : current.getDay() - 1) && current >= today) {
                matchingDays++;
            }
            current.setDate(current.getDate() + 1);
        }

        const totalSlots = matchingDays * slotsPerDay;
        previewEl.textContent = `Se crearán ~${totalSlots} horarios (${slotsPerDay} por día × ${matchingDays} días)`;
    }

    async function createSchedule() {
        const btn = document.getElementById('btnSaveSchedule');
        const btnText = document.getElementById('saveScheduleText');
        const btnLoading = document.getElementById('saveScheduleLoading');

        const startDate = document.getElementById('schedStartDate').value;
        const endDate = document.getElementById('schedEndDate').value;
        const startTime = document.getElementById('schedStartTime').value;
        const endTime = document.getElementById('schedEndTime').value;
        const duration = document.getElementById('schedDuration').value;
        const maxStudents = document.getElementById('schedMaxStudents').value;
        const locationId = document.getElementById('schedLocation').value;

        const weekdays = [];
        document.querySelectorAll('.weekday-btn.active').forEach(b => {
            weekdays.push(parseInt(b.dataset.day));
        });

        if (!startDate || !endDate || !startTime || !endTime || !weekdays.length) {
            VisteTecUtils.showToast('Completa todos los campos requeridos', 'warning');
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
                    start_date: startDate,
                    end_date: endDate,
                    weekdays: weekdays,
                    start_time: startTime,
                    end_time: endTime,
                    slot_duration_minutes: parseInt(duration),
                    max_students_per_slot: parseInt(maxStudents),
                    location_id: locationId || null,
                }),
            });

            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Error al crear horarios');

            scheduleModal.hide();
            VisteTecUtils.showToast(`${data.created} horarios creados`, 'success');
            loadAvailableSlots();
            document.getElementById('scheduleForm').reset();
            document.querySelectorAll('.weekday-btn').forEach(b => b.classList.remove('active'));
            document.getElementById('previewText').textContent = 'Selecciona fechas y horarios para ver la vista previa';

        } catch (e) {
            VisteTecUtils.showToast(e.message, 'danger');
        } finally {
            btn.disabled = false;
            btnText.classList.remove('d-none');
            btnLoading.classList.add('d-none');
        }
    }

    // ==================== ATTEND APPOINTMENT ====================

    window.openAttendModal = async function (appointmentId) {
        try {
            const res = await fetch(`${API_BASE}/appointments/volunteer/list`);
            if (!res.ok) throw new Error('Error');
            const appointments = await res.json();
            currentAppointment = appointments.find(a => a.id === appointmentId);

            if (!currentAppointment) {
                VisteTecUtils.showToast('Cita no encontrada', 'danger');
                return;
            }

            const garment = currentAppointment.garment || {};
            const student = currentAppointment.student || {};

            document.getElementById('attendInfo').innerHTML = `
                <div class="d-flex gap-3 align-items-center">
                    ${garment.image_path
                    ? `<img src="${API_BASE}/garments/image/${garment.image_path}" class="garment-mini" alt="">`
                    : `<div class="garment-mini-placeholder"><i class="bi bi-image text-muted"></i></div>`}
                    <div>
                        <h6 class="fw-bold mb-1">${escapeHtml(garment.name || 'Prenda')}</h6>
                        <p class="text-muted small mb-0">
                            <i class="bi bi-person me-1"></i>${escapeHtml(student.name || 'Estudiante')}
                        </p>
                    </div>
                </div>`;

            // Indicador de donación
            const donationEl = document.getElementById('donationIndicator');
            if (currentAppointment.will_bring_donation) {
                donationEl.classList.remove('d-none');
            } else {
                donationEl.classList.add('d-none');
            }

            // Reset modal state
            document.getElementById('attendanceStep').classList.remove('d-none');
            document.getElementById('outcomeStep').classList.add('d-none');

            if (currentAppointment.status === 'attended') {
                document.getElementById('attendanceStep').classList.add('d-none');
                document.getElementById('outcomeStep').classList.remove('d-none');
            }

            attendModal.show();
        } catch (e) {
            VisteTecUtils.showToast('Error al cargar detalles', 'danger');
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
            if (!res.ok) throw new Error(data.error || 'Error');

            if (attended) {
                document.getElementById('attendanceStep').classList.add('d-none');
                document.getElementById('outcomeStep').classList.remove('d-none');
                currentAppointment.status = 'attended';
            } else {
                attendModal.hide();
                VisteTecUtils.showToast('Inasistencia registrada', 'info');
                loadTodayAppointments();
            }
        } catch (e) {
            VisteTecUtils.showToast(e.message, 'danger');
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
            if (!res.ok) throw new Error(data.error || 'Error');

            attendModal.hide();
            VisteTecUtils.showToast('Cita completada', 'success');
            
            // Si el estudiante indicó que traería donación, redirigir a registro de donación
            if (currentAppointment.will_bring_donation && currentAppointment.student) {
                const student = currentAppointment.student;
                const controlNumber = student.control_number || '';
                const studentId = student.id || '';
                const studentName = encodeURIComponent(student.name || '');
                
                // Preguntar si quiere registrar la donación ahora
                const registerNow = await VisteTecUtils.confirmModal(
                    'Registrar donación',
                    'El estudiante indicó que traería una donación. ¿Deseas registrarla ahora?',
                    'Registrar donación',
                    'Más tarde'
                );
                
                if (registerNow) {
                    window.location.href = `/vistetec/volunteer/donations/register?donor_id=${studentId}&control_number=${controlNumber}&donor_name=${studentName}`;
                    return;
                }
            }
            
            loadTodayAppointments();
            document.getElementById('outcomeNotes').value = '';
        } catch (e) {
            VisteTecUtils.showToast(e.message, 'danger');
        }
    }

    // ==================== UPCOMING & PAST APPOINTMENTS ====================

    async function loadUpcomingAppointments() {
        const list = document.getElementById('upcomingList');
        const empty = document.getElementById('upcomingEmpty');
        const loading = document.getElementById('upcomingLoading');

        loading.classList.remove('d-none');
        list.innerHTML = '';
        empty.classList.add('d-none');

        try {
            const tomorrow = new Date();
            tomorrow.setDate(tomorrow.getDate() + 1);
            const dateStr = tomorrow.toISOString().split('T')[0];

            const res = await fetch(`${API_BASE}/appointments/volunteer/list?date=${dateStr}`);
            if (!res.ok) throw new Error('Error');
            const appointments = await res.json();

            // Filtrar solo futuras (después de hoy)
            const today = new Date().toISOString().split('T')[0];
            const upcoming = appointments.filter(a => a.slot && a.slot.date > today);

            loading.classList.add('d-none');

            if (!upcoming.length) {
                empty.classList.remove('d-none');
                return;
            }

            list.innerHTML = upcoming.map(renderAppointmentCard).join('');
        } catch (e) {
            loading.classList.add('d-none');
            empty.classList.remove('d-none');
        }
    }

    async function loadPastAppointments() {
        const list = document.getElementById('pastList');
        const empty = document.getElementById('pastEmpty');
        const loading = document.getElementById('pastLoading');

        loading.classList.remove('d-none');
        list.innerHTML = '';
        empty.classList.add('d-none');

        try {
            const res = await fetch(`${API_BASE}/appointments/volunteer/list`);
            if (!res.ok) throw new Error('Error');
            const appointments = await res.json();

            // Filtrar solo pasadas (antes de hoy)
            const today = new Date().toISOString().split('T')[0];
            const past = appointments.filter(a => a.slot && a.slot.date < today);

            loading.classList.add('d-none');

            if (!past.length) {
                empty.classList.remove('d-none');
                return;
            }

            list.innerHTML = past.map(renderAppointmentCard).join('');
        } catch (e) {
            loading.classList.add('d-none');
            empty.classList.remove('d-none');
        }
    }

    // ==================== UTILITIES ====================

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function formatDate(dateStr) {
        const d = new Date(dateStr + 'T00:00:00');
        const options = { weekday: 'long', day: 'numeric', month: 'long' };
        let formatted = d.toLocaleDateString('es-MX', options);
        return formatted.charAt(0).toUpperCase() + formatted.slice(1);
    }

    function formatTime(timeStr) {
        const [h, m] = timeStr.split(':');
        const hour = parseInt(h, 10);
        const ampm = hour >= 12 ? 'PM' : 'AM';
        const hour12 = hour % 12 || 12;
        return `${hour12}:${m} ${ampm}`;
    }

    // ==================== EVENT LISTENERS ====================

    document.getElementById('btnNewSchedule').addEventListener('click', () => {
        const today = new Date().toISOString().split('T')[0];
        document.getElementById('schedStartDate').min = today;
        document.getElementById('schedStartDate').value = today;
        document.getElementById('schedEndDate').min = today;
        scheduleModal.show();
    });

    document.getElementById('btnSaveSchedule').addEventListener('click', createSchedule);

    // Weekday toggle buttons
    document.querySelectorAll('.weekday-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            btn.classList.toggle('active');
            calculatePreview();
        });
    });

    // Preview recalculation on input change
    ['schedStartDate', 'schedEndDate', 'schedStartTime', 'schedEndTime', 'schedDuration'].forEach(id => {
        document.getElementById(id).addEventListener('change', calculatePreview);
    });

    // Attend modal buttons
    document.getElementById('btnAttended').addEventListener('click', () => markAttendance(true));
    document.getElementById('btnNoShow').addEventListener('click', () => markAttendance(false));

    document.querySelectorAll('[data-outcome]').forEach(btn => {
        btn.addEventListener('click', () => completeAppointment(btn.dataset.outcome));
    });

    // Tab change listeners
    document.getElementById('available-tab').addEventListener('shown.bs.tab', loadAvailableSlots);
    document.getElementById('mysignups-tab').addEventListener('shown.bs.tab', loadMySignups);
    document.getElementById('upcoming-tab').addEventListener('shown.bs.tab', loadUpcomingAppointments);
    document.getElementById('past-tab').addEventListener('shown.bs.tab', loadPastAppointments);

    // Available slots calendar navigation
    document.getElementById('btnAvailPrevMonth').addEventListener('click', () => changeAvailableMonth(-1));
    document.getElementById('btnAvailNextMonth').addEventListener('click', () => changeAvailableMonth(1));
    document.getElementById('btnSelectAllTimes').addEventListener('click', selectAllTimesForDay);
    document.getElementById('btnBulkSignup').addEventListener('click', bulkSignup);

    // Date filter for today's appointments
    document.getElementById('filterTodayDate').addEventListener('change', (e) => {
        loadTodayAppointments(e.target.value);
    });

    document.getElementById('btnTodayToday').addEventListener('click', () => {
        const today = new Date().toISOString().split('T')[0];
        loadTodayAppointments(today);
    });

    // ==================== INIT ====================

    scheduleModal = new bootstrap.Modal(document.getElementById('scheduleModal'));
    attendModal = new bootstrap.Modal(document.getElementById('attendModal'));

    loadLocations();
    loadTodayAppointments();
})();
