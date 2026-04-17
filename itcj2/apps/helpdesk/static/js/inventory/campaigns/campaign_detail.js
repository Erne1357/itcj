'use strict';
(function () {

    const API_BASE = `/api/help-desk/v2/inventory/campaigns/${CAMPAIGN_ID}`;

    // Estatus de campaña
    const STATUS_LABELS = {
        OPEN:               { label: 'Abierta',              cls: 'badge-primary' },
        PENDING_VALIDATION: { label: 'Pendiente validación', cls: 'badge-warning' },
        VALIDATED:          { label: 'Validada',             cls: 'badge-success' },
        REJECTED:           { label: 'Rechazada',            cls: 'badge-danger' },
    };

    // Estatus de equipo
    const ITEM_STATUS_LABELS = {
        ACTIVE:             { label: 'Activo',         cls: 'badge-success'   },
        PENDING_ASSIGNMENT: { label: 'Pendiente',      cls: 'badge-warning'   },
        MAINTENANCE:        { label: 'Mantenimiento',  cls: 'badge-info'      },
        DAMAGED:            { label: 'Dañado',         cls: 'badge-danger'    },
        RETIRED:            { label: 'Retirado',       cls: 'badge-secondary' },
        LOST:               { label: 'Extraviado',     cls: 'badge-dark'      },
    };

    function itemStatusBadge(status) {
        const s = ITEM_STATUS_LABELS[status] || { label: status, cls: 'badge-secondary' };
        return `<span class="badge ${s.cls}">${s.label}</span>`;
    }

    let campaignData = null;
    let selectedItemIds = new Set();

    // ── Helpers ──────────────────────────────────────────────────────────────

    function fmtDate(iso) {
        if (!iso) return '—';
        return new Date(iso).toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' });
    }

    function statusBadge(status) {
        const s = STATUS_LABELS[status] || { label: status, cls: 'badge-secondary' };
        return `<span class="badge ${s.cls} campaign-status-badge">${s.label}</span>`;
    }

    function el(id) { return document.getElementById(id); }

    // ── Cargar campaña ───────────────────────────────────────────────────────

    async function loadCampaign() {
        try {
            const res = await fetch(API_BASE);
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            campaignData = data.data;
            renderCampaign(campaignData);
            loadItems();
            renderValidationHistory(campaignData.validation_history || []);
        } catch (err) {
            el('campaign-folio').textContent = 'Error al cargar';
            HelpdeskUtils.showToast(err.message, 'danger');
        }
    }

    function renderCampaign(c) {
        el('campaign-folio').textContent = c.folio;
        el('campaign-status-badge').innerHTML = statusBadge(c.status);
        el('campaign-subtitle').textContent =
            `${c.department ? c.department.name : '—'} · ${fmtDate(c.started_at)}`;

        el('meta-department').textContent = c.department ? c.department.name : '—';
        el('meta-items').textContent = c.items_count;
        el('meta-created-by').textContent = c.created_by ? c.created_by.full_name : '—';
        el('meta-started-at').textContent = fmtDate(c.started_at);

        if (c.notes) {
            el('meta-notes').textContent = c.notes;
            el('meta-notes-row').style.removeProperty('display');
        }

        // Alertas de estado
        if (c.is_rejected) {
            el('rejection-alert').classList.remove('d-none');
            el('rejection-reason').textContent = c.rejection_reason
                ? ` Motivo: ${c.rejection_reason}`
                : '';
        }
        if (c.is_validated && c.validated_by) {
            el('validated-alert').classList.remove('d-none');
            el('validated-by-info').textContent =
                ` Aprobado por ${c.validated_by.full_name} el ${fmtDate(c.validated_at)}.`;
        }

        renderActions(c);
    }

    function renderActions(c) {
        const body = el('actions-body');
        let html = '';

        if (CAN_MANAGE && c.is_open) {
            html += `
            <button class="btn btn-warning btn-sm w-100" id="btn-close-campaign">
                <i class="fas fa-lock"></i> Cerrar y enviar a validación
            </button>
            <div id="col-unassign" class="d-none"></div>`;
            // Mostrar columna de desvincular en la tabla
            const colUnassign = document.getElementById('col-unassign');
            if (colUnassign) colUnassign.classList.remove('d-none');
            const itemsActions = el('items-actions');
            if (itemsActions) itemsActions.classList.remove('d-none');
        }

        if (CAN_VALIDATE && c.is_pending_validation) {
            html += `
            <a href="/help-desk/inventory/campaigns/${CAMPAIGN_ID}/validate"
               class="btn btn-primary btn-sm w-100">
                <i class="fas fa-clipboard-check"></i> Ir a validar inventario
            </a>`;
        }

        if (IS_ADMIN && c.is_rejected) {
            // El botón de reabrir ya está en el alert de rechazo
        }

        if (!html) {
            html = '<p class="text-muted small text-center mb-0">No hay acciones disponibles para tu rol.</p>';
        }

        body.innerHTML = html;

        // Bindear eventos
        const btnClose = el('btn-close-campaign');
        if (btnClose) {
            btnClose.addEventListener('click', closeCampaign);
        }
    }

    // ── Items ────────────────────────────────────────────────────────────────

    async function loadItems() {
        const tbody = el('items-tbody');
        const countBadge = el('items-count');

        try {
            const res = await fetch(`/api/help-desk/v2/inventory/items?campaign_id=${CAMPAIGN_ID}&per_page=100`);
            const data = await res.json();
            if (!data.success) throw new Error(data.error);

            const items = data.data || [];
            if (countBadge) countBadge.textContent = items.length;
            el('meta-items').textContent = items.length;

            if (items.length === 0) {
                tbody.innerHTML = `<tr><td colspan="6" class="text-center py-4 text-muted">
                    <i class="fas fa-inbox fa-lg mb-1 d-block"></i>Sin equipos aún</td></tr>`;
                return;
            }

            const isOpen = campaignData && campaignData.is_open;
            tbody.innerHTML = items.map(item => buildItemRow(item, isOpen)).join('');
        } catch (err) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center py-3 text-danger">
                Error: ${err.message}</td></tr>`;
        }
    }

    function buildItemRow(item, isOpen) {
        const lockedIcon = item.is_locked
            ? '<i class="fas fa-lock text-warning" title="Bloqueado"></i>'
            : '<i class="fas fa-lock-open text-muted" title="Sin bloquear"></i>';
        const predLink = item.predecessor_item_id
            ? `<a href="/help-desk/inventory/items/${item.predecessor_item_id}" target="_blank" class="small">
                 <i class="fas fa-history"></i> Ver
               </a>`
            : '—';
        const unassignBtn = (CAN_MANAGE && isOpen)
            ? `<td class="text-center">
                 <button class="btn btn-sm btn-outline-danger py-0 px-1" onclick="unassignItem(${item.id})" title="Desvincular">
                     <i class="fas fa-times"></i>
                 </button>
               </td>`
            : (CAN_MANAGE ? '<td></td>' : '');

        return `<tr>
            <td class="pl-3">
                <a href="/help-desk/inventory/items/${item.id}" target="_blank">
                    ${item.inventory_number}
                </a>
            </td>
            <td class="d-none d-sm-table-cell">${item.brand || '—'} ${item.model || ''}</td>
            <td class="d-none d-md-table-cell">${itemStatusBadge(item.status)}</td>
            <td class="d-none d-lg-table-cell">${predLink}</td>
            <td class="text-center">${lockedIcon}</td>
            ${unassignBtn}
        </tr>`;
    }

    // ── Historial de validaciones ─────────────────────────────────────────────

    async function renderValidationHistory() {
        const list = el('validation-history');
        try {
            const res = await fetch(`${API_BASE}/comparison`);
            const data = await res.json();
            // El historial viene en el detalle de la campaña, ya lo tenemos
        } catch (_) {}

        // Cargar historial directamente de los datos ya cargados
        if (!campaignData || !campaignData.validation_history) return;
        const history = campaignData.validation_history || [];
        if (history.length === 0) return;

        list.innerHTML = history.map(v => {
            const icon = v.action === 'APPROVED'
                ? '<i class="fas fa-check-circle text-success"></i>'
                : '<i class="fas fa-times-circle text-danger"></i>';
            return `<li class="list-group-item py-2 px-3">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        ${icon}
                        <strong class="ml-1">${v.action === 'APPROVED' ? 'Aprobada' : 'Rechazada'}</strong>
                        <div class="small text-muted">${v.performed_by ? v.performed_by.full_name : '—'}</div>
                        ${v.notes ? `<div class="small mt-1">${v.notes}</div>` : ''}
                    </div>
                    <small class="text-muted">${fmtDate(v.performed_at)}</small>
                </div>
            </li>`;
        }).join('');
    }

    // ── Cerrar campaña ───────────────────────────────────────────────────────

    async function closeCampaign() {
        const ok = await HelpdeskUtils.confirmDialog(
            '¿Cerrar campaña?',
            'Se enviará al jefe de departamento para su validación. Ya no podrás agregar más equipos sin reabrir.',
            'Cerrar y enviar'
        );
        if (!ok) return;

        const btn = el('btn-close-campaign');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Enviando...';

        try {
            const res = await fetch(`${API_BASE}/close`, { method: 'POST' });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            HelpdeskUtils.showToast(data.message, 'success');
            setTimeout(() => window.location.reload(), 1200);
        } catch (err) {
            HelpdeskUtils.showToast(err.message, 'danger');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-lock"></i> Cerrar y enviar a validación';
        }
    }

    // ── Reabrir campaña (admin) ───────────────────────────────────────────────

    async function reopenCampaign() {
        const ok = await HelpdeskUtils.confirmDialog(
            '¿Reabrir campaña rechazada?',
            'La campaña volverá a estado ABIERTA para que el CC pueda hacer correcciones.',
            'Reabrir'
        );
        if (!ok) return;

        try {
            const res = await fetch(`${API_BASE}/reopen`, { method: 'POST' });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            HelpdeskUtils.showToast(data.message, 'success');
            setTimeout(() => window.location.reload(), 1200);
        } catch (err) {
            HelpdeskUtils.showToast(err.message, 'danger');
        }
    }

    // ── Desvincular item ─────────────────────────────────────────────────────

    window.unassignItem = async function (itemId) {
        const ok = await HelpdeskUtils.confirmDialog(
            '¿Desvincular equipo?',
            'El equipo quedará sin campaña asignada.',
            'Desvincular'
        );
        if (!ok) return;

        try {
            const res = await fetch(`${API_BASE}/items/${itemId}`, { method: 'DELETE' });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            HelpdeskUtils.showToast('Equipo desvinculado', 'success');
            loadItems();
        } catch (err) {
            HelpdeskUtils.showToast(err.message, 'danger');
        }
    };

    // ── Bulk assign modal ────────────────────────────────────────────────────

    let bulkDebounce = null;

    function initBulkAssign() {
        const btnBulk = el('btn-bulk-assign');
        if (!btnBulk) return;

        btnBulk.addEventListener('click', () => {
            selectedItemIds.clear();
            el('bulk-selection-count').textContent = '0 seleccionados';
            el('btn-confirm-bulk-assign').disabled = true;
            const searchInput = el('bulk-search-input');
            if (searchInput) searchInput.value = '';
            // Poner spinner inmediatamente para que no se vea contenido viejo
            el('bulk-items-list').innerHTML =
                '<div class="text-center py-3"><i class="fas fa-spinner fa-spin text-primary"></i></div>';
            $('#modal-bulk-assign').modal('show');
        });

        // Cargar items sólo cuando el modal terminó de abrirse (evita conflictos con animación)
        $('#modal-bulk-assign').on('shown.bs.modal', () => {
            const searchInput = el('bulk-search-input');
            searchAvailableItems(searchInput ? searchInput.value.trim() : '');
        });

        const searchInput = el('bulk-search-input');
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                clearTimeout(bulkDebounce);
                bulkDebounce = setTimeout(() => searchAvailableItems(searchInput.value.trim()), 350);
            });
        }

        const btnConfirm = el('btn-confirm-bulk-assign');
        if (btnConfirm) {
            btnConfirm.addEventListener('click', confirmBulkAssign);
        }
    }

    async function searchAvailableItems(search) {
        const list = el('bulk-items-list');
        list.innerHTML = '<div class="text-center py-3"><i class="fas fa-spinner fa-spin text-primary"></i></div>';

        const deptId = campaignData ? campaignData.department_id : '';
        const params = new URLSearchParams({ per_page: 100, sort: 'recent' });
        if (deptId) params.set('department_id', deptId);
        if (search) params.set('search', search);

        try {
            const res = await fetch(`/api/help-desk/v2/inventory/items?${params}`);
            const data = await res.json();
            const items = (data.data || []).filter(i => !i.campaign_id);

            if (items.length === 0) {
                list.innerHTML = `<div class="text-center text-muted py-4 small">
                    <i class="fas fa-inbox fa-lg d-block mb-1"></i>Sin equipos disponibles para asignar</div>`;
                return;
            }

            list.innerHTML = items.map(i => _buildBulkCard(i)).join('');
        } catch (err) {
            list.innerHTML = `<div class="text-center text-danger py-3 small">
                <i class="fas fa-exclamation-circle"></i> ${err.message}</div>`;
        }
    }

    function _buildBulkCard(item) {
        const sel = selectedItemIds.has(item.id);
        const desc = [item.brand, item.model].filter(Boolean).join(' ') +
                     (item.itcj_serial ? ' · ' + item.itcj_serial : '');
        return `
        <div class="bulk-item-card${sel ? ' selected' : ''}" data-id="${item.id}"
             onclick="toggleBulkItem(${item.id})">
            <div class="d-flex align-items-center px-3 py-2">
                <div class="bulk-item-icon mr-3">
                    <i class="fas ${sel ? 'fa-check-circle' : 'fa-circle'}"></i>
                </div>
                <div class="flex-grow-1 overflow-hidden">
                    <div class="d-flex align-items-center flex-wrap">
                        <strong class="mr-2">${item.inventory_number}</strong>
                        ${itemStatusBadge(item.status)}
                        ${item.is_locked ? '<i class="fas fa-lock text-warning" title="Bloqueado"></i>' : ''}
                    </div>
                    ${desc ? `<div class="small text-muted text-truncate">${desc}</div>` : ''}
                </div>
            </div>
        </div>`;
    }

    window.toggleBulkItem = function (itemId) {
        if (selectedItemIds.has(itemId)) selectedItemIds.delete(itemId);
        else selectedItemIds.add(itemId);

        // Actualizar visual de la card sin re-renderizar la lista
        const card = document.querySelector(`.bulk-item-card[data-id="${itemId}"]`);
        if (card) {
            const sel = selectedItemIds.has(itemId);
            card.classList.toggle('selected', sel);
            const icon = card.querySelector('.bulk-item-icon i');
            if (icon) icon.className = `fas ${sel ? 'fa-check-circle' : 'fa-circle'}`;
        }

        const count = selectedItemIds.size;
        el('bulk-selection-count').textContent = `${count} seleccionado${count !== 1 ? 's' : ''}`;
        el('btn-confirm-bulk-assign').disabled = count === 0;
    };

    async function confirmBulkAssign() {
        if (selectedItemIds.size === 0) return;
        const btn = el('btn-confirm-bulk-assign');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

        try {
            const res = await fetch(`${API_BASE}/items/bulk-assign`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_ids: [...selectedItemIds] }),
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            $('#modal-bulk-assign').modal('hide');
            HelpdeskUtils.showToast(data.message, 'success');
            loadItems();
        } catch (err) {
            HelpdeskUtils.showToast(err.message, 'danger');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-check"></i> Asignar seleccionados';
        }
    }

    // ── Init ─────────────────────────────────────────────────────────────────

    function init() {
        // Botón reabrir (puede estar en el DOM del alert)
        const btnReopen = el('btn-reopen');
        if (btnReopen) btnReopen.addEventListener('click', reopenCampaign);

        initBulkAssign();
        loadCampaign();
    }

    document.addEventListener('DOMContentLoaded', init);

})();
