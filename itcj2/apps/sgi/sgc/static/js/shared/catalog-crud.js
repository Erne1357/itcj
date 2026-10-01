/**
 * shared/catalog-crud.js — CRUD genérico de los catálogos de solo-nombre.
 *
 * Expone SOLO `window.SgcCatalogCrud` (IIFE, sin globales sueltas).
 *
 * QUÉ SUSTITUYE
 * -------------
 * Cuatro archivos del legacy que eran el MISMO código con distintos ids:
 *   documents_categories.js · documents_classifications.js ·
 *   incidents_categories.js · programs_categories.js
 * (más sus cuatro plantillas y sus cuatro hojas CSS con el mismo
 * `.modal-overlay` copiado). Todos: hacían `formContainer.innerHTML` con el
 * nombre sin escapar, abrían el modal con `style.display='flex'`, usaban
 * `confirm()` para borrar y apuntaban a URLs con el prefijo `/app_prueba/api/…`
 * que no existía (404 silencioso).
 *
 * MARCADO (lo genera la macro `catalog_page()` de partials/_macros.html)
 * ---------------------------------------------------------------------
 *   <section data-sgi-catalog
 *            data-sgi-resource="document-categories"
 *            data-sgi-api="/api/sgi/v2/sgc/document-categories"
 *            data-sgi-singular="categoría" data-sgi-plural="categorías"
 *            data-sgi-name-label="Nombre"
 *            data-sgi-can-create="1" data-sgi-can-update="1" data-sgi-can-delete="1">
 *     …data_table('sgi-catalog-document-categories', …)…
 *
 * y en {% block modals %} la macro `catalog_modal()`, con
 * `data-sgi-catalog-modal="document-categories"`.
 *
 * CONTRATO DE API CONSUMIDO (plan §3)
 * -----------------------------------
 *   GET    {api}        → {success, data: [{id, name, …}], total}
 *   POST   {api}        → 201 {success, data, total, skipped, skipped_count, message}
 *   PATCH  {api}/{id}   → {success, data}
 *   DELETE {api}/{id}   → {success, message}
 *   error               → {"error": "texto", "status": N}  (lo traduce fetchJson)
 *
 * El alta es MASIVA y deduplicada del lado del service: un nombre repetido ya no
 * tumba el lote, se reporta en `skipped`.
 */
(function () {
    'use strict';

    var U = window.SgiUtils;

    // ==================== HELPERS ====================

    function bool(value) {
        return value === '1' || value === 'true' || value === true;
    }

    function icon(name) {
        return '<i class="' + name + '"></i>';
    }

    function busy(btn, isBusy) {
        if (!btn) return;
        btn.disabled = !!isBusy;
        btn.classList.toggle('disabled', !!isBusy);
    }

    function toast(message, type) {
        if (U && typeof U.showToast === 'function') U.showToast(message, type);
    }

    // ==================== INSTANCIA ====================

    /**
     * @param {HTMLElement} root  el <section data-sgi-catalog>
     * @param {Object} [overrides] config explícita (gana sobre los data-*)
     */
    function Catalog(root, overrides) {
        var d = root.dataset;
        var o = overrides || {};

        this.root = root;
        this.resource = o.resource || d.sgiResource || '';
        this.api = o.api || d.sgiApi || ('/api/sgi/v2/sgc/' + this.resource);
        this.singular = o.singular || d.sgiSingular || 'registro';
        this.plural = o.plural || d.sgiPlural || (this.singular + 's');
        this.nameLabel = o.nameLabel || d.sgiNameLabel || 'Nombre';
        this.canCreate = o.canCreate !== undefined ? !!o.canCreate : bool(d.sgiCanCreate);
        this.canUpdate = o.canUpdate !== undefined ? !!o.canUpdate : bool(d.sgiCanUpdate);
        this.canDelete = o.canDelete !== undefined ? !!o.canDelete : bool(d.sgiCanDelete);

        this.table = root.querySelector('table[data-sgi-table]');
        this.body = this.table ? this.table.querySelector('[data-sgi-table-body]') : null;
        this.emptyRow = this.body ? this.body.querySelector('[data-sgi-empty]') : null;
        this.modal = document.querySelector(
            '[data-sgi-catalog-modal="' + this.resource.replace(/["\\]/g, '\\$&') + '"]'
        );
        this.items = [];
        this.editingId = null;
    }

    Catalog.prototype.init = function () {
        if (!this.body) {
            console.error('[sgc] catalog-crud: falta la tabla de', this.resource);
            return;
        }
        this.bind();
        this.load();
    };

    // ---------- carga y pintado ----------

    Catalog.prototype.load = function () {
        var self = this;
        return U.fetchJson(this.api)
            .then(function (payload) {
                self.items = (payload && payload.data) || [];
                self.render();
            })
            .catch(function (err) {
                self.items = [];
                self.render();
                toast('No se pudo cargar el catálogo: ' + err.message, 'error');
            });
    };

    Catalog.prototype.render = function () {
        var frag = document.createDocumentFragment();
        for (var i = 0; i < this.items.length; i++) {
            frag.appendChild(this.buildRow(this.items[i]));
        }

        // Se vacía el tbody conservando la fila de "sin resultados".
        var rows = this.body.querySelectorAll('tr:not([data-sgi-empty])');
        for (var j = 0; j < rows.length; j++) rows[j].remove();

        if (this.emptyRow) {
            this.body.insertBefore(frag, this.emptyRow);
        } else {
            this.body.appendChild(frag);
        }

        this.editingId = null;
        if (window.SgcTableFilter && this.table) {
            window.SgcTableFilter.apply(this.table);
        }
    };

    Catalog.prototype.buildRow = function (item) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-id', String(item.id));

        // textContent: el nombre NUNCA se concatena a innerHTML (el legacy sí).
        var tdName = document.createElement('td');
        tdName.setAttribute('data-sgi-cell', 'name');
        tdName.className = 'sgi-catalog-name';
        tdName.textContent = item.name || '';
        tr.appendChild(tdName);

        var tdActions = document.createElement('td');
        tdActions.className = 'sgi-col-end';
        tdActions.appendChild(this.buildActions());
        tr.appendChild(tdActions);

        return tr;
    };

    // Iconos de accion de la fila: GLIFO PELADO (`sgi-icon-action` + su
    // variante de color), que es la familia de las otras diez pantallas de la
    // app. Salian de aqui como `btn btn-sm btn-outline-secondary|danger
    // sgi-btn-icon`: un recuadro de 32px con borde, para el mismo papel.
    // Coexistian las dos formas y en el catalogo se veia la del recuadro.
    Catalog.prototype.buildActions = function () {
        var box = document.createElement('div');
        box.className = 'sgi-actions';
        var html = '';
        if (this.canUpdate) {
            html += '<button type="button" class="sgi-icon-action sgi-icon-primary" ' +
                    'data-sgi-action="edit" title="Editar" aria-label="Editar">' + icon('fa-solid fa-pen') + '</button>';
        }
        if (this.canDelete) {
            html += '<button type="button" class="sgi-icon-action sgi-icon-danger" ' +
                    'data-sgi-action="delete" title="Eliminar" aria-label="Eliminar">' + icon('fa-solid fa-trash') + '</button>';
        }
        box.innerHTML = html;   // markup estático, sin datos del servidor
        return box;
    };

    // ---------- edición en línea ----------

    Catalog.prototype.startEdit = function (tr) {
        if (this.editingId !== null) this.cancelEdit();

        var id = tr.getAttribute('data-id');
        var item = this.find(id);
        if (!item) return;
        this.editingId = id;
        tr.classList.add('sgi-row-editing');

        var tdName = tr.querySelector('[data-sgi-cell="name"]');
        tdName.textContent = '';
        var input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-control form-control-sm';
        input.maxLength = 100;
        input.value = item.name || '';       // .value, no innerHTML
        input.setAttribute('data-sgi-edit-input', '');
        input.setAttribute('aria-label', this.nameLabel);
        tdName.appendChild(input);
        input.focus();
        input.select();

        var actions = tr.querySelector('.sgi-actions');
        // El check de confirmar fue INVISIBLE durante toda la migracion: salia
        // como `.btn-primary` (texto blanco) dentro de `.sgi-catalog
        // .sgi-actions`, donde la hoja le quitaba el fondo pero no el color,
        // asi que quedaba blanco sobre la fila blanca. Ahora usa la familia de
        // glifo pelado como el resto de iconos de fila de la app, que lleva el
        // color EN el texto: verde para confirmar, gris para cancelar.
        actions.innerHTML =
            '<button type="button" class="sgi-icon-action sgi-icon-success" ' +
            'data-sgi-action="save" title="Guardar" aria-label="Guardar">' + icon('fa-solid fa-check') + '</button>' +
            '<button type="button" class="sgi-icon-action sgi-icon-muted" ' +
            'data-sgi-action="cancel" title="Cancelar" aria-label="Cancelar">' + icon('fa-solid fa-xmark') + '</button>';
    };

    Catalog.prototype.cancelEdit = function () {
        var tr = this.rowOf(this.editingId);
        this.editingId = null;
        if (!tr) return;
        var item = this.find(tr.getAttribute('data-id'));
        tr.classList.remove('sgi-row-editing');
        var tdName = tr.querySelector('[data-sgi-cell="name"]');
        tdName.textContent = item ? (item.name || '') : '';
        var actions = tr.querySelector('.sgi-actions');
        actions.replaceWith(this.buildActions());
    };

    Catalog.prototype.saveEdit = function (tr) {
        var self = this;
        var id = tr.getAttribute('data-id');
        var input = tr.querySelector('[data-sgi-edit-input]');
        var value = input ? input.value.trim() : '';
        var btn = tr.querySelector('[data-sgi-action="save"]');

        if (!value) {
            toast('El ' + this.nameLabel.toLowerCase() + ' no puede quedar vacío.', 'warning');
            if (input) input.focus();
            return;
        }

        busy(btn, true);
        U.fetchJson(this.api + '/' + encodeURIComponent(id), {
            method: 'PATCH',
            body: JSON.stringify({ name: value })
        }).then(function () {
            toast('Cambio guardado.', 'success');
            self.editingId = null;
            return self.load();
        }).catch(function (err) {
            busy(btn, false);
            toast(err.message, 'error');
        });
    };

    // ---------- borrado ----------

    Catalog.prototype.remove = function (tr) {
        var self = this;
        var id = tr.getAttribute('data-id');
        var item = this.find(id);
        var name = item ? item.name : '';
        var btn = tr.querySelector('[data-sgi-action="delete"]');

        // El legacy usaba confirm() dentro de un handler síncrono; aquí el flujo
        // se invierte a await/promesa.
        U.confirmDialog({
            title: 'Eliminar ' + this.singular,
            message: '¿Eliminar "' + name + '"? Esta acción no se puede deshacer.',
            confirmText: 'Eliminar',
            variant: 'danger'
        }).then(function (ok) {
            if (!ok) return null;
            busy(btn, true);
            return U.fetchJson(self.api + '/' + encodeURIComponent(id), { method: 'DELETE' })
                .then(function (payload) {
                    toast((payload && payload.message) || 'Registro eliminado.', 'success');
                    return self.load();
                })
                .catch(function (err) {
                    busy(btn, false);
                    toast(err.message, 'error');
                });
        });
    };

    // ---------- alta masiva ----------

    Catalog.prototype.openNew = function () {
        if (!this.modal) {
            console.error('[sgc] catalog-crud: falta el modal de', this.resource);
            return;
        }
        this.buildFields();
        if (window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(this.modal).show();
        }
    };

    Catalog.prototype.buildFields = function () {
        var box = this.modal.querySelector('[data-sgi-catalog-fields]');
        var qtySelect = this.modal.querySelector('[data-sgi-catalog-qty]');
        var qty = qtySelect ? parseInt(qtySelect.value, 10) || 1 : 1;
        if (!box) return;

        box.textContent = '';
        for (var i = 1; i <= qty; i++) {
            var field = document.createElement('div');
            field.className = 'sgi-field';

            var label = document.createElement('label');
            label.className = 'form-label sgi-label';
            label.setAttribute('for', 'sgi-new-' + this.resource + '-' + i);
            label.textContent = this.nameLabel + ' ' + i;

            var input = document.createElement('input');
            input.type = 'text';
            input.className = 'form-control';
            input.id = 'sgi-new-' + this.resource + '-' + i;
            input.maxLength = 100;
            input.setAttribute('data-sgi-new-name', '');
            input.placeholder = this.nameLabel;

            field.appendChild(label);
            field.appendChild(input);
            box.appendChild(field);
        }
        var first = box.querySelector('input');
        if (first) first.focus();
    };

    Catalog.prototype.submitNew = function () {
        var self = this;
        var inputs = this.modal.querySelectorAll('[data-sgi-new-name]');
        var btn = this.modal.querySelector('[data-sgi-catalog-save]');
        var items = [];

        for (var i = 0; i < inputs.length; i++) {
            var value = inputs[i].value.trim();
            if (value) items.push({ name: value });
        }
        if (!items.length) {
            toast('Captura al menos un ' + this.nameLabel.toLowerCase() + '.', 'warning');
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
                (created + ' registro(s) creado(s)' + (skipped ? ', ' + skipped + ' omitido(s)' : ''));
            toast(message, skipped && !created ? 'warning' : 'success');
            if (window.bootstrap && window.bootstrap.Modal) {
                window.bootstrap.Modal.getOrCreateInstance(self.modal).hide();
            }
            return self.load();
        }).catch(function (err) {
            toast(err.message, 'error');
        }).then(function () {
            busy(btn, false);
        });
    };

    // ---------- utilidades ----------

    Catalog.prototype.find = function (id) {
        for (var i = 0; i < this.items.length; i++) {
            if (String(this.items[i].id) === String(id)) return this.items[i];
        }
        return null;
    };

    Catalog.prototype.rowOf = function (id) {
        if (id === null || id === undefined) return null;
        return this.body.querySelector('tr[data-id="' + String(id).replace(/["\\]/g, '\\$&') + '"]');
    };

    // ---------- listeners (delegados, cero onclick inline) ----------

    Catalog.prototype.bind = function () {
        var self = this;

        this.root.addEventListener('click', function (evt) {
            var newBtn = evt.target.closest('[data-sgi-catalog-new]');
            if (newBtn) { evt.preventDefault(); self.openNew(); return; }

            var btn = evt.target.closest('[data-sgi-action]');
            if (!btn) return;
            var tr = btn.closest('tr[data-id]');
            if (!tr) return;
            evt.preventDefault();

            var action = btn.getAttribute('data-sgi-action');
            if (action === 'edit') self.startEdit(tr);
            else if (action === 'cancel') self.cancelEdit();
            else if (action === 'save') self.saveEdit(tr);
            else if (action === 'delete') self.remove(tr);
        });

        this.root.addEventListener('keydown', function (evt) {
            if (!evt.target.matches || !evt.target.matches('[data-sgi-edit-input]')) return;
            if (evt.key === 'Enter') {
                evt.preventDefault();
                var tr = evt.target.closest('tr[data-id]');
                if (tr) self.saveEdit(tr);
            } else if (evt.key === 'Escape') {
                evt.preventDefault();
                self.cancelEdit();
            }
        });

        if (this.modal) {
            this.modal.addEventListener('change', function (evt) {
                if (evt.target.closest('[data-sgi-catalog-qty]')) self.buildFields();
            });
            this.modal.addEventListener('click', function (evt) {
                if (evt.target.closest('[data-sgi-catalog-save]')) {
                    evt.preventDefault();
                    self.submitNew();
                }
            });
            this.modal.addEventListener('keydown', function (evt) {
                if (evt.key === 'Enter' && evt.target.matches('[data-sgi-new-name]')) {
                    evt.preventDefault();
                    self.submitNew();
                }
            });
        }
    };

    // ==================== API PÚBLICA ====================

    /**
     * Arranca un catálogo. Sin argumentos, o con un elemento raíz, o con un
     * objeto de configuración `{root, resource, api, singular, plural,
     * nameLabel, canCreate, canUpdate, canDelete}`.
     * @returns {Catalog|null}
     */
    function init(config) {
        var cfg = config || {};
        var root = (cfg instanceof Element) ? cfg
            : (cfg.root || document.querySelector('[data-sgi-catalog]'));
        if (!root) return null;
        if (root.dataset.sgiCatalogBound === '1') return null;   // idempotente
        root.dataset.sgiCatalogBound = '1';

        var instance = new Catalog(root, (cfg instanceof Element) ? {} : cfg);
        instance.init();
        return instance;
    }

    function initAll(scope) {
        var node = scope || document;
        var out = [];
        var made;

        // El propio nodo puede SER el catálogo (swap de HTMX sobre la sección).
        if (node.matches && node.matches('[data-sgi-catalog]')) {
            made = init(node);
            if (made) out.push(made);
        }

        var roots = node.querySelectorAll('[data-sgi-catalog]');
        for (var i = 0; i < roots.length; i++) {
            made = init(roots[i]);
            if (made) out.push(made);
        }
        return out;
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { initAll(root || document); });
    }

    window.SgcCatalogCrud = { init: init, initAll: initAll };
})();
