/**
 * priorities_tab.js
 * Tab "Prioridades y SLA" del panel de Configuración.
 *
 * Responsabilidades:
 *  - Lista ordenable de prioridades con drag-drop (persiste en backend).
 *  - CRUD: crear (con code), editar (sin code), toggle activo, soft-delete.
 *  - Badge preview en tiempo real al editar badge_class / color.
 *  - Conversión humana de sla_hours (4h, 24h → 1d, 72h → 3d, etc.).
 *  - Toggle "mostrar inactivas".
 *  - Lazy init: carga datos solo la primera vez que el tab es visible.
 */
(function () {
    'use strict';

    // === ESTADO ===
    let initialized = false;
    let priorities = [];
    let showInactive = false;
    let sortableInstance = null;

    // === CONSTANTES ===
    const API_BASE = '/api/help-desk/v2/config/priorities';

    const BADGE_CLASS_OPTIONS = [
        { value: 'bg-success',                label: 'Verde (success)' },
        { value: 'bg-info text-dark',         label: 'Celeste (info)' },
        { value: 'bg-primary',                label: 'Azul (primary)' },
        { value: 'bg-secondary',              label: 'Gris (secondary)' },
        { value: 'bg-warning text-dark',      label: 'Amarillo (warning)' },
        { value: 'bg-danger',                 label: 'Rojo (danger)' },
        { value: 'bg-dark',                   label: 'Negro (dark)' },
    ];

    // === HELPERS ===
    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    async function apiErrorMsg(res, fallback) {
        try {
            const d = await res.json();
            const v = d.error || d.message || d.detail;
            if (typeof v === 'string' && v) return v;
            if (Array.isArray(v)) {
                return v.map(function (e) { return (e && e.msg) ? e.msg : String(e); }).join('; ') || fallback;
            }
            return fallback;
        } catch (_) {
            return fallback + ' (HTTP ' + res.status + ')';
        }
    }

    /**
     * Convierte horas a una etiqueta legible.
     * 1 → 1h, 24 → 1d, 48 → 2d, 72 → 3d, 168 → 7d
     */
    function formatSlaHours(hours) {
        if (!hours || hours <= 0) return hours + 'h';
        if (hours < 24) return hours + 'h';
        const days = Math.floor(hours / 24);
        const rem = hours % 24;
        if (rem === 0) return days + 'd';
        return days + 'd ' + rem + 'h';
    }

    /**
     * Devuelve la clase CSS de severidad para el badge de SLA.
     * < 24h → danger, 24–72h → warning, > 72h → success
     */
    function slaSeverityClass(hours) {
        if (hours <= 0) return 'bg-secondary';
        if (hours < 24) return 'priority-sla--critical';
        if (hours <= 72) return 'priority-sla--medium';
        return 'priority-sla--low';
    }

    function buildBadgeClassSelect(selectId, currentValue) {
        const opts = BADGE_CLASS_OPTIONS.map(function (opt) {
            const sel = (opt.value === currentValue) ? ' selected' : '';
            return '<option value="' + escapeHtml(opt.value) + '"' + sel + '>' + escapeHtml(opt.label) + '</option>';
        }).join('');
        return '<select class="form-select form-select-sm" id="' + selectId + '">' + opts + '</select>';
    }

    // === INIT ===
    document.addEventListener('config:tab-shown', function (e) {
        if (e.detail && e.detail.tab === '#prioridades') {
            if (!initialized) {
                initialized = true;
                initPrioritiesTab();
            }
        }
    });

    document.addEventListener('DOMContentLoaded', function () {
        const hash = window.location.hash || '';
        if (hash === '#prioridades') {
            if (!initialized) {
                initialized = true;
                initPrioritiesTab();
            }
        }
        bindCreateModal();
        bindEditModal();
    });

    function initPrioritiesTab() {
        renderShell();
        loadPriorities();
    }

    // === RENDER SHELL ===
    function renderShell() {
        const root = document.getElementById('prioridades-root');
        if (!root) return;

        root.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
                <h5 class="mb-0 fw-semibold">
                    <i class="fas fa-flag me-2 text-danger"></i>Prioridades y SLA
                </h5>
                <div class="d-flex align-items-center gap-2 flex-wrap">
                    <div class="form-check form-switch mb-0">
                        <input class="form-check-input" type="checkbox" id="toggle-inactive-prio"
                               role="switch" ${showInactive ? 'checked' : ''}>
                        <label class="form-check-label small text-muted" for="toggle-inactive-prio">
                            Mostrar inactivas
                        </label>
                    </div>
                    <button class="btn btn-sm btn-danger" id="btn-new-priority">
                        <i class="fas fa-plus me-1"></i><span class="d-none d-sm-inline">Nueva prioridad</span>
                    </button>
                </div>
            </div>

            <div id="priorities-list-wrapper">
                <div class="text-center py-4 text-muted small">
                    <div class="spinner-border spinner-border-sm" role="status"></div>
                    Cargando...
                </div>
            </div>
        `;

        root.addEventListener('change', function (e) {
            if (e.target.id === 'toggle-inactive-prio') {
                showInactive = e.target.checked;
                renderList();
            }
        });

        const btnNew = root.querySelector('#btn-new-priority');
        if (btnNew) {
            btnNew.addEventListener('click', function () { openCreateModal(); });
        }
    }

    // === CARGA DE DATOS ===
    async function loadPriorities() {
        const wrapper = document.getElementById('priorities-list-wrapper');
        if (wrapper) {
            wrapper.innerHTML = `
                <div class="text-center py-4 text-muted small">
                    <div class="spinner-border spinner-border-sm" role="status"></div>
                    Cargando...
                </div>`;
        }

        try {
            const res = await fetch(API_BASE + '?include_inactive=true');
            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al cargar prioridades');
                HelpdeskUtils.showToast(msg, 'error');
                if (wrapper) wrapper.innerHTML = '<div class="text-danger small p-2">Error al cargar</div>';
                return;
            }
            const data = await res.json();
            priorities = data.priorities || [];
            renderList();
        } catch (err) {
            console.error('Error loading priorities:', err);
            HelpdeskUtils.showToast('Error de conexión al cargar prioridades', 'error');
        }
    }

    // === RENDER LISTA ===
    function renderList() {
        const wrapper = document.getElementById('priorities-list-wrapper');
        if (!wrapper) return;

        const visible = priorities.filter(function (p) {
            return showInactive ? true : p.is_active;
        });

        if (!visible.length) {
            wrapper.innerHTML = `
                <div class="text-center py-5 text-muted">
                    <i class="fas fa-flag fa-3x mb-3 opacity-50"></i>
                    <p>${showInactive ? 'Sin prioridades configuradas.' : 'Sin prioridades activas.'}</p>
                    <p class="small">Usa el botón "Nueva prioridad" para agregar una.</p>
                </div>`;
            return;
        }

        wrapper.innerHTML = `
            <div class="priority-list-info text-muted small mb-2">
                <i class="fas fa-info-circle me-1"></i>
                Arrastra las filas para reordenar. El orden afecta la selección en el formulario de tickets.
            </div>
            <div id="priority-sortable-list" class="priority-sortable-list">
                ${visible.map(renderPriorityRow).join('')}
            </div>`;

        bindRowActions(wrapper);
        initSortable();
    }

    function renderPriorityRow(p) {
        const badgeCls = escapeHtml(p.badge_class || 'bg-secondary');
        const color = p.color ? escapeHtml(p.color) : '';
        const colorStyle = color ? ' style="background-color:' + color + ' !important;"' : '';
        const slaLabel = formatSlaHours(p.sla_hours);
        const sevClass = slaSeverityClass(p.sla_hours);
        const inactiveCls = p.is_active ? '' : 'priority-row--inactive';

        // Advertencia de contraste: bg-warning sin text-dark
        const contrastWarn = (p.badge_class === 'bg-warning')
            ? '<i class="fas fa-exclamation-triangle text-warning ms-1" title="Contraste bajo: agrega text-dark al badge_class"></i>'
            : '';

        return `
            <div class="priority-row ${inactiveCls}" data-id="${p.id}">
                <span class="drag-handle" title="Arrastrar para reordenar">
                    <i class="fas fa-grip-vertical"></i>
                </span>
                <div class="priority-badge-preview">
                    <span class="badge ${badgeCls}"${colorStyle}>${escapeHtml(p.label)}</span>
                    ${contrastWarn}
                </div>
                <div class="priority-row-info">
                    <code class="priority-row-code">${escapeHtml(p.code)}</code>
                    ${!p.is_active ? '<span class="badge bg-warning text-dark ms-1 small">Inactiva</span>' : ''}
                </div>
                <div class="priority-sla-cell">
                    <span class="badge priority-sla-badge ${sevClass}" title="${p.sla_hours}h">
                        <i class="fas fa-clock me-1"></i>${escapeHtml(slaLabel)}
                    </span>
                </div>
                <div class="priority-row-actions">
                    <div class="form-check form-switch mb-0" title="${p.is_active ? 'Desactivar' : 'Activar'}">
                        <input class="form-check-input prio-toggle" type="checkbox"
                               data-id="${p.id}" ${p.is_active ? 'checked' : ''}>
                    </div>
                    <button class="btn btn-sm btn-outline-secondary prio-btn-edit" title="Editar"
                            data-id="${p.id}">
                        <i class="fas fa-pencil-alt"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger prio-btn-delete" title="Eliminar"
                            data-id="${p.id}" data-code="${escapeHtml(p.code)}">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>`;
    }

    function bindRowActions(container) {
        container.querySelectorAll('.prio-toggle').forEach(function (chk) {
            chk.addEventListener('change', function () {
                handleToggle(parseInt(chk.dataset.id), chk.checked, chk);
            });
        });

        container.querySelectorAll('.prio-btn-edit').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const p = findById(parseInt(btn.dataset.id));
                if (p) openEditModal(p);
            });
        });

        container.querySelectorAll('.prio-btn-delete').forEach(function (btn) {
            btn.addEventListener('click', function () {
                handleDelete(parseInt(btn.dataset.id), btn.dataset.code);
            });
        });
    }

    function findById(id) {
        return priorities.find(function (p) { return p.id === id; }) || null;
    }

    // === SORTABLE ===
    function initSortable() {
        if (typeof Sortable === 'undefined') return;
        const list = document.getElementById('priority-sortable-list');
        if (!list) return;

        if (sortableInstance) {
            sortableInstance.destroy();
            sortableInstance = null;
        }

        sortableInstance = Sortable.create(list, {
            handle: '.drag-handle',
            animation: 150,
            ghostClass: 'priority-row--ghost',
            onEnd: function () { handleReorder(); },
        });
    }

    async function handleReorder() {
        const list = document.getElementById('priority-sortable-list');
        if (!list) return;

        const rows = list.querySelectorAll('.priority-row[data-id]');
        const order = Array.from(rows).map(function (row, idx) {
            return { id: parseInt(row.dataset.id), display_order: idx + 1 };
        });

        try {
            const res = await fetch(API_BASE + '/reorder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ order: order }),
            });
            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al reordenar');
                HelpdeskUtils.showToast(msg, 'error');
                return;
            }
            const data = await res.json();
            // Actualizar orden local
            order.forEach(function (item) {
                const p = findById(item.id);
                if (p) p.display_order = item.display_order;
            });
            // Reordenar array local según nuevo display_order
            if (data.priorities && data.priorities.length) {
                priorities = data.priorities;
            }
        } catch (err) {
            HelpdeskUtils.showToast('Error de conexión al reordenar', 'error');
        }
    }

    // === TOGGLE ===
    async function handleToggle(id, isActive, checkbox) {
        const original = !isActive;
        checkbox.disabled = true;

        try {
            const res = await fetch(API_BASE + '/' + id + '/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_active: isActive }),
            });
            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al cambiar estado');
                HelpdeskUtils.showToast(msg, 'error');
                checkbox.checked = original;
                return;
            }
            const data = await res.json();
            const p = findById(id);
            if (p) p.is_active = isActive;
            HelpdeskUtils.showToast(data.message || (isActive ? 'Prioridad activada' : 'Prioridad desactivada'), 'success');
            renderList();
        } catch (err) {
            HelpdeskUtils.showToast('Error de conexión', 'error');
            checkbox.checked = original;
        } finally {
            checkbox.disabled = false;
        }
    }

    // === DELETE ===
    async function handleDelete(id, code) {
        const confirmed = await HelpdeskUtils.confirmDialog(
            'Eliminar prioridad',
            'La prioridad <strong>' + escapeHtml(code) + '</strong> será eliminada (soft delete). ' +
            'Si tiene <em>cualquier</em> ticket asociado, la operación fallará.',
            'Eliminar',
            'Cancelar'
        );
        if (!confirmed) return;

        try {
            const res = await fetch(API_BASE + '/' + id, { method: 'DELETE' });
            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al eliminar');
                HelpdeskUtils.showToast(msg, 'error');
                return;
            }
            HelpdeskUtils.showToast('Prioridad eliminada', 'success');
            priorities = priorities.filter(function (p) { return p.id !== id; });
            renderList();
        } catch (err) {
            HelpdeskUtils.showToast('Error de conexión', 'error');
        }
    }

    // === MODAL CREAR ===
    function openCreateModal() {
        const modal = document.getElementById('modal-priority-create');
        if (!modal) return;

        modal.querySelector('#prio-create-code').value = '';
        modal.querySelector('#prio-create-label').value = '';
        modal.querySelector('#prio-create-sla').value = '';
        modal.querySelector('#prio-create-color').value = '#6c757d';

        // Reconstruir el select en su contenedor
        const badgeSelectWrap = modal.querySelector('#prio-create-badge-wrap');
        if (badgeSelectWrap) {
            badgeSelectWrap.innerHTML = buildBadgeClassSelect('prio-create-badge', 'bg-secondary');
        }

        // Reset errores
        modal.querySelectorAll('.is-invalid').forEach(function (el) { el.classList.remove('is-invalid'); });
        modal.querySelectorAll('.invalid-feedback').forEach(function (el) { el.textContent = ''; });

        updateBadgePreview(modal, 'prio-create-badge', 'prio-create-label', 'prio-create-color', 'prio-create-badge-preview');

        bootstrap.Modal.getOrCreateInstance(modal).show();
    }

    // === MODAL EDITAR ===
    function openEditModal(p) {
        const modal = document.getElementById('modal-priority-edit');
        if (!modal) return;

        modal.querySelector('#prio-edit-id').value = p.id;
        modal.querySelector('#prio-edit-code-display').textContent = p.code;
        modal.querySelector('#prio-edit-label').value = p.label || '';
        modal.querySelector('#prio-edit-sla').value = p.sla_hours || '';
        modal.querySelector('#prio-edit-color').value = p.color || '#6c757d';

        const badgeSelectWrap = modal.querySelector('#prio-edit-badge-wrap');
        if (badgeSelectWrap) {
            badgeSelectWrap.innerHTML = buildBadgeClassSelect('prio-edit-badge', p.badge_class || 'bg-secondary');
        }

        modal.querySelectorAll('.is-invalid').forEach(function (el) { el.classList.remove('is-invalid'); });
        modal.querySelectorAll('.invalid-feedback').forEach(function (el) { el.textContent = ''; });

        updateBadgePreview(modal, 'prio-edit-badge', 'prio-edit-label', 'prio-edit-color', 'prio-edit-badge-preview');

        bootstrap.Modal.getOrCreateInstance(modal).show();
    }

    // === BADGE PREVIEW ===
    function updateBadgePreview(modal, badgeSelectId, labelInputId, colorInputId, previewId) {
        const badgeSelect = modal.querySelector('#' + badgeSelectId);
        const labelInput = modal.querySelector('#' + labelInputId);
        const colorInput = modal.querySelector('#' + colorInputId);
        const preview = modal.querySelector('#' + previewId);
        if (!preview) return;

        const badgeCls = badgeSelect ? badgeSelect.value : 'bg-secondary';
        const label = labelInput ? (labelInput.value.trim() || 'Ejemplo') : 'Ejemplo';
        const color = colorInput ? colorInput.value : '';

        let styleAttr = '';
        if (color && color !== '#6c757d') {
            styleAttr = ' style="background-color:' + color + ' !important;"';
        }

        // Advertencia de contraste
        const warnHtml = (badgeCls === 'bg-warning')
            ? '<span class="text-warning small ms-2"><i class="fas fa-exclamation-triangle"></i> Contraste bajo — agrega <code>text-dark</code></span>'
            : '';

        preview.innerHTML = '<span class="badge ' + escapeHtml(badgeCls) + '"' + styleAttr + '>' + escapeHtml(label) + '</span>' + warnHtml;
    }

    // === VALIDACIÓN ===
    function validatePriorityForm(modal, isCreate) {
        let valid = true;

        if (isCreate) {
            const codeInput = modal.querySelector('#prio-create-code');
            const code = codeInput ? codeInput.value.trim() : '';
            const codeError = codeInput ? codeInput.nextElementSibling : null;
            if (codeInput) codeInput.classList.remove('is-invalid');

            if (!code) {
                if (codeInput) codeInput.classList.add('is-invalid');
                if (codeError) codeError.textContent = 'El código es requerido';
                valid = false;
            } else if (code.length < 2) {
                if (codeInput) codeInput.classList.add('is-invalid');
                if (codeError) codeError.textContent = 'Mínimo 2 caracteres';
                valid = false;
            } else if (!/^[A-Z][A-Z0-9_]*$/.test(code)) {
                if (codeInput) codeInput.classList.add('is-invalid');
                if (codeError) codeError.textContent = 'Solo mayúsculas, números y guión bajo. Ej: URGENTE, ALTA';
                valid = false;
            }
        }

        const prefix = isCreate ? 'prio-create' : 'prio-edit';

        const labelInput = modal.querySelector('#' + prefix + '-label');
        const labelError = labelInput ? labelInput.nextElementSibling : null;
        if (labelInput) labelInput.classList.remove('is-invalid');
        const labelVal = labelInput ? labelInput.value.trim() : '';
        if (!labelVal) {
            if (labelInput) labelInput.classList.add('is-invalid');
            if (labelError) labelError.textContent = 'La etiqueta es requerida';
            valid = false;
        } else if (labelVal.length < 2) {
            if (labelInput) labelInput.classList.add('is-invalid');
            if (labelError) labelError.textContent = 'Mínimo 2 caracteres';
            valid = false;
        }

        const slaInput = modal.querySelector('#' + prefix + '-sla');
        const slaError = slaInput ? slaInput.nextElementSibling : null;
        if (slaInput) slaInput.classList.remove('is-invalid');
        const slaVal = parseInt(slaInput ? slaInput.value : '', 10);
        if (!slaInput || slaInput.value.trim() === '') {
            if (slaInput) slaInput.classList.add('is-invalid');
            if (slaError) slaError.textContent = 'Las horas SLA son requeridas';
            valid = false;
        } else if (isNaN(slaVal) || slaVal <= 0) {
            if (slaInput) slaInput.classList.add('is-invalid');
            if (slaError) slaError.textContent = 'Debe ser un número entero mayor que 0';
            valid = false;
        } else if (slaVal > 10000) {
            if (slaInput) slaInput.classList.add('is-invalid');
            if (slaError) slaError.textContent = 'Máximo 10000 horas';
            valid = false;
        }

        return valid;
    }

    // === BIND MODAL CREAR ===
    function bindCreateModal() {
        const modal = document.getElementById('modal-priority-create');
        if (!modal) return;
        if (modal.dataset.listenerBound) return;
        modal.dataset.listenerBound = '1';

        // Auto-uppercase en code
        const codeInput = modal.querySelector('#prio-create-code');
        if (codeInput) {
            codeInput.addEventListener('input', function () {
                const pos = codeInput.selectionStart;
                codeInput.value = codeInput.value.toUpperCase().replace(/\s/g, '_');
                codeInput.setSelectionRange(pos, pos);
            });
        }

        // Preview en tiempo real
        function doPreview() {
            updateBadgePreview(modal, 'prio-create-badge', 'prio-create-label', 'prio-create-color', 'prio-create-badge-preview');
        }

        modal.addEventListener('change', function (e) {
            if (e.target.id === 'prio-create-badge' || e.target.id === 'prio-create-color') {
                doPreview();
            }
        });
        modal.addEventListener('input', function (e) {
            if (e.target.id === 'prio-create-label') {
                doPreview();
            }
        });

        const btnSave = modal.querySelector('#btn-prio-create-save');
        if (!btnSave) return;

        btnSave.addEventListener('click', async function () {
            if (!validatePriorityForm(modal, true)) return;

            const code = modal.querySelector('#prio-create-code').value.trim().toUpperCase();
            const label = modal.querySelector('#prio-create-label').value.trim();
            const sla_hours = parseInt(modal.querySelector('#prio-create-sla').value, 10);
            const badge_class = modal.querySelector('#prio-create-badge').value;
            const color = modal.querySelector('#prio-create-color').value;

            btnSave.disabled = true;

            try {
                const res = await fetch(API_BASE, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        code: code,
                        label: label,
                        sla_hours: sla_hours,
                        badge_class: badge_class || null,
                        color: color || null,
                    }),
                });

                if (!res.ok) {
                    const msg = await apiErrorMsg(res, 'Error al crear prioridad');
                    HelpdeskUtils.showToast(msg, 'error');
                    return;
                }

                const data = await res.json();
                HelpdeskUtils.showToast(data.message || 'Prioridad creada exitosamente', 'success');
                bootstrap.Modal.getInstance(modal).hide();

                priorities.push(data.priority);
                renderList();
            } catch (err) {
                HelpdeskUtils.showToast('Error de conexión', 'error');
            } finally {
                btnSave.disabled = false;
            }
        });
    }

    // === BIND MODAL EDITAR ===
    function bindEditModal() {
        const modal = document.getElementById('modal-priority-edit');
        if (!modal) return;
        if (modal.dataset.listenerBound) return;
        modal.dataset.listenerBound = '1';

        // Preview en tiempo real
        function doPreview() {
            updateBadgePreview(modal, 'prio-edit-badge', 'prio-edit-label', 'prio-edit-color', 'prio-edit-badge-preview');
        }

        modal.addEventListener('change', function (e) {
            if (e.target.id === 'prio-edit-badge' || e.target.id === 'prio-edit-color') {
                doPreview();
            }
        });
        modal.addEventListener('input', function (e) {
            if (e.target.id === 'prio-edit-label') {
                doPreview();
            }
        });

        const btnSave = modal.querySelector('#btn-prio-edit-save');
        if (!btnSave) return;

        btnSave.addEventListener('click', async function () {
            if (!validatePriorityForm(modal, false)) return;

            const id = parseInt(modal.querySelector('#prio-edit-id').value, 10);
            const label = modal.querySelector('#prio-edit-label').value.trim();
            const sla_hours = parseInt(modal.querySelector('#prio-edit-sla').value, 10);
            const badge_class = modal.querySelector('#prio-edit-badge').value;
            const color = modal.querySelector('#prio-edit-color').value;

            btnSave.disabled = true;

            try {
                const res = await fetch(API_BASE + '/' + id, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        label: label,
                        sla_hours: sla_hours,
                        badge_class: badge_class || null,
                        color: color || null,
                    }),
                });

                if (!res.ok) {
                    const msg = await apiErrorMsg(res, 'Error al actualizar prioridad');
                    HelpdeskUtils.showToast(msg, 'error');
                    return;
                }

                const data = await res.json();
                HelpdeskUtils.showToast(data.message || 'Prioridad actualizada', 'success');
                bootstrap.Modal.getInstance(modal).hide();

                // Actualizar local
                const idx = priorities.findIndex(function (p) { return p.id === id; });
                if (idx !== -1) priorities[idx] = data.priority;
                renderList();
            } catch (err) {
                HelpdeskUtils.showToast('Error de conexión', 'error');
            } finally {
                btnSave.disabled = false;
            }
        });
    }

})();
