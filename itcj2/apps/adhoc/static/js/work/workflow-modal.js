/**
 * work/workflow-modal.js — el modal de workflow de una tarea, COMPARTIDO.
 *
 * Expone SOLO `window.AdhocWorkflowModal` (IIFE, sin globales sueltas).
 *
 * De dónde sale
 * -------------
 * Vivía entero dentro de `dashboard/dashboard.js`, que es la landing y la única
 * pantalla que lo abría. Como el tablero solo lista las tareas ABIERTAS del
 * usuario (`get_dashboard_tasks`), el hilo de una tarea ya cerrada no se podía
 * leer desde ninguna URL de la app: 930 de los 1098 comentarios del SGC —el
 * 85 %, diez años de cómo se resolvió cada no conformidad— eran invisibles.
 * Este archivo es ese modal sacado del tablero, sin copiarlo: dashboard.js pasa
 * a CONSUMIRLO, y las listas de tareas de una incidencia o de un evento lo
 * abren desde el contador de la columna "Comentarios".
 *
 * Los dos modos
 * -------------
 *   'completo'  — el del tablero: hilo, adjuntos, validaciones, caja de
 *                 comentario nuevo y las tres acciones de flujo.
 *   'lectura'   — el de las listas de tareas: hilo, adjuntos y validaciones.
 *                 SIN caja de comentario y SIN acciones, también cuando la
 *                 tarea sigue abierta. Es el modo por DEFECTO: quien no declara
 *                 nada obtiene el que no puede tocar el SGC.
 *
 * El modo se consulta en UN solo sitio (`isFull()`) y decide tres cosas: qué
 * rótulo lleva el diálogo, qué controles se esconden (`applyMode`) y qué
 * entradas se rechazan (`saveComment` / `runAction` salen antes de tiempo, por
 * si alguien alcanza un botón que la pantalla no debería estar ofreciendo).
 *
 * API
 * ---
 *   AdhocWorkflowModal.open(taskId, {
 *       mode:     AdhocWorkflowModal.MODE_FULL | MODE_READ,   // def. MODE_READ
 *       status:   'Pendiente',        // estatus ya conocido de la fila/tarjeta
 *       onAction: function (accion, body) { … }               // solo MODE_FULL
 *   })                                    → el nodo del modal, o null
 *   AdhocWorkflowModal.close()
 *   AdhocWorkflowModal.reload()           // vuelve a pedir el hilo abierto
 *   AdhocWorkflowModal.MODE_FULL / MODE_READ
 *
 * `status` solo adelanta trabajo: pinta los botones antes de que llegue el
 * payload, y el estatus REAL que devuelve el servidor manda sobre él. `onAction`
 * es lo que el tablero necesitaba y el módulo no puede saber: qué hacer con la
 * pantalla de debajo cuando una acción de flujo se aplica.
 *
 * Requiere en la página: el partial `adhoc/partials/_workflow_modal.html` en su
 * `{% block modals %}` y la hoja `css/work/workflow-modal.css`.
 *
 * API consumida (todas bajo /api/adhoc/v2, resuelto por AdhocUtils.fetchJson):
 *   GET  /tasks/{id}/workflow          → {success, data:{task, parent, comments, approvals}}
 *   POST /tasks/{id}/comments          → multipart {comment, file}
 *   POST /tasks/{id}/workflow-action   → {accion: terminar|rechazar|aprobar}
 *   GET  /documents/{id}/download      → documento del padre
 *   GET  /tasks/comments/{id}/download → adjunto heredado de un comentario (columna `file_path`)
 *   GET  /tasks/comments/files/{id}/download → adjunto de `adhoc_task_comment_files` (0..N por comentario)
 */
(function () {
    'use strict';

    // Guarda de re-ejecucion, y va sobre `window` a proposito.
    //
    // Este modulo lo cargan VARIAS pantallas con el mismo <script id>, asi que
    // idiomorph conserva el nodo al navegar entre ellas y no lo re-ejecuta;
    // pero viniendo de una pantalla que NO lo carga, el <script> entra como
    // nodo nuevo y si se ejecuta otra vez. Sin esta guarda quedarian dos
    // clausuras: la vieja, duenna de los listeners delegados sobre `document`
    // (que sobreviven a todo), y la nueva, publicada en `window` y por tanto la
    // que llamarian tasks.js o dashboard.js. `open()` escribiria el `state` de
    // una y "Guardar Comentario" leeria el de la otra: `state.taskId` a null y
    // el comentario perdido.
    //
    // Con el retorno temprano manda SIEMPRE la primera clausura, que es la de
    // los listeners. Puede hacerlo porque no guarda ninguna referencia a nodos
    // de la pantalla: todo lo busca por id en el momento de usarlo, y el modal
    // es el mismo en las tres plantillas.
    if (window.AdhocWorkflowModal) return;

    var U = window.AdhocUtils;

    var MODAL_ID = 'adhoc-wf-modal';

    /** Modo completo: el del tablero. Todo lo que se puede hacer con la tarea. */
    var MODE_FULL = 'completo';
    /** Modo lectura: el de las listas de tareas. Solo el expediente. */
    var MODE_READ = 'lectura';

    /** Rotulo del dialogo por modo. En lectura no hay nada que "validar". */
    var HEADING_FULL = 'Gestión y Validación de Tarea';
    var HEADING_READ = 'Historial de la Tarea';

    /** Estados en los que se ofrece "¡Terminé esta tarea!". */
    var FINISHABLE = ['Pendiente', 'Rechazada', 'En Proceso'];
    /** Estados en los que se ofrece aprobar / rechazar. */
    var REVIEWABLE = ['En Revisión'];

    /** Texto del bloqueo de un paso anterior del flujo documental. */
    var LOCKED_NOTICE =
        'Documento bloqueado: está en una etapa anterior de revisión. ' +
        'Se habilitará cuando sea el turno de tu área.';

    var PARENT_LABEL = {
        document: 'Documento ISO',
        incident: 'Incidencia',
        program: 'Programa'
    };

    var ACTION_VERB = {
        terminar: 'terminar',
        rechazar: 'rechazar',
        aprobar: 'aprobar y validar'
    };

    var ACTION_VARIANT = {
        terminar: 'success',
        rechazar: 'danger',
        aprobar: 'primary'
    };

    /** Estado del modal abierto. Se reinicia en cada apertura. */
    var state = {
        taskId: null,
        status: null,
        mode: MODE_READ,
        hasComments: false,
        busy: false,
        onAction: null,
        // Testigo de apertura. `openWorkflow` lo incrementa y `loadWorkflow`
        // se queda con el valor que habia al pedir: cuando llega una respuesta
        // sellada con un numero viejo, se tira. Sin el, el reset del DOM es
        // sincrono y correcto pero la carga NO, asi que abrir la fila A,
        // cerrar y abrir la B antes de que responda A pinta el hilo de A —y su
        // `hasComments`— dentro del dialogo rotulado con B. En el tablero hay
        // un punado de tarjetas; en la lista de un expediente hay hasta 684.
        seq: 0
    };


    // ==================== HELPERS DE DOM ====================

    function byId(id) {
        return document.getElementById(id);
    }

    function show(el) {
        if (el) el.classList.remove('d-none');
    }

    function hide(el) {
        if (el) el.classList.add('d-none');
    }

    function setText(id, value) {
        var el = byId(id);
        if (el) el.textContent = (value === null || value === undefined || value === '') ? '—' : String(value);
    }

    function modalEl() {
        return byId(MODAL_ID);
    }

    // ==================== MODO ====================

    /** La ÚNICA lectura del modo. Todo lo demás pregunta aquí. */
    function isFull() {
        return state.mode === MODE_FULL;
    }

    /**
     * Aplica el modo al esqueleto: rótulo y los dos controles que el modo
     * lectura no ofrece nunca.
     *
     * La caja de comentario y las acciones pueden NO estar en el DOM —el
     * partial solo las emite si la página declaró `wf_can_comment` /
     * `wf_can_workflow`—, así que esto esconde lo que exista y no da por hecho
     * nada: el permiso decide si el control se emite, el modo decide si se ve.
     */
    function applyMode() {
        var completo = isFull();

        var heading = document.querySelector('[data-adhoc-wf-heading]');
        if (heading) heading.textContent = completo ? HEADING_FULL : HEADING_READ;

        var nuevo = document.querySelector('[data-adhoc-wf-comment-new]');
        if (nuevo) nuevo.classList.toggle('d-none', !completo);

        var acciones = document.querySelector('[data-adhoc-wf-actions]');
        if (acciones) acciones.classList.toggle('d-none', !completo);
    }

    // ==================== APERTURA DEL MODAL ====================

    /**
     * Abre el modal sobre una tarea.
     * @param {number|string} taskId
     * @param {{mode?:string,status?:string,onAction?:Function}} [opts]
     * @returns {HTMLElement|null} el nodo del modal, o null si la página no lo trae
     */
    function openWorkflow(taskId, opts) {
        var o = opts || {};
        var modal = modalEl();
        if (!modal || !window.bootstrap || !window.bootstrap.Modal) return null;

        state.taskId = taskId;
        state.seq += 1;
        // Cualquier valor que no sea exactamente 'completo' cae en lectura: el
        // modo que no puede tocar el SGC es el que se obtiene por descuido.
        state.mode = (o.mode === MODE_FULL) ? MODE_FULL : MODE_READ;
        state.status = o.status || null;
        state.hasComments = false;
        state.busy = false;
        state.onAction = (typeof o.onAction === 'function') ? o.onAction : null;

        applyMode();

        // Estado inicial "cargando": nada de datos viejos del modal anterior.
        setText('adhoc-wf-parent-type', 'Cargando…');
        setText('adhoc-wf-title', 'Cargando tarea…');
        ['adhoc-wf-assignees', 'adhoc-wf-start', 'adhoc-wf-due', 'adhoc-wf-status']
            .forEach(function (id) { setText(id, '…'); });

        var parent = byId('adhoc-wf-parent');
        if (parent) {
            parent.innerHTML = '';
            hide(parent);
        }
        setParentToggle(false);

        var approvals = byId('adhoc-wf-approvals');
        if (approvals) {
            approvals.innerHTML = '';
            hide(approvals);
        }

        var tbody = byId('adhoc-wf-comments');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="3" class="adhoc-wf-muted">Consultando historial…</td></tr>';
        }

        resetCommentForm();
        hideNotice();
        renderActionButtons(state.status);

        // El aviso del paso bloqueado habla de cuándo te tocará ACTUAR, así que
        // en modo lectura no tiene destinatario.
        if (isFull() && state.status === 'En Espera') {
            showNotice(LOCKED_NOTICE, 'warning');
        }

        window.bootstrap.Modal.getOrCreateInstance(modal).show();
        loadWorkflow();
        return modal;
    }

    function closeModal() {
        var modal = modalEl();
        if (!modal || !window.bootstrap || !window.bootstrap.Modal) return;
        var instance = window.bootstrap.Modal.getInstance(modal);
        if (instance) instance.hide();
    }

    // ==================== CARGA DE DATOS ====================

    /**
     * Trae el detalle de la tarea abierta y lo pinta.
     *
     * Sellada con `state.seq`: entre la peticion y su respuesta el usuario pudo
     * cerrar el dialogo y abrir otra tarea, y entonces ESTA respuesta ya no es
     * de lo que se esta viendo. El descarte va tambien en el `catch`: pintar
     * "No se pudo cargar la tarea" sobre el hilo recien cargado de otra seria
     * el mismo error al reves. La recarga que hace `saveComment` no toca el
     * testigo, asi que sigue siendo valida.
     */
    async function loadWorkflow() {
        if (!state.taskId) return;
        var mio = state.seq;
        try {
            var body = await U.fetchJson('/tasks/' + encodeURIComponent(state.taskId) + '/workflow');
            if (mio !== state.seq) return;
            var data = (body && body.data) || {};
            renderParent(data.parent || {});
            renderTask(data.task || {});
            renderComments(data.comments || []);
            renderApprovals(data.approvals || [], data.task || {});
        } catch (err) {
            if (mio !== state.seq) return;
            setText('adhoc-wf-title', 'No se pudo cargar la tarea.');
            setText('adhoc-wf-parent-type', 'No disponible');
            var tbody = byId('adhoc-wf-comments');
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="3" class="adhoc-wf-muted">' +
                    U.escapeHtml(err.message) + '</td></tr>';
            }
            U.showToast(err.message, 'error');
        }
    }

    // ==================== RENDER: PADRE ====================

    function cell(label, value, extraClass) {
        return '<div class="adhoc-wf-cell">' +
                 '<dt class="adhoc-wf-label">' + U.escapeHtml(label) + '</dt>' +
                 '<dd class="adhoc-wf-value ' + (extraClass || '') + '">' +
                   U.escapeHtml(value === null || value === undefined || value === '' ? '—' : value) +
                 '</dd>' +
               '</div>';
    }

    function userName(user) {
        return (user && user.name) ? user.name : 'Sistema';
    }

    function renderParent(parent) {
        var box = byId('adhoc-wf-parent');
        if (!box) return;

        var kind = parent.type || null;
        setText('adhoc-wf-parent-type', PARENT_LABEL[kind] || 'Sin origen');

        if (!kind || !parent.id) {
            box.innerHTML = '<p class="adhoc-wf-muted mb-0">Esta tarea no tiene un origen accesible.</p>';
            return;
        }

        var html = '<h6 class="adhoc-wf-parent-title">' + U.escapeHtml(parent.title || 'Sin título');
        if (kind === 'document' && parent.version) {
            html += ' <span class="adhoc-wf-version">v' + U.escapeHtml(parent.version) + '</span>';
        }
        html += '</h6><dl class="adhoc-wf-grid">';

        if (kind === 'document') {
            html += cell('Código', parent.code);
            html += cell('Autor (Solicitante)', userName(parent.author));
            html += cell('Paso Actual', parent.step_name, 'is-primary');
            html += cell('Días Límite', parent.step_days === null || parent.step_days === undefined
                ? null : parent.step_days + ' días');
            html += '</dl>';
            if (parent.has_file) {
                html += '<a class="btn btn-sm btn-primary adhoc-wf-download" target="_blank" rel="noopener" href="' +
                    U.escapeHtml(U.API_BASE + '/documents/' + parent.id + '/download') + '">' +
                    '<i class="fa-solid fa-file-pdf"></i> Revisar documento adjunto</a>';
            }
        } else {
            html += cell('Folio', parent.folio);
            html += cell('Área', parent.area);
            html += cell('Proceso', parent.process);
            html += cell('Validador', userName(parent.responsible));
            html += cell('Compromiso', parent.commitment_date);
            html += cell('Estatus', parent.status);
            html += '</dl>';
        }

        box.innerHTML = html;
    }

    function setParentToggle(open) {
        var btn = document.querySelector('[data-adhoc-wf-parent-toggle]');
        var icon = byId('adhoc-wf-parent-icon');
        if (btn) btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        if (icon) icon.className = open ? 'fa-solid fa-chevron-up' : 'fa-solid fa-chevron-down';
    }

    function toggleParent() {
        var box = byId('adhoc-wf-parent');
        if (!box) return;
        var willOpen = box.classList.contains('d-none');
        box.classList.toggle('d-none', !willOpen);
        setParentToggle(willOpen);
    }

    // ==================== RENDER: TAREA ====================

    function renderTask(task) {
        setText('adhoc-wf-title', task.description || 'Sin descripción');
        setText('adhoc-wf-start', task.start_date);
        setText('adhoc-wf-due', task.due_date);
        setText('adhoc-wf-status', task.status);

        var names = (task.assignees || []).map(function (u) { return userName(u); });
        setText('adhoc-wf-assignees', names.length ? names.join(', ') : 'Sin responsables');

        // El estatus real manda sobre el que traía la tarjeta: entre la carga
        // de la página y la apertura del modal la tarea pudo avanzar.
        if (task.status && task.status !== state.status) {
            state.status = task.status;
            renderActionButtons(task.status);
            if (isFull() && task.status === 'En Espera') showNotice(LOCKED_NOTICE, 'warning');
        }
    }

    function renderApprovals(approvals, task) {
        var box = byId('adhoc-wf-approvals');
        if (!box) return;

        var total = (task.assignees || []).length;
        if (!approvals.length && (!task.document_id || total < 2)) {
            box.innerHTML = '';
            hide(box);
            return;
        }

        var aprobados = approvals.filter(function (a) { return a.decision === 'aprobado'; });
        var html = '<p class="adhoc-wf-approvals-head">' +
            '<i class="fa-solid fa-clipboard-check"></i> Validaciones: ' +
            U.escapeHtml(aprobados.length + ' de ' + total) + '</p><ul class="adhoc-wf-approvals-list">';

        approvals.forEach(function (a) {
            var ok = a.decision === 'aprobado';
            html += '<li class="adhoc-wf-approval' + (ok ? ' is-ok' : ' is-ko') + '">' +
                '<i class="fa-solid ' + (ok ? 'fa-circle-check' : 'fa-circle-xmark') + '"></i> ' +
                U.escapeHtml(userName(a.user)) +
                ' <span class="adhoc-wf-muted">' + U.escapeHtml(a.created_at || '') + '</span>' +
                '</li>';
        });
        html += '</ul>';

        box.innerHTML = html;
        show(box);
    }

    // ==================== RENDER: COMENTARIOS ====================

    /**
     * Enlaces de descarga de un comentario, uniendo las dos fuentes de
     * adjunto: `files` (0..N, `adhoc_task_comment_files`) y el `file_path`
     * heredado (el único que sigue escribiendo el formulario de comentario).
     * Un adjunto migrado sin binario (`is_available: false`) se lista sin
     * enlace, en vez de ofrecer una descarga que va a dar 404.
     */
    function renderAttachments(c) {
        var pedazos = [];

        (c.files || []).forEach(function (f) {
            if (!f.is_available) {
                pedazos.push(
                    '<span class="adhoc-wf-muted" title="El archivo ya no está disponible">' +
                    '<i class="fa-solid fa-file-circle-xmark"></i> ' +
                    U.escapeHtml(f.original_name || 'Archivo') + '</span>'
                );
                return;
            }
            pedazos.push(
                '<a class="btn btn-sm btn-outline-secondary" target="_blank" rel="noopener" href="' +
                U.escapeHtml(U.API_BASE + '/tasks/comments/files/' + f.id + '/download') + '">' +
                '<i class="fa-solid fa-download"></i> ' + U.escapeHtml(f.original_name || 'Descargar') + '</a>'
            );
        });

        if (c.file_path) {
            pedazos.push(
                '<a class="btn btn-sm btn-outline-secondary" target="_blank" rel="noopener" href="' +
                U.escapeHtml(U.API_BASE + '/tasks/comments/' + c.id + '/download') + '">' +
                '<i class="fa-solid fa-download"></i> ' + U.escapeHtml(c.file_name || 'Descargar') + '</a>'
            );
        }

        if (!pedazos.length) {
            return '<span class="adhoc-wf-muted">Sin adjuntos</span>';
        }
        return pedazos.join(' ');
    }

    function renderComments(comments) {
        var tbody = byId('adhoc-wf-comments');
        state.hasComments = comments.length > 0;
        if (!tbody) return;

        if (!comments.length) {
            tbody.innerHTML = '<tr><td colspan="3" class="adhoc-wf-muted">' +
                'Aún no hay comentarios en esta tarea.</td></tr>';
            return;
        }

        var html = '';
        comments.forEach(function (c) {
            var adjunto = renderAttachments(c);
            html += '<tr>' +
                '<td class="adhoc-wf-date">' + U.escapeHtml(c.created_at || '') + '</td>' +
                '<td><span class="adhoc-wf-author">' + U.escapeHtml(userName(c.user)) + ':</span><br>' +
                U.escapeHtml(c.comment || '') + '</td>' +
                '<td class="adhoc-col-center">' + adjunto + '</td>' +
                '</tr>';
        });
        tbody.innerHTML = html;
    }

    // ==================== COMENTARIO NUEVO ====================

    function resetCommentForm() {
        var form = byId('adhoc-wf-comment-form');
        var text = byId('adhoc-wf-comment-text');
        var file = byId('adhoc-wf-comment-file');
        if (text) text.value = '';
        if (file) file.value = '';
        hide(form);
    }

    function openCommentForm() {
        if (!isFull()) return;
        var form = byId('adhoc-wf-comment-form');
        if (!form) return;
        show(form);
        var text = byId('adhoc-wf-comment-text');
        if (text) text.focus();
    }

    async function saveComment(btn) {
        if (!isFull()) return;

        var text = byId('adhoc-wf-comment-text');
        var file = byId('adhoc-wf-comment-file');
        var value = text ? text.value.trim() : '';

        if (!value) {
            U.showToast('Debes escribir un comentario.', 'warning');
            if (text) text.focus();
            return;
        }
        if (state.busy) return;

        var data = new FormData();
        data.append('comment', value);
        if (file && file.files && file.files[0]) data.append('file', file.files[0]);

        var original = btn.innerHTML;
        state.busy = true;
        btn.disabled = true;
        btn.textContent = 'Guardando…';

        try {
            await U.fetchJson('/tasks/' + encodeURIComponent(state.taskId) + '/comments', {
                method: 'POST',
                body: data
            });
            resetCommentForm();
            hideNotice();
            U.showToast('Comentario agregado.', 'success');
            await loadWorkflow();
        } catch (err) {
            U.showToast(err.message, 'error');
        } finally {
            state.busy = false;
            btn.disabled = false;
            btn.innerHTML = original;
        }
    }

    // ==================== ACCIONES DE WORKFLOW ====================

    function renderActionButtons(status) {
        var completo = isFull();
        document.querySelectorAll('[data-adhoc-wf-action]').forEach(function (btn) {
            var accion = btn.getAttribute('data-adhoc-wf-action');
            var visible = completo && ((accion === 'terminar')
                ? FINISHABLE.indexOf(status) !== -1
                : REVIEWABLE.indexOf(status) !== -1);
            btn.classList.toggle('d-none', !visible);
            btn.disabled = false;
        });
    }

    function showNotice(message, tone) {
        var el = byId('adhoc-wf-notice');
        if (!el) return;
        el.textContent = message;
        el.classList.remove('is-warning', 'is-danger');
        el.classList.add(tone === 'danger' ? 'is-danger' : 'is-warning');
        show(el);
    }

    function hideNotice() {
        var el = byId('adhoc-wf-notice');
        if (!el) return;
        el.textContent = '';
        hide(el);
    }

    async function runAction(accion, btn) {
        if (!isFull() || state.busy || !state.taskId) return;

        // Regla de calidad del SGC: sin comentario no hay acción. El servidor
        // responde 400 igualmente (task_workflow_service), pero avisar antes
        // ahorra el viaje y deja el foco donde toca.
        if (!state.hasComments) {
            showNotice(
                'Regla de calidad: es obligatorio guardar un comentario antes de ' +
                (ACTION_VERB[accion] || accion) + ' la tarea.',
                'danger'
            );
            openCommentForm();
            return;
        }

        var ok = await U.confirmDialog({
            title: 'Confirmar acción',
            message: '¿Seguro que deseas ' + (ACTION_VERB[accion] || accion) + ' esta tarea?',
            confirmText: 'Sí, continuar',
            variant: ACTION_VARIANT[accion] || 'primary'
        });
        if (!ok) return;

        state.busy = true;
        if (btn) btn.disabled = true;

        try {
            var body = await U.fetchJson('/tasks/' + encodeURIComponent(state.taskId) + '/workflow-action', {
                method: 'POST',
                body: JSON.stringify({ accion: accion })
            });
            closeModal();
            U.showToast((body && body.message) || 'Acción procesada exitosamente.', 'success');
            // Qué hacer con la pantalla de debajo es de la pantalla, no del
            // modal: el tablero se repinta y una lista de tareas recarga su
            // tabla. Por eso sale por `onAction` en vez de que el módulo mire
            // en qué URL está.
            if (state.onAction) state.onAction(accion, body);
        } catch (err) {
            U.showToast(err.message, 'error');
            state.busy = false;
            if (btn) btn.disabled = false;
        }
    }

    // ==================== CABLEADO ====================

    function onDocumentClick(evt) {
        var target = evt.target;
        if (!target || typeof target.closest !== 'function') return;

        if (target.closest('[data-adhoc-wf-parent-toggle]')) {
            toggleParent();
            return;
        }

        if (target.closest('[data-adhoc-wf-comment-new]')) {
            openCommentForm();
            return;
        }

        var save = target.closest('[data-adhoc-wf-comment-save]');
        if (save) {
            saveComment(save);
            return;
        }

        var action = target.closest('[data-adhoc-wf-action]');
        if (action) {
            runAction(action.getAttribute('data-adhoc-wf-action'), action);
        }
    }

    function init() {
        // La guarda va en <html>, NO en una variable de modulo: este archivo
        // puede volver a ejecutarse al navegar (idiomorph retira su <script> al
        // salir de las pantallas que lo cargan y lo inserta al volver), y una
        // variable de modulo arranca en false cada vez. Los listeners se
        // acumulaban sobre `document`, que sobrevive a todo, y con dos copias de
        // `onDocumentClick` la guarda `state.busy` deja de servir: un clic en
        // "Aprobar" abria dos dialogos y mandaba DOS POST de flujo sobre la
        // misma tarea del SGC.
        //
        // <html> es el unico nodo que ni el morph ni una navegacion boosted
        // tocan. Es el mismo patron de work-items.js, tasks.js y assignments.js.
        // (Aqui hace ademas de segundo cinturon: el retorno temprano del
        // principio del archivo ya impide la segunda ejecucion.)
        if (document.documentElement.dataset.adhocWfModalBound === '1') return;
        document.documentElement.dataset.adhocWfModalBound = '1';

        // Delegación en `document`: el morph de HTMX puede reemplazar el modal
        // entero sin que haya que reenganchar nada.
        document.addEventListener('click', onDocumentClick);
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(init);
    }

    window.AdhocWorkflowModal = {
        open: openWorkflow,
        close: closeModal,
        reload: loadWorkflow,
        MODE_FULL: MODE_FULL,
        MODE_READ: MODE_READ
    };
})();
