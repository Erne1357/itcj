/**
 * Verificación de Inventario — migrada a componentes server-side + HTMX (BS5).
 * La tabla, los filtros, la paginación y las tarjetas de resumen los rinde el
 * servidor (ver _verification_results.html + pages/inventory.py). Este módulo
 * conserva SOLO la lógica genuinamente de cliente: los modales de verificación /
 * historial / transferencia masiva (BS5, sin jQuery), la selección masiva por
 * checkbox (delegada) y las acciones que, al terminar, recargan el fragmento HTMX.
 */
(function () {
    'use strict';

    /* ═══════════════════════════════ Estado ═══════════════════════════════ */
    const state = {
        currentItemId: null,
        currentItemData: null,
    };

    let el = {};
    let VERIF_CONFIG = {};

    // Teardown refs
    let _resultsClickDelegate = null;
    let _resultsChangeDelegate = null;
    let _afterSettleHandler = null;
    const _boundBtns = [];   // {el, ev, fn}

    /* ═════════════════════════════ Utilidades ══════════════════════════════ */
    function bsModal(elem) {
        return bootstrap.Modal.getOrCreateInstance(elem);
    }

    function fmtDateTime(iso) {
        if (!iso) return '—';
        const d = new Date(iso);
        return d.toLocaleString('es-MX', {
            day: '2-digit', month: 'short', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    }

    function showToast(msg, type) {
        type = type || 'success';
        if (window.HelpdeskUtils && window.HelpdeskUtils.showToast) {
            window.HelpdeskUtils.showToast(msg, type);
            return;
        }
        console.warn('showToast fallback:', msg);
    }

    function escHtml(str) {
        return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    function escAttr(str) {
        return String(str || '').replace(/"/g, '&quot;');
    }

    // Recarga el fragmento server-side (tabla + stats OOB) vía HTMX.
    function refreshList() {
        const form = document.getElementById('hd-filter-form');
        if (form && window.htmx) window.htmx.trigger(form, 'refresh');
    }

    /* ═════════════════════════════ Modal Verificar ═════════════════════════ */
    async function openVerifyModal(itemId) {
        // El fragmento es server-side, así que no tenemos el array de items en el
        // cliente: pedimos el equipo completo al abrir el modal (incluye category
        // con spec_template, specifications, grupo, etc.).
        let item;
        try {
            const resp = await fetch(`/api/help-desk/v2/inventory/items/${itemId}`, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            const json = await resp.json();
            if (!resp.ok || !json.success) throw new Error((json.detail && json.detail.error) || json.error || 'No se pudo cargar el equipo');
            item = json.data;
        } catch (err) {
            console.error(err);
            showToast(err.message || 'No se pudo cargar el equipo.', 'error');
            return;
        }

        state.currentItemId = itemId;
        state.currentItemData = item;

        el.verifItemNumber.textContent = item.inventory_number;
        el.verifItemName.textContent = [item.brand, item.model].filter(Boolean).join(' ') || '—';
        el.verifItemDept.textContent = item.department ? item.department.name : '—';

        el.verifLocation.value = item.location_detail || '';
        el.verifStatus.value = item.status || 'ACTIVE';
        el.verifBrand.value = item.brand || '';
        el.verifModel.value = item.model || '';
        if (el.verifSupplierSerial) el.verifSupplierSerial.value = item.supplier_serial || '';
        if (el.verifItcjSerial) el.verifItcjSerial.value = item.itcj_serial || '';
        if (el.verifIdTecnm) el.verifIdTecnm.value = item.id_tecnm || '';
        el.verifObs.value = '';

        el.changesAlert.classList.add('d-none');
        el.btnVerifyLabel.textContent = 'Registrar Verificación';
        el.btnConfirm.disabled = false;

        if (el.verifGroup) {
            el.verifGroup.innerHTML = '<option value="">Cargando grupos…</option>';
            el.verifGroup.disabled = true;
        }
        if (el.verifGroupHint) el.verifGroupHint.textContent = '';

        renderSpecFields(item);

        bsModal(el.modalVerify).show();

        loadGroupsForModal(item);
    }

    /* ─── Grupos del departamento ─────────────────────────────────────── */
    async function loadGroupsForModal(item) {
        const select = el.verifGroup;
        if (!select) return;

        const deptId = item.department_id || (item.department && item.department.id);
        if (!deptId) {
            select.innerHTML = '<option value="">Sin grupo</option>';
            select.disabled = false;
            return;
        }

        const groupsApi = VERIF_CONFIG.apiBase.replace('/verification', '/groups');
        try {
            const resp = await fetch(
                `${groupsApi}/?department_id=${deptId}`,
                { headers: { 'X-Requested-With': 'XMLHttpRequest' } }
            );
            const json = await resp.json();
            if (!json.success) throw new Error(json.error || 'Error al cargar grupos');

            const currentGroupId = item.group_id || (item.group && item.group.id) || null;
            const groups = json.data || [];

            select.innerHTML = '<option value="">Sin grupo</option>' +
                groups.map(g =>
                    `<option value="${g.id}"${currentGroupId == g.id ? ' selected' : ''}>${escHtml(g.name)}</option>`
                ).join('');

            if (el.verifGroupHint) {
                el.verifGroupHint.textContent = currentGroupId
                    ? `Grupo actual: ${escHtml(item.group ? item.group.name : String(currentGroupId))}`
                    : 'Sin grupo asignado actualmente';
            }
        } catch (err) {
            console.error('Error loading groups:', err);
            select.innerHTML = '<option value="">Sin grupo</option>';
        } finally {
            select.disabled = false;
        }
    }

    /* ─── Especificaciones técnicas dinámicas ─────────────────────────── */
    function renderSpecFields(item) {
        let template = item.category && item.category.spec_template;
        if (template && typeof template === 'string') {
            try { template = JSON.parse(template); } catch (e) { template = null; }
        }

        if (!template || typeof template !== 'object' || Array.isArray(template) ||
            Object.keys(template).length === 0) {
            el.specsSection.classList.add('d-none');
            el.specsContainer.innerHTML = '';
            return;
        }

        const specs = item.specifications || {};

        el.specsContainer.innerHTML = Object.entries(template).map(([key, def]) => {
            if (!def || typeof def !== 'object') return '';
            const val = specs[key];
            const label = def.label || key;
            const id = `spec-field-${key}`;

            if (def.type === 'boolean') {
                const checked = (val === true || val === 'true') ? 'checked' : '';
                return `<div class="col-12 col-md-6 mb-2">
                    <div class="form-check mt-2">
                        <input class="form-check-input spec-field" type="checkbox"
                               id="${id}" data-spec-key="${key}" data-spec-type="boolean" ${checked}>
                        <label class="form-check-label small fw-bold" for="${id}">${escHtml(label)}</label>
                    </div>
                </div>`;
            }

            if (def.type === 'select' && Array.isArray(def.options)) {
                const opts = def.options.map(opt =>
                    `<option value="${escAttr(String(opt))}"${String(val) === String(opt) ? ' selected' : ''}>${escHtml(String(opt))}</option>`
                ).join('');
                return `<div class="col-12 col-md-6 mb-2">
                    <label class="small fw-bold" for="${id}">${escHtml(label)}</label>
                    <select class="form-select form-select-sm spec-field"
                            id="${id}" data-spec-key="${key}" data-spec-type="select">
                        <option value="">— seleccionar —</option>${opts}
                    </select>
                </div>`;
            }

            const inputType = def.type === 'number' ? 'number' : 'text';
            const valStr = (val !== undefined && val !== null) ? escAttr(String(val)) : '';
            return `<div class="col-12 col-md-6 mb-2">
                <label class="small fw-bold" for="${id}">${escHtml(label)}</label>
                <input type="${inputType}" class="form-control form-control-sm spec-field"
                       id="${id}" data-spec-key="${key}" data-spec-type="${inputType}"
                       value="${valStr}">
            </div>`;
        }).join('');

        el.specsCollapse.classList.add('d-none');
        const toggleText = document.getElementById('specs-toggle-text');
        const toggleIcon = document.getElementById('specs-toggle-icon');
        if (toggleText) toggleText.textContent = 'Mostrar';
        if (toggleIcon) { toggleIcon.classList.remove('fa-chevron-up'); toggleIcon.classList.add('fa-chevron-down'); }

        el.specsSection.classList.remove('d-none');

        el.specsContainer.querySelectorAll('.spec-field').forEach(f => {
            f.addEventListener('change', detectChanges);
            f.addEventListener('input', detectChanges);
        });
    }

    function bindSpecsToggle() {
        const btn = document.getElementById('btn-toggle-specs');
        if (!btn) return;
        const fn = () => {
            const hidden = el.specsCollapse.classList.toggle('d-none');
            const toggleText = document.getElementById('specs-toggle-text');
            const toggleIcon = document.getElementById('specs-toggle-icon');
            if (toggleText) toggleText.textContent = hidden ? 'Mostrar' : 'Ocultar';
            if (toggleIcon) {
                toggleIcon.classList.toggle('fa-chevron-down', hidden);
                toggleIcon.classList.toggle('fa-chevron-up', !hidden);
            }
        };
        btn.addEventListener('click', fn);
        _boundBtns.push({ el: btn, ev: 'click', fn });
    }

    function detectChanges() {
        const item = state.currentItemData;
        if (!item) return;

        const changes = [];
        if (el.verifLocation.value !== (item.location_detail || '')) changes.push('ubicación');
        if (el.verifStatus.value !== item.status) changes.push('estado');
        if (el.verifGroup && !el.verifGroup.disabled) {
            const currentGroupId = item.group_id || (item.group && item.group.id) || null;
            const selectedGroupId = el.verifGroup.value ? parseInt(el.verifGroup.value, 10) : null;
            if (selectedGroupId !== currentGroupId) changes.push('grupo');
        }
        if (el.verifBrand.value !== (item.brand || '')) changes.push('marca');
        if (el.verifModel.value !== (item.model || '')) changes.push('modelo');
        if (el.verifSupplierSerial && el.verifSupplierSerial.value !== (item.supplier_serial || '')) changes.push('serial proveedor');
        if (el.verifItcjSerial && el.verifItcjSerial.value !== (item.itcj_serial || '')) changes.push('serial ITCJ');
        if (el.verifIdTecnm && el.verifIdTecnm.value !== (item.id_tecnm || '')) changes.push('ID TecNM');

        const specFields = el.specsContainer ? el.specsContainer.querySelectorAll('.spec-field') : [];
        if (specFields.length > 0) {
            const currentSpecs = item.specifications || {};
            let specsChanged = false;
            specFields.forEach(field => {
                const key = field.dataset.specKey;
                const oldVal = currentSpecs[key];
                let newVal;
                if (field.type === 'checkbox') {
                    newVal = field.checked;
                    const oldBool = oldVal === true || oldVal === 'true';
                    if (newVal !== oldBool) specsChanged = true;
                } else if (field.dataset.specType === 'number') {
                    newVal = field.value !== '' ? parseFloat(field.value) : null;
                    if (String(newVal) !== String(oldVal ?? '')) specsChanged = true;
                } else {
                    newVal = field.value.trim() || null;
                    if (newVal !== (oldVal || null)) specsChanged = true;
                }
            });
            if (specsChanged) changes.push('especificaciones');
        }

        if (changes.length > 0) {
            el.changesMsg.textContent = `Se actualizará: ${changes.join(', ')}.`;
            el.changesAlert.classList.remove('d-none');
        } else {
            el.changesAlert.classList.add('d-none');
        }
    }

    async function submitVerification() {
        const itemId = state.currentItemId;
        if (!itemId) return;

        el.btnConfirm.disabled = true;
        el.btnVerifyLabel.textContent = 'Guardando…';

        const payload = {
            location_detail: el.verifLocation.value.trim() || null,
            status: el.verifStatus.value,
            brand: el.verifBrand.value.trim() || null,
            model: el.verifModel.value.trim() || null,
            supplier_serial: el.verifSupplierSerial ? el.verifSupplierSerial.value.trim() || null : undefined,
            itcj_serial: el.verifItcjSerial ? el.verifItcjSerial.value.trim() || null : undefined,
            id_tecnm: el.verifIdTecnm ? el.verifIdTecnm.value.trim() || null : undefined,
            location_confirmed: el.verifLocation.value.trim() || null,
            observations: el.verifObs.value.trim() || null,
        };

        if (el.verifGroup && !el.verifGroup.disabled) {
            payload.group_id = el.verifGroup.value ? parseInt(el.verifGroup.value, 10) : null;
        }

        const specFields = el.specsContainer ? el.specsContainer.querySelectorAll('.spec-field') : [];
        if (specFields.length > 0) {
            const specs = {};
            specFields.forEach(field => {
                const key = field.dataset.specKey;
                if (field.type === 'checkbox') {
                    specs[key] = field.checked;
                } else if (field.dataset.specType === 'number') {
                    specs[key] = field.value !== '' ? parseFloat(field.value) : null;
                } else {
                    specs[key] = field.value.trim() || null;
                }
            });
            payload.specifications = specs;
        }

        try {
            const resp = await fetch(
                `${VERIF_CONFIG.apiBase}/items/${itemId}/verify`,
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    body: JSON.stringify(payload),
                }
            );
            const json = await resp.json();
            if (!json.success) throw new Error(json.error || 'Error al guardar');

            bsModal(el.modalVerify).hide();
            refreshList();
            showToast('Verificación registrada correctamente.', 'success');

        } catch (err) {
            console.error(err);
            showToast(err.message || 'Error al registrar la verificación.', 'error');
        } finally {
            el.btnConfirm.disabled = false;
            el.btnVerifyLabel.textContent = 'Registrar Verificación';
        }
    }

    /* ═════════════════════════════ Modal Historial ═════════════════════════ */
    async function openHistoryModal(itemId, itemName) {
        el.historyLoading.classList.remove('d-none');
        el.historyEmpty.classList.add('d-none');
        el.historyList.innerHTML = '';
        el.historyItemName.textContent = itemName || '';

        bsModal(el.modalHistory).show();

        try {
            const resp = await fetch(
                `${VERIF_CONFIG.apiBase}/items/${itemId}/history`,
                { headers: { 'X-Requested-With': 'XMLHttpRequest' } }
            );
            const json = await resp.json();

            el.historyLoading.classList.add('d-none');

            if (!json.success) throw new Error(json.error || 'Error de servidor');

            const verifs = json.data || [];
            if (verifs.length === 0) {
                el.historyEmpty.classList.remove('d-none');
                return;
            }

            el.historyList.innerHTML = verifs.map(v => buildHistoryItem(v)).join('');

        } catch (err) {
            console.error(err);
            el.historyLoading.classList.add('d-none');
            el.historyList.innerHTML = `<li class="list-group-item text-danger small">Error al cargar historial.</li>`;
        }
    }

    function buildHistoryItem(v) {
        const verifier = v.verified_by ? v.verified_by.full_name : '—';
        const dt = fmtDateTime(v.verified_at);
        const obs = v.observations ? escHtml(v.observations) : '<em class="text-muted">Sin observaciones</em>';
        const hasChanges = v.changes_applied && Object.keys(v.changes_applied).length > 0;

        let changesHtml = '';
        if (hasChanges) {
            const items = Object.entries(v.changes_applied).map(([field, change]) =>
                `<li>${escHtml(field)}: <span class="text-muted">${escHtml(String(change.old || '—'))}</span>
                 → <strong>${escHtml(String(change.new || '—'))}</strong></li>`
            ).join('');
            changesHtml = `<ul class="mb-0 ps-3 small text-muted">${items}</ul>`;
        }

        return `<li class="list-group-item">
            <div class="d-flex justify-content-between align-items-start">
                <div>
                    <strong class="small">${escHtml(verifier)}</strong>
                    <span class="text-muted small ms-2">${dt}</span>
                </div>
                ${hasChanges ? '<span class="badge bg-info text-dark">Con cambios</span>' : ''}
            </div>
            <div class="small mt-1">${obs}</div>
            ${changesHtml}
        </li>`;
    }

    /* ═════════════════════════ Selección masiva ════════════════════════════ */
    function getVerifSelectedIds() {
        return Array.from(document.querySelectorAll('.verif-checkbox:checked'))
            .map(cb => parseInt(cb.dataset.itemId, 10));
    }

    function updateVerifBulkBar() {
        const ids = getVerifSelectedIds();
        const bar = document.getElementById('verif-bulk-bar');
        const cnt = document.getElementById('verif-bulk-count');
        if (!bar) return;
        bar.classList.toggle('d-none', ids.length === 0);
        if (cnt) cnt.textContent = ids.length;
    }

    function clearSelection() {
        document.querySelectorAll('.verif-checkbox, #verif-select-all').forEach(cb => { cb.checked = false; });
        updateVerifBulkBar();
    }

    async function executeVerifBulkTransfer() {
        const ids = getVerifSelectedIds();
        const deptEl = document.getElementById('verif-bulk-transfer-dept');
        const deptId = parseInt(deptEl.value, 10);
        if (!deptId) { showToast('Selecciona un departamento destino', 'error'); return; }

        const btn = document.getElementById('btn-confirm-verif-bulk-transfer');
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Transfiriendo...'; }

        try {
            const res = await fetch('/api/help-desk/v2/inventory/items/bulk-transfer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                body: JSON.stringify({ item_ids: ids, target_department_id: deptId }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error al transferir');

            bsModal(document.getElementById('modal-verif-bulk-transfer')).hide();
            clearSelection();

            const transferred = data.transferred_ids ? data.transferred_ids.length : 0;
            showToast(`${transferred} equipo(s) transferido(s) correctamente.`, transferred > 0 ? 'success' : 'error');
            refreshList();

        } catch (err) {
            showToast('Error: ' + err.message, 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-exchange-alt"></i> Transferir'; }
        }
    }

    async function executeVerifBulkLimbo() {
        const ids = getVerifSelectedIds();
        if (!ids.length) return;
        if (!await HelpdeskUtils.confirmDialog('Enviar al limbo', `¿Enviar ${ids.length} equipo(s) al limbo? Quedarán sin departamento ni usuario asignado.`)) return;

        const btn = document.getElementById('btn-verif-bulk-limbo');
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>'; }

        try {
            const res = await fetch('/api/help-desk/v2/inventory/items/bulk-send-to-limbo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                body: JSON.stringify({ item_ids: ids }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error al enviar al limbo');

            clearSelection();
            const sent = data.sent_ids ? data.sent_ids.length : 0;
            showToast(`${sent} equipo(s) enviado(s) al limbo.`, sent > 0 ? 'success' : 'error');
            refreshList();

        } catch (err) {
            showToast('Error: ' + err.message, 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-inbox"></i> Limbo'; }
        }
    }

    async function sendVerifSingleToLimbo(itemId) {
        if (!await HelpdeskUtils.confirmDialog('Enviar al limbo', '¿Enviar este equipo al limbo? Quedará sin departamento ni usuario asignado.')) return;

        try {
            const res = await fetch('/api/help-desk/v2/inventory/items/bulk-send-to-limbo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                body: JSON.stringify({ item_ids: [itemId] }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error al enviar al limbo');
            showToast('Equipo enviado al limbo correctamente.', 'success');
            refreshList();
        } catch (err) {
            showToast('Error: ' + err.message, 'error');
        }
    }

    /* ═════════════════════════════ Event binding ═══════════════════════════ */
    function bindBtn(id, ev, fn) {
        const node = document.getElementById(id);
        if (!node) return;
        node.addEventListener(ev, fn);
        _boundBtns.push({ el: node, ev, fn });
    }

    function bindEvents() {
        bindSpecsToggle();

        // Delegación sobre el contenedor de resultados (sobrevive a los swaps HTMX).
        const results = document.getElementById('hd-verif-results');
        if (results) {
            _resultsClickDelegate = function (e) {
                const btn = e.target.closest('[data-action]');
                if (!btn) return;
                const action = btn.dataset.action;
                const itemId = parseInt(btn.dataset.itemId, 10);
                if (action === 'verify') openVerifyModal(itemId);
                else if (action === 'history') openHistoryModal(itemId, btn.dataset.itemName);
                else if (action === 'limbo') sendVerifSingleToLimbo(itemId);
            };
            results.addEventListener('click', _resultsClickDelegate);

            _resultsChangeDelegate = function (e) {
                if (e.target.id === 'verif-select-all') {
                    results.querySelectorAll('.verif-checkbox').forEach(cb => { cb.checked = e.target.checked; });
                    updateVerifBulkBar();
                } else if (e.target.classList.contains('verif-checkbox')) {
                    updateVerifBulkBar();
                }
            };
            results.addEventListener('change', _resultsChangeDelegate);
        }

        // Al recargar el fragmento (filtro/paginación) la selección se reinicia.
        _afterSettleHandler = function () { updateVerifBulkBar(); };
        document.body.addEventListener('htmx:afterSettle', _afterSettleHandler);

        // Modal verificar: inputs → detectChanges; confirmar → submit.
        [el.verifLocation, el.verifStatus, el.verifBrand, el.verifModel,
         el.verifSupplierSerial, el.verifItcjSerial, el.verifIdTecnm].forEach(input => {
            if (input) {
                input.addEventListener('input', detectChanges);
                _boundBtns.push({ el: input, ev: 'input', fn: detectChanges });
            }
        });
        if (el.verifGroup) {
            el.verifGroup.addEventListener('change', detectChanges);
            _boundBtns.push({ el: el.verifGroup, ev: 'change', fn: detectChanges });
        }
        bindBtn('btn-confirm-verify', 'click', submitVerification);

        // Barra de acciones masivas (fuera del fragmento → estable).
        bindBtn('btn-verif-bulk-transfer', 'click', () => {
            const ids = getVerifSelectedIds();
            if (!ids.length) return;
            const cnt = document.getElementById('verif-bulk-transfer-count');
            if (cnt) cnt.textContent = ids.length;
            bsModal(document.getElementById('modal-verif-bulk-transfer')).show();
        });
        bindBtn('btn-confirm-verif-bulk-transfer', 'click', executeVerifBulkTransfer);
        bindBtn('btn-verif-bulk-deselect', 'click', clearSelection);
        bindBtn('btn-verif-bulk-baja', 'click', () => {
            const ids = getVerifSelectedIds();
            if (!ids.length) return;
            const url = `/help-desk/inventory/retirement-requests/create?item_ids=${ids.join(',')}`;
            if (window.HelpdeskPage && window.HelpdeskPage.navigate) window.HelpdeskPage.navigate(url);
            else window.location.href = url;
        });
        bindBtn('btn-verif-bulk-limbo', 'click', executeVerifBulkLimbo);
    }

    /* ═════════════════════════════ Init / Destroy ══════════════════════════ */
    function init() {
        VERIF_CONFIG = { apiBase: '/api/help-desk/v2/inventory/verification' };

        const qs = (sel) => document.querySelector(sel);
        el = {
            modalVerify: qs('#modal-verify'),
            verifItemNumber: qs('#verif-item-number'),
            verifItemName: qs('#verif-item-name'),
            verifItemDept: qs('#verif-item-dept'),
            verifLocation: qs('#verif-location'),
            verifStatus: qs('#verif-status'),
            verifBrand: qs('#verif-brand'),
            verifModel: qs('#verif-model'),
            verifSupplierSerial: qs('#verif-supplier-serial'),
            verifItcjSerial: qs('#verif-itcj-serial'),
            verifIdTecnm: qs('#verif-id-tecnm'),
            verifObs: qs('#verif-observations'),
            verifGroup: qs('#verif-group'),
            verifGroupHint: qs('#verif-group-hint'),
            specsSection: qs('#specs-section'),
            specsContainer: qs('#specs-fields-container'),
            specsCollapse: qs('#specs-collapse'),
            changesAlert: qs('#changes-alert'),
            changesMsg: qs('#changes-msg'),
            btnConfirm: qs('#btn-confirm-verify'),
            btnVerifyLabel: qs('#btn-verify-label'),
            modalHistory: qs('#modal-history'),
            historyLoading: qs('#history-loading'),
            historyEmpty: qs('#history-empty'),
            historyList: qs('#history-list'),
            historyItemName: qs('#history-item-name'),
        };

        bindEvents();
        updateVerifBulkBar();
    }

    function destroy() {
        const results = document.getElementById('hd-verif-results');
        if (results) {
            if (_resultsClickDelegate) results.removeEventListener('click', _resultsClickDelegate);
            if (_resultsChangeDelegate) results.removeEventListener('change', _resultsChangeDelegate);
        }
        if (_afterSettleHandler) document.body.removeEventListener('htmx:afterSettle', _afterSettleHandler);
        _boundBtns.forEach(b => { try { b.el.removeEventListener(b.ev, b.fn); } catch (e) { /* ignore */ } });
        _boundBtns.length = 0;

        // Dispose los modales BS5.
        ['#modal-verif-bulk-transfer', '#modal-verify', '#modal-history'].forEach(function (sel) {
            try {
                const modalEl = document.querySelector(sel);
                if (modalEl) bootstrap.Modal.getInstance(modalEl)?.dispose();
            } catch (e) { /* ignore */ }
        });

        _resultsClickDelegate = null;
        _resultsChangeDelegate = null;
        _afterSettleHandler = null;
        state.currentItemId = null;
        state.currentItemData = null;
        el = {};
        VERIF_CONFIG = {};
    }

    window.HelpdeskPage.page('inventory_reports_verification', { init: init, destroy: destroy });

})();
