/**
 * work/tasks.js — tareas de una incidencia O de un evento de programa.
 *
 * Expone SOLO `window.AdhocTasks` (IIFE, sin globales sueltas).
 *
 * UN SOLO módulo para las dos pantallas, como el template: lo que cambia
 * (`parent_type`, `parent_id`, a dónde vuelve el botón "Volver") llega en
 * `page_data`. El legacy también compartía el JS —`incidents/tasks.js`, clase
 * global `TareasExpedienteManager`— pero la URL de asignación se decidía en el
 * TEMPLATE con un `{% set ruta_base = ... %}` y viajaba en `data-url` por fila.
 *
 * QUÉ ARREGLA
 * -----------
 *  · `confirm('¿Borrar esta tarea de forma permanente?')` en el submit de un
 *    <form> síncrono → `AdhocUtils.confirmDialog()` (promesa).
 *  · `${desc}` sin escapar dentro de `formContainer.innerHTML` al editar → DOM.
 *  · `TAREAS_CONFIG.htmlUsers`: los `<option>` de responsables llegaban como
 *    HTML crudo desde Jinja dentro de un template literal → `page_data.users`.
 *  · La tabla venía renderizada desde Jinja con `tarea.assigned_users` dentro
 *    del `{% for %}` (un SELECT por tarea) → `GET /tasks` con eager loading.
 *  · El `<select>` de estatus del legacy solo ofrecía tres de los seis valores
 *    del vocabulario real, así que editar una tarea "En Revisión" la degradaba
 *    silenciosamente a "Pendiente" → aquí salen los seis de `page_data`.
 *  · La "fila hija" de detalle decía SIEMPRE "Pendiente de cierre", con el
 *    texto cableado → se sustituye por el estatus real y los responsables.
 *
 * API consumida:
 *   GET    /api/adhoc/v2/tasks?parent_type=&parent_id=   → {success, data, total}
 *   POST   /api/adhoc/v2/tasks                           → {parent_type, parent_id, tasks:[…]}
 *   PATCH  /api/adhoc/v2/tasks/{id}
 *   DELETE /api/adhoc/v2/tasks/{id}
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;

    // El legacy escribe el estatus de la tarea en NEGRITA, sin pastilla
    // (`<td><strong>{{ tarea.status }}</strong></td>`), y la prioridad ni la
    // enseña. Aqui se conserva el estatus en negrita y la prioridad se pinta
    // con las mismas clases de texto que la tabla de incidencias.
    var PRIORITY_CLASS = {
        'Baja': 'adhoc-prio-baja',
        'Media': 'adhoc-prio-media',
        'Alta': 'adhoc-prio-urgente',
        'Urgente': 'adhoc-prio-urgente'
    };

    // ==================== HELPERS ====================

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    /** `name` es la clase COMPLETA de Font Awesome 6 ("fa-solid fa-bell"). */
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

    /** Legacy `.btn-icon-small`: 1.1rem, sin recuadro, y crece al pasar el raton. */
    function actionButton(name, icon, title, variant) {
        var btn = el('button', 'adhoc-icon-btn ' + (variant || 'adhoc-icon-primary'));
        btn.type = 'button';
        btn.setAttribute('data-adhoc-task-action', name);
        btn.setAttribute('title', title);
        btn.setAttribute('aria-label', title);
        btn.appendChild(iconEl(icon));
        return btn;
    }

    function toast(message, type) {
        if (U && typeof U.showToast === 'function') U.showToast(message, type);
    }

    function assigneeNames(task) {
        var list = task.assignees || [];
        var names = [];
        for (var i = 0; i < list.length; i++) {
            names.push(list[i].name || ('#' + list[i].id));
        }
        return names.join(', ');
    }

    // ==================== INSTANCIA ====================

    function Tasks(root, data) {
        this.root = root;
        this.data = data || {};
        this.api = this.data.api || '/api/adhoc/v2/tasks';
        this.can = this.data.can || {};
        this.parentType = this.data.parent_type;
        this.parentId = this.data.parent_id;

        this.table = root.querySelector('table[data-adhoc-table]');
        this.body = this.table ? this.table.querySelector('[data-adhoc-table-body]') : null;
        this.emptyRow = this.body ? this.body.querySelector('[data-adhoc-empty]') : null;

        this.modal = document.querySelector('[data-adhoc-tasks-modal]');
        this.fieldsBox = this.modal ? this.modal.querySelector('[data-adhoc-tasks-fields]') : null;

        this.items = [];
        this.editing = null;
    }

    Tasks.prototype.init = function () {
        if (!this.body) {
            console.error('[adhoc] tasks.js: falta la tabla de tareas');
            return;
        }
        this.bind();
        this.load();
    };

    // ---------- carga ----------

    Tasks.prototype.load = function () {
        var self = this;
        var query = 'parent_type=' + encodeURIComponent(this.parentType) +
                    '&parent_id=' + encodeURIComponent(this.parentId);

        return U.fetchJson(this.api + '?' + query)
            .then(function (payload) {
                self.items = (payload && payload.data) || [];
                self.render();
            })
            .catch(function (err) {
                self.items = [];
                self.render();
                toast('No se pudieron cargar las tareas: ' + err.message, 'error');
            });
    };

    Tasks.prototype.render = function () {
        var frag = document.createDocumentFragment();
        for (var i = 0; i < this.items.length; i++) {
            frag.appendChild(this.buildRow(this.items[i]));
        }

        var rows = this.body.querySelectorAll('tr:not([data-adhoc-empty])');
        for (var j = 0; j < rows.length; j++) rows[j].remove();

        if (this.emptyRow) this.body.insertBefore(frag, this.emptyRow);
        else this.body.appendChild(frag);

        // Reaplica el filtrado en cliente: la lista de una tarea no está
        // paginada, así que aquí sí manda shared/table-filter.js.
        if (window.AdhocTableFilter && this.table) {
            window.AdhocTableFilter.apply(this.table);
        }
    };

    Tasks.prototype.buildRow = function (task) {
        var tr = el('tr', this.can.update ? 'adhoc-row-click' : '');
        tr.setAttribute('data-id', String(task.id));

        tr.appendChild(this.cell('description', task.description || '', 'adhoc-cell-clamp'));

        var responsables = assigneeNames(task);
        var tdUsers = this.cell('assignees', responsables || 'Sin asignar');
        if (!responsables) tdUsers.classList.add('adhoc-muted-cell');
        tr.appendChild(tdUsers);

        var tdStatus = this.cell('status', '');
        tdStatus.setAttribute('data-adhoc-value', task.status || '');
        tdStatus.appendChild(el('strong', null, task.status || '—'));
        tr.appendChild(tdStatus);

        var tdPriority = this.cell('priority', '');
        tdPriority.appendChild(priorityBadge(task.priority));
        tr.appendChild(tdPriority);

        tr.appendChild(this.cell('start_date', task.start_date || '—', 'adhoc-cell-nowrap'));
        tr.appendChild(this.cell('due_date', task.due_date || '—', 'adhoc-cell-nowrap'));
        tr.appendChild(this.cell('completed_at', task.completed_at || '—', 'adhoc-cell-nowrap'));

        var tdComments = this.cell('comments', '', 'adhoc-col-center');
        tdComments.appendChild(el('span', 'adhoc-count-pill', String(task.comments_count || 0)));
        tr.appendChild(tdComments);

        var tdActions = this.cell('actions', '', 'adhoc-col-end');
        tdActions.appendChild(this.buildActions(task));
        tr.appendChild(tdActions);

        return tr;
    };

    Tasks.prototype.cell = function (key, text, css) {
        var td = el('td', css || null, text);
        td.setAttribute('data-adhoc-cell', key);
        return td;
    };

    Tasks.prototype.buildActions = function (task) {
        var box = el('div', 'adhoc-actions');
        if (this.can.assign) {
            box.appendChild(actionButton('assign', 'fa-solid fa-user-plus', 'Asignar Usuarios', 'adhoc-icon-users'));
            box.appendChild(actionButton('notify', 'fa-solid fa-bell', 'Notificar Atraso', 'adhoc-icon-bell'));
        }
        if (this.can.update) {
            box.appendChild(actionButton('edit', 'fa-solid fa-pen', 'Editar'));
        }
        if (this.can.delete) {
            box.appendChild(actionButton('delete', 'fa-solid fa-trash', 'Eliminar', 'adhoc-icon-trash'));
        }
        return box;
    };

    // ---------- navegación a /adhoc/asignaciones ----------

    Tasks.prototype.goToAssign = function (task, action) {
        var base = this.data.assign_url || '/adhoc/asignaciones';
        var back = window.location.pathname + window.location.search;
        window.location.href = base +
            '?action=' + encodeURIComponent(action) +
            '&task_id=' + encodeURIComponent(task.id) +
            '&return_to=' + encodeURIComponent(back);
    };

    // ---------- formulario ----------

    Tasks.prototype.fieldSpecs = function (mode) {
        var specs = [
            { name: 'description', label: 'Descripción de la tarea', type: 'text',
              required: true, maxLength: 255, full: true,
              placeholder: '¿Qué hay que hacer?' },
            { name: 'priority', label: 'Prioridad', type: 'select',
              source: 'priorities', placeholder: null, fallback: 'Media' },
            { name: 'status', label: 'Estatus', type: 'select',
              source: 'statuses', placeholder: null },
            { name: 'start_date', label: 'Fecha de inicio', type: 'date' },
            { name: 'due_date', label: 'Fecha compromiso', type: 'date' }
        ];
        if (mode === 'create') {
            specs.push({
                name: 'assignee_id', label: 'Responsable inicial', type: 'select',
                source: 'users',
                help: 'Puedes añadir más responsables después, con el botón de asignación.'
            });
        }
        return specs;
    };

    Tasks.prototype.buildField = function (spec, index, values) {
        var wrap = el('div', 'adhoc-field' + (spec.full ? ' adhoc-field-full' : ''));
        var id = 'adhoc-tf-' + index + '-' + spec.name;
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
        if (spec.type === 'select') {
            control = el('select', 'form-select');
            var options = this.data[spec.source] || [];
            var chosen = (value === null || value === undefined) ? '' : String(value);
            if (spec.placeholder !== null) {
                var ph = document.createElement('option');
                ph.value = '';
                ph.textContent = spec.placeholder || 'Seleccionar...';
                control.appendChild(ph);
            }
            for (var i = 0; i < options.length; i++) {
                var raw = options[i];
                var option = document.createElement('option');
                if (raw && typeof raw === 'object') {
                    option.value = String(raw.id);
                    option.textContent = raw.full_name || raw.name || ('#' + raw.id);
                } else {
                    option.value = String(raw);
                    option.textContent = String(raw);
                }
                if (option.value === chosen) option.selected = true;
                control.appendChild(option);
            }
            if (!chosen && spec.fallback) control.value = spec.fallback;
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

    Tasks.prototype.buildBlock = function (index, values, mode, total) {
        var block = el('fieldset', 'adhoc-fieldset');
        block.setAttribute('data-adhoc-record', String(index));

        if (mode === 'create' && total > 1) {
            block.appendChild(el('legend', 'adhoc-fieldset-title', 'Tarea #' + (index + 1)));
        }

        var grid = el('div', 'adhoc-form-grid');
        var specs = this.fieldSpecs(mode);
        for (var i = 0; i < specs.length; i++) {
            grid.appendChild(this.buildField(specs[i], index, values));
        }
        block.appendChild(grid);
        return block;
    };

    Tasks.prototype.openNew = function () {
        if (!this.modal || !this.fieldsBox) return;
        var qty = this.root.querySelector('[data-adhoc-tasks-qty]');
        var count = qty ? (parseInt(qty.value, 10) || 1) : 1;

        this.editing = null;
        this.setTitle('Nuevas tareas', 'fa-solid fa-circle-plus');
        this.fieldsBox.textContent = '';
        for (var i = 0; i < count; i++) {
            this.fieldsBox.appendChild(this.buildBlock(i, null, 'create', count));
        }
        this.toggleDelete(false);
        this.show();
    };

    Tasks.prototype.openEdit = function (task) {
        if (!this.modal || !this.fieldsBox || !task) return;
        this.editing = task;
        this.setTitle('Editar tarea', 'fa-solid fa-pen-to-square');
        this.fieldsBox.textContent = '';
        this.fieldsBox.appendChild(this.buildBlock(0, task, 'edit', 1));
        this.toggleDelete(!!this.can.delete);
        this.show();
    };

    Tasks.prototype.setTitle = function (text, icon) {
        var title = this.modal.querySelector('[data-adhoc-tasks-modal-title]');
        var node = this.modal.querySelector('[data-adhoc-tasks-modal-icon]');
        if (title) title.textContent = text;
        if (node) node.className = icon + ' me-2';
    };

    Tasks.prototype.toggleDelete = function (show) {
        var btn = this.modal.querySelector('[data-adhoc-tasks-delete]');
        if (btn) btn.hidden = !show;
    };

    Tasks.prototype.show = function () {
        if (window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(this.modal).show();
        }
    };

    Tasks.prototype.hide = function () {
        if (window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(this.modal).hide();
        }
    };

    Tasks.prototype.readBlock = function (block) {
        var record = {};
        var controls = block.querySelectorAll('[data-adhoc-field]');
        for (var i = 0; i < controls.length; i++) {
            var name = controls[i].getAttribute('data-adhoc-field');
            var value = (controls[i].value || '').trim();
            record[name] = value === '' ? null : value;
        }
        return record;
    };

    // ---------- guardar ----------

    Tasks.prototype.save = function () {
        var self = this;
        var btn = this.modal.querySelector('[data-adhoc-tasks-save]');
        var blocks = this.fieldsBox.querySelectorAll('[data-adhoc-record]');
        var records = [];
        var i;

        for (i = 0; i < blocks.length; i++) {
            var record = this.readBlock(blocks[i]);
            if (!record.description) {
                toast('La descripción es obligatoria en todas las tareas.', 'warning');
                var input = blocks[i].querySelector('[data-adhoc-field="description"]');
                if (input) input.focus();
                return;
            }
            records.push(record);
        }
        if (!records.length) return;

        var request;
        if (this.editing) {
            var patch = records[0];
            delete patch.assignee_id;
            request = {
                url: this.api + '/' + encodeURIComponent(this.editing.id),
                options: { method: 'PATCH', body: JSON.stringify(patch) }
            };
        } else {
            var tasks = [];
            for (i = 0; i < records.length; i++) {
                var row = records[i];
                var assignee = row.assignee_id;
                delete row.assignee_id;
                row.assignee_ids = assignee ? [parseInt(assignee, 10)] : [];
                tasks.push(row);
            }
            request = {
                url: this.api,
                options: {
                    method: 'POST',
                    body: JSON.stringify({
                        parent_type: this.parentType,
                        parent_id: this.parentId,
                        tasks: tasks
                    })
                }
            };
        }

        btn.disabled = true;
        U.fetchJson(request.url, request.options)
            .then(function (payload) {
                toast(self.editing
                    ? 'Tarea actualizada.'
                    : ((payload && payload.total) || records.length) + ' tarea(s) creada(s).',
                    'success');
                self.hide();
                return self.load();
            })
            .catch(function (err) {
                toast(err.message, 'error');
            })
            .then(function () {
                btn.disabled = false;
            });
    };

    Tasks.prototype.remove = function (task) {
        var self = this;
        if (!task) return;

        U.confirmDialog({
            title: 'Eliminar tarea',
            message: '¿Borrar "' + (task.description || '') + '"? ' +
                     'Se borran también sus comentarios. No se puede deshacer.',
            confirmText: 'Eliminar',
            variant: 'danger'
        }).then(function (ok) {
            if (!ok) return null;
            return U.fetchJson(self.api + '/' + encodeURIComponent(task.id), { method: 'DELETE' })
                .then(function (payload) {
                    toast((payload && payload.message) || 'Tarea eliminada.', 'success');
                    self.hide();
                    return self.load();
                })
                .catch(function (err) {
                    toast(err.message, 'error');
                });
        });
    };

    Tasks.prototype.find = function (id) {
        for (var i = 0; i < this.items.length; i++) {
            if (String(this.items[i].id) === String(id)) return this.items[i];
        }
        return null;
    };

    // ---------- listeners ----------

    Tasks.prototype.bind = function () {
        var self = this;

        this.root.addEventListener('click', function (evt) {
            if (evt.target.closest('[data-adhoc-tasks-new]')) {
                evt.preventDefault();
                self.openNew();
                return;
            }
            // "Filtrar" existe porque la pantalla del legacy lo tiene. El
            // filtrado ya corre en vivo al teclear, asi que aqui solo se
            // reaplica sobre la tabla.
            if (evt.target.closest('[data-adhoc-tasks-filter]')) {
                evt.preventDefault();
                if (window.AdhocTableFilter && self.table) {
                    window.AdhocTableFilter.apply(self.table);
                }
                return;
            }

            var tr = evt.target.closest('tr[data-id]');
            if (!tr) return;
            var task = self.find(tr.getAttribute('data-id'));
            if (!task) return;

            var action = evt.target.closest('[data-adhoc-task-action]');
            if (action) {
                evt.preventDefault();
                evt.stopPropagation();
                var name = action.getAttribute('data-adhoc-task-action');
                if (name === 'edit') self.openEdit(task);
                else if (name === 'delete') self.remove(task);
                else if (name === 'assign') self.goToAssign(task, 'assign');
                else if (name === 'notify') self.goToAssign(task, 'notify');
                return;
            }

            if (self.can.update) self.openEdit(task);
        });

        if (this.modal) {
            this.modal.addEventListener('click', function (evt) {
                if (evt.target.closest('[data-adhoc-tasks-save]')) {
                    evt.preventDefault();
                    self.save();
                } else if (evt.target.closest('[data-adhoc-tasks-delete]')) {
                    evt.preventDefault();
                    self.remove(self.editing);
                }
            });
        }
    };

    // ==================== ARRANQUE ====================

    function initAll(scope) {
        var node = scope || document;
        var roots = [];
        var i;

        if (node.matches && node.matches('[data-adhoc-tasks]')) roots.push(node);
        var found = node.querySelectorAll ? node.querySelectorAll('[data-adhoc-tasks]') : [];
        for (i = 0; i < found.length; i++) roots.push(found[i]);

        var out = [];
        for (i = 0; i < roots.length; i++) {
            var root = roots[i];
            if (root.dataset.adhocTasksBound === '1') continue;
            root.dataset.adhocTasksBound = '1';
            var instance = new Tasks(root, (U && U.pageData) ? U.pageData() : {});
            instance.init();
            out.push(instance);
        }
        return out;
    }

    // Igual que en work/work-items.js: `onReady` cubre la carga inicial y el
    // listener de htmx la navegación con hx-boost (cuya guarda vive en el
    // dataset de <body>, que el morph conserva). La bandera de <html> evita
    // acumular listeners si el módulo se re-ejecuta tras un swap.
    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { initAll(root || document); });
    }
    if (!document.documentElement.dataset.adhocTasksHtmx) {
        document.documentElement.dataset.adhocTasksHtmx = '1';
        document.addEventListener('htmx:afterSettle', function (evt) {
            var api = window.AdhocTasks;
            if (api && typeof api.initAll === 'function') {
                api.initAll((evt && evt.target) || document);
            }
        });
    }

    window.AdhocTasks = { initAll: initAll };
})();
