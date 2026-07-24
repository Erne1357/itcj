// itcj2/apps/helpdesk/static/js/warehouse/movements.js
//
// Isla de cliente de la vista de MOVIMIENTOS del almacén. La lista, los filtros
// y la paginación se renderizan SERVER-SIDE (HTMX partial #hd-movements-results).
// La vista es de solo lectura: no hay modales ni acciones. Lo único de cliente
// es el botón Limpiar del filter_bar (reset de selects + recarga del fragmento).

const WarehouseMovements = (function () {
    'use strict';

    let _clearHandler = null;

    function refreshResults() {
        const form = document.getElementById('hd-filter-form');
        if (form && window.htmx) window.htmx.trigger(form, 'refresh');
    }

    function init() {
        const clearBtn = document.getElementById('btnClearFilters');
        if (clearBtn) {
            _clearHandler = function () {
                const form = document.getElementById('hd-filter-form');
                if (form) form.querySelectorAll('select').forEach((s) => { s.value = ''; });
                refreshResults();
            };
            clearBtn.addEventListener('click', _clearHandler);
        }
    }

    function destroy() {
        const clearBtn = document.getElementById('btnClearFilters');
        if (clearBtn && _clearHandler) clearBtn.removeEventListener('click', _clearHandler);
        _clearHandler = null;
    }

    window.HelpdeskPage.page('warehouse_movements', { init: init, destroy: destroy });

    return {};
})();
