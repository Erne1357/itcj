/**
 * VisteTec - Registro de Donaciones
 */
(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1';

    // State
    let donationType = null;
    let selectedDonorId = null;
    let successModal = null;

    // DOM Elements
    const step2 = document.getElementById('step2');
    const step3Garment = document.getElementById('step3Garment');
    const step3Pantry = document.getElementById('step3Pantry');
    const submitSection = document.getElementById('submitSection');

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
                submitSection.classList.remove('d-none');
            } else {
                step3Garment.classList.add('d-none');
                step3Pantry.classList.remove('d-none');
                submitSection.classList.add('d-none'); // Pantry not yet implemented
            }
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

    // Donor search (simplified - would need a real user search API)
    document.getElementById('btnSearchDonor').addEventListener('click', async () => {
        const query = donorSearch.value.trim();
        if (!query) return;

        // For now, just show a message - real implementation would search users
        donorSearchResults.classList.remove('d-none');
        donorSearchResults.innerHTML = `
            <div class="list-group-item text-muted small">
                <i class="bi bi-info-circle me-1"></i>
                Búsqueda de usuarios disponible próximamente.
                Use la opción "Donante externo" para ingresar el nombre.
            </div>
        `;
    });

    document.getElementById('btnClearDonor').addEventListener('click', () => {
        selectedDonorId = null;
        selectedDonor.classList.add('d-none');
        donorSearch.value = '';
    });

    // ==================== Submit ====================

    document.getElementById('btnSubmit').addEventListener('click', submitDonation);

    async function submitDonation() {
        if (donationType !== 'garment') {
            VisteTecUtils.showToast('Solo se pueden registrar donaciones de ropa por ahora', 'warning');
            return;
        }

        // Validate required fields
        const name = document.getElementById('garmentName').value.trim();
        const category = document.getElementById('garmentCategory').value;
        const condition = document.getElementById('garmentCondition').value;

        if (!name || !category || !condition) {
            VisteTecUtils.showToast('Completa los campos requeridos de la prenda', 'warning');
            return;
        }

        const btn = document.getElementById('btnSubmit');
        const btnText = document.getElementById('btnSubmitText');
        const btnLoading = document.getElementById('btnSubmitLoading');

        btn.disabled = true;
        btnText.classList.add('d-none');
        btnLoading.classList.remove('d-none');

        try {
            const payload = {
                garment: {
                    name,
                    category,
                    condition,
                    size: document.getElementById('garmentSize').value.trim() || null,
                    gender: document.getElementById('garmentGender').value || null,
                },
                notes: document.getElementById('garmentNotes').value.trim() || null,
            };

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

            const res = await fetch(`${API_BASE}/donations/garment`, {
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
})();
