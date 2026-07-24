// itcj2/apps/helpdesk/static/js/inventory/assignment/my_equipment_modal.js
// Reset del modal de detalle de equipo tras cerrarse (BS5, sin jQuery).
// El cierre (X del header, botón Cerrar, ESC, backdrop) lo maneja Bootstrap 5
// nativamente vía data-bs-dismiss="modal". Aquí solo re-seleccionamos la pestaña
// "Información" cuando el modal termina de ocultarse, para que la próxima apertura
// empiece siempre en la primera tab.
// Expone window.MyEquipmentModal = { setup, teardown } — NO DOMContentLoaded.

(function () {
    'use strict';

    var _hiddenModalHandler = null;

    function setup() {
        var modalEl = document.getElementById('equipmentDetailModal');
        if (!modalEl) return;

        _hiddenModalHandler = function () {
            var infoTab = document.getElementById('info-tab');
            if (infoTab && window.bootstrap) {
                try { bootstrap.Tab.getOrCreateInstance(infoTab).show(); }
                catch (e) { /* ignore */ }
            }
        };
        modalEl.addEventListener('hidden.bs.modal', _hiddenModalHandler);
    }

    function teardown() {
        var modalEl = document.getElementById('equipmentDetailModal');
        if (modalEl && _hiddenModalHandler) {
            modalEl.removeEventListener('hidden.bs.modal', _hiddenModalHandler);
        }
        _hiddenModalHandler = null;
    }

    window.MyEquipmentModal = { setup: setup, teardown: teardown };

})();
