// itcj2/apps/helpdesk/static/js/inventory/my_equipment_modal.js
// Handles modal close behavior for the equipment detail modal in iframe contexts

(function() {
    document.addEventListener('DOMContentLoaded', function() {
        // Botón de cerrar del footer
        const closeBtn = document.getElementById('closeModalBtn');
        if (closeBtn) {
            closeBtn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                $('#equipmentDetailModal').modal('hide');
            });
        }

        // Botón X del header
        const closeHeaderBtn = document.getElementById('closeModalHeaderBtn');
        if (closeHeaderBtn) {
            closeHeaderBtn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                $('#equipmentDetailModal').modal('hide');
            });
        }

        // Resetear tabs cuando se cierra
        $('#equipmentDetailModal').on('hidden.bs.modal', function() {
            // Resetear al primer tab
            setTimeout(() => {
                $('#equipmentTabs a[href="#info-content"]').tab('show');
            }, 200);
        });

        // Manejar tecla ESC manualmente
        $(document).on('keydown', function(e) {
            if (e.key === 'Escape' || e.keyCode === 27) {
                const $modal = $('#equipmentDetailModal');
                if ($modal.hasClass('show')) {
                    $modal.modal('hide');
                }
            }
        });

        // Manejar click en el backdrop (fondo oscuro)
        $('#equipmentDetailModal').on('click', function(e) {
            // Solo cerrar si se hace click directamente en el modal (no en su contenido)
            if (e.target === this) {
                $(this).modal('hide');
            }
        });
    });
})();
