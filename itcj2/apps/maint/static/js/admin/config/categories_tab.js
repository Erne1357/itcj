/**
 * categories_tab.js — CRUD de categorías para el tab #categorias
 * en la página de Configuración de Mantenimiento.
 *
 * Carga lazy: window.MaintConfigCategories.init() es invocado por
 * config_main.js la primera vez que se activa el tab #categorias.
 *
 * Depende de:
 *   - window.MaintUtils  (maint-utils.js)
 *   - window.MaintFieldTemplateBuilder  (field_template_builder.js)
 */

'use strict';

// === ESTADO ===
var _categories = [];
var _catModal = null;
var _editingId = null;
var _initialized = false;

// === API PÚBLICA (lazy init) ===
window.MaintConfigCategories = {
    init: function () {
        if (_initialized) return;
        _initialized = true;
        _setup();
        _loadCategories();
    },
    /**
     * Actualiza el contador de #campos en la fila de una categoría
     * después de que el builder guarda un template.
     * @param {number} categoryId
     * @param {number} fieldCount
     */
    updateFieldCount: function (categoryId, fieldCount) {
        var cell = document.querySelector('[data-cat-fields="' + categoryId + '"]');
        if (cell) {
            cell.textContent = fieldCount;
        }
    },
};

// === SETUP ===
function _setup() {
    _catModal = new bootstrap.Modal(document.getElementById('modal-categoria'));

    document.getElementById('btn-nueva-categoria').addEventListener('click', _openCreateModal);
    document.getElementById('btn-guardar-categoria').addEventListener('click', _handleSaveCategoria);

    // Previsualización de icono en tiempo real
    document.getElementById('cat-icon').addEventListener('input', _updateIconPreview);

    // Delegación de acciones en la tabla (una sola vez)
    document.getElementById('tbody-categorias').addEventListener('click', _handleTableAction);
}

// === CARGA DE DATOS ===
async function _loadCategories() {
    var tbody = document.getElementById('tbody-categorias');
    tbody.innerHTML =
        '<tr><td colspan="7" class="text-center py-4 text-muted">' +
        '<span class="spinner-border spinner-border-sm me-2" role="status"></span>' +
        'Cargando categorías...</td></tr>';

    try {
        var data = await MaintUtils.api.fetch('/api/maint/v2/categories?only_active=false');
        _categories = data.categories || [];
        _renderTable(_categories);
    } catch (e) {
        MaintUtils.toast(e.message || 'Error al cargar categorías', 'error');
        tbody.innerHTML =
            '<tr><td colspan="7" class="text-center py-4 text-danger small">' +
            '<i class="fas fa-exclamation-circle me-1"></i>' +
            MaintUtils.escapeHtml(e.message || 'Error de conexión') +
            '</td></tr>';
    }
}

// === RENDER ===
function _renderTable(items) {
    var tbody = document.getElementById('tbody-categorias');

    if (!items.length) {
        tbody.innerHTML =
            '<tr><td colspan="7" class="text-center py-5 text-muted">' +
            '<i class="fas fa-tags fa-2x mb-3 d-block opacity-50"></i>' +
            'Sin categorías. Crea la primera con el botón "Nueva categoría".' +
            '</td></tr>';
        return;
    }

    // El listener de delegación ya está adjunto (en _setup). Solo se reemplaza innerHTML.
    tbody.innerHTML = items.map(function (cat) {
        var iconClass = cat.icon ? 'fas ' + MaintUtils.escapeHtml(cat.icon) : 'fas fa-tag';
        var fieldCount = Array.isArray(cat.field_template) ? cat.field_template.length : 0;
        var activeBadge = cat.is_active
            ? '<span class="badge bg-success-subtle text-success border border-success-subtle">Activa</span>'
            : '<span class="badge bg-secondary-subtle text-secondary border border-secondary-subtle">Inactiva</span>';
        var toggleLabel = cat.is_active ? 'Desactivar' : 'Activar';
        var toggleIcon = cat.is_active ? 'fa-toggle-on text-success' : 'fa-toggle-off text-secondary';

        return '<tr data-cat-id="' + cat.id + '">' +
            '<td class="text-center">' +
                '<i class="' + iconClass + ' text-primary"></i>' +
            '</td>' +
            '<td><code class="mn-cat-code">' + MaintUtils.escapeHtml(cat.code) + '</code></td>' +
            '<td>' +
                '<span class="fw-medium">' + MaintUtils.escapeHtml(cat.name) + '</span>' +
                (cat.description
                    ? '<br><span class="text-muted small">' + MaintUtils.escapeHtml(cat.description) + '</span>'
                    : '') +
            '</td>' +
            '<td class="text-center d-none d-md-table-cell text-muted small">' +
                MaintUtils.escapeHtml(String(cat.display_order)) +
            '</td>' +
            '<td class="text-center">' +
                '<span class="badge bg-primary-subtle text-primary border border-primary-subtle" ' +
                    'data-cat-fields="' + cat.id + '">' +
                    fieldCount +
                '</span>' +
            '</td>' +
            '<td class="text-center">' + activeBadge + '</td>' +
            '<td class="text-end">' +
                '<div class="btn-group btn-group-sm" role="group">' +
                    '<button class="btn btn-outline-secondary" ' +
                            'data-action="edit" data-id="' + cat.id + '" ' +
                            'title="Editar categoría">' +
                        '<i class="fas fa-pencil-alt"></i>' +
                    '</button>' +
                    '<button class="btn btn-outline-secondary" ' +
                            'data-action="toggle" data-id="' + cat.id + '" ' +
                            'title="' + toggleLabel + '">' +
                        '<i class="fas ' + toggleIcon + '"></i>' +
                    '</button>' +
                    '<button class="btn btn-outline-primary" ' +
                            'data-action="fields" data-id="' + cat.id + '" ' +
                            'title="Editar campos dinámicos">' +
                        '<i class="fas fa-th-list"></i>' +
                    '</button>' +
                '</div>' +
            '</td>' +
        '</tr>';
    }).join('');
}

// === DELEGACIÓN DE ACCIONES EN TABLA ===
function _handleTableAction(e) {
    var btn = e.target.closest('[data-action]');
    if (!btn) return;

    var action = btn.dataset.action;
    var id = parseInt(btn.dataset.id, 10);
    var cat = _categories.find(function (c) { return c.id === id; });
    if (!cat) return;

    if (action === 'edit') {
        _openEditModal(cat);
    } else if (action === 'toggle') {
        _handleToggle(cat, btn);
    } else if (action === 'fields') {
        if (window.MaintFieldTemplateBuilder) {
            window.MaintFieldTemplateBuilder.open(cat);
        }
    }
}

// === MODAL CREAR ===
function _openCreateModal() {
    _editingId = null;
    document.getElementById('modal-categoria-label').textContent = 'Nueva categoría';
    _resetForm();
    _catModal.show();
}

// === MODAL EDITAR ===
function _openEditModal(cat) {
    _editingId = cat.id;
    document.getElementById('modal-categoria-label').textContent = 'Editar categoría';
    _resetForm();

    document.getElementById('cat-edit-id').value = cat.id;
    document.getElementById('cat-code').value = cat.code || '';
    document.getElementById('cat-code').disabled = true; // código no editable
    document.getElementById('cat-name').value = cat.name || '';
    document.getElementById('cat-description').value = cat.description || '';
    document.getElementById('cat-icon').value = cat.icon || '';
    document.getElementById('cat-display-order').value = cat.display_order !== null ? cat.display_order : 0;

    _updateIconPreview();
    _catModal.show();
}

// === RESET FORM ===
function _resetForm() {
    var form = document.getElementById('form-categoria');
    form.classList.remove('was-validated');
    form.reset();

    document.getElementById('cat-edit-id').value = '';
    document.getElementById('cat-code').disabled = false;
    document.getElementById('cat-code-err').textContent = '';
    document.getElementById('cat-name-err').textContent = '';
    document.getElementById('cat-code').classList.remove('is-invalid');
    document.getElementById('cat-name').classList.remove('is-invalid');
    _updateIconPreview();
}

// === PREVISUALIZACIÓN DE ICONO ===
function _updateIconPreview() {
    var val = (document.getElementById('cat-icon').value || '').trim();
    var iconEl = document.getElementById('cat-icon-preview-i');
    iconEl.className = val ? 'fas ' + val : 'fas fa-tag';
}

// === GUARDAR CATEGORÍA ===
async function _handleSaveCategoria() {
    var btn = document.getElementById('btn-guardar-categoria');

    var code = document.getElementById('cat-code').value.trim().toUpperCase();
    var name = document.getElementById('cat-name').value.trim();
    var description = document.getElementById('cat-description').value.trim();
    var icon = document.getElementById('cat-icon').value.trim();
    var displayOrder = parseInt(document.getElementById('cat-display-order').value, 10) || 0;

    // Validación cliente
    var valid = true;
    if (!_editingId && !code) {
        document.getElementById('cat-code').classList.add('is-invalid');
        document.getElementById('cat-code-err').textContent = 'El código es requerido.';
        valid = false;
    } else {
        document.getElementById('cat-code').classList.remove('is-invalid');
    }
    if (!name) {
        document.getElementById('cat-name').classList.add('is-invalid');
        document.getElementById('cat-name-err').textContent = 'El nombre es requerido.';
        valid = false;
    } else {
        document.getElementById('cat-name').classList.remove('is-invalid');
    }
    if (!valid) return;

    MaintUtils.loading.show(btn, 'Guardando...');
    try {
        if (_editingId) {
            // PATCH
            await MaintUtils.api.fetch('/api/maint/v2/categories/' + _editingId, {
                method: 'PATCH',
                body: JSON.stringify({ name: name, description: description || null, icon: icon || null, display_order: displayOrder }),
            });
            MaintUtils.toast('Categoría actualizada correctamente', 'success');
        } else {
            // POST
            await MaintUtils.api.fetch('/api/maint/v2/categories', {
                method: 'POST',
                body: JSON.stringify({
                    code: code,
                    name: name,
                    description: description || null,
                    icon: icon || null,
                    display_order: displayOrder,
                }),
            });
            MaintUtils.toast('Categoría creada correctamente', 'success');
        }
        _catModal.hide();
        await _loadCategories();
    } catch (e) {
        MaintUtils.toast(e.message || 'Error al guardar', 'error');
    } finally {
        MaintUtils.loading.hide(btn);
    }
}

// === TOGGLE ACTIVO ===
async function _handleToggle(cat, btn) {
    var newState = !cat.is_active;
    var label = newState ? 'activar' : 'desactivar';

    MaintUtils.confirm({
        title: (newState ? 'Activar' : 'Desactivar') + ' categoría',
        message: '¿Deseas ' + label + ' la categoría "' + cat.name + '"?',
        confirmLabel: newState ? 'Activar' : 'Desactivar',
        confirmClass: newState ? 'btn-success' : 'btn-warning',
        onConfirm: async function () {
            MaintUtils.loading.show(btn, '');
            try {
                await MaintUtils.api.fetch('/api/maint/v2/categories/' + cat.id + '/toggle', {
                    method: 'PATCH',
                    body: JSON.stringify({ is_active: newState }),
                });
                MaintUtils.toast(
                    'Categoría ' + (newState ? 'activada' : 'desactivada'),
                    newState ? 'success' : 'warning'
                );
                await _loadCategories();
            } catch (e) {
                MaintUtils.toast(e.message || 'Error al cambiar estado', 'error');
                MaintUtils.loading.hide(btn);
            }
        },
    });
}
