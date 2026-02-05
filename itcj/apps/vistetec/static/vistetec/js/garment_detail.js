/**
 * VisteTec - Detalle de prenda
 */
(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1/catalog';
    const loadingState = document.getElementById('loadingState');
    const detailView = document.getElementById('garmentDetail');
    const notFoundState = document.getElementById('notFoundState');

    const conditionLabels = {
        nuevo: 'Nuevo',
        como_nuevo: 'Como nuevo',
        buen_estado: 'Buen estado',
        usado: 'Usado',
    };

    async function loadGarment() {
        try {
            const res = await fetch(`${API_BASE}/${GARMENT_ID}`);
            if (!res.ok) {
                showNotFound();
                return;
            }
            const g = await res.json();
            renderDetail(g);
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
            img.src = `/api/vistetec/v1/garments/image/${g.image_path}`;
            img.classList.remove('d-none');
            document.getElementById('noImageIcon').classList.add('d-none');
        }

        // Status badge
        const statusBadge = document.getElementById('garmentStatus');
        if (g.status === 'available') {
            statusBadge.textContent = 'Disponible';
            statusBadge.className = 'badge bg-success-subtle text-success mb-2';
        } else if (g.status === 'reserved') {
            statusBadge.textContent = 'Reservada';
            statusBadge.className = 'badge bg-warning-subtle text-warning mb-2';
        } else {
            statusBadge.textContent = g.status;
            statusBadge.className = 'badge bg-secondary-subtle text-secondary mb-2';
        }
    }

    function showNotFound() {
        loadingState.classList.add('d-none');
        notFoundState.classList.remove('d-none');
    }

    loadGarment();
})();
