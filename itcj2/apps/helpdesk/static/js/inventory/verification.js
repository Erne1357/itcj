/**
 * Verificación de Inventario
 * Carga la tabla de equipos con su estado de verificación,
 * permite abrir el modal para verificar un equipo y
 * actualiza la fila en tiempo real sin recargar la página.
 */
(function () {
    'use strict';

    /* ═══════════════════════════════ Estado ═══════════════════════════════ */
    const state = {
        items: [],          // página actual cargada desde la API
        currentPage: 1,
        perPage: 50,
        totalItems: 0,      // total de la API (filtrado)
        totalPages: 1,
        currentItemId: null,
        currentItemData: null,
    };

    /* ═══════════════════════════════ DOM refs ══════════════════════════════ */
    const $ = (sel) => document.querySelector(sel);
    const el = {
        loading:         $('#loading-state'),
        empty:           $('#empty-state'),
        tableWrapper:    $('#table-wrapper'),
        tbody:           $('#verif-tbody'),
        tableCountLabel: $('#table-count-label'),
        paginationInfo:  $('#pagination-info'),
        paginationCtrl:  $('#pagination-controls'),
        countUnverified: $('#count-unverified'),
        badgeUnverified: $('#badge-unverified'),
        statTotal:       $('#stat-total'),
        statRecent:      $('#stat-recent'),
        statOutdated:    $('#stat-outdated'),
        statCritical:    $('#stat-critical'),
        filterSearch:    $('#filter-search'),
        filterDept:      $('#filter-department'),
        filterVerif:     $('#filter-verif-status'),
        btnRefresh:      $('#btn-refresh'),
        // Modal verificar
        modalVerify:     $('#modal-verify'),
        verifItemNumber: $('#verif-item-number'),
        verifItemName:   $('#verif-item-name'),
        verifItemDept:   $('#verif-item-dept'),
        verifLocation:   $('#verif-location'),
        verifStatus:     $('#verif-status'),
        verifBrand:      $('#verif-brand'),
        verifModel:      $('#verif-model'),
        verifSupplierSerial: $('#verif-supplier-serial'),
        verifItcjSerial:    $('#verif-itcj-serial'),
        verifIdTecnm:       $('#verif-id-tecnm'),
        verifObs:        $('#verif-observations'),
        verifGroup:      $('#verif-group'),
        verifGroupHint:  $('#verif-group-hint'),
        specsSection:    $('#specs-section'),
        specsContainer:  $('#specs-fields-container'),
        specsCollapse:   $('#specs-collapse'),
        changesAlert:    $('#changes-alert'),
        changesMsg:      $('#changes-msg'),
        btnConfirm:      $('#btn-confirm-verify'),
        btnVerifyLabel:  $('#btn-verify-label'),
        // Modal historial
        modalHistory:    $('#modal-history'),
        historyLoading:  $('#history-loading'),
        historyEmpty:    $('#history-empty'),
        historyList:     $('#history-list'),
        historyItemName: $('#history-item-name'),
    };

    /* ═══════════════════════════ Verificación status ══════════════════════ */
    const VERIF_LABELS = {
        recent:   { text: 'Reciente',   cls: 'badge-verif-recent',   row: 'row-recent'   },
        outdated: { text: 'Vencido',    cls: 'badge-verif-outdated', row: 'row-outdated' },
        critical: { text: 'Crítico',    cls: 'badge-verif-critical', row: 'row-critical' },
        never:    { text: 'Sin verificar', cls: 'badge-verif-never', row: 'row-never'   },
    };

    function verifBadgeHtml(status) {
        const info = VERIF_LABELS[status] || VERIF_LABELS.never;
        return `<span class="badge ${info.cls}">${info.text}</span>`;
    }

    /* ═════════════════════════════ Utilidades ══════════════════════════════ */
    function fmtDate(iso) {
        if (!iso) return '—';
        const d = new Date(iso);
        return d.toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' });
    }

    function fmtDateTime(iso) {
        if (!iso) return '—';
        const d = new Date(iso);
        return d.toLocaleString('es-MX', {
            day: '2-digit', month: 'short', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    }

    function showToast(msg, type = 'success') {
        if (window.HelpdeskUtils && window.HelpdeskUtils.showToast) {
            window.HelpdeskUtils.showToast(msg, type);
            return;
        }
        alert(msg);
    }

    function setLoading(on) {
        el.loading.classList.toggle('d-none', !on);
        el.tableWrapper.classList.toggle('d-none', on);
        el.empty.classList.add('d-none');
    }

    /* ═════════════════════════════ Carga de datos ══════════════════════════ */
    async function loadItems() {
        setLoading(true);

        const params = new URLSearchParams();
        params.set('page',     state.currentPage);
        params.set('per_page', state.perPage);

        if (el.filterDept && el.filterDept.value)
            params.set('department_id', el.filterDept.value);

        const verifFilter = el.filterVerif ? el.filterVerif.value : 'all';
        if (verifFilter !== 'all')
            params.set('status_filter', verifFilter);

        const search = el.filterSearch.value.trim();
        if (search) params.set('search', search);

        try {
            const resp = await fetch(
                `${VERIF_CONFIG.apiBase}/status?${params.toString()}`,
                { headers: { 'X-Requested-With': 'XMLHttpRequest' } }
            );
            const json = await resp.json();

            if (!json.success) throw new Error(json.error || 'Error de servidor');

            state.items      = json.data || [];
            state.totalItems = json.pagination.total;
            state.totalPages = json.pagination.pages;

            updateStats(json.stats || {});
            renderTable();

        } catch (err) {
            console.error(err);
            showToast('No se pudo cargar la lista de equipos.', 'error');
            setLoading(false);
        }
    }

    function updateStats(stats) {
        el.statTotal.textContent    = stats.total    ?? 0;
        el.statRecent.textContent   = stats.recent   ?? 0;
        el.statOutdated.textContent = stats.outdated ?? 0;

        const criticalAndNever = (stats.critical ?? 0) + (stats.never ?? 0);
        el.statCritical.textContent = criticalAndNever;
        el.countUnverified.textContent = (stats.never ?? 0) + (stats.outdated ?? 0);

        // Badge de nunca/vencido
        const urgent = (stats.never ?? 0) + (stats.outdated ?? 0) + (stats.critical ?? 0);
        el.badgeUnverified.classList.toggle('bg-danger',   urgent > 10);
        el.badgeUnverified.classList.toggle('text-white',  urgent > 10);
        el.badgeUnverified.classList.toggle('bg-warning',  urgent <= 10);
        el.badgeUnverified.classList.toggle('text-dark',   urgent <= 10);
    }

    /* ═══════════════════════════════════════════════════════════════════════ */
    /* Los filtros ahora se envían al servidor; applyFilters solo resetea     */
    /* la página y dispara loadItems.                                         */
    function applyFilters() {
        state.currentPage = 1;
        loadItems();
    }

    /* ═════════════════════════════ Renderizado ═════════════════════════════ */
    function renderTable() {
        const total = state.totalItems;

        if (state.items.length === 0) {
            el.tableWrapper.classList.add('d-none');
            el.empty.classList.remove('d-none');
            el.loading.classList.add('d-none');
            el.tableCountLabel.textContent = '';
            el.paginationInfo.textContent  = '';
            el.paginationCtrl.innerHTML    = '';
            return;
        }

        el.empty.classList.add('d-none');
        el.loading.classList.add('d-none');
        el.tableWrapper.classList.remove('d-none');

        el.tableCountLabel.textContent = ` (${total} equipo${total !== 1 ? 's' : ''})`;
        el.tbody.innerHTML = state.items.map(item => buildRow(item)).join('');
        // Reset checkboxes on page change
        const verifSelAll = document.getElementById('verif-select-all');
        if (verifSelAll) verifSelAll.checked = false;
        updateVerifBulkBar();

        // Info de paginación (calculada desde server)
        const start = (state.currentPage - 1) * state.perPage + 1;
        const end   = Math.min(state.currentPage * state.perPage, total);
        el.paginationInfo.textContent = `Mostrando ${start}-${end} de ${total}`;
        renderPagination(state.totalPages);
    }

    function buildRow(item) {
        const vs     = item.verification_status || 'never';
        const info   = VERIF_LABELS[vs] || VERIF_LABELS.never;
        const deptName = item.department ? item.department.name : '—';
        const lastVerif = item.last_verified_at ? fmtDate(item.last_verified_at) : '—';
        const verifiedBy = item.last_verified_by ? item.last_verified_by.full_name : '—';
        const loc = item.location_detail || '—';
        const equip = [item.brand, item.model].filter(Boolean).join(' ') || '—';

        return `<tr class="${info.row}" data-item-id="${item.id}">
            <td><input type="checkbox" class="verif-checkbox" data-item-id="${item.id}"
                       onchange="updateVerifBulkBar()"></td>
            <td class="text-nowrap font-weight-bold">${escHtml(item.inventory_number)}</td>
            <td class="d-none d-md-table-cell">${escHtml(equip)}</td>
            <td class="d-none d-lg-table-cell">${escHtml(deptName)}</td>
            <td class="d-none d-md-table-cell small">${escHtml(loc)}</td>
            <td class="small text-nowrap">${lastVerif}</td>
            <td class="d-none d-sm-table-cell small">${escHtml(verifiedBy)}</td>
            <td>${verifBadgeHtml(vs)}</td>
            <td class="text-center text-nowrap">
                <button class="btn btn-success btn-xs btn-verify mr-1"
                        data-item-id="${item.id}"
                        title="Verificar equipo">
                    <i class="fas fa-clipboard-check"></i>
                </button>
                <button class="btn btn-outline-secondary btn-xs btn-history mr-1"
                        data-item-id="${item.id}"
                        data-item-name="${escAttr(item.inventory_number)}"
                        title="Ver historial de verificaciones">
                    <i class="fas fa-history"></i>
                </button>
                <a class="btn btn-outline-danger btn-xs btn-baja mr-1"
                   href="/help-desk/inventory/retirement-requests/create?item_id=${item.id}"
                   title="Solicitar Baja">
                    <i class="fas fa-file-alt"></i>
                </a>
                <button class="btn btn-outline-warning btn-xs btn-limbo"
                        data-item-id="${item.id}"
                        title="Enviar al Limbo">
                    <i class="fas fa-inbox"></i>
                </button>
            </td>
        </tr>`;
    }

    function renderPagination(pages) {
        if (pages <= 1) {
            el.paginationCtrl.innerHTML = '';
            return;
        }
        const cur = state.currentPage;

        // Construir conjunto de páginas a mostrar (con ventana ±2 alrededor de la actual)
        const show = new Set([1, pages]);
        for (let i = Math.max(1, cur - 2); i <= Math.min(pages, cur + 2); i++) show.add(i);
        const sorted = [...show].sort((a, b) => a - b);

        let html = `<button class="btn btn-outline-secondary${cur===1?' disabled':''}" data-page="${cur-1}">&laquo;</button>`;

        let prev = 0;
        for (const p of sorted) {
            if (p - prev > 1) html += `<button class="btn btn-outline-secondary disabled">…</button>`;
            html += `<button class="btn btn-outline-secondary${p===cur?' active':''}" data-page="${p}">${p}</button>`;
            prev = p;
        }

        html += `<button class="btn btn-outline-secondary${cur===pages?' disabled':''}" data-page="${cur+1}">&raquo;</button>`;
        el.paginationCtrl.innerHTML = html;
    }

    function escHtml(str) {
        return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }
    function escAttr(str) {
        return String(str || '').replace(/"/g,'&quot;');
    }

    /* ═════════════════════════════ Modal Verificar ═════════════════════════ */
    function openVerifyModal(itemId) {
        const item = state.items.find(i => i.id == itemId);
        if (!item) return;

        state.currentItemId   = itemId;
        state.currentItemData = item;

        // Rellenar campos
        el.verifItemNumber.textContent = item.inventory_number;
        el.verifItemName.textContent   = [item.brand, item.model].filter(Boolean).join(' ') || '—';
        el.verifItemDept.textContent   = item.department ? item.department.name : '—';

        el.verifLocation.value = item.location_detail || '';
        el.verifStatus.value   = item.status || 'ACTIVE';
        el.verifBrand.value    = item.brand  || '';
        el.verifModel.value    = item.model  || '';
        if (el.verifSupplierSerial) el.verifSupplierSerial.value = item.supplier_serial || '';
        if (el.verifItcjSerial) el.verifItcjSerial.value = item.itcj_serial || '';
        if (el.verifIdTecnm) el.verifIdTecnm.value       = item.id_tecnm || '';
        el.verifObs.value      = '';

        el.changesAlert.classList.add('d-none');
        el.btnVerifyLabel.textContent = 'Registrar Verificación';
        el.btnConfirm.disabled = false;

        // Reset group select while groups load
        if (el.verifGroup) {
            el.verifGroup.innerHTML = '<option value="">Cargando grupos…</option>';
            el.verifGroup.disabled = true;
        }
        if (el.verifGroupHint) el.verifGroupHint.textContent = '';

        renderSpecFields(item);

        if (window.jQuery) window.jQuery(el.modalVerify).modal('show');

        // Load groups async (non-blocking — modal already visible)
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
        // Safety: spec_template puede venir como string JSON en algunos entornos
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
            const val   = specs[key];
            const label = def.label || key;
            const id    = `spec-field-${key}`;

            if (def.type === 'boolean') {
                const checked = (val === true || val === 'true') ? 'checked' : '';
                return `<div class="col-12 col-md-6 mb-2">
                    <div class="form-check mt-2">
                        <input class="form-check-input spec-field" type="checkbox"
                               id="${id}" data-spec-key="${key}" data-spec-type="boolean" ${checked}>
                        <label class="form-check-label small font-weight-bold" for="${id}">${escHtml(label)}</label>
                    </div>
                </div>`;
            }

            if (def.type === 'select' && Array.isArray(def.options)) {
                const opts = def.options.map(opt =>
                    `<option value="${escAttr(String(opt))}"${String(val) === String(opt) ? ' selected' : ''}>${escHtml(String(opt))}</option>`
                ).join('');
                return `<div class="col-12 col-md-6 mb-2">
                    <label class="small font-weight-bold" for="${id}">${escHtml(label)}</label>
                    <select class="form-control form-control-sm spec-field"
                            id="${id}" data-spec-key="${key}" data-spec-type="select">
                        <option value="">— seleccionar —</option>${opts}
                    </select>
                </div>`;
            }

            // text / number
            const inputType = def.type === 'number' ? 'number' : 'text';
            const valStr    = (val !== undefined && val !== null) ? escAttr(String(val)) : '';
            return `<div class="col-12 col-md-6 mb-2">
                <label class="small font-weight-bold" for="${id}">${escHtml(label)}</label>
                <input type="${inputType}" class="form-control form-control-sm spec-field"
                       id="${id}" data-spec-key="${key}" data-spec-type="${inputType}"
                       value="${valStr}">
            </div>`;
        }).join('');

        // Cerrar el panel al abrir un nuevo equipo
        el.specsCollapse.classList.add('d-none');
        const toggleText = document.getElementById('specs-toggle-text');
        const toggleIcon = document.getElementById('specs-toggle-icon');
        if (toggleText) toggleText.textContent = 'Mostrar';
        if (toggleIcon) { toggleIcon.classList.remove('fa-chevron-up'); toggleIcon.classList.add('fa-chevron-down'); }

        // Mostrar la sección
        el.specsSection.classList.remove('d-none');

        // Bind change detection a los nuevos campos
        el.specsContainer.querySelectorAll('.spec-field').forEach(f => {
            f.addEventListener('change', detectChanges);
            f.addEventListener('input',  detectChanges);
        });
    }

    function bindSpecsToggle() {
        const btn = document.getElementById('btn-toggle-specs');
        if (!btn) return;
        btn.addEventListener('click', () => {
            const hidden = el.specsCollapse.classList.toggle('d-none');
            const toggleText = document.getElementById('specs-toggle-text');
            const toggleIcon = document.getElementById('specs-toggle-icon');
            if (toggleText) toggleText.textContent = hidden ? 'Mostrar' : 'Ocultar';
            if (toggleIcon) {
                toggleIcon.classList.toggle('fa-chevron-down', hidden);
                toggleIcon.classList.toggle('fa-chevron-up',   !hidden);
            }
        });
    }

    function detectChanges() {
        const item = state.currentItemData;
        if (!item) return;

        const changes = [];
        if (el.verifLocation.value !== (item.location_detail || ''))
            changes.push('ubicación');
        if (el.verifStatus.value !== item.status)
            changes.push('estado');
        if (el.verifGroup && !el.verifGroup.disabled) {
            const currentGroupId = item.group_id || (item.group && item.group.id) || null;
            const selectedGroupId = el.verifGroup.value ? parseInt(el.verifGroup.value, 10) : null;
            if (selectedGroupId !== currentGroupId) changes.push('grupo');
        }
        if (el.verifBrand.value !== (item.brand || ''))
            changes.push('marca');
        if (el.verifModel.value !== (item.model || ''))
            changes.push('modelo');
        if (el.verifSupplierSerial && el.verifSupplierSerial.value !== (item.supplier_serial || ''))
            changes.push('serial proveedor');
        if (el.verifItcjSerial && el.verifItcjSerial.value !== (item.itcj_serial || ''))
            changes.push('serial ITCJ');
        if (el.verifIdTecnm && el.verifIdTecnm.value !== (item.id_tecnm || ''))
            changes.push('ID TecNM');

        // Especificaciones técnicas
        const specFields = el.specsContainer
            ? el.specsContainer.querySelectorAll('.spec-field') : [];
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
            location_detail:    el.verifLocation.value.trim() || null,
            status:             el.verifStatus.value,
            brand:              el.verifBrand.value.trim()  || null,
            model:              el.verifModel.value.trim()  || null,
            supplier_serial:    el.verifSupplierSerial ? el.verifSupplierSerial.value.trim() || null : undefined,
            itcj_serial:        el.verifItcjSerial ? el.verifItcjSerial.value.trim() || null : undefined,
            id_tecnm:           el.verifIdTecnm    ? el.verifIdTecnm.value.trim()    || null : undefined,
            location_confirmed: el.verifLocation.value.trim() || null,
            observations:       el.verifObs.value.trim()    || null,
        };

        // Grupo: siempre enviarlo para que el backend lo procese si cambió
        if (el.verifGroup && !el.verifGroup.disabled) {
            payload.group_id = el.verifGroup.value ? parseInt(el.verifGroup.value, 10) : null;
        }

        // Recopilar especificaciones técnicas si existen campos dinámicos
        const specFields = el.specsContainer
            ? el.specsContainer.querySelectorAll('.spec-field') : [];
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

            // Cerrar modal
            if (window.jQuery) window.jQuery(el.modalVerify).modal('hide');

            // Recargar la página actual con datos frescos del servidor
            // (actualiza stats y estado de verificación correctamente)
            loadItems();

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

        if (window.jQuery) window.jQuery(el.modalHistory).modal('show');

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
        const dt       = fmtDateTime(v.verified_at);
        const obs      = v.observations ? escHtml(v.observations) : '<em class="text-muted">Sin observaciones</em>';
        const hasChanges = v.changes_applied && Object.keys(v.changes_applied).length > 0;

        let changesHtml = '';
        if (hasChanges) {
            const items = Object.entries(v.changes_applied).map(([field, change]) =>
                `<li>${escHtml(field)}: <span class="text-muted">${escHtml(String(change.old || '—'))}</span>
                 → <strong>${escHtml(String(change.new || '—'))}</strong></li>`
            ).join('');
            changesHtml = `<ul class="mb-0 pl-3 small text-muted">${items}</ul>`;
        }

        return `<li class="list-group-item">
            <div class="d-flex justify-content-between align-items-start">
                <div>
                    <strong class="small">${escHtml(verifier)}</strong>
                    <span class="text-muted small ml-2">${dt}</span>
                </div>
                ${hasChanges ? '<span class="badge bg-info text-dark">Con cambios</span>' : ''}
            </div>
            <div class="small mt-1">${obs}</div>
            ${changesHtml}
        </li>`;
    }

    /* ═════════════════════════════ Event listeners ═════════════════════════ */
    function bindEvents() {
        bindSpecsToggle();

        // Filtros con debounce en búsqueda
        let searchTimer = null;
        el.filterSearch.addEventListener('input', () => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(applyFilters, 300);
        });

        if (el.filterVerif) el.filterVerif.addEventListener('change', applyFilters);
        if (el.filterDept)  el.filterDept.addEventListener('change',  applyFilters);

        el.btnRefresh.addEventListener('click', loadItems);

        // Delegación de eventos en la tabla
        el.tbody.addEventListener('click', (e) => {
            const btnVerify  = e.target.closest('.btn-verify');
            const btnHistory = e.target.closest('.btn-history');
            const btnLimbo   = e.target.closest('.btn-limbo');

            if (btnVerify) {
                openVerifyModal(parseInt(btnVerify.dataset.itemId, 10));
            } else if (btnHistory) {
                openHistoryModal(
                    parseInt(btnHistory.dataset.itemId, 10),
                    btnHistory.dataset.itemName
                );
            } else if (btnLimbo) {
                sendVerifSingleToLimbo(parseInt(btnLimbo.dataset.itemId, 10));
            }
        });

        // Paginación — cada clic carga la página del servidor
        el.paginationCtrl.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-page]');
            if (!btn || btn.classList.contains('disabled') || btn.classList.contains('active')) return;
            const newPage = parseInt(btn.dataset.page, 10);
            if (newPage < 1 || newPage > state.totalPages) return;
            state.currentPage = newPage;
            loadItems();
        });

        // Detectar cambios en modal
        [el.verifLocation, el.verifStatus, el.verifBrand, el.verifModel,
         el.verifSupplierSerial, el.verifItcjSerial, el.verifIdTecnm].forEach(input => {
            if (input) input.addEventListener('input', detectChanges);
        });
        if (el.verifGroup) el.verifGroup.addEventListener('change', detectChanges);

        // Confirmar verificación
        el.btnConfirm.addEventListener('click', submitVerification);

        // ── Bulk selection ────────────────────────────────────────────────────
        const verifSelectAll = document.getElementById('verif-select-all');
        if (verifSelectAll) {
            verifSelectAll.addEventListener('change', function () {
                document.querySelectorAll('.verif-checkbox').forEach(cb => cb.checked = this.checked);
                updateVerifBulkBar();
            });
        }

        const btnVerifBulkTransfer = document.getElementById('btn-verif-bulk-transfer');
        if (btnVerifBulkTransfer) btnVerifBulkTransfer.addEventListener('click', () => {
            const ids = getVerifSelectedIds();
            if (!ids.length) return;
            const cnt = document.getElementById('verif-bulk-transfer-count');
            if (cnt) cnt.textContent = ids.length;
            if (window.jQuery) window.jQuery('#modal-verif-bulk-transfer').modal('show');
        });

        const btnVerifBulkDeselect = document.getElementById('btn-verif-bulk-deselect');
        if (btnVerifBulkDeselect) btnVerifBulkDeselect.addEventListener('click', () => {
            document.querySelectorAll('.verif-checkbox, #verif-select-all').forEach(cb => cb.checked = false);
            updateVerifBulkBar();
        });

        const btnConfirmVerifBulk = document.getElementById('btn-confirm-verif-bulk-transfer');
        if (btnConfirmVerifBulk) btnConfirmVerifBulk.addEventListener('click', executeVerifBulkTransfer);

        const btnVerifBulkBaja = document.getElementById('btn-verif-bulk-baja');
        if (btnVerifBulkBaja) btnVerifBulkBaja.addEventListener('click', () => {
            const ids = getVerifSelectedIds();
            if (!ids.length) return;
            window.location.href = `/help-desk/inventory/retirement-requests/create?item_ids=${ids.join(',')}`;
        });

        const btnVerifBulkLimbo = document.getElementById('btn-verif-bulk-limbo');
        if (btnVerifBulkLimbo) btnVerifBulkLimbo.addEventListener('click', executeVerifBulkLimbo);
    }

    /* ═════════════════════════ Selección masiva ════════════════════════════ */
    function getVerifSelectedIds() {
        return Array.from(document.querySelectorAll('.verif-checkbox:checked'))
            .map(cb => parseInt(cb.dataset.itemId));
    }

    function updateVerifBulkBar() {
        const ids = getVerifSelectedIds();
        const bar = document.getElementById('verif-bulk-bar');
        const cnt = document.getElementById('verif-bulk-count');
        if (!bar) return;
        if (ids.length > 0) {
            bar.style.display = '';
            if (cnt) cnt.textContent = ids.length;
        } else {
            bar.style.display = 'none';
        }
    }

    async function executeVerifBulkTransfer() {
        const ids = getVerifSelectedIds();
        const deptId = parseInt(document.getElementById('verif-bulk-transfer-dept').value);
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

            if (window.jQuery) window.jQuery('#modal-verif-bulk-transfer').modal('hide');
            document.querySelectorAll('.verif-checkbox, #verif-select-all').forEach(cb => cb.checked = false);
            updateVerifBulkBar();

            const transferred = data.transferred_ids ? data.transferred_ids.length : 0;
            showToast(`${transferred} equipo(s) transferido(s) correctamente.`, transferred > 0 ? 'success' : 'error');
            loadItems();

        } catch (err) {
            showToast('Error: ' + err.message, 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-exchange-alt"></i> Transferir'; }
        }
    }

    async function executeVerifBulkLimbo() {
        const ids = getVerifSelectedIds();
        if (!ids.length) return;
        if (!confirm(`¿Enviar ${ids.length} equipo(s) al limbo? Quedarán sin departamento ni usuario asignado.`)) return;

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

            document.querySelectorAll('.verif-checkbox, #verif-select-all').forEach(cb => cb.checked = false);
            updateVerifBulkBar();

            const sent = data.sent_ids ? data.sent_ids.length : 0;
            showToast(`${sent} equipo(s) enviado(s) al limbo.`, sent > 0 ? 'success' : 'error');
            loadItems();

        } catch (err) {
            showToast('Error: ' + err.message, 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-inbox"></i> Limbo'; }
        }
    }

    async function sendVerifSingleToLimbo(itemId) {
        if (!confirm('¿Enviar este equipo al limbo? Quedará sin departamento ni usuario asignado.')) return;

        try {
            const res = await fetch('/api/help-desk/v2/inventory/items/bulk-send-to-limbo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                body: JSON.stringify({ item_ids: [itemId] }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error al enviar al limbo');
            showToast('Equipo enviado al limbo correctamente.', 'success');
            loadItems();
        } catch (err) {
            showToast('Error: ' + err.message, 'error');
        }
    }

    /* ═════════════════════════════ Init ════════════════════════════════════ */
    function init() {
        bindEvents();
        loadItems();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
