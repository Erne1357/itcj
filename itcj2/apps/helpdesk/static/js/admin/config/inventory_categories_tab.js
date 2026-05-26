/**
 * inventory_categories_tab.js
 * Tab "Cat. de Inventario" del panel de Configuración.
 *
 * Responsabilidades:
 *  - Lista de categorías de inventario en grid/tabla.
 *  - CRUD: crear, editar, toggle activa, soft-delete.
 *  - Lazy init: carga datos solo la primera vez que el tab es visible.
 */
(function () {
    'use strict';

    // === ESTADO ===
    let initialized = false;
    let categories = [];

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
            return (typeof v === 'string' && v) ? v : fallback;
        } catch (_) {
            return fallback + ' (HTTP ' + res.status + ')';
        }
    }

    // === INIT ===
    document.addEventListener('config:tab-shown', function (e) {
        if (e.detail && e.detail.tab === '#inv-cat') {
            if (!initialized) {
                initialized = true;
                initInvCatTab();
            }
        }
    });

    function initInvCatTab() {
        renderShell();
        loadCategories();
    }

    // === SHELL ===
    function renderShell() {
        const root = document.getElementById('inv-cat-root');
        if (!root) return;

        root.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
                <h5 class="mb-0 fw-semibold">
                    <i class="fas fa-boxes me-2 text-info"></i>Categorías de Inventario
                </h5>
                <button class="btn btn-sm btn-info text-white" id="btn-new-inv-cat">
                    <i class="fas fa-plus me-1"></i><span class="d-none d-sm-inline">Nueva categoría</span>
                </button>
            </div>

            <div id="inv-cat-table-wrapper">
                <div class="text-center py-4 text-muted small">
                    <div class="spinner-border spinner-border-sm me-1" role="status"></div>
                    Cargando...
                </div>
            </div>
        `;

        const btnNew = root.querySelector('#btn-new-inv-cat');
        if (btnNew) {
            btnNew.addEventListener('click', function () { openInvCatModal(null); });
        }
    }

    // === CARGA ===
    async function loadCategories() {
        const wrapper = document.getElementById('inv-cat-table-wrapper');
        if (wrapper) {
            wrapper.innerHTML = `
                <div class="text-center py-4 text-muted small">
                    <div class="spinner-border spinner-border-sm me-1" role="status"></div>
                    Cargando...
                </div>`;
        }

        try {
            const res = await fetch('/api/help-desk/v2/inventory/categories?with_count=true');
            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al cargar categorías de inventario');
                HelpdeskUtils.showToast(msg, 'error');
                if (wrapper) wrapper.innerHTML = '<div class="text-danger small p-2">Error al cargar</div>';
                return;
            }
            const data = await res.json();
            categories = data.data || [];
            renderTable();
        } catch (err) {
            console.error('Error loading inventory categories:', err);
            HelpdeskUtils.showToast('Error al cargar categorías de inventario', 'error');
        }
    }

    // === RENDER TABLA ===
    function renderTable() {
        const wrapper = document.getElementById('inv-cat-table-wrapper');
        if (!wrapper) return;

        if (!categories.length) {
            wrapper.innerHTML = `
                <div class="text-center py-5 text-muted">
                    <i class="fas fa-boxes fa-3x mb-3 opacity-50"></i>
                    <p>Sin categorías de inventario. Crea la primera.</p>
                </div>`;
            return;
        }

        wrapper.innerHTML = `
            <div class="table-responsive">
                <table class="table table-hover align-middle mb-0" id="inv-cat-table">
                    <thead class="table-light">
                        <tr>
                            <th style="width:48px;">Icono</th>
                            <th>Nombre</th>
                            <th>Código</th>
                            <th>Prefijo</th>
                            <th class="text-center">Equipos</th>
                            <th class="text-center">Estado</th>
                            <th class="text-end">Acciones</th>
                        </tr>
                    </thead>
                    <tbody id="inv-cat-tbody">
                        ${categories.map(renderTableRow).join('')}
                    </tbody>
                </table>
            </div>`;

        bindTableActions();
    }

    function renderTableRow(cat) {
        const icon = cat.icon || 'fas fa-box';
        return `
            <tr data-id="${cat.id}" class="${cat.is_active ? '' : 'table-secondary text-muted'}">
                <td class="text-center">
                    <i class="${escapeHtml(icon)} fa-lg"></i>
                </td>
                <td>
                    <span class="fw-medium">${escapeHtml(cat.name)}</span>
                    ${cat.description ? `<br><small class="text-muted">${escapeHtml(cat.description)}</small>` : ''}
                </td>
                <td><code>${escapeHtml(cat.code)}</code></td>
                <td><span class="badge bg-secondary">${escapeHtml(cat.inventory_prefix || '')}</span></td>
                <td class="text-center">
                    <span class="badge bg-light text-dark border">
                        ${cat.items_count != null ? cat.items_count : '—'}
                    </span>
                </td>
                <td class="text-center">
                    <div class="form-check form-switch d-inline-block mb-0">
                        <input class="form-check-input inv-cat-toggle" type="checkbox" role="switch"
                               data-id="${cat.id}" ${cat.is_active ? 'checked' : ''}
                               title="${cat.is_active ? 'Desactivar' : 'Activar'}">
                    </div>
                </td>
                <td class="text-end">
                    <button class="btn btn-sm btn-outline-secondary inv-cat-btn-edit me-1"
                            data-id="${cat.id}" title="Editar">
                        <i class="fas fa-pencil-alt"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger inv-cat-btn-delete"
                            data-id="${cat.id}" data-name="${escapeHtml(cat.name)}" title="Desactivar">
                        <i class="fas fa-trash"></i>
                    </button>
                </td>
            </tr>`;
    }

    function bindTableActions() {
        const tbody = document.getElementById('inv-cat-tbody');
        if (!tbody) return;

        // Toggle
        tbody.querySelectorAll('.inv-cat-toggle').forEach(function (chk) {
            chk.addEventListener('change', function () {
                handleToggle(parseInt(chk.dataset.id), chk);
            });
        });

        // Editar
        tbody.querySelectorAll('.inv-cat-btn-edit').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const cat = categories.find(function (c) { return c.id === parseInt(btn.dataset.id); });
                if (cat) openInvCatModal(cat);
            });
        });

        // Eliminar
        tbody.querySelectorAll('.inv-cat-btn-delete').forEach(function (btn) {
            btn.addEventListener('click', function () {
                handleDelete(parseInt(btn.dataset.id), btn.dataset.name);
            });
        });
    }

    // === ACCIONES ===
    async function handleToggle(id, checkbox) {
        const original = !checkbox.checked;
        checkbox.disabled = true;

        try {
            const res = await fetch('/api/help-desk/v2/inventory/categories/' + id + '/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al cambiar estado');
                HelpdeskUtils.showToast(msg, 'error');
                checkbox.checked = original;
                return;
            }
            const data = await res.json();
            const cat = categories.find(function (c) { return c.id === id; });
            if (cat) cat.is_active = data.data.is_active;
            HelpdeskUtils.showToast(data.message || 'Estado actualizado', 'success');
            renderTable();
        } catch (err) {
            HelpdeskUtils.showToast('Error de conexión', 'error');
            checkbox.checked = original;
        } finally {
            checkbox.disabled = false;
        }
    }

    async function handleDelete(id, name) {
        const cat = categories.find(function (c) { return c.id === id; });
        if (cat && cat.items_count > 0) {
            HelpdeskUtils.showToast(
                'No se puede desactivar "' + escapeHtml(name) + '" — tiene ' + cat.items_count + ' equipo(s) activo(s).',
                'warning'
            );
            return;
        }

        const confirmed = await HelpdeskUtils.confirmDialog(
            'Desactivar categoría',
            '¿Desactivar la categoría de inventario <strong>' + escapeHtml(name) + '</strong>? Podrás reactivarla después.',
            'Desactivar',
            'Cancelar'
        );
        if (!confirmed) return;

        // El backend no tiene DELETE; usamos toggle para desactivar
        try {
            const res = await fetch('/api/help-desk/v2/inventory/categories/' + id + '/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al desactivar');
                HelpdeskUtils.showToast(msg, 'error');
                return;
            }
            const data = await res.json();
            HelpdeskUtils.showToast('Categoría desactivada', 'success');
            if (cat) cat.is_active = data.data ? data.data.is_active : false;
            renderTable();
        } catch (err) {
            HelpdeskUtils.showToast('Error de conexión', 'error');
        }
    }

    // === MODAL CRUD ===
    function openInvCatModal(cat) {
        const modal = document.getElementById('modal-inv-cat');
        if (!modal) return;

        const isEdit = !!cat;
        modal.querySelector('.modal-title').textContent = isEdit ? 'Editar categoría de inventario' : 'Nueva categoría de inventario';
        modal.querySelector('#inv-cat-id').value = cat ? cat.id : '';
        modal.querySelector('#inv-cat-code').value = cat ? (cat.code || '') : '';
        modal.querySelector('#inv-cat-name').value = cat ? (cat.name || '') : '';
        modal.querySelector('#inv-cat-prefix').value = cat ? (cat.inventory_prefix || '') : '';
        modal.querySelector('#inv-cat-icon').value = cat ? (cat.icon || 'fas fa-box') : 'fas fa-box';
        modal.querySelector('#inv-cat-description').value = cat ? (cat.description || '') : '';

        // Código solo editable al crear
        const codeInput = modal.querySelector('#inv-cat-code');
        if (codeInput) codeInput.readOnly = isEdit;

        // Reset errores
        modal.querySelectorAll('.is-invalid').forEach(function (el) { el.classList.remove('is-invalid'); });

        // Preview del icono
        updateIconPreview(modal);

        const bsModal = bootstrap.Modal.getOrCreateInstance(modal);
        bsModal.show();
    }

    function updateIconPreview(modal) {
        const iconInput = modal.querySelector('#inv-cat-icon');
        const preview = modal.querySelector('#inv-cat-icon-preview');
        if (!iconInput || !preview) return;
        preview.className = escapeHtml(iconInput.value) + ' fa-lg';
    }

    // === BIND MODAL (una sola vez al cargar DOM) ===
    document.addEventListener('DOMContentLoaded', function () {
        bindInvCatModal();
    });

    function bindInvCatModal() {
        const modal = document.getElementById('modal-inv-cat');
        if (!modal) return;
        if (modal.dataset.listenerBound) return;
        modal.dataset.listenerBound = '1';

        // Preview icono en tiempo real
        const iconInput = modal.querySelector('#inv-cat-icon');
        if (iconInput) {
            iconInput.addEventListener('input', function () { updateIconPreview(modal); });
        }

        const btnSave = modal.querySelector('#btn-inv-cat-save');
        if (!btnSave) return;

        btnSave.addEventListener('click', async function () {
            const id = modal.querySelector('#inv-cat-id').value;
            const code = modal.querySelector('#inv-cat-code').value.trim();
            const name = modal.querySelector('#inv-cat-name').value.trim();
            const prefix = modal.querySelector('#inv-cat-prefix').value.trim().toUpperCase();
            const icon = modal.querySelector('#inv-cat-icon').value.trim();
            const description = modal.querySelector('#inv-cat-description').value.trim();

            // Validaciones
            let valid = true;
            const codeInput = modal.querySelector('#inv-cat-code');
            const nameInput = modal.querySelector('#inv-cat-name');
            const prefixInput = modal.querySelector('#inv-cat-prefix');

            [codeInput, nameInput, prefixInput].forEach(function (el) {
                if (el) { el.classList.remove('is-invalid'); if (el.nextElementSibling) el.nextElementSibling.textContent = ''; }
            });

            if (!id && !code) {
                if (codeInput) { codeInput.classList.add('is-invalid'); if (codeInput.nextElementSibling) codeInput.nextElementSibling.textContent = 'El código es requerido'; }
                valid = false;
            }
            if (!name) {
                if (nameInput) { nameInput.classList.add('is-invalid'); if (nameInput.nextElementSibling) nameInput.nextElementSibling.textContent = 'El nombre es requerido'; }
                valid = false;
            }
            if (!prefix) {
                if (prefixInput) { prefixInput.classList.add('is-invalid'); if (prefixInput.nextElementSibling) prefixInput.nextElementSibling.textContent = 'El prefijo es requerido'; }
                valid = false;
            } else if (prefix.length < 2 || prefix.length > 10) {
                if (prefixInput) { prefixInput.classList.add('is-invalid'); if (prefixInput.nextElementSibling) prefixInput.nextElementSibling.textContent = 'El prefijo debe tener entre 2 y 10 caracteres'; }
                valid = false;
            }
            if (!valid) return;

            btnSave.disabled = true;

            try {
                let res;
                if (id) {
                    // Editar
                    res = await fetch('/api/help-desk/v2/inventory/categories/' + id, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name, icon: icon || 'fas fa-box', description: description || null, inventory_prefix: prefix }),
                    });
                } else {
                    // Crear
                    res = await fetch('/api/help-desk/v2/inventory/categories', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ code, name, icon: icon || 'fas fa-box', description: description || null, inventory_prefix: prefix }),
                    });
                }

                if (!res.ok) {
                    const msg = await apiErrorMsg(res, id ? 'Error al actualizar' : 'Error al crear');
                    HelpdeskUtils.showToast(msg, 'error');
                    return;
                }

                const data = await res.json();
                HelpdeskUtils.showToast(data.message || (id ? 'Categoría actualizada' : 'Categoría creada'), 'success');
                bootstrap.Modal.getInstance(modal).hide();

                // Actualizar local y re-render
                if (id) {
                    const idx = categories.findIndex(function (c) { return c.id === parseInt(id); });
                    if (idx !== -1) categories[idx] = data.data;
                } else {
                    categories.push(data.data);
                }
                renderTable();
            } catch (err) {
                HelpdeskUtils.showToast('Error de conexión', 'error');
            } finally {
                btnSave.disabled = false;
            }
        });
    }

})();
