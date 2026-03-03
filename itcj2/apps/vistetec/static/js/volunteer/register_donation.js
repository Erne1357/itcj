/**
 * VisteTec - Registro de Donaciones
 */
(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1';

    // State
    let donationType = null;
    let selectedDonorId = null;
    let selectedCampaignId = null;
    let successModal = null;
    let pantryItems = [];
    let activeCampaigns = [];
    let searchTimeout = null;

    // DOM Elements
    const step2 = document.getElementById('step2');
    const step3Garment = document.getElementById('step3Garment');
    const step3Pantry = document.getElementById('step3Pantry');
    const submitSection = document.getElementById('submitSection');

    // ==================== URL Parameters (Pre-fill from appointment) ====================

    function getUrlParams() {
        const params = new URLSearchParams(window.location.search);
        return {
            donorId: params.get('donor_id'),
            controlNumber: params.get('control_number'),
            donorName: params.get('donor_name'),
        };
    }

    async function prefillFromUrl() {
        const params = getUrlParams();

        if (params.donorId) {
            selectedDonorId = parseInt(params.donorId, 10);
            const displayName = params.donorName
                ? decodeURIComponent(params.donorName)
                : (params.controlNumber || `ID: ${params.donorId}`);

            selectedDonorName.textContent = params.controlNumber
                ? `${displayName} (${params.controlNumber})`
                : displayName;
            selectedDonor.classList.remove('d-none');
            donorSearch.value = params.controlNumber || '';

            // Show step 2 since we already have donor info
            step2.classList.remove('d-none');
        }
    }

    // ==================== Step 1: Donation Type ====================

    document.querySelectorAll('.donation-type-card').forEach(card => {
        card.addEventListener('click', () => {
            // Remove previous selection
            document.querySelectorAll('.donation-type-card').forEach(c => c.classList.remove('selected'));

            // Select this one
            card.classList.add('selected');
            card.querySelector('input').checked = true;
            donationType = card.dataset.type;

            // Show step 2
            step2.classList.remove('d-none');

            // Show appropriate step 3
            if (donationType === 'garment') {
                step3Garment.classList.remove('d-none');
                step3Pantry.classList.add('d-none');
            } else {
                step3Garment.classList.add('d-none');
                step3Pantry.classList.remove('d-none');
                loadPantryItems();
                loadActiveCampaigns();
            }

            submitSection.classList.remove('d-none');
        });
    });

    // ==================== Step 2: Donor Info ====================

    const isAnonymous = document.getElementById('isAnonymous');
    const donorFields = document.getElementById('donorFields');
    const isExternalDonor = document.getElementById('isExternalDonor');
    const externalDonorFields = document.getElementById('externalDonorFields');
    const donorSearch = document.getElementById('donorSearch');
    const donorSearchResults = document.getElementById('donorSearchResults');
    const selectedDonor = document.getElementById('selectedDonor');
    const selectedDonorName = document.getElementById('selectedDonorName');

    isAnonymous.addEventListener('change', () => {
        if (isAnonymous.checked) {
            donorFields.classList.add('d-none');
            selectedDonorId = null;
            selectedDonor.classList.add('d-none');
        } else {
            donorFields.classList.remove('d-none');
        }
    });

    isExternalDonor.addEventListener('change', () => {
        if (isExternalDonor.checked) {
            externalDonorFields.classList.remove('d-none');
            donorSearch.parentElement.parentElement.classList.add('d-none');
            selectedDonor.classList.add('d-none');
            selectedDonorId = null;
        } else {
            externalDonorFields.classList.add('d-none');
            donorSearch.parentElement.parentElement.classList.remove('d-none');
        }
    });

    // Real donor search
    async function searchDonors(query) {
        if (query.length < 2) {
            donorSearchResults.classList.add('d-none');
            return;
        }

        try {
            const res = await fetch(`${API_BASE}/donations/search-donors?q=${encodeURIComponent(query)}`);
            if (!res.ok) throw new Error('Error en búsqueda');
            const donors = await res.json();

            donorSearchResults.classList.remove('d-none');

            if (donors.length === 0) {
                donorSearchResults.innerHTML = `
                    <div class="list-group-item text-muted small">
                        <i class="bi bi-info-circle me-1"></i>
                        No se encontraron estudiantes con ese criterio
                    </div>
                `;
                return;
            }

            donorSearchResults.innerHTML = donors.map(d => `
                <button type="button" class="list-group-item list-group-item-action donor-result"
                        data-id="${d.id}" data-name="${escapeHtml(d.name)}" data-control="${d.control_number || ''}">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong>${escapeHtml(d.name)}</strong>
                            ${d.control_number ? `<span class="text-muted ms-2">${d.control_number}</span>` : ''}
                        </div>
                        <i class="bi bi-plus-circle text-success"></i>
                    </div>
                </button>
            `).join('');

            // Add click listeners to results
            donorSearchResults.querySelectorAll('.donor-result').forEach(btn => {
                btn.addEventListener('click', () => selectDonor(btn));
            });
        } catch (err) {
            console.error('Error buscando donantes:', err);
            donorSearchResults.innerHTML = `
                <div class="list-group-item text-danger small">
                    <i class="bi bi-exclamation-circle me-1"></i>
                    Error en la búsqueda
                </div>
            `;
            donorSearchResults.classList.remove('d-none');
        }
    }

    function selectDonor(btn) {
        selectedDonorId = parseInt(btn.dataset.id, 10);
        const name = btn.dataset.name;
        const control = btn.dataset.control;

        selectedDonorName.textContent = control ? `${name} (${control})` : name;
        selectedDonor.classList.remove('d-none');
        donorSearchResults.classList.add('d-none');
        donorSearch.value = '';
    }

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // Search on button click
    document.getElementById('btnSearchDonor').addEventListener('click', () => {
        const query = donorSearch.value.trim();
        searchDonors(query);
    });

    // Search on input with debounce
    donorSearch.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            const query = donorSearch.value.trim();
            searchDonors(query);
        }, 300);
    });

    // Search on Enter key
    donorSearch.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            const query = donorSearch.value.trim();
            searchDonors(query);
        }
    });

    document.getElementById('btnClearDonor').addEventListener('click', () => {
        selectedDonorId = null;
        selectedDonor.classList.add('d-none');
        donorSearch.value = '';
        donorSearchResults.classList.add('d-none');
    });

    // ==================== Step 3: Pantry Items & Campaigns ====================

    async function loadPantryItems() {
        if (pantryItems.length > 0) return;

        const select = document.getElementById('pantryItem');
        const loading = document.getElementById('pantryItemsLoading');

        loading.classList.remove('d-none');

        try {
            const res = await fetch(`${API_BASE}/pantry/items?is_active=true&per_page=100`);
            if (!res.ok) throw new Error('Error cargando artículos');
            const data = await res.json();
            pantryItems = data.items;

            select.innerHTML = '<option value="">Seleccionar artículo...</option>';
            pantryItems.forEach(item => {
                const opt = document.createElement('option');
                opt.value = item.id;
                opt.textContent = item.name;
                opt.dataset.unit = item.unit || 'piezas';
                opt.dataset.category = item.category || '';
                select.appendChild(opt);
            });
        } catch (err) {
            VisteTecUtils.showToast('Error cargando artículos de despensa', 'danger');
        } finally {
            loading.classList.add('d-none');
        }
    }

    async function loadActiveCampaigns() {
        if (activeCampaigns.length > 0) return;

        const select = document.getElementById('pantryCampaign');
        if (!select) return;

        try {
            const res = await fetch(`${API_BASE}/pantry/campaigns/active`);
            if (!res.ok) throw new Error('Error cargando campañas');
            activeCampaigns = await res.json();

            select.innerHTML = '<option value="">Sin asociar a campaña</option>';
            activeCampaigns.forEach(campaign => {
                const opt = document.createElement('option');
                opt.value = campaign.id;
                opt.textContent = `${campaign.name}${campaign.requested_item ? ` (${campaign.requested_item.name})` : ''}`;
                opt.dataset.itemId = campaign.requested_item_id || '';
                select.appendChild(opt);
            });
        } catch (err) {
            console.error('Error cargando campañas:', err);
        }
    }

    document.getElementById('pantryItem').addEventListener('change', function () {
        const unitInput = document.getElementById('pantryUnit');
        const selected = this.options[this.selectedIndex];
        unitInput.value = selected.value ? selected.dataset.unit : '';

        // Auto-select matching campaign if exists
        const campaignSelect = document.getElementById('pantryCampaign');
        if (campaignSelect && selected.value) {
            const itemId = selected.value;
            for (let i = 0; i < campaignSelect.options.length; i++) {
                if (campaignSelect.options[i].dataset.itemId === itemId) {
                    campaignSelect.selectedIndex = i;
                    selectedCampaignId = parseInt(campaignSelect.value, 10) || null;
                    break;
                }
            }
        }
    });

    // Campaign selection
    const campaignSelect = document.getElementById('pantryCampaign');
    if (campaignSelect) {
        campaignSelect.addEventListener('change', function () {
            selectedCampaignId = this.value ? parseInt(this.value, 10) : null;

            // Auto-select matching item if campaign has requested_item
            const selected = this.options[this.selectedIndex];
            const itemId = selected.dataset.itemId;
            if (itemId) {
                const itemSelect = document.getElementById('pantryItem');
                itemSelect.value = itemId;
                itemSelect.dispatchEvent(new Event('change'));
            }
        });
    }

    // ==================== Submit ====================

    document.getElementById('btnSubmit').addEventListener('click', submitDonation);

    async function submitDonation() {
        const btn = document.getElementById('btnSubmit');
        const btnText = document.getElementById('btnSubmitText');
        const btnLoading = document.getElementById('btnSubmitLoading');

        let url, payload;

        if (donationType === 'garment') {
            const name = document.getElementById('garmentName').value.trim();
            const category = document.getElementById('garmentCategory').value;
            const condition = document.getElementById('garmentCondition').value;

            if (!name || !category || !condition) {
                VisteTecUtils.showToast('Completa los campos requeridos de la prenda', 'warning');
                return;
            }

            url = `${API_BASE}/donations/garment`;
            payload = {
                garment: {
                    name,
                    category,
                    condition,
                    size: document.getElementById('garmentSize').value.trim() || null,
                    gender: document.getElementById('garmentGender').value || null,
                },
                notes: document.getElementById('garmentNotes').value.trim() || null,
            };
        } else if (donationType === 'pantry') {
            const pantryItemId = document.getElementById('pantryItem').value;
            const quantity = parseInt(document.getElementById('pantryQuantity').value, 10);

            if (!pantryItemId) {
                VisteTecUtils.showToast('Selecciona un artículo de despensa', 'warning');
                return;
            }
            if (!quantity || quantity < 1) {
                VisteTecUtils.showToast('La cantidad debe ser al menos 1', 'warning');
                return;
            }

            url = `${API_BASE}/donations/pantry`;
            payload = {
                pantry_item_id: parseInt(pantryItemId, 10),
                quantity,
                notes: document.getElementById('pantryNotes').value.trim() || null,
            };

            // Add campaign if selected
            const campaignSel = document.getElementById('pantryCampaign');
            if (campaignSel && campaignSel.value) {
                payload.campaign_id = parseInt(campaignSel.value, 10);
            }
        } else {
            VisteTecUtils.showToast('Selecciona un tipo de donación', 'warning');
            return;
        }

        // Donor info
        if (!isAnonymous.checked) {
            if (selectedDonorId) {
                payload.donor_id = selectedDonorId;
            } else if (isExternalDonor.checked) {
                const externalName = document.getElementById('externalDonorName').value.trim();
                if (externalName) {
                    payload.donor_name = externalName;
                }
            }
        }

        btn.disabled = true;
        btnText.classList.add('d-none');
        btnLoading.classList.remove('d-none');

        try {
            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.error || 'Error al registrar donación');
            }

            // Success
            document.getElementById('donationCode').textContent = data.donation.code;
            successModal.show();

        } catch (e) {
            VisteTecUtils.showToast(e.message, 'danger');
        } finally {
            btn.disabled = false;
            btnText.classList.remove('d-none');
            btnLoading.classList.add('d-none');
        }
    }

    // Init
    successModal = new bootstrap.Modal(document.getElementById('successModal'));
    prefillFromUrl();
})();
