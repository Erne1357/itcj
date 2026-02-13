(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1/pantry';
    let currentPage = 1;
    let pantryItems = [];

    // ==================== INIT ====================

    document.addEventListener('DOMContentLoaded', () => {
        loadPantryItems();
        loadActiveCampaigns();
        loadAllCampaigns();
        setupEventListeners();
    });

    function setupEventListeners() {
        document.getElementById('btnNewCampaign').addEventListener('click', openNewCampaignModal);
        document.getElementById('btnSaveCampaign').addEventListener('click', saveCampaign);
    }

    // ==================== LOAD PANTRY ITEMS (for select) ====================

    async function loadPantryItems() {
        try {
            const res = await fetch(`${API_BASE}/items?is_active=true&per_page=100`);
            if (!res.ok) return;
            const data = await res.json();
            pantryItems = data.items;

            const select = document.getElementById('campaignItem');
            select.innerHTML = '<option value="">Sin artículo específico</option>';
            pantryItems.forEach(item => {
                const opt = document.createElement('option');
                opt.value = item.id;
                opt.textContent = `${item.name} (${item.unit || 'pzas'})`;
                select.appendChild(opt);
            });
        } catch (err) {
            console.error('Error cargando items:', err);
        }
    }

    // ==================== ACTIVE CAMPAIGNS ====================

    async function loadActiveCampaigns() {
        const container = document.getElementById('activeCampaigns');
        const empty = document.getElementById('noActiveCampaigns');

        try {
            const res = await fetch(`${API_BASE}/campaigns/active`);
            if (!res.ok) throw new Error('Error');
            const campaigns = await res.json();

            if (campaigns.length === 0) {
                container.innerHTML = '';
                empty.classList.remove('d-none');
                return;
            }

            empty.classList.add('d-none');
            container.innerHTML = campaigns.map(renderActiveCampaignCard).join('');
        } catch (err) {
            console.error('Error cargando campañas activas:', err);
        }
    }

    function renderActiveCampaignCard(campaign) {
        const progress = campaign.progress_percentage;
        const itemName = campaign.requested_item ? campaign.requested_item.name : 'Varios artículos';
        const dates = formatDateRange(campaign.start_date, campaign.end_date);

        return `
            <div class="col-12 col-md-6">
                <div class="card campaign-card border-0 shadow-sm h-100">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-start mb-2">
                            <h6 class="fw-bold mb-0">${escapeHtml(campaign.name)}</h6>
                            <span class="badge campaign-badge-active">Activa</span>
                        </div>
                        ${campaign.description ? `<p class="text-muted small mb-2">${escapeHtml(campaign.description)}</p>` : ''}
                        <div class="mb-2">
                            <small class="text-muted"><i class="bi bi-box-seam me-1"></i>${escapeHtml(itemName)}</small>
                        </div>
                        ${dates ? `<div class="campaign-dates mb-2"><i class="bi bi-calendar3 me-1"></i>${dates}</div>` : ''}
                        ${campaign.goal_quantity ? `
                            <div class="campaign-stats d-flex justify-content-between mb-1">
                                <span><strong>${campaign.collected_quantity}</strong> / ${campaign.goal_quantity}</span>
                                <span class="fw-bold" style="color: #8B1538;">${progress}%</span>
                            </div>
                            <div class="progress">
                                <div class="progress-bar" role="progressbar" style="width: ${progress}%"></div>
                            </div>
                        ` : `
                            <div class="campaign-stats">
                                <span>Recolectado: <strong>${campaign.collected_quantity}</strong></span>
                            </div>
                        `}
                        <div class="mt-3 d-flex gap-2">
                            <button class="btn btn-sm btn-outline-secondary" onclick="window._campaignEdit(${campaign.id})">
                                <i class="bi bi-pencil me-1"></i>Editar
                            </button>
                            <button class="btn btn-sm btn-outline-danger" onclick="window._campaignDeactivate(${campaign.id}, '${escapeHtml(campaign.name)}')">
                                <i class="bi bi-stop-circle me-1"></i>Cerrar
                            </button>
                        </div>
                    </div>
                </div>
            </div>`;
    }

    // ==================== ALL CAMPAIGNS ====================

    async function loadAllCampaigns() {
        const container = document.getElementById('allCampaignsBody');
        const loading = document.getElementById('campaignsLoading');

        loading.classList.remove('d-none');

        try {
            const res = await fetch(`${API_BASE}/campaigns?page=${currentPage}&per_page=10`);
            if (!res.ok) throw new Error('Error');
            const data = await res.json();

            loading.classList.add('d-none');
            container.innerHTML = '';

            if (data.items.length === 0) {
                container.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">No hay campañas registradas</td></tr>';
                return;
            }

            data.items.forEach(campaign => {
                container.insertAdjacentHTML('beforeend', renderCampaignRow(campaign));
            });

            renderPagination(data);
        } catch (err) {
            loading.classList.add('d-none');
            VisteTecUtils.showToast('Error cargando campañas', 'danger');
        }
    }

    function renderCampaignRow(campaign) {
        const statusBadge = campaign.is_active
            ? '<span class="badge campaign-badge-active">Activa</span>'
            : '<span class="badge campaign-badge-ended">Cerrada</span>';

        const progress = campaign.goal_quantity
            ? `${campaign.collected_quantity}/${campaign.goal_quantity} (${campaign.progress_percentage}%)`
            : `${campaign.collected_quantity}`;

        const itemName = campaign.requested_item ? campaign.requested_item.name : '-';

        return `
            <tr>
                <td class="fw-medium">${escapeHtml(campaign.name)}</td>
                <td>${escapeHtml(itemName)}</td>
                <td>${progress}</td>
                <td>${statusBadge}</td>
                <td>
                    <div class="d-flex gap-1">
                        <button class="btn btn-sm btn-outline-secondary" onclick="window._campaignEdit(${campaign.id})" title="Editar">
                            <i class="bi bi-pencil"></i>
                        </button>
                        ${campaign.is_active ? `
                            <button class="btn btn-sm btn-outline-danger" onclick="window._campaignDeactivate(${campaign.id}, '${escapeHtml(campaign.name)}')" title="Cerrar">
                                <i class="bi bi-stop-circle"></i>
                            </button>
                        ` : ''}
                    </div>
                </td>
            </tr>`;
    }

    function renderPagination(data) {
        const nav = document.getElementById('campaignsPaginationNav');
        const container = document.getElementById('campaignsPagination');

        if (data.pages <= 1) {
            nav.classList.add('d-none');
            return;
        }

        nav.classList.remove('d-none');
        let html = '';
        for (let i = 1; i <= data.pages; i++) {
            html += `<li class="page-item ${i === data.page ? 'active' : ''}">
                <a class="page-link" href="#" onclick="window._campaignGoPage(${i}); return false;">${i}</a>
            </li>`;
        }
        container.innerHTML = html;
    }

    // ==================== CRUD ====================

    function openNewCampaignModal() {
        document.getElementById('campaignModalTitle').textContent = 'Nueva campaña';
        document.getElementById('campaignForm').reset();
        document.getElementById('campaignId').value = '';
        const modal = new bootstrap.Modal(document.getElementById('campaignModal'));
        modal.show();
    }

    async function saveCampaign() {
        const campaignId = document.getElementById('campaignId').value;
        const name = document.getElementById('campaignName').value.trim();
        const description = document.getElementById('campaignDescription').value.trim();
        const requestedItemId = document.getElementById('campaignItem').value;
        const goalQuantity = document.getElementById('campaignGoal').value;
        const startDate = document.getElementById('campaignStartDate').value;
        const endDate = document.getElementById('campaignEndDate').value;

        if (!name) {
            VisteTecUtils.showToast('El nombre es requerido', 'warning');
            return;
        }

        const data = {
            name,
            description: description || null,
            requested_item_id: requestedItemId ? parseInt(requestedItemId) : null,
            goal_quantity: goalQuantity ? parseInt(goalQuantity) : null,
            start_date: startDate || null,
            end_date: endDate || null,
        };

        const url = campaignId ? `${API_BASE}/campaigns/${campaignId}` : `${API_BASE}/campaigns`;
        const method = campaignId ? 'PUT' : 'POST';

        try {
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            const result = await res.json();

            if (!res.ok) {
                VisteTecUtils.showToast(result.error || 'Error', 'danger');
                return;
            }

            bootstrap.Modal.getInstance(document.getElementById('campaignModal')).hide();
            VisteTecUtils.showToast(result.message, 'success');
            loadActiveCampaigns();
            loadAllCampaigns();
        } catch (err) {
            VisteTecUtils.showToast('Error de conexión', 'danger');
        }
    }

    async function editCampaign(campaignId) {
        try {
            const res = await fetch(`${API_BASE}/campaigns/${campaignId}`);
            if (!res.ok) return;
            const campaign = await res.json();

            document.getElementById('campaignModalTitle').textContent = 'Editar campaña';
            document.getElementById('campaignId').value = campaign.id;
            document.getElementById('campaignName').value = campaign.name;
            document.getElementById('campaignDescription').value = campaign.description || '';
            document.getElementById('campaignItem').value = campaign.requested_item_id || '';
            document.getElementById('campaignGoal').value = campaign.goal_quantity || '';
            document.getElementById('campaignStartDate').value = campaign.start_date || '';
            document.getElementById('campaignEndDate').value = campaign.end_date || '';

            const modal = new bootstrap.Modal(document.getElementById('campaignModal'));
            modal.show();
        } catch (err) {
            VisteTecUtils.showToast('Error cargando campaña', 'danger');
        }
    }

    async function deactivateCampaign(campaignId, campaignName) {
        const confirmed = await VisteTecUtils.confirmModal(
            '¿Cerrar campaña?',
            `Se cerrará la campaña "${campaignName}". Los datos de progreso se mantendrán.`
        );

        if (!confirmed) return;

        try {
            const res = await fetch(`${API_BASE}/campaigns/${campaignId}`, { method: 'DELETE' });
            const result = await res.json();

            if (!res.ok) {
                VisteTecUtils.showToast(result.error || 'Error', 'danger');
                return;
            }

            VisteTecUtils.showToast('Campaña cerrada', 'success');
            loadActiveCampaigns();
            loadAllCampaigns();
        } catch (err) {
            VisteTecUtils.showToast('Error de conexión', 'danger');
        }
    }

    // ==================== UTILS ====================

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function formatDateRange(start, end) {
        if (!start && !end) return '';
        const opts = { day: 'numeric', month: 'short', year: 'numeric' };
        const s = start ? new Date(start + 'T00:00:00').toLocaleDateString('es-MX', opts) : '?';
        const e = end ? new Date(end + 'T00:00:00').toLocaleDateString('es-MX', opts) : '?';
        return `${s} — ${e}`;
    }

    // ==================== GLOBAL HANDLERS ====================

    window._campaignGoPage = function (page) {
        currentPage = page;
        loadAllCampaigns();
    };

    window._campaignEdit = editCampaign;
    window._campaignDeactivate = deactivateCampaign;
})();
