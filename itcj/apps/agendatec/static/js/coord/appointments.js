// static/js/coord/appointments.js
// Página: /coord/appointments  → Listar y cambiar estado (vía Request)
function getCoordId() {
    try { return Number(document.body?.dataset?.coordId || 0); } catch { return 0; }
  }
  (function wireRealtimeAppointments() {
    const sock = () => window.__reqSocket;
    const refreshIfMatches = (payload) => {
      const selectedDay = document.querySelector("#apDay")?.value;
      if (!selectedDay) return;
      // Si es APPOINTMENT y corresponde al día seleccionado → recargar
      if (payload?.type === "APPOINTMENT" && payload?.day === selectedDay) {
        // opcional: filtrar por estado actual; por simplicidad, refrescamos todo
        document.querySelector("#btnLoadAppointments")?.click();
      }
    };

    const tryBind = () => {
      const s = sock();
      if (!s) return setTimeout(tryBind, 500);
      // Evitar doble registro
      s.off?.("appointment_created");
      s.off?.("request_status_changed");

      s.on("appointment_created", (p) => {
        console.log("[WS req] appointment_created", p);
        refreshIfMatches({ type: "APPOINTMENT", day: p?.slot_day });
      });
      s.on("request_status_changed", (p) => {
        console.log("[WS req] request_status_changed", p);
        refreshIfMatches(p);
      });
    };
    tryBind();
  })();
(() => {

  const $ = (sel) => document.querySelector(sel);
  const statusTone = (s) => ({
    "PENDING": "warning",
    "RESOLVED_SUCCESS": "success",
    "RESOLVED_NOT_COMPLETED": "secondary",
    "NO_SHOW": "danger",
    "ATTENDED_OTHER_SLOT": "info",
    "CANCELED": "secondary"
  }[s] || "secondary");
  const statusES = (s) => ({
    "PENDING": "Pendiente",
    "RESOLVED_SUCCESS": "Resuelta",
    "RESOLVED_NOT_COMPLETED": "No resuelta",
    "NO_SHOW": "No asistió",
    "ATTENDED_OTHER_SLOT": "Asistió en otro horario",
    "CANCELED": "Cancelada"
  }[s] || s);

  let useTable = true; // false = lista, true = tabla

  $("#btnViewList").addEventListener("click", () => {
    useTable = false;
    $("#btnViewList").classList.add("active");
    $("#btnViewTable").classList.remove("active");
  });
  $("#btnViewTable").addEventListener("click", () => {
    useTable = true;
    $("#btnViewTable").classList.add("active");
    $("#btnViewList").classList.remove("active");
  });

  $("#btnLoadAppointments").addEventListener("click", async () => {
    const day = $("#apDay").value;
    const reqStatus = $("#reqStatus").value;
    const url = new URL("/api/agendatec/v1/coord/appointments", window.location.origin);
    url.searchParams.set("day", day);
    // status de solicitud (ALL = no filtra)
    if (reqStatus && reqStatus !== "ALL") url.searchParams.set("req_status", reqStatus);
    // para vista "tabla", necesitamos TODOS los slots del día (incluso vacíos)
    url.searchParams.set("include_empty", useTable ? "1" : "0");

    const coordId = getCoordId();
    if (coordId > 0 && day) {
      // salir de cualquier día previo (guardamos último en el closure del módulo)
      window.__lastApJoin && window.__reqLeaveApDay?.({ coord_id: coordId, day: window.__lastApJoin });
      window.__reqJoinApDay?.({ coord_id: coordId, day });
      window.__lastApJoin = day;
    }
    try {
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();
      if (useTable) renderTable(data.slots || []);
      else renderList((data.items || []));
    } catch (e) {
      showToast("Error al cargar citas.", "error");
    }
  });

  function renderList(items) {
    const el = document.getElementById("apList");
    if (!items.length) {
      el.innerHTML = `<div class="text-muted">Sin citas.</div>`;
      return;
    }
    let html = `<table class="table table-sm table-striped align-middle">
      <thead>
        <tr>
          <th>Hora</th>
          <th>Alumno</th>
          <th>Carrera</th>
          <th>Estado (solicitud)</th>
          <th>Descripción</th>
          <th class="text-end">Acciones</th>
        </tr>
      </thead><tbody>`;
    for (const it of items) {
      const alumno = it.student ? `${it.student.full_name || "—"}<br><span class="text-muted small">${it.student.control_number || it.student.username || "—"}</span>` : "—";
      const st = it.request_status;
      html += `<tr>
        <td>${it.slot.start_time}–${it.slot.end_time}</td>
        <td>${alumno}</td>
        <td>${it.program.name}</td>
        <td><span class="badge text-bg-${statusTone(st)}">${statusES(st)}</span></td>
        <td class="text-truncate" style="max-width:360px;" title="${escapeHtml(it.description || "Sin descripción")}">${escapeHtml(it.description || "Sin descripción")}</td>
        <td class="text-end">
          <button class="btn btn-sm btn-primary ms-1" data-open="${it.request_id}">Ver datalles y responder</button>
        </td>
      </tr>`;
    }
    html += `</tbody></table>`;
    el.innerHTML = html;
  }

  function renderTable(slots) {
    const el = document.getElementById("apList");
    if (!slots.length) {
      el.innerHTML = `<div class="text-muted">Sin horarios configurados para este día.</div>`;
      return;
    }
    let html = `<table class="table table-sm table-bordered align-middle">
      <thead><tr><th style="width:120px">Hora</th><th>Alumno</th><th>Carrera</th><th>Solicitud</th><th class="text-end">Acciones</th></tr></thead><tbody>`;
    for (const s of slots) {
      if (!s.appointment) {
        html += `<tr>
          <td>${s.start}–${s.end}</td>
          <td class="text-muted">Libre</td>
          <td class="text-muted">—</td>
          <td class="text-muted">—</td>
          <td class="text-end text-muted small">—</td>
        </tr>`;
        continue;
      }
      const it = s.appointment;
      const alumno = it.student ? `${it.student.full_name || "—"}<br><span class="text-muted small">${it.student.control_number || it.student.username || "--"}</span>` : "—";
      const st = it.request_status;
      html += `<tr>
        <td>${s.start}–${s.end}</td>
        <td>${alumno}</td>
        <td>${it.program.name}</td>
        <td>
          <div><span class="badge text-bg-${statusTone(st)}">${statusES(st)}</span></div>
          <div class="small text-truncate" style="max-width:420px" title="${escapeHtml(it.description || "Sin descripción")}">${escapeHtml(it.description || "Sin descripción")}</div>
        </td>
        <td class="text-end">
          <button class="btn btn-sm btn-primary ms-1" data-open="${it.request_id}">Ver detalles y responder </button>
        </td>
      </tr>`;
    }
    html += `</tbody></table>`;
    el.innerHTML = html;
  }

  function actionBtns(requestId) {
    return `
      <div class="btn-group btn-group-sm">
        <button class="btn btn-outline-success"  data-req="${requestId}" data-st="RESOLVED_SUCCESS">Resuelta</button>
        <button class="btn btn-outline-warning"  data-req="${requestId}" data-st="RESOLVED_NOT_COMPLETED">No resuelta</button>
        <button class="btn btn-outline-secondary" data-req="${requestId}" data-st="NO_SHOW">No asistió</button>
        <button class="btn btn-outline-info"     data-req="${requestId}" data-st="ATTENDED_OTHER_SLOT">Otro horario</button>
        <button class="btn btn-outline-danger"   data-req="${requestId}" data-st="CANCELED">Cancelar</button>
      </div>`;
  }

  // Acciones (cambiar estado de la SOLICITUD)
  document.addEventListener("click", async (e) => {
    const act = e.target.closest("button[data-req][data-st]");
    if (act) {
      const id = act.getAttribute("data-req");
      const st = act.getAttribute("data-st");
      const commentEl = document.getElementById("reqCoordComment");
      const coordComment = (commentEl?.value || "").trim();

      const label = {
        "RESOLVED_SUCCESS": "Marcar resuelta",
        "RESOLVED_NOT_COMPLETED": "Marcar no resuelta",
        "NO_SHOW": "Marcar no asistió",
        "ATTENDED_OTHER_SLOT": "Marcar asistió en otro horario",
        "CANCELED": "Cancelar solicitud"
      }[st] || `Cambiar a ${st}`;
      if (!confirm(`${label} (#${id})`)) return;
      await patchRequest(id, st, coordComment);
      $("#btnLoadAppointments").click();
      return;
    }

    const openBtn = e.target.closest("button[data-open]");
    if (openBtn) {
      const reqId = openBtn.getAttribute("data-open");
      openDetail(reqId);
    }
  });

  async function patchRequest(reqId, newStatus,coordComment) {
    try {
      const r = await fetch(`/api/agendatec/v1/coord/requests/${reqId}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(
          coordComment ? { status: newStatus,coordinator_comment : coordComment } 
          : {status : newStatus}
        )
      });
      if (!r.ok) throw new Error();
      showToast("Estado de solicitud actualizado.", "success");
      try{
        const modalEl = document.getElementById("reqDetailModal");
        bootstrap.Modal.getInstance(modalEl)?.hide();
      }catch {}
    } catch {
      showToast("No se pudo actualizar el estado.", "error");
    }
  }

  // Modal detalle (carga on-demand)
  async function openDetail(reqId) {
    try {
      const url = new URL("/api/agendatec/v1/coord/appointments", window.location.origin);
      url.searchParams.set("request_id", reqId);
      url.searchParams.set("day", $("#apDay").value);
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();
      const it = (data.items || []).find(x => x.request_id == reqId);
      const body = $("#reqDetailBody");
      const actions = $("#reqDetailActions");
      if (!it) {
        body.innerHTML = `<div class="text-muted">No se encontró la solicitud.</div>`;
        actions.innerHTML = "";
      } else {
        const alumno = it.student ? `${it.student.full_name || "—"} (${it.student.control_number || it.student.username || "—"})` : "—";
        body.innerHTML = `
          <div class="mb-1"><strong>Alumno:</strong> ${alumno}</div>
          <div class="mb-1"><strong>Carrera:</strong> ${it.program.name}</div>
          <div class="mb-1"><strong>Horario:</strong> ${it.slot.start_time}–${it.slot.end_time}</div>
          <div class="mb-1"><strong>Estado solicitud:</strong> ${statusES(it.request_status)}</div>
          <div class="mb-2"><strong>Descripción:</strong><br>${escapeHtml(it.description || "Sin descripción")}</div>
        `;
        actions.innerHTML = actionBtns(it.request_id);
        const commentEl = document.getElementById("reqCoordComment");
        if(commentEl) commentEl.value = it.coordinator_comment || "";
      }
      const modal = new bootstrap.Modal(document.getElementById("reqDetailModal"));
      modal.show();
    } catch {
      showToast("No se pudo abrir el detalle.", "error");
    }
  }

  // Carga inicial
  try { $("#btnLoadAppointments").click(); } catch { }

  function escapeHtml(str) {
    return (str || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
  $("#btnViewTable").addEventListener("click", () => {
    useTable = true;
    $("#btnViewTable").classList.add("active");
    $("#btnViewList").classList.remove("active");
    $("#btnLoadAppointments").click();
  });

  $("#btnViewList").addEventListener("click", () => {
    useTable = false;
    $("#btnViewList").classList.add("active");
    $("#btnViewTable").classList.remove("active");
    $("#btnLoadAppointments").click();
  });

  $("#apDay").addEventListener("change", () => {
    $("#btnLoadAppointments").click();
  });

  $("#reqStatus").addEventListener("change", () => {
    $("#btnLoadAppointments").click();
  });
})();
