/**
 * panel/color-catalog.js — catálogos de nombre + color de Calidad.
 *
 * UN módulo para DOS pantallas (plan §6.5): /adhoc/panel/areas y
 * /adhoc/panel/procesos. En el legacy eran `areas_conf.js` y `processes.js`,
 * copias literales entre sí salvo los ids de los elementos.
 *
 * Expone SOLO `window.AdhocColorCatalog` (IIFE, sin globales sueltas: el legacy
 * dejaba `class AreasConfigManager` y `class ProcessesManager` en el scope).
 *
 * QUÉ ARREGLA respecto del legacy
 * -------------------------------
 *  · Las URLs iban a `/app_prueba/api/areas/edit/{id}` — un prefijo que no
 *    existía: el submit se perdía en un 404. Aquí todo va a la API v2.
 *  · El alta y la edición eran <form method="POST"> con `action`/`formaction`
 *    reescritos por JS; el borrado era un submit con `formaction`. Aquí son
 *    fetch a POST/PATCH/DELETE con el error real de la API en un toast.
 *  · Los modales se abrían con `style.display='flex'`; aquí son bootstrap.Modal.
 *  · Los inputs del alta se inyectaban con `innerHTML +=` dentro de un template
 *    literal. Aquí se construyen con createElement (nada de innerHTML con datos).
 *  · El color del PROCESO se guardaba dentro de `description`; ahora es una
 *    columna propia y la descripción es texto de verdad.
 *
 * CONFIGURACIÓN (atributos data-* que pinta panel/color_catalog.html)
 * ------------------------------------------------------------------
 *   data-adhoc-color-catalog          marca la sección raíz
 *   data-adhoc-resource               "areas" | "processes"
 *   data-adhoc-api                    "/api/adhoc/v2/areas"
 *   data-adhoc-singular / -plural     textos de los mensajes
 *   data-adhoc-name-label             etiqueta del campo nombre
 *   data-adhoc-default-color          hex por defecto del alta
 *   data-adhoc-has-active             1 → el recurso tiene is_active (áreas)
 *   data-adhoc-has-description        1 → el recurso tiene description (procesos)
 *   data-adhoc-can-create/-update/-delete
 *
 * CONTRATO DE API CONSUMIDO (plan §3)
 * -----------------------------------
 *   GET    {api}       → {success, data: [{id, name, color, …}], total}
 *   POST   {api}       → 201 {success, data, total, skipped, skipped_count, message}
 *   PATCH  {api}/{id}  → {success, data}
 *   DELETE {api}/{id}  → {success, message}
 *   error              → {"error": "texto", "status": N}  (lo traduce fetchJson)
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;

    var HEX = /^#[0-9a-fA-F]{6}$/;
    var FALLBACK_COLOR = '#4834d4';

    // ==================== HELPERS ====================

    function bool(value) {
        return value === '1' || value === 'true' || value === true;
    }

    function toast(message, type) {
        if (U && typeof U.showToast === 'function') U.showToast(message, type);
    }

    function busy(btn, isBusy) {
        if (!btn) return;
        btn.disabled = !!isBusy;
        btn.classList.toggle('disabled', !!isBusy);
    }

    /**
     * Normaliza un color del servidor. Nunca se asigna a style un valor sin
     * validar: aunque la columna es String(7) y el schema la valida, el hex
     * acaba en una propiedad CSS y un valor arbitrario ahí es inyección.
     */
    function safeColor(value, fallback) {
        return HEX.test(String(value || '')) ? String(value) : (fallback || FALLBACK_COLOR);
    }

    function modalFor(el) {
        if (!el || !window.bootstrap || !window.bootstrap.Modal) return null;
        return window.bootstrap.Modal.getOrCreateInstance(el);
    }

    // ==================== INSTANCIA ====================

    function ColorCatalog(root) {
        var d = root.dataset;

        this.root = root;
        this.resource = d.adhocResource || '';
        this.api = d.adhocApi || ('/api/adhoc/v2/' + this.resource);
        this.singular = d.adhocSingular || 'registro';
        this.plural = d.adhocPlural || (this.singular + 's');
        this.nameLabel = d.adhocNameLabel || 'Nombre';
        this.defaultColor = safeColor(d.adhocDefaultColor, FALLBACK_COLOR);
        this.hasActive = bool(d.adhocHasActive);
        this.hasDescription = bool(d.adhocHasDescription);
        this.canCreate = bool(d.adhocCanCreate);
        this.canUpdate = bool(d.adhocCanUpdate);
        this.canDelete = bool(d.adhocCanDelete);

        this.table = root.querySelector('table[data-adhoc-table]');
        this.body = this.table ? this.table.querySelector('[data-adhoc-table-body]') : null;
        this.emptyRow = this.body ? this.body.querySelector('[data-adhoc-empty]') : null;

        this.newModal = document.getElementById('adhoc-color-new-' + this.resource);
        this.editModal = document.getElementById('adhoc-color-edit-' + this.resource);

        this.items = [];
        this.editingId = null;
    }

    ColorCatalog.prototype.init = function () {
        if (!this.body) {
            console.error('[adhoc] color-catalog: falta la tabla de', this.resource);
            return;
        }
        this.bind();
        this.load();
    };

    // ---------- carga y pintado ----------

    ColorCatalog.prototype.load = function () {
        var self = this;
        return U.fetchJson(this.api)
            .then(function (payload) {
                self.items = (payload && payload.data) || [];
                self.render();
            })
            .catch(function (err) {
                self.items = [];
                self.render();
                toast('No se pudieron cargar los ' + self.plural + ': ' + err.message, 'error');
            });
    };

    ColorCatalog.prototype.render = function () {
        var frag = document.createDocumentFragment();
        for (var i = 0; i < this.items.length; i++) {
            frag.appendChild(this.buildRow(this.items[i]));
        }

        var rows = this.body.querySelectorAll('tr:not([data-adhoc-empty])');
        for (var j = 0; j < rows.length; j++) rows[j].remove();

        if (this.emptyRow) {
            this.body.insertBefore(frag, this.emptyRow);
        } else {
            this.body.appendChild(frag);
        }

        if (window.AdhocTableFilter && this.table) {
            window.AdhocTableFilter.apply(this.table);
        }
    };

    ColorCatalog.prototype.buildRow = function (item) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-id', String(item.id));

        // --- nombre (+ descripción del proceso, si la hay) ---
        var tdName = document.createElement('td');
        tdName.setAttribute('data-adhoc-cell', 'name');
        var name = document.createElement('span');
        name.className = 'adhoc-color-name';
        name.textContent = item.name || '';       // textContent, nunca innerHTML
        tdName.appendChild(name);

        if (this.hasDescription && item.description) {
            var desc = document.createElement('span');
            desc.className = 'adhoc-color-description';
            desc.textContent = item.description;
            desc.title = item.description;
            tdName.appendChild(desc);
        }
        tr.appendChild(tdName);

        // --- color ---
        var tdColor = document.createElement('td');
        tdColor.setAttribute('data-adhoc-cell', 'color');
        tdColor.className = 'adhoc-col-center adhoc-color-cell';
        var color = safeColor(item.color, this.defaultColor);
        var swatch = document.createElement('span');
        swatch.className = 'adhoc-swatch';
        swatch.style.backgroundColor = color;     // hex ya validado por safeColor
        var hex = document.createElement('span');
        hex.className = 'adhoc-color-hex';
        hex.textContent = color;
        tdColor.appendChild(swatch);
        tdColor.appendChild(hex);
        tr.appendChild(tdColor);

        // --- estado (solo áreas) ---
        if (this.hasActive) {
            var tdActive = document.createElement('td');
            tdActive.setAttribute('data-adhoc-cell', 'is_active');
            tdActive.className = 'adhoc-col-center';
            var badge = document.createElement('span');
            // El legacy nunca pinta el estatus como pastilla sólida: es texto de
            // color (verde/rojo). `.adhoc-status` es justo eso en adhoc.css.
            badge.className = 'adhoc-badge adhoc-status ' +
                (item.is_active ? 'adhoc-badge-success' : 'adhoc-badge-danger');
            badge.textContent = item.is_active ? 'Activa' : 'Inactiva';
            tdActive.appendChild(badge);
            tr.appendChild(tdActive);
        }

        // --- acciones ---
        var tdActions = document.createElement('td');
        tdActions.className = 'adhoc-col-end';
        tdActions.appendChild(this.buildActions());
        tr.appendChild(tdActions);

        return tr;
    };

    // Iconos de accion de la fila: GLIFO PELADO (`adhoc-icon-action` + variante
    // de color), como en el resto de la app. Antes salian de aqui con recuadro
    // (`btn btn-sm btn-outline-secondary|danger adhoc-btn-icon`), 32px con
    // borde: esta pantalla y la de usuarios eran las dos unicas que lo hacian
    // asi. `remove()` le pasa este mismo boton a `busy()`, que le pone la clase
    // `disabled`; `.adhoc-icon-action.disabled` de adhoc.css la cubre, asi que
    // el bloqueo durante el DELETE se sigue viendo sin depender del `btn`.
    ColorCatalog.prototype.buildActions = function () {
        var box = document.createElement('div');
        box.className = 'adhoc-actions';
        var html = '';
        if (this.canUpdate) {
            html += '<button type="button" class="adhoc-icon-action adhoc-icon-primary" ' +
                    'data-adhoc-action="edit" title="Editar" aria-label="Editar">' +
                    '<i class="fa-solid fa-pen"></i></button>';
        }
        if (this.canDelete) {
            html += '<button type="button" class="adhoc-icon-action adhoc-icon-danger" ' +
                    'data-adhoc-action="delete" title="Eliminar" aria-label="Eliminar">' +
                    '<i class="fa-solid fa-trash"></i></button>';
        }
        box.innerHTML = html;   // markup estático: no lleva ni un dato del servidor
        return box;
    };

    // ---------- alta masiva ----------

    ColorCatalog.prototype.openNew = function () {
        if (!this.newModal) {
            console.error('[adhoc] color-catalog: falta el modal de alta de', this.resource);
            return;
        }
        this.buildFields();
        var modal = modalFor(this.newModal);
        if (modal) modal.show();
    };

    ColorCatalog.prototype.buildFields = function () {
        var box = this.newModal.querySelector('[data-adhoc-catalog-fields]');
        var qtySelect = this.newModal.querySelector('[data-adhoc-catalog-qty]');
        var qty = qtySelect ? (parseInt(qtySelect.value, 10) || 1) : 1;
        if (!box) return;

        box.textContent = '';
        for (var i = 1; i <= qty; i++) {
            box.appendChild(this.buildField(i));
        }
        var first = box.querySelector('[data-adhoc-new-name]');
        if (first) first.focus();
    };

    ColorCatalog.prototype.buildField = function (index) {
        var row = document.createElement('div');
        row.className = 'adhoc-color-new-row';

        var nameWrap = document.createElement('div');
        nameWrap.className = 'adhoc-field adhoc-color-new-name';
        var nameId = 'adhoc-new-' + this.resource + '-name-' + index;

        var nameLabel = document.createElement('label');
        nameLabel.className = 'form-label adhoc-label';
        nameLabel.setAttribute('for', nameId);
        nameLabel.textContent = this.nameLabel + ' ' + index;

        var nameInput = document.createElement('input');
        nameInput.type = 'text';
        nameInput.className = 'form-control';
        nameInput.id = nameId;
        nameInput.maxLength = 100;
        nameInput.placeholder = this.nameLabel;
        nameInput.setAttribute('data-adhoc-new-name', '');

        nameWrap.appendChild(nameLabel);
        nameWrap.appendChild(nameInput);

        var colorWrap = document.createElement('div');
        colorWrap.className = 'adhoc-field adhoc-field-color adhoc-color-new-color';
        var colorId = 'adhoc-new-' + this.resource + '-color-' + index;

        var colorLabel = document.createElement('label');
        colorLabel.className = 'form-label adhoc-label';
        colorLabel.setAttribute('for', colorId);
        colorLabel.textContent = 'Color';

        var colorInput = document.createElement('input');
        colorInput.type = 'color';
        colorInput.className = 'form-control form-control-color adhoc-color-input';
        colorInput.id = colorId;
        colorInput.value = this.defaultColor;
        colorInput.setAttribute('data-adhoc-new-color', '');

        colorWrap.appendChild(colorLabel);
        colorWrap.appendChild(colorInput);

        row.appendChild(nameWrap);
        row.appendChild(colorWrap);
        return row;
    };

    ColorCatalog.prototype.submitNew = function () {
        var self = this;
        var rows = this.newModal.querySelectorAll('.adhoc-color-new-row');
        var btn = this.newModal.querySelector('[data-adhoc-catalog-save]');
        var items = [];

        for (var i = 0; i < rows.length; i++) {
            var nameInput = rows[i].querySelector('[data-adhoc-new-name]');
            var colorInput = rows[i].querySelector('[data-adhoc-new-color]');
            var value = nameInput ? nameInput.value.trim() : '';
            if (!value) continue;
            items.push({
                name: value,
                color: safeColor(colorInput ? colorInput.value : '', this.defaultColor)
            });
        }

        if (!items.length) {
            toast('Captura al menos un nombre.', 'warning');
            return;
        }

        busy(btn, true);
        U.fetchJson(this.api, {
            method: 'POST',
            body: JSON.stringify({ items: items })
        }).then(function (payload) {
            var created = (payload && payload.total) || 0;
            var skipped = (payload && payload.skipped_count) || 0;
            var message = (payload && payload.message) ||
                (created + ' registro(s) creado(s)' +
                 (skipped ? ', ' + skipped + ' omitido(s)' : ''));
            toast(message, (skipped && !created) ? 'warning' : 'success');
            var modal = modalFor(self.newModal);
            if (modal) modal.hide();
            return self.load();
        }).catch(function (err) {
            toast(err.message, 'error');
        }).then(function () {
            busy(btn, false);
        });
    };

    // ---------- edición ----------

    ColorCatalog.prototype.field = function (key) {
        return this.editModal
            ? this.editModal.querySelector('[data-adhoc-edit-field="' + key + '"]')
            : null;
    };

    ColorCatalog.prototype.openEdit = function (tr) {
        if (!this.editModal) return;
        var item = this.find(tr.getAttribute('data-id'));
        if (!item) return;

        this.editingId = item.id;

        var nameInput = this.field('name');
        if (nameInput) nameInput.value = item.name || '';       // .value, no innerHTML

        var colorInput = this.field('color');
        if (colorInput) colorInput.value = safeColor(item.color, this.defaultColor);

        var descInput = this.field('description');
        if (descInput) descInput.value = item.description || '';

        var activeInput = this.field('is_active');
        if (activeInput) activeInput.checked = item.is_active !== false;

        var modal = modalFor(this.editModal);
        if (modal) modal.show();
        if (nameInput) {
            // El foco tras la animación de apertura de Bootstrap.
            this.editModal.addEventListener('shown.bs.modal', function once() {
                nameInput.focus();
                nameInput.select();
                this.removeEventListener('shown.bs.modal', once);
            });
        }
    };

    ColorCatalog.prototype.saveEdit = function () {
        var self = this;
        var id = this.editingId;
        if (id === null || id === undefined) return;

        var btn = this.editModal.querySelector('[data-adhoc-catalog-update]');
        var nameInput = this.field('name');
        var value = nameInput ? nameInput.value.trim() : '';

        if (!value) {
            toast('El nombre no puede quedar vacío.', 'warning');
            if (nameInput) nameInput.focus();
            return;
        }

        var payload = { name: value };

        var colorInput = this.field('color');
        if (colorInput) payload.color = safeColor(colorInput.value, this.defaultColor);

        var descInput = this.field('description');
        if (descInput) payload.description = descInput.value.trim();

        var activeInput = this.field('is_active');
        if (activeInput) payload.is_active = !!activeInput.checked;

        busy(btn, true);
        U.fetchJson(this.api + '/' + encodeURIComponent(id), {
            method: 'PATCH',
            body: JSON.stringify(payload)
        }).then(function () {
            toast('Cambios guardados.', 'success');
            var modal = modalFor(self.editModal);
            if (modal) modal.hide();
            self.editingId = null;
            return self.load();
        }).catch(function (err) {
            toast(err.message, 'error');
        }).then(function () {
            busy(btn, false);
        });
    };

    // ---------- borrado ----------

    ColorCatalog.prototype.remove = function (id, btn) {
        var self = this;
        var item = this.find(id);
        if (!item) return;

        // El legacy borraba con un submit y `formaction`, sin confirmar (áreas)
        // o con confirm() nativo (usuarios). Aquí, promesa.
        U.confirmDialog({
            title: 'Eliminar ' + this.singular,
            message: 'Se eliminará "' + (item.name || '') + '". Esta acción no se puede deshacer.',
            confirmText: 'Eliminar',
            variant: 'danger'
        }).then(function (ok) {
            if (!ok) return null;
            busy(btn, true);
            return U.fetchJson(self.api + '/' + encodeURIComponent(id), { method: 'DELETE' })
                .then(function (payload) {
                    toast((payload && payload.message) || 'Registro eliminado.', 'success');
                    var modal = modalFor(self.editModal);
                    if (modal) modal.hide();
                    self.editingId = null;
                    return self.load();
                })
                .catch(function (err) {
                    // 409: el catálogo está en uso. El legacy se tragaba el
                    // IntegrityError y devolvía un redirect "exitoso".
                    toast(err.message, 'error');
                })
                .then(function () {
                    busy(btn, false);
                });
        });
    };

    // ---------- utilidades ----------

    ColorCatalog.prototype.find = function (id) {
        for (var i = 0; i < this.items.length; i++) {
            if (String(this.items[i].id) === String(id)) return this.items[i];
        }
        return null;
    };

    // ---------- listeners (delegados, cero onclick inline) ----------

    ColorCatalog.prototype.bind = function () {
        var self = this;

        this.root.addEventListener('click', function (evt) {
            var newBtn = evt.target.closest('[data-adhoc-catalog-new]');
            if (newBtn) { evt.preventDefault(); self.openNew(); return; }

            var btn = evt.target.closest('[data-adhoc-action]');
            if (!btn) return;
            var tr = btn.closest('tr[data-id]');
            if (!tr) return;
            evt.preventDefault();

            var action = btn.getAttribute('data-adhoc-action');
            if (action === 'edit') self.openEdit(tr);
            else if (action === 'delete') self.remove(tr.getAttribute('data-id'), btn);
        });

        if (this.newModal) {
            this.newModal.addEventListener('change', function (evt) {
                if (evt.target.closest('[data-adhoc-catalog-qty]')) self.buildFields();
            });
            this.newModal.addEventListener('click', function (evt) {
                if (evt.target.closest('[data-adhoc-catalog-save]')) {
                    evt.preventDefault();
                    self.submitNew();
                }
            });
            this.newModal.addEventListener('keydown', function (evt) {
                if (evt.key === 'Enter' && evt.target.matches('[data-adhoc-new-name]')) {
                    evt.preventDefault();
                    self.submitNew();
                }
            });
        }

        if (this.editModal) {
            this.editModal.addEventListener('click', function (evt) {
                if (evt.target.closest('[data-adhoc-catalog-update]')) {
                    evt.preventDefault();
                    self.saveEdit();
                    return;
                }
                var del = evt.target.closest('[data-adhoc-catalog-delete]');
                if (del) {
                    evt.preventDefault();
                    self.remove(self.editingId, del);
                }
            });
            this.editModal.addEventListener('keydown', function (evt) {
                if (evt.key === 'Enter' && evt.target.matches('[data-adhoc-edit-field="name"]')) {
                    evt.preventDefault();
                    self.saveEdit();
                }
            });
        }
    };

    // ==================== API PÚBLICA ====================

    /**
     * Arranca el catálogo de una sección. Idempotente por `dataset`: el morph de
     * HTMX puede reejecutar el init sobre el mismo nodo.
     * @param {Element} [root]
     * @returns {ColorCatalog|null}
     */
    function init(root) {
        var node = root || document.querySelector('[data-adhoc-color-catalog]');
        if (!node) return null;
        if (node.dataset.adhocColorCatalogBound === '1') return null;
        node.dataset.adhocColorCatalogBound = '1';

        var instance = new ColorCatalog(node);
        instance.init();
        return instance;
    }

    function initAll(scope) {
        var node = scope || document;
        var out = [];
        var made;

        if (node.matches && node.matches('[data-adhoc-color-catalog]')) {
            made = init(node);
            if (made) out.push(made);
        }

        var roots = node.querySelectorAll('[data-adhoc-color-catalog]');
        for (var i = 0; i < roots.length; i++) {
            made = init(roots[i]);
            if (made) out.push(made);
        }
        return out;
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { initAll(root || document); });
    }

    window.AdhocColorCatalog = { init: init, initAll: initAll };
})();
