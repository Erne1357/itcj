// static/prorrogas_tec/js/student/requests.js
(async () => {
  const panel = document.getElementById("reqPanel");

  // --- Helpers de mapeo a español (UI) ---
  const mapStatus = (s) => ({
    "PENDING": "PENDIENTE",
    "APPROVED": "APROBADA",
    "REJECTED": "RECHAZADA",
  }[s] || s);

  const toneForStatus = (s) => ({
    "PENDING": "warning",
    "APPROVED": "success",
    "REJECTED": "danger",
  }[s] || "secondary");

  const fmtDate = (iso) => {
    try {
      return new Date(iso).toLocaleString("es-MX", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit"
      });
    } catch { return iso || ""; }
  };

  const badge = (text, tone = "secondary") =>
    `<span class="badge text-bg-${tone}" style="letter-spacing:.3px">${text}</span>`;

  const btn = (label, { id = "", cls = "btn btn-sm btn-outline-danger", attrs = "" } = {}) =>
    `<button ${id ? `id="${id}"` : ""} class="${cls}" ${attrs}>${label}</button>`;

  function showToast(message, type = "info") {
    if (window.showToast && window.showToast !== showToast) {
      window.showToast(message, type);
      return;
    }
    alert(message);
  }

  function escapeHtml(str) {
    return (str || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  // --- Carga inicial ---
  await load();

  // --- Función principal de carga + render ---
  async function load() {
    try {
      panel.innerHTML = skeleton();
      const r = await fetch("/api/prorrogas/v2/request2/mine", { credentials: "include" });
      if (!r.ok) throw 0;
      const data = await r.json();

      panel.innerHTML = `
        <div class="d-flex flex-column gap-3">
          ${renderActive(data.active)}
          ${renderHistory(data.history || [])}
        </div>
      `;

      wireCancelModal();
    } catch (e) {
      panel.innerHTML = `<div class="text-muted">No se pudieron cargar tus solicitudes.</div>`;
      console.error("Error al cargar solicitudes:", e);
    }
  }

  function wireCancelModal() {
    const cancelBtn = document.getElementById("btnCancelRequest");
    if (!cancelBtn) return;

    const modalEl = document.getElementById("modalCancelRequest");
    const modal = new bootstrap.Modal(modalEl);
    const btnConfirm = document.getElementById("btnConfirmCancelRequest");

    cancelBtn.addEventListener("click", () => {
      const reqId = cancelBtn.getAttribute("data-id");
      btnConfirm.setAttribute("data-pending-id", reqId);
      modal.show();
    });

    btnConfirm?.addEventListener("click", async () => {
      const reqId = btnConfirm.getAttribute("data-pending-id");
      modal.hide();
      if (reqId) {
        await doCancel(reqId);
      }
    });
  }

  // --- Render "Solicitud activa" ---
  function renderActive(active) {
    if (!active) {
      return `
        <div class="card border-0 shadow-sm">
          <div class="card-body">
            <div class="d-flex align-items-center justify-content-between">
              <h6 class="mb-0">Solicitud activa</h6>
              ${badge("NINGUNA", "secondary")}
            </div>
            <div class="text-muted small mt-2">No tienes una solicitud de plazos de pago pendiente.</div>
          </div>
        </div>
      `;
    }

    const status = mapStatus(active.status);
    const statusTone = toneForStatus(active.status);
    const created = fmtDate(active.created_at);
    const letter = (active.letter || "Sin justificación").trim();
    const canCancel = active.status === "PENDING";

    return `
      <div class="card border-0 shadow-sm">
        <div class="card-body">
          <div class="d-flex align-items-center justify-content-between flex-wrap gap-2">
            <h6 class="mb-0">Solicitud activa</h6>
            <div class="d-flex align-items-center gap-2">
              ${badge(`${active.payments_terms} plazo${active.payments_terms === 1 ? "" : "s"}`, "primary")}
              ${badge(status, statusTone)}
            </div>
          </div>

          <div class="mt-2">
            <div class="small text-muted">
              <i class="bi bi-clock me-1"></i> Creada: ${created}
            </div>
            <div class="small mt-1">
              <textarea class="form-control" rows="5" cols="85" readonly>${escapeHtml(letter)}</textarea>
            </div>
          </div>

          ${canCancel ? `
          <div class="mt-3 d-flex gap-2">
            ${btn("Cancelar solicitud", {
              id: "btnCancelRequest",
              cls: "btn btn-sm btn-outline-danger",
              attrs: `data-id="${active.id}"`
            })}
          </div>
          ` : ""}
        </div>
      </div>
    `;
  }

  // --- Render "Historial" ---
  function renderHistory(items) {
    let html = `
      <div class="card border-0 shadow-sm">
        <div class="card-body">
          <h6 class="mb-3">Historial</h6>
    `;

    if (!items.length) {
      html += `<div class="text-muted small">Sin historial.</div>`;
    } else {
      html += `<ul class="list-group list-group-flush">`;
      for (const h of items) {
        const status = mapStatus(h.status);
        const tone = toneForStatus(h.status);
        const when = fmtDate(h.created_at);
        html += `
          <li class="list-group-item d-flex justify-content-between align-items-start">
            <div class="d-flex flex-column">
              <span class="fw-semibold">${h.payments_terms} plazo${h.payments_terms === 1 ? "" : "s"}</span>
              <textarea class="form-control" rows="5" cols="85" readonly>${escapeHtml((h.letter || "").trim())}</textarea>
              <span class="small text-muted">${when}</span>
            </div>
            ${badge(status, tone)}
          </li>
        `;
      }
      html += `</ul>`;
    }

    html += `
        </div>
      </div>
    `;
    return html;
  }

  // --- Cancelar solicitud ---
  async function doCancel(reqId) {
    try {
      const r = await fetch(`/api/prorrogas/v2/request2/${reqId}/cancel`, {
        method: "PATCH",
        credentials: "include"
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        const detail = err.detail || {};
        if (detail.error === "not_pending") {
          showToast("La solicitud ya no está pendiente.", "warn");
        } else if (detail.error === "request_not_found") {
          showToast("Solicitud no encontrada.", "warn");
        } else {
          showToast(detail.message || "No se pudo cancelar la solicitud.", "error");
        }
        return;
      }
      showToast("Solicitud cancelada.", "success");
      await load();
    } catch (e) {
      console.error(e);
      showToast("No se pudo conectar.", "error");
    }
  }

  // --- Skeleton mínimo mientras carga ---
  function skeleton() {
    return `
      <div class="card border-0 shadow-sm">
        <div class="card-body">
          <div class="placeholder-glow">
            <span class="placeholder col-3"></span>
            <div class="mt-2">
              <span class="placeholder col-6"></span>
              <span class="placeholder col-4"></span>
              <span class="placeholder col-8"></span>
            </div>
          </div>
        </div>
      </div>
    `;
  }
})();