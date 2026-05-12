/**
 * statuses_tab.js
 * Sub-sección "Estados" dentro del tab #estados del panel de Configuración.
 *
 * Responsabilidades:
 *  - Lista ordenable de estados con drag-drop (persiste vía POST /reorder).
 *  - Solo editar metadata: label, color, badge_class, icon, display_order.
 *  - NO crear ni borrar estados — el catálogo es fijo.
 *  - Toggle is_active (con validación de tickets activos en backend).
 *  - Badge preview en tiempo real al editar.
 *  - Toggle "mostrar inactivos".
 *  - Lazy init: carga datos solo la primera vez que el tab #estados es visible.
 */
(function () {
    'use strict';

    // === ESTADO ===
    let initialized = false;
    let statuses = [];
    let showInactive = false;
    let sortableInstance = null;

    // === CONSTANTES ===
    const API_BASE = '/api/help-desk/v2/config/statuses';

    const BADGE_CLASS_OPTIONS = [
        { value: 'bg-secondary',         label: 'Gris (secondary)' },
        { value: 'bg-primary',           label: 'Azul (primary)' },
        { value: 'bg-info text-dark',    label: 'Celeste (info)' },
        { value: 'bg-success',           label: 'Verde (success)' },
        { value: 'bg-warning text-dark', label: 'Amarillo (warning)' },
        { value: 'bg-danger',            label: 'Rojo (danger)' },
        { value: 'bg-dark',              label: 'Negro (dark)' },
        { value: 'bg-warning',           label: 'Amarillo sin contraste (warning)' },
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

    function buildBadgeClassSelect(selectId, currentValue) {
        const opts = BADGE_CLASS_OPTIONS.map(function (opt) {
            const sel = (opt.value === currentValue) ? ' selected' : '';
            return '<option value="' + escapeHtml(opt.value) + '"' + sel + '>' + escapeHtml(opt.label) + '</option>';
        }).join('');
        return '<select class="form-select form-select-sm" id="' + selectId + '">' + opts + '</select>';
    }

    function findById(id) {
        return statuses.find(function (s) { return s.id === id; }) || null;
    }

    function renderStageBadge(stage) {
        const stageMap = {
            'created':   { label: 'Creado',    cls: 'bg-secondary' },
            'assigned':  { label: 'Asignado',  cls: 'bg-primary' },
            'in_progress': { label: 'En progreso', cls: 'bg-info text-dark' },
            'resolved':  { label: 'Resuelto',  cls: 'bg-success' },
            'closed':    { label: 'Cerrado',   cls: 'bg-dark' },
            'canceled':  { label: 'Cancelado', cls: 'bg-warning text-dark' },
        };
        const s = stageMap[stage] || { label: escapeHtml(stage || '—'), cls: 'bg-secondary' };
        return '<span class="badge ' + s.cls + ' small">' + escapeHtml(s.label) + '</span>';
    }

    function renderFlagChips(status) {
        const chips = [];
        if (status.is_open)     chips.push('<span class="status-flag-chip status-flag--open">abierto</span>');
        if (status.is_resolved) chips.push('<span class="status-flag-chip status-flag--resolved">resuelto</span>');
        if (status.is_terminal) chips.push('<span class="status-flag-chip status-flag--terminal">terminal</span>');
        return chips.join('');
    }

    // === INIT ===
    document.addEventListener('config:tab-shown', function (e) {
        if (e.detail && e.detail.tab === '#estados') {
            if (!initialized) {
                initialized = true;
                initStatusesSection();
            }
        }
    });

    document.addEventListener('DOMContentLoaded', function () {
        const hash = window.location.hash || '';
        if (hash === '#estados') {
            if (!initialized) {
                initialized = true;
                initStatusesSection();
            }
        }
        bindEditModal();
    });

    function initStatusesSection() {
        renderShell();
        loadStatuses();
    }

    // === RENDER SHELL ===
    function renderShell() {
        const root = document.getElementById('estados-statuses-section');
        if (!root) return;

        root.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
                <h5 class="mb-0 fw-semibold">
                    <i class="fas fa-tag me-2 text-primary"></i>Estados del Ticket
                </h5>
                <div class="d-flex align-items-center gap-2 flex-wrap">
                    <div class="form-check form-switch mb-0">
                        <input class="form-check-input" type="checkbox" id="toggle-inactive-status"
                               role="switch" ${showInactive ? 'checked' : ''}>
                        <label class="form-check-label small text-muted" for="toggle-inactive-status">
                            Mostrar inactivos
                        </label>
                    </div>
                </div>
            </div>
            <div class="alert alert-info py-2 small mb-3">
                <i class="fas fa-info-circle me-1"></i>
                Los estados del sistema son fijos. Solo puedes editar su presentación visual (label, color, icono) y activarlos o desactivarlos.
            </div>
            <div id="statuses-list-wrapper">
                <div class="text-center py-4 text-muted small">
                    <div class="spinner-border spinner-border-sm" role="status"></div>
                    Cargando...
                </div>
            </div>
        `;

        root.addEventListener('change', function (e) {
            if (e.target.id === 'toggle-inactive-status') {
                showInactive = e.target.checked;
                renderList();
            }
        });
    }

    // === CARGA DE DATOS ===
    async function loadStatuses() {
        const wrapper = document.getElementById('statuses-list-wrapper');
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
                const msg = await apiErrorMsg(res, 'Error al cargar estados');
                HelpdeskUtils.showToast(msg, 'error');
                if (wrapper) wrapper.innerHTML = '<div class="text-danger small p-2">Error al cargar estados.</div>';
                return;
            }
            const data = await res.json();
            statuses = data.statuses || [];
            renderList();
        } catch (err) {
            console.error('Error loading statuses:', err);
            HelpdeskUtils.showToast('Error de conexión al cargar estados', 'error');
        }
    }

    // === RENDER LISTA ===
    function renderList() {
        const wrapper = document.getElementById('statuses-list-wrapper');
        if (!wrapper) return;

        const visible = statuses.filter(function (s) {
            return showInactive ? true : s.is_active;
        });

        if (!visible.length) {
            wrapper.innerHTML = `
                <div class="text-center py-5 text-muted">
                    <i class="fas fa-tag fa-3x mb-3 opacity-50"></i>
                    <p>${showInactive ? 'Sin estados configurados.' : 'Sin estados activos.'}</p>
                </div>`;
            return;
        }

        wrapper.innerHTML = `
            <div class="priority-list-info text-muted small mb-2">
                <i class="fas fa-info-circle me-1"></i>
                Arrastra las filas para cambiar el orden de visualización.
            </div>
            <div id="status-sortable-list" class="status-sortable-list">
                ${visible.map(renderStatusRow).join('')}
            </div>`;

        bindRowActions(wrapper);
        initSortable();
    }

    function renderStatusRow(s) {
        const badgeCls = escapeHtml(s.badge_class || 'bg-secondary');
        const color = s.color ? escapeHtml(s.color) : '';
        const colorStyle = color ? ' style="background-color:' + color + ' !important;"' : '';
        const iconCls = s.icon ? escapeHtml(s.icon) : 'fa-circle';
        const inactiveCls = s.is_active ? '' : 'status-row--inactive';

        const pct = (typeof s.progress_pct === 'number') ? s.progress_pct : 0;

        return `
            <div class="status-row ${inactiveCls}" data-id="${s.id}">
                <span class="drag-handle" title="Arrastrar para reordenar">
                    <i class="fas fa-grip-vertical"></i>
                </span>
                <div class="status-badge-preview">
                    <span class="badge ${badgeCls}"${colorStyle}>
                        <i class="fas ${iconCls} me-1"></i>${escapeHtml(s.label)}
                    </span>
                </div>
                <div class="status-row-info">
                    <code class="priority-row-code">${escapeHtml(s.code)}</code>
                    ${!s.is_active ? '<span class="badge bg-warning text-dark ms-1 small">Inactivo</span>' : ''}
                </div>
                <div class="status-row-meta">
                    ${renderStageBadge(s.stage)}
                    ${renderFlagChips(s)}
                </div>
                <div class="status-progress-col">
                    <div class="status-progress-bar" title="${pct}%">
                        <div class="progress" style="height:6px; width:80px;">
                            <div class="progress-bar bg-primary" role="progressbar"
                                 style="width:${pct}%"
                                 aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
                            </div>
                        </div>
                        <span class="status-pct-label text-muted">${pct}%</span>
                    </div>
                </div>
                <div class="status-row-actions">
                    <div class="form-check form-switch mb-0" title="${s.is_active ? 'Desactivar' : 'Activar'}">
                        <input class="form-check-input status-toggle" type="checkbox"
                               data-id="${s.id}" ${s.is_active ? 'checked' : ''}>
                    </div>
                    <button class="btn btn-sm btn-outline-secondary status-btn-edit" title="Editar presentación"
                            data-id="${s.id}">
                        <i class="fas fa-pencil-alt"></i>
                    </button>
                </div>
            </div>`;
    }

    function bindRowActions(container) {
        container.querySelectorAll('.status-toggle').forEach(function (chk) {
            chk.addEventListener('change', function () {
                handleToggle(parseInt(chk.dataset.id), chk.checked, chk);
            });
        });

        container.querySelectorAll('.status-btn-edit').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const s = findById(parseInt(btn.dataset.id));
                if (s) openEditModal(s);
            });
        });
    }

    // === SORTABLE ===
    function initSortable() {
        if (typeof Sortable === 'undefined') return;
        const list = document.getElementById('status-sortable-list');
        if (!list) return;

        if (sortableInstance) {
            sortableInstance.destroy();
            sortableInstance = null;
        }

        sortableInstance = Sortable.create(list, {
            handle: '.drag-handle',
            animation: 150,
            ghostClass: 'status-row--ghost',
            onEnd: function () { handleReorder(); },
        });
    }

    async function handleReorder() {
        const list = document.getElementById('status-sortable-list');
        if (!list) return;

        const rows = list.querySelectorAll('.status-row[data-id]');
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
            if (data.statuses && data.statuses.length) {
                statuses = data.statuses;
            } else {
                order.forEach(function (item) {
                    const s = findById(item.id);
                    if (s) s.display_order = item.display_order;
                });
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
            const s = findById(id);
            if (s) s.is_active = isActive;
            HelpdeskUtils.showToast(data.message || (isActive ? 'Estado activado' : 'Estado desactivado'), 'success');
            renderList();
        } catch (err) {
            HelpdeskUtils.showToast('Error de conexión', 'error');
            checkbox.checked = original;
        } finally {
            checkbox.disabled = false;
        }
    }

    // === MODAL EDITAR ===
    function openEditModal(s) {
        const modal = document.getElementById('modal-status-edit');
        if (!modal) return;

        modal.querySelector('#status-edit-id').value = s.id;
        modal.querySelector('#status-edit-code-display').textContent = s.code;
        modal.querySelector('#status-edit-label').value = s.label || '';
        modal.querySelector('#status-edit-color').value = s.color || '#6c757d';
        modal.querySelector('#status-edit-icon').value = s.icon || '';
        modal.querySelector('#status-edit-display-order').value = s.display_order || 1;

        const badgeWrap = modal.querySelector('#status-edit-badge-wrap');
        if (badgeWrap) {
            badgeWrap.innerHTML = buildBadgeClassSelect('status-edit-badge', s.badge_class || 'bg-secondary');
        }

        modal.querySelectorAll('.is-invalid').forEach(function (el) { el.classList.remove('is-invalid'); });
        modal.querySelectorAll('.invalid-feedback').forEach(function (el) { el.textContent = ''; });

        updateModalPreview(modal);

        bootstrap.Modal.getOrCreateInstance(modal).show();
    }

    function updateModalPreview(modal) {
        const badgeSelect = modal.querySelector('#status-edit-badge');
        const labelInput  = modal.querySelector('#status-edit-label');
        const colorInput  = modal.querySelector('#status-edit-color');
        const iconInput   = modal.querySelector('#status-edit-icon');
        const preview     = modal.querySelector('#status-edit-badge-preview');
        if (!preview) return;

        const badgeCls = badgeSelect ? badgeSelect.value : 'bg-secondary';
        const label    = labelInput  ? (labelInput.value.trim() || 'Estado') : 'Estado';
        const color    = colorInput  ? colorInput.value : '';
        const icon     = iconInput   ? (iconInput.value.trim() || 'fa-circle') : 'fa-circle';

        let styleAttr = '';
        if (color && color !== '#6c757d') {
            styleAttr = ' style="background-color:' + color + ' !important;"';
        }

        preview.innerHTML =
            '<span class="badge ' + escapeHtml(badgeCls) + '"' + styleAttr + '>' +
            '<i class="fas ' + escapeHtml(icon) + ' me-1"></i>' +
            escapeHtml(label) +
            '</span>';
    }

    function updateIconPreview(modal) {
        const iconInput = modal.querySelector('#status-edit-icon');
        const preview   = modal.querySelector('#status-edit-icon-preview');
        if (!iconInput || !preview) return;
        const icon = iconInput.value.trim() || 'fa-circle';
        preview.className = 'fas ' + escapeHtml(icon) + ' fa-lg text-muted';
    }

    // === BIND MODAL EDITAR ===
    function bindEditModal() {
        const modal = document.getElementById('modal-status-edit');
        if (!modal) return;
        if (modal.dataset.statusListenerBound) return;
        modal.dataset.statusListenerBound = '1';

        modal.addEventListener('input', function (e) {
            const id = e.target.id;
            if (id === 'status-edit-label' || id === 'status-edit-icon') {
                updateModalPreview(modal);
                if (id === 'status-edit-icon') updateIconPreview(modal);
            }
        });
        modal.addEventListener('change', function (e) {
            const id = e.target.id;
            if (id === 'status-edit-badge' || id === 'status-edit-color') {
                updateModalPreview(modal);
            }
        });

        const btnSave = modal.querySelector('#btn-status-edit-save');
        if (!btnSave) return;

        btnSave.addEventListener('click', async function () {
            const labelInput = modal.querySelector('#status-edit-label');
            const labelVal   = labelInput ? labelInput.value.trim() : '';
            if (!labelVal) {
                if (labelInput) {
                    labelInput.classList.add('is-invalid');
                    const fb = labelInput.nextElementSibling;
                    if (fb) fb.textContent = 'La etiqueta es requerida';
                }
                return;
            }
            if (labelInput) labelInput.classList.remove('is-invalid');

            const id          = parseInt(modal.querySelector('#status-edit-id').value, 10);
            const badge_class = modal.querySelector('#status-edit-badge').value;
            const color       = modal.querySelector('#status-edit-color').value;
            const icon        = modal.querySelector('#status-edit-icon').value.trim() || null;
            const display_order = parseInt(modal.querySelector('#status-edit-display-order').value, 10) || 1;

            btnSave.disabled = true;

            try {
                const res = await fetch(API_BASE + '/' + id, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        label: labelVal,
                        badge_class: badge_class || null,
                        color: color || null,
                        icon: icon,
                        display_order: display_order,
                    }),
                });

                if (!res.ok) {
                    const msg = await apiErrorMsg(res, 'Error al actualizar estado');
                    HelpdeskUtils.showToast(msg, 'error');
                    return;
                }

                const data = await res.json();
                HelpdeskUtils.showToast(data.message || 'Estado actualizado', 'success');
                bootstrap.Modal.getInstance(modal).hide();

                const idx = statuses.findIndex(function (s) { return s.id === id; });
                if (idx !== -1 && data.status) statuses[idx] = data.status;
                renderList();
            } catch (err) {
                HelpdeskUtils.showToast('Error de conexión', 'error');
            } finally {
                btnSave.disabled = false;
            }
        });
    }

})();
