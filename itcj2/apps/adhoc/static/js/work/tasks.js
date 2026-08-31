/**
 * work/tasks.js — tareas de una incidencia, de un evento de programa O de un
 * documento.
 *
 * Expone SOLO `window.AdhocTasks` (IIFE, sin globales sueltas).
 *
 * UN SOLO módulo para las TRES pantallas, como el template: lo que cambia
 * (`parent_type`, `parent_id`, a dónde vuelve el botón "Volver", si hay columna
 * "Paso") llega en `page_data`. El legacy también compartía el JS
 * —`incidents/tasks.js`, clase global `TareasExpedienteManager`— pero la URL de
 * asignación se decidía en el TEMPLATE con un `{% set ruta_base = ... %}` y
 * viajaba en `data-url` por fila.
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
 * QUÉ AÑADE B4 (pantalla de documento)
 * ------------------------------------
 *  · Columna "Paso": el nombre y el orden del paso del flujo al que pertenece
 *    cada tarea. Es lo que convierte esta lista en "el avance del documento por
 *    pasos" en vez de nueve tareas sueltas. Solo en documentos, porque solo sus
 *    tareas cuelgan de un `flow_step`.
 *  · Aviso de atasco: una tarea de aprobación cuyos responsables ya no pueden
 *    entrar a Calidad no la puede atender nadie, y el documento se queda a
 *    medias sin que nada lo diga. Es el caso vivo del documento 202: su tarea
 *    del paso 1 tiene un solo responsable y ese responsable no entra.
 *    Quién tiene acceso lo calcula el SERVIDOR (`assignees_without_access`, con
 *    el MISMO `users_with_assignment_select` que llena el desplegable de
 *    asignación): aquí no se vuelve a decidir, solo se pinta.
 *
 * QUÉ CAMBIA B5 (el aviso, en las tres pantallas)
 * -----------------------------------------------
 *  · El aviso deja de ser cosa de la pantalla de documento. Son 57 las tareas
 *    abiertas sin un solo responsable que pueda entrar a la app, y 56 cuelgan
 *    de una incidencia o de un evento: las dos pantallas que se callaban.
 *  · CUÁNDO se pinta ya no se decide aquí. Las tres reglas —si esta pantalla
 *    lo lleva, en qué estados tiene sentido y si perder a algunos ya para la
 *    tarea— llegan en `page_data` desde `pages/_work_context.py`
 *    (`show_access_warning`, `unfinished_statuses`, `all_assignees_required`),
 *    que es donde ya viven el vocabulario de estados y la máquina de flujo.
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

    /**
     * `['a','b']` → `{a: true, b: true}`, para consultar por estatus sin
     * recorrer. Sin prototipo: con `{}` la consulta por una clave heredada
     * ('constructor', 'toString') saldria verdadera. Hoy el estatus viene de un
     * CheckConstraint y no puede valer eso, pero el helper no tiene por que
     * saberlo.
     */
    function asSet(list) {
        var out = Object.create(null);
        var items = list || [];
        for (var i = 0; i < items.length; i++) out[items[i]] = true;
        return out;
    }

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

        //: Columna "Paso". La decide el SERVIDOR
        //: (`_work_context.tasks_page_context`), igual que la plantilla, y por
        //: eso no se lee aqui `parent_type === 'document'`: la plantilla emite
        //: los <th> a partir de la misma bandera, asi que encabezado y celdas
        //: no pueden descuadrarse.
        this.showStep = !!this.data.show_step_column;

        //: Aviso de atasco: las TRES reglas las manda el servidor
        //: (`_work_context.tasks_page_context`), igual que la columna "Paso".
        //: Aqui no se mira `parent_type` para ninguna de ellas.
        //:
        //:  · `show_access_warning` — si esta pantalla lleva el aviso.
        //:  · `unfinished_statuses` — los estatus en los que la tarea todavia
        //:    espera a alguien. Es el criterio de ruido: una 'Completada' cuyo
        //:    responsable ya se fue del Tec no esta atascada, esta hecha, y hay
        //:    184 asi —pintarlas ahogaria las 57 reales—.
        //:  · `all_assignees_required` — si perder a ALGUNOS ya para la tarea.
        //:
        //: Sin las claves el aviso se calla, que es el mismo defecto honesto
        //: que ya tiene `assignees_without_access` cuando el API no la emite:
        //: callarse no afirma nada; encenderse sin saber, si.
        this.showAccessWarning = !!this.data.show_access_warning;
        this.unfinishedStatuses = asSet(this.data.unfinished_statuses);
        this.allAssigneesRequired = !!this.data.all_assignees_required;

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

        // El <td> del paso va JUSTO detras de la descripcion, en la misma
        // posicion en que la plantilla emite su <th>. Las dos salen de
        // `show_step_column`, asi que o estan las dos o no esta ninguna: son
        // 9 celdas en incidencias y programas, 10 en documentos.
        if (this.showStep) tr.appendChild(this.stepCell(task));

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
     * Columna "Paso" — solo en la pantalla de un documento.
     *
     * Es lo que convierte esta lista en el AVANCE del documento: las tareas de
     * aprobacion se crean todas de golpe al arrancar el flujo (una por paso,
     * la primera 'En Revision' y el resto 'En Espera'), asi que sin el paso la
     * pantalla es un monton de filas casi identicas y no se ve por donde va.
     *
     * `flow_step` lo emite `serialize_task` SIEMPRE, tambien como `null`, y ese
     * null es informacion, no un hueco: una tarea de documento sin paso existe
     * de verdad —la de correccion que se crea al rechazar ("Corregir Documento
     * Rechazado: …"), o cualquiera dada de alta a mano desde esta misma
     * pantalla— y no pertenece al flujo de aprobacion. Por eso dice "Fuera del
     * flujo" y no un guion: un guion se lee como "no hay dato".
     *
     * Y por eso mismo NO usa `.adhoc-muted-cell`, que es el gris de placeholder
     * de "Sin asignar" (`--adhoc-disabled`, 1.9:1 sobre la tarjeta): si el
     * texto es informacion, tiene que leerse. Va con su propia clase en el gris
     * de texto atenuado, el mismo del contador apagado de esta pantalla.
     */
    Tasks.prototype.stepCell = function (task) {
        var step = task.flow_step;

        if (!step) {
            var vacio = this.cell('flow_step', 'Fuera del flujo', 'adhoc-step-empty');
            vacio.title = 'Esta tarea cuelga del documento pero no de un paso de ' +
                'su flujo de aprobación: se dio de alta a mano o es la tarea de ' +
                'corrección de un rechazo.';
            return vacio;
        }

        var nombre = step.name || ('Paso #' + step.id);
        var orden = (typeof step.step_order === 'number') ? step.step_order : null;
        var td = this.cell('flow_step', '');

        // El numero de orden va en su propio <span> para poder atenuarlo, pero
        // dentro de la MISMA celda: el filtro de la columna lee el textContent
        // completo, asi que teclear "2" o "Autorizacion" encuentra lo mismo.
        if (orden !== null) td.appendChild(el('span', 'adhoc-step-order', orden + '.'));
        td.appendChild(document.createTextNode(orden !== null ? ' ' + nombre : nombre));
        td.title = td.textContent;
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

    /**
     * Aviso de ATASCO: los responsables de esta tarea no pueden entrar a la app.
     *
     * El SGC arranca el flujo de un documento copiando los validadores del paso
     * a los asignados de la tarea —un snapshot deliberado—, asi que si a esa
     * persona le quitan el acceso a Calidad despues, la tarea se queda sin nadie
     * que pueda abrirla y el documento se para en ese paso para siempre. Nada lo
     * decia: la tarea seguia diciendo "En Revision", que es exactamente lo que
     * pasa con la tarea 683 del documento 202.
     *
     * DOS ESTADOS, porque no significan lo mismo:
     *
     *  · TODOS los asignados sin acceso → la tarea esta parada de verdad; no
     *    hay nadie que pueda aprobarla y el flujo no avanza solo. Tono de
     *    peligro, rotulo "Bloqueada". Vale para los tres padres.
     *  · ALGUNOS → degradado, y SOLO donde `all_assignees_required`: la
     *    aprobacion de un documento exige que aprueben TODOS los asignados
     *    (`_record_decision` cuenta contra `len(assignees)`), asi que con uno de
     *    dos fuera tampoco se completa el paso, pero el expediente sigue
     *    teniendo quien lo mire. Tono de aviso, con el conteo. En una
     *    incidencia o un evento cualquiera de sus responsables la cierra el
     *    solo, asi que mientras quede uno operativo la tarea NO esta parada:
     *    ahi el caso degradado no se pinta —serian 32 filas afirmando que algo
     *    no va a avanzar cuando si va a avanzar—.
     *
     * Y solo sobre tareas que siguen esperando a alguien
     * (`unfinished_statuses`): una 'Completada' cuyos responsables ya no entran
     * es trabajo terminado por gente que se fue, no un atasco. Son 184 filas;
     * sin ese filtro el aviso saldria en 273 y las 57 paradas de verdad
     * quedarian dentro de la pared de rojo.
     *
     * QUIEN tiene acceso NO se decide aqui. Viene en `assignees_without_access`,
     * que el servidor calcula una vez por peticion con
     * `users_with_assignment_select(db, "adhoc")` —las cuatro vias de
     * `require_app`—, el MISMO criterio con el que se llena el desplegable de
     * `/adhoc/asignaciones`. Si el aviso se calculara aqui con otra regla,
     * podria marcar como inalcanzable a alguien que la pantalla de asignacion si
     * ofrece. La clave puede no venir (un payload serializado sin ese contexto):
     * ausente cuenta como cero y la fila se calla, que es el defecto honesto.
     *
     * El texto dice QUE HACER, y lo que hay que hacer depende de si esta persona
     * puede reasignar: con `can.assign` el boton esta ahi al lado; sin el, lo
     * unico accionable es avisar a quien si puede.
     *
     * ACCESIBILIDAD: no es un control —no se pulsa, no recibe foco—, asi que
     * `role="img"` + `aria-label` es lo que hace que un lector de pantalla lea
     * la frase entera en vez de deletrear "Bloqueada"; el `title` es la misma
     * frase para quien pasa el raton. El icono va `aria-hidden`. Que al
     * pulsarlo no pase NADA lo garantiza el guard de `.adhoc-task-stuck` en
     * `bind()`: sin el, este `<span>` sin `data-adhoc-task-action` caia en el
     * atajo de fila y abria el modal de edicion de la tarea, que es justo el
     * fallo que ese guard ya arreglaba para el contador apagado.
     *
     * @returns {HTMLElement|null} null si esta fila no tiene nada que avisar
     */
    Tasks.prototype.stuckNotice = function (task) {
        if (!this.showAccessWarning) return null;
        if (!this.unfinishedStatuses[task.status]) return null;

        var sin = (task.assignees_without_access || []).length;
        if (!sin) return null;

        var total = (task.assignees || []).length;
        var todos = sin >= total;
        // Queda alguien que puede atenderla y con uno basta: no hay atasco.
        if (!todos && !this.allAssigneesRequired) return null;

        var salida = this.can.assign
            ? (todos ? ' Reasígnala con el botón Asignar de esta fila.'
                     : ' Revisa la asignación con el botón Asignar de esta fila.')
            : ' Pide a un supervisor del SGC que revise la asignación.';

        var texto;
        if (todos) {
            texto = (total === 1
                     ? 'Bloqueada: su único responsable no puede entrar a Calidad'
                     : 'Bloqueada: ninguno de sus ' + total +
                       ' responsables puede entrar a Calidad') +
                    ', así que nadie puede atenderla.' + salida;
        } else {
            texto = (sin === 1
                     ? '1 de los ' + total + ' responsables no puede'
                     : sin + ' de los ' + total + ' responsables no pueden') +
                    ' entrar a Calidad. El paso solo se completa cuando aprueban' +
                    ' todos, así que tampoco avanzará.' + salida;
        }

        var aviso = el('span', 'adhoc-task-stuck adhoc-badge ' +
                       (todos ? 'adhoc-badge-danger' : 'adhoc-badge-warning'));
        aviso.setAttribute('role', 'img');
        aviso.setAttribute('title', texto);
        aviso.setAttribute('aria-label', texto);

        var icono = iconEl(todos ? 'fa-solid fa-user-lock' : 'fa-solid fa-user-slash');
        icono.setAttribute('aria-hidden', 'true');
        aviso.appendChild(icono);
        // Rotulo VISIBLE, y distinto en cada estado: los dos casos tienen que
        // distinguirse sin pasar el raton por encima. "Bloqueada" no lleva
        // numero a proposito —con un solo asignado, "1 sin acceso" se veria
        // igual que el caso degradado—.
        aviso.appendChild(el('span', null, todos ? 'Bloqueada' : sin + ' sin acceso'));
        return aviso;
    };

    Tasks.prototype.buildActions = function (task) {
        var box = el('div', 'adhoc-actions');
        // Primero el aviso: es el contexto de los botones que vienen detras, y
        // el primero de ellos es justo el que lo resuelve.
        var atasco = this.stuckNotice(task);
        if (atasco) box.appendChild(atasco);
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

            // Los DOS rotulos inertes de esta fila. Ninguno es un control:
            // son `<span>` sin `data-adhoc-task-action`, asi que el clic seguia
            // de largo hasta el atajo de fila de abajo y abria el modal de
            // EDICION. O sea que la pastilla que dice "solo puedes abrir el
            // historial de las tareas en las que participas" y la que dice
            // "bloqueada: nadie puede atenderla", las dos con su cursor de
            // ayuda, terminaban abriendo el formulario de la tarea.
            //
            // Se quedan como `<span>` a proposito: un `<button disabled>` no
            // despacharia el clic, pero los navegadores tampoco muestran el
            // `title` de un control deshabilitado, y ese texto es TODO lo que
            // tienen que decir. Asi que son inertes por markup y aqui se les
            // corta el paso al atajo. Cualquier rotulo nuevo con `cursor: help`
            // entra en esta lista: prometer un tooltip y abrir un formulario es
            // la peor combinacion posible.
            if (evt.target.closest('.adhoc-count-off, .adhoc-task-stuck')) return;

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
