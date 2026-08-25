/**
 * dashboard.js — tablero de tareas de Calidad y modal de workflow.
 *
 * Sustituye a las 260 líneas de <script> inline de
 * templates/app_prueba/dashboard/dashboard.html, que dejaba 4 variables y 10
 * funciones sueltas en el scope global (abrirModalWorkflow, cargarDatosWorkflow,
 * guardarComentario, pedirConfirmacion, procesarWorkflow, mostrarAlerta,
 * mostrarConfirmacion, cerrarModal…), todas invocadas desde onclick= inline.
 *
 * Aquí: IIFE, un solo símbolo global (window.AdhocDashboard), listeners
 * delegados en document, bootstrap.Modal en vez de .modal-overlay con
 * style.display, AdhocUtils.confirmDialog() en vez de los dos modales caseros
 * de confirmación/alerta, y AdhocUtils.escapeHtml() en TODO dato del servidor
 * (el legacy volcaba ${c.texto} y ${c.usuario} crudos a innerHTML: XSS
 * almacenado, dashboard.html:395).
 *
 * API consumida (todas bajo /api/adhoc/v2, resuelto por AdhocUtils.fetchJson):
 *   GET  /tasks/{id}/workflow          → {success, data:{task, parent, comments, approvals}}
 *   POST /tasks/{id}/comments          → multipart {comment, file}
 *   POST /tasks/{id}/workflow-action   → {accion: terminar|rechazar|aprobar}
 *   GET  /documents/{id}/download      → documento del padre
 *   GET  /tasks/comments/{id}/download → adjunto de un comentario
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;

    var MODAL_ID = 'adhoc-wf-modal';

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
    var state = { taskId: null, status: null, hasComments: false, busy: false };

    var wired = false;

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

    function config() {
        return U.pageData();
    }

    // ==================== APERTURA DEL MODAL ====================

    function openWorkflow(taskId, status) {
        var modal = modalEl();
        if (!modal || !window.bootstrap || !window.bootstrap.Modal) return;

        state.taskId = taskId;
        state.status = status;
        state.hasComments = false;
        state.busy = false;

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
        renderActionButtons(status);

        if (status === 'En Espera') {
            showNotice(LOCKED_NOTICE, 'warning');
        }

        window.bootstrap.Modal.getOrCreateInstance(modal).show();
        loadWorkflow();
    }

    function closeModal() {
        var modal = modalEl();
        if (!modal || !window.bootstrap || !window.bootstrap.Modal) return;
        var instance = window.bootstrap.Modal.getInstance(modal);
        if (instance) instance.hide();
    }

    // ==================== CARGA DE DATOS ====================

    async function loadWorkflow() {
        if (!state.taskId) return;
        try {
            var body = await U.fetchJson('/tasks/' + encodeURIComponent(state.taskId) + '/workflow');
            var data = (body && body.data) || {};
            renderParent(data.parent || {});
            renderTask(data.task || {});
            renderComments(data.comments || []);
            renderApprovals(data.approvals || [], data.task || {});
        } catch (err) {
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
            if (task.status === 'En Espera') showNotice(LOCKED_NOTICE, 'warning');
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
            var adjunto = '<span class="adhoc-wf-muted">Sin adjuntos</span>';
            if (c.file_path) {
                adjunto = '<a class="btn btn-sm btn-outline-secondary" target="_blank" rel="noopener" href="' +
                    U.escapeHtml(U.API_BASE + '/tasks/comments/' + c.id + '/download') + '">' +
                    '<i class="fa-solid fa-download"></i> ' + U.escapeHtml(c.file_name || 'Descargar') + '</a>';
            }
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
        var form = byId('adhoc-wf-comment-form');
        if (!form) return;
        show(form);
        var text = byId('adhoc-wf-comment-text');
        if (text) text.focus();
    }

    async function saveComment(btn) {
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
        document.querySelectorAll('[data-adhoc-wf-action]').forEach(function (btn) {
            var accion = btn.getAttribute('data-adhoc-wf-action');
            var visible = (accion === 'terminar')
                ? FINISHABLE.indexOf(status) !== -1
                : REVIEWABLE.indexOf(status) !== -1;
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
        if (state.busy || !state.taskId) return;

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
            // El tablero se arma server-side: recargar es la forma más simple y
            // barata de reflejar el nuevo estado de la tarea y de su padre.
            setTimeout(function () { window.location.reload(); }, 1200);
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

        var card = target.closest('[data-adhoc-task]');
        if (card) {
            openWorkflow(card.getAttribute('data-adhoc-task'),
                         card.getAttribute('data-adhoc-task-status'));
            return;
        }

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

    function onDocumentKeydown(evt) {
        if (evt.key !== 'Enter' && evt.key !== ' ') return;
        var target = evt.target;
        if (!target || typeof target.closest !== 'function') return;
        var card = target.closest('[data-adhoc-task]');
        if (!card) return;
        evt.preventDefault();
        openWorkflow(card.getAttribute('data-adhoc-task'),
                     card.getAttribute('data-adhoc-task-status'));
    }

    function init() {
        if (wired) return;
        wired = true;
        // Delegación en `document`: el morph de HTMX puede reemplazar tanto las
        // tarjetas como el modal sin que haya que reenganchar nada.
        document.addEventListener('click', onDocumentClick);
        document.addEventListener('keydown', onDocumentKeydown);
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(init);
    }

    window.AdhocDashboard = {
        open: openWorkflow,
        reload: loadWorkflow,
        config: config
    };
})();
