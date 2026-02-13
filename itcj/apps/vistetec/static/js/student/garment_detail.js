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

    // ==================== Sistema de citas ====================

    async function loadAvailableSlots() {
        const slotsLoading = document.getElementById('slotsLoading');
        const noSlotsState = document.getElementById('noSlotsState');
        const slotsList = document.getElementById('slotsList');

        slotsLoading.classList.remove('d-none');
        noSlotsState.classList.add('d-none');
        slotsList.classList.add('d-none');
        document.getElementById('campaignSection').classList.add('d-none');

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
            const slots = await res.json();

            slotsLoading.classList.add('d-none');

            if (!slots.length) {
                noSlotsState.classList.remove('d-none');
                return;
            }

            renderSlots(slots);
            slotsList.classList.remove('d-none');

            // Cargar campañas activas
            loadActiveCampaigns();

        } catch (e) {
            console.error('Error cargando slots:', e);
            slotsLoading.classList.add('d-none');
            noSlotsState.classList.remove('d-none');
        }
    }

    function renderSlots(slots) {
        const slotsList = document.getElementById('slotsList');

        // Agrupar por fecha
        const grouped = {};
        slots.forEach(s => {
            const date = s.date;
            if (!grouped[date]) grouped[date] = [];
            grouped[date].push(s);
        });

        let html = '<div class="accordion" id="slotsAccordion">';
        Object.keys(grouped).sort().forEach((date, index) => {
            const dateSlots = grouped[date];
            const dateStr = formatDate(date);
            const accordionId = `collapse${index}`;

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
                     data-bs-parent="#slotsAccordion">
                    <div class="accordion-body p-2">
                        <div class="d-flex flex-column gap-2">`;

            dateSlots.forEach(s => {
                const timeStr = `${formatTime(s.start_time)} - ${formatTime(s.end_time)}`;
                const locationName = s.location ? s.location.name : '';
                const spotsText = s.available_spots === 1 ? '1 lugar' : `${s.available_spots} lugares`;

                html += `
                <label class="slot-card card border rounded-3 p-3 mb-0" data-slot-id="${s.id}">
                    <div class="d-flex align-items-center gap-3">
                        <input type="radio" name="slot" value="${s.id}" class="slot-radio">
                        <div class="flex-grow-1">
                            <div class="fw-bold">${timeStr}</div>
                            <div class="text-muted small">
                                ${locationName ? `<i class="bi bi-geo-alt me-1"></i>${escapeHtml(locationName)}` : '<i class="bi bi-clock me-1"></i>Horario disponible'}
                            </div>
                        </div>
                        <span class="badge bg-light text-dark">${spotsText}</span>
                    </div>
                </label>`;
            });

            html += `</div></div></div></div>`;
        });

        html += '</div>';
        slotsList.innerHTML = html;

        // Event listeners para selección
        slotsList.querySelectorAll('.slot-card').forEach(card => {
            card.addEventListener('click', () => {
                slotsList.querySelectorAll('.slot-card').forEach(c => c.classList.remove('selected'));
                card.classList.add('selected');
                card.querySelector('input').checked = true;
                selectedSlotId = parseInt(card.dataset.slotId);
                document.getElementById('btnConfirmSchedule').disabled = false;
            });
        });
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

    // Init
    scheduleModal = new bootstrap.Modal(document.getElementById('scheduleModal'));
    successModal = new bootstrap.Modal(document.getElementById('successModal'));
    loadGarment();
})();
