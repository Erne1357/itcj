'use strict';
(function () {

    // Server data (set in init from dataset)
    let CAMPAIGN_ID = null;
    let CAN_MANAGE = false;
    let CAN_VALIDATE = false;
    let IS_ADMIN = false;

    let API_BASE = null;

    // ── Estado ────────────────────────────────────────────────────────────────

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

    // Timer handles for destroy
    let _reloadTimer1 = null;
    let _reloadTimer2 = null;
    let bulkDebounce = null;

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
            _reloadTimer1 = setTimeout(() => window.location.reload(), 1200);
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
            _reloadTimer2 = setTimeout(() => window.location.reload(), 1200);
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
            loadGroupsView();
        } catch (err) {
            HelpdeskUtils.showToast(err.message, 'danger');
        }
    };

    // ── Bulk assign modal ────────────────────────────────────────────────────

    function initBulkAssign() {
        const btnBulk = el('btn-bulk-assign');
        if (!btnBulk) return;

        btnBulk.addEventListener('click', () => {
            selectedItemIds.clear();
            el('bulk-selection-count').textContent = '0 seleccionados';
            el('btn-confirm-bulk-assign').disabled = true;
            const searchInput = el('bulk-search-input');
            if (searchInput) searchInput.value = '';
            const groupFilter = el('bulk-group-filter');
            if (groupFilter) groupFilter.value = '';
            // Poner spinner inmediatamente para que no se vea contenido viejo
            el('bulk-items-list').innerHTML =
                '<div class="text-center py-3"><i class="fas fa-spinner fa-spin text-primary"></i></div>';
            $('#modal-bulk-assign').modal('show');
        });

        // Cargar items + grupos cuando el modal terminó de abrirse
        $('#modal-bulk-assign').on('shown.bs.modal', async () => {
            await loadGroupFilterOptions();
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

        const groupFilter = el('bulk-group-filter');
        if (groupFilter) {
            groupFilter.addEventListener('change', () => {
                const s = el('bulk-search-input');
                searchAvailableItems(s ? s.value.trim() : '');
            });
        }

        const btnConfirm = el('btn-confirm-bulk-assign');
        if (btnConfirm) {
            btnConfirm.addEventListener('click', confirmBulkAssign);
        }
    }

    // Caché local de grupos del depto (id → nombre)
    let bulkGroupsCache = {};

    async function loadGroupFilterOptions() {
        const select = el('bulk-group-filter');
        if (!select || !campaignData) return;
        const deptId = campaignData.department_id;
        try {
            const res = await fetch(`/api/help-desk/v2/inventory/groups/department/${deptId}`);
            const data = await res.json();
            const groups = data.data || [];
            bulkGroupsCache = {};
            for (const g of groups) bulkGroupsCache[g.id] = g.name;
            // Repintar las opciones (mantener primeras 2 fijas)
            const fixed = `
                <option value="">📦 Todos los equipos</option>
                <option value="__global__">🌐 Sólo globales (sin grupo)</option>
            `;
            const grpOptions = groups.map(g =>
                `<option value="${g.id}">🏫 ${g.name}</option>`
            ).join('');
            select.innerHTML = fixed + grpOptions;
        } catch (err) {
            console.error('loadGroupFilterOptions:', err);
        }
    }

    async function searchAvailableItems(search) {
        const list = el('bulk-items-list');
        list.innerHTML = '<div class="text-center py-3"><i class="fas fa-spinner fa-spin text-primary"></i></div>';

        const deptId = campaignData ? campaignData.department_id : '';
        const groupFilter = el('bulk-group-filter');
        const filterVal = groupFilter ? groupFilter.value : '';

        const params = new URLSearchParams({ per_page: 200, sort: 'recent', include_relations: 'true' });
        if (deptId) params.set('department_id', deptId);
        if (search) params.set('search', search);

        try {
            const res = await fetch(`/api/help-desk/v2/inventory/items?${params}`);
            const data = await res.json();
            let items = (data.data || []).filter(i => !i.campaign_id);

            // Aplicar filtro por grupo
            if (filterVal === '__global__') {
                items = items.filter(i => !i.group_id);
            } else if (filterVal) {
                const gid = parseInt(filterVal, 10);
                items = items.filter(i => i.group_id === gid);
            }

            if (items.length === 0) {
                list.innerHTML = `<div class="text-center text-muted py-4 small">
                    <i class="fas fa-inbox fa-lg d-block mb-1"></i>Sin equipos disponibles con este filtro</div>`;
                return;
            }

            // Agrupar visualmente: Globales primero, luego por grupo
            const globals = items.filter(i => !i.group_id);
            const byGroup = {};
            for (const it of items) {
                if (!it.group_id) continue;
                const gid = it.group_id;
                if (!byGroup[gid]) byGroup[gid] = [];
                byGroup[gid].push(it);
            }

            const sections = [];
            if (globals.length > 0) {
                sections.push(`
                    <div class="bulk-section-header py-1 px-2 bg-light small fw-bold border-bottom">
                        🌐 Globales (sin grupo) <span class="badge badge-secondary ml-1">${globals.length}</span>
                    </div>
                    ${globals.map(_buildBulkCard).join('')}
                `);
            }
            for (const gid of Object.keys(byGroup)) {
                const gName = bulkGroupsCache[gid] || `Grupo ${gid}`;
                sections.push(`
                    <div class="bulk-section-header py-1 px-2 bg-info bg-opacity-10 small fw-bold border-bottom mt-2">
                        🏫 ${gName} <span class="badge badge-info ml-1">${byGroup[gid].length}</span>
                    </div>
                    ${byGroup[gid].map(_buildBulkCard).join('')}
                `);
            }

            list.innerHTML = sections.join('');
        } catch (err) {
            list.innerHTML = `<div class="text-center text-danger py-3 small">
                <i class="fas fa-exclamation-circle"></i> ${err.message}</div>`;
        }
    }

    function _buildBulkCard(item) {
        const sel = selectedItemIds.has(item.id);
        const desc = [item.brand, item.model].filter(Boolean).join(' ') +
                     (item.itcj_serial ? ' · ' + item.itcj_serial : '');
        const groupBadge = item.group_id
            ? `<span class="badge badge-info ml-1" title="Pertenece al grupo">
                   🏫 ${bulkGroupsCache[item.group_id] || 'Grupo'}
               </span>`
            : `<span class="badge badge-secondary ml-1" title="Equipo global sin grupo">
                   🌐 Global
               </span>`;
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
                        ${groupBadge}
                        ${item.is_locked ? '<i class="fas fa-lock text-warning ml-1" title="Bloqueado"></i>' : ''}
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
            loadGroupsView();
        } catch (err) {
            HelpdeskUtils.showToast(err.message, 'danger');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-check"></i> Asignar seleccionados';
        }
    }

    // ── Init ─────────────────────────────────────────────────────────────────

    function init() {
        const root = document.querySelector('[data-hd-page]');
        if (root) {
            CAMPAIGN_ID = parseInt(root.dataset.campaignId, 10);
            CAN_MANAGE = root.dataset.canManage === 'true';
            CAN_VALIDATE = root.dataset.canValidate === 'true';
            IS_ADMIN = root.dataset.isAdmin === 'true';
        }
        API_BASE = `/api/help-desk/v2/inventory/campaigns/${CAMPAIGN_ID}`;

        // Botón reabrir (puede estar en el DOM del alert)
        const btnReopen = el('btn-reopen');
        if (btnReopen) btnReopen.addEventListener('click', reopenCampaign);

        initBulkAssign();
        initGroups();
        loadCampaign().then(() => loadGroupsView());
    }

    function destroy() {
        // Clear reload timers
        if (_reloadTimer1 !== null) { clearTimeout(_reloadTimer1); _reloadTimer1 = null; }
        if (_reloadTimer2 !== null) { clearTimeout(_reloadTimer2); _reloadTimer2 = null; }
        // Clear bulk debounce
        if (bulkDebounce !== null) { clearTimeout(bulkDebounce); bulkDebounce = null; }
        // Dispose Bootstrap modals
        const modalIds = ['modal-new-group', 'modal-move-item', 'modal-bulk-assign'];
        modalIds.forEach(id => {
            const modalEl = document.getElementById(id);
            if (modalEl) {
                try { $(modalEl).modal('hide'); } catch (_) {}
                try { $(modalEl).modal('dispose'); } catch (_) {}
            }
        });
        // Clear window globals
        delete window.unassignItem;
        delete window.toggleBulkItem;
        delete window.reloadCampaignGroups;
    }

    // ── Grupos / Salones de la campaña ─────────────────────────────────────────

    let groupsData = [];

    function escGroup(str) {
        return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    async function loadGroupsView() {
        const cont = el('groups-container');
        if (!cont) return;
        try {
            const res = await fetch(`${API_BASE}/groups-view`);
            const json = await res.json();
            if (!json.success) throw new Error(json.error || 'Error');
            groupsData = json.data.groups || [];
            const canEdit = json.data.can_edit;
            el('groups-count').textContent = groupsData.length;

            const btnNew = el('btn-new-group');
            if (btnNew) btnNew.classList.toggle('d-none', !canEdit || !CAN_MANAGE);

            if (groupsData.length === 0 && (json.data.unassigned_count === 0)) {
                cont.innerHTML = '<p class="text-muted small text-center py-3 mb-0">Sin grupos en este departamento aún.</p>';
                return;
            }

            const groupCards = groupsData.map(g => renderGroupCard(g, canEdit)).join('');
            const unassigned = json.data.unassigned_items || [];
            let unassignedBlock = '';
            if (unassigned.length > 0) {
                unassignedBlock = `
                    <div class="card border-warning mb-2">
                        <div class="card-header py-2 bg-warning bg-opacity-10">
                            <strong class="small"><i class="fas fa-exclamation-circle"></i> Equipos de la campaña sin grupo (${unassigned.length})</strong>
                        </div>
                        <div class="card-body py-2 small">
                            ${unassigned.map(it => renderItemRow(it, null, canEdit)).join('')}
                        </div>
                    </div>`;
            }
            cont.innerHTML = unassignedBlock + groupCards;
        } catch (err) {
            cont.innerHTML = `<p class="text-danger small text-center py-3 mb-0">Error: ${escGroup(err.message)}</p>`;
        }
    }

    function renderGroupCard(g, canEdit) {
        const inCamp = g.items.filter(i => i.in_current_campaign).length;
        return `
            <div class="card border mb-2">
                <div class="card-header py-2 d-flex justify-content-between align-items-center">
                    <div>
                        <strong class="small">${escGroup(g.name)}</strong>
                        <span class="text-muted small ml-2">${escGroup(g.code)} · ${escGroup(g.group_type)}</span>
                        ${g.building ? `<span class="badge bg-light text-dark ml-1">${escGroup(g.building)}${g.floor ? ' P'+escGroup(g.floor) : ''}</span>` : ''}
                    </div>
                    <span class="badge bg-info text-white">${g.items_count} equipos${inCamp ? ' · ' + inCamp + ' en campaña' : ''}</span>
                </div>
                <div class="card-body py-2">
                    ${g.items.length === 0
                        ? '<p class="text-muted small mb-0 text-center">Sin equipos en este grupo</p>'
                        : g.items.map(it => renderItemRow(it, g.id, canEdit)).join('')}
                </div>
            </div>
        `;
    }

    function renderItemRow(item, groupId, canEdit) {
        const badge = item.in_current_campaign
            ? '<span class="badge bg-primary text-white ml-1">Campaña actual</span>'
            : '';
        const lockedBadge = item.is_locked ? '<i class="fas fa-lock text-warning ml-1" title="Validado/Bloqueado"></i>' : '';
        const actionBtns = canEdit && CAN_MANAGE
            ? `<button class="btn btn-sm btn-link p-0 ml-2 btn-move-item"
                       data-item-id="${item.id}"
                       data-item-label="${escGroup(item.inventory_number)} - ${escGroup(item.brand || '')} ${escGroup(item.model || '')}">
                   <i class="fas fa-arrows-alt"></i>
               </button>${groupId ? `<button class="btn btn-sm btn-link p-0 ml-1 text-danger btn-remove-from-group"
                       data-item-id="${item.id}" data-group-id="${groupId}" title="Quitar del grupo">
                   <i class="fas fa-times"></i>
               </button>` : ''}`
            : '';
        return `
            <div class="d-flex justify-content-between align-items-center border-bottom py-1">
                <div class="small">
                    <strong>${escGroup(item.inventory_number)}</strong>
                    <span class="text-muted">${escGroup(item.brand || '')} ${escGroup(item.model || '')}</span>
                    ${badge}${lockedBadge}
                </div>
                <div>${actionBtns}</div>
            </div>
        `;
    }

    function initGroups() {
        const btnNewGroup = el('btn-new-group');
        if (btnNewGroup) {
            btnNewGroup.addEventListener('click', () => {
                el('form-new-group').reset();
                $('#modal-new-group').modal('show');
            });
        }

        const formNewGroup = el('form-new-group');
        if (formNewGroup) {
            formNewGroup.addEventListener('submit', async (e) => {
                e.preventDefault();
                try {
                    const res = await fetch(`${API_BASE}/groups`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            name:            el('new-group-name').value.trim(),
                            group_type:      el('new-group-type').value,
                            building:        el('new-group-building').value.trim() || null,
                            floor:           el('new-group-floor').value.trim() || null,
                            location_notes:  el('new-group-location-notes').value.trim() || null,
                            description:     el('new-group-description').value.trim() || null,
                        }),
                    });
                    const data = await res.json();
                    if (!data.success) throw new Error(data.error || data.detail?.error || 'Error');
                    HelpdeskUtils.showToast('Grupo creado', 'success');
                    $('#modal-new-group').modal('hide');
                    loadGroupsView();
                } catch (err) {
                    HelpdeskUtils.showToast(err.message, 'danger');
                }
            });
        }

        // Delegated click handler para mover/quitar items
        const cont = el('groups-container');
        if (cont) {
            cont.addEventListener('click', async (e) => {
                const moveBtn = e.target.closest('.btn-move-item');
                if (moveBtn) {
                    openMoveItemModal(moveBtn.dataset.itemId, moveBtn.dataset.itemLabel);
                    return;
                }
                const removeBtn = e.target.closest('.btn-remove-from-group');
                if (removeBtn) {
                    const itemId = removeBtn.dataset.itemId;
                    const groupId = removeBtn.dataset.groupId;
                    const ok = await HelpdeskUtils.confirmDialog(
                        'Quitar equipo del grupo',
                        '¿Confirmas que quieres remover este equipo del grupo? Quedará sin grupo asignado.',
                        'Quitar',
                        'Cancelar'
                    );
                    if (!ok) return;
                    try {
                        const res = await fetch(`${API_BASE}/groups/${groupId}/items/${itemId}`, {method: 'DELETE'});
                        const data = await res.json();
                        if (!data.success) throw new Error(data.error || data.detail?.error || 'Error');
                        HelpdeskUtils.showToast('Equipo removido del grupo', 'success');
                        loadGroupsView();
                    } catch (err) {
                        HelpdeskUtils.showToast(err.message, 'danger');
                    }
                }
            });
        }

        const btnConfirmMove = el('btn-confirm-move-item');
        if (btnConfirmMove) {
            btnConfirmMove.addEventListener('click', async () => {
                const itemId = btnConfirmMove.dataset.itemId;
                const groupId = el('move-item-group-select').value;
                if (!itemId) return;
                try {
                    let res, data;
                    if (groupId) {
                        res = await fetch(`${API_BASE}/groups/${groupId}/items/${itemId}`, {method: 'POST'});
                    } else {
                        // Quitar de cualquier grupo: necesita group_id actual
                        const item = findItemAcrossGroups(itemId);
                        if (!item || !item.group_id) {
                            HelpdeskUtils.showToast('No tiene grupo asignado', 'info');
                            $('#modal-move-item').modal('hide');
                            return;
                        }
                        res = await fetch(`${API_BASE}/groups/${item.group_id}/items/${itemId}`, {method: 'DELETE'});
                    }
                    data = await res.json();
                    if (!data.success) throw new Error(data.error || data.detail?.error || 'Error');
                    HelpdeskUtils.showToast('Equipo movido', 'success');
                    $('#modal-move-item').modal('hide');
                    loadGroupsView();
                } catch (err) {
                    HelpdeskUtils.showToast(err.message, 'danger');
                }
            });
        }
    }

    function findItemAcrossGroups(itemId) {
        for (const g of groupsData) {
            for (const it of g.items) {
                if (String(it.id) === String(itemId)) return { ...it, group_id: g.id };
            }
        }
        return null;
    }

    function openMoveItemModal(itemId, itemLabel) {
        el('move-item-label').textContent = itemLabel;
        const select = el('move-item-group-select');
        select.innerHTML = '<option value="">— Sin grupo —</option>' +
            groupsData.map(g => `<option value="${g.id}">${escGroup(g.name)}</option>`).join('');
        const btn = el('btn-confirm-move-item');
        btn.dataset.itemId = itemId;
        $('#modal-move-item').modal('show');
    }

    // Exponer recarga manual de grupos
    window.reloadCampaignGroups = loadGroupsView;

    window.HelpdeskPage.page('inventory_campaigns_campaign_detail', { init: init, destroy: destroy });

})();
