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
 *  · La columna "Notas" pintaba un contador MUERTO: el hilo de la tarea solo se
 *    podía abrir desde el tablero, que únicamente lista las tareas abiertas del
 *    usuario → el contador es ahora el botón que abre el hilo en modo lectura.
 *
 * Requiere en la página (ver `commentsControl`): el partial
 * `adhoc/partials/_workflow_modal.html` en su `{% block modals %}`, la hoja
 * `css/work/workflow-modal.css` y el `<script id="adhoc-mod-work-workflow-modal">`
 * cargado ANTES que este módulo.
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

        tr.appendChild(this.clampCell('description', task.description || ''));

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
        tdComments.appendChild(this.commentsControl(task));
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

    /**
     * <td> con el texto acotado a 2 lineas.
     *
     * El clamp va en un hijo bloque porque un <td> no acepta
     * `display:-webkit-box`. Aqui el alto de fila lo fija la columna Acciones
     * (63px), asi que sin el hijo el `overflow:hidden` cortaba la descripcion
     * A MEDIA LETRA en la tercera linea y se perdian las siguientes sin
     * elipsis. Son descripciones de hasta 255 caracteres.
     */
    Tasks.prototype.clampCell = function (key, text) {
        var td = this.cell(key, '', 'adhoc-cell-clamp');
        var box = el('div', 'adhoc-clamp-text');
        box.textContent = text;
        if (text) td.title = text;
        td.appendChild(box);
        return td;
    };

    /**
     * Columna "Notas": el contador de comentarios, que desde aqui es la UNICA
     * puerta al hilo de la tarea.
     *
     * Hasta ahora era una pastilla muerta. El unico visor del hilo era el modal
     * del tablero, y el tablero solo lista las tareas ABIERTAS del usuario, asi
     * que los 930 comentarios que cuelgan de tareas ya cerradas —el 85 % del
     * historico del SGC, diez anios de como se resolvio cada no conformidad— no
     * se podian leer desde ninguna URL. La pastilla pasa a abrir ese mismo
     * modal en modo LECTURA: hilo, adjuntos y validaciones, sin caja de
     * comentario y sin acciones de flujo aunque la tarea siga abierta.
     *
     * Tres estados, y los tres dicen algo distinto:
     *
     *  · SIN comentarios → un guion, como las fechas vacias de esta misma fila
     *    y como la columna "Archivos" de programas cuando no hay nada que
     *    ofrecer. Un boton que abre un hilo vacio es peor que no tenerlo, y una
     *    pastilla apagada con un «0» se veria IGUAL que la del tercer caso: dos
     *    cosas distintas con el mismo dibujo. El guion dice "no hay nada"; la
     *    pastilla apagada, "hay algo que tu no alcanzas".
     *  · Con comentarios y alcanzables → un <button> de verdad, no un <span>
     *    con listener: se llega con el tabulador y responde a Enter.
     *  · Con comentarios FUERA de alcance → la misma pastilla, apagada y sin
     *    envolver, con un title que explica por que. Sigue siendo un `<span>`
     *    y no un `<button disabled>` porque ese title es lo unico que el
     *    estado apagado tiene que decir, y los navegadores no muestran el
     *    tooltip de un control deshabilitado. Que no abra nada al pulsarlo lo
     *    garantiza el guard de `.adhoc-count-off` en `bind()`.
     *
     * `thread_readable` lo calcula `puede_leer_hilo()` en el servidor, la MISMA
     * funcion con la que `GET /tasks/{id}/workflow` decide su 403: por eso esta
     * fila no puede ofrecer un boton que acabe en un error. `undefined` —un
     * payload serializado sin contexto de actor— es falso, asi que el defecto
     * es apagar. El estado apagado es el del rol `consult`, que carga esta
     * lista con `adhoc.tasks.api.read.own` y solo alcanza los hilos de las
     * tareas en las que participa.
     */
    Tasks.prototype.commentsControl = function (task) {
        var count = task.comments_count || 0;
        if (!count) return document.createTextNode('—');

        var plural = count === 1 ? 'comentario' : 'comentarios';

        if (!task.thread_readable) {
            var off = el('span', 'adhoc-count-pill adhoc-count-off', String(count));
            off.setAttribute('title', count + ' ' + plural + '. Solo puedes abrir el ' +
                'historial de las tareas en las que participas.');
            return off;
        }

        var label = 'Ver ' +
            (count === 1 ? 'el comentario' : 'los ' + count + ' comentarios') +
            ' de esta tarea';
        var btn = el('button', 'adhoc-count-btn');
        btn.type = 'button';
        btn.setAttribute('data-adhoc-task-action', 'thread');
        btn.setAttribute('title', label);
        btn.setAttribute('aria-label', label);
        btn.appendChild(el('span', 'adhoc-count-pill', String(count)));
        return btn;
    };

    /**
     * Abre el hilo de la tarea en el modal compartido, en modo LECTURA.
     *
     * El modo va explicito aunque `MODE_READ` sea el defecto del modulo: el
     * unico modo que puede tocar el SGC es el otro, y aqui se lee en la llamada
     * cual de los dos se pidio. `status` solo adelanta trabajo (el estatus real
     * del servidor manda sobre el) y no se pasa `onAction`: en lectura no hay
     * accion que aplicar ni tabla que recargar.
     */
    Tasks.prototype.openThread = function (task) {
        var wf = window.AdhocWorkflowModal;
        // `open()` devuelve el nodo del dialogo, o null si la pantalla no trae
        // el partial. Sin ese aviso el boton se quedaria mudo.
        var abierto = wf ? wf.open(task.id, { mode: wf.MODE_READ, status: task.status }) : null;
        if (!abierto) toast('No se pudo abrir el historial de la tarea.', 'error');
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
        U.navigate(base +
            '?action=' + encodeURIComponent(action) +
            '&task_id=' + encodeURIComponent(task.id) +
            '&return_to=' + encodeURIComponent(back));
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
                if (name === 'thread') self.openThread(task);
                else if (name === 'edit') self.openEdit(task);
                else if (name === 'delete') self.remove(task);
                else if (name === 'assign') self.goToAssign(task, 'assign');
                else if (name === 'notify') self.goToAssign(task, 'notify');
                return;
            }

            // El contador APAGADO es un `<span>`, no un control: sin
            // `data-adhoc-task-action` el clic seguia de largo hasta el atajo
            // de fila de abajo y abria el modal de EDICION. O sea que la
            // pastilla que dice "solo puedes abrir el historial de las tareas
            // en las que participas", con su cursor de ayuda, terminaba
            // abriendo el formulario de la tarea.
            //
            // Se queda como `<span>` a proposito: un `<button disabled>` no
            // despacharia el clic, pero los navegadores tampoco muestran el
            // `title` de un control deshabilitado, y ese texto es TODO lo que
            // esa pastilla tiene que decir. Asi que el control se queda inerte
            // por markup y aqui se le corta el paso al atajo.
            if (evt.target.closest('.adhoc-count-off')) return;

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
