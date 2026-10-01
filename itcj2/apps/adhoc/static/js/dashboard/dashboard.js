/**
 * dashboard.js — tablero de tareas de Calidad.
 *
 * Sustituye a las 260 líneas de <script> inline de
 * templates/app_prueba/dashboard/dashboard.html, que dejaba 4 variables y 10
 * funciones sueltas en el scope global (abrirModalWorkflow, cargarDatosWorkflow,
 * guardarComentario, pedirConfirmacion, procesarWorkflow, mostrarAlerta,
 * mostrarConfirmacion, cerrarModal…), todas invocadas desde onclick= inline.
 *
 * Aquí: IIFE, un solo símbolo global (window.AdhocDashboard) y listeners
 * delegados en document.
 *
 * QUÉ HACE AHORA ESTE ARCHIVO
 * ---------------------------
 * Solo el tablero: abrir la tarjeta y decidir qué pasa con la pantalla cuando
 * una acción de flujo se aplica. **El modal de workflow ya no vive aquí**: es
 * `work/workflow-modal.js` (`window.AdhocWorkflowModal`), compartido con las
 * listas de tareas de una incidencia y de un evento de programa, que lo abren
 * en modo LECTURA desde el contador de la columna "Comentarios".
 *
 * El motivo del reparto: este modal era el único visor del hilo de una tarea, y
 * el tablero solo lista las tareas ABIERTAS del usuario, así que 930 de los
 * 1098 comentarios del SGC —los que cuelgan de tareas ya completadas— no se
 * podían leer desde ninguna URL. El tablero sigue siendo el que puede ACTUAR:
 * abre el mismo modal en modo COMPLETO y no ha perdido nada.
 *
 * Las tarjetas llegan renderizadas server-side desde pages/dashboard.py; este
 * archivo no pinta ninguna.
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;

    /** Constantes de la página (`{"user_id", "can_workflow", "can_comment"}`). */
    function config() {
        return U.pageData();
    }

    // ==================== APERTURA DEL MODAL ====================

    /**
     * Vuelve a pedir el tablero tras una acción de flujo aplicada.
     *
     * El tablero se arma server-side, así que hay que volver a pedirlo; lo que
     * ya NO se hace es recargar el documento entero. Antes eran 1,2 s mirando
     * el tablero desactualizado y después una recarga completa —volviendo a
     * bajar HTMX, Bootstrap y las fuentes— en la acción más repetida de la app.
     *
     * Los 400 ms son para que dé tiempo a leer el toast antes de que el tablero
     * se repinte debajo; sin ellos, el aviso y el cambio ocurren a la vez y
     * cuesta relacionarlos.
     *
     * Va aquí y no dentro del modal porque es la respuesta de ESTA pantalla:
     * una lista de tareas recarga su tabla y no navega a ningún sitio.
     */
    function reloadBoard() {
        setTimeout(function () { U.navigate(window.location.pathname + window.location.search); }, 400);
    }

    /**
     * Abre el expediente de una tarea del tablero, en modo COMPLETO: comentario
     * nuevo y las tres acciones de flujo, con las reglas de siempre.
     * @param {number|string} taskId
     * @param {string} [status] estatus que traía la tarjeta
     */
    function openWorkflow(taskId, status) {
        var wf = window.AdhocWorkflowModal;
        if (!wf) return;
        wf.open(taskId, {
            mode: wf.MODE_FULL,
            status: status,
            onAction: reloadBoard
        });
    }

    // ==================== CABLEADO ====================

    function onDocumentClick(evt) {
        var target = evt.target;
        if (!target || typeof target.closest !== 'function') return;

        var card = target.closest('[data-adhoc-task]');
        if (!card) return;
        openWorkflow(card.getAttribute('data-adhoc-task'),
                     card.getAttribute('data-adhoc-task-status'));
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
        // La guarda va en <html>, NO en una variable de modulo. Este archivo se
        // ejecuta de nuevo cada vez que vuelves al tablero desde otra pantalla
        // (idiomorph retira su <script> al salir y lo inserta al volver), asi que
        // una variable de modulo arranca en false cada vez y los dos listeners
        // se acumulaban sobre `document`, que sobrevive a todo. Con dos copias de
        // `onDocumentClick` cada clic en una tarjeta abria el modal dos veces.
        //
        // <html> es el unico nodo que ni el morph ni una navegacion boosted
        // tocan. Es el mismo patron de work-items.js, tasks.js y assignments.js.
        if (document.documentElement.dataset.adhocDashboardBound === '1') return;
        document.documentElement.dataset.adhocDashboardBound = '1';

        // Delegación en `document`: el morph de HTMX puede reemplazar las
        // tarjetas sin que haya que reenganchar nada.
        document.addEventListener('click', onDocumentClick);
        document.addEventListener('keydown', onDocumentKeydown);
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(init);
    }

    window.AdhocDashboard = {
        open: openWorkflow,
        config: config
    };
})();
