// static/js/admin/reports.js
(() => {
  const $ = (s) => document.querySelector(s);
  const cfg = window.__adminReportsCfg || {};
  const xlsxUrl = cfg.xlsxUrl || "/api/agendatec/v1/admin/reports/requests.xlsx";
  const programsUrl = cfg.programsUrl || "/api/agendatec/v1/programs";
  const coordsUrl = cfg.coordsUrl || "/api/agendatec/v1/admin/users/coordinators";

  initDates();
  loadProgramsAndCoords();

  $("#btnXlsx")?.addEventListener("click", exportXlsx);

  function initDates() {
    const to = new Date();
    const from = new Date(Date.now() - 30 * 86400000);
    $("#repTo").value = to.toISOString().slice(0, 10);
    $("#repFrom").value = from.toISOString().slice(0, 10);
  }

  async function loadProgramsAndCoords() {
    try {
      const [rp, rc] = await Promise.all([
        fetch(programsUrl, { credentials: "include" }),
        fetch(coordsUrl, { credentials: "include" }),
      ]);
      const pj = await rp.json();
      const cj = await rc.json();
      const progs = Array.isArray(pj) ? pj : (pj.items || pj.programs || []);
      const coords = (cj.items || []);
      fillSelect($("#repProgram"), [{ id: "", name: "Todos" }, ...progs]);
      fillSelect($("#repCoord"), [{ id: "", name: "Todos" }, ...coords.map(c => ({ id: c.id, name: c.name }))]);
    } catch { /* silent */ }
  }

  function buildQs() {
    const q = new URLSearchParams();
    const from = $("#repFrom")?.value;
    const to = $("#repTo")?.value;
    const status = $("#repStatus")?.value;
    const prog = $("#repProgram")?.value;
    const coord = $("#repCoord")?.value;
    const text = $("#repQ")?.value?.trim();

    if (from) q.set("from", from);
    if (to) q.set("to", to);
    if (status) q.set("status", status);
    if (prog) q.set("program_id", prog);
    if (coord) q.set("coordinator_id", coord);
    if (text) q.set("q", text);
    return q.toString();
  }

  async function exportXlsx() {
    try {
      const r = await fetch(`${xlsxUrl}?${buildQs()}`, {
        method: "POST",
        credentials: "include",
      });
      if (!r.ok) throw new Error();
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `solicitudes_${new Date().toISOString().slice(0,19).replace(/[:T]/g,"-")}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showToast?.("Reporte generado", "success");
    } catch {
      showToast?.("No se pudo generar el reporte", "error");
    }
  }

  function fillSelect(sel, items) {
    if (!sel || !Array.isArray(items)) return;
    sel.innerHTML = items
      .map((x) => `<option value="${x.id}">${escapeHtml(x.name)}</option>`)
      .join("");
  }

  function escapeHtml(s) {
    return (s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
})();
