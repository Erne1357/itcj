/**
 * work/work-items.js — base compartida de INCIDENCIAS y EVENTOS DE PROGRAMA.
 *
 * Expone SOLO `window.AdhocWorkItems` (IIFE, sin globales sueltas).
 *
 * QUÉ SUSTITUYE
 * -------------
 * `incidents/incidents.js` y `programs/programs.js` del legacy: dos clases ES6
 * globales (`IncidenciasManager`, `ProgramasManager`) idénticas al 90 %, con
 * una regresión propia en la copia (el filtrado de programas usaba
 * `cells[index]` donde el de incidencias usaba `cells[index + 1]`, así que la
 * columna de Docs filtraba por Prioridad). Aquí hay UNA base y dos
 * configuraciones, que es lo que exige el plan §6.5.
 *
 * Y de paso cierra lo que aquellas tenían roto:
 *   · `confirm()` nativo para borrar y para duplicar          → confirmDialog()
 *   · `${data.title}` / `${data.description}` en innerHTML     → DOM + textContent
 *   · `htmlCat`/`htmlArea`/`htmlProc`/`htmlUsers` (HTML crudo
 *     inyectado desde Jinja dentro de un template literal)     → page_data + JSON
 *   · `.modal-overlay` con style.display='flex'                → bootstrap.Modal
 *   · URLs `/app_prueba/api/incidents/edit/` (404 silencioso)  → page_data.api
 *   · `window.location.href = '/app_prueba/extintor/tareas/'`  → page_data.tasks_url
 *   · toda la tabla renderizada desde Jinja, sin paginar       → GET paginado
 *
 * CÓMO SE USA (desde el módulo de cada dominio)
 * ---------------------------------------------
 *   AdhocWorkItems.register({
 *       kind: 'program',
 *       extraFields: [ {name: 'location', label: 'Ubicación', type: 'text', after: 'process_id'} ],
 *       cells: { files: function (item, ctx) { ... } },
 *       actions: function (item, ctx) { return [ {name: 'duplicate', icon: 'fa-regular fa-copy'} ]; },
 *       onAction: function (name, item, ctx) { ... },
 *       buildCreate: function (records, formRoot, ctx) { return {url, options}; }
 *   });
 *
 * El contrato de datos llega en `page_data` (bloque `<script type="application/json">`):
 *   kind · api · table_id · tasks_url · statuses · priorities · categories ·
 *   areas · processes · users · can{} · labels{} · today · per_page · query_map
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;

    // ==================== TONOS (espejo de la macro status_badge) ====================

    // Prioridad: el legacy la pinta con la clase `.badge-` + la prioridad en
    // minusculas. Urgente va en recuadro rojo claro, Media en ambar y Baja en
    // verde, las tres como TEXTO en negrita, sin pastilla solida ni mayusculas.
    // Se conserva ese aspecto con clases propias (`.badge-` esta prohibida:
    // pisaria a Bootstrap). 'Alta' no existia en el legacy: se pinta como
    // Urgente.
    var PRIORITY_CLASS = {
        'Baja': 'adhoc-prio-baja',
        'Media': 'adhoc-prio-media',
        'Alta': 'adhoc-prio-urgente',
        'Urgente': 'adhoc-prio-urgente'
    };

    // ==================== HELPERS DE DOM ====================

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    /** `name` es la clase COMPLETA de Font Awesome 6 ("fa-solid fa-trash"). */
    function iconEl(name, title) {
        var i = el('i', name);
        if (title) i.setAttribute('title', title);
        return i;
    }

    function priorityBadge(value) {
        var span = el('span', PRIORITY_CLASS[value] || 'adhoc-prio-media');
        span.textContent = value || '—';
        return span;
    }

    /** Boton de icono suelto de la fila. Legacy `.btn-icon` / `.icon-action-blue`:
     *  sin recuadro, coloreado, y crece al pasar el raton. */
    function actionButton(name, icon, title, variant) {
        var btn = el('button', 'adhoc-icon-btn ' + (variant || 'adhoc-icon-primary'));
        btn.type = 'button';
        btn.setAttribute('data-adhoc-row-action', name);
        btn.setAttribute('title', title);
        btn.setAttribute('aria-label', title);
        btn.appendChild(iconEl(icon));
        return btn;
    }

    function busy(node, isBusy) {
        if (!node) return;
        node.disabled = !!isBusy;
        node.classList.toggle('disabled', !!isBusy);
    }

    function toast(message, type) {
        if (U && typeof U.showToast === 'function') U.showToast(message, type);
    }

    /** Nombre de un catálogo referenciado: `{category: {name}}` o `category_name`. */
    function refName(item, key) {
        var nested = item[key];
        if (nested && typeof nested === 'object' && nested.name) return nested.name;
        var flat = item[key + '_name'];
        return flat || '';
    }

    function userName(item, key) {
        var nested = item[key];
        if (nested && typeof nested === 'object') {
            return nested.full_name || nested.name || '';
        }
        return item[key + '_name'] || '';
    }

    // ==================== INSTANCIA ====================

    /**
     * @param {HTMLElement} root  la <section data-adhoc-work>
     * @param {Object} data       page_data
     * @param {Object} config     configuración del dominio (ver cabecera)
     */
    function WorkItems(root, data, config) {
        this.root = root;
        this.data = data || {};
        this.config = config || {};
        this.kind = this.data.kind || this.config.kind || 'incident';
        this.api = this.data.api || '';
        this.can = this.data.can || {};
        this.labels = this.data.labels || {};
        this.queryMap = this.data.query_map || {};
        this.perPage = this.data.per_page || 25;

        this.table = root.querySelector('table[data-adhoc-table]');
        this.body = this.table ? this.table.querySelector('[data-adhoc-table-body]') : null;
        this.emptyRow = this.body ? this.body.querySelector('[data-adhoc-empty]') : null;
        this.columns = this.readColumns();

        this.modal = document.querySelector('[data-adhoc-work-modal]');
        this.fieldsBox = this.modal ? this.modal.querySelector('[data-adhoc-work-fields]') : null;

        this.page = 1;
        this.totalPages = 1;
        this.total = 0;
        this.items = [];
        this.editing = null;
        this.loading = false;
        this.searchTimer = null;
    }

    /** Claves de columna, leídas del <thead> (nunca índices cableados a mano). */
    WorkItems.prototype.readColumns = function () {
        if (!this.table) return [];
        var ths = this.table.querySelectorAll('thead tr:first-child th[data-adhoc-filter-key]');
        var keys = [];
        for (var i = 0; i < ths.length; i++) {
            keys.push(ths[i].getAttribute('data-adhoc-filter-key'));
        }
        return keys;
    };

    WorkItems.prototype.init = function () {
        if (!this.body) {
            console.error('[adhoc] work-items: falta la tabla de', this.kind);
            return;
        }
        this.fillFilterOptions();
        this.bind();
        this.load();
    };

    // ---------- filtros ----------

    /**
     * Rellena los <select> de la barra de filtros desde page_data.
     * `data-adhoc-options="categories"` dice de qué colección salen las opciones;
     * cada <option> se crea con createElement + textContent, así que un nombre de
     * área con comillas o con markup no puede inyectar nada (el legacy los
     * concatenaba como HTML crudo desde Jinja).
     */
    WorkItems.prototype.fillFilterOptions = function () {
        var self = this;
        var selects = this.root.querySelectorAll('select[data-adhoc-options]');
        for (var i = 0; i < selects.length; i++) {
            (function (select) {
                var source = select.getAttribute('data-adhoc-options');
                var values = self.data[source] || [];
                for (var j = 0; j < values.length; j++) {
                    var raw = values[j];
                    var option = document.createElement('option');
                    if (raw && typeof raw === 'object') {
                        option.value = String(raw.id);
                        option.textContent = raw.full_name || raw.name || ('#' + raw.id);
                    } else {
                        option.value = String(raw);
                        option.textContent = String(raw);
                    }
                    select.appendChild(option);
                }
            })(selects[i]);
        }
    };

    /** Estado de los filtros → query string, ya traducido con `query_map`. */
    WorkItems.prototype.queryString = function () {
        var parts = ['page=' + this.page, 'per_page=' + this.perPage];
        var inputs = this.root.querySelectorAll('[data-adhoc-param]');
        for (var i = 0; i < inputs.length; i++) {
            var input = inputs[i];
            var value = (input.value || '').trim();
            if (!value) continue;
            var logical = input.getAttribute('data-adhoc-param');
            var param = this.queryMap[logical] || logical;
            parts.push(encodeURIComponent(param) + '=' + encodeURIComponent(value));
        }
        return parts.join('&');
    };

    WorkItems.prototype.clearFilters = function () {
        var inputs = this.root.querySelectorAll('[data-adhoc-param]');
        for (var i = 0; i < inputs.length; i++) inputs[i].value = '';
        this.page = 1;
        this.load();
    };

    // ---------- carga y pintado ----------

    WorkItems.prototype.load = function () {
        var self = this;
        if (this.loading) return Promise.resolve();
        this.loading = true;
        this.root.classList.add('is-loading');

        return U.fetchJson(this.api + '?' + this.queryString())
            .then(function (payload) {
                self.items = (payload && payload.data) || [];
                self.total = (payload && payload.total) || 0;
                self.totalPages = (payload && payload.total_pages) || 1;
                self.page = (payload && payload.page) || self.page;
                self.render();
            })
            .catch(function (err) {
                self.items = [];
                self.total = 0;
                self.totalPages = 1;
                self.render();
                toast('No se pudo cargar la lista: ' + err.message, 'error');
            })
            .then(function () {
                self.loading = false;
                self.root.classList.remove('is-loading');
            });
    };

    WorkItems.prototype.render = function () {
        var frag = document.createDocumentFragment();
        for (var i = 0; i < this.items.length; i++) {
            frag.appendChild(this.buildRow(this.items[i]));
        }

        // Se vacía el tbody conservando la fila de "sin resultados".
        var rows = this.body.querySelectorAll('tr:not([data-adhoc-empty])');
        for (var j = 0; j < rows.length; j++) rows[j].remove();

        if (this.emptyRow) this.body.insertBefore(frag, this.emptyRow);
        else this.body.appendChild(frag);

        this.renderPager();
    };

    WorkItems.prototype.renderPager = function () {
        var count = this.root.querySelector('[data-adhoc-work-count]');
        if (count) {
            count.textContent = this.total === 0
                ? 'Sin resultados'
                : (this.items.length + ' de ' + this.total + ' ' + (this.labels.plural || 'registros'));
        }

        var info = this.root.querySelector('[data-adhoc-work-pageinfo]');
        if (info) info.textContent = 'Página ' + this.page + ' de ' + (this.totalPages || 1);

        var prev = this.root.querySelector('[data-adhoc-work-page="prev"]');
        var next = this.root.querySelector('[data-adhoc-work-page="next"]');
        if (prev) prev.disabled = this.page <= 1;
        if (next) next.disabled = this.page >= (this.totalPages || 1);
    };

    WorkItems.prototype.buildRow = function (item) {
        var tr = el('tr', 'adhoc-row-click');
        tr.setAttribute('data-id', String(item.id));

        for (var i = 0; i < this.columns.length; i++) {
            var key = this.columns[i];
            var td = el('td');
            td.setAttribute('data-adhoc-cell', key);
            if (key === 'tasks' || key === 'files') td.className = 'adhoc-col-center';
            if (key === 'actions') td.className = 'adhoc-col-end';
            this.fillCell(td, key, item);
            tr.appendChild(td);
        }
        return tr;
    };

    WorkItems.prototype.fillCell = function (td, key, item) {
        // 1) el dominio puede sobrescribir cualquier celda
        var custom = this.config.cells && this.config.cells[key];
        if (typeof custom === 'function') {
            var made = custom(item, this);
            if (made instanceof Node) td.appendChild(made);
            else if (made !== undefined && made !== null) td.textContent = String(made);
            return;
        }

        switch (key) {
            case 'folio':
                td.appendChild(el('strong', null, item.folio || '—'));
                break;
            case 'title':
                // El clamp vive en el hijo: un <td> no puede ser -webkit-box, y
                // sin esto un titulo de 200 chars estira la fila a 235px.
                td.className += ' adhoc-cell-clamp';
                var titleBox = el('div', 'adhoc-clamp-text');
                titleBox.textContent = item.title || '';
                if (item.title) td.title = item.title;
                td.appendChild(titleBox);
                break;
            case 'category':
            case 'area':
            case 'process':
                td.textContent = refName(item, key) || '—';
                break;
            case 'responsible':
                td.textContent = userName(item, 'responsible') || 'Sin asignar';
                break;
            case 'location':
                td.textContent = item.location || '—';
                break;
            case 'start_date':
            case 'real_date':
                td.className += ' adhoc-cell-nowrap';
                td.textContent = item[key] || '—';
                break;
            case 'commitment_date':
                td.className += ' adhoc-cell-nowrap';
                td.textContent = item.commitment_date || '—';
                if (this.isOverdue(item)) {
                    td.appendChild(document.createTextNode(' '));
                    var warn = iconEl('fa-solid fa-triangle-exclamation', 'Vencido');
                    warn.classList.add('adhoc-overdue');
                    td.appendChild(warn);
                }
                break;
            case 'priority':
                td.appendChild(priorityBadge(item.priority));
                break;
            case 'status':
                // El legacy escribe el estatus tal cual, sin pastilla.
                td.className += ' adhoc-cell-nowrap';
                td.textContent = item.status || '—';
                break;
            case 'tasks':
                td.appendChild(this.tasksButton(item));
                break;
            case 'actions':
                td.appendChild(this.buildActions(item));
                break;
            default:
                var value = item[key];
                td.textContent = (value === null || value === undefined) ? '' : String(value);
        }
    };

    /** Compromiso pasado y sin cierre real. Comparación por cadena ISO (YYYY-MM-DD). */
    WorkItems.prototype.isOverdue = function (item) {
        var today = this.data.today;
        return !!(today && item.commitment_date && !item.real_date && item.commitment_date < today);
    };

    WorkItems.prototype.tasksButton = function (item) {
        var btn = actionButton('tasks', 'fa-solid fa-list-check', 'Ver Tareas', 'adhoc-icon-task');
        var count = item.task_count;
        if (typeof count === 'number') {
            btn.appendChild(document.createTextNode(' '));
            btn.appendChild(el('span', 'adhoc-count-pill', String(count)));
        }
        return btn;
    };

    WorkItems.prototype.buildActions = function (item) {
        var box = el('div', 'adhoc-actions');

        if (this.can.update) {
            box.appendChild(actionButton('edit', 'fa-solid fa-pen', 'Editar'));
        }

        var extra = (typeof this.config.actions === 'function')
            ? (this.config.actions(item, this) || []) : [];
        for (var i = 0; i < extra.length; i++) {
            var spec = extra[i];
            box.appendChild(actionButton(spec.name, spec.icon, spec.title, spec.variant));
        }

        if (this.can.delete) {
            box.appendChild(actionButton('delete', 'fa-solid fa-trash', 'Eliminar', 'adhoc-icon-trash'));
        }
        return box;
    };

    // ---------- campos del formulario ----------

    WorkItems.prototype.baseFields = function () {
        var labels = this.labels;
        return [
            { name: 'folio', label: 'Folio', type: 'text', maxLength: 50 },
            { name: 'title', label: labels.title_field || 'Título', type: 'text',
              required: true, maxLength: 200 },
            { name: 'category_id', label: 'Categoría', type: 'select', source: 'categories' },
            { name: 'area_id', label: 'Área', type: 'select', source: 'areas' },
            { name: 'process_id', label: 'Proceso', type: 'select', source: 'processes' },
            { name: 'responsible_id', label: 'Responsable', type: 'select', source: 'users' },
            { name: 'priority', label: 'Prioridad', type: 'select', source: 'priorities',
              placeholder: null, fallback: 'Media' },
            { name: 'status', label: 'Estatus', type: 'select', source: 'statuses',
              placeholder: null },
            { name: 'start_date', label: labels.date_start || 'Fecha de inicio', type: 'date' },
            { name: 'commitment_date', label: labels.date_commitment || 'Fecha compromiso', type: 'date' },
            { name: 'real_date', label: labels.date_real || 'Fecha real de cierre', type: 'date',
              editOnly: true },
            { name: 'description', label: labels.description || 'Descripción', type: 'textarea',
              full: true }
        ];
    };

    /** Campos base + los del dominio, colocados con `after`. */
    WorkItems.prototype.fields = function (mode) {
        var list = this.baseFields();
        var extra = this.config.extraFields || [];

        for (var i = 0; i < extra.length; i++) {
            var spec = extra[i];
            var at = list.length;
            if (spec.after) {
                for (var j = 0; j < list.length; j++) {
                    if (list[j].name === spec.after) { at = j + 1; break; }
                }
            }
            list.splice(at, 0, spec);
        }

        return list.filter(function (spec) {
            if (spec.editOnly && mode !== 'edit') return false;
            if (spec.createOnly && mode !== 'create') return false;
            return true;
        });
    };

    /** Construye un campo con DOM, nunca con innerHTML + interpolación. */
    WorkItems.prototype.buildField = function (spec, index, values) {
        var wrap = el('div', 'adhoc-field' + (spec.full ? ' adhoc-field-full' : ''));
        var id = 'adhoc-wf-' + index + '-' + spec.name;
        var value = values ? values[spec.name] : undefined;

        var label = el('label', 'form-label adhoc-label', spec.label);
        label.setAttribute('for', id);
        if (spec.required) {
            var star = el('span', 'adhoc-required', '*');
            star.setAttribute('aria-hidden', 'true');
            label.appendChild(star);
        }
        wrap.appendChild(label);

        var control;
        if (spec.type === 'textarea') {
            control = el('textarea', 'form-control');
            control.rows = spec.rows || 3;
            control.value = value == null ? '' : String(value);
        } else if (spec.type === 'select') {
            control = el('select', 'form-select');
            this.fillSelect(control, spec, value, values);
        } else if (spec.type === 'file') {
            control = el('input', 'form-control');
            control.type = 'file';
            if (spec.multiple !== false) control.multiple = true;
        } else {
            control = el('input', 'form-control');
            control.type = spec.type || 'text';
            control.value = value == null ? '' : String(value);
            if (spec.maxLength) control.maxLength = spec.maxLength;
            if (spec.placeholder) control.placeholder = spec.placeholder;
        }

        control.id = id;
        control.setAttribute('data-adhoc-field', spec.name);
        if (spec.required) control.required = true;
        wrap.appendChild(control);

        if (spec.help) wrap.appendChild(el('div', 'form-text adhoc-field-help', spec.help));
        return wrap;
    };

    /**
     * Rellena un <select> del modal.
     *
     * `record` es la fila que se esta editando y solo se usa para el caso de
     * abajo: si el valor guardado NO esta entre las opciones, hay que inyectarlo
     * igualmente. Sin eso el select se queda en el placeholder, `readBlock` lo
     * lee como '' y el PATCH manda `null`: guardar cualquier cambio BORRA el
     * valor historico sin avisar. Pasaba con `responsible_id` en 145 de las 276
     * incidencias migradas, porque `assignable_users()` solo devuelve a quien
     * tiene acceso a la app hoy (29 personas) y la mitad del historial de 10
     * anios lo firmo gente que ya no lo tiene.
     */
    WorkItems.prototype.fillSelect = function (select, spec, value, record) {
        var values = this.data[spec.source] || [];
        var chosen = (value === null || value === undefined) ? '' : String(value);
        var matched = false;

        if (spec.placeholder !== null) {
            var ph = document.createElement('option');
            ph.value = '';
            ph.textContent = spec.placeholder || 'Seleccionar...';
            select.appendChild(ph);
        }

        for (var i = 0; i < values.length; i++) {
            var raw = values[i];
            var option = document.createElement('option');
            if (raw && typeof raw === 'object') {
                option.value = String(raw.id);
                option.textContent = raw.full_name || raw.name || ('#' + raw.id);
            } else {
                option.value = String(raw);
                option.textContent = String(raw);
            }
            if (option.value === chosen) { option.selected = true; matched = true; }
            select.appendChild(option);
        }

        // El valor guardado ya no esta en el catalogo: se conserva como opcion
        // propia para que editar el registro no lo borre. Se rotula con el
        // nombre que la propia fila ya trae (viene por relationship en el
        // serializer), asi que no hace falta pedirlo al servidor.
        if (chosen && !matched) {
            var kept = document.createElement('option');
            kept.value = chosen;
            var label = record ? userName(record, spec.name.replace(/_id$/, '')) : '';
            kept.textContent = (label || '#' + chosen) + ' (sin acceso actual)';
            kept.selected = true;
            select.appendChild(kept);
        }

        if (!chosen && spec.fallback) select.value = spec.fallback;
    };

    // ---------- modal ----------

    WorkItems.prototype.openNew = function () {
        if (!this.modal || !this.fieldsBox) return;
        var qty = this.root.querySelector('[data-adhoc-work-qty]');
        var count = qty ? (parseInt(qty.value, 10) || 1) : 1;

        this.editing = null;
        this.setModalTitle('Nuevo ' + (this.labels.singular || 'registro'), 'fa-solid fa-circle-plus');
        this.fieldsBox.textContent = '';

        for (var i = 0; i < count; i++) {
            this.fieldsBox.appendChild(this.buildRecordBlock(i, null, 'create', count));
        }
        this.toggleDelete(false);
        this.showModal();
    };

    WorkItems.prototype.openEdit = function (item) {
        if (!this.modal || !this.fieldsBox || !item) return;
        this.editing = item;
        this.setModalTitle('Editar ' + (this.labels.singular || 'registro'), 'fa-solid fa-pen-to-square');
        this.fieldsBox.textContent = '';
        this.fieldsBox.appendChild(this.buildRecordBlock(0, item, 'edit', 1));
        this.toggleDelete(!!this.can.delete);
        this.showModal();
    };

    WorkItems.prototype.buildRecordBlock = function (index, values, mode, total) {
        var block = el('fieldset', 'adhoc-fieldset');
        block.setAttribute('data-adhoc-record', String(index));

        if (mode === 'create' && total > 1) {
            block.appendChild(el('legend', 'adhoc-fieldset-title',
                (this.labels.singular || 'Registro') + ' #' + (index + 1)));
        }

        var grid = el('div', 'adhoc-form-grid');
        var specs = this.fields(mode);
        for (var i = 0; i < specs.length; i++) {
            grid.appendChild(this.buildField(specs[i], index, values));
        }
        block.appendChild(grid);

        if (typeof this.config.onRecordBlock === 'function') {
            this.config.onRecordBlock(block, index, values, mode, this);
        }
        return block;
    };

    WorkItems.prototype.setModalTitle = function (text, icon) {
        var title = this.modal.querySelector('[data-adhoc-work-modal-title]');
        var iconEl_ = this.modal.querySelector('[data-adhoc-work-modal-icon]');
        if (title) title.textContent = text;
        if (iconEl_) iconEl_.className = icon + ' me-2';
    };

    WorkItems.prototype.toggleDelete = function (show) {
        var btn = this.modal.querySelector('[data-adhoc-work-delete]');
        if (btn) btn.hidden = !show;
    };

    WorkItems.prototype.showModal = function () {
        if (window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(this.modal).show();
        }
    };

    WorkItems.prototype.hideModal = function () {
        if (window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(this.modal).hide();
        }
    };

    // ---------- lectura del formulario ----------

    /** Un bloque `<fieldset data-adhoc-record>` → objeto plano listo para la API. */
    WorkItems.prototype.readBlock = function (block) {
        var record = {};
        var controls = block.querySelectorAll('[data-adhoc-field]');
        for (var i = 0; i < controls.length; i++) {
            var control = controls[i];
            if (control.type === 'file') continue;      // los archivos van aparte
            var name = control.getAttribute('data-adhoc-field');
            var value = (control.value || '').trim();
            // El "" del <option> placeholder se manda como null: el schema Pydantic
            // lo coacciona igual, pero así el PATCH limpia la FK de verdad.
            record[name] = value === '' ? null : value;
        }
        return record;
    };

    WorkItems.prototype.blocks = function () {
        return this.fieldsBox.querySelectorAll('[data-adhoc-record]');
    };

    // ---------- guardar ----------

    WorkItems.prototype.save = function () {
        var self = this;
        var btn = this.modal.querySelector('[data-adhoc-work-save]');
        var blocks = this.blocks();
        var records = [];
        var i;

        for (i = 0; i < blocks.length; i++) {
            var record = this.readBlock(blocks[i]);
            if (!record.title) {
                toast('El título es obligatorio en todos los registros.', 'warning');
                var input = blocks[i].querySelector('[data-adhoc-field="title"]');
                if (input) input.focus();
                return;
            }
            records.push(record);
        }
        if (!records.length) return;

        var request = this.editing
            ? {
                url: this.api + '/' + encodeURIComponent(this.editing.id),
                options: { method: 'PATCH', body: JSON.stringify(records[0]) }
            }
            : this.createRequest(records);

        busy(btn, true);
        U.fetchJson(request.url, request.options)
            .then(function (payload) {
                toast(self.editing
                    ? 'Cambios guardados.'
                    : ((payload && payload.total) || records.length) + ' registro(s) creado(s).',
                    'success');
                self.hideModal();
                return self.load();
            })
            .catch(function (err) {
                toast(err.message, 'error');
            })
            .then(function () {
                busy(btn, false);
            });
    };

    /** Alta masiva. El dominio puede sustituirla (programas manda multipart). */
    WorkItems.prototype.createRequest = function (records) {
        if (typeof this.config.buildCreate === 'function') {
            return this.config.buildCreate(records, this.fieldsBox, this);
        }
        return {
            url: this.api,
            options: { method: 'POST', body: JSON.stringify({ items: records }) }
        };
    };

    // ---------- borrar ----------

    WorkItems.prototype.remove = function (item) {
        var self = this;
        if (!item) return;

        // El legacy hacía `if (!confirm(...)) e.preventDefault()` dentro de un
        // handler síncrono; aquí el flujo se invierte a promesa.
        U.confirmDialog({
            title: 'Eliminar ' + (this.labels.singular || 'registro'),
            message: '¿Eliminar "' + (item.title || item.folio || '') + '"? ' +
                     'Se borran también sus tareas. Esta acción no se puede deshacer.',
            confirmText: 'Eliminar',
            variant: 'danger'
        }).then(function (ok) {
            if (!ok) return null;
            return U.fetchJson(self.api + '/' + encodeURIComponent(item.id), { method: 'DELETE' })
                .then(function (payload) {
                    toast((payload && payload.message) || 'Registro eliminado.', 'success');
                    self.hideModal();
                    return self.load();
                })
                .catch(function (err) {
                    toast(err.message, 'error');
                });
        });
    };

    // ---------- utilidades ----------

    WorkItems.prototype.find = function (id) {
        for (var i = 0; i < this.items.length; i++) {
            if (String(this.items[i].id) === String(id)) return this.items[i];
        }
        return null;
    };

    WorkItems.prototype.goToTasks = function (item) {
        var template = this.data.tasks_url;
        if (!template) return;
        U.navigate(template.replace('{id}', encodeURIComponent(item.id)));
    };

    // ---------- listeners (delegados, cero onclick inline) ----------

    WorkItems.prototype.bind = function () {
        var self = this;

        this.root.addEventListener('click', function (evt) {
            if (evt.target.closest('[data-adhoc-work-new]')) {
                evt.preventDefault();
                self.openNew();
                return;
            }
            if (evt.target.closest('[data-adhoc-work-clear]')) {
                evt.preventDefault();
                self.clearFilters();
                return;
            }
            // "Filtrar" existe porque la pantalla del legacy lo tiene. Los
            // filtros ya se aplican solos al cambiar, asi que aqui solo fuerza
            // una recarga desde la primera pagina.
            if (evt.target.closest('[data-adhoc-work-filter]')) {
                evt.preventDefault();
                self.page = 1;
                self.load();
                return;
            }

            var pager = evt.target.closest('[data-adhoc-work-page]');
            if (pager) {
                evt.preventDefault();
                var dir = pager.getAttribute('data-adhoc-work-page');
                var target = dir === 'prev' ? self.page - 1 : self.page + 1;
                if (target >= 1 && target <= (self.totalPages || 1)) {
                    self.page = target;
                    self.load();
                }
                return;
            }

            var tr = evt.target.closest('tr[data-id]');
            if (!tr) return;
            var item = self.find(tr.getAttribute('data-id'));
            if (!item) return;

            var action = evt.target.closest('[data-adhoc-row-action]');
            if (action) {
                evt.preventDefault();
                evt.stopPropagation();
                self.dispatch(action.getAttribute('data-adhoc-row-action'), item);
                return;
            }

            // Clic en la fila = editar (UX del legacy, que se conserva).
            if (self.can.update) self.openEdit(item);
        });

        // Filtros: los selects y las fechas disparan al cambiar; la búsqueda
        // libre espera a que el usuario deje de escribir.
        this.root.addEventListener('change', function (evt) {
            if (!evt.target.matches || !evt.target.matches('[data-adhoc-param]')) return;
            if (evt.target.type === 'search' || evt.target.type === 'text') return;
            self.page = 1;
            self.load();
        });

        this.root.addEventListener('input', function (evt) {
            if (!evt.target.matches || !evt.target.matches('[data-adhoc-param]')) return;
            if (evt.target.type !== 'search' && evt.target.type !== 'text') return;
            clearTimeout(self.searchTimer);
            self.searchTimer = setTimeout(function () {
                self.page = 1;
                self.load();
            }, 350);
        });

        this.root.addEventListener('keydown', function (evt) {
            if (evt.key !== 'Enter') return;
            if (!evt.target.matches || !evt.target.matches('[data-adhoc-param]')) return;
            evt.preventDefault();
            clearTimeout(self.searchTimer);
            self.page = 1;
            self.load();
        });

        if (this.modal) {
            this.modal.addEventListener('click', function (evt) {
                if (evt.target.closest('[data-adhoc-work-save]')) {
                    evt.preventDefault();
                    self.save();
                } else if (evt.target.closest('[data-adhoc-work-delete]')) {
                    evt.preventDefault();
                    self.remove(self.editing);
                }
            });
        }
    };

    WorkItems.prototype.dispatch = function (name, item) {
        if (name === 'edit') return this.openEdit(item);
        if (name === 'delete') return this.remove(item);
        if (name === 'tasks') return this.goToTasks(item);
        if (typeof this.config.onAction === 'function') {
            this.config.onAction(name, item, this);
        }
    };

    // ==================== ARRANQUE ====================

    var _config = null;
    var _instances = [];

    function mount(root) {
        if (!root || root.dataset.adhocWorkBound === '1') return null;
        // Sin la configuración del dominio la pantalla saldría a medias (sin las
        // celdas ni las acciones propias), así que se espera a `register()`.
        if (_config === null) return null;
        root.dataset.adhocWorkBound = '1';

        var data = (U && typeof U.pageData === 'function') ? U.pageData() : {};
        var instance = new WorkItems(root, data, _config || {});
        instance.init();
        _instances.push(instance);
        return instance;
    }

    function initAll(scope) {
        var node = scope || document;
        var out = [];
        var made;

        if (node.matches && node.matches('[data-adhoc-work]')) {
            made = mount(node);
            if (made) out.push(made);
        }
        var roots = node.querySelectorAll ? node.querySelectorAll('[data-adhoc-work]') : [];
        for (var i = 0; i < roots.length; i++) {
            made = mount(roots[i]);
            if (made) out.push(made);
        }
        return out;
    }

    /**
     * Registra la configuración del dominio y arranca. La llama el módulo de
     * cada pantalla (incidents.js / programs.js), que se carga DESPUÉS de este.
     * @param {Object} config
     */
    function register(config) {
        _config = config || {};
        _instances = [];
        initAll(document);
        return _instances;
    }

    window.AdhocWorkItems = {
        register: register,
        initAll: initAll,
        priorityBadge: priorityBadge,
        actionButton: actionButton,
        el: el,
        iconEl: iconEl
    };

    // ---------- init idempotente ----------
    //
    // Dos caminos, a propósito:
    //
    //  1. `AdhocUtils.onReady` — la carga inicial de la página.
    //  2. `htmx:afterSettle` — la navegación con hx-boost. Hace falta porque la
    //     guarda de `onReady` vive en el `dataset` del nodo raíz del swap, que
    //     con hx-boost es <body>: el morph lo CONSERVA, así que su bandera
    //     sobrevive a la navegación y aquel callback ya no volvería a correr.
    //     El listener se registra UNA sola vez (bandera en <html>, que ningún
    //     swap toca) y delega en `window.AdhocWorkItems`, es decir en la
    //     configuración VIGENTE: si idiomorph conserva el <script> del dominio
    //     —caso de un swap sobre la misma pantalla— este módulo no se re-ejecuta
    //     y leer el global es la única forma de no quedarse con una closure
    //     muerta.
    //
    // La idempotencia real la da `dataset.adhocWorkBound` de cada sección, que
    // sí se renueva con el morph: entrar por los dos caminos no duplica nada.
    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { initAll(root || document); });
    }
    if (!document.documentElement.dataset.adhocWorkHtmx) {
        document.documentElement.dataset.adhocWorkHtmx = '1';
        document.addEventListener('htmx:afterSettle', function (evt) {
            var api = window.AdhocWorkItems;
            if (api && typeof api.initAll === 'function') {
                api.initAll((evt && evt.target) || document);
            }
        });
    }
})();
