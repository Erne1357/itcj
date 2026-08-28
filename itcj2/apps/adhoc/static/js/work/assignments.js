/**
 * work/assignments.js — pantalla /adhoc/asignaciones.
 *
 * Expone SOLO `window.AdhocAssignments` (IIFE, sin globales sueltas).
 *
 * QUÉ SUSTITUYE
 * -------------
 * `incidents/tasks_users.js` (clase global `AsignacionUsuariosManager`), que:
 *  · decidía el destino leyendo `URLSearchParams` **en el navegador** y armaba
 *    la URL con `config.urlAssignStep.replace('/0', '/' + stepId)`; si faltaba
 *    el id, el usuario se enteraba DESPUÉS de elegir a diez personas, con un
 *    "Error: No se detectó el origen". Aquí el destino ya viene resuelto y
 *    validado por el servidor en `page_data.endpoint`, y sin id la página
 *    responde 400 antes de pintarse.
 *  · reimplementaba a mano el selector con orden (`selectedOrder`, badges
 *    `1º/2º`, filtros por columna cableados por índice) → `shared/user-picker.js`
 *    con `ordered=True`.
 *  · traía su propio modal de alerta (`#modalAlertCustom`, duplicado en tres
 *    plantillas con markup distinto) → `AdhocUtils.showToast`.
 *  · leía el error como `data.message || data.error` sobre un `{success:false}`
 *    con HTTP 200 → aquí el error llega como `{"error": …, "status": N}` y lo
 *    traduce `AdhocUtils.fetchJson`.
 *  · terminaba con `window.history.back()`, que no funciona si se entra a la
 *    URL directamente → `page_data.return_to`, validado en el servidor contra
 *    rutas de la propia app (`safe_return_to`).
 *
 * Endpoints posibles (los decide `pages/incidents.py::_ASSIGN_ACTIONS`):
 *   PUT /api/adhoc/v2/tasks/{id}/assignees
 *   PUT /api/adhoc/v2/tasks/{id}/overdue-notifications
 *   PUT /api/adhoc/v2/approval-flows/steps/{id}/validators
 *   PUT /api/adhoc/v2/approval-flows/steps/{id}/overdue-notifications
 * Los cuatro reciben `{"user_ids": [1, 2, 3]}` y responden `{success, message}`.
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;
    var PICKER_ID = 'adhoc-assign-picker';

    function toast(message, type) {
        if (U && typeof U.showToast === 'function') U.showToast(message, type);
    }

    function picker() {
        if (!window.AdhocUserPicker) return null;
        // `get` devuelve la instancia ya montada por su propio init; `mount` es
        // el respaldo por si esta pantalla se cargó antes que aquél.
        return window.AdhocUserPicker.get(PICKER_ID) ||
               window.AdhocUserPicker.mount(PICKER_ID, {
                   users: (U.pageData() || {}).users || [],
                   selected: (U.pageData() || {}).selected_ids || [],
                   ordered: true
               });
    }

    function Assignments(root, data) {
        this.root = root;
        this.data = data || {};
    }

    Assignments.prototype.init = function () {
        if (!this.data.endpoint) {
            console.error('[adhoc] assignments.js: page_data sin endpoint');
            return;
        }
        this.bind();
    };

    Assignments.prototype.leave = function () {
        U.navigate(this.data.return_to || '/adhoc/dashboard');
    };

    Assignments.prototype.save = function (button) {
        var self = this;
        var instance = picker();
        if (!instance) {
            toast('No se pudo leer la selección de personas.', 'error');
            return;
        }

        var ids = instance.getSelection();
        if (!ids.length) {
            // Vaciar la lista es una operación válida (desasignar a todos), pero
            // es destructiva y en el legacy era imposible, así que se confirma.
            U.confirmDialog({
                title: 'Guardar sin nadie seleccionado',
                message: 'No has marcado a ninguna persona. Se quitarán todas las asignaciones actuales.',
                confirmText: 'Guardar de todos modos',
                variant: 'warning'
            }).then(function (ok) {
                if (ok) self.send(button, []);
            });
            return;
        }

        // Quien ya no entra a la app viene MARCADO desde el servidor
        // (`picker_users` → `without_access`), así que guardar conservándolo es
        // una decisión, no un descuido. Sin este aviso lo era: el supervisor
        // llegaba aquí desde la fila "Bloqueada", marcaba un sustituto, guardaba
        // — y el payload seguía llevando al que no entra, así que la tarea
        // volvía marcada. La regla no se recalcula aquí: solo se lee la marca.
        var sinAcceso = (typeof instance.selectionWithoutAccess === 'function')
            ? instance.selectionWithoutAccess() : [];
        if (sinAcceso.length) {
            this.confirmWithoutAccess(button, ids, sinAcceso);
            return;
        }

        this.send(button, ids);
    };

    /**
     * Pregunta antes de guardar una selección que conserva a alguien sin acceso.
     *
     * Dice los NOMBRES, no cuántos: la ficha que hay que quitar se reconoce por
     * el nombre, y el número obligaría a volver a buscarla. Y no quita a nadie
     * por su cuenta —guardar sin ellos sería desasignar a alguien que el usuario
     * no ha tocado—: la acción sigue siendo suya, con la ✕ de su ficha.
     */
    Assignments.prototype.confirmWithoutAccess = function (button, ids, sinAcceso) {
        var self = this;
        var picker = window.AdhocUserPicker;
        var nombres = [];
        for (var i = 0; i < sinAcceso.length; i++) {
            nombres.push(picker && typeof picker.displayName === 'function'
                ? picker.displayName(sinAcceso[i])
                : ('#' + sinAcceso[i].id));
        }
        var lista = nombres.join(', ');
        var uno = sinAcceso.length === 1;

        U.confirmDialog({
            title: uno ? 'Hay alguien que ya no entra a Calidad'
                       : 'Hay personas que ya no entran a Calidad',
            message: (uno ? lista + ' sigue en la selección y ya no puede entrar a Calidad.'
                          : 'Siguen en la selección y ya no pueden entrar a Calidad: ' +
                            lista + '.') +
                     ' Quien no entra no puede atender la tarea, así que guardar así la ' +
                     'deja igual de parada. ' +
                     (uno ? 'Puedes quitarlo con la ✕ de su ficha.'
                          : 'Puedes quitarlos con la ✕ de sus fichas.'),
            confirmText: 'Guardar de todos modos',
            cancelText: 'Volver a la lista',
            variant: 'warning'
        }).then(function (ok) {
            if (ok) self.send(button, ids);
        });
    };

    Assignments.prototype.send = function (button, ids) {
        var self = this;
        button.disabled = true;

        U.fetchJson(this.data.endpoint, {
            method: this.data.method || 'PUT',
            body: JSON.stringify({ user_ids: ids })
        }).then(function (payload) {
            toast((payload && payload.message) || 'Selección guardada.', 'success');
            // Pequeña espera para que el toast se vea antes de navegar.
            setTimeout(function () { self.leave(); }, 700);
        }).catch(function (err) {
            button.disabled = false;
            toast(err.message, 'error');
        });
    };

    Assignments.prototype.bind = function () {
        var self = this;
        this.root.addEventListener('click', function (evt) {
            var save = evt.target.closest('[data-adhoc-assign-save]');
            if (save) {
                evt.preventDefault();
                self.save(save);
                return;
            }
            if (evt.target.closest('[data-adhoc-assign-cancel]')) {
                evt.preventDefault();
                self.leave();
            }
        });
    };

    // ==================== ARRANQUE ====================

    function initAll(scope) {
        var node = scope || document;
        var roots = [];
        var i;

        if (node.matches && node.matches('[data-adhoc-assign]')) roots.push(node);
        var found = node.querySelectorAll ? node.querySelectorAll('[data-adhoc-assign]') : [];
        for (i = 0; i < found.length; i++) roots.push(found[i]);

        var out = [];
        for (i = 0; i < roots.length; i++) {
            var root = roots[i];
            if (root.dataset.adhocAssignBound === '1') continue;
            root.dataset.adhocAssignBound = '1';
            var instance = new Assignments(root, (U && U.pageData) ? U.pageData() : {});
            instance.init();
            out.push(instance);
        }
        return out;
    }

    // Mismo patrón que el resto de la sección: `onReady` para la carga inicial y
    // `htmx:afterSettle` para la navegación con hx-boost, cuya guarda vive en el
    // dataset de <body> (que el morph conserva). La bandera de <html> evita
    // acumular listeners si el módulo se re-ejecuta tras un swap.
    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { initAll(root || document); });
    }
    if (!document.documentElement.dataset.adhocAssignHtmx) {
        document.documentElement.dataset.adhocAssignHtmx = '1';
        document.addEventListener('htmx:afterSettle', function (evt) {
            var api = window.AdhocAssignments;
            if (api && typeof api.initAll === 'function') {
                api.initAll((evt && evt.target) || document);
            }
        });
    }

    window.AdhocAssignments = { initAll: initAll };
})();
