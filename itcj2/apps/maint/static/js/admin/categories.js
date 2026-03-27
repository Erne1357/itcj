/**
 * admin-categories.js — Administración de categorías de Mantenimiento
 * Expone: window.MaintAdminCat (para callbacks en línea del HTML generado)
 */
'use strict';

(function () {

    var API = '/api/maint/v2';

    var FIELD_TYPES = [
        { value: 'text',   label: 'Texto' },
        { value: 'number', label: 'Número' },
        { value: 'date',   label: 'Fecha' },
        { value: 'time',   label: 'Hora' },
        { value: 'select', label: 'Lista desplegable' },
    ];

    var _categories = [];
    var _categoryModal = null;
    var _ftModal = null;

    // ── Init ──────────────────────────────────────────────────────────────────

    function init() {
        _categoryModal = new bootstrap.Modal(document.getElementById('categoryModal'));
        _ftModal = new bootstrap.Modal(document.getElementById('fieldTemplateModal'));

        document.getElementById('btnNewCategory').addEventListener('click', openNewCategoryModal);
        document.getElementById('btnSaveCategory').addEventListener('click', saveCategory);
        document.getElementById('btnAddField').addEventListener('click', addFieldRow);
        document.getElementById('btnSaveFieldTemplate').addEventListener('click', saveFieldTemplate);

        document.getElementById('categoryIcon').addEventListener('input', function () {
            updateIconPreview(this.value.trim());
        });

        loadCategories();
    }

    // ── Carga y renderizado ───────────────────────────────────────────────────

    function loadCategories() {
        var container = document.getElementById('categoriesTableContainer');
        container.innerHTML =
            '<div class="text-center py-5 text-muted">' +
            '<div class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></div>' +
            'Cargando categorías...</div>';

        MaintUtils.api.fetch(API + '/categories?only_active=false')
            .then(function (data) {
                _categories = data.categories || [];
                renderTable();
            })
            .catch(function () {
                container.innerHTML =
                    '<div class="alert alert-danger m-3">' +
                    '<i class="bi bi-exclamation-triangle me-2"></i>Error al cargar las categorías.</div>';
            });
    }

    function renderTable() {
        var container = document.getElementById('categoriesTableContainer');

        if (!_categories.length) {
            container.innerHTML =
                '<div class="text-center py-5 text-muted">' +
                '<i class="bi bi-tags fs-3 d-block mb-2"></i>' +
                'No hay categorías registradas. Crea la primera con el botón de arriba.</div>';
            return;
        }

        var rows = _categories.map(function (c) {
            var statusBadge = c.is_active
                ? '<span class="badge" style="background:#dcfce7;color:#166534;">Activa</span>'
                : '<span class="badge bg-secondary">Inactiva</span>';

            var fieldInfo = (c.field_template && c.field_template.length)
                ? '<span class="badge" style="background:#e0f2fe;color:#0369a1;">' +
                  c.field_template.length + ' campo' + (c.field_template.length !== 1 ? 's' : '') + '</span>'
                : '<span class="text-muted small">—</span>';

            var toggleTitle = c.is_active ? 'Desactivar' : 'Activar';
            var toggleIcon  = c.is_active ? 'bi-toggle-on' : 'bi-toggle-off';
            var toggleClass = c.is_active ? 'btn-outline-warning' : 'btn-outline-success';
            var newState    = !c.is_active;

            return '<tr class="' + (c.is_active ? '' : 'table-secondary') + '">' +
                '<td class="text-center fw-bold text-muted" style="width:55px;">' + c.display_order + '</td>' +
                '<td style="width:50px;" class="text-center">' +
                    '<i class="' + escHtml(c.icon || 'bi-tools') + ' fs-5" style="color:var(--maint-primary);"></i>' +
                '</td>' +
                '<td>' +
                    '<span class="badge bg-light border text-dark" style="font-family:monospace;font-size:0.8rem;">' +
                    escHtml(c.code) + '</span>' +
                '</td>' +
                '<td class="fw-semibold" style="color:var(--maint-primary-darker);">' + escHtml(c.name) + '</td>' +
                '<td class="text-muted small" style="max-width:240px;">' +
                    '<span title="' + escHtml(c.description || '') + '">' +
                    escHtml(truncate(c.description || '—', 60)) + '</span>' +
                '</td>' +
                '<td>' + fieldInfo + '</td>' +
                '<td>' + statusBadge + '</td>' +
                '<td>' +
                    '<div class="d-flex gap-1 flex-nowrap">' +
                        '<button class="btn btn-sm btn-outline-secondary" ' +
                            'onclick="MaintAdminCat.editCategory(' + c.id + ')" title="Editar categoría">' +
                            '<i class="bi bi-pencil"></i>' +
                        '</button>' +
                        '<button class="btn btn-sm btn-outline-primary" ' +
                            'onclick="MaintAdminCat.editFieldTemplate(' + c.id + ')" title="Editar campos dinámicos">' +
                            '<i class="bi bi-list-ul"></i>' +
                        '</button>' +
                        '<button class="btn btn-sm ' + toggleClass + '" ' +
                            'onclick="MaintAdminCat.toggleCategory(' + c.id + ', ' + newState + ')" title="' + toggleTitle + '">' +
                            '<i class="bi ' + toggleIcon + '"></i>' +
                        '</button>' +
                    '</div>' +
                '</td>' +
            '</tr>';
        }).join('');

        container.innerHTML =
            '<div class="table-responsive">' +
            '<table class="table table-hover align-middle mb-0" style="font-size:0.88rem;">' +
            '<thead class="table-light">' +
            '<tr>' +
            '<th class="text-center" style="width:55px;">Orden</th>' +
            '<th style="width:50px;"></th>' +
            '<th>Código</th>' +
            '<th>Nombre</th>' +
            '<th>Descripción</th>' +
            '<th>Campos</th>' +
            '<th>Estado</th>' +
            '<th>Acciones</th>' +
            '</tr>' +
            '</thead>' +
            '<tbody>' + rows + '</tbody>' +
            '</table>' +
            '</div>';
    }

    // ── Modal crear / editar ──────────────────────────────────────────────────

    function openNewCategoryModal() {
        document.getElementById('categoryId').value = '';
        document.getElementById('categoryCode').value = '';
        document.getElementById('categoryCode').disabled = false;
        document.getElementById('categoryName').value = '';
        document.getElementById('categoryDescription').value = '';
        document.getElementById('categoryIcon').value = 'bi-tools';
        document.getElementById('categoryOrder').value = '0';
        document.getElementById('categoryModalTitle').textContent = 'Nueva Categoría';
        updateIconPreview('bi-tools');
        _categoryModal.show();
    }

    function editCategory(categoryId) {
        var cat = _categories.find(function (c) { return c.id === categoryId; });
        if (!cat) return;

        document.getElementById('categoryId').value = cat.id;
        document.getElementById('categoryCode').value = cat.code;
        document.getElementById('categoryCode').disabled = true; // código inmutable
        document.getElementById('categoryName').value = cat.name;
        document.getElementById('categoryDescription').value = cat.description || '';
        document.getElementById('categoryIcon').value = cat.icon || 'bi-tools';
        document.getElementById('categoryOrder').value = cat.display_order || 0;
        document.getElementById('categoryModalTitle').textContent = 'Editar Categoría';
        updateIconPreview(cat.icon || 'bi-tools');
        _categoryModal.show();
    }

    function saveCategory() {
        var catId   = document.getElementById('categoryId').value;
        var name    = document.getElementById('categoryName').value.trim();
        var code    = document.getElementById('categoryCode').value.trim().toUpperCase();
        var desc    = document.getElementById('categoryDescription').value.trim();
        var icon    = document.getElementById('categoryIcon').value.trim() || 'bi-tools';
        var order   = parseInt(document.getElementById('categoryOrder').value, 10) || 0;
        var btn     = document.getElementById('btnSaveCategory');

        if (!name) { MaintUtils.toast('El nombre es requerido', 'warning'); return; }
        if (!catId && !code) { MaintUtils.toast('El código es requerido', 'warning'); return; }

        MaintUtils.loading.show(btn, 'Guardando...');

        var url, method, body;
        if (catId) {
            url    = API + '/categories/' + catId;
            method = 'PATCH';
            body   = { name: name, description: desc || null, icon: icon, display_order: order };
        } else {
            url    = API + '/categories';
            method = 'POST';
            body   = { code: code, name: name, description: desc || null, icon: icon, display_order: order };
        }

        MaintUtils.api.fetch(url, { method: method, body: JSON.stringify(body) })
            .then(function () {
                MaintUtils.toast(catId ? 'Categoría actualizada' : 'Categoría creada', 'success');
                _categoryModal.hide();
                loadCategories();
            })
            .catch(function (err) {
                MaintUtils.toast((err && err.message) || 'Error al guardar', 'error');
            })
            .finally(function () {
                MaintUtils.loading.hide(btn);
            });
    }

    function toggleCategory(categoryId, newState) {
        MaintUtils.confirm({
            title: newState ? 'Activar categoría' : 'Desactivar categoría',
            message: newState
                ? '¿Activar esta categoría? Los usuarios podrán seleccionarla al crear solicitudes.'
                : '¿Desactivar esta categoría? No podrá usarse en nuevas solicitudes, pero los tickets existentes no se ven afectados.',
            confirmLabel: newState ? 'Activar' : 'Desactivar',
            confirmClass: newState ? 'btn-success' : 'btn-warning',
            onConfirm: function () {
                MaintUtils.api.fetch(API + '/categories/' + categoryId + '/toggle', {
                    method: 'PATCH',
                    body: JSON.stringify({ is_active: newState }),
                })
                    .then(function () {
                        MaintUtils.toast(newState ? 'Categoría activada' : 'Categoría desactivada', 'success');
                        loadCategories();
                    })
                    .catch(function () {
                        MaintUtils.toast('Error al cambiar estado', 'error');
                    });
            },
        });
    }

    // ── Field Template ────────────────────────────────────────────────────────

    function editFieldTemplate(categoryId) {
        var cat = _categories.find(function (c) { return c.id === categoryId; });
        if (!cat) return;

        document.getElementById('ftCategoryId').value = cat.id;
        document.getElementById('ftCategoryName').textContent = cat.name + ' (' + cat.code + ')';
        renderFieldRows(cat.field_template || []);
        _ftModal.show();
    }

    function renderFieldRows(fields) {
        var container = document.getElementById('ftFieldsList');
        if (!fields.length) {
            container.innerHTML =
                '<p class="text-muted small fst-italic">' +
                'Sin campos definidos. Agrega el primero con el botón de abajo.</p>';
            return;
        }
        container.innerHTML = '';
        fields.forEach(function (f, idx) {
            container.insertAdjacentHTML('beforeend', buildFieldRowHtml(f, idx));
        });
    }

    function buildFieldRowHtml(field, idx) {
        var typeOpts = FIELD_TYPES.map(function (t) {
            return '<option value="' + t.value + '"' + (field.type === t.value ? ' selected' : '') + '>' +
                   t.label + '</option>';
        }).join('');

        var isSelect = field.type === 'select';
        var optionsVal = isSelect ? escHtml((field.options || []).join('\n')) : '';

        return '<div class="card mb-2 ft-field-row border" data-idx="' + idx + '" ' +
               'style="border-color:#CFD8DC!important;">' +
            '<div class="card-body py-2 px-3">' +
                '<div class="d-flex justify-content-between align-items-center mb-2">' +
                    '<span class="fw-semibold small" style="color:var(--maint-muted);">' +
                        'Campo #' + (idx + 1) +
                    '</span>' +
                    '<button type="button" class="btn-close btn-sm" ' +
                        'onclick="MaintAdminCat.removeFieldRow(this)" ' +
                        'aria-label="Eliminar campo"></button>' +
                '</div>' +
                '<div class="row g-2">' +
                    '<div class="col-6">' +
                        '<label class="form-label small mb-1">Clave <span class="text-danger">*</span></label>' +
                        '<input type="text" class="form-control form-control-sm ft-field-key" ' +
                               'value="' + escHtml(field.key || '') + '" ' +
                               'placeholder="destination" style="font-family:monospace;">' +
                    '</div>' +
                    '<div class="col-6">' +
                        '<label class="form-label small mb-1">Etiqueta <span class="text-danger">*</span></label>' +
                        '<input type="text" class="form-control form-control-sm ft-field-label" ' +
                               'value="' + escHtml(field.label || '') + '" ' +
                               'placeholder="Destino">' +
                    '</div>' +
                    '<div class="col-6">' +
                        '<label class="form-label small mb-1">Tipo</label>' +
                        '<select class="form-select form-select-sm ft-field-type" ' +
                                'onchange="MaintAdminCat.onFieldTypeChange(this)">' +
                            typeOpts +
                        '</select>' +
                    '</div>' +
                    '<div class="col-6 d-flex align-items-end pb-1">' +
                        '<div class="form-check">' +
                            '<input class="form-check-input ft-field-required" type="checkbox" ' +
                                   (field.required ? 'checked' : '') + '>' +
                            '<label class="form-check-label small">Requerido</label>' +
                        '</div>' +
                    '</div>' +
                '</div>' +
                '<div class="ft-options-section mt-2" style="display:' + (isSelect ? '' : 'none') + ';">' +
                    '<label class="form-label small mb-1">' +
                        'Opciones (una por línea) <span class="text-danger">*</span>' +
                    '</label>' +
                    '<textarea class="form-control form-control-sm ft-field-options" rows="3" ' +
                              'placeholder="Opción 1&#10;Opción 2&#10;Opción 3">' +
                        optionsVal +
                    '</textarea>' +
                '</div>' +
            '</div>' +
        '</div>';
    }

    function addFieldRow() {
        var container = document.getElementById('ftFieldsList');
        var emptyMsg  = container.querySelector('p.fst-italic');
        if (emptyMsg) emptyMsg.remove();

        var currentCount = container.querySelectorAll('.ft-field-row').length;
        container.insertAdjacentHTML('beforeend', buildFieldRowHtml(
            { key: '', label: '', type: 'text', required: false },
            currentCount
        ));

        // Scroll suave al nuevo campo
        container.lastElementChild.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function removeFieldRow(btn) {
        var row = btn.closest('.ft-field-row');
        if (row) row.remove();

        // Reindexar labels
        document.querySelectorAll('#ftFieldsList .ft-field-row').forEach(function (r, i) {
            r.dataset.idx = i;
            var lbl = r.querySelector('.fw-semibold.small');
            if (lbl) lbl.textContent = 'Campo #' + (i + 1);
        });

        if (!document.querySelectorAll('#ftFieldsList .ft-field-row').length) {
            document.getElementById('ftFieldsList').innerHTML =
                '<p class="text-muted small fst-italic">' +
                'Sin campos definidos. Agrega el primero con el botón de abajo.</p>';
        }
    }

    function onFieldTypeChange(select) {
        var row     = select.closest('.ft-field-row');
        var section = row && row.querySelector('.ft-options-section');
        if (section) section.style.display = (select.value === 'select') ? '' : 'none';
    }

    function collectFieldRows() {
        var rows   = document.querySelectorAll('#ftFieldsList .ft-field-row');
        var fields = [];
        var valid  = true;

        rows.forEach(function (row) {
            var key      = row.querySelector('.ft-field-key').value.trim();
            var label    = row.querySelector('.ft-field-label').value.trim();
            var type     = row.querySelector('.ft-field-type').value;
            var required = row.querySelector('.ft-field-required').checked;

            if (!key || !label) {
                valid = false;
                row.style.borderColor = '#dc3545';
                return;
            }
            row.style.borderColor = '';

            var field = { key: key, label: label, type: type, required: required };

            if (type === 'select') {
                var raw = row.querySelector('.ft-field-options').value.trim();
                field.options = raw
                    ? raw.split('\n').map(function (s) { return s.trim(); }).filter(Boolean)
                    : [];
                if (!field.options.length) {
                    valid = false;
                    row.querySelector('.ft-field-options').style.borderColor = '#dc3545';
                    return;
                }
            }

            fields.push(field);
        });

        return valid ? fields : null;
    }

    function saveFieldTemplate() {
        var catId  = document.getElementById('ftCategoryId').value;
        var fields = collectFieldRows();
        var btn    = document.getElementById('btnSaveFieldTemplate');

        if (fields === null) {
            MaintUtils.toast('Todos los campos necesitan clave, etiqueta y (para listas) al menos una opción', 'warning');
            return;
        }

        MaintUtils.loading.show(btn, 'Guardando...');
        MaintUtils.api.fetch(API + '/categories/' + catId + '/field-template', {
            method: 'PUT',
            body: JSON.stringify({ fields: fields }),
        })
            .then(function () {
                MaintUtils.toast('Campos actualizados correctamente', 'success');
                _ftModal.hide();
                loadCategories();
            })
            .catch(function (err) {
                MaintUtils.toast((err && err.message) || 'Error al guardar campos', 'error');
            })
            .finally(function () {
                MaintUtils.loading.hide(btn);
            });
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    function updateIconPreview(iconClass) {
        var icon = document.getElementById('categoryIconPreviewIcon');
        if (!icon) return;
        icon.className = (iconClass || 'bi-tools') + ' ' + (
            iconClass && iconClass.startsWith('fa') ? '' : ''
        );
        // Determinar si es Bootstrap Icons o FontAwesome
        if (iconClass && (iconClass.startsWith('fa-') || iconClass.startsWith('fas ') || iconClass.startsWith('far '))) {
            icon.className = iconClass;
        } else {
            icon.className = (iconClass || 'bi-tools');
        }
        icon.style.color = 'var(--maint-primary)';
    }

    function escHtml(str) {
        if (!str && str !== 0) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function truncate(str, max) {
        if (!str) return '';
        return str.length > max ? str.slice(0, max) + '…' : str;
    }

    // ── Público ───────────────────────────────────────────────────────────────

    window.MaintAdminCat = {
        editCategory:      editCategory,
        toggleCategory:    toggleCategory,
        editFieldTemplate: editFieldTemplate,
        removeFieldRow:    removeFieldRow,
        onFieldTypeChange: onFieldTypeChange,
    };

    // ── Arranque ──────────────────────────────────────────────────────────────

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
