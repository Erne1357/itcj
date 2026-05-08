/**
 * field_template_builder.js
 * Modal builder de plantillas de campos personalizados.
 *
 * Se abre desde categories_tab.js al hacer clic en "Editar campos".
 * Layout 2 columnas: lista de campos editable (izquierda) + preview (derecha).
 * Expone window.FieldTemplateBuilder.open(categoryId, categoryName, area).
 */
(function () {
    'use strict';

    // === ESTADO ===
    let currentCategoryId = null;
    let currentCategoryName = '';
    let currentArea = '';
    let templateEnabled = false;
    let fields = [];            // array de objetos field
    let editingFieldIdx = null; // índice del campo en edición inline
    let sortableInstance = null;
    let modalInstance = null;

    // === CONSTANTES ===
    const FIELD_TYPES = [
        { value: 'text',     label: 'Texto (una línea)' },
        { value: 'textarea', label: 'Texto largo' },
        { value: 'select',   label: 'Lista desplegable' },
        { value: 'radio',    label: 'Opción múltiple (radio)' },
        { value: 'checkbox', label: 'Casilla de verificación' },
        { value: 'file',     label: 'Archivo adjunto' },
    ];
    const TYPES_WITH_OPTIONS = ['select', 'radio'];
    const KEY_REGEX = /^[a-z][a-z0-9_]*$/;
    const API = window.HelpdeskUtils.api;

    // === HELPERS ===
    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function toSnakeCase(str) {
        return str
            .toLowerCase()
            .replace(/\s+/g, '_')
            .replace(/[^a-z0-9_]/g, '')
            .replace(/^[^a-z]+/, '');
    }

    function deepClone(obj) {
        return JSON.parse(JSON.stringify(obj));
    }

    // === INICIALIZACIÓN ===
    document.addEventListener('DOMContentLoaded', function () {
        const modalEl = document.getElementById('modal-field-builder');
        if (!modalEl) return;

        modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl, { backdrop: 'static', keyboard: false });

        // Prevenir memory leaks: re-usar la instancia
        modalEl.addEventListener('hidden.bs.modal', function () {
            cleanupSortable();
        });

        bindModalControls(modalEl);
    });

    function bindModalControls(modalEl) {
        if (modalEl.dataset.builderBound) return;
        modalEl.dataset.builderBound = '1';

        // Switch global habilitado
        const toggleEl = modalEl.querySelector('#field-builder-enabled');
        if (toggleEl) {
            toggleEl.addEventListener('change', function () {
                templateEnabled = toggleEl.checked;
                renderFieldList();
                updatePreview();
            });
        }

        // Botón agregar campo
        const btnAdd = modalEl.querySelector('#btn-builder-add-field');
        if (btnAdd) {
            btnAdd.addEventListener('click', addNewField);
        }

        // Botón guardar plantilla
        const btnSave = modalEl.querySelector('#btn-builder-save');
        if (btnSave) {
            btnSave.addEventListener('click', saveTemplate);
        }

        // Botón preview
        const btnPreview = modalEl.querySelector('#btn-builder-preview');
        if (btnPreview) {
            btnPreview.addEventListener('click', updatePreview);
        }
    }

    // === APERTURA DEL MODAL ===
    async function open(categoryId, categoryName, area) {
        currentCategoryId = categoryId;
        currentCategoryName = categoryName;
        currentArea = area;
        fields = [];
        editingFieldIdx = null;

        const modalEl = document.getElementById('modal-field-builder');
        if (!modalEl) {
            console.error('modal-field-builder no encontrado en el DOM');
            return;
        }

        // Actualizar título
        const titleEl = modalEl.querySelector('#field-builder-title');
        if (titleEl) {
            titleEl.textContent = `Campos personalizados: "${categoryName}" (${area})`;
        }

        // Reset UI
        const toggleEl = modalEl.querySelector('#field-builder-enabled');
        if (toggleEl) toggleEl.checked = false;

        const fieldListEl = modalEl.querySelector('#field-builder-list');
        if (fieldListEl) {
            fieldListEl.innerHTML = `
                <div class="text-center py-4 text-muted small">
                    <div class="spinner-border spinner-border-sm me-1" role="status"></div>
                    Cargando plantilla...
                </div>`;
        }

        const previewEl = modalEl.querySelector('#field-builder-preview');
        if (previewEl) previewEl.innerHTML = '';

        if (!modalInstance) {
            modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl, { backdrop: 'static', keyboard: false });
        }
        modalInstance.show();

        // Cargar plantilla existente
        try {
            const data = await API.request('/categories/' + categoryId + '/field-template');
            const tpl = data.field_template || { enabled: false, fields: [] };
            templateEnabled = !!tpl.enabled;
            fields = deepClone(tpl.fields || []);
            // Normalizar: asegurar que cada campo tenga order
            fields.forEach(function (f, i) { f.order = f.order != null ? f.order : i + 1; });
            fields.sort(function (a, b) { return a.order - b.order; });
            if (toggleEl) toggleEl.checked = templateEnabled;
            renderFieldList();
            updatePreview();
        } catch (err) {
            HelpdeskUtils.showToast('Error al cargar plantilla: ' + (err.message || ''), 'error');
            if (fieldListEl) fieldListEl.innerHTML = '<div class="text-danger small p-2">Error al cargar</div>';
        }
    }

    // === RENDER LISTA DE CAMPOS ===
    function renderFieldList() {
        const listEl = document.querySelector('#field-builder-list');
        if (!listEl) return;

        const addBtn = document.querySelector('#btn-builder-add-field');
        const saveBtn = document.querySelector('#btn-builder-save');

        if (!templateEnabled) {
            listEl.innerHTML = `
                <div class="text-center py-5 text-muted small">
                    <i class="fas fa-toggle-off fa-2x mb-2 opacity-50"></i><br>
                    Activa el switch para habilitar campos personalizados.
                </div>`;
            if (addBtn) addBtn.disabled = true;
            return;
        }

        if (addBtn) addBtn.disabled = false;
        if (saveBtn) saveBtn.disabled = false;

        if (!fields.length) {
            listEl.innerHTML = `
                <div class="text-center py-4 text-muted small" id="field-list-empty">
                    <i class="fas fa-plus-circle fa-2x mb-2 opacity-50"></i><br>
                    Sin campos. Haz clic en "+ Agregar campo".
                </div>`;
            return;
        }

        listEl.innerHTML = fields.map(function (field, idx) {
            return renderFieldCard(field, idx);
        }).join('');

        listEl.querySelectorAll('.field-card').forEach(function (card) {
            const idx = parseInt(card.dataset.idx);
            bindFieldCardActions(card, idx);
        });

        initFieldSortable(listEl);
    }

    function renderFieldCard(field, idx) {
        const isEditing = (editingFieldIdx === idx);
        const typeLabel = (FIELD_TYPES.find(function (t) { return t.value === field.type; }) || {}).label || field.type;
        const hasOptions = TYPES_WITH_OPTIONS.includes(field.type);

        if (isEditing) {
            return renderFieldCardEditing(field, idx);
        }

        const visibleWhenText = field.visible_when
            ? 'Visible cuando: ' + Object.entries(field.visible_when).map(function (e) { return e[0] + ' = ' + e[1]; }).join(', ')
            : '';

        return `
            <div class="field-card" data-idx="${idx}" data-key="${escapeHtml(field.key || '')}">
                <div class="field-card-header">
                    <span class="drag-handle"><i class="fas fa-grip-vertical"></i></span>
                    <div class="field-card-meta">
                        <code class="field-key">${escapeHtml(field.key || '(sin key)')}</code>
                        <span class="badge bg-light text-dark border ms-1">${escapeHtml(typeLabel)}</span>
                        ${field.required ? '<span class="badge bg-danger bg-opacity-75 ms-1">req</span>' : ''}
                    </div>
                    <div class="field-card-label text-muted small ms-2 flex-grow-1 text-truncate">${escapeHtml(field.label || '')}</div>
                    <div class="field-card-actions">
                        <button class="btn btn-sm btn-outline-secondary btn-field-edit" data-idx="${idx}" title="Editar campo">
                            <i class="fas fa-pencil-alt"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-danger btn-field-delete" data-idx="${idx}" title="Eliminar campo">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
                ${hasOptions && field.options && field.options.length
                    ? `<div class="field-card-options">
                        ${field.options.map(function (o) {
                            return `<span class="badge bg-secondary bg-opacity-50 me-1">${escapeHtml(o.label || o.value)}</span>`;
                        }).join('')}
                       </div>`
                    : ''}
                ${visibleWhenText
                    ? `<div class="field-card-visible-when text-muted small"><i class="fas fa-eye me-1"></i>${escapeHtml(visibleWhenText)}</div>`
                    : ''}
            </div>`;
    }

    function renderFieldCardEditing(field, idx) {
        const hasOptions = TYPES_WITH_OPTIONS.includes(field.type);
        const prevFields = fields.slice(0, idx);
        const validVisibleWhenFields = prevFields.filter(function (f) {
            return TYPES_WITH_OPTIONS.includes(f.type) || f.type === 'checkbox';
        });

        const currentVisibleWhenKey = field.visible_when ? Object.keys(field.visible_when)[0] : '';
        const currentVisibleWhenVal = field.visible_when ? Object.values(field.visible_when)[0] : '';

        return `
            <div class="field-card field-card--editing" data-idx="${idx}" data-key="${escapeHtml(field.key || '')}">
                <div class="mb-3 row g-2">
                    <div class="col-md-6">
                        <label class="form-label small fw-semibold required">Key <span class="text-danger">*</span></label>
                        <input type="text" class="form-control form-control-sm field-input-key"
                               value="${escapeHtml(field.key || '')}"
                               placeholder="ej: tipo_problema"
                               maxlength="50">
                        <div class="invalid-feedback"></div>
                        <div class="form-text small">Minúsculas, números y guión bajo. Ej: <code>tipo_problema</code></div>
                    </div>
                    <div class="col-md-6">
                        <label class="form-label small fw-semibold">Tipo <span class="text-danger">*</span></label>
                        <select class="form-select form-select-sm field-input-type">
                            ${FIELD_TYPES.map(function (t) {
                                return `<option value="${t.value}" ${field.type === t.value ? 'selected' : ''}>${t.label}</option>`;
                            }).join('')}
                        </select>
                    </div>
                    <div class="col-12">
                        <label class="form-label small fw-semibold">Etiqueta visible <span class="text-danger">*</span></label>
                        <input type="text" class="form-control form-control-sm field-input-label"
                               value="${escapeHtml(field.label || '')}"
                               placeholder="Ej: ¿Qué tipo de problema?"
                               maxlength="200">
                        <div class="invalid-feedback"></div>
                    </div>
                    <div class="col-12 d-flex align-items-center gap-3">
                        <div class="form-check">
                            <input type="checkbox" class="form-check-input field-input-required"
                                   id="field-req-${idx}" ${field.required ? 'checked' : ''}>
                            <label class="form-check-label small" for="field-req-${idx}">Obligatorio</label>
                        </div>
                    </div>

                    ${renderValidationSection(field)}

                    <div class="col-12 field-options-section" style="${hasOptions ? '' : 'display:none'}">
                        <label class="form-label small fw-semibold">Opciones</label>
                        <div class="field-options-list">
                            ${(field.options || []).map(function (opt, oi) {
                                return renderOptionRow(opt, oi);
                            }).join('')}
                        </div>
                        <button type="button" class="btn btn-sm btn-outline-secondary btn-add-option mt-1">
                            <i class="fas fa-plus me-1"></i>Agregar opción
                        </button>
                    </div>

                    <div class="col-12">
                        <label class="form-label small fw-semibold">Visible cuando (opcional)</label>
                        <div class="row g-1">
                            <div class="col-6">
                                <select class="form-select form-select-sm field-input-visible-key">
                                    <option value="">— ninguno —</option>
                                    ${validVisibleWhenFields.map(function (f2) {
                                        return `<option value="${escapeHtml(f2.key)}" ${currentVisibleWhenKey === f2.key ? 'selected' : ''}>${escapeHtml(f2.key)}</option>`;
                                    }).join('')}
                                </select>
                            </div>
                            <div class="col-6">
                                <input type="text" class="form-control form-control-sm field-input-visible-val"
                                       value="${escapeHtml(String(currentVisibleWhenVal || ''))}"
                                       placeholder="valor esperado">
                            </div>
                        </div>
                        <div class="form-text small">Solo muestra este campo cuando el campo elegido tenga ese valor.</div>
                    </div>
                </div>

                <div class="d-flex gap-2 justify-content-end border-top pt-2 mt-1">
                    <button type="button" class="btn btn-sm btn-outline-secondary btn-field-cancel" data-idx="${idx}">
                        Cancelar
                    </button>
                    <button type="button" class="btn btn-sm btn-primary btn-field-apply" data-idx="${idx}">
                        <i class="fas fa-check me-1"></i>Aplicar
                    </button>
                </div>
            </div>`;
    }

    function renderValidationSection(field) {
        const isText = (field.type === 'text' || field.type === 'textarea');
        const isFile = (field.type === 'file');
        const val = field.validation || {};

        if (!isText && !isFile) return '';

        if (isFile) {
            return `
                <div class="col-12">
                    <label class="form-label small fw-semibold">Extensiones permitidas</label>
                    <input type="text" class="form-control form-control-sm field-input-extensions"
                           value="${escapeHtml((val.allowedExtensions || []).join(','))}"
                           placeholder="pdf,jpg,png">
                    <div class="form-text small">Separadas por coma, sin punto. Ej: <code>pdf,jpg,png</code></div>
                </div>
                <div class="col-12">
                    <label class="form-label small fw-semibold">Descripción / ayuda</label>
                    <input type="text" class="form-control form-control-sm field-input-val-desc"
                           value="${escapeHtml(val.description || '')}"
                           maxlength="200">
                </div>`;
        }

        return `
            <div class="col-md-4">
                <label class="form-label small fw-semibold">Mín. caracteres</label>
                <input type="number" class="form-control form-control-sm field-input-minlength"
                       value="${val.minLength != null ? val.minLength : ''}"
                       min="0" max="10000">
            </div>
            <div class="col-md-4">
                <label class="form-label small fw-semibold">Máx. caracteres</label>
                <input type="number" class="form-control form-control-sm field-input-maxlength"
                       value="${val.maxLength != null ? val.maxLength : ''}"
                       min="0" max="10000">
            </div>
            <div class="col-12">
                <label class="form-label small fw-semibold">Descripción / ayuda</label>
                <input type="text" class="form-control form-control-sm field-input-val-desc"
                       value="${escapeHtml(val.description || '')}"
                       maxlength="200">
            </div>`;
    }

    function renderOptionRow(opt, idx) {
        return `
            <div class="field-option-row d-flex gap-1 mb-1" data-opt-idx="${idx}">
                <input type="text" class="form-control form-control-sm opt-value"
                       value="${escapeHtml(opt.value || '')}" placeholder="valor">
                <input type="text" class="form-control form-control-sm opt-label"
                       value="${escapeHtml(opt.label || '')}" placeholder="etiqueta visible">
                <button type="button" class="btn btn-sm btn-outline-danger btn-remove-option">
                    <i class="fas fa-times"></i>
                </button>
            </div>`;
    }

    // === BIND CARD ACTIONS ===
    function bindFieldCardActions(card, idx) {
        // Botón editar
        card.querySelectorAll('.btn-field-edit').forEach(function (btn) {
            btn.addEventListener('click', function () {
                editingFieldIdx = idx;
                renderFieldList();
            });
        });

        // Botón eliminar
        card.querySelectorAll('.btn-field-delete').forEach(function (btn) {
            btn.addEventListener('click', function () {
                fields.splice(idx, 1);
                editingFieldIdx = null;
                recomputeOrders();
                renderFieldList();
                updatePreview();
            });
        });

        // Botón aplicar cambios
        card.querySelectorAll('.btn-field-apply').forEach(function (btn) {
            btn.addEventListener('click', function () { applyFieldEdit(card, idx); });
        });

        // Botón cancelar edición
        card.querySelectorAll('.btn-field-cancel').forEach(function (btn) {
            btn.addEventListener('click', function () {
                editingFieldIdx = null;
                renderFieldList();
            });
        });

        // Botón agregar opción
        card.querySelectorAll('.btn-add-option').forEach(function (btn) {
            btn.addEventListener('click', function () { addOptionRow(card); });
        });

        // Botón quitar opción
        card.querySelectorAll('.btn-remove-option').forEach(function (btn) {
            btn.addEventListener('click', function () {
                btn.closest('.field-option-row').remove();
            });
        });

        // Auto snake_case en key input
        const keyInput = card.querySelector('.field-input-key');
        if (keyInput) {
            keyInput.addEventListener('input', function () {
                const cursor = keyInput.selectionStart;
                const converted = toSnakeCase(keyInput.value);
                if (converted !== keyInput.value) {
                    keyInput.value = converted;
                    keyInput.setSelectionRange(cursor, cursor);
                }
            });
        }

        // Cambio de tipo: mostrar/ocultar sección de opciones
        const typeSelect = card.querySelector('.field-input-type');
        if (typeSelect) {
            typeSelect.addEventListener('change', function () {
                const optSection = card.querySelector('.field-options-section');
                if (optSection) {
                    optSection.style.display = TYPES_WITH_OPTIONS.includes(typeSelect.value) ? '' : 'none';
                }
                // Refrescar validaciones
                const valSection = card.querySelector('.field-validation-section');
                if (valSection) {
                    // Re-renderizar inline — simple toggle
                }
            });
        }
    }

    function addOptionRow(card) {
        const optsList = card.querySelector('.field-options-list');
        if (!optsList) return;
        const newRow = document.createElement('div');
        newRow.innerHTML = renderOptionRow({ value: '', label: '' }, optsList.children.length);
        const row = newRow.firstElementChild;
        row.querySelector('.btn-remove-option').addEventListener('click', function () {
            row.remove();
        });
        optsList.appendChild(row);
    }

    // === APLICAR EDICIÓN DE CAMPO ===
    function applyFieldEdit(card, idx) {
        const key = (card.querySelector('.field-input-key') || {}).value || '';
        const type = (card.querySelector('.field-input-type') || {}).value || 'text';
        const label = (card.querySelector('.field-input-label') || {}).value || '';
        const required = !!(card.querySelector('.field-input-required') || {}).checked;

        // Validaciones
        let valid = true;

        const keyInput = card.querySelector('.field-input-key');
        const labelInput = card.querySelector('.field-input-label');
        if (keyInput) { keyInput.classList.remove('is-invalid'); keyInput.nextElementSibling && (keyInput.nextElementSibling.textContent = ''); }
        if (labelInput) { labelInput.classList.remove('is-invalid'); labelInput.nextElementSibling && (labelInput.nextElementSibling.textContent = ''); }

        if (!key) {
            if (keyInput) { keyInput.classList.add('is-invalid'); keyInput.nextElementSibling && (keyInput.nextElementSibling.textContent = 'El key es requerido'); }
            valid = false;
        } else if (!KEY_REGEX.test(key)) {
            if (keyInput) { keyInput.classList.add('is-invalid'); keyInput.nextElementSibling && (keyInput.nextElementSibling.textContent = 'Solo minúsculas, números y guión bajo. Debe iniciar con letra.'); }
            valid = false;
        } else {
            // Key único
            const duplicate = fields.some(function (f, i) { return i !== idx && f.key === key; });
            if (duplicate) {
                if (keyInput) { keyInput.classList.add('is-invalid'); keyInput.nextElementSibling && (keyInput.nextElementSibling.textContent = 'Ya existe un campo con ese key'); }
                valid = false;
            }
        }

        if (!label) {
            if (labelInput) { labelInput.classList.add('is-invalid'); labelInput.nextElementSibling && (labelInput.nextElementSibling.textContent = 'La etiqueta es requerida'); }
            valid = false;
        }

        // Opciones para select/radio
        let options = [];
        if (TYPES_WITH_OPTIONS.includes(type)) {
            const rows = card.querySelectorAll('.field-option-row');
            rows.forEach(function (row) {
                const v = row.querySelector('.opt-value').value.trim();
                const l = row.querySelector('.opt-label').value.trim();
                if (v) options.push({ value: v, label: l || v });
            });
            if (!options.length) {
                HelpdeskUtils.showToast('Los campos tipo "' + type + '" requieren al menos una opción.', 'warning');
                valid = false;
            }
        }

        if (!valid) return;

        // Validación
        const validation = {};
        const minLenEl = card.querySelector('.field-input-minlength');
        const maxLenEl = card.querySelector('.field-input-maxlength');
        const extEl = card.querySelector('.field-input-extensions');
        const valDescEl = card.querySelector('.field-input-val-desc');

        if (minLenEl && minLenEl.value !== '') validation.minLength = parseInt(minLenEl.value);
        if (maxLenEl && maxLenEl.value !== '') validation.maxLength = parseInt(maxLenEl.value);
        if (extEl && extEl.value.trim()) {
            validation.allowedExtensions = extEl.value.split(',').map(function (e) { return e.trim(); }).filter(Boolean);
        }
        if (valDescEl && valDescEl.value.trim()) validation.description = valDescEl.value.trim();

        if (validation.minLength != null && validation.maxLength != null) {
            if (validation.minLength > validation.maxLength) {
                HelpdeskUtils.showToast('El mínimo de caracteres no puede ser mayor al máximo.', 'warning');
                return;
            }
        }

        // visible_when
        let visibleWhen = null;
        const vwKeyEl = card.querySelector('.field-input-visible-key');
        const vwValEl = card.querySelector('.field-input-visible-val');
        if (vwKeyEl && vwValEl && vwKeyEl.value) {
            const vwVal = vwValEl.value.trim();
            if (vwVal) {
                visibleWhen = {};
                visibleWhen[vwKeyEl.value] = vwVal;
                // Verificar que el campo referenciado existe y aparece antes
                const refIdx = fields.findIndex(function (f, i) { return i < idx && f.key === vwKeyEl.value; });
                if (refIdx === -1) {
                    HelpdeskUtils.showToast('El campo referenciado en "visible cuando" no existe o no aparece antes en el orden.', 'warning');
                    return;
                }
            }
        }

        // Detectar ciclos (DFS simple)
        if (visibleWhen) {
            const tempFields = deepClone(fields);
            tempFields[idx] = Object.assign({}, tempFields[idx], { key, visible_when: visibleWhen });
            if (hasCycle(tempFields)) {
                HelpdeskUtils.showToast('La dependencia "visible cuando" crea un ciclo. Revisa las condiciones.', 'warning');
                return;
            }
        }

        // Guardar campo
        const oldKey = fields[idx] && fields[idx].key;
        if (oldKey && oldKey !== key) {
            HelpdeskUtils.showToast(
                'Advertencia: renombraste "' + oldKey + '" a "' + key + '". Los tickets existentes perderán el valor almacenado en ese campo.',
                'warning'
            );
        }

        fields[idx] = {
            key,
            type,
            label,
            required,
            order: fields[idx] ? fields[idx].order : fields.length,
            options: options.length ? options : undefined,
            validation: Object.keys(validation).length ? validation : undefined,
            visible_when: visibleWhen || undefined,
            trigger_fields: visibleWhen ? Object.keys(visibleWhen) : undefined,
        };

        // Limpiar undefined
        Object.keys(fields[idx]).forEach(function (k) {
            if (fields[idx][k] === undefined) delete fields[idx][k];
        });

        editingFieldIdx = null;
        renderFieldList();
        updatePreview();
    }

    // === CICLOS ===
    function hasCycle(fieldList) {
        const keyMap = {};
        fieldList.forEach(function (f) { keyMap[f.key] = f; });

        function visit(key, visited) {
            if (visited.has(key)) return true;
            visited.add(key);
            const f = keyMap[key];
            if (!f || !f.visible_when) return false;
            for (const depKey of Object.keys(f.visible_when)) {
                if (visit(depKey, new Set(visited))) return true;
            }
            return false;
        }

        return fieldList.some(function (f) { return f.key && visit(f.key, new Set()); });
    }

    // === AGREGAR CAMPO NUEVO ===
    function addNewField() {
        const newField = {
            key: '',
            type: 'text',
            label: '',
            required: false,
            order: fields.length + 1,
        };
        fields.push(newField);
        editingFieldIdx = fields.length - 1;
        renderFieldList();
        // Scroll al final
        const listEl = document.querySelector('#field-builder-list');
        if (listEl) listEl.lastElementChild && listEl.lastElementChild.scrollIntoView({ behavior: 'smooth' });
    }

    // === REORDENAR ===
    function recomputeOrders() {
        fields.forEach(function (f, i) { f.order = i + 1; });
    }

    function initFieldSortable(listEl) {
        cleanupSortable();
        if (typeof Sortable === 'undefined') return;

        sortableInstance = Sortable.create(listEl, {
            handle: '.drag-handle',
            animation: 150,
            ghostClass: 'field-card--ghost',
            filter: '.field-card--editing',
            preventOnFilter: false,
            onEnd: function () {
                const cards = listEl.querySelectorAll('.field-card[data-idx]');
                const newOrder = Array.from(cards).map(function (c) { return parseInt(c.dataset.idx); });
                const reordered = newOrder.map(function (i) { return fields[i]; }).filter(Boolean);
                fields = reordered;
                recomputeOrders();
                editingFieldIdx = null;
                renderFieldList();
                updatePreview();
            },
        });
    }

    function cleanupSortable() {
        if (sortableInstance) {
            try { sortableInstance.destroy(); } catch (_) {}
            sortableInstance = null;
        }
    }

    // === GUARDAR PLANTILLA ===
    async function saveTemplate() {
        if (!currentCategoryId) return;

        // Validar que no haya campos con key vacío
        const emptyKey = fields.find(function (f) { return !f.key; });
        if (emptyKey) {
            HelpdeskUtils.showToast('Hay campos sin key definido. Completa todos los campos antes de guardar.', 'warning');
            return;
        }

        // Validar ciclos en el estado actual
        if (hasCycle(fields)) {
            HelpdeskUtils.showToast('Existen dependencias cíclicas. Revisa los campos "visible cuando".', 'warning');
            return;
        }

        const payload = {
            enabled: templateEnabled,
            fields: fields.map(function (f, i) {
                return Object.assign({}, f, { order: i + 1 });
            }),
        };

        const btn = document.querySelector('#btn-builder-save');
        if (btn) btn.disabled = true;

        try {
            const res = await fetch('/api/help-desk/v2/categories/' + currentCategoryId + '/field-template', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            if (!res.ok) {
                let msg = 'Error al guardar plantilla';
                try {
                    const d = await res.json();
                    msg = d.message || d.error || msg;
                } catch (_) {}
                HelpdeskUtils.showToast(msg, 'error');
                return;
            }

            const data = await res.json();
            HelpdeskUtils.showToast('Plantilla guardada exitosamente', 'success');

            // Notificar a categories_tab para que actualice el ícono
            document.dispatchEvent(new CustomEvent('field-template:saved', {
                detail: {
                    categoryId: currentCategoryId,
                    fieldTemplate: data.field_template || payload,
                },
            }));
        } catch (err) {
            HelpdeskUtils.showToast('Error de conexión', 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    // === PREVIEW ===
    function updatePreview() {
        const previewEl = document.querySelector('#field-builder-preview');
        if (!previewEl) return;

        if (!templateEnabled || !fields.length) {
            previewEl.innerHTML = `
                <div class="text-center py-5 text-muted small">
                    <i class="fas fa-eye-slash fa-2x mb-2 opacity-40"></i><br>
                    ${!templateEnabled ? 'Campos personalizados desactivados.' : 'Sin campos que previsualizar.'}
                </div>`;
            return;
        }

        // Renderizar usando la misma lógica que CustomFields en create_ticket.js
        const container = document.createElement('div');
        container.id = 'preview-custom-fields';

        const sortedFields = [...fields].sort(function (a, b) { return a.order - b.order; });

        sortedFields.forEach(function (field) {
            if (!field.key) return;
            const wrapper = buildPreviewFieldElement(field);
            container.appendChild(wrapper);
        });

        previewEl.innerHTML = '';
        previewEl.appendChild(container);

        // Setup visibility handlers para la preview
        setupPreviewVisibility(sortedFields, previewEl);
    }

    function buildPreviewFieldElement(field) {
        const wrapper = document.createElement('div');
        wrapper.className = 'mb-3 custom-field-wrapper';
        wrapper.dataset.fieldKey = field.key;

        const isVisible = !field.visible_when;
        if (!isVisible) wrapper.style.display = 'none';

        const reqAttr = field.required && isVisible ? 'required' : '';
        const reqStar = field.required ? '<span class="text-danger">*</span>' : '';

        let inputHTML = '';

        switch (field.type) {
            case 'checkbox':
                inputHTML = `
                    <div class="form-check">
                        <input type="checkbox" class="form-check-input" id="prev_${field.key}" ${reqAttr} disabled>
                        <label class="form-check-label" for="prev_${field.key}">
                            ${escapeHtml(field.label)} ${reqStar}
                        </label>
                    </div>`;
                break;

            case 'text':
                inputHTML = `
                    <label class="form-label small" for="prev_${field.key}">${escapeHtml(field.label)} ${reqStar}</label>
                    <input type="text" class="form-control form-control-sm" id="prev_${field.key}"
                           placeholder="(preview)"
                           ${field.validation && field.validation.minLength ? `minlength="${field.validation.minLength}"` : ''}
                           ${field.validation && field.validation.maxLength ? `maxlength="${field.validation.maxLength}"` : ''}>
                    ${field.validation && field.validation.description ? `<div class="form-text small text-muted">${escapeHtml(field.validation.description)}</div>` : ''}`;
                break;

            case 'textarea':
                inputHTML = `
                    <label class="form-label small" for="prev_${field.key}">${escapeHtml(field.label)} ${reqStar}</label>
                    <textarea class="form-control form-control-sm" id="prev_${field.key}" rows="3"
                              ${field.validation && field.validation.minLength ? `minlength="${field.validation.minLength}"` : ''}
                              ${field.validation && field.validation.maxLength ? `maxlength="${field.validation.maxLength}"` : ''}></textarea>
                    ${field.validation && field.validation.description ? `<div class="form-text small text-muted">${escapeHtml(field.validation.description)}</div>` : ''}`;
                break;

            case 'select': {
                const opts = field.options || [];
                inputHTML = `
                    <label class="form-label small" for="prev_${field.key}">${escapeHtml(field.label)} ${reqStar}</label>
                    <select class="form-select form-select-sm" id="prev_${field.key}" data-field-key="${field.key}">
                        <option value="">Selecciona una opción...</option>
                        ${opts.map(function (o) {
                            return `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}</option>`;
                        }).join('')}
                    </select>`;
                break;
            }

            case 'radio': {
                const opts = field.options || [];
                inputHTML = `
                    <label class="form-label small">${escapeHtml(field.label)} ${reqStar}</label>
                    ${opts.map(function (o) {
                        return `
                            <div class="form-check">
                                <input type="radio" class="form-check-input" name="prev_${field.key}"
                                       id="prev_${field.key}_${escapeHtml(o.value)}"
                                       value="${escapeHtml(o.value)}" data-field-key="${field.key}">
                                <label class="form-check-label small" for="prev_${field.key}_${escapeHtml(o.value)}">
                                    ${escapeHtml(o.label)}
                                </label>
                            </div>`;
                    }).join('')}`;
                break;
            }

            case 'file': {
                const exts = (field.validation && field.validation.allowedExtensions) || [];
                inputHTML = `
                    <label class="form-label small" for="prev_${field.key}">${escapeHtml(field.label)} ${reqStar}</label>
                    <input type="file" class="form-control form-control-sm" id="prev_${field.key}"
                           accept="${exts.map(function (e) { return '.' + e; }).join(',')}">
                    ${field.validation && field.validation.description ? `<div class="form-text small text-muted">${escapeHtml(field.validation.description)}</div>` : ''}`;
                break;
            }
        }

        wrapper.innerHTML = inputHTML;
        return wrapper;
    }

    function setupPreviewVisibility(sortedFields, previewEl) {
        sortedFields.forEach(function (field) {
            if (!field.trigger_fields || !field.trigger_fields.length) return;

            let input;
            if (field.type === 'radio') {
                input = previewEl.querySelector(`input[name="prev_${field.key}"]`);
            } else {
                input = previewEl.querySelector(`#prev_${field.key}`);
            }
            if (!input) return;

            input.addEventListener('change', function (e) {
                const value = input.type === 'checkbox' ? input.checked : input.value;
                handlePreviewFieldChange(field.key, value, sortedFields, previewEl);
            });
        });
    }

    function handlePreviewFieldChange(fieldKey, value, sortedFields, previewEl) {
        sortedFields.forEach(function (depField) {
            if (!depField.visible_when || depField.visible_when[fieldKey] === undefined) return;
            const wrapper = previewEl.querySelector(`.custom-field-wrapper[data-field-key="${depField.key}"]`);
            if (!wrapper) return;
            const shouldShow = checkPreviewVisibility(depField.visible_when, previewEl);
            wrapper.style.display = shouldShow ? '' : 'none';
        });
    }

    function checkPreviewVisibility(visibleWhen, previewEl) {
        for (const [key, expected] of Object.entries(visibleWhen)) {
            const input = previewEl.querySelector(`#prev_${key}`);
            if (!input) return false;
            let actual;
            if (input.type === 'checkbox') actual = input.checked;
            else if (input.type === 'radio') {
                const checked = previewEl.querySelector(`[name="prev_${key}"]:checked`);
                actual = checked ? checked.value : null;
            } else actual = input.value;
            if (actual !== expected) return false;
        }
        return true;
    }

    // === EXPORT ===
    window.FieldTemplateBuilder = { open };

})();
