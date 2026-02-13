// itcj/core/static/js/must_change.js
(async () => {
    function showToast(message, type = "info") {
        // Crea el contenedor si no existe
        let toastContainer = document.getElementById("toast-container");
        if (!toastContainer) {
            toastContainer = document.createElement("div");
            toastContainer.id = "toast-container";
            toastContainer.style.position = "fixed";
            toastContainer.style.top = "20px";
            toastContainer.style.right = "20px";
            toastContainer.style.zIndex = "9999";
            document.body.appendChild(toastContainer);
        }

        // Crea el toast
        const toast = document.createElement("div");
        toast.className = `toast align-items-center text-bg-${type} border-0 show mb-2`;
        toast.setAttribute("role", "alert");
        toast.setAttribute("aria-live", "assertive");
        toast.setAttribute("aria-atomic", "true");
        toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${message}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
    `;

        toastContainer.appendChild(toast);

        // Elimina el toast después de 3 segundos
        setTimeout(() => {
            toast.remove();
        }, 3000);
    }

    // Función para bloquear toda la interfaz
    // Detectar si estamos en mobile o desktop
    const isMobile = document.body.classList.contains('mobile-body');

    function blockInterface() {
        if (isMobile) {
            // Bloquear interfaz mobile
            const mobileSelectors = [
                '.mobile-main',
                '.mobile-bottom-nav',
                '.mobile-app-card',
                '.mobile-quick-action-btn',
                '.mobile-nav-item'
            ];

            mobileSelectors.forEach(selector => {
                document.querySelectorAll(selector).forEach(element => {
                    element.style.pointerEvents = 'none';
                    element.style.opacity = '0.5';
                });
            });

            // Bloquear navegación inferior
            const bottomNav = document.getElementById('mobileBottomNav');
            if (bottomNav) {
                bottomNav.style.pointerEvents = 'none';
                bottomNav.style.opacity = '0.5';
            }

            // Bloquear contenido principal
            const mainContent = document.getElementById('mobileMainContent');
            if (mainContent) {
                mainContent.style.pointerEvents = 'none';
                mainContent.style.opacity = '0.6';
            }
        } else {
            // Bloquear interfaz desktop (original)
            const selectors = [
                '.desktop-icon',
                '.start-button',
                '.pinned-app',
                '.system-icon',
                'button:not(#btnSavePw):not(.btn-close)',
                '.taskbar button',
                '.taskbar input'
            ];

            selectors.forEach(selector => {
                document.querySelectorAll(selector).forEach(element => {
                    element.style.pointerEvents = 'none';
                    element.style.opacity = '0.5';
                    element.style.cursor = 'not-allowed';
                });
            });

            // Bloquear toda la taskbar
            const taskbar = document.querySelector('.taskbar');
            if (taskbar) {
                taskbar.style.pointerEvents = 'none';
                taskbar.style.opacity = '0.7';
            }

            // Bloquear el desktop
            const desktop = document.getElementById('desktop-grid');
            if (desktop) {
                desktop.style.pointerEvents = 'none';
                desktop.style.opacity = '0.6';
            }
        }
    }

    // Función para desbloquear la interfaz
    function unblockInterface() {
        if (isMobile) {
            // Desbloquear interfaz mobile
            const mobileSelectors = [
                '.mobile-main',
                '.mobile-bottom-nav',
                '.mobile-app-card',
                '.mobile-quick-action-btn',
                '.mobile-nav-item'
            ];

            mobileSelectors.forEach(selector => {
                document.querySelectorAll(selector).forEach(element => {
                    element.style.pointerEvents = '';
                    element.style.opacity = '';
                });
            });

            const bottomNav = document.getElementById('mobileBottomNav');
            if (bottomNav) {
                bottomNav.style.pointerEvents = '';
                bottomNav.style.opacity = '';
            }

            const mainContent = document.getElementById('mobileMainContent');
            if (mainContent) {
                mainContent.style.pointerEvents = '';
                mainContent.style.opacity = '';
            }
        } else {
            // Desbloquear interfaz desktop (original)
            const selectors = [
                '.desktop-icon',
                '.start-button',
                '.pinned-app',
                '.system-icon',
                'button',
                '.taskbar button',
                '.taskbar input'
            ];

            selectors.forEach(selector => {
                document.querySelectorAll(selector).forEach(element => {
                    element.style.pointerEvents = '';
                    element.style.opacity = '';
                    element.style.cursor = '';
                });
            });

            // Desbloquear la taskbar
            const taskbar = document.querySelector('.taskbar');
            if (taskbar) {
                taskbar.style.pointerEvents = '';
                taskbar.style.opacity = '';
            }

            // Desbloquear el desktop
            const desktop = document.getElementById('desktop-grid');
            if (desktop) {
                desktop.style.pointerEvents = '';
                desktop.style.opacity = '';
            }
        }
    }

    const modalEl = document.getElementById("forcePwModal");
    const newPw = document.getElementById("newPw");
    const confirmPw = document.getElementById("confirmPw");
    const btnSave = document.getElementById("btnSavePw");
    const pwErr = document.getElementById("pwErr");

    if (!modalEl || !newPw || !btnSave || !pwErr) {
        console.error("No se encontraron elementos del modal de cambio de contraseña.");
        return;
    }

    const modal = new bootstrap.Modal(modalEl, { backdrop: "static", keyboard: false });

    // Variable para rastrear si se mostró el modal
    let modalWasShown = false;

    try {
        const r = await fetch("/api/core/v1/user/password-state", { credentials: "include" });
        if (r.ok) {
            const { must_change } = await r.json();
            console.log("Estado de la contraseña:", must_change);
            if (must_change) {
                modalWasShown = true;
                blockInterface(); // Bloquear toda la interfaz
                modal.show();
            }
        }
    } catch (e) {
        console.error("Error al verificar el estado de la contraseña:", e);
    }

    // Función para manejar el cambio de contraseña
    const handlePasswordChange = async () => {
        const v = (newPw.value || "").trim();
        const confirmV = confirmPw ? (confirmPw.value || "").trim() : v;

        // Validar que la contraseña tenga al menos 8 caracteres
        if (v.length < 8) {
            pwErr.textContent = "La contraseña debe tener al menos 8 caracteres.";
            pwErr.classList.remove("d-none");
            return;
        }

        // Validar que las contraseñas coincidan
        if (v !== confirmV) {
            pwErr.textContent = "Las contraseñas no coinciden.";
            pwErr.classList.remove("d-none");
            return;
        }

        // Validar que NO sea la contraseña por defecto
        if (v === "tecno#2K") {
            pwErr.textContent = "No puedes usar la contraseña por defecto. Elige una diferente.";
            pwErr.classList.remove("d-none");
            return;
        }

        pwErr.classList.add("d-none");
        btnSave.disabled = true;

        try {
            const res = await fetch("/api/core/v1/user/change-password", {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ new_password: v })
            });

            if (!res.ok) {
                const errorData = await res.json();
                const errorMessage = errorData.message || "No se pudo actualizar la contraseña.";
                showToast(errorMessage, "error");
                return;
            }

            showToast("Contraseña actualizada.", "success");
            modal.hide();

            // Desbloquear la interfaz después de cerrar el modal
            setTimeout(() => {
                unblockInterface();

                // Disparar evento personalizado para indicar que el modal se cerró
                // El tutorial puede escuchar este evento para iniciar
                const event = new CustomEvent('passwordModalClosed');
                window.dispatchEvent(event);
                console.log('[MustChange] Password modal closed, interface unblocked');
            }, 300);
        } catch (e) {
            showToast("No se pudo actualizar la contraseña.", "error");
            console.error("Error al actualizar la contraseña:", e);
        } finally {
            btnSave.disabled = false;
            newPw.value = "";
            if (confirmPw) confirmPw.value = "";
        }
    };

    // Manejar clic en el botón
    btnSave.addEventListener("click", handlePasswordChange);

    // Manejar Enter en el campo de contraseña
    newPw.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            handlePasswordChange();
        }
    });

    // Exponer el estado del modal globalmente para que el tutorial pueda verificarlo
    window.passwordModalWasShown = () => modalWasShown;
})();