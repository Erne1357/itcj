/**
 * ticket-create.js — Formulario de nueva solicitud de Mantenimiento
 */
'use strict';

(function () {

    var API_BASE = '/api/maint/v2';
    var _selectedCategory = null;  // objeto completo {id, code, name, icon, field_template}
    var _selectedPriority = 'MEDIA';

    document.addEventListener('DOMContentLoaded', function () {
        _loadCategories();
        _bindPriority();
        _bindSubmit();
    });

    // ── Cargar categorías ─────────────────────────────────────────────────────

    function _loadCategories() {
        MaintUtils.api.fetch(API_BASE + '/categories')
            .then(function (data) {
                _renderCategories(data.categories || []);
            })
            .catch(function () {
                document.getElementById('categorySkeleton').innerHTML =
                    '<div class="col-12"><div class="alert alert-warning mb-0">No se pudieron cargar las categorías.</div></div>';
            });
    }

    var CAT_ICON_MAP = {
        TRANSPORT: 'bi-truck', GENERAL: 'bi-tools', ELECTRICAL: 'bi-lightning-charge',
        CARPENTRY: 'bi-hammer', AC: 'bi-thermometer-snow', GARDENING: 'bi-tree',
    };

    function _renderCategories(categories) {
        var skeleton = document.getElementById('categorySkeleton');
        var container = document.getElementById('categoryCards');

        skeleton.style.display = 'none';
        container.style.display = '';

        categories.forEach(function (cat) {
            var icon = cat.icon || CAT_ICON_MAP[cat.code] || 'bi-tools';
            var col = document.createElement('div');
            col.className = 'col-6 col-sm-4 col-md-3 col-lg-2';
            col.innerHTML =
                '<div class="mn-category-card" data-id="' + cat.id + '">' +
                    '<div class="cat-icon"><i class="bi ' + _esc(icon) + '"></i></div>' +
                    '<div class="cat-name">' + _esc(cat.name) + '</div>' +
                '</div>';
            col.querySelector('.mn-category-card').addEventListener('click', function () {
                _selectCategory(cat);
            });
            container.appendChild(col);
        });
    }

    function _selectCategory(cat) {
        _selectedCategory = cat;

        document.querySelectorAll('.mn-category-card').forEach(function (c) {
            c.classList.remove('selected');
        });
        document.querySelector('[data-id="' + cat.id + '"]').classList.add('selected');
        document.getElementById('categoryId').value = cat.id;
        document.getElementById('categoryError').style.display = 'none';

        _renderCustomFields(cat.field_template || []);
    }

    // ── Campos dinámicos ──────────────────────────────────────────────────────

    function _renderCustomFields(fields) {
        var section = document.getElementById('customFieldsSection');
        var body = document.getElementById('customFieldsBody');
        body.innerHTML = '';

        if (!fields || fields.length === 0) {
            section.style.display = 'none';
            return;
        }

        fields.forEach(function (f) {
            var col = document.createElement('div');
            col.className = 'col-md-6';
            var required = f.required ? ' <span class="text-danger">*</span>' : '';
            var input = '';

            if (f.type === 'select' && Array.isArray(f.options)) {
                input = '<select class="form-select" id="cf_' + _esc(f.key) + '" data-cf-key="' + _esc(f.key) + '"' +
                    (f.required ? ' required' : '') + '>' +
                    '<option value="">Selecciona...</option>' +
                    f.options.map(function (o) { return '<option value="' + _esc(o) + '">' + _esc(o) + '</option>'; }).join('') +
                    '</select>';
            } else if (f.type === 'number') {
                input = '<input type="number" class="form-control" id="cf_' + _esc(f.key) + '" data-cf-key="' + _esc(f.key) + '" min="0"' +
                    (f.required ? ' required' : '') + '>';
            } else if (f.type === 'date') {
                input = '<input type="date" class="form-control" id="cf_' + _esc(f.key) + '" data-cf-key="' + _esc(f.key) + '"' +
                    (f.required ? ' required' : '') + '>';
            } else if (f.type === 'time') {
                input = '<input type="time" class="form-control" id="cf_' + _esc(f.key) + '" data-cf-key="' + _esc(f.key) + '"' +
                    (f.required ? ' required' : '') + '>';
            } else {
                input = '<input type="text" class="form-control" id="cf_' + _esc(f.key) + '" data-cf-key="' + _esc(f.key) + '"' +
                    (f.required ? ' required' : '') + '>';
            }

            col.innerHTML =
                '<label class="form-label fw-medium" for="cf_' + _esc(f.key) + '">' + _esc(f.label) + required + '</label>' +
                input;
            body.appendChild(col);
        });

        section.style.display = '';
    }

    // ── Prioridad ─────────────────────────────────────────────────────────────

    function _bindPriority() {
        document.getElementById('priorityCards').addEventListener('click', function (e) {
            var card = e.target.closest('.mn-priority-card');
            if (!card) return;
            document.querySelectorAll('.mn-priority-card').forEach(function (c) { c.classList.remove('selected'); });
            card.classList.add('selected');
            _selectedPriority = card.dataset.priority;
            document.getElementById('priorityId').value = _selectedPriority;
        });
    }

    // ── Submit ────────────────────────────────────────────────────────────────

    function _bindSubmit() {
        document.getElementById('createTicketForm').addEventListener('submit', function (e) {
            e.preventDefault();
            _submitForm();
        });
    }

    function _submitForm() {
        var btn = document.getElementById('submitBtn');
        var valid = true;

        // Validar categoría
        if (!_selectedCategory) {
            document.getElementById('categoryError').style.display = 'block';
            valid = false;
        }

        var title = document.getElementById('titleInput').value.trim();
        var description = document.getElementById('descriptionInput').value.trim();

        _setInvalid('titleInput', title.length < 5);
        _setInvalid('descriptionInput', description.length < 10);
        if (title.length < 5 || description.length < 10) valid = false;

        // Validar custom fields requeridos
        if (_selectedCategory && _selectedCategory.field_template) {
            _selectedCategory.field_template.forEach(function (f) {
                if (f.required) {
                    var el = document.getElementById('cf_' + f.key);
                    if (el && !el.value.trim()) {
                        el.classList.add('is-invalid');
                        valid = false;
                    }
                }
            });
        }

        if (!valid) return;

        // Recopilar custom fields
        var customFields = {};
        document.querySelectorAll('[data-cf-key]').forEach(function (el) {
            var key = el.dataset.cfKey;
            if (el.value.trim()) customFields[key] = el.value.trim();
        });

        var payload = {
            category_id: _selectedCategory.id,
            priority: _selectedPriority,
            title: title,
            description: description,
            location: document.getElementById('locationInput').value.trim() || null,
            custom_fields: Object.keys(customFields).length > 0 ? customFields : null,
        };

        MaintUtils.loading.show(btn, 'Enviando...');

        MaintUtils.api.fetch(API_BASE + '/tickets', {
            method: 'POST',
            body: JSON.stringify(payload),
        })
            .then(function (data) {
                MaintUtils.toast('Solicitud creada: ' + data.ticket_number, 'success');
                setTimeout(function () {
                    window.location.href = '/maintenance/tickets/' + data.ticket_id;
                }, 800);
            })
            .catch(function (err) {
                MaintUtils.loading.hide(btn);
                MaintUtils.alert({ title: 'No se pudo crear la solicitud', message: err.message, type: 'error' });
            });
    }

    function _setInvalid(id, isInvalid) {
        var el = document.getElementById(id);
        if (!el) return;
        if (isInvalid) {
            el.classList.add('is-invalid');
            el.addEventListener('input', function () { el.classList.remove('is-invalid'); }, { once: true });
        } else {
            el.classList.remove('is-invalid');
        }
    }

    function _esc(s) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(String(s || '')));
        return d.innerHTML;
    }

})();
