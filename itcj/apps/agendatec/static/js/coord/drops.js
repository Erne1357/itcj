// static/js/coord/drops.js
// Página: /coord/drops  → Listar drops y responder vía modal

(() => {
  const $ = (sel) => document.querySelector(sel);
  function getCoordId() {
    try { return Number(document.body?.dataset?.coordId || 0); } catch { return 0; }
  }
  (function wireRealtimeDrops() {
    const sock = () => window.__reqSocket;
    const shouldRefreshForStatus = () => {
      // si el filtro actual incluye PENDING, refrescamos en creación;
      // y para cambios de estado refrescamos siempre (simple).
      return true;
    };
    const tryBind = () => {
      const s = sock();
      if (!s) return setTimeout(tryBind, 500);
      s.off?.("drop_created");
      s.off?.("request_status_changed");

      s.on("drop_created", (p) => {
        console.log("[WS req] drop_created", p);
        if (shouldRefreshForStatus()) {
          document.querySelector("#btnLoadDrops")?.click();
        }
      });
      s.on("request_status_changed", (p) => {
        if (p?.type !== "DROP") return;
        console.log("[WS req] request_status_changed", p);
        document.querySelector("#btnLoadDrops")?.click();
      });
    };
    tryBind();
  })();
  const mapReqStatusEs = (s) => ({
    "PENDING": "Pendiente",
    "RESOLVED_SUCCESS": "Resuelta",
    "RESOLVED_NOT_COMPLETED": "No resuelta",
    "CANCELED": "Cancelada"
  }[s] || s);

  const toneFor = (s) => ({
    "PENDING": "warning",
    "RESOLVED_SUCCESS": "success",
    "RESOLVED_NOT_COMPLETED": "secondary",
    "CANCELED": "secondary"
  }[s] || "secondary");

  const fmtDate = (iso) => {
    try {
      return new Date(iso).toLocaleString("es-MX", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit"
      });
    } catch { return iso || ""; }
  };

  $("#btnLoadDrops").addEventListener("click", async () => {
    const status = $("#dropStatus").value;
    const url = new URL("/api/agendatec/v1/coord/drops", window.location.origin);
    if (status) url.searchParams.set("status", status);

    try {
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();
      renderDrops(data.items || []);
    } catch {
      showToast("Error al cargar solicitudes de baja.", "error");
    }
  });

  function renderDrops(items) {
    const el = document.getElementById("dropList");
    if (!items.length) {
      el.innerHTML = `<div class="text-muted">Sin solicitudes.</div>`;
      return;
    }

    let html = `<table class="table table-sm table-striped align-middle">
      <thead>
        <tr>
          <th>ID</th>
          <th>Alumno</th>
          <th>Estado</th>
          <th>Descripción</th>
          <th>Creada</th>
          <th class="text-end">Detalle</th>
        </tr>
      </thead><tbody>`;

    for (const it of items) {
      const created = it.created_at ? fmtDate(it.created_at) : "-";
      const statusEs = mapReqStatusEs(it.status);
      const tone = toneFor(it.status);
      const desc = (it.description || "Sin descripción").trim();
      const alumno = it.student ? `${it.student.full_name || "—"}<br><span class="text-muted small">${it.student.control_number || it.student.username || "—"}</span>` : "—";

      html += `<tr>
        <td>#${it.id}</td>
        <td>${alumno}</td>
        <td><span class="badge text-bg-${tone}">${statusEs}</span></td>
        <td class="text-truncate" style="max-width:420px;" title="${escapeHtml(desc)}">${escapeHtml(desc)}</td>
        <td>${created}</td>
        <td class="text-end">
          <button class="btn btn-sm btn-primary" data-open="${it.id}">
            Ver detalle y responder
          </button>
        </td>
      </tr>`;
    }
    html += `</tbody></table>`;
    el.innerHTML = html;
  }

  // Escucha de botón "Ver detalle y responder"
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-open]");
    if (!btn) return;
    const id = btn.getAttribute("data-open");
    await openDetail(id);
  });

  // Modal detalle y acciones (solo RESUELTA / NO RESUELTA / CANCELAR)
  async function openDetail(reqId) {
    try {
      const url = new URL("/api/agendatec/v1/coord/drops", window.location.origin);
      url.searchParams.set("request_id", reqId);
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();
      const it = (data.items || [])[0];
      const body = $("#dropDetailBody");
      const actions = $("#dropDetailActions");

      if (!it) {
        body.innerHTML = `<div class="text-muted">No se encontró la solicitud.</div>`;
        actions.innerHTML = "";
      } else {
        const alumno = it.student ? `${it.student.full_name || "—"} (${it.student.control_number || it.student.username ||"—"})` : "—";
        body.innerHTML = `
          <div class="mb-1"><strong>Solicitud #${it.id}</strong></div>
          <div class="mb-1"><strong>Alumno:</strong> ${alumno}</div>
          <div class="mb-1"><strong>Estado:</strong> ${mapReqStatusEs(it.status)}</div>
          <div class="mb-1"><strong>Creada:</strong> ${fmtDate(it.created_at)}</div>
          <div class="mb-2"><strong>Descripción:</strong><br>${escapeHtml(it.description || "Sin descripción")}</div>
        `;

        actions.innerHTML = `
          <button class="btn btn-outline-success"  data-drop="${it.id}" data-st="RESOLVED_SUCCESS">Marcar resuelta</button>
          <button class="btn btn-outline-warning"  data-drop="${it.id}" data-st="RESOLVED_NOT_COMPLETED">No resuelta</button>
          <button class="btn btn-outline-danger"   data-drop="${it.id}" data-st="CANCELED">Cancelar</button>
        `;
        const cEl = document.getElementById("dropCoordComment");
        if (cEl) cEl.value = it.coordinator_comment || it.comment || "";
      }

      const modal = new bootstrap.Modal(document.getElementById("dropDetailModal"));
      modal.show();
    } catch {
      showToast("No se pudo abrir el detalle.", "error");
    }
  }

  // Acciones desde el modal
  document.addEventListener("click", async (e) => {
    const act = e.target.closest("button[data-drop][data-st]");
    if (!act) return;
    const id = act.getAttribute("data-drop");
    const st = act.getAttribute("data-st");
    const coordComment = (document.getElementById("dropCoordComment")?.value || "").trim();

    const label = {
      "RESOLVED_SUCCESS": "Marcar resuelta",
      "RESOLVED_NOT_COMPLETED": "Marcar no resuelta",
      "CANCELED": "Cancelar solicitud"
    }[st] || `Cambiar a ${st}`;

    if (!confirm(`${label} (#${id})`)) return;

    try {
      const r = await fetch(`/api/agendatec/v1/coord/requests/${id}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(
          coordComment ? { status: st, coordinator_comment: coordComment } : { status: st }
        )
      });
      if (!r.ok) throw new Error();
      showToast("Estado de solicitud actualizado.", "success");
      $("#btnLoadDrops").click(); // refrescar lista
      // cerrar modal si está abierto
      try { bootstrap.Modal.getInstance(document.getElementById("dropDetailModal"))?.hide(); } catch { }
    } catch {
      showToast("No se pudo actualizar el estado.", "error");
    }
  });

  // Carga inicial
  try {
    $("#btnLoadDrops").click();
    const coordId = getCoordId();
    if (coordId > 0) {
      window.__reqJoinDrops?.({ coord_id: coordId });
    }
  } catch { }

  function escapeHtml(str) {
    return (str || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
  $("#dropStatus").addEventListener("change", () => {
    $("#btnLoadDrops").click();
  });
})();
