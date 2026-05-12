/**
 * areas_tab.js
 * Sub-sección "Áreas" dentro del tab #areas del panel de Configuración.
 *
 * Responsabilidades:
 *  - Lista ordenable de 2 áreas (SOPORTE / DESARROLLO) con drag-drop (persiste vía POST /reorder).
 *  - Solo editar metadata: label, icon, color, description, display_order.
 *  - NO crear ni borrar áreas — el catálogo es fijo (solo 2 áreas).
 *  - Toggle is_active (con advertencia al desactivar; backend valida tickets activos → 400).
 *  - Preview combinada en modal (ícono + color + label) en tiempo real.
 *  - Toggle "mostrar inactivas".
 *  - Lazy init: carga datos solo la primera vez que el tab #areas es visible.
 */
(function () {
    'use strict';

    // === ESTADO ===
    let initialized = false;
    let areas = [];
    let showInactive = false;
    let sortableInstance = null;

    // === CONSTANTES ===
    const API_BASE = '/api/help-desk/v2/config/areas';

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

    function findById(id) {
        return areas.find(function (a) { return a.id === id; }) || null;
    }

    // === INIT ===
    document.addEventListener('config:tab-shown', function (e) {
        if (e.detail && e.detail.tab === '#areas') {
            if (!initialized) {
                initialized = true;
                initAreasSection();
            }
        }
    });

    document.addEventListener('DOMContentLoaded', function () {
        const hash = window.location.hash || '';
        if (hash === '#areas') {
            if (!initialized) {
                initialized = true;
                initAreasSection();
            }
        }
        bindEditModal();
    });

    function initAreasSection() {
        renderShell();
        loadAreas();
    }

    // === RENDER SHELL ===
    function renderShell() {
        const root = document.getElementById('areas-root');
        if (!root) return;

        root.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
                <h5 class="mb-0 fw-semibold">
                    <i class="fas fa-layer-group me-2 text-primary"></i>Áreas de Servicio
                </h5>
                <div class="d-flex align-items-center gap-2 flex-wrap">
                    <div class="form-check form-switch mb-0">
                        <input class="form-check-input" type="checkbox" id="toggle-inactive-areas"
                               role="switch" ${showInactive ? 'checked' : ''}>
                        <label class="form-check-label small text-muted" for="toggle-inactive-areas">
                            Mostrar inactivas
                        </label>
                    </div>
                </div>
            </div>
            <div class="alert alert-info py-2 small mb-3">
                <i class="fas fa-info-circle me-1"></i>
                Las áreas del sistema son fijas (SOPORTE / DESARROLLO). Solo puedes editar su presentación visual
                (label, ícono, color, descripción) y activarlas o desactivarlas.
            </div>
            <div id="areas-list-wrapper">
                <div class="text-center py-4 text-muted small">
                    <div class="spinner-border spinner-border-sm" role="status"></div>
                    Cargando...
                </div>
            </div>
        `;

        root.addEventListener('change', function (e) {
            if (e.target.id === 'toggle-inactive-areas') {
                showInactive = e.target.checked;
                renderList();
            }
        });
    }

    // === CARGA DE DATOS ===
    async function loadAreas() {
        const wrapper = document.getElementById('areas-list-wrapper');
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
                const msg = await apiErrorMsg(res, 'Error al cargar áreas');
                HelpdeskUtils.showToast(msg, 'error');
                if (wrapper) wrapper.innerHTML = '<div class="text-danger small p-2">Error al cargar áreas.</div>';
                return;
            }
            const data = await res.json();
            areas = data.areas || [];
            renderList();
        } catch (err) {
            console.error('Error loading areas:', err);
            HelpdeskUtils.showToast('Error de conexión al cargar áreas', 'error');
        }
    }

    // === RENDER LISTA ===
    function renderList() {
        const wrapper = document.getElementById('areas-list-wrapper');
        if (!wrapper) return;

        const visible = areas.filter(function (a) {
            return showInactive ? true : a.is_active;
        });

        if (!visible.length) {
            wrapper.innerHTML = `
                <div class="text-center py-5 text-muted">
                    <i class="fas fa-layer-group fa-3x mb-3 opacity-50"></i>
                    <p>${showInactive ? 'Sin áreas configuradas.' : 'Sin áreas activas.'}</p>
                </div>`;
            return;
        }

        wrapper.innerHTML = `
            <div class="priority-list-info text-muted small mb-2">
                <i class="fas fa-info-circle me-1"></i>
                Arrastra las filas para cambiar el orden de visualización.
            </div>
            <div id="areas-sortable-list" class="areas-sortable-list">
                ${visible.map(renderAreaRow).join('')}
            </div>`;

        bindRowActions(wrapper);
        initSortable();
    }

    function renderAreaRow(a) {
        const icon     = escapeHtml(a.icon || 'fa-layer-group');
        const color    = escapeHtml(a.color || '#6c757d');
        const label    = escapeHtml(a.label || a.code);
        const code     = escapeHtml(a.code);
        const desc     = escapeHtml(a.description || '');
        const inactive = a.is_active ? '' : 'area-row--inactive';

        return `
            <div class="area-row ${inactive}" data-id="${a.id}">
                <span class="drag-handle" title="Arrastrar para reordenar">
                    <i class="fas fa-grip-vertical"></i>
                </span>
                <div class="area-icon-large">
                    <i class="fas ${icon}" style="color:${color}; font-size:2rem;"></i>
                </div>
                <div class="area-info">
                    <div class="area-info-title">
                        ${label}
                        <span class="badge bg-secondary font-monospace ms-1 small">${code}</span>
                        ${!a.is_active ? '<span class="badge bg-warning text-dark ms-1 small">Inactiva</span>' : ''}
                    </div>
                    ${desc ? `<div class="area-info-desc">${desc}</div>` : '<div class="area-info-desc text-muted fst-italic small">Sin descripción</div>'}
                </div>
                <div class="area-row-actions">
                    <div class="form-check form-switch mb-0" title="${a.is_active ? 'Desactivar' : 'Activar'}">
                        <input class="form-check-input area-toggle" type="checkbox"
                               data-id="${a.id}" ${a.is_active ? 'checked' : ''}>
                    </div>
                    <button class="btn btn-sm btn-outline-secondary area-btn-edit" title="Editar presentación"
                            data-id="${a.id}">
                        <i class="fas fa-pencil-alt"></i>
                    </button>
                </div>
            </div>`;
    }

    function bindRowActions(container) {
        container.querySelectorAll('.area-toggle').forEach(function (chk) {
            chk.addEventListener('change', function () {
                handleToggle(parseInt(chk.dataset.id), chk.checked, chk);
            });
        });

        container.querySelectorAll('.area-btn-edit').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const a = findById(parseInt(btn.dataset.id));
                if (a) openEditModal(a);
            });
        });
    }

    // === SORTABLE ===
    function initSortable() {
        if (typeof Sortable === 'undefined') return;
        const list = document.getElementById('areas-sortable-list');
        if (!list) return;

        if (sortableInstance) {
            sortableInstance.destroy();
            sortableInstance = null;
        }

        sortableInstance = Sortable.create(list, {
            handle: '.drag-handle',
            animation: 150,
            ghostClass: 'area-row--ghost',
            onEnd: function () { handleReorder(); },
        });
    }

    async function handleReorder() {
        const list = document.getElementById('areas-sortable-list');
        if (!list) return;

        const rows = list.querySelectorAll('.area-row[data-id]');
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
            if (data.areas && data.areas.length) {
                areas = data.areas;
            } else {
                order.forEach(function (item) {
                    const a = findById(item.id);
                    if (a) a.display_order = item.display_order;
                });
            }
        } catch (err) {
            HelpdeskUtils.showToast('Error de conexión al reordenar', 'error');
        }
    }

    // === TOGGLE ===
    async function handleToggle(id, isActive, checkbox) {
        const original = !isActive;

        // Advertencia al desactivar
        if (!isActive) {
            const confirmed = await HelpdeskUtils.confirmDialog(
                'Desactivar área',
                'Si desactivas esta área, los usuarios no podrán seleccionarla al crear tickets. ' +
                'Los tickets existentes no se ven afectados.',
                'Desactivar',
                'Cancelar'
            );
            if (!confirmed) {
                checkbox.checked = original;
                return;
            }
        }

        doToggle(id, isActive, checkbox, original);
    }

    async function doToggle(id, isActive, checkbox, original) {
        checkbox.disabled = true;

        try {
            const res = await fetch(API_BASE + '/' + id + '/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_active: isActive }),
            });
            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al cambiar estado del área');
                HelpdeskUtils.showToast(msg, 'error');
                checkbox.checked = original;
                return;
            }
            const data = await res.json();
            const a = findById(id);
            if (a) a.is_active = isActive;
            HelpdeskUtils.showToast(data.message || (isActive ? 'Área activada' : 'Área desactivada'), 'success');
            renderList();
        } catch (err) {
            HelpdeskUtils.showToast('Error de conexión', 'error');
            checkbox.checked = original;
        } finally {
            checkbox.disabled = false;
        }
    }

    // === MODAL EDITAR ===
    function openEditModal(a) {
        const modal = document.getElementById('modal-area-edit');
        if (!modal) return;

        modal.querySelector('#area-edit-id').value = a.id;
        modal.querySelector('#area-edit-code-display').textContent = a.code;
        modal.querySelector('#area-edit-label').value = a.label || '';
        modal.querySelector('#area-edit-icon').value = a.icon || '';
        modal.querySelector('#area-edit-color').value = a.color || '#0d6efd';
        modal.querySelector('#area-edit-description').value = a.description || '';
        modal.querySelector('#area-edit-display-order').value = a.display_order || 1;

        modal.querySelectorAll('.is-invalid').forEach(function (el) { el.classList.remove('is-invalid'); });
        modal.querySelectorAll('.invalid-feedback').forEach(function (el) { el.textContent = ''; });

        updateIconPreview(modal);
        updateModalPreview(modal);

        bootstrap.Modal.getOrCreateInstance(modal).show();
    }

    function updateIconPreview(modal) {
        const iconInput  = modal.querySelector('#area-edit-icon');
        const colorInput = modal.querySelector('#area-edit-color');
        const preview    = modal.querySelector('#area-edit-icon-preview');
        if (!iconInput || !preview) return;
        const icon  = iconInput.value.trim() || 'fa-layer-group';
        const color = colorInput ? colorInput.value : '#6c757d';
        preview.className = 'fas ' + escapeHtml(icon) + ' fa-lg';
        preview.style.color = color;
    }

    function updateModalPreview(modal) {
        const labelInput = modal.querySelector('#area-edit-label');
        const iconInput  = modal.querySelector('#area-edit-icon');
        const colorInput = modal.querySelector('#area-edit-color');
        const preview    = modal.querySelector('#area-edit-combined-preview');
        if (!preview) return;

        const label = labelInput ? (labelInput.value.trim() || 'Área') : 'Área';
        const icon  = iconInput  ? (iconInput.value.trim() || 'fa-layer-group') : 'fa-layer-group';
        const color = colorInput ? colorInput.value : '#6c757d';

        preview.innerHTML =
            '<i class="fas ' + escapeHtml(icon) + ' me-2" style="color:' + escapeHtml(color) + '; font-size:1.6rem; vertical-align:middle;"></i>' +
            '<span class="fw-semibold fs-6">' + escapeHtml(label) + '</span>';
    }

    // === BIND MODAL EDITAR ===
    function bindEditModal() {
        const modal = document.getElementById('modal-area-edit');
        if (!modal) return;
        if (modal.dataset.areaListenerBound) return;
        modal.dataset.areaListenerBound = '1';

        modal.addEventListener('input', function (e) {
            const id = e.target.id;
            if (id === 'area-edit-label' || id === 'area-edit-icon') {
                updateIconPreview(modal);
                updateModalPreview(modal);
            }
        });
        modal.addEventListener('change', function (e) {
            if (e.target.id === 'area-edit-color') {
                updateIconPreview(modal);
                updateModalPreview(modal);
            }
        });

        const btnSave = modal.querySelector('#btn-area-edit-save');
        if (!btnSave) return;

        btnSave.addEventListener('click', async function () {
            const labelInput = modal.querySelector('#area-edit-label');
            const labelVal   = labelInput ? labelInput.value.trim() : '';

            if (!labelVal) {
                if (labelInput) {
                    labelInput.classList.add('is-invalid');
                    const fb = labelInput.nextElementSibling;
                    if (fb && fb.classList.contains('invalid-feedback')) fb.textContent = 'La etiqueta es requerida';
                }
                return;
            }
            if (labelInput) labelInput.classList.remove('is-invalid');

            const id            = parseInt(modal.querySelector('#area-edit-id').value, 10);
            const icon          = modal.querySelector('#area-edit-icon').value.trim() || null;
            const color         = modal.querySelector('#area-edit-color').value;
            const description   = modal.querySelector('#area-edit-description').value.trim() || null;
            const display_order = parseInt(modal.querySelector('#area-edit-display-order').value, 10) || 1;

            btnSave.disabled = true;

            try {
                const res = await fetch(API_BASE + '/' + id, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        label: labelVal,
                        icon: icon,
                        color: color || null,
                        description: description,
                        display_order: display_order,
                    }),
                });

                if (!res.ok) {
                    const msg = await apiErrorMsg(res, 'Error al actualizar área');
                    HelpdeskUtils.showToast(msg, 'error');
                    return;
                }

                const data = await res.json();
                HelpdeskUtils.showToast(data.message || 'Área actualizada', 'success');
                bootstrap.Modal.getInstance(modal).hide();

                const idx = areas.findIndex(function (a) { return a.id === id; });
                if (idx !== -1 && data.area) areas[idx] = data.area;
                renderList();
            } catch (err) {
                HelpdeskUtils.showToast('Error de conexión', 'error');
            } finally {
                btnSave.disabled = false;
            }
        });
    }

})();
