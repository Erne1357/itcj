/**
 * VisteTec - Mis Donaciones (Estudiante)
 */
(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1/donations';

    const list = document.getElementById('donationsList');
    const emptyState = document.getElementById('emptyState');
    const loadingState = document.getElementById('loadingState');
    const paginationNav = document.getElementById('paginationNav');
    const pagination = document.getElementById('pagination');

    let currentPage = 1;

    async function loadStats() {
        try {
            const res = await fetch(`${API_BASE}/stats?mine=true`);
            if (res.ok) {
                const data = await res.json();
                document.getElementById('statTotal').textContent = data.total_donations || 0;
                document.getElementById('statGarments').textContent = data.garments_donated || 0;
                document.getElementById('statPantry').textContent = data.pantry_donations || 0;
            }
        } catch (e) {
            console.error('Error cargando stats:', e);
        }
    }

    async function loadDonations(page = 1) {
        currentPage = page;
        loadingState.classList.remove('d-none');
        list.innerHTML = '';
        emptyState.classList.add('d-none');
        paginationNav.classList.add('d-none');

        try {
            const res = await fetch(`${API_BASE}/my-donations?page=${page}&per_page=10`);
            if (!res.ok) throw new Error('Error al cargar donaciones');
            const data = await res.json();

            loadingState.classList.add('d-none');

            if (!data.items.length) {
                emptyState.classList.remove('d-none');
                return;
            }

            renderDonations(data.items);
            renderPagination(data);

        } catch (e) {
            console.error(e);
            loadingState.classList.add('d-none');
            emptyState.classList.remove('d-none');
        }
    }

    function renderDonations(donations) {
        list.innerHTML = donations.map(d => {
            const dateStr = formatDate(d.created_at);
            const isGarment = d.donation_type === 'garment';

            let itemInfo = '';
            if (isGarment && d.garment) {
                itemInfo = `
                    <div class="d-flex align-items-center gap-2">
                        <i class="bi bi-bag-heart" style="color: #8B1538;"></i>
                        <span>${d.garment.name}</span>
                        ${d.garment.category ? `<span class="badge bg-light text-dark">${d.garment.category}</span>` : ''}
                    </div>`;
            } else if (!isGarment && d.pantry_item) {
                itemInfo = `
                    <div class="d-flex align-items-center gap-2">
                        <i class="bi bi-box-seam text-warning"></i>
                        <span>${d.pantry_item.name}</span>
                        <span class="badge bg-warning-subtle text-warning">x${d.quantity}</span>
                    </div>`;
            }

            // Campaign badge if donation is associated with a campaign
            const campaignBadge = d.campaign ? `
                <div class="mt-2">
                    <span class="badge bg-success-subtle text-success">
                        <i class="bi bi-flag me-1"></i>${d.campaign.name}
                    </span>
                </div>` : '';

            return `
            <div class="card donation-card type-${d.donation_type} mb-3 border-0 shadow-sm">
                <div class="card-body p-3">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <span class="badge bg-secondary-subtle text-secondary">${d.code}</span>
                        <small class="text-muted">${dateStr}</small>
                    </div>
                    ${itemInfo}
                    ${campaignBadge}
                    ${d.notes ? `<p class="text-muted small mb-0 mt-2"><i class="bi bi-chat-text me-1"></i>${d.notes}</p>` : ''}
                </div>
            </div>`;
        }).join('');
    }

    function renderPagination(data) {
        if (data.pages <= 1) {
            paginationNav.classList.add('d-none');
            return;
        }
        paginationNav.classList.remove('d-none');

        let html = '';
        html += `<li class="page-item ${data.has_prev ? '' : 'disabled'}">
                    <a class="page-link" href="#" data-page="${data.page - 1}">&laquo;</a>
                 </li>`;

        for (let i = 1; i <= data.pages; i++) {
            if (data.pages > 7 && i > 2 && i < data.pages - 1 && Math.abs(i - data.page) > 1) {
                if (i === 3 || i === data.pages - 2) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
                continue;
            }
            html += `<li class="page-item ${i === data.page ? 'active' : ''}">
                        <a class="page-link" href="#" data-page="${i}">${i}</a>
                     </li>`;
        }

        html += `<li class="page-item ${data.has_next ? '' : 'disabled'}">
                    <a class="page-link" href="#" data-page="${data.page + 1}">&raquo;</a>
                 </li>`;

        pagination.innerHTML = html;
    }

    function formatDate(dateStr) {
        const date = new Date(dateStr);
        const options = { day: 'numeric', month: 'short', year: 'numeric' };
        return date.toLocaleDateString('es-MX', options);
    }

    // Event listeners
    pagination.addEventListener('click', (e) => {
        e.preventDefault();
        const page = e.target.closest('[data-page]')?.dataset.page;
        if (page) loadDonations(parseInt(page));
    });

    // Init
    loadStats();
    loadDonations(1);
})();
