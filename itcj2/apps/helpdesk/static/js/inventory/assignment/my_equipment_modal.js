// itcj2/apps/helpdesk/static/js/inventory/assignment/my_equipment_modal.js
// Handles modal close behavior for the equipment detail modal in iframe contexts.
// Exposes window.MyEquipmentModal = { setup, teardown } — NO DOMContentLoaded.

(function () {
    'use strict';

    var _closeBtnHandler = null;
    var _closeHeaderBtnHandler = null;
    var _hiddenModalHandler = null;
    var _escHandler = null;
    var _backdropHandler = null;

    function setup() {
        // Botón de cerrar del footer
        var closeBtn = document.getElementById('closeModalBtn');
        if (closeBtn) {
            _closeBtnHandler = function (e) {
                e.preventDefault();
                e.stopPropagation();
                if (window.jQuery) window.jQuery('#equipmentDetailModal').modal('hide');
            };
            closeBtn.addEventListener('click', _closeBtnHandler);
        }

        // Botón X del header
        var closeHeaderBtn = document.getElementById('closeModalHeaderBtn');
        if (closeHeaderBtn) {
            _closeHeaderBtnHandler = function (e) {
                e.preventDefault();
                e.stopPropagation();
                if (window.jQuery) window.jQuery('#equipmentDetailModal').modal('hide');
            };
            closeHeaderBtn.addEventListener('click', _closeHeaderBtnHandler);
        }

        // Resetear tabs cuando se cierra
        if (window.jQuery) {
            _hiddenModalHandler = function () {
                setTimeout(function () {
                    window.jQuery('#equipmentTabs a[href="#info-content"]').tab('show');
                }, 200);
            };
            window.jQuery('#equipmentDetailModal').on('hidden.bs.modal', _hiddenModalHandler);

            // Click en backdrop
            _backdropHandler = function (e) {
                if (e.target === this) {
                    window.jQuery(this).modal('hide');
                }
            };
            window.jQuery('#equipmentDetailModal').on('click', _backdropHandler);
        }

        // Manejar tecla ESC manualmente
        _escHandler = function (e) {
            if (e.key === 'Escape' || e.keyCode === 27) {
                if (window.jQuery) {
                    var $modal = window.jQuery('#equipmentDetailModal');
                    if ($modal.hasClass('show')) {
                        $modal.modal('hide');
                    }
                }
            }
        };
        document.addEventListener('keydown', _escHandler);
    }

    function teardown() {
        var closeBtn = document.getElementById('closeModalBtn');
        if (closeBtn && _closeBtnHandler) {
            closeBtn.removeEventListener('click', _closeBtnHandler);
        }

        var closeHeaderBtn = document.getElementById('closeModalHeaderBtn');
        if (closeHeaderBtn && _closeHeaderBtnHandler) {
            closeHeaderBtn.removeEventListener('click', _closeHeaderBtnHandler);
        }

        if (window.jQuery) {
            if (_hiddenModalHandler) {
                window.jQuery('#equipmentDetailModal').off('hidden.bs.modal', _hiddenModalHandler);
            }
            if (_backdropHandler) {
                window.jQuery('#equipmentDetailModal').off('click', _backdropHandler);
            }
        }

        if (_escHandler) {
            document.removeEventListener('keydown', _escHandler);
        }

        _closeBtnHandler = null;
        _closeHeaderBtnHandler = null;
        _hiddenModalHandler = null;
        _escHandler = null;
        _backdropHandler = null;
    }

    window.MyEquipmentModal = { setup: setup, teardown: teardown };

})();
