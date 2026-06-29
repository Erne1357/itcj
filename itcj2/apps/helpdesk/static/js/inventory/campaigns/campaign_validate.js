'use strict';
(function () {

    // Server data (set in init from dataset)
    let CAMPAIGN_ID = null;
    let API_BASE = null;

    let validationData = null;
    let currentView = 'all'; // all | new | existing | changes

    // Timer handles for destroy
    let _redirectTimer1 = null;
    let _redirectTimer2 = null;

    // ── Helpers ──────────────────────────────────────────────────────────────

    const ITEM_STATUS_LABELS = {
        ACTIVE:             'Activo',
        PENDING_ASSIGNMENT: 'Pendiente',
        MAINTENANCE:        'Mantenimiento',
        DAMAGED:            'Dañado',
        RETIRED:            'Retirado',
        LOST:               'Extraviado',
    };

    const ITEM_STATUS_COLORS = {
        ACTIVE:             'badge-success',
        PENDING_ASSIGNMENT: 'badge-warning',
        MAINTENANCE:        'badge-info',
        DAMAGED:            'badge-danger',
        RETIRED:            'badge-secondary',
        LOST:               'badge-dark',
    };

    function itemStatusBadge(status, extraStyle) {
        const label = ITEM_STATUS_LABELS[status] || status;
        const cls   = ITEM_STATUS_COLORS[status] || 'badge-secondary';
        const style = extraStyle ? ` style="${extraStyle}"` : '';
        return `<span class="badge ${cls}"${style}>${label}</span>`;
    }

    function fmtDate(iso) {
        if (!iso) return '—';
        return new Date(iso).toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' });
    }

    function el(id) { return document.getElementById(id); }

    // ── Cargar datos ─────────────────────────────────────────────────────────

    async function loadValidationData() {
        try {
            const res = await fetch(`${API_BASE}/validation-data`);
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            validationData = data.data;
            renderAll();
        } catch (err) {
            el('new-items-list').innerHTML = `<div class="alert alert-danger m-2">${err.message}</div>`;
            el('existing-items-list').innerHTML = '';
            HelpdeskUtils.showToast(err.message, 'danger');
        }
    }

    function renderAll() {
        const d = validationData;
        const campaign = d.campaign;

        // Encabezado
        el('campaign-folio').textContent = campaign.folio;
        el('campaign-subtitle').textContent =
            `${campaign.department ? campaign.department.name : '—'} · ${campaign.items_count} equipos registrados`;

        // Conteos resumen
        el('count-new').textContent = d.summary.new_items_count;
        el('count-existing').textContent = d.summary.existing_items_count;
        el('count-with-predecessor').textContent = d.summary.new_with_predecessor;
        el('count-replaced').textContent = d.summary.existing_replaced;

        // Badges de columna
        el('badge-new').textContent = d.summary.new_items_count;
        el('badge-existing').textContent = d.summary.existing_items_count;

        renderReplacements();
        renderColumns();
    }

    // ── Renderizado de columnas ───────────────────────────────────────────────

    // ── Sección de reemplazos ─────────────────────────────────────────────────

    function renderReplacements() {
        const pairs = (validationData.new_items || []).filter(i => i.predecessor);
        const section  = el('replacements-section');
        const listEl   = el('replacements-list');
        const countEl  = el('replacements-count');

        if (pairs.length === 0) {
            section.style.display = 'none';
            return;
        }

        countEl.textContent = pairs.length;
        listEl.innerHTML = pairs.map(buildReplacementPair).join('');
        section.style.display = 'block';
    }

    function buildReplacementPair(newItem) {
        const old = newItem.predecessor;
        const changes = newItem.changes_vs_predecessor || {};
        const hasChanges = Object.keys(changes).length > 0;

        const arrowLabel = hasChanges
            ? '<span style="color:#c0392b;">Con cambios</span>'
            : '<span style="color:#1a7a4a;">Sin cambios</span>';

        const diffHtml = hasChanges
            ? buildDiffTable(changes)
            : '<div class="small text-success mt-1"><i class="fas fa-check-circle mr-1"></i>Campos críticos sin cambios</div>';

        function sideFields(item) {
            return `
                <div class="small mt-2">
                    ${item.itcj_serial   ? `<div><span class="text-muted">Serial ITCJ:</span> ${item.itcj_serial}</div>` : ''}
                    ${item.supplier_serial ? `<div><span class="text-muted">Serial prov.:</span> ${item.supplier_serial}</div>` : ''}
                    ${item.id_tecnm      ? `<div><span class="text-muted">ID TecNM:</span> ${item.id_tecnm}</div>` : ''}
                    ${item.status        ? `<div><span class="text-muted">Estado:</span> ${itemStatusBadge(item.status, 'font-size:.65rem;')}</div>` : ''}
                    ${item.acquisition_date ? `<div><span class="text-muted">Adquisición:</span> ${item.acquisition_date}</div>` : ''}
                </div>
                <div class="mt-2">
                    <button class="btn btn-link btn-sm p-0 small" onclick="showItemModal(${item.id})">
                        <i class="fas fa-info-circle"></i> Ver detalle
                    </button>
                </div>`;
        }

        return `
        <div class="replacement-pair-card mb-3 shadow-sm">
            <div class="row no-gutters">

                <!-- Lado izquierdo: equipo ANTIGUO -->
                <div class="col-12 col-md-5 replacement-side-old p-3">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <span class="badge badge-danger mb-1" style="font-size:.65rem;">ANTERIOR</span>
                            <div class="replacement-inv-old">${old.inventory_number}</div>
                            <div class="text-muted small">${[old.brand, old.model].filter(Boolean).join(' ') || '—'}</div>
                        </div>
                    </div>
                    ${sideFields(old)}
                </div>

                <!-- Columna de la flecha -->
                <div class="col-12 col-md-2 replacement-arrow-col">
                    <i class="fas fa-arrow-right fa-2x arrow-icon-h"></i>
                    <i class="fas fa-arrow-down fa-2x arrow-icon-v"></i>
                    <div class="replacement-label">${arrowLabel}</div>
                </div>

                <!-- Lado derecho: equipo NUEVO -->
                <div class="col-12 col-md-5 replacement-side-new p-3">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <span class="badge badge-success mb-1" style="font-size:.65rem;">NUEVO</span>
                            <div class="replacement-inv-new">${newItem.inventory_number}</div>
                            <div class="text-muted small">${[newItem.brand, newItem.model].filter(Boolean).join(' ') || '—'}</div>
                        </div>
                    </div>
                    ${sideFields(newItem)}
                    ${diffHtml}
                </div>

            </div>
        </div>`;
    }

    window.toggleReplacementsSection = function () {
        const list    = el('replacements-list');
        const chevron = el('replacements-chevron');
        const hidden  = list.style.display === 'none';
        list.style.display = hidden ? 'block' : 'none';
        chevron.className  = hidden ? 'fas fa-chevron-up' : 'fas fa-chevron-down';
    };

    function renderColumns() {
        const d = validationData;
        const { new_items, existing_items } = d;

        // Filtrar según la vista activa
        let filteredNew = new_items;
        let filteredExisting = existing_items;

        if (currentView === 'new') {
            filteredExisting = [];
        } else if (currentView === 'existing') {
            filteredNew = [];
        } else if (currentView === 'changes') {
            filteredNew = new_items.filter(i => i.predecessor);
            filteredExisting = existing_items.filter(i => i.replaced_by);
        }

        renderNewItems(filteredNew);
        renderExistingItems(filteredExisting);
    }

    function renderNewItems(items) {
        const container = el('new-items-list');
        if (items.length === 0) {
            container.innerHTML = '<div class="text-center text-muted py-4 small"><i class="fas fa-inbox fa-lg d-block mb-1"></i>Sin items en esta vista</div>';
            return;
        }
        container.innerHTML = items.map(buildNewItemCard).join('');
    }

    function renderExistingItems(items) {
        const container = el('existing-items-list');
        if (items.length === 0) {
            container.innerHTML = '<div class="text-center text-muted py-4 small"><i class="fas fa-inbox fa-lg d-block mb-1"></i>Sin items en esta vista</div>';
            return;
        }
        container.innerHTML = items.map(buildExistingItemCard).join('');
    }

    function buildNewItemCard(item) {
        const hasPred = !!item.predecessor;
        const hasChanges = hasPred && Object.keys(item.changes_vs_predecessor || {}).length > 0;
        const cls = hasPred ? 'has-predecessor' : '';

        let predBlock = '';
        if (hasPred) {
            predBlock = `
            <div class="mt-1 pt-1 border-top">
                <small class="text-warning"><i class="fas fa-exchange-alt"></i> Reemplaza a:
                    <strong>${item.predecessor.inventory_number}</strong>
                    — ${item.predecessor.brand || ''} ${item.predecessor.model || ''}
                </small>
                ${hasChanges ? buildDiffTable(item.changes_vs_predecessor) : '<br><small class="text-muted">Sin cambios en campos críticos</small>'}
            </div>`;
        } else {
            predBlock = '<small class="text-muted"><i class="fas fa-star"></i> Item nuevo sin predecesor</small>';
        }

        return `
        <div class="item-card ${cls}">
            <div class="item-card-header" onclick="toggleCard(this)">
                <div>
                    <strong>${item.inventory_number}</strong>
                    <span class="text-muted ml-1 small">${item.brand || ''} ${item.model || ''}</span>
                </div>
                <div>
                    ${hasPred ? '<span class="badge badge-warning badge-sm">Con predecesor</span>' : '<span class="badge badge-info badge-sm">Nuevo</span>'}
                    <i class="fas fa-chevron-down ml-1 small"></i>
                </div>
            </div>
            <div class="item-card-body" style="display:none;">
                <div class="row mb-1">
                    <div class="col-6"><small class="text-muted">Serial ITCJ</small><br>${item.itcj_serial || '—'}</div>
                    <div class="col-6"><small class="text-muted">Serial proveedor</small><br>${item.supplier_serial || '—'}</div>
                </div>
                ${predBlock}
                <div class="mt-2">
                    <button class="btn btn-link btn-sm p-0 small" onclick="showItemModal(${item.id})">
                        <i class="fas fa-info-circle"></i> Ver detalle completo
                    </button>
                </div>
            </div>
        </div>`;
    }

    function buildExistingItemCard(item) {
        const isReplaced = !!item.replaced_by;
        const cls = isReplaced ? 'is-replaced' : 'unchanged';

        const replacedBlock = isReplaced
            ? `<div class="mt-1 pt-1 border-top">
                <small class="text-danger"><i class="fas fa-arrow-right"></i> Reemplazado por:
                    <strong>${item.replaced_by.inventory_number}</strong>
                    — ${item.replaced_by.brand || ''} ${item.replaced_by.model || ''}
                </small>
               </div>`
            : '<small class="text-success"><i class="fas fa-check"></i> Sin cambios registrados</small>';

        return `
        <div class="item-card ${cls}">
            <div class="item-card-header" onclick="toggleCard(this)">
                <div>
                    <strong>${item.inventory_number}</strong>
                    <span class="text-muted ml-1 small">${item.brand || ''} ${item.model || ''}</span>
                </div>
                <div>
                    ${isReplaced
                        ? '<span class="badge badge-danger badge-sm">Reemplazado</span>'
                        : '<span class="badge badge-success badge-sm">Sin cambios</span>'}
                    <i class="fas fa-chevron-down ml-1 small"></i>
                </div>
            </div>
            <div class="item-card-body" style="display:none;">
                <div class="row mb-1">
                    <div class="col-6"><small class="text-muted">Serial ITCJ</small><br>${item.itcj_serial || '—'}</div>
                    <div class="col-6"><small class="text-muted">Serial proveedor</small><br>${item.supplier_serial || '—'}</div>
                </div>
                ${replacedBlock}
                <div class="mt-2">
                    <button class="btn btn-link btn-sm p-0 small" onclick="showItemModal(${item.id})">
                        <i class="fas fa-info-circle"></i> Ver detalle completo
                    </button>
                </div>
            </div>
        </div>`;
    }

    function buildDiffTable(changes) {
        const FIELD_LABELS = {
            brand: 'Marca', model: 'Modelo', supplier_serial: 'Serial proveedor',
            itcj_serial: 'Serial ITCJ', id_tecnm: 'ID TECNM', category_id: 'Categoría',
        };
        const rows = Object.entries(changes).map(([field, val]) =>
            `<tr>
                <td>${FIELD_LABELS[field] || field}</td>
                <td class="diff-old">${val.old || '—'}</td>
                <td class="diff-new">${val.new || '—'}</td>
            </tr>`
        ).join('');
        return `<table class="table table-sm diff-table mt-1 mb-0">
            <thead><tr><th>Campo</th><th>Antes</th><th>Ahora</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
    }

    // ── Toggle card ───────────────────────────────────────────────────────────

    window.toggleCard = function (header) {
        const body = header.nextElementSibling;
        const icon = header.querySelector('.fa-chevron-down, .fa-chevron-up');
        if (body.style.display === 'none') {
            body.style.display = 'block';
            if (icon) { icon.classList.remove('fa-chevron-down'); icon.classList.add('fa-chevron-up'); }
        } else {
            body.style.display = 'none';
            if (icon) { icon.classList.remove('fa-chevron-up'); icon.classList.add('fa-chevron-down'); }
        }
    };

    // ── Modal detalle de item ─────────────────────────────────────────────────

    window.showItemModal = async function (itemId) {
        const modal = document.getElementById('modal-item-detail');
        const title = el('modal-item-title');
        const body  = el('modal-item-body');
        title.textContent = 'Cargando...';
        body.innerHTML = '<div class="text-center py-4"><i class="fas fa-spinner fa-spin text-primary fa-2x"></i></div>';
        $(modal).modal('show');

        try {
            const res = await fetch(`/api/help-desk/v2/inventory/items/${itemId}`);
            const data = await res.json();
            const item = data.data || data;
            title.textContent = item.inventory_number;
            body.innerHTML = `
            <div class="row">
                <div class="col-6 col-md-4 mb-2 spec-row">
                    <span class="spec-key d-block">Marca / Modelo</span>
                    ${item.brand || '—'} ${item.model || ''}
                </div>
                <div class="col-6 col-md-4 mb-2 spec-row">
                    <span class="spec-key d-block">Serial ITCJ</span>${item.itcj_serial || '—'}
                </div>
                <div class="col-6 col-md-4 mb-2 spec-row">
                    <span class="spec-key d-block">Serial proveedor</span>${item.supplier_serial || '—'}
                </div>
                <div class="col-6 col-md-4 mb-2 spec-row">
                    <span class="spec-key d-block">ID TECNM</span>${item.id_tecnm || '—'}
                </div>
                <div class="col-6 col-md-4 mb-2 spec-row">
                    <span class="spec-key d-block">Estado</span>
                    ${itemStatusBadge(item.status)}
                </div>
                <div class="col-6 col-md-4 mb-2 spec-row">
                    <span class="spec-key d-block">Adquisición</span>${item.acquisition_date || '—'}
                </div>
            </div>
            <div class="mt-2">
                <a href="/help-desk/inventory/items/${itemId}" target="_blank" class="btn btn-sm btn-outline-primary">
                    <i class="fas fa-external-link-alt"></i> Abrir ficha completa
                </a>
            </div>`;
        } catch (err) {
            body.innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
        }
    };

    // ── Acciones de validación ────────────────────────────────────────────────

    function initDecisionPanel() {
        const btnApprove = el('btn-approve');
        const btnReject  = el('btn-reject');
        const btnConfirmApprove = el('btn-confirm-approve');
        const confirmCheck      = el('confirm-checkbox');

        if (confirmCheck) {
            confirmCheck.addEventListener('change', () => {
                if (btnConfirmApprove) btnConfirmApprove.disabled = !confirmCheck.checked;
            });
        }

        if (btnApprove) {
            btnApprove.addEventListener('click', () => {
                if (confirmCheck) confirmCheck.checked = false;
                if (btnConfirmApprove) btnConfirmApprove.disabled = true;
                $('#modal-confirm-approve').modal('show');
            });
        }

        if (btnConfirmApprove) {
            btnConfirmApprove.addEventListener('click', () => approveCampaign());
        }

        if (btnReject) {
            btnReject.addEventListener('click', rejectCampaign);
        }
    }

    async function approveCampaign() {
        const notes = el('decision-notes') ? el('decision-notes').value.trim() : '';
        const btn = el('btn-confirm-approve');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

        try {
            const res = await fetch(`${API_BASE}/approve`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ notes: notes || null }),
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            $('#modal-confirm-approve').modal('hide');
            HelpdeskUtils.showToast(data.message, 'success');
            _redirectTimer1 = setTimeout(() => { window.location = `/help-desk/inventory/campaigns/${CAMPAIGN_ID}`; }, 1500);
        } catch (err) {
            HelpdeskUtils.showToast(err.message, 'danger');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-check-circle"></i> Aprobar';
        }
    }

    async function rejectCampaign() {
        const notes = el('decision-notes') ? el('decision-notes').value.trim() : '';
        if (!notes || notes.length < 5) {
            HelpdeskUtils.showToast('Debes indicar el motivo del rechazo (mínimo 5 caracteres).', 'warning');
            el('decision-notes').focus();
            return;
        }

        const ok = await HelpdeskUtils.confirmDialog(
            '¿Rechazar inventario?',
            `El Centro de Cómputo será notificado para corregir. Motivo: "${notes}"`,
            'Rechazar'
        );
        if (!ok) return;

        const btn = el('btn-reject');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

        try {
            const res = await fetch(`${API_BASE}/reject`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ notes }),
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            HelpdeskUtils.showToast(data.message, 'success');
            _redirectTimer2 = setTimeout(() => { window.location = `/help-desk/inventory/campaigns/${CAMPAIGN_ID}`; }, 1500);
        } catch (err) {
            HelpdeskUtils.showToast(err.message, 'danger');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-times-circle"></i> Rechazar';
        }
    }

    // ── Filtros de vista ─────────────────────────────────────────────────────

    function initViewFilters() {
        document.querySelectorAll('[data-view]').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('[data-view]').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentView = btn.dataset.view;
                if (validationData) renderColumns();
            });
        });
    }

    // ── Init ─────────────────────────────────────────────────────────────────

    function init() {
        const root = document.querySelector('[data-hd-page]');
        if (root) {
            CAMPAIGN_ID = parseInt(root.dataset.campaignId, 10);
        }
        API_BASE = `/api/help-desk/v2/inventory/campaigns/${CAMPAIGN_ID}`;

        initViewFilters();
        initDecisionPanel();
        loadValidationData();
        loadValidationGroups();
    }

    function destroy() {
        if (_redirectTimer1 !== null) { clearTimeout(_redirectTimer1); _redirectTimer1 = null; }
        if (_redirectTimer2 !== null) { clearTimeout(_redirectTimer2); _redirectTimer2 = null; }
        // Dispose Bootstrap modals
        ['modal-item-detail', 'modal-confirm-approve'].forEach(id => {
            const modalEl = document.getElementById(id);
            if (modalEl) {
                try { $(modalEl).modal('hide'); } catch (_) {}
                try { $(modalEl).modal('dispose'); } catch (_) {}
            }
        });
        // Clear window globals
        delete window.toggleReplacementsSection;
        delete window.toggleCard;
        delete window.showItemModal;
    }

    // ── Grupos / Salones (vista de validación) ───────────────────────────────

    function escHtml(s) {
        return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
                              .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    async function loadValidationGroups() {
        const cont = document.getElementById('groups-validation-container');
        if (!cont) return;
        try {
            const res = await fetch(`/api/help-desk/v2/inventory/campaigns/${CAMPAIGN_ID}/validation-groups`);
            const json = await res.json();
            if (!json.success) throw new Error(json.error || json.detail?.error || 'Error');

            const groups = json.data.groups || [];
            const summary = json.data.summary || {};

            document.getElementById('groups-validation-count').textContent = summary.total_groups || 0;
            document.getElementById('groups-summary-added').textContent = summary.total_added || 0;
            document.getElementById('groups-summary-removed').textContent = summary.total_removed || 0;
            document.getElementById('groups-summary-new').textContent = summary.new_groups || 0;

            if (!json.data.has_initial_snapshot) {
                cont.innerHTML = `
                    <div class="alert alert-warning small mb-3">
                        <i class="fas fa-exclamation-triangle"></i>
                        Esta campaña se cerró antes de la incorporación de snapshots de grupos. Sólo se muestra el estado actual.
                    </div>` + renderGroupsList(groups, false);
                return;
            }
            if (groups.length === 0) {
                cont.innerHTML = '<p class="text-muted small text-center py-3 mb-0">Sin grupos en este departamento.</p>';
                return;
            }

            cont.innerHTML = renderGroupsList(groups, true);
        } catch (err) {
            cont.innerHTML = `<p class="text-danger small text-center mb-0">Error: ${escHtml(err.message)}</p>`;
        }
    }

    function renderGroupsList(groups, showDiff) {
        return groups.map(g => renderGroupCard(g, showDiff)).join('');
    }

    function renderGroupCard(g, showDiff) {
        const newBadge = g.new_group
            ? '<span class="badge badge-success ml-2" title="Grupo creado durante la campaña"><i class="fas fa-star"></i> Nuevo</span>'
            : '';
        const deletedBadge = g.deleted
            ? '<span class="badge badge-danger ml-2"><i class="fas fa-trash"></i> Eliminado</span>'
            : '';
        const meta = [g.code, g.group_type].filter(Boolean).join(' · ');
        const locBits = [g.building, g.floor ? 'P' + g.floor : null].filter(Boolean).join(', ');

        const changeCount = (g.added_count || 0) + (g.removed_count || 0);
        const headerCls = changeCount > 0 ? 'bg-warning bg-opacity-10' : '';

        const itemsCurrent = (g.items_current || []).map(it => `
            <div class="d-flex justify-content-between align-items-center border-bottom py-1 small">
                <span>
                    <strong>${escHtml(it.inventory_number)}</strong>
                    <span class="text-muted">${escHtml(it.brand || '')} ${escHtml(it.model || '')}</span>
                    ${it.in_current_campaign ? '<span class="badge badge-primary ml-1">Campaña actual</span>' : ''}
                    ${it.is_locked ? '<i class="fas fa-lock text-warning ml-1" title="Bloqueado"></i>' : ''}
                </span>
            </div>
        `).join('') || '<p class="text-muted small mb-0">Sin equipos.</p>';

        const itemsAdded = (g.items_added || []).map(it => `
            <div class="d-flex justify-content-between align-items-center py-1 small bg-success bg-opacity-10 px-2 rounded mb-1">
                <span>
                    <i class="fas fa-plus-circle text-success"></i>
                    <strong>${escHtml(it.inventory_number)}</strong>
                    <span class="text-muted">${escHtml(it.brand || '')} ${escHtml(it.model || '')}</span>
                </span>
            </div>
        `).join('');

        const itemsRemoved = (g.items_removed || []).map(it => `
            <div class="d-flex justify-content-between align-items-center py-1 small bg-danger bg-opacity-10 px-2 rounded mb-1">
                <span>
                    <i class="fas fa-minus-circle text-danger"></i>
                    <strong>${escHtml(it.inventory_number)}</strong>
                    <span class="text-muted">${escHtml(it.brand || '')} ${escHtml(it.model || '')}</span>
                </span>
                <small class="text-muted">${escHtml(it.destino || '')}</small>
            </div>
        `).join('');

        const diffBlock = showDiff && (itemsAdded || itemsRemoved) ? `
            <div class="mt-2">
                ${g.added_count > 0 ? `
                    <div class="small font-weight-bold text-success mb-1">
                        <i class="fas fa-plus"></i> Agregados durante la campaña (${g.added_count})
                    </div>
                    ${itemsAdded}
                ` : ''}
                ${g.removed_count > 0 ? `
                    <div class="small font-weight-bold text-danger mt-2 mb-1">
                        <i class="fas fa-minus"></i> Salieron del grupo (${g.removed_count})
                    </div>
                    ${itemsRemoved}
                ` : ''}
            </div>
        ` : '';

        return `
            <div class="card border mb-3">
                <div class="card-header py-2 ${headerCls} d-flex justify-content-between align-items-center">
                    <div>
                        <strong>${escHtml(g.name)}</strong>
                        ${newBadge}${deletedBadge}
                        <div class="small text-muted">
                            ${escHtml(meta)}${locBits ? ' · ' + escHtml(locBits) : ''}
                        </div>
                    </div>
                    ${showDiff ? `
                        <div class="text-right small">
                            <span class="badge badge-light">${g.kept_count} sin cambio</span>
                            ${g.added_count > 0 ? `<span class="badge badge-success">+${g.added_count}</span>` : ''}
                            ${g.removed_count > 0 ? `<span class="badge badge-danger">-${g.removed_count}</span>` : ''}
                        </div>
                    ` : ''}
                </div>
                <div class="card-body py-2">
                    <div class="small font-weight-bold mb-1">
                        <i class="fas fa-list"></i> Equipos actuales (${(g.items_current || []).length})
                    </div>
                    ${itemsCurrent}
                    ${diffBlock}
                </div>
            </div>
        `;
    }

    window.HelpdeskPage.page('inventory_campaigns_campaign_validate', { init: init, destroy: destroy });

})();
