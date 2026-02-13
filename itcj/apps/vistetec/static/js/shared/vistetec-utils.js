/**
 * VisteTec - Utilidades centralizadas
 * Funciones compartidas para toda la aplicación VisteTec.
 */
(function () {
    'use strict';

    // ==================== TOAST NOTIFICATIONS ====================

    function showToast(message, type = 'info') {
        const container = document.getElementById('toastContainer');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast align-items-center text-bg-${type} border-0 show`;
        toast.setAttribute('role', 'alert');
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>`;

        container.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    }

    // ==================== CONFIRMATION MODAL ====================

    async function confirmModal(title, message, confirmText = 'Confirmar', cancelText = 'Cancelar') {
        return new Promise((resolve) => {
            let resolved = false;
            const modalId = `vt-modal-${Date.now()}`;
            const modal = document.createElement('div');
            modal.className = 'modal fade';
            modal.id = modalId;
            modal.innerHTML = `
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">
                                <i class="bi bi-exclamation-triangle me-2"></i>${title}
                            </h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">${message}</div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">${cancelText}</button>
                            <button type="button" class="btn text-white" id="${modalId}-confirm"
                                    style="background-color: #8B1538;">${confirmText}</button>
                        </div>
                    </div>
                </div>`;

            document.body.appendChild(modal);
            const bsModal = new bootstrap.Modal(modal);
            bsModal.show();

            modal.querySelector(`#${modalId}-confirm`).addEventListener('click', () => {
                resolved = true;
                bsModal.hide();
            });

            modal.addEventListener('hidden.bs.modal', () => {
                modal.remove();
                resolve(resolved);
            });
        });
    }

    // ==================== IMAGE COMPRESSION ====================

    async function compressImage(file, { maxSizeMB = 3, maxDimension = 1920, initialQuality = 0.8 } = {}) {
        const maxBytes = maxSizeMB * 1024 * 1024;

        if (file.size <= maxBytes) {
            return file;
        }

        return new Promise((resolve, reject) => {
            const img = new Image();
            const url = URL.createObjectURL(file);

            img.onload = () => {
                URL.revokeObjectURL(url);

                let { width, height } = img;

                if (width > maxDimension || height > maxDimension) {
                    const ratio = Math.min(maxDimension / width, maxDimension / height);
                    width = Math.round(width * ratio);
                    height = Math.round(height * ratio);
                }

                const canvas = document.createElement('canvas');
                canvas.width = width;
                canvas.height = height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, width, height);

                let quality = initialQuality;

                function tryCompress() {
                    canvas.toBlob((blob) => {
                        if (!blob) {
                            reject(new Error('Error al comprimir la imagen'));
                            return;
                        }

                        if (blob.size <= maxBytes || quality <= 0.3) {
                            const name = file.name.replace(/\.\w+$/, '.jpg');
                            const compressed = new File([blob], name, {
                                type: 'image/jpeg',
                                lastModified: Date.now(),
                            });
                            resolve(compressed);
                        } else {
                            quality -= 0.1;
                            tryCompress();
                        }
                    }, 'image/jpeg', quality);
                }

                tryCompress();
            };

            img.onerror = () => {
                URL.revokeObjectURL(url);
                reject(new Error('Error al leer la imagen'));
            };

            img.src = url;
        });
    }

    // ==================== EXPORT ====================

    window.VisteTecUtils = {
        showToast,
        confirmModal,
        compressImage,
    };

})();
