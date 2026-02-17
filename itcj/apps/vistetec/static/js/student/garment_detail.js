/**
 * VisteTec - Detalle de prenda con sistema de citas
 */
(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1';
    const loadingState = document.getElementById('loadingState');
    const detailView = document.getElementById('garmentDetail');
    const notFoundState = document.getElementById('notFoundState');
    const scheduleSection = document.getElementById('scheduleSection');
    const notAvailableSection = document.getElementById('notAvailableSection');
    const btnSchedule = document.getElementById('btnSchedule');

    const conditionLabels = {
        nuevo: 'Nuevo',
        como_nuevo: 'Como nuevo',
        buen_estado: 'Buen estado',
        usado: 'Usado',
    };

    let garmentData = null;
    let selectedSlotId = null;
    let scheduleModal = null;
    let successModal = null;

    async function loadGarment() {
        try {
            const res = await fetch(`${API_BASE}/catalog/${GARMENT_ID}`);
            if (!res.ok) {
                showNotFound();
                return;
            }
            garmentData = await res.json();
            renderDetail(garmentData);
        } catch (e) {
            console.error(e);
            showNotFound();
        }
    }

    function renderDetail(g) {
        loadingState.classList.add('d-none');
        detailView.classList.remove('d-none');

        document.getElementById('breadcrumbName').textContent = g.name;
        document.getElementById('garmentName').textContent = g.name;
        document.getElementById('garmentCode').textContent = g.code;
        document.getElementById('garmentDescription').textContent = g.description || 'Sin descripción';
        document.getElementById('garmentCategory').textContent = g.category || '-';
        document.getElementById('garmentSize').textContent = g.size || '-';
        document.getElementById('garmentColor').textContent = g.color || '-';
        document.getElementById('garmentCondition').textContent = conditionLabels[g.condition] || g.condition;
        document.getElementById('garmentBrand').textContent = g.brand || '-';
        document.getElementById('garmentGender').textContent = g.gender || '-';

        // Imagen
        if (g.image_path) {
            const img = document.getElementById('garmentImage');
            img.src = `${API_BASE}/garments/image/${g.image_path}`;
            img.classList.remove('d-none');
            document.getElementById('noImageIcon').classList.add('d-none');
        }

        // Status badge y disponibilidad
        const statusBadge = document.getElementById('garmentStatus');
        if (g.status === 'available') {
            statusBadge.textContent = 'Disponible';
            statusBadge.className = 'badge bg-success-subtle text-success mb-2';
            scheduleSection.classList.remove('d-none');
            notAvailableSection.classList.add('d-none');
        } else if (g.status === 'reserved') {
            statusBadge.textContent = 'Reservada';
            statusBadge.className = 'badge bg-warning-subtle text-warning mb-2';
            scheduleSection.classList.add('d-none');
            notAvailableSection.classList.remove('d-none');
            document.getElementById('notAvailableMessage').textContent = 'Esta prenda está reservada para alguien más';
        } else {
            statusBadge.textContent = g.status === 'delivered' ? 'Entregada' : g.status;
            statusBadge.className = 'badge bg-secondary-subtle text-secondary mb-2';
            scheduleSection.classList.add('d-none');
            notAvailableSection.classList.remove('d-none');
            document.getElementById('notAvailableMessage').textContent = 'Esta prenda ya no está disponible';
        }
    }

    function showNotFound() {
        loadingState.classList.add('d-none');
        notFoundState.classList.remove('d-none');
    }

    // ==================== Sistema de citas con calendario ====================

    let allSlots = [];
    let slotsByDate = {};
    let currentMonth = new Date();
    let selectedDate = null;

    async function loadAvailableSlots() {
        const slotsLoading = document.getElementById('slotsLoading');
        const noSlotsState = document.getElementById('noSlotsState');
        const calendarContainer = document.getElementById('calendarContainer');
        const step1 = document.getElementById('step1-dateSelection');
        const step2 = document.getElementById('step2-timeSelection');

        // Reset
        step1.classList.remove('d-none');
        step2.classList.add('d-none');
        slotsLoading.classList.remove('d-none');
        noSlotsState.classList.add('d-none');
        calendarContainer.classList.add('d-none');
        document.getElementById('campaignSection').classList.add('d-none');
        selectedDate = null;
        selectedSlotId = null;

        try {
            const res = await fetch(`${API_BASE}/slots`);
            if (!res.ok) {
                if (res.status === 403) {
                    VisteTecUtils.showToast('No tienes permisos para ver horarios disponibles', 'warning');
                } else {
                    VisteTecUtils.showToast('Error al cargar horarios', 'danger');
                }
                throw new Error(`HTTP ${res.status}`);
            }
            allSlots = await res.json();

            slotsLoading.classList.add('d-none');

            if (!allSlots.length) {
                noSlotsState.classList.remove('d-none');
                return;
            }

            // Agrupar slots por fecha
            slotsByDate = {};
            allSlots.forEach(s => {
                if (!slotsByDate[s.date]) {
                    slotsByDate[s.date] = [];
                }
                slotsByDate[s.date].push(s);
            });

            // Inicializar mes actual al primer día disponible
            const firstDate = Object.keys(slotsByDate).sort()[0];
            currentMonth = new Date(firstDate + 'T00:00:00');

            renderCalendar();
            calendarContainer.classList.remove('d-none');

            // Cargar campañas activas
            loadActiveCampaigns();

        } catch (e) {
            console.error('Error cargando slots:', e);
            slotsLoading.classList.add('d-none');
            noSlotsState.classList.remove('d-none');
        }
    }

    function renderCalendar() {
        const monthDisplay = document.getElementById('calendarMonth');
        const grid = document.querySelector('.calendar-grid');
        
        // Mostrar mes/año
        const options = { month: 'long', year: 'numeric' };
        let monthStr = currentMonth.toLocaleDateString('es-MX', options);
        monthStr = monthStr.charAt(0).toUpperCase() + monthStr.slice(1);
        monthDisplay.textContent = monthStr;

        // Limpiar días anteriores (mantener headers)
        const existingDays = grid.querySelectorAll('.calendar-day');
        existingDays.forEach(day => day.remove());

        // Calcular inicio del mes
        const firstDay = new Date(currentMonth.getFullYear(), currentMonth.getMonth(), 1);
        const lastDay = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 0);
        
        // Ajustar para que Lunes sea 0
        let startDayOfWeek = firstDay.getDay() - 1;
        if (startDayOfWeek === -1) startDayOfWeek = 6;

        // Agregar días vacíos al inicio
        for (let i = 0; i < startDayOfWeek; i++) {
            const emptyDay = document.createElement('div');
            emptyDay.className = 'calendar-day empty';
            grid.appendChild(emptyDay);
        }

        // Agregar días del mes
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        for (let day = 1; day <= lastDay.getDate(); day++) {
            const currentDate = new Date(currentMonth.getFullYear(), currentMonth.getMonth(), day);
            const dateStr = formatDateKey(currentDate);
            const daySlots = slotsByDate[dateStr] || [];
            
            const dayElement = document.createElement('div');
            dayElement.className = 'calendar-day';
            
            // Verificar si el día está en el pasado
            if (currentDate < today) {
                dayElement.classList.add('disabled');
            } else if (daySlots.length > 0) {
                dayElement.classList.add('available');
                
                // Calcular nivel de disponibilidad
                const totalSpots = daySlots.reduce((sum, s) => sum + s.available_spots, 0);
                const avgSpots = totalSpots / daySlots.length;
                
                if (avgSpots >= 5) {
                    dayElement.classList.add('high');
                } else if (avgSpots >= 2) {
                    dayElement.classList.add('medium');
                } else {
                    dayElement.classList.add('low');
                }
                
                dayElement.dataset.date = dateStr;
                dayElement.addEventListener('click', () => selectDate(dateStr));
            } else {
                dayElement.classList.add('disabled');
            }
            
            dayElement.innerHTML = `
                <span class="calendar-day-number">${day}</span>
                ${daySlots.length > 0 ? '<span class="calendar-day-indicator"></span>' : ''}
            `;
            
            grid.appendChild(dayElement);
        }
    }

    function selectDate(dateStr) {
        selectedDate = dateStr;
        
        // Actualizar visual del calendario
        document.querySelectorAll('.calendar-day.available').forEach(day => {
            day.classList.remove('selected');
        });
        document.querySelector(`[data-date="${dateStr}"]`)?.classList.add('selected');
        
        // Mostrar paso 2
        const step1 = document.getElementById('step1-dateSelection');
        const step2 = document.getElementById('step2-timeSelection');
        step1.classList.add('d-none');
        step2.classList.remove('d-none');
        
        renderTimeSlots(dateStr);
    }

    function renderTimeSlots(dateStr) {
        const dateDisplay = document.getElementById('selectedDateDisplay');
        const timeSlotsList = document.getElementById('timeSlotsList');
        
        // Formatear fecha para mostrar
        dateDisplay.textContent = formatDate(dateStr);
        
        const daySlots = slotsByDate[dateStr] || [];
        daySlots.sort((a, b) => a.start_time.localeCompare(b.start_time));
        
        let html = '<div class="d-flex flex-column gap-2">';
        
        daySlots.forEach(s => {
            const timeStr = `${formatTime(s.start_time)} - ${formatTime(s.end_time)}`;
            const locationName = s.location ? s.location.name : '';
            const spotsText = s.available_spots === 1 ? '1 lugar disponible' : `${s.available_spots} lugares disponibles`;
            
            html += `
            <label class="time-slot-card card rounded-3 p-3 mb-0" data-slot-id="${s.id}">
                <div class="d-flex align-items-center gap-3">
                    <input type="radio" name="timeSlot" value="${s.id}" class="slot-radio">
                    <div class="flex-grow-1">
                        <div class="fw-bold">${timeStr}</div>
                        ${locationName ? `<div class="text-muted small mt-1">
                            <i class="bi bi-geo-alt me-1"></i>${escapeHtml(locationName)}
                        </div>` : ''}
                    </div>
                    <div class="text-end">
                        <span class="badge bg-success-subtle text-success">${spotsText}</span>
                    </div>
                </div>
            </label>`;
        });
        
        html += '</div>';
        timeSlotsList.innerHTML = html;
        
        // Event listeners para selección
        timeSlotsList.querySelectorAll('.time-slot-card').forEach(card => {
            card.addEventListener('click', () => {
                timeSlotsList.querySelectorAll('.time-slot-card').forEach(c => c.classList.remove('selected'));
                card.classList.add('selected');
                card.querySelector('input').checked = true;
                selectedSlotId = parseInt(card.dataset.slotId);
                document.getElementById('btnConfirmSchedule').disabled = false;
            });
        });
    }

    function formatDateKey(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    function changeMonth(direction) {
        currentMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + direction, 1);
        renderCalendar();
    }

    function backToCalendar() {
        const step1 = document.getElementById('step1-dateSelection');
        const step2 = document.getElementById('step2-timeSelection');
        step1.classList.remove('d-none');
        step2.classList.add('d-none');
        selectedSlotId = null;
        document.getElementById('btnConfirmSchedule').disabled = true;
    }

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

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ==================== Campañas ====================

    async function loadActiveCampaigns() {
        try {
            const res = await fetch(`${API_BASE}/pantry/campaigns/active`);
            const campaigns = res.ok ? await res.json() : [];

            const campaignList = document.getElementById('campaignList');
            const campaignNeeds = document.getElementById('campaignNeeds');

            // Mostrar campañas si hay (qué artículos se necesitan)
            if (campaigns.length > 0) {
                campaignList.innerHTML = campaigns.map(c => {
                    // Mostrar el artículo que se necesita
                    const itemName = c.requested_item ? c.requested_item.name : c.name;
                    const progress = c.goal_quantity
                        ? `<span class="text-muted">(${c.collected_quantity}/${c.goal_quantity})</span>`
                        : '';
                    return `<div class="d-flex align-items-center gap-1">
                        <i class="bi bi-box-seam text-warning" style="font-size: 0.8rem;"></i>
                        <span>${escapeHtml(itemName)}</span>
                        ${progress}
                    </div>`;
                }).join('');
                campaignNeeds.classList.remove('d-none');
            } else {
                campaignNeeds.classList.add('d-none');
            }

            // Siempre mostrar la sección (porque también se puede donar ropa)
            document.getElementById('campaignSection').classList.remove('d-none');
            document.getElementById('willBringDonation').checked = false;
        } catch (e) {
            // Aún mostrar la sección para donación de ropa
            document.getElementById('campaignSection').classList.remove('d-none');
            document.getElementById('campaignNeeds').classList.add('d-none');
            document.getElementById('willBringDonation').checked = false;
            // Silently fail - campaigns are optional
        }
    }

    async function confirmSchedule() {
        if (!selectedSlotId) return;

        const btn = document.getElementById('btnConfirmSchedule');
        const btnText = document.getElementById('scheduleBtnText');
        const btnLoading = document.getElementById('scheduleBtnLoading');

        btn.disabled = true;
        btnText.classList.add('d-none');
        btnLoading.classList.remove('d-none');

        try {
            const res = await fetch(`${API_BASE}/appointments`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    garment_id: GARMENT_ID,
                    slot_id: selectedSlotId,
                    will_bring_donation: !!document.getElementById('willBringDonation')?.checked,
                }),
            });

            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.error || 'Error al agendar cita');
            }

            // Éxito
            scheduleModal.hide();
            document.getElementById('appointmentCode').textContent = data.appointment.code;
            successModal.show();

        } catch (e) {
            VisteTecUtils.showToast(e.message, 'danger');
            btn.disabled = false;
        } finally {
            btnText.classList.remove('d-none');
            btnLoading.classList.add('d-none');
        }
    }

    // Event listeners
    btnSchedule.addEventListener('click', () => {
        selectedSlotId = null;
        document.getElementById('btnConfirmSchedule').disabled = true;
        scheduleModal.show();
        loadAvailableSlots();
    });

    document.getElementById('btnConfirmSchedule').addEventListener('click', confirmSchedule);
    
    // Navegación del calendario
    document.getElementById('btnPrevMonth').addEventListener('click', () => changeMonth(-1));
    document.getElementById('btnNextMonth').addEventListener('click', () => changeMonth(1));
    document.getElementById('btnBackToCalendar').addEventListener('click', backToCalendar);

    // Init
    scheduleModal = new bootstrap.Modal(document.getElementById('scheduleModal'));
    successModal = new bootstrap.Modal(document.getElementById('successModal'));
    loadGarment();
})();
