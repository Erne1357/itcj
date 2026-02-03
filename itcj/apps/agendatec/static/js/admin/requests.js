// static/js/admin/requests.js
(() => {
  const $ = (s) => document.querySelector(s);
  const cfg = window.__adminRequestsCfg || {};
  const listUrl = cfg.listUrl || "/api/agendatec/v1/admin/requests";
  const detailBase = cfg.detailBase || "/api/agendatec/v1/admin/requests/"; // + id
  const statusBase = cfg.statusBase || "/api/agendatec/v1/admin/requests/"; // + id + /status
  const programsUrl = cfg.programsUrl || "/api/agendatec/v1/programs";
  const coordsUrl = cfg.coordsUrl || "/api/agendatec/v1/admin/users/coordinators";
  const periodsUrl = cfg.periodsUrl || "/api/agendatec/v1/periods";

  let page = 0;
  const pageSize = 10;
  let activePeriodId = null;

  const statusTone = (s) =>
    ({
      PENDING: "warning",
      RESOLVED_SUCCESS: "success",
      RESOLVED_NOT_COMPLETED: "secondary",
      NO_SHOW: "danger",
      ATTENDED_OTHER_SLOT: "info",
      CANCELED: "secondary",
    }[s] || "secondary");
  const statusES = (s) =>
    ({
      PENDING: "Pendiente",
      RESOLVED_SUCCESS: "Resuelta",
      RESOLVED_NOT_COMPLETED: "No resuelta",
      NO_SHOW: "No asistió",
      ATTENDED_OTHER_SLOT: "Otro horario",
      CANCELED: "Cancelada",
    }[s] || s);

  function initDates() {
    const to = new Date();
    const from = new Date(Date.now() - 7 * 86400000);
    $("#fltTo").value = to.toISOString().slice(0, 10);
    $("#fltFrom").value = from.toISOString().slice(0, 10);
  }

  async function loadProgramsAndCoords() {
    try {
      const [rp, rc, rper] = await Promise.all([
        fetch(programsUrl, { credentials: "include" }),
        fetch(coordsUrl, { credentials: "include" }),
        fetch(periodsUrl, { credentials: "include" }),
      ]);
      const pj = (await rp.json());
      const cj = (await rc.json());
      const perj = (await rper.json());

      const progs = Array.isArray(pj) ? pj : (pj.items || pj.programs || []);
      const coords = (cj.items || []);
      const periods = Array.isArray(perj) ? perj : (perj.items || perj.periods || []);

      fillSelect($("#fltProgram"), [{ id: "", name: "Programa" }, ...progs]);
      fillSelect($("#fltCoordinator"), [{ id: "", name: "Coordinador" }, ...coords.map(c => ({ id: c.id, name: c.name }))]);

      // Find active period
      const activePeriod = periods.find(p => p.status === "ACTIVE");
      if (activePeriod) {
        activePeriodId = activePeriod.id;
      }

      // Fill periods select with "Todos" as first option and active period preselected
      const periodOptions = [{ id: "", name: "Todos los períodos" }, ...periods.map(p => ({ id: p.id, name: p.name }))];
      fillSelect($("#fltPeriod"), periodOptions);

      // Set active period as default
      if (activePeriodId) {
        $("#fltPeriod").value = activePeriodId;
      }
    } catch { /* silent */ }
  }

  function fillSelect(sel, items) {
    if (!sel || !Array.isArray(items)) return;
    sel.innerHTML = items
      .map((x) => `<option value="${x.id}">${escapeHtml(x.name)}</option>`)
      .join("");
  }

  function buildQs() {
    const q = new URLSearchParams();
    const from = $("#fltFrom")?.value;
    const to = $("#fltTo")?.value;
    const status = $("#fltStatus")?.value;
    const prog = $("#fltProgram")?.value;
    const coord = $("#fltCoordinator")?.value;
    const period = $("#fltPeriod")?.value;
    const text = $("#txtQ")?.value?.trim();

    if (from) q.set("from", from);
    if (to) q.set("to", to);
    if (status) q.set("status", status);
    if (prog) q.set("program_id", prog);
    if (coord) q.set("coordinator_id", coord);
    if (period) q.set("period_id", period);
    if (text) q.set("q", text);
    q.set("limit", pageSize);
    q.set("offset", page * pageSize);
    return q.toString();
  }

  async function reload() {
    try {
      const r = await fetch(`${listUrl}?${buildQs()}`, { credentials: "include" });
      if (!r.ok) throw new Error();
      const j = await r.json();
      console.log("Loaded requests:", j);

      renderTable(j.items || []);
      $("#lblTotal").textContent = `${j.total || 0} registros`;
      togglePager(j.total || 0);
    } catch {
      showToast?.("Error al cargar solicitudes", "error");
    }
  }

  function renderTable(items) {
    const tb = $("#tblReqBody");
    if (!items.length) {
      tb.innerHTML = `<tr><td colspan="8" class="text-muted">Sin resultados.</td></tr>`;
      return;
    }
    tb.innerHTML = items
      .map((r) => {
        const badge = `<span class="badge text-bg-${statusTone(r.status)}">${statusES(r.status)}</span>`;
        return `<tr data-req-id="${r.id}" style="cursor: pointer;">
          <td>#${r.id}</td>
          <td>${escapeHtml(r.type == "DROP" ? "Baja" : "Cita")}</td>
          <td>${badge}</td>
          <td>${escapeHtml(r.program || "—")}</td>
          <td>${escapeHtml(r.student || "—")}</td>
          <td>${escapeHtml(r.coordinator_name || "—")}</td>
          <td>${fmtDate(r.created_at)}</td>
          <td class="text-end">
            <button class="btn btn-sm btn-outline-info me-1" data-view="${r.id}" title="Ver detalles">
              <i class="bi bi-eye"></i>
            </button>
            ${
              r.status === "PENDING"
                ? `<button class="btn btn-sm btn-outline-primary" data-change="${r.id}" data-type="${r.type}">
                     Cambiar
                   </button>`
                : `<button class="btn btn-sm btn-outline-secondary" data-change="${r.id}" data-type="${r.type}">
                     Re-etiquetar
                   </button>`
            }
          </td>
        </tr>`;
      })
      .join("");
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("es-MX", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return iso;
    }
  }

  function escapeHtml(s) {
    return (s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  // Paginación
  $("#btnPrev")?.addEventListener("click", () => {
    if (page > 0) {
      page--;
      reload();
    }
  });
  $("#btnNext")?.addEventListener("click", () => {
    page++;
    reload();
  });
  function togglePager(total) {
    const maxPage = Math.max(Math.ceil(total / pageSize) - 1, 0);
    $("#btnPrev").disabled = page <= 0;
    $("#btnNext").disabled = page >= maxPage;
  }

  // Filtros
  $("#btnSearch")?.addEventListener("click", () => {
    page = 0;
    reload();
  });
  $("#txtQ")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      page = 0;
      reload();
    }
  });
  $("#fltPeriod")?.addEventListener("change", () => {
    page = 0;
    reload();
  });

  // Cambio de estado (modal)
  let currentReqId = null;

  // Ver detalles (modal)
  document.addEventListener("click", async (e) => {
    const viewBtn = e.target.closest("button[data-view]");
    const row = e.target.closest("tr[data-req-id]");
    
    // Si hace clic en el botón "Ver detalles" o en la fila (pero no en botones de acción)
    if (viewBtn || (row && !e.target.closest("button[data-change]"))) {
      const reqId = viewBtn ? viewBtn.getAttribute("data-view") : row.getAttribute("data-req-id");
      if (reqId) {
        await showRequestDetails(reqId);
        return;
      }
    }

    // Cambio de estado
    const changeBtn = e.target.closest("button[data-change]");
    if (!changeBtn) return;
    currentReqId = changeBtn.getAttribute("data-change");
    const rowForStatus = changeBtn.closest("tr");
    $("#curReqInfo").innerHTML = rowForStatus ? rowForStatus.cells[0].innerText + " · " + rowForStatus.cells[2].innerText : `#${currentReqId}`;
    $("#fNewStatus").value = "RESOLVED_SUCCESS";
    $("#fReason").value = "";
    new bootstrap.Modal($("#mdlStatus")).show();
  });

  async function showRequestDetails(reqId) {
    currentReqId = reqId;
    const modal = new bootstrap.Modal($("#mdlDetails"));
    modal.show();

    // Mostrar loading
    $("#detLoading").style.display = "block";
    $("#detContent").style.display = "none";
    $("#detReqId").textContent = `#${reqId}`;

    try {
      const r = await fetch(`${detailBase}${reqId}`, { credentials: "include" });
      if (!r.ok) throw new Error("Error al cargar detalles");
      const data = await r.json();

      // Alumno
      $("#detStudentName").textContent = data.student?.name || "—";
      $("#detStudentControl").textContent = data.student?.control_number || "—";
      $("#detStudentEmail").textContent = data.student?.email || "—";

      // Info general
      const typeBadge = data.type === "DROP" 
        ? '<span id="detType" class="badge text-bg-warning">Baja</span>' 
        : '<span id="detType" class="badge text-bg-info">Cita</span>';
      $("#detTypeContainer").innerHTML = typeBadge;
      
      const statusBadge = `<span id="detStatus" class="badge text-bg-${statusTone(data.status)}">${statusES(data.status)}</span>`;
      $("#detStatusContainer").innerHTML = statusBadge;
      
      $("#detProgram").textContent = data.program || "—";
      $("#detPeriod").textContent = data.period || "—";

      // Cita (si aplica)
      if (data.appointment) {
        $("#detAppointmentSection").style.display = "block";
        $("#detSlotDay").textContent = data.appointment.slot?.day 
          ? new Date(data.appointment.slot.day + "T00:00:00").toLocaleDateString("es-MX", { 
              weekday: "long", year: "numeric", month: "long", day: "numeric" 
            })
          : "—";
        $("#detSlotTime").textContent = data.appointment.slot 
          ? `${data.appointment.slot.start_time} - ${data.appointment.slot.end_time}`
          : "—";
        $("#detCoordName").textContent = data.coordinator?.name || "—";
        
        const appStatusMap = {
          "SCHEDULED": { text: "Programada", tone: "primary" },
          "DONE": { text: "Completada", tone: "success" },
          "NO_SHOW": { text: "No asistió", tone: "danger" },
          "CANCELED": { text: "Cancelada", tone: "secondary" },
        };
        const appSt = appStatusMap[data.appointment.status] || { text: data.appointment.status, tone: "secondary" };
        $("#detAppStatusContainer").innerHTML = `<span id="detAppStatus" class="badge text-bg-${appSt.tone}">${appSt.text}</span>`;
      } else {
        $("#detAppointmentSection").style.display = "none";
      }

      // Descripción
      if (data.description && data.description.trim()) {
        $("#detDescription").textContent = data.description;
        $("#detDescription").classList.remove("text-muted", "fst-italic");
      } else {
        $("#detDescription").textContent = "Sin descripción proporcionada.";
        $("#detDescription").classList.add("text-muted", "fst-italic");
      }

      // Comentario del coordinador
      if (data.coordinator_comment && data.coordinator_comment.trim()) {
        $("#detCoordComment").textContent = data.coordinator_comment;
        $("#detCoordComment").classList.remove("text-muted", "fst-italic");
      } else {
        $("#detCoordComment").textContent = "Sin comentario del coordinador.";
        $("#detCoordComment").classList.add("text-muted", "fst-italic");
      }

      // Fechas
      $("#detCreatedAt").textContent = fmtDate(data.created_at);
      $("#detUpdatedAt").textContent = fmtDate(data.updated_at);

      // Mostrar contenido
      $("#detLoading").style.display = "none";
      $("#detContent").style.display = "block";

    } catch (err) {
      console.error(err);
      $("#detLoading").innerHTML = `<div class="text-danger"><i class="bi bi-exclamation-triangle me-2"></i>Error al cargar detalles</div>`;
    }
  }

  // Botón "Cambiar Estado" desde modal de detalles
  $("#btnChangeStatusFromDetails")?.addEventListener("click", () => {
    bootstrap.Modal.getInstance($("#mdlDetails"))?.hide();
    if (currentReqId) {
      $("#curReqInfo").innerHTML = `#${currentReqId}`;
      $("#fNewStatus").value = "RESOLVED_SUCCESS";
      $("#fReason").value = "";
      setTimeout(() => new bootstrap.Modal($("#mdlStatus")).show(), 200);
    }
  });

  $("#btnApplyStatus")?.addEventListener("click", async () => {
    const newStatus = $("#fNewStatus").value;
    const reason = $("#fReason").value.trim();
    if (!currentReqId) return;

    try {
      const r = await fetch(`${statusBase}${currentReqId}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(reason ? { status: newStatus, reason } : { status: newStatus }),
      });
      if (!r.ok) throw new Error();
      showToast?.("Estado actualizado", "success");
      bootstrap.Modal.getInstance($("#mdlStatus"))?.hide();
      reload();
    } catch {
      showToast?.("No se pudo actualizar el estado", "error");
    }
  });

  // Realtime con tu socket /requests
  (function wireRealtime() {
    const tryBind = () => {
      const s = window.__reqSocket;
      if (!s) return setTimeout(tryBind, 400);
      const debounced = debounce(reload, 400);
      s.off?.("appointment_created");
      s.off?.("drop_created");
      s.off?.("request_status_changed");
      s.on("appointment_created", debounced);
      s.on("drop_created", debounced);
      s.on("request_status_changed", debounced);
    };
    tryBind();
  })();

  function debounce(fn, t) {
    let h;
    return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), t); };
  }

  // Boot
  initDates();
  loadProgramsAndCoords().then(() => {
    // Reload after loading periods so the active period is preselected
    reload();
  });
})();
