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
    const modalEl = document.getElementById("forcePwModal");
    const newPw = document.getElementById("newPw");
    const btnSave = document.getElementById("btnSavePw");
    const pwErr = document.getElementById("pwErr");

    if (!modalEl || !newPw || !btnSave || !pwErr) {
        console.error("No se encontraron elementos del modal de cambio de contraseña.");
        return;
    }

    const modal = new bootstrap.Modal(modalEl, { backdrop: "static", keyboard: false });

    try {
        const r = await fetch("/api/core/v1/user/password-state", { credentials: "include" });
        if (r.ok) {
            const { must_change } = await r.json();
            if (must_change) modal.show();
        }
    } catch (e) {
        console.error("Error al verificar el estado de la contraseña:", e);
    }

    btnSave.addEventListener("click", async () => {
        const v = (newPw.value || "").trim();
        if (!/^\d{4}$/.test(v)) {
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
            if (!res.ok) throw new Error("No se pudo actualizar la contraseña.");
            showToast("Contraseña actualizada.", "success");
            modal.hide();
        } catch (e) {
            showToast("No se pudo actualizar la contraseña.", "error");
            console.error("Error al actualizar la contraseña:", e);
        } finally {
            btnSave.disabled = false;
            newPw.value = "";
        }
    });
})();