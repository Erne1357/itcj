// static/js/admin/requests.js
(() => {
  const $ = (s) => document.querySelector(s);
  const cfg       = window.__adminRequestsCfg || {};
  const listUrl   = cfg.listUrl   || "/api/agendatec/v2/admin/requests";
  const detailBase = cfg.detailBase || "/api/agendatec/v2/admin/requests/";
  const statusBase  = cfg.statusBase  || "/api/agendatec/v2/admin/requests/";
  const programsUrl = cfg.programsUrl || "/api/agendatec/v2/programs";
  const coordsUrl   = cfg.coordsUrl   || "/api/agendatec/v2/admin/users/coordinators";
  const periodsUrl  = cfg.periodsUrl  || "/api/agendatec/v2/periods";

  // === ESTADO GLOBAL DEL MÓDULO ===
  let page         = 0;
  let pageSize     = 10;
  let totalItems   = 0;
  let activePeriodId = null;
  let sortCol      = "";
  let sortDir      = "";

  // === MAPS ===
  const statusTone = (s) => ({
    PENDING:                "warning",
    RESOLVED_SUCCESS:       "success",
    RESOLVED_NOT_COMPLETED: "secondary",
    NO_SHOW:                "danger",
    ATTENDED_OTHER_SLOT:    "info",
    CANCELED:               "secondary",
  }[s] || "secondary");

  const statusES = (s) => ({
    PENDING:                "Pendiente",
    RESOLVED_SUCCESS:       "Resuelta",
    RESOLVED_NOT_COMPLETED: "No resuelta",
    NO_SHOW:                "No asistió",
    ATTENDED_OTHER_SLOT:    "Otro horario",
    CANCELED:               "Cancelada",
  }[s] || s);

  // === FECHAS INICIALES ===
  function initDates() {
    const to   = new Date();
    const from = new Date(Date.now() - 7 * 86400000);
    $("#fltTo").value   = to.toISOString().slice(0, 10);
    $("#fltFrom").value = from.toISOString().slice(0, 10);
  }

  // === CARGA SELECTS FILTROS ===
  async function loadProgramsAndCoords() {
    try {
      const [rp, rc, rper] = await Promise.all([
        fetch(programsUrl, { credentials: "include" }),
        fetch(coordsUrl,   { credentials: "include" }),
        fetch(periodsUrl,  { credentials: "include" }),
      ]);
      const pj   = await rp.json();
      const cj   = await rc.json();
      const perj = await rper.json();

      const progs   = Array.isArray(pj)   ? pj   : (pj.items   || pj.programs   || []);
      const coords  = (cj.items || []);
      const periods = Array.isArray(perj) ? perj : (perj.items || perj.periods   || []);

      fillSelect($("#fltProgram"),     [{ id: "", name: "Programa" },    ...progs]);
      fillSelect($("#fltCoordinator"), [{ id: "", name: "Coordinador" }, ...coords.map((c) => ({ id: c.id, name: c.name }))]);

      const activePeriod = periods.find((p) => p.status === "ACTIVE");
      if (activePeriod) activePeriodId = activePeriod.id;

      fillSelect($("#fltPeriod"), [{ id: "", name: "Todos los períodos" }, ...periods.map((p) => ({ id: p.id, name: p.name }))]);
      if (activePeriodId) $("#fltPeriod").value = activePeriodId;
    } catch { /* silent */ }
  }

  function fillSelect(sel, items) {
    if (!sel || !Array.isArray(items)) return;
    sel.innerHTML = items
      .map((x) => `<option value="${x.id}">${escapeHtml(x.name)}</option>`)
      .join("");
  }

  // === QUERY STRING ===
  function buildQs() {
    const q = new URLSearchParams();
    const from   = $("#fltFrom")?.value;
    const to     = $("#fltTo")?.value;
    const status = $("#fltStatus")?.value;
    const prog   = $("#fltProgram")?.value;
    const coord  = $("#fltCoordinator")?.value;
    const period = $("#fltPeriod")?.value;
    const text   = $("#txtQ")?.value?.trim();

    if (from)   q.set("from", from);
    if (to)     q.set("to", to);
    if (status) q.set("status", status);
    if (prog)   q.set("program_id", prog);
    if (coord)  q.set("coordinator_id", coord);
    if (period) q.set("period_id", period);
    if (text)   q.set("q", text);
    if (sortCol) { q.set("order_by", sortCol); q.set("order_dir", sortDir || "asc"); }
    q.set("limit",  pageSize);
    q.set("offset", page * pageSize);
    return q.toString();
  }

  // === RECARGA ===
  async function reload() {
    const tb = $("#tblReqBody");
    if (!tb) return;

    // Skeleton
    if (window.AgendaTec?.Skeleton) {
      tb.innerHTML = window.AgendaTec.Skeleton.tableRows(pageSize > 10 ? 6 : 4, 8, { withActions: true });
    }

    try {
      const r = await fetch(`${listUrl}?${buildQs()}`, { credentials: "include" });
      if (!r.ok) throw new Error();
      const j = await r.json();
      totalItems = j.total || 0;

      renderTable(j.items || []);
      renderPagination();
      $("#lblTotal").textContent = `${totalItems} registros`;
    } catch {
      showToast?.("Error al cargar solicitudes", "error");
      if (tb) tb.innerHTML = `<tr><td colspan="8" class="text-center text-danger small py-3">
        <i class="bi bi-exclamation-triangle me-1"></i>Error al cargar datos</td></tr>`;
    }
  }

  // === RENDER TABLA ===
  function renderTable(items) {
    const tb = $("#tblReqBody");
    if (!items.length) {
      tb.innerHTML = `
        <tr>
          <td colspan="8">
            <div class="at-empty py-4">
              <i class="bi bi-funnel fs-3" aria-hidden="true"></i>
              <p class="mt-2 mb-1">Sin resultados con estos filtros</p>
              <button type="button" class="btn btn-sm btn-outline-secondary" id="btnClearFilters">
                <i class="bi bi-x-lg me-1"></i>Limpiar filtros
              </button>
            </div>
          </td>
        </tr>`;
      document.getElementById("btnClearFilters")?.addEventListener("click", clearFilters);
      return;
    }
    tb.innerHTML = items.map((r) => {
      const badge = `<span class="badge text-bg-${statusTone(r.status)}">${statusES(r.status)}</span>`;
      return `<tr data-req-id="${r.id}" role="button" tabindex="0" aria-label="Ver solicitud #${r.id}" style="cursor:pointer;">
        <td data-at-label="ID">#${r.id}</td>
        <td data-at-label="Tipo">${escapeHtml(r.type === "DROP" ? "Baja" : "Cita")}</td>
        <td data-at-label="Estado">${badge}</td>
        <td data-at-label="Programa">${escapeHtml(r.program || "—")}</td>
        <td data-at-label="Alumno">${escapeHtml(r.student || "—")}</td>
        <td data-at-label="Coordinador">${escapeHtml(r.coordinator_name || "—")}</td>
        <td data-at-label="Creado">${fmtDate(r.created_at)}</td>
        <td class="text-end">
          <button class="btn btn-sm btn-outline-info me-1" data-view="${r.id}" title="Ver detalles" aria-label="Ver detalles solicitud #${r.id}">
            <i class="bi bi-eye" aria-hidden="true"></i>
          </button>
          <button class="btn btn-sm ${r.status === "PENDING" ? "btn-outline-primary" : "btn-outline-secondary"}"
                  data-change="${r.id}" data-type="${r.type}"
                  title="${r.status === "PENDING" ? "Cambiar estado" : "Re-etiquetar"}"
                  aria-label="Cambiar estado solicitud #${r.id}">
            ${r.status === "PENDING" ? "Cambiar" : "Re-etiquetar"}
          </button>
        </td>
      </tr>`;
    }).join("");

    // Sincronizar labels para mobile cards
    if (window.AgendaTec?.TableCard) {
      window.AgendaTec.TableCard.syncLabels(tb.closest("table"));
    }
  }

  // === PAGINACIÓN NUMÉRICA ===
  function renderPagination() {
    const totalPages = Math.max(Math.ceil(totalItems / pageSize), 1);
    const pager = document.getElementById("pagerContainer");
    if (!pager) return;

    // Texto de página
    const pageInfo = document.getElementById("lblPageInfo");
    if (pageInfo) pageInfo.textContent = `Página ${page + 1} de ${totalPages}`;

    // Rango de 5 páginas alrededor de la actual
    const half  = 2;
    let start = Math.max(0, page - half);
    let end   = Math.min(totalPages - 1, page + half);
    if (end - start < 4) {
      if (start === 0) end   = Math.min(totalPages - 1, 4);
      else             start = Math.max(0, end - 4);
    }

    let html = "";
    // Primera
    if (start > 0) {
      html += `<li class="page-item"><button class="page-link" data-pg="0">1</button></li>`;
      if (start > 1) html += `<li class="page-item disabled"><span class="page-link">…</span></li>`;
    }
    // Rango
    for (let i = start; i <= end; i++) {
      html += `<li class="page-item ${i === page ? "active" : ""}">
        <button class="page-link" data-pg="${i}"${i === page ? ' aria-current="page"' : ''}>${i + 1}</button>
      </li>`;
    }
    // Última
    if (end < totalPages - 1) {
      if (end < totalPages - 2) html += `<li class="page-item disabled"><span class="page-link">…</span></li>`;
      html += `<li class="page-item"><button class="page-link" data-pg="${totalPages - 1}">${totalPages}</button></li>`;
    }
    pager.innerHTML = html;

    // Botones prev/next
    const btnPrev = document.getElementById("btnPrev");
    const btnNext = document.getElementById("btnNext");
    if (btnPrev) btnPrev.disabled = page <= 0;
    if (btnNext) btnNext.disabled = page >= totalPages - 1;
  }

  // === ORDENAMIENTO POR COLUMNA ===
  function updateSortIndicators() {
    document.querySelectorAll("#tblReqHead th[data-sort]").forEach((th) => {
      th.querySelectorAll(".bi-arrow-up, .bi-arrow-down, .bi-arrow-up-down").forEach((i) => i.remove());
      const col = th.dataset.sort;
      const icon = document.createElement("i");
      if (col === sortCol) {
        icon.className = `bi ms-1 ${sortDir === "desc" ? "bi-arrow-down" : "bi-arrow-up"}`;
        icon.setAttribute("aria-hidden", "true");
      } else {
        icon.className = "bi bi-arrow-up-down ms-1 opacity-50";
        icon.setAttribute("aria-hidden", "true");
      }
      th.appendChild(icon);
    });
  }

  // === LIMPIAR FILTROS ===
  function clearFilters() {
    ["fltFrom", "fltTo", "fltStatus", "fltProgram", "fltCoordinator", "txtQ"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = "";
    });
    if (activePeriodId && document.getElementById("fltPeriod")) {
      document.getElementById("fltPeriod").value = activePeriodId;
    }
    page = 0;
    reload();
  }

  // === ESTADO ACTUAL DE SOLICITUD (para cambio) ===
  let currentReqId = null;

  // === VER DETALLES ===
  async function showRequestDetails(reqId) {
    currentReqId = reqId;
    const modal = new bootstrap.Modal($("#mdlDetails"));
    modal.show();

    const detLoading = $("#detLoading");
    const detContent = $("#detContent");
    if (detLoading) { detLoading.hidden = false; }
    if (detContent) { detContent.hidden = true;  }
    $("#detReqId").textContent = `#${reqId}`;

    try {
      const r = await fetch(`${detailBase}${reqId}`, { credentials: "include" });
      if (!r.ok) throw new Error("Error al cargar detalles");
      const data = await r.json();

      $("#detStudentName").textContent    = data.student?.name           || "—";
      $("#detStudentControl").textContent = data.student?.control_number || "—";
      $("#detStudentEmail").textContent   = data.student?.email          || "—";

      const typeBadge   = data.type === "DROP"
        ? '<span class="badge text-bg-warning">Baja</span>'
        : '<span class="badge text-bg-info">Cita</span>';
      $("#detTypeContainer").innerHTML    = typeBadge;
      $("#detStatusContainer").innerHTML  = `<span class="badge text-bg-${statusTone(data.status)}">${statusES(data.status)}</span>`;
      $("#detProgram").textContent        = data.program || "—";
      $("#detPeriod").textContent         = data.period  || "—";

      const apptSec = $("#detAppointmentSection");
      if (data.appointment) {
        if (apptSec) apptSec.hidden = false;
        $("#detSlotDay").textContent  = data.appointment.slot?.day
          ? new Date(data.appointment.slot.day + "T00:00:00").toLocaleDateString("es-MX", {
              weekday: "long", year: "numeric", month: "long", day: "numeric",
            })
          : "—";
        $("#detSlotTime").textContent = data.appointment.slot
          ? `${data.appointment.slot.start_time} - ${data.appointment.slot.end_time}` : "—";
        $("#detCoordName").textContent = data.coordinator?.name || "—";
        const appStatusMap = {
          SCHEDULED: { text: "Programada",  tone: "primary" },
          DONE:      { text: "Completada",  tone: "success" },
          NO_SHOW:   { text: "No asistió",  tone: "danger"  },
          CANCELED:  { text: "Cancelada",   tone: "secondary" },
        };
        const appSt = appStatusMap[data.appointment.status] || { text: data.appointment.status, tone: "secondary" };
        $("#detAppStatusContainer").innerHTML = `<span class="badge text-bg-${appSt.tone}">${appSt.text}</span>`;
      } else {
        if (apptSec) apptSec.hidden = true;
      }

      if (data.description?.trim()) {
        $("#detDescription").textContent = data.description;
        $("#detDescription").classList.remove("text-muted", "fst-italic");
      } else {
        $("#detDescription").textContent = "Sin descripción proporcionada.";
        $("#detDescription").classList.add("text-muted", "fst-italic");
      }

      if (data.coordinator_comment?.trim()) {
        $("#detCoordComment").textContent = data.coordinator_comment;
        $("#detCoordComment").classList.remove("text-muted", "fst-italic");
      } else {
        $("#detCoordComment").textContent = "Sin comentario del coordinador.";
        $("#detCoordComment").classList.add("text-muted", "fst-italic");
      }

      $("#detCreatedAt").textContent = fmtDate(data.created_at);
      $("#detUpdatedAt").textContent = fmtDate(data.updated_at);

      if (detLoading) detLoading.hidden = true;
      if (detContent) detContent.hidden = false;

    } catch {
      if (detLoading) detLoading.innerHTML =
        `<div class="text-danger"><i class="bi bi-exclamation-triangle me-2"></i>Error al cargar detalles</div>`;
    }
  }

  // === EVENT LISTENERS ===

  // Paginación numérica (delegación)
  document.getElementById("pagerContainer")?.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-pg]");
    if (!btn) return;
    const pg = parseInt(btn.dataset.pg, 10);
    if (!isNaN(pg)) { page = pg; reload(); }
  });

  document.getElementById("btnPrev")?.addEventListener("click", () => {
    if (page > 0) { page--; reload(); }
  });
  document.getElementById("btnNext")?.addEventListener("click", () => {
    const totalPages = Math.ceil(totalItems / pageSize);
    if (page < totalPages - 1) { page++; reload(); }
  });

  // Selector de page-size
  document.getElementById("selPageSize")?.addEventListener("change", (e) => {
    pageSize = parseInt(e.target.value, 10) || 10;
    page = 0;
    reload();
  });

  // Ordenamiento por columna
  document.querySelectorAll("#tblReqHead th[data-sort]").forEach((th) => {
    th.style.cursor = "pointer";
    th.setAttribute("role", "button");
    th.addEventListener("click", () => {
      const col = th.dataset.sort;
      if (sortCol === col) {
        sortDir = sortDir === "asc" ? "desc" : "asc";
      } else {
        sortCol = col;
        sortDir = "asc";
      }
      page = 0;
      updateSortIndicators();
      reload();
    });
  });

  // Filtros
  document.getElementById("btnSearch")?.addEventListener("click", () => { page = 0; reload(); });
  $("#txtQ")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { page = 0; reload(); }
  });
  $("#fltPeriod")?.addEventListener("change", () => { page = 0; reload(); });

  // Click en tabla — ver detalles / cambiar estado
  document.addEventListener("click", async (e) => {
    const viewBtn  = e.target.closest("button[data-view]");
    const row      = e.target.closest("tr[data-req-id]");
    const changeBtn = e.target.closest("button[data-change]");

    if (changeBtn) {
      currentReqId = changeBtn.dataset.change;
      const rowEl  = changeBtn.closest("tr");
      $("#curReqInfo").innerHTML = rowEl
        ? `${rowEl.cells[0]?.innerText || ""} · ${rowEl.cells[2]?.innerHTML || ""}`
        : `#${currentReqId}`;
      $("#fNewStatus").value = "RESOLVED_SUCCESS";
      $("#fReason").value    = "";
      new bootstrap.Modal($("#mdlStatus")).show();
      return;
    }

    if (viewBtn) {
      await showRequestDetails(viewBtn.dataset.view);
      return;
    }

    if (row && !e.target.closest("button")) {
      await showRequestDetails(row.dataset.reqId);
    }
  });

  // Teclado para filas de tabla
  document.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const row = e.target.closest("tr[data-req-id]");
    if (row && !e.target.closest("button")) {
      e.preventDefault();
      await showRequestDetails(row.dataset.reqId);
    }
  });

  // Botón cambiar estado desde modal de detalles
  $("#btnChangeStatusFromDetails")?.addEventListener("click", () => {
    bootstrap.Modal.getInstance($("#mdlDetails"))?.hide();
    if (currentReqId) {
      $("#curReqInfo").innerHTML = `#${currentReqId}`;
      $("#fNewStatus").value    = "RESOLVED_SUCCESS";
      $("#fReason").value       = "";
      setTimeout(() => new bootstrap.Modal($("#mdlStatus")).show(), 200);
    }
  });

  // Aplicar nuevo estado
  const btnApply = $("#btnApplyStatus");
  if (btnApply) {
    btnApply.addEventListener("click", async () => {
      const newStatus = $("#fNewStatus").value;
      const reason    = $("#fReason")?.value.trim();
      if (!currentReqId) return;

      btnApply.disabled = true;
      const orig = btnApply.innerHTML;
      btnApply.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Aplicando...';

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
      } finally {
        btnApply.disabled = false;
        btnApply.innerHTML = orig;
      }
    });
  }

  // Tiempo real
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

  // === UTILIDADES ===
  function fmtDate(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("es-MX", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      });
    } catch { return iso; }
  }

  function escapeHtml(s) {
    return (s || "")
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }

  function debounce(fn, t) {
    let h;
    return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), t); };
  }

  // === ARRANQUE ===
  updateSortIndicators();
  initDates();
  loadProgramsAndCoords().then(() => reload());
})();
