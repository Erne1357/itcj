// Prórrogas · Consulta (vista de secretaría): todas las solicitudes, con filtros, y su detalle e historial.
// API: /api/prorrogas/v2/solicitudes/todas y /solicitudes/{id}. Todo texto del servidor entra con textContent.
(function () {
  "use strict";

  const root = document.querySelector(".cst");
  if (!root) return;
  const API = root.dataset.api + "/solicitudes";
  const $ = (id) => document.getElementById(id);
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const PER_PAGE = 25;
  const ESTADOS = {
    pendiente: ["Pendiente", ""], aceptada: ["Aceptada", ""], rechazada: ["Rechazada", "est-pill-alert"],
    cancelada: ["Cancelada", "est-pill-grey"], cerrada_sin_plan: ["Cerrada sin plan", "est-pill-grey"],
  };
  const st = { estado: "", semestre: "", q: "", page: 1, total: 0 };
  let seq = 0;
  let timer = null;

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  async function get(path) {
    let r;
    try { r = await fetch(API + path, { credentials: "include" }); } catch (e) { return { ok: false, data: { message: "Sin conexión con el servidor." } }; }
    const data = await r.json().catch(() => ({}));
    if (r.status === 403 && !data.message) data.message = "No tienes permiso para esta acción.";
    return { ok: r.ok, data };
  }

  // Las fechas ISO se leen por partes: new Date("2026-03-01") sería UTC y mostraría el día anterior.
  function fmtDate(iso) {
    if (!iso) return "—";
    const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
    return `${d} ${MESES[m - 1]} ${y}`;
  }
  const fmtDateTime = (iso) => fmtDate(iso) + (iso && String(iso).length > 15 ? `, ${String(iso).slice(11, 16)}` : "");

  function pill(estado) {
    const [txt, cls] = ESTADOS[estado] || [estado, "est-pill-grey"];
    return el("span", "est-pill " + cls, txt);
  }

  function showError(msg) { const e = $("cstError"); e.textContent = msg || ""; e.hidden = !msg; }

  async function load() {
    const mine = ++seq;
    const qs = new URLSearchParams({ page: st.page, per_page: PER_PAGE });
    for (const k of ["estado", "semestre", "q"]) if (st[k]) qs.set(k, st[k]);
    const { ok, data } = await get("/todas?" + qs);
    if (mine !== seq) return;
    if (!ok) { showError(data.message || "No se pudo cargar la lista."); return; }
    showError("");
    st.total = data.total;
    fillSemestres(data.semestres);
    const rows = $("cstRows");
    rows.replaceChildren(...data.items.map(row));
    $("cstVacio").hidden = data.items.length > 0;
    const ini = data.items.length ? (data.page - 1) * data.per_page + 1 : 0;
    $("cstMostrando").textContent = `Mostrando ${ini}–${ini ? ini + data.items.length - 1 : 0} de ${data.total}`;
    const paginas = Math.max(1, Math.ceil(data.total / data.per_page));
    $("cstPagina").textContent = `${data.page} / ${paginas}`;
    $("cstPrev").disabled = data.page <= 1;
    $("cstNext").disabled = data.page >= paginas;
  }

  function fillSemestres(lista) {
    const sel = $("cstSemestre");
    if (sel.options.length - 1 === lista.length) return;
    sel.replaceChildren(new Option("Todos los semestres", ""), ...lista.map((s) => new Option(s, s)));
    sel.value = st.semestre;
  }

  function row(it) {
    const r = el("div", "est-row cst-row");
    r.tabIndex = 0;
    r.setAttribute("role", "button");
    const nombre = el("span", "est-name");
    nombre.append(el("span", null, it.nombre || "—"), el("small", "mono", it.folio));
    const estado = el("span");
    estado.append(pill(it.estado));
    r.append(el("span", "mono", it.control || "—"), nombre, el("span", null, it.carrera || "—"),
             el("span", null, it.semestre || "—"), estado);
    const abrir = () => openDetail(it);
    r.addEventListener("click", abrir);
    r.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); abrir(); } });
    return r;
  }

  async function openDetail(it) {
    const { ok, data } = await get("/" + it.id);
    if (!ok) { showError(data.message || "No se pudo abrir la solicitud."); return; }
    // request_out no trae al alumno: el encabezado sale de la fila.
    $("cstNombre").textContent = it.nombre || "";
    $("cstControl").textContent = it.control || "";
    $("cstCarrera").textContent = it.carrera || "";
    const dl = $("cstDatos");
    dl.replaceChildren();
    const datos = [["Folio", data.folio], ["Estado", (ESTADOS[data.estado] || [data.estado])[0]],
      ["Semestre", data.semestre], ["Plazos solicitados", data.plazos], ["Creada", fmtDateTime(data.creada)],
      ["Decidida", fmtDateTime(data.decidida)], ["Motivo", data.motivo], ["Comentario de la decisión", data.comentario]];
    for (const [k, v] of datos) if (v != null && v !== "") dl.append(el("dt", null, k), el("dd", null, String(v)));
    const docs = $("cstDocs");
    docs.replaceChildren(...data.documentos.map((d) => {
      const li = el("li");
      const a = el("a", "est-ver", `${d.label} (v${d.version})${d.firmado ? " · firmado" : ""}`);
      a.href = `${API}/${data.id}/documentos/${d.id}.pdf`;
      a.target = "_blank";
      a.rel = "noopener";
      li.append(a);
      return li;
    }));
    if (!data.documentos.length) docs.append(el("li", null, "Sin documentos."));
    const hist = $("cstHist");
    hist.replaceChildren(...data.historial.map((e) => {
      const li = el("li");
      li.append(el("b", null, e.tipo.replace(/_/g, " ")), el("time", null, " " + fmtDateTime(e.fecha)));
      if (e.datos && e.datos.motivo) li.append(el("div", null, "Motivo: " + e.datos.motivo));
      return li;
    }));
    if (!data.historial.length) hist.append(el("li", null, "Sin movimientos."));
    $("cstDialog").showModal();
  }

  function reset() { st.page = 1; load(); }
  $("cstEstado").addEventListener("change", (e) => { st.estado = e.target.value; reset(); });
  $("cstSemestre").addEventListener("change", (e) => { st.semestre = e.target.value; reset(); });
  $("cstQ").addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { st.q = e.target.value.trim(); reset(); }, 300);
  });
  $("cstPrev").addEventListener("click", () => { st.page -= 1; load(); });
  $("cstNext").addEventListener("click", () => { st.page += 1; load(); });
  $("cstClose").addEventListener("click", () => $("cstDialog").close());
  load();
})();
