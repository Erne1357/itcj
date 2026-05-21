/* =============================================================================
   ITCJ — AppModal
   -----------------------------------------------------------------------------
   Reemplaza window.alert() y window.confirm() nativos por modales Bootstrap.
   Devuelve Promises para flujos async/await.

   Uso:
     await AppModal.alert({ title, message, variant, okText });
     const ok = await AppModal.confirm({ title, message, confirmText, confirmVariant, cancelText });

   Variants: primary | success | warning | danger | info (default primary).
   Expone window.AppModal.
   ============================================================================= */
(function () {
  "use strict";

  const VARIANT_HEADER = {
    primary: { bg: "bg-primary",  text: "text-white", icon: "bi-info-circle"     },
    success: { bg: "bg-success",  text: "text-white", icon: "bi-check-circle"    },
    warning: { bg: "bg-warning",  text: "text-dark",  icon: "bi-exclamation-triangle" },
    danger:  { bg: "bg-danger",   text: "text-white", icon: "bi-exclamation-octagon"  },
    info:    { bg: "bg-info",     text: "text-dark",  icon: "bi-info-circle"     },
  };

  const VARIANT_BTN = {
    primary: "btn-primary",
    success: "btn-success",
    warning: "btn-warning",
    danger:  "btn-danger",
    info:    "btn-info",
  };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function uniqueId() {
    return "appModal-" + Math.random().toString(36).slice(2, 10);
  }

  /**
   * Construye el HTML del modal y lo monta en <body>.
   * Devuelve {el, modal, ok, cancel, dispose}.
   */
  function build(opts, kind /* "alert" | "confirm" */) {
    const id      = uniqueId();
    const variant = opts.variant || (kind === "confirm" ? "warning" : "primary");
    const header  = VARIANT_HEADER[variant] || VARIANT_HEADER.primary;
    const okBtn   = VARIANT_BTN[opts.confirmVariant || variant] || VARIANT_BTN.primary;

    const okText     = esc(opts.confirmText || opts.okText || (kind === "confirm" ? "Confirmar" : "Aceptar"));
    const cancelText = esc(opts.cancelText  || "Cancelar");
    const title      = esc(opts.title || (kind === "confirm" ? "Confirmar acción" : "Aviso"));
    const message    = opts.html
      ? String(opts.message || "")
      : esc(opts.message || "");

    const showCancel = kind === "confirm";

    const wrapper = document.createElement("div");
    wrapper.innerHTML = `
      <div class="modal fade" id="${id}" tabindex="-1"
           aria-labelledby="${id}-label" aria-hidden="true">
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header ${header.bg} ${header.text}">
              <h5 class="modal-title d-flex align-items-center gap-2" id="${id}-label">
                <i class="bi ${header.icon}" aria-hidden="true"></i>
                ${title}
              </h5>
              <button type="button"
                      class="btn-close ${header.text === "text-white" ? "btn-close-white" : ""}"
                      data-bs-dismiss="modal" aria-label="Cerrar"></button>
            </div>
            <div class="modal-body">
              <div class="${opts.html ? "" : "mb-0"}">${message}</div>
            </div>
            <div class="modal-footer">
              ${showCancel
                ? `<button type="button" class="btn btn-secondary" data-bs-dismiss="modal" data-app-modal-cancel>${cancelText}</button>`
                : ""}
              <button type="button" class="btn ${okBtn}" data-app-modal-ok>${okText}</button>
            </div>
          </div>
        </div>
      </div>`;
    document.body.appendChild(wrapper);
    const el = wrapper.firstElementChild;

    if (typeof window.bootstrap === "undefined" || !window.bootstrap.Modal) {
      // Fallback degradado si Bootstrap aún no carga (raro).
      console.warn("[AppModal] bootstrap.Modal no disponible — fallback a confirm/alert nativo");
      el.remove();
      return null;
    }

    const modal = window.bootstrap.Modal.getOrCreateInstance(el, {
      backdrop: "static",
      keyboard: true,
    });

    function dispose() {
      el.addEventListener("hidden.bs.modal", () => el.remove(), { once: true });
    }

    return { el, modal, dispose };
  }

  /**
   * Confirmación. Devuelve Promise<boolean>.
   */
  function confirmModal(opts = {}) {
    return new Promise((resolve) => {
      const built = build(opts, "confirm");
      if (!built) {
        resolve(window.confirm(opts.message || ""));
        return;
      }
      const { el, modal, dispose } = built;
      let confirmed = false;
      el.querySelector("[data-app-modal-ok]").addEventListener("click", () => {
        confirmed = true;
        modal.hide();
      });
      el.addEventListener("hidden.bs.modal", () => {
        dispose();
        if (typeof opts.onConfirm === "function" && confirmed) opts.onConfirm();
        if (typeof opts.onCancel  === "function" && !confirmed) opts.onCancel();
        resolve(confirmed);
      }, { once: true });
      modal.show();
    });
  }

  /**
   * Alerta. Devuelve Promise<void>.
   */
  function alertModal(opts = {}) {
    return new Promise((resolve) => {
      const built = build(opts, "alert");
      if (!built) {
        window.alert(opts.message || "");
        resolve();
        return;
      }
      const { el, modal, dispose } = built;
      el.querySelector("[data-app-modal-ok]").addEventListener("click", () => modal.hide());
      el.addEventListener("hidden.bs.modal", () => {
        dispose();
        if (typeof opts.onClose === "function") opts.onClose();
        resolve();
      }, { once: true });
      modal.show();
    });
  }

  window.AppModal = {
    confirm: confirmModal,
    alert:   alertModal,
  };
})();
