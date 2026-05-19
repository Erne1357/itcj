/**
 * field_template_builder.js — Editor visual de field_template para categorías.
 *
 * Abre en modal-xl (#modal-builder), carga GET /config/field-templates/{id},
 * permite agregar/editar/reordenar/eliminar campos y guarda con
 * PUT /config/field-templates/{id} body { fields: [...] }.
 *
 * Schema de campo: { key, label, type, required, options? }
 * types válidos: text | number | date | time | select
 *
 * Depende de:
 *   - window.MaintUtils  (maint-utils.js)
 *   - window.MaintConfigCategories  (categories_tab.js)
 *   - SortableJS (CDN)
 */

(function () {
    'use strict';

    // === ESTADO ===
    var _builderModal = null;
    var _sortable = null;
    var _currentCat = null;
    var _originalKeys = [];   // keys que existían al abrir el modal
    var _fields = [];          // array de objetos campo en memoria

    var VALID_TYPES = ['text', 'number', 'date', 'time', 'select'];

    // === API PÚBLICA ===
    window.MaintFieldTemplateBuilder = {
        /**
         * Abre el modal builder para la categoría dada.
         * @param {{ id: number, code: string, name: string, field_template: Array }} cat
         */
        open: function (cat) {
            _currentCat = cat;
            _openBuilder(cat);
        },
    };

    // === INICIALIZACIÓN ===
    document.addEventListener('DOMContentLoaded', function () {
        var modalEl = document.getElementById('modal-builder');
        if (!modalEl) return;
        _builderModal = new bootstrap.Modal(modalEl);

        document.getElementById('btn-agregar-campo').addEventListener('click', _addField);
        document.getElementById('btn-guardar-template').addEventListener('click', _handleSaveTemplate);

        // Delegación en la lista de campos
        document.getElementById('builder-fields-list').addEventListener('click', _handleFieldListClick);
        document.getElementById('builder-fields-list').addEventListener('input', _handleFieldListInput);
        document.getElementById('builder-fields-list').addEventListener('change', _handleFieldListChange);
    });

    // === ABRIR BUILDER ===
    async function _openBuilder(cat) {
        document.getElementById('builder-cat-name').textContent = cat.name;
        document.getElementById('builder-cat-code').textContent = 'Código: ' + cat.code;
        document.getElementById('builder-save-error').classList.add('d-none');
        document.getElementById('builder-save-error').textContent = '';

        _fields = [];
        _originalKeys = [];
        _renderFieldsList();
        _renderPreview();

        _builderModal.show();

        try {
            var data = await MaintUtils.api.fetch('/api/maint/v2/config/field-templates/' + cat.id);
            var template = (data.data && Array.isArray(data.data.field_template))
                ? data.data.field_template
                : [];

            _fields = template.map(function (f, idx) {
                return {
                    _id: 'f-' + Date.now() + '-' + idx,
                    key: f.key || '',
                    label: f.label || '',
                    type: f.type || 'text',
                    required: !!f.required,
                    options: Array.isArray(f.options) ? f.options.slice() : [],
                };
            });
            _originalKeys = _fields.map(function (f) { return f.key; });
            _renderFieldsList();
            _renderPreview();
            _initSortable();
        } catch (e) {
            MaintUtils.toast(e.message || 'Error al cargar campos', 'error');
        }
    }

    // === SORTABLE ===
    function _initSortable() {
        var list = document.getElementById('builder-fields-list');
        if (_sortable) {
            _sortable.destroy();
            _sortable = null;
        }
        _sortable = new Sortable(list, {
            handle: '.mn-field-handle',
            animation: 150,
            ghostClass: 'mn-field-row--ghost',
            onEnd: function (evt) {
                // Sincronizar _fields con el nuevo orden del DOM
                var newOrder = [];
                list.querySelectorAll('.mn-field-row').forEach(function (row) {
                    var fid = row.dataset.fid;
                    var f = _fields.find(function (x) { return x._id === fid; });
                    if (f) newOrder.push(f);
                });
                _fields = newOrder;
                _renderPreview();
                _validateAll();
            },
        });
    }

    // === AGREGAR CAMPO ===
    function _addField() {
        var newField = {
            _id: 'f-' + Date.now() + '-' + Math.floor(Math.random() * 1000),
            key: '',
            label: '',
            type: 'text',
            required: false,
            options: [],
        };
        _fields.push(newField);
        _renderFieldsList();
        _initSortable();
        _renderPreview();

        // Scroll al último campo
        var list = document.getElementById('builder-fields-list');
        var lastRow = list.querySelector('.mn-field-row:last-child');
        if (lastRow) {
            lastRow.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            var keyInput = lastRow.querySelector('.mn-field-key');
            if (keyInput) keyInput.focus();
        }

        _hideEmptyState();
    }

    // === RENDER LISTA ===
    function _renderFieldsList() {
        var list = document.getElementById('builder-fields-list');

        if (!_fields.length) {
            list.innerHTML =
                '<div class="text-center text-muted py-4" id="builder-fields-empty">' +
                '<i class="fas fa-inbox fa-2x mb-2 d-block text-muted opacity-50"></i>' +
                'Sin campos. Usa "Agregar campo" para comenzar.' +
                '</div>';
            return;
        }

        list.innerHTML = _fields.map(function (f) {
            return _buildFieldRowHtml(f);
        }).join('');
    }

    function _buildFieldRowHtml(f) {
        var esc = MaintUtils.escapeHtml;
        var typeOptions = VALID_TYPES.map(function (t) {
            return '<option value="' + t + '"' + (f.type === t ? ' selected' : '') + '>' + _typeName(t) + '</option>';
        }).join('');

        var optionsHtml = '';
        if (f.type === 'select') {
            optionsHtml =
                '<div class="mn-field-options-wrap mt-2">' +
                    '<label class="form-label form-label-sm mb-1 text-muted">Opciones (mínimo 1)</label>' +
                    '<div class="mn-chips-container" data-fid="' + f._id + '">' +
                        _buildChipsHtml(f.options, f._id) +
                        '<input type="text" class="mn-chip-input form-control form-control-sm" ' +
                               'placeholder="Nueva opción… Enter para agregar" ' +
                               'data-fid="' + f._id + '" data-action="add-option">' +
                    '</div>' +
                    '<div class="mn-field-err small text-danger d-none" data-fid="' + f._id + '" data-err="options"></div>' +
                '</div>';
        }

        return '<div class="mn-field-row" data-fid="' + f._id + '">' +
            '<div class="mn-field-handle" title="Arrastrar para reordenar">' +
                '<i class="fas fa-grip-vertical text-muted"></i>' +
            '</div>' +
            '<div class="mn-field-body">' +
                '<div class="row g-2 align-items-start">' +
                    '<div class="col-sm-3">' +
                        '<label class="form-label form-label-sm mb-1">Key</label>' +
                        '<input type="text" class="form-control form-control-sm mn-field-key" ' +
                               'data-fid="' + f._id + '" data-field="key" ' +
                               'value="' + esc(f.key) + '" ' +
                               'placeholder="ej. numero_serie" maxlength="60">' +
                        '<div class="mn-field-err small text-danger d-none" data-fid="' + f._id + '" data-err="key"></div>' +
                    '</div>' +
                    '<div class="col-sm-4">' +
                        '<label class="form-label form-label-sm mb-1">Etiqueta</label>' +
                        '<input type="text" class="form-control form-control-sm mn-field-label" ' +
                               'data-fid="' + f._id + '" data-field="label" ' +
                               'value="' + esc(f.label) + '" ' +
                               'placeholder="Ej. Número de serie" maxlength="100">' +
                        '<div class="mn-field-err small text-danger d-none" data-fid="' + f._id + '" data-err="label"></div>' +
                    '</div>' +
                    '<div class="col-sm-3">' +
                        '<label class="form-label form-label-sm mb-1">Tipo</label>' +
                        '<select class="form-select form-select-sm mn-field-type" ' +
                                'data-fid="' + f._id + '" data-field="type">' +
                            typeOptions +
                        '</select>' +
                    '</div>' +
                    '<div class="col-sm-1 d-flex align-items-end justify-content-center pb-1">' +
                        '<div class="form-check form-switch mb-0" title="Requerido">' +
                            '<input class="form-check-input mn-field-required" type="checkbox" ' +
                                   'data-fid="' + f._id + '" data-field="required" ' +
                                   (f.required ? ' checked' : '') + ' ' +
                                   'id="req-' + f._id + '">' +
                            '<label class="form-check-label small text-muted" for="req-' + f._id + '">Req.</label>' +
                        '</div>' +
                    '</div>' +
                    '<div class="col-sm-1 d-flex align-items-end justify-content-end pb-1">' +
                        '<button class="btn btn-outline-danger btn-sm" ' +
                                'data-action="delete-field" data-fid="' + f._id + '" ' +
                                'title="Eliminar campo">' +
                            '<i class="fas fa-trash-alt"></i>' +
                        '</button>' +
                    '</div>' +
                '</div>' +
                optionsHtml +
            '</div>' +
        '</div>';
    }

    function _buildChipsHtml(options, fid) {
        return options.map(function (opt, idx) {
            return '<span class="mn-chip">' +
                '<span class="mn-chip-label">' + MaintUtils.escapeHtml(opt) + '</span>' +
                '<button type="button" class="mn-chip-remove" ' +
                        'data-action="remove-option" data-fid="' + fid + '" data-idx="' + idx + '" ' +
                        'aria-label="Eliminar opción">&times;</button>' +
            '</span>';
        }).join('');
    }

    function _typeName(t) {
        var names = { text: 'Texto', number: 'Número', date: 'Fecha', time: 'Hora', select: 'Selección' };
        return names[t] || t;
    }

    function _hideEmptyState() {
        var empty = document.getElementById('builder-fields-empty');
        if (empty) empty.remove();
    }

    // === DELEGACIÓN DE EVENTOS — CLICK ===
    function _handleFieldListClick(e) {
        var target = e.target;

        // Eliminar campo
        var delBtn = target.closest('[data-action="delete-field"]');
        if (delBtn) {
            var fid = delBtn.dataset.fid;
            var f = _getField(fid);
            if (!f) return;

            if (f.key && _originalKeys.includes(f.key)) {
                MaintUtils.confirm({
                    title: 'Eliminar campo existente',
                    message: 'El campo "' + f.key + '" ya existe en tickets anteriores. Al eliminarlo, los tickets antiguos perderán este dato. ¿Continuar?',
                    confirmLabel: 'Eliminar',
                    confirmClass: 'btn-danger',
                    onConfirm: function () { _deleteField(fid); },
                });
            } else {
                _deleteField(fid);
            }
            return;
        }

        // Eliminar opción (chip)
        var removeOpt = target.closest('[data-action="remove-option"]');
        if (removeOpt) {
            var fid2 = removeOpt.dataset.fid;
            var idx = parseInt(removeOpt.dataset.idx, 10);
            var f2 = _getField(fid2);
            if (!f2) return;
            f2.options.splice(idx, 1);
            _refreshOptionsChips(fid2);
            _validateField(f2);
            _renderPreview();
        }
    }

    // === DELEGACIÓN DE EVENTOS — INPUT ===
    function _handleFieldListInput(e) {
        var target = e.target;

        // Actualizar key / label
        if (target.classList.contains('mn-field-key') || target.classList.contains('mn-field-label')) {
            var fid = target.dataset.fid;
            var fieldName = target.dataset.field;
            var f = _getField(fid);
            if (!f) return;

            var oldKey = f.key;
            f[fieldName] = target.value;

            // Advertir si se renombra un key existente
            if (fieldName === 'key' && oldKey && oldKey !== f.key && _originalKeys.includes(oldKey)) {
                _showKeyRenameWarning(f, oldKey);
            }

            _validateField(f);
            _renderPreview();
        }

        // Escribir en el input de nueva opción: agregar al presionar Enter
        if (target.dataset.action === 'add-option') {
            // handled in keydown via input event won't catch Enter; use keydown below
        }
    }

    // === DELEGACIÓN DE EVENTOS — CHANGE ===
    function _handleFieldListChange(e) {
        var target = e.target;

        // Cambio de tipo
        if (target.classList.contains('mn-field-type')) {
            var fid = target.dataset.fid;
            var f = _getField(fid);
            if (!f) return;
            f.type = target.value;
            // Re-renderizar la fila para mostrar/ocultar sección de opciones
            _rerenderRow(f);
            _validateField(f);
            _renderPreview();
            return;
        }

        // Cambio de required
        if (target.classList.contains('mn-field-required')) {
            var fid2 = target.dataset.fid;
            var f2 = _getField(fid2);
            if (!f2) return;
            f2.required = target.checked;
            _renderPreview();
            return;
        }
    }

    // Captura Enter en inputs de opciones (keydown en el documento delegado al container)
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter') return;
        var target = e.target;
        if (target.dataset.action !== 'add-option') return;
        e.preventDefault();
        var fid = target.dataset.fid;
        var val = target.value.trim();
        if (!val) return;
        var f = _getField(fid);
        if (!f) return;
        if (f.options.includes(val)) {
            MaintUtils.toast('La opción "' + val + '" ya existe.', 'warning');
            return;
        }
        f.options.push(val);
        target.value = '';
        _refreshOptionsChips(fid);
        _validateField(f);
        _renderPreview();
    });

    // === HELPERS DE CAMPO ===
    function _getField(fid) {
        return _fields.find(function (f) { return f._id === fid; }) || null;
    }

    function _deleteField(fid) {
        _fields = _fields.filter(function (f) { return f._id !== fid; });
        _renderFieldsList();
        _initSortable();
        _renderPreview();
        _validateAll();
    }

    function _rerenderRow(f) {
        var list = document.getElementById('builder-fields-list');
        var row = list.querySelector('.mn-field-row[data-fid="' + f._id + '"]');
        if (!row) return;
        // Insertar el nuevo HTML antes del nodo actual y eliminar el viejo
        var tmp = document.createElement('div');
        tmp.innerHTML = _buildFieldRowHtml(f);
        var newRow = tmp.firstChild;
        row.parentNode.insertBefore(newRow, row);
        row.parentNode.removeChild(row);
        // Re-inicializar sortable para incluir la nueva fila en el DOM
        _initSortable();
    }

    function _refreshOptionsChips(fid) {
        var f = _getField(fid);
        if (!f) return;
        var container = document.querySelector('.mn-chips-container[data-fid="' + fid + '"]');
        if (!container) return;
        // Reemplazar chips (todo excepto el input)
        var chipInput = container.querySelector('.mn-chip-input');
        container.innerHTML = _buildChipsHtml(f.options, fid);
        container.appendChild(chipInput);
    }

    function _showKeyRenameWarning(f, oldKey) {
        MaintUtils.alert({
            type: 'warning',
            title: 'Renombrar key existente',
            message: 'El key "' + oldKey + '" ya existe en tickets anteriores. Si lo renombras, los tickets antiguos perderán la vinculación con este campo.',
        });
    }

    // === VALIDACIÓN ===
    var KEY_REGEX = /^[a-z][a-z0-9_]*$/;

    function _validateField(f) {
        var errors = {};

        if (!f.key) {
            errors.key = 'El key es requerido.';
        } else if (!KEY_REGEX.test(f.key)) {
            errors.key = 'Solo minúsculas, dígitos y guion bajo. Debe comenzar con letra.';
        } else {
            // Duplicado
            var dupes = _fields.filter(function (x) { return x.key === f.key; });
            if (dupes.length > 1) {
                errors.key = 'El key "' + f.key + '" está duplicado.';
            }
        }

        if (!f.label.trim()) {
            errors.label = 'La etiqueta es requerida.';
        }

        if (f.type === 'select') {
            var uniqueOpts = Array.from(new Set(f.options.filter(function (o) { return o.trim(); })));
            if (uniqueOpts.length === 0) {
                errors.options = 'El tipo Selección requiere al menos una opción.';
            }
        }

        _displayFieldErrors(f._id, errors);
        return Object.keys(errors).length === 0;
    }

    function _validateAll() {
        var allValid = true;
        _fields.forEach(function (f) {
            if (!_validateField(f)) allValid = false;
        });
        return allValid;
    }

    function _displayFieldErrors(fid, errors) {
        var fields = ['key', 'label', 'options'];
        fields.forEach(function (errKey) {
            var errEl = document.querySelector('[data-fid="' + fid + '"][data-err="' + errKey + '"]');
            if (!errEl) return;
            var inputEl = document.querySelector('[data-fid="' + fid + '"][data-field="' + errKey + '"]');
            if (errors[errKey]) {
                errEl.textContent = errors[errKey];
                errEl.classList.remove('d-none');
                if (inputEl) inputEl.classList.add('is-invalid');
            } else {
                errEl.textContent = '';
                errEl.classList.add('d-none');
                if (inputEl) inputEl.classList.remove('is-invalid');
            }
        });
    }

    // === VISTA PREVIA EN VIVO ===
    /**
     * Replica exacta de create.js _renderCustomFields() para la previsualización.
     */
    function _renderPreview() {
        var previewBody = document.getElementById('builder-preview-body');

        if (!_fields.length) {
            previewBody.innerHTML =
                '<div class="col-12 text-muted small text-center py-3" id="builder-preview-empty">' +
                'Agrega campos para ver la vista previa.' +
                '</div>';
            return;
        }

        var esc = MaintUtils.escapeHtml;

        var html = _fields.map(function (f) {
            var required = f.required ? ' <span class="text-danger">*</span>' : '';
            var input = '';
            var safeKey = esc(f.key || 'campo');
            var safeLabel = esc(f.label || '(sin etiqueta)');

            if (f.type === 'select' && Array.isArray(f.options)) {
                input = '<select class="form-select form-select-sm" disabled>' +
                    '<option value="">Selecciona...</option>' +
                    f.options.map(function (o) {
                        return '<option value="' + esc(o) + '">' + esc(o) + '</option>';
                    }).join('') +
                    '</select>';
            } else if (f.type === 'number') {
                input = '<input type="number" class="form-control form-control-sm" min="0" disabled>';
            } else if (f.type === 'date') {
                input = '<input type="date" class="form-control form-control-sm" disabled>';
            } else if (f.type === 'time') {
                input = '<input type="time" class="form-control form-control-sm" disabled>';
            } else {
                input = '<input type="text" class="form-control form-control-sm" disabled>';
            }

            return '<div class="col-md-6">' +
                '<label class="form-label form-label-sm fw-medium">' + safeLabel + required + '</label>' +
                input +
            '</div>';
        }).join('');

        previewBody.innerHTML = html;
    }

    // === GUARDAR TEMPLATE ===
    async function _handleSaveTemplate() {
        if (!_currentCat) return;

        var btn = document.getElementById('btn-guardar-template');
        var errEl = document.getElementById('builder-save-error');
        errEl.classList.add('d-none');
        errEl.textContent = '';

        // Validar todos los campos
        _validateAll();

        // Comprobar errores en DOM
        var hasErrors = document.querySelectorAll('#builder-fields-list .mn-field-err:not(.d-none)').length > 0;
        if (hasErrors) {
            errEl.textContent = 'Corrige los errores antes de guardar.';
            errEl.classList.remove('d-none');
            return;
        }

        var currentKeys = _fields.map(function (f) { return f.key; });

        // Construir payload (solo claves del schema real)
        var payload = {
            fields: _fields.map(function (f) {
                var obj = {
                    key: f.key,
                    label: f.label,
                    type: f.type,
                    required: f.required,
                };
                if (f.type === 'select') {
                    obj.options = f.options.filter(function (o) { return o.trim(); });
                }
                return obj;
            }),
        };

        MaintUtils.loading.show(btn, 'Guardando...');
        try {
            var data = await MaintUtils.api.fetch(
                '/api/maint/v2/config/field-templates/' + _currentCat.id,
                {
                    method: 'PUT',
                    body: JSON.stringify(payload),
                }
            );

            MaintUtils.toast('Campos guardados correctamente', 'success');

            // Actualizar el contador en la tabla de categorías
            if (window.MaintConfigCategories) {
                window.MaintConfigCategories.updateFieldCount(_currentCat.id, _fields.length);
            }

            // Actualizar originalKeys con el estado guardado
            _originalKeys = currentKeys.filter(Boolean);

            _builderModal.hide();
        } catch (e) {
            var msg = e.message || 'Error al guardar campos';
            errEl.textContent = msg;
            errEl.classList.remove('d-none');
            MaintUtils.toast(msg, 'error');
        } finally {
            MaintUtils.loading.hide(btn);
        }
    }

})();
